"""Abnahmekriterien der Presets (Detailplan plan_nahverkehr.html, Abschnitt 7): welche Geschichte erzählt jedes Beispielszenario, und
woran erkennt man, dass sie trägt?

Einzige Quelle für tests/test_stories.py (Schwellen einzeln kippen) und tests/test_preset_stories.py (Abnahme der echten Presets).
Die Kriterien der Messreihe (`criteria`) stehen auf data/nv_results.json, Vorzeichen-Kriterien IMMER zusammen mit der Standardfehler-
Bedingung (Betrag > 2 SE). Der gezeigte Tag (`day_criteria`) bleibt qualitativ, weil ein Tag streut; sein Seed liegt bewusst außerhalb
der Stichprobe-Seeds der Messreihe (0 bis 199). Kein Löser mit Wall-Clock-Grenze in den Kriterien.

`criteria(name, data)` liefert für jedes Preset eine Liste (erfüllt, Text). Die Schwellen stehen als Konstanten oben, damit ein Test jede
einzeln an ihre Grenze schieben kann."""
import nv_constants as C
import nv_results as R

# Standard: Neuplanung lohnt, ein Preis je Änderung holt fast alles mit der Hälfte der Änderungen, Einfrieren nicht
STANDARD_MIN_P_SHARE = 0.75            # P-Anteil bei 50 % der R-Änderungen mindestens 75 %
STANDARD_MAX_F_SHARE = 0.70            # F-Anteil bei 50 % höchstens 70 %
STANDARD_BEST = "P1.5"                 # bei Kosten 2 der beste Regler
# Viele neue Aufträge: großer Gewinn, hoher Gewinn je Änderung
MANY_MIN_GAIN = 200.0                  # R − S0 mindestens 200
MANY_MIN_PER_CHANGE = 5.0              # Gewinn je Änderung mindestens 5
# Nur Änderungen: fast nichts zu holen
ONLY_MAX_GAIN = 25.0                   # R − S0 unter 25
ONLY_MAX_CHANGES = 10.0                # Änderungen von R unter 10
# Knappe Frist: Einfrieren bringt nichts, ein Preis schon
TIGHT_MIN_P2_GAIN = 40.0               # P_2 mindestens +40
TIGHT_P_POLICY, TIGHT_F_POLICY = "P2", "F3"
# Teure Änderungen: R verliert, der beste Regler nicht
EXPENSIVE_BEST = "P3"

FACTOR = C.SE_FACTOR

# --- gezeigter Tag (qualitativ) ----------------------------------------------------------------------------------
DAY_ONLY_MAX_GAIN = 40.0               # Nur Änderungen: R − S0 auf dem Tag unter 40 (Messreihe im Mittel +10,8)


def _de(v, digits=1, sign=False):
    text = f"{v:+.{digits}f}" if sign else f"{v:.{digits}f}"
    return text.replace(".", ",")


def _band(mean, se):
    return f"{_de(mean, 1, True)} ± {_de(se)}"


def _clear(mean, se, sign=+1):
    """Vorzeichen-Bedingung mit Standardfehler: sign +1 (Mittel > 2 SE) oder −1 (Mittel < −2 SE)."""
    return mean > FACTOR * se if sign > 0 else mean < -FACTOR * se


def _pol(cell, name):
    return cell["pol"][name]


def preset_cost(name):
    return C.PRESETS[name]["cost"]


