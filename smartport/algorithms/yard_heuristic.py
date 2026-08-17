"""堆场规划（Yard Planning）启发式：分箱区分贝堆存 + 翻箱次数计算。

核心机制：
1. 进口箱 / 出口箱分箱区（import / export block 池）；
2. 重叠感知轮转分配：作业时间重叠的船舶错开箱区，不重叠船舶复用 bay
   （因此泊位计划越平滑、重叠越少，混堆越少 —— 翻箱指标与 BAP 模式联动）；
3. 栈级堆存：独占 bay 按取箱序倒序完美堆叠（零翻箱）；
   混堆 bay 模拟无序到场（随机入栈，栈含多船箱交错）；
4. 取箱模拟计算翻箱次数：目标箱不在栈顶时，上方箱逐个翻至最优栈。

翻箱定义：装船（export 按装船序）/ 提箱（import 按外卡序）前，
为取到目标箱而搬动其上方箱的次数（含他船障碍箱）。
"""
from __future__ import annotations

import logging
import math
import random
from collections import defaultdict

from smartport.core.models import (
    BerthAssignment,
    Container,
    ContainerBlock,
    YardPlanItem,
)

logger = logging.getLogger("smartport.yard")

YARD_DEFAULTS: dict = {
    "import_dwell_hours": 1e6,   # 进口箱计划期内驻场（外卡提箱缓慢）
    "export_lead_hours": 12.0,   # 出口箱集港提前期（早于船舶到港进场）
    "arrival_batch": 2,          # 到场分段乱序批量（越小越接近理想序）
}

# 重量级堆存序（重箱在下保证堆垛稳定，与装船序冲突产生自然翻箱）
WEIGHT_RANK = {"heavy": 0, "medium": 1, "light": 2}

BayKey = tuple[str, int]
# 栈内容：(vessel_id, seq, weight_rank)，栈底 -> 栈顶
Stack = list[tuple[str, int, int]]


def _choose_dest(stacks: list[Stack], box: tuple, exclude: int) -> int:
    """为障碍箱选择落位栈：优先「栈顶 seq 不大于自身」的最接近栈，
    其次任意未满栈，最坏放回高度最小的栈（含源栈，允许临时超限）。"""
    best, best_key = -1, None
    for dj, dst in enumerate(stacks):
        if dj == exclude or len(dst) >= _TIER_LIMIT:
            continue
        key = dst[-1][1] if dst else -1
        if key <= box[1] and (best_key is None or key > best_key):
            best, best_key = dj, key
    if best >= 0:
        return best
    for dj, dst in enumerate(stacks):
        if dj != exclude and len(dst) < _TIER_LIMIT:
            return dj
    # 全部满：放至（除源栈外）最矮的栈；仅源栈可用时放回源栈
    others = [(len(dst), dj) for dj, dst in enumerate(stacks) if dj != exclude]
    return min(others)[1] if others else exclude


def _count_reshuffles(stacks: list[Stack], vessel_id: str) -> int:
    """按 seq 升序取出指定船舶的全部箱，返回翻箱次数。

    算法：目标箱上方障碍箱依次吊出至暂存（每箱计一次翻箱），
    取出目标后再将障碍箱按「最优栈」规则放回（先出后进保持原相对序）。
    """
    where: dict[tuple[str, int], int] = {}
    for si, st in enumerate(stacks):
        for box in st:
            if box[0] == vessel_id:
                where[(box[0], box[1])] = si
    order = sorted(where.keys(), key=lambda b: b[1])
    reshuffles = 0
    for target in order:
        si = where.get(target)
        if si is None:
            continue
        st = stacks[si]
        held: list[tuple] = []
        while st and st[-1][:2] != target:
            held.append(st.pop())
            reshuffles += 1
        if st and st[-1][:2] == target:
            st.pop()
        for box in reversed(held):
            dest = _choose_dest(stacks, box, si)
            stacks[dest].append(box)
            if box[0] == vessel_id:
                where[(box[0], box[1])] = dest
    return reshuffles


_TIER_LIMIT = 6  # 障碍箱移动的单栈高度上限（全局安全值）


