"""LLM 层测试：无密钥降级、决策解析、纯规则仲裁。"""
from __future__ import annotations

import asyncio

from smartport.agents.conflict_resolution import ConflictResolutionAgent
from smartport.core import topics
from smartport.core.board import ScheduleBoard
from smartport.core.bus import MessageBus
from smartport.llm.client import LLMClient
from smartport.llm.prompts import parse_llm_decision


class TestLLMClient:
    def test_no_key_unavailable(self, monkeypatch):
        monkeypatch.delenv("SMARTPORT_LLM_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        client = LLMClient(api_key="")
        assert client.is_available() is False
        assert client.chat("sys", "user") is None

    def test_chat_failure_returns_none(self, monkeypatch):
        monkeypatch.setenv("SMARTPORT_LLM_API_KEY", "sk-invalid")
        monkeypatch.setenv("SMARTPORT_LLM_BASE_URL",
                           "http://127.0.0.1:1/api/paas/v4")
        client = LLMClient(timeout=0.5)
        assert client.chat("sys", "user") is None  # 连接失败 → None → 降级


class TestParseDecision:
    def test_valid_json(self):
        text = '好的，我的建议是 {"winner": "V002", "reason": "优先级更高"}'
        d = parse_llm_decision(text, ["V001", "V002"])
        assert d == {"winner": "V002", "reason": "优先级更高"}

    def test_invalid_winner(self):
        assert parse_llm_decision('{"winner": "VX"}', ["V001"]) is None

    def test_garbage(self):
        assert parse_llm_decision("no json here", ["V001"]) is None
        assert parse_llm_decision(None, ["V001"]) is None


def _conflict_payload() -> dict:
    return {
        "berth_id": "B1",
        "vessels": [
            {"vessel_id": "V001", "role": "incumbent", "start": 2.0,
             "end": 9.5, "planned_end": 8.0, "wait_hours": 0.5, "eta": 1.5,
             "moves": 500, "priority": 2, "preferred_berth": None},
            {"vessel_id": "V002", "role": "challenger", "start": 8.5,
             "end": 13.0, "planned_end": 13.0, "wait_hours": 2.0, "eta": 6.5,
             "moves": 480, "priority": 2, "preferred_berth": "B1"},
        ],
    }


def test_rule_arbitration_without_llm():
    """纯规则模式：优先级高者胜，败方平移至胜方完工 + 缓冲。"""
    async def scenario():
        bus = MessageBus()
        board = ScheduleBoard(bus)
        agent = ConflictResolutionAgent(bus, board, llm_client=None,
                                        use_llm=False, buffer_hours=0.5)
        await agent.start()
        resp = await bus.request("orchestrator", "conflict_agent",
                                 topics.ARBITRATION_REQUEST,
                                 _conflict_payload())
        await agent.stop()
        assert resp.payload["ok"] is True
        assert resp.payload["method"] == "rule"
        assert resp.payload["winner"] == "V001"    # moves 更大者赢
        assert resp.payload["loser"] == "V002"
        assert resp.payload["new_loser_start"] == 10.0  # 9.5 + 0.5

    asyncio.run(scenario())


def test_llm_unavailable_falls_back_to_rule(monkeypatch):
    """LLM 增强开启但无密钥 → 自动回退规则仲裁（100% 可运行）。"""
    async def scenario():
        monkeypatch.delenv("SMARTPORT_LLM_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        client = LLMClient(api_key="")
        bus = MessageBus()
        board = ScheduleBoard(bus)
        agent = ConflictResolutionAgent(bus, board, llm_client=client,
                                        use_llm=True)
        await agent.start()
        resp = await bus.request("orchestrator", "conflict_agent",
                                 topics.ARBITRATION_REQUEST,
                                 _conflict_payload())
        await agent.stop()
        assert resp.payload["ok"] is True
        assert resp.payload["method"] == "rule"

    asyncio.run(scenario())
