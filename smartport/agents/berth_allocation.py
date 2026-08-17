"""BerthAllocationAgent（泊位分配 Agent）。

三种求解模式：
- fcfs：先到先服务基准；
- ga：自适应 NSGA-II 遗传算法；
- mip：pulp + CBC 精确求解（以 FCFS 解 warm start，时限内未找到
  可行解时自动回退遗传算法并记录说明）。

决策流程：接收 Orchestrator 的泊位计划请求 → 求解 → 黑板发布 → 响应。
"""
from __future__ import annotations

from smartport.agents.base import BaseAgent
from smartport.algorithms.bap_common import estimate_service_hours
from smartport.algorithms.bap_fcfs import solve_bap_fcfs
from smartport.algorithms.bap_ga import solve_bap_ga
from smartport.algorithms.bap_mip import solve_bap_mip
from smartport.core.board import SECTION_BERTH_PLAN
from smartport.core import topics
from smartport.core.models import Berth, Vessel


class BerthAllocationAgent(BaseAgent):
    """负责泊位-船舶分配（BAP），最小化加权总在港时间。"""

    name = "berth_agent"

    def __init__(
        self,
        bus,
        board,
        vessels: list[Vessel],
        berths: list[Berth],
        algo_config: dict | None = None,
        crane_efficiency: float = 30.0,
        n_cranes: int = 8,
    ) -> None:
        super().__init__(bus, board)
        self.vessels = vessels
        self.berths = berths
        self.algo_config = algo_config or {}
        self.crane_efficiency = crane_efficiency
        self.n_cranes = n_cranes
        self.register_handler(topics.BERTH_PLAN_REQUEST, self.handle_plan_request)

    def description(self) -> str:
        return "Berth allocation (BAP): FCFS / GA(NSGA-II) / MIP(pulp)"

    async def handle_plan_request(self, payload: dict) -> dict:
        """请求-响应：生成泊位分配方案。payload: {"mode": "fcfs"|"ga"|"mip"}"""
        mode = payload.get("mode", "ga")
        service = estimate_service_hours(self.vessels, self.crane_efficiency)
        notes: list[str] = []
        mode_used = mode

        if mode == "fcfs":
            plan, meta = solve_bap_fcfs(self.vessels, self.berths, service)
        elif mode == "ga":
            plan, meta = solve_bap_ga(
                self.vessels, self.berths, service,
                config=self.algo_config.get("ga"),
                seed=payload.get("seed", 42),
                n_cranes=self.n_cranes,
            )
        elif mode == "mip":
            # 先解 FCFS 作为 warm start，加速 CBC 找到可行解
            warm, _ = solve_bap_fcfs(self.vessels, self.berths, service)
            plan, meta = solve_bap_mip(
                self.vessels, self.berths, service,
                config=self.algo_config.get("mip"),
                warm_start_plan=warm,
            )
            if plan is None:
                reason = meta.get("status", "unknown")
                plan, meta = solve_bap_ga(
                    self.vessels, self.berths, service,
                    config=self.algo_config.get("ga"),
                    seed=payload.get("seed", 42),
                    n_cranes=self.n_cranes,
                )
                notes.append(
                    f"MIP 求解失败（{reason}），已自动回退遗传算法")
                mode_used = "ga (fallback of mip)"
            else:
                mode_used = "mip"
        else:
            raise ValueError(f"unknown berth planning mode: {mode}")

        # 黑板发布状态变更（广播 STATE_UPDATED）
        self.board.update(
            SECTION_BERTH_PLAN, [a.model_dump() for a in plan], self.name)
        self.logger.info(
            "berth plan ready: mode=%s vessels=%d solve=%.2fs",
            mode, len(plan), meta.get("solve_seconds", 0.0))
        return {
            "berth_plan": [a.model_dump() for a in plan],
            "meta": meta,
            "mode_used": mode_used,
            "notes": notes,
        }
