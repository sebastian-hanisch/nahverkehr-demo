"""Die Live-Rechnung (nv_live): ein Tag, alle Politiken, Tagesverlauf einer Politik, Annahmeregeln ohne Änderungsereignisse. Rechnet auf den
eingefrorenen Morgenplänen (nur Simulation); die Ergebnisse müssen exakt die von nv_sim sein."""
import math
from dataclasses import replace

import pytest

import nv_constants as C
import nv_live as LV
import nv_model as M
import nv_sim as S

DAY = dict(morning=40, rate=6, events="mittel", deadline=120, seed=292)
SMALL = dict(morning=16, rate=6, events="mittel", deadline=120, seed=1)


def solve(**kw):
    a = dict(DAY, **kw)
    return LV.solve_day(a["morning"], a["rate"], a["events"], a["deadline"], a["seed"])


def detail(policy, **kw):
    a = dict(DAY, **kw)
    return LV.day_detail(a["morning"], a["rate"], a["events"], a["deadline"], a["seed"], policy)


def test_live_cfg_maps_the_controls_to_the_measured_model():
    cfg = LV.live_cfg(28, 12, "viele", 240)
    assert (cfg.K, cfg.n_m, cfg.lam, cfg.delta, cfg.p_chg, cfg.p_cancel) == (3, 28, 12.0, 240, 0.5, 0.16)
    assert isinstance(cfg.n_m, int) and isinstance(cfg.lam, float) and isinstance(cfg.delta, int)
    base = LV.live_cfg(40, 6, "mittel", 120)
    assert base == replace(M.Cfg(), K=3, n_m=40, lam=6.0, delta=120, p_chg=0.25, p_cancel=0.08)
    assert LV.live_cfg(16, 0, "keine", 60).p_chg == 0.0 and LV.live_cfg(16, 0, "keine", 60).lam == 0.0
    for level, (pc, pk) in C.EVENT_LEVELS.items():
        c = LV.live_cfg(40, 6, level, 120)
        assert (c.p_chg, c.p_cancel) == (pc, pk)


def test_app_never_writes_morning_plans_to_disk():
    assert LV.M.MORNING_DISK_CACHE is None and M.MORNING_DISK_CACHE is None


def test_solve_day_equals_direct_simulation():
    day = solve()
    inst = M.make_instance(LV.live_cfg(40, 6, "mittel", 120), 292)
    assert set(day["results"]) == set(C.POLICY_NAMES)
    for name in C.POLICY_NAMES:
        r = S.run_events(inst, **C.POLICY_SPECS[name])
        assert day["results"][name] == {k: r[k] for k in LV.METRIC_KEYS}, name
    assert (day["n_morning"], day["n_arrivals"], day["n_events"], day["n_orders"]) == (inst.n_morning, len(inst.arrivals), len(inst.events), inst.n_orders_base)
    assert day["plan_drive"] == M.fleet_drive(inst, inst.plan)
    assert day["plan_util"] == pytest.approx(sum(M.vend(inst, r, f) for r, f in zip(inst.plan.routes, inst.plan.F)) / (3 * 480))
    assert 0.6 < day["plan_util"] < 0.8 and day["seconds"] >= day["seconds_morning"] >= 0


def test_solve_day_is_deterministic():
    a, b = solve(), solve()
    assert a["results"] == b["results"] and a["n_events"] == b["n_events"]


def test_rows_have_all_metrics_and_s0_definitions():
    day = solve()
    for name, r in day["results"].items():
        assert set(r) == set(LV.METRIC_KEYS), name
    s0 = day["results"]["S0"]
    assert s0["a"] == 0 and s0["c"] == 0 and s0["n_change"] + s0["n_cancel"] + s0["n_ign"] == day["n_events"]
    for name, r in day["results"].items():
        assert r["profit_total"] == r["profit"] + 60 * r["n_morning_served"], name
        assert r["a"] >= r["c"] >= 0 and r["b"] >= 0 and r["n_fail"] >= 0


def test_no_event_day_has_no_changes_anywhere():
    day = solve(events="keine")
    assert day["n_events"] == 0
    for name, r in day["results"].items():
        assert r["n_change"] == 0 and r["n_cancel"] == 0 and r["n_ign"] == 0 and r["n_fail"] == 0, name


def test_rate_zero_day_has_no_new_orders():
    day = solve(rate=0)
    assert day["n_arrivals"] == 0 and all(r["n_acc"] == 0 and r["n_served_sd"] == 0 for r in day["results"].values())


