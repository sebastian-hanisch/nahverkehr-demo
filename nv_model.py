"""Kern der Nahverkehrs-Demo: Instanz, Flotte, Einfuegen, lokale Suche, Morgenplan (OR-Tools), Ereignisstrom.

MECHANISCH aus messreihe_stabilitaet/stab.py uebernommen (Zeilen 26-692, 853-1018), die Logik ist unveraendert; stab.py selbst ist
eine Erweiterung von messreihe_sameday/sameday.py und liefert ohne Aenderungsereignisse bitgenau dieselben Ergebnisse.
Aufgeteilt: nv_model (dieses Modul), nv_sim (Annahmeregeln P0..P2, Politiken S0/R/F/P/T/H, Stabilitaetsmasse),
nv_oracle (Hindsight-Orakel mit Aenderungen, nur fuer die Reproduktion, nicht in der App).

Abweichungen gegenueber stab.py (Konfiguration, nicht Logik): (1) der Festplatten-Zwischenspeicher fuer Morgenplaene ist
standardmaessig AUS (MORNING_DISK_CACHE = None; nur die Umgebungsvariable NV_MORNING_CACHE, die tools/sweep.py fuer die
Mehrprozess-Reproduktion setzt, schaltet ihn ein): die App darf auf Streamlit Cloud nicht auf die Festplatte schreiben.
(2) Der Orakel-Aufruf fuer den Morgenplan (`oracle`, OR-Tools) steht hier, weil build_morning ihn braucht; das Orakel mit Aenderungen
(oracle_ev) steht in nv_oracle.

Zeitmodell einer Route: S[j] = Servicebeginn, F[j] = S[j] + Service. Ein Stop j ist BINDEND (gefahren/unterwegs), sobald
der Transporter spaetestens losfahren muss, um S[j] zu halten: S[j] - T[vorher][j] <= t. Nur hinter dem bindenden Praefix
darf eingefuegt/umgebaut werden. Ein Transporter, der wieder im Depot ist, darf erneut ausruecken (bis zu M Touren je
Fahrzeug); die Tour wird dann durch einen eingebetteten Depotknoten 0 getrennt.
"""

from __future__ import annotations

import hashlib
import math
import os
import pickle
import random
from dataclasses import dataclass

TRIP_FALLBACK = 10**9


@dataclass(frozen=True)
class Cfg:
    K: int = 3                # Transporter
    n_m: int = 14             # Morgenauftraege (Zielanzahl; bei Ueberlastung weniger)
    H: int = 480              # Schichtende (Rueckkehr ins Depot spaetestens)
    speed: float = 1.2        # Minuten je km (50 km/h)
    svc: int = 6              # Servicezeit je Stopp (min)
    lam: float = 3.0          # Same-Day-Ankuenfte je Stunde
    t_arr: int = 300          # Ankunftsfenster [1, t_arr] Minuten
    delta: int = 120          # Frist: Lieferung innerhalb delta Min nach Eingang
    sigma: float = 0.6        # Streuung des Erloeses (lognormal, Mittelwert bleibt rev_mean)
    rev_mean: float = 60.0
    conc: float = 0.0         # Anteil der Same-Day-Auftraege aus einem Hotspot
    hot_sd: float = 5.0       # Streuung des Hotspots (km)
    area: float = 60.0
    win_w: int = 180          # Breite der Morgen-Zeitfenster
    Q: int = TRIP_FALLBACK    # Kapazitaet je Tour (unbegrenzt = Standard)
    dem_max: int = 3
    M: int = 1                # max. Touren je Fahrzeug und Tag (1 = eine Tour je Schicht; M>1 nur in Tests)
    c: int = 1                # Kosten je Fahrminute (Erloes in derselben Einheit)
    max_tries: int = 80
    # --- Aenderungsereignisse (alle aus: bitgleich zu sameday.py)
    p_chg: float = 0.0        # Wahrscheinlichkeit, dass ein Auftrag im Tagesverlauf eine Aenderung erhaelt
    p_cancel: float = 0.0     # Wahrscheinlichkeit eines Stornos (je Auftrag, exklusiv zu p_chg)
    w_time: float = 1.0       # Gewichte der Aenderungsart: Zeitfenster verschoben / Adresse verschoben / Menge geaendert
    w_addr: float = 1.0
    w_qty: float = 0.0
    chg_delta: int = 30       # Verschiebung des Zeitfensters um +-chg_delta Minuten
    addr_radius: float = 5.0  # Adressverschiebung im Kreis mit diesem Radius (km)
    pen: int = 60             # Strafe je angenommenem Auftrag, der nach einer Aenderung nicht mehr bedienbar ist


# ------------------------------------------------------------------ Instanz und Flotte

