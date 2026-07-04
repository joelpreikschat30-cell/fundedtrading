# Ergebnisbericht — Master Session-Range-Strategie auf ECHTEN Daten

**Stand:** 2026-07-04 · **Branch:** `claude/pine-v6-futures-strategies-symrq5`
**Daten:** echte Dukascopy-Bars, 12 Monate (2025-07-01 – 2026-06-30),
261 Handelstage je Instrument — XAUUSD (Gold) & USATECHIDXUSD (Nasdaq-100-CFD ≈ NQ).

---

## Was hier neu ist

Auf deinen Wunsch: die drei alten, indikatorlastigen Strategien wurden ersetzt
durch **eine** price-action-basierte **Master-Strategie** mit zwei Modi
(NY-Opening-Range-**Breakout** nach Zarattini/Aziz + ICT-Asian-Range-**Sweep**),
VWAP als einziger optionaler Filter — und validiert nicht mehr auf synthetischen,
sondern auf **echten** von Dukascopy geladenen Bars (12 Monate, 1m→5m aggregiert).

Getestet wurden 4 Kombinationen (2 Instrumente × 2 Modi), jeweils mit voller
8-Test-Suite. Alle Zahlen unten sind auf echten Daten berechnet.

---

## Kernergebnisse (12 Monate, Analyselauf ohne Kill-Switch, 0,5 % Risiko/Trade)

| Konfiguration | Trades | Win-Rate | PF | Expectancy | Net % | Max-DD | Sharpe |
|---|---|---|---|---|---|---|---|
| **Gold · Breakout (NY-ORB)** | 235 | 42,1 % | **1,11** | +0,07 R | **+5,7 %** | 8,8 % | 0,84 |
| NAS · Breakout (NY-ORB) | 245 | 40,0 % | 1,01 | +0,01 R | +0,4 % | 9,0 % | −0,03 |
| Gold · Sweep (Asia) | 179 | 39,1 % | 0,85 | −0,12 R | −8,3 % | 10,3 % | −0,87 |
| NAS · Sweep (Asia) | 124 | 27,4 % | 0,52 | −0,47 R | −21,0 % | 21,4 % | −3,45 |

Auf den ersten Blick: Gold-Breakout sieht gut aus. **Die kritische Analyse
zerlegt dieses Ergebnis aber — und das ist die eigentliche Botschaft.**

---

## 🚨 Die kritischen Befunde (warum „positiv" hier nicht „fundbar" heißt)

### 1. Sweep-Modus hat auf keinem Instrument einen Edge
Gold-Sweep PF 0,85, NAS-Sweep PF 0,52 (−21 %!). Beide werden nach Kosten noch
schlechter (Gold-Sweep 2x-Kosten → PF 0,52). Walk-Forward NAS-Sweep 0/5 positiv.
**→ ICT-Asian-Range-Sweep in dieser mechanischen Form: verwerfen.**

### 2. Der Breakout-Gewinn kommt AUSSCHLIESSLICH aus Shorts — Longs verlieren
Der wichtigste Fund. Richtungs-Split (o. Limits, 0,5 %):

| | Long net | Long PF | Short net | Short PF |
|---|---|---|---|---|
| **Gold-Breakout** | **−$1.032** | 0,94 | **+$3.893** | 1,43 |
| NAS-Breakout | −$1.652 | 0,89 | +$1.840 | 1,16 |

Auf beiden Instrumenten sind die **Long-Breakouts defizitär**; der gesamte
Netto-Gewinn stammt aus einer Handvoll Short-Trades (Gold: 95 Shorts).
- **Entlastend:** Es ist *kein* naives Trend-Reiten — im +85 %-Gold-Bullenjahr
  hätte Trend-Reiten über Longs verdient; hier verlieren die Longs.
- **Belastend:** Ein so einseitiger Edge über *ein* 12-Monats-Fenster, getragen
  von ~95 Trades, ist mit hoher Wahrscheinlichkeit eine **perioden- und
  richtungsspezifische Anomalie**, kein stabiler, symmetrischer Edge.

