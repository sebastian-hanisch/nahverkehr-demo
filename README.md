# Nahverkehr: Same-Day-Aufträge, Änderungen und der Preis der Planänderung – Streamlit-Demo

*(noch nicht deployed)*

Interaktive Fall-Demo (Tourenplanung): Im Nahverkehr steht der Plan am Morgen, aber der Tag hält sich nicht daran – **neue Aufträge** (Same-Day-Aufträge) kommen herein, teils wenn die Touren schon laufen, und **Aufträge ändern sich**
(Zeitfenster, Adresse, Menge) oder werden storniert. Die Demo beantwortet: **Wie viel Neuplanung lohnt sich, wenn jede Planänderung etwas kostet – und welche neuen Aufträge nimmt man überhaupt an?** Live auf **einem Tag**
(Morgenplan mit OR-Tools, Ereignisstrom, alle Politiken über denselben Tag, mit Zeitstrahl der Ereignisse und der Änderungen je Ereignis, Karte und Halteliste) und **vorgerechnet** über 200 bzw. 60 gepaarte Tage, die die Aussage tragen.

Teil des Portfolios für die Website „Sebastian Hanisch – Operations Research und Machine Learning". **Erweiterung der Tourenplanungs-Demo** (`vrp_demo`), aus zwei Vorab-Messreihen verschmolzen: `messreihe_sameday` (welche neuen
Aufträge annehmen?) und `messreihe_stabilitaet` (wie viel Neuplanung lohnt, wenn jede Planänderung etwas kostet?). Beide laufen auf demselben Simulator; ohne Änderungsereignisse liefert die Stabilitäts-Simulation **bitgleich** die
Zahlen der Same-Day-Messreihe (Test). Alle Instanzen sind deterministisch (Seed), die Streuung kommt aus der Stichprobe von Tagen.

## Warum dieses Problem

Das Muster „starrer Plan gegen reaktives Nachplanen" gibt es im Portfolio schon (`fahrzeugflotte-demo`, `robuste-kaiplatz-demo`, `blockzuweisung-demo`, `hofrobust-demo`): dort ist die Neuplanung kostenlos oder die Unruhe nur gezählt. Neu ist hier
**die Achse „Stabilität wird bepreist und gemessen"**: jede Planänderung (Fahrer informieren, Kunden neue Zeiten ansagen) hat einen Preis, drei Maße zählen, was als Änderung gilt, und die Kurve **Gewinn gegen Änderungen** zeigt, wie
schnell sich zusätzliche Änderungen nicht mehr lohnen. Die Vorab-Hypothese, ausdrücklich zu prüfen: wenige Änderungen holen fast den ganzen Nutzen der vollen Neuoptimierung. Sie stimmt – **aber nur für einen Preis in der
Entscheidung (Änderungsstrafe), nicht für den naheliegenden Einfrierhorizont**. Die Hauptansicht formuliert deshalb eine **bedingte Aussage in drei Zuständen** (volle Neuplanung lohnt / hier lohnt ein Preis je Änderung /
volle Neuplanung verliert gegen den starren Plan) aus der vorgerechneten Netto-Tabelle und stellt sie neben den einen gezeigten Tag: ein einzelner Tag streut stark.

## Befunde und Korrekturen gegenüber dem Plan

Die App folgt dem Detailplan (`plan_nahverkehr.html`, Arbeitspakete 0 bis 7; die Integration in die Website ist nicht Teil dieses Bausteins). Abweichungen und Präzisierungen, ehrlich benannt:

- **Der Orakel-Aufruf für den Morgenplan steht in `nv_model.py`, das Orakel mit Änderungen in `nv_oracle.py`.** Der Plan sah `nv_oracle` für „das Orakel" vor; `build_morning` braucht aber den OR-Tools-Aufruf für den Morgenplan, und ein Import von `nv_oracle`
  in `nv_model` wäre ein Zyklus. Die Logik ist mechanisch aus `stab.py` übernommen und unverändert.
- **Der Festplatten-Zwischenspeicher der Morgenpläne ist in der App aus** (`nv_model.MORNING_DISK_CACHE = None`, Streamlit Cloud darf nicht schreiben); zwischengespeichert wird im Speicher und über `st.cache_data`. Nur die Umgebungsvariable
  `NV_MORNING_CACHE` (setzt `tools/sweep.py` für die Mehrprozess-Reproduktion) schaltet ihn wieder ein.
- **Die Live-Rechnung startet automatisch mit Spinner** (Ergebnis je Einstellung zwischengespeichert), nicht über einen eigenen Knopf. Ein Tag braucht auf dem Entwicklungsgerät 0,6 s (16 Morgenaufträge) bis 3,7 s (52), davon der Morgenplan fast alles;
  auf einem langsameren Server entsprechend länger. Die Kosten je Änderung und die Anzeigewahl rechnen nichts neu.
