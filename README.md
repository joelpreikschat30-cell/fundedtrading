# fundedtrading — Pine v6 Futures-Strategien + Validierungs-Suite

Drei intraday Futures-Strategien (Gold GC/MGC, Nasdaq NQ/MNQ) als
produktionsreife **Pine Script v6**-Implementierungen mit eingebautem
Prop-Firm-Risikomanagement, plus eine lauffähige **Python-Validierungs-Pipeline**
(IS/OOS, Walk-Forward, Sensitivität, Monte Carlo, Kosten-Stress, Regime-Analyse,
Wilson-CI, Prop-Compliance).

➡️ **Ergebnisse & Einschätzung: [REPORT.md](REPORT.md)** — bitte zuerst den
Abschnitt zu synthetischen Daten lesen.

## Strategien (`strategies/`)

| # | Datei | Markt/TF | Logik |
|---|---|---|---|
| S1 | `strategy1_gold_trend_pullback_engulfing.pine` | Gold 5m (Trend 15m) | Trend-Pullback an Swing-Level + Engulfing, RR 1:2–1:3 |
| S2 | `strategy2_gold_meanrev_rsi_ema200.pine` | Gold 1m/5m | Mean-Reversion RSI 30/70 + EMA200-Filter, fixe Pip- oder ATR-Exits |
| S3 | `strategy3_nq_ema_vwap_momentum.pine` | NQ 5m (RTH) | EMA-9/21-Cross + VWAP-Slope + Volumen-Spike, 1:2 RR |

Gemeinsame Features: % Equity-Position-Sizing, ATR-/Swing-Stops, Session-Filter,
Max-Trades/Tag, **Daily-Loss-Limiter** und **Max-Drawdown-Kill-Switch**
(konfigurierbar, z. B. 3 % / 6 %), Anti-Repaint (`barstate.isconfirmed`,
`lookahead_off` + `[1]`-Offset), Live-Dashboard (`table.new`), Futures-gerechte
Kommission/Slippage/Margin.

**Nutzung:** Datei-Inhalt in den TradingView Pine-Editor kopieren → auf
MGC1!/GC1! bzw. MNQ1!/NQ1! im passenden Timeframe laden → Inputs (Session-
Zeitzone, Prop-Limits, Risiko-%) prüfen.

## Validierung (`validation/`)

```bash
pip install numpy
cd validation && python3 run_validation.py
# -> results/validation_results.json  (Laufzeit ~1-2 min)
```

Läuft auf klar gekennzeichneten **synthetischen Daten** (Demonstration der
Methodik; echte Validierung erfordert TradingView-Backtests auf echten Bars —
Ablauf siehe REPORT.md, "Nächste Schritte").
