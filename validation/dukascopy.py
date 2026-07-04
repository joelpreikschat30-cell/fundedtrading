"""
Dukascopy-Echtdaten-Downloader (freie Tick-Historie, kein Account).

Laedt .bi5-Tickdateien (LZMA-komprimiert), dekodiert sie, baut daraus
1-Minuten-OHLCV-Bars und speichert sie als .npz. Resumierbar (Tages-Cache),
robuste Retries gegen die transienten Connection-Resets des Feeds.

Tick-Format (20 Byte, Big-Endian): ms_offset(uint32), ask(uint32),
bid(uint32), askvol(float), bidvol(float). Preis = int / 1000 (XAUUSD & die
USATECHIDXUSD/US-Index-CFDs haben 3 Nachkommastellen -> Divisor 1000).

Aufruf:  python3 dukascopy.py XAUUSD 2025-07-01 2026-06-30
"""
from __future__ import annotations

import lzma
import struct
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

BASE = "https://datafeed.dukascopy.com/datafeed"
PRICE_DIV = {"XAUUSD": 1000.0, "USATECHIDXUSD": 1000.0}
CACHE = Path(__file__).parent / "cache"
DATA = Path(__file__).parent / "data"
CACHE.mkdir(exist_ok=True)
DATA.mkdir(exist_ok=True)

_HDR = {"User-Agent": "Mozilla/5.0"}


def fetch_hour(sym: str, dt: datetime, retries: int = 6) -> bytes | None:
    """Eine Stundendatei holen. None = definitiv keine Daten (404/leer)."""
    # Dukascopy: Monat 0-indexiert
    url = (f"{BASE}/{sym}/{dt.year:04d}/{dt.month - 1:02d}/{dt.day:02d}/"
           f"{dt.hour:02d}h_ticks.bi5")
    delay = 1.0
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=_HDR),
                                        timeout=30) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None            # keine Daten (Wochenende/Feiertag/Randstunde)
            time.sleep(delay); delay *= 1.8
        except Exception:
            time.sleep(delay); delay *= 1.8
    return None


def decode_ticks(raw: bytes, sym: str, hour_start: datetime):
    """bi5 -> Liste (epoch_sec_float, mid_price, volume)."""
    if not raw:
        return []
    data = lzma.decompress(raw)
    n = len(data) // 20
    div = PRICE_DIV[sym]
    base = hour_start.timestamp()
    out = []
    for i in range(n):
        ms, ask, bid, av, bv = struct.unpack(">IIIff", data[i * 20:(i + 1) * 20])
        out.append((base + ms / 1000.0, (ask + bid) / 2.0 / div, av + bv))
    return out


def day_to_1m(sym: str, d: date, pool: ThreadPoolExecutor) -> np.ndarray | None:
    """Ein Handelstag -> 1m-OHLCV-Array [epoch_min, o,h,l,c,v]. Cache-fähig."""
    cache_f = CACHE / f"{sym}_{d.isoformat()}.npz"
    if cache_f.exists():
        return np.load(cache_f)["bars"]

    hours = [datetime(d.year, d.month, d.day, h, tzinfo=timezone.utc)
             for h in range(24)]
    raws = list(pool.map(lambda hh: fetch_hour(sym, hh), hours))
    ticks = []
    for hh, raw in zip(hours, raws):
        ticks.extend(decode_ticks(raw, sym, hh))
    if not ticks:
        np.savez_compressed(cache_f, bars=np.empty((0, 6)))
        return np.empty((0, 6))

    ticks.sort(key=lambda t: t[0])
    ts = np.array([t[0] for t in ticks])
    px = np.array([t[1] for t in ticks])
    vol = np.array([t[2] for t in ticks])
    minute = (ts // 60).astype(np.int64)
    bars = []
    # gruppiere nach Minute (ts ist sortiert)
    uniq, idx = np.unique(minute, return_index=True)
    idx = list(idx) + [len(minute)]
    for k in range(len(uniq)):
        s, e = idx[k], idx[k + 1]
        seg = px[s:e]
        bars.append((uniq[k], seg[0], seg.max(), seg.min(), seg[-1], vol[s:e].sum()))
    arr = np.array(bars, dtype=np.float64)
    np.savez_compressed(cache_f, bars=arr)
    return arr


def build(sym: str, start: str, end: str):
    d0 = datetime.strptime(start, "%Y-%m-%d").date()
    d1 = datetime.strptime(end, "%Y-%m-%d").date()
    all_bars = []
    n_days = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=24) as pool:
        d = d0
        while d <= d1:
            if d.weekday() < 5:  # Mo-Fr
                arr = day_to_1m(sym, d, pool)
                if arr is not None and len(arr):
                    all_bars.append(arr)
                n_days += 1
                if n_days % 20 == 0:
                    tot = sum(len(a) for a in all_bars)
                    print(f"  {sym} {d} | {n_days} Tage | {tot} 1m-Bars | "
                          f"{time.time() - t0:.0f}s", flush=True)
            d += timedelta(days=1)
    out = np.vstack(all_bars) if all_bars else np.empty((0, 6))
    np.savez_compressed(DATA / f"{sym}_1m.npz", bars=out)
    print(f"FERTIG {sym}: {len(out)} 1m-Bars -> {DATA / (sym + '_1m.npz')} "
          f"({time.time() - t0:.0f}s)", flush=True)


if __name__ == "__main__":
    build(sys.argv[1], sys.argv[2], sys.argv[3])
