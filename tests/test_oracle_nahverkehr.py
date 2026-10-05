"""Unabhängiges Referenzmodell (Orakel) für den Kern der Nahverkehrs-Demo, ohne OR-Tools und ohne die Einfüge-/Suchcode der Demo.

Die vorhandenen Tests prüfen die Simulation gegen eingefrorene eigene Zahlen, Handinstanzen und Brute-Force-Obergrenzen. Hier zusätzlich
ein zweiter Rechenweg auf Zufallsinstanzen (Morgenplan nur Einfüge-Heuristik, damit kein OR-Tools nötig ist):

- eigene Fahrzeitmatrix, eigener frühester Zeitplan ab einem gebundenen Präfix, eigene Fahrzeit je Route per Vollneuberechnung
  (statt Delta-Formeln): Einfügekandidaten (Menge, Zusatzfahrzeit, Zusatz-Rückkehrzeit, Servicebeginne) gleich denen der Demo;
- eine eigene Tagessimulation (S0, Annahme P1p, Änderungen, Stornos, Reparatur, Stabilitätsmaße (a) (b) (c), Gewinn): Annahmen, Routen,
  Zeiten und alle Zähler gleich `run_events(kind="S0")`;
- Zugvollständigkeit der lokalen Suche: nach `local_search` gibt es unter allen Relocate-, Swap-, 2-opt*- und 2-opt-Zügen keinen
  zulässigen, strikt verbessernden Zug mehr (Brute-Force-Aufzählung), der Plan ist gültig, der Präfix unverändert, `saved` gleich der
  Differenz der Fahrzeit.
"""

from __future__ import annotations

import math
import random

import pytest

import nv_model as M
from nv_model import Cfg, candidates, fleet_drive, local_search
from nv_sim import run_events, simulate


@pytest.fixture(autouse=True)
def heuristic_morning(monkeypatch):
    """Morgenplan ohne OR-Tools (nur Heuristik) mit eigenem Zwischenspeicher; der eingefrorene bleibt unberührt."""
    saved = dict(M._MORNING_CACHE)
    monkeypatch.setattr(M, "oracle", lambda *a, **k: dict(profit=None, routes=None))
    M._MORNING_CACHE.clear()
    yield
    M._MORNING_CACHE.clear()
    M._MORNING_CACHE.update(saved)


class Ref:
    def __init__(self, inst):
        self.inst, self.cfg = inst, inst.cfg
        xy, speed = inst.xy, inst.cfg.speed
        n = len(xy)
        self.T = [[0 if i == j else max(math.ceil(math.hypot(xy[i][0] - xy[j][0], xy[i][1] - xy[j][1]) * speed), 1) for j in range(n)]
                  for i in range(n)]

    def drive(self, r):
        if not r:
            return 0
        return self.T[0][r[0]] + sum(self.T[a][b] for a, b in zip(r, r[1:])) + self.T[r[-1]][0]

    def committed(self, r, S, t):
        m, prev = 0, 0
        for j, node in enumerate(r):
            if S[j] - self.T[prev][node] <= t:
                m, prev = j + 1, node
            else:
                break
        return m

    def times_from(self, r, S, p, t):
        inst = self.inst
        prev = r[p - 1] if p > 0 else 0
        dep = max(S[p - 1] + inst.svc[prev] if p > 0 else 0, t)
        out = []
        for node in r[p:]:
            s = max(dep + self.T[prev][node], inst.A[node])
            if s > inst.B[node]:
                return None
            out.append(s)
            dep, prev = s + inst.svc[node], node
        return None if dep + self.T[prev][0] > self.cfg.H else out

    def cap_ok(self, r):
        return self.cfg.Q >= M.TRIP_FALLBACK or sum(self.inst.dem[x] for x in r) <= self.cfg.Q

    def positions(self, r, S, t, m):
        n = len(r)
        if n == 0:
            return [0]
        if m == n and S[n - 1] + self.inst.svc[r[-1]] <= t:
            return []
        return list(range(m, n + 1))

    def candidates(self, routes, Ss, x, t):
        inst, T = self.inst, self.T
        out = []
        for v, (r, S) in enumerate(zip(routes, Ss)):
            n = len(r)
            m = self.committed(r, S, t) if n else 0
            old_end = max(S[-1] + inst.svc[r[-1]] + T[r[-1]][0], t) if n else t
            for p in self.positions(r, S, t, m):
                new = r[:p] + [x] + r[p:]
                if not self.cap_ok(new):
                    continue
                s2 = self.times_from(new, S[:p], p, t)
                if s2 is None:
                    continue
                out.append((self.drive(new) - self.drive(r), s2[-1] + inst.svc[new[-1]] + T[new[-1]][0] - old_end,
                            r[p - 1] if p > 0 else 0, r[p] if p < n else 0, v, p, s2))
        return out


