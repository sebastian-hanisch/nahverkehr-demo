"""Fehler-Einbau-Test: baut einzelne Fehler in die Module ein und prüft, ob die Tests (ohne AppTests, die sind zu langsam für viele
Mutanten) sie finden.

Aufruf (im Projektordner): ./venv/Scripts/python.exe tools/mutation_check.py [Teilstring des Dateinamens] [--jobs N]
Jeder Mutant ersetzt genau eine Stelle; Überlebende sind entweder gleichwertig (kein sichtbarer Unterschied) oder eine Lücke der
Tests. Jeder Mutant läuft in einer eigenen temporären Kopie (deshalb parallel möglich, Standard 6 Jobs); PYTHONDONTWRITEBYTECODE=1,
damit veralteter Bytecode keine Überlebenden vortäuscht; Quelltexte als LF (Windows-Python schreibt sonst CRLF und die Zeichenketten
unten finden nichts).

Selbstprüfung (Baseline): VOR den Mutanten läuft eine UNVERÄNDERTE Kopie gegen die Tests, für ein Kernmodul und für ein
Randmodul. Besteht sie nicht, bricht das Werkzeug ab: sonst wäre jeder "gefundene" Mutant vorgetäuscht (in wellenfreigabe-demo
fehlte der Kopie zuerst das README, das test_claims.py liest, und alle Läufe waren ungültig). Die Kopie enthält deshalb das ganze
Projekt: alle *.py, README.md, data/, tests/ (mit tests/data) und tools/.

Die Mutanten sind maschinell erzeugt (Vergleichsoperatoren, Plus/Minus, and/or, True/False, min/max, Zahlen +1 bzw. +10 %) und stichprobenartig
über alle Module verteilt (feste Zufallszahlen), jeweils mit gerade so viel Umgebung, dass die Stelle im Quelltext eindeutig ist.

Die Tests der Kernmodule laufen mit den EINGEFRORENEN Morgenplänen (tests/data/nv_morning.json): kein Mutant hängt von der OR-Tools-Version ab.

Reihenfolge: die Tests des Moduls laufen zuerst, damit ein gefundener Mutant schnell scheitert; die langsamen Modelltests
(test_checks.py, test_frozen_reference.py) laufen nur für die Modelldateien.

Bewusst NICHT als Mutanten geführt (gleichwertig, kein sichtbarer Unterschied) - siehe EQUIVALENT_NOTES."""
import concurrent.futures as cf
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")                # die Mutanten enthalten Emoji und Umlaute

ROOT = pathlib.Path(__file__).resolve().parent.parent
PY = sys.executable
TIMEOUT = 420
CORE = ("nv_model.py", "nv_sim.py", "nv_oracle.py")
APP_TESTS = ("tests/test_app.py",)
SLOW_CORE_TESTS = ("tests/test_checks.py", "tests/test_frozen_reference.py")
# Testdateien, die ein Modul zuerst prüfen (schnelles Scheitern); der Rest folgt in Dateireihenfolge
FIRST = {
    "nv_model.py": ["test_frozen_reference.py", "test_model_units.py"], "nv_sim.py": ["test_frozen_reference.py", "test_model_units.py"],
    "nv_oracle.py": ["test_model_units.py", "test_checks.py"], "nv_live.py": ["test_live.py"], "nv_results.py": ["test_results.py"],
    "nv_stories.py": ["test_stories.py"], "nv_presets.py": ["test_presets.py"], "nv_visualization.py": ["test_visualization.py"],
    "nv_pdf_export.py": ["test_pdf_export.py"], "nv_ui_panel.py": ["test_ui_panel.py"], "nv_constants.py": ["test_presets.py", "test_results.py"],
    "nv_format.py": ["test_ui_panel.py"], "tools/build_results.py": ["test_tools.py"],
}

EQUIVALENT_NOTES = """
Von den 533 maschinell erzeugten Mutanten sind 74 bewusst NICHT geführt (gleichwertig oder ohne beobachtbares Verhalten); die übrigen 459 werden alle gefunden.
Der erste vollständige Lauf ließ 142 überleben; 68 davon schlossen Testlücken (Tests in tests/test_mutation_gaps.py), 74 sind begründet ausgenommen:

(1) Gleichheit von Gleitkommazahlen (Maß null): `u < p` gegen `u <= p` bei den Zufallszahlen des Ereignisstroms (3 Stellen in make_events), der Vergleich
    `abs(a - b) < 1e-9` in den Tabellen (2 Stellen), das Ereignis genau zur Schichtende-Minute `t_e >= H` (mit den Standardparametern nicht erreichbar).
(2) OR-Tools-Modellparameter, die nur die Lösung des Solvers verändern, deren exakte Routen die Tests absichtlich nicht prüfen (die CI installiert immer das
    neueste OR-Tools): fix_start_cumul_to_zero, Slack der Kapazitätsdimension, Umrechnung der Zeitgrenze in Millisekunden, die Zusatzbedingung für mehrere Touren
    je Fahrzeug (M > 1, in den Sweeps nie genutzt), die Prüfung leerer Fenster (a == b), die Disjunktion einzelner Knoten, das Vorgabe-solution_limit (14 Stellen
    in nv_model.oracle und nv_oracle.oracle_ev). Sie sind über Invarianten (gültig, nie schlechter als der Warmstart, Brute-Force auf Kleinstinstanzen) abgesichert.
(3) Gleichwertige Umformungen: `lam > 0 and base_pred` gegen `or` (bei lam = 0 ist die Strafprüfung wirkungslos), `n != 0 and is_sd` gegen `or` (Morgenaufträge haben
    Erlös 0), `cfg.lam > 0` im Rollout (ohne Rate gibt es keine Ankünfte, die Schleife läuft nie), `is_sd` der Szenarioknoten (wird dort nie gelesen), die
    Reihenfolge-Nummer im Sortierschlüssel der Ereignisse (gleiche Ordnung), `va > vb` bei exaktem Gleichstand von Annehmen und Ablehnen, `maxsize` des Ladecaches,
    das Vorgabe-`digits` von `_de` (immer explizit), das Vorzeichen `sign > 0` (nur +1 und -1), `net_best > net_R` (P_1,5 ist nie gleich R), das Vorzeichen des
    negativen R-Netto in der Meldung „verliert", `and` statt `or` in cross_frame (die Zelle hat immer ein Gegenstück), `isinstance(x, bool) or x is None`, argv-Ausschnitt
    im Aufruf als Skript.
(4) Nur Gleichstände der Einfügeposition im Morgenplan-Aufbau bei t = -1 für ein leeres Fahrzeug (`n > 0`, Vorgabe -1 der lokalen Suche): das OR-Tools-Ergebnis ersetzt den
    Plan ohnehin fast immer; der Aufbau selbst ist über eingefrorene Heuristik-Routen (tests/data/nv_heuristic.json) abgesichert.
(5) Abstimmungskonstanten ohne fachliche Vorgabe: die Skalen der Zellen-Zuordnung der Annahme (12 / 60), die Größe des st.cache_data-Speichers.
(6) Darstellung ohne Verhaltensänderung: Ränder, Höhen, Deckkraft, Zeilenanteile und Markergrößen der Plotly-Figuren (13 Stellen), Zeilenhöhen, Spaltenbreiten,
    Schriftgrößen und Seitenumbruch-Schwelle des PDF (15 Stellen), die Höhe der Halteliste, die Rundung der gemessenen Sekunden und der Kilobyte-Angabe.
"""

