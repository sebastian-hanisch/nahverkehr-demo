"""Testlücken, die der Fehler-Einbau-Test (tools/mutation_check.py) gefunden hat: die Tests standen zuerst nur auf ganzen Läufen (eingefrorene
Referenz) und übersahen Randfälle, die die Ergebnisse dieser Läufe nicht berühren. Jeder Test hier schließt eine benannte Lücke."""
import json
import pathlib
from dataclasses import replace

import pytest

import nv_constants as C
import nv_format as F
import nv_live as LV
import nv_model as M
import nv_oracle as O
import nv_presets as P
import nv_results as R
import nv_sim as S
import nv_stories as ST
import nv_ui_panel as UI
import nv_visualization as V

DATA = R.load_results()
BASE = R.find_cell(DATA)
TESTS = pathlib.Path(__file__).resolve().parent
FROZEN = json.loads((TESTS / "data" / "nv_morning.json").read_text(encoding="utf-8"))
HEURISTIC = json.loads((TESTS / "data" / "nv_heuristic.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------------------------------
# Morgenplan: der Teil, der nicht von OR-Tools abhängt (Aufträge, Heuristik, Ersetzungsregel)
# ---------------------------------------------------------------------------------------------------
def morning_without_ortools(cfg, seed, monkeypatch, fake=None):
    monkeypatch.setattr(M, "oracle", fake or (lambda *a, **k: dict(profit=None)))
    saved = dict(M._MORNING_CACHE)
    M._MORNING_CACHE.clear()
    try:
        return M.build_morning(cfg, seed)
    finally:
        M._MORNING_CACHE.clear()
        M._MORNING_CACHE.update(saved)


@pytest.mark.parametrize("n_m,seed", [(16, 0), (16, 1), (16, 2), (16, 3), (40, 0), (40, 1), (40, 2)])
def test_morning_orders_and_heuristic_do_not_depend_on_ortools(n_m, seed, monkeypatch):
    """Die Morgenaufträge (Zufallsstrom, Rejection-Sampling) sind reine Standardbibliothek und gleich denen der eingefrorenen Pläne; die Heuristik
    (Einfügen plus lokale Suche) liefert ohne OR-Tools die eingefrorenen Touren."""
    cfg = M.Cfg(K=3, n_m=n_m, lam=6.0)
    nodes, routes, shortfall = morning_without_ortools(cfg, seed, monkeypatch)
    frozen = FROZEN[json.dumps(list(M._morning_key(cfg, seed)))]
    assert [list(n) for n in nodes] == frozen[0] and shortfall == frozen[2] == HEURISTIC[f"{n_m}_{seed}"]["shortfall"]
    assert routes == HEURISTIC[f"{n_m}_{seed}"]["routes"]
    assert sorted(x for r in routes for x in r) == list(range(1, len(nodes) + 1))


def test_ortools_result_replaces_the_heuristic_only_if_strictly_shorter(monkeypatch):
    cfg = M.Cfg(K=3, n_m=16, lam=6.0)
    h_nodes, h_routes, _ = morning_without_ortools(cfg, 0, monkeypatch)
    inst = M.make_instance(cfg, 0)
    fl = M.Fleet(cfg.K)
    fl.routes = [list(r) for r in h_routes]
    for v, r in enumerate(fl.routes):
        fl.S[v], fl.F[v] = M.retime(inst, r, [], [], 0, -1)
    drive = M.fleet_drive(inst, fl)                                                     # Fahrzeit der Heuristik (nicht des eingefrorenen OR-Tools-Plans)
    swapped = [list(r) for r in reversed(h_routes)]
    same = morning_without_ortools(cfg, 0, monkeypatch, lambda *a, **k: dict(profit=-drive, routes=swapped))       # gleich lang: keine Ersetzung
    assert same[1] == h_routes
    better = morning_without_ortools(cfg, 0, monkeypatch, lambda *a, **k: dict(profit=-(drive - 1), routes=swapped))  # kürzer: ersetzt
    assert better[1] == swapped
    worse = morning_without_ortools(cfg, 0, monkeypatch, lambda *a, **k: dict(profit=-(drive + 5), routes=swapped))
    assert worse[1] == h_routes
    none = morning_without_ortools(cfg, 0, monkeypatch, lambda *a, **k: dict(profit=None, routes=None))
    assert none[1] == h_routes


def test_second_trips_of_a_vehicle_are_joined_by_a_depot_visit(monkeypatch):
    cfg = M.Cfg(K=2, n_m=6, lam=0.0, M=2)
    h_nodes, h_routes, _ = morning_without_ortools(cfg, 0, monkeypatch)
    nodes = list(range(1, len(h_nodes) + 1))
    trips = [nodes[:2], nodes[2:3], nodes[3:], []]                                # Fahrzeug 0: zwei Touren, Fahrzeug 1: eine Tour
    got = morning_without_ortools(cfg, 0, monkeypatch, lambda *a, **k: dict(profit=-1, routes=trips))
    assert got[1] == [nodes[:2] + [0] + nodes[2:3], nodes[3:]]


def test_draw_order_clips_both_coordinates_of_the_hotspot():
    import random
    cfg = replace(M.Cfg(), conc=1.0, hot_sd=100.0)
    xs, ys = [], []
    for s in range(300):
        x, y, _, _ = M.draw_order(cfg, random.Random(s), (30.0, 30.0))
        xs.append(x)
        ys.append(y)
    assert min(xs) == min(ys) == 0.0 and max(xs) == max(ys) == cfg.area


# ---------------------------------------------------------------------------------------------------
# Ereignisstrom an Handinstanzen
# ---------------------------------------------------------------------------------------------------
def event_instance(points, timed=True, **kw):
    """Instanz ohne Morgenplan-Rechnung: ein Fahrzeug, Morgenaufträge an `points` (Reihenfolge = Plan), Ereignisse aus make_events.
    timed=False: feste Servicebeginne 50 statt einer gültigen Zeitrechnung (für Instanzen, die der Schicht nicht genügen müssen)."""
    cfg = M.Cfg(K=1, n_m=0, lam=0.0, speed=1.0, svc=10, H=480, area=60.0, M=1, **kw)
    inst = M.make_instance(cfg, 0)
    for x, y in points:
        inst.add_node(x, y, 1, 0, 400, 0, False)
    inst.n_orders_base = inst.n_morning = len(points)
    fl = M.Fleet(1)
    fl.routes[0] = list(range(1, len(points) + 1))
    if timed:
        fl.S[0], fl.F[0] = M.retime(inst, fl.routes[0], [], [], 0, -1)
    else:
        fl.S[0], fl.F[0] = [50] * len(points), [60] * len(points)
    inst.plan = fl
    return inst


def test_morning_events_are_never_earlier_than_five_minutes():
    inst = event_instance([(31.0, 30.0)] * 6, p_chg=0.0, p_cancel=1.0)              # geplanter Servicebeginn 1, 11, ...: Ereignis vor dem Start
    M.make_events(inst, 3)
    assert inst.events and all(e["t"] >= 5 for e in inst.events)
    assert min(e["t"] for e in inst.events) == 5                                        # die Klammer auf 5 Minuten greift genau


def test_address_changes_are_clipped_to_the_area_on_both_axes():
    inst = event_instance([(0.0, 0.0), (60.0, 60.0)] * 20, timed=False, p_chg=1.0, p_cancel=0.0, w_time=0.0, w_addr=1.0, addr_radius=40.0)
    M.make_events(inst, 5)
    xs = [inst.xy[e["var"]][0] for e in inst.events]
    ys = [inst.xy[e["var"]][1] for e in inst.events]
    assert len(xs) == 40 and min(xs) == min(ys) == 0.0 and max(xs) == max(ys) == 60.0
    assert all(0.0 <= v <= 60.0 for v in xs + ys)


# ---------------------------------------------------------------------------------------------------
# Annahmeregeln: Vorgabewerte, Protokoll, Schwellen in decide
# ---------------------------------------------------------------------------------------------------
def accept_instance(rev):
    inst = event_instance([(40.0, 30.0), (60.0, 30.0)])
    X = inst.add_node(50.0, 40.0, 1, 1, 400, rev, True)
    inst.arrivals = [(1, X)]
    return inst, X


def test_default_arguments_of_the_rules():
    inst, X = accept_instance(rev=100)
    r = S.simulate(inst, "P2")                                                          # Vorgabe µ = 0: dieselbe Regel wie P1p
    assert r["profit"] == S.simulate(inst, "P1p")["profit"] == S.simulate(inst, "P2", mu=0.0)["profit"]
    assert "events" not in r and "snaps" not in r and r["ls_calls"] == 0                # Vorgaben: kein Protokoll, keine Neuoptimierung
    assert S.simulate(inst, "P2v")["n_acc"] == 1 and S.simulate(inst, "P2m")["n_acc"] == 1     # Vorgabe rho = 0
    inst2, X2 = accept_instance(rev=1)
    assert S.simulate(inst2, "P2v")["n_acc"] == 0 and S.simulate(inst2, "P2m")["n_acc"] == 0
    ok, best, n = S.decide(inst, inst.plan.clone(), X, 1, "P2")
    assert ok is True and n >= 1 and S.decide(inst, inst.plan.clone(), X, 1, "P2v")[0] is True
    assert S.decide(inst2, inst2.plan.clone(), X2, 1, "P2v")[0] is False and S.decide(inst2, inst2.plan.clone(), X2, 1, "P2m")[0] is False
    assert S.decide(inst2, inst2.plan.clone(), X2, 1, "P2c")[0] is False


def test_decide_p2_and_p2c_thresholds_are_exact():
    inst, X = accept_instance(rev=100)
    cs = M.candidates(inst, inst.plan, X, 1)
    best = min(cs, key=lambda c: (c[0], c[1], c[2], c[3]))
    extra, dend = best[0], best[1]
    assert (extra, dend) == (8, 18)                                                     # Anhängen nach B: Umweg 8 min, spätere Rückkehr um 18 min
    w = 1.0 - 1.0 / 300.0
    mu_ok = (100.0 - extra) / (w * dend)
    assert S.decide(inst, inst.plan.clone(), X, 1, "P2", mu=mu_ok - 0.001)[0] is True
    assert S.decide(inst, inst.plan.clone(), X, 1, "P2", mu=mu_ok + 0.001)[0] is False
    mu_c = (100.0 - extra) / dend
    assert S.decide(inst, inst.plan.clone(), X, 1, "P2c", mu=mu_c - 0.001)[0] is True
    assert S.decide(inst, inst.plan.clone(), X, 1, "P2c", mu=mu_c + 0.001)[0] is False
    eq, Xe = accept_instance(rev=extra)                                                 # Erlös = Zusatzkosten: angenommen (>=)
    assert S.decide(eq, eq.plan.clone(), Xe, 1, "P2", mu=0.0)[0] is True and S.decide(eq, eq.plan.clone(), Xe, 1, "P1p")[0] is True
    assert S.simulate(eq, "P2", mu=0.0)["n_acc"] == 1


def test_log_records_the_best_candidate_and_the_tie_count():
    inst, X = accept_instance(rev=100)
    r = S.simulate(inst, "P1p", log=True)
    (t, x, verdict, best, ties), = r["events"]
    cs = M.candidates(inst, inst.plan, X, 1)
    top = min(cs, key=lambda c: (c[0], c[1], c[2], c[3]))
    assert best == top[:4] and len(best) == 4 and ties == sum(1 for c in cs if c[:4] == top[:4]) == 1
    assert (t, x, verdict) == (1, X, "accept")


def test_rollout_defaults_and_result_fields():
    inst = M.make_instance(M.Cfg(K=3, n_m=16, lam=4.0), 2)
    default = S.simulate_rollout(inst)
    explicit = S.simulate_rollout(inst, S=16, base="P1p", ls=False, mu=0.0)
    assert default["profit"] == explicit["profit"] and default["accepted"] == explicit["accepted"]
    assert S.simulate_rollout(inst, S=17)["profit"] is not None and default["ls_calls"] == 0 and default["n_feas"] == 0
    assert S.simulate_rollout(inst, S=4, ls=True)["ls_calls"] == 0


def test_run_events_defaults_are_the_neutral_policy_parameters():
    inst = M.make_instance(replace(M.Cfg(K=3, n_m=16, lam=6.0), p_chg=0.25, p_cancel=0.08), 1)
    r = S.run_events(inst, "R")
    assert S.run_events(inst, "F")["fleet"].routes == r["fleet"].routes                 # k = 0
    assert S.run_events(inst, "P")["fleet"].routes == r["fleet"].routes                 # lam = 0
    assert S.run_events(inst, "T")["fleet"].routes == r["fleet"].routes                 # T_per = 0
    assert S.run_events(inst, "H")["fleet"].routes == r["fleet"].routes                 # H_min = 0
    assert "trace" not in r and "snaps" not in r                                        # log = False
    assert S.run_events(inst)["a"] == 0                                                 # Vorgabe: S0


# ---------------------------------------------------------------------------------------------------
# Orakel-Modell: Zulässigkeit wird geprüft
# ---------------------------------------------------------------------------------------------------
def orakel_instance():
    inst = event_instance([(40.0, 30.0)])
    return inst


def test_offline_profit_ev_checks_travel_time_and_the_shift_end():
    inst = orakel_instance()
    A = 1
    assert O.offline_profit_ev(inst, [[A]]) == 60 - 20                                  # bedient: Erlös 60, Fahrt 20
    inst.B[A] = 5                                                                        # Anfahrt 10 min, Frist 5: unzulässig
    with pytest.raises(AssertionError):
        O.offline_profit_ev(inst, [[A]])
    inst.B[A] = 400
    inst.A[A] = 470                                                                      # Fenster ab 470: Wartezeit, dann Rückfahrt über das Schichtende
    with pytest.raises(AssertionError):
        O.offline_profit_ev(inst, [[A]])
    with pytest.raises(AssertionError):
        _capacity_case()


def _capacity_case():
    inst = event_instance([(40.0, 30.0), (50.0, 30.0)])
    inst.cfg = replace(inst.cfg, Q=1)                                                    # Bedarf 1 + 1 > Q: Kapazität verletzt
    O.offline_profit_ev(inst, [[1, 2]])


# ---------------------------------------------------------------------------------------------------
# Auswertung, Live-Tag, Figuren, Tabellen
# ---------------------------------------------------------------------------------------------------
def test_sameday_setting_text_and_family_points_and_odd_median():
    sd = R.sameday_cells(DATA)[0]
    assert R.sameday_setting_text(sd) == "40 Morgenaufträge, Rate 6 je Stunde, Frist 120 min"
    pts = R.curve_points(BASE, "b")
    s0b = BASE["pol"]["S0"]["b"]
    for fam in C.FAMILIES:
        assert [p[0] for p in pts[fam]] == sorted(BASE["pol"][p[2]]["b"] - s0b for p in pts[fam])
    cells = [dict(stats={"share_P_50": v}) for v in (0.1, 0.9, 0.2, 0.8, 0.5)]
    assert R.median_share({"stab": {"cells": cells}}, "P") == 0.5


def test_live_stops_flag_changed_variants_by_node_number():
    inst = M.make_instance(LV.live_cfg(40, 6, "mittel", 120), 292)
    day = LV.day_detail(40, 6, "mittel", 120, 292, "R")
    stops = [s for v in day["vehicles"] for s in v["stops"]]
    assert stops and all(s["changed"] == (s["node"] > inst.n_orders_base) for s in stops)
    morning_vehicle = {}
    for v, route in enumerate(inst.plan.routes, 1):
        for n in route:
            morning_vehicle[inst.order_of[n]] = v
    for v in day["vehicles"]:
        for s in v["stops"]:
            if s["change"] == "anderes Fahrzeug":
                assert morning_vehicle[s["order"]] != v["vehicle"]
            elif s["change"] == "anderer Vorgänger":
                assert morning_vehicle[s["order"]] == v["vehicle"]
    assert {"anderes Fahrzeug", "anderer Vorgänger"} <= {s["change"] for s in stops}


def test_story_thresholds_are_the_planned_numbers():
    assert ST.STANDARD_MIN_P_SHARE == 0.75 and ST.STANDARD_MAX_F_SHARE == 0.70 and ST.MANY_MIN_GAIN == 200.0 and ST.MANY_MIN_PER_CHANGE == 5.0
    assert ST.ONLY_MAX_GAIN == 25.0 and ST.ONLY_MAX_CHANGES == 10.0 and ST.TIGHT_MIN_P2_GAIN == 40.0 and ST.DAY_ONLY_MAX_GAIN == 40.0


def fake_day(**pol):
    pol.setdefault("R", pol["S0"])
    return dict(results={p: dict(profit_total=v[0], a=v[1]) for p, v in pol.items()}, n_arrivals=4)


def test_story_criterion_texts_carry_signed_numbers():
    day = fake_day(S0=(1000, 0), R=(1100, 20), **{"P1.5": (1090, 5), "F3": (1010, 4), "P2": (1030, 4), "P3": (1090, 4)})
    texts = {n: [t for _, t in ST.day_criteria(n, day, C.PRESETS[n]["cost"])] for n in C.PRESETS}
    assert texts["Standard"][0] == "R gewinnt auf dem Tag: +100"
    assert texts["Standard"][1] == "P_1,5 netto mindestens so gut wie R: +80 gegenüber +60"
    assert texts["Standard"][2] == "P_1,5 ändert weniger als R: 5 gegenüber 20"
    assert texts["Viele neue Aufträge"] == ["R gewinnt auf dem Tag: +100", "neue Aufträge: 4"]
    assert texts["Nur Änderungen"][1] == "R − S0 auf dem Tag unter 40: +100"
    assert texts["Knappe Frist"] == ["P_2 gewinnt auf dem Tag: +30", "P_2 mindestens so gut wie F_3: +30 gegenüber +10"]
    expensive = fake_day(S0=(1000, 0), R=(1090, 20), P3=(1090, 4))                    # Kosten 5: R netto 990, P_3 netto 1070
    assert [t for _, t in ST.day_criteria("Teure Änderungen", expensive, 5.0)] == ["R netto unter S0 auf dem Tag: -10", "P_3 netto über R: +70 gegenüber -10"]
    m = [t for _, t in ST.criteria("Standard", DATA)]
    assert m[3] == "bei Kosten 2 bester Regler P_1,5 mit R netto darunter: P_1,5 +84,4 gegenüber R +65,8"
    assert ST.criteria("Teure Änderungen", DATA)[1][1] == "bester Regler P_3 netto über 0: P_3 +57,3 (+77,2 gegenüber R)"


def test_setting_specs_are_immutable_and_format_defaults():
    import dataclasses
    with pytest.raises(dataclasses.FrozenInstanceError):
        P.SETTING_SPECS["seed_input"].default = 5
    assert F.fmt_pct(12.34) == "12,3 %" and F.fmt_pct(12.34, signed=True) == "+12,3 %"


def test_message_today_sentence_keeps_the_sign():
    day = fake_day(S0=(1000, 0), R=(1100, 20), **{"P1.5": (1090, 5)})
    text = UI.message(day, BASE, 2.0)[1]
    assert "Auf diesem einen Tag: R netto +60 gegenüber S0, P_1,5 netto +80." in text
    text = UI.message(fake_day(S0=(1000, 0), R=(900, 20), **{"P3": (1010, 4)}), BASE, 5.0)[1]
    assert "Auf diesem einen Tag: R netto -200 gegenüber S0, P_3 netto -10." in text
    assert text.startswith("⚠️") and "netto -20 gegenüber S0" in text


def test_tables_signs_and_names_for_positive_values():
    positive = json.loads(json.dumps(DATA))
    cell = R.find_cell(positive)
    for k in ("F_minus_P_25", "F_minus_P_50", "F_minus_P_b_25", "F_minus_P_b_50", "F_minus_P_c_25", "F_minus_P_c_50"):
        cell["F_vs_P"][k] = dict(mean=5.0, ci=[1.0, 9.0])
    row = UI.measure_frame(positive, cell).iloc[0]
    assert row["F − P bei 25 % (95 %)"] == "+5,0 (1 bis 9)" and row["F − P bei 50 % (95 %)"] == "+5,0 (1 bis 9)"
    for c in R.h_cells(positive):
        c["H_vs_P"] = {k: dict(mean=3.0, ci=[1.0, 5.0]) for k in c["H_vs_P"]}
    h = UI.horizon_frame(positive)
    assert set(h["H − P bei 25 % (95 %)"]) == {"+3,0 (1 bis 5)"} and set(h["H − P bei 50 % (95 %)"]) == {"+3,0 (1 bis 5)"}
    assert UI.oracle_sameday_frame(DATA, "frist")["Orakel"].tolist() == ["900 ± 57", "1093 ± 66", "1289 ± 81", "1404 ± 89"]
    det = LV.day_detail(40, 6, "mittel", 120, 292, "R")
    ev = UI.events_table(det)
    by_kind = {}
    for e, name in zip(det["events"], ev["Ereignis"]):
        by_kind.setdefault(e["kind"], set()).add(name)
    assert by_kind["cancel"] == {"Storno"} and by_kind["change"] == {"Änderung"} and by_kind["ignored"] == {"ignoriert"}
    none_cell = json.loads(json.dumps(BASE))
    none_cell["stats"]["gain_per_change"] = None
    fake = {"stab": {"cells": [none_cell]}}
    assert UI.regime_frame(fake)["Gewinn je Änderung"].iloc[0] == "0,0"


def test_tours_and_map_figures_use_exact_bar_lengths_and_ranges():
    det = LV.day_detail(40, 6, "mittel", 120, 292, "R")
    fig = V.tours_figure(det)
    service = [t for t in fig.data if t.showlegend is not False]
    stops = {kind: [s for v in det["vehicles"] for s in v["stops"] if s["kind"] == kind] for kind in ("morning", "new", "changed")}
    for tr in service:
        kind = {"Morgenauftrag": "morning", "neuer Auftrag (Same-Day)": "new", "geänderter Morgenauftrag": "changed"}[tr.name]
        assert sorted(tr.x) == sorted(s["end"] - s["start"] for s in stops[kind]) and set(tr.x) == {6}
    windows = [t for t in fig.data if t.showlegend is False]
    for tr, kind in zip(windows, ("morning", "new", "changed")):
        assert sorted(tr.x) == sorted(s["window"][1] - s["window"][0] for s in stops[kind]) and tr.opacity == 0.22
    assert list(fig.layout.xaxis.range) == [0, det["shift_end"] + 10]
    m = V.route_map_figure(det)
    assert list(m.layout.yaxis.range) == [-2, det["area"] + 2] and list(m.layout.xaxis.range) == [-2, det["area"] + 2]
    assert m.layout.height == C.CHART_HEIGHT + 60 and fig.layout.height == max(C.CHART_HEIGHT - 120, 170 + 55 * 3)
    e = V.events_figure(det, [("R", C.COLOR_R, det)])
    assert list(e.layout.xaxis.range) == [0, 480] and list(e.layout.xaxis2.range) == [0, 480] and list(e.layout.yaxis.range) == [0.4, 1.6]


# ---------------------------------------------------------------------------------------------------
# Werkzeug build_results: Konstanten und Hauptablauf
# ---------------------------------------------------------------------------------------------------
def test_build_results_main_writes_the_file_from_given_inputs(tmp_path, monkeypatch, capsys):
    import importlib.util
    spec = importlib.util.spec_from_file_location("nv_tool_build_results_gaps", TESTS.parent / "tools" / "build_results.py")
    br = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(br)
    from test_tools import synthetic_stab_cell
    stab = dict(n_eval=200, n_ora=10, cells=[synthetic_stab_cell()])
    h = dict(cells=[dict(synthetic_stab_cell(), pol={"H15": dict(gain=1.0, gain_se=0.1, a=1.0, a_se=0.1, b=1.0, c=1.0)})])
    sd = dict(n_eval=60, cells=[], cross=[])
    files = []
    for name, payload in (("stab.json", stab), ("h.json", h), ("sd.json", sd)):
        p = tmp_path / name
        p.write_text(json.dumps(payload), encoding="utf-8")
        files.append(str(p))
    timing = tmp_path / "t.txt"
    timing.write_text("n_m=16 seed=1: instance+morning 0.6s events 0.00s | S0 0.00s\n", encoding="utf-8")
    out = tmp_path / "out" / "nv_results.json"
    out.parent.mkdir()                                                                   # der Ordner existiert schon: mkdir(exist_ok=True)
    monkeypatch.setattr(br, "OUT", out)
    assert br.main(files + [str(timing), "ignoriertes fünftes Argument"]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["_timings"]["morgenplan_s"] == {"16": [0.6]} and data["_meta"]["n_eval"] == 200 and out.read_text(encoding="utf-8").endswith("\n")
    printed = capsys.readouterr().out
    assert "geschrieben:" in printed and "1 Stabilitäts-, 1 H-, 0 Annahme-Zellen" in printed
    assert f"({out.stat().st_size / 1024:.0f} KB;" in printed
    assert br.TIMINGS_CONST == dict(messreihe_wanduhr_min=35, messreihe_kerne=14, sameday_wanduhr_min=72, sameday_prozesse=16)
    assert br.DIGITS == 4


# ---------------------------------------------------------------------------------------------------
# zweite Runde des Fehler-Einbau-Tests
# ---------------------------------------------------------------------------------------------------
def test_documented_default_arguments():
    """Die Vorgabewerte der Simulationsfunktionen sind Teil ihrer Schnittstelle (S0 = kein Neuoptimieren, Regler-Parameter neutral)."""
    import inspect

    def defaults(fn):
        return {k: v.default for k, v in inspect.signature(fn).parameters.items() if v.default is not inspect.Parameter.empty}
    assert defaults(S.simulate) == dict(mu=0.0, rho=0.0, ls=False, log=False, vehicle_order=None, arrivals=None)
    assert defaults(S.decide) == dict(mu=0.0, rho=0.0)
    assert defaults(S.simulate_rollout) == dict(S=16, base="P1p", ls=False, mu=0.0)
    assert defaults(S.run_events) == dict(kind="S0", k=0, lam=0.0, T_per=0, log=False, H_min=0)


def test_p2_default_threshold_is_zero_and_decide_uses_it():
    inst, X = accept_instance(rev=9)                                                    # Zusatzkosten 8: mit µ = 0 angenommen, mit µ = 0,1 (8 + 0,1 * 18 * w = 9,8) nicht
    assert S.simulate(inst, "P2")["n_acc"] == 1 and S.decide(inst, inst.plan.clone(), X, 1, "P2")[0] is True
    assert S.simulate(inst, "P2", mu=0.1)["n_acc"] == 0 and S.decide(inst, inst.plan.clone(), X, 1, "P2c")[0] is True
    assert S.decide(inst, inst.plan.clone(), X, 1, "P2c", mu=0.1)[0] is False


def test_tie_count_counts_only_equal_candidates():
    inst = event_instance([(40.0, 30.0), (50.0, 30.0), (60.0, 30.0)])
    X = inst.add_node(45.0, 40.0, 1, 1, 400, 100, True)
    inst.arrivals = [(1, X)]
    cs = M.candidates(inst, inst.plan, X, 1)
    assert len(cs) >= 3
    (t, x, verdict, best, ties), = S.simulate(inst, "P1p", log=True)["events"]
    top = min(cs, key=lambda c: (c[0], c[1], c[2], c[3]))
    assert best == top[:4] and ties == 1 == sum(1 for c in cs if c[:4] == top[:4])


def test_day_criteria_boundaries_with_a_single_unit():
    one = dict(results=dict(S0=dict(profit_total=1000, a=0), R=dict(profit_total=1001, a=3), F3=dict(profit_total=1000, a=0), P2=dict(profit_total=1001, a=1)),
               n_arrivals=1)
    assert [ok for ok, _ in ST.day_criteria("Viele neue Aufträge", one, 2.0)] == [True, True]
    assert [ok for ok, _ in ST.day_criteria("Knappe Frist", one, 2.0)] == [True, True]


def test_stops_of_a_day_without_new_orders_are_morning_or_changed_by_node_number():
    inst = M.make_instance(LV.live_cfg(40, 0, "mittel", 120), 292)
    day = LV.day_detail(40, 0, "mittel", 120, 292, "R")
    stops = [s for v in day["vehicles"] for s in v["stops"]]
    assert stops and {s["kind"] for s in stops} == {"morning", "changed"} and inst.n_orders_base == inst.n_morning
    assert all((s["kind"] == "changed") == (s["node"] > inst.n_orders_base) and s["changed"] == (s["node"] > inst.n_orders_base) for s in stops)
    assert any(s["node"] == inst.n_orders_base for s in stops)                          # der letzte Morgenauftrag ist ein Ursprungsknoten, keine Variante