class Inst:
    def __init__(self, cfg: Cfg):
        self.cfg = cfg
        self.xy = [(cfg.area / 2, cfg.area / 2)]
        self.T = [[0]]
        self.svc = [0]
        self.dem = [0]
        self.A = [0]
        self.B = [cfg.H]
        self.rev = [0]
        self.is_sd = [False]
        self.arrivals: list[tuple[int, int]] = []   # (Eingangszeit, Knoten), aufsteigend
        self.plan: Fleet | None = None
        self.n_morning = 0
        self.shortfall = 0
        self.seed = 0
        self.hot = None
        self.order_of = [0]          # Knoten -> Auftrag (Variantenknoten zeigen auf ihren Ursprungsauftrag)
        self.events: list[dict] = []  # Aenderungs-/Stornoereignisse
        self.n_orders_base = 0

    def add_node(self, x, y, dm, a, braw, rev, sd):
        cfg = self.cfg
        n = len(self.xy)
        self.xy.append((x, y))
        for i in range(n):
            d = math.ceil(math.hypot(x - self.xy[i][0], y - self.xy[i][1]) * cfg.speed)
            d = max(d, 1)
            self.T[i].append(d)
        self.T.append([self.T[i][n] for i in range(n)] + [0])
        self.svc.append(cfg.svc)
        self.dem.append(dm)
        self.A.append(a)
        self.B.append(min(braw, cfg.H - self.T[n][0] - cfg.svc))
        self.rev.append(rev)
        self.is_sd.append(sd)
        self.order_of.append(n)
        return n

    def pop_node(self):
        n = len(self.xy) - 1
        for row in self.T:
            row.pop()
        self.T.pop()
        for lst in (self.xy, self.svc, self.dem, self.A, self.B, self.rev, self.is_sd, self.order_of):
            lst.pop()
        return n


class Fleet:
    def __init__(self, K: int):
        self.routes: list[list[int]] = [[] for _ in range(K)]
        self.S: list[list[int]] = [[] for _ in range(K)]
        self.F: list[list[int]] = [[] for _ in range(K)]

    def clone(self) -> "Fleet":
        f = Fleet(0)
        f.routes = [r[:] for r in self.routes]
        f.S = [s[:] for s in self.S]
        f.F = [s[:] for s in self.F]
        return f


def fleet_drive(inst: Inst, fl: Fleet) -> int:
    T = inst.T
    tot = 0
    for r in fl.routes:
        if r:
            tot += T[0][r[0]] + T[r[-1]][0]
            for a, b in zip(r, r[1:]):
                tot += T[a][b]
    return tot


def vend(inst: Inst, route, F) -> int:
    return F[-1] + inst.T[route[-1]][0] if route else 0


def committed(T, route, S, t) -> int:
    m = 0
    prev = 0
    for j, node in enumerate(route):
        if S[j] - T[prev][node] <= t:
            m = j + 1
            prev = node
        else:
            break
    return m


def retime(inst: Inst, route, S, F, p, t):
    """Zeiten fuer route[p:], Praefix S[:p], F[:p] gueltig. (S2, F2) oder None (Fenster/Schichtende verletzt)."""
    T, svc, A, B, H = inst.T, inst.svc, inst.A, inst.B, inst.cfg.H
    if p > 0:
        prevn = route[p - 1]
        dep = F[p - 1]
    else:
        prevn = 0
        dep = 0
    if t > dep:
        dep = t
    S2 = []
    F2 = []
    for j in range(p, len(route)):
        node = route[j]
        arr = dep + T[prevn][node]
        s = arr if arr > A[node] else A[node]
        if s > B[node]:
            return None
        f = s + svc[node]
        S2.append(s)
        F2.append(f)
        prevn = node
        dep = f
    if dep + T[prevn][0] > H:
        return None
    return S2, F2


def trip_ok(inst: Inst, route) -> bool:
    Q = inst.cfg.Q
    if Q >= TRIP_FALLBACK:
        return True
    load = 0
    for node in route:
        if node == 0:
            load = 0
        else:
            load += inst.dem[node]
            if load > Q:
                return False
    return True


def n_trips(route) -> int:
    return 1 + sum(1 for x in route if x == 0)


def pos_range(route, m, F, t):
    """Erlaubte Einfuegepositionen p (vor route[p]) im freien Teil."""
    n = len(route)
    if n == 0:
        return range(0, 1)
    if m == n and F[-1] <= t and route[-1] != 0:
        return range(0)
    return range(m, n + 1)


# ------------------------------------------------------------------ Einfuegung