MUTANTS = [
    ('nv_model.py', ' 3 ', ' 4 '),
    ('nv_model.py', '14', '15'),
    ('nv_model.py', '120', '121'),
    ('nv_model.py', '0.6', '0.66'),
    ('nv_model.py', 'oat = 0.0     #', 'oat = 0.1     #'),
    ('nv_model.py', '/ 2)]', '/ 3)]'),
    ('nv_model.py', '[False]', '[True]'),
    ('nv_model.py', 'y - s', 'y + s'),
    ('nv_model.py', ' [0])', ' [1])'),
    ('nv_model.py', 'H - s', 'H + s'),
    ('nv_model.py', '] - c', '] + c'),
    ('nv_model.py', '[j] - T[p', '[j] + T[p'),
    ('nv_model.py', 'e] <= t:', 'e] < t:'),
    ('nv_model.py', '= dep + T[pre', '= dep - T[pre'),
    ('nv_model.py', 's > B', 's >= B'),
    ('nv_model.py', 'e == 0', 'e != 0'),
    ('nv_model.py', ' sum(1 for ', ' sum(2 for '),
    ('nv_model.py', ' x == 0)', ' x != 0)'),
    ('nv_model.py', 'n == 0', 'n != 0'),
    ('nv_model.py', '   if m == n and F', '   if m != n and F'),
    ('nv_model.py', 'n and F', 'n or F'),
    ('nv_model.py', '1] <= t ', '1] < t '),
    ('nv_model.py', '1] != 0:', '1] == 0:'),
    ('nv_model.py', '   if m == n and r', '   if m != n and r'),
    ('nv_model.py', '1] != 0 ', '1] == 0 '),
    ('nv_model.py', '] != 0 and ', '] != 1 and '),
    ('nv_model.py', 'route[-1]][0] <', 'route[-2]][0] <'),
    ('nv_model.py', 'e + [', 'e - ['),
    ('nv_model.py', 'S + [', 'S - ['),
    ('nv_model.py', 'p < n', 'p <= n'),
    ('nv_model.py', 'v][x] + T[x][', 'v][x] - T[x]['),
    ('nv_model.py', 't] - T[', 't] + T['),
    ('nv_model.py', 'p] + [x', 'p] - [x'),
    ('nv_model.py', '= F[-1] + i', '= F[-2] + i'),
    ('nv_model.py', '[min(', '[max('),
    ('nv_model.py', '> 0 a', '> 1 a'),
    ('nv_model.py', ') - c', ') + c'),
    ('nv_model.py', 'turn [(mv[1], mv[3])]', 'turn [(mv[2], mv[3])]'),
    ('nv_model.py', 'mv[3])]', 'mv[4])]'),
    ('nv_model.py', 'mv[3]),', 'mv[4]),'),
    ('nv_model.py', '7', '8'),
    ('nv_model.py', 'L + 1', 'L - 1'),
    ('nv_model.py', 'L < n', 'L <= n'),
    ('nv_model.py', 'v][seg[0]] + T[seg[-1]]', 'v][seg[0]] - T[seg[-1]]'),
    ('nv_model.py', 'q == i', 'q != i'),
    ('nv_model.py', 'q - 1] if', 'q - 2] if'),
    ('nv_model.py', 'q > 0', 'q >= 0'),
    ('nv_model.py', 's >= g', 's > g'),
    ('nv_model.py', 'd[:q] + seg +', 'd[:q] - seg +'),
    ('nv_model.py', 'u, min(i,', 'u, max(i,'),
    ('nv_model.py', 's, g - ins)', 's, g + ins)'),
    ('nv_model.py', 'w[:q] + seg +', 'w[:q] - seg +'),
    ('nv_model.py', 'w, g - ins)', 'w, g + ins)'),
    ('nv_model.py', '[i + 1]', '[i - 1]'),
    ('nv_model.py', 'i + 1] if', 'i + 2] if'),
    ('nv_model.py', ' i + 1 ', ' i - 1 '),
    ('nv_model.py', 'i + 1 < n', 'i + 2 < n'),
    ('nv_model.py', ' 1 < nw', ' 1 <= nw'),
    ('nv_model.py', 'y] + T[', 'y] - T['),
    ('nv_model.py', 'u] - T[', 'u] + T['),
    ('nv_model.py', ') + (', ') - ('),
    ('nv_model.py', 'w[j + 1:]', 'w[j - 1:]'),
    ('nv_model.py', '   if 0 in ru', '   if 1 in ru'),
    ('nv_model.py', 'nu0] - T[pw', 'nu0] + T[pw'),
    ('nv_model.py', 'i] + rw', 'i] - rw'),
    ('nv_model.py', '(i + 1,', '(i - 1,'),
    ('nv_model.py', '] if j + 1 < nu', '] if j - 1 < nu'),
    ('nv_model.py', ' j + 1 < nu', ' j + 2 < nu'),
    ('nv_model.py', 'i]][nx] - T[pv][r', 'i]][nx] + T[pv][r'),
    ('nv_model.py', ':-1] ', ':-2] '),
    ('nv_model.py', '1] + ru', '1] - ru'),
    ('nv_model.py', '][:p] + res[0', '][:p] - res[0'),
    ('nv_model.py', 'w][:jw] + res_w[0', 'w][:jw] - res_w[0'),
    ('nv_model.py', 'e and o', 'e or o'),
    ('nv_model.py', '3 + 1', '3 - 1'),
    ('nv_model.py', 'm.randint(1, cfg.dem_', 'm.randint(2, cfg.dem_'),
    ('nv_model.py', 'w - 6', 'w + 6'),
    ('nv_model.py', 'e and -', 'e or -'),
    ('nv_model.py', '] < f', '] <= f'),
    ('nv_model.py', 's.randint(1, cfg.dem_', 's.randint(2, cfg.dem_'),
    ('nv_model.py', 'x, 0.0), ', 'x, 0.1), '),
    ('nv_model.py', ', min(m', ', max(m'),
    ('nv_model.py', 'in(max(gy', 'in(min(gy'),
    ('nv_model.py', 'y, 0.0), ', 'y, 0.1), '),
    ('nv_model.py', 'v = max(5, ', 'v = min(5, '),
    ('nv_model.py', '* 2 /', '* 3 /'),
    ('nv_model.py', '3 + 3', '3 - 3'),
    ('nv_model.py', ', rs.uniform(10, cfg.area - ', ', rs.uniform(11, cfg.area - '),
    ('nv_model.py', 'r > c', 'r >= c'),
    ('nv_model.py', 'r + c', 'r - c'),
    ('nv_model.py', ' 4)', ' 5)'),
    ('nv_model.py', '= 1 i', '= 2 i'),
    ('nv_model.py', '0.5', '0.55'),
    ('nv_model.py', 'rm(0, 2', 'rm(1, 2'),
    ('nv_model.py', ', 2 *', ', 3 *'),
    ('nv_model.py', 'ts[0] e', 'ts[1] e'),
    ('nv_model.py', '] + w', '] - w'),
    ('nv_model.py', ' 5 ', ' 6 '),
    ('nv_model.py', 'ax(5, p', 'ax(6, p'),
    ('nv_model.py', ' 10 ', ' 11 '),
    ('nv_model.py', '0 - i', '0 + i'),
    ('nv_model.py', 'd != "', 'd == "'),
    ('nv_model.py', 'nd == "a', 'nd != "a'),
    ('nv_model.py', 'x = min(max', 'x = max(max'),
    ('nv_model.py', 's(ang), 0.0), cfg.a', 's(ang), 0.1), cfg.a'),
    ('nv_model.py', '  y = min(max(y', '  y = max(max(y'),
    ('nv_model.py', 'n(max(y', 'n(min(y'),
    ('nv_model.py', 'n(ang), 0.0), cfg.a', 'n(ang), 0.1), cfg.a'),
    ('nv_model.py', 'n(max(d', 'n(min(d'),
    ('nv_model.py', 'x + 2', 'x - 2'),
    ('nv_model.py', ' = 0, 0', ' = 1, 0'),
    ('nv_model.py', 'e != 0', 'e == 0'),
    ('nv_model.py', ')] + in', ')] - in'),
    ('nv_model.py', '=sum(1 for ', '=sum(2 for '),
    ('nv_sim.py', 'max', 'min'),
    ('nv_sim.py', '(0.0,', '(0.1,'),
    ('nv_sim.py', ' 1.0 ', ' 1.1 '),
    ('nv_sim.py', '0 - t', '0 + t'),
    ('nv_sim.py', ': str, mu: float = 0.0, rho: float = 0.0,', ': str, mu: float = 0.1, rho: float = 0.0,'),
    ('nv_sim.py', ' = 0.0, l', ' = 0.1, l'),
    ('nv_sim.py', ' = False, v', ' = True, v'),
    ('nv_sim.py', 'ind == "P0', 'ind != "P0'),
    ('nv_sim.py', '         best = min(cs, key=lambda cd: (c * cd[0] + mu * w * cd[1], cd[0], cd[1], cd[2], cd[3])', '         best = min(cs, key=lambda cd: (c * cd[1] + mu * w * cd[1], cd[0], cd[1], cd[2], cd[3])'),
    ('nv_sim.py', ' = c * best[0] + mu * w *', ' = c * best[1] + mu * w *'),
    ('nv_sim.py', ' = c * best[0] + mu * w * best[', ' = c * best[0] - mu * w * best['),
    ('nv_sim.py', 'ev >= co', 'ev > co'),
    ('nv_sim.py', '         ok = rev >= dc and rev >= rho', '         ok = rev > dc and rev >= rho'),
    ('nv_sim.py', '= sum(1 for c', '= sum(2 for c'),
    ('nv_sim.py', '[:4] ', '[:5] '),
    ('nv_sim.py', '] == b', '] != b'),
    ('nv_sim.py', '[:4])', '[:5])'),
    ('nv_sim.py', '[:4],', '[:5],'),
    ('nv_sim.py', '= dict(profit=rev_acc - c * drive, drive=driv', '= dict(profit=rev_acc + c * drive, drive=driv'),
    ('nv_sim.py', ': str, mu: float = 0.0, rho: float = 0.0)', ': str, mu: float = 0.1, rho: float = 0.0)'),
    ('nv_sim.py', '= 0.0):', '= 0.1):'),
    ('nv_sim.py', 'n False, ', 'n True, '),
    ('nv_sim.py', 'ev >= c ', 'ev > c '),
    ('nv_sim.py', '>= c * best[0] + mu * w *', '>= c * best[1] + mu * w *'),
    ('nv_sim.py', '>= c * best[0] + mu * w * best[', '>= c * best[0] - mu * w * best['),
    ('nv_sim.py', 'st[1], ', 'st[2], '),
    ('nv_sim.py', '16', '17'),
    ('nv_sim.py', ' = False, m', ' = True, m'),
    ('nv_sim.py', '= 0.0) ', '= 0.1) '),
    ('nv_sim.py', '7_919', '8710.9'),
    ('nv_sim.py', '9 + x', '9 - x'),
    ('nv_sim.py', '104_729', '115201.9'),
    ('nv_sim.py', '9 + 1', '9 - 1'),
    ('nv_sim.py', '17', '18'),
    ('nv_sim.py', ' True:', ' False:'),
    ('nv_sim.py', '60.0', '66.0'),
    ('nv_sim.py', 'r > c', 'r >= c'),
    ('nv_sim.py', 'r + c', 'r - c'),
    ('nv_sim.py', '(0,', '(1,'),
    ('nv_sim.py', ', 1):', ', 2):'),
    ('nv_sim.py', 'n - c', 'n + c'),
    ('nv_sim.py', ') > n', ') >= n'),
    ('nv_sim.py', 'n dict(profit=rev_acc - c * drive, drive=driv', 'n dict(profit=rev_acc + c * drive, drive=driv'),
    ('nv_sim.py', '=0,', '=1,'),
    ('nv_sim.py', '=0)', '=1)'),
    ('nv_sim.py', '= 15  ', '= 16  '),
    ('nv_sim.py', 'j >= m', 'j > m'),
    ('nv_sim.py', 'n sum(1 for n', 'n sum(2 for n'),
    ('nv_sim.py', 'w and n', 'w or n'),
    ('nv_sim.py', '] != v', '] == v'),
    ('nv_sim.py', 'x] + ro', 'x] - ro'),
    ('nv_sim.py', '] + [', '] - ['),
    ('nv_sim.py', 'w] + ro', 'w] - ro'),
    ('nv_sim.py', 't = 0, la', 't = 1, la'),
    ('nv_sim.py', ' = 0.0, T', ' = 0.1, T'),
    ('nv_sim.py', 't = 0, lo', 't = 1, lo'),
    ('nv_sim.py', ' 0)', ' 1)'),
    ('nv_sim.py', 'l": 0, "t', 'l": 1, "t'),
    ('nv_sim.py', 'e": 0, "a', 'e": 1, "a'),
    ('nv_sim.py', 'r": 0, "q', 'r": 1, "q'),
    ('nv_sim.py', ' 0}', ' 1}'),
    ('nv_sim.py', ', 0, ', ', 1, '),
    ('nv_sim.py', 't[0],', 't[1],'),
    ('nv_sim.py', 'it[1], ', 'it[2], '),
    ('nv_sim.py', 'p == "', 'p != "'),
    ('nv_sim.py', '<', '<='),
    ('nv_sim.py', '] == "', '] != "'),
    ('nv_sim.py', 'elif kind == "T" and T', 'elif kind != "T" and T'),
    ('nv_sim.py', '" and T', '" or T'),
    ('nv_sim.py', 'r == 0', 'r != 0'),
    ('nv_sim.py', 'elif kind == "T" and t', 'elif kind != "T" and t'),
    ('nv_sim.py', '" and t', '" or t'),
    ('nv_sim.py', 't >= n', 't > n'),
    ('nv_sim.py', 'r + 1', 'r - 1'),
    ('nv_sim.py', '+ 1) ', '+ 2) '),
    ('nv_sim.py', 'nd == "F', 'nd != "F'),
    ('nv_sim.py', 'nd == "H', 'nd != "H'),
    ('nv_sim.py', 't + H', 't - H'),
    ('nv_sim.py', 'ind == "P"', 'ind != "P"'),
    ('nv_sim.py', '] == o', '] != o'),
    ('nv_sim.py', 'N and o', 'N or o'),
    ('nv_sim.py', 'n and a', 'n or a'),
    ('nv_sim.py', '] - a', '] + a'),
    ('nv_sim.py', ') > E', ') >= E'),
    ('nv_sim.py', 'a > 0', 'a >= 0'),
    ('nv_sim.py', 'n != 0', 'n == 0'),
    ('nv_sim.py', ' 0]', ' 1]'),
    ('nv_sim.py', '= sum(1 for n', '= sum(2 for n'),
    ('nv_sim.py', 'd - c', 'd + c'),
    ('nv_sim.py', 'e - c', 'e + c'),
    ('nv_sim.py', 't + i', 't - i'),
    ('nv_sim.py', '=sum(1 for ', '=sum(2 for '),
    ('nv_oracle.py', '= max(i', '= min(i'),
    ('nv_oracle.py', 'm + c', 'm - c'),
    ('nv_oracle.py', '= max(t', '= min(t'),
    ('nv_oracle.py', '(t + T[', '(t - T['),
    ('nv_oracle.py', 'm - c', 'm + c'),
    ('nv_oracle.py', '] + i', '] - i'),
    ('nv_oracle.py', 'n][0] >', 'n][1] >'),
    ('nv_oracle.py', '][1])', '][2])'),
    ('nv_oracle.py', ' 0:', ' 1:'),
    ('nv_results.py', '(0.0,', '(0.1,'),
    ('nv_results.py', ' 0.5,', ' 0.55,'),
    ('nv_results.py', ' 2.0,', ' 2.2,'),
    ('nv_results.py', '5.0', '5.5'),
    ('nv_results.py', ' 12.0,', ' 13.2,'),
    ('nv_results.py', '20.0', '22.0'),
    ('nv_results.py', 'n > f', 'n >= f'),
    ('nv_results.py', 'n < -', 'n <= -'),
    ('nv_results.py', 'a - p', 'a + p'),
    ('nv_results.py', '_m"] != base', '_m"] == base'),
    ('nv_results.py', '] or c', '] and c'),
    ('nv_results.py', 'r cfg["K"] != base["K"]:', 'r cfg["K"] == base["K"]:'),
    ('nv_results.py', 'f cfg["K"] != base["K"] ', 'f cfg["K"] == base["K"] '),
    ('nv_results.py', 'delta"] != base["d', 'delta"] == base["d'),
    ('nv_results.py', ') != (', ') == ('),
    ('nv_results.py', '], 2)}"', '], 3)}"'),
    ('nv_results.py', 's != (', 's == ('),
    ('nv_results.py', ' 0]', ' 1]'),
    ('nv_results.py', 'delta"] != base["c', 'delta"] == base["c'),
    ('nv_results.py', 'f any(c', 'f all(c'),
    ('nv_results.py', 'k] != ba', 'k] == ba'),
    ('nv_results.py', '=3,', '=4,'),
    ('nv_results.py', '0.6', '0.66'),
    ('nv_results.py', '=60.0,', '=66.0,'),
    ('nv_results.py', '] == v', '] != v'),
    ('nv_results.py', '] - r', '] + r'),
    ('nv_results.py', '] - d', '] + d'),
    ('nv_results.py', "(g['lam'], 0)} je Stund", "(g['lam'], 1)} je Stund"),
    ('nv_results.py', 'e or e', 'e and e'),
    ('nv_results.py', '] - c', '] + c'),
    ('nv_results.py', '] > n', '] >= n'),
    ('nv_results.py', '[best] - net["R', '[best] + net["R'),
    ('nv_results.py', 'r < 0', 'r <= 0'),
    ('nv_results.py', 'me == "R', 'me != "R'),
    ('nv_results.py', 'e[0]}', 'e[1]}'),
    ('nv_results.py', '[1:', '[2:'),
    ('nv_results.py', '[measure] - x0, pol[p', '[measure] + x0, pol[p'),
    ('nv_results.py', '] == f', '] != f'),
    ('nv_results.py', 'm and p', 'm or p'),
    ('nv_results.py', 'p != "', 'p == "'),
    ('nv_results.py', '", 50), ', '", 51), '),
    ('nv_results.py', '" if measure == "a" else f"F', '" if measure != "a" else f"F'),
    ('nv_results.py', '(1 ', '(2 '),
    ('nv_results.py', '< 0),', '< 1),'),
    ('nv_results.py', '=50)', '=51)'),
    ('nv_results.py', '/ 2] ', '/ 3] '),
    ('nv_results.py', ' 0.5 ', ' 0.55 '),
    ('nv_results.py', '2 - 1', '2 + 1'),
    ('nv_results.py', '/ 2])', '/ 3])'),
    ('nv_results.py', ') and c', ') or c'),
    ('nv_results.py', ')[1])', ')[2])'),
    ('nv_stories.py', '0.75', '0.825'),
    ('nv_stories.py', '0.70', '0.77'),
    ('nv_stories.py', ' 5.0 ', ' 5.5 '),
    ('nv_stories.py', 'X_GAIN = 40.0         ', 'X_GAIN = 44.0         '),
    ('nv_stories.py', 'False', 'True'),
    ('nv_stories.py', 'n, 1, T', 'n, 2, T'),
    ('nv_stories.py', 'p50, 0)} %"', 'p50, 1)} %"'),
    ('nv_stories.py', '12.0', '13.2'),
    ('nv_stories.py', 'n"] >= MAN', 'n"] > MAN'),
    ('nv_stories.py', ') and r', ') or r'),
    ('nv_stories.py', 'n"] < ONL', 'n"] <= ONL'),
    ('nv_stories.py', '60', '61'),
    ('nv_stories.py', '] < 0', '] <= 0'),
    ('nv_stories.py', '< 0, ', '< 1, '),
    ('nv_stories.py', '] == E', '] != E'),
    ('nv_stories.py', ' 1, True)} "', ' 1, False)} "'),
    ('nv_stories.py', "R'], 1, True)} gegen", "R'], 1, False)} gegen"),
    ('nv_stories.py', "e R: {_de(nets[b] - nets['S0'], 0, True)} gegenüber {_de(nets['R'] - nets[", "e R: {_de(nets[b] - nets['S0'], 0, False)} gegenüber {_de(nets['R'] - nets["),
    ('nv_stories.py', 'r, 0, True)}"), ', 'r, 0, False)}"), '),
    ('nv_stories.py', '] > 0, f"', '] > 1, f"'),
    ('nv_stories.py', '] == 0', '] != 0'),
    ('nv_stories.py', '= 0, ', '= 1, '),
    ('nv_stories.py', 'r < D', 'r <= D'),
    ('nv_stories.py', '3["profit_total"] - s0["profit_total"', '3["profit_total"] + s0["profit_total"'),
    ('nv_stories.py', 'p > 0', 'p >= 0'),
    ('nv_stories.py', 'p > 0, f"', 'p > 1, f"'),
    ('nv_stories.py', 'p, 0, True)}"), ', 'p, 0, False)}"), '),
    ('nv_stories.py', 'f, 0, T', 'f, 1, T'),
    ('nv_stories.py', ": {_de(nets['R'] - nets['S0'], 0, T", ": {_de(nets['R'] + nets['S0'], 0, T"),
    ('nv_stories.py', '] > n', '] >= n'),
    ('nv_stories.py', "r R: {_de(nets[b] - nets['S0'], 0, Tr", "r R: {_de(nets[b] + nets['S0'], 0, Tr"),
    ('nv_stories.py', 'gegenüber {_de(nets[\'R\'] - nets[\'S0\'], 0, True)}")]', 'gegenüber {_de(nets[\'R\'] + nets[\'S0\'], 0, True)}")]'),
    ('nv_presets.py', '=True)', '=False)'),
    ('nv_presets.py', ' and ', ' or '),
    ('nv_presets.py', 'n min(s', 'n max(s'),
    ('nv_presets.py', ' - ', ' + '),
    ('nv_presets.py', '= max(s', '= min(s'),
    ('nv_presets.py', ', min(s', ', max(s'),
    ('nv_presets.py', '(min(', '(max('),
    ('nv_presets.py', ', max(s', ', min(s'),
    ('nv_constants.py', '(16,', '(17,'),
    ('nv_constants.py', '2, 6, 1', '2, 7, 1'),
    ('nv_constants.py', ', 12),', ', 13),'),
    ('nv_constants.py', ' 6 ', ' 7 '),
    ('nv_constants.py', ' 0.0)', ' 0.1)'),
    ('nv_constants.py', '(0.1,', '(0.11,'),
    ('nv_constants.py', '0.03', '0.033'),
    ('nv_constants.py', ': (0.25, 0', ': (0.275, 0'),
    ('nv_constants.py', ' 0.08)', ' 0.088)'),
    ('nv_constants.py', '(60, 120, 240', '(60, 121, 240'),
    ('nv_constants.py', ' 120 ', ' 121 '),
    ('nv_constants.py', 'm=40, ', 'm=41, '),
    ('nv_constants.py', '=0.25,', '=0.275,'),
    ('nv_constants.py', '=0.08,', '=0.088,'),
    ('nv_constants.py', ' 9,', ' 10,'),
    ('nv_constants.py', 'e=1.0, ', 'e=1.1, '),
    ('nv_constants.py', '= 200  ', '= 201  '),
    ('nv_constants.py', ' 60 ', ' 61 '),
    ('nv_constants.py', '(1,', '(2,'),
    ('nv_constants.py', ', 4, ', ', 5, '),
    ('nv_constants.py', '4, 6, 8', '4, 7, 8'),
    ('nv_constants.py', ' 8,', ' 9,'),
    ('nv_constants.py', ' 1.0,', ' 1.1,'),
    ('nv_constants.py', '8.0', '8.8'),
    ('nv_constants.py', '0, 60, 9', '0, 61, 9'),
    ('nv_constants.py', '") + tu', '") - tu'),
    ('nv_constants.py', 'd": dict(morning=40, rate=6, events=', 'd": dict(morning=41, rate=6, events='),
    ('nv_constants.py', 'morning=40, rate=1', 'morning=41, rate=1'),
    ('nv_constants.py', '=60,', '=61,'),
    ('nv_format.py', 'm(v, digits=1, signed=Fal', 'm(v, digits=2, signed=Fal'),
    ('nv_format.py', 't(v, digits=1, signed=Fal', 't(v, digits=2, signed=Fal'),
    ('nv_format.py', '100.0', '110.0'),
    ('nv_format.py', 'e, digits=1, signed=T', 'e, digits=2, signed=T'),
    ('nv_format.py', 'True', 'False'),
    ('nv_format.py', '=0)', '=1)'),
    ('nv_format.py', '[0]', '[1]'),
    ('nv_format.py', '[1]', '[2]'),
    ('nv_format.py', ' 60}', ' 61}'),
    ('nv_format.py', ' 60:', ' 61:'),
    ('nv_ui_panel.py', 'd=False):', 'd=True):'),
    ('nv_ui_panel.py', 'l"] - cos', 'l"] + cos'),
    ('nv_ui_panel.py', 't] - ne', 't] + ne'),
    ('nv_ui_panel.py', '"] - ne', '"] + ne'),
    ('nv_ui_panel.py', "n'], True)} ge", "n'], False)} ge"),
    ('nv_ui_panel.py', 's[2].', 's[3].'),
    ('nv_ui_panel.py', "r_over_s0'], True)} gegenüber ", "r_over_s0'], False)} gegenüber "),
    ('nv_ui_panel.py', "_R_over_S0'], True)} gegenüber d", "_R_over_S0'], False)} gegenüber d"),
    ('nv_ui_panel.py', ' 100.0 ', ' 110.0 '),
    ('nv_ui_panel.py', '1.0', '1.1'),
    ('nv_ui_panel.py', '>', '>='),
    ('nv_ui_panel.py', '], True)},', '], False)},'),
    ('nv_ui_panel.py', 'n"], True), F.', 'n"], False), F.'),
    ('nv_ui_panel.py', ', 0, True)}, M', ', 0, False)}, M'),
    ('nv_ui_panel.py', '0], 0, Tr', '0], 1, Tr'),
    ('nv_ui_panel.py', 'q[2],', 'q[3],'),
    ('nv_ui_panel.py', '0, True)}]', '0, False)}]'),
    ('nv_ui_panel.py', '(100.0 ', '(110.0 '),
    ('nv_ui_panel.py', '], 1)} ', '], 2)} '),
    ('nv_ui_panel.py', 'd"] == "ca', 'd"] != "ca'),
    ('nv_ui_panel.py', '][1])', '][2])'),
    ('nv_ui_panel.py', '[100 ', '[101 '),
    ('nv_ui_panel.py', 'c"] - cos', 'c"] + cos'),
    ('nv_ui_panel.py', '] or 0', '] and 0'),
    ('nv_ui_panel.py', ' 0.0)', ' 0.1)'),
    ('nv_ui_panel.py', '] - e', '] + e'),
    ('nv_ui_panel.py', 'm == "', 'm != "'),
    ('nv_ui_panel.py', 'F", 50, m)', 'F", 51, m)'),
    ('nv_ui_panel.py', "5['mean'], 1, True)} {F", "5['mean'], 2, True)} {F"),
    ('nv_ui_panel.py', "5['mean'], 1, True)} {F.fmt_ci(f", "5['mean'], 1, False)} {F.fmt_ci(f"),
    ('nv_ui_panel.py', "0['mean'], 1, True)} {F", "0['mean'], 2, True)} {F"),
    ('nv_ui_panel.py', "5']['mean'], 1, True)} {F.fmt_ci(d['", "5']['mean'], 1, False)} {F.fmt_ci(d['"),
    ('nv_ui_panel.py', "0']['mean'], 1, True)} {F.fmt_ci(d['", "0']['mean'], 1, False)} {F.fmt_ci(d['"),
    ('nv_ui_panel.py', '(r["mu"] - par["mu"', '(r["mu"] + par["mu"'),
    ('nv_ui_panel.py', '(r["mu"] - par["mu_', '(r["mu"] + par["mu_'),
    ('nv_ui_panel.py', '0, False), ', '0, True), '),
    ('nv_ui_panel.py', '] or (', '] and ('),
    ('nv_ui_panel.py', ') == (', ') != ('),
    ('nv_ui_panel.py', '6.0', '6.6'),
    ('nv_ui_panel.py', '120', '121'),
    ('nv_visualization.py', 's=1, ', 's=2, '),
    ('nv_visualization.py', '(range=[0, view["', '(range=[1, view["'),
    ('nv_visualization.py', '], row=2, col=1', '], row=3, col=1'),
    ('nv_visualization.py', '"] - s[', '"] + s['),
    ('nv_visualization.py', '1] - s[', '1] + s['),
    ('nv_visualization.py', '55', '56'),
    ('nv_visualization.py', 'e=[0, d', 'e=[1, d'),
    ('nv_visualization.py', '"]] + [dx', '"]] - [dx'),
    ('nv_visualization.py', 'EIGHT + 60, m', 'EIGHT - 60, m'),
    ('nv_visualization.py', 'ct(range=[-2, a + 2], t', 'ct(range=[-3, a + 2], t'),
    ('nv_visualization.py', 'ct(range=[-2, a + 2], s', 'ct(range=[-3, a + 2], s'),
    ('nv_visualization.py', '-2, a + 2], s', '-2, a - 2], s'),
    ('nv_visualization.py', '0.0] + [p[1', '0.0] - [p[1'),
    ('nv_visualization.py', '"] + [R', '"] - [R'),
    ('nv_visualization.py', 'y=[0.0 if (ci is None or v is None) else max(0', 'y=[0.0 if (ci is None and v is None) else max(0'),
    ('nv_visualization.py', 'v is None) else max(0.0, 100.0 * (c', 'v is None) else min(0.0, 100.0 * (c'),
    ('nv_visualization.py', '0.0, 100.0 * (v', '0.0, 110.0 * (v'),
    ('nv_visualization.py', 'v - c', 'v + c'),
    ('nv_visualization.py', '(0,', '(1,'),
    ('nv_visualization.py', '), (True, "Z', '), (False, "Z'),
    ('nv_visualization.py', ') == i', ') != i'),
    ('nv_pdf_export.py', '[1]', '[2]'),
    ('nv_live.py', '=3,', '=4,'),
    ('nv_live.py', 'e["kind"] == "cancel":', 'e["kind"] != "cancel":'),
    ('nv_live.py', 'w] - in', 'w] + in'),
    ('nv_live.py', '"] == "a', '"] != "a'),
    ('nv_live.py', 'w][0] -', 'w][1] -'),
    ('nv_live.py', '][1] ', '][2] '),
    ('nv_live.py', '1] - in', '1] + in'),
    ('nv_live.py', '][1])', '][2])'),
    ('nv_live.py', 'T[0][', 'T[1]['),
    ('nv_live.py', 'e[0]]', 'e[1]]'),
    ('nv_live.py', '] + T', '] - T'),
    ('nv_live.py', 'oute[-1]][0] ', 'oute[-2]][0] '),
    ('nv_live.py', '] + s', '] - s'),
    ('nv_live.py', '=True,', '=False,'),
    ('nv_live.py', ', a=0, b=', ', a=1, b='),
    ('nv_live.py', 'e["kind"] == "cancel" ', 'e["kind"] != "cancel" '),
    ('nv_live.py', ') + "', ') - "'),
    ('nv_live.py', '  a=0, b=', '  a=1, b='),
    ('nv_live.py', ' node > inst.', ' node >= inst.'),
    ('nv_live.py', ') == (', ') != ('),
    ('nv_live.py', '!=', '=='),
    ('nv_live.py', '=node > inst.', '=node >= inst.'),
    ('nv_live.py', 'e][0], ', 'e][1], '),
    ('nv_live.py', ' 1,', ' 2,'),
    ('nv_live.py', '[-1] ', '[-2] '),
    ('nv_live.py', '][0])', '][1])'),
    ('nv_live.py', 'n][0], ', 'n][1], '),
    ('nv_live.py', 'n][1], ', 'n][2], '),
    ('nv_live.py', 'y[0],', 'y[1],'),
    ('nv_live.py', 's=True),', 's=False),'),
    ('nv_live.py', 's=True)}', 's=False)}'),
    ('tools/build_results.py', '=35,', '=36,'),
    ('tools/build_results.py', '=14,', '=15,'),
    ('tools/build_results.py', '=72,', '=73,'),
    ('tools/build_results.py', '=16)', '=17)'),
    ('tools/build_results.py', 'S or k', 'S and k'),
    ('tools/build_results.py', ' and ', ' or '),
    ('tools/build_results.py', ') or k == "gain_', ') or k != "gain_'),
    ('tools/build_results.py', ') or k', ') and k'),
    ('tools/build_results.py', '  or k == "gain_', '  or k != "gain_'),
    ('tools/build_results.py', '  or k', '  and k'),
    ('tools/build_results.py', '(1)', '(2)'),
    ('tools/build_results.py', '(3)', '(4)'),
    ('tools/build_results.py', '(5)', '(6)'),
    ('tools/build_results.py', ' max(', ' min('),
    ('tools/build_results.py', '0.0', '0.1'),
    ('tools/build_results.py', '=True,', '=False,'),
    ('tools/build_results.py', 'False', 'True'),
    ('tools/build_results.py', ' + ', ' - '),
    ('tools/build_results.py', ':4]', ':5]'),
    ('tools/build_results.py', '=True)', '=False)'),
    ('tools/build_results.py', '_ == "', '_ != "'),
]