- **Der „beste Regler" der Hauptansicht ist der in der Messreihe für die eingestellten Kosten beste** (höchster Netto-Gewinn, aus den Politik-Mittelwerten der Zelle für jede beliebige Kostenstufe neu gerechnet, gleich der gespeicherten Netto-Tabelle) und wird dann
  auf dem gezeigten Tag gerechnet; nicht der auf diesem einen Tag zufällig beste (das wäre Rosinenpicken).
- **Zell-Zuordnung:** die Stufen der Regler (16 / 28 / 40 / 52 Morgenaufträge, Rate 0 / 2 / 6 / 12, fünf Ereignisstufen, Frist 60 / 120 / 240) sind gemessene Zellen, aber die Messreihe variiert je Zelle nur **einen** Parameter ausgehend vom Basisfall (13 Zellen
  liegen ganz auf den Stufen). Für jede andere Kombination zeigt die Vergleichsspalte die nächstliegende gemessene Zelle (Abstand = Summe der Stufenabstände; Gleichstand: die Zelle des früheren Parameters in der Reihenfolge Rate, Morgenaufträge,
  Ereignisse, Frist) **und sagt es** (Hinweis in der Meldung und im Kernabschnitt). Für die Annahme gilt dasselbe mit Abstand in Rohgrößen (die Annahme-Messreihe hat 21 passende Zellen inklusive der Rasterzellen 24 / 40 / 52 Morgenaufträge mal Rate 2 / 6 / 12).
- **Bei Rate 0 gibt es keine neuen Aufträge und damit nichts anzunehmen:** der Kernabschnitt „Welche Aufträge annehmen?" sagt das, statt sechs gleiche Zahlen zu zeigen (die Annahme-Messreihe kennt keine Rate 0).
- **Die Annahme-Regeln laufen live auf demselben Tag ohne Änderungsereignisse** (die Messreihe der Annahme kennt keine); der Schwellenwert µ kommt aus der Kalibriertabelle der nächstliegenden gemessenen Zelle.
- **Kosten je Änderung sind ein Regler in 0,5er-Schritten** (0 bis 20); die Netto-Tabelle rechnet jede Stufe exakt aus den Mittelwerten, nicht nur die Stufen des Rasters der Messreihe.
- **Rundungsdifferenz der Vorab-Messung:** `ERGEBNIS.md` der Annahme-Messreihe nennt P1p mit „707 ± 28", der Mittelwert der Rohzahlen ist 706,5 und rundet auf 706; die App und diese README zeigen 706.

## Modell

60 × 60 km, Depot in der Mitte, **3 Transporter** mit einer Tour je Schicht, Fahrzeit = Entfernung × 1,2 min/km (aufgerundet), Service 6 min je Stopp, Schichtende nach 480 min. **Morgenplan:** 40 Aufträge (Auslastung 0,70) mit Zeitfenstern von 180 min,
Einfüge-Heuristik plus lokale Suche, von OR-Tools verbessert (deterministisch über eine Lösungszahl, nicht über Zeit). **Neue Aufträge:** Poisson, Standard 6 je Stunde im Fenster [1, 300] min, Frist 120 min nach Eingang, Erlös lognormal (Mittel 60, σ 0,6);
sofortige, verbindliche Annahme oder Ablehnung (abgelehnt = entfällt). **Annahmeregeln:** P0 nie annehmen, P1 annehmen wenn machbar, P1p wenn machbar und Erlös ≥ Fahrt-Zusatzkosten, P2 Zeit-Schattenpreis (Schwelle µ aus der Route, kalibriert auf getrennten Seeds),
je mit und ohne Neuoptimierung (L). **Änderungsereignisse:** je Auftrag mit Wahrscheinlichkeit 0,25 eine Änderung (Zeitfenster ±30 min oder Adresse im Umkreis 5 km) und 0,08 ein Storno, im Mittel 22,6 Ereignisse je Tag; ein Ereignis wirkt nur auf
einen noch nicht bindenden Auftrag (bindend: das Fahrzeug muss spätestens losgefahren sein). Wird ein geänderter Auftrag an seiner Stelle unzulässig, wird er billigst anderswo eingefügt, sonst gescheitert (Erlös weg, Strafe 60). **Neuplanungs-Regler:**
S0 kein Neuoptimieren · R volle Neuoptimierung nach jedem Ereignis · F_k die nächsten k Stopps je Fahrzeug fest · P_λ Zug nur, wenn die Fahrzeitersparnis größer ist als λ × zusätzlich geänderte Stopps · T_x nur alle x Minuten · H_h Stopps der nächsten
h Minuten fest (nur vorgerechnet). **Stabilitätsmaße:** (a) fahrerseitig (Hauptmaß): noch nicht gefahrene Stopps mit anderem Fahrzeug oder Vorgänger, der Ereignisauftrag ausgenommen, S0 damit exakt 0; (b) kundenseitig: angesagte Ankunftszeiten, die sich
um mehr als 15 min ändern; (c) Neuplanungsereignisse mit mindestens einer Änderung. **Gewinn:** Erlös der bedienten Same-Day-Aufträge + 60 je bedientem Morgenauftrag − Fahrminuten − 60 je nicht mehr bedienbarem Auftrag. **Kosten je Änderung stehen nicht im
gemessenen Gewinn:** sie werden nachträglich als Netto-Tabelle angesetzt (Netto = Gewinn − Kosten × Änderungen) und sind **nicht** der Reglerparameter λ (Entscheidungsstrafe). Formal im Expander „📐 Mathematische Formulierung" der App.

