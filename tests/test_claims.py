"""Jede Zahl der README (Abschnitte „Befunde", „Modell", „Ehrliche Grenzen", „Befunde und Korrekturen") wird hier aus data/nv_results.json
nachgerechnet, dazu Aufbau der README (Reihenfolge der Abschnitte, Nachbardemos, Dateistruktur gegen die echten Dateien). Die Vorzeichen stehen in
der README als Minuszeichen (U+2212); die Formate der App nutzen den Bindestrich, deshalb übersetzt `mn`."""
import pathlib
import re

import nv_constants as C
import nv_format as F
import nv_results as R

ROOT = pathlib.Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")
FLAT = re.sub(r"\s+", " ", README)                                              # Absätze der README sind hart umbrochen
DATA = R.load_results()
BASE = R.find_cell(DATA)
SD = R.sameday_cells(DATA)[0]


def mn(text):
    """ASCII-Bindestrich vor Ziffern als Minuszeichen (U+2212), wie in der README."""
    return re.sub(r"-(?=\d)", "−", text)


def has(text):
    assert mn(text) in FLAT, mn(text)


def gain(cell):
    return cell["pol"]["R"]["gain"]


def band(mean, se, digits=1, signed=True):
    return F.fmt_band(mean, se, digits, signed)


def pct(v):
    return f"{100 * v:.0f}"


# ---------------------------------------------------------------------------------------------------
# Aufbau
# ---------------------------------------------------------------------------------------------------
def test_readme_structure_follows_the_portfolio_order():
    headings = re.findall(r"^## (.+)$", README, flags=re.M)
    expected = ["Warum dieses Problem", "Befunde und Korrekturen gegenüber dem Plan", "Modell", "Methodik", "Befunde (gemessen, keine Behauptungen)", "Ehrliche Grenzen",
                "Verwandte Demos mit demselben mathematischen Modell", "Tests", "Dateistruktur", "Bewusst nicht umgesetzt", "Reproduktion der Messreihen", "Lokal ausführen"]
    assert headings == expected
    assert README.startswith("# Nahverkehr: Same-Day-Aufträge, Änderungen und der Preis der Planänderung – Streamlit-Demo\n\n*(noch nicht deployed)*\n")
    assert README.rstrip().endswith("Gebaut mit Streamlit, Plotly, OR-Tools und fpdf2.")
    assert "@@" not in README and "TODO" not in README and "noch offen" not in README


def test_related_demos_section_names_the_neighbours():
    section = README.split("## Verwandte Demos mit demselben mathematischen Modell")[1].split("\n## ")[0]
    assert "Stand 2026-09-24" in section
    for name in ("vrp_demo", "fahrzeugflotte-demo", "robuste-kaiplatz-demo", "blockzuweisung-demo", "hofrobust-demo", "revenue-management-demo", "fernverkehr-demo",
                 "Basismodell", "bepreiste Stabilitätsaspekt", "Schwester im Tourenplanungs-Zweig", "Annahme ohne Geometrie"):
        assert name in section, name


def test_file_table_lists_every_module_tool_and_data_file():
    table = README.split("## Dateistruktur")[1].split("## Bewusst nicht umgesetzt")[0]
    files = [p.name for p in ROOT.glob("*.py")] + [f"tools/{p.name}" for p in (ROOT / "tools").glob("*.py")] + ["data/nv_results.json"]
    for name in files:
        stem = name.split("/")[-1]
        assert f"`{name}`" in table or f"`{stem}`" in table or stem in table, name
    for mentioned in re.findall(r"`((?:nv_\w+|app|tools/\w+)\.py)`", table):
        assert (ROOT / mentioned).exists() or (ROOT / "tests" / mentioned).exists(), mentioned
    assert "`tests/`" in table and "data/nv_results.json" in table


def test_readme_mentions_only_existing_tests_and_tools():
    for path in re.findall(r"`(tools/\w+\.py)`", README):
        assert (ROOT / path).exists(), path
    for path in re.findall(r"`(tests/\w+\.py)`", README):
        assert (ROOT / path).exists(), path


def test_readme_has_honest_limits():
    limits = README.split("## Ehrliche Grenzen")[1].split("## Verwandte Demos")[0]
    for needle in ("Der Betrag ist klein", "rund 5 % Gewinn", "optimiert das Maß (a) selbst mit", "nur in 13 / 10 von 28 Zellen belastbar", "abgeleitet, nicht getestet",
                   "nachträglich angesetzt", "sind nicht λ", "Das Orakel ist klein und heuristisch", "10 (Änderungen) bzw. 16 (Annahme)", "Ein einzelner Tag streut stark",
                   "Stornokosten sind großenteils Erlösverlust"):
        assert needle in re.sub(r"\s+", " ", limits), needle