def build_args(name):
    tests = sorted(p.as_posix() for p in (ROOT / "tests").glob("test_*.py"))
    rel = [str(pathlib.PurePosixPath("tests") / pathlib.PurePosixPath(t).name) for t in tests]
    skip = set(APP_TESTS)
    if name not in CORE:
        skip |= set(SLOW_CORE_TESTS)
    first = [f"tests/{f}" for f in FIRST.get(name, []) if f"tests/{f}" not in skip]
    rest = [t for t in rel if t not in skip and t not in first]
    return first + rest


def run_one(n, name, old, new, tmp_root):
    """Ein Mutant in eigener Kopie; Rückgabe (n, name, old, new, Status)."""
    work = pathlib.Path(tempfile.mkdtemp(prefix=f"nv_mut{n}_", dir=tmp_root))
    try:
        for f in ROOT.glob("*.py"):
            (work / f.name).write_bytes(f.read_bytes().replace(b"\r\n", b"\n"))
        (work / "tools").mkdir()
        for f in (ROOT / "tools").glob("*.py"):
            (work / "tools" / f.name).write_bytes(f.read_bytes().replace(b"\r\n", b"\n"))
        shutil.copy(ROOT / "README.md", work / "README.md")                        # test_claims.py liest das README
        shutil.copytree(ROOT / "data", work / "data")                              # test_results.py liest die Ergebnisdatei
        shutil.copytree(ROOT / "tests", work / "tests", ignore=shutil.ignore_patterns("__pycache__"))
        for f in (work / "tests").rglob("*.py"):
            f.write_bytes(f.read_bytes().replace(b"\r\n", b"\n"))
        path = work / name
        original = path.read_bytes().decode("utf-8")
        if original.count(old) != 1:
            return n, name, old, new, f"FEHLER:{original.count(old)}"
        path.write_bytes(original.replace(old, new).encode("utf-8"))
        args = [PY, "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider"] + build_args(name)
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        env.pop("NV_RECORD_MORNING", None)
        env["NV_MUTATION_RUN"] = "1"                       # tests/test_tools.py prüft die Mutantenliste selbst und würde sonst jeden Mutanten "finden"
        try:
            r = subprocess.run(args, cwd=work, env=env, capture_output=True, text=True, timeout=TIMEOUT)
            return n, name, old, new, "UEBERLEBT" if r.returncode == 0 else "gefunden"
        except subprocess.TimeoutExpired:
            return n, name, old, new, "gefunden(Zeitueberschreitung)"     # Endlosschleife gilt als gefunden
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    jobs = 6
    for i, a in enumerate(sys.argv[1:]):
        if a == "--jobs":
            jobs = int(sys.argv[i + 2])
            args = [x for x in args if x != sys.argv[i + 2]]
    only = args[0] if args else ""
    tmp_root = tempfile.mkdtemp(prefix="nv_mut_")
    # Selbstprüfung des Werkzeugs: ein Mutant, der nichts ändert, MUSS überleben. Sonst scheitern die Tests schon in der Kopie
    # (fehlende Datei, Umgebung), und jeder "gefundene" Mutant wäre vorgetäuscht. Ein Kernmodul und ein Randmodul.
    for probe, marker in (("nv_sim.py", "import math"), ("nv_results.py", "import json")):
        status = run_one(0, probe, marker, marker, tmp_root)[4]
        if status != "UEBERLEBT":
            print(f"ABBRUCH: unveränderte Kopie besteht die Tests nicht ({probe}: {status}) - Ergebnisse wären wertlos")
            shutil.rmtree(tmp_root, ignore_errors=True)
            return 2
    print("Selbstprüfung: unveränderte Kopie besteht alle Tests (Werkzeug funktioniert)", flush=True)
    todo = [(n, *m) for n, m in enumerate(MUTANTS, 1) if not only or only in m[0]]
    survivors, errors, killed = [], [], 0
    with cf.ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = [pool.submit(run_one, n, name, old, new, tmp_root) for n, name, old, new in todo]
        for fut in cf.as_completed(futures):
            n, name, old, new, status = fut.result()
            if status.startswith("FEHLER"):
                errors.append((n, name, old[:60], status))
                print(f"[{n:3d}] FEHLER (Stelle nicht eindeutig: {status})  {name}: {old[:60]!r}", flush=True)
            elif status == "UEBERLEBT":
                survivors.append((n, name, old[:70], new[:70]))
                print(f"[{n:3d}] UEBERLEBT  {name}: {old[:60]!r} -> {new[:60]!r}", flush=True)
            else:
                killed += 1
                print(f"[{n:3d}] {status}  {name}", flush=True)
    print(f"\n{killed} gefunden, {len(survivors)} überlebt, {len(errors)} Fehler in der Mutantenliste (von {len(todo)})")
    shutil.rmtree(tmp_root, ignore_errors=True)
    return 1 if (survivors or errors) else 0


if __name__ == "__main__":
    sys.exit(main())
