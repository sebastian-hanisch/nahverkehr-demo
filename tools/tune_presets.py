"""Preset-Abstimmung: sucht die Anzeige-Seeds der Beispielszenarien. Der Seed bestimmt nur den GEZEIGTEN Tag (die Messreihe steht auf den
Seeds 0 bis 199), deshalb wird nur außerhalb der Stichprobe gesucht (200 bis 299). Für jeden Seed werden die fünf Presets auf dem echten Tag
gerechnet (echtes OR-Tools für den Morgenplan, lokal) und die qualitativen Tageskriterien aus nv_stories.day_criteria geprüft; ausgegeben
werden die Seeds, die alle fünf erfüllen, mit dem R-Gewinn des Standard-Tages (typisch = nah am Mittel der Messreihe).

Aufruf (im Projektordner):  python tools/tune_presets.py [von bis]   (Standard 200 300)"""
import pathlib
import sys

sys.dont_write_bytecode = True
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import nv_constants as C  # noqa: E402
import nv_live as LV  # noqa: E402
import nv_results as R  # noqa: E402
import nv_stories as ST  # noqa: E402


def evaluate(seed, presets=None):
    """Ergebnis je Preset auf dem Tag `seed`: (alle Kriterien erfüllt, Liste der Texte, R-Gewinn des Tages)."""
    out = {}
    for name, p in (presets or C.PRESETS).items():
        day = LV.solve_day(p["morning"], p["rate"], p["events"], p["deadline"], seed)
        crit = ST.day_criteria(name, day, p["cost"])
        gain = day["results"]["R"]["profit_total"] - day["results"]["S0"]["profit_total"]
        out[name] = (all(ok for ok, _ in crit), crit, gain)
    return out


def main(argv):
    lo, hi = (int(argv[0]), int(argv[1])) if len(argv) >= 2 else (200, 300)
    data = R.load_results()
    mean_gain = R.find_cell(data)["pol"]["R"]["gain"]
    good = []
    for seed in range(lo, hi):
        res = evaluate(seed)
        flags = "".join("+" if ok else "-" for ok, _, _ in res.values())
        std = res["Standard"][2]
        print(f"Seed {seed}: {flags}  R-Gewinn Standard {std:+d} (Messreihe Mittel {mean_gain:+.0f})", flush=True)
        if all(ok for ok, _, _ in res.values()):
            good.append((abs(std - mean_gain), seed))
    good.sort()
    print("\nSeeds, die alle fünf Tageskriterien erfüllen (nach Nähe des R-Gewinns zum Mittel der Messreihe):", [s for _, s in good])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
