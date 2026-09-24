"""Aggregiert sweep_sameday_raw.json (Rohergebnisse aus tools/sweep_sameday.py) zu sweep_sameday_data.json und druckt eine Kurzübersicht.
Alle Zahlen der Same-Day-Messreihe stammen aus dieser Datei. Nur Standardbibliothek.

Aufruf (im Projektordner):  python tools/dump_sweep_sameday.py [roh.json [daten.json]]; danach tools/build_results.py.
Übernommen aus messreihe_sameday/dump_sweep.py, unverändert bis auf die Standardpfade."""

from __future__ import annotations

import json
import os
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

POL = ("P0", "P1", "P1p", "P2v", "P2m", "P2", "P2c", "P1L", "P1pL", "P2L", "P4", "P4L")
PAIRS = (("P1p", "P1"), ("P2", "P1p"), ("P2v", "P1p"), ("P2m", "P1p"), ("P2", "P2c"), ("P2", "P2v"), ("P2", "P2m"),
         ("P1L", "P1"), ("P1pL", "P1p"), ("P2L", "P2"), ("P2L", "P1L"), ("P2L", "P1pL"), ("P4", "P2"), ("P4", "P1p"), ("P4L", "P2L"),
         ("P4L", "P1L"), ("P2L", "P1p"))


def ms(xs):
    xs = list(xs)
    if not xs:
        return dict(mean=None, se=None)
    return dict(mean=st.fmean(xs), se=(st.stdev(xs) / len(xs) ** 0.5) if len(xs) > 1 else 0.0)


def q(xs):
    xs = sorted(xs)
    if len(xs) < 4:
        return [xs[0], st.median(xs), xs[-1]]
    a = st.quantiles(xs, n=4)
    return [a[0], a[1], a[2]]


def gain(r, p):
    return r["res"][p]["profit"] - r["res"]["P0"]["profit"]


def agg_rows(rows, with_oracle=True):
    out = dict(n=len(rows))
    out["n_morning"] = st.fmean(r["n_morning"] for r in rows)
    out["n_sd"] = st.fmean(r["n_sd"] for r in rows)
    out["plan_util"] = st.fmean(r["plan_util"] for r in rows)
    out["n_feas_P1"] = st.fmean(r["res"]["P1"]["n_feas"] for r in rows)
    pol = {}
    for p in POL:
        g = [gain(r, p) for r in rows]
        d = dict(**ms(g), q=q(g), acc=st.fmean(r["res"][p]["n_acc"] for r in rows),
                 drive=st.fmean(r["res"][p]["drive"] for r in rows), rev=st.fmean(r["res"][p]["rev"] for r in rows))
        pol[p] = d
    out["pol"] = pol
    pr = {}
    for a, b in PAIRS:
        d = [r["res"][a]["profit"] - r["res"][b]["profit"] for r in rows]
        pr[f"{a}-{b}"] = dict(**ms(d), wins=sum(x > 0 for x in d), losses=sum(x < 0 for x in d), ties=sum(x == 0 for x in d))
    out["pairs"] = pr
    ora = [r for r in rows if "oracle" in r]
    if ora and with_oracle:
        o = dict(n=len(ora))
        og = [r["oracle"] - r["res"]["P0"]["profit"] for r in ora]
        o["ORA"] = dict(**ms(og), q=q(og))
        o["served"] = st.fmean(r["oracle_served"] for r in ora)
        o["best_online_gain"] = ms([r["best_online"] - r["res"]["P0"]["profit"] for r in ora])
        o["gap_best_online"] = ms([r["oracle"] - r["best_online"] for r in ora])
        o["route_opt_P2L"] = ms([r["route_opt_P2L"] - r["res"]["P0"]["profit"] for r in ora])
        o["pol_on_ora"] = {p: st.fmean(gain(r, p) for r in ora) for p in POL}
        o["acc_on_ora"] = {p: st.fmean(r["res"][p]["n_acc"] for r in ora) for p in POL}
        o["gap_by_policy"] = {p: ms([r["oracle"] - r["res"][p]["profit"] for r in ora]) for p in ("P1", "P1p", "P2", "P1L", "P2L", "P4L")}
        o["sd_arrivals"] = st.fmean(r["n_sd"] for r in ora)
        o["oracle_ge_all"] = all(r["oracle"] >= max(v["profit"] for v in r["res"].values()) for r in ora)
        o["warm_ok"] = all(r["oracle_warm_ok"] for r in ora)
        out["oracle"] = o
    return out


def main(raw_path=os.path.join(HERE, "sweep_sameday_raw.json"), out_path=os.path.join(HERE, "sweep_sameday_data.json")):
    raw = json.load(open(raw_path, encoding="utf-8"))
    cells = []
    for key, c in raw["cells"].items():
        a = agg_rows(c["rows"])
        a.update(cfg=c["cfg"], par=c["par"], groups=c["groups"], n_ora=c["n_ora"],
                 cal_mean={k: v for k, v in (c.get("cal_mean") or {}).items() if k.startswith(("P2@", "P2L@", "P2m@", "P2v@", "P2c@"))})
        cells.append(a)
    cross = []
    for key, c in raw.get("cross", {}).items():
        a = agg_rows(c["rows"], with_oracle=False)
        a.update(cfg=c["cfg"], par=c["par"], groups=c["groups"])
        cross.append(a)
    data = dict(n_eval=cells[0]["n"] if cells else 0, cells=cells, cross=cross)
    json.dump(data, open(out_path, "w", encoding="utf-8"), indent=1, sort_keys=True)
    return data


def show(data):
    for c in data["cells"]:
        lab = " / ".join(f"{g}:{n}" for g, n in c["groups"])
        p = c["pol"]
        pa = c["pairs"]
        print(f"\n== {lab}  Morgen {c['n_morning']:.1f} Auslastung {c['plan_util']:.2f} SD {c['n_sd']:.1f} machbar {c['n_feas_P1']:.1f}  par {c['par']}")
        print("  Gewinn ggue. P0 (Mittel+-SE | Median): " + "  ".join(f"{k} {p[k]['mean']:.0f}+-{p[k]['se']:.0f}|{p[k]['q'][1]:.0f}" for k in POL if k != "P0"))
        print("  gepaart: " + "  ".join(f"{k} {v['mean']:+.0f}+-{v['se']:.0f}" for k, v in pa.items()))
        if "oracle" in c:
            o = c["oracle"]
            print(f"  Orakel (n={o['n']}): {o['ORA']['mean']:.0f}+-{o['ORA']['se']:.0f}, bester Online {o['best_online_gain']['mean']:.0f}, Luecke {o['gap_best_online']['mean']:.0f}+-{o['gap_best_online']['se']:.0f}, "
                  f"Routenopt. (P2L-Menge) {o['route_opt_P2L']['mean']:.0f}, Orakel bedient {o['served']:.1f} von {o['sd_arrivals']:.1f}, obere Schranke ok {o['oracle_ge_all']}")


if __name__ == "__main__":
    d = main(*(sys.argv[1:3]))
    show(d)
