"""Simulation der Nahverkehrs-Demo: Annahmeregeln fuer neue Auftraege (P0, P1, P1p, P2v, P2m, P2, P2c, optional mit Neuoptimierung L,
Stichproben-Rollout) und die ereignisgesteuerte Tagessimulation mit Aenderungen/Stornos, Neuplanungs-Politiken (S0, R, F_k, P_lambda,
T_x, H_h) und den Stabilitaetsmassen (a) fahrerseitig, (b) kundenseitig, (c) Neuplanungsereignisse mit Aenderung.

MECHANISCH aus messreihe_stabilitaet/stab.py uebernommen (Zeilen 695-850 und 1021-1235), Logik unveraendert. Nur Standardbibliothek."""

from __future__ import annotations

import math
import random

from nv_model import (Cfg, Fleet, Inst, apply_insertion, candidates, committed, draw_order, fleet_drive, local_search,
                      retime, trip_ok)

# ------------------------------------------------------------------ Simulation

def opp_weight(cfg: Cfg, t: int) -> float:
    """Anteil des Ankunftsfensters, der noch bevorsteht: Schatten-Preis der Zeit klingt mit den erwarteten Ankuenften ab."""
    return max(0.0, 1.0 - t / cfg.t_arr)


KINDS = ("P0", "P1", "P1p", "P2v", "P2m", "P2", "P2c")


def simulate(inst: Inst, kind: str, mu: float = 0.0, rho: float = 0.0, ls: bool = False,
             log: bool = False, vehicle_order=None, arrivals=None) -> dict:
    """kind: P0 nie, P1 machbar, P1p machbar und Erloes >= Fahrkosten, P2v zusaetzlich Erloes >= rho (Erloes-Schutzniveau,
    geometrie-blind), P2m Nettomarge (Erloes - Fahrkosten) >= rho, P2 Erloes >= Fahrkosten + mu*w(t)*Zusatz-Rueckkehrzeit."""
    assert kind in KINDS
    cfg = inst.cfg
    fl = inst.plan.clone()
    c = cfg.c
    accepted: list[int] = []
    n_feas = 0
    ls_saved = 0
    ls_calls = 0
    events = []
    snaps = []
    for r, x in (inst.arrivals if arrivals is None else arrivals):
        if kind == "P0":
            continue
        if log:
            snaps.append((r, [(list(fl.routes[v][:committed(inst.T, fl.routes[v], fl.S[v], r)]),
                               list(fl.S[v][:committed(inst.T, fl.routes[v], fl.S[v], r)])) for v in range(cfg.K)]))
        cs = candidates(inst, fl, x, r, vehicle_order)
        if not cs:
            if log:
                events.append((r, x, "infeasible", None, None))
            continue
        n_feas += 1
        rev = inst.rev[x]
        if kind in ("P2", "P2c"):
            w = opp_weight(cfg, r) if kind == "P2" else 1.0
            best = min(cs, key=lambda cd: (c * cd[0] + mu * w * cd[1], cd[0], cd[1], cd[2], cd[3]))
            comp = c * best[0] + mu * w * best[1]
            ok = rev >= comp
        else:
            best = min(cs, key=lambda cd: (cd[0], cd[1], cd[2], cd[3]))
            dc = c * best[0]
            if kind == "P1":
                ok = True
            elif kind == "P1p":
                ok = rev >= dc
            elif kind == "P2v":
                ok = rev >= dc and rev >= rho
            else:  # P2m
                ok = rev - dc >= rho
        if log:
            ties = sum(1 for cd in cs if cd[:4] == best[:4])
            events.append((r, x, "accept" if ok else "reject", best[:4], ties))
        if ok:
            apply_insertion(inst, fl, x, best)
            accepted.append(x)
            if ls:
                ls_calls += 1
                ls_saved += local_search(inst, fl, r)
    drive = fleet_drive(inst, fl)
    rev_acc = sum(inst.rev[x] for x in accepted)
    out = dict(profit=rev_acc - c * drive, drive=drive, rev=rev_acc, n_acc=len(accepted), n_feas=n_feas,
               accepted=accepted, fleet=fl, ls_saved=ls_saved, ls_calls=ls_calls)
    if log:
        out["events"] = events
        out["snaps"] = snaps
    return out


