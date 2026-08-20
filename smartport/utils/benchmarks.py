"""文献基准算例（移植自 Berth-Scheduler，适配 smartport 数据模型）。

复现 Imai et al. (2001, 2005) 及 BAP/QCAP 相关文献的小规模测试算例，
用于与公开数字交叉校验。算例以 smartport 的 Scenario 表达：
- 船长/到港时刻按原样转录；
- 作业量按「base_handling × 2 台岸桥 × 30 moves/h」映射为 moves
  （服务时长换算关系在 README 中声明）；
- 岸桥总数按原算例配置。
"""
from __future__ import annotations

from smartport.core.models import (Berth, QuayCrane, Scenario, Vessel)

__all__ = ["benchmark_scenario", "BENCHMARK_NAMES"]

BENCHMARK_NAMES = ("imai_5_2", "imai_10_3", "dense_20_5")

# (id, length_m, eta_h, base_handling_h) —— Imai 风格转录
_IMAI_5_2_VESSELS = [
    (0, 200.0, 0.0, 12.0),
    (1, 180.0, 3.0, 10.0),
    (2, 250.0, 6.0, 15.0),
    (3, 150.0, 8.0, 8.0),
    (4, 220.0, 12.0, 13.0),
]
_IMAI_5_2_BERTHS = [(300.0, 0.0), (250.0, 300.0)]

_IMAI_10_3_VESSELS = [
    (0, 200.0, 0.0, 12.0),
    (1, 180.0, 2.0, 10.0),
    (2, 250.0, 5.0, 15.0),
    (3, 150.0, 7.0, 8.0),
    (4, 220.0, 10.0, 13.0),
    (5, 190.0, 14.0, 11.0),
    (6, 240.0, 18.0, 14.0),
    (7, 170.0, 22.0, 9.0),
    (8, 210.0, 25.0, 12.0),
    (9, 230.0, 30.0, 14.0),
]
_IMAI_10_3_BERTHS = [(300.0, 0.0), (250.0, 300.0), (280.0, 550.0)]


def _vessels(specs: list[tuple[int, float, float, float]]) -> list[Vessel]:
    out = []
    for vid, length, eta, base_h in specs:
        moves = max(1, round(base_h * 2 * 30))   # 2 台岸桥 × 30 moves/h
        out.append(Vessel(
            id=f"V{vid + 1:02d}", name=f"MV-bench-{vid + 1:02d}",
            size="medium", length_m=length, draft_m=10.0, eta=eta,
            moves=moves, priority=3,
        ))
    return out


def _berths(specs: list[tuple[float, float]]) -> list[Berth]:
    return [
        Berth(id=f"B{i + 1}", name=f"Berth-{i + 1}", length_m=length,
              depth_m=15.0, position_m=pos)
        for i, (length, pos) in enumerate(specs)
    ]


def _cranes(n: int) -> list[QuayCrane]:
    return [QuayCrane(id=f"QC{i + 1}", position_m=i * 40.0) for i in range(n)]


def benchmark_scenario(name: str = "imai_5_2") -> Scenario:
    """按名称返回文献基准 Scenario。"""
    if name == "imai_5_2":
        return Scenario(name="imai_5_2", horizon_hours=72.0,
                        vessels=_vessels(_IMAI_5_2_VESSELS),
                        berths=_berths(_IMAI_5_2_BERTHS),
                        cranes=_cranes(4), blocks=[])
    if name == "imai_10_3":
        return Scenario(name="imai_10_3", horizon_hours=96.0,
                        vessels=_vessels(_IMAI_10_3_VESSELS),
                        berths=_berths(_IMAI_10_3_BERTHS),
                        cranes=_cranes(6), blocks=[])
    if name == "dense_20_5":
        import random
        rng = random.Random(123)
        specs = []
        for i in range(20):
            length = max(120.0, rng.gauss(220, 40))
            eta = rng.uniform(0, 48)
            base_h = max(4.0, rng.gauss(12, 3))
            specs.append((i, length, eta, base_h))
        berth_specs = [(max(200.0, rng.gauss(300, 40)), i * 320.0) for i in range(5)]
        return Scenario(name="dense_20_5", horizon_hours=120.0,
                        vessels=_vessels(specs), berths=_berths(berth_specs),
                        cranes=_cranes(8), blocks=[])
    raise ValueError(
        f"unknown benchmark '{name}'; choose from {', '.join(BENCHMARK_NAMES)}")
