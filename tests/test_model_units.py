"""Bausteine von nv_model und nv_sim an Handinstanzen: Parameter, Distanzen, Zeitrechnung (retime, bindender Präfix), Einfügen,
Zwischentouren (M > 1), Ereignisstrom, Annahmeregeln, Stabilitätszähler, Reparatur bei Änderungen, Validator, Orakel-Fenster.
Alles exakt und ganzzahlig; die Bitgleichheit ganzer Läufe steht in tests/test_frozen_reference.py."""
import dataclasses
import math
from dataclasses import replace

import pytest

import nv_model as M
import nv_sim as S
from nv_oracle import offline_profit_ev, order_windows

LINE = M.Cfg(K=1, n_m=0, lam=0.0, speed=1.0, svc=10, H=480, area=60.0, M=1)


def line_instance(cfg=LINE, xs=(40.0, 50.0, 60.0), a0=0, b0=400, route=None):
    """Depot (30, 30), Knoten auf der Geraden y = 30 bei x = xs; Plan: alle Knoten in der Reihenfolge `route` (Standard: 1, 2, ...)."""
    inst = M.make_instance(cfg, 0)
    nodes = [inst.add_node(x, 30.0, 1, a0, b0, 0, False) for x in xs]
    inst.n_orders_base = inst.n_morning = len(nodes)
    fl = M.Fleet(cfg.K)
    fl.routes[0] = list(route if route is not None else nodes)
    fl.S[0], fl.F[0] = M.retime(inst, fl.routes[0], [], [], 0, -1)
    inst.plan = fl
    return inst, nodes


# ---------------------------------------------------------------------------------------------------
# Parameter und Instanz
# ---------------------------------------------------------------------------------------------------
def test_cfg_defaults_are_the_measured_model():
    c = M.Cfg()
    assert (c.K, c.n_m, c.H, c.speed, c.svc, c.lam, c.t_arr, c.delta) == (3, 14, 480, 1.2, 6, 3.0, 300, 120)
    assert (c.sigma, c.rev_mean, c.conc, c.hot_sd, c.area, c.win_w) == (0.6, 60.0, 0.0, 5.0, 60.0, 180)
    assert (c.Q, c.dem_max, c.M, c.c, c.max_tries) == (M.TRIP_FALLBACK, 3, 1, 1, 80)
    assert (c.p_chg, c.p_cancel, c.w_time, c.w_addr, c.w_qty, c.chg_delta, c.addr_radius, c.pen) == (0.0, 0.0, 1.0, 1.0, 0.0, 30, 5.0, 60)
    assert M.TRIP_FALLBACK == 10 ** 9
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.K = 5


def test_new_instance_has_only_the_depot():
    inst = M.Inst(M.Cfg())
    assert inst.xy == [(30.0, 30.0)] and inst.T == [[0]] and inst.A == [0] and inst.B == [480] and inst.rev == [0] and inst.is_sd == [False]
    assert inst.order_of == [0] and inst.arrivals == [] and inst.events == [] and inst.plan is None


def test_add_node_distances_are_rounded_up_and_symmetric():
    inst = M.Inst(M.Cfg(speed=1.2))
    a = inst.add_node(40.0, 30.0, 2, 10, 300, 55, True)                   # 10 km -> 12 min
    b = inst.add_node(40.0, 40.0, 1, 0, 100, 0, False)                    # von a: 10 km -> 12; vom Depot hypot(10,10) = 14,14 -> 16,97 -> 17
    assert (inst.T[0][a], inst.T[a][0], inst.T[a][b], inst.T[b][a], inst.T[0][b], inst.T[b][0]) == (12, 12, 12, 12, 17, 17)
    assert inst.T[a][a] == 0 and inst.T[0][0] == 0 and len(inst.T) == 3 and all(len(r) == 3 for r in inst.T)
    assert (inst.svc[a], inst.dem[a], inst.A[a], inst.rev[a], inst.is_sd[a], inst.order_of[a]) == (6, 2, 10, 55, True, a)
    assert inst.B[a] == 300 and inst.B[b] == 100                          # Frist unter der Schichtgrenze bleibt
    same = inst.add_node(30.0, 30.0, 1, 0, 100, 0, False)                 # gleicher Ort wie das Depot: Mindestfahrzeit 1
    assert inst.T[0][same] == 1 and inst.T[same][0] == 1


def test_add_node_clips_the_deadline_to_the_shift_end():
    inst = M.Inst(M.Cfg(speed=1.0, svc=10, H=480))
    n = inst.add_node(40.0, 30.0, 1, 0, 1000, 0, False)                   # spätester Start: H - Rückfahrt (10) - Service (10) = 460
    assert inst.B[n] == 460


def test_pop_node_removes_everything_it_added():
    inst = M.Inst(M.Cfg())
    inst.add_node(40.0, 30.0, 1, 0, 100, 0, False)
    before = ([list(r) for r in inst.T], list(inst.xy), list(inst.order_of))
    n = inst.add_node(50.0, 30.0, 1, 0, 100, 0, False)
    assert inst.pop_node() == n
    assert ([list(r) for r in inst.T], list(inst.xy), list(inst.order_of)) == before
    for lst in (inst.svc, inst.dem, inst.A, inst.B, inst.rev, inst.is_sd):
        assert len(lst) == 2


def test_fleet_clone_is_deep():
    fl = M.Fleet(2)
    fl.routes[0], fl.S[0], fl.F[0] = [1, 2], [10, 20], [16, 26]
    c = fl.clone()
    assert c.routes == fl.routes and c.S == fl.S and c.F == fl.F
    c.routes[0].append(3)
    c.S[0][0] = 99
    c.F[1].append(1)
    assert fl.routes == [[1, 2], []] and fl.S == [[10, 20], []] and fl.F == [[16, 26], []]


def test_fleet_drive_vend_and_trips():
    inst, (A, B, C) = line_instance(route=None)
    fl = inst.plan
    assert M.fleet_drive(inst, fl) == 10 + 10 + 10 + 30                    # Depot-A 10, A-B 10, B-C 10, C-Depot 30
    assert M.fleet_drive(inst, M.Fleet(1)) == 0
    assert M.vend(inst, fl.routes[0], fl.F[0]) == fl.F[0][-1] + 30 and M.vend(inst, [], []) == 0
    assert M.n_trips([1, 2]) == 1 and M.n_trips([1, 0, 2]) == 2 and M.n_trips([]) == 1
    assert fl.S[0] == [10, 30, 50] and fl.F[0] == [20, 40, 60]