def ref_day_s0(inst):
    R = Ref(inst)
    cfg, oo = R.cfg, inst.order_of
    routes = [list(r) for r in inst.plan.routes]
    Ss = [list(s) for s in inst.plan.S]
    ann = {oo[nd]: s for r, S in zip(routes, Ss) for nd, s in zip(r, S)}
    cur, accepted = {}, []
    n_fail = n_cancel = n_change = n_ign = a_tot = b_tot = c_tot = 0
    items = [(r, 0, i, "new", x) for i, (r, x) in enumerate(inst.arrivals)] + [(e["t"], 1, i, "ev", e) for i, e in enumerate(inst.events)]
    items.sort(key=lambda it: it[:3])

    def pre_state(o, t):
        res = {}
        for v, (r, S) in enumerate(zip(routes, Ss)):
            m, last = R.committed(r, S, t), 0
            for j, node in enumerate(r):
                if oo[node] == o:
                    continue
                if j >= m:
                    res[node] = (v, last)
                last = node
        return res

    def post_state(o):
        res = {}
        for v, r in enumerate(routes):
            last = 0
            for node in r:
                if oo[node] == o:
                    continue
                res[node] = (v, last)
                last = node
        return res

    def insert(x, cand):
        _, _, _, _, v, p, s2 = cand
        routes[v] = routes[v][:p] + [x] + routes[v][p:]
        Ss[v] = Ss[v][:p] + s2

    for t, _, _, typ, obj in items:
        if typ == "new":
            x = obj
            cs = R.candidates(routes, Ss, x, t)
            if not cs:
                continue
            best = min(cs, key=lambda cd: cd[:4])
            if not inst.rev[x] >= cfg.c * best[0]:
                continue
            o = x
            pre = pre_state(o, t)
            insert(x, best)
            accepted.append(x)
        else:
            o = obj["order"]
            node = cur.get(o, o)
            loc = next(((v, r.index(node)) for v, r in enumerate(routes) if node in r), None)
            if loc is None or loc[1] < R.committed(routes[loc[0]], Ss[loc[0]], t):
                n_ign += 1
                continue
            v, idx = loc
            pre = pre_state(o, t)
            if obj["kind"] == "cancel":
                red = routes[v][:idx] + routes[v][idx + 1:]
                routes[v], Ss[v] = red, Ss[v][:idx] + R.times_from(red, Ss[v][:idx], idx, t)
                n_cancel += 1
                ann.pop(o, None)
            else:
                w = obj["var"]
                n_change += 1
                new = routes[v][:idx] + [w] + routes[v][idx + 1:]
                s2 = R.times_from(new, Ss[v][:idx], idx, t) if R.cap_ok(new) else None
                if s2 is not None:
                    routes[v], Ss[v] = new, Ss[v][:idx] + s2
                else:
                    red = routes[v][:idx] + routes[v][idx + 1:]
                    routes[v], Ss[v] = red, Ss[v][:idx] + R.times_from(red, Ss[v][:idx], idx, t)
                    cs = R.candidates(routes, Ss, w, t)
                    if cs:
                        insert(w, min(cs, key=lambda cd: cd[:4]))
                    else:
                        n_fail += 1
                        ann.pop(o, None)
                cur[o] = w
        post = post_state(o)
        a = sum(1 for nd, vp in pre.items() if nd in post and post[nd] != vp)
        now = {nd: s for r, S in zip(routes, Ss) for nd, s in zip(r, S)}
        for nd in pre:
            oid = oo[nd]
            if nd in now and oid in ann and abs(now[nd] - ann[oid]) > 15:
                b_tot += 1
                ann[oid] = now[nd]
        if cur.get(o, o) in now:
            ann[o] = now[cur.get(o, o)]
        a_tot += a
        c_tot += a > 0
    drive = sum(R.drive(r) for r in routes)
    served = [nd for r in routes for nd in r]
    profit = sum(inst.rev[nd] for nd in served if inst.is_sd[nd]) - cfg.c * drive - cfg.pen * n_fail
    return dict(profit=profit, drive=drive, n_acc=len(accepted), n_fail=n_fail, n_cancel=n_cancel, n_change=n_change, n_ign=n_ign,
                a=a_tot, b=b_tot, c=c_tot, routes=routes, S=Ss)


