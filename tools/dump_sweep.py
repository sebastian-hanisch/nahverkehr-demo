"""Aggregiert sweep_raw.json (Rohdaten aus tools/sweep.py) zu sweep_data.json (alle Zahlen der Stabilitäts-Messreihe stammen von hier) und druckt
eine Kurzübersicht. Bootstrap über Instanzen (gepaart, feste Zufallszahlen) für Anteile und Interpolationen. numpy nötig (kommt mit pandas).

Aufruf (im Projektordner):  python tools/dump_sweep.py [tools/sweep_raw.json [tools/sweep_data.json]]; danach tools/build_results.py.
Übernommen aus messreihe_stabilitaet/dump_sweep.py, unverändert bis auf die Standardpfade."""

from __future__ import annotations

import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))

FRACS = (0.25, 0.5, 0.75)
CC_A = (0.0, 0.5, 1.0, 2.0, 3.0, 5.0, 8.0, 12.0, 20.0)      # Kosten je Aenderung im Mass (a)
CC_B = (0.0, 0.5, 1.0, 2.0, 3.0, 5.0)                        # Mass (b): je Kundenankuendigung
CC_C = (0.0, 2.0, 5.0, 10.0, 20.0, 40.0)                     # Mass (c): je Neuplanungsereignis mit Aenderung
N_BOOT = 300


def se(x):
    x = np.asarray(x, float)
    return float(x.std(ddof=1) / np.sqrt(len(x))) if len(x) > 1 else 0.0


def families(names):
    fam = {"F": [], "P": [], "T": [], "H": []}
    for i, n in enumerate(names):
        if n[0] in fam and n not in ("S0", "R"):
            fam[n[0]].append(i)
    return {f: ids for f, ids in fam.items() if ids}


def interp_gain(xs, ys, x_star):
    order = np.argsort(xs, kind="stable")
    x, y = np.asarray(xs)[order], np.asarray(ys)[order]
    return float(np.interp(x_star, x, y))


def step_frontier(xs, ys, x_star):
    """Bester erreichbarer Gewinn mit hoechstens x_star Aenderungen (nur vorhandene Politiken)."""
    ok = [y for x, y in zip(xs, ys) if x <= x_star + 1e-12]
    return float(max(ok)) if ok else 0.0


def cell_stats(names, PT, A, B, C, idx=None):
    """Kennzahlen aus Mittelwerten ueber die Instanzen idx (fuer Punktschaetzung und Bootstrap)."""
    if idx is not None:
        PT, A, B, C = PT[idx], A[idx], B[idx], C[idx]
    pt, a, b, c = PT.mean(0), A.mean(0), B.mean(0), C.mean(0)
    i0, iR = names.index("S0"), names.index("R")
    g = pt - pt[i0]
    out = dict(gain_R=float(g[iR]), a_R=float(a[iR]), b_R=float(b[iR]), c_R=float(c[iR]))
    out["gain_per_change"] = float(g[iR] / a[iR]) if a[iR] > 1e-9 else None
    fam = families(names)
    for meas, x in (("a", a), ("b", b), ("c", c)):
        x = x - x[i0]                       # zusaetzliche Aenderungen gegenueber S0 (fuer (a) ist S0 exakt 0)
        xR = x[iR]
        for frac in FRACS:
            xs = frac * xR
            # gemeinsame (Pareto-)Stufenfront ueber alle Politiken
            allx = list(x)
            ally = list(g)
            yfront = step_frontier(allx, ally, xs)
            out[f"share_front_{meas}_{int(frac * 100)}"] = float(yfront / g[iR]) if g[iR] > 1e-9 else None
            for f, ids in fam.items():
                px = [0.0] + [float(x[i]) for i in ids] + [float(xR)]
                py = [0.0] + [float(g[i]) for i in ids] + [float(g[iR])]
                yi = interp_gain(px, py, xs)
                tag = "" if meas == "a" else f"_{meas}"
                out[f"share_{f}{tag}_{int(frac * 100)}"] = float(yi / g[iR]) if g[iR] > 1e-9 else None
                out[f"gain_{f}{tag}_{int(frac * 100)}"] = yi
    return out


