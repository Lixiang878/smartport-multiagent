"""泊位分配问题（BAP）公共工具：服务时长估计、可行泊位筛选、共享解码器。

BAP 采用「离散泊位」模型：同一泊位同一时刻仅服务一艘船，
决策变量为每船的 (泊位, 靠泊开始时刻)，最小化加权总在港时间。
"""
from __future__ import annotations

from smartport.core.models import Berth, BerthAssignment, Vessel

# 岸桥单机默认效率（moves/hour），与配置一致
DEFAULT_CRANE_EFFICIENCY = 30.0
# 单船岸桥配额估计：按作业量映射（小船 2 台，大船 4 台）
CRANE_QUOTA_RULES: list[tuple[int, int]] = [(600, 2), (1400, 3)]  # (moves 上限, 台数)
CRANE_QUOTA_MAX = 4
# 岸桥作业切换缓冲（h），用于冲突仲裁后的级联平移
BERTH_BUFFER_HOURS = 0.5


def estimate_crane_quota(vessel: Vessel) -> int:
    """估计单船岸桥配额（BAP 阶段解耦用）：小船 2 台 / 中船 3 台 / 大船 4 台。"""
    for limit, quota in CRANE_QUOTA_RULES:
        if vessel.moves <= limit:
            return quota
    return CRANE_QUOTA_MAX


def estimate_service_hours(
    vessels: list[Vessel], crane_efficiency: float = DEFAULT_CRANE_EFFICIENCY
) -> dict[str, float]:
    """按估计岸桥配额计算每船服务时长（h）：service = moves / (quota * eff)。"""
    return {
        v.id: v.moves / (estimate_crane_quota(v) * crane_efficiency)
        for v in vessels
    }


def feasible_berths(vessel: Vessel, berths: list[Berth]) -> list[Berth]:
    """静态可行泊位：长度、水深满足（时段约束在解码时检查）。"""
    return [b for b in berths if b.can_host(vessel)]


def earliest_slot(
    occupied: list[tuple[float, float]], earliest: float, duration: float,
    window_to: float = 1e9,
) -> float | None:
    """在泊位占用区间中寻找最早可容纳 [t, t+duration] 的空隙。

    occupied: 已占用区间列表（无需有序，内部排序）；
    返回最早的可行开始时刻，无解返回 None。
    """
    t = earliest
    for s, e in sorted(occupied):
        if t + duration <= s:
            break
        if e > t:
            t = e
    if t + duration > window_to:
        return None
    return t


def decode_schedule(
    order: list[str],
    berth_pref: dict[str, str | None],
    vessels: list[Vessel],
    berths: list[Berth],
    service_hours: dict[str, float],
) -> list[BerthAssignment]:
    """序列解码器（GA 与 FCFS 共用）。

    order: 船舶服务顺序（vessel id 排列）；
    berth_pref: 每船偏好泊位（tie-break 与优先尝试）；
    贪心插空：逐船在可行泊位中选「最早可开工」者，tie-break 为偏好泊位。

    返回 BerthAssignment 列表（含 wait/service 统计）。
    """
    vmap = {v.id: v for v in vessels}
    bmap = {b.id: b for b in berths}
    occupied: dict[str, list[tuple[float, float]]] = {b.id: [] for b in berths}
    assignments: list[BerthAssignment] = []

    for vid in order:
        vessel = vmap[vid]
        duration = service_hours[vid]
        cands = feasible_berths(vessel, berths)
        if not cands:
            raise ValueError(f"vessel {vid} has no feasible berth (draft/length)")

        # 候选排序：偏好泊位优先，其次按泊位索引稳定排序
        pref = berth_pref.get(vid)
        cands.sort(key=lambda b: (0 if b.id == pref else 1, berths.index(b)))

        best: tuple[float, str] | None = None  # (开工时刻, 泊位)
        for b in cands:
            t = earliest_slot(
                occupied[b.id], max(vessel.eta, b.available_from),
                duration, b.available_to,
            )
            if t is None:
                continue
            if best is None or t < best[0] - 1e-9:
                best = (t, b.id)
        if best is None:
            raise ValueError(f"vessel {vid} cannot be berthed within window")

        start, berth_id = best
        end = start + duration
        occupied[berth_id].append((start, end))
        assignments.append(
            BerthAssignment(
                vessel_id=vid,
                berth_id=berth_id,
                start=start,
                end=end,
                planned_end=end,
                wait_hours=round(start - vessel.eta, 6),
                service_hours=round(duration, 6),
            )
        )
    # 泊位占用列表按时间排序，便于后续校验
    _ = bmap  # 保持引用一致性（解码不修改泊位对象）
    return assignments


def validate_berth_plan(
    plan: list[BerthAssignment], vessels: list[Vessel], berths: list[Berth]
) -> list[str]:
    """约束校验（Review 阶段复用）：返回违例描述列表，空列表表示通过。

    检查项：全部分配、泊位可行（长/深）、开始时刻不早于 ETA、同一泊位不重叠。
    """
    issues: list[str] = []
    vmap = {v.id: v for v in vessels}
    bmap = {b.id: b for b in berths}
    assigned = {a.vessel_id for a in plan}
    for v in vessels:
        if v.id not in assigned:
            issues.append(f"vessel {v.id} not assigned")
    by_berth: dict[str, list[BerthAssignment]] = {}
    for a in plan:
        berth = bmap.get(a.berth_id)
        vessel = vmap.get(a.vessel_id)
        if berth is None or vessel is None:
            issues.append(f"unknown id in assignment {a.vessel_id}->{a.berth_id}")
            continue
        if not berth.can_host(vessel):
            issues.append(f"vessel {v.id} infeasible at berth {berth.id}")
        if a.start < vessel.eta - 1e-6:
            issues.append(f"vessel {v.id} starts before ETA")
        by_berth.setdefault(a.berth_id, []).append(a)
    for bid, items in by_berth.items():
        items.sort(key=lambda x: x.start)
        for prev, nxt in zip(items, items[1:]):
            if nxt.start < prev.end - 1e-6:
                issues.append(
                    f"berth {bid} overlap: {prev.vessel_id} ends {prev.end:.2f} "
                    f"but {nxt.vessel_id} starts {nxt.start:.2f}"
                )
    return issues
