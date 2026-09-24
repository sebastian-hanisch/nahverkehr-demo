"""Die Live-Rechnung: EIN Tag (Instanz mit Morgenplan, Same-Day-Aufträgen, Änderungen und Stornos), alle Politiken über denselben Tag.

Gerechnet wird mit nv_model / nv_sim (unverändert aus der Messreihe). Der Morgenplan (OR-Tools, 0,6 bis 3,7 s) ist der teure Teil,
jede Simulation dauert 0,01 bis 0,08 s. Kein Streamlit: die Funktionen liefern reine Daten-Wörterbücher (Listen, Zahlen, Text), die sich
mit st.cache_data zwischenspeichern lassen. Der Festplatten-Zwischenspeicher für Morgenpläne ist hier ausdrücklich AUS (Streamlit
Cloud): nv_model.MORNING_DISK_CACHE = None; zwischengespeichert wird im Speicher (nv_model) und über st.cache_data (app.py)."""
import math
import time

import nv_constants as C
import nv_model as M
import nv_sim as S

M.MORNING_DISK_CACHE = None            # die App schreibt nie auf die Festplatte

METRIC_KEYS = ("profit_total", "profit", "drive", "a", "b", "c", "n_fail", "n_acc", "n_cancel", "n_change", "n_ign", "ls_saved",
               "n_morning_served", "n_served_sd", "rev")


def live_cfg(morning, rate, events, deadline):
    """Parameter des Tages: Basisfall der Messreihe (3 Transporter) mit den eingestellten Stufen."""
    p_chg, p_cancel = C.EVENT_LEVELS[events]
    return M.Cfg(K=3, n_m=int(morning), lam=float(rate), delta=int(deadline), p_chg=p_chg, p_cancel=p_cancel)


def build_instance(morning, rate, events, deadline, seed):
    """(Instanz, Parameter) des Tages; Instanz und Ereignisstrom sind je (Parameter, Seed) deterministisch."""
    cfg = live_cfg(morning, rate, events, deadline)
    return M.make_instance(cfg, int(seed)), cfg


def _summary(r):
    return {k: r[k] for k in METRIC_KEYS}


def solve_day(morning, rate, events, deadline, seed):
    """Rechnet alle Politiken (S0, R, F_k, P_λ, T_x) über denselben Tag. Rückgabe ein reines Wörterbuch:
    Tageskennzahlen und je Politik die Kennzahlen (Gewinn, Änderungen (a) (b) (c), angenommene, gescheiterte Aufträge ...)."""
    t0 = time.time()
    inst, cfg = build_instance(morning, rate, events, deadline, seed)
    t1 = time.time()
    results = {name: _summary(S.run_events(inst, **C.POLICY_SPECS[name])) for name in C.POLICY_NAMES}
    plan_util = sum(M.vend(inst, rt, f) for rt, f in zip(inst.plan.routes, inst.plan.F)) / (cfg.K * cfg.H)
    return dict(morning=int(morning), rate=int(rate), events=events, deadline=int(deadline), seed=int(seed), n_morning=inst.n_morning,
                n_arrivals=len(inst.arrivals), n_events=len(inst.events), n_orders=inst.n_orders_base,
                plan_drive=M.fleet_drive(inst, inst.plan), plan_util=plan_util, results=results,
                seconds_morning=round(t1 - t0, 1), seconds=round(time.time() - t0, 1))


# ----------------------------------------------------------------------------------------------------------------
# Tagesverlauf einer Politik: Touren, Ereignisse, Änderungen je Ereignis
# ----------------------------------------------------------------------------------------------------------------
def _event_text(inst, e):
    """Kurztext einer Änderung/eines Stornos (aus den Attributen des Ursprungs- und des Variantenknotens)."""
    if e["kind"] == "cancel":
        return "Storno"
    o, w = e["order"], e["var"]
    if e["kind"] == "time":
        return f"Zeitfenster um {inst.A[w] - inst.A[o]:+d} min verschoben"
    if e["kind"] == "addr":
        km = math.hypot(inst.xy[w][0] - inst.xy[o][0], inst.xy[w][1] - inst.xy[o][1])
        return f"Adresse um {km:.1f} km verschoben".replace(".", ",")
    return f"Menge {inst.dem[o]} → {inst.dem[w]}"


def _route_drive(inst, route):
    """Fahrminuten einer Tour (Depot, Stopps, Depot)."""
    if not route:
        return 0
    T = inst.T
    return T[0][route[0]] + T[route[-1]][0] + sum(T[a][b] for a, b in zip(route, route[1:]))


