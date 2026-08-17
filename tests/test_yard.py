"""堆场规划测试：翻箱计算、分箱区、混堆机制。"""
from __future__ import annotations

from smartport.algorithms.yard_heuristic import (
    _count_reshuffles,
    plan_yard,
)
from smartport.core.models import (
    BerthAssignment,
    Container,
    ContainerBlock,
    Vessel,
)


def make_vessel(vid: str, moves: int = 60) -> Vessel:
    return Vessel(id=vid, length_m=200, draft_m=10, eta=0.0,
                  moves=moves, priority=3)


class TestReshuffleCounting:
    def test_perfect_stack_zero(self):
        # 完美堆叠：seq 降序入栈，按升序取箱 → 零翻箱
        st1 = [("V1", 6, 1), ("V1", 4, 1), ("V1", 2, 0)]
        st2 = [("V1", 5, 1), ("V1", 3, 1), ("V1", 1, 0)]
        assert _count_reshuffles([st1[:], st2[:]], "V1") == 0

    def test_blocked_target_counts(self):
        # 栈 [1,2,3]（1 底 3 顶）：取 1 翻 2 次；放回后取 2 再翻 1 次 → 共 3 次
        st = [("V1", 1, 1), ("V1", 2, 1), ("V1", 3, 0)]
        st_other: list = []
        assert _count_reshuffles([st[:], st_other[:]], "V1") == 3

    def test_single_stack_reversal(self):
        # 单栈完全逆序（1 底 4 顶）：取 1 翻 3、取 2 翻 2、取 3 翻 1 → 6 次
        st = [("V1", 1, 1), ("V1", 2, 1), ("V1", 3, 1), ("V1", 4, 1)]
        assert _count_reshuffles([st[:]], "V1") == 6


class TestPlanYard:
    def test_exclusive_bays_low_reshuffles(self):
        """大容量独占 bay：完美堆存 → 翻箱为 0。"""
        vessels = [make_vessel("V1", 60), make_vessel("V2", 60)]
        vessels[1] = vessels[1].model_copy(update={"eta": 0.0})
        containers = [
            Container(id=f"C{i}", vessel_id="V1", kind="export", seq=i + 1)
            for i in range(36)
        ] + [
            Container(id=f"D{i}", vessel_id="V2", kind="export", seq=i + 1)
            for i in range(36)
        ]
        blocks = [ContainerBlock(id="YE01", block_type="export",
                                 bays=10, stacks_per_bay=6, tiers=4)]
        berth_plan = [
            BerthAssignment(vessel_id="V1", berth_id="B1", start=0, end=4,
                            planned_end=4, wait_hours=0, service_hours=4),
            BerthAssignment(vessel_id="V2", berth_id="B1", start=5, end=9,
                            planned_end=9, wait_hours=0, service_hours=4),
        ]
        items, stats = plan_yard(vessels, blocks, containers, berth_plan,
                                 seed=1)
        assert len(items) == 2
        assert stats["total_reshuffles"] == 0
        assert stats["assigned_import"] == 0
        assert stats["assigned_export"] == len(containers)

    def test_capacity_shortage_creates_shared(self):
        """容量不足 → 混堆 → 翻箱 > 0。"""
        vessels = [make_vessel(f"V{i}", 200) for i in range(1, 5)]
        containers = [
            Container(id=f"C{i}", vessel_id=f"V{(i // 50) + 1}",
                      kind="export", seq=(i % 50) + 1)
            for i in range(200)
        ]
        blocks = [ContainerBlock(id="YE01", block_type="export",
                                 bays=2, stacks_per_bay=2, tiers=2)]  # 仅 8 箱容量
        berth_plan = [
            BerthAssignment(vessel_id=f"V{i}", berth_id="B1",
                            start=i * 2.0, end=i * 2.0 + 1.5, planned_end=i * 2.0 + 1.5,
                            wait_hours=0.0, service_hours=1.5)
            for i in range(1, 5)
        ]
        items, stats = plan_yard(vessels, blocks, containers, berth_plan, seed=3)
        assert sum(i.shared_bays for i in items) > 0
        assert stats["assigned_export"] == len(containers)
        assert stats["overflow_blocks"]
