"""Regler-Spezifikation, Permalink (Begrenzen und Einrasten), Presets und Seed-Knopf."""
import types

import pytest

import nv_constants as C
import nv_presets as P


def fake_streamlit(monkeypatch, query=None):
    fake = types.SimpleNamespace(session_state={}, query_params=dict(query or {}))
    monkeypatch.setattr(P, "st", fake)
    return fake


def test_specs_cover_every_control_once():
    assert list(P.SETTING_SPECS) == ["morning_slider", "rate_slider", "events_slider", "deadline_slider", "change_cost_slider", "seed_input"]
    assert {s.url_param for s in P.SETTING_SPECS.values()} == {"m", "r", "e", "d", "c", "seed"}
    assert P.SETTING_SPECS["morning_slider"].default == 40 and P.SETTING_SPECS["rate_slider"].default == 6
    assert P.SETTING_SPECS["events_slider"].default == "mittel" and P.SETTING_SPECS["deadline_slider"].default == 120
    assert P.SETTING_SPECS["change_cost_slider"].default == 2.0 and P.SETTING_SPECS["seed_input"].default == C.SEED_DEFAULT
    assert P.bounds("change_cost_slider") == (0.0, 20.0) and P.bounds("seed_input") == (0, 299)
    assert P.bounds("morning_slider") == (None, None)
    assert set(P.PRESET_STATE_KEYS.values()) == set(P.SETTING_SPECS)


def test_defaults_are_inside_their_ranges_and_stages():
    for key, spec in P.SETTING_SPECS.items():
        if spec.options:
            assert spec.default in spec.options, key
        else:
            assert spec.lo <= spec.default <= spec.hi, key
    assert C.MORNING_DEFAULT in C.MORNING_OPTIONS and C.RATE_DEFAULT in C.RATE_OPTIONS and C.DEADLINE_DEFAULT in C.DEADLINE_OPTIONS


@pytest.mark.parametrize("key,raw,expected", [
    ("morning_slider", "40", 40), ("morning_slider", "30", 28), ("morning_slider", "34", 28), ("morning_slider", "35", 40), ("morning_slider", "0", 16), ("morning_slider", "999", 52),
    ("morning_slider", "22", 16),                                      # 22 liegt genau zwischen 16 und 28: die kleinere Stufe
    ("rate_slider", "1", 0), ("rate_slider", "4", 2), ("rate_slider", "9", 6), ("rate_slider", "10", 12), ("rate_slider", "-5", 0),
    ("deadline_slider", "90", 60), ("deadline_slider", "180", 120), ("deadline_slider", "181", 240), ("deadline_slider", "5000", 240),
    ("events_slider", "viele", "viele"), ("events_slider", " Sehr Viele ", "sehr viele"), ("events_slider", "unbekannt", None), ("events_slider", "", None),
    ("change_cost_slider", "2", 2.0), ("change_cost_slider", "2.3", 2.5), ("change_cost_slider", "2.2", 2.0), ("change_cost_slider", "-4", 0.0),
    ("change_cost_slider", "100", 20.0), ("change_cost_slider", "4.75", 5.0),
    ("seed_input", "217", 217), ("seed_input", "-3", 0), ("seed_input", "300", 299), ("seed_input", "12.6", 13),
    ("seed_input", "abc", None), ("seed_input", "nan", None), ("seed_input", "inf", None), ("seed_input", None, None),
])
def test_parse_setting(key, raw, expected):
    got = P.parse_setting(P.SETTING_SPECS[key], raw)
    assert got == expected and type(got) is type(expected)


def test_encoders_round_trip_through_the_address_bar():
    for key, value in (("morning_slider", 28), ("rate_slider", 12), ("events_slider", "sehr viele"), ("deadline_slider", 240),
                       ("change_cost_slider", 4.5), ("seed_input", 33)):
        spec = P.SETTING_SPECS[key]
        assert P.parse_setting(spec, spec.encoder(value)) == value
    assert P.SETTING_SPECS["change_cost_slider"].encoder(2.0) == "2" and P.SETTING_SPECS["change_cost_slider"].encoder(0.5) == "0.5"


def test_init_defaults_do_not_overwrite(monkeypatch):
    fake = fake_streamlit(monkeypatch)
    fake.session_state["rate_slider"] = 12
    P.init_session_state_defaults()
    assert fake.session_state["rate_slider"] == 12 and fake.session_state["morning_slider"] == 40 and len(fake.session_state) == 6


def test_permalink_is_loaded_once_and_limited(monkeypatch):
    fake = fake_streamlit(monkeypatch, {"m": "30", "r": "12", "e": "viele", "d": "999", "c": "7.3", "seed": "-4"})
    P.load_permalink_settings()
    assert fake.session_state["morning_slider"] == 28 and fake.session_state["rate_slider"] == 12 and fake.session_state["events_slider"] == "viele"
    assert fake.session_state["deadline_slider"] == 240 and fake.session_state["change_cost_slider"] == 7.5 and fake.session_state["seed_input"] == 0
    assert fake.session_state["permalink_loaded"] is True
    fake.query_params["m"] = "16"
    P.load_permalink_settings()                                       # nur beim ersten Aufruf
    assert fake.session_state["morning_slider"] == 28


def test_permalink_ignores_bad_values(monkeypatch):
    fake = fake_streamlit(monkeypatch, {"m": "abc", "e": "gibtsnicht", "c": "nan", "unbekannt": "1"})
    P.load_permalink_settings()
    assert set(fake.session_state) == {"permalink_loaded"}


