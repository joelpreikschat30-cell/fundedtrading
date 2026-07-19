# Schritt 0 — Repo-Abgleich für den Snipe-Points-Indikator

**Stand:** 2026-07-19 · **Branch:** `claude/tradingview-snipe-points-bna9yl`

Abgleich des bestehenden Repos gegen die Snipe-Points-Spezifikation
(Session-Engine, Sweep-Detection, MSS/Displacement, SMT-Filter,
Stop/Target-Engine, Kalender-Filter, Range-Expansion-Filter).

## 1. Vorhandene Komponenten → Modul-Zuordnung

| Vorhanden (Datei / Stelle) | Modul lt. Spez | Bewertung |
|---|---|---|
| `strategies/master_session_range.pine` — `inRange`/`inTrade` via `time()` + `input.session`, Range-Bildung mit Freeze (`rHigh/rLow/rReady`, Z. 128–160) | Session-Engine | **(b) anpassen** — Muster (Start-Reset, Max/Min-Tracking, Freeze bei Fensterende) ist korrekt und anti-repaint-sauber, aber die Architektur kennt nur **eine** Range gleichzeitig. Spez braucht 8 parallele Fenster (Asia, London-KZ, NY-Pre, NY-Open/IB, PM, 3 LBMA-Fixes). → Muster in generische, mehrfach instanziierbare Funktion überführt. |
| Sweep-Bedingung `low < rLow and close > rLow` / `high > rHigh and close < rHigh` (Z. 199–200) | Sweep-Detection | **(b) anpassen** — Kernbedingung stimmt exakt mit der Spez überein und wird übernommen. Fehlt: Min-Penetration in Ticks, Sweep-Wick-Speicherung (für Stop), mehrere Referenz-Level (Asia/London/PDH-PDL/Rolling-24h) statt einer Range, Killzone-Gating. |
| Tages-ATR via `request.security(…,"D", ta.atr()[1], lookahead_off)` (Z. 135) | Range-Expansion-Filter (Teilbaustein) | **(a) wiederverwendbar** — korrektes Anti-Repaint-Muster, wird 1:1 für PDH/PDL und später ATR-Regime-Perzentil genutzt. Min/Max-Range-Filter (Z. 159–160) ist ein binärer Vorläufer des geforderten Score — Score selbst fehlt. |
| Stop-Engine: Structure/ATR-Stop + Puffer (Z. 221–234), Ziel R-Multiple/OppositeRange (Z. 249, 261) | Stop/Target-Engine | **(b) anpassen** — 2 von 3 Stop-Methoden (Wick-basiert ≈ „Structure/Sweep-Docht", ATR-Multiplikator) existieren als Logikmuster. Fehlt: FVG-Rand-Stop, Tick-Offset-Input, **RR-Gate** (im Bestand ist RR ein Ziel, kein Filter). Übernahme in Session 2. |
| VWAP `ta.vwap(hlc3)` als Richtungsfilter (Z. 136, 205–208) | VWAP-Rejection (optionaler Filter) | **(b) anpassen** — VWAP vorhanden, aber nur als Seitenfilter. Rejection-Kerzen-Logik (Wick durch VWAP, Close zurück) fehlt. |
| Risk-Engine (Daily-Loss, Kill-Switch, Sizing, Z. 97–186) | — (kein Spez-Modul) | Nicht relevant für den **Indikator** (ordert nicht); bleibt in der Strategie für spätere Strategy-Portierung wertvoll. |
| `validation/` (Dukascopy-Loader, master_engine, 8-Test-Suite, Monte Carlo, Wilson-CI) | — Kalibrierung/Backtest | **(a) wiederverwendbar** — genau die Pipeline, mit der die fehlenden MGC/SIL-HOD/LOD-Timings und der Score-Cutoff später ermittelt werden. Für Silber: `dukascopy.py XAGUSD …` funktioniert unverändert. |
| `REPORT.md` — Befund: mechanischer Asia-Sweep ohne Filter hat **keinen Edge** (Gold PF 0,85 / NAS PF 0,52) | — Evidenz | Wichtigster Bestandsbefund: bestätigt die Spez-Richtung. Der rohe Sweep-Fade (genau das, was der Bestandscode tut) verliert; die in der Spez geforderten Zusatzstufen (MSS + Displacement + RR-Gate + Expansion-Score + Selektivität 1x/Woche) sind exakt die fehlenden Bausteine. Kein Widerspruch zur 12.095-Sessions-Studie. |

## 2. Komplett fehlende Module (Kategorie c / neu)

1. **Multi-Session-Engine mit LBMA-Fix-Fenstern** (getrennt von Index-Killzones) + Session-Boxen im Chart
2. **MSS/CISD-Detection** (Swing-Punkte, Close jenseits Gegenstruktur)
3. **Displacement-Filter** (Körper > k × Ø-Körper, optional Strukturlevel-Close)
4. **FVG-Detection + FVG-Rand-Stop**
5. **RR-Gate** (Mindest-RR als Anzeigefilter)
6. **Range-Expansion-Score** (ATR-Regime-Perzentil, Narrow-IB, Overnight-Range, Inside-Day — kombiniert, nicht binär)
7. **SMT-Divergenz** (MNQ↔MES, MGC↔SIL via `request.security`, lookahead_off, confirmed-only)
8. **Turtle Soup** (N-Tage-Extrem-Fehlausbruch, Daily-HTF)
9. **Kalender-Filter** (Datumsliste als Input, Toggle)
10. **`alertcondition()`-Signale** (Strategie hat keine)
11. **Entry/Stop/Target-Linien + Labels** bei Signal

## 3. Zentrale Design-Entscheidungen

- **Neue Datei `indicators/snipe_points.pine` als `indicator()`, nicht Umbau der Strategie:** `alertcondition()` existiert nur in Indikatoren; die Master-Strategie bleibt unangetastet als Backtest-Referenz. Wiederverwendung erfolgt auf Muster-Ebene (Range-Tracking, Sweep-Bedingung, ATR-Daily-Request), nicht per Copy des Monolithen — die Ein-Range-Architektur passt strukturell nicht zu 8 parallelen Fenstern.
- **LBMA-Fixes in `Europe/London`-Zeitzone definiert** (10:15–10:45 / 11:45–12:15 / 14:45–15:15 London-Zeit), nicht in UTC: Die Fixes hängen an London-Lokalzeit, so folgt das Fenster automatisch der Sommer-/Winterzeit. UTC bleibt Basis aller übrigen Fenster (wie in der Spez).
- **24h-Modus als Rolling-Lookback-Range zusätzlich zu Session-Leveln:** deckt Metall-Bewegungen außerhalb der Killzones ab, ohne die Index-Logik zu verwässern (per Input trennbar, pro Symbol kalibrierbar).

## 4. Arbeitsstand

- **Session 1 (erledigt):** Multi-Session-Engine + Boxen, Sweep-Detection (Asia/London/PDH-PDL/Rolling), MSS + Displacement, Sweep-/Signal-Marker, Basis-Alerts — Testversion ohne Stop/Target/RR-Gate zur visuellen Kontrolle.
- **Session 2 (offen):** Stop/Target-Engine (3 Methoden inkl. FVG), RR-Gate, Expansion-Score, SMT, VWAP-Rejection, Turtle Soup, Kalender-Filter, finale Alerts/Labels, Frequenz-Sichttest.
