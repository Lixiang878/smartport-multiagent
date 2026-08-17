"""BAP 自适应遗传算法（NSGA-II 思路）。

染色体 = (船舶服务顺序排列, 每船偏好泊位表)，解码复用贪心插空器。

多目标（NSGA-II 非支配排序 + 拥挤距离）：
- f1: 优先级加权平均在港时间（主目标）
- f2: 等待时间峰值
- f3: 偏好泊位违反数

自适应机制：种群多样性下降时自动提高变异概率，
避免早熟收敛；精英保留确保单调不退化。
"""
from __future__ import annotations

import random
import time

from smartport.algorithms.bap_common import decode_schedule, feasible_berths
from smartport.core.models import Berth, BerthAssignment, Vessel

GA_DEFAULTS: dict = {
    "population": 50,
    "generations": 60,
    "p_crossover": 0.9,
    "p_mut_base": 0.15,          # 基础变异率（自适应上浮至 0.45）
    "elite_size": 4,             # 精英保留数
    "order_mut": "swap",         # swap / inversion
    "max_concurrent": 0,         # 同时在泊船数上限（0 = 按岸桥数自动估计）
    "overload_penalty": 0.5,     # 超载船·小时惩罚系数（感知下游岸桥瓶颈）
    "peak_wait_weight": 0.02,    # 最终解选择时等待峰值权重
}


# ---------------------------------------------------------------- 个体与目标

def _overload_hours(plan: list[BerthAssignment], cap: int) -> float:
    """在泊船数超过容量上限的「超额船·小时」积分（下游岸桥可行性感知）。"""
    events: list[tuple[float, int]] = []
    for a in plan:
        events.append((a.start, 1))
        events.append((a.end, -1))
    events.sort()
    cur, prev_t, total = 0, None, 0.0
    for t, d in events:
        if prev_t is not None and cur > cap:
            total += (t - prev_t) * (cur - cap)
        cur += d
        prev_t = t
    return total


def _objectives(
    plan: list[BerthAssignment], vessels: list[Vessel],
    cap: int = 0, overload_penalty: float = 0.0,
) -> tuple[float, float, int]:
    """(加权平均在港时间+超载惩罚, 等待峰值, 偏好违反数)。"""
    vmap = {v.id: v for v in vessels}
    total_w = sum(v.weight for v in vessels)
    weighted = sum(
        vmap[a.vessel_id].weight * a.port_time for a in plan
    ) / max(total_w, 1e-9)
    if cap > 0:
        weighted += overload_penalty * _overload_hours(plan, cap)
    max_wait = max((a.wait_hours for a in plan), default=0.0)
    violations = sum(
        1 for a in plan
        if vmap[a.vessel_id].preferred_berth
        and a.berth_id != vmap[a.vessel_id].preferred_berth
    )
    return weighted, max_wait, violations


def _evaluate(
    order: list[str],
    pref: dict[str, str | None],
    vessels: list[Vessel],
    berths: list[Berth],
    service_hours: dict[str, float],
    cap: int = 0,
    overload_penalty: float = 0.0,
) -> tuple[list[BerthAssignment], tuple[float, float, int]]:
    plan = decode_schedule(order, pref, vessels, berths, service_hours)
    return plan, _objectives(plan, vessels, cap, overload_penalty)


# ---------------------------------------------------------------- 遗传算子

def _ox_crossover(p1: list[str], p2: list[str], rng: random.Random) -> list[str]:
    """顺序交叉 OX：保留 p1 片段，其余按 p2 相对顺序填充。"""
    n = len(p1)
    i, j = sorted(rng.sample(range(n), 2))
    segment = p1[i:j]
    fill = [g for g in p2 if g not in segment]
    child = fill[:i] + segment + fill[i:]
    return child


def _swap_mutate(order: list[str], rng: random.Random) -> list[str]:
    i, j = rng.sample(range(len(order)), 2)
    order[i], order[j] = order[j], order[i]
    return order


def _inversion_mutate(order: list[str], rng: random.Random) -> list[str]:
    i, j = sorted(rng.sample(range(len(order)), 2))
    order[i:j] = reversed(order[i:j])
    return order


# ---------------------------------------------------------------- NSGA-II

def _dominates(a: tuple, b: tuple) -> bool:
    return all(x <= y for x, y in zip(a, b)) and any(x < y for x, y in zip(a, b))


def _fast_non_dominated_sort(objs: list[tuple]) -> list[list[int]]:
    """返回各支配层（front 0 为帕累托前沿）。"""
    n = len(objs)
    dominated: list[list[int]] = [[] for _ in range(n)]
    dom_count = [0] * n
    fronts: list[list[int]] = [[]]
    for p in range(n):
        for q in range(n):
            if p == q:
                continue
            if _dominates(objs[p], objs[q]):
                dominated[p].append(q)
            elif _dominates(objs[q], objs[p]):
                dom_count[p] += 1
        if dom_count[p] == 0:
            fronts[0].append(p)
    fi = 0
    while fronts[fi]:
        nxt: list[int] = []
        for p in fronts[fi]:
            for q in dominated[p]:
                dom_count[q] -= 1
                if dom_count[q] == 0:
                    nxt.append(q)
        fi += 1
        fronts.append(nxt)
    return [f for f in fronts if f]