def test_trip_ok_capacity_and_depot_reset():
    inst = M.make_instance(replace(LINE, Q=5), 0)
    n = [inst.add_node(40.0, 30.0, d, 0, 400, 0, False) for d in (2, 2, 2)]
    assert M.trip_ok(inst, [n[0], n[1]]) is True                          # 4 <= 5
    assert M.trip_ok(inst, [n[0], n[1], n[2]]) is False                   # 6 > 5
    assert M.trip_ok(inst, [n[0], n[1], 0, n[2]]) is True                 # der Depotbesuch setzt die Ladung zurück
    assert M.trip_ok(inst, [n[0], n[1], 0, n[2], n[0], n[1]]) is False    # zweite Tour: 6 > 5
    assert M.trip_ok(M.make_instance(LINE, 0), [1, 2, 3]) is True         # ohne Kapazität immer wahr


# ---------------------------------------------------------------------------------------------------
# Zeitrechnung
# ---------------------------------------------------------------------------------------------------
def test_retime_waits_for_the_window_and_checks_deadlines():
    inst, (A, B, C) = line_instance(a0=100)                                # Fenster ab 100: Wartezeit
    S_, F_ = M.retime(inst, [A, B, C], [], [], 0, -1)
    assert S_ == [100, 120, 140] and F_ == [110, 130, 150]
    S2, F2 = M.retime(inst, [A, B, C], S_, F_, 1, -1)                      # Präfix bleibt, ab Position 1 neu
    assert S2 == [120, 140] and F2 == [130, 150]
    inst.B[B] = 119
    assert M.retime(inst, [A, B, C], [], [], 0, -1) is None                # Frist von B verletzt
    inst.B[B] = 120
    assert M.retime(inst, [A, B, C], [], [], 0, -1) is not None            # genau die Frist reicht
    assert M.retime(inst, [], [], [], 0, -1) == ([], [])


def test_retime_starts_no_earlier_than_now_and_respects_the_shift_end():
    inst, (A, B, C) = line_instance(a0=0)
    assert M.retime(inst, [A], [], [], 0, 50)[0] == [60]                   # Fahrzeug fährt frühestens bei t = 50 los: 50 + 10
    assert M.retime(inst, [A], [], [], 0, -1)[0] == [10]
    assert M.retime(inst, [A], [], [], 0, 5)[0] == [15]
    inst2, (A2, B2) = line_instance(xs=(40.0, 50.0))
    inst2.cfg = replace(inst2.cfg, H=59)
    assert M.retime(inst2, [A2, B2], [], [], 0, -1) is None                # Anfahrt 10, Service 10, 10, Service 10, Rückfahrt 20: 60 > 59
    inst2.cfg = replace(inst2.cfg, H=60)
    assert M.retime(inst2, [A2, B2], [], [], 0, -1) is not None            # 60 <= 60: genau das Schichtende reicht


def test_committed_prefix_boundary():
    inst, (A, B, C) = line_instance()                                      # S = [10, 30, 50], Anfahrt 10, 10, 10
    T = inst.T
    S_ = inst.plan.S[0]
    route = inst.plan.routes[0]
    assert [M.committed(T, route, S_, t) for t in (-1, 0, 1, 2)] == [0, 1, 1, 1]      # A: spätester Start 10 - 10 = 0
    assert M.committed(T, route, S_, 19) == 1 and M.committed(T, route, S_, 20) == 2  # B: S - T = 30 - 10 = 20
    assert M.committed(T, route, S_, 39) == 2 and M.committed(T, route, S_, 40) == 3
    assert M.committed(T, [], [], 10 ** 6) == 0


def test_pos_range():
    assert list(M.pos_range([], 0, [], 100)) == [0]
    assert list(M.pos_range([5, 6, 7], 1, [10, 20, 30], 5)) == [1, 2, 3]
    assert list(M.pos_range([5, 6, 7], 3, [10, 20, 30], 25)) == [3]        # alles bindend, aber das Fahrzeug fährt noch: anhängen möglich
    assert list(M.pos_range([5, 6, 7], 3, [10, 20, 30], 30)) == []         # schon zurück (F[-1] <= t) und keine Tour offen: keine Position
    assert list(M.pos_range([5, 6, 7], 3, [10, 20, 30], 31)) == []
    assert list(M.pos_range([5, 0], 2, [10, 20], 100)) == [2]              # letzter Knoten ist ein Depotbesuch: Anhängen bleibt erlaubt


# ---------------------------------------------------------------------------------------------------
# Einfügen
# ---------------------------------------------------------------------------------------------------
def test_candidates_costs_positions_and_feasibility():
    inst, (A, B) = line_instance(xs=(40.0, 60.0), a0=100)                  # A bei 40, B bei 60, Fenster ab 100
    X = inst.add_node(50.0, 30.0, 1, 1, 150, 40, True)                     # zwischen A und B auf der Geraden
    cs = M.candidates(inst, inst.plan, X, 1)
    by_pos = {c[5]: c for c in cs}
    assert set(by_pos) == {0, 1, 2}
    # dcost = T[prev][x] + T[x][nxt] - T[prev][nxt]: vor A 20 + 10 - 10, zwischen A und B 10 + 10 - 20, nach B 10 + 20 - 30
    assert (by_pos[0][0], by_pos[1][0], by_pos[2][0]) == (20, 0, 0)
    assert by_pos[1][2:7] == (A, B, 0, 1, False) and by_pos[0][2:4] == (0, A) and by_pos[2][2:4] == (B, 0)
    # A: Start 100 (Fenster), Ende 110; X: 110 + 10 = 120, Ende 130; B: 130 + 10 = 140 -> Endzeit 150 + 30 = 180 gegen 170 vorher: dend 10
    assert by_pos[1][1] == 10 and by_pos[1][7] == [120, 140] and by_pos[1][8] == [130, 150]
    best = min(cs, key=lambda c: (c[0], c[1], c[2], c[3]))
    assert best[5] == 1                                                    # Gleichstand mit "nach B" (dcost 0, dend 10): kleinerer Vorgänger
    inst.B[X] = 119                                                        # zwischen A und B beginnt X erst bei 120: nicht mehr machbar
    cs2 = M.candidates(inst, inst.plan, X, 1)
    assert {c[5] for c in cs2} == {0}