def candidates(inst: Inst, fl: Fleet, x: int, t: int, vehicle_order=None):
    """Alle machbaren Einfuegungen von Knoten x zum Zeitpunkt t.
    Eintrag: (dcost, dend, prev, nxt, v, p, virt, S2, F2). Kapazitaet und Tourenzahl inklusive."""
    T = inst.T
    H = inst.cfg.H
    M = inst.cfg.M
    out = []
    order = range(len(fl.routes)) if vehicle_order is None else vehicle_order
    for v in order:
        route, S, F = fl.routes[v], fl.S[v], fl.F[v]
        n = len(route)
        virt = False
        if n > 0:
            m = committed(T, route, S, t)
            if m == n and route[-1] != 0 and F[-1] + T[route[-1]][0] <= t and n_trips(route) < M:
                # Fahrzeug ist wieder im Depot: virtueller Depotknoten, neue Tour
                virt = True
                s0 = F[-1] + T[route[-1]][0]
                route = route + [0]
                S = S + [s0]
                F = F + [s0]
                n += 1
                m = n
        else:
            m = 0
        old_end = max(vend(inst, route, F), t) if n > 0 else t
        for p in pos_range(route, m, F, t):
            prev = route[p - 1] if p > 0 else 0
            nxt = route[p] if p < n else 0
            dcost = T[prev][x] + T[x][nxt] - T[prev][nxt]
            new_route = route[:p] + [x] + route[p:]
            if not trip_ok(inst, new_route):
                continue
            res = retime(inst, new_route, S, F, p, t)
            if res is None:
                continue
            S2, F2 = res
            new_end = F2[-1] + T[new_route[-1]][0]
            out.append((dcost, new_end - old_end, prev, nxt, v, p, virt, S2, F2))
    return out


def apply_insertion(inst: Inst, fl: Fleet, x: int, cand):
    dcost, dend, prev, nxt, v, p, virt, S2, F2 = cand
    route, S, F = fl.routes[v], fl.S[v], fl.F[v]
    if virt:
        s0 = F[-1] + inst.T[route[-1]][0]
        route.append(0)
        S.append(s0)
        F.append(s0)
    route.insert(p, x)
    del S[p:]
    del F[p:]
    S.extend(S2)
    F.extend(F2)


# ------------------------------------------------------------------ lokale Suche (P3)

def local_search(inst: Inst, fl: Fleet, t: int, max_moves: int = 300, freeze: int = 0, lam: float = 0.0,
                 base_pred: dict | None = None, excl=frozenset(), freeze_until: int | None = None) -> int:
    """Relocate (1-3 Stopps, ueber Fahrzeuge), Swap (zwischen Fahrzeugen), 2-opt im freien Teil, 2-opt* (Endstuecke tauschen).
    Minimiert die Fahrzeit. Bindender Praefix bleibt unangetastet. Gibt die gesparte Fahrzeit zurueck (>= 0).
    freeze: die naechsten `freeze` noch nicht gefahrenen Stopps je Fahrzeug bleiben zusaetzlich fest (Einfrierhorizont).
    lam: Aenderungsstrafe je Stopp, dessen (Fahrzeug, Vorgaenger) sich gegenueber base_pred aendert; ein Zug wird nur
    ausgefuehrt, wenn die Fahrzeitersparnis strikt groesser als lam * (zusaetzliche Aenderungen) ist. excl: Knoten des
    Ereignisauftrags, die in der Aenderungszaehlung ignoriert werden. Mit freeze=0, lam=0 exakt wie in sameday.py."""
    T = inst.T
    K = len(fl.routes)
    saved = 0
    moves = 0
    M = [committed(T, fl.routes[v], fl.S[v], t) for v in range(K)]
    if freeze:
        M = [min(len(fl.routes[v]), M[v] + freeze) for v in range(K)]
    if freeze_until is not None:              # zeitbasierter Einfrierhorizont: Stopps mit geplantem Servicebeginn <= freeze_until fest
        for v in range(K):
            m, Sv = M[v], fl.S[v]
            while m < len(Sv) and Sv[m] <= freeze_until:
                m += 1
            M[v] = m
    chk = None
    cur_ch = None
    if lam > 0 and base_pred is not None:
        def veh_changes(v, route):
            cnt = 0
            pred = 0
            for node in route:
                if node in excl:
                    continue
                b = base_pred.get(node)
                if b is not None and b != (v, pred):
                    cnt += 1
                pred = node
            return cnt

        cur_ch = [veh_changes(v, fl.routes[v]) for v in range(K)]

        def chk(mv):
            delta = 0
            for v, r in mv_routes(mv):
                delta += veh_changes(v, r) - cur_ch[v]
            return mv[-1] - lam * delta > 1e-9

    while moves < max_moves:
        mv = _find_move(inst, fl, t, M, chk)
        if mv is None:
            break
        gain = _apply_move(inst, fl, mv, t)
        if cur_ch is not None:
            for v, r in mv_routes(mv):
                cur_ch[v] = veh_changes(v, r)
        saved += gain
        moves += 1
    return saved


def mv_routes(mv):
    kind = mv[0]
    if kind in ("rel_same", "two"):
        return [(mv[1], mv[3])]
    return [(mv[1], mv[3]), (mv[5], mv[7])]


