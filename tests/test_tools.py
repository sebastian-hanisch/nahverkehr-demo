"""Werkzeuge im Ordner tools/: Reduktion der Messreihen zur Ergebnisdatei (build_results), Auswertung der Rohdaten (dump_sweep, dump_sweep_sameday),
die Zellenlisten der Sweeps (sweep, sweep_sameday), Bau der eingefrorenen Referenz (freeze_reference), Abstimmung der Presets, Vollständigkeit der
Mutantenliste. Die Sweeps selbst (etwa 35 bzw. 70 Minuten) laufen nie in den Tests."""
import importlib.util
import json
import os
import pathlib
import random
import sys
from dataclasses import asdict

import pytest

import nv_constants as C
import nv_model as M
import nv_results as R
import nv_sim as S

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
SOURCES = ROOT.parent / "tourenplanung-planung"
DATA = R.load_results()


def load_tool(name):
    """Ein Werkzeug als Modul laden (tools/ ist kein Paket); Umgebungsvariablen, die der Import setzt, werden zurückgenommen."""
    before = dict(os.environ)
    spec = importlib.util.spec_from_file_location(f"nv_tool_{name}", TOOLS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    for k in set(os.environ) - set(before):
        del os.environ[k]
    return mod


BR = load_tool("build_results")
SW = load_tool("sweep")
SWS = load_tool("sweep_sameday")
DS = load_tool("dump_sweep")
DSS = load_tool("dump_sweep_sameday")
FR = load_tool("freeze_reference")
TP = load_tool("tune_presets")


# ---------------------------------------------------------------------------------------------------
# build_results
# ---------------------------------------------------------------------------------------------------
def test_rnd_rounds_recursively_and_keeps_special_values():
    assert BR.rnd(1.23456789) == 1.2346 and BR.rnd(5) == 5 and BR.rnd(None) is None and BR.rnd(True) is True and BR.rnd("x") == "x"
    assert BR.rnd([1.23456, [2.98766, None]]) == [1.2346, [2.9877, None]] and BR.rnd((0.00004, 1)) == [0.0, 1]
    assert BR.rnd({"a": 0.123456, "b": {"c": [1.55557]}}) == {"a": 0.1235, "b": {"c": [1.5556]}}
    assert BR.DIGITS == 4 and BR._pick({"a": 1, "b": 2}, ("b", "z")) == {"b": 2}


def synthetic_stab_cell():
    names = ["S0", "R", "F1", "P0.5", "T30"]
    pol = {n: dict(pt=1000.0 + i, pt_se=1.0, gain=float(i), gain_se=0.5, gain_q=[1.0, 2.0, 3.0], a=float(i), a_se=0.1, b=2.0, c=1.0, fail=0.1, acc=5.0, drive=700.0,
                   ls_saved=3.0, wins=10, losses=2) for i, n in enumerate(names)}
    return dict(groups=[["basis", "basis"]], cfg=dict(dict(M.Cfg().__dict__), K=3), n=200, names=names, n_events=20.123456, n_arrivals=6.0, n_orders=40.0, plan_util=0.7,
                eff_change=10.0, eff_cancel=3.0, ign=1.0, pol=pol, stats={"gain_R": 1.0, "a_R": 1.0, "b_R": 2.0, "c_R": 3.0, "gain_per_change": 1.0, "share_P_50": 0.85,
                                                                        "gain_P_50": 40.0, "share_front_a_25": 0.5}, stats_ci={"share_P_50": [0.7, 1.0], "share_front_a_25": [0.1, 0.2],
                                                                                                                            "gain_R": [1.0, 2.0], "a_R": [0.0, 1.0]},
                F_vs_P={"F_minus_P_25": dict(mean=-1.0, ci=[-2.0, 0.0])}, head={}, R_dist=dict(q=[1, 2, 3, 4, 5], share_pos=0.8, share_zero=0.0, top10_share=0.3),
                net={"a": [dict(cc=0.0, best="R")], "b": [dict(cc=0.0)]}, event_cost={"S0": dict(mean=1.0, se=0.1)},
                oracle=dict(n=10, oracle_mean=5.0, share_s0=0.0, gap_r=[1.0, 0.1]))


def test_reduce_stab_cell_keeps_only_what_the_app_shows():
    out = BR.reduce_stab_cell(synthetic_stab_cell())
    assert set(out["cfg"]) == set(BR.STAB_CFG_KEYS) and out["n_events"] == 20.1235
    assert all(set(v) == set(BR.POL_KEYS) for v in out["pol"].values())
    assert set(out["stats"]) == {"gain_R", "a_R", "b_R", "c_R", "gain_per_change", "share_P_50", "share_front_a_25"}       # keine gain_-Zwischenwerte
    assert set(out["stats_ci"]) == {"share_P_50", "gain_R"} and out["net"] == {"a": [dict(cc=0.0, best="R")]}
    assert "share_s0" not in out["oracle"] and out["event_cost"] and "drive" not in out["pol"]["R"] and "ls_saved" not in out["pol"]["R"]
    cell = synthetic_stab_cell()
    del cell["event_cost"], cell["oracle"]
    out = BR.reduce_stab_cell(cell)
    assert "event_cost" not in out and "oracle" not in out


def test_reduce_h_and_cross_and_sameday_cells():
    c = synthetic_stab_cell()
    c["pol"]["H60"] = dict(gain=1.23456, gain_se=0.5, a=3.0, a_se=0.1, b=1.0, c=1.0, pt=9.0, wins=1)
    c["stats"]["share_H_25"] = 0.3333333
    c["F_vs_P"]["H_minus_P_25"] = dict(mean=-2.0, ci=[-3.0, -1.0])
    h = BR.reduce_h_cell(c)
    assert set(h["pol"]) == {"H60"} and set(h["pol"]["H60"]) == {"gain", "gain_se", "a", "a_se", "b", "c"} and h["stats"] == {"share_H_25": 0.3333}
    assert set(h["H_vs_P"]) == {"H_minus_P_25"} and h["pol"]["H60"]["gain"] == 1.2346
    sd = dict(groups=[["basis", "basis"]], cfg=dict(M.Cfg().__dict__), n=60, n_ora=16, n_morning=40.0, n_sd=29.0, n_feas_P1=15.0, plan_util=0.7,
              par=dict(mu=3.0, mu_L=1.5, mu_c=0.5, rho_m=30.0, rho_v=40.0),
              cal_mean={"P2@0.0": 1.0, "P2L@0.0": 2.0, "P2c@0.0": 3.0, "P2m@5.0": 4.0}, pol={p: dict(mean=1.0) for p in ("P0", "P1", "P2v", "P2m", "P2c", "P4L")},
              pairs={"P2-P1p": dict(mean=1.0), "P9-P1": dict(mean=9.0)}, oracle=dict(n=16, ORA=dict(mean=1.0, se=0.1, q=[1, 2, 3]), served=20.0, sd_arrivals=28.0,
                                                                             best_online_gain=dict(mean=1), gap_best_online=dict(mean=2), gap_by_policy={}, pol_on_ora={},
                                                                             route_opt_P2L=dict(mean=1), oracle_ge_all=True, warm_ok=True, acc_on_ora={}))
    out = BR.reduce_sameday_cell(sd)
    assert set(out["cal_mean"]) == {"P2@0.0", "P2L@0.0"} and list(out["pol"]) == ["P0", "P1", "P4L"] and set(out["pairs"]) == {"P2-P1p"}
    assert set(out["oracle"]["ORA"]) == {"mean", "se"} and "acc_on_ora" not in out["oracle"] and set(out["cfg"]) == set(BR.SAMEDAY_CFG_KEYS)
    sd.pop("oracle")
    assert "oracle" not in BR.reduce_sameday_cell(sd)
    cross = BR.reduce_cross_cell(dict(groups=[["x"]], cfg=sd["cfg"], par=sd["par"], pairs={"P2-P1p": dict(mean=1.0), "P4-P2": dict(mean=2.0), "P2v-P1p": dict(mean=3.0)}))
    assert set(cross["pairs"]) == {"P2-P1p", "P2v-P1p"}


def test_parse_timing_reads_the_measured_live_times():
    text = ("cache var: None\nn_m=16 seed=9001: instance+morning 0.6s events 0.00s | S0 0.00s, R 0.01s, F3 0.00s\n"
            "n_m=16 seed=9002: instance+morning 0.5s events 0.00s | S0 0.00s, R 0.02s, F3 0.00s\n"
            "n_m=52 seed=9001: instance+morning 3.6s events 0.00s | S0 0.00s, R 0.07s, F3 0.04s\ngarbage\n")
    t = BR.parse_timing(text)
    assert t["morgenplan_s"] == {"16": [0.6, 0.5], "52": [3.6]} and t["simulation_max_s"] == {"16": 0.02, "52": 0.07}
    assert BR.parse_timing("")["morgenplan_s"] == {}
    assert DATA["_timings"]["morgenplan_s"] == {"16": [0.6, 0.5], "28": [1.1, 1.0], "40": [2.1, 3.2], "52": [3.6, 3.7]}
    assert DATA["_timings"]["simulation_max_s"] == {"16": 0.01, "28": 0.02, "40": 0.05, "52": 0.08}


def test_dumps_is_deterministic_compact_and_sorted():
    a = BR.dumps({"b": [1, 2], "a": {"z": 1.5, "y": "ä"}})
    assert a == '{"a":{"y":"ä","z":1.5},"b":[1,2]}\n' and BR.dumps({"a": 1, "b": 2}) == BR.dumps({"b": 2, "a": 1})


def test_build_assembles_all_parts():
    stab = dict(n_eval=200, n_ora=10, cells=[synthetic_stab_cell()])
    h = dict(cells=[dict(synthetic_stab_cell(), pol={"H15": dict(gain=1.0, gain_se=0.1, a=1.0, a_se=0.1, b=1.0, c=1.0)})])
    sd = dict(n_eval=60, cells=[], cross=[])
    out = BR.build(stab, h, sd, "n_m=16 seed=1: instance+morning 0.6s events 0.00s | S0 0.00s")
    assert set(out) == {"_meta", "_timings", "stab", "sameday"} and out["_meta"]["n_eval"] == 200 and out["_meta"]["sameday_n_eval"] == 60
    assert out["_timings"]["messreihe_kerne"] == 14 and out["_timings"]["messreihe_wanduhr_min"] == 35 and out["_timings"]["morgenplan_s"] == {"16": [0.6]}
    assert len(out["stab"]["cells"]) == 1 and len(out["stab"]["h_cells"]) == 1 and out["sameday"] == {"cells": [], "cross": []}


@pytest.mark.skipif(not (SOURCES / "messreihe_stabilitaet" / "sweep_data.json").exists(), reason="Quellen der Messreihen nicht vorhanden (nur lokal)")
def test_rebuilding_from_the_sources_reproduces_the_committed_file(tmp_path, monkeypatch):
    monkeypatch.setattr(BR, "OUT", tmp_path / "nv_results.json")
    assert BR.main([]) == 0
    assert (tmp_path / "nv_results.json").read_bytes() == R.DATA_PATH.read_bytes()


# ---------------------------------------------------------------------------------------------------
# dump_sweep (Stabilität) und dump_sweep_sameday auf künstlichen Rohdaten
# ---------------------------------------------------------------------------------------------------
NAMES = ["S0", "R", "F1", "F2", "P0.5", "P1", "T30", "T60"]
GAINS = dict(S0=0, R=50, F1=20, F2=10, P0=0, **{"P0.5": 45, "P1": 40, "T30": 25, "T60": 12})
CHANGES = dict(S0=0, R=10, F1=6, F2=3, **{"P0.5": 8, "P1": 5, "T30": 5, "T60": 2})


def synthetic_raw(events=True, n=30, seed=1):
    rnd = random.Random(seed)
    rows = []
    for i in range(n):
        base = 1000 + rnd.randint(-40, 40)
        res = {}
        for p in NAMES:
            jitter = rnd.randint(-5, 5)
            res[p] = dict(profit_total=base + GAINS[p] + jitter, profit=base - 1500 + GAINS[p] + jitter, profit_ora_conv=base + GAINS[p] + jitter, drive=700, a=CHANGES[p] if events else 0,
                          b=CHANGES[p] + 20, c=CHANGES[p] // 2, n_fail=0, n_acc=15, n_cancel=3 if events else 0, n_change=5 if events else 0, n_ign=2, ls_saved=10,
                          n_morning_served=38, n_served_sd=15)
        rows.append(dict(seed=i, res=res, n_events=20 if events else 0, n_arrivals=25, n_orders=65, n_morning=40, plan_util=0.7))
    cfg = dict(M.Cfg().__dict__, p_chg=0.25 if events else 0.0, p_cancel=0.08 if events else 0.0)
    return dict(cfg=cfg, rows=rows, t_eval=1.0, groups=[["basis", "basis"]] if events else [["ereignisrate", "chg=0,cancel=0"]])


def test_dump_sweep_computes_gains_shares_net_and_event_cost(tmp_path):
    raw = dict(cells={"ev": synthetic_raw(True), "ctrl": synthetic_raw(False, seed=2)}, n_eval=30, n_ora=0, t_total=1.0)
    raw_p, out_p = tmp_path / "raw.json", tmp_path / "data.json"
    raw_p.write_text(json.dumps(raw), encoding="utf-8")
    data = DS.main(str(raw_p), str(out_p))
    assert json.loads(out_p.read_text(encoding="utf-8")) == json.loads(json.dumps(data))
    cell = next(c for c in data["cells"] if c["cfg"]["p_chg"] == 0.25)
    rows = raw["cells"]["ev"]["rows"]
    gain_r = sum(r["res"]["R"]["profit_total"] - r["res"]["S0"]["profit_total"] for r in rows) / 30
    assert cell["pol"]["R"]["gain"] == pytest.approx(gain_r) and cell["stats"]["gain_R"] == pytest.approx(gain_r) and cell["pol"]["S0"]["gain"] == 0.0
    assert cell["pol"]["R"]["a"] == 10.0 and cell["pol"]["S0"]["a"] == 0.0 and cell["stats"]["a_R"] == 10.0
    assert cell["stats"]["gain_per_change"] == pytest.approx(gain_r / 10.0) and cell["n"] == 30 and cell["names"] == NAMES
    assert 0 < cell["stats"]["share_P_50"] < 1.5 and cell["stats"]["share_P_50"] > cell["stats"]["share_F_50"]                         # P holt mehr je Änderung
    lo, hi = cell["stats_ci"]["share_P_50"]
    assert lo <= cell["stats"]["share_P_50"] <= hi
    net0 = cell["net"]["a"][0]
    pts = {p: sum(r["res"][p]["profit_total"] for r in rows) / 30 for p in NAMES}
    assert net0["cc"] == 0.0 and net0["best"] == max(pts, key=pts.get) and net0["net_over_S0"] == pytest.approx(max(pts.values()) - pts["S0"])
    high = next(r for r in cell["net"]["a"] if r["cc"] == 20.0)                                                                          # bei hohen Kosten gewinnt Nichtstun
    assert high["best"] in ("S0", "T60") and cell["net"]["c"][0]["cc"] == 0.0 and cell["net"]["b"][-1]["cc"] == 5.0
    ec = cell["event_cost"]                                                                                                              # gepaart mit der Kontrollzelle
    ctrl = raw["cells"]["ctrl"]["rows"]
    loss = sum(c["res"]["S0"]["profit_total"] - r["res"]["S0"]["profit_total"] for r, c in zip(rows, ctrl)) / 30
    assert ec["S0"]["mean"] == pytest.approx(loss) and set(ec) >= {"S0", "R", "gainR_event", "gainR_control", "gainR_extra", "fail_S0", "fail_R"}
    assert "event_cost" not in next(c for c in data["cells"] if c["cfg"]["p_chg"] == 0.0)
    assert cell["R_dist"]["share_pos"] == sum(1 for r in rows if r["res"]["R"]["profit_total"] > r["res"]["S0"]["profit_total"]) / 30
    assert len(cell["R_dist"]["q"]) == 5 and cell["F_vs_P"]["F_minus_P_25"]["ci"][0] < cell["F_vs_P"]["F_minus_P_25"]["ci"][1]
    again = DS.main(str(raw_p), str(tmp_path / "again.json"))
    assert json.dumps(again, sort_keys=True) == json.dumps(data, sort_keys=True)                                                        # feste Zufallszahlen


def test_dump_sweep_helpers():
    assert DS.families(["S0", "R", "F1", "P2", "T30", "H60", "P3"]) == {"F": [2], "P": [3, 6], "T": [4], "H": [5]}
    assert DS.interp_gain([0.0, 10.0, 5.0], [0.0, 100.0, 60.0], 7.5) == pytest.approx(80.0) and DS.step_frontier([0, 5, 10], [0, 60, 100], 7.0) == 60.0
    assert DS.step_frontier([5], [60], 1.0) == 0.0 and DS.se([1, 2, 3, 4]) == pytest.approx(0.6455, abs=1e-3) and DS.se([1]) == 0.0
    assert DS.FRACS == (0.25, 0.5, 0.75) and DS.CC_A[-1] == 20.0 and DS.N_BOOT == 300


def synthetic_sameday_raw(n=12, seed=3):
    rnd = random.Random(seed)
    rows = []
    for i in range(n):
        res = {p: dict(profit=rnd.randint(-900, -500) + 100 * k, drive=700, n_acc=k, n_feas=10, rev=300, ls_saved=0) for k, p in enumerate(DSS.POL)}
        row = dict(seed=i, res=res, n_sd=29, n_morning=40, plan_util=0.7, sd_rev=1000)
        if i < 4:
            row.update(oracle=res["P4L"]["profit"] + 300, oracle_served=20, oracle_warm_ok=True, best_online=res["P4L"]["profit"], route_opt_P2L=res["P2L"]["profit"] + 10)
        rows.append(row)
    return dict(cells={"k": dict(cfg=dict(M.Cfg().__dict__), par=dict(mu=3.0, mu_L=1.5, mu_c=0.5, rho_v=40.0, rho_m=30.0), cal_mean={"P2@0.0": 1.0, "P2c@0.0": 2.0, "P1@0.0": 3.0},
                                 groups=[["basis", "basis"]], n_ora=4, rows=rows)},
                cross={"x": dict(cfg=dict(M.Cfg().__dict__), par=dict(mu=3.0), groups=[["basis", "basis"]], rows=rows)})


def test_dump_sweep_sameday_aggregates_gains_pairs_and_oracle(tmp_path):
    raw = synthetic_sameday_raw()
    raw_p, out_p = tmp_path / "raw.json", tmp_path / "data.json"
    raw_p.write_text(json.dumps(raw), encoding="utf-8")
    data = DSS.main(str(raw_p), str(out_p))
    cell = data["cells"][0]
    rows = raw["cells"]["k"]["rows"]
    assert data["n_eval"] == 12 and cell["n"] == 12 and cell["n_ora"] == 4 and cell["par"]["mu"] == 3.0 and set(cell["cal_mean"]) == {"P2@0.0", "P2c@0.0"}
    assert cell["pol"]["P0"]["mean"] == 0.0 and cell["pol"]["P1"]["mean"] == pytest.approx(sum(r["res"]["P1"]["profit"] - r["res"]["P0"]["profit"] for r in rows) / 12)
    pair = cell["pairs"]["P1p-P1"]
    d = [r["res"]["P1p"]["profit"] - r["res"]["P1"]["profit"] for r in rows]
    assert pair["mean"] == pytest.approx(sum(d) / 12) and pair["wins"] == sum(x > 0 for x in d) and pair["losses"] == sum(x < 0 for x in d) and pair["ties"] == sum(x == 0 for x in d)
    o = cell["oracle"]
    assert o["n"] == 4 and o["ORA"]["mean"] > 0 and o["oracle_ge_all"] is True and o["warm_ok"] is True and o["served"] == 20.0
    assert o["gap_best_online"]["mean"] == pytest.approx(300.0) and set(o["gap_by_policy"]) == {"P1", "P1p", "P2", "P1L", "P2L", "P4L"}
    assert len(data["cross"]) == 1 and "oracle" not in data["cross"][0]
    assert DSS.q([1.0]) == [1.0, 1.0, 1.0] and DSS.q([1.0, 2.0, 3.0, 4.0, 5.0])[1] == 3.0 and DSS.ms([]) == dict(mean=None, se=None)


# ---------------------------------------------------------------------------------------------------
# Zellenlisten der Sweeps, eine Instanz, Referenzwerkzeug, Presets, Mutanten
# ---------------------------------------------------------------------------------------------------
def test_sweep_cell_list_is_exactly_the_measured_grid():
    recs = SW.cell_list()
    assert len(recs) == 28
    by_cfg = {json.dumps({k: c["cfg"][k] for k in BR_KEYS}, sort_keys=True): c for c in R.stab_cells(DATA)}
    for rec in recs:
        key = json.dumps({k: asdict(rec["cfg"])[k] for k in BR_KEYS}, sort_keys=True)
        assert key in by_cfg, rec["groups"]
        assert [list(g) for g in rec["groups"]] == by_cfg[key]["groups"]
    assert sum(1 for r in recs if r["ora"]) == 9 and SW.N_EVAL == 200 and SW.N_ORA == 10 and SW.ORACLE_SOL_LIMIT == 800


BR_KEYS = BR.STAB_CFG_KEYS


def test_sweep_policy_grid_is_the_live_grid():
    assert list(SW.POLICY_SPECS) == list(C.POLICY_NAMES) and SW.POLICY_SPECS == {k: C.POLICY_SPECS[k] for k in C.POLICY_NAMES}


def test_sweep_eval_task_on_one_frozen_instance():
    cfg = M.Cfg(K=3, n_m=16, lam=6.0, p_chg=0.25, p_cancel=0.08)
    out = SW.eval_task((asdict(cfg), 0, False))
    inst = M.make_instance(cfg, 0)
    assert out["seed"] == 0 and set(out["res"]) == set(C.POLICY_NAMES) and "oracle" not in out
    assert (out["n_events"], out["n_arrivals"], out["n_orders"], out["n_morning"]) == (len(inst.events), len(inst.arrivals), inst.n_orders_base, inst.n_morning)
    for name in ("S0", "R", "P1.5", "F3", "T60"):
        r = S.run_events(inst, **C.POLICY_SPECS[name])
        assert out["res"][name] == {**{k: r[k] for k in SW.METRICS if k != "profit_ora_conv"},
                                    "profit_ora_conv": r["profit_total"] + cfg.pen * sum(1 for o in r["failed_orders"] if inst.is_sd[o])}
    assert set(out["res"]["R"]) == set(SW.METRICS) | {"profit_ora_conv"} and 0.3 < out["plan_util"] < 0.8


def test_sweep_sameday_cell_list_is_exactly_the_measured_grid():
    recs = SWS.cell_list()
    assert len(recs) == 34
    keys = BR.SAMEDAY_CFG_KEYS
    by_cfg = {json.dumps({k: c["cfg"][k] for k in keys}, sort_keys=True): c for c in R.sameday_cells(DATA)}
    for rec in recs:
        key = json.dumps({k: asdict(rec["cfg"])[k] for k in keys}, sort_keys=True)
        assert key in by_cfg and [list(g) for g in rec["groups"]] == by_cfg[key]["groups"] and rec["n_ora"] == by_cfg[key]["n_ora"]
    assert SWS.N_EVAL == 60 and SWS.N_CAL == 40 and SWS.CAL_BASE == 100_000 and SWS.MU_GRID[-1] == 20.0 and len(SWS.MU_GRID) == 13


def test_sweep_sameday_run_policy_matches_direct_simulation():
    cfg = M.Cfg(K=3, n_m=16, lam=6.0)
    inst = M.make_instance(cfg, 0)
    par = dict(mu=3.0, mu_L=1.5, mu_c=0.5, rho_v=40.0, rho_m=30.0)
    for name, direct in (("P0", S.simulate(inst, "P0")), ("P1p", S.simulate(inst, "P1p")), ("P2", S.simulate(inst, "P2", mu=3.0)),
                         ("P2L", S.simulate(inst, "P2", mu=1.5, ls=True)), ("P2v", S.simulate(inst, "P2v", rho=40.0)), ("P2m", S.simulate(inst, "P2m", rho=30.0))):
        assert SWS.run_policy(inst, name, par)["profit"] == direct["profit"], name
    with pytest.raises(ValueError):
        SWS.run_policy(inst, "P9", par)
    assert SWS.mean_se([1.0, 3.0]) == (2.0, pytest.approx(1.0)) and SWS.mean_se([5.0]) == (5.0, 0.0)


def test_freeze_reference_helpers_and_cases_match_the_data(tmp_path, monkeypatch):
    key = M._morning_key(M.Cfg(K=3, n_m=40), 5)
    assert FR.key_str(key) == json.dumps(list(key)) and json.loads(FR.key_str(key)) == list(key)
    monkeypatch.setattr(M, "MORNING_DISK_CACHE", str(tmp_path))
    assert os.path.basename(M._disk_path(key)) == FR.disk_name(key)                                     # derselbe Dateiname wie der Zwischenspeicher der Messreihe
    assert FR.STAB_CASES[0] == ("basis", {}, list(range(8))) and len(FR.STAB_CASES) == 9 and len(FR.SD_CASES) == 7
    for name, over, seeds in FR.STAB_CASES:
        assert R.find_cell(DATA, **{k: v for k, v in over.items()}) is not None, name
    ref = json.loads((ROOT / "tests" / "data" / "nv_reference.json").read_text(encoding="utf-8"))
    assert [c["name"] for c in ref["stab"]] == [c[0] for c in FR.STAB_CASES] and [c["name"] for c in ref["sameday"]] == [c[0] for c in FR.SD_CASES]
    morning = json.loads((ROOT / "tests" / "data" / "nv_morning.json").read_text(encoding="utf-8"))
    for case in ref["stab"]:
        for seed in case["seeds"]:
            assert FR.key_str(M._morning_key(M.Cfg(**case["cfg"]), seed)) in morning, (case["name"], seed)


def test_tune_presets_evaluates_all_presets_on_one_day():
    res = TP.evaluate(292)
    assert list(res) == list(C.PRESETS) and all(ok for ok, _, _ in res.values())
    assert isinstance(res["Standard"][2], int) and res["Standard"][2] > 0                # Gewinn der vollen Neuplanung auf dem gezeigten Tag


def test_check_full_is_importable():
    mod = load_tool("check_full")
    assert callable(mod.main)


@pytest.mark.skipif(os.environ.get("NV_MUTATION_RUN") == "1", reason="im Fehler-Einbau-Lauf ist die Stelle des Mutanten absichtlich verändert")
def test_mutation_list_is_well_formed():
    mut = load_tool("mutation_check")
    assert len(mut.MUTANTS) >= 150 and len(set(mut.MUTANTS)) == len(mut.MUTANTS)
    for name, old, new in mut.MUTANTS:
        assert old != new, (name, old)
        path = ROOT / name
        assert path.exists(), name
        assert path.read_bytes().replace(b"\r\n", b"\n").decode("utf-8").count(old) == 1, (name, old[:60])
    assert {m[0] for m in mut.MUTANTS} <= set(mut.FIRST)                                  # zu jedem mutierten Modul gibt es eine Testreihenfolge
