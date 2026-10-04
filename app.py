"""
Nahverkehr: Same-Day-Aufträge, Änderungen und der Preis der Planänderung - interaktive Fall-Demo
Sebastian Hanisch - Operations Research und Machine Learning

Erweiterung der Tourenplanungs-Demo (vrp_demo): Im Nahverkehr steht der Plan am Morgen, aber der Tag hält sich nicht daran - neue Aufträge kommen
herein, Aufträge ändern sich oder werden storniert. Live: EIN Tag (Morgenplan mit OR-Tools, Ereignisstrom), alle Politiken (starrer Plan S0, volle
Neuplanung R, Einfrierhorizont F, Änderungsstrafe P, periodisch T) laufen über denselben Tag. Vorgerechnet: die Messreihen über 200 bzw. 60 Tage
(data/nv_results.json), die die Aussage über den Preis der Planänderung und die Annahme neuer Aufträge tragen.

Lauffähig mit: streamlit run app.py
"""
import streamlit as st

import nv_constants as C
import nv_format as F
import nv_live as LV
import nv_model
import nv_results as R
import nv_ui_panel as UI
import nv_visualization as V
from nv_pdf_export import generate_nv_pdf
from nv_presets import (SETTING_SPECS, apply_preset, bounds, init_session_state_defaults, load_permalink_settings, randomize_seed,
                        sync_query_params)

st.set_page_config(page_title="Nahverkehr – Sebastian Hanisch", layout="wide")

nv_model.MORNING_DISK_CACHE = None            # Streamlit Cloud: nie auf die Festplatte schreiben (Zwischenspeicher: nv_model im Speicher, st.cache_data)
SCENARIO_KEYS = list(SETTING_SPECS)
CFG = nv_model.Cfg()
DATA = R.load_results()
TIMINGS = DATA["_timings"]
# Zahlen der Texte: alle aus der vorgerechneten Messreihe (kein Text-Zahlen-Widerspruch möglich)
_BASE = R.find_cell(DATA)
_NO_EVENTS = R.find_cell(DATA, p_chg=0.0, p_cancel=0.0)
_ONLY_CANCEL = R.find_cell(DATA, p_chg=0.0, p_cancel=0.33)
_RATE0 = R.find_cell(DATA, lam=0.0)
_B_CELLS = tuple(R.count_ci_negative(DATA, "b", q)[0] for q in (25, 50))
_N_CELLS = len(R.stab_cells(DATA))
_R_PCT = 100.0 * _BASE["pol"]["R"]["gain"] / _BASE["pol"]["S0"]["pt"]


@st.cache_data(show_spinner=False, max_entries=C.CACHE_ENTRIES)
def _day(morning, rate, events, deadline, seed):
    """Live-Tag, alle Politiken (Sekunden), je Einstellung zwischengespeichert. Der Aufruf geht über das Modul, damit die Tests die Rechnung
    ersetzen können."""
    return LV.solve_day(morning, rate, events, deadline, seed)


@st.cache_data(show_spinner=False, max_entries=C.CACHE_ENTRIES * 3)
def _detail(morning, rate, events, deadline, seed, policy):
    """Tagesverlauf einer Politik (mit Protokoll), zwischengespeichert."""
    return LV.day_detail(morning, rate, events, deadline, seed, policy)


@st.cache_data(show_spinner=False, max_entries=C.CACHE_ENTRIES)
def _accept(morning, rate, deadline, seed, mu, mu_l):
    """Annahmeregeln auf demselben Tag ohne Änderungsereignisse, zwischengespeichert."""
    return LV.solve_accept(morning, rate, deadline, seed, mu, mu_l)


st.title("📦 Nahverkehr: Same-Day-Aufträge, Änderungen und der Preis der Planänderung")
st.markdown(
    """
Im Nahverkehr steht der Plan am Morgen, aber der Tag hält sich nicht daran: **neue Aufträge** (Same-Day-Aufträge) kommen herein, teils wenn die Touren schon laufen, und **Aufträge ändern sich**
(Zeitfenster, Adresse, Menge) oder werden storniert. Die Demo fragt, **wie viel Neuplanung sich lohnt, wenn jede Planänderung etwas kostet** (Fahrer informieren, Kunden neue Zeiten ansagen) und welche
neuen Aufträge man überhaupt annimmt – live auf einem Tag und vorgerechnet über 200 Tage. Eine **Erweiterung der Tourenplanungs-Demo** (`vrp_demo`); das Muster „starrer Plan gegen reaktives Nachplanen“
kennen auch `fahrzeugflotte-demo`, `robuste-kaiplatz-demo`, `blockzuweisung-demo` und `hofrobust-demo` – neu ist hier der **Preis der Änderung**, der die Stabilität des Plans bepreist und misst; die Annahme
ohne Geometrie zeigt `revenue-management-demo`. Wie das Modell funktioniert, steht im Expander „Wie funktioniert diese Demo?“ weiter unten, die formale Beschreibung im Expander „📐 Mathematische Formulierung“.
"""
)