def _find_move(inst: Inst, fl: Fleet, t: int, M, chk=None):
    T = inst.T
    K = len(fl.routes)
    routes, S, F = fl.routes, fl.S, fl.F
    # --- Relocate (Segment der Laenge 1 oder 2)
    for u in range(K):
        ru = routes[u]
        nu = len(ru)
        for L in (1, 2, 3):
            for i in range(M[u], nu - L + 1):
                seg = ru[i:i + L]
                if 0 in seg:
                    continue
                pv = ru[i - 1] if i > 0 else 0
                nx = ru[i + L] if i + L < nu else 0
                g = T[pv][seg[0]] + T[seg[-1]][nx] - T[pv][nx]
                red = ru[:i] + ru[i + L:]
                for w in range(K):
                    rw = red if w == u else routes[w]
                    nw = len(rw)
                    Fw = F[w]
                    mw = M[w]
                    if w == u:
                        rng = pos_range(rw, M[u], F[u][:nw], t)
                    else:
                        rng = pos_range(rw, mw, Fw, t)
                    for q in rng:
                        if w == u and q == i:
                            continue
                        qp = rw[q - 1] if q > 0 else 0
                        qn = rw[q] if q < nw else 0
                        ins = T[qp][seg[0]] + T[seg[-1]][qn] - T[qp][qn]
                        if ins >= g:
                            continue
                        if w == u:
                            new = red[:q] + seg + red[q:]
                            if not trip_ok(inst, new):
                                continue
                            res = retime(inst, new, S[u], F[u], min(i, q), t)
                            if res is None:
                                continue
                            mv = ("rel_same", u, min(i, q), new, res, g - ins)
                            if chk is None or chk(mv):
                                return mv
                            continue
                        else:
                            new_w = rw[:q] + seg + rw[q:]
                            if not trip_ok(inst, new_w):
                                continue
                            res_w = retime(inst, new_w, S[w], F[w], q, t)
                            if res_w is None:
                                continue
                            res_u = retime(inst, red, S[u], F[u], i, t)
                            if res_u is None:
                                continue
                            mv = ("rel", u, i, red, res_u, w, q, new_w, res_w, g - ins)
                            if chk is None or chk(mv):
                                return mv
                            continue
    # --- Swap (Fahrzeug u < w)
    for u in range(K):
        ru = routes[u]
        nu = len(ru)
        for w in range(u + 1, K):
            rw = routes[w]
            nw = len(rw)
            for i in range(M[u], nu):
                x = ru[i]
                if x == 0:
                    continue
                pu = ru[i - 1] if i > 0 else 0
                nuu = ru[i + 1] if i + 1 < nu else 0
                for j in range(M[w], nw):
                    y = rw[j]
                    if y == 0:
                        continue
                    pw = rw[j - 1] if j > 0 else 0
                    nww = rw[j + 1] if j + 1 < nw else 0
                    d = (T[pu][y] + T[y][nuu] - T[pu][x] - T[x][nuu]) + (T[pw][x] + T[x][nww] - T[pw][y] - T[y][nww])
                    if d >= 0:
                        continue
                    new_u = ru[:i] + [y] + ru[i + 1:]
                    new_w = rw[:j] + [x] + rw[j + 1:]
                    if not (trip_ok(inst, new_u) and trip_ok(inst, new_w)):
                        continue
                    res_u = retime(inst, new_u, S[u], F[u], i, t)
                    if res_u is None:
                        continue
                    res_w = retime(inst, new_w, S[w], F[w], j, t)
                    if res_w is None:
                        continue
                    mv = ("swap", u, i, new_u, res_u, w, j, new_w, res_w, -d)
                    if chk is None or chk(mv):
                        return mv
    # --- 2-opt* (Endstuecke zweier Fahrzeuge tauschen; keine Depotbesuche in den Endstuecken)
    for u in range(K):
        ru = routes[u]
        nu = len(ru)
        for w in range(u + 1, K):
            rw = routes[w]
            nw = len(rw)
            for i in pos_range(ru, M[u], F[u], t):
                if 0 in ru[i:]:
                    continue
                pu = ru[i - 1] if i > 0 else 0
                nu0 = ru[i] if i < nu else 0
                for j in pos_range(rw, M[w], F[w], t):
                    if 0 in rw[j:]:
                        continue
                    pw = rw[j - 1] if j > 0 else 0
                    nw0 = rw[j] if j < nw else 0
                    d = T[pu][nw0] + T[pw][nu0] - T[pu][nu0] - T[pw][nw0]
                    if d >= 0:
                        continue
                    new_u = ru[:i] + rw[j:]
                    new_w = rw[:j] + ru[i:]
                    if not (trip_ok(inst, new_u) and trip_ok(inst, new_w)):
                        continue
                    res_u = retime(inst, new_u, S[u], F[u], i, t)
                    if res_u is None:
                        continue
                    res_w = retime(inst, new_w, S[w], F[w], j, t)
                    if res_w is None:
                        continue
                    mv = ("swap", u, i, new_u, res_u, w, j, new_w, res_w, -d)
                    if chk is None or chk(mv):
                        return mv
    # --- 2-opt im freien Teil
    for u in range(K):
        ru = routes[u]
        nu = len(ru)
        for i in range(M[u], nu - 1):
            for j in range(i + 1, nu):
                if ru[j] == 0:
                    break                                   # Depotbesuche (Tourgrenzen) bleiben an ihrem Platz
                if ru[i] == 0:
                    continue
                pv = ru[i - 1] if i > 0 else 0
                nx = ru[j + 1] if j + 1 < nu else 0
                d = T[pv][ru[j]] + T[ru[i]][nx] - T[pv][ru[i]] - T[ru[j]][nx]
                if d >= 0:
                    continue
                new = ru[:i] + ru[i:j + 1][::-1] + ru[j + 1:]
                res = retime(inst, new, S[u], F[u], i, t)
                if res is None:
                    continue
                mv = ("two", u, i, new, res, -d)
                if chk is None or chk(mv):
                    return mv
    return None