**Modellzuordnung:** dynamisches Tourenproblem mit Same-Day-Aufträgen (sofortige Annahmeentscheidung, Einfügebewertung plus Schwelle) und Auftragsänderungen; die Referenz ist das offline Prize-Collecting-VRPTW (Hindsight-Orakel).

## Methodik

- **Ereignissimulation** (`nv_sim.py`): jedes Ereignis bekommt bei **jeder** Politik denselben Basisschritt (Einfügen an der billigsten machbaren Stelle, minimale Reparatur bei einer Änderung, Entfernen bei einem Storno); danach folgt je Politik ein
  Neuoptimierungsschritt (lokale Suche Relocate, Swap, 2-opt, 2-opt\* über den noch nicht gefahrenen Teil, nur strikte Verbesserungen). Gleichstände erzeugen nie Änderungen.
- **Vergleich der Regler** über die Kurve Gewinn gegen Änderungen, gepaart auf denselben Tagen, Mittel ± Standardfehler, Bootstrap (300 Ziehungen) für die Anteile am R-Gewinn bei 25 / 50 / 75 % der R-Änderungen.
- **Drei Stabilitätsmaße**, damit die Aussage nicht am Maß hängt; **Netto-Tabelle** je Kosten je Änderung; **Urteil in drei Zuständen** (Mittel mehr als 2 Standardfehler von 0).
- **Hindsight-Orakel** (OR-Tools, alle Ereignisse vorab bekannt): nur vorgerechnet, auf 10 bzw. 16 Instanzen je Zelle; eine Heuristik, also eine untere Schranke des Optimums.

## Befunde (gemessen, keine Behauptungen)

Alle Zahlen stehen in `data/nv_results.json` und werden in `tests/test_claims.py` aus der Datei nachgerechnet. Basisfall: 3 Transporter, 40 Morgenaufträge, Rate 6, Ereignisse mittel, Frist 120, je 200 Tage.

