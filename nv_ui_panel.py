"""Wiederverwendbares Panel: Kennzahlen (2 x 2), Meldung in drei Zuständen, Vergleichstabelle Tag gegen Messreihe, Tagesverlauf,
Tabellen der Kernabschnitte ① und ② (Plan Abschnitt 6/8). Die Tabellen sind reine Funktionen (pandas), die Darstellung ist getrennt."""
import pandas as pd
import streamlit as st

import nv_constants as C
import nv_format as F
import nv_results as R
import nv_visualization as V

CHART_TABLE_HEIGHT = C.CHART_HEIGHT + 60


def fmt_eur(v, signed=False):
    """Gewinneinheiten mit Tausenderpunkt (Einheit „~ Euro“, rein illustrativ)."""
    text = f"{v:+,.0f}" if signed else f"{v:,.0f}"
    return text.replace(",", ".")


# ---------------------------------------------------------------------------------------------------
# Live-Tag: Kennzahlen und Meldung
# ---------------------------------------------------------------------------------------------------
def live_nets(day, cost):
    """Netto-Gewinn (Gewinn − Kosten × Änderungen fahrerseitig) je Politik des Live-Tages."""
    return {p: r["profit_total"] - cost * r["a"] for p, r in day["results"].items()}


def live_numbers(day, best, cost):
    """Kennzahlen des Live-Tages für S0, R und den empfohlenen Regler `best` bei `cost` Kosten je Änderung."""
    res, nets = day["results"], live_nets(day, cost)
    return dict(s0=res["S0"]["profit_total"], r=res["R"]["profit_total"], r_gain=res["R"]["profit_total"] - res["S0"]["profit_total"],
                r_a=res["R"]["a"], best=best, best_profit=res[best]["profit_total"], best_a=res[best]["a"],
                net_s0=nets["S0"], net_r=nets["R"], net_best=nets[best], net_best_over_s0=nets[best] - nets["S0"],
                net_r_over_s0=nets["R"] - nets["S0"])


def render_metrics(columns, day, best, cost):
    """Vier Kennzahlen im 2 x 2-Raster: Gewinn starrer Plan, Gewinn volle Neuplanung (mit Änderungen), Netto-Gewinn des empfohlenen
    Reglers bei den eingestellten Kosten, Änderungen je Regler. Live-Tag: ein einzelner Tag."""
    x = live_numbers(day, best, cost)
    columns[0].metric("Gewinn starrer Plan (S0)", fmt_eur(x["s0"]), delta="0 Änderungen per Definition", delta_color="off", delta_arrow="off",
                      help="Gewinn des Tages ohne jede Neuplanung: Ereignisse werden nur minimal repariert (Einfügen, Ersetzen an derselben "
                           "Stelle, Entfernen). S0 ändert nie andere Stopps, ihre Zahl der Änderungen (a) ist per Definition 0. Ein einzelner Tag.")
    columns[1].metric("Gewinn volle Neuplanung (R)", fmt_eur(x["r"]), delta=f"{fmt_eur(x['r_gain'], True)} gegenüber S0, {x['r_a']} Änderungen",
                      delta_color="normal",
                      help="Gewinn, wenn nach jedem Ereignis der ganze noch nicht gefahrene Plan neu optimiert wird (lokale Suche). Darunter der "
                           "Unterschied zu S0 und die Zahl der dabei umgeworfenen Stopps. Ein einzelner Tag, der stark streut.")
    columns[2].metric(f"Netto bester Regler ({R.policy_label(best)})", fmt_eur(x["net_best"]),
                      delta=f"{fmt_eur(x['net_best_over_s0'], True)} gegenüber S0 bei {F.fmt_num(cost)} Kosten je Änderung", delta_color="normal",
                      help="Netto-Gewinn = Gewinn − Kosten je Änderung × geänderte Stopps. Der Regler ist der in der Messreihe für diese Kosten "
                           "beste (höchster Netto-Gewinn), hier auf diesem Tag gerechnet. Die Kosten je Änderung sind NICHT der Reglerparameter λ: "
                           "sie gehen nur in die Bewertung ein, λ steuert die Entscheidung des Reglers.")
    columns[3].metric("Änderungen je Regler (S0 / R / bester)", f"{day['results']['S0']['a']} / {x['r_a']} / {x['best_a']}",
                      delta="geänderte Stopps je Tag, fahrerseitig", delta_color="off", delta_arrow="off",
                      help="Zahl der noch nicht gefahrenen Stopps, deren Fahrzeug oder Vorgänger sich durch die Neuplanung ändert (Maß a), "
                           "summiert über den Tag. S0 hat per Definition 0.")
    return x


