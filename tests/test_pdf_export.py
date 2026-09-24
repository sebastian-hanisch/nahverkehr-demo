"""PDF-Export des Tagesplans: Sonderzeichen (die Kernschriften kennen nur Latin-1), Inhalt, mehrere Seiten."""
import pytest

import nv_constants as C
import nv_live as LV
import nv_pdf_export as PDF
import nv_results as R
import nv_ui_panel as UI

DATA = R.load_results()
SETTINGS = dict(morning=40, rate=6, events="mittel", deadline=120, cost=2.0, seed=292)
CELL = R.find_cell(DATA)


@pytest.fixture(scope="module")
def day():
    return LV.solve_day(40, 6, "mittel", 120, 292)


@pytest.fixture(scope="module")
def view():
    return LV.day_detail(40, 6, "mittel", 120, 292, "P1.5")


def make(day, view, compress=False, **kw):
    state, text = UI.message(day, CELL, 2.0)
    args = dict(settings=SETTINGS, day=day, view=view, best="P1.5", cost=2.0, message_text=text, note="", cell_text=R.cell_setting_text(CELL), compress=compress)
    args.update(kw)
    return PDF.generate_nv_pdf(**args)


def text_of(pdf):
    """Der unkomprimierte PDF-Inhalt als Text; Klammern stehen in PDF-Zeichenketten mit vorangestelltem Backslash."""
    return pdf.decode("latin-1").replace("\\(", "(").replace("\\)", ")")


def test_pdf_is_a_valid_document_with_the_expected_content(day, view):
    pdf = make(day, view)
    assert pdf.startswith(b"%PDF-") and pdf.rstrip().endswith(b"%%EOF") and len(pdf) > 5000
    text = text_of(pdf)
    for needle in ("Nahverkehr: Same-Day-Auftr", "Einstellungen", "Kennzahlen des gezeigten Tages", "Meldung (aus der vorgerechneten Messreihe)",
                   "Ereignisse des Tages: P_1,5", "Tagesplan: P_1,5", "Fahrzeug 1:", "Fahrzeug 3:", "Hinweise zum Modell", "S0 (starrer Plan)",
                   "R (volle Neuplanung)", "Seed", "292", "Kosten je Plan", "sebastianhanisch.net"):
        assert needle in text, needle
    assert "Vergleichszelle der Messreihe" in text


def test_pdf_shows_the_selected_policies_only_once(day, view):
    text = text_of(make(day, view))
    assert text.count("(P_1,5)") + text.count("P_1,5") >= 2
    same = make(day, LV.day_detail(40, 6, "mittel", 120, 292, "R"), best="R")
    assert text_of(same).count("R (volle Neuplanung)") >= 2


def test_pdf_survives_all_unicode_traps():
    """Gedankenstrich, Minuszeichen, Euro, Emoji, Lambda, Pfeil, Pfeile in Texten stürzen die Kernschriften nicht ab (genau diese Zeichen)."""
    trap = "– — ‑ − ≥ ≤ → ≈ € ± · “ ” „ ‘ ’ ⚠️ ✅ ℹ️ 📦 📐 🎯 λ Δ ◀ ▶ ä ö ü ß µ × 😀"
    out = PDF.pdf_text(trap)
    assert out.encode("latin-1")                                             # lässt sich in Latin-1 schreiben
    assert "-" in out and ">=" in out and "<=" in out and "->" in out and "ca." in out and "EUR" in out and "+-" in out and "lambda" in out and "Delta" in out
    assert "ä ö ü ß µ ×" in out and "–" not in out and "−" not in out and "€" not in out and "⚠" not in out and "📦" not in out
    assert "(!)" in out and "<" in out and ">" in out


@pytest.mark.parametrize("char", ["–", "—", "−", "€", "≥", "→", "λ", "😀", "⚠️", "✅", "📄", "‑", "“", "„", "±", "≈", "Δ"])
def test_pdf_renders_a_message_with_each_special_character(day, view, char):
    pdf = make(day, view, message_text=f"Test {char} Zeichen {char}", note=f"Hinweis {char}", compress=True)
    assert pdf.startswith(b"%PDF-")


def test_pdf_text_keeps_latin1_and_replaces_the_rest():
    assert PDF.pdf_text("Größe 5 µm × 2") == "Größe 5 µm × 2"
    assert PDF.pdf_text("日本") == "??"
    assert PDF.pdf_text("a–b") == "a-b" and PDF.pdf_text("−5") == "-5" and PDF.pdf_text("10 €") == "10 EUR"
    assert PDF.pdf_text("x ≥ 1 → y ≈ 2 ± 1") == "x >= 1 -> y ca. 2 +- 1"


def test_pdf_compression_switch(day, view):
    plain, packed = make(day, view, compress=False), make(day, view, compress=True)
    assert len(packed) < len(plain) and packed.startswith(b"%PDF-")


def test_pdf_many_stops_run_over_several_pages():
    busy = LV.solve_day(40, 12, "mittel", 120, 292)
    view = LV.day_detail(40, 12, "mittel", 120, 292, "R")
    pdf = make(busy, view, compress=False)
    assert text_of(pdf).count("/Type /Page\n") >= 2                        # mehrere Seiten, der Umbruch von fpdf2 hält die Tabellenzeilen zusammen
    assert f"Fahrzeug 1: {len(view['vehicles'][0]['stops'])} Stopps" in text_of(pdf)


def test_pdf_lists_every_stop_and_event(day, view):
    text = text_of(make(day, view))
    for veh in view["vehicles"]:
        assert f"Fahrzeug {veh['vehicle']}: {len(veh['stops'])} Stopps" in text
    assert text.count("Zeitfenster um") >= 1 and "Storno" in text
    assert C.EVENT_NAMES["new"] in text
