"""Zahlenformate mit deutschem Dezimalkomma und Zeitangaben (Minuten ab Schichtbeginn)."""


def fmt_num(v, digits=1, signed=False):
    text = f"{v:+.{digits}f}" if signed else f"{v:.{digits}f}"
    return text.replace(".", ",")


def fmt_pct(v, digits=1, signed=False):
    return f"{fmt_num(v, digits, signed)} %"


def fmt_share(v):
    """Anteil (0..1) als ganze Prozent; None (Anteil nicht bestimmbar) als Gedankenstrich."""
    return "–" if v is None else f"{100.0 * v:.0f} %"


def fmt_band(mean, se, digits=1, signed=True):
    """Mittel ± Standardfehler mit Vorzeichen: '+123,0 ± 12,1'."""
    return f"{fmt_num(mean, digits, signed)} ± {fmt_num(se, digits)}"


def fmt_ci(ci, digits=0):
    """95-%-Intervall '(56 bis 82)'; ohne Intervall leer."""
    if not ci:
        return ""
    return f"({fmt_num(ci[0], digits)} bis {fmt_num(ci[1], digits)})"


def fmt_clock(minutes):
    """Minuten ab Schichtbeginn als 'h:mm' (0 = Schichtbeginn)."""
    m = int(round(minutes))
    return f"{m // 60}:{m % 60:02d}"


def fmt_min(minutes):
    return f"{int(round(minutes))} min"
