"""Ergebnisdatei und Auswertung: Struktur von data/nv_results.json, Netto-Tabelle (aus den Politik-Mittelwerten neu gerechnet gleich der
gespeicherten der Messreihe), Urteil in drei Zuständen an künstlichen Zellen, Zell-Zuordnung, Kennzahlen des Kernabschnitts."""
import copy
import json

import pytest

import nv_constants as C
import nv_results as R

DATA = R.load_results()
BASE = R.find_cell(DATA)


def synthetic_cell(gain_r, a_r, best_gain, best_a, best="P1"):
    """Künstliche Zelle: S0 (0 Änderungen), R (gain_r, a_r) und eine Politik `best` (best_gain, best_a); alle anderen Politiken wie S0."""
    names = ["S0", "R", best]
    pol = {"S0": dict(pt=1000.0, a=0.0), "R": dict(pt=1000.0 + gain_r, a=a_r), best: dict(pt=1000.0 + best_gain, a=best_a)}
    return dict(names=names, pol=pol, stats={}, cfg=dict(C.BASE_CFG), n=200)


# ---------------------------------------------------------------------------------------------------
# Struktur der Datei
# ---------------------------------------------------------------------------------------------------
def test_structure_and_sizes():
    assert len(R.stab_cells(DATA)) == 28 and len(R.h_cells(DATA)) == 7 and len(R.sameday_cells(DATA)) == 34
    assert len(DATA["sameday"]["cross"]) == 17
    assert DATA["_meta"]["n_eval"] == 200 == C.MEASURED_N and DATA["_meta"]["sameday_n_eval"] == 60 == C.SAMEDAY_N and DATA["_meta"]["n_ora"] == 10
    assert all(c["n"] == 200 for c in R.stab_cells(DATA)) and all(c["n"] == 60 for c in R.sameday_cells(DATA))
    assert DATA["_timings"]["messreihe_kerne"] == 14 and DATA["_timings"]["messreihe_wanduhr_min"] == 35


def test_file_is_small_and_has_no_raw_instance_data():
    text = R.DATA_PATH.read_text(encoding="utf-8")
    assert len(text) < 400_000
    assert '"rows"' not in text and '"seed"' not in text and '"xy"' not in text


def test_policy_names_are_the_live_policy_grid():
    for c in R.stab_cells(DATA):
        assert c["names"] == list(C.POLICY_NAMES) and set(c["pol"]) == set(C.POLICY_NAMES)
    for c in R.h_cells(DATA):
        assert set(c["pol"]) == {f"H{h}" for h in C.H_STEPS}


def test_cfg_of_every_cell_is_unique():
    keys = [json.dumps(c["cfg"], sort_keys=True) for c in R.stab_cells(DATA)]
    assert len(set(keys)) == 28
    labels = [R.cell_label(c) for c in R.stab_cells(DATA)]
    assert len(set(labels)) == 28 and labels[0] == "Basisfall"


def test_null_column_signal_only_where_defined():
    """Keine Ergebnisspalte ist überall exakt 0, außer den per Definition nullwertigen (S0: Änderungen (a) und (c))."""
    for c in R.stab_cells(DATA):
        for name, p in c["pol"].items():
            if name == "S0":
                assert p["a"] == 0 and p["c"] == 0 and p["gain"] == 0
                assert p["b"] > 0                                       # (b) hat auch S0 (Einfügungen verschieben Ansagen)
            else:
                assert p["a"] > 0 or name in ("F12", "T240", "P8") or c["cfg"]["lam"] == 0.0, (R.cell_label(c), name)
    for key in ("gain", "a", "b", "c", "fail", "acc", "pt", "wins"):
        assert any(p[key] != 0 for c in R.stab_cells(DATA) for n, p in c["pol"].items() if n != "S0")


def test_all_cells_show_replanning_beats_doing_nothing():
    """R − S0 ist in allen 28 Zellen mehr als 2 Standardfehler positiv (kein Regime-Widerspruch)."""
    for row in R.regime_rows(DATA):
        assert row["verdict"] == "pos", row["label"]
    rows = {r["label"]: r for r in R.regime_rows(DATA)}
    assert min(r["gain"] for r in rows.values()) == pytest.approx(10.8, abs=0.06)
    assert max(r["gain"] for r in rows.values()) == pytest.approx(233.3, abs=0.06)


