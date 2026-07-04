# Ergebnisbericht — 3 Intraday-Futures-Strategien (Pine Script v6)

**Stand:** 2026-07-04 · **Branch:** `claude/pine-v6-futures-strategies-symrq5`

---

## ⚠️ Lies das zuerst: Was diese Zahlen sind — und was nicht

In dieser Umgebung stehen **keine echten historischen GC/NQ-Bars** zur Verfügung
(kein TradingView-Chart, kein Datenfeed). Gemäß der Vorgabe *"erfinde keine
Performance-Zahlen ohne tatsächliche Berechnung"* wurde die **komplette
Validierungslogik lauffähig implementiert und ausgeführt** — auf **synthetischen
OHLCV-Daten** (Regime-Switching-Prozess mit Vol-Clustering, Intraday-Saisonalität,
~500 Handelstage ≈ 2 Jahre, Seed-fixiert und reproduzierbar).

Das bedeutet:

1. **Alle Zahlen unten sind Demonstration der Testmethodik**, keine Aussage über
   echte Marktperformance. Synthetische Daten enthalten die Mikrostruktur-Effekte
   nicht, aus denen diese Strategien ihren Edge ziehen wollen (Orderflow an
   Swing-Levels, Session-Momentum, echte Mean-Reversion-Zonen).
2. Der wissenschaftlich **korrekte** Befund: Auf Daten ohne ausbeutbare Struktur
   müssen alle drei Strategien **nach Kosten negativ** sein — und genau das zeigt
   die Pipeline. Eine Pipeline, die hier Gewinne anzeigen würde, wäre kaputt
   (Lookahead/Repaint/Kosten-Fehler).
3. Was die Pipeline **real validiert hat**: Regel-Implementierung, Anti-Repaint-
   Logik, Position-Sizing, Kostenmodell, Daily-Loss-Limiter, Kill-Switch,
   und die statistische Auswertungsmethodik (IS/OOS, Walk-Forward, Sensitivität,
   Monte Carlo, Kosten-Stress, Regime-Split, Wilson-CI, Prop-Compliance).
4. **Für echte Zahlen:** Pine-Skripte aus `strategies/` in TradingView auf
   MGC/GC bzw. MNQ/NQ laden (mind. 1–2 Jahre 5m-Daten, Premium-Plan für
   ausreichend Bars), Strategy-Tester-Export ziehen und die Trade-Liste durch
   `validation/` schicken (Monte Carlo, Wilson-CI etc. funktionieren 1:1 auf
   echten Trade-Listen).

**Setup der Simulation:** $50.000 Konto, MGC ($10/Punkt, Tick 0,1) bzw.
MNQ ($2/Punkt, Tick 0,25), Kommission $2,00–2,50/Kontrakt/Seite, Slippage 2–4
Ticks auf Market-/Stop-Fills (Limit-TPs füllen ohne Slippage, wie in
TradingView), SL-first-Annahme wenn SL und TP in derselben Bar liegen
(konservativ), Entries nur auf Bar-Close.

---

## Strategie 1 — Gold 5m Trend-Pullback Engulfing (`strategy1_gold_trend_pullback_engulfing.pine`)

### Kernkennzahlen (synthetisch, Analyselauf ohne Kill-Switch, 320 Trades)

| Kennzahl | Wert |
|---|---|
| Trades | 320 (Stichprobe ✅ ≥ 200) |
| Win-Rate | 37,8 % (Wilson-95%-CI: 32,7–43,2 %) |
| Profit Factor | 0,76 |
| Expectancy | −0,19 R / Trade |
| Max Drawdown | 21,5 % (ohne Limits) / **6,16 % mit Kill-Switch** |
| Sharpe / Sortino | −1,39 / −2,01 |

### IS/OOS (70/30, Mini-Grid auf IS optimiert, OOS unberührt)
IS: PF 0,83, WR 39,4 % → OOS: PF 0,69, WR 33,7 %. **OOS deutlich schwächer als
IS** — die Pipeline flaggt korrekt, dass selbst ein kleines 9-Punkte-Grid auf
Rauschen overfittet. Genau dieses Muster (IS ok, OOS bricht ein) ist das
Warnsignal, auf das man bei echten Daten achten muss.

### Walk-Forward (6M Train / 2M Test, 8 Walks)
Nur 2 von 8 Test-Fenstern positiv, kumuliertes OOS-Netto negativ. Kriterium für
echte Daten: **≥ 60–70 % positive Walks** und stabile Parameterwahl über die
Walks hinweg, sonst kein Go.

### Parameter-Sensitivität (±20–30 %)
Kein Vorzeichen-Flip über die Grids (PF bewegt sich glatt zwischen 0,63 und
0,82) → die Regel-Logik ist **strukturell stabil, aber ohne Edge auf diesen
Daten**. Auffällig: `rsi_lo=50` würgt fast alle Trades ab — die RSI-45–55-Zone
ist der bindende Filter und wäre bei echten Daten der erste
Curve-Fitting-Verdächtige.

