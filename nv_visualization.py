"""Plotly-Figuren der Nahverkehrs-Demo: Ereignis-Zeitstrahl mit Änderungen je Ereignis, Touren-Zeitstrahl, Karte, Kurve Gewinn gegen
Änderungen, Anteil am R-Gewinn, Netto-Gewinn gegen Kosten, Annahme-Balken, Regime-Balken, Maßvergleich.

Konventionen des Portfolios: Achsen `fixedrange` (Touch-Scrollen), Vorlage plotly_white, Legende unten, Farben über alle Figuren
konsistent, KEINE Farblisten in Marker-Eigenschaften (je Merkmal eine eigene Spur; das vermeidet Plotly-Warnungen). Plotly wird erst
in den Funktionen importiert, damit die reine Rechnung ohne Plotly testbar bleibt."""
import nv_constants as C
import nv_format as F
import nv_results as R

LEGEND_BOTTOM = dict(orientation="h", yref="container", yanchor="bottom", y=0.0, x=0)


def _lock_axes(fig):
    """Achsen fest: verhindert Zoomen und Verschieben per Touch, damit die Seite scrollbar bleibt (Hover bleibt)."""
    fig.update_xaxes(fixedrange=True)
    fig.update_yaxes(fixedrange=True)
    return fig


# ---------------------------------------------------------------------------------------------------
# Tagesverlauf
# ---------------------------------------------------------------------------------------------------
def events_figure(view, others):
    """Oben die Ereignisse des Tages (Markerart nach Ereignisart; ignoriert = wirkungslos unter der gezeigten Politik), darunter die
    geänderten Stopps (fahrerseitig, Maß (a)) je Ereigniszeitpunkt für die gezeigte Politik und die Vergleichspolitiken.

    view: day_detail der gezeigten Politik; others: Liste (Beschriftung, Farbe, day_detail) der Vergleichspolitiken einschließlich der
    gezeigten."""
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.32, 0.68], vertical_spacing=0.06)
    for kind in ("new", "new_rejected", "change", "cancel", "ignored"):
        evs = [e for e in view["events"] if e["kind"] == kind]
        if not evs:
            continue
        symbol = {"new": "circle", "new_rejected": "circle-open", "change": "diamond", "cancel": "x", "ignored": "cross-thin-open"}[kind]
        fig.add_trace(go.Scatter(
            x=[e["t"] for e in evs], y=[1] * len(evs), mode="markers", name=C.EVENT_NAMES[kind],
            marker=dict(symbol=symbol, size=11, color=C.EVENT_COLORS[kind], line=dict(width=2, color=C.EVENT_COLORS[kind])),
            text=[f"Auftrag {e['order']}, {F.fmt_clock(e['t'])}: {e['text']}" for e in evs], hovertemplate="%{text}<extra></extra>"), row=1, col=1)
    for label, color, det in others:
        per_t = {}
        for e in det["events"]:
            per_t[e["t"]] = per_t.get(e["t"], 0) + e["a"]
        ts = sorted(per_t)
        fig.add_trace(go.Bar(x=ts, y=[per_t[t] for t in ts], name=label, marker_color=color, width=2.2,
                             hovertemplate=f"{label}: %{{y}} geänderte Stopps um %{{x}} min<extra></extra>"), row=2, col=1)
    fig.update_layout(template="plotly_white", height=C.CHART_HEIGHT + 60, barmode="group", margin=dict(t=20, b=100, l=10, r=10),
                      legend=LEGEND_BOTTOM, bargap=0.0)
    fig.update_yaxes(visible=False, range=[0.4, 1.6], row=1, col=1)
    fig.update_yaxes(title_text="geänderte Stopps", rangemode="tozero", row=2, col=1)
    fig.update_xaxes(range=[0, view["shift_end"]], row=1, col=1)
    fig.update_xaxes(title_text="Minuten ab Schichtbeginn", range=[0, view["shift_end"]], row=2, col=1)
    return _lock_axes(fig)