st.caption("🎯 Schnellstart – ein Beispielszenario laden:")
preset_names = list(C.PRESETS)
for row in (preset_names[:3], preset_names[3:]):
    cols = st.columns(3)
    for col, name in zip(cols, row):
        with col:
            st.button(name, width="stretch", on_click=apply_preset, args=(name,), help=C.PRESET_HELP[name])

st.caption("🔗 Die Adresszeile oben spiegelt Ihre aktuelle Konfiguration wider – einfach kopieren, um ein Szenario zu teilen.")

load_permalink_settings()
init_session_state_defaults()

with st.sidebar:
    st.header("⚙️ Einstellungen")
    st.markdown("**Der Tag**")
    morning = st.select_slider("Morgenaufträge", options=list(C.MORNING_OPTIONS), key="morning_slider",
                               help="Aufträge des Morgenplans (Auslastung des Plans 0,44 / 0,61 / 0,70 / 0,75). Die Stufen sind die gemessenen Zellen der Messreihe.")
    rate = st.select_slider("Same-Day-Rate", options=list(C.RATE_OPTIONS), key="rate_slider", format_func=lambda v: f"{v} je Stunde",
                            help="Neue Aufträge je Stunde im Fenster der ersten 300 Minuten. Bei 0 gibt es nur Änderungen und Stornos von Morgenaufträgen: "
                                 "dort zeigt sich, dass der Nutzen der Neuplanung nicht von den Änderungen kommt.")
    events = st.select_slider("Änderungen und Stornos", options=list(C.EVENT_OPTIONS), key="events_slider",
                              help="Anteil der Aufträge, die im Tagesverlauf eine Änderung oder einen Storno erhalten: keine (0 / 0), wenige (10 % / 3 %), "
                                   "mittel (25 % / 8 %), viele (50 % / 16 %), sehr viele (80 % / 20 %).")
    deadline = st.select_slider("Frist", options=list(C.DEADLINE_OPTIONS), key="deadline_slider", format_func=lambda v: f"{v} min",
                                help="Zeit von Eingang bis Lieferung der neuen Aufträge. Je knapper, desto weniger lässt sich einschieben.")
    st.markdown("**Bewertung**")
    cost = st.slider("Kosten je Planänderung", *bounds("change_cost_slider"), key="change_cost_slider", step=C.COST_STEP,
                     help="Was eine geänderte Zeile im Plan kostet (Fahrer informieren, Kunden neue Zeiten ansagen), in Gewinneinheiten. Verschiebt nur die "
                          "Netto-Rechnung und den empfohlenen Regler, nicht die Simulation. NICHT der Reglerparameter λ der Änderungsstrafe (siehe „Wie funktioniert diese Demo?“).")
    seed = st.number_input("Seed", *bounds("seed_input"), key="seed_input", step=1,
                           help="Nummer des gezeigten Tages. Die Kennzahlen der Messreihe stehen auf den Seeds 0 bis 199 (Stabilität) bzw. 0 bis 59 (Annahme), "
                                "die Beispielszenarien zeigen Tage außerhalb.")
    st.button("🎲 Neuer Tag", width="stretch", on_click=randomize_seed, help="Würfelt einen neuen Seed.")

sync_query_params({key: st.session_state[key] for key in SCENARIO_KEYS})
morning, rate, deadline, seed, cost = int(morning), int(rate), int(deadline), int(seed), float(cost)

cell, exact, diff = R.nearest_stab_cell(DATA, morning, rate, events, deadline)
note = R.assignment_note(morning, rate, events, deadline, cell, diff)
judged = R.judge(cell, cost)
best = judged["best"]

est = sum(TIMINGS["morgenplan_s"][str(morning)]) / len(TIMINGS["morgenplan_s"][str(morning)])
with st.spinner(f"Rechne den Tag: Morgenplan mit {morning} Aufträgen (OR-Tools) und alle Politiken … (gemessen etwa {est:.1f} s, danach je Einstellung gespeichert)"):
    day = _day(morning, rate, events, deadline, seed)

# ---------------------------------------------------------------------------------------------------
# Hauptansicht (Kernabschnitt ①/② live: ein Tag)
# ---------------------------------------------------------------------------------------------------
st.markdown("## 📦 Wie viel Neuplanen lohnt, wenn jede Planänderung etwas kostet?")
st.caption(f"Live-Tag (ein Tag, ein Ereignisstrom): Seed {day['seed']}, {day['n_morning']} Morgenaufträge, {day['n_arrivals']} neue Aufträge, {day['n_events']} Änderungen und Stornos "
           f"(Änderungen und Stornos: {events}), Frist {deadline} min, Plan-Auslastung {F.fmt_num(day['plan_util'], 2)}. Alle Politiken gerechnet in {F.fmt_num(day['seconds'])} s "
           "(davon der Morgenplan " + F.fmt_num(day["seconds_morning"]) + " s). Ein einzelner Tag – die vorgerechnete Messreihe unten trägt die Aussage.")

metric_rows = [st.columns(2), st.columns(2)]
UI.render_metrics(metric_rows[0] + metric_rows[1], day, best, cost)
msg_state = UI.render_message(day, cell, cost, note)
_, msg_text = UI.message(day, cell, cost, note)