| Frage | Befund |
|---|---|
| Wie viel bringt die volle Neuplanung, und wie viel dreht sie um? | R dreht 28,6 ± 1,2 Stopps je Tag um und bringt +123,0 ± 12,1 gegenüber dem starren Plan (5,1 % des Gewinns von S0), also 4,3 Gewinn je Änderung. **Schief verteilt:** Median +99, Quartile [+22; +215], 78,5 % der Tage gewinnen. |
| Holt ein Preis je Änderung fast alles mit wenigen Änderungen? | Ja: die Änderungsstrafe holt 69 % / 85 % / 99 % des R-Gewinns bei 25 / 50 / 75 % der R-Änderungen; der Einfrierhorizont nur 37 % / 60 % / 84 %, periodische Neuplanung 36 % / 65 % bei 25 / 50 %. |
| Schlägt die Strafe den Horizont bei gleicher Änderungszahl? | Ja, im Maß (a): F − P = −39,0 (95 %: −60,6 bis −19,3) bei 25 % und −30,1 bei 50 % der R-Änderungen; das Intervall liegt in 26 bzw. 27 von 28 Zellen unter 0, in keiner darüber. Mit dem zeitbasierten Horizont H in 7 von 7 Zellen. |
| Hängt das am Stabilitätsmaß? | **Die Deutlichkeit schon:** unter (c) in 24 / 26 von 28 Zellen belastbar, unter (b) (angesagte Zeiten) nur in 13 / 10 von 28. Die Strafe optimiert das Maß (a) selbst mit: ihr Vorsprung dort ist teilweise per Konstruktion. |
| Ab welchem Preis lohnt volle Neuplanung nicht mehr? | R verliert ab 4,3 Kosten je Änderung gegen den starren Plan. Bester Regler bei Kosten 0 / 1 / 2 / 3 / 5 / 8: P_0,25 / P_0,5 / P_1,5 / P_1,5 / P_3 / P_3 mit +123,9 / +100,5 / +84,4 / +74,4 / +57,3 / +42,1 gegenüber S0 (R selbst: +123,0 / +94,4 / +65,8 / +37,2 / −19,9 / −105,6). |
| Wovon hängt die Größe ab? | Von der Last: Rate 0 / 2 / 6 / 12 je Stunde: R − S0 = +10,8 / +34 / +123 / +233; Frist 60 / 120 / 240 min: +79 / +123 / +181; Morgenaufträge 16 / 28 / 40 / 52: +152 / +150 / +123 / +118. Kein Vorzeichenwechsel: in allen 28 Zellen ist R mehr als 2 Standardfehler besser als der starre Plan. |
| Kommt der Nutzen von den Änderungen? | **Nein, von den neuen Aufträgen:** ohne jedes Änderungsereignis bringt R +84,7 ± 9,5, mit Änderungen und Stornos +123,0, bei Rate 0 (nur Änderungen und Stornos) nur +10,8. |
| Was kosten Änderungen und Stornos selbst? | Der Tag verliert gegenüber demselben Tag ohne Ereignisse mit S0 228 ± 12, mit R 190 ± 13; Neuplanung holt davon 38 ± 13 (17 %) zurück. Reine Stornos: Neuplanung hilft nicht (−6 ± 15). |
| Welche Annahmeregel? | Gewinn gegenüber „nie annehmen" (60 Tage): P1 618 ± 29, P1p 706 ± 28, **Zeit-Schattenpreis P2 758 ± 33**; P2 − P1p = +51 ± 13, die reine Erlös-Schwelle à la Littlewood P2v − P1p = −14 ± 11 (überträgt sich nicht auf das Straßennetz); Neuoptimieren P1pL − P1p = +77 ± 14, Schwelle auf Neuoptimierung P2L − P1pL = +15 ± 16 (nicht nachweisbar). |
| Wie groß ist der Rest zum Rückblick-Orakel? | Annahme (16 Instanzen): Orakel 1175 ± 81, die je Instanz beste Online-Regel holt 836, Lücke 339 ± 53; nach Frist 45 / 90 / 180 / 300 min holt sie 54 / 64 / 82 / 91 % des Orakels. Mit Änderungen (10 Instanzen): Lücke zu R 582 ± 102 (20 % des Orakel-Gewinns), überwiegend Information über künftige Aufträge, nicht Stabilität. |
| Trägt ein fest kalibrierter Schwellenwert? | Nein: die in der Basiszelle kalibrierte Schwelle in andere Regime übertragen kippt das Vorzeichen (16 Morgenaufträge: P2 − P1p = −97 ± 26, kalibriert +0 ± 0). |

## Ehrliche Grenzen

- **Der Betrag ist klein:** die volle Neuplanung bringt rund 5 % Gewinn. Die Aussage ist der Vergleich der Regler und der Preis der Änderung, nicht die Größe; erst bei nennenswerten Kosten je Änderung (ab etwa 1) wird die Wahl des Reglers wichtig.
- **Die Strafe optimiert das Maß (a) selbst mit**, ihr Vorsprung dort ist teilweise per Konstruktion; unter dem kundenseitigen Maß (b) ist er nur in 13 / 10 von 28 Zellen belastbar. Dass die Strafe Züge nach Nutzen je Änderung rangiert, während Einfrieren und Periodik nach
  Ort bzw. Zeit sperren, ist **abgeleitet, nicht getestet**.