def tours_figure(det):
    """Ein Balken je Stopp und Fahrzeug: heller Balken = Zeitfenster, dunkler Balken = Service; Farbe nach Art des Auftrags."""
    import plotly.graph_objects as go

    fig = go.Figure()
    kinds = ("morning", "new", "changed")
    names = {"morning": "Morgenauftrag", "new": "neuer Auftrag (Same-Day)", "changed": "geänderter Morgenauftrag"}
    for kind in kinds:
        xs, bases, ys, texts, wx, wb = [], [], [], [], [], []
        for veh in det["vehicles"]:
            for s in veh["stops"]:
                if s["kind"] != kind:
                    continue
                label = f"Fahrzeug {veh['vehicle']}"
                xs.append(s["end"] - s["start"])
                bases.append(s["start"])
                ys.append(label)
                wx.append(s["window"][1] - s["window"][0])
                wb.append(s["window"][0])
                texts.append(f"Auftrag {s['order']} ({names[kind]}), Service {F.fmt_clock(s['start'])}, Fenster {F.fmt_clock(s['window'][0])}"
                             f"–{F.fmt_clock(s['window'][1])}, Erlös {s['rev']}, {s['change']}")
        if not xs:
            continue
        fig.add_trace(go.Bar(x=wx, base=wb, y=ys, orientation="h", marker_color=C.STOP_COLORS[kind], opacity=0.22, showlegend=False,
                             hoverinfo="skip"))
        fig.add_trace(go.Bar(x=xs, base=bases, y=ys, orientation="h", name=names[kind], marker_color=C.STOP_COLORS[kind],
                             hovertext=texts, hoverinfo="text"))
    fig.add_vline(x=det["shift_end"], line=dict(color="#9aa5b4", width=1, dash="dot"))
    fig.update_layout(template="plotly_white", height=max(C.CHART_HEIGHT - 120, 170 + 55 * len(det["vehicles"])), barmode="overlay",
                      margin=dict(t=20, b=100, l=10, r=10), legend=LEGEND_BOTTOM, xaxis_title="Minuten ab Schichtbeginn", bargap=0.3)
    fig.update_yaxes(autorange="reversed")
    fig.update_xaxes(range=[0, det["shift_end"] + 10])
    return _lock_axes(fig)


def route_map_figure(det):
    """Depot, Stopps (nach Art) und die Touren der Politik; abgelehnte neue Aufträge als graue Kreuze."""
    import plotly.graph_objects as go

    fig = go.Figure()
    dx, dy = det["depot"]
    for veh in det["vehicles"]:
        if not veh["stops"]:
            continue
        color = C.VEHICLE_COLORS[(veh["vehicle"] - 1) % len(C.VEHICLE_COLORS)]
        xs = [dx] + [s["x"] for s in veh["stops"]] + [dx]
        ys = [dy] + [s["y"] for s in veh["stops"]] + [dy]
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", name=f"Fahrzeug {veh['vehicle']}", line=dict(color=color, width=2), hoverinfo="skip",
                                 showlegend=False))                          # sonst wird die Legende so hoch, dass sie die Zeichenfläche zusammendrückt
    names = {"morning": "Morgenauftrag", "new": "neuer Auftrag", "changed": "geänderter Morgenauftrag"}
    for kind in ("morning", "new", "changed"):
        pts = [(v["vehicle"], s) for v in det["vehicles"] for s in v["stops"] if s["kind"] == kind]
        if not pts:
            continue
        fig.add_trace(go.Scatter(
            x=[s["x"] for _, s in pts], y=[s["y"] for _, s in pts], mode="markers", name=names[kind],
            marker=dict(size=9, color=C.STOP_COLORS[kind], line=dict(color="white", width=1)),
            text=[f"Auftrag {s['order']}, Fahrzeug {v}, Service {F.fmt_clock(s['start'])}, Erlös {s['rev']}" for v, s in pts],
            hovertemplate="%{text}<extra></extra>"))
    if det["rejected"]:
        fig.add_trace(go.Scatter(
            x=[r["x"] for r in det["rejected"]], y=[r["y"] for r in det["rejected"]], mode="markers", name="abgelehnter neuer Auftrag",
            marker=dict(symbol="x", size=8, color="#9aa5b4"),
            text=[f"Auftrag {r['order']}, Eingang {F.fmt_clock(r['t'])}, Erlös {r['rev']}" for r in det["rejected"]],
            hovertemplate="%{text}<extra></extra>"))
    fig.add_trace(go.Scatter(x=[dx], y=[dy], mode="markers", name="Depot", marker=dict(symbol="diamond", size=14, color=C.COLOR_R,
                                                                                    line=dict(color="white", width=1)),
                             hovertemplate="Depot<extra></extra>"))
    a = det["area"]
    fig.update_layout(template="plotly_white", height=C.CHART_HEIGHT + 60, margin=dict(t=20, b=140, l=10, r=10), legend=LEGEND_BOTTOM,
                      xaxis=dict(range=[-2, a + 2], title="km", constrain="domain"),
                      yaxis=dict(range=[-2, a + 2], scaleanchor="x", scaleratio=1, title="km", constrain="domain"))
    return _lock_axes(fig)


