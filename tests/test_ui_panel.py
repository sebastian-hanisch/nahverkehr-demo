"""Kennzahlen, Meldungen und Tabellen des Panels (reine Funktionen und Text-Formate) sowie die Zahlenformate."""
import pytest

import nv_constants as C
import nv_format as F
import nv_live as LV
import nv_results as R
import nv_ui_panel as UI

DATA = R.load_results()
BASE = R.find_cell(DATA)


def fake_day(**pol):
    """Künstlicher Live-Tag: Politik -> (Gewinn, Änderungen); S0 und R sind immer da."""
    pol.setdefault("S0", (1000, 0))
    pol.setdefault("R", (1000, 0))
    for name in C.POLICY_NAMES:                                                    # jede Politik der Live-Rechnung ist da (wie S0, wenn nicht angegeben)
        pol.setdefault(name, pol["S0"])
    res = {p: dict(profit_total=v[0], a=v[1], b=3, c=1, n_acc=5, n_fail=0) for p, v in pol.items()}
    return dict(results=res, seed=7, n_arrivals=10)


class Recorder:
    def __init__(self):
        self.calls = []

    def metric(self, label, value, delta=None, delta_color="normal", delta_arrow="auto", help=None):
        self.calls.append(dict(label=label, value=value, delta=delta, delta_color=delta_color, delta_arrow=delta_arrow, help=help))


# --- Formate --------------------------------------------------------------------------------------------
def test_number_formats_use_the_german_decimal_comma():
    assert F.fmt_num(1.25) == "1,2" and F.fmt_num(1.26) == "1,3" and F.fmt_num(3.0, 0) == "3" and F.fmt_num(2.5, 2, True) == "+2,50"
    assert F.fmt_num(-0.04, 1, True) == "-0,0" and F.fmt_num(-4.5, 1, True) == "-4,5" and F.fmt_pct(12.34, 1) == "12,3 %" and F.fmt_pct(-1, 0, True) == "-1 %"
    assert F.fmt_share(0.855) == "86 %" and F.fmt_share(0.0) == "0 %" and F.fmt_share(None) == "–" and F.fmt_share(1.0) == "100 %"
    assert F.fmt_band(123.0, 12.1) == "+123,0 ± 12,1" and F.fmt_band(-5.0, 1.0) == "-5,0 ± 1,0" and F.fmt_band(5.0, 1.0, signed=False) == "5,0 ± 1,0"
    assert F.fmt_band(2.0, 0.5, 0) == "+2 ± 0"
    assert F.fmt_ci([56.4, 82.4]) == "(56 bis 82)" and F.fmt_ci(None) == "" and F.fmt_ci([-1.6, 3.2], 1) == "(-1,6 bis 3,2)"
    assert F.fmt_clock(0) == "0:00" and F.fmt_clock(65) == "1:05" and F.fmt_clock(479.6) == "8:00" and F.fmt_clock(125) == "2:05"
    assert F.fmt_min(59.6) == "60 min"
    assert UI.fmt_eur(1234567) == "1.234.567" and UI.fmt_eur(1234, True) == "+1.234" and UI.fmt_eur(-1234.4, True) == "-1.234" and UI.fmt_eur(0) == "0"


# --- Live-Kennzahlen ---------------------------------------------------------------------------------------
def test_live_nets_and_numbers():
    day = fake_day(R=(1100, 20), **{"P1.5": (1090, 5)})
    nets = UI.live_nets(day, 2.0)
    assert len(nets) == 21 and {k: nets[k] for k in ("S0", "R", "P1.5")} == {"S0": 1000.0, "R": 1060.0, "P1.5": 1080.0}
    x = UI.live_numbers(day, "P1.5", 2.0)
    assert x == dict(s0=1000, r=1100, r_gain=100, r_a=20, best="P1.5", best_profit=1090, best_a=5, net_s0=1000.0, net_r=1060.0, net_best=1080.0,
                     net_best_over_s0=80.0, net_r_over_s0=60.0)
    assert UI.live_nets(day, 0.0)["R"] == 1100.0


