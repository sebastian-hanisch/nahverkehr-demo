"""Plotly-Figuren: Achsen fest (fixedrange), Legende unten, keine Farblisten, Inhalte stimmen mit den Daten überein, keine Warnungen."""
import warnings

import pytest

import nv_constants as C
import nv_live as LV
import nv_results as R
import nv_ui_panel as UI
import nv_visualization as V

DATA = R.load_results()
BASE = R.find_cell(DATA)


@pytest.fixture(scope="module")
def details():
    return {p: LV.day_detail(40, 6, "mittel", 120, 292, p) for p in ("S0", "R", "P1.5")}


def all_axes(fig):
    return {k: v for k, v in fig.layout.to_plotly_json().items() if k.startswith(("xaxis", "yaxis"))}


def check_common(fig, legend=True):
    assert all_axes(fig), "keine Achsen"
    for name, ax in all_axes(fig).items():
        if ax.get("visible") is False:
            continue
        assert ax.get("fixedrange") is True, name                            # Touch-Scrollen der Seite bleibt möglich
    assert fig.layout.template.layout.plot_bgcolor == "white"                # Vorlage plotly_white
    if legend:
        lg = fig.layout.legend.to_plotly_json()
        assert lg.get("orientation") == "h" and lg.get("yanchor") == "bottom" and lg.get("yref") == "container"
    for tr in fig.data:
        marker = getattr(tr, "marker", None)
        if marker is not None:
            for prop in (marker.color, marker.line.color if marker.line is not None else None):
                assert not isinstance(prop, (list, tuple)), tr.name                # Farblisten vermeiden (Warnungen), je Merkmal eine Spur


def build(fn, *args, **kw):
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        return fn(*args, **kw)


@pytest.mark.parametrize("measure", ["a", "b", "c"])
def test_curve_figure(measure):
    fig = build(V.curve_figure, BASE, measure)
    check_common(fig)
    pts = R.curve_points(BASE, measure)
    names = [t.name for t in fig.data]
    assert names == [C.FAMILY_LABELS[f] for f in C.FAMILIES] + ["volle Neuplanung R"]
    for tr, fam in zip(fig.data[:3], C.FAMILIES):
        assert tr.x[0] == 0.0 and tr.y[0] == 0.0 and tr.x[1:] == tuple(p[0] for p in pts[fam]) and tr.y[1:] == tuple(p[1] for p in pts[fam])
        assert tr.text[0] == "S0" and tr.marker.color == C.FAMILY_COLORS[fam]
    r = fig.data[3]
    assert r.x == (pts["R"][0],) and r.y == (pts["R"][1],) and r.marker.color == C.COLOR_R
    assert fig.layout.xaxis.title.text.startswith({"a": "geänderte Stopps", "b": "geänderte Ankunftsansagen", "c": "Neuplanungsereignisse"}[measure])
    assert fig.layout.yaxis.title.text == "Gewinn gegenüber starrem Plan"


@pytest.mark.parametrize("measure", ["a", "b", "c"])
def test_share_figure(measure):
    fig = build(V.share_figure, BASE, measure)
    check_common(fig)
    assert [t.name for t in fig.data] == [C.FAMILY_LABELS[f] for f in C.FAMILIES]
    for tr, fam in zip(fig.data, C.FAMILIES):
        expected = [R.share(BASE, fam, q, measure) for q in (25, 50, 75)]
        assert list(tr.y) == [None if v is None else 100.0 * v for v in expected]
        assert list(tr.x) == [f"bei {q} % der R-Änderungen" for q in (25, 50, 75)]
        if measure == "a":
            ci = [R.share_ci(BASE, fam, q) for q in (25, 50, 75)]
            for v, c, up, down in zip(expected, ci, tr.error_y.array, tr.error_y.arrayminus):
                if v is None or c is None:
                    assert up == 0.0 and down == 0.0
                else:
                    assert up == pytest.approx(max(0.0, 100 * (c[1] - v))) and down == pytest.approx(max(0.0, 100 * (v - c[0])))
        else:
            assert tr.error_y.array is None
    assert any(s["y0"] == 100 for s in fig.layout.shapes)                       # Linie bei 100 %


