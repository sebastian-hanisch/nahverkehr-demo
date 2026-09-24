"""Die 12 Korrektheits-Checks der Messreihe (messreihe_stabilitaet/check.py) für die nv_-Module. Ganzzahlig und deterministisch (keine
Toleranzen, außer wo angegeben).

Zwei Verwendungen: tests/test_checks.py ruft jeden Check VERKLEINERT auf (kleine Instanzzahlen, nur reine Simulation auf den
eingefrorenen Morgenplänen, OR-Tools-Orakel nur mit unabhängig gültigen Schranken); tools/check_full.py ruft sie in voller Größe auf (das
Bau-Gate, einmal lokal, mit dem echten OR-Tools). Die Checks rufen nie build_morning mit einem nicht eingefrorenen Schlüssel auf, solange
die Instanzzahlen so klein bleiben wie in tests/test_checks.py (die Morgenpläne stehen in tests/data/nv_morning.json)."""
from __future__ import annotations

import itertools
import json
import os
import statistics as st
import sys
from dataclasses import replace

from nv_model import Cfg, Fleet, candidates, fleet_drive, local_search, make_instance, retime, trip_ok
from nv_oracle import offline_profit_ev, oracle_ev, order_windows
from nv_sim import run_events

HERE = os.path.dirname(os.path.abspath(__file__))
REFERENCE = os.path.join(HERE, "data", "nv_reference.json")
BASE = Cfg(K=3, n_m=40, lam=6.0)
EV = replace(BASE, p_chg=0.25, p_cancel=0.08)                 # Basiszelle der Messreihe (mit Änderungen)
SMALL = replace(Cfg(K=2, n_m=10, lam=5.0), p_chg=0.3, p_cancel=0.1)
POLS = [("S0", dict(kind="S0")), ("R", dict(kind="R")), ("F3", dict(kind="F", k=3)), ("F1", dict(kind="F", k=1)),
        ("P1", dict(kind="P", lam=1.0)), ("P3", dict(kind="P", lam=3.0)), ("T60", dict(kind="T", T_per=60)), ("H60", dict(kind="H", H_min=60))]
# Die ersten 8 Seeds, für die tiny_instance eine gültige Kleinstinstanz liefert (mit dem Morgenplan der Messreihe-Umgebung ermittelt und
# eingefroren; die volle Fassung sucht selbst).
TINY_SEEDS = (7, 9, 13, 17, 27, 32, 33, 34)


def run(inst, spec):
    return run_events(inst, **spec)


# ------------------------------------------------------------------ Reproduktion und Grenzfälle

def check_repro_original(n: int = 30, sources=None) -> str:
    """NUR lokal (die Quellen der Messreihe liegen neben dem Projektordner): ohne Änderungsereignisse S0 == P1p und R == P1pL bitgenau
    aus sameday.py, sowohl gegen die gespeicherten Sweep-Zahlen der Same-Day-Messreihe (Basiszelle, Seeds 0..n-1) als auch gegen
    sameday.simulate (Routen). Rückgabe: Meldung; None, wenn die Quellen fehlen."""
    src = sources or os.path.join(HERE, "..", "..", "tourenplanung-planung", "messreihe_sameday")
    raw_path, mod_path = os.path.join(src, "sweep_raw.json"), os.path.join(src, "sameday.py")
    if not (os.path.exists(raw_path) and os.path.exists(mod_path)):
        return None
    raw = json.load(open(raw_path, encoding="utf-8"))
    cell = list(raw["cells"].values())[0]
    cfg0 = cell["cfg"]
    assert (cfg0["K"], cfg0["n_m"], cfg0["lam"], cfg0["sigma"], cfg0["delta"], cfg0["conc"], cfg0["rev_mean"]) == (3, 40, 6.0, 0.6, 120, 0.0, 60.0)
    import importlib.util
    spec = importlib.util.spec_from_file_location("sameday_orig", mod_path)
    sd = importlib.util.module_from_spec(spec)
    sys.modules["sameday_orig"] = sd
    spec.loader.exec_module(sd)
    for seed in range(n):
        inst = make_instance(BASE, seed)
        s0, r = run_events(inst, "S0"), run_events(inst, "R")
        row = cell["rows"][seed]["res"]
        assert s0["profit"] == row["P1p"]["profit"] and r["profit"] == row["P1pL"]["profit"], (seed, s0["profit"], row["P1p"]["profit"])
        assert s0["n_acc"] == row["P1p"]["n_acc"] and r["n_acc"] == row["P1pL"]["n_acc"] and s0["drive"] == row["P1p"]["drive"]
        if seed < 10:
            io = sd.make_instance(sd.Cfg(K=3, n_m=40, lam=6.0), seed)
            assert io.T == inst.T and io.arrivals == inst.arrivals and io.plan.routes == inst.plan.routes
            assert sd.simulate(io, "P1p")["fleet"].routes == s0["fleet"].routes
            assert sd.simulate(io, "P1p", ls=True)["fleet"].routes == r["fleet"].routes
    return (f"reproduktion: {n} Seeds Basiszelle ohne Änderungsereignisse: S0 == P1p und R == P1pL bitgenau (Gewinn, Annahmen, Fahrzeit "
            f"aus sweep_raw.json der Same-Day-Messreihe; Routen und Instanz gegen sameday.py auf 10 Seeds)")


