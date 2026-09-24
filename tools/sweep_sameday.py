"""Reproduktion der Same-Day-Messreihe (Annahmeregeln, 34 Zellen x 60 Instanzen, Kalibrierung des Schwellenparameters µ, Hindsight-Orakel).
Aufruf (im Projektordner):  python tools/sweep_sameday.py [--out tools/sweep_sameday_raw.json] [schnell]  (Mehrprozess, deterministisch je Seed).
Etwa 70 Minuten auf 16 Prozessen, NICHT in der CI; Auswertung: tools/dump_sweep_sameday.py, danach tools/build_results.py.
Übernommen aus messreihe_sameday/sweep.py; geändert sind nur die Importe (nv_model, nv_sim) und die Ablage im Ordner tools/.

Ablauf je Zelle (Cfg):
  1. KALIBRIERUNG auf getrennten Seeds (CAL_SEEDS, 100000+): beste Parameter je Politik (mu, rho) aus einem Gitter.
  2. AUSWERTUNG auf den Seeds 0..N-1 (nie zur Kalibrierung verwendet): alle Politiken, gepaart, plus Hindsight-Orakel.
"""

from __future__ import annotations

import multiprocessing as mp
import os
import statistics as st
import sys
import time
from dataclasses import asdict, replace

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ.setdefault("NV_MORNING_CACHE", os.path.join(HERE, "cache_morning"))

from nv_model import Cfg, make_instance, oracle, vend  # noqa: E402
from nv_sim import simulate, simulate_rollout  # noqa: E402

N_EVAL = 60
N_CAL = 40
CAL_BASE = 100_000
ORACLE_SOL_LIMIT = 1000
ROUTE_SOL_LIMIT = 400
N_ORA = 16
TIME_SAFETY = 600          # Sekunden; nur Sicherheitsnetz, die Laeufe enden ueber solution_limit (deterministisch)
MU_GRID = (0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 9.0, 13.0, 20.0)
RHO_V_GRID = (0.0, 20.0, 40.0, 60.0, 80.0, 100.0, 130.0)
RHO_M_GRID = (0.0, 5.0, 10.0, 15.0, 20.0, 30.0, 40.0, 60.0)

POLICIES = ("P0", "P1", "P1p", "P2v", "P2m", "P2", "P2c", "P1L", "P1pL", "P2L", "P4", "P4L")
ROLLOUT_S = 24


def run_policy(inst, name, par):
    if name == "P0":
        return simulate(inst, "P0")
    if name == "P1":
        return simulate(inst, "P1")
    if name == "P1p":
        return simulate(inst, "P1p")
    if name == "P2v":
        return simulate(inst, "P2v", rho=par["rho_v"])
    if name == "P2m":
        return simulate(inst, "P2m", rho=par["rho_m"])
    if name == "P2":
        return simulate(inst, "P2", mu=par["mu"])
    if name == "P2c":
        return simulate(inst, "P2c", mu=par["mu_c"])
    if name == "P4":
        return simulate_rollout(inst, S=ROLLOUT_S)
    if name == "P4L":
        return simulate_rollout(inst, S=ROLLOUT_S, ls=True)
    if name == "P1L":
        return simulate(inst, "P1", ls=True)
    if name == "P1pL":
        return simulate(inst, "P1p", ls=True)
    if name == "P2L":
        return simulate(inst, "P2", mu=par["mu_L"], ls=True)
    raise ValueError(name)


def cal_task(args):
    cfgd, seed = args
    cfg = Cfg(**cfgd)
    inst = make_instance(cfg, seed)
    out = {}
    for mu in MU_GRID:
        out[("P2", mu)] = simulate(inst, "P2", mu=mu)["profit"]
        out[("P2c", mu)] = simulate(inst, "P2c", mu=mu)["profit"]
        out[("P2L", mu)] = simulate(inst, "P2", mu=mu, ls=True)["profit"]
    for rho in RHO_V_GRID:
        out[("P2v", rho)] = simulate(inst, "P2v", rho=rho)["profit"]
    for rho in RHO_M_GRID:
        out[("P2m", rho)] = simulate(inst, "P2m", rho=rho)["profit"]
    return out


def calibrate(pool, cfg: Cfg) -> dict:
    res = pool.map(cal_task, [(asdict(cfg), CAL_BASE + i) for i in range(N_CAL)])
    keys = res[0].keys()
    mean = {k: st.fmean(r[k] for r in res) for k in keys}

    def best(name, grid):
        # bei Gleichstand die kleinste Schwelle (deterministisch)
        return max(grid, key=lambda g: (round(mean[(name, g)], 9), -g))

    par = dict(mu=best("P2", MU_GRID), mu_c=best("P2c", MU_GRID), mu_L=best("P2L", MU_GRID), rho_v=best("P2v", RHO_V_GRID),
               rho_m=best("P2m", RHO_M_GRID))
    par["cal_mean"] = {f"{k[0]}@{k[1]}": v for k, v in mean.items()}
    return par


