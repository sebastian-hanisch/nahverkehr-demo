"""Reproduktion der Stabilitäts-Messreihe (28 Zellen x 200 Instanzen, Politiken S0/R/F/P/T; mit --h der Zusatzlauf zeitbasierter Horizont H).
Aufruf (im Projektordner):  python tools/sweep.py [--out tools/sweep_raw.json] [--cache DIR] [schnell] [--h]

Etwa 15 Minuten für den Hauptlauf auf 14 Kernen (die Morgenpläne mit OR-Tools sind der teure Teil, sie werden in --cache zwischengespeichert;
etwa 35 Minuten für alle Läufe samt Zusatzlauf, Wiederholung und Orakel) - NICHT in der CI. Mehrprozess, deterministisch je Seed. Rohdaten je
Instanz und Politik in sweep_raw.json; Auswertung: tools/dump_sweep.py, danach tools/build_results.py -> data/nv_results.json.

Je Zelle: N_EVAL Instanzen (Seeds 0..N_EVAL-1), alle Politiken auf denselben Instanzen und Ereignisströmen (gepaart). Es gibt
keine kalibrierten Parameter (die Politiken haben feste Reglerstufen, die Kurve Gewinn gegen Änderungen entsteht aus dem
ganzen Raster), also auch keine Kalibrier-/Auswertungs-Trennung nötig; das Orakel läuft nur auf den ersten N_ORA Seeds.

Übernommen aus messreihe_stabilitaet/sweep.py; geändert sind nur die Importe (nv_model, nv_sim, nv_oracle), die Ablage der Zwischenspeicher
und Rohdaten im Ordner tools/ und die Umgebungsvariable NV_MORNING_CACHE (die Messreihe hieß sie anders)."""

from __future__ import annotations

import json
import multiprocessing as mp
import os
import sys
import time
from dataclasses import asdict, replace

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
if "--cache" in sys.argv:
    os.environ["NV_MORNING_CACHE"] = sys.argv[sys.argv.index("--cache") + 1]
else:
    os.environ.setdefault("NV_MORNING_CACHE", os.path.join(HERE, "cache_morning"))

from nv_model import Cfg, make_instance, vend  # noqa: E402
from nv_oracle import oracle_ev  # noqa: E402
from nv_sim import run_events  # noqa: E402

N_EVAL = 200
N_ORA = 10
ORACLE_SOL_LIMIT = 800
TIME_SAFETY = 900

H_MODE = "--h" in sys.argv          # Zusatzlauf: zeitbasierter Einfrierhorizont H (Minuten) statt Stopp-Anzahl F_k

# Politik-Raster: Name -> Argumente von run_events
POLICY_SPECS: dict[str, dict] = {"S0": dict(kind="S0"), "R": dict(kind="R")}
if H_MODE:
    POLICY_SPECS["F3"] = dict(kind="F", k=3)
    POLICY_SPECS["P0.5"] = dict(kind="P", lam=0.5)
    POLICY_SPECS["P2"] = dict(kind="P", lam=2.0)
    for _h in (15, 30, 60, 90, 120, 180, 240, 300):
        POLICY_SPECS[f"H{_h}"] = dict(kind="H", H_min=_h)
else:
    for _k in (1, 2, 3, 4, 6, 8, 12):
        POLICY_SPECS[f"F{_k}"] = dict(kind="F", k=_k)
    for _l in (0.25, 0.5, 1.0, 1.5, 2.0, 3.0, 5.0, 8.0):
        POLICY_SPECS[f"P{_l:g}"] = dict(kind="P", lam=_l)
    for _t in (30, 60, 120, 240):
        POLICY_SPECS[f"T{_t}"] = dict(kind="T", T_per=_t)

BASE = Cfg(K=3, n_m=40, lam=6.0, p_chg=0.25, p_cancel=0.08)

METRICS = ("profit_total", "profit", "drive", "a", "b", "c", "n_fail", "n_acc", "n_cancel", "n_change", "n_ign", "ls_saved",
           "n_morning_served", "n_served_sd")


