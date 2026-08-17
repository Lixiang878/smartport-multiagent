"""OrchestratorAgent（协调器）：调度闭环的驱动核心。

执行闭环：
- Observation：感知全局状态（黑板快照）；
- Planning：向专业 Agent 发起请求-响应（泊位 → 岸桥 → 堆场）；
- Execution：应用仲裁决策（平移受影响船舶及其岸桥时序）；
- Review：每阶段校验方案一致性（约束校验 + 泊位重叠检测），
  发现冲突时移交 ConflictResolutionAgent 仲裁并循环直至消解。

本协调器同时承担任务分解、全局状态监控与 Agent 间冲突处理。
"""
from __future__ import annotations

import time

from smartport.agents.base import BaseAgent
from smartport.algorithms.bap_common import validate_berth_plan
from smartport.algorithms.metrics import evaluate
from smartport.core import topics
from smartport.core.board import (
    SECTION_BERTH_PLAN,
    SECTION_CRANE_PLAN,
    SECTION_KPI,
    SECTION_PHASE,
)
from smartport.core.models import (
    BerthAssignment,
    CraneAssignment,
    Schedule,
    Scenario,
    YardPlanItem,
)

EPS = 1e-6


class OrchestratorAgent(BaseAgent):
    """接收船舶到港计划，分解任务、监控状态、处理冲突。"""

    name = "orchestrator"

    def __init__(
        self,
        bus,
        board,
        scenario: Scenario,
        conflict_agent: str = "conflict_agent",
        max_arbitration_rounds: int = 30,
    ) -> None:
        super().__init__(bus, board)
        self.scenario = scenario
        self.conflict_agent = conflict_agent
        self.max_arbitration_rounds = max_arbitration_rounds

    def description(self) -> str:
        return "Orchestrator: task decomposition, review, conflict handling"

    # ------------------------------------------------------------ 主闭环
    async def plan(self, mode: str) -> Schedule:
        """完整调度闭环：泊位 → 岸桥 → 冲突仲裁 → 堆场 → KPI 汇总。"""
        t0 = time.perf_counter()
        notes: list[str] = []
        vessels, berths = self.scenario.vessels, self.scenario.berths

        # ---- Observation：黑板置为泊位规划阶段
        self.board.update(SECTION_PHASE, "berth_planning", self.name)
        self.logger.info("=== scheduling cycle start (mode=%s, %d vessels) ===",
                         mode, len(vessels))

        # ---- Planning 1/3：泊位分配（请求-响应）
        resp = await self.bus.request(
            self.name, "berth_agent", topics.BERTH_PLAN_REQUEST,
            {"mode": mode})
        if not resp.payload.get("ok"):
            raise RuntimeError(f"berth planning failed: {resp.payload}")
        berth_plan = [BerthAssignment.model_validate(d)
                      for d in resp.payload["berth_plan"]]
        notes.extend(resp.payload.get("notes", []))

        # ---- Review：泊位计划约束校验
        issues = validate_berth_plan(berth_plan, vessels, berths)
        if issues:
            notes.append(f"berth review issues: {issues}")

        # ---- Planning 2/3：岸桥调度（可能延长完工时刻）
        self.board.update(SECTION_PHASE, "crane_scheduling", self.name)
        resp = await self.bus.request(
            self.name, "crane_agent", topics.CRANE_PLAN_REQUEST,
            {"berth_plan": [a.model_dump() for a in berth_plan]})
        if not resp.payload.get("ok"):
            raise RuntimeError(f"crane scheduling failed: {resp.payload}")
        crane_plan = [CraneAssignment.model_validate(d)
                      for d in resp.payload["crane_plan"]]
        revised = [BerthAssignment.model_validate(d)
                   for d in resp.payload["revised_berth_plan"]]
        crane_stats: dict = resp.payload["stats"]

        # ---- Review + Execution：泊位重叠检测 → 仲裁循环
        self.board.update(SECTION_PHASE, "conflict_resolution", self.name)
        for round_no in range(1, self.max_arbitration_rounds + 1):
            conflict = self._first_overlap(revised)
            if conflict is None:
                break
            # 广播冲突事件（订阅者可感知）
            self.bus.publish(self.name, topics.CONFLICT_DETECTED,
                             {"round": round_no, **conflict})
            self.logger.warning(
                "conflict round %d on berth %s: %s(end=%.1f) overlaps %s(start=%.1f)",
                round_no, conflict["berth_id"],
                conflict["vessels"][0]["vessel_id"], conflict["vessels"][0]["end"],
                conflict["vessels"][1]["vessel_id"], conflict["vessels"][1]["start"],
            )
            arb = await self.bus.request(
                self.name, self.conflict_agent,
                topics.ARBITRATION_REQUEST, conflict)
            if not arb.payload.get("ok"):
                raise RuntimeError(f"arbitration failed: {arb.payload}")
            self._apply_arbitration(revised, crane_plan, arb.payload)
            notes.append(
                f"[arbitration r{round_no}] berth {conflict['berth_id']}: "
                f"{arb.payload['winner']} keeps berth, "
                f"{arb.payload['loser']} delayed to "
                f"{arb.payload['new_loser_start']:.2f}h "
                f"({arb.payload['method']}: {arb.payload['reason']})"
            )
        else:
            notes.append("arbitration round limit reached, residual conflicts remain")

        # ---- Planning 3/3：堆场规划（感知最终泊位计划的重叠结构）
        self.board.update(SECTION_PHASE, "yard_planning", self.name)
        resp = await self.bus.request(
            self.name, "yard_agent", topics.YARD_PLAN_REQUEST,
            {"berth_plan": [a.model_dump() for a in revised]})
        if not resp.payload.get("ok"):
            raise RuntimeError(f"yard planning failed: {resp.payload}")
        yard_plan = [YardPlanItem.model_validate(d)
                     for d in resp.payload["yard_plan"]]

        # ---- Review：最终方案一致性校验
        final_issues = validate_berth_plan(revised, vessels, berths)
        if final_issues:
            notes.append(f"final review issues: {final_issues}")
        else:
            notes.append("final review: berth plan consistent")

        # ---- KPI 汇总与黑板发布
        elapsed = time.perf_counter() - t0
        kpi = evaluate(
            self.scenario, revised, crane_plan, yard_plan,
            solve_seconds=elapsed, extra=crane_stats)
        self.board.update(SECTION_KPI, kpi.model_dump(), self.name)
        self.board.update(SECTION_BERTH_PLAN,
                          [a.model_dump() for a in revised], self.name)
        self.board.update(SECTION_CRANE_PLAN,
                          [r.model_dump() for r in crane_plan], self.name)

        schedule = Schedule(
            mode=mode, berth_plan=revised, crane_plan=crane_plan,
            yard_plan=yard_plan, kpi=kpi, notes=notes)
        self.bus.publish(self.name, topics.SIM_COMPLETE,
                         {"mode": mode, "makespan": kpi.makespan_hours})
        self.logger.info(
            "=== cycle done (mode=%s): avg_port=%.2fh max_wait=%.2fh "
            "reshuffles=%d elapsed=%.1fs ===",
            mode, kpi.avg_port_time_hours, kpi.max_wait_hours,
            kpi.total_reshuffles, elapsed)
        return schedule

    # ------------------------------------------------------------ 冲突检测
    def _first_overlap(
        self, plan: list[BerthAssignment]
    ) -> dict | None:
        """检测第一个同泊位时间重叠（岸桥延长完工所致）。

        返回仲裁请求 payload：incumbent = 靠泊较早者，challenger = 被挤占者。
        """
        vmap = self.scenario.vessel_map()
        by_berth: dict[str, list[BerthAssignment]] = {}
        for a in plan:
            by_berth.setdefault(a.berth_id, []).append(a)

        for bid, items in by_berth.items():
            items.sort(key=lambda x: x.start)
            for prev, cur in zip(items, items[1:]):
                if prev.end > cur.start + EPS:
                    def info(a: BerthAssignment, role: str) -> dict:
                        v = vmap[a.vessel_id]
                        return {
                            "vessel_id": a.vessel_id, "role": role,
                            "start": a.start, "end": a.end,
                            "planned_end": a.planned_end,
                            "wait_hours": a.wait_hours,
                            "eta": v.eta, "moves": v.moves,
                            "priority": v.priority,
                            "preferred_berth": v.preferred_berth,
                        }
                    return {
                        "berth_id": bid,
                        "vessels": [info(prev, "incumbent"),
                                    info(cur, "challenger")],
                    }
        return None

    # ------------------------------------------------------------ 仲裁执行
    def _apply_arbitration(
        self,
        plan: list[BerthAssignment],
        crane_plan: list[CraneAssignment],
        decision: dict,
    ) -> None:
        """Execution：败方及其同泊位后续船整体后移，岸桥时序同步平移。"""
        loser_id = decision["loser"]
        new_start = decision["new_loser_start"]
        loser = next(a for a in plan if a.vessel_id == loser_id)
        delta = new_start - loser.start
        if delta <= 0:
            return
        vmap = self.scenario.vessel_map()

        # 同泊位、排在 loser 之后（含）的船舶级联平移，保持先后序
        shifted: set[str] = set()
        for a in plan:
            if a.berth_id == loser.berth_id and a.start >= loser.start - EPS:
                a.start = round(a.start + delta, 6)
                a.end = round(a.end + delta, 6)
                a.planned_end = round(a.planned_end + delta, 6)
                a.wait_hours = round(a.start - vmap[a.vessel_id].eta, 6)
                shifted.add(a.vessel_id)

        for r in crane_plan:
            if r.vessel_id in shifted:
                r.start = round(r.start + delta, 6)
                r.end = round(r.end + delta, 6)

        self.logger.info("execution: shifted %d vessel(s) on berth %s by %.2fh",
                         len(shifted), loser.berth_id, delta)
