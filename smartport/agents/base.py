"""Agent 基类：统一的消息循环、请求分发与生命周期管理。

子类通过 register_handler(topic, fn) 声明支持的请求主题，
fn 为同步或异步函数：payload(dict) -> payload(dict)。
广播事件通过覆盖 on_event 处理（默认仅记录日志）。
"""
from __future__ import annotations

import abc
import asyncio
import logging
from typing import Any, Awaitable, Callable

from smartport.core.bus import Message, MessageBus, MsgType
from smartport.core.board import ScheduleBoard

Handler = Callable[[dict], Any] | Callable[[dict], Awaitable[Any]]


class BaseAgent(abc.ABC):
    """多 Agent 系统的抽象基类。"""

    name: str = "agent"

    def __init__(self, bus: MessageBus, board: ScheduleBoard) -> None:
        self.bus = bus
        self.board = board
        self.queue = bus.register(self.name)
        self.handlers: dict[str, Handler] = {}
        self.logger = logging.getLogger(f"smartport.agent.{self.name}")
        self._task: asyncio.Task | None = None
        self._running = False

    # ------------------------------------------------------------ 生命周期
    async def start(self) -> None:
        """启动消息循环协程。"""
        if self._task is None or self._task.done():
            self._running = True
            self._task = asyncio.get_running_loop().create_task(self._run())
            self.logger.info("agent started")

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
            self.logger.info("agent stopped")

    async def _run(self) -> None:
        """消息主循环：Observation 入口。"""
        while self._running:
            msg = await self.queue.get()
            try:
                await self._dispatch(msg)
            except Exception:  # noqa: BLE001 - Agent 隔离，单个消息异常不终止循环
                self.logger.exception("error handling message topic=%s", msg.topic)

    async def _dispatch(self, msg: Message) -> None:
        if msg.type == MsgType.REQUEST:
            handler = self.handlers.get(msg.topic)
            if handler is None:
                await self.bus.reply_error(msg, f"no handler for topic {msg.topic}")
                return
            try:
                result = handler(msg.payload)
                if asyncio.iscoroutine(result):
                    result = await result
                await self.bus.reply(msg, {"ok": True, **result})
            except Exception as exc:  # noqa: BLE001
                self.logger.exception("handler failed for %s", msg.topic)
                await self.bus.reply_error(msg, str(exc))
        else:
            await self.on_event(msg)

    # ------------------------------------------------------------ 扩展点
    def register_handler(self, topic: str, handler: Handler) -> None:
        self.handlers[topic] = handler

    async def on_event(self, msg: Message) -> None:
        """广播事件钩子（子类可覆盖以订阅状态变更）。"""
        self.logger.debug("event %s from %s", msg.topic, msg.sender)

    @abc.abstractmethod
    def description(self) -> str:
        """Agent 职责描述（用于日志与文档）。"""