def cell_list():
    """(Gruppe, Name, Cfg, mit_orakel). Doppelte Cfgs werden nur einmal gerechnet (Gruppen werden zusammengefuehrt)."""
    b = BASE
    cells = [("basis", "basis", b, True)]
    for pc, pk in ((0.0, 0.0), (0.1, 0.03), (0.5, 0.16), (0.8, 0.2)):
        cells.append(("ereignisrate", f"chg={pc:g},cancel={pk:g}", replace(b, p_chg=pc, p_cancel=pk), pc in (0.0, 0.5)))
    for share in (0.0, 0.5, 1.0):
        tot = 0.33
        cells.append(("stornoanteil", f"storno={share:g}", replace(b, p_chg=round(tot * (1 - share), 4), p_cancel=round(tot * share, 4)), share == 1.0))
    cells.append(("art", "nur Zeitfenster", replace(b, w_time=1.0, w_addr=0.0, w_qty=0.0), True))
    cells.append(("art", "nur Adresse", replace(b, w_time=0.0, w_addr=1.0, w_qty=0.0), True))
    cells.append(("kapazitaet", "Q=34 ohne Mengenaenderung (Kontrolle)", replace(b, Q=34), False))
    cells.append(("art", "nur Menge (Q=34)", replace(b, Q=34, w_time=0.0, w_addr=0.0, w_qty=1.0), False))
    cells.append(("art", "alle drei (Q=34)", replace(b, Q=34, w_time=1.0, w_addr=1.0, w_qty=1.0), False))
    cells.append(("kapazitaet", "Q=34 ohne Ereignisse (Kontrolle)", replace(b, Q=34, p_chg=0.0, p_cancel=0.0), False))
    for lam in (0.0, 2.0, 12.0):
        cells.append(("same-day-rate", f"lam={lam:g}", replace(b, lam=lam), lam == 12.0))
    for n in (16, 28, 52):
        cells.append(("auslastung", f"n_m={n}", replace(b, n_m=n), n == 52))
    for dl in (60, 240):
        cells.append(("frist", f"delta={dl}", replace(b, delta=dl), dl == 60))
    for cd in (15, 60):
        cells.append(("verschiebung", f"chg_delta={cd}", replace(b, chg_delta=cd), False))
    for rad in (2.0, 12.0):
        cells.append(("adressradius", f"radius={rad:g}", replace(b, addr_radius=rad), False))
    cells.append(("flotte", "K=2 (n_m=27, lam=4)", replace(b, K=2, n_m=27, lam=4.0), False))
    cells.append(("flotte", "K=4 (n_m=53, lam=8)", replace(b, K=4, n_m=53, lam=8.0), False))
    if H_MODE:
        keep = {"basis:basis", "ereignisrate:chg=0,cancel=0", "ereignisrate:chg=0.5,cancel=0.16", "same-day-rate:lam=12", "auslastung:n_m=52",
                "frist:delta=60", "stornoanteil:storno=1"}
        cells = [(g, n, c, False) for g, n, c, o in cells if f"{g}:{n}" in keep]
    seen, out = {}, []
    for g, name, cfg, ora in cells:
        key = repr(asdict(cfg))
        if key in seen:
            seen[key]["groups"].append((g, name))
            seen[key]["ora"] = seen[key]["ora"] or ora
            continue
        rec = dict(groups=[(g, name)], cfg=cfg, ora=ora)
        seen[key] = rec
        out.append(rec)
    return out


def eval_task(args):
    cfgd, seed, with_oracle = args
    cfg = Cfg(**cfgd)
    inst = make_instance(cfg, seed)
    res = {}
    best, best_profit = None, None
    for name, spec in POLICY_SPECS.items():
        r = run_events(inst, **spec)
        res[name] = {k: r[k] for k in METRICS}
        n_sd_fail = sum(1 for o in r["failed_orders"] if inst.is_sd[o])
        adj = r["profit_total"] + cfg.pen * n_sd_fail          # Orakel-Konvention (ohne Ausfallstrafe fuer nie angenommene Same-Day-Auftraege)
        res[name]["profit_ora_conv"] = adj
        if best_profit is None or adj > best_profit:
            best_profit, best = adj, r["fleet"]
    out = dict(seed=seed, res=res, n_events=len(inst.events), n_arrivals=len(inst.arrivals), n_orders=inst.n_orders_base,
               n_morning=inst.n_morning,
               plan_util=sum(vend(inst, rt, f) for rt, f in zip(inst.plan.routes, inst.plan.F)) / (cfg.K * cfg.H))
    if with_oracle:
        o = oracle_ev(inst, warm=best, time_limit=TIME_SAFETY, sol_limit=ORACLE_SOL_LIMIT)
        out["oracle"] = o["profit"]
        out["oracle_warm_ok"] = o["warm_ok"]
        out["best_online_ora_conv"] = best_profit
    return out


def run_cell(pool, cfg: Cfg, n_eval: int, n_ora: int) -> dict:
    t0 = time.time()
    rows = pool.map(eval_task, [(asdict(cfg), s, s < n_ora) for s in range(n_eval)], chunksize=1)
    return dict(cfg=asdict(cfg), rows=rows, t_eval=time.time() - t0)


def quick_print(label: str, cell: dict) -> None:
    rows = cell["rows"]
    n = len(rows)

    def mean(f):
        return sum(f(r) for r in rows) / n

    s0 = mean(lambda r: r["res"]["S0"]["profit_total"])
    line = f"== {label}  n={n} Ereignisse {mean(lambda r: r['n_events']):.1f}  S0 {s0:.0f}  "
    for p in ("R", "F3", "P2", "T60", "H60"):
        if p not in cell["rows"][0]["res"]:
            continue
        line += f"{p}: {mean(lambda r: r['res'][p]['profit_total']) - s0:+.0f} (a={mean(lambda r: r['res'][p]['a']):.1f})  "
    print(line + f"[{cell['t_eval']:.0f}s]", flush=True)


def main(out_path: str, n_eval: int, n_ora: int) -> None:
    raw = json.load(open(out_path, encoding="utf-8")) if os.path.exists(out_path) else {"cells": {}}
    t_all = time.time()
    with mp.Pool(min(14, mp.cpu_count())) as pool:
        for rec in cell_list():
            key = repr(asdict(rec["cfg"]))
            if key in raw["cells"]:
                continue
            cell = run_cell(pool, rec["cfg"], n_eval, n_ora if rec["ora"] else 0)
            cell["groups"] = rec["groups"]
            raw["cells"][key] = cell
            quick_print(" / ".join(f"{g}:{n}" for g, n in rec["groups"]), cell)
            json.dump(raw, open(out_path, "w", encoding="utf-8"))
    raw["t_total"] = raw.get("t_total", 0) + time.time() - t_all
    raw["n_eval"], raw["n_ora"] = n_eval, n_ora
    json.dump(raw, open(out_path, "w", encoding="utf-8"))
    print(f"Gesamtlaufzeit dieses Laufs {time.time() - t_all:.0f} s", flush=True)


if __name__ == "__main__":
    out = os.path.join(HERE, "sweep_raw.json")
    if "--out" in sys.argv:
        out = sys.argv[sys.argv.index("--out") + 1]
    fast = "schnell" in sys.argv
    main(out, 30 if fast else N_EVAL, 2 if fast else N_ORA)
