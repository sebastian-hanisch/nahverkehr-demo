"""Abnahmekriterien der Presets an KÜNSTLICHEN Werten: jedes Kriterium kippt einzeln an seiner Schwelle (Kopie der Ergebnisdatei mit
verstellten Werten), Vorzeichen-Kriterien nur zusammen mit der Standardfehler-Bedingung. Die Abnahme der echten Presets steht in
tests/test_preset_stories.py."""
import copy

import pytest

import nv_constants as C
import nv_results as R
import nv_stories as ST

DATA = R.load_results()


def crit(name, mutate=None):
    d = copy.deepcopy(DATA)
    if mutate:
        mutate(d)
    return [ok for ok, _ in ST.criteria(name, d)]


def texts(name):
    return [t for _, t in ST.criteria(name, DATA)]


def cell(d, **ov):
    return R.find_cell(d, **ov)


def set_r(d, gain, se, **ov):
    c = cell(d, **ov)
    c["pol"]["R"]["gain"], c["pol"]["R"]["gain_se"] = gain, se


def test_all_real_criteria_hold_and_have_texts():
    for name in C.PRESETS:
        result = ST.criteria(name, DATA)
        assert result and all(ok for ok, _ in result), (name, result)
        assert all(isinstance(t, str) and len(t) > 10 for _, t in result)
    assert [len(ST.criteria(n, DATA)) for n in C.PRESETS] == [4, 2, 2, 2, 2]
    with pytest.raises(KeyError):
        ST.criteria("gibt es nicht", DATA)


# --- Standard ---------------------------------------------------------------------------------------------
def test_standard_gain_needs_two_standard_errors():
    assert crit("Standard", lambda d: set_r(d, 20.0, 9.99))[0] is True
    assert crit("Standard", lambda d: set_r(d, 20.0, 10.0))[0] is False          # genau 2 SE: nicht belastbar
    assert crit("Standard", lambda d: set_r(d, -50.0, 1.0))[0] is False          # Vorzeichen falsch
    assert crit("Standard", lambda d: set_r(d, 0.0, 0.0))[0] is False


def test_standard_p_share_threshold():
    def with_p(v):
        return lambda d: cell(d)["stats"].__setitem__("share_P_50", v)
    assert crit("Standard", with_p(ST.STANDARD_MIN_P_SHARE))[1] is True
    assert crit("Standard", with_p(ST.STANDARD_MIN_P_SHARE - 0.0001))[1] is False


def test_standard_f_share_threshold():
    def with_f(v):
        return lambda d: cell(d)["stats"].__setitem__("share_F_50", v)
    assert crit("Standard", with_f(ST.STANDARD_MAX_F_SHARE))[2] is True
    assert crit("Standard", with_f(ST.STANDARD_MAX_F_SHARE + 0.0001))[2] is False


def test_standard_best_policy_at_cost_two():
    def lower_p15(d):
        cell(d)["pol"]["P1.5"]["pt"] -= 1000.0                                    # P_1,5 ist nicht mehr der beste Regler
    def raise_r(d):
        cell(d)["pol"]["R"]["pt"] += 5000.0                                       # R ist der beste (und "R netto darunter" gilt nicht)
    assert crit("Standard")[3] is True
    assert crit("Standard", lower_p15)[3] is False
    assert crit("Standard", raise_r)[3] is False
    assert ST.preset_cost("Standard") == 2.0 and ST.STANDARD_BEST == "P1.5"


# --- Viele neue Aufträge -------------------------------------------------------------------------------------------
def test_many_orders_gain_threshold_and_two_standard_errors():
    assert crit("Viele neue Aufträge", lambda d: set_r(d, 200.0, 5.0, lam=12.0))[0] is True
    assert crit("Viele neue Aufträge", lambda d: set_r(d, 199.99, 5.0, lam=12.0))[0] is False
    assert crit("Viele neue Aufträge", lambda d: set_r(d, 250.0, 125.0, lam=12.0))[0] is False        # genau 2 SE
    assert crit("Viele neue Aufträge", lambda d: set_r(d, 250.0, 124.9, lam=12.0))[0] is True


def test_many_orders_gain_per_change_threshold():
    def per_change(v):
        return lambda d: cell(d, lam=12.0)["stats"].__setitem__("gain_per_change", v)
    assert crit("Viele neue Aufträge", per_change(5.0))[1] is True
    assert crit("Viele neue Aufträge", per_change(4.99))[1] is False