def test_candidates_respect_the_binding_prefix_and_capacity():
    inst, (A, B) = line_instance(xs=(40.0, 60.0), a0=0)                    # S = [10, 40]
    X = inst.add_node(50.0, 30.0, 1, 0, 400, 40, True)
    cs = M.candidates(inst, inst.plan, X, 15)                              # A ist bindend (S - T = 0 <= 15), B nicht (30 > 15)
    assert sorted(c[5] for c in cs) == [1, 2]
    cs = M.candidates(inst, inst.plan, X, 35)                              # beide bindend
    assert sorted(c[5] for c in cs) == [2]
    inst.cfg = replace(LINE, Q=1)                                          # jeder Auftrag Bedarf 1: die Tour mit 2 Aufträgen ist voll
    assert M.candidates(inst, inst.plan, X, 1) == []


def test_candidates_dend_is_the_extra_return_time():
    inst, (A, B) = line_instance(xs=(40.0, 60.0), a0=0)
    X = inst.add_node(40.0, 40.0, 1, 0, 400, 40, True)                     # abseits
    cs = {c[5]: c for c in M.candidates(inst, inst.plan, X, 1)}
    old_end = max(M.vend(inst, inst.plan.routes[0], inst.plan.F[0]), 1)
    for pos, c in cs.items():
        route = inst.plan.routes[0][:pos] + [X] + inst.plan.routes[0][pos:]
        S2, F2 = M.retime(inst, route, inst.plan.S[0][:pos], inst.plan.F[0][:pos], pos, 1)
        assert c[1] == F2[-1] + inst.T[route[-1]][0] - old_end
        assert (c[7], c[8]) == (S2, F2)


def test_second_trip_after_return_with_virtual_depot():
    cfg = replace(LINE, M=2)
    inst, (A,) = line_instance(cfg=cfg, xs=(40.0,), a0=0)                  # A: S = 10, F = 20, zurück im Depot bei 30
    X = inst.add_node(50.0, 30.0, 1, 0, 400, 40, True)
    assert M.candidates(inst, inst.plan, X, 29) == []                      # noch unterwegs, alles bindend: keine Position
    cs = M.candidates(inst, inst.plan, X, 30)                              # wieder im Depot: zweite Tour über einen eingebetteten Depotknoten
    assert len(cs) == 1 and cs[0][6] is True and cs[0][5] == 2
    fl = inst.plan.clone()
    M.apply_insertion(inst, fl, X, cs[0])
    assert fl.routes[0] == [A, 0, X] and fl.S[0] == [10, 30, 50] and fl.F[0] == [20, 30, 60]
    assert M.n_trips(fl.routes[0]) == 2
    # mit M = 1 gibt es die zweite Tour nicht
    inst1, (A1,) = line_instance(xs=(40.0,), a0=0)
    X1 = inst1.add_node(50.0, 30.0, 1, 0, 400, 40, True)
    assert M.candidates(inst1, inst1.plan, X1, 30) == []


def test_apply_insertion_updates_routes_and_times():
    inst, (A, B) = line_instance(xs=(40.0, 60.0), a0=0)
    X = inst.add_node(50.0, 30.0, 1, 0, 400, 40, True)
    fl = inst.plan.clone()
    cs = M.candidates(inst, fl, X, 1)
    best = min(cs, key=lambda c: (c[0], c[1], c[2], c[3]))
    M.apply_insertion(inst, fl, X, best)
    assert fl.routes[0] == [A, X, B] and fl.S[0] == [10, 30, 50] and fl.F[0] == [20, 40, 60]
    assert inst.plan.routes[0] == [A, B]                                    # die Ausgangsflotte bleibt unberührt


# ---------------------------------------------------------------------------------------------------
# Lokale Suche
# ---------------------------------------------------------------------------------------------------
def scrambled_line():
    """Ein Fahrzeug, Plan [C, A, B] auf der Geraden: eine Umordnung spart Fahrzeit."""
    inst, (A, B, C) = line_instance(a0=0)
    fl = M.Fleet(1)
    fl.routes[0] = [C, A, B]
    fl.S[0], fl.F[0] = M.retime(inst, fl.routes[0], [], [], 0, -1)
    return inst, fl, (A, B, C)


def test_local_search_saves_drive_time_and_is_idempotent():
    inst, fl, (A, B, C) = scrambled_line()
    before = M.fleet_drive(inst, fl)
    saved = M.local_search(inst, fl, -1)
    assert before == 30 + 20 + 10 + 20 and saved > 0
    assert M.fleet_drive(inst, fl) == before - saved and M.fleet_drive(inst, fl) == 10 + 10 + 10 + 30
    assert sorted(fl.routes[0]) == [A, B, C]                               # mehrere gleich lange Reihenfolgen (60) sind optimal
    assert M.local_search(inst, fl, -1) == 0                               # nur strikte Verbesserungen: kein weiterer Zug


def test_local_search_freeze_and_binding_prefix():
    inst, fl, (A, B, C) = scrambled_line()
    ref = fl.clone()
    assert M.local_search(inst, ref, -1, freeze=3) == 0 and ref.routes == fl.routes           # alles eingefroren
    ref = fl.clone()
    assert M.local_search(inst, ref, -1, freeze=1) >= 0 and ref.routes[0][0] == C             # der erste Stopp bleibt
    ref = fl.clone()
    assert M.committed(inst.T, fl.routes[0], fl.S[0], 40) == 2                                 # C und A bindend (S - T = 0 und 40), B frei
    assert M.local_search(inst, ref, 40) == 0 and ref.routes == fl.routes                     # ein freier Stopp: nichts zu gewinnen
    ref = fl.clone()
    assert M.local_search(inst, ref, 0) > 0 and ref.routes[0][0] == C                          # nur C bindend: A und B lassen sich umdrehen
    ref = fl.clone()
    assert M.local_search(inst, ref, -1, freeze_until=10 ** 6) == 0 and ref.routes == fl.routes  # zeitbasiert: alles eingefroren
    ref = fl.clone()
    assert M.local_search(inst, ref, -1, freeze_until=-1) > 0                                  # nichts eingefroren
    ref = fl.clone()
    assert M.local_search(inst, ref, -1, max_moves=0) == 0 and ref.routes == fl.routes         # Zuglimit