def check_no_events(n: int = 15) -> None:
    """Keine Ereignisse (weder Neuaufträge noch Änderungen): null Änderungen, alle Politiken gleich dem Morgenplan."""
    cfg = replace(SMALL, lam=0.0, p_chg=0.0, p_cancel=0.0)
    for seed in range(n):
        inst = make_instance(cfg, seed)
        assert not inst.arrivals and not inst.events
        base = run_events(inst, "S0")
        assert base["profit"] == -fleet_drive(inst, inst.plan) and base["fleet"].routes == inst.plan.routes
        for name, spec in POLS:
            r = run(inst, spec)
            assert r["fleet"].routes == inst.plan.routes and r["profit_total"] == base["profit_total"], (seed, name)
            assert (r["a"], r["b"], r["c"], r["n_acc"]) == (0, 0, 0, 0), (seed, name)


def check_limits(n: int = 40) -> None:
    """F_alle == S0, F_0 == R, lambda = 0 == R, T_0 == R, T_unendlich == S0: exakt (Routen, Gewinn, alle Zähler), mit Ereignissen."""
    for seed in range(n):
        inst = make_instance(EV if seed % 2 else replace(EV, lam=3.0, p_chg=0.4), seed)
        s0, r = run_events(inst, "S0"), run_events(inst, "R")
        keys = ("profit_total", "profit", "drive", "a", "b", "c", "n_acc", "n_fail", "n_cancel", "n_change", "n_ign")
        for name, o, ref in (("F_alle", run_events(inst, "F", k=10 ** 6), s0), ("T_inf", run_events(inst, "T", T_per=10 ** 9), s0),
                             ("F_0", run_events(inst, "F", k=0), r), ("P_0", run_events(inst, "P", lam=0.0), r),
                             ("T_0", run_events(inst, "T", T_per=0), r), ("H_0", run_events(inst, "H", H_min=0), r),
                             ("H_inf", run_events(inst, "H", H_min=10 ** 6), s0)):
            assert o["fleet"].routes == ref["fleet"].routes and all(o[k] == ref[k] for k in keys), (seed, name)
        assert s0["a"] == 0 and s0["c"] == 0                    # S0 stört nie andere Stopps (per Definition des Maßes)


# ------------------------------------------------------------------ Ereignisstrom

def check_event_stream(n: int = 60) -> None:
    n_ord = n_ev = 0
    kinds = {"cancel": 0, "time": 0, "addr": 0, "qty": 0}
    for seed in range(n):
        cfg = replace(EV, w_qty=1.0, Q=40)
        inst = make_instance(cfg, seed)
        plain = make_instance(replace(cfg, p_chg=0.0, p_cancel=0.0), seed)
        assert plain.arrivals == inst.arrivals and plain.T[:len(plain.T)] == [row[:len(plain.T)] for row in inst.T[:len(plain.T)]]
        n_ord += inst.n_orders_base
        n_ev += len(inst.events)
        seen = set()
        for e in inst.events:
            assert e["order"] not in seen and 1 <= e["order"] <= inst.n_orders_base
            seen.add(e["order"])
            kinds[e["kind"]] += 1
            assert 5 <= e["t"] < cfg.H
            if e["kind"] == "cancel":
                assert e["var"] is None
            else:
                w = e["var"]
                assert inst.order_of[w] == e["order"] and w > inst.n_orders_base and inst.A[w] <= inst.B[w]
                assert inst.is_sd[w] == inst.is_sd[e["order"]] and inst.rev[w] == inst.rev[e["order"]]
        assert make_instance(cfg, seed).events == inst.events
    return n_ev / n_ord, kinds