# ---------------------------------------------------------------------------------------------------
# Kernabschnitt ②: vorgerechnet
# ---------------------------------------------------------------------------------------------------
def curve_figure(cell, measure="a"):
    """Kurve Gewinn gegenüber dem starren Plan über den Änderungen je Tag: eine Linie je Reglerfamilie (Stufen als Punkte), dazu R."""
    import plotly.graph_objects as go

    pts = R.curve_points(cell, measure)
    fig = go.Figure()
    for fam in C.FAMILIES:
        xs = [0.0] + [p[0] for p in pts[fam]]
        ys = [0.0] + [p[1] for p in pts[fam]]
        names = ["S0"] + [R.policy_label(p[2]) for p in pts[fam]]
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines+markers", name=C.FAMILY_LABELS[fam], line=dict(color=C.FAMILY_COLORS[fam], width=2),
                                 marker=dict(size=6, color=C.FAMILY_COLORS[fam]), text=names,
                                 hovertemplate="%{text}: %{x:.1f} Änderungen, Gewinn %{y:+.1f}<extra></extra>"))
    rx, ry, _ = pts["R"]
    fig.add_trace(go.Scatter(x=[rx], y=[ry], mode="markers", name="volle Neuplanung R", marker=dict(size=13, color=C.COLOR_R,
                                                                                                  line=dict(color="white", width=1)),
                             hovertemplate="R: %{x:.1f} Änderungen, Gewinn %{y:+.1f}<extra></extra>"))
    xtitle = {"a": "geänderte Stopps je Tag (fahrerseitig, Maß a)", "b": "geänderte Ankunftsansagen je Tag (kundenseitig, Maß b)",
              "c": "Neuplanungsereignisse mit Änderung je Tag (Maß c)"}[measure]
    fig.update_layout(template="plotly_white", height=C.CHART_HEIGHT + 20, margin=dict(t=20, b=110, l=10, r=10), legend=LEGEND_BOTTOM,
                      xaxis=dict(title=xtitle, rangemode="tozero"), yaxis=dict(title="Gewinn gegenüber starrem Plan", rangemode="tozero"))
    return _lock_axes(fig)