def test_render_metrics_shows_four_tiles_in_the_expected_order():
    day = fake_day(R=(1100, 20), **{"P1.5": (1090, 5)})
    cols = [Recorder() for _ in range(4)]
    x = UI.render_metrics(cols, day, "P1.5", 2.0)
    m = [c.calls[0] for c in cols]
    assert [c["label"] for c in m] == ["Gewinn starrer Plan (S0)", "Gewinn volle Neuplanung (R)", "Netto bester Regler (P_1,5)", "Änderungen je Regler (S0 / R / bester)"]
    assert [c["value"] for c in m] == ["1.000", "1.100", "1.080", "0 / 20 / 5"]
    assert m[0]["delta"] == "0 Änderungen per Definition" and m[0]["delta_color"] == "off" and m[0]["delta_arrow"] == "off"
    assert m[1]["delta"] == "+100 gegenüber S0, 20 Änderungen" and m[1]["delta_color"] == "normal"
    assert m[2]["delta"] == "+80 gegenüber S0 bei 2,0 Kosten je Änderung" and m[2]["delta_color"] == "normal"
    assert m[3]["delta"] == "geänderte Stopps je Tag, fahrerseitig" and m[3]["delta_color"] == "off"
    assert all(c["help"] and len(c["help"]) > 60 for c in m) and x["net_best"] == 1080.0
    assert "NICHT der Reglerparameter" in m[2]["help"] and "per Definition 0" in m[0]["help"] and "Ein einzelner Tag" in m[0]["help"]


def test_render_metrics_delta_sign_is_mine_minus_reference():
    day = fake_day(R=(900, 10), **{"P1.5": (1090, 5)})
    cols = [Recorder() for _ in range(4)]
    UI.render_metrics(cols, day, "P1.5", 0.0)
    assert cols[1].calls[0]["delta"].startswith("-100 gegenüber S0")               # R verliert: negatives Vorzeichen, Farbe über delta_color
    assert cols[2].calls[0]["delta"].startswith("+90 gegenüber S0")


# --- Meldung in drei Zuständen ---------------------------------------------------------------------------------------
def test_message_three_states_and_texts():
    day = fake_day(R=(1100, 20), **{"P1.5": (1090, 5), "P0.25": (1100, 20), "P3": (1090, 5)})
    state, text = UI.message(day, BASE, 0.0)
    assert state == C.STATE_LOHNT and text.startswith("✅ Volle Neuplanung lohnt: bei 0,0 Kosten je Änderung") and "höchstens 10 % mehr" in text
    assert "+123" in text and "+124" in text and "P_0,25" in text and "Messreihe, 40 Morgenaufträge, Rate 6 je Stunde, Ereignisse mittel, Frist 120 min, 200 Tage" in text
    assert "Auf diesem einen Tag:" in text
    state, text = UI.message(day, BASE, 2.0)
    assert state == C.STATE_PREIS and text.startswith("ℹ️ Hier lohnt ein Preis je Änderung") and "+66" in text and "+84" in text and "(+28 % mehr)" in text
    assert "P_1,5" in text and "mit weniger Änderungen" in text
    state, text = UI.message(day, BASE, 5.0)
    assert state == C.STATE_VERLIERT and text.startswith("⚠️ Volle Neuplanung verliert gegen den starren Plan") and "-20" in text and "+57" in text and "P_3" in text


def test_message_appends_the_assignment_note_and_handles_zero_gain():
    day = fake_day(R=(1100, 20))
    assert UI.message(day, BASE, 2.0, "Hinweis XYZ")[1].endswith("Hinweis XYZ")
    assert "Hinweis XYZ" not in UI.message(day, BASE, 2.0)[1]
    cell = dict(names=["S0", "R", "P1"], pol={"S0": dict(pt=1000.0, a=0.0), "R": dict(pt=1000.0, a=0.0), "P1": dict(pt=1010.0, a=1.0)}, cfg=dict(C.BASE_CFG),
                stats={}, n=200)
    state, text = UI.message(day, cell, 0.0)
    assert state == C.STATE_PREIS and "% mehr" not in text                          # R gewinnt nichts: kein Prozentvergleich