def _apply_move(inst: Inst, fl: Fleet, mv, t) -> int:
    kind = mv[0]
    if kind in ("rel_same", "two"):
        _, u, p, new, res, gain = mv
        fl.routes[u] = new
        fl.S[u] = fl.S[u][:p] + res[0]
        fl.F[u] = fl.F[u][:p] + res[1]
        return gain
    _, u, iu, new_u, res_u, w, jw, new_w, res_w, gain = mv
    fl.routes[u] = new_u
    fl.S[u] = fl.S[u][:iu] + res_u[0]
    fl.F[u] = fl.F[u][:iu] + res_u[1]
    fl.routes[w] = new_w
    fl.S[w] = fl.S[w][:jw] + res_w[0]
    fl.F[w] = fl.F[w][:jw] + res_w[1]
    return gain


# ------------------------------------------------------------------ Instanzerzeugung

_MORNING_CACHE: dict = {}
MORNING_DISK_CACHE = os.environ.get("NV_MORNING_CACHE") or None   # Verzeichnis; None = nur Speicher (reine Beschleunigung, ergebnisgleich). In der App IMMER None.


def _disk_path(key):
    if not MORNING_DISK_CACHE:
        return None
    os.makedirs(MORNING_DISK_CACHE, exist_ok=True)
    return os.path.join(MORNING_DISK_CACHE, hashlib.md5(repr(key).encode()).hexdigest() + ".pkl")
MORNING_SOL_LIMIT = 400


def _morning_key(cfg: Cfg, seed: int):
    return (cfg.K, cfg.n_m, cfg.H, cfg.speed, cfg.svc, cfg.win_w, cfg.area, cfg.dem_max, cfg.M, cfg.c, cfg.Q,
            cfg.max_tries, seed)


def build_morning(cfg: Cfg, seed: int):
    """Morgenauftraege (Rejection-Sampling: nur einplanbare) und Morgenplan. Plan = Einfuege-Heuristik + lokale Suche,
    danach von OR-Tools (Warmstart, deterministisch ueber solution_limit) verbessert; Ergebnis: Knotendaten und Routen
    (Knoten-IDs 1..n, 0 = eingebetteter Depotbesuch zwischen Touren). Nur von Morgen-Parametern und Seed abhaengig."""
    key = _morning_key(cfg, seed)
    if key in _MORNING_CACHE:
        return _MORNING_CACHE[key]
    disk = _disk_path(key)
    if disk is not None and os.path.exists(disk):
        try:
            with open(disk, "rb") as fh:
                _MORNING_CACHE[key] = pickle.load(fh)
            return _MORNING_CACHE[key]
        except Exception:
            pass
    rm = random.Random(seed * 1_000_003 + 1)
    inst = Inst(cfg)
    fl = Fleet(cfg.K)
    nodes = []
    shortfall = 0
    for _ in range(cfg.n_m):
        placed = False
        for _try in range(cfg.max_tries):
            x, y = rm.uniform(0, cfg.area), rm.uniform(0, cfg.area)
            dm = rm.randint(1, cfg.dem_max)
            a0 = rm.randint(0, cfg.H - cfg.win_w - 60)
            node = inst.add_node(x, y, dm, a0, a0 + cfg.win_w, 0, False)
            cs = candidates(inst, fl, node, -1)
            if cs:
                best = min(cs, key=lambda c: (c[0], c[1], c[2], c[3], c[4], c[5]))
                apply_insertion(inst, fl, node, best)
                nodes.append((x, y, dm, a0))
                placed = True
                break
            inst.pop_node()
        if not placed:
            shortfall += 1
    local_search(inst, fl, -1, max_moves=2000)
    inst.plan = fl
    inst.n_morning = len(nodes)
    routes = [r[:] for r in fl.routes]
    if nodes:
        o = oracle(inst, warm=fl, time_limit=30, sol_limit=MORNING_SOL_LIMIT)
        if o["profit"] is not None and -o["profit"] < fleet_drive(inst, fl):
            M = cfg.M
            new_routes = []
            for v in range(cfg.K):
                r = []
                for m in range(M):
                    trip = o["routes"][v * M + m]
                    if trip:
                        if r:
                            r.append(0)
                        r += trip
                new_routes.append(r)
            routes = new_routes
    _MORNING_CACHE[key] = (nodes, routes, shortfall)
    if disk is not None:
        tmp = disk + f".{os.getpid()}.tmp"
        with open(tmp, "wb") as fh:
            pickle.dump(_MORNING_CACHE[key], fh)
        os.replace(tmp, disk)
    return _MORNING_CACHE[key]