def share_figure(cell, measure="a"):
    """Anteil am R-Gewinn bei 25 / 50 / 75 % der R-Änderungen je Familie (Balken; Fehlerbalken = 95-%-Intervall im Maß (a))."""
    import plotly.graph_objects as go

    fig = go.Figure()
    fracs = (25, 50, 75)
    for fam in C.FAMILIES:
        vals = [R.share(cell, fam, q, measure) for q in fracs]
        kw = {}
        if measure == "a":                                     # Intervalle gibt es nur für das Hauptmaß
            cis = [R.share_ci(cell, fam, q) for q in fracs]
            kw["error_y"] = dict(type="data", symmetric=False, visible=True, color="#4b5d75", thickness=1.2,
                                 array=[0.0 if (ci is None or v is None) else max(0.0, 100.0 * (ci[1] - v)) for ci, v in zip(cis, vals)],
                                 arrayminus=[0.0 if (ci is None or v is None) else max(0.0, 100.0 * (v - ci[0])) for ci, v in zip(cis, vals)])
        fig.add_trace(go.Bar(x=[f"bei {q} % der R-Änderungen" for q in fracs], y=[None if v is None else 100.0 * v for v in vals],
                             name=C.FAMILY_LABELS[fam], marker_color=C.FAMILY_COLORS[fam],
                             hovertemplate="%{y:.0f} % des R-Gewinns<extra></extra>", **kw))
    fig.add_hline(y=100, line=dict(color="#9aa5b4", width=1, dash="dash"))
    fig.update_layout(template="plotly_white", height=C.CHART_HEIGHT, barmode="group", margin=dict(t=20, b=110, l=10, r=10), legend=LEGEND_BOTTOM,
                      yaxis=dict(title="Anteil am Gewinn der vollen Neuplanung (%)", rangemode="tozero"))
    return _lock_axes(fig)


def net_figure(cell, marked_cost=None):
    """Netto-Gewinn gegenüber dem starren Plan über den Kosten je Änderung: volle Neuplanung R und der jeweils beste Regler."""
    import plotly.graph_objects as go

    costs = [i * 0.5 for i in range(0, 41)]
    rows = [R.net_row(cell, c) for c in costs]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=costs, y=[r["net_over_S0"] for r in rows], mode="lines", name="bester Regler bei diesen Kosten",
                             line=dict(color=C.COLOR_P, width=3), text=[R.policy_label(r["best"]) for r in rows],
                             hovertemplate="Kosten %{x}: bester Regler %{text}, %{y:+.1f} gegenüber S0<extra></extra>"))
    fig.add_trace(go.Scatter(x=costs, y=[r["net_R_over_S0"] for r in rows], mode="lines", name="volle Neuplanung R",
                             line=dict(color=C.COLOR_R, width=2), hovertemplate="Kosten %{x}: R %{y:+.1f} gegenüber S0<extra></extra>"))
    fig.add_hline(y=0, line=dict(color=C.COLOR_S0, width=1.5, dash="dash"))
    if marked_cost is not None:
        fig.add_vline(x=marked_cost, line=dict(color="#4b5d75", width=1, dash="dot"))
    fig.update_layout(template="plotly_white", height=C.CHART_HEIGHT, margin=dict(t=20, b=110, l=10, r=10), legend=LEGEND_BOTTOM,
                      xaxis=dict(title="Kosten je Planänderung (Gewinneinheiten)", range=[0, 20]),
                      yaxis=dict(title="Netto-Gewinn gegenüber starrem Plan"))
    return _lock_axes(fig)


def regime_figure(rows):
    """R − S0 je Zelle (Mittel ± Standardfehler), waagerechte Balken; die Zelle der Einstellung ist hervorgehoben (eigene Spur)."""
    import plotly.graph_objects as go

    fig = go.Figure()
    for highlight, name, color in ((False, "gemessene Zelle", C.COLOR_R), (True, "Zelle Ihrer Einstellung", C.COLOR_P)):
        sel = [r for r in rows if r.get("highlight", False) == highlight]
        if not sel:
            continue
        fig.add_trace(go.Bar(y=[r["label"] for r in sel], x=[r["gain"] for r in sel], orientation="h", name=name, marker_color=color,
                             error_x=dict(type="data", array=[r["se"] for r in sel], visible=True, color="#4b5d75", thickness=1.2),
                             hovertemplate="%{y}: R − S0 = %{x:+.1f}<extra></extra>"))
    fig.update_layout(template="plotly_white", height=max(C.CHART_HEIGHT, 26 * len(rows) + 130), barmode="overlay", bargap=0.25,
                      margin=dict(t=20, b=100, l=10, r=10), legend=LEGEND_BOTTOM, xaxis_title="Gewinn der vollen Neuplanung gegenüber dem starren Plan")
    labels = [r["label"] for r in rows]
    # lange Beschriftungen kürzen (der volle Text steht im Hover und in der Tabelle darunter), sonst bleibt auf dem Telefon keine Zeichenfläche
    fig.update_yaxes(autorange="reversed", tickmode="array", tickvals=labels, ticktext=[short_label(t) for t in labels], tickfont=dict(size=10))
    return _lock_axes(fig)


