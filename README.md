# fundedtrading — Master Session-Range-Strategie (Pine v6) + Echtdaten-Validierung

**Eine** price-action-basierte Master-Strategie für Gold (XAUUSD/GC/MGC) **und**
Nasdaq (NAS100/NQ/MNQ), validiert auf **echten Dukascopy-Daten (12 Monate)**.

Keine laggenden Indikatoren (kein EMA/RSI) — reine Session-Struktur + Price
Action, VWAP als einziger optionaler Konfluenz-Filter.

➡️ **Ergebnisse & Einschätzung: [REPORT.md](REPORT.md)**

## Die Strategie (`strategies/master_session_range.pine`)

Ein Framework, zwei dokumentierte Price-Action-Edges per Modus-Schalter:

| Modus | Quelle | Logik |
|---|---|---|
| **Breakout** | NY Opening Range Breakout (Zarattini & Aziz 2024) | Referenz-Range = erste Min. der NY-RTH; 5m-Close jenseits der Range → Entry in Ausbruchsrichtung |
| **Sweep** | ICT Asian Range / Judas Swing | Asia-Range über Nacht; Docht durchsticht Extrem + Close zurück in Range (Liquidity-Sweep) → Reversal-Fade |

Gemeinsam: %-Equity-Sizing, Struktur-/ATR-Stops, R-Multiple- oder Opposite-Range-
Ziele, Session-Filter, Range-Größenfilter (relativ zum **Tages-ATR**),
Daily-Loss-Limiter + Max-DD-Kill-Switch, EOD-Flat, 1 Setup/Richtung/Tag.
Anti-Repaint: `barstate.isconfirmed`, `process_orders_on_close`, HTF-Requests
mit `lookahead_off` + `[1]`-Offset. Live-Dashboard via `table.new`.

**Presets** (in den Inputs dokumentiert): Gold-Asia-Sweep · Index-NY-ORB.

## Echtdaten-Pipeline (`validation/`)

```bash
pip install numpy
cd validation
# 1) Echte 1m-Bars von Dukascopy laden (freie Tick-Historie, kein Account):
python3 dukascopy.py XAUUSD        2025-07-01 2026-06-30
python3 dukascopy.py USATECHIDXUSD 2025-07-01 2026-06-30
# 2) Volle Validierung (4 Konfigs = 2 Instrumente x 2 Modi):
python3 run_master.py
python3 summarize.py       # kompakte Konsolen-Übersicht
```

| Datei | Zweck |
|---|---|
| `dukascopy.py` | Lädt & dekodiert echte .bi5-Tickdaten → 1m-OHLCV (resumierbar) |
| `master_engine.py` | Resampling, Signal-Logik (1:1 zur Pine), Trade-Simulator |
| `run_master.py` | 8-Test-Suite: IS/OOS, Walk-Forward, Sensitivität, Monte Carlo, Kosten-Stress, Regime, Wilson-CI, Prop-Compliance |
| `engine.py` | Wiederverwendete Analytik (Metriken, Monte Carlo, Wilson) |
| `results/master_results.json` | Vollständige Roh-Ergebnisse |

**Daten:** echte XAUUSD- und NAS100-CFD-Bars von Dukascopy. Der NAS100-CFD ist
eine sehr enge Näherung an NQ/MNQ (Index vs. Future — minimale Spec-Unterschiede);
XAUUSD-Spot ist quasi identisch zur GC/MGC-Preisbewegung. Für die finale
Freigabe empfiehlt sich zusätzlich ein Check auf echten CME-Futures (Databento).
