"""
Führt die komplette Validierungs-Suite für alle drei Strategien aus:

  1. In-Sample / Out-of-Sample Split (70/30, chronologisch)
  2. Walk-Forward-Analyse (6 Monate Train / 2 Monate Test, rollierend)
  3. Parameter-Sensitivität (+/- 20-30 % um die Defaults)
  4. Monte-Carlo-Simulation der Trade-Reihenfolge (1000 Läufe)
  5. Kosten-Stresstest (1x / 2x / 3x Kommission + Slippage)
  6. Regime-Analyse (Trend vs. Range, Hoch- vs. Niedrig-Vol)
  7. Stichprobengröße + Wilson-Konfidenzintervall der Win-Rate
  8. Prop-Firm-Compliance (Daily-Loss 3 %, Max-DD 6 %)

ACHTUNG: Läuft auf SYNTHETISCHEN Daten (siehe engine.py-Docstring).
Zweck: lauffähige Demonstration der Testmethodik + Plausibilisierung der
Regel-Implementierung. KEINE echte Markt-Performance.
"""
from __future__ import annotations

import json
import time
from dataclasses import replace
from pathlib import Path

import numpy as np

from engine import (SimConfig, make_synthetic_bars, metrics, monte_carlo,
                    prop_compliance, regime_split, run, signals_s1,
                    signals_s2, signals_s3, slice_bars)

OUT = Path(__file__).parent / "results"
OUT.mkdir(exist_ok=True)

DAYS = 500  # ~2 Jahre Handelstage
TRAIN_DAYS, TEST_DAYS = 126, 42  # ~6 Monate / ~2 Monate

# ----------------------------------------------------------------------------
# Strategie-Definitionen: Signale, Default-Parameter, Kosten, Grids
# ----------------------------------------------------------------------------
STRATS = {
    "S1_Gold_TrendPullback": dict(
        sig=signals_s1,
        market="gold",
        params=dict(swing_htf=5, struct_shift=10, swing=5,
                    rsi_lo=45, rsi_hi=55, prox_atr=0.5, rr=2.5),
        cfg=SimConfig(point_value=10.0, tick_size=0.1, commission=2.5,
                      slippage_ticks=2, risk_pct=0.5, max_trades_day=6,
                      daily_loss_pct=3.0, max_dd_pct=6.0, max_bars_hold=12,
                      session=(8, 16)),
        # Sensitivität: zentrale Parameter +/- 20-30 %
        sens=dict(rr=[1.75, 2.0, 2.5, 3.0, 3.25],
                  prox_atr=[0.35, 0.4, 0.5, 0.6, 0.65],
                  rsi_lo=[40, 42, 45, 48, 50],
                  swing=[4, 5, 6, 7]),
        # Walk-Forward-Grid (klein halten -> kein Parameter-Surfing)
        wf_grid=[dict(rr=r, prox_atr=p) for r in (2.0, 2.5, 3.0)
                 for p in (0.4, 0.5, 0.6)],
    ),
    "S2_Gold_MeanReversion": dict(
        sig=signals_s2,
        market="gold_1m",
        params=dict(ema_len=200, rsi_len=14, rsi_os=30, rsi_ob=70,
                    pip_size=0.10, tp_pips=10.0, sl_pips=5.0),
        cfg=SimConfig(point_value=10.0, tick_size=0.1, commission=2.5,
                      slippage_ticks=3, risk_pct=0.3, max_trades_day=10,
                      daily_loss_pct=2.5, max_dd_pct=6.0, max_bars_hold=20,
                      session=(0, 24)),  # 1m-Interpretation: jeder Block = Session
        sens=dict(rsi_os=[24, 27, 30, 33, 36],
                  sl_pips=[3.5, 4.0, 5.0, 6.0, 6.5],
                  tp_pips=[7.0, 8.0, 10.0, 12.0, 13.0],
                  ema_len=[140, 170, 200, 230, 260]),
        wf_grid=[dict(rsi_os=os_, rsi_ob=100 - os_, sl_pips=s, tp_pips=2 * s)
                 for os_ in (25, 30, 35) for s in (4.0, 5.0, 6.0)],
    ),
    "S3_NQ_EmaVwapMomentum": dict(
        sig=signals_s3,
        market="nq",
        params=dict(ema_fast=9, ema_slow=21, slope_len=5, vol_mult=1.0,
                    atr_mult=1.25, rr=2.0),
        cfg=SimConfig(point_value=2.0, tick_size=0.25, commission=2.0,
                      slippage_ticks=4, risk_pct=0.5, max_trades_day=5,
                      daily_loss_pct=3.0, max_dd_pct=6.0, max_bars_hold=24,
                      session=(14, 21), profit_target_pct=4.0),
        sens=dict(atr_mult=[0.9, 1.0, 1.25, 1.5, 1.6],
                  rr=[1.4, 1.6, 2.0, 2.4, 2.6],
                  ema_fast=[7, 8, 9, 11, 12],
                  ema_slow=[15, 18, 21, 25, 27]),
        wf_grid=[dict(atr_mult=a, rr=r) for a in (1.0, 1.25, 1.5)
                 for r in (1.5, 2.0, 2.5)],
    ),
}