def _place_arrivals(
    arrivals: list[Container],
    bays: list[BayKey],
    bay_stacks: dict[BayKey, list[Stack]],
    blk_map: dict[str, ContainerBlock],
) -> None:
    """按到场序入栈，遵循「重下轻上」堆垛约束。

    每箱放入「栈顶重量不轻于自身且最接近」的未满栈；
    无合适栈则新建栈；无空间则挤入首个未满栈（现实偶发违规）。
    到场序与取箱序（装船序/外卡序）的冲突产生自然翻箱。
    """
    for box in arrivals:
        wr = WEIGHT_RANK.get(box.weight_class, 1)
        # 1) 找可堆叠（栈顶更重）的最接近栈
        best: tuple[BayKey, int] | None = None
        best_top = -1
        for key in bays:
            blk = blk_map[key[0]]
            for si, st in enumerate(bay_stacks[key]):
                if len(st) >= blk.tiers:
                    continue
                top_wr = st[-1][2] if st else -1
                if top_wr <= wr and top_wr >= best_top:
                    if best is None or top_wr > best_top:
                        best, best_top = (key, si), top_wr
        if best is not None:
            bay_stacks[best[0]][best[1]].append((box.vessel_id, box.seq, wr))
            continue
        # 2) 新建栈
        for key in bays:
            blk = blk_map[key[0]]
            if len(bay_stacks[key]) < blk.stacks_per_bay:
                bay_stacks[key].append([(box.vessel_id, box.seq, wr)])
                break
        else:
            # 3) 无空间：挤入第一个未满栈（接受重量违规）
            for key in bays:
                blk = blk_map[key[0]]
                done = False
                for st in bay_stacks[key]:
                    if len(st) < blk.tiers:
                        st.append((box.vessel_id, box.seq, wr))
                        done = True
                        break
                if done:
                    break


