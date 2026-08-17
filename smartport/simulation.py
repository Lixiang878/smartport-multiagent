"""PortSimulation：一键组装多 Agent 系统并运行调度闭环。

用法：
    sim = PortSimulation(scenario, algo_config, llm_config)
    async with sim:
        schedule = await sim.run("ga")            # 单模式
        report = await sim.run_comparison()       # fcfs / ga / mip 对比
"""
from __future__ import annotations

import logging

from smartport.agents import (
    BerthAllocationAgent,
    ConflictResolutionAgent,
    CraneSchedulingAgent,
    OrchestratorAgent,
    YardPlanningAgent,
)
from smartport.core.board import ScheduleBoard
from smartport.core.bus import MessageBus
from smartport.core.models import Schedule, Scenario
from smartport.llm import build_client

logger = logging.getLogger("smartport.simulation")

DEFAULT_MODES = ["fcfs", "ga", "mip"]


class PortSimulation:
    """组装消息总线、黑板与五个 Agent 的仿真入口。"""

    def __init__(
        self,
        scenario: Scenario,
        algo_config: dict | None = None,
        llm_config: dict | None = None,
        use_llm: bool = True,
    ) -> None:
        self.scenario = scenario
        self.algo_config = algo_config or {}
        self.bus = MessageBus()
        self.board = ScheduleBoard(self.bus)

        crane_eff = (
            sum(c.efficiency for c in scenario.cranes) / len(scenario.cranes)
            if scenario.cranes else 30.0
        )
        self.berth_agent = BerthAllocationAgent(
            self.bus, self.board, scenario.vessels, scenario.berths,
            algo_config=self.algo_config, crane_efficiency=crane_eff,
            n_cranes=len(scenario.cranes))
        self.crane_agent = CraneSchedulingAgent(
            self.bus, self.board, scenario.vessels, scenario.berths,
            scenario.cranes, algo_config=self.algo_config)
        self.yard_agent = YardPlanningAgent(
            self.bus, self.board, scenario.vessels, scenario.blocks,
            scenario.containers, algo_config=self.algo_config)
        llm_client = build_client(llm_config) if use_llm else None
        self.conflict_agent = ConflictResolutionAgent(
            self.bus, self.board, llm_client=llm_client, use_llm=use_llm)
        self.orchestrator = OrchestratorAgent(self.bus, self.board, scenario)
        self.agents = [self.orchestrator, self.berth_agent, self.crane_agent,
                       self.yard_agent, self.conflict_agent]

        self.board.update("scenario", {
            "name": scenario.name, "vessels": len(scenario.vessels),
            "berths": len(scenario.berths), "cranes": len(scenario.cranes),
        }, "simulation")

    # ------------------------------------------------------------ 生命周期
    async def start(self) -> None:
        for agent in self.agents:
            await agent.start()
        logger.info("simulation ready: agents=%s", self.bus.agents)

    async def stop(self) -> None:
        for agent in self.agents:
            await agent.stop()

    async def __aenter__(self) -> "PortSimulation":
        await self.start()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.stop()

    # ------------------------------------------------------------ 运行
    async def run(self, mode: str = "ga") -> Schedule:
        """运行单个模式的完整调度闭环。"""
        return await self.orchestrator.plan(mode)

    async def run_comparison(
        self, modes: list[str] | None = None
    ) -> dict[str, Schedule]:
        """依次运行多组模式并返回对比结果。"""
        results: dict[str, Schedule] = {}
        for mode in (modes or DEFAULT_MODES):
            logger.info("comparison run: mode=%s", mode)
            results[mode] = await self.run(mode)
        return results