def test_local_search_change_penalty_blocks_moves_that_change_too_many_stops():
    inst, fl, (A, B, C) = scrambled_line()
    base = {}
    pred = 0
    for node in fl.routes[0]:
        base[node] = (0, pred)
        pred = node
    small, big = fl.clone(), fl.clone()
    saved = M.local_search(inst, small, -1, lam=1.0, base_pred=base)
    assert saved > 0 and M.fleet_drive(inst, small) == 60                  # Ersparnis 20 gegen höchstens 3 Änderungen x 1: erlaubt
    assert M.local_search(inst, big, -1, lam=100.0, base_pred=base) == 0 and big.routes == fl.routes
    excl = M.local_search(inst, fl.clone(), -1, lam=100.0, base_pred=base, excl=frozenset([A, B, C]))
    assert excl > 0                                                        # ausgenommene Knoten zählen nicht als Änderung


def two_vehicle_swap():
    """Zwei Fahrzeuge, beide fahren einmal nach rechts und einmal nach links; die Aufteilung ist verdreht."""
    cfg = replace(LINE, K=2, Q=2)                                          # höchstens zwei Stopps je Tour: eine Zusammenlegung ist ausgeschlossen
    inst = M.make_instance(cfg, 0)
    R1 = inst.add_node(50.0, 30.0, 1, 0, 400, 0, False)
    R2 = inst.add_node(55.0, 30.0, 1, 0, 400, 0, False)
    L1 = inst.add_node(10.0, 30.0, 1, 0, 400, 0, False)
    L2 = inst.add_node(5.0, 30.0, 1, 0, 400, 0, False)
    inst.n_orders_base = inst.n_morning = 4
    fl = M.Fleet(2)
    fl.routes[0], fl.routes[1] = [R1, L1], [L2, R2]
    for v in range(2):
        fl.S[v], fl.F[v] = M.retime(inst, fl.routes[v], [], [], 0, -1)
    inst.plan = fl
    return inst, fl, (R1, R2, L1, L2)


def test_local_search_moves_stops_between_vehicles():
    inst, fl, (R1, R2, L1, L2) = two_vehicle_swap()
    before = M.fleet_drive(inst, fl)
    saved = M.local_search(inst, fl, -1)
    assert saved > 0 and M.fleet_drive(inst, fl) == before - saved
    sides = sorted(sorted(r) for r in fl.routes)
    assert sides == sorted([sorted([R1, R2]), sorted([L1, L2])])           # ein Fahrzeug fährt rechts, eines links
    assert M.local_search(inst, fl, -1) == 0
    for v in range(2):
        assert (fl.S[v], fl.F[v]) == M.retime(inst, fl.routes[v], [], [], 0, -1)


# ---------------------------------------------------------------------------------------------------
# Instanzerzeugung und Ereignisstrom
# ---------------------------------------------------------------------------------------------------
def test_draw_order_floors_the_revenue_and_clips_the_hotspot():
    import random
    cfg = replace(M.Cfg(), sigma=5.0, conc=1.0, hot_sd=100.0)
    revs, xs = [], []
    for s in range(300):
        x, y, dm, rev = M.draw_order(cfg, random.Random(s), (30.0, 30.0))
        assert 0.0 <= x <= cfg.area and 0.0 <= y <= cfg.area and 1 <= dm <= cfg.dem_max
        revs.append(rev)
        xs.append(x)
    assert min(revs) == 5 and max(revs) > 60 and 0.0 in xs and cfg.area in xs      # Erlös nie unter 5; der Hotspot wird an den Rand geklemmt
    x, y, dm, rev = M.draw_order(M.Cfg(sigma=0.0, conc=0.0), random.Random(3), (30.0, 30.0))
    assert rev == 60 and 0 <= x <= 60                                        # ohne Streuung immer der Mittelwert


def test_same_day_stream_is_extended_by_a_higher_rate_not_redrawn():
    """Drei getrennte Zufallsströme: die Attribute der Same-Day-Aufträge stammen aus einem eigenen Strom, eine höhere Rate verlängert ihn nur."""
    lo, hi = M.make_instance(M.Cfg(K=3, n_m=40, lam=6.0), 0), M.make_instance(M.Cfg(K=3, n_m=40, lam=12.0), 0)
    attrs = lambda i: [(i.xy[x], i.dem[x], i.rev[x]) for _, x in i.arrivals]        # noqa: E731
    a_lo, a_hi = attrs(lo), attrs(hi)
    assert len(a_hi) > len(a_lo) > 0 and a_hi[:len(a_lo)] == a_lo
    assert lo.xy[:lo.n_morning + 1] == hi.xy[:hi.n_morning + 1] and lo.plan.routes == hi.plan.routes      # gleicher Morgenplan


def test_arrivals_are_inside_the_window_sorted_and_have_deadlines():
    inst = M.make_instance(M.Cfg(K=3, n_m=40, lam=6.0, delta=90), 3)
    times = [r for r, _ in inst.arrivals]
    assert times == sorted(times) and all(1 <= t <= 300 for t in times) and len(times) > 5
    for r, x in inst.arrivals:
        assert inst.A[x] == r and inst.is_sd[x] and inst.rev[x] >= 5 and inst.B[x] <= r + 90
        assert inst.B[x] == min(r + 90, 480 - inst.T[x][0] - inst.cfg.svc)
    assert M.make_instance(M.Cfg(K=3, n_m=40, lam=0.0), 3).arrivals == []