def eval_task(args):
    cfgd, seed, par, with_oracle = args
    cfg = Cfg(**cfgd)
    inst = make_instance(cfg, seed)
    res = {}
    best_fleet, best_profit = None, None
    for name in POLICIES:
        r = run_policy(inst, name, par)
        res[name] = dict(profit=r["profit"], drive=r["drive"], n_acc=r["n_acc"], n_feas=r["n_feas"],
                         rev=r["rev"], ls_saved=r["ls_saved"])
        if best_profit is None or r["profit"] > best_profit:
            best_profit, best_fleet = r["profit"], r["fleet"]
    plan_util = sum(vend(inst, rt, f) for rt, f in zip(inst.plan.routes, inst.plan.F)) / (cfg.K * cfg.H)
    out = dict(seed=seed, res=res, n_sd=len(inst.arrivals), n_morning=inst.n_morning, plan_util=plan_util,
               sd_rev=sum(inst.rev[x] for _, x in inst.arrivals))
    if with_oracle:
        rL = run_policy(inst, "P2L", par)
        ro = oracle(inst, warm=rL["fleet"], time_limit=TIME_SAFETY, sol_limit=ROUTE_SOL_LIMIT, mandatory=set(rL["accepted"]))
        out["route_opt_P2L"] = ro["profit"]
        o = oracle(inst, warm=best_fleet, time_limit=TIME_SAFETY, sol_limit=ORACLE_SOL_LIMIT)
        out["oracle"] = o["profit"]
        out["oracle_served"] = o.get("n_served_sd")
        out["oracle_warm_ok"] = o["warm_ok"]
        out["best_online"] = best_profit
    return out


def run_cell(pool, cfg: Cfg, n_eval: int = N_EVAL, n_ora: int = N_ORA, par: dict | None = None) -> dict:
    t0 = time.time()
    if par is None:
        par = calibrate(pool, cfg)
    t1 = time.time()
    rows = pool.map(eval_task, [(asdict(cfg), s, par, s < n_ora) for s in range(n_eval)], chunksize=1)
    return dict(cfg=asdict(cfg), par={k: v for k, v in par.items() if k != "cal_mean"}, cal_mean=par.get("cal_mean"),
                rows=rows, t_cal=t1 - t0, t_eval=time.time() - t1)


# ------------------------------------------------------------------ Auswertung

def mean_se(xs):
    xs = list(xs)
    m = st.fmean(xs)
    se = st.stdev(xs) / len(xs) ** 0.5 if len(xs) > 1 else 0.0
    return m, se


def gain(row, name, base="P0"):
    return row["res"][name]["profit"] - row["res"][base]["profit"]


def summarize(cell: dict) -> dict:
    rows = cell["rows"]
    out = {"n": len(rows)}
    for nm in POLICIES:
        g = [gain(r, nm) for r in rows]
        out[nm] = dict(mean=mean_se(g)[0], se=mean_se(g)[1], median=st.median(g),
                       q1=st.quantiles(g, n=4)[0], q3=st.quantiles(g, n=4)[2],
                       acc=st.fmean(r["res"][nm]["n_acc"] for r in rows))
    ora = [r for r in rows if "oracle" in r]
    if ora:
        g = [r["oracle"] - r["res"]["P0"]["profit"] for r in ora]
        out["ORA"] = dict(mean=mean_se(g)[0], se=mean_se(g)[1], median=st.median(g),
                          q1=st.quantiles(g, n=4)[0], q3=st.quantiles(g, n=4)[2])
    out["n_sd"] = st.fmean(r["n_sd"] for r in rows)
    out["n_feas_P1"] = st.fmean(r["res"]["P1"]["n_feas"] for r in rows)
    out["plan_util"] = st.fmean(r["plan_util"] for r in rows)
    out["n_morning"] = st.fmean(r["n_morning"] for r in rows)
    return out


def paired(rows, a, b):
    """Mittel und Standardfehler von profit(a) - profit(b), gepaart ueber Instanzen."""
    d = [r["res"][a]["profit"] - r["res"][b]["profit"] for r in rows]
    return mean_se(d)


def print_cell(label: str, cell: dict) -> None:
    s = summarize(cell)
    p = cell["par"]
    print(f"\n== {label}  (n={s['n']}, Morgen={s['n_morning']:.1f}, SD-Eingaenge={s['n_sd']:.1f}, machbar(P1)={s['n_feas_P1']:.1f}, "
          f"Auslastung Plan={s['plan_util']:.2f}; mu={p['mu']}, mu_c={p['mu_c']}, mu_L={p['mu_L']}, rho_v={p['rho_v']}, rho_m={p['rho_m']}; "
          f"cal {cell['t_cal']:.0f}s eval {cell['t_eval']:.0f}s)")
    for nm in POLICIES + (("ORA",) if "ORA" in s else ()):
        d = s[nm]
        acc = f" angenommen {d['acc']:.1f}" if "acc" in d else ""
        print(f"  {nm:4s} Gewinn vs P0: {d['mean']:8.1f} +- {d['se']:5.1f}  med {d['median']:8.1f} [{d['q1']:.0f}, {d['q3']:.0f}]{acc}")