# --- Nur Änderungen ---------------------------------------------------------------------------------------------------
def test_only_changes_gain_between_two_standard_errors_and_25():
    assert crit("Nur Änderungen", lambda d: set_r(d, 24.99, 1.0, lam=0.0))[0] is True
    assert crit("Nur Änderungen", lambda d: set_r(d, 25.0, 1.0, lam=0.0))[0] is False
    assert crit("Nur Änderungen", lambda d: set_r(d, 24.0, 12.0, lam=0.0))[0] is False                # genau 2 SE
    assert crit("Nur Änderungen", lambda d: set_r(d, -3.0, 0.5, lam=0.0))[0] is False                # kein Gewinn


def test_only_changes_change_count_threshold():
    def a_r(v):
        return lambda d: cell(d, lam=0.0)["pol"]["R"].__setitem__("a", v)
    assert crit("Nur Änderungen", a_r(9.99))[1] is True
    assert crit("Nur Änderungen", a_r(10.0))[1] is False


# --- Knappe Frist -----------------------------------------------------------------------------------------------------
def test_tight_deadline_f3_must_not_be_clear():
    def f3(gain, se):
        def m(d):
            p = cell(d, delta=60)["pol"]["F3"]
            p["gain"], p["gain_se"] = gain, se
        return m
    assert crit("Knappe Frist", f3(6.0, 3.0))[0] is True                       # genau 2 SE: nicht belastbar, Kriterium erfüllt
    assert crit("Knappe Frist", f3(6.03, 3.0))[0] is False
    assert crit("Knappe Frist", f3(-10.0, 1.0))[0] is True                     # ein negativer Wert ist nicht "über 2 SE"
    assert ST.TIGHT_F_POLICY == "F3" and ST.TIGHT_P_POLICY == "P2"


def test_tight_deadline_p2_threshold_and_two_standard_errors():
    def p2(gain, se):
        def m(d):
            p = cell(d, delta=60)["pol"]["P2"]
            p["gain"], p["gain_se"] = gain, se
        return m
    assert crit("Knappe Frist", p2(40.0, 5.0))[1] is True
    assert crit("Knappe Frist", p2(39.99, 5.0))[1] is False
    assert crit("Knappe Frist", p2(50.0, 25.0))[1] is False                    # genau 2 SE
    assert crit("Knappe Frist", p2(50.0, 24.9))[1] is True


# --- Teure Änderungen ---------------------------------------------------------------------------------------------------
def test_expensive_changes_r_loses_at_cost_five():
    def r_net(target):
        def m(d):
            c = cell(d)
            s0, r = c["pol"]["S0"], c["pol"]["R"]
            r["pt"] = s0["pt"] + target + 5.0 * (r["a"] - s0["a"])            # netto R − S0 bei Kosten 5 = target
        return m
    assert crit("Teure Änderungen", r_net(-0.01))[0] is True
    assert crit("Teure Änderungen", r_net(0.01))[0] is False
    assert crit("Teure Änderungen", r_net(0.0))[0] is False                   # gleich S0: R verliert nicht


def test_expensive_changes_best_policy_is_p3_with_positive_net():
    def lower_p3(d):
        cell(d)["pol"]["P3"]["pt"] -= 200.0
    def raise_p5(d):
        cell(d)["pol"]["P5"]["pt"] += 200.0                                    # ein anderer Regler ist besser als P_3
    assert crit("Teure Änderungen")[1] is True
    assert crit("Teure Änderungen", lower_p3)[1] is False
    assert crit("Teure Änderungen", raise_p5)[1] is False
    assert ST.preset_cost("Teure Änderungen") == 5.0 and ST.EXPENSIVE_BEST == "P3"


def test_criteria_texts_carry_the_measured_numbers():
    assert "+123,0 ± 12,1" in texts("Standard")[0] and "85 %" in texts("Standard")[1] and "60 %" in texts("Standard")[2]
    assert "P_1,5" in texts("Standard")[3] and "+84,4" in texts("Standard")[3] and "+65,8" in texts("Standard")[3]
    assert "+233,3" in texts("Viele neue Aufträge")[0] and "6,0" in texts("Viele neue Aufträge")[1]
    assert "+10,8" in texts("Nur Änderungen")[0] and "5,3" in texts("Nur Änderungen")[1]
    assert "-19,9" in texts("Teure Änderungen")[0] and "P_3" in texts("Teure Änderungen")[1] and "+57,3" in texts("Teure Änderungen")[1]