def test_render_message_uses_the_matching_box(monkeypatch):
    calls = []
    for kind in ("success", "info", "warning"):
        monkeypatch.setattr(UI.st, kind, lambda text, kind=kind: calls.append((kind, text.split()[0])))
    day = fake_day(R=(1100, 20))
    assert UI.render_message(day, BASE, 0.0) == C.STATE_LOHNT and UI.render_message(day, BASE, 2.0) == C.STATE_PREIS
    assert UI.render_message(day, BASE, 5.0) == C.STATE_VERLIERT
    assert [c[0] for c in calls] == ["success", "info", "warning"] and [c[1] for c in calls] == ["✅", "ℹ️", "⚠️"]


# --- Tabellen --------------------------------------------------------------------------------------------------------
def test_comparison_table_rows_and_columns():
    day = fake_day(R=(1100, 20), **{"P1.5": (1090, 5)})
    df = UI.comparison_table(day, BASE, "P1.5", 2.0)
    assert list(df.columns) == ["Kennzahl", "Dieser Tag (Seed 7, 1 Tag)", "Messreihe (200 Tage)"] and len(df) == 6
    rows = {r["Kennzahl"]: r for r in df.to_dict("records")}
    assert rows["Gewinn R − S0"]["Dieser Tag (Seed 7, 1 Tag)"] == "+100" and rows["Gewinn R − S0"]["Messreihe (200 Tage)"] == "+123,0 ± 12,1"
    assert rows["Änderungen von R (a)"]["Messreihe (200 Tage)"] == "28,6 ± 1,2" and rows["Änderungen von R (a)"]["Dieser Tag (Seed 7, 1 Tag)"] == "20"
    assert rows["Gewinn P_1,5 − S0"]["Dieser Tag (Seed 7, 1 Tag)"] == "+90" and rows["Änderungen von P_1,5 (a)"]["Dieser Tag (Seed 7, 1 Tag)"] == "5"
    assert rows["Netto R − S0 bei 2,0 Kosten je Änderung"]["Messreihe (200 Tage)"] == "+65,8"
    assert rows["Netto P_1,5 − S0 bei 2,0 Kosten je Änderung"]["Messreihe (200 Tage)"] == "+84,4"
    assert rows["Netto R − S0 bei 2,0 Kosten je Änderung"]["Dieser Tag (Seed 7, 1 Tag)"] == "+60"


def test_distribution_sentence_shows_median_and_quartiles():
    text = UI.distribution_sentence(BASE)
    assert "Mittel +123" in text and "Median +99" in text and "[+22; +215]" in text and "78,5 % der Tage gewinnen" in text and "200 Tage" in text


def test_policy_table_lists_all_policies():
    day = LV.solve_day(40, 6, "mittel", 120, 292)
    df = UI.policy_table(day, 2.0)
    assert len(df) == 21 and df["Politik"].iloc[0] == "S0 (starrer Plan)" and df["Politik"].iloc[1] == "R (volle Neuplanung)"
    assert list(df.columns)[-1] == "Netto bei 2,0 je Änderung" and df["Gewinn − S0"].iloc[0] == 0 and df["Änderungen (a)"].iloc[0] == 0
    for _, row in df.iterrows():
        assert row.iloc[-1] == pytest.approx(row["Gewinn"] - 2.0 * row["Änderungen (a)"], abs=0.05)
    assert df["Politik"].tolist()[2] == "F_1" and df["Politik"].tolist()[-1] == "T_240"


