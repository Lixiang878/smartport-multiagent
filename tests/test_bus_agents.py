"""消息总线与 Agent 交互流程测试。"""
from __future__ import annotations

import asyncio

from smartport.agents.base import BaseAgent
from smartport.core.board import ScheduleBoard
from smartport.core.bus import Message, MessageBus, MsgType
from smartport.core import topics
from smartport.simulation import PortSimulation


class EchoAgent(BaseAgent):
    """测试用回显 Agent：请求原样返回，事件计数。"""

    name = "echo_agent"

    def __init__(self, bus, board):
        super().__init__(bus, board)
        self.events: list[str] = []
        self.register_handler("echo.request", lambda p: {"echo": p})

    def description(self) -> str:
        return "echo for tests"

    async def on_event(self, msg) -> None:
        self.events.append(msg.topic)


class CallerAgent(BaseAgent):
    name = "caller_agent"

    def __init__(self, bus, board):
        super().__init__(bus, board)

    def description(self) -> str:
        return "caller for tests"


def test_bus_register_duplicate():
    bus = MessageBus()
    bus.register("a")
    try:
        bus.register("a")
        assert False, "duplicate registration should raise"
    except ValueError:
        pass


def test_bus_request_response():
    async def scenario():
        bus = MessageBus()
        board = ScheduleBoard(bus)
        echo = EchoAgent(bus, board)
        caller = CallerAgent(bus, board)
        await echo.start()
        await caller.start()
        resp = await bus.request("caller_agent", "echo_agent",
                                 "echo.request", {"x": 1})
        assert resp.type == MsgType.RESPONSE
        assert resp.payload == {"ok": True, "echo": {"x": 1}}
        await echo.stop()
        await caller.stop()

    asyncio.run(scenario())


def test_bus_broadcast_and_board_events():
    async def scenario():
        bus = MessageBus()
        board = ScheduleBoard(bus)
        echo = EchoAgent(bus, board)
        await echo.start()
        await bus.broadcast(Message(type=MsgType.EVENT, sender="other",
                                    topic="hello.topic", payload={}))
        await asyncio.sleep(0.05)          # 等待事件循环投递
        assert "hello.topic" in echo.events
        # 黑板更新会广播 STATE_UPDATED（订阅者可感知）
        board.update("phase", "testing", "other")
        await asyncio.sleep(0.05)
        assert topics.STATE_UPDATED in echo.events
        assert board.version >= 1
        await echo.stop()

    asyncio.run(scenario())


def test_full_simulation_cycle(scenario10):
    """端到端：10 船 GA 模式完整闭环（含岸桥/堆场/仲裁/KPI）。"""
    async def scenario():
        sim = PortSimulation(scenario10, use_llm=False)
        async with sim:
            schedule = await sim.run("ga")
        assert schedule.mode == "ga"
        assert schedule.kpi is not None
        assert schedule.kpi.n_vessels == len(scenario10.vessels)
        assert schedule.kpi.makespan_hours > 0
        assert len(schedule.berth_plan) == len(scenario10.vessels)
        assert len(schedule.crane_plan) > 0
        assert len(schedule.yard_plan) > 0
        # 黑板上留存全局状态
        assert sim.board.get("kpi") is not None
        # 总线消息日志支持回溯
        assert len(sim.bus.message_log) >= 3
        return schedule

    asyncio.run(scenario())


def test_comparison_runs_all_modes(scenario10):
    """对比模式：fcfs / ga 均可运行并产出方案。"""
    async def scenario():
        sim = PortSimulation(scenario10, use_llm=False)
        async with sim:
            results = await sim.run_comparison(["fcfs", "ga"])
        assert set(results) == {"fcfs", "ga"}
        for sch in results.values():
            assert sch.kpi is not None

    asyncio.run(scenario())