- **Die Kosten je Änderung wurden nachträglich angesetzt**, nicht in der Entscheidung gemessen (sie sind nicht λ); ein Version 2 könnte mit echten Kosten simulieren. Die „beste Politik je Kosten" ist im Stichprobendurchschnitt gewählt, also leicht optimistisch.
- **Stark stilisiert:** deterministische Fahrzeiten, eine Tour je Fahrzeug, Ereignisse unabhängig je Auftrag und höchstens eines je Auftrag, Bindung ab Abfahrt (keine Umleitung mitten auf der Strecke), keine Rechenzeitkosten. Erlöse und Strafen sind erfunden.
- **Stornokosten sind großenteils Erlösverlust** (60 je Morgenauftrag) und sagen nichts über die Wirkung der Neuplanung; die Strafe 60 für gescheiterte Aufträge ist gesetzt, nicht kalibriert.
- **Das Orakel ist klein und heuristisch:** 10 (Änderungen) bzw. 16 (Annahme) Instanzen je Zelle, OR-Tools mit Warmstart aus der besten Online-Lösung (das macht „Orakel ≥ Online" per Konstruktion wahr; belegt wird die Schranke durch Brute-Force auf Kleinstinstanzen). Die
  Lücke ist eher unterschätzt.
- **Ein einzelner Tag streut stark** und ist kein Beleg; die Live-Zahlen tragen die Überschrift „ein Tag", die Meldung stützt sich auf die vorgerechnete Messreihe.
- **Mehrfachvergleiche:** 28 Zellen mal viele gepaarte Vergleiche auf gemeinsamen Seeds 0 bis 199; einzelne Ausschläge sind zu erwarten. Wechselwirkungen zwischen den Parametern sind nicht gemessen (Ein-Faktor-Sweeps um den Basisfall).

## Verwandte Demos mit demselben mathematischen Modell

Verschiedene Themen im Portfolio teilen (fast) dasselbe Modell. Vor einer neuen Demo-Idee deshalb das Modell vergleichen, nicht die Kulisse (Stand 2026-09-24):

- **`vrp_demo`** – das **Basismodell**: CVRP mit Zeitfenstern, dort ein Vergleich von Tourenheuristiken. Hier bleibt die Geometrie (Depot, Zeitfenster, Einfügen und lokale Suche über Touren), neu ist der Tag als Ereignisstrom mit Annahme, Änderungen und Stornos.
- **Das Muster „starrer Plan gegen reaktives Nachplanen"** in **`fahrzeugflotte-demo`**, **`robuste-kaiplatz-demo`**, **`blockzuweisung-demo`** und **`hofrobust-demo`**: dort ist die Störung exogen (Ausfall, Verspätung, Fahrzeitrauschen) und die Neuplanung kostenlos oder die Unruhe nur
  gezählt. **Hier neu: der bepreiste Stabilitätsaspekt** – jede Planänderung hat einen Preis, drei Maße zählen sie, und die Kurve Gewinn gegen Änderungen vergleicht Strafe, Stopp-Horizont, Zeit-Horizont und Periode. Kein Regime-Widerspruch wie bei `hofrobust-demo`: das Vorzeichen des
  Neuplanungsnutzens bleibt in allen 28 Zellen gleich, nur die Größenordnung ändert sich.
- **`revenue-management-demo`** – die **Annahme ohne Geometrie** (Littlewood, eine Kapazitätsdimension); hier kommt die Geometrie (Einfügekosten, Route, Zeitfenster) hinzu, und Littlewoods Erlös-Schutzniveau überträgt sich gerade nicht (P2v − P1p = −14 ± 11).
- **`online-matching-demo`** – sofortige Zuordnung gegen das Offline-Optimum (Wettbewerbsverhältnis); inhaltlich der nächste Nachbar der Annahme-Hälfte.
- **`fernverkehr-demo`** – die **Schwester im Tourenplanungs-Zweig**: dort Fahrerregeln und Elektro-Lkw als Ressourcenschicht entlang der Route, hier der Tag als Ereignisstrom; beide erweitern die `vrp_demo` in verschiedene Richtungen.

## Tests

`python -m pytest tests/ -v` – 366 Tests, rund 2,5 Minuten (davon etwa eine Minute AppTests). **Alle Tests rechnen auf EINGEFRORENEN Morgenplänen** (`tests/data/nv_morning.json`): die CI installiert immer das neueste OR-Tools, und Morgenpläne können
sich zwischen Versionen ändern; ein Test, der OR-Tools für den Morgenplan bräuchte, scheitert mit einer klaren Meldung (`conftest.py`), fehlende Pläne trägt `NV_RECORD_MORNING=1 python -m pytest tests/` lokal nach. Nur `test_morning_real.py` rechnet mit dem echten OR-Tools und prüft
ausschließlich Invarianten (gültig, nicht schlechter als die Heuristik, deterministisch innerhalb eines Laufs), keine exakten Routen. Zusammensetzung:

- **Korrektheit des Modells** (`test_checks.py`, Helfer `tests/nv_checks.py`): die 12 Checks aus `messreihe_stabilitaet/check.py` in verkleinerter Fassung – Ereignisstrom, Änderungszähler an der Handinstanz (R = (3, 2, 1)), Ausfall bei Mengenänderung, Tie-Break
  (Gleichstände erzeugen nie Änderungen), keine Ereignisse (alle Politiken gleich dem Morgenplan, Zähler 0), exakte Grenzfälle (F_alle = T_∞ = H_∞ = S0, F_0 = P_0 = T_0 = H_0 = R), Idempotenz der Neuoptimierung, Invarianten (Endplan gültig, bindender Präfix unverändert,
  Gewinn unabhängig nachgerechnet, Endplan im Orakel-Modell zulässig), **jede Politik und jeder Zähler greift** (Zweig-Test gegen die Nullspalten-Falle), Brute-Force auf Kleinstinstanzen, Orakel als obere Schranke. Das **volle Bau-Gate** (`python tools/check_full.py`, mit dem echten
  OR-Tools) lief einmal lokal: 466 Sekunden, alle Checks bestanden, mit denselben Zahlen wie in der Messreihe (187 Ausfälle, 1190 Stornos, 2625 Änderungen, 2345 ignorierte Ereignisse in den Invarianten-Läufen; Ereignisanteil 0,328).
- **Bitgleichheit zur Messreihe** (`test_frozen_reference.py`, `tests/data/nv_reference.json`): die reine Simulation auf den eingefrorenen Morgenplänen reproduziert **exakt** die Rohzahlen der Sweeps – alle 21 Politiken mit 14 Kennzahlen für 9 Zellen (Basis, Rate 12, Frist 60, viele
  Ereignisse, Rate 0, 16 Morgenaufträge, alle drei Änderungsarten mit Kapazität, 2 Fahrzeuge, ohne Ereignisse), der Zusatzlauf H, und die Annahmeregeln P0 bis P2L (mit den kalibrierten Schwellenwerten) samt Rollout für 7 Zellen. Dazu: **ohne Änderungsereignisse ist S0 = P1p und R = P1pL**
  bitgleich zwischen den beiden Messreihen. Der Nachweis, dass die mechanische Aufteilung von `stab.py` in drei Module nichts an der Logik geändert hat.
- **Bausteine** (`test_model_units.py`): Parameter, Distanzen, `retime` und bindender Präfix, Einfügen (auch die zweite Tour über den eingebetteten Depotknoten), lokale Suche, Ereignisstrom (Verschiebung, Radius, Arten, Zeitpunkte), Annahmeregeln an der Handinstanz (jede Schwelle an ihrer Grenze),
  Stabilitätszähler (die 15-Minuten-Toleranz), Reparatur bei Änderungen, Validator, Orakel-Fenster.
- **Messreihe und Urteil** (`test_results.py`, `test_claims.py`): Struktur und Invarianten der Ergebnisdatei (klein, keine Rohdaten), die Netto-Tabelle aus den Politik-Mittelwerten neu gerechnet gleich der gespeicherten in allen 28 Zellen, Urteil in drei Zuständen an künstlichen Zellen an ihren
  Schwellen, Zell-Zuordnung; **jede Zahl dieser README**.
- **Presets** (`test_stories.py`, `test_preset_stories.py`, `test_presets.py`): jedes Abnahmekriterium kippt an künstlichen Werten genau an seiner Schwelle, Vorzeichen-Kriterien nur zusammen mit der Standardfehler-Bedingung; die echten Presets erfüllen sie auf den Messreihen, der gezeigte Tag
  erzählt qualitativ dieselbe Geschichte, alle drei Meldungszustände kommen vor; Permalink-Parsing (Begrenzen, Einrasten, Müll).
- **Live-Rechnung, Figuren, PDF** (`test_live.py`, `test_visualization.py`, `test_ui_panel.py`, `test_pdf_export.py`): der Live-Tag gleich der direkten Simulation, Tagesverlauf und Ereigniszähler, alle Achsen `fixedrange`, keine Farblisten, Tabellen gegen die Daten, PDF mit den genauen Sonderzeichen (fpdf2 stürzt bei „–", „€", Emoji und
  dem Unicode-Minus ab).
- **Werkzeuge** (`test_tools.py`): die Kette Rohdaten → `dump_sweep` → `build_results` auf künstlichen Rohdaten, die Zellenlisten der Sweeps gleich den gemessenen Zellen, Wiederaufbau der Ergebnisdatei aus den Quellen (lokal, wenn vorhanden), Vollständigkeit der Mutantenliste.
- **End-to-End** (`test_app.py`, AppTest): Skelett und Footer, jedes Preset, Permalink, alle Regler an Min und Max, kein toter Regler, alle drei Meldungszustände, Zell-Zuordnung mit Hinweis, Rate 0, Kernabschnitte, Ansichten, PDF. Die Live-Rechnung läuft auf eingefrorenen Plänen, ohne Wall-Clock-Assertions.

- **Lücken aus dem Fehler-Einbau-Test** (`test_mutation_gaps.py`): Morgenaufträge und Heuristik ohne OR-Tools (eingefrorene Routen in `tests/data/nv_heuristic.json`), die Ersetzungsregel des OR-Tools-Ergebnisses, Ereignisstrom an Handinstanzen (Klammer auf 5 Minuten, Adressen am Rand des
  Gebiets), Vorgabewerte und exakte Schwellen der Annahmeregeln, Zählung der Gleichstände, Wortlaut der Kriterien, Vorzeichen in den Tabellen, Balkenlängen der Figuren.

Zusätzlich ein **Fehler-Einbau-Test** (`tools/mutation_check.py`, 459 maschinell erzeugte Mutanten über `nv_model`, `nv_sim`, `nv_oracle`, `nv_live`, `nv_results`, `nv_stories`, `nv_presets`, `nv_constants`, `nv_format`, `nv_ui_panel`, `nv_visualization`, `nv_pdf_export` und
`tools/build_results.py`): **459 gefunden, 0 überlebt**, mit Selbstprüfung der Werkzeugkette (unveränderte Kopie besteht die Tests, Kopie enthält `README.md`, `data/`, `tests/` und `tools/`). Der erste vollständige Lauf ließ 142 von 533 Mutanten überleben: 68 zeigten echte Testlücken
(geschlossen, siehe oben), 74 sind im Werkzeug begründet nicht geführt (Gleitkomma-Gleichheit, OR-Tools-Modellparameter, gleichwertige Umformungen, Abstimmungskonstanten, reine Darstellung). Ein erster Lauf war wertlos, weil ein Test die Mutantenliste selbst prüfte und in jeder Kopie
scheiterte; das Werkzeug setzt jetzt `NV_MUTATION_RUN=1`, der Test überspringt sich dann.

## Dateistruktur

| Datei | Inhalt | Herkunft |
|---|---|---|
| `app.py` | Streamlit-Hauptablauf: Presets, Sidebar, Hauptansicht (ein Tag), Kernabschnitte ② und ①, Ansichten, Texte | neu |
| `nv_constants.py` | Regler-Stufen, Politik-Raster, Meldungsschwellen, Farben, `PRESETS` | neu |
| `nv_presets.py` | `SETTING_SPECS`, Permalink (Begrenzen, Einrasten), Presets, Seed-Knopf | Muster `fv_presets.py` |
| `nv_model.py` | `Cfg`, Instanz, Flotte, Kandidaten, Einfüge-Evaluator, lokale Suche, Morgenplan (OR-Tools), Ereignisstrom, Validator | `stab.py`, mechanisch aufgeteilt, Logik unverändert |
| `nv_sim.py` | `simulate` (Annahmeregeln), `run_events` (Politiken S0/R/F/P/T/H), Stabilitätszähler (a) (b) (c), Rollout | `stab.py`, unverändert |
| `nv_oracle.py` | Hindsight-Orakel mit Änderungen (nur Reproduktion, nicht in der App) | `stab.py`, unverändert |
| `nv_live.py` | Live-Tag: alle Politiken, Tagesverlauf einer Politik, Annahmeregeln ohne Änderungsereignisse | neu |
| `nv_results.py` | Laden und Auswerten von `data/nv_results.json`: Zell-Zuordnung, Netto-Tabelle, Urteil in drei Zuständen, Kennzahlen | neu |
| `nv_visualization.py` | Zeitstrahl, Karte, Kurve, Anteilsbalken, Netto-Kurve, Regime, Annahme (alle Achsen fest) | neu |
| `nv_ui_panel.py` | Kennzahlen (2 × 2), Meldung, Vergleichstabelle, Tagesverlauf, Tabellen der Kernabschnitte | Muster `fv_ui_panel.py` |
| `nv_format.py` | Zahlenformate (Dezimalkomma), Zeitangaben | neu |
| `nv_pdf_export.py` | Tagesplan-PDF (`fpdf2`, Sonderzeichen-Bereinigung) | Muster `fv_pdf_export.py` |
| `nv_stories.py` | Abnahmekriterien der Presets (Messreihe und gezeigter Tag) | Muster `fv_stories.py` |
| `data/nv_results.json` | Aggregate beider Messreihen (28 + 7 + 34 Zellen), Kalibriertabelle für µ, Netto-Tabellen, Orakel | `tools/build_results.py` |
| `tools/sweep.py`, `tools/dump_sweep.py` | Reproduktion der Stabilitäts-Messreihe (nicht in der CI) | `messreihe_stabilitaet/`, Importe angepasst |
| `tools/sweep_sameday.py`, `tools/dump_sweep_sameday.py` | Reproduktion der Same-Day-Messreihe (nicht in der CI) | `messreihe_sameday/`, Importe angepasst |
| `tools/build_results.py` | erzeugt `data/nv_results.json` aus den Auswertungen beider Messreihen | neu |
| `tools/freeze_reference.py` | erzeugt `tests/data/nv_reference.json` und `nv_morning.json` aus den Rohdaten der Messreihen | neu |
| `tools/check_full.py` | das volle Bau-Gate (alle 12 Checks in Originalgröße, echtes OR-Tools) | neu |
| `tools/tune_presets.py` | Suche der Anzeige-Seeds der Presets | neu |
| `tools/mutation_check.py` | Fehler-Einbau-Test (parallel, je Mutant eine Kopie, mit Selbstprüfung) | Muster `fv` |
| `tests/` | siehe oben; `nv_checks.py` sind die 12 Checks der Messreihe, `data/` die eingefrorenen Referenzen und Morgenpläne | neu |

## Bewusst nicht umgesetzt

- **Fahrzeitunsicherheit**, **mehrere Touren je Fahrzeug**, **Umleitung mitten auf der Strecke** (Bindung ab Abfahrt).
- **Exakte Neuoptimierung** statt lokaler Suche (die lokale Suche holt auf Kleininstanzen 79 % des Potenzials, dort gemessen, hier nicht wiederholt).
- **Kosten je Änderung in der Entscheidung** (nur nachträglich als Netto-Tabelle).
- **Kalibrierung an echten Daten** (Erlöse, Strafen, Ereignisraten sind synthetisch).
- **Mengenänderungen als eigener Schwerpunkt** (nur mit endlicher Kapazität gemessen; die App rechnet immer ohne Kapazitätsgrenze).
- **Live-Rechnung für die Messreihen und das Orakel**: 200 Tage je Zelle brauchen etwa 35 Minuten auf 14 Kernen, das Orakel 25 bis 70 Sekunden je Instanz; beides wird nie im Browser gerechnet.
- **Wechselwirkungen zwischen den Parametern** (nur Ein-Faktor-Sweeps um den Basisfall; ein Raster gibt es nur für Morgenaufträge mal Rate in der Annahme).

## Reproduktion der Messreihen

Nicht in der CI, nicht im Browser: die Läufe brauchten zusammen etwa **35 Minuten Wanduhrzeit auf 14 Kernen** (Stabilität: Hauptsweep 15 Minuten, Zusatzlauf H 1,5 Minuten, dazu Wiederholung und Bau-Gate) bzw. 72 Minuten auf 16 Prozessen (Annahme).

```bash
python tools/sweep.py [--cache ordner]             # Stabilität: 28 Zellen x 200 Instanzen -> tools/sweep_raw.json (mit --h: Zusatzlauf Horizont H)
python tools/dump_sweep.py                          # aggregiert -> tools/sweep_data.json
python tools/sweep_sameday.py                       # Annahme: 34 Zellen x 60 Instanzen, Kalibrierung, Orakel -> tools/sweep_sameday_raw.json
python tools/dump_sweep_sameday.py                  # aggregiert -> tools/sweep_sameday_data.json
python tools/build_results.py [Argumente]           # -> data/nv_results.json (ohne Argumente aus ../tourenplanung-planung/)
```

`tools/*_raw.json`, `tools/*_data.json` und `tools/cache_morning/` stehen in der `.gitignore` (Rohdaten, zusammen mehr als 30 MB). Ein Wiederholungslauf der Stabilitäts-Messreihe (frisch berechnete Morgenpläne, gleiche Seeds) lieferte alle 5600 Instanz-Zeilen bitgleich; in der
Annahme-Messreihe wich genau ein OR-Tools-Referenzwert ab (`solution_limit` beendet OR-Tools nicht perfekt reproduzierbar). Die Simulation selbst (`nv_sim`) ist reine Standardbibliothek und auf allen Plattformen bitgleich.

## Lokal ausführen

```bash
pip install -r requirements-dev.txt
streamlit run app.py
```

Tests: `python -m pytest tests/ -v`. Volles Bau-Gate: `python tools/check_full.py`. Preset-Abstimmung: `python tools/tune_presets.py [erster_Seed] [letzter_Seed]`. Fehler-Einbau: `python tools/mutation_check.py [Modul] [--jobs N]`.
Fehlende Morgenpläne für neue Tests trägt `NV_RECORD_MORNING=1 python -m pytest tests/` (mit dem echten OR-Tools) in `tests/data/nv_morning.json` nach.

---

Gebaut mit Streamlit, Plotly, OR-Tools und fpdf2.