def test_sync_query_params(monkeypatch):
    fake = fake_streamlit(monkeypatch)
    P.sync_query_params({"morning_slider": 52, "events_slider": "keine", "change_cost_slider": 3.5, "seed_input": 9})
    assert fake.query_params == {"m": "52", "e": "keine", "c": "3.5", "seed": "9"}

    class Broken:
        def __setitem__(self, k, v):
            raise RuntimeError

    monkeypatch.setattr(P, "st", types.SimpleNamespace(query_params=Broken()))
    P.sync_query_params({"morning_slider": 52})                        # ein Fehler beim Schreiben der Adresszeile bleibt folgenlos


def test_apply_preset_sets_every_control(monkeypatch):
    fake = fake_streamlit(monkeypatch)
    for name, p in C.PRESETS.items():
        fake.session_state.clear()
        P.apply_preset(name)
        assert fake.session_state == {"morning_slider": p["morning"], "rate_slider": p["rate"], "events_slider": p["events"],
                                      "deadline_slider": p["deadline"], "change_cost_slider": p["cost"], "seed_input": p["seed"]}, name


def test_randomize_seed_stays_in_range(monkeypatch):
    fake = fake_streamlit(monkeypatch)
    seeds = set()
    for _ in range(200):
        P.randomize_seed()
        seeds.add(fake.session_state["seed_input"])
    assert min(seeds) >= 0 and max(seeds) <= 299 and len(seeds) > 50 and all(isinstance(s, int) for s in seeds)


def test_presets_are_valid_and_distinct():
    assert list(C.PRESETS) == ["Standard", "Viele neue Aufträge", "Nur Änderungen", "Knappe Frist", "Teure Änderungen"]
    assert set(C.PRESET_HELP) == set(C.PRESETS)
    assert all(len(n) <= 32 for n in C.PRESETS) and all(C.PRESET_HELP[n].endswith(".") for n in C.PRESETS)
    keys = set(P.PRESET_STATE_KEYS)
    for name, p in C.PRESETS.items():
        assert set(p) == keys, name
        assert p["morning"] in C.MORNING_OPTIONS and p["rate"] in C.RATE_OPTIONS and p["events"] in C.EVENT_OPTIONS and p["deadline"] in C.DEADLINE_OPTIONS
        assert C.COST_RANGE[0] <= p["cost"] <= C.COST_RANGE[1] and p["cost"] % C.COST_STEP == 0
        assert C.SEED_RANGE[0] <= p["seed"] <= C.SEED_RANGE[1] and p["seed"] >= 200      # außerhalb der Stichprobe-Seeds der Messreihe
    settings = {tuple(sorted(p.items())) for p in C.PRESETS.values()}
    assert len(settings) == 5
    std = C.PRESETS["Standard"]
    assert (std["morning"], std["rate"], std["events"], std["deadline"], std["cost"]) == (40, 6, "mittel", 120, 2.0)
    assert C.PRESETS["Viele neue Aufträge"]["rate"] == 12 and C.PRESETS["Nur Änderungen"]["rate"] == 0
    assert C.PRESETS["Knappe Frist"]["deadline"] == 60 and C.PRESETS["Teure Änderungen"]["cost"] == 5.0
    for name, p in C.PRESETS.items():                                # jedes Preset weicht nur in EINEM Regler vom Standard ab
        if name != "Standard":
            assert sum(p[k] != std[k] for k in ("morning", "rate", "events", "deadline", "cost")) == 1, name


def test_constants_are_consistent():
    assert C.EVENT_OPTIONS == ("keine", "wenige", "mittel", "viele", "sehr viele")
    assert C.EVENT_LEVELS["keine"] == (0.0, 0.0) and C.EVENT_LEVELS["mittel"] == (0.25, 0.08) and C.EVENT_LEVELS["sehr viele"] == (0.8, 0.2)
    assert C.EVENT_LEVELS["wenige"] == (0.1, 0.03) and C.EVENT_LEVELS["viele"] == (0.5, 0.16)
    assert C.MORNING_OPTIONS == (16, 28, 40, 52) and C.RATE_OPTIONS == (0, 2, 6, 12) and C.DEADLINE_OPTIONS == (60, 120, 240)
    assert len(C.POLICY_NAMES) == 21 and C.POLICY_NAMES[:2] == ("S0", "R") and len(set(C.POLICY_NAMES)) == 21
    assert set(C.POLICY_NAMES) < set(C.POLICY_SPECS) and len(C.POLICY_SPECS) == 29
    assert C.POLICY_SPECS["P1.5"] == dict(kind="P", lam=1.5) and C.POLICY_SPECS["F12"] == dict(kind="F", k=12)
    assert C.POLICY_SPECS["T240"] == dict(kind="T", T_per=240) and C.POLICY_SPECS["H300"] == dict(kind="H", H_min=300)
    assert C.BASE_CFG["n_m"] == C.MORNING_DEFAULT and C.BASE_CFG["lam"] == C.RATE_DEFAULT and C.BASE_CFG["delta"] == C.DEADLINE_DEFAULT
    assert (C.BASE_CFG["p_chg"], C.BASE_CFG["p_cancel"]) == C.EVENT_LEVELS[C.EVENT_DEFAULT]
    assert C.BEST_SHARE_LIMIT == 1.10 and C.SE_FACTOR == 2.0
    assert {C.STATE_LOHNT, C.STATE_PREIS, C.STATE_VERLIERT} == {"lohnt", "preis", "verliert"}
