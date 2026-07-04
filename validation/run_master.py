"""
Validierung der MASTER-Strategie auf ECHTEN Dukascopy-Daten (12 Monate).

Testet die EINE Master-Strategie in ihren zwei Price-Action-Modi auf beiden
Instrumenten -> 4 Konfigurationen:
  (1) Gold  + Sweep     (ICT Asian Range Reversal)   -- Primär-Setup Gold
  (2) NAS100+ Breakout  (NY Opening Range Breakout)   -- Primär-Setup Index
  (3) Gold  + Breakout  (NY-ORB auf Gold, Cross-Test)
  (4) NAS100+ Sweep     (Asia-Sweep auf Index, Cross-Test)

Für jede Konfiguration die volle Suite: IS/OOS (70/30), Walk-Forward,
Parameter-Sensitivität, Monte Carlo (1000), Kosten-Stress (1x/2x/3x),
Regime-Analyse, Wilson-CI/Stichprobe, Prop-Compliance.

Daten: echte 1m-Bars aus dem Dukascopy-Tages-Cache (cache/), assembliert.
"""
from __future__ import annotations

import json
import time
from dataclasses import replace
from pathlib import Path

import numpy as np

from engine import metrics, monte_carlo, prop_compliance
from master_engine import (DATA, MasterCfg, load_1m, master_signals,
                          master_simulate, regime_split_real, resample)

CACHE = Path(__file__).parent / "cache"
OUT = Path(__file__).parent / "results"
OUT.mkdir(exist_ok=True)


def assemble_from_cache(sym: str) -> np.ndarray:
    """Baut den vollen 1m-Datensatz aus allen Tages-Cache-Dateien."""
    files = sorted(CACHE.glob(f"{sym}_*.npz"))
    parts = []
    for f in files:
        b = np.load(f)["bars"]
        if len(b):
            parts.append(b)
    arr = np.vstack(parts) if parts else np.empty((0, 6))
    arr = arr[np.argsort(arr[:, 0])]
    _, idx = np.unique(arr[:, 0], return_index=True)
    arr = arr[idx]
    np.savez_compressed(DATA / f"{sym}_1m.npz", bars=arr)
    return arr


# Instrument-Specs (prop-freundliche Micros)
GOLD = dict(point_value=10.0, tick_size=0.1, commission=2.5, slippage_ticks=2)   # MGC
NAS = dict(point_value=2.0, tick_size=0.25, commission=2.0, slippage_ticks=4)    # MNQ

# Sessions (Minute des Tages, UTC)
ASIA = dict(range_start=0, range_end=360, trade_start=360, trade_end=720)         # Range 00-06, Trade 06-12
NYORB = dict(range_start=810, range_end=825, trade_start=825, trade_end=1200)     # Range 13:30-13:45, Trade -20:00

CONFIGS = {
    "Gold_Sweep_Asia": dict(
        sym="XAUUSD", spec=GOLD, sess=ASIA,
        cfg=dict(mode="Sweep", target_mode="R-Multiple", rr=2.0, stop_mode="Structure",
                 stop_buf_atr=0.1, min_range_atr=0.25, max_range_atr=6.0,
                 risk_pct=0.5, max_trades_day=2, daily_loss_pct=3.0, max_dd_pct=6.0),
        sens=dict(rr=[1.5, 1.75, 2.0, 2.5, 2.75],
                  min_range_atr=[0.1, 0.25, 0.4, 0.6],
                  stop_buf_atr=[0.05, 0.1, 0.2, 0.3],
                  range_end=[300, 360, 420]),
        grid=[dict(rr=r, min_range_atr=m) for r in (1.5, 2.0, 2.5) for m in (0.1, 0.25, 0.4)],
    ),
    "NAS_Breakout_NYORB": dict(
        sym="USATECHIDXUSD", spec=NAS, sess=NYORB,
        cfg=dict(mode="Breakout", target_mode="R-Multiple", rr=2.0, stop_mode="Structure",
                 stop_buf_atr=0.1, min_range_atr=0.0, max_range_atr=8.0,
                 risk_pct=0.5, max_trades_day=2, daily_loss_pct=3.0, max_dd_pct=6.0),
        sens=dict(rr=[1.5, 1.75, 2.0, 2.5, 2.75],
                  max_range_atr=[4.0, 6.0, 8.0, 10.0],
                  stop_buf_atr=[0.0, 0.1, 0.2],
                  range_end=[815, 825, 840]),
        grid=[dict(rr=r, stop_buf_atr=b) for r in (1.5, 2.0, 2.5) for b in (0.0, 0.1, 0.2)],
    ),
    "Gold_Breakout_NYORB": dict(
        sym="XAUUSD", spec=GOLD, sess=NYORB,
        cfg=dict(mode="Breakout", target_mode="R-Multiple", rr=2.0, stop_mode="Structure",
                 stop_buf_atr=0.1, min_range_atr=0.0, max_range_atr=8.0,
                 risk_pct=0.5, max_trades_day=2, daily_loss_pct=3.0, max_dd_pct=6.0),
        sens=dict(rr=[1.5, 2.0, 2.5], max_range_atr=[4.0, 6.0, 8.0]),
        grid=[dict(rr=r, stop_buf_atr=b) for r in (1.5, 2.0, 2.5) for b in (0.0, 0.1, 0.2)],
    ),
    "NAS_Sweep_Asia": dict(
        sym="USATECHIDXUSD", spec=NAS, sess=ASIA,
        cfg=dict(mode="Sweep", target_mode="R-Multiple", rr=2.0, stop_mode="Structure",
                 stop_buf_atr=0.1, min_range_atr=0.25, max_range_atr=6.0,
                 risk_pct=0.5, max_trades_day=2, daily_loss_pct=3.0, max_dd_pct=6.0),
        sens=dict(rr=[1.5, 2.0, 2.5], min_range_atr=[0.1, 0.25, 0.4]),
        grid=[dict(rr=r, min_range_atr=m) for r in (1.5, 2.0, 2.5) for m in (0.1, 0.25, 0.4)],
    ),
}

