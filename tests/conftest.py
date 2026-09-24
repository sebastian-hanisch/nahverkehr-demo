"""Projektwurzel und tests/ auf den Importpfad, damit `pytest tests/` auch ohne `python -m` die nv_-Module und die Test-Hilfsmodule
(nv_checks) findet. Dazu die EINGEFRORENEN MORGENPLÄNE: die CI installiert immer das neueste OR-Tools, und Morgenpläne können sich zwischen
Versionen ändern. Alle Tests rechnen deshalb auf den Morgenplänen aus tests/data/nv_morning.json; ein Test, der einen nicht eingefrorenen
Morgenplan braucht (also OR-Tools rufen würde), scheitert mit einer klaren Meldung. Ausnahme: Tests mit der Fixture `real_ortools`
(tests/test_morning_real.py) rechnen mit dem echten OR-Tools und prüfen nur Invarianten.

Nachtragen fehlender Morgenpläne (lokal, mit dem echten OR-Tools):  NV_RECORD_MORNING=1 python -m pytest tests/"""
import json
import os
import pathlib
import sys

import pytest

sys.dont_write_bytecode = True
TESTS = str(pathlib.Path(__file__).resolve().parent)
ROOT = str(pathlib.Path(__file__).resolve().parent.parent)
for p in (ROOT, TESTS):
    if p not in sys.path:
        sys.path.insert(0, p)

import nv_model  # noqa: E402

MORNING_PATH = pathlib.Path(TESTS) / "data" / "nv_morning.json"
RECORD = os.environ.get("NV_RECORD_MORNING") == "1"
_REAL_ORACLE = nv_model.oracle


def key_str(key):
    return json.dumps(list(key))


def _plan_from_json(entry):
    nodes, routes, shortfall = entry
    return [tuple(n) for n in nodes], [list(r) for r in routes], shortfall


def _no_ortools(*args, **kwargs):
    raise AssertionError("Morgenplan nicht eingefroren: der Test würde OR-Tools rufen. Fehlende Morgenpläne trägt "
                         "`NV_RECORD_MORNING=1 python -m pytest tests/` (lokal, mit dem echten OR-Tools) in tests/data/nv_morning.json nach.")


@pytest.fixture(scope="session", autouse=True)
def frozen_morning():
    """Morgenpläne aus tests/data/nv_morning.json in den Zwischenspeicher von nv_model laden; OR-Tools für den Morgenplan sperren."""
    stored = json.loads(MORNING_PATH.read_text(encoding="utf-8")) if MORNING_PATH.exists() else {}
    nv_model.MORNING_DISK_CACHE = None
    nv_model._MORNING_CACHE.clear()
    for k, entry in stored.items():
        nv_model._MORNING_CACHE[tuple(json.loads(k))] = _plan_from_json(entry)
    if not RECORD:
        nv_model.oracle = _no_ortools
    yield
    nv_model.oracle = _REAL_ORACLE
    if RECORD:
        merged = {key_str(k): [[list(n) for n in nodes], [list(r) for r in routes], shortfall]
                  for k, (nodes, routes, shortfall) in nv_model._MORNING_CACHE.items()}
        if set(merged) != set(stored):
            MORNING_PATH.write_text(json.dumps(merged, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8", newline="\n")
            print(f"\nnv_morning.json: {len(merged) - len(set(merged) & set(stored))} neue Morgenpläne eingetragen ({len(merged)} insgesamt)")


@pytest.fixture
def real_ortools(monkeypatch):
    """Echtes OR-Tools für den Morgenplan mit eigenem Zwischenspeicher (der eingefrorene bleibt unberührt)."""
    saved = dict(nv_model._MORNING_CACHE)
    monkeypatch.setattr(nv_model, "oracle", _REAL_ORACLE)
    nv_model._MORNING_CACHE.clear()
    yield
    nv_model._MORNING_CACHE.clear()
    nv_model._MORNING_CACHE.update(saved)