### 3. Walk-Forward widerspricht dem Gesamt-Ergebnis
Trotz positivem Gesamt- und IS/OOS-Split ist die rollierende Re-Optimierung schwach:

| Konfig | IS→OOS (PF) | Walk-Forward positiv | WF OOS-net |
|---|---|---|---|
| Gold-Breakout | 1,04 → **1,58** | **2/5** | **−$1.326** |
| NAS-Breakout | 1,05 → 1,06 | 2/5 | −$604 |

Der 70/30-Holdout hält (gut, kein klassisches Overfitting auf dem Split), aber
**nur 2 von 5 rollierenden Testfenstern sind positiv, mit negativer Summe.**
Das ist das klassische Zeichen für einen **zeitlich instabilen Edge** — er lebt
von wenigen Phasen, nicht von durchgehender Kante.

### 4. NAS-Breakout ist brutto nur break-even und stirbt nach Kosten
PF 1,01, Expectancy +0,01 R. Kosten-Stress: 1x PF 1,01 → **2x PF 0,96** → 3x 0,92.
Der Edge existiert nur im Trend-/Hoch-Vol-Regime (Trend-Tage PF 1,12, Range-Tage
0,56) und überlebt realistische Kosten nicht. **Nicht handelbar wie er ist.**

### 5. Robust ist nur Gold-Breakout — mit Sternchen
Positiv: übersteht 2x Kosten (PF 1,04), parameter-robust (rr & Range-Filter
durchgängig positiv, keine Vorzeichen-Flips), Monte-Carlo-Worst-DD ~12 %,
OOS ≥ IS. Aber Punkte 2+3 (Short-only, WF 2/5) ziehen die Belastbarkeit stark
nach unten.

---

## Prop-Firm-Compliance & Sizing

- **Bei 0,5 % Risiko/Trade reißen ALLE vier Configs die 6 %-Trailing-DD-Grenze**
  (Max-DD 8,8–21,4 % ohne Limits). Der eingebaute Kill-Switch kappt in der
  Produktion korrekt bei ~6,0–6,2 % und schaltet die Strategie ab (killed=True
  überall) — d. h. selbst die profitable Gold-Config wäre auf einem 6 %-Konto
  abgeschaltet worden, bevor sie den Gewinn einfahren konnte.
- **Risiko-Reduktion hilft, ist aber durch Kontrakt-Granularität begrenzt.**
  Bei $50k-Konto und MGC ($10/Punkt) rundet feineres Sizing auf breiten Stops
  häufig auf 0 Kontrakte:

  | Gold-Breakout | Trades | PF | Max-DD |
  |---|---|---|---|
  | 0,50 % Risiko | 235 | 1,11 | 8,8 % |
  | **0,35 % Risiko** | 171 | **1,26** | **4,9 %** ✅ |
  | 0,25 % Risiko | 110 | 1,08 | 4,1 % |

  Bei 0,35 % passt Gold-Breakout unter 6 % DD und bleibt profitabel — allerdings
  fallen dabei ~60 Trades weg (nur weil sie auf 0 Kontrakte runden), was die
  Statistik dünner macht. Sauberes 0,25–0,35 %-Sizing bräuchte ein größeres
  Konto oder feinere Kontrakte.
- Tägliches Loss-Limit (3 %) wurde in keiner Config je an einem einzelnen Tag
  gerissen (schlechtester Tag ≤ 1,3 %) — die Strategien sind intraday gut
  gestreut; das Risiko ist der **kumulative Trailing-Drawdown**, nicht der Tag.

---

## Klare Einschätzung: fundbar?

**Nein — keine der vier Konfigurationen ist in dieser Form für ein striktes
Funded-/Prop-Konto geeignet.** Begründung:
- Sweep-Modus: kein Edge (verwerfen).
- NAS-Breakout: break-even, stirbt nach Kosten.
- Gold-Breakout: bester Kandidat, aber der Gewinn ist (a) einseitig auf Shorts,
  (b) auf ~95 Trades und ein einzelnes 12-Monats-Fenster konzentriert und
  (c) walk-forward-instabil. Das reicht nicht für echtes Kapital mit 6 %-Limit.