def message(day, cell, cost, note=""):
    """Bedingte Meldung der Hauptansicht in drei Zuständen aus der VORGERECHNETEN Netto-Tabelle der Messreihe (nicht aus dem einen Tag).
    Rückgabe (Zustand, Text) mit Zustand 'lohnt', 'preis' oder 'verliert'."""
    j = R.judge(cell, cost)
    best = R.policy_label(j["best"])
    where = f"Messreihe, {R.cell_setting_text(cell)}, {cell['n']} Tage"
    x = live_numbers(day, j["best"], cost)
    today = (f"Auf diesem einen Tag: R netto {fmt_eur(x['net_r_over_s0'], True)} gegenüber S0, {best} netto {fmt_eur(x['net_best_over_s0'], True)}.")
    tail = f" {note}" if note else ""
    if j["state"] == C.STATE_LOHNT:
        return j["state"], (f"✅ Volle Neuplanung lohnt: bei {F.fmt_num(cost)} Kosten je Änderung bringt sie in der {where} netto "
                            f"{fmt_eur(j['net_R_over_S0'], True)} gegenüber dem starren Plan, und der beste Regler ({best}) holt mit "
                            f"{fmt_eur(j['net_best_over_S0'], True)} höchstens 10 % mehr. {today}{tail}")
    if j["state"] == C.STATE_PREIS:
        more = 100.0 * (j["net_best_over_S0"] / j["net_R_over_S0"] - 1.0) if j["net_R_over_S0"] > 0 else None
        gain = f" ({F.fmt_num(more, 0, True)} % mehr)" if more is not None else ""
        return j["state"], (f"ℹ️ Hier lohnt ein Preis je Änderung: volle Neuplanung bringt in der {where} bei {F.fmt_num(cost)} Kosten je "
                            f"Änderung netto {fmt_eur(j['net_R_over_S0'], True)}, der Regler {best} {fmt_eur(j['net_best_over_S0'], True)}{gain} "
                            f"mit weniger Änderungen. {today}{tail}")
    return j["state"], (f"⚠️ Volle Neuplanung verliert gegen den starren Plan: bei {F.fmt_num(cost)} Kosten je Änderung ist sie in der {where} "
                        f"netto {fmt_eur(j['net_R_over_S0'], True)} gegenüber S0. Der beste Regler ({best}) hält "
                        f"{fmt_eur(j['net_best_over_S0'], True)} gegenüber S0. {today}{tail}")


def render_message(day, cell, cost, note=""):
    state, text = message(day, cell, cost, note)
    {C.STATE_LOHNT: st.success, C.STATE_PREIS: st.info, C.STATE_VERLIERT: st.warning}[state](text)
    return state