def test_make_events_use_the_configured_shift_radius_and_kinds():
    base = replace(M.Cfg(K=3, n_m=40, lam=6.0), p_chg=1.0, p_cancel=0.0)
    inst = M.make_instance(replace(base, chg_delta=15, w_addr=0.0), 1)
    times = [e for e in inst.events if e["kind"] == "time"]
    assert len(times) == len(inst.events) > 30 and not any(e["kind"] in ("addr", "qty", "cancel") for e in inst.events)
    for e in times:
        o, w = e["order"], e["var"]
        assert abs(inst.B[w] - inst.B[o]) == 15 or inst.B[w] == inst.A[w]      # beide Grenzen um chg_delta verschoben
        assert inst.A[w] - inst.A[o] in (15, -15) or (inst.A[o] < 15 and inst.A[w] == 0)
        assert inst.xy[w] == inst.xy[o] and inst.dem[w] == inst.dem[o]
    inst = M.make_instance(replace(base, addr_radius=2.0, w_time=0.0), 1)
    assert all(e["kind"] == "addr" for e in inst.events)
    for e in inst.events:
        o, w = e["order"], e["var"]
        assert math.hypot(inst.xy[w][0] - inst.xy[o][0], inst.xy[w][1] - inst.xy[o][1]) <= 2.0 + 1e-9
        assert (inst.A[w], inst.dem[w]) == (inst.A[o], inst.dem[o]) and 0 <= inst.xy[w][0] <= 60 and 0 <= inst.xy[w][1] <= 60
    inst = M.make_instance(replace(base, w_time=0.0, w_addr=0.0, w_qty=1.0, Q=40), 1)
    assert all(e["kind"] == "qty" for e in inst.events)
    for e in inst.events:
        o, w = e["order"], e["var"]
        assert 1 <= inst.dem[w] <= 5 and (inst.dem[w] != inst.dem[o] or inst.dem[o] in (1, 5))     # +-1 oder 2, geklemmt auf 1 bis dem_max + 2
    inst = M.make_instance(replace(base, p_chg=0.0, p_cancel=1.0), 1)
    assert all(e["kind"] == "cancel" and e["var"] is None for e in inst.events) and len(inst.events) > 30


def test_events_are_timed_before_the_planned_service_and_after_arrival():
    inst = M.make_instance(replace(M.Cfg(K=3, n_m=40, lam=6.0), p_chg=0.5, p_cancel=0.2), 4)
    plan_S = {n: s for r, ss in zip(inst.plan.routes, inst.plan.S) for n, s in zip(r, ss)}
    arr = {x: r for r, x in inst.arrivals}
    assert [e["t"] for e in inst.events] == sorted(e["t"] for e in inst.events)
    for e in inst.events:
        o = e["order"]
        if o in arr:
            assert arr[o] + 5 <= e["t"] <= arr[o] + 100
        else:
            assert 5 <= e["t"] <= max(5, plan_S[o] - 10) and e["t"] >= plan_S[o] - 10 - 190
    assert len({e["order"] for e in inst.events}) == len(inst.events)
    none = M.make_instance(M.Cfg(K=3, n_m=40, lam=6.0), 4)
    assert none.events == [] and len(none.xy) == len(inst.xy) - sum(1 for e in inst.events if e["var"] is not None)


def test_events_only_for_configured_probabilities():
    inst = M.make_instance(replace(M.Cfg(K=3, n_m=40, lam=6.0), p_chg=0.25, p_cancel=0.08), 2)
    assert 0 < len(inst.events) < inst.n_orders_base
    assert M.make_instance(replace(M.Cfg(K=3, n_m=40, lam=6.0), p_chg=0.25, p_cancel=0.08), 2).events == inst.events


# ---------------------------------------------------------------------------------------------------
# Annahmeregeln
# ---------------------------------------------------------------------------------------------------
def accept_instance(rev, extra_windows=(1, 400)):
    """Ein Fahrzeug fährt auf der Geraden nach A (40) und B (60); ein neuer Auftrag X bei (50, 30) trifft zur Zeit 1 ein (Umweg 0)."""
    inst, (A, B) = line_instance(xs=(40.0, 60.0), a0=0)
    X = inst.add_node(50.0, 40.0, 1, extra_windows[0], extra_windows[1], rev, True)      # Abstecher 10 km rechtwinklig: Umweg 2*10 = 20 min
    inst.arrivals = [(1, X)]
    return inst, X


def test_opp_weight_decays_with_the_expected_arrivals():
    cfg = M.Cfg()
    assert S.opp_weight(cfg, 0) == 1.0 and S.opp_weight(cfg, 150) == 0.5 and S.opp_weight(cfg, 300) == 0.0 and S.opp_weight(cfg, 450) == 0.0
    assert S.opp_weight(cfg, 75) == 0.75


def test_acceptance_rules_on_a_hand_instance():
    inst, X = accept_instance(rev=15)
    best = min(M.candidates(inst, inst.plan, X, 1), key=lambda c: (c[0], c[1], c[2], c[3]))
    extra = best[0]
    assert extra > 0
    p0 = S.simulate(inst, "P0")
    assert p0["n_acc"] == 0 and p0["accepted"] == [] and p0["profit"] == -M.fleet_drive(inst, inst.plan) and p0["n_feas"] == 0
    p1 = S.simulate(inst, "P1")
    assert p1["n_acc"] == 1 and p1["accepted"] == [X] and p1["rev"] == 15 and p1["profit"] == 15 - p1["drive"] and p1["n_feas"] == 1
    assert p1["drive"] == M.fleet_drive(inst, inst.plan) + extra
    assert S.simulate(inst, "P1p")["n_acc"] == (1 if 15 >= extra else 0)
    rev_lo, rev_hi = extra - 1, extra                                      # Erlös < Zusatzfahrt: P1p lehnt ab, Erlös = Zusatzfahrt: nimmt an
    lo, _ = accept_instance(rev_lo)
    hi, _ = accept_instance(rev_hi)
    assert S.simulate(lo, "P1p")["n_acc"] == 0 and S.simulate(hi, "P1p")["n_acc"] == 1
    assert S.simulate(lo, "P1")["n_acc"] == 1                              # P1 nimmt auch das Verlustgeschäft an


