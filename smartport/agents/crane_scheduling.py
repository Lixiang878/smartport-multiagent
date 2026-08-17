"""CraneSchedulingAgent（岸桥调度 Agent）。

职责：给定泊位计划，完成岸桥到船舶的指派与作业时序优化：
- 高峰期岸桥不足时减配（作业延长，可能触发泊位冲突）；
- 空闲岸桥优先「借调恢复」被减配船只；
- 就近指派降低移机次数；
- 输出修订后的泊位计划（完工时刻调整）。
"""
from __future__ import annotations

from smartport.agents.base import BaseAgent
from smartport.algorithms.crane_heuristic import plan_cranes
from smartport.core.board import SECTION_CRANE_PLAN
from smartport.core import topics
from smartport.core.models import Berth, BerthAssignment, QuayCrane, Vessel


class CraneSchedulingAgent(BaseAgent):
    """岸桥调度：指派、时序与移机控制。"""

    name = "crane_agent"

    def __init__(
        self,
        bus,
        board,
        vessels: list[Vessel],
        berths: list[Berth],
        cranes: list[QuayCrane],
        algo_config: dict | None = None,
    ) -> None:
        super().__init__(bus, board)
        self.vessels = vessels
        self.berths = berths
        self.cranes = cranes
        self.algo_config = algo_config or {}
        self.register_handler(topics.CRANE_PLAN_REQUEST, self.handle_plan_request)

    def description(self) -> str:
        return "Quay crane scheduling: assignment, sequencing, move control"

    async def handle_plan_request(self, payload: dict) -> dict:
        """请求-响应：岸桥调度。payload: {"berth_plan": [...]}"""
        berth_plan = [BerthAssignment.model_validate(d)
                      for d in payload["berth_plan"]]
        crane_plan, revised, stats = plan_cranes(
            berth_plan, self.vessels, self.berths, self.cranes,
            config=self.algo_config.get("crane"),
        )
        self.board.update(
            SECTION_CRANE_PLAN,
            {"crane_plan": [r.model_dump() for r in crane_plan],
             "stats": stats},
            self.name,
        )
        self.logger.info(
            "crane plan ready: assignments=%d crane_moves=%d extended=%d",
            len(crane_plan), stats["crane_moves"], len(stats["extended_vessels"]),
        )
        return {
            "crane_plan": [r.model_dump() for r in crane_plan],
            "revised_berth_plan": [a.model_dump() for a in revised],
            "stats": stats,
        }