def _cfg(rng):
    w = rng.choice([(1, 1, 0), (1, 0, 0), (0, 1, 0), (1, 1, 1), (0, 0, 1)])
    return Cfg(K=rng.choice([1, 2, 3, 4]), n_m=rng.choice([5, 10, 16, 28, 40]), lam=rng.choice([0.0, 2.0, 6.0, 12.0]),
               delta=rng.choice([60, 120, 240]), p_chg=rng.choice([0.0, 0.15, 0.25, 0.5]), p_cancel=rng.choice([0.0, 0.08, 0.2]),
               Q=rng.choice([M.TRIP_FALLBACK, M.TRIP_FALLBACK, 8, 14]), w_time=w[0], w_addr=w[1], w_qty=w[2],
               chg_delta=rng.choice([15, 30, 60]), addr_radius=rng.choice([2.0, 5.0, 12.0]))


def test_day_without_replanning_matches_independent_simulation():
    rng = random.Random(4242)
    totals = dict(acc=0, change=0, cancel=0, b=0)
    for _ in range(45):
        inst = M.make_instance(_cfg(rng), rng.randint(0, 10**5))
        ref, dem = ref_day_s0(inst), run_events(inst, "S0")
        for key in ("profit", "drive", "n_acc", "n_fail", "n_cancel", "n_change", "n_ign", "a", "b", "c"):
            assert ref[key] == dem[key], key
        assert ref["routes"] == dem["fleet"].routes and ref["S"] == dem["fleet"].S
        totals["acc"] += ref["n_acc"]; totals["change"] += ref["n_change"]; totals["cancel"] += ref["n_cancel"]; totals["b"] += ref["b"]
    assert min(totals.values()) > 0  # Nullspalten-Falle: Annahmen, Änderungen, Stornos und Maß (b) kommen vor


def test_insertion_candidates_match_full_recomputation():
    rng = random.Random(1)
    compared = 0
    for seed in range(20):
        cfg = Cfg(K=rng.choice([1, 2, 3]), n_m=rng.choice([10, 24, 40]), lam=rng.choice([6.0, 12.0]), delta=rng.choice([60, 120]),
                  Q=rng.choice([M.TRIP_FALLBACK, 12]))
        inst = M.make_instance(cfg, seed)
        R, fl = Ref(inst), inst.plan.clone()
        for r, x in inst.arrivals:
            demo = sorted((c[0], c[1], c[2], c[3], c[4], c[5], tuple(c[7])) for c in candidates(inst, fl, x, r))
            ref = sorted((c[0], c[1], c[2], c[3], c[4], c[5], tuple(c[6])) for c in R.candidates(fl.routes, fl.S, x, r))
            assert demo == ref
            compared += 1
            cs = candidates(inst, fl, x, r)
            if cs:
                best = min(cs, key=lambda cd: cd[:4])
                if inst.rev[x] >= cfg.c * best[0]:
                    M.apply_insertion(inst, fl, x, best)
    assert compared > 100