# ------------------------------------------------------------------ Handinstanzen

def hand_line_instance(with_windows: bool = True):
    """Ein Fahrzeug auf einer Geraden: A (+10 km), B (+20), C (+30), X (weit weg, wird storniert). Geschwindigkeit 1 min/km,
    Service 10, Fenster ab 100 (damit zum Ereigniszeitpunkt t=1 nichts bindend ist). Plan (bewusst schlecht): [B, A, C, X]."""
    cfg = Cfg(K=1, n_m=0, lam=0.0, speed=1.0, svc=10, H=480, area=60.0, M=1)
    inst = make_instance(cfg, 0)
    a0 = 100 if with_windows else 0
    A = inst.add_node(40.0, 30.0, 1, a0, 400, 0, False)
    B = inst.add_node(50.0, 30.0, 1, a0, 400, 0, False)
    C = inst.add_node(60.0, 30.0, 1, a0, 400, 0, False)
    X = inst.add_node(30.0, 58.0, 1, a0, 400, 0, False)
    inst.n_orders_base = inst.n_morning = 4
    fl = Fleet(1)
    fl.routes[0] = [B, A, C, X]
    fl.S[0], fl.F[0] = retime(inst, fl.routes[0], [], [], 0, -1)
    inst.plan = fl
    return inst, (A, B, C, X)


def check_hand_measures() -> None:
    """Erwartete Änderungszahlen von Hand: Plan [B,A,C,X], Storno von X bei t=1 (alles noch frei).
    S0: nur X entfernt -> (a,b,c) = (0,0,0). R: Neuoptimierung zu [A,B,C]: B, A, C haben neue Vorgänger -> a=3, c=1; angekündigte
    Zeiten vorher B100 A120 C150, nachher A100 B120 C140 -> A (20) und B (20) ändern sich um mehr als 15, C (10) nicht -> b=2.
    Fahrzeit 80 -> 60, Gewinn_total 100 -> 120. F_2 (B und A fest) kann nichts verbessern (a=0), F_1 setzt A ans Ende (a=2), F_0 == R,
    P_5 (Ersparnis 20 > 5 x 3) führt den Zug aus, P_12 (20 < 12 x 2, jeder Zug ändert mindestens 2 Stopps) keinen."""
    inst, (A, B, C, X) = hand_line_instance()
    assert inst.plan.S[0] == [100, 120, 150, 202] and fleet_drive(inst, inst.plan) == 20 + 10 + 20 + 42 + 28
    inst.events = [dict(t=1, kind="cancel", order=X, var=None)]
    s0 = run_events(inst, "S0")
    assert (s0["a"], s0["b"], s0["c"], s0["n_cancel"]) == (0, 0, 0, 1) and s0["fleet"].routes[0] == [B, A, C]
    assert fleet_drive(inst, s0["fleet"]) == 80 and s0["profit_total"] == 180 - 80
    r = run_events(inst, "R")
    assert r["fleet"].routes[0] == [A, B, C] and r["fleet"].S[0] == [100, 120, 140]
    assert (r["a"], r["b"], r["c"]) == (3, 2, 1), (r["a"], r["b"], r["c"])
    assert fleet_drive(inst, r["fleet"]) == 60 and r["profit_total"] == 180 - 60
    f2 = run_events(inst, "F", k=2)                          # B und A fest: nur noch C frei, nichts zu verbessern
    assert (f2["a"], f2["b"], f2["c"]) == (0, 0, 0) and f2["fleet"].routes[0] == [B, A, C]
    f1 = run_events(inst, "F", k=1)                          # nur B fest: A ans Ende ([B,C,A], ebenfalls 60): A und C ändern den Vorgänger
    assert f1["fleet"].routes[0] == [B, C, A] and f1["a"] == 2 and fleet_drive(inst, f1["fleet"]) == 60
    assert run_events(inst, "F", k=0)["fleet"].routes == r["fleet"].routes
    # jeder verbessernde Zug (Ersparnis 20) ändert mindestens 2 Stopps: lambda 5 lässt den ersten Zug (3 Änderungen: 20 > 15) zu,
    # lambda 12 verbietet alle (20 < 24)
    assert run_events(inst, "P", lam=5.0)["a"] == 3 and run_events(inst, "P", lam=12.0)["a"] == 0
    # zweiter Fall: Ereignis nach dem Abfahren wird ignoriert (B ist bei t=90 bindend: spätester Start 100-20=80 <= 90)
    inst.events = [dict(t=90, kind="cancel", order=B, var=None)]
    ig = run_events(inst, "R")
    assert ig["n_ign"] == 1 and ig["n_cancel"] == 0 and ig["a"] == 0 and B in ig["fleet"].routes[0]


