"""Regler-Spezifikation, Permalink, Presets und Seed-Knopf (Standardmuster aus dem OR-Demo-Portfolio, siehe fv_presets.py in
fernverkehr-demo). Vier Regler sind feste Stufen (Morgenaufträge, Same-Day-Rate, Änderungen und Stornos, Frist), zwei sind Zahlenbereiche
(Kosten je Planänderung, Seed): beim Permalink wird jeder Wert auf den Bereich begrenzt bzw. auf die nächste Stufe eingerastet, damit die
Adresszeile nie einen Wert außerhalb des Rasters in den Regler schreibt."""
import math
import random
from dataclasses import dataclass
from typing import Callable, Optional

import streamlit as st

import nv_constants as C


def _text(value):
    return str(value)


def _num(value):
    return f"{value:g}"


@dataclass(frozen=True)
class SettingSpec:
    url_param: str
    caster: Callable
    default: object
    lo: Optional[float] = None
    hi: Optional[float] = None
    options: Optional[tuple] = None          # feste Stufen (Zahlen: einrasten auf die nächste Stufe, Text: nur bekannte Namen)
    step: Optional[float] = None             # Rasterweite eines Zahlenbereichs (Kosten)
    encoder: Callable = _text


SETTING_SPECS = {
    "morning_slider": SettingSpec("m", int, C.MORNING_DEFAULT, options=C.MORNING_OPTIONS),
    "rate_slider": SettingSpec("r", int, C.RATE_DEFAULT, options=C.RATE_OPTIONS),
    "events_slider": SettingSpec("e", str, C.EVENT_DEFAULT, options=C.EVENT_OPTIONS),
    "deadline_slider": SettingSpec("d", int, C.DEADLINE_DEFAULT, options=C.DEADLINE_OPTIONS),
    "change_cost_slider": SettingSpec("c", float, C.COST_DEFAULT, *C.COST_RANGE, step=C.COST_STEP, encoder=_num),
    "seed_input": SettingSpec("seed", int, C.SEED_DEFAULT, *C.SEED_RANGE),
}

PRESET_STATE_KEYS = {
    "morning": "morning_slider", "rate": "rate_slider", "events": "events_slider", "deadline": "deadline_slider",
    "cost": "change_cost_slider", "seed": "seed_input",
}


def bounds(state_key):
    spec = SETTING_SPECS[state_key]
    return spec.lo, spec.hi


def parse_setting(spec, raw):
    """Wert aus der Adresszeile: umwandeln, auf den Bereich begrenzen bzw. auf die nächste Stufe einrasten. None, wenn er sich
    nicht auswerten lässt (kein Zahlenwert, nicht endlich, unbekannter Stufenname)."""
    if spec.caster is str:
        text = str(raw).strip().lower()
        return text if spec.options and text in spec.options else None
    try:
        value = float(raw)
    except (ValueError, TypeError):
        return None
    if not math.isfinite(value):
        return None
    if spec.options:                                        # Zahlenstufen: die nächste Stufe, bei Gleichstand die kleinere
        return min(spec.options, key=lambda o: (abs(o - value), o))
    value = max(spec.lo, min(spec.hi, value))
    if spec.step:                                           # Zahlenbereich mit Raster: auf das Raster einrasten
        value = round(value / spec.step) * spec.step
        return float(min(spec.hi, max(spec.lo, value)))
    return int(round(value))


def init_session_state_defaults():
    for state_key, spec in SETTING_SPECS.items():
        if state_key not in st.session_state:
            st.session_state[state_key] = spec.default


def load_permalink_settings():
    if "permalink_loaded" in st.session_state:
        return
    qp = st.query_params
    for state_key, spec in SETTING_SPECS.items():
        if spec.url_param in qp:
            value = parse_setting(spec, qp[spec.url_param])
            if value is not None:
                st.session_state[state_key] = value
    st.session_state["permalink_loaded"] = True


def sync_query_params(values):
    """values: dict state_key -> aktueller Wert (aus den Widgets)."""
    try:
        for state_key, value in values.items():
            st.query_params[SETTING_SPECS[state_key].url_param] = SETTING_SPECS[state_key].encoder(value)
    except Exception:
        pass


def apply_preset(name):
    for field, state_key in PRESET_STATE_KEYS.items():
        st.session_state[state_key] = C.PRESETS[name][field]


def randomize_seed():
    """Würfelt einen neuen Seed für den gezeigten Tag."""
    st.session_state["seed_input"] = random.randint(*C.SEED_RANGE)
