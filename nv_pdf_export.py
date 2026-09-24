"""PDF-Export des Tagesplans der gezeigten Politik (fpdf2, Helvetica-Kernschrift, nur Text und Tabellen).

Die Kernschriften kennen nur Latin-1: Umlaute sind erlaubt, aber Gedankenstrich (U+2013), Minuszeichen (U+2212), Euro-Zeichen, Emoji, das
griechische Lambda usw. lassen fpdf2 abstürzen. Deshalb läuft jeder Text durch pdf_text()."""
import time

import nv_constants as C
import nv_format as F
import nv_results as R

_REPLACEMENTS = {
    "–": "-", "—": "-", "‑": "-", "−": "-", "≥": ">=", "≤": "<=", "→": "->", "≈": "ca.", "€": "EUR", "±": "+-",
    "·": "-", "“": '"', "”": '"', "„": '"', "‘": "'", "’": "'", "⚠️": "(!)", "⚠": "(!)", "✅": "", "ℹ️": "", "λ": "lambda", "Δ": "Delta",
    "◀": "<", "▶": ">", "📦": "", "📐": "", "🎯": "", "📊": "", "🔧": "", "🎲": "", "📅": "", "📈": "", "📄": "",
}


def pdf_text(text):
    """Text für die Helvetica-Kernschrift: bekannte Sonderzeichen ersetzen, den Rest Latin-1-sicher machen."""
    for old, new in _REPLACEMENTS.items():
        text = text.replace(old, new)
    return text.encode("latin-1", "replace").decode("latin-1")


