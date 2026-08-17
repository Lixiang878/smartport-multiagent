"""YardPlanningAgent（堆场规划 Agent）。

职责：进出口箱分箱区、贝位分层堆存，最小化装船前翻箱次数。
堆场分配感知泊位计划的作业重叠（重叠船错开箱区），
因此不同的泊位方案会导出不同的翻箱水平。
"""
from __future__ import annotations

from smartport.agents.base import BaseAgent
from smartport.algorithms.yard_heuristic import plan_yard
from smartport.core.board import SECTION_YARD_PLAN
from smartport.core import topics
from smartport.core.models import (
    BerthAssignment,
    Container,
    ContainerBlock,
    Vessel,
)


class YardPlanningAgent(BaseAgent):
    """堆场规划：分箱区堆存与翻箱最小化。"""

    name = "yard_agent"

    def __init__(
        self,
        bus,
        board,
        vessels: list[Vessel],
        blocks: list[ContainerBlock],
        containers: list[Container],
        algo_config: dict | None = None,
    ) -> None:
        super().__init__(bus, board)
        self.vessels = vessels
        self.blocks = blocks
        self.containers = containers
        self.algo_config = algo_config or {}
        self.register_handler(topics.YARD_PLAN_REQUEST, self.handle_plan_request)

    def description(self) -> str:
        return "Yard planning: block allocation + reshuffle minimization"

    async def handle_plan_request(self, payload: dict) -> dict:
        """请求-响应：堆场规划。payload: {"berth_plan": [...]}"""
        berth_plan = [BerthAssignment.model_validate(d)
                      for d in payload["berth_plan"]]
        items, stats = plan_yard(
            self.vessels, self.blocks, self.containers, berth_plan,
            config=self.algo_config.get("yard"),
            seed=payload.get("seed", 42),
        )
        self.board.update(
            SECTION_YARD_PLAN, [i.model_dump() for i in items], self.name)
        self.logger.info(
            "yard plan ready: vessels=%d reshuffles=%d",
            len(items), stats["total_reshuffles"],
        )
        return {
            "yard_plan": [i.model_dump() for i in items],
            "stats": stats,
        }
