"""HiGHS 精确解测试（scipy 为可选依赖，未安装时跳过）。"""
import pytest

pytest.importorskip("scipy")  # HiGHS 经 scipy.optimize.milp 提供

from smartport.algorithms.bap_common import (estimate_service_hours,  # noqa: E402
                                             validate_berth_plan)
from smartport.algorithms.bap_fcfs import solve_bap_fcfs  # noqa: E402
from smartport.algorithms.bap_milp_highs import solve_bap_milp_highs  # noqa: E402
from smartport.utils.benchmarks import benchmark_scenario  # noqa: E402


def test_milp_highs_solves_imai_5_2():
    sc = benchmark_scenario("imai_5_2")
    service = estimate_service_hours(sc.vessels)
    plan, meta = solve_bap_milp_highs(sc.vessels, sc.berths, service)
    assert plan is not None, meta
    assert validate_berth_plan(plan, sc.vessels, sc.berths) == []
    assert {a.vessel_id for a in plan} == {v.id for v in sc.vessels}
    assert all(a.start >= v.eta - 1e-6
               for a in plan for v in sc.vessels if v.id == a.vessel_id)


def test_milp_highs_not_worse_than_fcfs_up_to_discretization():
    sc = benchmark_scenario("imai_5_2")
    service = estimate_service_hours(sc.vessels)
    fcfs_plan, _ = solve_bap_fcfs(sc.vessels, sc.berths, service)
    exact_plan, meta = solve_bap_milp_highs(sc.vessels, sc.berths, service)
    assert exact_plan is not None, meta

    def weighted_total(plan):
        w = {v.id: v.weight for v in sc.vessels}
        return sum(w[a.vessel_id] * (a.wait_hours + a.service_hours)
                   for a in plan)

    # 精确解不劣于 FCFS；容忍离散时段粒度（0.5h）带来的上取整松弛
    slack = 0.5 * len(sc.vessels) * max(w for w in
                                        (v.weight for v in sc.vessels))
    assert weighted_total(exact_plan) <= weighted_total(fcfs_plan) + slack