def draw_order(cfg: Cfg, rs: random.Random, hot):
    """Attribute eines Same-Day-Auftrags (Reihenfolge der Ziehungen fest, damit Zufallsstroeme stabil bleiben)."""
    ux, uy = rs.uniform(0, cfg.area), rs.uniform(0, cfg.area)
    gx, gy = rs.gauss(hot[0], cfg.hot_sd), rs.gauss(hot[1], cfg.hot_sd)
    u = rs.random()
    dm = rs.randint(1, cfg.dem_max)
    z = rs.gauss(0.0, 1.0)
    if u < cfg.conc:
        x, y = min(max(gx, 0.0), cfg.area), min(max(gy, 0.0), cfg.area)
    else:
        x, y = ux, uy
    rev = max(5, round(cfg.rev_mean * math.exp(cfg.sigma * z - cfg.sigma ** 2 / 2)))
    return x, y, dm, rev



def make_instance(cfg: Cfg, seed: int) -> Inst:
    """Deterministisch je (cfg, seed). Drei getrennte Zufallsstroeme (Morgen, Same-Day-Attribute, Ankunftszeiten):
    eine hoehere Rate verlaengert nur den Same-Day-Strom (gemeinsame Zufallszahlen ueber Zellen)."""
    rs = random.Random(seed * 1_000_003 + 2)
    ra = random.Random(seed * 1_000_003 + 3)
    nodes, routes, shortfall = build_morning(cfg, seed)
    inst = Inst(cfg)
    for (x, y, dm, a0) in nodes:
        inst.add_node(x, y, dm, a0, a0 + cfg.win_w, 0, False)
    inst.n_morning = len(nodes)
    inst.shortfall = shortfall
    fl = Fleet(cfg.K)
    for v, r in enumerate(routes):
        res = retime(inst, r, [], [], 0, -1)
        assert res is not None, "Morgenplan nicht machbar"
        fl.routes[v] = r[:]
        fl.S[v], fl.F[v] = res
    inst.plan = fl
    inst.seed = seed
    # Same-Day-Strom
    hx, hy = rs.uniform(10, cfg.area - 10), rs.uniform(10, cfg.area - 10)
    inst.hot = (hx, hy)
    if cfg.lam > 0:
        tt = 0.0
        while True:
            tt += ra.expovariate(cfg.lam / 60.0)
            r = math.ceil(tt)
            if r > cfg.t_arr:
                break
            x, y, dm, rev = draw_order(cfg, rs, inst.hot)
            node = inst.add_node(x, y, dm, r, r + cfg.delta, rev, True)
            inst.arrivals.append((r, node))
    inst.n_orders_base = len(inst.xy) - 1
    if cfg.p_chg + cfg.p_cancel > 0:
        make_events(inst, seed)
    return inst