def generate_nv_pdf(settings, day, view, best, cost, message_text, note, cell_text, compress=True):
    """Tagesplan als PDF: Einstellungen, Kennzahlen der Politiken, Meldung, Ereignisse mit Änderungen, Halteliste je Fahrzeug, Hinweise.

    settings: dict der Reglerwerte (morning, rate, events, deadline, cost, seed); day: nv_live.solve_day; view: nv_live.day_detail der
    gezeigten Politik; best: Name des empfohlenen Reglers; cost: Kosten je Änderung; message_text: Text der Meldung; note: Hinweis zur
    Zell-Zuordnung (leer, wenn exakt); cell_text: Beschreibung der Vergleichszelle der Messreihe."""
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos

    pdf = FPDF()
    pdf.set_compression(compress)
    pdf.add_page()

    def line(text, height=7, width=0):
        pdf.cell(width, height, pdf_text(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def heading(text):
        pdf.set_font("Helvetica", "B", 12)
        line(text, 8)
        pdf.set_font("Helvetica", "", 10)

    def pairs(rows):
        for label, value in rows:
            pdf.cell(80, 6, pdf_text(label), border=0)
            line(value, 6)

    def table(headers, widths, rows, size=8):
        pdf.set_font("Helvetica", "B", size)
        pdf.set_fill_color(230, 230, 230)
        for header, width in zip(headers, widths):
            pdf.cell(width, 7, pdf_text(header), border=1, fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.ln(7)
        pdf.set_font("Helvetica", "", size)
        for row in rows:                                    # der automatische Seitenumbruch von fpdf2 hält die Zeile zusammen
            for value, width in zip(row, widths):
                pdf.cell(width, 7, pdf_text(str(value)), border=1, new_x=XPos.RIGHT, new_y=YPos.TOP)
            pdf.ln(7)

    def keep_together(height):
        if pdf.get_y() + height > pdf.h - pdf.b_margin:
            pdf.add_page()

    pdf.set_font("Helvetica", "B", 16)
    line("Nahverkehr: Same-Day-Aufträge, Änderungen und der Preis der Planänderung", 10)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(120, 120, 120)
    line(f"Erstellt: {time.strftime('%d.%m.%Y %H:%M')}  -  sebastianhanisch.net", 6)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(3)

    heading("Einstellungen")
    pairs([("Morgenaufträge", str(settings["morning"])), ("Same-Day-Rate", f"{settings['rate']} je Stunde"),
           ("Änderungen und Stornos", str(settings["events"])), ("Frist", f"{settings['deadline']} min"),
           ("Kosten je Planänderung", f"{F.fmt_num(settings['cost'])} (Gewinneinheiten)"), ("Seed", str(settings["seed"]))])
    pdf.ln(3)

    heading("Kennzahlen des gezeigten Tages (ein einzelner Tag)")
    res = day["results"]
    base = res["S0"]["profit_total"]
    rows = []
    for name in dict.fromkeys(("S0", "R", best, view["policy"])):
        r = res[name]
        rows.append([R.policy_label(name), r["profit_total"], f"{r['profit_total'] - base:+d}", r["a"], r["b"], r["c"],
                     F.fmt_num(r["profit_total"] - cost * r["a"], 0)])
    table(["Politik", "Gewinn", "gegenüber S0", "Änderungen (a)", "Ansagen (b)", "Ereignisse (c)", "Netto"], [50, 22, 26, 28, 24, 26, 20], rows)
    pdf.ln(3)

    heading("Meldung (aus der vorgerechneten Messreihe)")
    pdf.set_font("Helvetica", "", 9)
    pdf.multi_cell(0, 5, pdf_text(message_text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(90, 90, 90)
    pdf.multi_cell(0, 4.5, pdf_text(f"Vergleichszelle der Messreihe: {cell_text}. {note}".strip()), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "", 10)
    pdf.ln(2)

    keep_together(40)
    heading(f"Ereignisse des Tages: {R.policy_label(view['policy'])}")
    table(["Zeit", "Auftrag", "Ereignis", "Einzelheit", "(a)", "(b)"], [16, 18, 42, 84, 12, 12],
          [[F.fmt_clock(e["t"]), e["order"], C.EVENT_NAMES[e["kind"]] if e["kind"] in ("new", "new_rejected", "ignored") else
            ("Storno" if e["kind"] == "cancel" else "Änderung"), e["text"], e["a"], e["b"]] for e in view["events"]], size=7)
    pdf.ln(3)

    keep_together(40)
    heading(f"Tagesplan: {R.policy_label(view['policy'])}")
    kinds = {"morning": "Morgenauftrag", "new": "neuer Auftrag", "changed": "geänderter Morgenauftrag"}
    for veh in view["vehicles"]:
        keep_together(30)
        pdf.set_font("Helvetica", "B", 10)
        line(f"Fahrzeug {veh['vehicle']}: {len(veh['stops'])} Stopps, Fahrzeit {veh['drive']} min, Rückkehr {F.fmt_clock(veh['return_time'])}", 6)
        pdf.set_font("Helvetica", "", 8)
        table(["Nr.", "Auftrag", "Art", "Service ab", "Zeitfenster", "Erlös", "Änderung ggü. Morgenplan"], [10, 16, 44, 22, 32, 14, 42],
              [[i, s["order"], kinds[s["kind"]], F.fmt_clock(s["start"]), f"{F.fmt_clock(s['window'][0])}-{F.fmt_clock(s['window'][1])}", s["rev"], s["change"]]
               for i, s in enumerate(veh["stops"], 1)], size=7)
        pdf.ln(3)

    keep_together(60)
    heading("Hinweise zum Modell")
    pdf.set_font("Helvetica", "", 9)
    for text in [
        "Stark stilisiert: 60 x 60 km, ein Depot, drei Transporter mit einer Tour je Schicht, deterministische Fahrzeiten, Ereignisse unabhängig je "
        "Auftrag, Bindung ab Abfahrt. Die Erlöse und Strafen sind erfunden, nicht kalibriert: Gewinne sind Größenordnungen.",
        "Kosten je Planänderung werden nur nachträglich in der Netto-Rechnung angesetzt; sie sind nicht der Reglerparameter lambda (Entscheidungsstrafe).",
        f"Ein einzelner Tag streut stark; die Aussage tragen die vorgerechneten Messreihen ({C.MEASURED_N} Tage je Zelle für die Stabilität, "
        f"{C.SAMEDAY_N} Tage für die Annahme).",
    ]:
        pdf.multi_cell(0, 5, pdf_text("- " + text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    return bytes(pdf.output())