Der Test hat sich also **methodisch bewährt**: Er hat auf echten Daten Struktur
gefunden (anders als auf synthetischen), aber die kritischen Zerlegungen
(Richtungs-Split, Walk-Forward, Kosten-Stress) entlarven das Headline-Ergebnis
als fragil statt fundbar. Genau dafür sind diese Tests da.

---

## Was müsste angepasst werden (konkrete nächste Schritte)

1. **Regime-Filter einbauen** — der stärkste Hebel. Auf beiden Breakout-Configs
   liegt der Edge fast vollständig in Trend-/Hoch-Vol-Tagen (Gold Trend-Tag
   PF 1,27 vs Range-Tag 0,68; NAS 1,12 vs 0,56). Nur an Tagen mit hohem
   Tages-ATR / klarer Vortagsrichtung handeln. (Der Range-Größenfilter am
   Tages-ATR ist bereits im Code — als Tagestyp-Filter ausbauen.)
2. **Die Short-only-Asymmetrie untersuchen**, statt sie zu glauben. Ist der
   Long-Verlust ein Kosteneffekt (breitere Stops?), ein Session-Timing-Problem,
   oder echt? Wenn Longs strukturell nicht funktionieren → ggf. nur Shorts
   handeln, aber erst nach Bestätigung auf einem zweiten Zeitraum.
3. **Auf einem ÄLTEREN/LÄNGEREN Fenster gegentesten**, das Gold-Range- und
   -Bärenphasen enthält (z. B. 2022–2024). Das aktuelle Fenster ist ein extremes
   Gold-Bullenjahr; ein Edge muss auch außerhalb überleben.
4. **Kosten konservativ halten:** Alle Live-Entscheidungen an der 2x-Kosten-Zeile
   messen (Limit-TPs füllen im Backtest ohne Slippage — real schlechter).
5. **Forward-Test** (nur falls 1–3 bestehen): 4–6 Wochen Sim-Funded auf MGC
   (Gold-Breakout, Regime-gefiltert, 0,35 % Risiko), NY-Session. NAS/MNQ erst
   nachziehen, wenn dort ein Edge nachweisbar ist.
6. **Für die finale Freigabe** echte CME-Futures gegenchecken (Databento),
   da hier XAUUSD-Spot bzw. NAS100-CFD als Näherung dienten.

---

## Grenzen dieses Tests (Transparenz)

- **Instrument-Näherung:** XAUUSD-Spot ≈ GC/MGC (Preisbewegung quasi identisch,
  Kontraktspezifikation leicht anders); NAS100-CFD ≈ NQ/MNQ (Index vs. Future,
  minimale Abweichungen, kein echter Kontraktrollover/Verfall).
- **Ein 12-Monats-Fenster** — statistisch grenzwertig (Session-Setups = ~1/Tag).
  Gold-Sweep/NAS-Sweep haben < 200 Trades (Wilson-CI entsprechend breit).
- **Fill-Annahmen:** SL-first konservativ, Slippage auf Market/Stop, Limit-TP
  ohne Slippage (wie TradingView) — reale Fills an schnellen Breaks sind schlechter.
- **Backtest ≠ Live:** Latenz, Teilfills, Spread-Ausweitung an News nicht
  abgebildet. Kein Ersatz für Forward-Test.

---

## Dateien

| Pfad | Inhalt |
|---|---|
| `strategies/master_session_range.pine` | Master-Strategie, Pine v6 (Breakout + Sweep) |
| `validation/dukascopy.py` | Echtdaten-Downloader (freie .bi5-Tickdaten → 1m-Bars) |
| `validation/master_engine.py` | Resampling, Signal-Logik (1:1 zu Pine), Simulator |
| `validation/run_master.py` | 8-Test-Suite auf echten 12-Monats-Bars |
| `validation/summarize.py` | Konsolen-Übersicht der Ergebnisse |
| `validation/results/master_results.json` | Vollständige Roh-Ergebnisse |