def test_share_figure_handles_missing_shares():
    cell = dict(BASE, stats={k: (None if k.startswith("share_T") else v) for k, v in BASE["stats"].items()})
    fig = build(V.share_figure, cell)
    assert all(v is None for v in fig.data[2].y)


def test_net_figure_matches_the_net_table():
    fig = build(V.net_figure, BASE, 2.0)
    check_common(fig)
    best, r = fig.data
    assert best.x == r.x and len(best.x) == 41 and best.x[0] == 0.0 and best.x[-1] == 20.0
    for cost, y_best, y_r in zip(best.x, best.y, r.y):
        row = R.net_row(BASE, cost)
        assert y_best == pytest.approx(row["net_over_S0"]) and y_r == pytest.approx(row["net_R_over_S0"])
    assert min(best.y) > 0 > min(r.y) and all(a >= b - 1e-9 for a, b in zip(best.y, r.y))       # der beste Regler liegt nie unter R
    shapes = fig.layout.shapes
    assert any(s["x0"] == 2.0 for s in shapes) and any(s["y0"] == 0 for s in shapes)
    assert not any(s["x0"] == 2.0 for s in build(V.net_figure, BASE).layout.shapes)


def test_regime_figure_highlights_the_selected_cell():
    rows = UI.regime_rows_for_chart(DATA, BASE)
    fig = build(V.regime_figure, rows)
    check_common(fig)
    assert [t.name for t in fig.data] == ["gemessene Zelle", "Zelle Ihrer Einstellung"]
    assert len(fig.data[1].y) == 1 and fig.data[1].y[0] == "Basisfall" and len(fig.data[0].y) == 27
    assert sum(len(t.x) for t in fig.data) == 28
    assert all(se > 0 for t in fig.data for se in t.error_x.array)
    ticks = fig.layout.yaxis
    assert list(ticks.tickvals) == [r["label"] for r in rows] and len(ticks.ticktext) == 28 and all(len(t) <= 26 for t in ticks.ticktext)
    assert V.short_label("Ereignisse viele (Änderungen 0,50 / Stornos 0,16)") == "Ereignisse viele"
    assert V.short_label("27 Morgenaufträge, 2 Fahrzeuge, Rate 4 je Stunde") == "27 Morgenaufträge, 2 Fahr…"
    assert V.short_label("kurz") == "kurz" and V.short_label("a" * 26) == "a" * 26 and V.short_label("a" * 27) == "a" * 25 + "…"
    one = build(V.regime_figure, UI.regime_rows_for_chart(DATA, None))
    assert [t.name for t in one.data] == ["gemessene Zelle"]


def test_measure_figure():
    fig = build(V.measure_figure, BASE)
    check_common(fig)
    assert [t.name for t in fig.data] == [C.FAMILY_LABELS["P"], C.FAMILY_LABELS["F"]]
    assert list(fig.data[0].y) == [pytest.approx(100 * R.share(BASE, "P", 50, m)) for m in "abc"]
    assert list(fig.data[0].x) == [R.MEASURES[m] for m in "abc"]


def test_accept_figures():
    acc = LV.solve_accept(40, 6, 120, 292, 3.0, 1.5)
    fig = build(V.accept_live_figure, acc)
    check_common(fig, legend=False)
    bar = fig.data[0]
    assert list(bar.x) == list(C.ACCEPT_ORDER) and list(bar.y) == [acc["rules"][n]["gain"] for n in C.ACCEPT_ORDER]
    assert list(bar.text) == [f"{acc['rules'][n]['n_acc']} angenommen" for n in C.ACCEPT_ORDER]
    sd = DATA["sameday"]["cells"][0]
    fig = build(V.accept_measured_figure, R.accept_bars(sd))
    check_common(fig)
    assert [t.name for t in fig.data] == ["Online-Regel", "Rückblick-Orakel (Heuristik)"]
    assert list(fig.data[0].x) == ["P1", "P1p", "P2", "P1pL", "P2L", "P4L"] and list(fig.data[1].x) == ["Orakel"]
    assert fig.data[1].y[0] == pytest.approx(sd["oracle"]["ORA"]["mean"]) and fig.data[1].error_y.array[0] == pytest.approx(sd["oracle"]["ORA"]["se"])
    no_ora = build(V.accept_measured_figure, [b for b in R.accept_bars(sd) if b[0] != "Orakel"])
    assert [t.name for t in no_ora.data] == ["Online-Regel"]