st.markdown("**Dieser Tag und die Messreihe nebeneinander**")
st.dataframe(UI.comparison_table(day, cell, best, cost), width="stretch", hide_index=True)
st.caption(UI.distribution_sentence(cell) + (" " + note if note else ""))

VIEW_OPTIONS = ["S0 (starrer Plan)", "R (volle Neuplanung)", "bester Regler"]
view_label = st.radio("Tagesverlauf anzeigen für", VIEW_OPTIONS, index=2, horizontal=True, key="view_select",
                      help="Reine Anzeigewahl im Ergebnisbereich: alle Politiken sind auf diesem Tag schon gerechnet, hier wählen Sie nur, welchen Tagesverlauf Sie sehen. "
                           "Der beste Regler ist der in der Messreihe für die eingestellten Kosten je Änderung beste.")
view_policy = {VIEW_OPTIONS[0]: "S0", VIEW_OPTIONS[1]: "R", VIEW_OPTIONS[2]: best}[view_label]
st.markdown("#### 🗺️ Tagesverlauf: Ereignisse, Änderungen, Touren und Karte")
_names = list(dict.fromkeys(("S0", "R", best)))
details = {p: _detail(morning, rate, events, deadline, seed, p) for p in dict.fromkeys(_names + [view_policy])}
compare = [(R.policy_label(p) if p not in ("S0", "R") else p, {"S0": C.COLOR_S0, "R": C.COLOR_R}.get(p, C.COLOR_BEST), details[p]) for p in _names]
UI.render_day("main", details[view_policy], compare)

pdf_slot = st.container()

st.markdown("---")

# ---------------------------------------------------------------------------------------------------
# Kernabschnitt ② (vorgerechnet): Stabilität
# ---------------------------------------------------------------------------------------------------
st.markdown("### 📐 Was die Messreihe über 200 Tage zeigt")
st.markdown(
    f"""
Kernfrage: Wie viel vom Plan sollte man umwerfen, wenn jede Änderung etwas kostet? Die Antwort steht auf **{cell['n']} gepaarten Tagen je Zelle** (alle Politiken auf denselben Tagen und Ereignisströmen),
vorgerechnet und **nie live** gerechnet: etwa {TIMINGS['messreihe_wanduhr_min']} Minuten auf {TIMINGS['messreihe_kerne']} Kernen. Gezeigt wird die gemessene Zelle, die Ihrer Einstellung am nächsten liegt:
**{R.cell_setting_text(cell)}**. Mittel ± Standardfehler; ein Vorzeichen gilt nur ab 2 Standardfehlern.
"""
)
if note:
    st.info(note)

st.markdown("**1 · Kurve Gewinn gegen Änderungen** – wie viel des Gewinns der vollen Neuplanung holt jeder Regler mit wie vielen Änderungen?")
measure = st.selectbox("Stabilitätsmaß", list(R.MEASURES), key="measure_select", format_func=lambda m: R.MEASURES[m],
                       help="Reine Anzeigewahl: welches Maß die Kurve auf der Achse „Änderungen“ zählt – fahrerseitig (a, Hauptmaß, gestrichen ist der Ereignisauftrag selbst), "
                            "kundenseitig (b, angesagte Ankunftszeiten, die sich um mehr als 15 Minuten ändern) oder Neuplanungsereignisse mit mindestens einer Änderung (c).")
c1, c2 = st.columns(2)
with c1:
    st.plotly_chart(V.curve_figure(cell, measure), width="stretch", key="core_curve")
with c2:
    st.plotly_chart(V.share_figure(cell, measure), width="stretch", key="core_share")
st.dataframe(UI.share_table(cell), width="stretch", hide_index=True)
_rp = cell["pol"]["R"]
st.caption(f"Volle Neuplanung R dreht in dieser Zelle {F.fmt_num(_rp['a'])} Stopps je Tag um und bringt {F.fmt_band(_rp['gain'], _rp['gain_se'])} gegenüber dem starren Plan, also "
           f"{F.fmt_num(cell['stats']['gain_per_change'] or 0.0)} Gewinn je Änderung. Anteil am R-Gewinn bei 25 / 50 / 75 % der R-Änderungen (lineare Interpolation der Reglerfamilie, in Klammern das 95-%-Intervall): "
           f"die Änderungsstrafe holt {F.fmt_share(R.share(cell, 'P', 25))} / {F.fmt_share(R.share(cell, 'P', 50))} / {F.fmt_share(R.share(cell, 'P', 75))}, das Einfrieren nach Stopps "
           f"{F.fmt_share(R.share(cell, 'F', 25))} / {F.fmt_share(R.share(cell, 'F', 50))} / {F.fmt_share(R.share(cell, 'F', 75))}. Die Kurve der Strafe steigt steil und knickt früh ab, Einfrieren und periodische "
           "Neuplanung steigen fast linear: die Stellschraube ist der Preis der Änderung, nicht der Horizont.")

