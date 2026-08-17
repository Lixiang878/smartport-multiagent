"""BAP 算法测试：FCFS / GA / MIP 的正确性与约束满足。"""
from __future__ import annotations

import time

from smartport.algorithms.bap_common import (
    estimate_service_hours,
    validate_berth_plan,
)
from smartport.algorithms.bap_fcfs import solve_bap_fcfs
from smartport.algorithms.bap_ga import solve_bap_ga
from smartport.algorithms.bap_mip import solve_bap_mip
from smartport.core.models import Scenario


def _run_all_modes(scenario: Scenario) -> dict:
    service = estimate_service_hours(scenario.vessels)
    n_cranes = len(scenario.cranes) if scenario.cranes else 8
    results = {}
    results["fcfs"], _ = solve_bap_fcfs(scenario.vessels, scenario.berths, service)
    t0 = time.perf_counter()
    results["ga"], _ = solve_bap_ga(
        scenario.vessels, scenario.berths, service,
        config={"population": 30, "generations": 30}, seed=42,
        n_cranes=n_cranes)
    ga_seconds = time.perf_counter() - t0
    results["_ga_seconds"] = ga_seconds
    mip_plan, mip_meta = solve_bap_mip(
        scenario.vessels, scenario.berths, service,
        config={"time_limit": 15.0}, warm_start_plan=results["fcfs"])
    results["mip"] = mip_plan
    results["_mip_meta"] = mip_meta
    return results


def test_all_modes_valid(scenario10):
    """三种模式（MIP 若可用）均满足泊位约束且全部分配。"""
    res = _run_all_modes(scenario10)
    for mode in ("fcfs", "ga"):
        plan = res[mode]
        assert len(plan) == len(scenario10.vessels)
        assert validate_berth_plan(plan, scenario10.vessels,
                                   scenario10.berths) == []
    if res["mip"] is not None:
        assert len(res["mip"]) == len(scenario10.vessels)
        assert validate_berth_plan(res["mip"], scenario10.vessels,
                                   scenario10.berths) == []


def test_ga_objective_not_worse_than_fcfs_seed(scenario10):
    """GA 精英保留：最终解的目标值必不劣于初始种群中的 FCFS 种子。"""
    from smartport.algorithms.bap_ga import GA_DEFAULTS, _objectives
    res = _run_all_modes(scenario10)
    cap = max(2, len(scenario10.cranes) // 3)
    pen = GA_DEFAULTS["overload_penalty"]
    f_ga = _objectives(res["ga"], scenario10.vessels, cap, pen)[0]
    f_fcfs = _objectives(res["fcfs"], scenario10.vessels, cap, pen)[0]
    assert f_ga <= f_fcfs + 1e-9


def test_ga_beats_fcfs_under_congestion():
    """强拥堵算例（2 泊位 + 高峰 90%）：GA 平均在港时间显著优于 FCFS。"""
    from smartport.utils.instance_gen import generate_scenario
    scenario = generate_scenario(
        name="congested-18v", n_vessels=18, n_berths=2, n_cranes=6,
        n_import_blocks=2, n_export_blocks=2, size_profile="small_port",
        eta_span_hours=6.0, peak_ratio=0.9, peak_window=(0.5, 5.0),
        seed=5, block_bays=20, block_stacks_per_bay=6, block_tiers=4)
    service = estimate_service_hours(scenario.vessels)
    fcfs_plan, _ = solve_bap_fcfs(scenario.vessels, scenario.berths, service)
    ga_plan, _ = solve_bap_ga(
        scenario.vessels, scenario.berths, service,
        config={"population": 40, "generations": 40}, seed=42, n_cranes=6)

    def avg_port(plan) -> float:
        vmap = scenario.vessel_map()
        return sum(a.end - vmap[a.vessel_id].eta for a in plan) / len(plan)

    assert avg_port(ga_plan) < avg_port(fcfs_plan)


def test_ga_solves_40v_within_budget(tmp_path):
    """40 船标准规模：GA 主求解应在 30 秒内完成（交付指标）。"""
    from smartport.utils.instance_gen import generate_scenario
    scenario = generate_scenario(
        n_vessels=40, seed=7, n_import_blocks=5, n_export_blocks=3,
        block_bays=28, block_stacks_per_bay=8, block_tiers=5)
    service = estimate_service_hours(scenario.vessels)
    t0 = time.perf_counter()
    plan, meta = solve_bap_ga(
        scenario.vessels, scenario.berths, service,
        config={"population": 50, "generations": 60}, seed=42)
    elapsed = time.perf_counter() - t0
    assert len(plan) == 40
    assert validate_berth_plan(plan, scenario.vessels, scenario.berths) == []
    assert elapsed < 30.0, f"GA exceeded 30s budget: {elapsed:.1f}s"
    assert meta["solve_seconds"] > 0


def test_mip_warm_start_or_fallback(scenario10):
    """MIP：有 pulp 时应返回可行解或明确回退状态。"""
    import pulp  # noqa: F401  (环境装有 pulp；无 pulp 环境跳过本测试)
    service = estimate_service_hours(scenario10.vessels)
    fcfs_plan, _ = solve_bap_fcfs(scenario10.vessels, scenario10.berths, service)
    plan, meta = solve_bap_mip(
        scenario10.vessels, scenario10.berths, service,
        config={"time_limit": 10.0}, warm_start_plan=fcfs_plan)
    if plan is not None:
        assert validate_berth_plan(plan, scenario10.vessels,
                                   scenario10.berths) == []
    else:
        assert meta["status"]  # 明确的失败原因（供上层回退）