def decide(inst: Inst, fl: Fleet, x: int, r: int, kind: str, mu: float = 0.0, rho: float = 0.0):
    """Annahmeentscheidung einer Regel fuer Auftrag x zum Zeitpunkt r. Rueckgabe (ok, best, n_cands)."""
    cfg = inst.cfg
    c = cfg.c
    cs = candidates(inst, fl, x, r)
    if not cs:
        return False, None, 0
    rev = inst.rev[x]
    if kind in ("P2", "P2c"):
        w = opp_weight(cfg, r) if kind == "P2" else 1.0
        best = min(cs, key=lambda cd: (c * cd[0] + mu * w * cd[1], cd[0], cd[1], cd[2], cd[3]))
        return rev >= c * best[0] + mu * w * best[1], best, len(cs)
    best = min(cs, key=lambda cd: (cd[0], cd[1], cd[2], cd[3]))
    dc = c * best[0]
    if kind == "P1":
        ok = True
    elif kind == "P1p":
        ok = rev >= dc
    elif kind == "P2v":
        ok = rev >= dc and rev >= rho
    else:
        ok = rev - dc >= rho
    return ok, best, len(cs)


def simulate_rollout(inst: Inst, S: int = 16, base: str = "P1p", ls: bool = False, mu: float = 0.0) -> dict:
    """P4 (Zusatz): Stichproben-Rollout. Bei jedem Eingang mit machbarer Einfuegung werden Annehmen und Ablehnen an S
    gemeinsamen Zufallsszenarien der noch ausstehenden Ankuenfte (aus dem BEKANNTEN Erzeugungsmodell gezogen, also mit
    perfekter Verteilungskenntnis) mit der Basisregel `base` zu Ende gespielt; gewaehlt wird der bessere Mittelwert."""
    cfg = inst.cfg
    c = cfg.c
    fl = inst.plan.clone()
    accepted = []
    ls_saved = 0
    n0 = len(inst.T)
    for r, x in inst.arrivals:
        cs = candidates(inst, fl, x, r)
        if not cs:
            continue
        best = min(cs, key=lambda cd: (cd[0], cd[1], cd[2], cd[3]))
        rng = random.Random(inst.seed * 7_919 + x * 104_729 + 17)
        scen = []
        for _s in range(S):
            tt = float(r)
            fut = []
            if cfg.lam > 0:
                while True:
                    tt += rng.expovariate(cfg.lam / 60.0)
                    rr = math.ceil(tt)
                    if rr > cfg.t_arr:
                        break
                    px, py, dm, rev = draw_order(cfg, rng, inst.hot)
                    node = inst.add_node(px, py, dm, rr, rr + cfg.delta, rev, True)
                    fut.append((rr, node))
            scen.append(fut)
        va = vb = 0.0
        for fut in scen:
            for opt in (0, 1):
                f2 = fl.clone()
                gain = 0
                if opt == 1:
                    apply_insertion(inst, f2, x, best)
                    gain = inst.rev[x]
                for rr, node in fut:
                    ok, b2, _ = decide(inst, f2, node, rr, base, mu=mu)
                    if ok:
                        apply_insertion(inst, f2, node, b2)
                        gain += inst.rev[node]
                val = gain - c * fleet_drive(inst, f2)
                if opt == 1:
                    va += val
                else:
                    vb += val
        while len(inst.T) > n0:
            inst.pop_node()
        if va > vb:
            apply_insertion(inst, fl, x, best)
            accepted.append(x)
            if ls:
                ls_saved += local_search(inst, fl, r)
    drive = fleet_drive(inst, fl)
    rev_acc = sum(inst.rev[x] for x in accepted)
    return dict(profit=rev_acc - c * drive, drive=drive, rev=rev_acc, n_acc=len(accepted), n_feas=0,
                accepted=accepted, fleet=fl, ls_saved=ls_saved, ls_calls=0)


# =====================================================================================================================
# Ereignissimulation mit Aenderungen/Stornos, Stabilitaetsmassen und Neuplanungs-Politiken
# =====================================================================================================================

ETA_TOL = 15   # Kundenseitig: angekuendigte Ankunftszeit gilt als geaendert, wenn sie um mehr als 15 min abweicht


def snapshot(inst: Inst, fl: Fleet, t: int, excl_orders) -> dict:
    """Vorher-Zustand fuer die Stabilitaetsmasse: Knoten -> (Fahrzeug, Vorgaenger) fuer alle NOCH NICHT gefahrenen Stopps.
    Die Stopps des Ereignisauftrags werden ausgelassen (auch als Vorgaenger): Einfuegen/Entfernen/Ersetzen des Ereignisauftrags
    selbst zaehlt nicht als Aenderung der uebrigen Stopps."""
    res = {}
    T = inst.T
    oo = inst.order_of
    for v, (route, S) in enumerate(zip(fl.routes, fl.S)):
        m = committed(T, route, S, t)
        pred = 0
        for j, node in enumerate(route):
            if oo[node] in excl_orders:
                continue
            if j >= m:
                res[node] = (v, pred)
            pred = node
    return res