st.markdown("**2 · Wie viel Neuplanen lohnt bei Kosten je Änderung** – Netto-Tabelle (Gewinn minus Kosten × Änderungen)")
st.plotly_chart(V.net_figure(cell, cost), width="stretch", key="core_net")
st.dataframe(UI.net_frame(cell, cost), width="stretch", hide_index=True)
_be = R.break_even_cost(cell)
st.caption("Bester Regler = die Politik mit dem höchsten Netto-Gewinn bei diesen Kosten (im Stichprobendurchschnitt gewählt, also leicht optimistisch). "
           + (f"**Ab {F.fmt_num(_be)} Kosten je Änderung verliert die volle Neuplanung gegen den starren Plan.** " if _be else "")
           + "Die **Kosten je Änderung** gehen nur in diese Bewertung ein (nachträglich angesetzt, nicht in der Entscheidung gemessen); der **Reglerparameter λ** "
             "der Strafe P_λ steuert dagegen, wie viel Fahrzeitersparnis ein Zug mindestens bringen muss, je zusätzlich geändertem Stopp. Beide sind nicht identisch: "
             "die Tabelle zeigt zu jedem Preis den besten Regler.")

st.markdown("**3 · Regime** – wo ist die Neuplanung viel, wo wenig wert? (alle gemessenen Zellen, je 200 Tage)")
st.plotly_chart(V.regime_figure(UI.regime_rows_for_chart(DATA, cell)), width="stretch", key="core_regime")
st.dataframe(UI.regime_frame(DATA, cell), width="stretch", hide_index=True)
st.caption("Urteil in drei Zuständen: der Gewinn der vollen Neuplanung gegenüber dem starren Plan ist belastbar positiv, belastbar negativ oder nicht von 0 zu unterscheiden (Mittel mehr als 2 Standardfehler von 0). "
           "Ein Regime-Widerspruch wie in `hofrobust-demo` (Sieger hängt von der Störungsart ab) tritt nicht auf: in allen Zellen ist Neuplanen besser als Nichtstun, nur die Größenordnung ändert sich. "
           f"Der Treiber sind neue Aufträge, nicht Änderungen: bei Rate 0 bringt R nur {F.fmt_num(_RATE0['pol']['R']['gain'], 0, True)}, ohne jedes Änderungsereignis schon {F.fmt_num(_NO_EVENTS['pol']['R']['gain'], 0, True)}.")

st.markdown("**4 · Kosten der Änderungen selbst** – was kosten Änderungen und Stornos, und wie viel holt Neuplanung zurück?")
_ec_cell = cell if cell.get("event_cost") else R.find_cell(DATA)
if not cell.get("event_cost"):
    st.info("Für die nächstliegende Zelle wurde keine Kontrolle ohne Ereignisse gerechnet; die Tabelle zeigt deshalb den Basisfall.")
st.dataframe(UI.event_cost_frame(_ec_cell), width="stretch", hide_index=True)
st.caption("Verlust = Gewinn desselben Tages ohne Ereignisse minus Gewinn mit Ereignissen (gepaart). Stornos kosten großenteils den Erlös des Auftrags (60 je Morgenauftrag) – das sagt nichts über die Wirkung der Neuplanung; "
           f"Neuplanung hilft bei Änderungen, nicht bei Stornos (reine Stornos: {F.fmt_band(_ONLY_CANCEL['event_cost']['gainR_extra']['mean'], _ONLY_CANCEL['event_cost']['gainR_extra']['se'], 0)}).")

st.markdown("**5 · Hängt die Aussage am Stabilitätsmaß?**")
st.plotly_chart(V.measure_figure(cell), width="stretch", key="core_measure")
st.dataframe(UI.measure_frame(DATA, cell), width="stretch", hide_index=True)
st.caption(f"Die Aussage „Strafe schlägt Einfrieren“ gilt unter allen drei Maßen, ist aber unter (b) nur in {_B_CELLS[0]} / {_B_CELLS[1]} von {_N_CELLS} Zellen belastbar (bei 25 / 50 % der R-Änderungen). Da die Strafe das Maß (a) selbst optimiert, ist ihr Vorsprung dort teilweise per Konstruktion; "
           "er bleibt unter (c) und in geringerem Maß unter (b) bestehen.")

st.markdown("**6 · Zeitbasierter Horizont H** – hängt „Einfrieren ist schlechter“ an der Stopp-Zahl-Definition?")
st.dataframe(UI.horizon_frame(DATA), width="stretch", hide_index=True)
st.caption(f"Zusatzlauf mit dem Einfrierhorizont in Minuten statt in Stopps ({len(R.h_cells(DATA))} Zellen, dieselben Instanzen): in allen {len(R.h_cells(DATA))} Zellen liegt der Vorsprung der Strafe im 95-%-Intervall über 0. Ein kurzer Horizont (30 min) "
           "lässt fast alle Änderungen zu, erst große Horizonte sparen Änderungen – dann aber überproportional Gewinn.")

