"""岸桥调度（CSP）启发式：事件驱动的岸桥指派与作业时序。

输入泊位分配结果，输出：
- 岸桥-船舶指派时序（CraneAssignment 列表）；
- 岸桥调整后的泊位计划（完工时刻可能延长/恢复）；
- 统计（移机次数、单船配额、被减配船列表）。

机制：
1. 按事件（靠泊/完工）推进模拟，为每船分配「就近」空闲岸桥；
2. 高峰期岸桥不足时按需减配 → 作业时间延长（可能引发泊位冲突，
   由 Orchestrator 检测并交给 ConflictResolutionAgent 仲裁）；
3. 岸桥空闲后优先「借调恢复」被减配船只至计划配额（完工时刻提前恢复）；
4. 岸桥换泊位作业记一次移机（moves_count）。

说明：岸桥 non-crossing 采用「就近指派 + 泊位次序」近似，未做严格
不可穿越约束的精确建模（文档中已注明，接口预留）。
"""
from __future__ import annotations

import heapq
import logging

from smartport.algorithms.bap_common import estimate_crane_quota
from smartport.core.models import (
    Berth,
    BerthAssignment,
    CraneAssignment,
    QuayCrane,
    Vessel,
)

logger = logging.getLogger("smartport.crane")

CRANE_DEFAULTS: dict = {
    "max_q_per_vessel": 4,       # 单船岸桥上限
    "borrow_back": True,         # 空闲岸桥优先恢复被减配船只
    "idle_retry_hours": 0.25,    # 无岸桥可用时靠泊推迟步长
}