def check_hand_failure() -> None:
    """Änderung der Menge über die Kapazität: Q = 5, Route [A(2), B(2)], B wird auf 4 geändert -> nicht mehr bedienbar:
    n_fail = 1, Strafe 60, B entfernt. Gewinn_total = 60 (nur A) - 20 (Fahrt Depot-A-Depot) - 60 = -20."""
    cfg = Cfg(K=1, n_m=0, lam=0.0, speed=1.0, svc=10, H=480, area=60.0, M=1, Q=5, pen=60)
    inst = make_instance(cfg, 0)
    A = inst.add_node(40.0, 30.0, 2, 100, 400, 0, False)
    B = inst.add_node(50.0, 30.0, 2, 100, 400, 0, False)
    Bv = inst.add_node(50.0, 30.0, 4, 100, 400, 0, False)
    inst.order_of[Bv] = B
    inst.n_orders_base = inst.n_morning = 2
    fl = Fleet(1)
    fl.routes[0] = [A, B]
    fl.S[0], fl.F[0] = retime(inst, fl.routes[0], [], [], 0, -1)
    inst.plan = fl
    inst.events = [dict(t=1, kind="qty", order=B, var=Bv)]
    for kind in ("S0", "R"):
        r = run_events(inst, kind)
        assert r["n_fail"] == 1 and r["fleet"].routes[0] == [A] and r["failed_orders"] == [B]
        assert fleet_drive(inst, r["fleet"]) == 20 and r["profit"] == -20 - 60 and r["profit_total"] == -20, r["profit_total"]
    # mit genug Kapazität bleibt der Auftrag an derselben Stelle (minimale Reparatur), n_fail = 0
    inst.cfg = replace(cfg, Q=10)
    r = run_events(inst, "S0")
    assert r["n_fail"] == 0 and r["fleet"].routes[0] == [A, Bv]


def check_tiebreak_symmetric() -> None:
    """Gleichwertige Alternativen dürfen keine Änderungen erzeugen: zwei spiegelbildliche Fahrzeuge, Neuauftrag mit exakt gleichen
    Einfügekosten in beide, danach Neuoptimierung: R == S0, a = 0; und eine zweite Neuoptimierung auf dem Ergebnis ändert nichts."""
    cfg = Cfg(K=2, n_m=0, lam=0.0, speed=1.0, svc=10, H=480, area=60.0, M=1, Q=2)   # Q=2: keine Zusammenlegung auf ein Fahrzeug möglich
    inst = make_instance(cfg, 0)
    P = inst.add_node(40.0, 30.0, 1, 100, 400, 0, False)      # rechts
    Q = inst.add_node(20.0, 30.0, 1, 100, 400, 0, False)      # links (Spiegelbild)
    Xn = inst.add_node(30.0, 40.0, 1, 1, 151, 80, True)       # oben: gleiche Kosten in beide Routen
    inst.n_orders_base = 3
    inst.n_morning = 2
    fl = Fleet(2)
    fl.routes[0], fl.routes[1] = [P], [Q]
    for v in range(2):
        fl.S[v], fl.F[v] = retime(inst, fl.routes[v], [], [], 0, -1)
    inst.plan = fl
    inst.arrivals = [(1, Xn)]
    cs = candidates(inst, fl, Xn, 1)
    tie = sorted((c[0], c[1]) for c in cs)
    assert len({(c[0], c[1]) for c in cs if c[5] == 0}) >= 1
    s0, r = run_events(inst, "S0"), run_events(inst, "R")
    assert r["a"] == 0 and r["fleet"].routes == s0["fleet"].routes and r["b"] == s0["b"], (r["fleet"].routes, s0["fleet"].routes)
    assert local_search(inst, r["fleet"], 2) == 0
    return tie


