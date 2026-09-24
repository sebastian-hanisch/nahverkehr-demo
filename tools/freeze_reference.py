"""Erzeugt die eingefrorenen Referenzdaten der Tests aus den Rohdaten der beiden Messreihen (nur lesend):

  tests/data/nv_reference.json   erwartete Ergebnisse (Gewinn, Fahrzeit, Zähler ...) je Instanz und Politik, so wie die Sweeps der
                                 Messreihen sie gerechnet haben (messreihe_stabilitaet/sweep_raw.json, sweep_h_raw.json und
                                 messreihe_sameday/sweep_raw.json): mehrere Zellen, Seeds und alle Politiken
  tests/data/nv_morning.json     die dazugehörigen MORGENPLÄNE aus dem Zwischenspeicher der Messreihe (cache_morning), also genau die
                                 Pläne, mit denen die Sweeps gerechnet haben (Knoten und Touren je Morgenparameter und Seed)

Warum eingefroren: die CI installiert immer das NEUESTE OR-Tools, und Morgenpläne können sich zwischen Versionen ändern. Die Tests
rechnen deshalb nur die reine Simulation (nv_sim, Standardbibliothek) auf den eingefrorenen Morgenplänen und verlangen bitgleiche Ergebnisse
zur Messreihe: der Nachweis, dass die mechanische Aufteilung von stab.py in nv_model / nv_sim nichts an der Logik geändert hat.

Aufruf (im Projektordner):  python tools/freeze_reference.py [Ordner_der_Messreihen]
(Standard ../tourenplanung-planung). Weitere Morgenpläne, die die Tests brauchen, trägt `NV_RECORD_MORNING=1 pytest tests/` nach."""
import hashlib
import json
import os
import pathlib
import pickle
import sys

sys.dont_write_bytecode = True
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import nv_model as M  # noqa: E402

# Stabilität: (Bezeichnung, Abweichungen vom Basisfall in der Cfg, Seeds); je Zelle alle 21 Politiken
STAB_CASES = [
    ("basis", {}, list(range(8))),
    ("rate12", dict(lam=12.0), [0, 1, 2]),
    ("frist60", dict(delta=60), [0, 1, 2]),
    ("ereignisse_viele", dict(p_chg=0.5, p_cancel=0.16), [0, 1, 2]),
    ("rate0", dict(lam=0.0), [0, 1, 2]),
    ("morgen16", dict(n_m=16), [0, 1, 2, 3]),
    ("alle_drei_q34", dict(Q=34, w_qty=1.0, w_time=1.0, w_addr=1.0), [0, 1, 2]),
    ("k2", dict(K=2, n_m=27, lam=4.0), [0, 1, 2]),
    ("ohne_ereignisse", dict(p_chg=0.0, p_cancel=0.0), [0, 1, 2, 3]),
]
STAB_METRICS = ("profit_total", "profit", "drive", "a", "b", "c", "n_fail", "n_acc", "n_cancel", "n_change", "n_ign", "ls_saved",
                "n_morning_served", "n_served_sd")
H_SEEDS = [0, 1, 2, 3]
# Annahme: (Bezeichnung, Abweichungen vom Basisfall der Annahme-Messreihe, Seeds)
SD_CASES = [
    ("basis", {}, list(range(10))),
    ("rate12", dict(lam=12.0), [0, 1, 2]),
    ("frist45", dict(delta=45), [0, 1, 2]),
    ("morgen16", dict(n_m=16), [0, 1, 2]),
    ("sigma0", dict(sigma=0.0), [0, 1, 2]),
    ("hotspot", dict(conc=0.5), [0, 1, 2]),
    ("rollout", {}, [0, 1]),                   # zusätzlich P4 und P4L (Stichproben-Rollout)
]
SD_KEYS = ("profit", "drive", "n_acc", "n_feas", "rev", "ls_saved")


def key_str(key):
    return json.dumps(list(key))


def disk_name(key):
    return hashlib.md5(repr(key).encode()).hexdigest() + ".pkl"