def test_threshold_rules_p2v_p2m_p2_and_p2c():
    inst, X = accept_instance(rev=100)
    cs = M.candidates(inst, inst.plan, X, 1)
    best = min(cs, key=lambda c: (c[0], c[1], c[2], c[3]))
    extra, dend = best[0], best[1]
    assert S.simulate(inst, "P2v", rho=100.0)["n_acc"] == 1 and S.simulate(inst, "P2v", rho=100.01)["n_acc"] == 0     # Erlösniveau
    assert S.simulate(inst, "P2m", rho=100.0 - extra)["n_acc"] == 1 and S.simulate(inst, "P2m", rho=100.0 - extra + 0.01)["n_acc"] == 0
    # P2: Erlös >= Kosten + mu * w(t) * Zusatz-Rückkehrzeit, w(1) = 1 - 1/300
    w = 1.0 - 1.0 / 300.0
    mu_ok = (100.0 - extra) / (w * dend)
    assert S.simulate(inst, "P2", mu=mu_ok - 0.01)["n_acc"] == 1 and S.simulate(inst, "P2", mu=mu_ok + 0.01)["n_acc"] == 0
    assert S.simulate(inst, "P2c", mu=(100.0 - extra) / dend - 0.01)["n_acc"] == 1 and S.simulate(inst, "P2c", mu=(100.0 - extra) / dend + 0.01)["n_acc"] == 0
    assert S.simulate(inst, "P2", mu=0.0)["n_acc"] == 1 and S.simulate(inst, "P2", mu=0.0)["accepted"] == [X]
    with pytest.raises(AssertionError):
        S.simulate(inst, "P9")


def test_infeasible_arrivals_are_rejected_and_logged():
    inst, X = accept_instance(rev=100, extra_windows=(1, 2))               # Frist 2: nicht erreichbar
    r = S.simulate(inst, "P1", log=True)
    assert r["n_acc"] == 0 and r["n_feas"] == 0 and r["events"] == [(1, X, "infeasible", None, None)]
    inst, X = accept_instance(rev=100)
    r = S.simulate(inst, "P1p", log=True)
    (t, x, verdict, best, ties), = r["events"]
    assert (t, x, verdict) == (1, X, "accept") and best[0] > 0 and ties >= 1
    assert len(r["snaps"]) == 1 and r["snaps"][0][0] == 1
    r = S.simulate(accept_instance(rev=1)[0], "P1p", log=True)
    assert r["events"][0][2] == "reject"


def test_decide_matches_simulate_and_reports_the_candidate_count():
    inst, X = accept_instance(rev=100)
    for kind, kw in (("P1", {}), ("P1p", {}), ("P2", dict(mu=2.0)), ("P2v", dict(rho=50.0)), ("P2m", dict(rho=20.0)), ("P2c", dict(mu=1.0))):
        ok, best, n = S.decide(inst, inst.plan.clone(), X, 1, kind, **kw)
        assert ok == (S.simulate(inst, kind, **kw)["n_acc"] == 1) and n == len(M.candidates(inst, inst.plan, X, 1)) and best is not None
    inst2, X2 = accept_instance(rev=100, extra_windows=(1, 2))
    assert S.decide(inst2, inst2.plan.clone(), X2, 1, "P1") == (False, None, 0)


def test_simulate_with_local_search_never_loses_drive_time():
    inst = M.make_instance(M.Cfg(K=3, n_m=40, lam=6.0), 5)
    plain, ls = S.simulate(inst, "P1p"), S.simulate(inst, "P1p", ls=True)
    assert ls["ls_calls"] == ls["n_acc"] and plain["ls_calls"] == 0 and ls["ls_saved"] >= 0 and plain["ls_saved"] == 0
    M.validate(inst, plain["fleet"], plain["accepted"])
    M.validate(inst, ls["fleet"], ls["accepted"])
    assert plain["profit"] == M.profit_of(inst, plain["fleet"]) and ls["profit"] == M.profit_of(inst, ls["fleet"])
    assert plain["profit"] == plain["rev"] - plain["drive"] and plain["rev"] == sum(inst.rev[x] for x in plain["accepted"])


def test_simulate_vehicle_order_and_custom_arrivals():
    inst = M.make_instance(M.Cfg(K=3, n_m=40, lam=6.0), 5)
    rev_order = S.simulate(inst, "P1p", vehicle_order=[2, 1, 0])
    base = S.simulate(inst, "P1p")
    assert rev_order["profit"] == base["profit"] and rev_order["accepted"] == base["accepted"]    # billigste Einfügung, eindeutiger Tie-Break
    few = S.simulate(inst, "P1", arrivals=inst.arrivals[:3])
    assert few["n_feas"] <= 3 and set(few["accepted"]) <= {x for _, x in inst.arrivals[:3]}


def test_rollout_is_consistent_and_restores_the_instance():
    inst = M.make_instance(M.Cfg(K=3, n_m=16, lam=4.0), 2)
    n_nodes = len(inst.T)
    r = S.simulate_rollout(inst, S=4)
    assert len(inst.T) == n_nodes and len(inst.xy) == n_nodes                # die Szenarioknoten sind wieder entfernt
    M.validate(inst, r["fleet"], r["accepted"])
    assert r["profit"] == r["rev"] - r["drive"] and r["n_feas"] == 0 and set(r["accepted"]) <= {x for _, x in inst.arrivals}
    assert S.simulate_rollout(inst, S=4)["profit"] == r["profit"]           # deterministisch
    assert S.simulate_rollout(inst, S=4, ls=True)["ls_saved"] >= 0
    zero = M.make_instance(M.Cfg(K=3, n_m=16, lam=0.0), 2)
    assert S.simulate_rollout(zero, S=4)["accepted"] == []


# ---------------------------------------------------------------------------------------------------
# Validator und Gewinn
# ---------------------------------------------------------------------------------------------------
def test_validate_accepts_valid_and_rejects_broken_plans():
    inst = M.make_instance(M.Cfg(K=3, n_m=16, lam=4.0), 2)
    r = S.simulate(inst, "P1p")
    M.validate(inst, r["fleet"], r["accepted"])

    def broken(mutate):
        fl = r["fleet"].clone()
        mutate(fl)
        with pytest.raises(AssertionError):
            M.validate(inst, fl, r["accepted"])

    v = next(v for v, rt in enumerate(r["fleet"].routes) if len(rt) >= 3)
    broken(lambda fl: fl.S[v].__setitem__(1, fl.S[v][1] - 1000))            # Fahrzeit unterschritten / vor Fensterbeginn
    broken(lambda fl: fl.F[v].__setitem__(0, fl.F[v][0] + 1))               # F != S + Service
    broken(lambda fl: fl.routes[v].pop())                                   # ein Auftrag fehlt (Abdeckung)
    broken(lambda fl: fl.routes[v].append(fl.routes[v][0]))                 # ein Auftrag doppelt
    broken(lambda fl: fl.S[v].__setitem__(0, inst.B[fl.routes[v][0]] + 1))  # Frist verletzt
    rejected = [x for _, x in inst.arrivals if x not in r["accepted"]]
    assert rejected and r["accepted"]
    with pytest.raises(AssertionError):
        M.validate(inst, r["fleet"], r["accepted"] + rejected[:1])          # ein angeblich angenommener Auftrag fehlt im Plan
    with pytest.raises(AssertionError):
        M.validate(inst, r["fleet"], r["accepted"][:-1])                    # ein bedienter Auftrag gilt nicht als angenommen
    tight = replace(inst.cfg, H=100)
    inst.cfg = tight                                                        # Schichtende verletzt
    with pytest.raises(AssertionError):
        M.validate(inst, r["fleet"], r["accepted"])