def check_local_search_idempotent(n: int = 40) -> None:
    """Auf dem Ergebnis einer Neuoptimierung findet eine weitere (bei gleichem Zeitpunkt) keinen Zug: Gleichstände führen nie zu Zügen."""
    for seed in range(n):
        inst = make_instance(EV if seed % 2 else SMALL, seed)
        for name, spec in POLS[1:]:
            r = run(inst, spec)
            fl = r["fleet"].clone()
            t = 100 + seed
            local_search(inst, fl, t)
            routes = [x[:] for x in fl.routes]
            assert local_search(inst, fl, t) == 0 and fl.routes == routes, (seed, name)


# ------------------------------------------------------------------ Invarianten

def check_invariants(n: int = 40) -> dict:
    """Endplan gültig gegen die AKTUELLEN Auftragsattribute, exakt die erwartete Auftragsmenge bedient, bindender Präfix nie verändert,
    Gewinn unabhängig nachgerechnet, und jeder Online-Endplan ist im Orakel-Modell zulässig (Relaxation)."""
    cnt = dict(fail=0, cancel=0, change=0, ign=0)
    for seed in range(n):
        cfg = replace(EV, w_qty=1.0, Q=44) if seed % 3 == 0 else (EV if seed % 3 == 1 else SMALL)
        inst = make_instance(cfg, seed)
        for name, spec in POLS:
            r = run_events(inst, log=True, **spec)
            fl = r["fleet"]
            seen = []
            for v, route in enumerate(fl.routes):
                prevn, prevF = 0, 0
                for j, node in enumerate(route):
                    S = fl.S[v][j]
                    assert S >= prevF + inst.T[prevn][node] and S >= inst.A[node] and S <= inst.B[node], (seed, name, v, j)
                    assert fl.F[v][j] == S + inst.svc[node]
                    prevn, prevF = node, fl.F[v][j]
                    seen.append(node)
                if route:
                    assert prevF + inst.T[prevn][0] <= cfg.H
                assert trip_ok(inst, route)
            served_orders = sorted(inst.order_of[n_] for n_ in seen)
            assert len(served_orders) == len(set(served_orders))
            expected = (set(range(1, inst.n_morning + 1)) | set(r["accepted"])) - set(r["cancelled_orders"]) - set(r["failed_orders"])
            assert set(served_orders) == expected, (seed, name)
            for (t, snaps) in r["snaps"]:
                for v, (nodes, starts) in enumerate(snaps):
                    # ein bindender Knoten kann nur durch dieselbe Stelle ersetzt sein, wenn er unverändert blieb
                    assert fl.routes[v][:len(nodes)] == nodes and fl.S[v][:len(nodes)] == starts, (seed, name, t, v)
            vr = [list(x) for x in fl.routes]
            off = offline_profit_ev(inst, vr)                     # prüft nebenbei die Zulässigkeit im Orakel-Modell
            n_sd_fail = sum(1 for o in r["failed_orders"] if inst.is_sd[o])
            assert off == r["profit_total"] + cfg.pen * n_sd_fail, (seed, name, off, r["profit_total"], n_sd_fail)
            assert r["a"] >= r["c"] and r["c"] <= len(inst.events) + len(inst.arrivals)
            cnt["fail"] += r["n_fail"]
            cnt["cancel"] += r["n_cancel"]
            cnt["change"] += r["n_change"]
            cnt["ign"] += r["n_ign"]
    assert all(v > 0 for v in cnt.values()), cnt
    return cnt


