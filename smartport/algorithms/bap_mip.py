"""BAP 精确求解：混合整数规划（MIP，基于 pulp + CBC）。

模型（离散泊位、连续时间）：
- x[i,b] = 1 当且仅当船 i 靠泊位 b（仅对静态可行泊位建变量）；
- t[i] ≥ ETA_i 为靠泊开始时刻；
- y[i,j] ∈ {0,1}（i<j）表示同泊位时的先后关系；
- 同泊位互斥约束通过大 M 松弛线性化。

目标：最小化 Σ w_i·(t_i + s_i) + 偏好泊位违反惩罚。
支持 warm start（注入 FCFS/GA 解加速 CBC 找到可行解）；
未安装 pulp 或时限内无可行解时返回 None，由上层回退遗传算法。
"""
from __future__ import annotations

import logging
import time

from smartport.algorithms.bap_common import feasible_berths, validate_berth_plan
from smartport.core.models import Berth, BerthAssignment, Vessel

logger = logging.getLogger("smartport.mip")

MIP_DEFAULTS: dict = {
    "time_limit": 25.0,          # CBC 求解时限（秒）
    "pref_penalty": 2.0,         # 偏好泊位违反惩罚（目标函数系数）
    "gap_rel": 0.02,             # 相对间隙
}


def solve_bap_mip(
    vessels: list[Vessel],
    berths: list[Berth],
    service_hours: dict[str, float],
    config: dict | None = None,
    warm_start_plan: list[BerthAssignment] | None = None,
) -> tuple[list[BerthAssignment] | None, dict]:
    """MIP 求解 BAP。返回 (方案或 None, 元信息)。"""
    try:
        import pulp
    except ImportError:
        return None, {"algorithm": "mip", "status": "pulp not installed"}

    cfg = {**MIP_DEFAULTS, **(config or {})}
    t0 = time.perf_counter()

    feas: dict[str, list[Berth]] = {v.id: feasible_berths(v, berths) for v in vessels}
    for v, bs in feas.items():
        if not bs:
            return None, {"algorithm": "mip", "status": f"vessel {v} infeasible"}

    # 大 M：覆盖最坏情形（全部船串行于单泊位）
    horizon = max(v.eta for v in vessels) + sum(service_hours.values())

    model = pulp.LpProblem("BAP", pulp.LpMinimize)
    x = {(v.id, b.id): pulp.LpVariable(f"x_{v.id}_{b.id}", cat="Binary")
         for v in vessels for b in feas[v.id]}
    t = {v.id: pulp.LpVariable(f"t_{v.id}", lowBound=v.eta) for v in vessels}
    y: dict[tuple[str, str], pulp.LpVariable] = {}
    for i, vi in enumerate(vessels):
        for vj in vessels[i + 1:]:
            y[(vi.id, vj.id)] = pulp.LpVariable(
                f"y_{vi.id}_{vj.id}", cat="Binary")

    # 每船恰靠一个泊位
    for v in vessels:
        model += pulp.lpSum(x[(v.id, b.id)] for b in feas[v.id]) == 1, f"assign_{v.id}"

    # 同泊位互斥（大 M 线性化）
    M = horizon * 1.2
    for i, vi in enumerate(vessels):
        for vj in vessels[i + 1:]:
            yv = y[(vi.id, vj.id)]
            shared = [b for b in feas[vi.id] if b in feas[vj.id]]
            for b in shared:
                xb = x[(vi.id, b.id)]
                xj = x[(vj.id, b.id)]
                model += (
                    t[vi.id] + service_hours[vi.id]
                    <= t[vj.id] + M * (1 - yv) + M * (2 - xb - xj)
                ), f"mutex_{vi.id}_{vj.id}_{b.id}_a"
                model += (
                    t[vj.id] + service_hours[vj.id]
                    <= t[vi.id] + M * yv + M * (2 - xb - xj)
                ), f"mutex_{vi.id}_{vj.id}_{b.id}_b"

    # 目标：加权完工时刻（等价加权在港时间，因 s_i 与 ETA_i 为常数）+ 偏好惩罚
    # 注：不加等待峰值项 —— 实测 40 船规模下额外目标会让 CBC 在时限内解得更差
    obj = pulp.lpSum(
        v.weight * (t[v.id] + service_hours[v.id]) for v in vessels
    )
    for v in vessels:
        if v.preferred_berth and (v.id, v.preferred_berth) in x:
            obj += cfg["pref_penalty"] * (1 - x[(v.id, v.preferred_berth)])
    model += obj

    # ---- warm start：注入已有方案，加速 CBC 获得可行解
    if warm_start_plan:
        try:
            start_map = {a.vessel_id: a for a in warm_start_plan}
            for v in vessels:
                for b in feas[v.id]:
                    x[(v.id, b.id)].setInitialValue(
                        1 if start_map[v.id].berth_id == b.id else 0)
                t[v.id].setInitialValue(start_map[v.id].start)
            for (vid_i, vid_j), yv in y.items():
                ai, aj = start_map[vid_i], start_map[vid_j]
                same_berth = ai.berth_id == aj.berth_id
                yv.setInitialValue(1 if (same_berth and ai.start <= aj.start) else 0)
        except Exception as exc:  # noqa: BLE001 - warm start 失败不应中断求解
            logger.warning("mip: warm start failed (%s), continue cold", exc)

    solver = pulp.PULP_CBC_CMD(
        msg=0,
        timeLimit=cfg["time_limit"],
        gapRel=cfg["gap_rel"],
        warmStart=bool(warm_start_plan),
    )
    status_code = model.solve(solver)
    status = pulp.LpStatus[status_code]
    elapsed = time.perf_counter() - t0

    if status not in ("Optimal", "Not Solved", "Integer Feasible"):
        return None, {"algorithm": "mip", "status": status,
                      "solve_seconds": elapsed}

    # 提取解：泊位 = 取值为 1 的 x，开始 = t
    plan: list[BerthAssignment] = []
    try:
        for v in vessels:
            berth_id = None
            for b in feas[v.id]:
                if round(pulp.value(x[(v.id, b.id)] or 0)) == 1:
                    berth_id = b.id
                    break
            if berth_id is None:
                return None, {"algorithm": "mip", "status": "no berth extracted"}
            start = float(pulp.value(t[v.id]))
            duration = service_hours[v.id]
            plan.append(BerthAssignment(
                vessel_id=v.id, berth_id=berth_id,
                start=start, end=start + duration, planned_end=start + duration,
                wait_hours=round(start - v.eta, 6),
                service_hours=round(duration, 6),
            ))
    except TypeError:
        return None, {"algorithm": "mip", "status": "solution extraction failed"}

    issues = validate_berth_plan(plan, vessels, berths)
    if issues:
        logger.warning("mip: solution violates constraints: %s", issues[:3])
        return None, {"algorithm": "mip", "status": "invalid solution",
                      "issues": issues[:3]}

    meta = {"algorithm": "mip", "status": status, "solve_seconds": elapsed}
    return plan, meta