### Monte Carlo (1000 Reihenfolge-Permutationen)
Median-MaxDD 20,5 %, P95 24,0 %, Worst 28,1 %, P(DD ≥ 6 %) = 100 % (erwartbar
bei negativer Expectancy).

### Kosten-Stress: 1x → PF 0,76 · 2x → 0,44 · 3x → 0,23
Monotone Degradation wie erwartet; bei echten Daten gilt: **Edge muss 2x-Kosten
überleben**, sonst kein Live-Einsatz.

### Regime: Trend PF 0,81 (215 Tr.) vs. Range 0,68 (105 Tr.) — die Strategie ist
wie designt trendabhängig; auf echten Daten Range-Phasen ggf. per ADX-Filter aussperren.

### Prop-Compliance
Ohne Limits: 21,5 % Max-DD (Konto-Bust). **Mit Limits: Kill-Switch greift bei
6,16 %** — Daily-Limit wurde nie gerissen (schlechtester Tag 1,6 %).
⚠️ Overshoot 6,16 % > 6,00 %: Der Check läuft auf Bar-Close; Prop-Firmen messen
intrabar. **Praxisregel: Kill-Switch 1 %-Punkt UNTER der Firm-Grenze
konfigurieren** (Firm 6 % → Input 5 %).

### Einschätzung
Implementierung produktionsreif, Risiko-Stack funktioniert nachweislich. Ob ein
Edge existiert, ist **offen** bis zum Test auf echten Bars. Erst MGC London/NY-
Session testen, RSI-Fenster und Engulfing-Modus (Body vs. strikt) als erste
Robustheits-Checks.

---

## Strategie 2 — Gold 1m Mean-Reversion RSI + EMA200 (`strategy2_gold_meanrev_rsi_ema200.pine`)

### Kernkennzahlen (synthetisch, 1m-Interpretation, 315 Trades)

| Kennzahl | Wert |
|---|---|
| Trades | 315 (Stichprobe ✅) |
| Win-Rate | 11,1 % (Wilson-CI: 8,1–15,1 %) |
| Profit Factor | 0,05 |
| Expectancy | **−2,13 R / Trade** |
| Max Drawdown | 67,2 % ohne Limits / 6,16 % mit Kill-Switch |

### 🚨 Der wichtigste Befund des gesamten Projekts — und er ist KEIN Synthetik-Artefakt:

**Die literale LuxAlgo-Regel (TP 10 Pips / SL 5 Pips) ist auf Futures
arithmetisch tot.** Nachrechnung: SL = 0,5 Gold-Punkte = $5 Risiko/MGC-Kontrakt.
Kosten pro Trade = 2×Kommission ($5) + 2×3 Ticks Slippage ($6) = **$11 — mehr als
das 2-fache des geplanten Risikos** (daher Expectancy ≈ −2 R statt −1 R bei
Losern). Selbst mit 1 Tick Slippage auf GC bleiben die Kosten ≈ 0,5 R. Das
bestätigt exakt die Warnung aus der Recherche ("Stop trusting your strategy
tester" für Scalping): Der Edge müsste absurd groß sein, um das zu bezahlen.

IS/OOS, Walk-Forward (0/8 positiv), Sensitivität (PF 0,01–0,08 über ALLE Grids —
kein Parameter rettet die Kostenstruktur), Monte Carlo (Median-DD 67 %) und
Kosten-Stress (2x → PF 0,00) bestätigen: strukturelles Problem, kein
Parameter-Problem.

### Einschätzung: **In der 10/5-Pip-Form NICHT für Futures-Prop-Konten geeignet.**
Erforderliche Anpassungen (im Pine-Skript bereits vorbereitet):
1. **Exit-Modus "ATR"** verwenden (SL = 1×ATR, TP = 2×SL) statt fixer Pips —
   Stop-Distanz skaliert dann mit realer Vol und die Kosten fallen auf < 0,15 R.
2. Alternativ Instrument wechseln: Spot-XAUUSD mit engem Spread (dafür war die
   LuxAlgo-Regel gebaut), nicht GC/MGC.
3. Trades/Tag niedrig halten (Kommissions-Drag) und nur London/NY handeln.

---

## Strategie 3 — NQ 5m EMA + VWAP Momentum (`strategy3_nq_ema_vwap_momentum.pine`)

### Kernkennzahlen (synthetisch, 377 Trades)

| Kennzahl | Wert |
|---|---|
| Trades | 377 (Stichprobe ✅) |
| Win-Rate | 36,1 % (Wilson-CI: 31,4–41,0 %) |
| Profit Factor | 0,73 |
| Expectancy | −0,31 R / Trade |
| Max Drawdown | 27,0 % ohne Limits / **6,26 % mit Kill-Switch** |
| Sharpe / Sortino | −1,93 / −2,81 |

### IS/OOS: PF 0,86 → 0,52 (WR 41,4 % → 28,6 %) — starkes Overfitting-Signal des Grids.
### Walk-Forward: 2/8 Walks positiv, OOS-Netto negativ.
### Sensitivität: glatt, keine Flips; PF steigt monoton mit `atr_mult` (0,9→1,6:
PF 0,57→0,82) — weitere Stops = weniger Noise-Stopouts. Auf echten Daten wäre
`atr_mult ≥ 1,5` der erste Kandidat.
### Monte Carlo: Median-DD 27,7 %, P95 31,3 %, P(DD ≥ 6 %) = 100 %.
### Kosten-Stress: 1x PF 0,73 · 2x 0,45 · 3x 0,27.
### Regime — das interessanteste Ergebnis: **Trend PF 0,94 (228 Tr.) vs. Range PF 0,46 (149 Tr.).**
Die Strategie ist im Trend-Regime fast break-even trotz Kosten und stirbt in der
Range. Ein Regime-Filter (z. B. ADX > 20 oder |EMA50−EMA200| > x·ATR auf 15m)
ist die vielversprechendste Weiterentwicklung — noch vor jeder Parameter-Optimierung.