# ---------------------------------------------------------------------------------------------------
# Kernabschnitt ① (Annahme): live ohne Änderungsereignisse + vorgerechnet
# ---------------------------------------------------------------------------------------------------
st.markdown("### 📐 Welche Aufträge annehmen?")
st.markdown(
    """
Neue Aufträge werden **sofort und verbindlich** angenommen oder abgelehnt (abgelehnt = Erlös entfällt). Fünf Regeln: **P1** nimmt alles Machbare an, **P1p** nur, wenn der Erlös die zusätzliche Fahrt deckt, **P2** rechnet
zusätzlich einen **Schattenpreis der Zeit** (Schwelle µ, aus der Route und der noch erwarteten Ankunftsrate), dazu je mit **Neuoptimierung** (L) nach jeder Annahme. Die Messreihe der Annahme kennt keine Änderungsereignisse:
live laufen die Regeln deshalb auf **demselben Tag ohne Änderungen und Stornos**.
"""
)
sd_cell, sd_exact = R.nearest_sameday_cell(DATA, morning, rate, deadline)
if sd_cell is None:
    st.info("Bei Rate 0 gibt es keine neuen Aufträge und damit nichts anzunehmen: die Annahmeregeln sind alle gleich dem Morgenplan. Die Messreihe der Annahme kennt keine Rate 0. "
            "Bitte eine Rate von 2 oder mehr je Stunde wählen.")
else:
    sd_note = R.sameday_note(morning, rate, deadline, sd_cell, sd_exact)
    par = sd_cell["par"]
    acc = _accept(morning, rate, deadline, seed, float(par["mu"]), float(par["mu_L"]))
    st.markdown(f"**Live: dieser Tag ohne Änderungen** (Seed {seed}, {acc['n_arrivals']} neue Aufträge, µ = {F.fmt_num(par['mu'], 2)} für P2 und µ = {F.fmt_num(par['mu_L'], 2)} für P2L)")
    a1, a2 = st.columns([1, 1])
    with a1:
        st.plotly_chart(V.accept_live_figure(acc), width="stretch", key="core_accept_live")
    with a2:
        st.dataframe(UI.accept_live_frame(acc), width="stretch", hide_index=True)
    st.caption("Ein einzelner Tag: die Reihenfolge der Regeln kann hier von der Messreihe abweichen. µ stammt aus der Kalibriertabelle der nächstliegenden gemessenen Zelle "
               "(kalibriert auf 40 getrennten Seeds). " + sd_note)
    st.markdown(f"**Vorgerechnet: Messreihe über {sd_cell['n']} Tage** ({R.sameday_setting_text(sd_cell)}; das Orakel nur auf {sd_cell['oracle']['n'] if sd_cell.get('oracle') else 0} Instanzen)")
    b1, b2 = st.columns([1, 1])
    with b1:
        st.plotly_chart(V.accept_measured_figure(R.accept_bars(sd_cell)), width="stretch", key="core_accept_measured")
    with b2:
        st.dataframe(UI.accept_measured_frame(sd_cell), width="stretch", hide_index=True)
    st.dataframe(UI.accept_pairs_frame(sd_cell), width="stretch", hide_index=True)
    st.caption("Gewinn gegenüber „nie annehmen“, Mittel ± Standardfehler, gepaart über die Instanzen. Die reine Erlös-Schwelle im Sinn von Littlewood (P2v) überträgt sich nicht auf das Straßennetz; "
               "erst ein Zeit-Schattenpreis, der die Route mitrechnet, wirkt – und das nur bei hoher Ankunftsrate und hohen Erlösen. Neuoptimieren (L) bringt oft mehr als die Schwelle.")
    with st.container():
        st.markdown(f"**Kalibriertabelle für µ und Fehlkalibrierung.** Je gemessener Zelle wurde µ auf 40 **getrennten Kalibrier-Seeds** (100000 bis 100039) aus einem Gitter gewählt und nie auf den Auswertungsseeds. Hier die Zelle {R.sameday_setting_text(sd_cell)}:")
        st.dataframe(UI.calibration_frame(sd_cell), width="stretch", hide_index=True)
        st.markdown("**Fehlkalibrierung:** dieselbe Schwelle der Basiszelle in andere Regime übertragen (ohne Neukalibrierung) kann das Vorzeichen kippen:")
        st.dataframe(UI.cross_frame(DATA), width="stretch", hide_index=True)
        st.caption("Eine Schwelle ist ein regimeabhängiger Parameter, keine robuste Regel: bei knappem Bedarf zu hoch angesetzt, verschenkt sie Aufträge. Die Kalibrierung auf 40 Seeds ist verrauscht "
                   "(Zelle 24 Morgenaufträge, Rate 12: −55 ± 39).")

# PDF (nach der Live-Rechnung, damit der Tagesplan der gewählten Politik drinsteht)
with pdf_slot:
    st.download_button(
        "📄 Tagesplan als PDF herunterladen",
        data=generate_nv_pdf(dict(morning=morning, rate=rate, events=events, deadline=deadline, cost=cost, seed=seed), day, details[view_policy], best, cost, msg_text, note,
                             R.cell_setting_text(cell)),
        file_name="nahverkehr_tagesplan.pdf", mime="application/pdf", key="primary_pdf_download",
        help="Einstellungen, Kennzahlen der Politiken, Meldung, Ereignisse mit Änderungen und die Halteliste je Fahrzeug der gezeigten Politik.")

st.markdown("---")

