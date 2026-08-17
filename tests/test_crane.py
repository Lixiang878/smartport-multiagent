"""岸桥调度启发式测试：并发约束、指派正确性、修订一致性。"""
from __future__ import annotations

from smartport.algorithms.crane_heuristic import plan_cranes


def test_crane_concurrency_limit(scenario10):
    """任一时刻在役岸桥数不得超过总岸桥数。"""
    from smartport.algorithms.bap_fcfs import solve_bap_fcfs
    from smartport.algorithms.bap_common import estimate_service_hours
    service = estimate_service_hours(scenario10.vessels)
    plan, _ = solve_bap_fcfs(scenario10.vessels, scenario10.berths, service)
    crane_plan, revised, stats = plan_cranes(
        plan, scenario10.vessels, scenario10.berths, scenario10.cranes)

    n_cranes = len(scenario10.cranes)
    events: list[tuple[float, int, str]] = []
    for r in crane_plan:
        events.append((r.start, 1, r.crane_id))
        events.append((r.end, -1, r.crane_id))
    busy: set[str] = set()
    peak = 0
    for t, kind, cid in sorted(events):
        if kind == 1:
            busy.add(cid)
            peak = max(peak, len(busy))
        else:
            busy.discard(cid)
    assert peak <= n_cranes
    assert len(revised) == len(plan)
    assert stats["crane_moves"] >= 0


def test_every_vessel_served(scenario10):
    """每艘船至少分配到一台岸桥且完成作业。"""
    from smartport.algorithms.bap_fcfs import solve_bap_fcfs
    from smartport.algorithms.bap_common import estimate_service_hours
    service = estimate_service_hours(scenario10.vessels)
    plan, _ = solve_bap_fcfs(scenario10.vessels, scenario10.berths, service)
    crane_plan, revised, _ = plan_cranes(
        plan, scenario10.vessels, scenario10.berths, scenario10.cranes)
    served = {r.vessel_id for r in crane_plan}
    assert served == {v.id for v in scenario10.vessels}
    # 修订计划中完工不早于开始
    for a in revised:
        assert a.end > a.start
        assert a.service_hours > 0
