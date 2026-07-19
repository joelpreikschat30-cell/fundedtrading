"""
Reversal-Timing-Analyse — WANN kommen die besten Sweep-Reversals?

Beantwortet die Frage, die für die Kalibrierung des Snipe-Points-Indikators
zählt und für die es (speziell MGC/SIL) keine öffentliche Studie gibt:
zu welcher UHRZEIT / in welcher SESSION / an welchem REFERENZ-LEVEL entstehen
auf echten 1m-Daten am häufigsten UND am hochwertigsten Liquidity-Sweep-
Reversals.

Die Erkennung spiegelt die Indikator-Logik (indicators/snipe_points.pine),
aber bewusst OHNE die späten MSS-/Score-/RR-Gates — hier wird gemessen, was
ein früher Sweep-Reclaim-Entry (Wick-Stop) danach real an RR liefert. Genau
das ist die Datengrundlage, um pro Symbol zu entscheiden:
  • welche Sessions/Stunden man aktiv lässt,
  • welche Referenz-Level (Asia / London / Vortag / Rolling-24h) tragen,
  • wie eng die Penetration und wie hoch das RR-Gate realistisch sein darf.

Datenquelle: dieselben Dukascopy-1m-Bars wie der Rest der Pipeline
(data/{sym}_1m.npz, sonst aus cache/{sym}_*.npz assembliert).

Nutzung:
    python3 reversal_timing.py XAUUSD
    python3 reversal_timing.py XAGUSD --pen 0.05 --lookfwd 120 --target 5
    python3 reversal_timing.py USATECHIDXUSD --levels PD,ROLL --cooldown 30

Vorher Daten laden (falls noch nicht vorhanden):
    python3 dukascopy.py XAGUSD 2025-07-01 2026-06-30
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

DATA = Path(__file__).parent / "data"
CACHE = Path(__file__).parent / "cache"
OUT = Path(__file__).parent / "results"
OUT.mkdir(exist_ok=True)

# Session-Fenster in Minuten des Tages (UTC) — deckungsgleich mit dem Indikator.
SESSIONS = [
    ("Asia",      0,   360),   # 00:00-06:00
    ("London-KZ", 420, 600),   # 07:00-10:00
    ("NY-Pre",    720, 810),   # 12:00-13:30
    ("NY-IB",     810, 930),   # 13:30-15:30
    ("PM/LC",     1020, 1200), # 17:00-20:00
]


def load_1m(sym: str) -> np.ndarray:
    """[epoch_min, o,h,l,c,v], sortiert/dedupliziert. Assembliert bei Bedarf."""
    f = DATA / f"{sym}_1m.npz"
    if f.exists():
        arr = np.load(f)["bars"]
    else:
        files = sorted(CACHE.glob(f"{sym}_*.npz"))
        if not files:
            raise SystemExit(
                f"Keine Daten für {sym}. Erst laden:\n"
                f"  python3 dukascopy.py {sym} 2025-07-01 2026-06-30")
        parts = [np.load(x)["bars"] for x in files]
        parts = [p for p in parts if len(p)]
        arr = np.vstack(parts) if parts else np.empty((0, 6))
        DATA.mkdir(exist_ok=True)
        np.savez_compressed(f, bars=arr)
    arr = arr[np.argsort(arr[:, 0])]
    _, idx = np.unique(arr[:, 0], return_index=True)
    return arr[idx]


def rolling_extreme(x: np.ndarray, n: int, want_max: bool) -> np.ndarray:
    """Rollierendes Max/Min der N Bars VOR dem aktuellen Bar (Bar selbst aus)."""
    out = np.full(len(x), np.nan)
    if len(x) <= n:
        return out
    try:
        from numpy.lib.stride_tricks import sliding_window_view
        sw = sliding_window_view(x, n)          # sw[j] = x[j:j+n]
        agg = sw.max(axis=1) if want_max else sw.min(axis=1)
        out[n:] = agg[: len(x) - n]             # out[i] = extreme von x[i-n:i]
    except Exception:
        for i in range(n, len(x)):
            seg = x[i - n:i]
            out[i] = seg.max() if want_max else seg.min()
    return out


def build_levels(o, h, l, c, em, level_names):
    """Referenz-Level je Bar. Gibt dict[name] -> (levelArr, isLow)."""
    mod = (em % 1440).astype(np.int64)
    day = (em // 1440).astype(np.int64)
    levels: dict[str, tuple[np.ndarray, bool]] = {}

    # Vortages-Hoch/-Tief
    if "PD" in level_names:
        udays = np.unique(day)
        dh = {}; dl = {}
        for d in udays:
            m = day == d
            dh[d] = h[m].max(); dl[d] = l[m].min()
        pdh = np.full(len(em), np.nan); pdl = np.full(len(em), np.nan)
        prev = {}
        for k, d in enumerate(udays):
            if k > 0:
                prev[d] = (dh[udays[k - 1]], dl[udays[k - 1]])
        for i in range(len(em)):
            if day[i] in prev:
                pdh[i], pdl[i] = prev[day[i]]
        levels["PD-High"] = (pdh, False)
        levels["PD-Low"] = (pdl, True)

    # Rolling-24h (Default 360 Bars = 6h; via CLI überschreibbar)
    if "ROLL" in level_names:
        rn = build_levels.roll_n
        levels["Roll-High"] = (rolling_extreme(h, rn, True), False)
        levels["Roll-Low"] = (rolling_extreme(l, rn, False), True)

    # Asia- / London-Session-Extreme, eingefroren nach Fensterende
    def sess_levels(start, end, label):
        hi = np.full(len(em), np.nan); lo = np.full(len(em), np.nan)
        for d in np.unique(day):
            dm = day == d
            win = dm & (mod >= start) & (mod < end)
            if not win.any():
                continue
            wh = h[win].max(); wl = l[win].min()
            after = dm & (mod >= end)          # erst nach Fensterende sweepbar
            hi[after] = wh; lo[after] = wl
        levels[f"{label}-High"] = (hi, False)
        levels[f"{label}-Low"] = (lo, True)

    if "ASIA" in level_names:
        sess_levels(0, 360, "Asia")
    if "LON" in level_names:
        sess_levels(420, 600, "London")
    return levels


build_levels.roll_n = 360


def session_of(minute: int) -> str:
    for name, s, e in SESSIONS:
        if s <= minute < e:
            return name
    return "Off-Session"


_LOADED: dict = {}


def _bars(sym):
    if sym not in _LOADED:
        arr = load_1m(sym)
        _LOADED[sym] = arr
    return _LOADED[sym]


def detect(sym, pen, buf, lookfwd, cooldown, level_names):
    """Erkennt Sweep-Reversal-Events. TARGET-UNABHÄNGIG: pro Event wird die
    maximal erreichte R-Ausdehnung VOR dem Stop gemessen (r_max), sodass jede
    Ziel-RR nachträglich als Schwelle (r_max >= target) anwendbar ist."""
    arr = _bars(sym)
    em = arr[:, 0].astype(np.int64)
    o, h, l, c = arr[:, 1], arr[:, 2], arr[:, 3], arr[:, 4]
    mod = (em % 1440).astype(np.int64)
    hod = (mod // 60).astype(np.int64)
    n = len(em)
    levels = build_levels(o, h, l, c, em, level_names)

    events = []
    last_ev = -10**9
    for i in range(1, n - 1):
        if i - last_ev < cooldown:
            continue
        for name, (lv, is_low) in levels.items():
            L = lv[i]
            if np.isnan(L):
                continue
            if is_low:
                swept = l[i] <= L - pen and c[i] > L      # Tiefs gesweept -> Long
                side = "long"
            else:
                swept = h[i] >= L + pen and c[i] < L      # Hochs gesweept -> Short
                side = "short"
            if not swept:
                continue

            entry = c[i]
            end = min(i + 1 + lookfwd, n)
            if side == "long":
                stop = l[i] - buf
                risk = entry - stop
                if risk <= 0:
                    continue
                r_max = 0.0; stopped = 0
                for k in range(i + 1, end):
                    if l[k] <= stop:                      # Stop zuerst prüfen (konservativ)
                        stopped = 1; break
                    r_here = (h[k] - entry) / risk
                    if r_here > r_max:
                        r_max = r_here
            else:
                stop = h[i] + buf
                risk = stop - entry
                if risk <= 0:
                    continue
                r_max = 0.0; stopped = 0
                for k in range(i + 1, end):
                    if h[k] >= stop:
                        stopped = 1; break
                    r_here = (entry - l[k]) / risk
                    if r_here > r_max:
                        r_max = r_here

            events.append(dict(
                i=i, hod=int(hod[i]), minute=int(mod[i]), side=side,
                level=name, session=session_of(int(mod[i])),
                risk=float(risk), r_max=float(r_max), stopped=stopped))
            last_ev = i
            break   # ein Event je Bar (erstes zutreffendes Level)
    return events


def agg(events, key, target):
    """Aggregiert Events nach key. Ziel-Hit = r_max >= target."""
    buckets: dict = {}
    for e in events:
        buckets.setdefault(e[key], []).append(e)
    rows = []
    for b, ev in buckets.items():
        rr = np.array([x["r_max"] for x in ev])
        rows.append(dict(
            bucket=b, n=len(ev),
            hit_rate=round(100 * np.mean(rr >= target), 1),
            stop_rate=round(100 * np.mean([x["stopped"] for x in ev]), 1),
            median_rr=round(float(np.median(rr)), 2),
            p75_rr=round(float(np.percentile(rr, 75)), 2),
            share=0.0))
    tot = sum(r["n"] for r in rows) or 1
    for r in rows:
        r["share"] = round(100 * r["n"] / tot, 1)
    return rows


def ptable(title, rows, sort_key, top=None):
    rows = sorted(rows, key=lambda r: r[sort_key], reverse=True)
    if top:
        rows = rows[:top]
    print(f"\n{title}")
    print(f"  {'Bucket':<14}{'n':>6}{'Anteil':>8}{'Ziel-Hit%':>10}{'Stop%':>8}{'Median-RR':>11}{'P75-RR':>9}")
    for r in rows:
        print(f"  {str(r['bucket']):<14}{r['n']:>6}{r['share']:>7}%{r['hit_rate']:>9}%{r['stop_rate']:>7}%{r['median_rr']:>11}{r['p75_rr']:>9}")


def _flist(s):
    return [float(x) for x in str(s).split(",") if x.strip() != ""]


def run_grid(sym, pen_list, target_list, buf_fixed, lookfwd, cooldown, level_names):
    """Matrix über pen (Detektion) × target (Bewertung). events pro pen einmal."""
    print("\nGRID  (pro pen einmal erkannt; Ziel-RR nur als Schwelle auf r_max)")
    hdr = f"  {'pen':>6}{'buf':>7}{'events':>8}{'med-RR':>8}{'p75-RR':>8}{'stop%':>7}"
    hdr += "".join([f"{'Hit@'+str(t):>9}" for t in target_list])
    print(hdr)
    grid = []
    for pen in pen_list:
        buf = pen if buf_fixed is None else buf_fixed
        ev = detect(sym, pen, buf, lookfwd, cooldown, level_names)
        n = len(ev)
        if n == 0:
            print(f"  {pen:>6}{buf:>7}{0:>8}{'-':>8}{'-':>8}{'-':>7}")
            grid.append(dict(pen=pen, buf=buf, events=0))
            continue
        rr = np.array([e["r_max"] for e in ev])
        med = float(np.median(rr)); p75 = float(np.percentile(rr, 75))
        stopr = 100 * np.mean([e["stopped"] for e in ev])
        hits = {t: round(100 * float(np.mean(rr >= t)), 1) for t in target_list}
        row = f"  {pen:>6}{buf:>7}{n:>8}{med:>8.2f}{p75:>8.2f}{stopr:>6.0f}%"
        row += "".join([f"{hits[t]:>8}%" for t in target_list])
        print(row)
        grid.append(dict(pen=pen, buf=buf, events=n, median_rr=round(med, 2),
                         p75_rr=round(p75, 2), stop_rate=round(stopr, 1),
                         hit_rate=hits))
    out = OUT / f"reversal_grid_{sym}.json"
    out.write_text(json.dumps(dict(sym=sym, pen_grid=pen_list,
                   target_grid=target_list, grid=grid), indent=2))
    print(f"\n→ Grid-Details: {out}")
    print("\nLesehilfe: 'events' = Signalzahl (fällt mit größerer pen), "
          "'Hit@T' = % der Events, die vor dem Stop >= T·R erreichten.\n"
          "Für ~1 Signal/Woche/Symbol: pen so wählen, dass events/Zeitraum passt, "
          "und ein target, dessen Hit@T noch tragbar ist.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sym")
    ap.add_argument("--pen", type=float, default=0.0, help="Min-Penetration in PREIS-Einheiten (Docht über Level). 0 = jeder Durchstich.")
    ap.add_argument("--buf", type=float, default=None, help="Stop-Puffer hinter dem Wick (Preis). Default = --pen.")
    ap.add_argument("--lookfwd", type=int, default=120, help="Forward-Fenster in Bars (1m) für RR-Messung.")
    ap.add_argument("--target", type=float, default=5.0, help="Ziel-RR für die Hit-Rate (Default 5).")
    ap.add_argument("--cooldown", type=int, default=30, help="Min. Bars zwischen Events.")
    ap.add_argument("--roll", type=int, default=360, help="Rolling-Range-Lookback (Bars).")
    ap.add_argument("--levels", type=str, default="PD,ROLL,ASIA,LON", help="Referenz-Level: PD,ROLL,ASIA,LON (Komma).")
    ap.add_argument("--pen-grid", type=str, default="", help="Grid-Modus: pen-Werte, z.B. 0,5,10,15,20,25")
    ap.add_argument("--target-grid", type=str, default="", help="Grid-Modus: target-RR-Werte, z.B. 3,5,8,10")
    a = ap.parse_args()

    level_names = [x.strip().upper() for x in a.levels.split(",") if x.strip()]
    build_levels.roll_n = a.roll

    print(f"== Reversal-Timing {a.sym} ==")

    # ---- Grid-Modus ----
    if a.pen_grid or a.target_grid:
        pen_list = _flist(a.pen_grid) if a.pen_grid else [a.pen]
        target_list = _flist(a.target_grid) if a.target_grid else [a.target]
        print(f"lookfwd={a.lookfwd}  cooldown={a.cooldown}  roll={a.roll}  levels={level_names}")
        run_grid(a.sym, pen_list, target_list, a.buf, a.lookfwd, a.cooldown, level_names)
        return

    # ---- Einzel-Lauf mit voller Aufschlüsselung ----
    buf = a.pen if a.buf is None else a.buf
    print(f"pen={a.pen}  buf={buf}  lookfwd={a.lookfwd}  target-RR={a.target}  "
          f"cooldown={a.cooldown}  roll={a.roll}  levels={level_names}")

    events = detect(a.sym, a.pen, buf, a.lookfwd, a.cooldown, level_names)
    if not events:
        print("Keine Events erkannt — Penetration/Level prüfen.")
        return

    n = len(events)
    hit = np.mean([e["r_max"] >= a.target for e in events])
    med = np.median([e["r_max"] for e in events])
    print(f"\nGesamt: {n} Reversal-Events | Ziel-RR>={a.target} erreicht: {100*hit:.1f}% "
          f"| Median-max-RR: {med:.2f}")

    by_hour = agg(events, "hod", a.target)
    ptable("Nach UTC-Stunde (Top nach Häufigkeit):", by_hour, "n")
    ptable("Nach UTC-Stunde (Top nach Ziel-Hit-Rate, min. 10 Events):",
           [r for r in by_hour if r["n"] >= 10], "hit_rate")
    ptable("Nach Session:", agg(events, "session", a.target), "n")
    ptable("Nach Referenz-Level:", agg(events, "level", a.target), "n")
    ptable("Nach Richtung:", agg(events, "side", a.target), "n")

    out = OUT / f"reversal_timing_{a.sym}.json"
    out.write_text(json.dumps(dict(
        sym=a.sym, params=vars(a), total=n,
        hit_rate=round(100 * float(hit), 1), median_rr=round(float(med), 2),
        by_hour=by_hour, by_session=agg(events, "session", a.target),
        by_level=agg(events, "level", a.target), by_side=agg(events, "side", a.target)),
        indent=2))
    print(f"\n→ Details: {out}")


if __name__ == "__main__":
    main()
