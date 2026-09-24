"""Hindsight-Orakel mit Aenderungen und Stornos (OR-Tools): alle Ereignisse vorab bekannt, Prize-Collecting-VRPTW.

MECHANISCH aus messreihe_stabilitaet/stab.py uebernommen (Zeilen 1238-1384), Logik unveraendert. NUR fuer die Reproduktion der
Messreihe (tools/sweep.py) und die Tests; die App rechnet das Orakel nie live (25 bis 70 s je Instanz), sie zeigt die vorgerechneten
Zahlen aus data/nv_results.json. OR-Tools wird erst in oracle_ev importiert."""

from __future__ import annotations

from nv_model import TRIP_FALLBACK, Fleet, Inst

# ------------------------------------------------------------------ Hindsight-Orakel mit Aenderungen

def order_windows(inst: Inst):
    """Fuer jeden Knoten die Fenster im Orakel-Modell (Relaxation aller Online-Ergebnisse). Rueckgabe:
    win[node] = (a, b); groups = Liste (Auftrag, [Knoten], Strafe fuer Nichtbedienen; None = Pflicht)."""
    cfg = inst.cfg
    N = len(inst.T)
    ev_of = {e["order"]: e for e in inst.events}
    win = {}
    groups = []
    rev_m = int(cfg.rev_mean)
    for o in range(1, inst.n_orders_base + 1):
        e = ev_of.get(o)
        if e is None:
            win[o] = (inst.A[o], inst.B[o])
            groups.append((o, [o], None if not inst.is_sd[o] else inst.rev[o]))
            continue
        tcap = max(inst.T[j][o] for j in range(N))
        win[o] = (inst.A[o], min(inst.B[o], e["t"] + tcap))      # Ursprungsversion nur, wenn vor der Aenderung bindend
        if e["kind"] == "cancel":
            groups.append((o, [o], inst.rev[o] if inst.is_sd[o] else rev_m))
        else:
            w = e["var"]
            win[w] = (max(inst.A[w], e["t"]), inst.B[w])          # Variantenversion erst ab dem Ereigniszeitpunkt
            groups.append((o, [o, w], inst.rev[o] if inst.is_sd[o] else rev_m + cfg.pen))
    return win, groups


def offline_profit_ev(inst: Inst, vroutes) -> int:
    """Gewinn (profit_total-Konvention) einer Offline-Loesung, unabhaengig nachgerechnet und auf Machbarkeit im
    Orakel-Modell geprueft (fruehester Zeitplan je Tour, Fenster aus order_windows)."""
    cfg = inst.cfg
    T = inst.T
    win, groups = order_windows(inst)
    rev_sd = 0
    n_m = 0
    drive = 0
    served_orders = {}
    for v, trip in enumerate(vroutes):
        if not trip:
            continue
        t = 0
        prevn = 0
        for x in trip:
            t = max(t + T[prevn][x], win[x][0])
            assert t <= win[x][1], ("Fenster", x, t, win[x])
            t += inst.svc[x]
            drive += T[prevn][x]
            prevn = x
            served_orders.setdefault(inst.order_of[x], []).append(x)
        drive += T[prevn][0]
        assert t + T[prevn][0] <= cfg.H, "Schichtende"
        cap = sum(inst.dem[x] for x in trip)
        assert cap <= cfg.Q, "Kapazitaet"
    ev_of = {e["order"]: e for e in inst.events}
    pen_total = 0
    for o, nodes in served_orders.items():
        assert len(nodes) == 1, ("Auftrag doppelt bedient", o, nodes)
    for o in range(1, inst.n_orders_base + 1):
        got = served_orders.get(o)
        if inst.is_sd[o]:
            if got:
                rev_sd += inst.rev[o]
        else:
            if got:
                n_m += 1
            else:
                e = ev_of.get(o)
                assert e is not None, ("Morgenauftrag ohne Ereignis nicht bedient", o)
                if e["kind"] != "cancel":
                    pen_total += cfg.pen
    return rev_sd + int(cfg.rev_mean) * n_m - cfg.c * drive - pen_total