def make_market(market: str, seed: int):
    if market == "gold":
        return make_synthetic_bars(seed=seed, n_days=DAYS, s0=2400.0,
                                   base_vol=0.00045, trend_drift=0.00004)
    if market == "gold_1m":
        # S2 handelt lt. Recherche den 1m-Chart: Bars als 1-MINUTEN-Bars
        # interpretiert (Vol um sqrt(5) skaliert). Ein synthetischer "Tag"
        # (288 Bars) entspricht dann einer ~4.8h-Session; der Daily-Limiter
        # wirkt pro Session-Block.
        return make_synthetic_bars(seed=seed + 50, n_days=DAYS, s0=2400.0,
                                   base_vol=0.00045 / 5 ** 0.5,
                                   trend_drift=0.00004 / 5)
    return make_synthetic_bars(seed=seed + 100, n_days=DAYS, s0=19000.0,
                               base_vol=0.00075, trend_drift=0.00006)


def net_of(res):
    return sum(t.pnl for t in res["trades"])


def pf_of(res):
    pnl = np.array([t.pnl for t in res["trades"]]) if res["trades"] else np.array([0.0])
    gp = pnl[pnl > 0].sum(); gl = -pnl[pnl < 0].sum()
    return float(gp / gl) if gl > 0 else float("inf")


