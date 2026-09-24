"""Eingefrorene Referenzwerte: die reine Simulation (nv_sim) auf den EINGEFRORENEN Morgenplänen (tests/data/nv_morning.json, die Pläne
aus dem Zwischenspeicher der Messreihe) muss die Ergebnisse der Sweeps der Messreihen BITGLEICH reproduzieren (tests/data/nv_reference.json,
erzeugt von tools/freeze_reference.py aus den Rohdaten sweep_raw.json der Stabilitäts- und der Same-Day-Messreihe): mehrere Zellen, Seeds
und alle Politiken. Das ist der Nachweis, dass die mechanische Aufteilung von stab.py in nv_model / nv_sim / nv_oracle nichts an der Logik
geändert hat. Kein OR-Tools: die Ergebnisse sind unabhängig von seiner Version."""
import json
import pathlib

import pytest

import nv_constants as C
from nv_model import Cfg, make_instance
from nv_sim import run_events, simulate, simulate_rollout

REF = json.loads((pathlib.Path(__file__).resolve().parent / "data" / "nv_reference.json").read_text(encoding="utf-8"))
STAB_METRICS = ("profit_total", "profit", "drive", "a", "b", "c", "n_fail", "n_acc", "n_cancel", "n_change", "n_ign", "ls_saved",
                "n_morning_served", "n_served_sd")
SD_KEYS = ("profit", "drive", "n_acc", "n_feas", "rev", "ls_saved")


def _by_name(cases, name):
    return next(c for c in cases if c["name"] == name)


@pytest.mark.parametrize("case", REF["stab"], ids=lambda c: c["name"])
def test_stabilitaet_bitgleich_zur_messreihe(case):
    """Alle 21 Politiken, 14 Kennzahlen je Instanz: exakt gleich den Zahlen aus sweep_raw.json."""
    cfg = Cfg(**case["cfg"])
    assert set(case["rows"]) == {str(s) for s in case["seeds"]}
    for seed_s, rows in case["rows"].items():
        inst = make_instance(cfg, int(seed_s))
        counts = case["counts"][seed_s]
        assert (len(inst.events), len(inst.arrivals), inst.n_orders_base, inst.n_morning) == (
            counts["n_events"], counts["n_arrivals"], counts["n_orders"], counts["n_morning"])
        assert set(rows) == set(C.POLICY_NAMES)
        for pol, expected in rows.items():
            r = run_events(inst, **C.POLICY_SPECS[pol])
            for m in STAB_METRICS:
                assert r[m] == expected[m], (case["name"], seed_s, pol, m, r[m], expected[m])


def test_horizont_h_bitgleich_zum_zusatzlauf():
    """Der Zusatzlauf (zeitbasierter Horizont H) reproduziert bitgleich, einschließlich S0, R, F3, P0.5 und P2 des Hauptlaufs."""
    case = REF["h"][0]
    cfg = Cfg(**case["cfg"])
    for seed_s, rows in case["rows"].items():
        inst = make_instance(cfg, int(seed_s))
        assert {"S0", "R", "F3", "P0.5", "P2"} <= set(rows) and sum(1 for p in rows if p.startswith("H")) == 8
        for pol, expected in rows.items():
            r = run_events(inst, **C.POLICY_SPECS[pol])
            for m in STAB_METRICS:
                assert r[m] == expected[m], (seed_s, pol, m, r[m], expected[m])
    # und der Zusatzlauf stimmt mit dem Hauptlauf überein (dieselben Instanzen)
    base = _by_name(REF["stab"], "basis")
    for seed_s, rows in case["rows"].items():
        for pol in ("S0", "R", "F3", "P0.5", "P2"):
            assert rows[pol] == base["rows"][seed_s][pol]


def _sd_runner(par, S):
    return {
        "P0": lambda i: simulate(i, "P0"), "P1": lambda i: simulate(i, "P1"), "P1p": lambda i: simulate(i, "P1p"),
        "P2v": lambda i: simulate(i, "P2v", rho=par["rho_v"]), "P2m": lambda i: simulate(i, "P2m", rho=par["rho_m"]),
        "P2": lambda i: simulate(i, "P2", mu=par["mu"]), "P2c": lambda i: simulate(i, "P2c", mu=par["mu_c"]),
        "P1L": lambda i: simulate(i, "P1", ls=True), "P1pL": lambda i: simulate(i, "P1p", ls=True),
        "P2L": lambda i: simulate(i, "P2", mu=par["mu_L"], ls=True),
        "P4": lambda i: simulate_rollout(i, S=S), "P4L": lambda i: simulate_rollout(i, S=S, ls=True),
    }


@pytest.mark.parametrize("case", REF["sameday"], ids=lambda c: c["name"])
def test_annahme_bitgleich_zur_messreihe(case):
    """Annahmeregeln P0 bis P2L (mit Schwellenwerten der Kalibrierung) bitgleich zu sweep_raw.json der Same-Day-Messreihe: Basiszelle,
    Rate 12, Frist 45, 16 Morgenaufträge, keine Erlösstreuung, Hotspot; dazu der Stichproben-Rollout P4 und P4L."""
    cfg = Cfg(**case["cfg"])
    runner = _sd_runner(case["par"], case["rollout_s"] or 24)
    for seed_s, rows in case["rows"].items():
        inst = make_instance(cfg, int(seed_s))
        for pol, expected in rows.items():
            r = runner[pol](inst)
            for k in SD_KEYS:
                assert r[k] == expected[k], (case["name"], seed_s, pol, k, r[k], expected[k])


def test_ohne_aenderungsereignisse_ist_s0_gleich_p1p_und_r_gleich_p1pl():
    """Zwischen den beiden Messreihen: ohne Änderungsereignisse liefert die Stabilitäts-Simulation (S0, R) bitgleich die Zahlen der
    Same-Day-Messreihe (P1p, P1pL): Gewinn, Fahrzeit, Annahmen (beide aus den eingefrorenen Rohdaten)."""
    stab = _by_name(REF["stab"], "ohne_ereignisse")
    sd = _by_name(REF["sameday"], "basis")
    common = sorted(set(stab["rows"]) & set(sd["rows"]))
    assert len(common) >= 4
    for seed_s in common:
        s, d = stab["rows"][seed_s], sd["rows"][seed_s]
        for mine, theirs in (("S0", "P1p"), ("R", "P1pL")):
            assert s[mine]["profit"] == d[theirs]["profit"] and s[mine]["drive"] == d[theirs]["drive"], (seed_s, mine)
            assert s[mine]["n_acc"] == d[theirs]["n_acc"] and s[mine]["ls_saved"] == d[theirs]["ls_saved"], (seed_s, mine)
        assert s["S0"]["a"] == 0 and s["S0"]["n_change"] == 0 and s["S0"]["n_cancel"] == 0


def test_referenzdaten_sind_vollstaendig():
    """Die Referenz deckt mehrere Zellen, Seeds und alle Politiken ab (kein leeres Gerüst)."""
    assert len(REF["stab"]) >= 8 and sum(len(c["rows"]) for c in REF["stab"]) >= 25
    assert {c["name"] for c in REF["stab"]} >= {"basis", "rate12", "frist60", "ereignisse_viele", "alle_drei_q34", "k2", "ohne_ereignisse"}
    assert {c["name"] for c in REF["sameday"]} >= {"basis", "hotspot", "sigma0", "rollout"}
    for case in REF["stab"]:
        for rows in case["rows"].values():
            assert set(rows) == set(C.POLICY_NAMES)