# ---------------------------------------------------------------------------------------------------
# Netto-Tabelle
# ---------------------------------------------------------------------------------------------------
def test_net_table_matches_the_stored_one_in_every_cell():
    """Die Netto-Tabelle, aus den Politik-Mittelwerten (Gewinn, Änderungen) neu gerechnet, ist die der Messreihe (dump_sweep.py)."""
    for c in R.stab_cells(DATA):
        stored = c["net"]["a"]
        assert [r["cc"] for r in stored] == list(R.COST_GRID)
        for st_row in stored:
            row = R.net_row(c, st_row["cc"])
            assert row["best"] == st_row["best"], (R.cell_label(c), st_row["cc"])
            assert row["net_over_S0"] == pytest.approx(st_row["net_over_S0"], abs=0.02)
            assert row["net_R_over_S0"] == pytest.approx(st_row["net_R_over_S0"], abs=0.02)
            assert row["net_over_R"] == pytest.approx(st_row["net_over_R"], abs=0.02)
            assert row["net_best"] == pytest.approx(st_row["net_best"], abs=0.05)


def test_base_net_table_matches_the_findings():
    rows = {r["cc"]: r for r in R.net_table(BASE)}
    best = {0.0: "P0.25", 1.0: "P0.5", 2.0: "P1.5", 3.0: "P1.5", 5.0: "P3", 8.0: "P3", 12.0: "P5", 20.0: "P8"}
    over = {0.0: 123.9, 1.0: 100.5, 2.0: 84.4, 3.0: 74.4, 5.0: 57.3, 8.0: 42.1, 12.0: 27.0, 20.0: 16.7}
    for cc, name in best.items():
        assert rows[cc]["best"] == name and rows[cc]["net_over_S0"] == pytest.approx(over[cc], abs=0.06)
    assert rows[5.0]["net_R_over_S0"] == pytest.approx(-19.9, abs=0.06) and rows[5.0]["net_over_R"] == pytest.approx(77.2, abs=0.06)
    assert R.break_even_cost(BASE) == pytest.approx(4.3, abs=0.05)
    # R verliert genau ab dem Gewinn je Änderung
    assert R.net_row(BASE, 4.2)["net_R_over_S0"] > 0 > R.net_row(BASE, 4.4)["net_R_over_S0"]


def test_net_row_ties_pick_the_first_policy_and_use_measure():
    cell = dict(names=["S0", "R", "F1"], pol={"S0": dict(pt=10.0, a=0.0, b=5.0), "R": dict(pt=20.0, a=2.0, b=9.0), "F1": dict(pt=20.0, a=2.0, b=1.0)})
    assert R.net_row(cell, 0.0)["best"] == "R"                        # Gleichstand: die erste in der Reihenfolge der Messreihe
    assert R.net_row(cell, 1.0, "a")["best"] == "R" and R.net_row(cell, 1.0, "b")["best"] == "F1"   # (b): 20 − 1 gegen 20 − 9
    assert R.net_row(cell, 100.0)["best"] == "S0"                     # bei hohen Kosten gewinnt Nichtstun
    assert R.net_row(cell, 3.0)["net"]["R"] == 14.0


# ---------------------------------------------------------------------------------------------------
# Urteil in drei Zuständen
# ---------------------------------------------------------------------------------------------------
def test_verdict_needs_more_than_two_standard_errors():
    assert R.verdict(2.0, 1.0) == "none" and R.verdict(2.0001, 1.0) == "pos"
    assert R.verdict(-2.0, 1.0) == "none" and R.verdict(-2.0001, 1.0) == "neg"
    assert R.verdict(0.0, 0.0) == "none" and R.verdict(0.1, 0.0) == "pos"


