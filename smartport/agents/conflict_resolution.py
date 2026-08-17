"""ConflictResolutionAgent（冲突仲裁 Agent）。

两级仲裁机制：
1. 规则引擎（默认，100% 离线可用）：
   优先级 → 作业量 → 已等待时长 → 先到先得 的字典序规则；
2. LLM 增强模式（可选）：当两船优先级相同且作业量接近（规则难以裁决的
   「灰色地带」）时，将冲突场景结构化后交由 LLM（OpenAI/GLM 兼容接口）
   给出裁决建议；LLM 不可用或输出非法时自动回退规则引擎。

仲裁输出：winner / loser 及 loser 的新靠泊时刻（由规则统一执行：
loser 平移至 winner 完工 + 缓冲时间）。
"""
from __future__ import annotations

from smartport.agents.base import BaseAgent
from smartport.core import topics
from smartport.llm import LLMClient, build_conflict_prompt, parse_llm_decision
from smartport.llm.prompts import CONFLICT_SYSTEM_PROMPT

# 规则难以裁决的灰色地带阈值
GRAY_ZONE_PRIORITY_EQUAL = True
GRAY_ZONE_MOVES_RATIO = 0.2     # 作业量相对差 < 20% 视为接近


class ConflictResolutionAgent(BaseAgent):
    """资源冲突仲裁：规则引擎 + LLM 增强（可切换）。"""

    name = "conflict_agent"

    def __init__(
        self,
        bus,
        board,
        llm_client: LLMClient | None = None,
        use_llm: bool = True,
        buffer_hours: float = 0.5,
    ) -> None:
        super().__init__(bus, board)
        self.llm = llm_client
        self.use_llm = use_llm
        self.buffer_hours = buffer_hours
        self.register_handler(topics.ARBITRATION_REQUEST, self.handle_arbitration)

    def description(self) -> str:
        mode = "rule+llm" if (self.use_llm and self.llm and self.llm.is_available()) else "rule"
        return f"Conflict resolution ({mode})"

    # ------------------------------------------------------------ 规则引擎
    def _rule_decide(self, vessels: list[dict]) -> dict:
        """字典序规则：优先级 > 作业量 > 已等待 > 先到先得。"""

        def key(v: dict) -> tuple:
            return (
                v.get("priority", 5),        # 优先级高者（数值小）赢
                -v.get("moves", 0),          # 作业量大者赢（锁定大船进度）
                -v.get("wait_hours", 0.0),   # 已等待久者赢
                v.get("eta", 0.0),           # 早到者赢
                v.get("vessel_id", ""),      # 稳定 tie-break
            )

        ranked = sorted(vessels, key=key)
        winner, loser = ranked[0], ranked[1]
        reason = (
            f"rule: priority={winner.get('priority')} moves={winner.get('moves')} "
            f"wait={winner.get('wait_hours', 0):.1f}h"
        )
        return {"winner": winner["vessel_id"], "loser": loser["vessel_id"],
                "reason": reason, "method": "rule"}

    def _is_gray_zone(self, vessels: list[dict]) -> bool:
        """规则灰色地带：优先级相同且作业量接近。"""
        if len(vessels) != 2:
            return False
        a, b = vessels
        if a.get("priority") != b.get("priority"):
            return False
        ma, mb = max(a.get("moves", 1), 1), max(b.get("moves", 1), 1)
        return abs(ma - mb) / max(ma, mb) < GRAY_ZONE_MOVES_RATIO

    # ------------------------------------------------------------ LLM 增强
    def _llm_decide(self, conflict: dict) -> dict | None:
        if not (self.use_llm and self.llm and self.llm.is_available()):
            return None
        vessels = conflict.get("vessels", [])
        valid_ids = [v["vessel_id"] for v in vessels]
        prompt = build_conflict_prompt(conflict)
        text = self.llm.chat(system=CONFLICT_SYSTEM_PROMPT, user=prompt)
        decision = parse_llm_decision(text, valid_ids)
        if decision is None:
            self.logger.info("llm output invalid/unavailable, fallback to rule")
            return None
        loser = next(v["vessel_id"] for v in vessels
                     if v["vessel_id"] != decision["winner"])
        decision.update({"loser": loser, "method": "llm"})
        return decision

    # ------------------------------------------------------------ 仲裁入口
    async def handle_arbitration(self, payload: dict) -> dict:
        """请求-响应：仲裁一个泊位重叠冲突。

        payload: {"berth_id", "vessels": [incumbent, challenger], ...}
        返回: {"winner", "loser", "new_loser_start", "method", "reason"}
        """
        vessels = payload["vessels"]
        decision: dict | None = None
        if self._is_gray_zone(vessels):
            self.logger.info("gray-zone conflict on berth %s, trying LLM",
                             payload.get("berth_id"))
            decision = self._llm_decide(payload)
        if decision is None:
            decision = self._rule_decide(vessels)

        vmap = {v["vessel_id"]: v for v in vessels}
        winner_end = vmap[decision["winner"]]["end"]
        new_loser_start = round(winner_end + self.buffer_hours, 6)
        result = {**decision, "new_loser_start": new_loser_start,
                  "berth_id": payload.get("berth_id")}

        # 广播仲裁结果（订阅者可感知）
        self.bus.publish(self.name, topics.ARBITRATION_DECIDED, {
            "berth_id": payload.get("berth_id"),
            "winner": decision["winner"],
            "loser": decision["loser"],
            "method": decision["method"],
            "reason": decision["reason"],
        })
        self.logger.info(
            "arbitration on berth %s: winner=%s loser=%s method=%s, "
            "loser new start = %.2fh",
            payload.get("berth_id"), decision["winner"], decision["loser"],
            decision["method"], new_loser_start,
        )
        return result