def plan_yard(
    vessels: list,
    blocks: list[ContainerBlock],
    containers: list[Container],
    berth_plan: list[BerthAssignment],
    config: dict | None = None,
    seed: int = 42,
) -> tuple[list[YardPlanItem], dict]:
    """堆场规划主入口。返回 (每船 YardPlanItem 列表, 统计信息)。"""
    cfg = {**YARD_DEFAULTS, **(config or {})}
    rng = random.Random(seed)
    berth_map = {a.vessel_id: a for a in berth_plan}

    by_vessel_kind: dict[tuple[str, str], list[Container]] = defaultdict(list)
    for c in containers:
        by_vessel_kind[(c.vessel_id, c.kind)].append(c)

    # 配置容量不足时使用动态 overflow block，避免静默丢箱。
    # overflow block 仍进入正常分配流程，并在统计中单独计数。
    overflow_blocks: list[ContainerBlock] = []
    for kind in ("import", "export"):
        total_kind = sum(
            len(boxes) for (vid, box_kind), boxes in by_vessel_kind.items()
            if box_kind == kind
        )
        if total_kind:
            overflow_blocks.append(ContainerBlock(
                id=f"YOVERFLOW_{kind.upper()}",
                block_type=kind,
                bays=max(1, math.ceil(total_kind / (8 * 5)) + 1),
                stacks_per_bay=8,
                tiers=5,
            ))
    planning_blocks = [*blocks, *overflow_blocks]
    blk_map = {b.id: b for b in planning_blocks}

    # bay 级状态
    bay_windows: dict[BayKey, list[tuple[str, float, float]]] = defaultdict(list)
    bay_stacks: dict[BayKey, list[Stack]] = defaultdict(list)

    def pool_for(kind: str) -> list[ContainerBlock]:
        prim = [b for b in planning_blocks if b.block_type == kind]
        return prim or [b for b in planning_blocks if b.block_type == "mixed"] or planning_blocks

    def allocate_bays(vid: str, window: tuple[float, float],
                      stacks_needed: int, pool: list[ContainerBlock],
                      rotate: int) -> tuple[list[BayKey], int]:
        """为船舶分配栈容量：优先轮转 block 的无重叠 bay，不足回退混堆。"""
        assigned: list[BayKey] = []
        shared = 0
        remaining = stacks_needed
        ordered = pool[rotate % len(pool):] + pool[: rotate % len(pool)]

        def overlap(key: BayKey) -> bool:
            return any(
                not (w[2] <= window[0] or w[1] >= window[1])
                for w in bay_windows[key]
            )

        for fallback in (False, True):
            for blk in ordered:
                for bay in range(blk.bays):
                    if remaining <= 0:
                        break
                    key = (blk.id, bay)
                    cap = blk.stacks_per_bay - len(bay_stacks[key])
                    if cap <= 0:
                        continue
                    ov = overlap(key)
                    if ov and not fallback:
                        continue
                    take = min(cap, remaining)
                    if ov:
                        shared += 1
                    bay_windows[key].append((vid, window[0], window[1]))
                    assigned.append(key)
                    remaining -= take
                if remaining <= 0:
                    break
            if remaining <= 0:
                break
        return assigned, shared

    items: list[YardPlanItem] = []
    total_reshuffles = 0
    assigned_counts = {"import": 0, "export": 0}
    rotate = {"import": 0, "export": 0}
    prev_win: dict[str, tuple[float, float] | None] = {"import": None, "export": None}

    def vessel_start(v) -> float:
        a = berth_map.get(v.id)
        return a.start if a else v.eta

    for vessel in sorted(vessels, key=vessel_start):
        item = YardPlanItem(vessel_id=vessel.id, block_id="-")
        for kind in ("import", "export"):
            boxes = by_vessel_kind.get((vessel.id, kind), [])
            if not boxes:
                continue
            pool = pool_for(kind)
            a = berth_map.get(vessel.id)
            start = a.start if a else vessel.eta
            if kind == "export":
                # 出口箱集港窗：提前进场 -> 船舶离泊（装船完毕释放 bay）
                lead = float(cfg.get("export_lead_hours", 12.0))
                window = (max(0.0, vessel.eta - lead), a.end if a else 1e6)
            else:
                window = (start, cfg["import_dwell_hours"])

            # 重叠感知轮转：与前船作业窗重叠 → 错开到下一个 block
            pw = prev_win[kind]
            if pw is not None and not (pw[1] <= window[0] or pw[0] >= window[1]):
                rotate[kind] += 1
            prev_win[kind] = window

            tiers = pool[rotate[kind] % len(pool)].tiers
            stacks_needed = math.ceil(len(boxes) / tiers)
            bays, shared = allocate_bays(
                vessel.id, window, stacks_needed, pool, rotate[kind])
            if not bays:
                raise RuntimeError(
                    f"yard capacity exhausted after overflow allocation for "
                    f"{vessel.id}/{kind}")

            # ---- 堆叠
            # 独占 bay：按取箱序倒序完美堆叠（seq 降序，栈顶先取）→ 零翻箱；
            # 混堆 bay：到场分段乱序 + 重下轻上约束入栈 → 与他船箱交错产生翻箱。
            if shared == 0:
                ordered_seq = sorted(boxes, key=lambda c: c.seq, reverse=True)
                box_iter = iter(ordered_seq)
                for key in bays:
                    blk = blk_map[key[0]]
                    while len(bay_stacks[key]) < blk.stacks_per_bay:
                        st: Stack = []
                        nxt = next(box_iter, None)
                        while nxt is not None and len(st) < blk.tiers:
                            st.append((nxt.vessel_id, nxt.seq,
                                       WEIGHT_RANK.get(nxt.weight_class, 1)))
                            nxt = next(box_iter, None)
                        if st:
                            bay_stacks[key].append(st)
                        if nxt is None:
                            break
            else:
                batch = int(cfg.get("arrival_batch", 2))
                ordered_seq = sorted(boxes, key=lambda c: c.seq)
                arrivals: list[Container] = []
                for i in range(0, len(ordered_seq), batch):
                    seg = ordered_seq[i:i + batch]
                    rng.shuffle(seg)
                    arrivals.extend(seg)
                _place_arrivals(arrivals, bays, bay_stacks, blk_map)

            # ---- 取箱翻箱模拟（相关 bay 的全部栈，含他船障碍箱）
            related = [s for key in bays for s in bay_stacks[key]]
            reshuffles = _count_reshuffles(related, vessel.id)
            total_reshuffles += reshuffles

            item.block_id = bays[0][0]
            item.bays_used.extend(k[1] for k in bays)
            if kind == "import":
                item.import_containers = len(boxes)
            else:
                item.export_containers = len(boxes)
            assigned_counts[kind] += len(boxes)
            item.reshuffles += reshuffles
            item.shared_bays += shared
        items.append(item)

    expected_counts = {
        "import": sum(1 for c in containers if c.kind == "import"),
        "export": sum(1 for c in containers if c.kind == "export"),
    }
    if assigned_counts != expected_counts:
        raise RuntimeError(
            f"yard assignment incomplete: assigned={assigned_counts}, "
            f"expected={expected_counts}")
    stats = {
        "total_reshuffles": total_reshuffles,
        "items": len(items),
        "assigned_import": assigned_counts["import"],
        "assigned_export": assigned_counts["export"],
        "overflow_blocks": [b.id for b in overflow_blocks],
    }
    return items, stats