def test_judge_three_states_at_their_thresholds():
    # R: +100 bei 10 Änderungen; bester Regler P1: +110 bei 5 Änderungen. Bei Kosten c: R netto 100 − 10c, P1 netto 110 − 5c.
    cell = synthetic_cell(100.0, 10.0, 110.0, 5.0)
    j = R.judge(cell, 0.0)                                            # 110 gegen 100: genau 10 % mehr -> "lohnt" (höchstens 10 %)
    assert j["state"] == C.STATE_LOHNT and j["best"] == "P1"
    assert R.judge(synthetic_cell(100.0, 10.0, 110.01, 5.0), 0.0)["state"] == C.STATE_PREIS   # knapp über 10 %
    j = R.judge(cell, 2.0)                                            # R netto 80, P1 netto 100: 25 % mehr
    assert j["state"] == C.STATE_PREIS and j["net_R_over_S0"] == pytest.approx(80.0) and j["net_best_over_S0"] == pytest.approx(100.0)
    j = R.judge(cell, 10.0)                                           # R netto 0 (genau S0), P1 netto 60 -> nicht "verliert"
    assert j["net_R_over_S0"] == pytest.approx(0.0) and j["state"] == C.STATE_PREIS
    j = R.judge(cell, 10.5)                                           # R netto unter S0 -> "verliert"
    assert j["state"] == C.STATE_VERLIERT and j["net_R_over_S0"] < 0
    # R und bester Regler gleich (zwei gleiche Politiken): "lohnt"
    same = synthetic_cell(50.0, 5.0, 50.0, 5.0)
    assert R.judge(same, 1.0)["state"] == C.STATE_LOHNT
    # beide 0 gegen S0: kein "verliert" (R netto == S0) und der beste ist nicht besser -> "lohnt"
    zero = synthetic_cell(0.0, 0.0, 0.0, 0.0)
    assert R.judge(zero, 5.0)["state"] == C.STATE_LOHNT


def test_judge_on_the_real_base_cell():
    assert R.judge(BASE, 0.0)["state"] == C.STATE_LOHNT
    assert R.judge(BASE, 2.0)["state"] == C.STATE_PREIS and R.judge(BASE, 2.0)["best"] == "P1.5"
    assert R.judge(BASE, 5.0)["state"] == C.STATE_VERLIERT
    states = {R.judge(BASE, c / 2.0)["state"] for c in range(0, 41)}
    assert states == {C.STATE_LOHNT, C.STATE_PREIS, C.STATE_VERLIERT}     # alle drei Zustände kommen im Bereich 0 bis 20 vor


def test_judge_switches_state_only_in_the_expected_order():
    order = [R.judge(BASE, c / 2.0)["state"] for c in range(0, 41)]
    first_preis, first_verliert = order.index(C.STATE_PREIS), order.index(C.STATE_VERLIERT)
    assert first_preis < first_verliert and set(order[first_verliert:]) == {C.STATE_VERLIERT}


# ---------------------------------------------------------------------------------------------------
# Zell-Zuordnung
# ---------------------------------------------------------------------------------------------------
def test_assignable_cells_are_the_thirteen_grid_cells():
    cells = R.assignable_cells(DATA)
    assert len(cells) == 13
    settings = [s for _, s in cells]
    assert len(set(settings)) == 13
    assert (40, 6, "mittel", 120) in settings and (16, 6, "mittel", 120) in settings and (40, 12, "mittel", 120) in settings
    assert (40, 6, "keine", 120) in settings and (40, 6, "sehr viele", 120) in settings and (40, 6, "mittel", 60) in settings
    assert all(R.cfg_setting(c["cfg"]) == s for c, s in cells)
    assert R.cfg_setting(dict(C.BASE_CFG, K=2)) is None and R.cfg_setting(dict(C.BASE_CFG, n_m=27)) is None
    assert R.cfg_setting(dict(C.BASE_CFG, Q=34)) is None and R.cfg_setting(dict(C.BASE_CFG, p_chg=0.33, p_cancel=0.0)) is None


def test_every_measured_grid_cell_is_found_exactly():
    for cell, s in R.assignable_cells(DATA):
        found, exact, diff = R.nearest_stab_cell(DATA, *s)
        assert found is cell and exact and diff == []


def test_nearest_cell_for_combinations():
    def nearest(*s):
        cell, exact, diff = R.nearest_stab_cell(DATA, *s)
        return R.cfg_setting(cell["cfg"]), exact, diff
    assert nearest(40, 6, "mittel", 120) == ((40, 6, "mittel", 120), True, [])
    # zwei Nachbarzellen mit gleichem Abstand: die des früheren Parameters gewinnt (Rate vor Morgenaufträgen)
    assert nearest(52, 12, "mittel", 120) == ((40, 12, "mittel", 120), False, ["morning"])
    assert nearest(16, 12, "mittel", 120)[0] == (40, 12, "mittel", 120) or nearest(16, 12, "mittel", 120)[0] == (16, 6, "mittel", 120)
    # Abstand in Stufen: Zelle "sehr viele" 1 + 1 + 0 + 1 = 3, alle anderen Zellen 4: die Zelle "sehr viele" ist am nächsten
    assert nearest(28, 12, "sehr viele", 240) == ((40, 6, "sehr viele", 120), False, ["rate", "morning", "deadline"])
    # Abstand 2: eine Stufe in zwei Parametern
    cell, exact, diff = R.nearest_stab_cell(DATA, 16, 2, "mittel", 120)
    assert not exact and len(diff) >= 1
    assert R.differing_params((40, 6, "mittel", 120), (16, 0, "keine", 60)) == ["rate", "morning", "events", "deadline"]
    assert R.differing_params((40, 6, "mittel", 120), (40, 6, "mittel", 120)) == []