# ---------------------------------------------------------------------------------------------------
# Befunde: jede Zahl
# ---------------------------------------------------------------------------------------------------
def test_full_replanning_row():
    r = BASE["pol"]["R"]
    has(f"R dreht {band(r['a'], r['a_se'], signed=False)} Stopps je Tag um und bringt {band(r['gain'], r['gain_se'])} gegenüber dem starren Plan")
    has(f"({F.fmt_num(100 * r['gain'] / BASE['pol']['S0']['pt'])} % des Gewinns von S0), also {F.fmt_num(BASE['stats']['gain_per_change'])} Gewinn je Änderung")
    q = r["gain_q"]
    has(f"Median {F.fmt_num(q[1], 0, True)}, Quartile [{F.fmt_num(q[0], 0, True)}; {F.fmt_num(q[2], 0, True)}], {F.fmt_num(100 * r['wins'] / BASE['n'], 1)} % der Tage gewinnen")
    assert r["gain"] > q[1] > 0                                                   # schief verteilt: Mittel über Median


def test_share_row():
    p, f, t = ([R.share(BASE, fam, q) for q in (25, 50, 75)] for fam in ("P", "F", "T"))
    has(f"die Änderungsstrafe holt {pct(p[0])} % / {pct(p[1])} % / {pct(p[2])} % des R-Gewinns bei 25 / 50 / 75 % der R-Änderungen")
    has(f"der Einfrierhorizont nur {pct(f[0])} % / {pct(f[1])} % / {pct(f[2])} %, periodische Neuplanung {pct(t[0])} % / {pct(t[1])} % bei 25 / 50 %")


def test_penalty_beats_horizon_row():
    f25, f50 = BASE["F_vs_P"]["F_minus_P_25"], BASE["F_vs_P"]["F_minus_P_50"]
    has(f"F − P = {F.fmt_num(f25['mean'], 1, True)} (95 %: {F.fmt_num(f25['ci'][0])} bis {F.fmt_num(f25['ci'][1])}) bei 25 % und {F.fmt_num(f50['mean'], 1, True)} bei 50 % der R-Änderungen")
    n25, n50 = R.count_ci_negative(DATA, "a", 25)[0], R.count_ci_negative(DATA, "a", 50)[0]
    has(f"in {n25} bzw. {n50} von 28 Zellen unter 0, in keiner darüber")
    assert not any(c["F_vs_P"][k]["ci"][0] > 0 for c in R.stab_cells(DATA) for k in ("F_minus_P_25", "F_minus_P_50"))
    h_neg = sum(1 for c in R.h_cells(DATA) if c["H_vs_P"]["H_minus_P_25"]["ci"][1] < 0 and c["H_vs_P"]["H_minus_P_50"]["ci"][1] < 0)
    assert h_neg == len(R.h_cells(DATA)) == 7
    has("Mit dem zeitbasierten Horizont H in 7 von 7 Zellen")


def test_measure_row():
    has(f"unter (c) in {R.count_ci_negative(DATA, 'c', 25)[0]} / {R.count_ci_negative(DATA, 'c', 50)[0]} von 28 Zellen belastbar")
    has(f"unter (b) (angesagte Zeiten) nur in {R.count_ci_negative(DATA, 'b', 25)[0]} / {R.count_ci_negative(DATA, 'b', 50)[0]} von 28")


def test_price_row():
    has(f"R verliert ab {F.fmt_num(R.break_even_cost(BASE))} Kosten je Änderung gegen den starren Plan")
    costs = (0.0, 1.0, 2.0, 3.0, 5.0, 8.0)
    rows = {r["cc"]: r for r in R.net_table(BASE)}
    has("Bester Regler bei Kosten 0 / 1 / 2 / 3 / 5 / 8: " + " / ".join(R.policy_label(rows[c]["best"]) for c in costs))
    has("mit " + " / ".join(F.fmt_num(rows[c]["net_over_S0"], 1, True) for c in costs) + " gegenüber S0")
    has("(R selbst: " + " / ".join(F.fmt_num(rows[c]["net_R_over_S0"], 1, True) for c in costs) + ")")


