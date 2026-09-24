"""Konstanten der Nahverkehrs-Demo (Same-Day-Aufträge, Änderungen und der Preis der Planänderung).

Modell und Zahlen aus messreihe_stabilitaet/ und messreihe_sameday/ (siehe tourenplanung-planung/plan_nahverkehr.html). Fachmodell-
Konstanten (Gebiet, Fahrzeiten, Erlöse) sind FEST (nv_model.Cfg); einstellbar sind Morgenaufträge, Same-Day-Rate, Änderungen und
Stornos, Frist, Kosten je Planänderung und der Seed. Die ersten vier stehen bewusst auf den GEMESSENEN Stufen: zu jeder Reglerstellung
gibt es eine vorgerechnete Vergleichsspalte (die Messreihe variiert je Zelle einen Parameter ausgehend vom Basisfall; für Kombinationen
jenseits der gemessenen Zellen zeigt die App die nächstliegende Zelle und sagt es). Alle Politiken laufen live über denselben Tag, kein
Regler ist je wirkungslos."""

# --- Regler (Plan Abschnitt 5) -----------------------------------------------------------------------------------------
MORNING_OPTIONS, MORNING_DEFAULT = (16, 28, 40, 52), 40
RATE_OPTIONS, RATE_DEFAULT = (0, 2, 6, 12), 6                     # Same-Day-Aufträge je Stunde
# Änderungen und Stornos: Stufe -> (p_chg, p_cancel) je Auftrag
EVENT_LEVELS = {"keine": (0.0, 0.0), "wenige": (0.1, 0.03), "mittel": (0.25, 0.08), "viele": (0.5, 0.16), "sehr viele": (0.8, 0.2)}
EVENT_OPTIONS, EVENT_DEFAULT = tuple(EVENT_LEVELS), "mittel"
DEADLINE_OPTIONS, DEADLINE_DEFAULT = (60, 120, 240), 120           # Minuten von Eingang bis Lieferung der Same-Day-Aufträge
COST_RANGE, COST_DEFAULT, COST_STEP = (0.0, 20.0), 2.0, 0.5       # Kosten je Planänderung (Gewinneinheiten)
SEED_RANGE, SEED_DEFAULT = (0, 299), 292

# Basisfall der Messreihen
BASE_CFG = dict(K=3, n_m=40, lam=6.0, delta=120, p_chg=0.25, p_cancel=0.08, Q=10 ** 9, w_time=1.0, w_addr=1.0, w_qty=0.0,
                chg_delta=30, addr_radius=5.0)
MEASURED_N = 200                  # Instanzen je Zelle (Stabilität), Seeds 0..199
SAMEDAY_N = 60                    # Instanzen je Zelle (Annahme), Seeds 0..59
CACHE_ENTRIES = 24                # Ergebnisse je Einstellung (st.cache_data)

# --- Live-Rechnung: Politik-Raster (dasselbe wie tools/sweep.py) -------------------------------------------------------
F_STEPS = (1, 2, 3, 4, 6, 8, 12)                                  # F_k: die nächsten k Stopps je Fahrzeug fest
LAMBDAS = (0.25, 0.5, 1.0, 1.5, 2.0, 3.0, 5.0, 8.0)               # P_λ: Entscheidungsstrafe je zusätzlich geändertem Stopp
T_STEPS = (30, 60, 120, 240)                                      # T_x: nur alle x Minuten neu planen
H_STEPS = (15, 30, 60, 90, 120, 180, 240, 300)                    # H_h (nur vorgerechnet, Zusatzlauf)


def _lam_label(lam):
    return f"{lam:g}"


POLICY_NAMES = (("S0", "R") + tuple(f"F{k}" for k in F_STEPS) + tuple(f"P{_lam_label(x)}" for x in LAMBDAS)
                + tuple(f"T{x}" for x in T_STEPS))
POLICY_SPECS = {"S0": dict(kind="S0"), "R": dict(kind="R")}
POLICY_SPECS.update({f"F{k}": dict(kind="F", k=k) for k in F_STEPS})
POLICY_SPECS.update({f"P{_lam_label(x)}": dict(kind="P", lam=x) for x in LAMBDAS})
POLICY_SPECS.update({f"T{x}": dict(kind="T", T_per=x) for x in T_STEPS})
POLICY_SPECS.update({f"H{h}": dict(kind="H", H_min=h) for h in H_STEPS})   # nur für die Reproduktion (Zusatzlauf)
FAMILIES = ("P", "F", "T")
FAMILY_LABELS = {"P": "Änderungsstrafe (P)", "F": "Einfrierhorizont in Stopps (F)", "T": "periodische Neuplanung (T)",
                 "H": "Einfrierhorizont in Minuten (H)"}

