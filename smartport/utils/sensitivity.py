"""灵敏度分析（移植自 Berth-Scheduler）：岸桥数量对调度收益的影响。

在固定种子的参数化算例上扫描岸桥总数，比较 FCFS 与 GA 的总在港时间，
输出改善幅度曲线——用于回答「加岸桥还有没有边际收益」这类规划问题。
"""
from __future__ import annotations

from smartport.algorithms.bap_common import estimate_service_hours
from smartport.algorithms.bap_fcfs import solve_bap_fcfs
from smartport.algorithms.bap_ga import solve_bap_ga
from smartport.utils.instance_gen import generate_scenario

__all__ = ["crane_sensitivity"]


def _total_port_time(plan) -> float:
    return sum(a.wait_hours + a.service_hours for a in plan)


def crane_sensitivity(
    n_vessels: int = 12,
    n_berths: int = 3,
    cranes_min: int = 3,
    cranes_max: int = 10,
    ga_generations: int = 200,
    seed: int = 7,
) -> list[dict]:
    """扫描岸桥数量，返回每档的 FCFS/GA 总在港时间与改善幅度。"""
    rows: list[dict] = []
    for nc in range(cranes_min, cranes_max + 1):
        scenario = generate_scenario(
            name=f"sens_c{nc}", n_vessels=n_vessels, n_berths=n_berths,
            n_cranes=nc, seed=seed,
        )
        service = estimate_service_hours(scenario.vessels)
        fcfs_plan, _ = solve_bap_fcfs(scenario.vessels, scenario.berths, service)
        ga_plan, _ = solve_bap_ga(
            scenario.vessels, scenario.berths, service,
            config={"generations": ga_generations}, seed=seed, n_cranes=nc)
        f_total = _total_port_time(fcfs_plan)
        g_total = _total_port_time(ga_plan)
        rows.append({
            "n_cranes": nc,
            "fcfs_total_port_hours": round(f_total, 2),
            "ga_total_port_hours": round(g_total, 2),
            "improvement": round((f_total - g_total) / max(f_total, 1e-9), 4),
        })
    return rows