def test_regime_row():
    def g(**kw):
        return gain(R.find_cell(DATA, **kw))
    has("Rate 0 / 2 / 6 / 12 je Stunde: R − S0 = " + " / ".join([F.fmt_num(g(lam=0.0), 1, True), F.fmt_num(g(lam=2.0), 0, True), F.fmt_num(gain(BASE), 0, True), F.fmt_num(g(lam=12.0), 0, True)]))
    has("Frist 60 / 120 / 240 min: " + " / ".join(F.fmt_num(v, 0, True) for v in (g(delta=60), gain(BASE), g(delta=240))))
    has("Morgenaufträge 16 / 28 / 40 / 52: " + " / ".join(F.fmt_num(v, 0, True) for v in (g(n_m=16), g(n_m=28), gain(BASE), g(n_m=52))))
    assert all(r["verdict"] == "pos" for r in R.regime_rows(DATA))
    has("in allen 28 Zellen ist R mehr als 2 Standardfehler besser als der starre Plan")


def test_driver_row():
    no_ev = R.find_cell(DATA, p_chg=0.0, p_cancel=0.0)
    rate0 = R.find_cell(DATA, lam=0.0)
    has(f"ohne jedes Änderungsereignis bringt R {band(gain(no_ev), no_ev['pol']['R']['gain_se'])}, mit Änderungen und Stornos {F.fmt_num(gain(BASE), 1, True)}")
    has(f"bei Rate 0 (nur Änderungen und Stornos) nur {F.fmt_num(gain(rate0), 1, True)}")
    assert gain(no_ev) > 5 * gain(rate0)                                          # der Nutzen kommt von den neuen Aufträgen


def test_event_cost_row():
    e = BASE["event_cost"]
    has(f"mit S0 {band(e['S0']['mean'], e['S0']['se'], 0, False)}, mit R {band(e['R']['mean'], e['R']['se'], 0, False)}")
    back = e["S0"]["mean"] - e["R"]["mean"]
    has(f"holt davon {band(back, e['gainR_extra']['se'], 0, False)} ({pct(back / e['S0']['mean'])} %) zurück")
    cancel = R.find_cell(DATA, p_chg=0.0, p_cancel=0.33)["event_cost"]["gainR_extra"]
    has(f"Reine Stornos: Neuplanung hilft nicht ({band(cancel['mean'], cancel['se'], 0)})")
    assert cancel["mean"] < 2 * cancel["se"]


def test_acceptance_rows():
    p = SD["pol"]
    pr = SD["pairs"]
    has(f"P1 {band(p['P1']['mean'], p['P1']['se'], 0, False)}, P1p {band(p['P1p']['mean'], p['P1p']['se'], 0, False)}, **Zeit-Schattenpreis P2 {band(p['P2']['mean'], p['P2']['se'], 0, False)}**")
    has(f"P2 − P1p = {band(pr['P2-P1p']['mean'], pr['P2-P1p']['se'], 0)}, die reine Erlös-Schwelle à la Littlewood P2v − P1p = {band(pr['P2v-P1p']['mean'], pr['P2v-P1p']['se'], 0)}")
    has(f"Neuoptimieren P1pL − P1p = {band(pr['P1pL-P1p']['mean'], pr['P1pL-P1p']['se'], 0)}, Schwelle auf Neuoptimierung P2L − P1pL = {band(pr['P2L-P1pL']['mean'], pr['P2L-P1pL']['se'], 0)}")
    assert abs(pr["P2L-P1pL"]["mean"]) < 1.0 * pr["P2L-P1pL"]["se"] + 1e-9        # nicht nachweisbar
    assert abs(pr["P2v-P1p"]["mean"]) < 2 * pr["P2v-P1p"]["se"] + 1e-9 or pr["P2v-P1p"]["mean"] < 0
    assert pr["P2-P1p"]["mean"] > 2 * pr["P2-P1p"]["se"]                            # der Schattenpreis wirkt belastbar


def test_oracle_rows():
    o = SD["oracle"]
    has(f"Orakel {band(o['ORA']['mean'], o['ORA']['se'], 0, False)}, die je Instanz beste Online-Regel holt {F.fmt_num(o['best_online_gain']['mean'], 0)}, Lücke {band(o['gap_best_online']['mean'], o['gap_best_online']['se'], 0, False)}")
    frist = R.sameday_rows(DATA, "frist")
    has("nach Frist 45 / 90 / 180 / 300 min holt sie " + " / ".join(pct(c["oracle"]["best_online_gain"]["mean"] / c["oracle"]["ORA"]["mean"]) for c in frist) + " % des Orakels")
    assert [c["cfg"]["delta"] for c in frist] == [45, 90, 180, 300]
    stab = BASE["oracle"]
    has(f"Lücke zu R {band(stab['gap_r'][0], stab['gap_r'][1], 0, False)} ({pct(stab['gap_r'][0] / stab['oracle_mean'])} % des Orakel-Gewinns)")
    assert SD["n_ora"] == 16 and stab["n"] == 10