# Annahmeregeln (Kernabschnitt ①), Reihenfolge und Namen
ACCEPT_ORDER = ("P1", "P1p", "P2", "P1pL", "P2L")
ACCEPT_LABELS = {"P0": "nie annehmen", "P1": "alles Machbare", "P1p": "Erlös ≥ Fahrt", "P2": "Schattenpreis", "P1pL": "Erlös ≥ Fahrt + Neuopt.",
                 "P2L": "Schattenpreis + Neuopt.", "P4L": "Rollout"}

# --- Meldungen und Urteile (Plan Abschnitt 6) -----------------------------------------------------------------------------------
BEST_SHARE_LIMIT = 1.10           # bester Regler höchstens 10 % besser als R (gemessen am Gewinn über S0): "volle Neuplanung lohnt"
SE_FACTOR = 2.0                   # ein Vorzeichen gilt als belastbar, wenn |Mittel| > 2 Standardfehler
STATE_LOHNT, STATE_PREIS, STATE_VERLIERT = "lohnt", "preis", "verliert"

# --- Farben ----------------------------------------------------------------------------------------------------------------------
COLOR_P, COLOR_F, COLOR_T, COLOR_H = "#2a6fb0", "#c0392b", "#2e7d4f", "#7d5ba6"
COLOR_R, COLOR_S0, COLOR_BEST = "#c77700", "#9aa5b4", "#2a6fb0"
FAMILY_COLORS = {"P": COLOR_P, "F": COLOR_F, "T": COLOR_T, "H": COLOR_H}
EVENT_COLORS = {"new": "#2e7d4f", "new_rejected": "#8bbf6a", "change": "#e0a800", "cancel": "#c0392b", "ignored": "#9aa5b4"}
EVENT_NAMES = {"new": "neuer Auftrag, angenommen", "new_rejected": "neuer Auftrag, abgelehnt", "change": "Änderung", "cancel": "Storno",
               "ignored": "Ereignis ignoriert (Auftrag schon bindend)"}
VEHICLE_COLORS = ("#2a6fb0", "#c0392b", "#2e7d4f", "#7d5ba6", "#c77700")
STOP_COLORS = {"morning": "#5b6b80", "new": "#2e7d4f", "changed": "#e0a800"}
CHART_HEIGHT = 380

# --- Presets (Plan Abschnitt 7; Abnahmekriterien in nv_stories.py) ---------------------------------------------------------------
# Der Seed bestimmt nur den GEZEIGTEN Tag: die Messreihe steht auf den Seeds 0..199, die Anzeige-Seeds liegen ausserhalb. Seed 292 kommt aus
# tools/tune_presets.py (Suche über 200 bis 299): der Tag erfüllt für alle fünf Presets die qualitativen Tageskriterien aus nv_stories.day_criteria
# und liegt mit +102 R-Gewinn im Standard nah am Median der Messreihe (+99; Mittel +123).
PRESETS = {
    "Standard": dict(morning=40, rate=6, events="mittel", deadline=120, cost=2.0, seed=292),
    "Viele neue Aufträge": dict(morning=40, rate=12, events="mittel", deadline=120, cost=2.0, seed=292),
    "Nur Änderungen": dict(morning=40, rate=0, events="mittel", deadline=120, cost=2.0, seed=292),
    "Knappe Frist": dict(morning=40, rate=6, events="mittel", deadline=60, cost=2.0, seed=292),
    "Teure Änderungen": dict(morning=40, rate=6, events="mittel", deadline=120, cost=5.0, seed=292),
}
PRESET_HELP = {
    "Standard": "Der Grundfall: Volle Neuplanung lohnt, aber ein Preis je Änderung holt fast alles mit der Hälfte der Änderungen.",
    "Viele neue Aufträge": "Mehr neue Aufträge: mehr Nutzen der Neuplanung und mehr Änderungen.",
    "Nur Änderungen": "Ohne neue Aufträge kommt der Nutzen der Neuplanung nicht von den Änderungen: fast nichts zu holen.",
    "Knappe Frist": "Bei knapper Frist bringt Einfrieren fast nichts, ein Preis je Änderung schon.",
    "Teure Änderungen": "Ab etwa 4,3 Kosten je Änderung verliert die volle Neuplanung gegen den starren Plan.",
}
