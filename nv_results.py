"""Laden und Auswerten der vorgerechneten Messreihen (data/nv_results.json, erzeugt von tools/build_results.py aus den Auswertungen
von messreihe_stabilitaet und messreihe_sameday): Zellen, Zell-Zuordnung, Netto-Tabelle, Urteil in drei Zuständen.

Die App rechnet die Messreihen NIE live (etwa 35 Minuten auf 14 Kernen); sie liest nur diese Datei. Reine Rechnung, kein Streamlit."""
import functools
import json
import pathlib

import nv_constants as C

DATA_PATH = pathlib.Path(__file__).resolve().parent / "data" / "nv_results.json"

VERDICT_TEXT = {"pos": "Neuplanung lohnt (belastbar)", "neg": "Neuplanung verliert (belastbar)", "none": "nicht von 0 zu unterscheiden"}
STATE_TEXT = {C.STATE_LOHNT: "volle Neuplanung lohnt", C.STATE_PREIS: "hier lohnt ein Preis je Änderung",
              C.STATE_VERLIERT: "volle Neuplanung verliert gegen den starren Plan"}

MEASURES = {"a": "fahrerseitig (a)", "b": "kundenseitig (b)", "c": "Neuplanungsereignisse (c)"}
COST_GRID = (0.0, 0.5, 1.0, 2.0, 3.0, 5.0, 8.0, 12.0, 20.0)      # Kosten je Änderung im Maß (a), wie in der Messreihe


def verdict(mean, se, factor=C.SE_FACTOR):
    """Urteil in drei Zuständen: 'pos', 'neg', 'none' - ein Vorzeichen nur, wenn der Betrag des Mittels mehr als `factor`
    Standardfehler beträgt."""
    if mean > factor * se:
        return "pos"
    if mean < -factor * se:
        return "neg"
    return "none"


@functools.lru_cache(maxsize=4)
def _load(path):
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def load_results(path=None):
    """Die vorgerechneten Messreihen (nicht verändern: das Ergebnis ist zwischengespeichert)."""
    return _load(str(path or DATA_PATH))


def stab_cells(data):
    return data["stab"]["cells"]


def sameday_cells(data):
    return data["sameday"]["cells"]


def h_cells(data):
    return data["stab"]["h_cells"]


# ----------------------------------------------------------------------------------------------------------------
# Zellen finden und beschriften
# ----------------------------------------------------------------------------------------------------------------
def find_cell(data, **overrides):
    """Die Stabilitäts-Zelle, die sich vom Basisfall genau in `overrides` unterscheidet (cfg-Schlüssel)."""
    want = dict(C.BASE_CFG, **overrides)
    hits = [c for c in stab_cells(data) if all(c["cfg"].get(k) == v for k, v in want.items())]
    if len(hits) != 1:
        raise KeyError((overrides, len(hits)))
    return hits[0]


def find_h_cell(data, **overrides):
    want = dict(C.BASE_CFG, **overrides)
    hits = [c for c in h_cells(data) if all(c["cfg"].get(k) == v for k, v in want.items())]
    if len(hits) != 1:
        raise KeyError((overrides, len(hits)))
    return hits[0]


def _de(v, digits=1):
    return f"{v:.{digits}f}".replace(".", ",")


def event_level(p_chg, p_cancel):
    """Name der Reglerstufe zu (p_chg, p_cancel) oder None."""
    for name, (a, b) in C.EVENT_LEVELS.items():
        if abs(a - p_chg) < 1e-9 and abs(b - p_cancel) < 1e-9:
            return name
    return None