def test_profit_of_counts_only_same_day_revenue():
    inst, X = accept_instance(rev=100)
    r = S.simulate(inst, "P1")
    assert M.profit_of(inst, r["fleet"]) == 100 - r["drive"] == r["profit"]
    assert M.profit_of(inst, inst.plan) == -M.fleet_drive(inst, inst.plan)


def test_fleet_to_trips_and_offline_profit():
    cfg = replace(LINE, M=2)
    inst, (A,) = line_instance(cfg=cfg, xs=(40.0,), a0=0)
    X = inst.add_node(50.0, 30.0, 1, 0, 400, 40, True)
    fl = M.Fleet(1)
    fl.routes[0] = [A, 0, X]
    assert M.fleet_to_trips(inst, fl) == [[A], [X]]
    fl.routes[0] = [A]
    assert M.fleet_to_trips(inst, fl) == [[A], []]
    # Gewinn einer Offline-Lösung: Erlös 40 - Fahrminuten (Depot-A-Depot 20, Depot-X-Depot 40)
    assert M.offline_profit(inst, [[A], [X]]) == 40 - (20 + 40)
    assert M.offline_profit(inst, [[A, X], []]) == 40 - (10 + 10 + 20)
    with pytest.raises(AssertionError):
        M.offline_profit(inst, [[X], []])                                   # Morgenauftrag A fehlt
    inst.B[X] = 20
    with pytest.raises(AssertionError):
        M.offline_profit(inst, [[A, X], []])                                # Frist von X verletzt (Ankunft 30)


# ---------------------------------------------------------------------------------------------------
# Ereignissimulation: Zähler, Reparatur, Orakel-Fenster
# ---------------------------------------------------------------------------------------------------
def test_snapshot_and_count_changes():
    inst, (A, B, C) = line_instance()
    fl = inst.plan
    pre = S.snapshot(inst, fl, -1, set())
    assert pre == {A: (0, 0), B: (0, A), C: (0, B)}
    pre = S.snapshot(inst, fl, 12, set())                                   # A ist bindend (S - T = 0 <= 12), B nicht (S - T = 20)
    assert pre == {B: (0, A), C: (0, B)}
    assert S.snapshot(inst, fl, -1, {B}) == {A: (0, 0), C: (0, A)}         # der Ereignisauftrag fehlt, auch als Vorgänger
    swapped = fl.clone()
    swapped.routes[0] = [A, C, B]
    pre = S.snapshot(inst, fl, -1, set())
    assert S.count_changes(inst, swapped, pre, set()) == 2                  # C und B haben neue Vorgänger
    assert S.count_changes(inst, fl, pre, set()) == 0
    assert S.count_changes(inst, swapped, pre, {B}) == 1                    # B ausgenommen: nur C hat einen neuen Vorgänger (A statt B)
    gone = fl.clone()
    gone.routes[0] = [A, B]
    assert S.count_changes(inst, gone, pre, set()) == 0                     # entfernte Stopps zählen nicht als geändert


def test_locate_remove_and_apply_change():
    inst, (A, B, C) = line_instance()
    fl = inst.plan.clone()
    assert S.locate(fl, B) == (0, 1) and S.locate(fl, 99) is None
    S.remove_at(inst, fl, 0, 1, -1)
    assert fl.routes[0] == [A, C] and fl.S[0] == [10, 40] and fl.F[0] == [20, 50]
    # Änderung: Variante von B mit neuem Fenster; an derselben Stelle möglich
    inst2, (A, B, C) = line_instance()
    fl = inst2.plan.clone()
    Bv = inst2.add_node(50.0, 30.0, 1, 0, 400, 0, False)
    assert S.apply_change(inst2, fl, 0, 1, Bv, -1) is True and fl.routes[0] == [A, Bv, C] and fl.S[0] == [10, 30, 50]
    # Variante mit Frist, die an derselben Stelle nicht mehr reicht, aber an anderer (vor A): billigste Einfügung anderswo
    fl = inst2.plan.clone()
    Bw = inst2.add_node(50.0, 30.0, 1, 0, 25, 0, False)                     # bis 25: nach A (S=10..20) wäre B erst bei 30
    assert S.apply_change(inst2, fl, 0, 1, Bw, -1) is True
    assert sorted(fl.routes[0]) == sorted([A, Bw, C]) and fl.routes[0][0] == Bw and fl.S[0][0] <= 25
    # nirgends möglich: gescheitert, der Auftrag ist entfernt
    fl = inst2.plan.clone()
    Bx = inst2.add_node(50.0, 30.0, 1, 0, 5, 0, False)
    assert S.apply_change(inst2, fl, 0, 1, Bx, -1) is False and fl.routes[0] == [A, C]


def test_node_s_maps_nodes_to_service_starts():
    inst, (A, B, C) = line_instance()
    assert S.node_S(inst.plan) == {A: 10, B: 30, C: 50}


def test_eta_tolerance_is_fifteen_minutes():
    """Ein neuer Auftrag X zwischen Z und Q auf der Geraden (ohne Umweg) verschiebt die angesagte Zeit von Q um genau die Servicezeit:
    15 min zählen nicht, 16 min zählen als geänderte Ansage (b)."""
    for svc, expected_b in ((15, 0), (16, 1)):
        cfg = replace(LINE, svc=svc)
        inst, (Z, Q) = line_instance(cfg=cfg, xs=(40.0, 50.0), a0=0)
        X = inst.add_node(45.0, 30.0, 1, 1, 400, 100, True)
        inst.arrivals = [(1, X)]
        r = S.run_events(inst, "S0")
        assert r["fleet"].routes[0] == [Z, X, Q] and r["n_acc"] == 1, svc
        assert r["b"] == expected_b and r["a"] == 0 and r["c"] == 0, svc
    assert S.ETA_TOL == 15