def comparison_table(day, cell, best, cost):
    """Dieser Tag gegen die Messreihe (nächstliegende Zelle): Gewinn und Änderungen von R und des empfohlenen Reglers, Netto bei den
    eingestellten Kosten."""
    x = live_numbers(day, best, cost)
    p = cell["pol"]
    row = R.net_row(cell, cost)
    j = R.judge(cell, cost)
    bp = p[best]
    col_day = f"Dieser Tag (Seed {day['seed']}, 1 Tag)"
    col_ms = f"Messreihe ({cell['n']} Tage)"
    rows = [
        ("Gewinn R − S0", fmt_eur(x["r_gain"], True), F.fmt_band(p["R"]["gain"], p["R"]["gain_se"])),
        ("Änderungen von R (a)", str(x["r_a"]), F.fmt_band(p["R"]["a"], p["R"]["a_se"], signed=False)),
        (f"Gewinn {R.policy_label(best)} − S0", fmt_eur(x["best_profit"] - x["s0"], True), F.fmt_band(bp["gain"], bp["gain_se"])),
        (f"Änderungen von {R.policy_label(best)} (a)", str(x["best_a"]), F.fmt_band(bp["a"], bp["a_se"], signed=False)),
        (f"Netto R − S0 bei {F.fmt_num(cost)} Kosten je Änderung", fmt_eur(x["net_r_over_s0"], True), F.fmt_num(row["net_R_over_S0"], 1, True)),
        (f"Netto {R.policy_label(best)} − S0 bei {F.fmt_num(cost)} Kosten je Änderung", fmt_eur(x["net_best_over_s0"], True),
         F.fmt_num(j["net_best_over_S0"], 1, True)),
    ]
    return pd.DataFrame([{"Kennzahl": a, col_day: b, col_ms: c} for a, b, c in rows])


def distribution_sentence(cell):
    """Verteilung des R-Gewinns in der Messreihe (schief: Median unter Mittel)."""
    r = cell["pol"]["R"]
    q = r["gain_q"]
    return (f"Verteilung des R-Gewinns über {cell['n']} Tage: Mittel {F.fmt_num(r['gain'], 0, True)}, Median {F.fmt_num(q[1], 0, True)}, Quartile "
            f"[{F.fmt_num(q[0], 0, True)}; {F.fmt_num(q[2], 0, True)}], {F.fmt_num(100.0 * r['wins'] / cell['n'], 1)} % der Tage gewinnen "
            "(schief verteilt: ein einzelner Tag streut stark, die Meldung stützt sich deshalb auf die Messreihe).")


# ---------------------------------------------------------------------------------------------------
# Politiken-Tabelle des Live-Tages
# ---------------------------------------------------------------------------------------------------
def policy_table(day, cost):
    """Alle Politiken auf dem Live-Tag: Gewinn, Unterschied zu S0, Änderungen (a) (b) (c), Annahmen, Ausfälle, Netto."""
    res = day["results"]
    base = res["S0"]["profit_total"]
    nets = live_nets(day, cost)
    rows = []
    for p in C.POLICY_NAMES:
        r = res[p]
        rows.append({"Politik": R.policy_label(p), "Gewinn": r["profit_total"], "Gewinn − S0": r["profit_total"] - base,
                     "Änderungen (a)": r["a"], "Ansagen geändert (b)": r["b"], "Ereignisse mit Änderung (c)": r["c"],
                     "neue Aufträge angenommen": r["n_acc"], "gescheiterte Aufträge": r["n_fail"],
                     f"Netto bei {F.fmt_num(cost)} je Änderung": round(nets[p], 1)})
    return pd.DataFrame(rows)


def events_table(det):
    """Ereignisliste einer Politik mit den Änderungen je Ereignis."""
    rows = [{"Zeit": F.fmt_clock(e["t"]), "Auftrag": e["order"], "Ereignis": C.EVENT_NAMES[e["kind"]] if e["kind"] in ("new", "new_rejected") else
             ("Storno" if e["kind"] == "cancel" else ("Änderung" if e["kind"] == "change" else "ignoriert")),
             "Einzelheit": e["text"], "geänderte Stopps (a)": e["a"], "geänderte Ansagen (b)": e["b"]} for e in det["events"]]
    return pd.DataFrame(rows)


def halteliste_frame(vehicle):
    """Halteliste eines Fahrzeugs: Stopps in Fahrtreihenfolge mit Zeiten und Änderung gegenüber dem Morgenplan."""
    kinds = {"morning": "Morgenauftrag", "new": "neuer Auftrag", "changed": "geänderter Morgenauftrag"}
    rows = [{"Nr.": i, "Auftrag": s["order"], "Art": kinds[s["kind"]], "Service ab": F.fmt_clock(s["start"]),
             "Zeitfenster": f"{F.fmt_clock(s['window'][0])}–{F.fmt_clock(s['window'][1])}", "Erlös": s["rev"], "Änderung gegenüber Morgenplan": s["change"]}
            for i, s in enumerate(vehicle["stops"], 1)]
    return pd.DataFrame(rows)