def check_policies_are_exercised(n: int = 60) -> tuple:
    """Jede Politik weicht auf mindestens einer Instanz von ihrer Nachbarpolitik ab; Zähler sind keine Nullspalten;
    jede Ereignisart wird angewendet (mit endlicher Kapazität auch die Mengenänderung)."""
    diff = dict(R_vs_S0=0, F3_vs_S0=0, F3_vs_R=0, F1_vs_F3=0, P1_vs_S0=0, P1_vs_R=0, P3_vs_S0=0, P3_vs_P1=0, T60_vs_S0=0, T60_vs_R=0, H60_vs_S0=0,
                H60_vs_R=0, H60_vs_F3=0)
    nz = dict(a_R=0, b_S0=0, b_R=0, c_R=0, a_F3=0, a_P3=0, a_T60=0, a_H60=0)
    kinds = dict(cancel=0, time=0, addr=0, qty=0)
    for seed in range(n):
        inst = make_instance(replace(EV, w_qty=1.0, Q=44), seed)
        Rs = {name: run_events(inst, **spec) for name, spec in POLS}
        rt = {k: v["fleet"].routes for k, v in Rs.items()}
        diff["R_vs_S0"] += rt["R"] != rt["S0"]
        diff["F3_vs_S0"] += rt["F3"] != rt["S0"]
        diff["F3_vs_R"] += rt["F3"] != rt["R"]
        diff["F1_vs_F3"] += rt["F1"] != rt["F3"]
        diff["P1_vs_S0"] += rt["P1"] != rt["S0"]
        diff["P1_vs_R"] += rt["P1"] != rt["R"]
        diff["P3_vs_S0"] += rt["P3"] != rt["S0"]
        diff["P3_vs_P1"] += rt["P3"] != rt["P1"]
        diff["T60_vs_S0"] += rt["T60"] != rt["S0"]
        diff["T60_vs_R"] += rt["T60"] != rt["R"]
        diff["H60_vs_S0"] += rt["H60"] != rt["S0"]
        diff["H60_vs_R"] += rt["H60"] != rt["R"]
        diff["H60_vs_F3"] += rt["H60"] != rt["F3"]
        nz["a_R"] += Rs["R"]["a"] > 0
        nz["b_S0"] += Rs["S0"]["b"] > 0
        nz["b_R"] += Rs["R"]["b"] > 0
        nz["c_R"] += Rs["R"]["c"] > 0
        nz["a_F3"] += Rs["F3"]["a"] > 0
        nz["a_P3"] += Rs["P3"]["a"] > 0
        nz["a_T60"] += Rs["T60"]["a"] > 0
        nz["a_H60"] += Rs["H60"]["a"] > 0
        for k, v in Rs["S0"]["by_kind"].items():
            kinds[k] += v
    for d in (diff, nz, kinds):
        for k, v in d.items():
            assert v > 0, f"{k} greift nie (Nullspalte = Bug-Signal)"
    return diff, nz, kinds


# ------------------------------------------------------------------ Orakel

def tiny_instance(seed: int):
    cfg = Cfg(K=2, n_m=3, lam=1.0, M=1, t_arr=300, delta=150, max_tries=200, p_chg=0.5, p_cancel=0.15)
    inst = make_instance(cfg, seed)
    return inst if len(inst.arrivals) <= 3 and len(inst.T) <= 12 else None


def bruteforce_ev(inst):
    """Exakter Offline-Optimalgewinn (K=2): je Auftrag Version wählen (nicht/Ursprung/Variante gemäß Orakel-Modell), Knoten auf die
    zwei Fahrzeuge verteilen, alle Reihenfolgen mit frühestem Zeitplan. Eigene Gewinnformel."""
    cfg = inst.cfg
    T = inst.T
    win, groups = order_windows(inst)
    ev_of = {e["order"]: e for e in inst.events}
    cache = {}

    def vcost(nodes):
        key = frozenset(nodes)
        if key in cache:
            return cache[key]
        if not nodes:
            res = 0
        else:
            res = None
            for perm in itertools.permutations(nodes):
                t, prevn, ok = 0, 0, True
                for x in perm:
                    t = max(t + T[prevn][x], win[x][0])
                    if t > win[x][1]:
                        ok = False
                        break
                    t += inst.svc[x]
                    prevn = x
                if not ok or t + T[prevn][0] > cfg.H:
                    continue
                d = T[0][perm[0]] + T[perm[-1]][0] + sum(T[a][b] for a, b in zip(perm, perm[1:]))
                if res is None or d < res:
                    res = d
        cache[key] = res
        return res

    choices = []
    for o, nodes, pen in groups:
        opts = [(n,) for n in nodes]
        if pen is not None:
            opts.append(())
        choices.append(opts)
    best = None
    for combo in itertools.product(*choices):
        chosen = [n for c in combo for n in c]
        for assign in itertools.product((0, 1), repeat=len(chosen)):
            v0 = [n for n, a in zip(chosen, assign) if a == 0]
            v1 = [n for n, a in zip(chosen, assign) if a == 1]
            c0, c1 = vcost(v0), vcost(v1)
            if c0 is None or c1 is None:
                continue
            profit = -cfg.c * (c0 + c1)
            for (o, nodes, pen), c in zip(groups, combo):
                if inst.is_sd[o]:
                    profit += inst.rev[o] if c else 0
                else:
                    if c:
                        profit += int(cfg.rev_mean)
                    elif o in ev_of and ev_of[o]["kind"] != "cancel":
                        profit -= cfg.pen
            if best is None or profit > best:
                best = profit
    return best