def test_run_events_counters_and_policy_call_counts():
    inst = M.make_instance(replace(M.Cfg(K=3, n_m=40, lam=6.0), p_chg=0.25, p_cancel=0.08), 6)
    s0, r = S.run_events(inst, "S0"), S.run_events(inst, "R")
    def processed(x):
        return x["n_acc"] + x["n_cancel"] + x["n_change"]                     # wirksam bearbeitete Ereignisse (ignorierte ausgenommen)
    assert s0["ls_calls"] == 0 and r["ls_calls"] == processed(r) > 0
    assert r["n_cancel"] + r["n_change"] + r["n_ign"] == len(inst.events) and r["n_acc"] == len(r["accepted"])
    assert sum(r["by_kind"].values()) == r["n_cancel"] + r["n_change"] and r["by_kind"]["cancel"] == r["n_cancel"]
    t0 = S.run_events(inst, "T", T_per=0)
    assert S.run_events(inst, "T", T_per=10 ** 9)["ls_calls"] == 0 and t0["ls_calls"] == processed(t0) and t0["fleet"].routes == r["fleet"].routes
    t60 = S.run_events(inst, "T", T_per=60)
    assert 0 < t60["ls_calls"] <= 8
    for x in (S.run_events(inst, "F", k=3), S.run_events(inst, "H", H_min=60), S.run_events(inst, "P", lam=1.0)):
        assert x["ls_calls"] == processed(x) > 0
    assert s0["n_morning_served"] + s0["n_served_sd"] == sum(len(rt) for rt in s0["fleet"].routes)
    assert s0["profit_total"] == s0["profit"] + int(inst.cfg.rev_mean) * s0["n_morning_served"]
    assert s0["profit"] == s0["rev"] - s0["drive"] - inst.cfg.pen * s0["n_fail"]
    with pytest.raises(AssertionError):
        S.run_events(inst, "X9")


def test_run_events_without_arrival_rejections_being_events():
    """Abgelehnte neue Aufträge erscheinen nicht im Protokoll; angenommene mit Zähler (a, b)."""
    inst = M.make_instance(replace(M.Cfg(K=3, n_m=40, lam=6.0), p_chg=0.25, p_cancel=0.08), 6)
    r = S.run_events(inst, "R", log=True)
    kinds = [t[1] for t in r["trace"]]
    assert kinds.count("new") == r["n_acc"] and kinds.count("ev") == r["n_cancel"] + r["n_change"]
    assert [t[0] for t in r["trace"]] == sorted(t[0] for t in r["trace"]) and sum(t[3] for t in r["trace"]) == r["a"]
    assert sum(t[4] for t in r["trace"]) == r["b"] and len(r["snaps"]) >= len(r["trace"])


def test_order_windows_and_offline_profit_of_events():
    inst, (Z, Q) = line_instance(xs=(40.0, 50.0), a0=0)
    inst.events = [dict(t=100, kind="cancel", order=Z, var=None)]
    win, groups = order_windows(inst)
    tcap = max(inst.T[j][Z] for j in range(len(inst.T)))
    assert win[Z] == (inst.A[Z], min(inst.B[Z], 100 + tcap)) and win[Q] == (inst.A[Q], inst.B[Q])
    assert groups == [(Z, [Z], 60), (Q, [Q], None)]                         # ein stornierter Morgenauftrag: Pflicht entfällt für 60 (Erlös)
    Zv = inst.add_node(40.0, 30.0, 1, 0, 400, 0, False)
    inst.order_of[Zv] = Z
    inst.events = [dict(t=100, kind="time", order=Z, var=Zv)]
    win, groups = order_windows(inst)
    assert win[Zv] == (max(inst.A[Zv], 100), inst.B[Zv]) and groups[0] == (Z, [Z, Zv], 60 + inst.cfg.pen)
    # Gewinn im Orakel-Modell: beide Morgenaufträge bedient: 2 x 60 - Fahrt (10 + 10 + 20)
    assert offline_profit_ev(inst, [[Z, Q]]) == 120 - 40 and offline_profit_ev(inst, [[Zv, Q]]) == 120 - 40
    assert offline_profit_ev(inst, [[Q]]) == 60 - 40 - inst.cfg.pen                # Z (geändert) nicht bedient: Strafe 60
    inst.events = [dict(t=100, kind="cancel", order=Z, var=None)]
    assert offline_profit_ev(inst, [[Q]]) == 60 - 40                               # Z storniert: keine Strafe, nur der Erlös von Q entfällt nicht
    with pytest.raises(AssertionError):
        offline_profit_ev(inst, [[Z, Z]])                                           # ein Auftrag doppelt
    with pytest.raises(AssertionError):
        offline_profit_ev(inst, [[Z]])                                              # Q (Morgenauftrag ohne Ereignis) fehlt


def test_runs_are_deterministic_and_do_not_change_the_instance():
    """Zwei Läufe über dieselbe Instanz liefern dieselben Routen und Zähler; die Instanz (Plan, Knoten) bleibt unverändert."""
    inst = M.make_instance(replace(M.Cfg(K=3, n_m=40, lam=6.0), p_chg=0.25, p_cancel=0.08), 6)
    plan_before = [r[:] for r in inst.plan.routes]
    n_nodes = len(inst.T)
    for spec in (dict(kind="S0"), dict(kind="R"), dict(kind="P", lam=1.5), dict(kind="F", k=3), dict(kind="T", T_per=60), dict(kind="H", H_min=60)):
        a, b = S.run_events(inst, **spec), S.run_events(inst, **spec)
        assert a["fleet"].routes == b["fleet"].routes and all(a[k] == b[k] for k in ("profit_total", "a", "b", "c", "n_acc", "n_fail", "ls_saved"))
    assert inst.plan.routes == plan_before and len(inst.T) == n_nodes
    s1, s2 = S.simulate(inst, "P2", mu=2.0, ls=True), S.simulate(inst, "P2", mu=2.0, ls=True)
    assert s1["profit"] == s2["profit"] and s1["accepted"] == s2["accepted"]