def test_assignment_note_is_empty_when_exact_and_explicit_otherwise():
    cell, exact, diff = R.nearest_stab_cell(DATA, 40, 6, "mittel", 120)
    assert R.assignment_note(40, 6, "mittel", 120, cell, diff) == ""
    cell, exact, diff = R.nearest_stab_cell(DATA, 52, 12, "mittel", 120)
    note = R.assignment_note(52, 12, "mittel", 120, cell, diff)
    assert "52 Morgenaufträge" in note and "nächstliegende gemessene Zelle" in note and "40 Morgenaufträge, Rate 12" in note
    assert "Morgenaufträge" in note.split("abweichend:")[1]
    assert R.setting_text((40, 6, "mittel", 120)) == "40 Morgenaufträge, Rate 6 je Stunde, Ereignisse mittel, Frist 120 min"


def test_nearest_sameday_cell():
    cell, exact = R.nearest_sameday_cell(DATA, 40, 6, 120)
    assert exact and cell["cfg"]["n_m"] == 40 and cell["cfg"]["lam"] == 6.0 and cell["cfg"]["delta"] == 120
    assert R.nearest_sameday_cell(DATA, 40, 0, 120) == (None, False)          # Rate 0: keine neuen Aufträge, nichts anzunehmen
    for m, r, d in ((16, 6, 120), (52, 12, 120), (40, 2, 120), (40, 12, 120), (52, 6, 120), (24, 12, 120), (24, 2, 120)):
        cell, exact = R.nearest_sameday_cell(DATA, m, r, d)
        assert exact and (cell["cfg"]["n_m"], cell["cfg"]["lam"], cell["cfg"]["delta"]) == (m, float(r), d)
    cell, exact = R.nearest_sameday_cell(DATA, 28, 6, 120)                      # 28 liegt zwischen 24 und 32: gleicher Abstand, die frühere Zelle
    assert not exact and cell["cfg"]["n_m"] == 24
    cell, exact = R.nearest_sameday_cell(DATA, 40, 6, 60)                       # Frist 60: am nächsten 45
    assert not exact and cell["cfg"]["delta"] == 45
    cell, exact = R.nearest_sameday_cell(DATA, 40, 6, 240)                      # Frist 240: 180 und 300 gleich weit, die frühere
    assert not exact and cell["cfg"]["delta"] == 180
    cell, exact = R.nearest_sameday_cell(DATA, 16, 12, 120)                     # Kombination: die Rasterzelle 24 / Rate 12
    assert not exact and (cell["cfg"]["n_m"], cell["cfg"]["lam"]) == (24, 12.0)
    assert all(c["cfg"][k] == v for c in R.sameday_candidates(DATA) for k, v in R.SAMEDAY_BASE.items())
    assert len(R.sameday_candidates(DATA)) == 21 and R.sameday_note(40, 6, 120, cell, True) == ""
    note = R.sameday_note(28, 6, 120, *R.nearest_sameday_cell(DATA, 28, 6, 120))
    assert "28 Morgenaufträge" in note and "24 Morgenaufträge" in note and "µ" in note
    assert R.sameday_note(40, 0, 120, None, False) == ""


# ---------------------------------------------------------------------------------------------------
# Kennzahlen des Kernabschnitts
# ---------------------------------------------------------------------------------------------------
def test_shares_and_intervals_of_the_base_cell():
    for fam, expected in (("P", (0.69, 0.85, 0.99)), ("F", (0.37, 0.60, 0.84))):
        for q, e in zip((25, 50, 75), expected):
            assert R.share(BASE, fam, q) == pytest.approx(e, abs=0.006)
    assert R.share(BASE, "T", 25) == pytest.approx(0.36, abs=0.006) and R.share(BASE, "T", 50) == pytest.approx(0.65, abs=0.006)
    lo, hi = R.share_ci(BASE, "P", 25)
    assert lo == pytest.approx(0.56, abs=0.006) and hi == pytest.approx(0.82, abs=0.006)
    assert R.share(BASE, "P", 50, "b") == pytest.approx(0.84, abs=0.006) and R.share(BASE, "F", 50, "c") == pytest.approx(0.52, abs=0.006)
    assert R.share(BASE, "P", 50, "a") == R.share(BASE, "P", 50)