def make_events(inst: Inst, seed: int) -> None:
    """Aenderungen/Stornos je Auftrag (Morgen- und Same-Day-Auftraege), eigener Zufallsstrom: Politik-unabhaengig, die
    Same-Day-Attribute bleiben unveraendert. Zeitpunkt: Morgenauftraege 10..200 min vor dem im Morgenplan
    geplanten Servicebeginn (mind. 5), Same-Day-Auftraege Eingang + [5, 100]. Aenderungsart: Zeitfenster +-chg_delta (beide Grenzen), Adresse im Kreis, Menge +-1/2 (nur wirksam bei
    endlicher Kapazitaet). Bei jeder Aenderung entsteht ein Variantenknoten (neue Attribute); die Simulation tauscht den
    Knoten in der Route aus. Es gibt hoechstens ein Ereignis je Auftrag."""
    cfg = inst.cfg
    rv = random.Random(seed * 1_000_003 + 4)
    weights = [cfg.w_time, cfg.w_addr, cfg.w_qty]
    tot_w = sum(weights) or 1.0
    arr_time = {x: r for r, x in inst.arrivals}
    plan_S = {n: sv for route, S in zip(inst.plan.routes, inst.plan.S) for n, sv in zip(route, S)}
    for o in range(1, inst.n_orders_base + 1):
        u = rv.random()
        tu = rv.random()
        ut = rv.random()
        sign = 1 if rv.random() < 0.5 else -1
        ang = rv.uniform(0, 2 * math.pi)
        rad = cfg.addr_radius * math.sqrt(rv.random())
        qd = rv.randint(1, 2) * sign
        if u < cfg.p_cancel:
            kind = "cancel"
        elif u < cfg.p_cancel + cfg.p_chg:
            kind = "time" if ut * tot_w < weights[0] else ("addr" if ut * tot_w < weights[0] + weights[1] else "qty")
        else:
            continue
        if o in arr_time:
            t_e = arr_time[o] + 5 + int(tu * 96)
        else:
            t_e = max(5, plan_S.get(o, 200) - 10 - int(tu * 191))     # vor dem geplanten Servicebeginn im Morgenplan
        if t_e >= cfg.H:
            continue
        w = None
        if kind != "cancel":
            x, y = inst.xy[o]
            a, b, dm = inst.A[o], inst.B[o], inst.dem[o]
            if kind == "time":
                a, b = max(0, a + sign * cfg.chg_delta), b + sign * cfg.chg_delta
            elif kind == "addr":
                x = min(max(x + rad * math.cos(ang), 0.0), cfg.area)
                y = min(max(y + rad * math.sin(ang), 0.0), cfg.area)
            else:
                dm = min(max(dm + qd, 1), cfg.dem_max + 2)
            w = inst.add_node(x, y, dm, a, b, inst.rev[o], inst.is_sd[o])
            inst.order_of[w] = o
            if inst.B[w] < inst.A[w]:
                inst.B[w] = inst.A[w]
        inst.events.append(dict(t=t_e, kind=kind, order=o, var=w))
    inst.events.sort(key=lambda e: (e["t"], e["order"]))


# ------------------------------------------------------------------ Validator (unabhaengig vom Einfuege-Code)

def validate(inst: Inst, fl: Fleet, accepted) -> None:
    """Prueft ein Endergebnis von Grund auf: jeder Morgenauftrag und jeder angenommene Same-Day-Auftrag genau einmal,
    kein abgelehnter drin, Zeiten (Fahrzeit, Fenster, Schichtende), Touren, Kapazitaet."""
    T = inst.T
    cfg = inst.cfg
    seen = []
    for v, route in enumerate(fl.routes):
        S, F = fl.S[v], fl.F[v]
        assert len(S) == len(F) == len(route)
        prevn, prevF = 0, 0
        for j, node in enumerate(route):
            assert S[j] >= prevF + T[prevn][node], (v, j, "Fahrzeit unterschritten")
            assert S[j] >= inst.A[node], (v, j, "vor Fensterbeginn / vor Eingang")
            assert S[j] <= inst.B[node], (v, j, "Frist verletzt")
            assert F[j] == S[j] + inst.svc[node]
            prevn, prevF = node, F[j]
            if node != 0:
                seen.append(node)
        if route:
            assert prevF + T[prevn][0] <= cfg.H, (v, "Schichtende")
        assert n_trips(route) <= cfg.M, (v, "zu viele Touren")
        assert trip_ok(inst, route), (v, "Kapazitaet")
    morning = set(range(1, inst.n_morning + 1))
    assert sorted(seen) == sorted(morning | set(accepted)), "Abdeckung"
    assert len(seen) == len(set(seen))


def profit_of(inst: Inst, fl: Fleet) -> int:
    served = [n for r in fl.routes for n in r if n != 0 and inst.is_sd[n]]
    return sum(inst.rev[n] for n in served) - inst.cfg.c * fleet_drive(inst, fl)


# ------------------------------------------------------------------ Hindsight-Orakel (OR-Tools)

def fleet_to_trips(inst: Inst, fl: Fleet):
    """Zerlegt die Fahrzeugrouten an eingebetteten Depotknoten in Touren (fuer den Warmstart des Orakels)."""
    M = inst.cfg.M
    routes = []
    for v, r in enumerate(fl.routes):
        trips = [[]]
        for x in r:
            if x == 0:
                trips.append([])
            else:
                trips[-1].append(x)
        assert len(trips) <= M
        trips += [[] for _ in range(M - len(trips))]
        routes += trips
    return routes