# --- gezeigter Tag ---------------------------------------------------------------------------------------------------------
def fake_day(**profits):
    """Künstlicher Tag: profits Politik -> (Gewinn, Änderungen); n_arrivals als Schlüssel `arrivals`."""
    arrivals = profits.pop("arrivals", 10)
    profits.setdefault("R", profits["S0"])                                         # jeder echte Tag hat S0 und R
    res = {p: dict(profit_total=v[0], a=v[1]) for p, v in profits.items()}
    return dict(results=res, n_arrivals=arrivals)


def dcrit(name, day, cost=None):
    return [ok for ok, _ in ST.day_criteria(name, day, C.PRESETS[name]["cost"] if cost is None else cost)]


def test_day_criteria_standard():
    ok = fake_day(S0=(1000, 0), R=(1100, 20), **{"P1.5": (1090, 5)})
    assert dcrit("Standard", ok) == [True, True, True]                           # Netto bei Kosten 2: R 1060, P_1,5 1080
    assert dcrit("Standard", fake_day(S0=(1000, 0), R=(1000, 20), **{"P1.5": (1090, 5)}))[0] is False   # R gewinnt nicht
    assert dcrit("Standard", fake_day(S0=(1000, 0), R=(1100, 20), **{"P1.5": (1059, 5)}))[1] is False   # 1049 < 1060
    assert dcrit("Standard", fake_day(S0=(1000, 0), R=(1100, 20), **{"P1.5": (1090, 20)}))[2] is False  # ändert nicht weniger
    assert dcrit("Standard", fake_day(S0=(1000, 0), R=(1100, 20), **{"P1.5": (1070, 5)}))[1] is True    # 1060 gleich R: mindestens so gut


def test_day_criteria_many_orders():
    assert dcrit("Viele neue Aufträge", fake_day(S0=(1000, 0), R=(1001, 3))) == [True, True]
    assert dcrit("Viele neue Aufträge", fake_day(S0=(1000, 0), R=(1000, 3))) == [False, True]
    assert dcrit("Viele neue Aufträge", fake_day(S0=(1000, 0), R=(1001, 3), arrivals=0)) == [True, False]


def test_day_criteria_only_changes():
    assert dcrit("Nur Änderungen", fake_day(S0=(1000, 0), R=(1039, 3), arrivals=0)) == [True, True]
    assert dcrit("Nur Änderungen", fake_day(S0=(1000, 0), R=(1040, 3), arrivals=0)) == [True, False]
    assert dcrit("Nur Änderungen", fake_day(S0=(1000, 0), R=(1039, 3), arrivals=1)) == [False, True]


def test_day_criteria_tight_deadline():
    assert dcrit("Knappe Frist", fake_day(S0=(1000, 0), F3=(1010, 4), P2=(1030, 4))) == [True, True]
    assert dcrit("Knappe Frist", fake_day(S0=(1000, 0), F3=(1010, 4), P2=(1000, 4))) == [False, False]
    assert dcrit("Knappe Frist", fake_day(S0=(1000, 0), F3=(1030, 4), P2=(1030, 4))) == [True, True]     # gleich: mindestens so gut
    assert dcrit("Knappe Frist", fake_day(S0=(1000, 0), F3=(1031, 4), P2=(1030, 4))) == [True, False]


def test_day_criteria_expensive_changes():
    assert dcrit("Teure Änderungen", fake_day(S0=(1000, 0), R=(1100, 30), P3=(1090, 4))) == [True, True]   # Kosten 5: R 950, P_3 1070
    assert dcrit("Teure Änderungen", fake_day(S0=(1000, 0), R=(1150, 30), P3=(1090, 4))) == [False, True]   # R netto 1000 = S0: nicht darunter
    assert dcrit("Teure Änderungen", fake_day(S0=(1000, 0), R=(1149, 30), P3=(1090, 4)))[0] is True
    assert dcrit("Teure Änderungen", fake_day(S0=(1000, 0), R=(1100, 30), P3=(1070, 4)))[1] is True         # 1050 gegen R 950: über R
    assert dcrit("Teure Änderungen", fake_day(S0=(1000, 0), R=(1100, 30), P3=(1000, 10)))[1] is False       # 950 = R netto: nicht über R
    with pytest.raises(KeyError):
        ST.day_criteria("gibt es nicht", fake_day(S0=(1, 0), R=(1, 0)), 1.0)