def render_day(prefix, view, others):
    """Ereignis-Zeitstrahl mit Änderungen je Ereignis, darunter Touren-Zeitstrahl, Karte und Haltelisten der gezeigten Politik."""
    m = view["metrics"]
    st.caption(f"{R.policy_label(view['policy'])}: Gewinn {fmt_eur(m['profit_total'])}, {m['a']} geänderte Stopps (a), {m['n_acc']} neue Aufträge "
               f"angenommen, {m['n_fail']} gescheitert, {m['n_cancel']} Stornos und {m['n_change']} Änderungen wirksam, {m['n_ign']} Ereignisse ignoriert.")
    st.plotly_chart(V.events_figure(view, others), width="stretch", key=f"{prefix}_events")
    st.caption("Oben die Ereignisse des Tages (neu grün, Änderung orange, Storno rot, ignoriert grau; abgelehnte neue Aufträge hohl), unten die "
               "Stopps, die das jeweilige Ereignis fahrerseitig umwirft (Maß a). S0 bleibt bei 0.")
    st.plotly_chart(V.tours_figure(view), width="stretch", key=f"{prefix}_tours")
    st.caption("Touren der gezeigten Politik: dunkler Balken = Service, heller Balken = Zeitfenster des Auftrags.")
    left, right = st.columns([1, 1])
    with left:
        st.plotly_chart(V.route_map_figure(view), width="stretch", key=f"{prefix}_map")
        st.caption("Karte: Linienfarbe = Fahrzeug, Punktfarbe = Art des Auftrags.")
    with right:
        tabs = st.tabs([f"Halteliste Fahrzeug {v['vehicle']}" for v in view["vehicles"]])
        for tab, veh in zip(tabs, view["vehicles"]):
            with tab:
                st.dataframe(halteliste_frame(veh), width="stretch", hide_index=True, height=CHART_TABLE_HEIGHT)


# ---------------------------------------------------------------------------------------------------
# Kernabschnitt ②: Tabellen (vorgerechnet)
# ---------------------------------------------------------------------------------------------------
def share_table(cell):
    """Anteil am R-Gewinn bei 25 / 50 / 75 % der R-Änderungen je Familie mit 95-%-Intervall (Maß a)."""
    rows = []
    for fam in C.FAMILIES:
        row = {"Reglerfamilie": C.FAMILY_LABELS[fam]}
        for q in (25, 50, 75):
            v, ci = R.share(cell, fam, q), R.share_ci(cell, fam, q)
            row[f"bei {q} % der R-Änderungen"] = "–" if v is None else F.fmt_share(v) + (" " + F.fmt_ci([100 * c for c in ci]) if ci else "")
        rows.append(row)
    return pd.DataFrame(rows)


def net_frame(cell, cost):
    """Netto-Tabelle je Kosten je Änderung (Raster der Messreihe plus die eingestellten Kosten): bester Regler, Netto gegenüber S0, R
    gegenüber S0."""
    costs = sorted(set(R.COST_GRID) | {float(cost)})
    rows = []
    for row in R.net_table(cell, costs):
        mark = "  ◀ eingestellt" if abs(row["cc"] - cost) < 1e-9 else ""
        rows.append({"Kosten je Änderung": F.fmt_num(row["cc"], 1) + mark, "bester Regler": R.policy_label(row["best"]),
                     "Netto bester Regler − S0": F.fmt_num(row["net_over_S0"], 1, True), "Netto R − S0": F.fmt_num(row["net_R_over_S0"], 1, True),
                     "bester Regler − R": F.fmt_num(row["net_over_R"], 1, True)})
    return pd.DataFrame(rows)


