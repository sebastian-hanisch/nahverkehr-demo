"""AppTest: Skelett und Footer, jedes Preset, Permalink, alle Regler an Min und Max, alle drei Meldungszustände, Kernabschnitte, Ansichten, PDF,
Texte. Die Live-Rechnung läuft auf den EINGEFRORENEN Morgenplänen (tests/conftest.py: OR-Tools ist gesperrt), also ohne Wall-Clock-Annahmen."""
import pathlib

import pytest
from streamlit.testing.v1 import AppTest

import nv_constants as C
import nv_live as LV
import nv_results as R
import nv_presets as P
from nv_presets import PRESET_STATE_KEYS, SETTING_SPECS

APP = str(pathlib.Path(__file__).resolve().parent.parent / "app.py")
DATA = R.load_results()
FOOTER = (
    "Diese Demo ist Teil des Portfolios von [Sebastian Hanisch](https://sebastianhanisch.net) – "
    "Operations Research und Machine Learning ([Über mich](https://sebastianhanisch.net/ueber-mich.html)). "
    "Mehr zum Thema: [Tourenplanung optimieren](https://sebastianhanisch.net/tourenplanung-optimierung.html)."
)


@pytest.fixture(autouse=True)
def clean_state():
    """st.cache_data ist prozessweit: Tests dürfen keine Ergebnisse anderer Tests sehen."""
    import streamlit as st
    st.cache_data.clear()
    yield


def fresh(**query):
    at = AppTest.from_file(APP, default_timeout=180)
    for k, v in query.items():
        at.query_params[k] = v
    at.run()
    assert not at.exception, at.exception
    return at


def set_and_run(at, **values):
    for key, value in values.items():
        if key == "seed_input":
            at.number_input(key=key).set_value(value)
        elif key == "change_cost_slider":
            at.slider(key=key).set_value(value)
        else:
            at.select_slider(key=key).set_value(value)
    at.run()
    assert not at.exception, at.exception
    return at


def click(at, label):
    next(b for b in at.button if b.label == label).click().run()
    assert not at.exception, at.exception
    return at


def main_metrics(at):
    return [(m.label, m.value) for m in at.metric[:4]]


def box(at, kind, needle):
    for x in getattr(at, kind):
        if needle in x.value:
            return x.value
    return None


def any_box(at, needle):
    return next((v for k in ("success", "warning", "info", "error") for v in [box(at, k, needle)] if v), None)


def state_values(at):
    return {key: at.session_state[key] for key in SETTING_SPECS}


# ---------------------------------------------------------------------------------------------------
# Skelett
# ---------------------------------------------------------------------------------------------------
def test_skeleton_and_footer():
    at = fresh()
    assert [h.value for h in at.sidebar.header] == ["⚙️ Einstellungen"]                   # genau EIN Header
    assert len(at.title) == 1 and at.title[0].value == "📦 Nahverkehr: Same-Day-Aufträge, Änderungen und der Preis der Planänderung"
    assert any(v.value.startswith("## 📦 Wie viel Neuplanen lohnt, wenn jede Planänderung etwas kostet?") for v in at.markdown)
    assert any(v.value.startswith("### 📐 Was die Messreihe über 200 Tage zeigt") for v in at.markdown)
    assert any(v.value.startswith("### 📐 Welche Aufträge annehmen?") for v in at.markdown)
    assert [e.label for e in at.expander] == ["🔧 Wie wir das erreichen – Politiken im Vergleich", "Wie funktioniert diese Demo?", "📐 Mathematische Formulierung"]
    assert any(c.value == FOOTER for c in at.caption)
    presets = [b.label for b in at.button if b.label in C.PRESETS]
    assert presets == list(C.PRESETS) and len(presets) == 5 and all(len(n) <= 32 for n in presets)
    assert [s.label for s in at.sidebar.select_slider] == ["Morgenaufträge", "Same-Day-Rate", "Änderungen und Stornos", "Frist"]
    assert [s.label for s in at.sidebar.slider] == ["Kosten je Planänderung"]
    assert [n.label for n in at.sidebar.number_input] == ["Seed"]
    assert [b.label for b in at.sidebar.button] == ["🎲 Neuer Tag"]                        # letztes Sidebar-Element
    assert [type(e).__name__ for e in at.sidebar.children.values()][-1] == "Button"
    assert [tab.label for tab in at.tabs] and "📅 Tagesverlauf" in [t.label for t in at.tabs] and "📈 Messreihe" in [t.label for t in at.tabs]