def short_label(label, limit=26):
    """Zellenbeschriftung ohne Klammerzusatz, auf `limit` Zeichen gekürzt."""
    text = label.split(" (")[0]
    return text if len(text) <= limit else text[:limit - 1] + "…"


def measure_figure(cell):
    """Anteil am R-Gewinn bei 50 % der R-Änderungen unter den drei Stabilitätsmaßen (a) (b) (c): Änderungsstrafe P gegen Einfrieren F."""
    import plotly.graph_objects as go

    labels = [R.MEASURES[m] for m in ("a", "b", "c")]
    fig = go.Figure()
    for fam in ("P", "F"):
        vals = [R.share(cell, fam, 50, m) for m in ("a", "b", "c")]
        fig.add_trace(go.Bar(x=labels, y=[None if v is None else 100.0 * v for v in vals], name=C.FAMILY_LABELS[fam],
                             marker_color=C.FAMILY_COLORS[fam], hovertemplate="%{y:.0f} % des R-Gewinns<extra></extra>"))
    fig.update_layout(template="plotly_white", height=C.CHART_HEIGHT - 60, barmode="group", margin=dict(t=20, b=100, l=10, r=10),
                      legend=LEGEND_BOTTOM, yaxis=dict(title="Anteil am R-Gewinn bei 50 % der Änderungen (%)", rangemode="tozero"))
    return _lock_axes(fig)


# ---------------------------------------------------------------------------------------------------
# Kernabschnitt ①: Annahme
# ---------------------------------------------------------------------------------------------------
def accept_live_figure(res):
    """Gewinn gegenüber „nie annehmen“ der Annahmeregeln auf dem Live-Tag (ein Tag, keine Streuung)."""
    import plotly.graph_objects as go

    names = list(C.ACCEPT_ORDER)
    fig = go.Figure(go.Bar(x=names, y=[res["rules"][n]["gain"] for n in names], marker_color=C.COLOR_P,
                           text=[f"{res['rules'][n]['n_acc']} angenommen" for n in names], textposition="outside", cliponaxis=False,
                           customdata=[C.ACCEPT_LABELS[n] for n in names],
                           hovertemplate="%{x} (%{customdata}): %{y:+.0f} gegenüber „nie annehmen“<extra></extra>"))
    fig.update_layout(template="plotly_white", height=C.CHART_HEIGHT - 60, margin=dict(t=30, b=60, l=10, r=10),
                      yaxis=dict(title="Gewinn gegenüber „nie annehmen“"), showlegend=False)
    return _lock_axes(fig)


def accept_measured_figure(bars):
    """Annahme-Messreihe: Mittel ± Standardfehler je Regel und das Rückblick-Orakel (grau); bars aus nv_results.accept_bars."""
    import plotly.graph_objects as go

    fig = go.Figure()
    for is_oracle, name, color in ((False, "Online-Regel", C.COLOR_P), (True, "Rückblick-Orakel (Heuristik)", C.COLOR_S0)):
        sel = [b for b in bars if (b[0] == "Orakel") == is_oracle]
        if not sel:
            continue
        fig.add_trace(go.Bar(x=[b[0] for b in sel], y=[b[1] for b in sel], name=name, marker_color=color,
                             error_y=dict(type="data", array=[b[2] for b in sel], visible=True, color="#4b5d75", thickness=1.2),
                             hovertemplate="%{x}: %{y:.0f} gegenüber „nie annehmen“<extra></extra>"))
    fig.update_layout(template="plotly_white", height=C.CHART_HEIGHT - 40, barmode="group", margin=dict(t=20, b=100, l=10, r=10),
                      legend=LEGEND_BOTTOM, yaxis=dict(title="Gewinn gegenüber „nie annehmen“", rangemode="tozero"))
    return _lock_axes(fig)