def regime_frame(data, highlight_cell=None):
    """Regime-Tabelle: alle 28 Zellen mit R − S0 (Mittel ± SE), Änderungen, Gewinn je Änderung, Anteile und Urteil."""
    rows = []
    for r in R.regime_rows(data):
        hl = highlight_cell is not None and r["cell"] is highlight_cell
        rows.append({"Gruppe": r["group"], "Zelle": ("▶ " if hl else "") + r["label"], "Tage": r["n"],
                     "R − S0": F.fmt_band(r["gain"], r["se"]), "Änderungen von R": F.fmt_num(r["a"]), "Gewinn je Änderung": F.fmt_num(r["per_change"] or 0.0),
                     "P-Anteil bei 50 %": F.fmt_share(r["share_p"]), "F-Anteil bei 50 %": F.fmt_share(r["share_f"]), "Urteil": R.VERDICT_TEXT[r["verdict"]]})
    return pd.DataFrame(rows)


def regime_rows_for_chart(data, highlight_cell):
    rows = R.regime_rows(data)
    for r in rows:
        r["highlight"] = r["cell"] is highlight_cell
    return rows


def event_cost_frame(cell):
    """Kosten der Änderungen und Stornos selbst: Verlust gegenüber demselben Tag ohne Ereignisse mit S0 und R, Gewinn von R mit und ohne."""
    e = cell["event_cost"]
    rows = [
        ("Verlust von S0 gegenüber dem Tag ohne Ereignisse", F.fmt_band(e["S0"]["mean"], e["S0"]["se"], 0, False)),
        ("Verlust von R gegenüber dem Tag ohne Ereignisse", F.fmt_band(e["R"]["mean"], e["R"]["se"], 0, False)),
        ("R holt davon zurück", F.fmt_band(e["S0"]["mean"] - e["R"]["mean"], e["gainR_extra"]["se"], 0)),
        ("Gewinn von R − S0 ohne jedes Änderungsereignis", F.fmt_band(e["gainR_control"]["mean"], e["gainR_control"]["se"], 0)),
        ("Gewinn von R − S0 mit Änderungen und Stornos", F.fmt_band(e["gainR_event"]["mean"], e["gainR_event"]["se"], 0)),
        ("zusätzlicher Gewinn von R durch die Ereignisse", F.fmt_band(e["gainR_extra"]["mean"], e["gainR_extra"]["se"], 0)),
    ]
    return pd.DataFrame([{"Kennzahl": a, "Mittel ± Standardfehler": b} for a, b in rows])


def event_kind_frame(data):
    """Kosten der Ereignisse nach Ereignisart und Rate (alle Zellen mit Ereignissen und Kontrolle)."""
    rows = []
    for cell in R.stab_cells(data):
        e = cell.get("event_cost")
        if not e:
            continue
        rows.append({"Zelle": R.cell_label(cell), "Verlust S0": F.fmt_band(e["S0"]["mean"], e["S0"]["se"], 0, False),
                     "Verlust R": F.fmt_band(e["R"]["mean"], e["R"]["se"], 0, False),
                     "zusätzlicher R-Gewinn": F.fmt_band(e["gainR_extra"]["mean"], e["gainR_extra"]["se"], 0)})
    return pd.DataFrame(rows)


def measure_frame(data, cell):
    """Aussage unter den drei Stabilitätsmaßen: Anteile von P und F bei 50 %, F − P bei 25/50 % und in wie vielen Zellen belastbar."""
    rows = []
    for m in ("a", "b", "c"):
        f25, f50 = (cell["F_vs_P"][f"F_minus_P_{q}" if m == "a" else f"F_minus_P_{m}_{q}"] for q in (25, 50))
        n25, total = R.count_ci_negative(data, m, 25)
        n50, _ = R.count_ci_negative(data, m, 50)
        rows.append({"Maß": R.MEASURES[m], "P-Anteil bei 50 %": F.fmt_share(R.share(cell, "P", 50, m)), "F-Anteil bei 50 %": F.fmt_share(R.share(cell, "F", 50, m)),
                     "F − P bei 25 % (95 %)": f"{F.fmt_num(f25['mean'], 1, True)} {F.fmt_ci(f25['ci'])}",
                     "F − P bei 50 % (95 %)": f"{F.fmt_num(f50['mean'], 1, True)} {F.fmt_ci(f50['ci'])}",
                     "Zellen mit F − P < 0 (25 % / 50 %)": f"{n25} / {n50} von {total}"})
    return pd.DataFrame(rows)