def test_intro_names_the_expanders_and_neighbours():
    at = fresh()
    intro = next(m.value for m in at.markdown if m.value.strip().startswith("Im Nahverkehr steht der Plan"))
    for needle in ("Same-Day-Aufträge", "Aufträge ändern sich", "Preis der Änderung", "Wie funktioniert diese Demo?", "📐 Mathematische Formulierung",
                   "vrp_demo", "revenue-management-demo", "hofrobust-demo", "robuste-kaiplatz-demo"):
        assert needle in intro, needle


def test_sidebar_has_no_second_header_or_subheader():
    at = fresh()
    assert len(at.sidebar.header) == 1 and len(at.sidebar.subheader) == 0
    assert [m.value for m in at.sidebar.markdown] == ["**Der Tag**", "**Bewertung**"]


def test_there_are_no_dead_switches():
    at = fresh()
    assert not at.sidebar.checkbox and not at.sidebar.toggle and not at.checkbox and not at.toggle
    assert len(at.sidebar.select_slider) == 4 and len(at.sidebar.slider) == 1 and len(at.sidebar.number_input) == 1


def test_sliders_have_the_measured_stages_and_bounds():
    at = fresh()
    assert [str(o) for o in at.select_slider(key="morning_slider").options] == ["16", "28", "40", "52"]
    assert [str(o) for o in at.select_slider(key="events_slider").options] == list(C.EVENT_OPTIONS)
    assert [str(o) for o in at.select_slider(key="deadline_slider").options] == ["60 min", "120 min", "240 min"]
    assert [str(o) for o in at.select_slider(key="rate_slider").options] == ["0 je Stunde", "2 je Stunde", "6 je Stunde", "12 je Stunde"]
    cost = at.slider(key="change_cost_slider")
    assert (cost.min, cost.max, cost.step) == (0.0, 20.0, 0.5) and cost.value == 2.0
    seed = at.number_input(key="seed_input")
    assert (seed.min, seed.max, seed.step, seed.value) == (0, 299, 1, C.SEED_DEFAULT)


def test_default_state_and_permalink_written_to_the_address_bar():
    at = fresh()
    assert state_values(at) == dict(morning_slider=40, rate_slider=6, events_slider="mittel", deadline_slider=120, change_cost_slider=2.0, seed_input=292)
    qp = {k: (v[0] if isinstance(v, list) else v) for k, v in dict(at.query_params).items()}
    assert qp == {"m": "40", "r": "6", "e": "mittel", "d": "120", "c": "2", "seed": "292"}


def test_main_metrics_are_2x2_with_the_right_labels_and_values():
    at = fresh()
    labels = [m[0] for m in main_metrics(at)]
    assert labels[0] == "Gewinn starrer Plan (S0)" and labels[1] == "Gewinn volle Neuplanung (R)" and labels[2].startswith("Netto bester Regler (")
    assert labels[3] == "Änderungen je Regler (S0 / R / bester)"
    day = LV.solve_day(40, 6, "mittel", 120, 292)
    values = dict(main_metrics(at))
    assert values["Gewinn starrer Plan (S0)"] == f"{day['results']['S0']['profit_total']:,}".replace(",", ".")
    assert values["Gewinn volle Neuplanung (R)"] == f"{day['results']['R']['profit_total']:,}".replace(",", ".")
    best = R.judge(R.find_cell(DATA), 2.0)["best"]
    assert best == "P1.5" and labels[2] == "Netto bester Regler (P_1,5)"
    s0a, ra, ba = (day["results"][p]["a"] for p in ("S0", "R", best))
    assert values["Änderungen je Regler (S0 / R / bester)"] == f"{s0a} / {ra} / {ba}"
    delta = {m.label: m.delta for m in at.metric[:4]}
    assert delta["Gewinn starrer Plan (S0)"] == "0 Änderungen per Definition" and "gegenüber S0" in delta["Gewinn volle Neuplanung (R)"]


def test_live_caption_says_it_is_one_day():
    at = fresh()
    cap = next(c.value for c in at.caption if c.value.startswith("Live-Tag (ein Tag, ein Ereignisstrom)"))
    assert "Seed 292" in cap and "Ein einzelner Tag" in cap and "40 Morgenaufträge" in cap