def plan_cranes(
    berth_plan: list[BerthAssignment],
    vessels: list[Vessel],
    berths: list[Berth],
    cranes: list[QuayCrane],
    config: dict | None = None,
) -> tuple[list[CraneAssignment], list[BerthAssignment], dict]:
    """岸桥调度主入口。返回 (岸桥计划, 修订后泊位计划, 统计信息)。"""
    cfg = {**CRANE_DEFAULTS, **(config or {})}
    vmap = {v.id: v for v in vessels}
    bmap = {b.id: b for b in berths}
    eff = sum(c.efficiency for c in cranes) / max(len(cranes), 1)

    plan_map = {a.vessel_id: dict(a.model_dump()) for a in berth_plan}
    crane_eff = {c.id: c.efficiency for c in cranes}

    free = sorted(cranes, key=lambda c: c.position_m)      # 空闲岸桥池
    crane_to_vessel: dict[str, str] = {}                    # 岸桥 -> 服务船
    crane_last_berth: dict[str, str | None] = {c.id: None for c in cranes}
    crane_moves = 0                                         # 移机次数

    active: dict[str, dict] = {}
    done_at: dict[str, float] = {}
    open_records: dict[tuple[str, str], dict] = {}          # (crane, vessel) -> 记录
    crane_plan: list[CraneAssignment] = []

    events: list[tuple[float, int, str]] = []               # (time, kind, vid)
    for vid, pa in plan_map.items():
        heapq.heappush(events, (pa["start"], 1, vid))

    def settle(vid: str, now: float) -> None:
        """结算在泊船的已完成箱量（连续产量近似）。"""
        st = active[vid]
        dt = now - st["last_update"]
        st["done_moves"] += dt * st["q"] * eff
        st["last_update"] = now

    def push_completion(vid: str) -> None:
        st = active[vid]
        remaining = max(st["moves"] - st["done_moves"], 0.0)
        st["end_est"] = st["last_update"] + remaining / (st["q"] * eff)
        heapq.heappush(events, (round(st["end_est"], 6), 0, vid))

    def take_cranes(vid: str, n: int) -> list[QuayCrane]:
        """从空闲池取 n 台距该船泊位位置最近的岸桥（就近指派）。"""
        berth = bmap[plan_map[vid]["berth_id"]]
        orderd = sorted(free, key=lambda c: abs(c.position_m - berth.position_m))
        picked = orderd[:n]
        for c in picked:
            free.remove(c)
        return picked

    def assign(vid: str, now: float) -> bool:
        """为到港船分配岸桥；成功返回 True。"""
        vessel = vmap[vid]
        q_req = min(cfg["max_q_per_vessel"], estimate_crane_quota(vessel))
        if not free:
            return False
        q = min(q_req, len(free))
        picked = take_cranes(vid, q)
        berth_id = plan_map[vid]["berth_id"]
        for c in picked:
            crane_to_vessel[c.id] = vid
            nonlocal crane_moves
            if crane_last_berth[c.id] not in (None, berth_id):
                crane_moves += 1
            crane_last_berth[c.id] = berth_id
            open_records[(c.id, vid)] = {
                "crane_id": c.id, "vessel_id": vid, "berth_id": berth_id,
                "start": now, "moves": 0,
            }
        # 实际靠泊时刻更新（可能因无岸桥可用而推迟）
        plan_map[vid]["start"] = now
        plan_map[vid]["wait_hours"] = round(now - vessel.eta, 6)
        active[vid] = {
            "moves": float(vessel.moves), "done_moves": 0.0,
            "q": len(picked), "q_req": q_req, "last_update": now,
        }
        push_completion(vid)
        if q < q_req:
            logger.info("crane: vessel %s under-allocated %d/%d cranes", vid, q, q_req)
        return True

    def borrow_back(now: float) -> None:
        """空闲岸桥优先恢复被减配在泊船（完工时刻随之提前恢复）。"""
        if not cfg["borrow_back"] or not free:
            return
        for vid, st in list(active.items()):
            need = st["q_req"] - st["q"]
            if need <= 0 or not free:
                continue
            settle(vid, now)
            picked = take_cranes(vid, need)
            if not picked:
                continue
            berth_id = plan_map[vid]["berth_id"]
            for c in picked:
                crane_to_vessel[c.id] = vid
                nonlocal crane_moves
                if crane_last_berth[c.id] not in (None, berth_id):
                    crane_moves += 1
                crane_last_berth[c.id] = berth_id
                open_records[(c.id, vid)] = {
                    "crane_id": c.id, "vessel_id": vid, "berth_id": berth_id,
                    "start": now, "moves": 0,
                }
            st["q"] += len(picked)
            push_completion(vid)
            logger.info("crane: borrow back %d crane(s) to vessel %s", len(picked), vid)

    def finalize(vid: str, now: float) -> None:
        """船舶完工：关闭岸桥记录、释放岸桥、固化泊位计划。"""
        for (cid, v2), rec in list(open_records.items()):
            if v2 != vid:
                continue
            dur = now - rec["start"]
            crane_plan.append(CraneAssignment(
                crane_id=cid, vessel_id=vid, berth_id=rec["berth_id"],
                start=rec["start"], end=now,
                moves=int(dur * crane_eff[cid]),
            ))
            del open_records[(cid, v2)]
            crane_to_vessel.pop(cid, None)
            crane = next(c for c in cranes if c.id == cid)
            free.append(crane)
        free.sort(key=lambda c: c.position_m)
        done_at[vid] = now
        del active[vid]
        plan_map[vid]["end"] = now
        plan_map[vid]["service_hours"] = round(
            now - plan_map[vid]["start"], 6)

    # ---- 事件循环：同刻先完工释放、再靠泊分配
    while events:
        t, kind, vid = heapq.heappop(events)
        if kind == 0:
            # 惰性失效：仅当事件时刻等于当前估计完工时刻才生效
            st = active.get(vid)
            if st is None or abs(st["end_est"] - t) > 1e-6:
                continue
            settle(vid, t)
            finalize(vid, t)
            borrow_back(t)
        else:
            if vid in active or vid in done_at:
                continue
            if not assign(vid, t):
                # 无岸桥可用：推迟靠泊
                heapq.heappush(events, (round(t + cfg["idle_retry_hours"], 6), 1, vid))

    if active:  # 理论上不会发生（箱量有限必然完工）
        logger.error("crane: %d vessels still active at end", len(active))

    revised = [BerthAssignment.model_validate(p) for p in plan_map.values()]
    revised.sort(key=lambda a: (a.berth_id, a.start))
    extended = [a.vessel_id for a in revised if a.end > a.planned_end + 1e-6]
    stats = {
        "crane_moves": crane_moves,
        "extended_vessels": extended,
        "per_vessel_q": {vid: st.get("q_req") for vid, st in active.items()},
    }
    crane_plan.sort(key=lambda r: (r.crane_id, r.start))
    return crane_plan, revised, stats
