"""Die 12 Korrektheits-Checks der Messreihe (tests/nv_checks.py) in VERKLEINERTER Fassung; das volle Bau-Gate ist tools/check_full.py
(einmal lokal, mit dem echten OR-Tools). Alle Instanzen rechnen auf den eingefrorenen Morgenplänen (tests/data/nv_morning.json), die
Checks sind also unabhängig von der OR-Tools-Version der CI."""
import nv_checks as K


def test_event_stream():
    rate, kinds = K.check_event_stream(20)
    assert 0.2 < rate < 0.45                             # erwartet p_chg + p_cancel = 0.33 (die volle Fassung prüft 0,27 bis 0,39 auf 60 Instanzen)
    assert all(v > 0 for v in kinds.values()), kinds


def test_hand_measures():
    K.check_hand_measures()


def test_hand_failure():
    K.check_hand_failure()


def test_tiebreak_symmetric():
    tie = K.check_tiebreak_symmetric()
    assert len(tie) >= 2 and tie[0][0] == tie[1][0]      # zwei gleichwertige Einfügungen


def test_no_events():
    K.check_no_events(6)


def test_limits():
    K.check_limits(10)


def test_local_search_idempotent():
    K.check_local_search_idempotent(8)


def test_invariants():
    cnt = K.check_invariants(10)
    assert set(cnt) == {"fail", "cancel", "change", "ign"}


def test_policies_are_exercised():
    diff, nz, kinds = K.check_policies_are_exercised(40)
    assert all(v > 0 for d in (diff, nz, kinds) for v in d.values())


def test_bruteforce_tiny():
    used, gap = K.check_bruteforce_tiny(3, seeds=K.TINY_SEEDS, exact=False)
    assert used == list(K.TINY_SEEDS[:3]) and gap >= 0


def test_oracle_upper_bound():
    assert K.check_oracle_upper_bound(2, small=True) >= 0