def test_miscalibration_row():
    cell16 = next(x for x in DATA["sameday"]["cross"] if x["cfg"]["n_m"] == 16 and x["cfg"]["lam"] == 6.0)
    own = next(c for c in R.sameday_cells(DATA) if (c["cfg"]["n_m"], c["cfg"]["lam"], c["cfg"]["delta"]) == (16, 6.0, 120))
    v, o = cell16["pairs"]["P2-P1p"], own["pairs"]["P2-P1p"]
    has(f"(16 Morgenaufträge: P2 − P1p = {band(v['mean'], v['se'], 0)}, kalibriert {band(o['mean'], o['se'], 0)})")
    assert v["mean"] < -2 * v["se"]                                              # das Vorzeichen kippt belastbar


# ---------------------------------------------------------------------------------------------------
# Modell und Korrekturen
# ---------------------------------------------------------------------------------------------------
def test_model_numbers():
    has(f"im Mittel {F.fmt_num(BASE['n_events'])} Ereignisse je Tag")
    assert f"Auslastung {F.fmt_num(BASE['plan_util'], 2)})" in FLAT
    assert (BASE["cfg"]["K"], BASE["cfg"]["n_m"], BASE["cfg"]["lam"], BASE["cfg"]["delta"], BASE["cfg"]["p_chg"], BASE["cfg"]["p_cancel"]) == (3, 40, 6.0, 120, 0.25, 0.08)
    for needle in ("60 × 60 km", "**3 Transporter**", "1,2 min/km", "Service 6 min", "Schichtende nach 480 min", "40 Aufträge", "Zeitfenstern von 180 min", "[1, 300] min",
                   "Erlös lognormal (Mittel 60, σ 0,6)", "Wahrscheinlichkeit 0,25", "0,08 ein Storno", "±30 min", "Umkreis 5 km", "Strafe 60", "um mehr als 15 min",
                   "Bootstrap (300 Ziehungen)", "60 je bedientem Morgenauftrag"):
        assert needle in FLAT, needle
    from nv_model import Cfg
    c = Cfg()
    assert (c.area, c.speed, c.svc, c.H, c.win_w, c.t_arr, c.rev_mean, c.sigma, c.chg_delta, c.addr_radius, c.pen) == (60.0, 1.2, 6, 480, 180, 300, 60.0, 0.6, 30, 5.0, 60)
    import nv_sim
    assert nv_sim.ETA_TOL == 15
    import importlib.util
    spec = importlib.util.spec_from_file_location("nv_dump", ROOT / "tools" / "dump_sweep.py")
    dump = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dump)
    assert dump.N_BOOT == 300


def test_corrections_section_numbers():
    assert len(R.assignable_cells(DATA)) == 13 and len(R.sameday_candidates(DATA)) == 21
    assert "(13 Zellen liegen ganz auf den Stufen)" in FLAT and "21 passende Zellen" in FLAT and "24 / 40 / 52 Morgenaufträge mal Rate 2 / 6 / 12" in FLAT
    p1p = SD["pol"]["P1p"]["mean"]
    assert F.fmt_num(p1p, 1) == "706,5" and round(p1p) == 706
    assert "„707 ± 28" in FLAT and "Mittelwert der Rohzahlen ist 706,5 und rundet auf 706" in FLAT
    times = DATA["_timings"]["morgenplan_s"]
    assert min(min(v) for v in times.values()) == 0.5 and max(max(v) for v in times.values()) == 3.7
    assert "0,6 s (16 Morgenaufträge) bis 3,7 s (52)" in FLAT
    assert C.COST_STEP == 0.5 and "0,5er-Schritten" in FLAT and C.COST_RANGE == (0.0, 20.0)


def test_reproduction_section_matches_the_recorded_timings():
    t = DATA["_timings"]
    assert f"etwa **{t['messreihe_wanduhr_min']} Minuten Wanduhrzeit auf {t['messreihe_kerne']} Kernen**" in FLAT
    assert f"{t['sameday_wanduhr_min']} Minuten auf {t['sameday_prozesse']} Prozessen" in FLAT
    assert f"etwa {t['messreihe_wanduhr_min']} Minuten auf {t['messreihe_kerne']} Kernen" in FLAT
    for cmd in ("tools/sweep.py", "tools/dump_sweep.py", "tools/sweep_sameday.py", "tools/dump_sweep_sameday.py", "tools/build_results.py"):
        assert f"python {cmd}" in README


def test_presets_claims_match_the_help_texts():
    for name, text in C.PRESET_HELP.items():
        assert text and text[0].isupper()
    assert f"{R.break_even_cost(BASE):.1f}".replace(".", ",") in C.PRESET_HELP["Teure Änderungen"]