def main(raw_path=os.path.join(HERE, "sweep_raw.json"), out_path=os.path.join(HERE, "sweep_data.json")):
    raw = json.load(open(raw_path, encoding="utf-8"))
    rng = np.random.default_rng(12345)
    cells = []
    cfg_key = {}
    for key, c in raw["cells"].items():
        rows = c["rows"]
        names = list(rows[0]["res"].keys())
        n = len(rows)
        PT = np.array([[r["res"][p]["profit_total"] for p in names] for r in rows], float)
        PC = np.array([[r["res"][p]["profit_ora_conv"] for p in names] for r in rows], float)
        A = np.array([[r["res"][p]["a"] for p in names] for r in rows], float)
        B = np.array([[r["res"][p]["b"] for p in names] for r in rows], float)
        C = np.array([[r["res"][p]["c"] for p in names] for r in rows], float)
        F_ = {m: np.array([[r["res"][p][m] for p in names] for r in rows], float)
              for m in ("n_fail", "n_acc", "drive", "n_cancel", "n_change", "n_ign", "ls_saved", "profit")}
        i0, iR = names.index("S0"), names.index("R")
        d = dict(cfg=c["cfg"], groups=c["groups"], n=n, names=names)
        d["n_events"] = float(np.mean([r["n_events"] for r in rows]))
        d["n_arrivals"] = float(np.mean([r["n_arrivals"] for r in rows]))
        d["n_orders"] = float(np.mean([r["n_orders"] for r in rows]))
        d["plan_util"] = float(np.mean([r["plan_util"] for r in rows]))
        d["eff_change"] = float(F_["n_change"][:, i0].mean())
        d["eff_cancel"] = float(F_["n_cancel"][:, i0].mean())
        d["ign"] = float(F_["n_ign"][:, i0].mean())
        pol = {}
        for j, p in enumerate(names):
            gg = PT[:, j] - PT[:, i0]
            pol[p] = dict(pt=float(PT[:, j].mean()), pt_se=se(PT[:, j]), gain=float(gg.mean()), gain_se=se(gg),
                          gain_q=[float(v) for v in np.percentile(gg, [25, 50, 75])],
                          a=float(A[:, j].mean()), a_se=se(A[:, j]), b=float(B[:, j].mean()), c=float(C[:, j].mean()),
                          fail=float(F_["n_fail"][:, j].mean()), acc=float(F_["n_acc"][:, j].mean()),
                          drive=float(F_["drive"][:, j].mean()), ls_saved=float(F_["ls_saved"][:, j].mean()),
                          wins=int((gg > 0).sum()), losses=int((gg < 0).sum()))
        d["pol"] = pol
        pt_stats = cell_stats(names, PT, A, B, C)
        boots = []
        for _ in range(N_BOOT):
            idx = rng.integers(0, n, n)
            boots.append(cell_stats(names, PT, A, B, C, idx))
        ci = {}
        for k, v in pt_stats.items():
            vals = [bt[k] for bt in boots if bt[k] is not None]
            ci[k] = [float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))] if len(vals) > 20 else None
        d["stats"] = pt_stats
        d["stats_ci"] = ci
        # F gegen P bei gleicher Aenderungszahl (Interpolation), Bootstrap
        diff = {}
        for frac in (25, 50):
            for meas in ("", "_b", "_c"):
                pt_v = pt_stats[f"gain_F{meas}_{frac}"] - pt_stats[f"gain_P{meas}_{frac}"]
                bv = [bt[f"gain_F{meas}_{frac}"] - bt[f"gain_P{meas}_{frac}"] for bt in boots]
                diff[f"F_minus_P{meas}_{frac}"] = dict(mean=pt_v, ci=[float(np.percentile(bv, 2.5)), float(np.percentile(bv, 97.5))])
            if "gain_H_25" in pt_stats:
                pt_v = pt_stats[f"gain_H_{frac}"] - pt_stats[f"gain_P_{frac}"]
                bv = [bt[f"gain_H_{frac}"] - bt[f"gain_P_{frac}"] for bt in boots]
                diff[f"H_minus_P_{frac}"] = dict(mean=pt_v, ci=[float(np.percentile(bv, 2.5)), float(np.percentile(bv, 97.5))])
        d["F_vs_P"] = diff
        # Netto-Gewinn mit Aenderungskosten
        net = {}
        for meas, X, ccs in (("a", A, CC_A), ("b", B, CC_B), ("c", C, CC_C)):
            xm = X.mean(0)
            rows_net = []
            for cc in ccs:
                nv = PT.mean(0) - cc * xm
                jb = int(np.argmax(nv))
                rows_net.append(dict(cc=cc, best=names[jb], net_best=float(nv[jb]), net_over_S0=float(nv[jb] - nv[i0]),
                                     net_over_R=float(nv[jb] - nv[iR]), net_R_over_S0=float(nv[iR] - nv[i0])))
            net[meas] = rows_net
        d["net"] = net
        # gepaarte Kopfvergleiche (Gewinn- und Aenderungsdifferenz, Mittel +- SE ueber Instanzen)
        head = {}
        for x, y in (("P0.25", "R"), ("P0.5", "R"), ("P1", "R"), ("P2", "R"), ("P3", "R"), ("P3", "F2"), ("P3", "F3"), ("P2", "F3"), ("P1", "F1"),
                     ("P0.5", "F1"), ("P0.5", "T30"), ("P1", "T60"), ("P2", "T120"), ("F1", "T30"), ("R", "S0")):
            if x in names and y in names:
                jx, jy = names.index(x), names.index(y)
                head[f"{x}-{y}"] = dict(gain=[float((PT[:, jx] - PT[:, jy]).mean()), se(PT[:, jx] - PT[:, jy])],
                                        a=[float((A[:, jx] - A[:, jy]).mean()), se(A[:, jx] - A[:, jy])])
        d["head"] = head
        # Verteilung des R-Gewinns (schief): Anteil Instanzen mit Gewinn, Quantile
        gR = PT[:, iR] - PT[:, i0]
        d["R_dist"] = dict(q=[float(v) for v in np.percentile(gR, [10, 25, 50, 75, 90])], share_pos=float((gR > 0).mean()), share_zero=float((gR == 0).mean()),
                           top10_share=float(np.sort(gR)[::-1][:max(1, n // 10)].sum() / gR.sum()) if gR.sum() > 0 else None)
        # Orakel
        ora_rows = [k for k, r in enumerate(rows) if "oracle" in r]
        if ora_rows:
            o = np.array([rows[k]["oracle"] for k in ora_rows], float)
            pcs = PC[ora_rows]
            best = pcs.max(1)
            d["oracle"] = dict(n=len(ora_rows), ge_all=bool(np.all(o[:, None] >= pcs)), warm_ok=all(rows[k]["oracle_warm_ok"] for k in ora_rows),
                               oracle_mean=float(o.mean()), best_mean=float(best.mean()), s0_mean=float(pcs[:, i0].mean()), r_mean=float(pcs[:, iR].mean()),
                               gap_best=[float((o - best).mean()), se(o - best)], gap_s0=[float((o - pcs[:, i0]).mean()), se(o - pcs[:, i0])],
                               gap_r=[float((o - pcs[:, iR]).mean()), se(o - pcs[:, iR])],
                               share_s0=float((pcs[:, i0].mean() - PC[ora_rows][:, i0].mean()) if False else 0.0))
        cells.append(d)
        cfg_key[key] = d
    # Kosten der Ereignisse (gepaart mit der Kontrollzelle ohne Ereignisse, gleiche uebrige Konfiguration)
    def norm(cfg):
        return tuple((k, v) for k, v in sorted(cfg.items()) if k not in ("p_chg", "p_cancel", "w_time", "w_addr", "w_qty"))
    ctrl = {}
    for key, c in raw["cells"].items():
        cf = c["cfg"]
        if cf["p_chg"] == 0 and cf["p_cancel"] == 0:
            ctrl[norm(cf)] = c
    for d in cells:
        cf = d["cfg"]
        cc = ctrl.get(norm(cf))
        if cc is None or (cf["p_chg"] == 0 and cf["p_cancel"] == 0):
            continue
        rows = raw["cells"][[k for k, v in cfg_key.items() if v is d][0]]["rows"]
        crow = cc["rows"]
        names = d["names"]
        ev = {}
        for p in ("S0", "R"):
            loss = np.array([cr["res"][p]["profit_total"] - r["res"][p]["profit_total"] for r, cr in zip(rows, crow)], float)
            ev[p] = dict(mean=float(loss.mean()), se=se(loss))
        gR_ev = np.array([r["res"]["R"]["profit_total"] - r["res"]["S0"]["profit_total"] for r in rows], float)
        gR_ct = np.array([cr["res"]["R"]["profit_total"] - cr["res"]["S0"]["profit_total"] for cr in crow], float)
        ev["gainR_event"] = dict(mean=float(gR_ev.mean()), se=se(gR_ev))
        ev["gainR_control"] = dict(mean=float(gR_ct.mean()), se=se(gR_ct))
        ev["gainR_extra"] = dict(mean=float((gR_ev - gR_ct).mean()), se=se(gR_ev - gR_ct))
        ev["fail_S0"] = float(np.mean([r["res"]["S0"]["n_fail"] for r in rows]))
        ev["fail_R"] = float(np.mean([r["res"]["R"]["n_fail"] for r in rows]))
        d["event_cost"] = ev
    data = dict(n_eval=raw.get("n_eval"), n_ora=raw.get("n_ora"), t_total=raw.get("t_total"), cells=cells)
    json.dump(data, open(out_path, "w", encoding="utf-8"), indent=1, sort_keys=True)
    return data


def lab(c):
    return " / ".join(f"{g}:{n}" for g, n in c["groups"])


def show(data):
    for c in data["cells"]:
        s, ci, p = c["stats"], c["stats_ci"], c["pol"]
        print(f"\n== {lab(c)}  n={c['n']} Ereignisse {c['n_events']:.1f} (wirksam {c['eff_change'] + c['eff_cancel']:.1f}, ignoriert {c['ign']:.1f}) "
              f"Auslastung {c['plan_util']:.2f}  S0 {p['S0']['pt']:.0f}  Ausfaelle S0 {p['S0']['fail']:.2f} R {p['R']['fail']:.2f}")
        print(f"   R - S0 = {s['gain_R']:+.1f} (SE {p['R']['gain_se']:.1f}), a_R = {s['a_R']:.1f}, b_R = {s['b_R']:.1f}, c_R = {s['c_R']:.1f}, Gewinn je Aenderung {s['gain_per_change'] if s['gain_per_change'] is None else round(s['gain_per_change'], 2)}")
        for f in ("front_a", "F", "P", "T"):
            key = f"share_{f}_" if f != "front_a" else "share_front_a_"
            print(f"   Anteil des R-Gewinns bei 25/50/75 % der R-Aenderungen ({f}): " + " / ".join(
                "n.a." if s.get(f'{key}{q}') is None else f"{100 * s[f'{key}{q}']:.0f} %" for q in (25, 50, 75)))
        print("   F - P bei gleicher Aenderungszahl 25 %: {:+.1f} [{:+.1f}, {:+.1f}], 50 %: {:+.1f} [{:+.1f}, {:+.1f}]".format(
            c["F_vs_P"]["F_minus_P_25"]["mean"], *c["F_vs_P"]["F_minus_P_25"]["ci"], c["F_vs_P"]["F_minus_P_50"]["mean"], *c["F_vs_P"]["F_minus_P_50"]["ci"]))
        if "event_cost" in c:
            e = c["event_cost"]
            print(f"   Kosten der Ereignisse: S0 {e['S0']['mean']:.1f} +- {e['S0']['se']:.1f}, R {e['R']['mean']:.1f} +- {e['R']['se']:.1f}; "
                  f"R-Gewinn mit Ereignissen {e['gainR_event']['mean']:.1f}, ohne {e['gainR_control']['mean']:.1f}, zusaetzlich {e['gainR_extra']['mean']:.1f} +- {e['gainR_extra']['se']:.1f}")
        if "oracle" in c:
            o = c["oracle"]
            print(f"   Orakel (n={o['n']}): {o['oracle_mean']:.0f}, S0 {o['s0_mean']:.0f}, R {o['r_mean']:.0f}, bester Online {o['best_mean']:.0f}; Luecke zu R {o['gap_r'][0]:.0f} +- {o['gap_r'][1]:.0f}; "
                  f"Schranke gilt: {o['ge_all']}")


if __name__ == "__main__":
    args = sys.argv[1:]
    d = main(*(args[:2]))
    show(d)
