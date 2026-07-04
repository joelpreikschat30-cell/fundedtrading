"""
Echtdaten-Engine für die Master-Strategie "Session Range: Breakout & Sweep".

Lädt echte Dukascopy-1m-Bars (aus dukascopy.py), resampelt auf den Handels-TF,
erzeugt die Price-Action-Signale (Range-Breakout + Sweep-Reversal) exakt nach
der Pine-Logik in strategies/master_session_range.pine und simuliert Trades mit
Prop-Firm-Risikomanagement.

Analytik (Metriken, Monte Carlo, Wilson-CI, Prop-Compliance) wird aus engine.py
wiederverwendet — dieselben Formeln, jetzt auf ECHTEN Bars.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

from engine import (Trade, atr as atr_wilder, metrics, monte_carlo,
                    prop_compliance, wilson_ci)

DATA = Path(__file__).parent / "data"


# ============================================================================
# Echtdaten laden & resampeln
# ============================================================================
def load_1m(sym: str) -> np.ndarray:
    """Lädt [epoch_min, o,h,l,c,v] und sortiert/dedupliziert nach Minute."""
    arr = np.load(DATA / f"{sym}_1m.npz")["bars"]
    arr = arr[np.argsort(arr[:, 0])]
    _, idx = np.unique(arr[:, 0], return_index=True)
    return arr[idx]


def resample(bars1m: np.ndarray, tf_min: int) -> dict:
    """1m -> tf_min-Bars. Liefert dict mit o,h,l,c,v,epoch_min,day,mod,hod,n."""
    em = bars1m[:, 0].astype(np.int64)
    bucket = (em // tf_min) * tf_min
    uniq, idx = np.unique(bucket, return_index=True)
    idx = list(idx) + [len(em)]
    o = np.empty(len(uniq)); h = np.empty(len(uniq)); l = np.empty(len(uniq))
    c = np.empty(len(uniq)); v = np.empty(len(uniq))
    for k in range(len(uniq)):
        s, e = idx[k], idx[k + 1]
        seg = bars1m[s:e]
        o[k] = seg[0, 1]; h[k] = seg[:, 2].max(); l[k] = seg[:, 3].min()
        c[k] = seg[-1, 4]; v[k] = seg[:, 5].sum()
    epoch_sec = uniq * 60
    day = (uniq // (60 * 24)).astype(np.int64)
    day = day - day[0]
    mod = (uniq % (60 * 24)).astype(np.int64)      # Minute des Tages (UTC)
    hod = (mod // 60).astype(np.int64)
    return dict(open=o, high=h, low=l, close=c, volume=v, epoch_min=uniq,
                day=day, mod=mod, hod=hod, n=len(uniq))


def daily_atr(bars: dict, length: int = 14) -> np.ndarray:
    """ATR auf Tagesbasis, je 5m-Bar der Wert des VORTAGES (kein Lookahead).
    Dient als korrekt skalierter Maßstab für die Session-Range-Größe."""
    day = bars["day"]
    uniq = np.unique(day)
    do = np.empty(len(uniq)); dh = np.empty(len(uniq)); dl = np.empty(len(uniq)); dc = np.empty(len(uniq))
    for k, d in enumerate(uniq):
        m = day == d
        do[k] = bars["open"][m][0]; dh[k] = bars["high"][m].max()
        dl[k] = bars["low"][m].min(); dc[k] = bars["close"][m][-1]
    datr = atr_wilder(dh, dl, dc, length)
    prev = np.roll(datr, 1); prev[0] = datr[0]        # Vortagswert
    mp = {d: prev[k] for k, d in enumerate(uniq)}
    return np.array([mp[d] for d in day])


def session_vwap(bars: dict) -> np.ndarray:
    """Täglich (UTC-Tag) verankerter VWAP wie ta.vwap."""
    hlc3 = (bars["high"] + bars["low"] + bars["close"]) / 3
    pv = hlc3 * bars["volume"]
    out = np.empty(bars["n"]); cum_pv = cum_v = 0.0; prev = -1
    for i in range(bars["n"]):
        if bars["day"][i] != prev:
            cum_pv = cum_v = 0.0; prev = bars["day"][i]
        cum_pv += pv[i]; cum_v += bars["volume"][i]
        out[i] = cum_pv / max(cum_v, 1e-12)
    return out


# ============================================================================
# Konfiguration
# ============================================================================
@dataclass
class MasterCfg:
    # Instrument
    point_value: float = 10.0
    tick_size: float = 0.1
    commission: float = 2.5
    slippage_ticks: int = 2
    initial_capital: float = 50_000.0
    tf_min: int = 5
    # Sessions (Minute des Tages, UTC)
    range_start: int = 0          # 00:00
    range_end: int = 360          # 06:00
    trade_start: int = 360        # 06:00
    trade_end: int = 720          # 12:00
    # Signal
    mode: str = "Sweep"           # Breakout | Sweep | Both
    use_vwap: bool = True
    # Range-Größenfilter in Einheiten des TAGES-ATR (korrekt skaliert):
    min_range_atr: float = 0.15   # Asia-6h ~0.3-0.6 Tages-ATR; ORB-15m ~0.03-0.15
    max_range_atr: float = 1.2
    one_setup_dir: bool = True
    # Exit
    stop_mode: str = "Structure"  # Structure | ATR
    atr_len: int = 14
    atr_stop_k: float = 1.25
    stop_buf_atr: float = 0.1
    target_mode: str = "R-Multiple"  # R-Multiple | OppositeRange
    rr: float = 2.0
    # Risiko / Prop
    risk_pct: float = 0.5
    max_contracts: int = 20
    max_trades_day: int = 3
    daily_loss_pct: float = 3.0
    max_dd_pct: float = 6.0
    limits_on: bool = True


# ============================================================================
# Signal-Erzeugung — 1:1 zur Pine-Logik
# ============================================================================
def master_signals(bars: dict, cfg: MasterCfg) -> dict:
    n = bars["n"]
    o, h, l, c = bars["open"], bars["high"], bars["low"], bars["close"]
    mod, day = bars["mod"], bars["day"]
    a = atr_wilder(h, l, c, cfg.atr_len)       # 5m-ATR (für Stops)
    datr = daily_atr(bars, cfg.atr_len)        # Tages-ATR (für Range-Größenfilter)
    vw = session_vwap(bars)

    in_range = (mod >= cfg.range_start) & (mod < cfg.range_end)
    in_trade = (mod >= cfg.trade_start) & (mod < cfg.trade_end)

    # Pro Tag Range-Hoch/-Tief über das Range-Fenster
    rHigh = np.full(n, np.nan); rLow = np.full(n, np.nan)
    cur_hi = cur_lo = np.nan
    cur_day = -1
    for i in range(n):
        if day[i] != cur_day:
            cur_day = day[i]; cur_hi = np.nan; cur_lo = np.nan
        if in_range[i]:
            cur_hi = h[i] if np.isnan(cur_hi) else max(cur_hi, h[i])
            cur_lo = l[i] if np.isnan(cur_lo) else min(cur_lo, l[i])
        rHigh[i] = cur_hi; rLow[i] = cur_lo

    range_size = rHigh - rLow
    ready = in_trade & ~np.isnan(range_size)
    range_ok = ready & (range_size >= cfg.min_range_atr * datr) & \
               (range_size <= cfg.max_range_atr * datr)

    do_break = cfg.mode in ("Breakout", "Both")
    do_sweep = cfg.mode in ("Sweep", "Both")
    pc = np.roll(c, 1)

    break_long = do_break & (c > rHigh) & (pc <= rHigh)
    break_short = do_break & (c < rLow) & (pc >= rLow)
    sweep_long = do_sweep & (l < rLow) & (c > rLow)
    sweep_short = do_sweep & (h > rHigh) & (c < rHigh)

    # VWAP-Konfluenz — RICHTUNG hängt vom Modus ab:
    #  Breakout (Momentum): long nur wenn close > VWAP (Trend-Rückhalt).
    #  Sweep (Reversal):    long nur wenn close < VWAP (Ziel = Rückkehr nach oben zum Mittelwert).
    if cfg.use_vwap:
        break_long = break_long & (c > vw)
        break_short = break_short & (c < vw)
        sweep_long = sweep_long & (c < vw)
        sweep_short = sweep_short & (c > vw)

    go_long = range_ok & (break_long | sweep_long)
    go_short = range_ok & (break_short | sweep_short)

    # Stop-Distanzen
    if cfg.stop_mode == "ATR":
        sl_long = cfg.atr_stop_k * a
        sl_short = cfg.atr_stop_k * a
    else:
        # Breakout: Gegenseite der Range; Sweep: jenseits des Dochts
        sl_long = np.where(break_long, c - (rLow - cfg.stop_buf_atr * a),
                           c - (l - cfg.stop_buf_atr * a))
        sl_short = np.where(break_short, (rHigh + cfg.stop_buf_atr * a) - c,
                            (h + cfg.stop_buf_atr * a) - c)
    sl_long = np.maximum(sl_long, 0.0)
    sl_short = np.maximum(sl_short, 0.0)

    if cfg.target_mode == "OppositeRange":
        tp_long = np.maximum(rHigh - c, sl_long)      # mind. 1R
        tp_short = np.maximum(c - rLow, sl_short)
    else:
        tp_long = cfg.rr * sl_long
        tp_short = cfg.rr * sl_short

    return dict(go_long=go_long, go_short=go_short, in_trade=in_trade,
                sl_long=sl_long, sl_short=sl_short, tp_long=tp_long,
                tp_short=tp_short, atr=a, rHigh=rHigh, rLow=rLow, vwap=vw)


# ============================================================================
# Simulator — Session-Range + ein Setup je Richtung/Tag
# ============================================================================
def master_simulate(bars: dict, sig: dict, cfg: MasterCfg) -> dict:
    o, h, l, c = bars["open"], bars["high"], bars["low"], bars["close"]
    day = bars["day"]
    n = bars["n"]
    slip = cfg.slippage_ticks * cfg.tick_size
    in_trade = sig["in_trade"]

    equity = cfg.initial_capital
    peak = equity
    day_start_eq = equity
    cur_day = -1
    trades_today = 0
    took_long = took_short = False
    day_halted = killed = False

    pos = 0; qty = 0
    entry_px = sl_px = tp_px = 0.0
    entry_i = -1; risk_usd = 0.0
    trades: list[Trade] = []
    eq_curve = np.empty(n)
    daily_loss_hits = 0

    def close_pos(i, px, reason):
        nonlocal pos, equity, qty
        px_f = px if reason == "TP" else px - slip * pos
        pnl = pos * (px_f - entry_px) * qty * cfg.point_value - cfg.commission * qty * 2
        equity += pnl
        trades.append(Trade(entry_i, i, pos, qty, entry_px, px_f, pnl, risk_usd, reason))
        pos = 0; qty = 0

    for i in range(n):
        if day[i] != cur_day:
            cur_day = day[i]; day_start_eq = equity
            trades_today = 0; day_halted = False
            took_long = took_short = False

        # Position managen (SL-first konservativ)
        if pos != 0:
            if pos > 0:
                if l[i] <= sl_px:
                    close_pos(i, sl_px, "SL")
                elif h[i] >= tp_px:
                    close_pos(i, tp_px, "TP")
            else:
                if h[i] >= sl_px:
                    close_pos(i, sl_px, "SL")
                elif l[i] <= tp_px:
                    close_pos(i, tp_px, "TP")
            # EOD-Flat außerhalb Handelsfenster
            if pos != 0 and not in_trade[i]:
                close_pos(i, c[i], "EOD")

        open_pnl = pos * (c[i] - entry_px) * qty * cfg.point_value if pos else 0.0
        mtm = equity + open_pnl
        eq_curve[i] = mtm
        peak = max(peak, mtm)

        if cfg.limits_on:
            if not killed and (peak - mtm) / peak * 100 >= cfg.max_dd_pct:
                killed = True
                if pos != 0:
                    close_pos(i, c[i], "KILL")
            if not day_halted and (day_start_eq - mtm) / day_start_eq * 100 >= cfg.daily_loss_pct:
                day_halted = True; daily_loss_hits += 1
                if pos != 0:
                    close_pos(i, c[i], "DAYHALT")
        if killed:
            eq_curve[i] = equity
            continue

        allow = (not day_halted and in_trade[i] and pos == 0
                 and trades_today < cfg.max_trades_day)
        if allow:
            long_ok = sig["go_long"][i] and (not cfg.one_setup_dir or not took_long)
            short_ok = sig["go_short"][i] and (not cfg.one_setup_dir or not took_short)
            direction = 1 if long_ok else (-1 if short_ok else 0)
            if direction != 0:
                sld = sig["sl_long"][i] if direction > 0 else sig["sl_short"][i]
                tpd = sig["tp_long"][i] if direction > 0 else sig["tp_short"][i]
                if sld > 0 and np.isfinite(sld) and np.isfinite(tpd) and tpd > 0:
                    risk_cash = equity * cfg.risk_pct / 100
                    q = int(min(max(math.floor(risk_cash / (sld * cfg.point_value)), 0),
                                cfg.max_contracts))
                    if q >= 1:
                        pos = direction; qty = q
                        entry_px = c[i] + slip * direction
                        sl_px = entry_px - direction * sld
                        tp_px = entry_px + direction * tpd
                        entry_i = i
                        risk_usd = sld * q * cfg.point_value
                        trades_today += 1
                        if direction > 0:
                            took_long = True
                        else:
                            took_short = True

    if pos != 0:
        close_pos(n - 1, c[n - 1], "END")
        eq_curve[n - 1] = equity
    return dict(trades=trades, equity=eq_curve, killed=killed,
                daily_loss_hits=daily_loss_hits, day=day,
                initial_capital=cfg.initial_capital)


# ============================================================================
# Regime-Analyse für ECHTE Daten (berechenbare Proxys statt Label)
# ============================================================================
def regime_split_real(bars: dict, sig: dict, res: dict) -> dict:
    """Trend/Range über Tages-|Move|/ATR, Vol über ATR-Median am Entry."""
    trades = res["trades"]
    if not trades:
        return {}
    a = sig["atr"]
    med_a = np.nanmedian(a)
    # Tages-Bewegung: |close_letzte_bar - open_erste_bar| des Tages / ATR
    day = bars["day"]
    o, c = bars["open"], bars["close"]
    day_move = {}
    for d in np.unique(day):
        m = day == d
        idxs = np.where(m)[0]
        rng = c[idxs[-1]] - o[idxs[0]]
        atr_d = np.nanmedian(a[idxs])
        day_move[d] = abs(rng) / atr_d if atr_d > 0 else 0.0
    out = {}
    for name, fn in [
        ("trend_day", lambda t: day_move.get(day[t.entry_i], 0) >= 3.0),
        ("range_day", lambda t: day_move.get(day[t.entry_i], 0) < 3.0),
        ("high_vol", lambda t: a[t.entry_i] >= med_a),
        ("low_vol", lambda t: a[t.entry_i] < med_a),
    ]:
        sel = [t for t in trades if fn(t)]
        if not sel:
            out[name] = dict(trades=0); continue
        pnl = np.array([t.pnl for t in sel])
        gp = pnl[pnl > 0].sum(); gl = -pnl[pnl < 0].sum()
        out[name] = dict(trades=len(sel), win_rate=float(100 * (pnl > 0).mean()),
                         profit_factor=float(gp / gl) if gl > 0 else float("inf"),
                         net=float(pnl.sum()))
    return out