_BARS_CACHE: dict = {}


def get_bars(sym: str, tf_min: int = 5) -> dict:
    key = (sym, tf_min)
    if key not in _BARS_CACHE:
        _BARS_CACHE[key] = resample(assemble_from_cache(sym), tf_min)
    return _BARS_CACHE[key]


def build_cfg(spec, sess, extra) -> MasterCfg:
    return MasterCfg(**spec, **sess, **extra)


def net_of(res):
    return float(sum(t.pnl for t in res["trades"]))


def pf_of(res):
    pnl = np.array([t.pnl for t in res["trades"]]) if res["trades"] else np.array([0.0])
    gp = pnl[pnl > 0].sum(); gl = -pnl[pnl < 0].sum()
    return float(gp / gl) if gl > 0 else float("inf")


def run_slice(bars_full: dict, i0: int, i1: int, cfg: MasterCfg) -> dict:
    sl = {k: (v[i0:i1] if isinstance(v, np.ndarray) else v) for k, v in bars_full.items()}
    sl["n"] = i1 - i0
    sl["day"] = sl["day"] - sl["day"][0]
    sig = master_signals(sl, cfg)
    return master_simulate(sl, sig, cfg)


def validate(name: str, spec_all: dict) -> dict:
    t0 = time.time()
    sym, spec, sess, base = spec_all["sym"], spec_all["spec"], spec_all["sess"], spec_all["cfg"]
    bars = get_bars(sym, 5)
    n = bars["n"]
    rep = {"config": name, "instrument": sym, "real_data": True,
           "bars_5m": n, "days": int(bars["day"][-1]) + 1}

    cfg = build_cfg(spec, sess, base)

    # Basisläufe: mit Limits (Prod) + ohne Limits (Analyse-Stichprobe)
    sig = master_signals(bars, cfg)
    res = master_simulate(bars, sig, cfg)
    res_nl = master_simulate(bars, sig, replace(cfg, limits_on=False))
    rep["baseline_production"] = metrics(res)
    rep["baseline"] = metrics(res_nl)
    rep["regimes"] = regime_split_real(bars, sig, res_nl)

    # 1) IS/OOS 70/30
    cut = int(n * 0.7)
    best, bn = base, -1e18
    for g in spec_all["grid"]:
        r = run_slice(bars, 0, cut, build_cfg(spec, sess, {**base, **g, "limits_on": False}))
        if len(r["trades"]) >= 15 and net_of(r) > bn:
            bn, best = net_of(r), {**base, **g}
    is_res = run_slice(bars, 0, cut, build_cfg(spec, sess, {**best, "limits_on": False}))
    oos_res = run_slice(bars, cut, n, build_cfg(spec, sess, {**best, "limits_on": False}))
    gridkeys = set().union(*[set(g) for g in spec_all["grid"]])
    rep["is_oos"] = dict(chosen={k: best[k] for k in gridkeys if k in best},
                         in_sample=metrics(is_res), out_of_sample=metrics(oos_res))

    # 2) Walk-Forward: ~6M Train / ~2M Test (in Bar-Indizes)
    bars_per_day = n / rep["days"]
    train_len = int(126 * bars_per_day); test_len = int(42 * bars_per_day)
    walks = []; start = 0
    while start + train_len + test_len <= n:
        bw, bwn = base, -1e18
        for g in spec_all["grid"]:
            r = run_slice(bars, start, start + train_len,
                          build_cfg(spec, sess, {**base, **g, "limits_on": False}))
            if len(r["trades"]) >= 8 and net_of(r) > bwn:
                bwn, bw = net_of(r), {**base, **g}
        te = run_slice(bars, start + train_len, start + train_len + test_len,
                       build_cfg(spec, sess, {**bw, "limits_on": False}))
        m = metrics(te)
        walks.append(dict(test_trades=m.get("trades", 0), test_net=m.get("net_profit", 0.0),
                          test_pf=m.get("profit_factor"),
                          params={k: bw[k] for k in gridkeys if k in bw}))
        start += test_len
    rep["walk_forward"] = dict(n_walks=len(walks),
                               positive_walks=sum(1 for w in walks if (w["test_net"] or 0) > 0),
                               oos_net_total=float(sum(w["test_net"] or 0 for w in walks)),
                               walks=walks)

    # 3) Parameter-Sensitivität
    sens = {}
    for pname, values in spec_all["sens"].items():
        row = []
        for v in values:
            if pname in ("range_end",):   # Session-Parameter
                cc = build_cfg(spec, {**sess, pname: v}, {**base, "limits_on": False})
            else:
                cc = build_cfg(spec, sess, {**base, pname: v, "limits_on": False})
            sg = master_signals(bars, cc); r = master_simulate(bars, sg, cc)
            row.append(dict(value=v, trades=len(r["trades"]), net=net_of(r), pf=pf_of(r)))
        nets = [x["net"] for x in row]
        sens[pname] = dict(grid=row, all_positive=bool(all(x > 0 for x in nets)),
                           sign_flips=int(sum(1 for a, b in zip(nets, nets[1:]) if (a > 0) != (b > 0))))
    rep["sensitivity"] = sens

    # 4) Monte Carlo
    rep["monte_carlo"] = monte_carlo(res_nl["trades"], cfg.initial_capital, n_runs=1000)

    # 5) Kosten-Stress
    stress = []
    for mult in (1, 2, 3):
        cc = build_cfg(spec, sess, {**base, "limits_on": False})
        cc = replace(cc, commission=cc.commission * mult, slippage_ticks=cc.slippage_ticks * mult)
        sg = master_signals(bars, cc); r = master_simulate(bars, sg, cc)
        stress.append(dict(cost_mult=mult, trades=len(r["trades"]), net=net_of(r), pf=pf_of(r)))
    rep["cost_stress"] = stress

    # 7) Stichprobe / Wilson
    b = rep["baseline"]
    rep["sample_size"] = dict(trades=b.get("trades", 0), sufficient=bool(b.get("trades", 0) >= 200),
                              wilson_95=[b.get("wilson_lo"), b.get("wilson_hi")],
                              note=("OK >=200" if b.get("trades", 0) >= 200 else "WARNUNG <200 Trades"))

    # 8) Prop-Compliance
    rep["prop_compliance"] = dict(
        with_limits=prop_compliance(res, cfg.daily_loss_pct, cfg.max_dd_pct),
        without_limits=prop_compliance(res_nl, cfg.daily_loss_pct, cfg.max_dd_pct))

    rep["runtime_sec"] = round(time.time() - t0, 1)
    return rep


def main():
    reports = {}
    for name, spec_all in CONFIGS.items():
        print(f"=== {name} ===", flush=True)
        r = validate(name, spec_all)
        reports[name] = r
        b = r["baseline"]
        print(f"  bars={r['bars_5m']} days={r['days']} tr={b.get('trades')} "
              f"wr={b.get('win_rate',0):.1f}% pf={b.get('profit_factor',0):.2f} "
              f"exp={b.get('expectancy_r',0):.2f}R netpct={b.get('net_pct',0):.1f}%", flush=True)
    (OUT / "master_results.json").write_text(json.dumps(reports, indent=2, default=str))
    print(f"\n-> {OUT / 'master_results.json'}")


if __name__ == "__main__":
    main()