# ---------------------------------------------------------------------------------------------------
# Presets, Permalink, Regler
# ---------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("name", list(C.PRESETS))
def test_every_preset_sets_all_controls_and_shows_its_message(name):
    at = fresh()
    click(at, name)
    p = C.PRESETS[name]
    assert state_values(at) == {PRESET_STATE_KEYS[k]: v for k, v in p.items()}
    expected = {"Standard": ("info", "Hier lohnt ein Preis je Änderung"), "Viele neue Aufträge": ("success", "Volle Neuplanung lohnt"),
                "Nur Änderungen": ("info", "Hier lohnt ein Preis je Änderung"), "Knappe Frist": ("info", "Hier lohnt ein Preis je Änderung"),
                "Teure Änderungen": ("warning", "Volle Neuplanung verliert gegen den starren Plan")}[name]
    kind, needle = expected
    assert box(at, kind, needle) is not None                                              # Streamlit macht das führende Emoji zum Symbol des Kastens
    assert next(x for x in getattr(at, kind) if needle in x.value).icon == {"success": "✅", "info": "ℹ️", "warning": "⚠️"}[kind]
    cell, exact, _ = R.nearest_stab_cell(DATA, p["morning"], p["rate"], p["events"], p["deadline"])
    assert exact and R.cell_setting_text(cell) in box(at, kind, needle)
    assert at.metric[2].label == f"Netto bester Regler ({R.policy_label(R.judge(cell, p['cost'])['best'])})"
    assert dict(at.query_params).get("seed") in ("292", ["292"])


def test_presets_change_the_day_shown():
    at = fresh()
    base_values = main_metrics(at)
    click(at, "Viele neue Aufträge")
    assert main_metrics(at) != base_values
    click(at, "Nur Änderungen")
    assert "0 neue Aufträge" in next(c.value for c in at.caption if c.value.startswith("Live-Tag"))


def test_permalink_sets_the_controls_and_snaps_to_stages():
    at = fresh(m="28", r="12", e="viele", d="240", c="4.5", seed="17")
    assert state_values(at) == dict(morning_slider=28, rate_slider=12, events_slider="viele", deadline_slider=240, change_cost_slider=4.5, seed_input=17)
    at = fresh(m="30", r="5", e="gibtsnicht", d="100", c="99", seed="-4")
    assert state_values(at) == dict(morning_slider=28, rate_slider=6, events_slider="mittel", deadline_slider=120, change_cost_slider=20.0, seed_input=0)


def test_all_controls_at_min_and_max_run_without_exception():
    at = fresh()
    for key, values in (("morning_slider", (16, 52)), ("rate_slider", (0, 12)), ("events_slider", ("keine", "sehr viele")), ("deadline_slider", (60, 240)),
                        ("change_cost_slider", (0.0, 20.0)), ("seed_input", (0, 299))):
        for v in values:
            set_and_run(at, **{key: v})
            assert state_values(at)[key] == v
    set_and_run(at, morning_slider=16, rate_slider=0, events_slider="keine", deadline_slider=60, change_cost_slider=0.0, seed_input=0)
    assert any_box(at, "Volle Neuplanung lohnt") is not None or any_box(at, "Hier lohnt ein Preis") is not None
    set_and_run(at, morning_slider=52, rate_slider=12, events_slider="sehr viele", deadline_slider=240, change_cost_slider=20.0, seed_input=299)
    assert any_box(at, "Volle Neuplanung verliert") is not None


def test_new_day_button_rolls_a_new_seed(monkeypatch):
    frozen = iter([3, 5, 292, 3])                                                          # nur eingefrorene Morgenpläne (Seeds 3, 5, 292 bei 40 Morgenaufträgen)
    monkeypatch.setattr(P.random, "randint", lambda lo, hi: next(frozen))
    at = fresh()
    before = at.session_state["seed_input"]
    seen = {before}
    for _ in range(3):
        click(at, "🎲 Neuer Tag")
        seen.add(at.session_state["seed_input"])
        assert 0 <= at.session_state["seed_input"] <= 299
    assert seen == {292, 3, 5}


# ---------------------------------------------------------------------------------------------------
# Meldung in drei Zuständen, Zell-Zuordnung
# ---------------------------------------------------------------------------------------------------
def test_three_message_states_follow_the_cost_slider():
    at = fresh()
    set_and_run(at, change_cost_slider=0.0)
    assert box(at, "success", "Volle Neuplanung lohnt") and not box(at, "info", "Hier lohnt ein Preis") and not box(at, "warning", "Volle Neuplanung verliert")
    set_and_run(at, change_cost_slider=2.0)
    assert box(at, "info", "Hier lohnt ein Preis je Änderung") and not box(at, "success", "Volle Neuplanung lohnt")
    set_and_run(at, change_cost_slider=5.0)
    assert box(at, "warning", "Volle Neuplanung verliert gegen den starren Plan") and not box(at, "info", "Hier lohnt ein Preis je Änderung")
    at.slider(key="change_cost_slider").set_value(4.0).run()
    assert box(at, "info", "Hier lohnt ein Preis je Änderung")                        # 4,3 ist die Grenze: 4,0 verliert noch nicht
    at.slider(key="change_cost_slider").set_value(4.5).run()
    assert box(at, "warning", "Volle Neuplanung verliert")