def test_events_and_halteliste_frames():
    det = LV.day_detail(40, 6, "mittel", 120, 292, "R")
    df = UI.events_table(det)
    assert len(df) == len(det["events"]) and list(df.columns) == ["Zeit", "Auftrag", "Ereignis", "Einzelheit", "geänderte Stopps (a)", "geänderte Ansagen (b)"]
    assert set(df["Ereignis"]) <= {"neuer Auftrag, angenommen", "neuer Auftrag, abgelehnt", "Storno", "Änderung", "ignoriert"}
    assert df["geänderte Stopps (a)"].sum() == det["metrics"]["a"] and df["Zeit"].iloc[0] == F.fmt_clock(det["events"][0]["t"])
    veh = det["vehicles"][0]
    h = UI.halteliste_frame(veh)
    assert len(h) == len(veh["stops"]) and h["Nr."].tolist() == list(range(1, len(veh["stops"]) + 1))
    assert set(h["Art"]) <= {"Morgenauftrag", "neuer Auftrag", "geänderter Morgenauftrag"}
    assert h["Service ab"].iloc[0] == F.fmt_clock(veh["stops"][0]["start"]) and "–" in h["Zeitfenster"].iloc[0]


def test_share_and_net_frames():
    df = UI.share_table(BASE)
    assert df["Reglerfamilie"].tolist() == [C.FAMILY_LABELS[f] for f in C.FAMILIES]
    assert df.iloc[0]["bei 25 % der R-Änderungen"] == "69 % (56 bis 82)" and df.iloc[1]["bei 50 % der R-Änderungen"] == "60 % (48 bis 74)"
    assert df.iloc[2]["bei 25 % der R-Änderungen"] == "36 % (25 bis 47)"
    cell = dict(BASE, stats=dict(BASE["stats"], share_T_75=None))
    assert UI.share_table(cell).iloc[2]["bei 75 % der R-Änderungen"] == "–"
    net = UI.net_frame(BASE, 2.0)
    assert len(net) == 9 and net["Kosten je Änderung"].str.contains("◀ eingestellt").sum() == 1
    row = net[net["Kosten je Änderung"].str.contains("eingestellt")].iloc[0]
    assert row["bester Regler"] == "P_1,5" and row["Netto bester Regler − S0"] == "+84,4" and row["Netto R − S0"] == "+65,8" and row["bester Regler − R"] == "+18,6"
    off = UI.net_frame(BASE, 4.0)                                                    # Kosten abseits des Rasters: eigene Zeile, sortiert
    assert len(off) == 10 and off["Kosten je Änderung"].tolist().index("4,0  ◀ eingestellt") == 5
    assert UI.net_frame(BASE, 0.0)["Kosten je Änderung"].iloc[0] == "0,0  ◀ eingestellt"


def test_regime_frame_and_event_frames():
    df = UI.regime_frame(DATA, BASE)
    assert len(df) == 28 and df["Zelle"].iloc[0] == "▶ Basisfall" and df["Zelle"].str.startswith("▶").sum() == 1 and df["Gruppe"].iloc[0] == "Basisfall"
    assert df["R − S0"].iloc[0] == "+123,0 ± 12,1" and df["Änderungen von R"].iloc[0] == "28,6" and df["Gewinn je Änderung"].iloc[0] == "4,3"
    assert df["P-Anteil bei 50 %"].iloc[0] == "85 %" and df["F-Anteil bei 50 %"].iloc[0] == "60 %" and set(df["Urteil"]) == {"Neuplanung lohnt (belastbar)"}
    assert UI.regime_frame(DATA)["Zelle"].str.startswith("▶").sum() == 0
    rows = UI.regime_rows_for_chart(DATA, BASE)
    assert sum(r["highlight"] for r in rows) == 1 and rows[0]["highlight"] is True
    ec = UI.event_cost_frame(BASE)
    assert ec["Mittel ± Standardfehler"].tolist()[:2] == ["228 ± 12", "190 ± 13"] and ec["Mittel ± Standardfehler"].iloc[2] == "+38 ± 13"
    assert ec["Mittel ± Standardfehler"].iloc[3] == "+85 ± 9" and ec["Mittel ± Standardfehler"].iloc[4] == "+123 ± 12"
    ek = UI.event_kind_frame(DATA)
    assert len(ek) == sum(1 for c in R.stab_cells(DATA) if c.get("event_cost")) and ek["Zelle"].iloc[0] == "Basisfall"
    only_cancel = ek[ek["Zelle"] == "Änderungen 0,00 / Stornos 0,33"].iloc[0]
    assert only_cancel["Verlust S0"] == "526 ± 15" and only_cancel["zusätzlicher R-Gewinn"] == "-6 ± 15"