def horizon_frame(data):
    """Zusatzlauf zeitbasierter Horizont H (7 Zellen): Anteil am R-Gewinn bei 25/50 % und H − P."""
    rows = []
    for c in R.h_cells(data):
        d = c["H_vs_P"]
        rows.append({"Zelle": R.cell_label(c), "H-Anteil bei 25 %": F.fmt_share(c["stats"].get("share_H_25")), "H-Anteil bei 50 %": F.fmt_share(c["stats"].get("share_H_50")),
                     "H − P bei 25 % (95 %)": f"{F.fmt_num(d['H_minus_P_25']['mean'], 1, True)} {F.fmt_ci(d['H_minus_P_25']['ci'])}",
                     "H − P bei 50 % (95 %)": f"{F.fmt_num(d['H_minus_P_50']['mean'], 1, True)} {F.fmt_ci(d['H_minus_P_50']['ci'])}"})
    return pd.DataFrame(rows)


def h_points_frame(cell_h):
    """Basiszelle des Zusatzlaufs: Gewinn und Änderungen je Horizont."""
    rows = [{"Horizont": f"H_{p[1:]} min", "Gewinn gegenüber S0": F.fmt_band(v["gain"], v["gain_se"]), "Änderungen (a)": F.fmt_num(v["a"])}
            for p, v in cell_h["pol"].items() if p.startswith("H")]
    return pd.DataFrame(rows)


def oracle_frame(data):
    """Orakel-Lücke der Stabilitäts-Zellen mit Orakel (10 Instanzen je Zelle): Orakel, S0, R, bester Online, Lücke zu R."""
    rows = []
    for r in R.oracle_rows(data):
        rows.append({"Zelle": r["label"], "Instanzen": r["n"], "Orakel": F.fmt_num(r["oracle"], 0), "S0": F.fmt_num(r["s0"], 0), "R": F.fmt_num(r["r"], 0),
                     "bester Online-Regler je Instanz": F.fmt_num(r["best"], 0), "Lücke zu R": F.fmt_band(r["gap_r"][0], r["gap_r"][1], 0, False),
                     "Lücke in % des Orakels": F.fmt_share(r["gap_r"][0] / r["oracle"])})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------------------------------
# Kernabschnitt ①: Annahme
# ---------------------------------------------------------------------------------------------------
def accept_live_frame(res):
    rows = [{"Regel": f"{n} ({C.ACCEPT_LABELS[n]})", "Gewinn gegenüber „nie annehmen“": res["rules"][n]["gain"], "angenommen": res["rules"][n]["n_acc"],
             "Fahrzeit (min)": res["rules"][n]["drive"], "Erlös": res["rules"][n]["rev"]} for n in ("P0",) + C.ACCEPT_ORDER]
    return pd.DataFrame(rows)


def accept_measured_frame(cell):
    """Annahme-Messreihe einer Zelle: Gewinn gegenüber „nie annehmen“ (Mittel ± SE), Median und Quartile, angenommene Aufträge."""
    rows = []
    for p in ("P1", "P1p", "P2", "P1L", "P1pL", "P2L", "P4", "P4L"):
        v = cell["pol"][p]
        rows.append({"Regel": f"{p}" + (f" ({C.ACCEPT_LABELS[p]})" if p in C.ACCEPT_LABELS else ""), "Gewinn gegenüber „nie annehmen“": F.fmt_band(v["mean"], v["se"], 0, False),
                     "Median [Q1; Q3]": f"{F.fmt_num(v['q'][1], 0)} [{F.fmt_num(v['q'][0], 0)}; {F.fmt_num(v['q'][2], 0)}]", "angenommen": F.fmt_num(v["acc"])})
    return pd.DataFrame(rows)


