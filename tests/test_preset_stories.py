"""Abnahme der echten Presets: die Kriterien der Messreihe (data/nv_results.json) und die qualitativen Kriterien am GEZEIGTEN Tag (der Tag
kommt aus der reinen Simulation auf dem eingefrorenen Morgenplan, unabhängig von der OR-Tools-Version), dazu die Meldungszustände."""
import pytest

import nv_constants as C
import nv_live as LV
import nv_results as R
import nv_stories as ST
import nv_ui_panel as UI

DATA = R.load_results()


@pytest.mark.parametrize("name", list(C.PRESETS))
def test_measured_criteria_hold(name):
    result = ST.criteria(name, DATA)
    assert result and all(ok for ok, _ in result), [t for ok, t in result if not ok]


def day_of(name):
    p = C.PRESETS[name]
    return LV.solve_day(p["morning"], p["rate"], p["events"], p["deadline"], p["seed"])


@pytest.mark.parametrize("name", list(C.PRESETS))
def test_shown_day_tells_the_same_story(name):
    crit = ST.day_criteria(name, day_of(name), C.PRESETS[name]["cost"])
    assert crit and all(ok for ok, _ in crit), [t for ok, t in crit if not ok]


def test_all_presets_show_a_day_outside_the_measured_sample():
    assert all(p["seed"] >= C.MEASURED_N for p in C.PRESETS.values())
    assert len({p["seed"] for p in C.PRESETS.values()}) == 1                   # ein gemeinsamer Tag: die Presets ändern nur die Regler


def test_message_state_of_every_preset():
    """Alle drei Meldungszustände kommen in den Presets vor: Neuplanung lohnt, ein Preis lohnt, Neuplanung verliert."""
    expected = {"Standard": C.STATE_PREIS, "Viele neue Aufträge": C.STATE_LOHNT, "Nur Änderungen": C.STATE_PREIS, "Knappe Frist": C.STATE_PREIS,
                "Teure Änderungen": C.STATE_VERLIERT}
    for name, p in C.PRESETS.items():
        cell, exact, _ = R.nearest_stab_cell(DATA, p["morning"], p["rate"], p["events"], p["deadline"])
        assert exact, name                                                     # jedes Preset steht auf einer gemessenen Zelle
        assert R.judge(cell, p["cost"])["state"] == expected[name], name
        state, text = UI.message(day_of(name), cell, p["cost"])
        assert state == expected[name] and text.startswith({"lohnt": "✅", "preis": "ℹ️", "verliert": "⚠️"}[state])
    assert set(expected.values()) == {C.STATE_LOHNT, C.STATE_PREIS, C.STATE_VERLIERT}


def test_preset_help_numbers_match_the_measurement():
    cell = R.find_cell(DATA)
    assert "4,3" in C.PRESET_HELP["Teure Änderungen"] and f"{R.break_even_cost(cell):.1f}".replace(".", ",") == "4,3"
