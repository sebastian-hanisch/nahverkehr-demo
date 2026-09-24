"""Das VOLLE Bau-Gate: alle Korrektheits-Checks der Messreihe (messreihe_stabilitaet/check.py, 12 Checks, etwa 8 Minuten) in voller Größe
mit dem ECHTEN OR-Tools für die Morgenpläne und das Orakel. Läuft einmal lokal vor dem Commit, nicht in der CI: dort laufen dieselben
Prüfungen verkleinert und auf eingefrorenen Morgenplänen (tests/test_checks.py).

Der Reproduktions-Check gegen die Original-Quellen (sameday.py und deren sweep_raw.json neben dem Projektordner) läuft nur, wenn diese
vorhanden sind; die bitgleiche Reproduktion der Sweeps auf eingefrorenen Morgenplänen prüft tests/test_frozen_reference.py.

Aufruf (im Projektordner):  python tools/check_full.py"""
import multiprocessing as mp
import pathlib
import sys
import time

sys.dont_write_bytecode = True
ROOT = pathlib.Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "tests"):
    sys.path.insert(0, str(p))

import nv_checks as K  # noqa: E402


def main():
    t0 = time.time()
    rate, kinds = K.check_event_stream(60)
    assert 0.27 < rate < 0.39, rate                                     # erwartet p_chg + p_cancel = 0.33
    assert all(v > 0 for v in kinds.values()), kinds
    print(f"ereignisstrom: 60 Instanzen, Ereignisanteil {rate:.3f} je Auftrag (erwartet 0,33), Arten {kinds}", flush=True)
    K.check_hand_measures()
    print("handinstanz masse: Storno bei Plan [B,A,C,X]: S0 (a,b,c) = (0,0,0); R = (3,2,1), Fahrzeit 80 -> 60; F_2 = 0, F_1 = 2; lambda 5 fuehrt den Zug aus, lambda 12 keinen; "
          "Ereignis nach Abfahrt ignoriert", flush=True)
    K.check_hand_failure()
    print("handinstanz ausfall: Mengenaenderung ueber die Kapazitaet -> n_fail = 1, Strafe 60, Gewinn_total -20", flush=True)
    tie = K.check_tiebreak_symmetric()
    print(f"tie-break: spiegelbildliche Fahrzeuge, gleichwertige Einfuegung ({tie[:2]}): R == S0, a = 0, zweite Neuoptimierung ohne Zug", flush=True)
    K.check_no_events(15)
    print("keine ereignisse: 15 Instanzen, alle 8 Politiken identisch mit dem Morgenplan, Zaehler exakt 0", flush=True)
    K.check_limits(40)
    print("grenzfaelle: 40 Instanzen: F_alle == T_inf == H_inf == S0, F_0 == P_0 == T_0 == H_0 == R exakt; S0 hat a = 0", flush=True)
    K.check_local_search_idempotent(40)
    print("idempotenz: 40 Instanzen x 7 Neuoptimierungs-Politiken: zweite Neuoptimierung ohne Zug", flush=True)
    cnt = K.check_invariants(40)
    print(f"invarianten: 40 Instanzen x 8 Politiken gueltig, Praefix unveraendert, Gewinn nachgerechnet, Endplan im Orakel-Modell zulaessig ({cnt})", flush=True)
    diff, nz, kinds = K.check_policies_are_exercised(60)
    print(f"politiken greifen (60 Instanzen): Abweichungen {diff}; Zaehler ungleich 0: {nz}; wirksame Ereignisse {kinds}", flush=True)
    msg = K.check_repro_original(30)
    print(msg or "reproduktion gegen sameday.py: uebersprungen (Quellen der Messreihe nicht gefunden)", flush=True)
    used, gap = K.check_bruteforce_tiny(8, exact=True)
    print(f"brute-force: 8 Kleinstinstanzen (Seeds {used}): Orakel (warm UND kalt) = exaktes Optimum, keine Online-Politik darueber (mittlere Luecke {gap:.1f})", flush=True)
    with mp.Pool(8) as pool:
        lead = K.check_oracle_upper_bound(12, pool=pool)
    print(f"orakel: 12 Instanzen (K=2, 14 Morgenauftraege): Orakel >= alle 8 Online-Politiken; mittlerer Vorsprung vor der besten {lead:.1f}", flush=True)
    print(f"\nalle Checks bestanden ({time.time() - t0:.0f} s)")


if __name__ == "__main__":
    main()