def cell_by_cfg(raw, want):
    hits = [c for c in raw["cells"].values() if all(c["cfg"].get(k) == v for k, v in want.items())]
    assert len(hits) == 1, (want, len(hits))
    return hits[0]


def main(argv):
    src = pathlib.Path(argv[0]) if argv else ROOT.parent / "tourenplanung-planung"
    stab_dir, sd_dir = src / "messreihe_stabilitaet", src / "messreihe_sameday"
    raw = json.loads((stab_dir / "sweep_raw.json").read_text(encoding="utf-8"))
    raw_h = json.loads((stab_dir / "sweep_h_raw.json").read_text(encoding="utf-8"))
    raw_sd = json.loads((sd_dir / "sweep_raw.json").read_text(encoding="utf-8"))
    cache = stab_dir / "cache_morning"
    base = dict(K=3, n_m=40, lam=6.0, delta=120, p_chg=0.25, p_cancel=0.08, Q=10 ** 9, w_time=1.0, w_addr=1.0, w_qty=0.0, chg_delta=30, addr_radius=5.0)
    ref = dict(stab=[], h=[], sameday=[])
    morning = {}

    def take_morning(cfgd, seeds):
        cfg = M.Cfg(**cfgd)
        for seed in seeds:
            key = M._morning_key(cfg, seed)
            with open(cache / disk_name(key), "rb") as fh:
                nodes, routes, shortfall = pickle.load(fh)
            morning[key_str(key)] = [[list(n) for n in nodes], [list(r) for r in routes], shortfall]

    for name, over, seeds in STAB_CASES:
        cell = cell_by_cfg(raw, dict(base, **over))
        rows = {str(r["seed"]): {p: {m: v[m] for m in STAB_METRICS} for p, v in r["res"].items()} for r in cell["rows"] if r["seed"] in seeds}
        ref["stab"].append(dict(name=name, cfg=cell["cfg"], seeds=seeds, rows=rows,
                                counts={str(r["seed"]): dict(n_events=r["n_events"], n_arrivals=r["n_arrivals"], n_orders=r["n_orders"], n_morning=r["n_morning"])
                                        for r in cell["rows"] if r["seed"] in seeds}))
        take_morning(cell["cfg"], seeds)
    cell_h = cell_by_cfg(raw_h, base)
    ref["h"].append(dict(name="basis", cfg=cell_h["cfg"], seeds=H_SEEDS,
                         rows={str(r["seed"]): {p: {m: v[m] for m in STAB_METRICS} for p, v in r["res"].items()} for r in cell_h["rows"] if r["seed"] in H_SEEDS}))
    take_morning(cell_h["cfg"], H_SEEDS)
    sd_base = dict(K=3, n_m=40, lam=6.0, delta=120, sigma=0.6, rev_mean=60.0, conc=0.0)
    for name, over, seeds in SD_CASES:
        cell = cell_by_cfg(raw_sd, dict(sd_base, **over))
        pols = ("P0", "P1", "P1p", "P2v", "P2m", "P2", "P2c", "P1L", "P1pL", "P2L") + (("P4", "P4L") if name == "rollout" else ())
        rows = {str(r["seed"]): {p: {k: r["res"][p][k] for k in SD_KEYS} for p in pols} for r in cell["rows"] if r["seed"] in seeds}
        ref["sameday"].append(dict(name=name, cfg=cell["cfg"], par=cell["par"], seeds=seeds, rows=rows, rollout_s=24 if name == "rollout" else 0))
        take_morning(cell["cfg"], seeds)
    out = ROOT / "tests" / "data"
    out.mkdir(exist_ok=True)
    (out / "nv_reference.json").write_text(json.dumps(ref, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8", newline="\n")
    (out / "nv_morning.json").write_text(json.dumps(morning, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8", newline="\n")
    print(f"geschrieben: nv_reference.json ({os.path.getsize(out / 'nv_reference.json') // 1024} KB), nv_morning.json "
          f"({os.path.getsize(out / 'nv_morning.json') // 1024} KB, {len(morning)} Morgenpläne)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
