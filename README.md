# fundedtrading — Master Session-Range-Strategie (Pine v6) + Echtdaten-Validierung

**Eine** price-action-basierte Master-Strategie für Gold (XAUUSD/GC/MGC) **und**
Nasdaq (NAS100/NQ/MNQ), validiert auf **echten Dukascopy-Daten (12 Monate)**.

Keine laggenden Indikatoren (kein EMA/RSI) — reine Session-Struktur + Price
Action, VWAP als einziger optionaler Konfluenz-Filter.

➡️ **Ergebnisse & Einschätzung: [REPORT.md](REPORT.md)**

## NEU: Snipe-Points-Indikator (`indicators/snipe_points.pine`)

Pine-v6-**Indikator** (nicht Strategie) für seltene, hoch-asymmetrische
1m-Reversal-Setups auf MGC/SIL/MNQ/MES. Vollständige Signal-Pipeline:

1. **Multi-Session-Engine** — Asia, London-KZ, NY-Pre, NY-IB, PM/London-Close
   + 3 LBMA-Fix-Fenster (in `Europe/London`, DST-sicher); Boxen im Chart.
2. **Sweep-Detection** gegen Asia-/London-/Vortages-H-L + Rolling-24h-Range,
   mit Min-Penetration in Ticks.
3. **MSS + Displacement** — Close jenseits Gegen-Swing + Körper > k×Ø-Körper.
4. **Stop-Engine, 3 Methoden** — Wick+Ticks · ATR(1m,n)×k · FVG-Rand.
5. **RR-Gate** — Signal nur wenn RR zum Ziel (Gegenseite Range / PDH-PDL)
   ≥ Mindest-RR (Default 1:5).
6. **Range-Expansion-Score** — gewichtet aus ATR-Regime-Perzentil, Narrow-IB,
   Overnight-Range, Inside-Day; Cutoff kalibrierbar für ~1 Signal/Woche/Symbol.
7. **Optionale Filter** — SMT-Divergenz (MNQ↔MES, MGC↔SIL), VWAP-Rejection,
   Kalender-Filter (manuelle Datumsliste, block/allow).
8. **Turtle Soup** — separates Modul (N-Tage-Extrem-Fehlausbruch).

Alerts für jedes Signal, Dashboard mit Score-Transparenz + Signalzählern.
Repo-Abgleich & Modulplan: [docs/SNIPE_ANALYSE.md](docs/SNIPE_ANALYSE.md)

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
| `reversal_timing.py` | **Timing-Analyse für den Snipe-Indikator:** findet auf echten 1m-Daten, WANN (Stunde/Session/Referenz-Level) die häufigsten und hochwertigsten Sweep-Reversals entstehen — Kalibriergrundlage für Session-Toggles, Penetration und RR-Gate pro Symbol. Bsp: `python3 reversal_timing.py XAGUSD --target 5` |

**Daten:** echte XAUUSD- und NAS100-CFD-Bars von Dukascopy. Der NAS100-CFD ist
eine sehr enge Näherung an NQ/MNQ (Index vs. Future — minimale Spec-Unterschiede);
XAUUSD-Spot ist quasi identisch zur GC/MGC-Preisbewegung. Für die finale
Freigabe empfiehlt sich zusätzlich ein Check auf echten CME-Futures (Databento).
