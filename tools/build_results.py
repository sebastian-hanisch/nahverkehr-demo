"""Erzeugt data/nv_results.json: die vorgerechnete Messreihe der App (klein, ohne Roh-Instanzdaten), reduziert aus den Auswertungen
BEIDER Messreihen:

  messreihe_stabilitaet/sweep_data.json     (28 Zellen x 200 Instanzen, Politiken S0/R/F/P/T, Stabilitätsmaße, Netto, Orakel)
  messreihe_stabilitaet/sweep_h_data.json   (Zusatzlauf: zeitbasierter Einfrierhorizont H, 7 Zellen)
  messreihe_stabilitaet/timing_live.txt     (gemessene Rechenzeiten der Live-Rechnung)
  messreihe_sameday/sweep_data.json         (34 Zellen x 60 Instanzen, Annahmeregeln, Kalibriertabelle für µ, Orakel, Fehlkalibrierung)

Aufruf (im Projektordner):  python tools/build_results.py [stab_data.json stab_h_data.json sameday_data.json timing_live.txt]
Ohne Argumente werden die Dateien neben dem Projektordner unter ../tourenplanung-planung/ gelesen. Nur Standardbibliothek;
die Ausgabe ist deterministisch (sortierte Schlüssel, auf 4 Nachkommastellen gerundet)."""
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_SRC = ROOT.parent / "tourenplanung-planung"
OUT = ROOT / "data" / "nv_results.json"
DIGITS = 4

# Aus ERGEBNIS.md (Gesamtlaufzeit aller Sweeps): etwa 35 Minuten Wanduhr auf 14 Kernen (Hauptsweep 894 s, Zusatzlauf H 86 s,
# Wiederholung 17 min 50 s, Same-Day-Sweep 72 min auf 16 Prozessen); die Same-Day-Messreihe brauchte einmalig 72 Minuten.
TIMINGS_CONST = dict(messreihe_wanduhr_min=35, messreihe_kerne=14, sameday_wanduhr_min=72, sameday_prozesse=16)

STAB_CFG_KEYS = ("K", "n_m", "lam", "delta", "p_chg", "p_cancel", "Q", "w_time", "w_addr", "w_qty", "chg_delta", "addr_radius")
SAMEDAY_CFG_KEYS = ("K", "n_m", "lam", "delta", "sigma", "rev_mean", "conc")
POL_KEYS = ("pt", "gain", "gain_se", "gain_q", "a", "a_se", "b", "c", "fail", "acc", "wins")
STAT_KEYS = ("gain_R", "a_R", "b_R", "c_R", "gain_per_change")
SAMEDAY_PAIRS = ("P1p-P1", "P2-P1p", "P2v-P1p", "P2m-P1p", "P1pL-P1p", "P2L-P1pL", "P2L-P2", "P4-P2", "P4L-P2L", "P2-P2v", "P2-P2m", "P2-P2c")
CROSS_PAIRS = ("P2-P1p", "P2v-P1p", "P2m-P1p", "P1pL-P1p", "P2L-P1pL")
SAMEDAY_POL_ORDER = ("P0", "P1", "P1p", "P2", "P1L", "P1pL", "P2L", "P4", "P4L")


def rnd(x):
    """Rundet Zahlen (auch verschachtelt) auf DIGITS Stellen; None bleibt None, ganze Zahlen bleiben ganz."""
    if isinstance(x, bool) or x is None:
        return x
    if isinstance(x, float):
        return round(x, DIGITS)
    if isinstance(x, (list, tuple)):
        return [rnd(v) for v in x]
    if isinstance(x, dict):
        return {k: rnd(v) for k, v in x.items()}
    return x


def _pick(d, keys):
    return {k: d[k] for k in keys if k in d}


def reduce_stab_cell(c):
    """Eine Zelle der Stabilitäts-Messreihe (Auswertung aus dump_sweep.py) auf das, was die App zeigt."""
    out = dict(groups=c["groups"], cfg=_pick(c["cfg"], STAB_CFG_KEYS), n=c["n"], names=list(c["names"]),
               n_events=c["n_events"], n_arrivals=c["n_arrivals"], n_orders=c["n_orders"], plan_util=c["plan_util"],
               eff_change=c["eff_change"], eff_cancel=c["eff_cancel"], ign=c["ign"])
    out["pol"] = {p: _pick(v, POL_KEYS) for p, v in c["pol"].items()}
    out["stats"] = {k: v for k, v in c["stats"].items() if k in STAT_KEYS or k.startswith("share_")}
    out["stats_ci"] = {k: v for k, v in c["stats_ci"].items() if (k.startswith("share_") and "front" not in k) or k == "gain_per_change"
                       or k == "gain_R"}
    out["F_vs_P"] = c["F_vs_P"]
    out["head"] = c["head"]
    out["R_dist"] = c["R_dist"]
    out["net"] = {"a": c["net"]["a"]}
    if "event_cost" in c:
        out["event_cost"] = c["event_cost"]
    if "oracle" in c:
        o = dict(c["oracle"])
        o.pop("share_s0", None)
        out["oracle"] = o
    return rnd(out)


