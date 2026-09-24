"""Morgenplan mit dem ECHTEN OR-Tools (Fixture `real_ortools`, eigener Zwischenspeicher): NUR Invarianten, keine exakten Routen. Die CI installiert
immer das neueste OR-Tools, und Morgenpläne können sich zwischen Versionen ändern; alle anderen Tests rechnen deshalb auf eingefrorenen Plänen."""
import os
from dataclasses import replace

import pytest

import conftest
import nv_model as M
import nv_oracle as O
from nv_sim import run_events

pytestmark = pytest.mark.usefixtures("real_ortools")

CFG = M.Cfg(K=3, n_m=16, lam=4.0)


def heuristic_only(cfg, seed):
    """Der Morgenplan ohne OR-Tools (Einfüge-Heuristik plus lokale Suche) als Vergleich."""
    orig = M.oracle
    try:
        M.oracle = lambda *a, **k: dict(profit=None)
        M._MORNING_CACHE.clear()
        nodes, routes, shortfall = M.build_morning(cfg, seed)
    finally:
        M.oracle = orig
        M._MORNING_CACHE.clear()
    return nodes, routes, shortfall


def test_morning_plan_is_valid_and_not_worse_than_the_heuristic():
    nodes, routes, shortfall = M.build_morning(CFG, 5)
    assert len(nodes) + shortfall == CFG.n_m and len(routes) == CFG.K
    covered = sorted(n for r in routes for n in r)
    assert covered == list(range(1, len(nodes) + 1))                                  # jeder Morgenauftrag genau einmal
    inst = M.make_instance(CFG, 5)
    M.validate(inst, inst.plan, [])                                                   # Zeiten, Fenster, Schichtende, Kapazität
    h_nodes, h_routes, h_short = heuristic_only(CFG, 5)
    assert h_nodes == nodes and h_short == shortfall                                  # dieselben Aufträge, nur die Touren können sich unterscheiden
    drive = M.fleet_drive(inst, inst.plan)
    fl = M.Fleet(CFG.K)
    fl.routes = [r[:] for r in h_routes]
    for v, r in enumerate(fl.routes):
        fl.S[v], fl.F[v] = M.retime(inst, r, [], [], 0, -1)
    assert drive <= M.fleet_drive(inst, fl)                                           # OR-Tools ersetzt den Plan nur, wenn er kürzer ist


def test_morning_plan_is_deterministic_within_a_run_and_cached_in_memory():
    first = M.build_morning(CFG, 6)
    assert M.build_morning(CFG, 6) is first                                           # Zwischenspeicher im Speicher
    M._MORNING_CACHE.clear()
    again = M.build_morning(CFG, 6)
    assert again == first                                                             # dieselbe Lösungszahl, dasselbe Ergebnis
    key = M._morning_key(CFG, 6)
    assert key == (3, 16, 480, 1.2, 6, 180, 60.0, 3, 1, 1, M.TRIP_FALLBACK, 80, 6)
    assert M._morning_key(replace(CFG, lam=99.0, delta=10, p_chg=0.5, sigma=2.0), 6) == key       # Same-Day-Parameter und Ereignisse gehören nicht zum Schlüssel
    assert M._morning_key(replace(CFG, n_m=17), 6) != key and M._morning_key(replace(CFG, K=2), 6) != key and M._morning_key(replace(CFG, Q=30), 6) != key


def test_disk_cache_is_off_by_default_and_works_when_switched_on(tmp_path, monkeypatch):
    assert M.MORNING_DISK_CACHE is None and M._disk_path(("x",)) is None
    monkeypatch.setattr(M, "MORNING_DISK_CACHE", str(tmp_path / "cache"))
    first = M.build_morning(CFG, 7)
    files = list((tmp_path / "cache").glob("*.pkl"))
    assert len(files) == 1 and files[0].name == M._disk_path(M._morning_key(CFG, 7)).split(os.sep)[-1]
    M._MORNING_CACHE.clear()
    assert M.build_morning(CFG, 7) == first                                           # aus der Datei geladen
    monkeypatch.setattr(M, "oracle", lambda *a, **k: (_ for _ in ()).throw(AssertionError("kein OR-Tools nötig: der Plan liegt auf der Platte")))
    M._MORNING_CACHE.clear()
    assert M.build_morning(CFG, 7) == first
    files[0].write_bytes(b"kaputt")                                                   # beschädigte Datei: neu rechnen statt abstürzen
    monkeypatch.setattr(M, "oracle", conftest._REAL_ORACLE)
    M._MORNING_CACHE.clear()
    assert M.build_morning(CFG, 7) == first


def test_disk_cache_is_never_touched_when_off(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    M.build_morning(CFG, 8)
    assert list(tmp_path.iterdir()) == []                                             # die App schreibt nichts auf die Festplatte


def test_oracle_returns_a_feasible_offline_solution_and_never_loses_to_the_warm_start():
    inst = M.make_instance(replace(M.Cfg(K=2, n_m=6, lam=3.0), delta=150), 3)
    from nv_sim import simulate
    online = simulate(inst, "P1p")
    o = M.oracle(inst, warm=online["fleet"], time_limit=20, sol_limit=300)
    assert o["status"] == "ok" and o["warm_ok"] is True and o["profit"] is not None
    assert o["profit"] >= online["profit"]                                            # Warmstart: nie schlechter als die Online-Lösung
    assert M.offline_profit(inst, o["routes"]) == o["profit"]
    assert o["n_served_sd"] == sum(1 for r in o["routes"] for n in r if inst.is_sd[n])
    served = sorted(n for r in o["routes"] for n in r)
    assert set(range(1, inst.n_morning + 1)) <= set(served) and len(served) == len(set(served))
    mand = M.oracle(inst, warm=online["fleet"], time_limit=20, sol_limit=300, mandatory=set(online["accepted"]))
    assert mand["profit"] is not None and set(online["accepted"]) <= {n for r in mand["routes"] for n in r}


def test_hindsight_oracle_with_changes_is_an_upper_bound_of_the_online_policies():
    from nv_checks import POLS
    cfg = M.Cfg(K=2, n_m=3, lam=1.0, M=1, t_arr=300, delta=150, max_tries=200, p_chg=0.5, p_cancel=0.15)
    inst = M.make_instance(cfg, 7)
    runs = [run_events(inst, **spec) for _, spec in POLS]
    best = max(runs, key=lambda r: r["profit_total"])
    vals = [r["profit_total"] + cfg.pen * sum(1 for x in r["failed_orders"] if inst.is_sd[x]) for r in runs]
    o = O.oracle_ev(inst, warm=best["fleet"], time_limit=60, sol_limit=500)
    assert o["warm_ok"] and o["profit"] is not None and o["profit"] >= max(vals)
    win, groups = O.order_windows(inst)
    assert O.offline_profit_ev(inst, o["routes"]) == o["profit"] and len(groups) == inst.n_orders_base
    inst.cfg = replace(inst.cfg, M=2)                                                 # das Orakel mit Änderungen kennt nur eine Tour je Fahrzeug
    with pytest.raises(AssertionError):
        O.oracle_ev(inst, warm=None)