# ---------------------------------------------------------------------------------------------------
# Ansichten
# ---------------------------------------------------------------------------------------------------
with st.expander("🔧 Wie wir das erreichen – Politiken im Vergleich"):
    tabs = st.tabs(["📅 Tagesverlauf", "📊 Politiken", "🎯 Orakel (vorgerechnet)", "📈 Messreihe"])
    with tabs[0]:
        st.markdown(
            "Der **Tagesverlauf** ist eine Ereignissimulation: neue Aufträge, Änderungen und Stornos treffen nacheinander ein. Bei jedem Ereignis macht **jede** Politik denselben **Basisschritt** (Einfügen an der billigsten machbaren "
            "Stelle, bei einer Änderung minimale Reparatur an derselben Stelle, sonst billigste Einfügung anderswo, bei einem Storno Entfernen); danach folgt je Politik ein **Neuoptimierungsschritt** (lokale Suche über den noch nicht "
            "gefahrenen Teil). Was schon losgefahren sein muss, ist **bindend** und bleibt unberührt. Unten die Ereignisse der gezeigten Politik mit den Änderungen je Ereignis."
        )
        st.dataframe(UI.events_table(details[view_policy]), width="stretch", hide_index=True)
    with tabs[1]:
        st.markdown(
            "Alle Politiken auf **diesem** Tag. **S0** plant nie neu, **R** optimiert nach jedem Ereignis den ganzen freien Teil, **F_k** hält die nächsten k Stopps je Fahrzeug fest, **P_λ** führt einen Zug nur aus, wenn die "
            "Fahrzeitersparnis größer ist als λ × zusätzlich geänderte Stopps, **T_x** plant nur alle x Minuten neu. Die Netto-Spalte rechnet die eingestellten Kosten je Änderung ab."
        )
        st.dataframe(UI.policy_table(day, cost), width="stretch", hide_index=True)
        st.caption("S0 hat bei (a) und (c) per Definition 0 (sie ändert nie andere Stopps), bei (b) nicht: Einfügungen verschieben auch bei S0 angesagte Zeiten. Ein einzelner Tag: Unterschiede zwischen Politiken sind hier oft null, "
                   "weil auf einem Tag nur wenige Züge zur Wahl stehen – die Messreihe trägt die Aussage.")
    with tabs[2]:
        st.markdown("Das **Rückblick-Orakel** kennt alle Ereignisse vorab (Prize-Collecting-Tourenplanung mit OR-Tools). Es wird **nie live** gerechnet (25 bis 70 Sekunden je Instanz), hier stehen nur die vorgerechneten Zahlen.")
        st.markdown("**Mit Änderungen** (Stabilitäts-Messreihe, 10 Instanzen je Zelle):")
        st.dataframe(UI.oracle_frame(DATA), width="stretch", hide_index=True)
        st.markdown("**Annahme nach Frist** (16 Instanzen je Zelle):")
        st.dataframe(UI.oracle_sameday_frame(DATA, "frist"), width="stretch", hide_index=True)
        st.markdown("**Annahme nach Auslastung** (16 Instanzen je Zelle):")
        st.dataframe(UI.oracle_sameday_frame(DATA, "auslastung"), width="stretch", hide_index=True)
        st.caption("Vorsicht: sehr kleine Stichprobe (10 bis 16 Instanzen, Standardfehler 30 bis 120) und das Orakel ist eine **Heuristik** (untere Schranke des echten Optimums, Warmstart aus der besten Online-Lösung), die Lücke ist "
                   "also eher unterschätzt. Das Orakel darf den Morgenplan neu bauen und kennt alle künftigen Aufträge: der Großteil der Lücke ist **Information über künftige Aufträge**, keine Frage der Stabilität. "
                   "Die Lücke wächst mit engen Fristen und hoher Auslastung.")
    with tabs[3]:
        st.markdown("Weitere vorgerechnete Auswertungen der Stabilitäts-Messreihe (200 Tage je Zelle).")
        st.markdown("**Ereignisarten und Ereignisraten** – Kosten der Ereignisse (Verlust gegenüber demselben Tag ohne Ereignisse):")
        st.dataframe(UI.event_kind_frame(DATA), width="stretch", hide_index=True)
        st.markdown("**Zeitbasierter Horizont H im Basisfall** (Zusatzlauf, Gewinn gegenüber dem starren Plan):")
        st.dataframe(UI.h_points_frame(R.find_h_cell(DATA)), width="stretch", hide_index=True)
        st.markdown("**Verteilung des Gewinns der vollen Neuplanung** (gewählte Zelle, schief verteilt):")
        _rd = cell["R_dist"]
        st.caption("Quantile 10 / 25 / 50 / 75 / 90 %: " + " / ".join(F.fmt_num(v, 0, True) for v in _rd["q"]) + f"; {F.fmt_share(_rd['share_pos'])} der Tage mit Gewinn"
                   + (f"; die besten 10 % der Tage liefern {F.fmt_share(_rd['top10_share'])} des Gewinns." if _rd.get("top10_share") is not None else "."))