def test_count_ci_negative_and_median_share():
    assert R.count_ci_negative(DATA, "a", 25) == (26, 28) and R.count_ci_negative(DATA, "a", 50) == (27, 28)
    assert R.count_ci_negative(DATA, "b", 25) == (13, 28) and R.count_ci_negative(DATA, "b", 50) == (10, 28)
    assert R.count_ci_negative(DATA, "c", 25) == (24, 28) and R.count_ci_negative(DATA, "c", 50) == (26, 28)
    assert R.median_share(DATA, "P") == pytest.approx(0.85, abs=0.01) and R.median_share(DATA, "F") == pytest.approx(0.54, abs=0.01)


def test_median_share_handles_odd_and_even_counts_and_none():
    def fake(vals):
        cells = [dict(stats={"share_P_50": v}) for v in vals]
        return {"stab": {"cells": cells}}
    assert R.median_share(fake([0.1, 0.9, 0.5]), "P") == 0.5
    assert R.median_share(fake([0.1, 0.9, 0.5, 0.7]), "P") == pytest.approx(0.6)
    assert R.median_share(fake([0.1, None, 0.5]), "P") == pytest.approx(0.3)


def test_curve_points_are_sorted_and_relative_to_s0():
    pts = R.curve_points(BASE)
    for fam in C.FAMILIES:
        xs = [p[0] for p in pts[fam]]
        assert xs == sorted(xs) and len(xs) == {"P": 8, "F": 7, "T": 4}[fam]
    rx, ry, name = pts["R"]
    assert (rx, ry, name) == (BASE["pol"]["R"]["a"], BASE["pol"]["R"]["gain"], "R") and rx == pytest.approx(28.6, abs=0.05)
    b = R.curve_points(BASE, "b")
    s0b = BASE["pol"]["S0"]["b"]
    assert b["R"][0] == pytest.approx(BASE["pol"]["R"]["b"] - s0b) and s0b == pytest.approx(24.9, abs=0.05)
    c = R.curve_points(BASE, "c")
    assert c["R"][0] == pytest.approx(BASE["pol"]["R"]["c"])


def test_labels_and_policy_names():
    assert R.policy_label("S0") == "S0 (starrer Plan)" and R.policy_label("R") == "R (volle Neuplanung)"
    assert R.policy_label("P1.5") == "P_1,5" and R.policy_label("F3") == "F_3" and R.policy_label("T120") == "T_120"
    assert [R.policy_family(n) for n in ("S0", "R", "F3", "P0.5", "T30", "H60")] == ["S0", "R", "F", "P", "T", "H"]
    assert R.event_level(0.25, 0.08) == "mittel" and R.event_level(0.33, 0.0) is None
    assert R.cell_label(R.find_cell(DATA, lam=12.0)) == "Rate 12 je Stunde"
    assert R.cell_label(R.find_cell(DATA, delta=60)) == "Frist 60 min" and R.cell_label(R.find_cell(DATA, n_m=52)) == "52 Morgenaufträge"
    assert R.cell_label(R.find_cell(DATA, w_addr=0.0)) == "nur Zeitfenster" and R.cell_label(R.find_cell(DATA, w_time=0.0)) == "nur Adresse"
    assert "Kapazität 34" in R.cell_label(R.find_cell(DATA, Q=34)) and "Verschiebung ±15 min" == R.cell_label(R.find_cell(DATA, chg_delta=15))
    assert R.cell_label(R.find_cell(DATA, addr_radius=12.0)) == "Adressradius 12 km"
    assert R.cell_label(R.find_cell(DATA, K=2, n_m=27, lam=4.0)) == "27 Morgenaufträge, 2 Fahrzeuge, Rate 4 je Stunde"
    assert R.cell_group(BASE) == "Basisfall" and R.cell_group(R.find_cell(DATA, delta=60)) == "Frist"
    assert R.cell_group(R.find_cell(DATA, lam=2.0)) == "Same-Day-Rate"


def test_find_cell_errors():
    with pytest.raises(KeyError):
        R.find_cell(DATA, n_m=999)
    with pytest.raises(KeyError):
        R.find_h_cell(DATA, n_m=999)
    assert R.find_h_cell(DATA)["cfg"] == {k: BASE["cfg"][k] for k in R.find_h_cell(DATA)["cfg"]}