def oracle_ev(inst: Inst, warm: Fleet | None = None, time_limit: float = 600.0, sol_limit: int | None = 800,
              first: str = "PATH_CHEAPEST_ARC"):
    """Hindsight-Orakel mit Aenderungen (nur M = 1): alle Ereignisse vorab bekannt. Jede Ausfuehrung eines Online-Laufs ist
    eine zulaessige Loesung: Ursprungsversion eines Auftrags nur mit Servicebeginn <= Ereigniszeit + max. Anfahrtszeit
    (war dann bindend), Variantenversion nur ab Ereigniszeit; hoechstens eine Version je Auftrag (Disjunktion)."""
    from ortools.constraint_solver import pywrapcp, routing_enums_pb2

    cfg = inst.cfg
    assert cfg.M == 1
    N = len(inst.T)
    K = cfg.K
    win, groups = order_windows(inst)
    mgr = pywrapcp.RoutingIndexManager(N, K, 0)
    routing = pywrapcp.RoutingModel(mgr)
    T = inst.T

    def arc(i, j):
        return cfg.c * T[mgr.IndexToNode(i)][mgr.IndexToNode(j)]

    def tr(i, j):
        a = mgr.IndexToNode(i)
        return T[a][mgr.IndexToNode(j)] + inst.svc[a]

    routing.SetArcCostEvaluatorOfAllVehicles(routing.RegisterTransitCallback(arc))
    routing.AddDimension(routing.RegisterTransitCallback(tr), cfg.H, cfg.H, False, "Time")
    time = routing.GetDimensionOrDie("Time")
    used = set()
    for o, nodes, pen in groups:
        for n in nodes:
            if win[n][0] > win[n][1]:                      # Version nie bedienbar (z. B. Ursprungsfenster endet vor seinem Beginn)
                routing.solver().Add(routing.ActiveVar(mgr.NodeToIndex(n)) == 0)
            else:
                time.CumulVar(mgr.NodeToIndex(n)).SetRange(win[n][0], win[n][1])
            used.add(n)
        idxs = [mgr.NodeToIndex(n) for n in nodes]
        if pen is None:
            if len(nodes) == 1:
                continue
            routing.AddDisjunction(idxs, 10**6, 1)
        else:
            routing.AddDisjunction(idxs, int(pen), 1)
    if cfg.Q < TRIP_FALLBACK:
        dcb = routing.RegisterUnaryTransitCallback(lambda i: inst.dem[mgr.IndexToNode(i)])
        routing.AddDimensionWithVehicleCapacity(dcb, 0, [cfg.Q] * K, True, "Cap")
    prm = pywrapcp.DefaultRoutingSearchParameters()
    prm.first_solution_strategy = getattr(routing_enums_pb2.FirstSolutionStrategy, first)
    if sol_limit is not None:
        prm.solution_limit = sol_limit
    prm.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    prm.time_limit.FromMilliseconds(int(time_limit * 1000))
    routing.CloseModelWithParameters(prm)
    sol = None
    warm_ok = False
    if warm is not None:
        init = routing.ReadAssignmentFromRoutes([list(r) for r in warm.routes], True)
        if init is not None:
            warm_ok = True
            sol = routing.SolveFromAssignmentWithParameters(init, prm)
    if sol is None:
        sol = routing.SolveWithParameters(prm)
    if sol is None:
        return dict(profit=None, routes=None, warm_ok=warm_ok)
    vroutes = []
    for v in range(K):
        idx = routing.Start(v)
        r = []
        while not routing.IsEnd(idx):
            n = mgr.IndexToNode(idx)
            if n != 0:
                r.append(n)
            idx = sol.Value(routing.NextVar(idx))
        vroutes.append(r)
    return dict(profit=offline_profit_ev(inst, vroutes), routes=vroutes, warm_ok=warm_ok)