def criteria(name, data):
    """Abnahmekriterien des Presets `name` auf den Messreihen `data`: Liste (erfüllt, Text)."""
    if name == "Standard":
        cell = R.find_cell(data)
        r = _pol(cell, "R")
        p50, f50 = R.share(cell, "P", 50), R.share(cell, "F", 50)
        j = R.judge(cell, preset_cost(name))
        return [
            (_clear(r["gain"], r["gain_se"]), f"R − S0 > 2 Standardfehler: {_band(r['gain'], r['gain_se'])}"),
            (p50 >= STANDARD_MIN_P_SHARE, f"P-Anteil bei 50 % mindestens 75 %: {_de(100 * p50, 0)} %"),
            (f50 <= STANDARD_MAX_F_SHARE, f"F-Anteil bei 50 % höchstens 70 %: {_de(100 * f50, 0)} %"),
            (j["best"] == STANDARD_BEST and j["net_best_over_S0"] > j["net_R_over_S0"],
             f"bei Kosten {_de(preset_cost(name), 0)} bester Regler P_1,5 mit R netto darunter: {R.policy_label(j['best'])} "
             f"{_de(j['net_best_over_S0'], 1, True)} gegenüber R {_de(j['net_R_over_S0'], 1, True)}"),
        ]
    if name == "Viele neue Aufträge":
        cell = R.find_cell(data, lam=12.0)
        r = _pol(cell, "R")
        return [
            (r["gain"] >= MANY_MIN_GAIN and _clear(r["gain"], r["gain_se"]), f"R − S0 mindestens 200 und > 2 Standardfehler: {_band(r['gain'], r['gain_se'])}"),
            (cell["stats"]["gain_per_change"] >= MANY_MIN_PER_CHANGE, f"Gewinn je Änderung mindestens 5: {_de(cell['stats']['gain_per_change'])}"),
        ]
    if name == "Nur Änderungen":
        cell = R.find_cell(data, lam=0.0)
        r = _pol(cell, "R")
        return [
            (_clear(r["gain"], r["gain_se"]) and r["gain"] < ONLY_MAX_GAIN, f"R − S0 > 2 Standardfehler und unter 25: {_band(r['gain'], r['gain_se'])}"),
            (r["a"] < ONLY_MAX_CHANGES, f"Änderungen von R unter 10: {_de(r['a'])}"),
        ]
    if name == "Knappe Frist":
        cell = R.find_cell(data, delta=60)
        f3, p2 = _pol(cell, TIGHT_F_POLICY), _pol(cell, TIGHT_P_POLICY)
        return [
            (not _clear(f3["gain"], f3["gain_se"]), f"F_3 nicht über 2 Standardfehler: {_band(f3['gain'], f3['gain_se'])}"),
            (_clear(p2["gain"], p2["gain_se"]) and p2["gain"] >= TIGHT_MIN_P2_GAIN,
             f"P_2 über 2 Standardfehler und mindestens 40: {_band(p2['gain'], p2['gain_se'])}"),
        ]
    if name == "Teure Änderungen":
        cell = R.find_cell(data)
        j = R.judge(cell, preset_cost(name))
        return [
            (j["net_R_over_S0"] < 0, f"R netto unter S0: {_de(j['net_R_over_S0'], 1, True)}"),
            (j["best"] == EXPENSIVE_BEST and j["net_best_over_S0"] > 0,
             f"bester Regler P_3 netto über 0: {R.policy_label(j['best'])} {_de(j['net_best_over_S0'], 1, True)} "
             f"({_de(j['net_best_over_R'], 1, True)} gegenüber R)"),
        ]
    raise KeyError(name)


def day_criteria(name, day, cost):
    """Qualitative Kriterien am gezeigten Tag `day` (nv_live.solve_day): ein Tag streut, deshalb nur die Richtung der Geschichte."""
    res = day["results"]
    s0, r = res["S0"], res["R"]
    gain_r = r["profit_total"] - s0["profit_total"]
    nets = {p: v["profit_total"] - cost * v["a"] for p, v in res.items()}
    best_measured = {"Standard": STANDARD_BEST, "Teure Änderungen": EXPENSIVE_BEST}.get(name)
    if name == "Standard":
        b = best_measured
        return [(gain_r > 0, f"R gewinnt auf dem Tag: {_de(gain_r, 0, True)}"),
                (nets[b] >= nets["R"], f"{R.policy_label(b)} netto mindestens so gut wie R: {_de(nets[b] - nets['S0'], 0, True)} gegenüber {_de(nets['R'] - nets['S0'], 0, True)}"),
                (res[b]["a"] < r["a"], f"{R.policy_label(b)} ändert weniger als R: {res[b]['a']} gegenüber {r['a']}")]
    if name == "Viele neue Aufträge":
        return [(gain_r > 0, f"R gewinnt auf dem Tag: {_de(gain_r, 0, True)}"), (day["n_arrivals"] > 0, f"neue Aufträge: {day['n_arrivals']}")]
    if name == "Nur Änderungen":
        return [(day["n_arrivals"] == 0, f"keine neuen Aufträge: {day['n_arrivals']}"),
                (gain_r < DAY_ONLY_MAX_GAIN, f"R − S0 auf dem Tag unter 40: {_de(gain_r, 0, True)}")]
    if name == "Knappe Frist":
        f3, p2 = res[TIGHT_F_POLICY], res[TIGHT_P_POLICY]
        g_f, g_p = f3["profit_total"] - s0["profit_total"], p2["profit_total"] - s0["profit_total"]
        return [(g_p > 0, f"P_2 gewinnt auf dem Tag: {_de(g_p, 0, True)}"), (g_p >= g_f, f"P_2 mindestens so gut wie F_3: {_de(g_p, 0, True)} gegenüber {_de(g_f, 0, True)}")]
    if name == "Teure Änderungen":
        b = best_measured
        return [(nets["R"] < nets["S0"], f"R netto unter S0 auf dem Tag: {_de(nets['R'] - nets['S0'], 0, True)}"),
                (nets[b] > nets["R"], f"{R.policy_label(b)} netto über R: {_de(nets[b] - nets['S0'], 0, True)} gegenüber {_de(nets['R'] - nets['S0'], 0, True)}")]
    raise KeyError(name)
