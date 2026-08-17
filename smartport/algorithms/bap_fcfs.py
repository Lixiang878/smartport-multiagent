"""BAP 基准算法：FCFS（先到先服务）。

按 (ETA, 优先级, ID) 排序逐船分配最早可用泊位，
作为衡量优化算法（GA / MIP）改进幅度的 baseline。
"""
from __future__ import annotations

import time

from smartport.algorithms.bap_common import decode_schedule
from smartport.core.models import Berth, BerthAssignment, Vessel


def solve_bap_fcfs(
    vessels: list[Vessel],
    berths: list[Berth],
    service_hours: dict[str, float],
) -> tuple[list[BerthAssignment], dict]:
    """FCFS 泊位分配：顺序 = 到港先后（同刻优先级高者先）。"""
    t0 = time.perf_counter()
    order = [v.id for v in sorted(vessels, key=lambda v: (v.eta, v.priority, v.id))]
    pref = {v.id: v.preferred_berth for v in vessels}
    plan = decode_schedule(order, pref, vessels, berths, service_hours)
    meta = {"algorithm": "fcfs", "solve_seconds": time.perf_counter() - t0}
    return plan, meta