def test_measure_horizon_and_oracle_frames():
    m = UI.measure_frame(DATA, BASE)
    assert m["Maß"].tolist() == [R.MEASURES[k] for k in "abc"]
    assert m["Zellen mit F − P < 0 (25 % / 50 %)"].tolist() == ["26 / 27 von 28", "13 / 10 von 28", "24 / 26 von 28"]
    assert m["F − P bei 25 % (95 %)"].iloc[0] == "-39,0 (-61 bis -19)" and m["F − P bei 50 % (95 %)"].iloc[2] == "-38,3 (-56 bis -19)"
    assert m["P-Anteil bei 50 %"].tolist() == ["85 %", "84 %", "83 %"] and m["F-Anteil bei 50 %"].tolist() == ["60 %", "64 %", "52 %"]
    h = UI.horizon_frame(DATA)
    assert len(h) == 7 and h["H − P bei 25 % (95 %)"].iloc[0] == "-37,6 (-58 bis -19)" and h["H-Anteil bei 50 %"].iloc[0] == "63 %"
    hp = UI.h_points_frame(R.find_h_cell(DATA))
    assert len(hp) == 8 and dict(zip(hp["Horizont"], hp["Änderungen (a)"]))["H_60 min"] == "18,5"
    o = UI.oracle_frame(DATA)
    assert len(o) == 9 and o["Orakel"].iloc[0] == "2943" and o["Lücke zu R"].iloc[0] == "582 ± 102" and o["Lücke in % des Orakels"].iloc[0] == "20 %"
    assert (o["Instanzen"] == 10).all()


def test_accept_frames():
    sd = R.sameday_cells(DATA)[0]
    a = UI.accept_measured_frame(sd)
    assert a["Regel"].iloc[0] == "P1 (alles Machbare)" and a["Gewinn gegenüber „nie annehmen“"].iloc[0] == "618 ± 29" and a["angenommen"].iloc[0] == "15,0"
    assert a["Median [Q1; Q3]"].iloc[0] == "638 [452; 792]" and a["Regel"].tolist()[3] == "P1L"
    p = UI.accept_pairs_frame(sd)
    assert p["Vergleich"].iloc[2] == "reine Erlös-Schwelle à la Littlewood (P2v − P1p)" and p["Unterschied"].iloc[2] == "-14 ± 11"
    assert p["Siege / Niederlagen / Gleichstand"].iloc[1] == "35 / 20 / 5" and len(p) == 7
    c = UI.calibration_frame(sd)
    assert len(c) == 13 and c[c["µ"].str.contains("P2L")]["µ"].iloc[0] == "1,50  ◀ P2L" and c[c["µ"].str.contains("◀ P2$")]["µ"].iloc[0] == "3,00  ◀ P2"
    both = UI.calibration_frame(dict(sd, par=dict(sd["par"], mu_L=3.0)))
    assert both[both["µ"].str.contains("P2L")]["µ"].iloc[0] == "3,00  ◀ P2  ◀ P2L"
    fr = UI.oracle_sameday_frame(DATA, "frist")
    assert fr["Frist"].tolist() == ["45 min", "90 min", "180 min", "300 min"] and fr["Anteil des Orakels"].tolist() == ["54 %", "64 %", "82 %", "91 %"]
    au = UI.oracle_sameday_frame(DATA, "auslastung")
    assert au["Morgenaufträge"].tolist() == [16, 24, 32, 48, 56] and au["Lücke"].iloc[0] == "221 ± 27"
    cr = UI.cross_frame(DATA)
    assert len(cr) == 16 and cr["Zelle"].iloc[0].startswith("16 Morgenaufträge") and cr["P2 − P1p mit µ der Basiszelle"].iloc[0] == "-97 ± 26"
    live = UI.accept_live_frame(LV.solve_accept(40, 6, 120, 292, 3.0, 1.5))
    assert live["Regel"].tolist()[0] == "P0 (nie annehmen)" and len(live) == 6 and live["Gewinn gegenüber „nie annehmen“"].iloc[0] == 0