with st.expander("Wie funktioniert diese Demo?"):
    st.markdown(
        f"""
**Basis.** Wie in der `vrp_demo`: ein Depot in der Mitte eines 60 × 60 km großen Gebiets, {CFG.K} Transporter mit einer Tour je Schicht, Fahrzeit = Entfernung × {CFG.speed:.1f} min/km (aufgerundet), Service {CFG.svc} min je Stopp,
Schichtende nach {CFG.H} min. Der **Morgenplan** (Aufträge mit Zeitfenstern von {CFG.win_w} min) entsteht mit Einfüge-Heuristik und lokaler Suche und wird von OR-Tools verbessert (deterministisch über eine Lösungszahl, nicht über Zeit).

**Neue Aufträge.** Poisson-verteilt im Fenster der ersten {CFG.t_arr} Minuten, Frist wie eingestellt, Erlös lognormal (Mittel {CFG.rev_mean:.0f}, Streuung {CFG.sigma}). Sofortige, verbindliche Annahme oder Ablehnung. **Änderungen und Stornos:** je Auftrag mit
der eingestellten Wahrscheinlichkeit eine **Änderung** (Zeitfenster ±30 min oder Adresse im Umkreis von 5 km) oder ein **Storno**, im Basisfall im Mittel {F.fmt_num(_BASE['n_events'])} Ereignisse je Tag. Ein Ereignis wirkt nur auf einen noch nicht bindenden Auftrag
(bindend: das Fahrzeug muss spätestens losgefahren sein, um den Servicebeginn zu halten), sonst wird es ignoriert. Wird ein geänderter Auftrag an seiner Stelle unzulässig, wird er billigst anderswo eingefügt; geht auch das nicht, gilt er als
gescheitert (Erlös weg, Strafe {CFG.pen}).

**Was als Planänderung zählt (drei Maße).** (a) *fahrerseitig, Hauptmaß:* noch nicht gefahrene Stopps, deren Fahrzeug oder Vorgänger sich ändert; der Ereignisauftrag selbst ist ausgenommen, S0 hat damit per Definition 0. (b) *kundenseitig:* angesagte
Ankunftszeiten, die sich um mehr als 15 min ändern. (c) Neuplanungsereignisse mit mindestens einer Änderung. Die Aussage darf nicht am Maß hängen: die Demo zeigt alle drei.

**Politiken.** **S0** kein Neuoptimieren. **R** volle Neuoptimierung nach jedem Ereignis. **F_k** die nächsten k Stopps je Fahrzeug fest. **P_λ** Zug nur, wenn die Fahrzeitersparnis größer ist als λ × zusätzlich geänderte Stopps (**Strafe in der Entscheidung**).
**T_x** nur alle x Minuten. **H_h** Stopps der nächsten h Minuten fest (nur vorgerechnet). Warum die Strafe dem Einfrierhorizont überlegen ist, ist *abgeleitet, nicht getestet*: sie rangiert Züge nach Nutzen je Änderung, Einfrieren und Periodik
sperren nach Ort bzw. Zeit, blind für den Nutzen.

**Kosten je Änderung sind nicht λ.** Die **Kosten je Änderung** (Regler „Kosten je Planänderung“) sind ein **Preis in der Bewertung**: Netto-Gewinn = Gewinn − Kosten × Änderungen. Sie verschieben die Netto-Rechnung und den empfohlenen Regler, nicht die Simulation.
Der **Reglerparameter λ** ist die **Strafe in der Entscheidung** der Politik P_λ. Beide sind nicht identisch; die App zeigt zu jedem Preis den besten Regler. Die Kosten je Änderung wurden **nicht in der Entscheidung gemessen**, sondern nachträglich angesetzt.

**Gewinn.** Erlös der bedienten Same-Day-Aufträge + {CFG.rev_mean:.0f} je bedientem Morgenauftrag − Fahrminuten − {CFG.pen} je nach einer Änderung nicht mehr bedienbarem Auftrag. Erlöse und Strafen sind **erfunden, nicht kalibriert**: Gewinne sind Größenordnungen.

**Warum Live-Tag und Messreihe nebeneinanderstehen.** Ein einzelner Tag streut stark (der Gewinn der vollen Neuplanung ist schief verteilt: Median unter Mittel, {F.fmt_num(100 - 100 * _BASE['R_dist']['share_pos'], 0)} % der Tage verlieren). Live macht den Tagesverlauf anfassbar, die Mittelwerte
über 200 Tage tragen die Aussage. Die Meldung stützt sich deshalb auf die **vorgerechnete Netto-Tabelle**: „volle Neuplanung lohnt“ (der beste Regler gewinnt höchstens 10 % mehr als R), „hier lohnt ein Preis je Änderung“ (mehr als 10 %) oder „volle
Neuplanung verliert gegen den starren Plan“ (R netto unter S0). **Die Stufen der Regler sind gemessene Zellen**; die Messreihe variiert je Zelle nur einen Parameter ausgehend vom Basisfall, für Kombinationen zeigt die App die nächstliegende gemessene Zelle und sagt es.

**Grenzen dieses Modells** (bewusst so gewählt, damit die Aussage ehrlich bleibt):

- **Stark stilisiert** – deterministische Fahrzeiten, eine Tour je Fahrzeug, Ereignisse unabhängig je Auftrag und höchstens eines je Auftrag, keine Rechenzeitkosten, Bindung ab Abfahrt (keine Umleitung mitten auf der Strecke).
- **Der Betrag ist klein** – die volle Neuplanung bringt im Basisfall rund {F.fmt_num(_R_PCT, 0)} % Gewinn; die Aussage ist der Vergleich der Regler und der Preis der Änderung, nicht die Größe.
- **Die Strafe optimiert das Maß (a) selbst mit** – ihr Vorsprung dort ist teilweise per Konstruktion; unter (b) ist er nur in {_B_CELLS[0]} von {_N_CELLS} Zellen belastbar.
- **Stornokosten** sind großenteils Erlösverlust und sagen nichts über die Wirkung der Neuplanung; die Strafe {CFG.pen} für gescheiterte Aufträge ist gesetzt.
- **Das Orakel ist klein und heuristisch** (10 bis 16 Instanzen, untere Schranke des Optimums) und nur vorgerechnet.
- **Nicht Teil dieser Demo** – Fahrzeitunsicherheit, mehrere Touren je Fahrzeug, Umleitung mitten auf der Strecke, exakte Neuoptimierung, Kosten je Änderung in der Entscheidung, Kalibrierung an echten Daten, Mengenänderungen als eigener Schwerpunkt.
        """
    )