def accept_pairs_frame(cell):
    """Gepaarte Vergleiche der Annahme-Messreihe (Gewinnunterschied Mittel ± SE, Siege / Niederlagen)."""
    labels = {"P1p-P1": "Erlös ≥ Fahrt statt alles Machbare (P1p − P1)", "P2-P1p": "Schattenpreis-Schwelle (P2 − P1p)",
              "P2v-P1p": "reine Erlös-Schwelle à la Littlewood (P2v − P1p)", "P2m-P1p": "Nettomarge-Schwelle (P2m − P1p)",
              "P1pL-P1p": "Neuoptimieren (P1pL − P1p)", "P2L-P1pL": "Schwelle auf Neuoptimierung (P2L − P1pL)", "P4L-P2L": "Rollout (P4L − P2L)"}
    rows = []
    for k, lab in labels.items():
        v = cell["pairs"].get(k)
        if v:
            rows.append({"Vergleich": lab, "Unterschied": F.fmt_band(v["mean"], v["se"], 0), "Siege / Niederlagen / Gleichstand": f"{v['wins']} / {v['losses']} / {v['ties']}"})
    return pd.DataFrame(rows)


def calibration_frame(cell):
    """Kalibriertabelle: mittlerer Gewinn je Schwellenparameter µ (getrennte Kalibrier-Seeds); der gewählte Wert ist markiert."""
    par = cell["par"]
    rows = []
    for r in R.calibration_rows(cell):
        rows.append({"µ": F.fmt_num(r["mu"], 2) + ("  ◀ P2" if abs(r["mu"] - par["mu"]) < 1e-9 else "") + ("  ◀ P2L" if abs(r["mu"] - par["mu_L"]) < 1e-9 else ""),
                     "Gewinn P2 (Kalibrierung)": F.fmt_num(r["p2"], 1), "Gewinn P2L (Kalibrierung)": F.fmt_num(r["p2l"], 1)})
    return pd.DataFrame(rows)


def oracle_sameday_frame(data, group):
    """Rest-Lücke zum Rückblick-Orakel der Annahme nach Frist oder Auslastung (nur vorgerechnet, 10 bis 16 Instanzen je Zelle)."""
    rows = []
    for c in R.sameday_rows(data, group):
        o = c["oracle"]
        g = c["cfg"]
        rows.append({("Frist" if group == "frist" else "Morgenaufträge"): f"{g['delta']} min" if group == "frist" else g["n_m"], "Instanzen": o["n"],
                     "Orakel": F.fmt_band(o["ORA"]["mean"], o["ORA"]["se"], 0, False), "bester Online-Regler je Instanz": F.fmt_num(o["best_online_gain"]["mean"], 0),
                     "Lücke": F.fmt_band(o["gap_best_online"]["mean"], o["gap_best_online"]["se"], 0, False),
                     "Anteil des Orakels": F.fmt_share(o["best_online_gain"]["mean"] / o["ORA"]["mean"])})
    return pd.DataFrame(rows)


def cross_frame(data):
    """Fehlkalibrierung: die in der Basiszelle kalibrierte Schwelle in anderen Zellen (P2 − P1p) gegenüber der dort kalibrierten."""
    calibrated = {tuple(c["cfg"][k] for k in ("n_m", "lam", "delta")): c for c in R.sameday_cells(data)}
    rows = []
    for x in data["sameday"]["cross"]:
        g = x["cfg"]
        own = calibrated.get((g["n_m"], g["lam"], g["delta"]))
        if own is None or "P2-P1p" not in x["pairs"] or (g["n_m"], g["lam"], g["delta"]) == (40, 6.0, 120):
            continue
        v, o = x["pairs"]["P2-P1p"], own["pairs"]["P2-P1p"]
        rows.append({"Zelle": R.sameday_setting_text(x), "P2 − P1p mit µ der Basiszelle": F.fmt_band(v["mean"], v["se"], 0),
                     "P2 − P1p mit eigener Kalibrierung": F.fmt_band(o["mean"], o["se"], 0)})
    return pd.DataFrame(rows)