def test_detail_events_match_the_counters():
    for policy in ("S0", "R", "P1.5", "F3", "T60"):
        d = detail(policy)
        m = d["metrics"]
        by_kind = {k: sum(1 for e in d["events"] if e["kind"] == k) for k in C.EVENT_NAMES}
        assert by_kind["new"] == m["n_acc"] and by_kind["cancel"] == m["n_cancel"] and by_kind["change"] == m["n_change"]
        assert by_kind["ignored"] == m["n_ign"] and by_kind["new_rejected"] == len(d["rejected"])
        assert sum(e["a"] for e in d["events"]) == m["a"] and sum(e["b"] for e in d["events"]) == m["b"]
        assert [e["t"] for e in d["events"]] == sorted(e["t"] for e in d["events"])
        stops = [s for v in d["vehicles"] for s in v["stops"]]
        assert len(stops) == m["n_morning_served"] + m["n_served_sd"]
        assert m == solve()["results"][policy]                                # dieselben Kennzahlen wie die Live-Rechnung
        for e in d["events"]:
            assert e["kind"] in C.EVENT_NAMES and isinstance(e["text"], str) and e["text"]
            if e["kind"] in ("new_rejected", "ignored"):
                assert e["a"] == 0 and e["b"] == 0


def test_detail_stops_are_valid_plans():
    d = detail("R")
    assert d["depot"] == (30.0, 30.0) and d["area"] == 60.0 and d["shift_end"] == 480 and len(d["vehicles"]) == 3
    for v in d["vehicles"]:
        assert v["vehicle"] in (1, 2, 3)
        prev_end = 0
        for s in v["stops"]:
            assert s["start"] >= prev_end and s["end"] > s["start"] and s["window"][0] <= s["start"] <= s["window"][1]
            assert s["kind"] in ("morning", "new", "changed") and s["change"] in ("–", "neu", "anderes Fahrzeug", "anderer Vorgänger")
            assert (s["kind"] == "new") == (s["change"] == "neu")
            assert 0 <= s["x"] <= 60 and 0 <= s["y"] <= 60
            prev_end = s["end"]
        if v["stops"]:
            last = v["stops"][-1]
            assert v["return_time"] == last["end"] + math.ceil(math.hypot(last["x"] - 30, last["y"] - 30) * 1.2)
            assert v["return_time"] <= 480 and v["drive"] > 0
        else:
            assert v["return_time"] == 0 and v["drive"] == 0
    kinds = {s["kind"] for v in d["vehicles"] for s in v["stops"]}
    assert kinds == {"morning", "new", "changed"}


def test_detail_marks_replanned_stops_only_under_replanning():
    calm = LV.day_detail(40, 6, "keine", 120, 292, "S0")
    assert {s["change"] for v in calm["vehicles"] for s in v["stops"]} == {"–", "neu"}      # ohne Ereignisse bewegt S0 nichts
    r, s0 = detail("R"), detail("S0")

    def flagged(d):
        return sum(1 for v in d["vehicles"] for s in v["stops"] if s["change"] in ("anderes Fahrzeug", "anderer Vorgänger"))

    assert flagged(r) > flagged(s0) and flagged(r) > 5
    assert any(s["change"] == "anderes Fahrzeug" for v in r["vehicles"] for s in v["stops"])


def test_detail_event_texts():
    d = detail("R")
    texts = " ".join(e["text"] for e in d["events"])
    assert "Storno" in texts and "Zeitfenster um" in texts and "Adresse um" in texts and "neuer Auftrag, Erlös" in texts and "abgelehnt" in texts
    assert all(e["text"].endswith("(wirkungslos: Auftrag schon bindend)") for e in d["events"] if e["kind"] == "ignored")
    assert not any("Menge" in e["text"] for e in d["events"])                     # Mengenänderung nur mit endlicher Kapazität


def test_event_text_variants():
    inst = M.make_instance(replace(M.Cfg(K=3, n_m=40, lam=0.0), p_chg=0.0, p_cancel=0.0), 0)
    o = inst.n_morning - 1
    w_t = inst.add_node(inst.xy[o][0], inst.xy[o][1], inst.dem[o], inst.A[o] + 30, inst.B[o] + 30, 0, False)
    w_a = inst.add_node(inst.xy[o][0] + 3.0, inst.xy[o][1] + 4.0, inst.dem[o], inst.A[o], inst.B[o], 0, False)
    w_q = inst.add_node(inst.xy[o][0], inst.xy[o][1], inst.dem[o] + 2, inst.A[o], inst.B[o], 0, False)
    assert LV._event_text(inst, dict(kind="cancel", order=o, var=None)) == "Storno"
    assert LV._event_text(inst, dict(kind="time", order=o, var=w_t)) == "Zeitfenster um +30 min verschoben"
    assert LV._event_text(inst, dict(kind="addr", order=o, var=w_a)) == "Adresse um 5,0 km verschoben"
    assert LV._event_text(inst, dict(kind="qty", order=o, var=w_q)) == f"Menge {inst.dem[o]} → {inst.dem[o] + 2}"
    w_m = inst.add_node(inst.xy[o][0], inst.xy[o][1], inst.dem[o], max(0, inst.A[o] - 30), inst.B[o] - 30, 0, False)
    assert LV._event_text(inst, dict(kind="time", order=o, var=w_m)) == f"Zeitfenster um {max(0, inst.A[o] - 30) - inst.A[o]:+d} min verschoben"


