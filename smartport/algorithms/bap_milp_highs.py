"""BAP 精确求解（HiGHS 后端，经 scipy.optimize.milp）。

离散时间模型（移植自 Berth-Scheduler 并适配 smartport 数据模型）：
- x[i,b,s] ∈ {0,1}：船 i 在泊位 b、时段 s 开工；
- 目标：最小化 Σ w_i·(开工 + 服务时长 − ETA)，即加权在港时间；
- 约束：每船恰一个 (泊位, 开工)；同一泊位同一时段至多一船在作业；
  静态不可行（长度/水深）与早于 ETA 的变量直接固定为 0。

定位：小规模算例（≤10 船）的 ground truth，用于校验 GA/MIP-CBC 解质量；
大规模请用 GA。scipy 为可选依赖，未安装时返回明确状态供上层回退。
"""
from __future__ import annotations

import logging
import math
import time

from smartport.algorithms.bap_common import feasible_berths, validate_berth_plan
from smartport.core.models import Berth, BerthAssignment, Vessel

logger = logging.getLogger("smartport.milp_highs")

MILP_DEFAULTS: dict = {
    "time_step": 0.5,        # 离散时段粒度（h）
    "max_periods": 400,      # 时段数上限（控制变量规模）
    "time_limit": 30.0,      # HiGHS 求解时限（秒）
}


def solve_bap_milp_highs(
    vessels: list[Vessel],
    berths: list[Berth],
    service_hours: dict[str, float],
    config: dict | None = None,
    warm_start_plan: list[BerthAssignment] | None = None,  # 接口对齐，HiGHS 路径暂不用
) -> tuple[list[BerthAssignment] | None, dict]:
    """HiGHS 精确求解 BAP。返回 (方案或 None, 元信息)。"""
    try:
        import numpy as np
        from scipy.optimize import Bounds, LinearConstraint, milp
    except ImportError:
        return None, {"algorithm": "milp_highs", "status": "scipy not installed"}

    cfg = {**MILP_DEFAULTS, **(config or {})}
    t0 = time.perf_counter()
    dt = float(cfg["time_step"])

    feas = {v.id: feasible_berths(v, berths) for v in vessels}
    for v in vessels:
        if not feas[v.id]:
            return None, {"algorithm": "milp_highs",
                          "status": f"vessel {v.id} has no feasible berth"}

    horizon = max(v.eta for v in vessels) + sum(service_hours.values()) + 12.0
    T = min(int(cfg["max_periods"]), math.ceil(horizon / dt))
    n, B = len(vessels), len(berths)
    nvar = n * B * T
    idx = lambda i, b, s: i * B * T + b * T + s  # noqa: E731

    # 目标：加权在港时间
    c_obj = np.zeros(nvar)
    for i, v in enumerate(vessels):
        s_i = service_hours[v.id]
        for b in range(B):
            for s in range(T):
                c_obj[idx(i, b, s)] = v.weight * (s * dt + s_i - v.eta)

    constraints = []
    # 每船恰选一个 (泊位, 开工)
    A_one = np.zeros((n, nvar))
    for i in range(n):
        for b in range(B):
            for s in range(T):
                A_one[i, idx(i, b, s)] = 1.0
    constraints.append(LinearConstraint(A_one, 1, 1))

    # 泊位时段互斥：对每个 (泊位, 时段)，占用该时段的开工选择之和 ≤ 1
    rows = []
    for b in range(B):
        for t in range(T):
            row = np.zeros(nvar)
            for i, v in enumerate(vessels):
                h_periods = max(1, math.ceil(service_hours[v.id] / dt))
                for s in range(max(0, t - h_periods + 1), min(T, t + 1)):
                    row[idx(i, b, s)] = 1.0
            if row.any():
                rows.append(row)
    if rows:
        constraints.append(LinearConstraint(np.vstack(rows), 0, 1))

    # 静态不可行 / 早于 ETA：变量上界置 0
    ub = np.ones(nvar)
    bmap_idx = {b.id: b_i for b_i, b in enumerate(berths)}
    for i, v in enumerate(vessels):
        infeasible = [b for b in berths if b not in feas[v.id]]
        for b in infeasible:
            bi = bmap_idx[b.id]
            ub[idx(i, bi, 0): idx(i, bi, T)] = 0.0
        min_period = math.ceil(v.eta / dt)
        for b in range(B):
            ub[idx(i, b, 0): idx(i, b, 0) + min(min_period, T)] = 0.0

    res = milp(c=c_obj, constraints=constraints,
               integrality=np.ones(nvar, dtype=int),
               bounds=Bounds(np.zeros(nvar), ub),
               options={"time_limit": cfg["time_limit"]})
    elapsed = time.perf_counter() - t0
    if res.status != 0:
        return None, {"algorithm": "milp_highs", "status": res.message,
                      "feasible": False, "solve_seconds": elapsed}

    x = res.x.reshape(n, B, T)
    plan: list[BerthAssignment] = []
    for i, v in enumerate(vessels):
        pos = np.argwhere(x[i] > 0.5)
        if len(pos) == 0:
            return None, {"algorithm": "milp_highs",
                          "status": f"no assignment extracted for {v.id}"}
        b_i, s = int(pos[0][0]), int(pos[0][1])
        start = s * dt
        duration = service_hours[v.id]
        plan.append(BerthAssignment(
            vessel_id=v.id, berth_id=berths[b_i].id,
            start=start, end=start + duration, planned_end=start + duration,
            wait_hours=round(start - v.eta, 6),
            service_hours=round(duration, 6),
        ))

    issues = validate_berth_plan(plan, vessels, berths)
    if issues:
        logger.warning("milp_highs: solution violates constraints: %s", issues[:3])
        return None, {"algorithm": "milp_highs", "status": "invalid solution",
                      "issues": issues[:3], "solve_seconds": elapsed}

    meta = {"algorithm": "milp_highs", "status": res.message,
            "milp_obj": float(res.fun), "solve_seconds": elapsed}
    return plan, meta
