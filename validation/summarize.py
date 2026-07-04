"""Kompakte Konsolen-Zusammenfassung von results/master_results.json."""
import json
from pathlib import Path

r = json.load(open(Path(__file__).parent / "results" / "master_results.json"))
for name, v in r.items():
    print("=" * 72)
    print(f"{name}  [{v['instrument']}]  {v['days']} Tage, {v['bars_5m']} 5m-Bars")
    b, bp = v["baseline"], v["baseline_production"]
    print(f"  Analyse (o. Limits): tr={b.get('trades')} wr={b.get('win_rate',0):.1f}% "
          f"pf={b.get('profit_factor',0):.2f} exp={b.get('expectancy_r',0):.2f}R "
          f"net={b.get('net_pct',0):.1f}% maxDD={b.get('max_dd_pct',0):.1f}% "
          f"sharpe={b.get('sharpe',0):.2f}")
    print(f"  Produktion (Limits): tr={bp.get('trades')} net={bp.get('net_pct',0):.1f}% "
          f"maxDD={bp.get('max_dd_pct',0):.1f}% killed={bp.get('killed')}")
    io = v["is_oos"]
    ism, oos = io["in_sample"], io["out_of_sample"]
    print(f"  IS/OOS chosen={io['chosen']}: IS pf={ism.get('profit_factor',0):.2f} "
          f"net={ism.get('net_profit',0):.0f} | OOS pf={oos.get('profit_factor',0):.2f} "
          f"net={oos.get('net_profit',0):.0f} wr={oos.get('win_rate',0):.1f}%")
    wf = v["walk_forward"]
    print(f"  Walk-Forward: {wf['positive_walks']}/{wf['n_walks']} Fenster positiv, "
          f"OOS-net gesamt={wf['oos_net_total']:.0f}")
    print("  Sensitivität:")
    for p, s in v["sensitivity"].items():
        g = " ".join(f"{x['value']}:pf{x['pf']:.2f}" for x in s["grid"])
        print(f"    {p:16s} allpos={str(s['all_positive']):5s} flips={s['sign_flips']} | {g}")
    mc = v["monte_carlo"]
    if mc.get("runs"):
        print(f"  MonteCarlo(1000): DD p50={mc['dd_p50']:.1f}% p95={mc['dd_p95']:.1f}% "
              f"worst={mc['dd_worst']:.1f}% | finalP05={mc['final_p05']:.1f}% "
              f"P50={mc['final_p50']:.1f}%")
    print("  Kosten-Stress:", " ".join(f"{x['cost_mult']}x:pf{x['pf']:.2f}/net{x['net']:.0f}"
                                        for x in v["cost_stress"]))
    print("  Regime:", {k: f"n{d.get('trades')}/pf{d.get('profit_factor',0):.2f}"
                        for k, d in v["regimes"].items() if d.get('trades')})
    ss = v["sample_size"]
    print(f"  Stichprobe: {ss['note']} | Wilson-95%-WR: "
          f"[{(ss['wilson_95'][0] or 0):.1f}, {(ss['wilson_95'][1] or 0):.1f}]%")
    pc = v["prop_compliance"]["with_limits"]
    pcn = v["prop_compliance"]["without_limits"]
    print(f"  Prop (mit Limits): worstDay={pc['worst_daily_dd']:.2f}% "
          f"maxDD={pc['max_trailing_dd']:.2f}% kill={pc['kill_switch_fired']} "
          f"dayBreaches={pc['daily_breaches']}")
    print(f"       (ohne Limits):  maxDD={pcn['max_trailing_dd']:.2f}% "
          f"dayBreaches={pcn['daily_breaches']}")