def cell_label(cell):
    """Beschriftung einer Stabilitäts-Zelle aus dem Unterschied zum Basisfall (deutsch), z. B. 'Rate 12 je Stunde'."""
    cfg, base = cell["cfg"], C.BASE_CFG
    parts = []
    if cfg["n_m"] != base["n_m"] or cfg["K"] != base["K"]:
        parts.append(f"{cfg['n_m']} Morgenaufträge" + (f", {cfg['K']} Fahrzeuge" if cfg["K"] != base["K"] else ""))
    if cfg["lam"] != base["lam"]:
        parts.append(f"Rate {_de(cfg['lam'], 0)} je Stunde")
    if cfg["delta"] != base["delta"]:
        parts.append(f"Frist {cfg['delta']} min")
    if (cfg["p_chg"], cfg["p_cancel"]) != (base["p_chg"], base["p_cancel"]):
        lvl = event_level(cfg["p_chg"], cfg["p_cancel"])
        text = f"Änderungen {_de(cfg['p_chg'], 2)} / Stornos {_de(cfg['p_cancel'], 2)}"
        parts.append(f"Ereignisse {lvl} ({text})" if lvl else text)
    if cfg["Q"] != base["Q"]:
        parts.append(f"Kapazität {cfg['Q']}")
    kinds = (cfg["w_time"], cfg["w_addr"], cfg["w_qty"])
    if kinds != (base["w_time"], base["w_addr"], base["w_qty"]):
        names = [n for n, w in zip(("Zeitfenster", "Adresse", "Menge"), kinds) if w > 0]
        parts.append("nur " + " + ".join(names) if len(names) == 1 else "Arten " + " + ".join(names))
    if cfg["chg_delta"] != base["chg_delta"]:
        parts.append(f"Verschiebung ±{cfg['chg_delta']} min")
    if cfg["addr_radius"] != base["addr_radius"]:
        parts.append(f"Adressradius {_de(cfg['addr_radius'], 0)} km")
    return ", ".join(parts) if parts else "Basisfall"


GROUP_LABELS = {"basis": "Basisfall", "ereignisrate": "Ereignisrate", "stornoanteil": "Stornoanteil", "art": "Änderungsart",
                "kapazitaet": "Kapazität", "same-day-rate": "Same-Day-Rate", "auslastung": "Auslastung", "frist": "Frist",
                "verschiebung": "Verschiebungsgröße", "adressradius": "Adressradius", "flotte": "Flotte"}


def cell_group(cell):
    """Gruppe der Messreihe (Ein-Faktor-Sweep um den Basisfall), deutsch beschriftet."""
    return GROUP_LABELS[cell["groups"][0][0]]


# ----------------------------------------------------------------------------------------------------------------
# Zell-Zuordnung: die Regler stehen auf gemessenen Stufen, aber die Messreihe variiert je Zelle nur EINEN Parameter
# ----------------------------------------------------------------------------------------------------------------
PARAM_PRIORITY = ("rate", "morning", "events", "deadline")        # bei gleichem Abstand gewinnt die Zelle des früheren Parameters
PARAM_LABELS = {"rate": "Same-Day-Rate", "morning": "Morgenaufträge", "events": "Änderungen und Stornos", "deadline": "Frist"}


def cfg_setting(cfg):
    """(Morgenaufträge, Rate, Ereignisstufe, Frist) einer Zelle, wenn sie ganz auf den Reglerstufen liegt (und sonst dem Basisfall
    entspricht), sonst None."""
    base = C.BASE_CFG
    if any(cfg[k] != base[k] for k in ("K", "Q", "w_time", "w_addr", "w_qty", "chg_delta", "addr_radius")):
        return None
    level = event_level(cfg["p_chg"], cfg["p_cancel"])
    if cfg["n_m"] not in C.MORNING_OPTIONS or cfg["lam"] not in C.RATE_OPTIONS or level is None or cfg["delta"] not in C.DEADLINE_OPTIONS:
        return None
    return cfg["n_m"], int(cfg["lam"]), level, cfg["delta"]


def _level_index(setting):
    m, r, e, d = setting
    return dict(morning=C.MORNING_OPTIONS.index(m), rate=C.RATE_OPTIONS.index(r), events=C.EVENT_OPTIONS.index(e),
                deadline=C.DEADLINE_OPTIONS.index(d))


def assignable_cells(data):
    """Die gemessenen Zellen, die ganz auf den Reglerstufen liegen: [(Zelle, Einstellung)]. Im Basisfall 13 Zellen."""
    out = []
    for c in stab_cells(data):
        s = cfg_setting(c["cfg"])
        if s is not None:
            out.append((c, s))
    return out


def differing_params(setting_a, setting_b):
    ia, ib = _level_index(setting_a), _level_index(setting_b)
    return [p for p in PARAM_PRIORITY if ia[p] != ib[p]]