with st.expander("📐 Mathematische Formulierung"):
    st.markdown(
        r"""
**Ereignisse und Plan.** Ereignis $e$ zur Zeit $t_e$: Auftrag $i$ neu (Erlös $r_i$, Frist $\delta$), geändert ($i \to i'$ mit neuen Attributen) oder storniert. Der Plan $x_t$ besteht aus den Touren der noch nicht gefahrenen Stopps; ein Stopp $j$ ist
bindend, sobald $S_j - T_{\mathrm{prev}(j),j} \le t$.

**Annahme.** Nimm $i$ an, wenn ein zulässiger Einfügeplatz existiert und
$$r_i \ge \Delta c_i \;\;(\text{P1p}),\qquad r_i \ge \Delta c_i + \mu\, w(t)\, \Delta e_i \;\;(\text{P2}),\qquad w(t) = 1 - t/300,$$
mit den Zusatzfahrminuten $\Delta c_i$ und der zusätzlichen Rückkehrzeit $\Delta e_i$ des gewählten Fahrzeugs; $\mu$ kommt aus einer Kalibriertabelle je Zelle.

**Neuoptimierung.** Zug $m$ (Relocate, Swap, 2-opt, 2-opt\*) wird nur bei strikter Verbesserung ausgeführt, mit Fahrzeitersparnis $\Delta(m)$:
$$\text{P}_\lambda:\; \Delta(m) > \lambda \cdot c(m),\qquad c(m) = \#\{\text{zusätzlich geänderte Stopps}\}.$$
$\mathrm{F}_k$ sperrt die nächsten $k$ Stopps je Fahrzeug, $\mathrm{T}_x$ erlaubt nur alle $x$ Minuten einen Lauf, $\mathrm{H}_h$ sperrt Stopps mit geplantem Servicebeginn in den nächsten $h$ Minuten. Grenzfälle exakt:
$\mathrm{F}_\infty = \mathrm{T}_\infty = \mathrm{H}_\infty = \mathrm{S0}$ und $\mathrm{F}_0 = \mathrm{P}_0 = \mathrm{T}_0 = \mathrm{H}_0 = \mathrm{R}$.

**Stabilität und Netto.** Maß (a): $A = \sum_e \bigl|\{ s : s \text{ vor } e \text{ nicht gefahren, Fahrzeug oder Vorgänger ändert sich}\}\bigr|$ ohne den Ereignisauftrag. Netto-Gewinn bei Kosten $c$ je Änderung:
$$\text{Netto}(\pi) = G(\pi) - c \cdot A(\pi),\qquad \text{bester Regler} = \arg\max_\pi \text{Netto}(\pi).$$
$c$ ist ein Preis in der Bewertung, $\lambda$ ein Parameter der Entscheidung: $c \ne \lambda$.

**Meldung.** Mit $g_R = \text{Netto}(R) - \text{Netto}(S0)$ und $g^* = \max_\pi \text{Netto}(\pi) - \text{Netto}(S0)$: $g_R < 0$: „verliert“; $g_R \ge 0$ und $g^* \le 1{,}1\, g_R$: „lohnt“; sonst „Preis lohnt“.
Gemessen wird über $N$ gepaarte Tage mit Mittel und Standardfehler $\text{SE} = s/\sqrt{N}$; ein Vorzeichen gilt als belastbar, wenn $|\bar g| > 2\,\text{SE}$.

Implementiert in `nv_model.py` (Instanz, Einfügen, lokale Suche, Morgenplan), `nv_sim.py` (Annahmeregeln, Politiken, Stabilitätsmaße), `nv_oracle.py` (Orakel, nur Reproduktion), `nv_live.py` (Live-Tag) und `nv_results.py` (Messreihe, Urteil).
        """
    )

st.markdown("---")

st.caption(
    "Diese Demo ist Teil des Portfolios von [Sebastian Hanisch](https://sebastianhanisch.net) – "
    "Operations Research und Machine Learning ([Über mich](https://sebastianhanisch.net/ueber-mich.html)). "
    "Mehr zum Thema: [Tourenplanung optimieren](https://sebastianhanisch.net/tourenplanung-optimierung.html)."
)