def test_events_figure(details):
    view = details["R"]
    others = [("S0", C.COLOR_S0, details["S0"]), ("R", C.COLOR_R, details["R"]), ("P_1,5", C.COLOR_BEST, details["P1.5"])]
    fig = build(V.events_figure, view, others)
    check_common(fig)
    markers = [t for t in fig.data if t.type == "scatter"]
    bars = [t for t in fig.data if t.type == "bar"]
    kinds_present = {e["kind"] for e in view["events"]}
    assert len(markers) == len(kinds_present) and {t.name for t in markers} == {C.EVENT_NAMES[k] for k in kinds_present}
    for tr in markers:
        kind = next(k for k, n in C.EVENT_NAMES.items() if n == tr.name)
        assert len(tr.x) == sum(1 for e in view["events"] if e["kind"] == kind) and tr.marker.color == C.EVENT_COLORS[kind]
    assert [b.name for b in bars] == ["S0", "R", "P_1,5"] and [b.marker.color for b in bars] == [C.COLOR_S0, C.COLOR_R, C.COLOR_BEST]
    for bar, (_, _, det) in zip(bars, others):
        assert sum(bar.y) == det["metrics"]["a"]                              # die Balken summieren sich zu den Änderungen des Tages
    assert sum(bars[0].y) == 0                                               # S0: keine geänderten Stopps
    assert list(fig.layout.xaxis.range) == [0, 480] and list(fig.layout.xaxis2.range) == [0, 480]


def test_tours_figure(details):
    det = details["R"]
    fig = build(V.tours_figure, det)
    check_common(fig)
    named = [t for t in fig.data if t.showlegend is not False]
    assert {t.name for t in named} == {"Morgenauftrag", "neuer Auftrag (Same-Day)", "geänderter Morgenauftrag"}
    n_stops = sum(len(v["stops"]) for v in det["vehicles"])
    assert sum(len(t.x) for t in named) == n_stops
    for tr in named:
        assert all(w > 0 for w in tr.x)                                       # Service-Balken haben Länge
    assert sorted({y for t in named for y in t.y}) == ["Fahrzeug 1", "Fahrzeug 2", "Fahrzeug 3"]
    assert any(s["x0"] == 480 for s in fig.layout.shapes) and fig.layout.yaxis.autorange == "reversed"


def test_route_map_figure(details):
    det = details["R"]
    fig = build(V.route_map_figure, det)
    check_common(fig)
    names = [t.name for t in fig.data]
    assert names.count("Depot") == 1 and "abgelehnter neuer Auftrag" in names
    for i in (1, 2, 3):
        assert f"Fahrzeug {i}" in names
    lines = [t for t in fig.data if t.mode == "lines"]
    assert lines and all(t.showlegend is False for t in lines)                        # die Legende bleibt kurz (sonst drückt sie die Zeichenfläche zusammen)
    assert fig.layout.xaxis.constrain == "domain" and fig.layout.yaxis.constrain == "domain"
    for tr, veh in zip(lines, det["vehicles"]):
        assert tr.x[0] == tr.x[-1] == 30.0 and len(tr.x) == len(veh["stops"]) + 2
    assert fig.layout.yaxis.scaleanchor == "x" and list(fig.layout.xaxis.range) == [-2, 62]
    empty = dict(det, vehicles=[dict(vehicle=1, stops=[], return_time=0, drive=0)], rejected=[])
    build(V.route_map_figure, empty)
    build(V.tours_figure, empty)


def test_every_figure_has_a_unique_purpose_and_no_empty_traces(details):
    figs = [V.curve_figure(BASE), V.share_figure(BASE), V.net_figure(BASE), V.measure_figure(BASE), V.route_map_figure(details["R"])]
    for fig in figs:
        assert len(fig.data) >= 2 and all(t.name for t in fig.data)