def nearest_stab_cell(data, morning, rate, events, deadline):
    """Die nächstliegende gemessene Zelle zu einer Reglerstellung. Rückgabe (Zelle, exakt, abweichende Parameter): exakt heißt, die
    Zelle hat genau diese Einstellung. Abstand = Summe der Stufenabstände; bei Gleichstand gewinnt die Zelle, deren variierter
    Parameter in PARAM_PRIORITY früher steht, dann die frühere in der Messreihe."""
    want = (int(morning), int(rate), events, int(deadline))
    iw = _level_index(want)
    base_setting = (C.MORNING_DEFAULT, C.RATE_DEFAULT, C.EVENT_DEFAULT, C.DEADLINE_DEFAULT)
    best = None
    for pos, (cell, setting) in enumerate(assignable_cells(data)):
        ic = _level_index(setting)
        dist = sum(abs(iw[p] - ic[p]) for p in PARAM_PRIORITY)
        varied = differing_params(setting, base_setting)
        rank = PARAM_PRIORITY.index(varied[0]) if varied else -1
        key = (dist, rank, pos)
        if best is None or key < best[0]:
            best = (key, cell, setting)
    _, cell, setting = best
    diff = differing_params(want, setting)
    return cell, not diff, diff


def setting_text(setting):
    m, r, e, d = setting
    return f"{m} Morgenaufträge, Rate {r} je Stunde, Ereignisse {e}, Frist {d} min"


def cell_setting_text(cell):
    s = cfg_setting(cell["cfg"])
    return setting_text(s) if s else cell_label(cell)


def assignment_note(morning, rate, events, deadline, cell, diff):
    """Hinweis zur Vergleichsspalte; leer, wenn die gemessene Zelle genau die Einstellung ist."""
    if not diff:
        return ""
    want = setting_text((morning, rate, events, deadline))
    return (f"Für Ihre Einstellung ({want}) gibt es keine eigene Messreihe: die Messreihe variiert je Zelle nur einen Parameter "
            f"ausgehend vom Basisfall. Die Vergleichsspalte zeigt die nächstliegende gemessene Zelle ({cell_setting_text(cell)}); "
            f"abweichend: {', '.join(PARAM_LABELS[p] for p in diff)}.")


# ----------------------------------------------------------------------------------------------------------------
# Annahme-Messreihe: nächstliegende Zelle (getrennte Zellen, Werte in Rohgrößen)
# ----------------------------------------------------------------------------------------------------------------
SAMEDAY_SCALES = dict(n_m=12.0, lam=3.0, delta=60.0)
SAMEDAY_BASE = dict(K=3, sigma=0.6, rev_mean=60.0, conc=0.0)


def sameday_candidates(data):
    """Annahme-Zellen, die sich nur in Morgenaufträgen, Rate und Frist vom Basisfall unterscheiden."""
    return [c for c in sameday_cells(data) if all(c["cfg"][k] == v for k, v in SAMEDAY_BASE.items())]


def nearest_sameday_cell(data, morning, rate, deadline):
    """Die nächstliegende Annahme-Zelle (Abstand: Summe |Δ| / Skala; Gleichstand: die frühere in der Messreihe). Rückgabe (Zelle,
    exakt) oder (None, False) bei Rate 0 (keine neuen Aufträge, nichts anzunehmen)."""
    if rate <= 0:
        return None, False
    best = None
    for pos, c in enumerate(sameday_candidates(data)):
        g = c["cfg"]
        dist = (abs(g["n_m"] - morning) / SAMEDAY_SCALES["n_m"] + abs(g["lam"] - rate) / SAMEDAY_SCALES["lam"]
                + abs(g["delta"] - deadline) / SAMEDAY_SCALES["delta"])
        key = (round(dist, 9), pos)
        if best is None or key < best[0]:
            best = (key, c)
    cell = best[1]
    g = cell["cfg"]
    return cell, (g["n_m"], g["lam"], g["delta"]) == (morning, rate, deadline)


def sameday_setting_text(cell):
    g = cell["cfg"]
    return f"{g['n_m']} Morgenaufträge, Rate {_de(g['lam'], 0)} je Stunde, Frist {g['delta']} min"