def reduce_h_cell(c):
    """Eine Zelle des Zusatzlaufs (zeitbasierter Horizont H): nur die H-Politiken und die H-Anteile."""
    out = dict(groups=c["groups"], cfg=_pick(c["cfg"], STAB_CFG_KEYS), n=c["n"])
    out["pol"] = {p: _pick(v, ("gain", "gain_se", "a", "a_se", "b", "c")) for p, v in c["pol"].items() if p.startswith("H")}
    out["stats"] = {k: v for k, v in c["stats"].items() if k.startswith("share_H")}
    out["H_vs_P"] = {k: v for k, v in c["F_vs_P"].items() if k.startswith("H_minus_P")}
    return rnd(out)


def reduce_sameday_cell(c):
    """Eine Zelle der Annahme-Messreihe: Kennzahlen je Regel, gepaarte Vergleiche, Kalibrierung, Orakel."""
    out = dict(groups=c["groups"], cfg=_pick(c["cfg"], SAMEDAY_CFG_KEYS), n=c["n"], n_ora=c["n_ora"], n_morning=c["n_morning"],
               n_sd=c["n_sd"], n_feas_P1=c["n_feas_P1"], plan_util=c["plan_util"], par=c["par"])
    out["cal_mean"] = {k: v for k, v in c["cal_mean"].items() if k.startswith(("P2@", "P2L@"))}
    out["pol"] = {p: c["pol"][p] for p in SAMEDAY_POL_ORDER if p in c["pol"]}
    out["pairs"] = {k: c["pairs"][k] for k in SAMEDAY_PAIRS if k in c["pairs"]}
    if "oracle" in c:
        o = c["oracle"]
        out["oracle"] = dict(n=o["n"], ORA=_pick(o["ORA"], ("mean", "se")), served=o["served"], sd_arrivals=o["sd_arrivals"],
                             best_online_gain=o["best_online_gain"], gap_best_online=o["gap_best_online"],
                             gap_by_policy=o["gap_by_policy"], pol_on_ora=o["pol_on_ora"], route_opt_P2L=o["route_opt_P2L"],
                             oracle_ge_all=o["oracle_ge_all"], warm_ok=o["warm_ok"])
    return rnd(out)


def reduce_cross_cell(c):
    """Fehlkalibrierung: die in der Basiszelle kalibrierten Schwellen in einer anderen Zelle (ohne Neukalibrierung)."""
    return rnd(dict(groups=c["groups"], cfg=_pick(c["cfg"], SAMEDAY_CFG_KEYS), par=c["par"],
                    pairs={k: c["pairs"][k] for k in CROSS_PAIRS if k in c["pairs"]}))


_TIMING = re.compile(r"n_m=(\d+) seed=(\d+): instance\+morning ([\d.]+)s events ([\d.]+)s \| (.*)")


def parse_timing(text):
    """Rechenzeiten der Live-Rechnung aus timing_live.txt: je Morgenauftragszahl Instanz+Morgenplan (Sekunden je Seed) und die
    Simulationszeiten je Politik (Maximum)."""
    morning, sim = {}, {}
    for line in text.splitlines():
        m = _TIMING.match(line.strip())
        if not m:
            continue
        n = m.group(1)
        morning.setdefault(n, []).append(float(m.group(3)))
        for name, sec in re.findall(r"(\S+) ([\d.]+)s", m.group(5)):
            sim[n] = max(sim.get(n, 0.0), float(sec))
    return dict(morgenplan_s=morning, simulation_max_s=sim)


def build(stab, stab_h, sameday, timing_text):
    data = dict(
        _meta=dict(n_eval=stab["n_eval"], n_ora=stab["n_ora"], sameday_n_eval=sameday["n_eval"],
                   quellen="messreihe_stabilitaet/sweep_data.json, sweep_h_data.json, timing_live.txt, messreihe_sameday/sweep_data.json"),
        _timings=dict(TIMINGS_CONST, **parse_timing(timing_text)),
        stab=dict(cells=[reduce_stab_cell(c) for c in stab["cells"]], h_cells=[reduce_h_cell(c) for c in stab_h["cells"]]),
        sameday=dict(cells=[reduce_sameday_cell(c) for c in sameday["cells"]], cross=[reduce_cross_cell(c) for c in sameday["cross"]]))
    return data


def dumps(data):
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"


def main(argv):
    if argv:
        stab_p, h_p, sd_p, tm_p = (pathlib.Path(a) for a in argv[:4])
    else:
        stab_p = DEFAULT_SRC / "messreihe_stabilitaet" / "sweep_data.json"
        h_p = DEFAULT_SRC / "messreihe_stabilitaet" / "sweep_h_data.json"
        sd_p = DEFAULT_SRC / "messreihe_sameday" / "sweep_data.json"
        tm_p = DEFAULT_SRC / "messreihe_stabilitaet" / "timing_live.txt"
    data = build(*(json.loads(p.read_text(encoding="utf-8")) for p in (stab_p, h_p, sd_p)), tm_p.read_text(encoding="utf-8"))
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(dumps(data), encoding="utf-8", newline="\n")
    print(f"geschrieben: {OUT} ({OUT.stat().st_size / 1024:.0f} KB; {len(data['stab']['cells'])} Stabilitäts-, "
          f"{len(data['stab']['h_cells'])} H-, {len(data['sameday']['cells'])} Annahme-Zellen)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