def _crowding_distance(objs: list[tuple], front: list[int]) -> dict[int, float]:
    """按各目标归一化极差计算拥挤距离。"""
    dist = {i: 0.0 for i in front}
    m = len(objs[front[0]])
    for k in range(m):
        srt = sorted(front, key=lambda i: objs[i][k])
        dist[srt[0]] = dist[srt[-1]] = float("inf")
        lo, hi = objs[srt[0]][k], objs[srt[-1]][k]
        if hi - lo < 1e-12:
            continue
        for a, b, c in zip(srt, srt[1:], srt[2:]):
            dist[b] += (objs[c][k] - objs[a][k]) / (hi - lo)
    return dist


# ---------------------------------------------------------------- 主流程

def solve_bap_ga(
    vessels: list[Vessel],
    berths: list[Berth],
    service_hours: dict[str, float],
    config: dict | None = None,
    seed: int = 42,
    n_cranes: int = 8,
) -> tuple[list[BerthAssignment], dict]:
    """自适应 NSGA-II 求解 BAP，返回（最终入选方案, 元信息）。

    目标函数内置岸桥容量超载惩罚（同时在泊船数超过 cap 时计入
    超额船·小时 × penalty），使泊位计划感知下游岸桥瓶颈。
    """
    cfg = {**GA_DEFAULTS, **(config or {})}
    # 在泊船数上限：按「平均岸桥配额 ≈ 3 台/船」估计（12 岸桥 → 4 船）
    cap = int(cfg["max_concurrent"]) or max(2, n_cranes // 3)
    overload_penalty = float(cfg["overload_penalty"])
    rng = random.Random(seed)
    ids = [v.id for v in vessels]
    feasible: dict[str, list[Berth]] = {
        v.id: feasible_berths(v, berths) for v in vessels
    }
    mutator = _inversion_mutate if cfg["order_mut"] == "inversion" else _swap_mutate

    def random_pref() -> dict[str, str | None]:
        out: dict[str, str | None] = {}
        for v in vessels:
            cands = feasible[v.id]
            out[v.id] = (
                rng.choice(cands).id if cands and rng.random() < 0.7 else v.preferred_berth
            )
        return out

    # ---- 初始种群：FCFS 种子 + 随机个体
    fcfs_order = [v.id for v in sorted(vessels, key=lambda v: (v.eta, v.priority, v.id))]
    population: list[tuple[list[str], dict[str, str | None]]] = [(fcfs_order, {
        v.id: v.preferred_berth for v in vessels})]
    while len(population) < cfg["population"]:
        order = ids[:]
        rng.shuffle(order)
        population.append((order, random_pref()))

    best_plan: list[BerthAssignment] | None = None
    best_key: float | None = None
    best_obj: tuple | None = None
    peak_w = float(cfg["peak_wait_weight"])
    t0 = time.perf_counter()

    for _gen in range(cfg["generations"]):
        # ---- 评估
        plans: list[list[BerthAssignment] | None] = []
        objs: list[tuple] = []
        for order, pref in population:
            plan, obj = _evaluate(order, pref, vessels, berths, service_hours,
                                  cap, overload_penalty)
            plans.append(plan)
            objs.append(obj)
        # 记录历史最优（精英，防止退化）；选择键考虑等待峰值
        for plan, obj in zip(plans, objs):
            key = obj[0] + peak_w * obj[1]
            if best_key is None or key < best_key:
                best_key, best_obj, best_plan = key, obj, plan

        fronts = _fast_non_dominated_sort(objs)
        rank = {i: fi for fi, f in enumerate(fronts) for i in f}
        crowd = {}
        for f in fronts:
            crowd.update(_crowding_distance(objs, f))

        # ---- 自适应变异率：第一前沿唯一解比例低 → 提高变异
        unique_front = len({tuple(population[i][0]) for i in fronts[0]})
        diversity = unique_front / max(len(fronts[0]), 1)
        p_mut = min(cfg["p_mut_base"] + (1.0 - diversity) * 0.30, 0.45)

        # ---- 环境选择：精英 + 锦标赛产生下一代
        def tournament() -> tuple[list[str], dict[str, str | None]]:
            a, b = rng.sample(range(len(population)), 2)
            ka = (rank[a], -crowd[a])
            kb = (rank[b], -crowd[b])
            return population[a] if ka <= kb else population[b]

        new_pop: list[tuple[list[str], dict[str, str | None]]] = []
        elite_idx = sorted(range(len(population)),
                           key=lambda i: (rank[i], -crowd[i]))[: cfg["elite_size"]]
        new_pop.extend(population[i] for i in elite_idx)
        while len(new_pop) < cfg["population"]:
            p1, p2 = tournament(), tournament()
            if rng.random() < cfg["p_crossover"]:
                child_order = _ox_crossover(p1[0], p2[0], rng)
                child_pref = {
                    k: (p1[1][k] if rng.random() < 0.5 else p2[1][k]) for k in p1[1]
                }
            else:
                child_order, child_pref = p1
            if rng.random() < p_mut:
                child_order = mutator(child_order[:], rng)
            if rng.random() < 0.1:                       # 偏好基因小概率重置
                vid = rng.choice(ids)
                cands = feasible[vid]
                if cands:
                    child_pref[vid] = rng.choice(cands).id
            new_pop.append((child_order, child_pref))
        population = new_pop

    elapsed = time.perf_counter() - t0
    assert best_plan is not None and best_obj is not None
    meta = {
        "algorithm": "ga",
        "objectives": {
            "weighted_port_time": best_obj[0],
            "max_wait": best_obj[1],
            "pref_violations": best_obj[2],
        },
        "max_concurrent": cap,
        "generations": cfg["generations"],
        "population": cfg["population"],
        "solve_seconds": elapsed,
    }
    return best_plan, meta