def sameday_note(morning, rate, deadline, cell, exact):
    if cell is None or exact:
        return ""
    return (f"Für Ihre Einstellung ({morning} Morgenaufträge, Rate {rate} je Stunde, Frist {deadline} min) gibt es keine eigene "
            f"Annahme-Messreihe; die vorgerechneten Zahlen und der Schwellenwert µ stammen aus der nächstliegenden gemessenen Zelle "
            f"({sameday_setting_text(cell)}).")


# ----------------------------------------------------------------------------------------------------------------
# Netto-Tabelle und Urteil in drei Zuständen
# ----------------------------------------------------------------------------------------------------------------
def net_row(cell, cost, measure="a"):
    """Netto-Gewinn Gewinn − Kosten × Änderungen je Politik einer Zelle bei `cost` Kosten je Änderung: die Politik mit dem höchsten
    Netto-Gewinn (Gleichstand: die erste in der Reihenfolge der Messreihe) und ihr Abstand zu S0 und R."""
    pol, names = cell["pol"], cell["names"]
    net = {p: pol[p]["pt"] - cost * pol[p][measure] for p in names}
    best = names[0]
    for p in names:
        if net[p] > net[best]:
            best = p
    return dict(cc=cost, best=best, net_best=net[best], net_over_S0=net[best] - net["S0"], net_over_R=net[best] - net["R"],
                net_R_over_S0=net["R"] - net["S0"], net=net)


def net_table(cell, costs=COST_GRID, measure="a"):
    return [net_row(cell, cc, measure) for cc in costs]


def judge(cell, cost):
    """Meldung der Hauptansicht in drei Zuständen aus der vorgerechneten Netto-Tabelle der Zelle bei `cost` Kosten je Änderung:
    'verliert' (R netto unter S0), 'lohnt' (der beste Regler gewinnt über S0 höchstens 10 % mehr als R), 'preis' (mehr als 10 %)."""
    row = net_row(cell, cost)
    gain_r, gain_best = row["net_R_over_S0"], row["net_over_S0"]
    if gain_r < 0:
        state = C.STATE_VERLIERT
    elif gain_best <= C.BEST_SHARE_LIMIT * gain_r:
        state = C.STATE_LOHNT
    else:
        state = C.STATE_PREIS
    return dict(state=state, best=row["best"], net_R_over_S0=gain_r, net_best_over_S0=gain_best, net_best_over_R=row["net_over_R"],
                cost=cost)


def policy_label(name):
    """Anzeigename einer Politik: S0 starrer Plan, R volle Neuplanung, F3 -> F_3 usw."""
    if name == "S0":
        return "S0 (starrer Plan)"
    if name == "R":
        return "R (volle Neuplanung)"
    return f"{name[0]}_{name[1:].replace('.', ',')}"


def policy_family(name):
    """Familie einer Politik: 'S0', 'R' oder der Anfangsbuchstabe ('F', 'P', 'T', 'H')."""
    return name if name in ("S0", "R") else name[0]


def break_even_cost(cell):
    """Kosten je Änderung, ab denen R gegen S0 verliert (Gewinn je Änderung der vollen Neuplanung), oder None."""
    return cell["stats"].get("gain_per_change")


# ----------------------------------------------------------------------------------------------------------------
# Kennzahlen des Kernabschnitts ②
# ----------------------------------------------------------------------------------------------------------------
def share(cell, family, frac, measure="a"):
    """Anteil am R-Gewinn bei `frac` (25, 50, 75) % der R-Änderungen, je Reglerfamilie 'P', 'F', 'T' und Maß 'a', 'b', 'c'."""
    key = f"share_{family}_{frac}" if measure == "a" else f"share_{family}_{measure}_{frac}"
    return cell["stats"].get(key)


def share_ci(cell, family, frac):
    return cell["stats_ci"].get(f"share_{family}_{frac}")


def curve_points(cell, measure="a"):
    """Punkte der Kurve Gewinn gegen Änderungen je Familie: [(Änderungen, Gewinn gegenüber S0, Name)], aufsteigend nach Änderungen;
    Familien P, F, T; dazu R als eigener Punkt und der Ursprung S0 (0, 0). Bei (b) und (c) sind die Änderungen die zusätzlichen
    gegenüber S0."""
    pol = cell["pol"]
    x0 = pol["S0"][measure]
    out = {}
    for fam in C.FAMILIES:
        pts = [(pol[p][measure] - x0, pol[p]["gain"], p) for p in cell["names"] if p[0] == fam and p != "S0"]
        out[fam] = sorted(pts)
    out["R"] = (pol["R"][measure] - x0, pol["R"]["gain"], "R")
    return out