def count_changes(inst: Inst, fl: Fleet, pre: dict, excl_orders) -> int:
    """Massfamilie (a): Zahl der vorher noch nicht gefahrenen Stopps, deren Fahrzeug oder Vorgaenger sich geaendert hat."""
    now = {}
    oo = inst.order_of
    for v, route in enumerate(fl.routes):
        pred = 0
        for node in route:
            if oo[node] in excl_orders:
                continue
            now[node] = (v, pred)
            pred = node
    return sum(1 for node, vp in pre.items() if node in now and now[node] != vp)


def locate(fl: Fleet, node: int):
    for v, r in enumerate(fl.routes):
        if node in r:
            return v, r.index(node)
    return None


def remove_at(inst: Inst, fl: Fleet, v: int, idx: int, t: int) -> None:
    route, S, F = fl.routes[v], fl.S[v], fl.F[v]
    red = route[:idx] + route[idx + 1:]
    res = retime(inst, red, S, F, idx, t)
    assert res is not None, "Entfernen eines Stopps darf nie unzulaessig machen (Dreiecksungleichung)"
    fl.routes[v] = red
    fl.S[v] = S[:idx] + res[0]
    fl.F[v] = F[:idx] + res[1]


def apply_change(inst: Inst, fl: Fleet, v: int, idx: int, w: int, t: int) -> bool:
    """Ersetzt den Stopp an Position idx durch den Variantenknoten w: erst an derselben Stelle (minimale Reparatur),
    sonst billigste Einfuegung irgendwo im freien Teil, sonst gescheitert (False; der Auftrag ist dann entfernt)."""
    route, S, F = fl.routes[v], fl.S[v], fl.F[v]
    new = route[:idx] + [w] + route[idx + 1:]
    if trip_ok(inst, new):
        res = retime(inst, new, S, F, idx, t)
        if res is not None:
            fl.routes[v] = new
            fl.S[v] = S[:idx] + res[0]
            fl.F[v] = F[:idx] + res[1]
            return True
    remove_at(inst, fl, v, idx, t)
    cs = candidates(inst, fl, w, t)
    if cs:
        best = min(cs, key=lambda cd: (cd[0], cd[1], cd[2], cd[3]))
        apply_insertion(inst, fl, w, best)
        return True
    return False


def node_S(fl: Fleet) -> dict:
    out = {}
    for route, S in zip(fl.routes, fl.S):
        for node, s in zip(route, S):
            out[node] = s
    return out


POLICIES_STAB = ("S0", "R", "F", "P", "T", "H")