def offline_profit(inst: Inst, vroutes) -> int:
    """Gewinn einer Offline-Loesung (Touren je virtuellem Fahrzeug, Reihenfolge v*M+m), unabhaengig nachgerechnet und
    auf Machbarkeit geprueft: fruehester Zeitplan je Tour, Touren desselben Fahrzeugs nacheinander."""
    cfg = inst.cfg
    T = inst.T
    tot_rev = 0
    drive = 0
    seen = set()
    for v in range(cfg.K):
        avail = 0
        for m in range(cfg.M):
            trip = vroutes[v * cfg.M + m]
            if not trip:
                continue
            cap = sum(inst.dem[x] for x in trip)
            assert cap <= cfg.Q, "Kapazitaet"
            t = avail
            prevn = 0
            for x in trip:
                t = max(t + T[prevn][x], inst.A[x])
                assert t <= inst.B[x], ("Frist", x, t, inst.B[x])
                t += inst.svc[x]
                drive += T[prevn][x]
                prevn = x
                seen.add(x)
                if inst.is_sd[x]:
                    tot_rev += inst.rev[x]
            drive += T[prevn][0]
            t += T[prevn][0]
            assert t <= cfg.H, "Schichtende"
            avail = t
    assert set(range(1, inst.n_morning + 1)) <= seen, "Morgenauftrag fehlt"
    return tot_rev - cfg.c * drive


def oracle(inst: Inst, warm: Fleet | None = None, time_limit: float = 4.0, cold: bool = False,
           first: str = "PATH_CHEAPEST_ARC", sol_limit: int | None = None, mandatory=None,
           meta: str = "GUIDED_LOCAL_SEARCH"):
    """Hindsight-Orakel: alle Same-Day-Auftraege vorab bekannt, Prize-Collecting-VRPTW mit Disjunktionsstrafe = Erloes,
    Fensteruntergrenze = Eingangszeit, Morgenauftraege Pflicht. OR-Tools ist eine Heuristik: das Ergebnis ist die beste
    gefundene Offline-Loesung (untere Schranke des echten Optimums). Mit Warmstart aus einer Online-Loesung ist sie per
    Konstruktion nie schlechter als diese. cold=True: ohne Warmstart (Qualitaetstest des Loesers)."""
    from ortools.constraint_solver import pywrapcp, routing_enums_pb2

    cfg = inst.cfg
    N = len(inst.T)
    K, M = cfg.K, cfg.M
    V = K * M
    mgr = pywrapcp.RoutingIndexManager(N, V, 0)
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
    for n in range(1, N):
        time.CumulVar(mgr.NodeToIndex(n)).SetRange(inst.A[n], inst.B[n])
        if inst.is_sd[n]:
            if mandatory is None:
                routing.AddDisjunction([mgr.NodeToIndex(n)], int(inst.rev[n]))
            elif n in mandatory:
                pass                                   # Pflicht: feste Auftragsmenge, nur die Route wird optimiert
            else:
                routing.AddDisjunction([mgr.NodeToIndex(n)], 0)
    solver = routing.solver()
    if mandatory is not None:
        for n in range(1, N):
            if inst.is_sd[n] and n not in mandatory:
                solver.Add(routing.ActiveVar(mgr.NodeToIndex(n)) == 0)
    for v in range(K):
        for m in range(1, M):
            solver.Add(time.CumulVar(routing.Start(v * M + m)) >= time.CumulVar(routing.End(v * M + m - 1)))
    if cfg.Q < TRIP_FALLBACK:
        dcb = routing.RegisterUnaryTransitCallback(lambda i: inst.dem[mgr.IndexToNode(i)])
        routing.AddDimensionWithVehicleCapacity(dcb, 0, [cfg.Q] * V, True, "Cap")
    prm = pywrapcp.DefaultRoutingSearchParameters()
    prm.first_solution_strategy = getattr(routing_enums_pb2.FirstSolutionStrategy, first)
    if sol_limit is not None:
        prm.solution_limit = sol_limit
    prm.local_search_metaheuristic = getattr(routing_enums_pb2.LocalSearchMetaheuristic, meta)
    prm.time_limit.FromMilliseconds(int(time_limit * 1000))
    routing.CloseModelWithParameters(prm)
    warm_ok = False
    sol = None
    if warm is not None and not cold:
        init = routing.ReadAssignmentFromRoutes(fleet_to_trips(inst, warm), True)
        if init is not None:
            warm_ok = True
            sol = routing.SolveFromAssignmentWithParameters(init, prm)
    if sol is None:
        sol = routing.SolveWithParameters(prm)
    if sol is None:
        return dict(profit=None, routes=None, warm_ok=warm_ok, status="keine Loesung")
    vroutes = []
    for v in range(V):
        idx = routing.Start(v)
        r = []
        while not routing.IsEnd(idx):
            n = mgr.IndexToNode(idx)
            if n != 0:
                r.append(n)
            idx = sol.Value(routing.NextVar(idx))
        vroutes.append(r)
    prof = offline_profit(inst, vroutes)
    return dict(profit=prof, routes=vroutes, warm_ok=warm_ok, status="ok",
                n_served_sd=sum(1 for r in vroutes for n in r if inst.is_sd[n]))
