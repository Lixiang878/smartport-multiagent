"""调度方案 KPI 评估：在港时间、等待峰值、翻箱率、资源利用率。"""
from __future__ import annotations

from smartport.core.models import (
    BerthAssignment,
    CraneAssignment,
    KPI,
    Scenario,
    YardPlanItem,
)


def evaluate(
    scenario: Scenario,
    berth_plan: list[BerthAssignment],
    crane_plan: list[CraneAssignment],
    yard_plan: list[YardPlanItem],
    solve_seconds: float = 0.0,
    extra: dict | None = None,
) -> KPI:
    """由三个子计划计算全局 KPI。extra 可携带 crane_moves 等模拟统计。"""
    extra = extra or {}
    vmap = scenario.vessel_map()

    waits = [a.wait_hours for a in berth_plan]
    port_times = [a.end - vmap[a.vessel_id].eta for a in berth_plan]
    weights = [vmap[a.vessel_id].weight for a in berth_plan]
    total_w = max(sum(weights), 1e-9)
    weighted = sum(w * p for w, p in zip(weights, port_times)) / total_w

    makespan = max((a.end for a in berth_plan), default=0.0)
    total_service = sum(a.service_hours for a in berth_plan)
    berth_util = total_service / max(
        len(scenario.berths) * makespan, 1e-9)
    crane_hours = sum(r.end - r.start for r in crane_plan)
    crane_util = crane_hours / max(len(scenario.cranes) * makespan, 1e-9)

    reshuffles = sum(y.reshuffles for y in yard_plan)
    total_moves = sum(v.moves for v in scenario.vessels)
    rate = 1000.0 * reshuffles / max(total_moves, 1)

    return KPI(
        n_vessels=len(berth_plan),
        avg_wait_hours=sum(waits) / max(len(waits), 1),
        max_wait_hours=max(waits, default=0.0),
        avg_port_time_hours=sum(port_times) / max(len(port_times), 1),
        weighted_port_time_hours=weighted,
        total_reshuffles=reshuffles,
        reshuffles_per_1000=rate,
        crane_utilization=crane_util,
        berth_utilization=berth_util,
        makespan_hours=makespan,
        crane_moves_count=int(extra.get("crane_moves", 0)),
        solve_seconds=solve_seconds,
    )