def validate(name: str, spec: dict, seed: int = 42) -> dict:
    t0 = time.time()
    bars = make_market(spec["market"], seed)
    sig, params, cfg = spec["sig"], spec["params"], spec["cfg"]
    report: dict = {"strategy": name, "synthetic_data": True, "days": DAYS}

    # ---------------- Basisläufe -------------------------------------------
    # (a) Produktionslauf: Limits AN (Daily-Limiter + Kill-Switch) — zeigt
    #     das reale Prop-Konto-Verhalten (Kill-Switch kann Sample abschneiden)
    # (b) Analyselauf: Limits AUS — volle Stichprobe für Statistik-Tests 1-7
    res = run(bars, sig, params, cfg)
    res_nolim = run(bars, sig, params, replace(cfg, limits_on=False))
    report["baseline_production"] = metrics(res)
    report["baseline"] = metrics(res_nolim)
    report["regimes"] = regime_split(bars, res_nolim)

    # ---------------- 1) IS/OOS 70/30 --------------------------------------
    cut = int(bars["n"] * 0.7)
    is_bars, oos_bars = slice_bars(bars, 0, cut), slice_bars(bars, cut, bars["n"])
    # "ehrlich": auf IS wird per Mini-Grid optimiert, OOS bleibt unberührt
    best, best_net = params, -1e18
    for g in spec["wf_grid"]:
        cand = {**params, **g}
        r = run(is_bars, sig, cand, replace(cfg, limits_on=False))
        if len(r["trades"]) >= 20 and net_of(r) > best_net:
            best_net, best = net_of(r), cand
    is_res = run(is_bars, sig, best, replace(cfg, limits_on=False))
    oos_res = run(oos_bars, sig, best, replace(cfg, limits_on=False))
    report["is_oos"] = dict(chosen_params={k: best[k] for k in best if k in
                                           set().union(*[set(g) for g in spec["wf_grid"]])},
                            in_sample=metrics(is_res),
                            out_of_sample=metrics(oos_res))

    # ---------------- 2) Walk-Forward (6m Train / 2m Test) ------------------
    walks = []
    bpd = 288
    start = 0
    while (start + TRAIN_DAYS + TEST_DAYS) * bpd <= bars["n"]:
        tr = slice_bars(bars, start * bpd, (start + TRAIN_DAYS) * bpd)
        te = slice_bars(bars, (start + TRAIN_DAYS) * bpd,
                        (start + TRAIN_DAYS + TEST_DAYS) * bpd)
        bw, bn = params, -1e18
        for g in spec["wf_grid"]:
            cand = {**params, **g}
            r = run(tr, sig, cand, replace(cfg, limits_on=False))
            if len(r["trades"]) >= 10 and net_of(r) > bn:
                bn, bw = net_of(r), cand
        te_res = run(te, sig, bw, replace(cfg, limits_on=False))
        m = metrics(te_res)
        walks.append(dict(train_net=bn if bn > -1e17 else None,
                          test_trades=m.get("trades", 0),
                          test_net=m.get("net_profit", 0.0),
                          test_pf=m.get("profit_factor"),
                          params={k: bw[k] for k in bw if k in set().union(*[set(g) for g in spec["wf_grid"]])}))
        start += TEST_DAYS
    pos_walks = sum(1 for w in walks if (w["test_net"] or 0) > 0)
    report["walk_forward"] = dict(walks=walks, n_walks=len(walks),
                                  positive_walks=pos_walks,
                                  oos_net_total=float(sum(w["test_net"] or 0 for w in walks)))

    # ---------------- 3) Parameter-Sensitivität ------------------------------
    sens_out = {}
    for pname, values in spec["sens"].items():
        row = []
        for v in values:
            cand = {**params, pname: v}
            if pname == "rsi_os":  # Symmetrie Overbought
                cand["rsi_ob"] = 100 - v
            if pname == "rsi_lo":
                cand["rsi_hi"] = 100 - v
            r = run(bars, sig, cand, replace(cfg, limits_on=False))
            row.append(dict(value=v, trades=len(r["trades"]),
                            net=net_of(r), pf=pf_of(r)))
        nets = [x["net"] for x in row]
        sens_out[pname] = dict(grid=row,
                               all_positive=bool(all(x > 0 for x in nets)),
                               sign_flips=int(sum(1 for a, b in zip(nets, nets[1:])
                                                  if (a > 0) != (b > 0))))
    report["sensitivity"] = sens_out

    # ---------------- 4) Monte Carlo (1000 Läufe) ---------------------------
    report["monte_carlo"] = monte_carlo(res_nolim["trades"], cfg.initial_capital,
                                        n_runs=1000)

    # ---------------- 5) Kosten-Stresstest ----------------------------------
    stress = []
    for mult in (1, 2, 3):
        c2 = replace(cfg, commission=cfg.commission * mult,
                     slippage_ticks=cfg.slippage_ticks * mult, limits_on=False)
        r = run(bars, sig, params, c2)
        stress.append(dict(cost_mult=mult, trades=len(r["trades"]),
                           net=net_of(r), pf=pf_of(r)))
    report["cost_stress"] = stress

    # ---------------- 7) Stichprobe / Wilson-CI ------------------------------
    b = report["baseline"]
    report["sample_size"] = dict(
        trades=b.get("trades", 0),
        sufficient=bool(b.get("trades", 0) >= 200),
        note=("OK: >= 200 Trades" if b.get("trades", 0) >= 200 else
              "WARNUNG: < 200 Trades — Kennzahlen statistisch nicht belastbar"),
        wilson_95=[b.get("wilson_lo"), b.get("wilson_hi")],
    )

    # ---------------- 8) Prop-Firm-Compliance --------------------------------
    report["prop_compliance"] = dict(
        with_limits=prop_compliance(res, cfg.daily_loss_pct, cfg.max_dd_pct),
        without_limits=prop_compliance(res_nolim, cfg.daily_loss_pct, cfg.max_dd_pct),
    )

    report["runtime_sec"] = round(time.time() - t0, 1)
    return report


def main():
    all_reports = {}
    for name, spec in STRATS.items():
        print(f"=== {name} ===", flush=True)
        rep = validate(name, spec)
        all_reports[name] = rep
        print(json.dumps(rep["baseline"], indent=2, default=str)[:600], flush=True)
    (OUT / "validation_results.json").write_text(
        json.dumps(all_reports, indent=2, default=str))
    print(f"\nErgebnisse -> {OUT / 'validation_results.json'}")


if __name__ == "__main__":
    main()