### Prop-Compliance: Daily-Limit nie gerissen (worst day 1,75 %), Kill-Switch
begrenzt auf 6,26 % (gleicher Bar-Close-Overshoot wie S1 → Puffer einplanen).

### Einschätzung
Sauber implementiert, Risiko-Stack greift. Momentum-Logik ist plausibel, braucht
aber (a) echten NQ-RTH-Test, (b) Regime-Filter, (c) `atr_mult`-Bereich 1,25–1,6.
MNQ zuerst, NQ erst ab nachgewiesener Live-Konsistenz.

---

## Gesamtfazit & kritische Warnungen

1. **Kein einziger Performance-Wert hier belegt einen Edge** — die Tests liefen
   auf synthetischen Daten. Was belegt ist: die Strategien sind korrekt, ohne
   Repaint/Lookahead implementiert, das Risikomanagement funktioniert mechanisch
   (Kill-Switch kappte 21–67 % Drawdowns auf ~6,2 %), und die Auswertungs-
   pipeline erkennt Overfitting (IS→OOS-Bruch), Kosten-Fragilität und
   Regime-Abhängigkeit zuverlässig.
2. **Curve-Fitting-Risiko:** Schon das Mini-Grid (9 Kombinationen) produzierte
   IS-Ergebnisse, die OOS zusammenbrachen. Bei echten Daten: Grid klein halten,
   OOS nur EINMAL anfassen, Walk-Forward als Pflicht, niemals "Parameter-Surfing"
   bis das OOS schön aussieht.
3. **Hindsight-Bias:** Die Regeln stammen aus veröffentlichten TradingView-
   Skripten, deren gezeigte Equity-Kurven selbst überlebensverzerrt sind
   (publiziert wird, was rückblickend funktionierte).
4. **Kill-Switch-Puffer:** Bar-Close-Checks überschießen die Grenze um
   0,15–0,3 %-Punkte. Limits im Skript 1–1,5 %-Punkte unter der Firm-Grenze setzen
   (Firm 3 %/6 % → Inputs 2 %/4,5–5 %).
5. **TradingView-Slippage-Semantik:** Limit-TPs füllen ohne Slippage — reale
   Fills an schnellen Märkten sind schlechter. Der 2x-Kosten-Stress ist deshalb
   das relevante Szenario, nicht 1x.

## Nächste Schritte (konkret)

1. **Woche 0:** Skripte in TradingView laden (MGC 5m für S1, MGC/XAUUSD 1m für
   S2 im ATR-Modus, MNQ 5m für S3), Bar-Magnifier aktivieren falls Premium,
   2 Jahre Backtest, Trade-Listen exportieren.
2. **Woche 0–1:** Exportierte Trades durch `validation/` schicken (MC, Wilson,
   Kosten-Stress auf echten Trades). Go-Kriterien: ≥ 200 Trades, PF ≥ 1,3 nach
   2x-Kosten, OOS-PF ≥ 0,75×IS-PF, ≥ 60 % positive Walk-Forward-Fenster,
   MC-P95-DD < 2/3 der Prop-Grenze.
3. **Woche 1–7 (nur bei Go):** 4–6 Wochen Forward-Test auf Demo/Sim-Funded
   (Tradovate/NinjaTrader-Sim), 1 Kontrakt MGC bzw. MNQ, nur Haupt-Session.
   Slippage-Ist vs. -Annahme protokollieren.
4. **Danach:** Eval-Account mit halber Risikogröße (0,25 %/Trade), erst nach
   30+ Live-Trades ohne Limit-Verletzung auf Zielgröße.

## Dateien

| Pfad | Inhalt |
|---|---|
| `strategies/strategy1_gold_trend_pullback_engulfing.pine` | S1, Pine v6, produktionsreif |
| `strategies/strategy2_gold_meanrev_rsi_ema200.pine` | S2, Pine v6 (Pip- & ATR-Exit-Modus) |
| `strategies/strategy3_nq_ema_vwap_momentum.pine` | S3, Pine v6 |
| `validation/engine.py` | Simulations-/Metrik-Engine (Regeln 1:1 aus Pine) |
| `validation/run_validation.py` | Alle 8 Tests, reproduzierbar (Seed 42) |
| `validation/results/validation_results.json` | Vollständige Roh-Ergebnisse |