def day_detail(morning, rate, events, deadline, seed, policy):
    """Der Tag unter EINER Politik (mit Protokoll): Touren mit Zeiten, Ereignisliste mit Änderungen je Ereignis, Karte.

    Ereignis: t (Minute), kind ('new', 'new_rejected', 'change', 'cancel', 'ignored'), order, text, a (geänderte Stopps fahrerseitig),
    b (geänderte Ankunftsansagen). Stopps: Knoten, Auftrag, Art (Morgen/neu/geändert), Servicebeginn, Zeitfenster, Erlös, Änderung
    gegenüber dem Morgenplan."""
    inst, cfg = build_instance(morning, rate, events, deadline, seed)
    r = S.run_events(inst, log=True, **C.POLICY_SPECS[policy])
    oo = inst.order_of
    trace = {(t, typ, o): (a, b) for t, typ, o, a, b in r["trace"]}
    accepted = set(r["accepted"])
    evs = []
    for t, x in inst.arrivals:
        if x in accepted:
            a, b = trace[(t, "new", x)]
            evs.append(dict(t=t, kind="new", order=x, text=f"neuer Auftrag, Erlös {inst.rev[x]}", a=a, b=b))
        else:
            evs.append(dict(t=t, kind="new_rejected", order=x, text=f"neuer Auftrag abgelehnt (Erlös {inst.rev[x]})", a=0, b=0))
    for e in inst.events:
        key = (e["t"], "ev", e["order"])
        if key in trace:
            a, b = trace[key]
            evs.append(dict(t=e["t"], kind="cancel" if e["kind"] == "cancel" else "change", order=e["order"], text=_event_text(inst, e),
                            a=a, b=b))
        else:
            evs.append(dict(t=e["t"], kind="ignored", order=e["order"], text=_event_text(inst, e) + " (wirkungslos: Auftrag schon bindend)",
                            a=0, b=0))
    evs.sort(key=lambda d: (d["t"], d["order"]))
    # Morgenplan: (Fahrzeug, Vorgänger) je Auftrag, zum Vergleich mit dem Endplan. Wie beim Maß (a) zählen stornierte und gescheiterte
    # Aufträge nicht als Vorgänger, und neue Aufträge werden übersprungen: das Einfügen oder Entfernen eines Auftrags markiert seine
    # Nachbarn nicht als geändert.
    removed = set(r["cancelled_orders"]) | set(r["failed_orders"])
    morning_pos = {}
    for v, route in enumerate(inst.plan.routes):
        pred_o = 0
        for node in route:
            o = oo[node]
            if o in removed:
                continue
            morning_pos[o] = (v, pred_o)
            pred_o = o
    fl = r["fleet"]
    vehicles = []
    for v, (route, Sv, Fv) in enumerate(zip(fl.routes, fl.S, fl.F)):
        stops, pred_o = [], 0
        for node, s, f in zip(route, Sv, Fv):
            o = oo[node]
            kind = "new" if inst.is_sd[node] else ("changed" if node > inst.n_orders_base else "morning")
            if inst.is_sd[node]:
                change = "neu"
            else:
                mv, mp = morning_pos[o]
                change = "–" if (mv, mp) == (v, pred_o) else ("anderes Fahrzeug" if mv != v else "anderer Vorgänger")
                pred_o = o
            stops.append(dict(node=node, order=o, kind=kind, changed=node > inst.n_orders_base, start=s, end=f, window=(inst.A[node], inst.B[node]),
                              rev=inst.rev[node], x=inst.xy[node][0], y=inst.xy[node][1], dem=inst.dem[node], change=change))
        vehicles.append(dict(vehicle=v + 1, stops=stops, return_time=(Fv[-1] + inst.T[route[-1]][0]) if route else 0,
                             drive=_route_drive(inst, route)))
    rejected = [dict(t=t, x=inst.xy[n][0], y=inst.xy[n][1], rev=inst.rev[n], order=n) for t, n in inst.arrivals if n not in accepted]
    return dict(policy=policy, depot=inst.xy[0], vehicles=vehicles, events=evs, rejected=rejected, area=cfg.area, shift_end=cfg.H,
                metrics=_summary(r), failed=list(r["failed_orders"]), cancelled=list(r["cancelled_orders"]))


# ----------------------------------------------------------------------------------------------------------------
# Kernabschnitt ①: Annahmeregeln auf demselben Tag ohne Änderungsereignisse (wie in der Messreihe)
# ----------------------------------------------------------------------------------------------------------------
ACCEPT_RUNS = ("P0", "P1", "P1p", "P2", "P1pL", "P2L")


def solve_accept(morning, rate, deadline, seed, mu, mu_L):
    """Die Annahmeregeln P0, P1, P1p, P2 (Schwelle µ), P1pL, P2L (Schwelle µ_L, mit Neuoptimierung) auf demselben Tag OHNE
    Änderungsereignisse (die Messreihe der Annahme kennt keine). Instanz und Morgenplan sind dieselben wie in solve_day."""
    cfg = live_cfg(morning, rate, "keine", deadline)
    inst = M.make_instance(cfg, int(seed))
    runs = {"P0": S.simulate(inst, "P0"), "P1": S.simulate(inst, "P1"), "P1p": S.simulate(inst, "P1p"),
            "P2": S.simulate(inst, "P2", mu=mu), "P1pL": S.simulate(inst, "P1p", ls=True), "P2L": S.simulate(inst, "P2", mu=mu_L, ls=True)}
    base = runs["P0"]["profit"]
    out = {name: dict(profit=r["profit"], gain=r["profit"] - base, n_acc=r["n_acc"], drive=r["drive"], rev=r["rev"], n_feas=r["n_feas"])
           for name, r in runs.items()}
    return dict(rules=out, n_arrivals=len(inst.arrivals), mu=mu, mu_L=mu_L, seed=int(seed))