def check_bruteforce_tiny(n: int = 8, seeds=None, exact: bool = True) -> tuple:
    """Kleinstinstanzen mit Änderungen/Stornos (2 Fahrzeuge). Immer: keine Online-Politik liegt über dem exakten Optimum (Brute-Force),
    das OR-Tools-Orakel mit Warmstart liegt nicht unter der besten Online-Politik und nicht über dem exakten Optimum. exact=True (volles
    Bau-Gate): das Orakel (warm UND kalt) trifft das exakte Optimum; in der CI aus, weil die CI immer das neueste OR-Tools installiert."""
    done, gaps = 0, []
    used = []
    seed = 0
    todo = list(seeds) if seeds is not None else None
    while done < n and (seed < 400 if todo is None else todo):
        if todo is not None:
            seed = todo.pop(0)
            inst = tiny_instance(seed)
        else:
            inst = tiny_instance(seed)
            seed += 1
        if inst is None or not inst.events:
            continue
        opt = bruteforce_ev(inst)
        assert opt is not None
        runs = [run_events(inst, **spec) for _, spec in POLS]
        best = max(runs, key=lambda r: r["profit_total"])
        vals = []
        for r in runs:
            n_sd_fail = sum(1 for o in r["failed_orders"] if inst.is_sd[o])
            vals.append(r["profit_total"] + inst.cfg.pen * n_sd_fail)
        assert max(vals) <= opt, (seed, max(vals), opt)
        ow = oracle_ev(inst, warm=best["fleet"], time_limit=120, sol_limit=3000)
        assert ow["profit"] is not None and max(vals) <= ow["profit"] <= opt, (seed, "warm", ow["profit"], max(vals), opt)
        if exact:
            oc = oracle_ev(inst, warm=None, time_limit=120, sol_limit=3000)
            assert ow["profit"] == opt, (seed, "warm", ow["profit"], opt)
            assert oc["profit"] is not None and oc["profit"] == opt, (seed, "kalt", oc["profit"], opt)
        gaps.append(opt - max(vals))
        used.append(seed if todo is not None else seed - 1)
        done += 1
    return used, st.fmean(gaps)


def _ora_task(seed, small=False):
    cfg = replace(EV, K=2, n_m=14, lam=4.0) if not small else replace(EV, K=2, n_m=10, lam=3.0)
    inst = make_instance(cfg, seed)
    runs = [run_events(inst, **spec) for _, spec in POLS]
    best = max(runs, key=lambda r: r["profit_total"])
    o = oracle_ev(inst, warm=best["fleet"], time_limit=300 if not small else 60, sol_limit=800 if not small else 300)
    vals = [r["profit_total"] + inst.cfg.pen * sum(1 for x in r["failed_orders"] if inst.is_sd[x]) for r in runs]
    return seed, max(vals), o["profit"], o["warm_ok"], [v for v in vals]


def check_oracle_upper_bound(n: int = 12, base_seed: int = 500, small: bool = False, pool=None) -> float:
    """Orakel >= jede Online-Politik einzeln auf denselben Instanzen (Gewinn nach Orakel-Konvention, also ohne Sd-Ausfallstrafe),
    Online-Endpläne im Orakel-Modell zulässig (offline_profit_ev in check_invariants), Kosten konsistent."""
    seeds = range(base_seed, base_seed + n)
    if pool is not None:
        res = pool.starmap(_ora_task, [(s, small) for s in seeds])
    else:
        res = [_ora_task(s, small) for s in seeds]
    for seed, bestv, o, warm_ok, vals in res:
        assert warm_ok and o is not None and o >= bestv, (seed, o, bestv)
        assert all(o >= v for v in vals)
    return st.fmean(o - b for _, b, o, _, _ in res)