def regime_rows(data):
    """Regime-Tabelle: je Zelle R − S0 (Mittel, SE), Änderungen (a), Gewinn je Änderung, P- und F-Anteil bei 50 %, Urteil."""
    rows = []
    for cell in stab_cells(data):
        r = cell["pol"]["R"]
        rows.append(dict(cell=cell, label=cell_label(cell), group=cell_group(cell), gain=r["gain"], se=r["gain_se"], a=r["a"],
                         per_change=cell["stats"]["gain_per_change"], share_p=share(cell, "P", 50), share_f=share(cell, "F", 50),
                         verdict=verdict(r["gain"], r["gain_se"]), n=cell["n"]))
    return rows


def count_ci_negative(data, measure, frac):
    """Zahl der Zellen, in denen F − P (bei `frac` % der R-Änderungen) im 95-%-Intervall unter 0 liegt, und Zahl der Zellen."""
    key = f"F_minus_P_{frac}" if measure == "a" else f"F_minus_P_{measure}_{frac}"
    cells = stab_cells(data)
    return sum(1 for c in cells if c["F_vs_P"][key]["ci"][1] < 0), len(cells)


def median_share(data, family, frac=50):
    """Median des Anteils am R-Gewinn über die Zellen (Angabe im Kernabschnitt: P etwa 85 %, F etwa 54 % bei 50 %)."""
    vals = sorted(v for v in (share(c, family, frac) for c in stab_cells(data)) if v is not None)
    n = len(vals)
    return vals[n // 2] if n % 2 else 0.5 * (vals[n // 2 - 1] + vals[n // 2])


def oracle_rows(data):
    """Orakel-Lücke der Stabilitäts-Zellen (nur die mit Orakel): Orakel, S0, R, bester Online, Lücke zu R."""
    rows = []
    for cell in stab_cells(data):
        o = cell.get("oracle")
        if o:
            rows.append(dict(cell=cell, label=cell_label(cell), n=o["n"], oracle=o["oracle_mean"], s0=o["s0_mean"], r=o["r_mean"],
                             best=o["best_mean"], gap_r=o["gap_r"], gap_best=o["gap_best"], gap_s0=o["gap_s0"]))
    return rows


def sameday_rows(data, group):
    """Zellen der Annahme-Messreihe einer Gruppe ('frist', 'auslastung', 'rate', ...) mit Orakel, nach der Achse aufsteigend."""
    out = []
    for c in sameday_cells(data):
        if any(g == group for g, _ in c["groups"]) and c.get("oracle"):
            out.append(c)
    key = {"frist": "delta", "auslastung": "n_m", "rate": "lam"}[group]
    return sorted(out, key=lambda c: c["cfg"][key])


def accept_bars(cell):
    """Balken der Annahme-Messreihe einer Zelle: [(Regel, Mittel, SE)] für P1, P1p, P2, P1pL, P2L, P4L und das Orakel (falls vorhanden)."""
    out = []
    for p in ("P1", "P1p", "P2", "P1pL", "P2L", "P4L"):
        out.append((p, cell["pol"][p]["mean"], cell["pol"][p]["se"]))
    if cell.get("oracle"):
        o = cell["oracle"]
        out.append(("Orakel", o["ORA"]["mean"], o["ORA"]["se"]))
    return out


def calibration_rows(cell):
    """Kalibriertabelle der Zelle: mittlerer Gewinn auf 40 getrennten Kalibrier-Seeds (100000 bis 100039) je µ für P2 und P2L; gewählt
    ist der Wert mit dem höchsten Gewinn (Gleichstand: der kleinste)."""
    mus = sorted({float(k.split("@")[1]) for k in cell["cal_mean"]})
    return [dict(mu=mu, p2=cell["cal_mean"].get(f"P2@{mu}"), p2l=cell["cal_mean"].get(f"P2L@{mu}")) for mu in mus]