BASE = Cfg(K=3, n_m=40, lam=6.0)


def cell_list():
    """(Gruppe, Name, Cfg, n_ora). Doppelte Cfgs (die Basis kommt in jeder Gruppe vor) werden nur einmal gerechnet."""
    cells = [("basis", "basis", BASE, N_ORA)]
    for n in (16, 24, 32, 48, 56):
        cells.append(("auslastung", f"n_m={n}", replace(BASE, n_m=n), N_ORA))
    for lam in (1.0, 2.0, 4.0, 10.0, 16.0):
        cells.append(("rate", f"lam={lam:g}", replace(BASE, lam=lam), N_ORA))
    for sg in (0.0, 0.3, 1.0, 1.5):
        cells.append(("streuung", f"sigma={sg:g}", replace(BASE, sigma=sg), N_ORA))
    for dl in (45, 90, 180, 300):
        cells.append(("frist", f"delta={dl}", replace(BASE, delta=dl), N_ORA))
    for K, n_m, lam, no in ((2, 27, 4.0, N_ORA), (4, 53, 8.0, 10), (5, 67, 10.0, 6)):
        cells.append(("flotte", f"K={K}", replace(BASE, K=K, n_m=n_m, lam=lam), no))
    for cc in (0.5, 1.0):
        cells.append(("konzentration", f"conc={cc:g}", replace(BASE, conc=cc), N_ORA))
    for rv in (30.0, 45.0, 90.0, 120.0):
        cells.append(("erloes", f"rev={rv:g}", replace(BASE, rev_mean=rv), N_ORA))
    for n in (24, 40, 52):
        for lam in (2.0, 6.0, 12.0):
            cells.append(("raster", f"n_m={n},lam={lam:g}", replace(BASE, n_m=n, lam=lam), 0))
    seen, out = {}, []
    for g, name, cfg, no in cells:
        key = repr(asdict(cfg))
        if key in seen:
            seen[key]["groups"].append((g, name))
            continue
        rec = dict(groups=[(g, name)], cfg=cfg, n_ora=no)
        seen[key] = rec
        out.append(rec)
    # Zellen, die im Raster UND in einer Ein-Faktor-Gruppe vorkommen, brauchen das Orakel (Maximum)
    for rec in out:
        if len(rec["groups"]) > 1:
            rec["n_ora"] = max(no for g, n, c, no in cells if repr(asdict(c)) == repr(asdict(rec["cfg"])))
    return out


def main(out_path: str, only: str | None = None, n_eval: int = N_EVAL) -> None:
    import json
    import os
    raw = json.load(open(out_path, encoding="utf-8")) if os.path.exists(out_path) else {"cells": {}}
    t_all = time.time()
    with mp.Pool(min(16, mp.cpu_count())) as pool:
        base_par = None
        for rec in cell_list():
            cfg = rec["cfg"]
            key = repr(asdict(cfg))
            label = " / ".join(f"{g}:{n}" for g, n in rec["groups"])
            if key in raw["cells"]:
                cell = raw["cells"][key]
                if cfg == BASE:
                    base_par = cell["par"]
                continue
            if only and only not in label:
                continue
            cell = run_cell(pool, cfg, n_eval=n_eval, n_ora=rec["n_ora"])
            cell["groups"] = rec["groups"]
            cell["n_ora"] = rec["n_ora"]
            if cfg == BASE:
                base_par = cell["par"]
            raw["cells"][key] = cell
            print_cell(label, cell)
            sys.stdout.flush()
            json.dump(raw, open(out_path, "w", encoding="utf-8"))
        # Fehlkalibrierung: die in der Basiszelle kalibrierten Schwellen auf Auslastungs-/Raten-Zellen anwenden (ohne Orakel)
        raw.setdefault("cross", {})
        for rec in cell_list():
            gs = {g for g, _ in rec["groups"]}
            if not gs & {"auslastung", "rate", "raster", "basis"}:
                continue
            key = repr(asdict(rec["cfg"]))
            if key in raw["cross"]:
                continue
            c2 = run_cell(pool, rec["cfg"], n_eval=n_eval, n_ora=0, par=dict(base_par))
            raw["cross"][key] = dict(cfg=asdict(rec["cfg"]), groups=rec["groups"], rows=c2["rows"], par=c2["par"])
            json.dump(raw, open(out_path, "w", encoding="utf-8"))
    raw["t_total"] = time.time() - t_all
    json.dump(raw, open(out_path, "w", encoding="utf-8"))
    print(f"Gesamtlaufzeit dieses Laufs {time.time() - t_all:.0f} s")


if __name__ == "__main__":
    out = os.path.join(HERE, "sweep_sameday_raw.json")
    args = [a for a in sys.argv[1:]]
    if "--out" in args:
        out = args[args.index("--out") + 1]
    main(out, n_eval=16 if "schnell" in args else N_EVAL)