def test_message_and_first_metric_do_not_depend_on_the_cost_only_the_net_does():
    at = fresh()
    before = main_metrics(at)
    set_and_run(at, change_cost_slider=8.0)
    after = main_metrics(at)
    assert before[0] == after[0] and before[1] == after[1]                                # S0 und R (Gewinn ohne Kosten) bleiben
    assert before[2] != after[2]                                                          # nur die Netto-Rechnung und der empfohlene Regler wandern


def test_cost_slider_does_not_recompute_the_day(monkeypatch):
    calls = []
    real = LV.solve_day
    monkeypatch.setattr(LV, "solve_day", lambda *a, **k: (calls.append(a), real(*a, **k))[1])
    at = fresh()
    assert len(calls) == 1
    set_and_run(at, change_cost_slider=7.0)
    set_and_run(at, change_cost_slider=1.0)
    assert len(calls) == 1                                                                # Kosten verschieben nur die Bewertung (st.cache_data)
    set_and_run(at, rate_slider=12)
    assert len(calls) == 2


def test_unmeasured_combination_shows_the_nearest_cell_with_a_note():
    at = fresh()
    set_and_run(at, morning_slider=52, rate_slider=12)
    note = "keine eigene Messreihe: die Messreihe variiert je Zelle nur einen Parameter"
    assert any(note in i.value for i in at.info) and any("nächstliegende gemessene Zelle" in i.value for i in at.info)
    assert any(note in c.value for c in at.caption)
    set_and_run(at, morning_slider=40, rate_slider=6)
    assert not any(note in i.value for i in at.info)                                       # exakt gemessen: kein Hinweis


def test_rate_zero_shows_no_acceptance_rules_and_says_why():
    at = fresh()
    set_and_run(at, rate_slider=0)
    assert any("Bei Rate 0 gibt es keine neuen Aufträge" in i.value for i in at.info)
    set_and_run(at, rate_slider=2)
    assert not any("Bei Rate 0 gibt es keine neuen Aufträge" in i.value for i in at.info)


# ---------------------------------------------------------------------------------------------------
# Kernabschnitte, Ansichten, Texte
# ---------------------------------------------------------------------------------------------------
def test_core_section_two_shows_the_measured_numbers():
    at = fresh()
    text = " ".join(c.value for c in at.caption)
    assert "+123,0 ± 12,1" in text and "28,6" in text and "4,3 Gewinn je Änderung" in text
    assert "Ab 4,3 Kosten je Änderung verliert die volle Neuplanung" in text
    assert "69 % / 85 % / 99 %" in text and "37 % / 60 % / 84 %" in text
    assert "26 / 27" not in text and "13 / 10 von 28 Zellen" in text
    frames = [d.value for d in at.dataframe]
    assert len(frames) >= 12
    assert any("Neuplanung lohnt (belastbar)" in " ".join(map(str, f.to_numpy().ravel())) for f in frames if hasattr(f, "to_numpy"))


def test_core_section_two_explains_price_and_lambda_separately():
    at = fresh()
    text = " ".join(c.value for c in at.caption)
    assert "**Kosten je Änderung**" in text and "**Reglerparameter λ**" in text and "nicht identisch" in text


def test_measure_selectbox_switches_the_measure():
    at = fresh()
    box_ = at.selectbox(key="measure_select")
    assert list(box_.options) == ["a", "b", "c"] or list(box_.options) == list(R.MEASURES.values())
    for m in ("b", "c"):
        at.selectbox(key="measure_select").set_value(m).run()
        assert not at.exception


def test_view_select_shows_the_chosen_policy_only_as_display():
    at = fresh()
    radio = at.radio(key="view_select")
    assert list(radio.options) == ["S0 (starrer Plan)", "R (volle Neuplanung)", "bester Regler"] and radio.value == "bester Regler"
    before = main_metrics(at)
    for label in radio.options:
        at.radio(key="view_select").set_value(label).run()
        assert not at.exception
        assert main_metrics(at) == before                                                  # reine Anzeigewahl: die Kennzahlen bleiben
    at.radio(key="view_select").set_value("S0 (starrer Plan)").run()
    assert any(c.value.startswith("S0 (starrer Plan): Gewinn") for c in at.caption)
    at.radio(key="view_select").set_value("R (volle Neuplanung)").run()
    assert any(c.value.startswith("R (volle Neuplanung): Gewinn") for c in at.caption)