def improving_moves(R, routes, Ss, t, first_free):
    """Alle zulässigen, strikt verbessernden Züge (Relocate 1-3, Swap, 2-opt*, 2-opt) im freien Teil."""
    K, found = len(routes), []
    d0 = [R.drive(r) for r in routes]

    def feasible(v, new, p):
        return R.times_from(new, Ss[v][:p], p, t) is not None and R.cap_ok(new)

    for u in range(K):
        for length in (1, 2, 3):
            for i in range(first_free[u], len(routes[u]) - length + 1):
                seg, red = routes[u][i:i + length], routes[u][:i] + routes[u][i + length:]
                for w in range(K):
                    rw = red if w == u else routes[w]
                    nw = len(rw)
                    if nw == 0:
                        slots = [0]
                    elif first_free[w] == nw and Ss[w][nw - 1] + R.inst.svc[rw[-1]] <= t:
                        slots = []
                    else:
                        slots = list(range(first_free[w], nw + 1))
                    for q in slots:
                        if w == u and q == i:
                            continue
                        new = rw[:q] + seg + rw[q:]
                        if w == u:
                            if feasible(u, new, min(i, q)) and d0[u] - R.drive(new) > 0:
                                found.append(("relocate", u, i, length, q))
                        elif feasible(w, new, q) and feasible(u, red, i) and d0[u] + d0[w] - R.drive(red) - R.drive(new) > 0:
                            found.append(("relocate", u, i, length, w, q))
    for u in range(K):
        for w in range(u + 1, K):
            for i in range(first_free[u], len(routes[u])):
                for j in range(first_free[w], len(routes[w])):
                    nu = routes[u][:i] + [routes[w][j]] + routes[u][i + 1:]
                    nw = routes[w][:j] + [routes[u][i]] + routes[w][j + 1:]
                    if d0[u] + d0[w] - R.drive(nu) - R.drive(nw) > 0 and feasible(u, nu, i) and feasible(w, nw, j):
                        found.append(("swap", u, i, w, j))
            for i in R.positions(routes[u], Ss[u], t, first_free[u]):
                for j in R.positions(routes[w], Ss[w], t, first_free[w]):
                    nu, nw = routes[u][:i] + routes[w][j:], routes[w][:j] + routes[u][i:]
                    if d0[u] + d0[w] - R.drive(nu) - R.drive(nw) > 0 and feasible(u, nu, i) and feasible(w, nw, j):
                        found.append(("2opt*", u, i, w, j))
    for u in range(K):
        ru = routes[u]
        for i in range(first_free[u], len(ru) - 1):
            for j in range(i + 1, len(ru)):
                new = ru[:i] + ru[i:j + 1][::-1] + ru[j + 1:]
                if d0[u] - R.drive(new) > 0 and feasible(u, new, i):
                    found.append(("2opt", u, i, j))
    return found


def test_local_search_leaves_no_improving_move():
    rng = random.Random(777)
    improved = cases = 0
    for _ in range(14):
        cfg = Cfg(K=rng.choice([2, 3, 4]), n_m=rng.choice([8, 14, 24, 36]), lam=rng.choice([2.0, 6.0, 12.0]),
                  delta=rng.choice([60, 120, 240]), Q=rng.choice([M.TRIP_FALLBACK, M.TRIP_FALLBACK, 12]))
        inst = M.make_instance(cfg, rng.randint(0, 10**5))
        R = Ref(inst)
        base = simulate(inst, "P1", ls=False)["fleet"]   # unaufgeräumter Plan: alle machbaren Aufträge, keine lokale Suche
        for t in (330, 90, -1):
            mode = rng.choice(["plain", "plain", "freeze", "until"])
            fl = base.clone()
            routes0, s0 = [list(r) for r in fl.routes], [list(s) for s in fl.S]
            first_free = [R.committed(r, s, t) for r, s in zip(routes0, s0)]
            kw = {}
            if mode == "freeze":
                k = rng.choice([1, 2, 3])
                kw, first_free = dict(freeze=k), [min(len(r), m + k) for r, m in zip(routes0, first_free)]
            elif mode == "until":
                hh = rng.choice([30, 60, 120])
                kw = dict(freeze_until=t + hh)
                grown = []
                for s, m in zip(s0, first_free):
                    while m < len(s) and s[m] <= t + hh:
                        m += 1
                    grown.append(m)
                first_free = grown
            before = fleet_drive(inst, fl)
            saved = local_search(inst, fl, t, **kw)
            cases += 1
            improved += saved > 0
            assert before - fleet_drive(inst, fl) == saved == before - sum(R.drive(r) for r in fl.routes)
            seen = [nd for r in fl.routes for nd in r]
            assert sorted(seen) == sorted(nd for r in routes0 for nd in r)
            for v, (r1, s1) in enumerate(zip(fl.routes, fl.S)):
                assert r1[:first_free[v]] == routes0[v][:first_free[v]] and s1[:first_free[v]] == s0[v][:first_free[v]]
                prev, prev_f = 0, 0
                for nd, s in zip(r1, s1):
                    assert prev_f + R.T[prev][nd] <= s and inst.A[nd] <= s <= inst.B[nd]
                    prev, prev_f = nd, s + inst.svc[nd]
                assert not r1 or prev_f + R.T[prev][0] <= cfg.H
                assert R.cap_ok(r1)
            assert improving_moves(R, fl.routes, fl.S, t, first_free) == []
    assert improved > 5
