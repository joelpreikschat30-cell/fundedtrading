"""
Backtest-/Validierungs-Engine für die drei Pine-v6-Strategien.

WICHTIG — TRANSPARENZ:
Diese Engine läuft auf SYNTHETISCHEN OHLCV-Daten (Regime-Switching-Prozess mit
Vol-Clustering und Intraday-Saisonalität). Sie demonstriert die VALIDIERUNGS-
METHODIK (IS/OOS, Walk-Forward, Sensitivität, Monte Carlo, Kosten-Stress,
Regime-Analyse, Wilson-CI, Prop-Compliance) vollständig und lauffähig.
Die absoluten Performance-Zahlen sind KEINE Aussage über echte Markt-
performance — dafür müssen die Pine-Skripte auf echten TradingView-Bars
(GC/MGC, NQ/MNQ) laufen. Siehe REPORT.md, Abschnitt "Grenzen".

Die Handelsregeln sind 1:1 aus den Pine-v6-Skripten übernommen:
Entry auf Bar-Close (bestätigte Bar), SL/TP intrabar via High/Low,
konservative Annahme "SL zuerst" wenn SL und TP in derselben Bar liegen,
Slippage auf jeder Marktorder/Stop-Order, Kommission pro Kontrakt & Seite,
Position-Sizing über % Equity, Daily-Loss-Limiter, Max-DD-Kill-Switch,
Max-Trades/Tag, Time-Stop, EOD-Flat.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

import numpy as np

MIN5_PER_DAY = 288  # 24h * 12


# ============================================================================
# Synthetische Daten (Regime-Switching, Vol-Clustering, Intraday-Saisonalität)
# ============================================================================
def make_synthetic_bars(seed: int, n_days: int, s0: float, base_vol: float,
                        trend_drift: float, vol_of_vol: float = 0.10,
                        mean_rev: float = 0.03) -> dict:
    """Erzeugt 5m-OHLCV-Bars für n_days Handelstage (24h, Mo-Fr angenommen).

    Regime-Markov-Kette: 0=Range, 1=Uptrend, 2=Downtrend (persistent).
    Vol-Regime: log-AR(1) (Clustering). Intraday-Vol-Saisonalität über
    Stunden-Multiplikator (London/NY aktiv, Asien ruhig).
    """
    rng = np.random.default_rng(seed)
    n = n_days * MIN5_PER_DAY

    # --- Regime-Kette (persistent, mittlere Dauer ~ 6 Tage) ---
    p_stay = 1.0 - 1.0 / (6 * MIN5_PER_DAY)
    regimes = np.zeros(n, dtype=np.int8)
    r = 0
    for i in range(n):
        if rng.random() > p_stay:
            r = rng.integers(0, 3)
        regimes[i] = r

    # --- Vol-Prozess (log-AR(1)) ---
    logv = np.zeros(n)
    phi = 0.999
    for i in range(1, n):
        logv[i] = phi * logv[i - 1] + vol_of_vol * math.sqrt(1 - phi * phi) * rng.standard_normal() * 8
    vol = base_vol * np.exp(logv - logv.var() / 2)

    # --- Intraday-Saisonalität (UTC-Stunden) ---
    hod = (np.arange(n) % MIN5_PER_DAY) // 12  # Stunde 0..23
    season = np.where((hod >= 7) & (hod < 16), 1.35,          # London/Overlap
              np.where((hod >= 16) & (hod < 21), 1.15,         # NY-Nachmittag
                       0.55))                                   # Asien/Nacht
    sigma = vol * season

    drift = np.where(regimes == 1, trend_drift,
             np.where(regimes == 2, -trend_drift, 0.0))

    # --- Log-Returns mit leichter Mean-Reversion in Range-Regimes ---
    z = rng.standard_normal(n)
    ret = np.empty(n)
    dev = 0.0
    for i in range(n):
        mr = -mean_rev * dev if regimes[i] == 0 else 0.0
        ret[i] = drift[i] + mr + sigma[i] * z[i]
        dev = 0.9 * dev + ret[i]

    close = s0 * np.exp(np.cumsum(ret))
    open_ = np.empty(n)
    open_[0] = s0
    # kleine Open-Gaps (Spread-/Mikrostruktur-Jitter) — nötig, damit
    # Engulfing-Muster (open < low[1]) überhaupt auftreten können
    gap = rng.standard_normal(n) * sigma * 0.25
    open_[1:] = close[:-1] * (1 + gap[1:])

    # Intrabar-Range proportional zur Bar-Vol
    wick = np.abs(rng.standard_normal((2, n))) * sigma * close * 0.55
    high = np.maximum(open_, close) + wick[0]
    low = np.minimum(open_, close) - wick[1]

    volu = (1000 * season * (1 + 3 * np.abs(ret) / (sigma + 1e-12))
            * np.exp(0.3 * rng.standard_normal(n)))

    day = np.arange(n) // MIN5_PER_DAY
    minute_of_day = (np.arange(n) % MIN5_PER_DAY) * 5
    return dict(open=open_, high=high, low=low, close=close, volume=volu,
                day=day, hod=hod.astype(int), mod=minute_of_day,
                regime=regimes, sigma=sigma, n=n)


# ============================================================================
# Indikatoren (identisch zur Pine-Semantik: Wilder-RSI/ATR, EMA, SMA)
# ============================================================================
def ema(x: np.ndarray, length: int) -> np.ndarray:
    a = 2.0 / (length + 1)
    out = np.empty_like(x)
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def rma(x: np.ndarray, length: int) -> np.ndarray:
    a = 1.0 / length
    out = np.empty_like(x)
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def rsi(close: np.ndarray, length: int) -> np.ndarray:
    d = np.diff(close, prepend=close[0])
    up = rma(np.maximum(d, 0), length)
    dn = rma(np.maximum(-d, 0), length)
    rs = up / np.maximum(dn, 1e-12)
    return 100 - 100 / (1 + rs)


def atr(h: np.ndarray, l: np.ndarray, c: np.ndarray, length: int) -> np.ndarray:
    pc = np.roll(c, 1); pc[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    return rma(tr, length)


def sma(x: np.ndarray, length: int) -> np.ndarray:
    c = np.cumsum(np.insert(x, 0, 0.0))
    out = np.full(len(x), np.nan)
    out[length - 1:] = (c[length:] - c[:-length]) / length
    out[:length - 1] = out[length - 1] if len(x) >= length else np.nan
    return out


def roll_max(x: np.ndarray, w: int) -> np.ndarray:
    from numpy.lib.stride_tricks import sliding_window_view
    out = np.empty(len(x))
    if len(x) < w:
        return np.maximum.accumulate(x)
    out[w - 1:] = sliding_window_view(x, w).max(axis=1)
    out[:w - 1] = np.maximum.accumulate(x[:w - 1])
    return out


def roll_min(x: np.ndarray, w: int) -> np.ndarray:
    return -roll_max(-x, w)


def session_vwap(bars: dict) -> np.ndarray:
    """Session-verankerter VWAP (Anker: Tageswechsel), wie ta.vwap."""
    hlc3 = (bars["high"] + bars["low"] + bars["close"]) / 3
    pv = hlc3 * bars["volume"]
    out = np.empty(bars["n"])
    cum_pv = cum_v = 0.0
    prev_day = -1
    for i in range(bars["n"]):
        if bars["day"][i] != prev_day:
            cum_pv = cum_v = 0.0
            prev_day = bars["day"][i]
        cum_pv += pv[i]; cum_v += bars["volume"][i]
        out[i] = cum_pv / max(cum_v, 1e-12)
    return out


# ============================================================================
# Konfiguration
# ============================================================================
@dataclass
class SimConfig:
    point_value: float = 10.0      # MGC: $10/Punkt (Gold), MNQ: $2/Punkt
    tick_size: float = 0.1
    commission: float = 2.5        # $/Kontrakt/Seite
    slippage_ticks: int = 2        # Ticks je Fill
    initial_capital: float = 50_000.0
    risk_pct: float = 0.5          # % Equity je Trade
    max_contracts: int = 10
    max_trades_day: int = 6
    daily_loss_pct: float = 3.0
    max_dd_pct: float = 6.0
    max_bars_hold: int = 12
    session: tuple = (8, 16)       # UTC-Stunden [von, bis)
    limits_on: bool = True         # Daily-Limiter + Kill-Switch aktiv
    profit_target_pct: float = 0.0 # 0 = aus


# ============================================================================
# Signal-Generatoren — 1:1-Abbild der Pine-Regeln
# ============================================================================
def signals_s1(bars: dict, p: dict) -> tuple:
    """Strategie 1: Gold 5m Trend-Pullback Engulfing."""
    o, h, l, c = bars["open"], bars["high"], bars["low"], bars["close"]
    n = bars["n"]
    # 15m-Aggregation (3 x 5m), nur ABGESCHLOSSENE 15m-Bars (Anti-Repaint)
    n15 = n // 3
    h15 = h[:n15 * 3].reshape(-1, 3).max(axis=1)
    l15 = l[:n15 * 3].reshape(-1, 3).min(axis=1)
    c15 = c[2::3][:n15]
    hh15 = roll_max(h15, p["swing_htf"]); hl15 = roll_max(l15, p["swing_htf"])
    lh15 = roll_min(h15, p["swing_htf"]); ll15 = roll_min(l15, p["swing_htf"])
    e50 = ema(c15, 50); e200 = ema(c15, 200)
    sh = p["struct_shift"]
    up15 = (hh15 > np.roll(hh15, sh)) & (hl15 > np.roll(hl15, sh)) & (e50 > e200)
    dn15 = (lh15 < np.roll(lh15, sh)) & (ll15 < np.roll(ll15, sh)) & (e50 < e200)
    up15[:sh + 200] = False; dn15[:sh + 200] = False
    # Mapping auf 5m: Wert der letzten abgeschlossenen 15m-Bar ([1]-Offset)
    idx15 = np.minimum(np.arange(n) // 3 - 1, n15 - 1)
    valid = idx15 >= 0
    t_up = np.zeros(n, bool); t_dn = np.zeros(n, bool)
    t_up[valid] = up15[idx15[valid]]; t_dn[valid] = dn15[idx15[valid]]

    # Swing-Level der VOR-Bars ([1]-Shift): das Pullback-Ziel, das die
    # aktuelle Kerze mit ihrem Low/High anlaufen muss
    swing_lo = np.roll(roll_min(l, p["swing"]), 1)
    swing_hi = np.roll(roll_max(h, p["swing"]), 1)
    r = rsi(c, 14); a = atr(h, l, c, 14); e50_5 = ema(c, 50)
    po, pc_, ph, pl = np.roll(o, 1), np.roll(c, 1), np.roll(h, 1), np.roll(l, 1)
    if p.get("engulf_mode", "body") == "range":
        # Recherche-Variante (strikt): Body umschließt die GESAMTE Vorbar-Range.
        # Auf gap-armen Futures extrem selten -> im Pine-Skript als Option.
        bull_eng = (c > o) & (pc_ < po) & (c > ph) & (o < pl)
        bear_eng = (c < o) & (pc_ > po) & (c < pl) & (o > ph)
    else:
        # Standard-Body-Engulfing: Body umschließt den Vorbar-BODY
        bull_eng = (c > o) & (pc_ < po) & (c >= po) & (o <= pc_)
        bear_eng = (c < o) & (pc_ > po) & (c <= po) & (o >= pc_)
    r1 = np.roll(r, 1)
    rsi_ok = (r1 > p["rsi_lo"]) & (r1 < p["rsi_hi"])

    # [R5] Pullback hat die Swing-Zone BERÜHRT: Low der Engulfing-Kerze
    # max. prox_atr*ATR über dem Swing-Low (Spiegel für Short)
    lg = (t_up & bull_eng & rsi_ok & (c > e50_5)
          & (l <= swing_lo + p["prox_atr"] * a))
    sh_ = (t_dn & bear_eng & rsi_ok & (c < e50_5)
           & (h >= swing_hi - p["prox_atr"] * a))
    # SL: unter/über Swing + 0.1*ATR-Puffer; TP: RR * SL-Distanz
    sl_long = np.maximum(c - (swing_lo - 0.1 * a), 0.05 * a)
    sl_short = np.maximum((swing_hi + 0.1 * a) - c, 0.05 * a)
    tp_long = p["rr"] * sl_long; tp_short = p["rr"] * sl_short
    return lg, sh_, sl_long, sl_short, tp_long, tp_short


def signals_s2(bars: dict, p: dict) -> tuple:
    """Strategie 2: Gold Mean-Reversion RSI + 200 EMA (fixe Pip-Exits)."""
    c = bars["close"]; h, l = bars["high"], bars["low"]
    e200 = ema(c, p["ema_len"]); r = rsi(c, p["rsi_len"])
    r1 = np.roll(r, 1)
    # Re-Cross-Modus (Anti-"falling-knife") wie im Pine-Default
    long_trig = (r1 <= p["rsi_os"]) & (r > p["rsi_os"])
    short_trig = (r1 >= p["rsi_ob"]) & (r < p["rsi_ob"])
    lg = long_trig & (c > e200)
    sh_ = short_trig & (c < e200)
    n = bars["n"]
    sl = np.full(n, p["sl_pips"] * p["pip_size"])
    tp = np.full(n, p["tp_pips"] * p["pip_size"])
    return lg, sh_, sl, sl, tp, tp


def signals_s3(bars: dict, p: dict) -> tuple:
    """Strategie 3: NQ 5m EMA(9/21)-Cross + VWAP-Slope + Volumen-Spike."""
    c, v = bars["close"], bars["volume"]
    h, l = bars["high"], bars["low"]
    ef = ema(c, p["ema_fast"]); es = ema(c, p["ema_slow"])
    ef1, es1 = np.roll(ef, 1), np.roll(es, 1)
    cross_up = (ef > es) & (ef1 <= es1)
    cross_dn = (ef < es) & (ef1 >= es1)
    vw = session_vwap(bars)
    slope = vw - np.roll(vw, p["slope_len"])
    # Session-Anker: Slope über Tagesgrenzen hinweg ungültig -> maskieren
    same_day = bars["day"] == np.roll(bars["day"], p["slope_len"])
    vol_ma = sma(v, 20)
    spike = v > p["vol_mult"] * vol_ma
    a = atr(h, l, c, 14)
    lg = cross_up & (slope > 0) & same_day & spike
    sh_ = cross_dn & (slope < 0) & same_day & spike
    sl = p["atr_mult"] * a
    tp = p["rr"] * sl
    return lg, sh_, sl, sl, tp, tp


# ============================================================================
# Trade-Simulator (bar-by-bar Positions-State, vektorisierte Signale)
# ============================================================================
@dataclass
class Trade:
    entry_i: int
    exit_i: int
    direction: int      # +1 long, -1 short
    qty: int
    entry: float
    exit: float
    pnl: float          # USD netto (inkl. Kommission + Slippage)
    risk_usd: float     # geplantes Risiko (SL-Distanz * qty * pv)
    reason: str


def simulate(bars: dict, sigs: tuple, cfg: SimConfig) -> dict:
    lg, sh, sl_l, sl_s, tp_l, tp_s = sigs
    o, h, l, c = bars["open"], bars["high"], bars["low"], bars["close"]
    day, hod = bars["day"], bars["hod"]
    n = bars["n"]
    slip = cfg.slippage_ticks * cfg.tick_size
    in_sess = (hod >= cfg.session[0]) & (hod < cfg.session[1])

    equity = cfg.initial_capital
    peak = equity
    day_start_eq = equity
    cur_day = -1
    trades_today = 0
    day_halted = False
    killed = False
    kill_bar = -1

    pos = 0          # +1/-1/0
    qty = 0
    entry_px = sl_px = tp_px = 0.0
    entry_i = -1
    risk_usd = 0.0

    trades: list[Trade] = []
    eq_curve = np.empty(n)
    daily_loss_hits = 0

    def close_pos(i: int, px: float, reason: str):
        nonlocal pos, equity, qty
        # Slippage nur auf Market-/Stop-Fills — Limit-Orders (TP) füllen
        # zum Limit-Preis oder besser (wie TradingView-Slippage-Semantik)
        px_f = px if reason == "TP" else px - slip * pos
        pnl = pos * (px_f - entry_px) * qty * cfg.point_value - cfg.commission * qty * 2
        equity += pnl
        trades.append(Trade(entry_i, i, pos, qty, entry_px, px_f, pnl, risk_usd, reason))
        pos = 0; qty = 0

    for i in range(n):
        # --- Tageswechsel ---
        if day[i] != cur_day:
            cur_day = day[i]
            day_start_eq = equity
            trades_today = 0
            day_halted = False

        # --- Offene Position managen (SL/TP intrabar, konservativ SL zuerst) ---
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
            if pos != 0 and i - entry_i >= cfg.max_bars_hold:
                close_pos(i, c[i], "TIME")
            if pos != 0 and not in_sess[i]:
                close_pos(i, c[i], "EOD")

        # --- Mark-to-Market Equity ---
        open_pnl = pos * (c[i] - entry_px) * qty * cfg.point_value if pos != 0 else 0.0
        mtm = equity + open_pnl
        eq_curve[i] = mtm
        peak = max(peak, mtm)

        if cfg.limits_on:
            # Kill-Switch (Trailing-DD vom Peak)
            if not killed and (peak - mtm) / peak * 100 >= cfg.max_dd_pct:
                killed = True
                kill_bar = i
                if pos != 0:
                    close_pos(i, c[i], "KILL")
            # Daily-Loss-Limiter
            if not day_halted and (day_start_eq - mtm) / day_start_eq * 100 >= cfg.daily_loss_pct:
                day_halted = True
                daily_loss_hits += 1
                if pos != 0:
                    close_pos(i, c[i], "DAYHALT")

        if killed:
            eq_curve[i] = equity
            continue

        # --- Entries (auf Bar-Close = bestätigte Bar) ---
        profit_hit = (cfg.profit_target_pct > 0
                      and (mtm - day_start_eq) / day_start_eq * 100 >= cfg.profit_target_pct)
        allow = (not day_halted and not profit_hit and in_sess[i]
                 and trades_today < cfg.max_trades_day and pos == 0)
        if allow and (lg[i] or sh[i]):
            direction = 1 if lg[i] else -1
            sld = sl_l[i] if direction > 0 else sl_s[i]
            tpd = tp_l[i] if direction > 0 else tp_s[i]
            if sld > 0 and np.isfinite(sld):
                risk_cash = equity * cfg.risk_pct / 100
                q = int(min(max(math.floor(risk_cash / (sld * cfg.point_value)), 0),
                            cfg.max_contracts))
                if q >= 1:
                    pos = direction
                    qty = q
                    entry_px = c[i] + slip * direction
                    sl_px = entry_px - direction * sld
                    tp_px = entry_px + direction * tpd
                    entry_i = i
                    risk_usd = sld * q * cfg.point_value
                    equity -= 0.0  # Kommission wird beim Exit für beide Seiten gebucht
                    trades_today += 1

    if pos != 0:
        close_pos(n - 1, c[n - 1], "END")
        eq_curve[n - 1] = equity

    return dict(trades=trades, equity=eq_curve, killed=killed, kill_bar=kill_bar,
                daily_loss_hits=daily_loss_hits, day=day,
                initial_capital=cfg.initial_capital)


# ============================================================================
# Kennzahlen
# ============================================================================
def wilson_ci(wins: int, n: int, z: float = 1.96) -> tuple:
    if n == 0:
        return (0.0, 0.0)
    p = wins / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def metrics(res: dict, bars_per_day: int = MIN5_PER_DAY) -> dict:
    trades = res["trades"]
    eq = res["equity"]
    n_tr = len(trades)
    if n_tr == 0:
        return dict(trades=0)
    pnl = np.array([t.pnl for t in trades])
    wins = int((pnl > 0).sum())
    gross_p = pnl[pnl > 0].sum()
    gross_l = -pnl[pnl < 0].sum()
    pf = gross_p / gross_l if gross_l > 0 else float("inf")
    # realisiertes RR: Gewinn/Verlust relativ zum geplanten Risiko
    rr = np.array([t.pnl / t.risk_usd for t in trades if t.risk_usd > 0])
    # Max Drawdown auf der Bar-Equity-Kurve
    peak = np.maximum.accumulate(eq)
    dd = (peak - eq) / peak
    max_dd = float(dd.max() * 100)
    # Tages-Returns für Sharpe/Sortino (252 Handelstage p.a.)
    day = res["day"]
    day_ends = np.where(np.diff(day, append=day[-1] + 1) != 0)[0]
    eq_d = eq[day_ends]
    ret_d = np.diff(eq_d) / eq_d[:-1]
    sharpe = float(ret_d.mean() / ret_d.std() * math.sqrt(252)) if ret_d.std() > 0 else 0.0
    downside = ret_d[ret_d < 0]
    sortino = (float(ret_d.mean() / downside.std() * math.sqrt(252))
               if len(downside) > 1 and downside.std() > 0 else float("inf"))
    lo, hi = wilson_ci(wins, n_tr)
    return dict(
        trades=n_tr,
        win_rate=100 * wins / n_tr,
        wilson_lo=100 * lo, wilson_hi=100 * hi,
        profit_factor=float(pf),
        avg_rr=float(rr.mean()) if len(rr) else 0.0,
        expectancy_usd=float(pnl.mean()),
        expectancy_r=float(rr.mean()) if len(rr) else 0.0,
        net_profit=float(pnl.sum()),
        net_pct=float(pnl.sum() / res["initial_capital"] * 100),
        max_dd_pct=max_dd,
        sharpe=sharpe, sortino=sortino,
        daily_loss_hits=res["daily_loss_hits"],
        killed=res["killed"],
    )


# ============================================================================
# Validierungs-Suite
# ============================================================================
def slice_bars(bars: dict, i0: int, i1: int) -> dict:
    out = {k: (v[i0:i1] if isinstance(v, np.ndarray) else v) for k, v in bars.items()}
    out["n"] = i1 - i0
    out["day"] = out["day"] - out["day"][0]
    return out


def run(bars: dict, sigfn, params: dict, cfg: SimConfig) -> dict:
    return simulate(bars, sigfn(bars, params), cfg)


def monte_carlo(trades: list, initial_capital: float, n_runs: int = 1000,
                dd_levels=(3.0, 6.0, 10.0), seed: int = 7) -> dict:
    """Trade-Reihenfolge-Resampling: Verteilung von MaxDD & Ruin-Wahrsch."""
    if len(trades) < 5:
        return dict(runs=0)
    rng = np.random.default_rng(seed)
    # P&L in % des Kontostands beim jeweiligen Trade -> auf Startkapital normiert
    pnl_pct = np.array([t.pnl for t in trades]) / initial_capital
    max_dds = np.empty(n_runs)
    finals = np.empty(n_runs)
    for k in range(n_runs):
        perm = rng.permutation(pnl_pct)
        eq = 1.0 + np.cumsum(perm)
        peak = np.maximum.accumulate(np.insert(eq, 0, 1.0))[1:]
        max_dds[k] = ((peak - eq) / peak).max() * 100
        finals[k] = eq[-1]
    return dict(
        runs=n_runs,
        dd_p50=float(np.percentile(max_dds, 50)),
        dd_p95=float(np.percentile(max_dds, 95)),
        dd_worst=float(max_dds.max()),
        prob_dd=[{ "level": lvl, "prob": float((max_dds >= lvl).mean() * 100)} for lvl in dd_levels],
        final_p05=float(np.percentile(finals, 5) * 100 - 100),
        final_p50=float(np.percentile(finals, 50) * 100 - 100),
        ruin_prob_6pct=float((max_dds >= 6.0).mean() * 100),
    )


def regime_split(bars: dict, res: dict) -> dict:
    """Performance getrennt nach Trend/Range und Hoch-/Niedrig-Vol am Entry."""
    trades = res["trades"]
    if not trades:
        return {}
    sig = bars["sigma"]
    med_sig = np.median(sig)
    reg = bars["regime"]
    out = {}
    for name, mask_fn in [
        ("trend", lambda t: reg[t.entry_i] != 0),
        ("range", lambda t: reg[t.entry_i] == 0),
        ("high_vol", lambda t: sig[t.entry_i] >= med_sig),
        ("low_vol", lambda t: sig[t.entry_i] < med_sig),
    ]:
        sel = [t for t in trades if mask_fn(t)]
        if not sel:
            out[name] = dict(trades=0)
            continue
        pnl = np.array([t.pnl for t in sel])
        gp = pnl[pnl > 0].sum(); gl = -pnl[pnl < 0].sum()
        out[name] = dict(
            trades=len(sel),
            win_rate=float(100 * (pnl > 0).mean()),
            profit_factor=float(gp / gl) if gl > 0 else float("inf"),
            net=float(pnl.sum()),
        )
    return out


def prop_compliance(res: dict, daily_limit: float, max_dd_limit: float) -> dict:
    """Prüft auf der Equity-Kurve, ob Prop-Grenzen je gerissen worden wären."""
    eq = res["equity"]; day = res["day"]
    n_days = int(day[-1]) + 1
    worst_daily = 0.0
    daily_breaches = 0
    for d in range(n_days):
        m = day == d
        if not m.any():
            continue
        e = eq[m]
        start = e[0]
        dd = (start - e.min()) / start * 100
        worst_daily = max(worst_daily, dd)
        if dd >= daily_limit:
            daily_breaches += 1
    peak = np.maximum.accumulate(eq)
    max_dd = float(((peak - eq) / peak).max() * 100)
    return dict(
        worst_daily_dd=float(worst_daily),
        daily_breaches=daily_breaches,
        max_trailing_dd=max_dd,
        max_dd_breached=bool(max_dd >= max_dd_limit),
        kill_switch_fired=res["killed"],
        limiter_interventions=res["daily_loss_hits"],
    )