def run_events(inst: Inst, kind: str = "S0", k: int = 0, lam: float = 0.0, T_per: int = 0, log: bool = False,
               H_min: int = 0) -> dict:
    """Ereignisgesteuerte Tagessimulation. Annahme wie P1p (Erloes >= Fahr-Zusatzkosten). Basisschritt je Ereignis (fuer alle
    Politiken gleich): Einfuegen / minimale Reparatur (Ersetzen an derselben Stelle, sonst billigste Einfuegung) / Entfernen.
    Danach je Politik ein Neuoptimierungsschritt (lokale Suche ueber den nicht gefahrenen Teil):
      S0: keiner.  R: volle Neuoptimierung nach jedem wirksamen Ereignis.  F (k): die naechsten k Stopps je Fahrzeug fest.
      P (lam): Aenderungsstrafe lam je geaendertem Stopp.  T (T_per): nur wenn seit dem letzten Lauf >= T_per Minuten vergangen.
      H (H_min): zeitbasierter Einfrierhorizont: Stopps mit geplantem Servicebeginn in den naechsten H_min Minuten fest.
    Ohne Aenderungsereignisse und mit kind='R' (bzw. 'S0') identisch mit sameday.simulate(P1p, ls=True) (bzw. P1p)."""
    assert kind in POLICIES_STAB
    cfg = inst.cfg
    c = cfg.c
    oo = inst.order_of
    fl = inst.plan.clone()
    ann = {}
    for route, S in zip(fl.routes, fl.S):
        for node, s in zip(route, S):
            ann[oo[node]] = s
    cur = {}                       # Auftrag -> aktueller Knoten (nach Aenderung: Variante)
    accepted: list[int] = []
    n_fail = n_cancel_eff = n_change_eff = n_ign = n_new_acc = 0
    a_cnt = b_cnt = c_cnt = 0
    ls_saved = ls_calls = 0
    by_kind = {"cancel": 0, "time": 0, "addr": 0, "qty": 0}
    cancelled_orders = []
    items = [(r, 0, i, "new", x) for i, (r, x) in enumerate(inst.arrivals)]
    items += [(e["t"], 1, i, "ev", e) for i, e in enumerate(inst.events)]
    items.sort(key=lambda it: (it[0], it[1], it[2]))
    next_tick = T_per if T_per else 0
    trace = []
    snaps = []
    failed_orders = []
    for t, _, _, typ, obj in items:
        if log:
            snaps.append((t, [(list(fl.routes[v][:committed(inst.T, fl.routes[v], fl.S[v], t)]),
                               list(fl.S[v][:committed(inst.T, fl.routes[v], fl.S[v], t)])) for v in range(cfg.K)]))
        if typ == "new":
            x = obj
            ok, best, _n = decide(inst, fl, x, t, "P1p")
            if not ok:
                continue
            o = x
            pre = snapshot(inst, fl, t, {o})
            apply_insertion(inst, fl, x, best)
            accepted.append(x)
            n_new_acc += 1
        else:
            e = obj
            o = e["order"]
            node = cur.get(o, o)
            loc = locate(fl, node)
            if loc is None:
                n_ign += 1
                continue
            v, idx = loc
            m = committed(inst.T, fl.routes[v], fl.S[v], t)
            if idx < m:
                n_ign += 1
                continue
            pre = snapshot(inst, fl, t, {o})
            by_kind[e["kind"]] += 1
            if e["kind"] == "cancel":
                remove_at(inst, fl, v, idx, t)
                n_cancel_eff += 1
                cancelled_orders.append(o)
                ann.pop(o, None)
            else:
                w = e["var"]
                ok = apply_change(inst, fl, v, idx, w, t)
                cur[o] = w
                n_change_eff += 1
                if not ok:
                    n_fail += 1
                    failed_orders.append(o)
                    ann.pop(o, None)
        # Neuoptimierungsschritt (nur nach einem wirksamen Ereignis; hier ist jedes Ereignis an dieser Stelle wirksam)
        do_ls = False
        if kind in ("R", "F", "P", "H"):
            do_ls = True
        elif kind == "T" and T_per == 0:
            do_ls = True
        elif kind == "T" and t >= next_tick:
            do_ls = True
            next_tick = (t // T_per + 1) * T_per
        if do_ls:
            ls_calls += 1
            if kind == "F":
                ls_saved += local_search(inst, fl, t, freeze=k)
            elif kind == "H":
                ls_saved += local_search(inst, fl, t, freeze_until=t + H_min)
            elif kind == "P":
                exn = frozenset(n for n in range(len(inst.T)) if oo[n] == o)
                ls_saved += local_search(inst, fl, t, lam=lam, base_pred=pre, excl=exn)
            else:
                ls_saved += local_search(inst, fl, t)
        # Stabilitaetsmasse nach dem Ereignis
        a = count_changes(inst, fl, pre, {o})
        SN = node_S(fl)
        bb = 0
        for node in pre:
            oid = oo[node]
            if node in SN and oid in ann and abs(SN[node] - ann[oid]) > ETA_TOL:
                bb += 1
                ann[oid] = SN[node]
        cur_node = cur.get(o, o)
        if cur_node in SN:
            ann[o] = SN[cur_node]
        a_cnt += a
        b_cnt += bb
        c_cnt += a > 0
        if log:
            trace.append((t, typ, o, a, bb))
    drive = fleet_drive(inst, fl)
    served = [n for r in fl.routes for n in r if n != 0]
    rev_sd = sum(inst.rev[n] for n in served if inst.is_sd[n])
    n_morning_served = sum(1 for n in served if not inst.is_sd[n])
    profit = rev_sd - c * drive - cfg.pen * n_fail
    out = dict(profit=profit, profit_total=profit + int(cfg.rev_mean) * n_morning_served, drive=drive, rev=rev_sd,
               n_acc=n_new_acc, n_fail=n_fail, n_cancel=n_cancel_eff, n_change=n_change_eff, n_ign=n_ign,
               a=a_cnt, b=b_cnt, c=int(c_cnt), ls_saved=ls_saved, ls_calls=ls_calls, accepted=accepted, fleet=fl,
               n_served_sd=sum(1 for n in served if inst.is_sd[n]), n_morning_served=n_morning_served,
               failed_orders=failed_orders, cancelled_orders=cancelled_orders, by_kind=by_kind, cur=cur)
    if log:
        out["trace"] = trace
        out["snaps"] = snaps
    return out