def test_acceptance_section_shows_live_and_measured_parts():
    at = fresh()
    md = [m.value for m in at.markdown]
    assert any(v.startswith("**Live: dieser Tag ohne Änderungen**") and "µ = 3,00 für P2 und µ = 1,50 für P2L" in v for v in md)
    assert any(v.startswith("**Vorgerechnet: Messreihe über 60 Tage**") and "das Orakel nur auf 16 Instanzen" in v for v in md)
    assert any(v.startswith("**Kalibriertabelle für µ und Fehlkalibrierung.**") and "40 **getrennten Kalibrier-Seeds**" in v for v in md)
    text = " ".join(c.value for c in at.caption)
    assert "Littlewood" in text and "regimeabhängiger Parameter" in text


def test_acceptance_uses_the_calibrated_threshold_of_the_nearest_cell():
    at = fresh()
    set_and_run(at, morning_slider=16, rate_slider=6)
    assert any("µ = 0,00 für P2 und µ = 0,00 für P2L" in m.value for m in at.markdown)          # 16 Morgenaufträge: die Kalibrierung wählt µ = 0
    set_and_run(at, morning_slider=52, rate_slider=6)
    assert any("µ = 4,00 für P2 und µ = 4,00 für P2L" in m.value for m in at.markdown)


def test_expander_texts_state_the_limits_and_the_price_versus_lambda():
    at = fresh()
    how = next(m.value for m in at.markdown if m.value.strip().startswith("**Basis.**"))
    for needle in ("Kosten je Änderung sind nicht λ", "Preis in der Bewertung", "Strafe in der Entscheidung", "nicht in der Entscheidung gemessen", "erfunden, nicht kalibriert",
                   "Stark stilisiert", "Der Betrag ist klein", "Die Strafe optimiert das Maß (a) selbst mit", "Das Orakel ist klein und heuristisch", "Nicht Teil dieser Demo",
                   "abgeleitet, nicht getestet", "nächstliegende gemessene Zelle", "S0 hat damit per Definition 0"):
        assert needle in how or needle.replace("abgeleitet", "*abgeleitet") in how, needle
    math = next(m.value for m in at.markdown if m.value.strip().startswith("**Ereignisse und Plan.**"))
    for needle in ("P}_\\lambda", "arg\\max", "c \\ne \\lambda", "nv_model.py", "nv_sim.py", "nv_oracle.py", "nv_live.py", "nv_results.py", "1{,}1"):
        assert needle in math, needle


def test_no_dead_file_links_in_markdown():
    at = fresh()
    import re
    for md in list(at.markdown) + list(at.caption):
        for target in re.findall(r"\]\(([^)]+)\)", md.value):
            assert target.startswith("https://"), (target, md.value[:80])                  # nur echte Links, kein [foo.py](foo.py)


def test_real_umlauts_and_no_ascii_replacements_in_texts():
    at = fresh()
    text = " ".join(m.value for m in at.markdown) + " ".join(c.value for c in at.caption)
    for bad in (" fuer ", " ueber ", " waehlen ", "Aenderung", "Auftraege", "Kosten je Aenderung"):
        assert bad not in text, bad
    assert "Änderung" in text and "Aufträge" in text and "Überlagerung" not in text


def test_all_plotly_charts_render_with_unique_keys():
    at = fresh()
    charts = at.get("plotly_chart")
    assert len(charts) >= 9
    ids = [c.proto.id for c in charts]
    assert len(set(ids)) == len(ids)


def test_dataframes_have_no_null_columns():
    """Keine Ergebnisspalte ist überall gleich (Nullspalten-Signal), außer den per Definition oder Befund konstanten (Änderungen von S0 = 0, Zahl der Tage, Urteil: in allen 28 Zellen belastbar positiv)."""
    at = fresh()
    for d in at.dataframe:
        df = d.value
        if len(df) < 3:
            continue
        for col in df.columns:
            if str(col) in ("Änderungen (a)", "Ereignisse mit Änderung (c)", "Tage", "Instanzen", "Urteil"):     # konstant per Definition bzw. Befund (kein Regime-Widerspruch)
                continue
            assert df[col].astype(str).nunique() > 1, (col, df[col].tolist()[:3])


def test_pdf_download_button_is_present_and_named():
    at = fresh()
    buttons = at.get("download_button")
    assert len(buttons) == 1
    assert buttons[0].proto.label == "📄 Tagesplan als PDF herunterladen"


def test_app_survives_every_policy_view_at_every_preset():
    at = fresh()
    for name in C.PRESETS:
        click(at, name)
        for label in ("S0 (starrer Plan)", "R (volle Neuplanung)", "bester Regler"):
            at.radio(key="view_select").set_value(label).run()
            assert not at.exception, (name, label)