def test_regime_rows_and_regime_findings():
    rows = R.regime_rows(DATA)
    assert len(rows) == 28 and rows[0]["cell"] is BASE and rows[0]["gain"] == BASE["pol"]["R"]["gain"] and rows[0]["se"] == BASE["pol"]["R"]["gain_se"]
    by = {r["label"]: r for r in rows}
    for label, gain in (("Rate 12 je Stunde", 233.3), ("Rate 2 je Stunde", 34.0), ("Frist 60 min", 79.0), ("Frist 240 min", 181.0),
                        ("16 Morgenaufträge", 152.0), ("52 Morgenaufträge", 118.0)):
        assert by[label]["gain"] == pytest.approx(gain, abs=1.0), label
    assert by["Basisfall"]["per_change"] == pytest.approx(4.3, abs=0.05) and by["Rate 12 je Stunde"]["per_change"] == pytest.approx(6.0, abs=0.05)
    assert by["Rate 0 je Stunde"]["per_change"] == pytest.approx(2.0, abs=0.05)


def test_event_cost_and_oracle_rows():
    e = BASE["event_cost"]
    assert (round(e["S0"]["mean"]), round(e["R"]["mean"])) == (228, 190) and e["gainR_extra"]["mean"] == pytest.approx(38.3, abs=0.06)
    rows = R.oracle_rows(DATA)
    assert len(rows) == 9 and all(r["n"] == 10 for r in rows)
    base_row = rows[0]
    assert base_row["oracle"] == pytest.approx(2942.8, abs=0.06) and base_row["gap_r"][0] == pytest.approx(582.3, abs=0.06)
    assert base_row["gap_r"][0] / base_row["oracle"] == pytest.approx(0.20, abs=0.005)
    assert all(r["oracle"] > r["best"] >= r["r"] > 0 for r in rows)


def test_sameday_selectors_and_bars():
    sd = R.sameday_cells(DATA)[0]
    assert sd["cfg"]["n_m"] == 40 and sd["par"]["mu"] == 3.0 and sd["par"]["mu_L"] == 1.5
    bars = R.accept_bars(sd)
    assert [b[0] for b in bars] == ["P1", "P1p", "P2", "P1pL", "P2L", "P4L", "Orakel"]
    assert bars[0][1] == pytest.approx(618, abs=0.6) and bars[2][1] == pytest.approx(758, abs=0.6) and bars[-1][1] == pytest.approx(1174.8, abs=0.06)
    no_ora = [c for c in R.sameday_cells(DATA) if not c.get("oracle")][0]
    assert [b[0] for b in R.accept_bars(no_ora)][-1] == "P4L"
    frist = R.sameday_rows(DATA, "frist")
    assert [c["cfg"]["delta"] for c in frist] == [45, 90, 180, 300]          # nur Zellen mit Orakel; die Basiszelle (120) gehört zur Gruppe "basis"
    assert [c["cfg"]["n_m"] for c in R.sameday_rows(DATA, "auslastung")] == [16, 24, 32, 48, 56]
    assert [c["cfg"]["lam"] for c in R.sameday_rows(DATA, "rate")] == [1.0, 2.0, 4.0, 10.0, 16.0]
    rows = R.calibration_rows(sd)
    assert [r["mu"] for r in rows] == sorted(r["mu"] for r in rows) and len(rows) == 13
    best_p2 = max(rows, key=lambda r: r["p2"])
    best_p2l = max(rows, key=lambda r: r["p2l"])
    assert best_p2["mu"] == sd["par"]["mu"] and best_p2l["mu"] == sd["par"]["mu_L"]


def test_calibration_picks_the_argmax_in_every_cell():
    """Der gewählte Schwellenwert µ ist in jeder Zelle der mit dem höchsten Kalibrier-Gewinn (Gleichstand: der kleinste)."""
    for c in R.sameday_cells(DATA):
        rows = R.calibration_rows(c)
        for key, par_key in (("p2", "mu"), ("p2l", "mu_L")):
            top = max(round(r[key], 9) for r in rows)
            assert min(r["mu"] for r in rows if round(r[key], 9) == top) == c["par"][par_key], (R.sameday_setting_text(c), key)


def test_data_is_not_mutated_by_the_analysis():
    before = json.dumps(DATA, sort_keys=True)
    cell = copy.deepcopy(BASE)
    R.judge(cell, 3.0)
    R.net_table(cell)
    R.regime_rows(DATA)
    R.curve_points(BASE)
    assert json.dumps(DATA, sort_keys=True) == before