def test_detail_rejected_orders_are_the_unaccepted_arrivals():
    d = detail("R")
    inst = M.make_instance(LV.live_cfg(40, 6, "mittel", 120), 292)
    r = S.run_events(inst, "R")
    rej = {x for _, x in inst.arrivals} - set(r["accepted"])
    assert {q["order"] for q in d["rejected"]} == rej and len(rej) > 0
    for q in d["rejected"]:
        assert q["rev"] == inst.rev[q["order"]] and (q["x"], q["y"]) == inst.xy[q["order"]]


def test_route_drive_hand_case():
    inst = M.make_instance(replace(M.Cfg(K=1, n_m=0, lam=0.0, speed=1.0), K=1), 0)
    a = inst.add_node(40.0, 30.0, 1, 0, 400, 0, False)
    b = inst.add_node(40.0, 40.0, 1, 0, 400, 0, False)
    assert LV._route_drive(inst, [a, b]) == 10 + 10 + math.ceil(math.hypot(10, 10)) and LV._route_drive(inst, []) == 0
    assert LV._route_drive(inst, [a]) == 20


def test_solve_accept_matches_direct_simulation_and_is_paired():
    acc = LV.solve_accept(40, 6, 120, 292, 3.0, 1.5)
    inst = M.make_instance(LV.live_cfg(40, 6, "keine", 120), 292)
    base = S.simulate(inst, "P0")["profit"]
    expected = {"P0": S.simulate(inst, "P0"), "P1": S.simulate(inst, "P1"), "P1p": S.simulate(inst, "P1p"), "P2": S.simulate(inst, "P2", mu=3.0),
                "P1pL": S.simulate(inst, "P1p", ls=True), "P2L": S.simulate(inst, "P2", mu=1.5, ls=True)}
    assert set(acc["rules"]) == set(LV.ACCEPT_RUNS)
    for name, r in expected.items():
        assert acc["rules"][name] == dict(profit=r["profit"], gain=r["profit"] - base, n_acc=r["n_acc"], drive=r["drive"], rev=r["rev"], n_feas=r["n_feas"])
    assert acc["rules"]["P0"]["gain"] == 0 and acc["rules"]["P0"]["n_acc"] == 0
    assert acc["n_arrivals"] == len(inst.arrivals) and acc["mu"] == 3.0 and acc["mu_L"] == 1.5 and acc["seed"] == 292
    assert acc["rules"]["P1p"]["gain"] > 0


def test_solve_accept_uses_the_same_day_as_solve_day():
    """Der Annahme-Tag ist der Live-Tag ohne Änderungsereignisse: dieselben Morgenaufträge und dieselben neuen Aufträge."""
    ev_inst = M.make_instance(LV.live_cfg(40, 6, "mittel", 120), 292)
    plain = M.make_instance(LV.live_cfg(40, 6, "keine", 120), 292)
    assert plain.arrivals == ev_inst.arrivals and plain.plan.routes == ev_inst.plan.routes
    acc = LV.solve_accept(40, 6, 120, 292, 0.0, 0.0)
    # mit µ = 0 sind P2 und P1p dieselbe Regel; S0 des Live-Tages ohne Ereignisse ist P1p, R ist P1pL (bitgleich zu sameday)
    day = solve(events="keine")
    assert acc["rules"]["P1p"]["profit"] == day["results"]["S0"]["profit"] and acc["rules"]["P2"]["profit"] == acc["rules"]["P1p"]["profit"]
    assert acc["rules"]["P1pL"]["profit"] == day["results"]["R"]["profit"]


def test_solve_accept_rate_zero():
    acc = LV.solve_accept(40, 0, 120, 292, 3.0, 1.5)
    assert acc["n_arrivals"] == 0 and all(r["gain"] == 0 and r["n_acc"] == 0 for r in acc["rules"].values())


def test_small_day_runs_on_the_frozen_plan():
    day = LV.solve_day(**{k: SMALL[k] for k in ("morning", "rate", "events", "deadline", "seed")})
    assert day["n_morning"] <= 16 and day["results"]["R"]["profit_total"] > 0
