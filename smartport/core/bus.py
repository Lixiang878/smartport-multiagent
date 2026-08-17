"""异步消息总线：基于 asyncio Queue 的 Agent 间事件驱动通信。

支持三种协作协议：
- 请求-响应（request/reply，基于 correlation_id + Future）；
- 单播（send，指定接收者）；
- 广播（broadcast，状态变更通知）。

所有消息写入总线日志（message_log），支持回溯与测试断言。
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from enum import Enum

from pydantic import BaseModel, Field

logger = logging.getLogger("smartport.bus")


class MsgType(str, Enum):
    REQUEST = "request"        # 请求（期待响应）
    RESPONSE = "response"      # 响应（携带 correlation_id）
    EVENT = "event"            # 广播事件
    ERROR = "error"            # 错误响应


class Message(BaseModel):
    """总线消息信封。payload 为普通 dict，便于跨 Agent 序列化。"""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    type: MsgType
    sender: str
    receiver: str | None = None                # None 表示广播
    topic: str
    payload: dict = Field(default_factory=dict)
    correlation_id: str | None = None
    timestamp: float = Field(default_factory=time.time)


class MessageBus:
    """轻量异步消息总线：每个 Agent 一个独立队列。"""

    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue[Message]] = {}
        self._pending: dict[str, asyncio.Future[Message]] = {}
        self.message_log: list[Message] = []

    # ------------------------------------------------------------ 注册
    def register(self, agent_name: str) -> asyncio.Queue[Message]:
        if agent_name in self._queues:
            raise ValueError(f"agent already registered: {agent_name}")
        q: asyncio.Queue[Message] = asyncio.Queue()
        self._queues[agent_name] = q
        logger.debug("bus: registered agent '%s'", agent_name)
        return q

    @property
    def agents(self) -> list[str]:
        return list(self._queues)

    # ------------------------------------------------------------ 投递
    async def send(self, msg: Message) -> None:
        """单播：投递到指定接收者队列。响应消息同时唤醒等待的 Future。"""
        self.message_log.append(msg)
        if (
            msg.type == MsgType.RESPONSE
            and msg.correlation_id
            and msg.correlation_id in self._pending
        ):
            fut = self._pending.pop(msg.correlation_id)
            if not fut.done():
                fut.set_result(msg)
        if msg.receiver is None or msg.receiver not in self._queues:
            logger.warning("bus: drop message to unknown receiver '%s'", msg.receiver)
            return
        await self._queues[msg.receiver].put(msg)

    async def broadcast(self, msg: Message) -> None:
        """广播：投递到除发送者外的所有队列。"""
        self.message_log.append(msg)
        for name, q in self._queues.items():
            if name != msg.sender:
                await q.put(msg.model_copy())

    # ------------------------------------------------------------ 请求-响应
    async def request(
        self,
        sender: str,
        receiver: str,
        topic: str,
        payload: dict | None = None,
        timeout: float | None = 120.0,
    ) -> Message:
        """发送请求并等待响应（请求-响应模式）。超时抛 asyncio.TimeoutError。"""
        corr = uuid.uuid4().hex[:12]
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[Message] = loop.create_future()
        self._pending[corr] = fut
        msg = Message(
            type=MsgType.REQUEST,
            sender=sender,
            receiver=receiver,
            topic=topic,
            payload=payload or {},
            correlation_id=corr,
        )
        await self.send(msg)
        try:
            return await asyncio.wait_for(fut, timeout)
        finally:
            self._pending.pop(corr, None)

    async def reply(self, request_msg: Message, payload: dict) -> None:
        """对请求消息进行响应。"""
        resp = Message(
            type=MsgType.RESPONSE,
            sender=request_msg.receiver or "",
            receiver=request_msg.sender,
            topic=request_msg.topic,
            payload=payload,
            correlation_id=request_msg.correlation_id,
        )
        await self.send(resp)

    async def reply_error(self, request_msg: Message, error: str) -> None:
        await self.reply(request_msg, {"ok": False, "error": error})

    def publish(self, sender: str, topic: str, payload: dict | None = None) -> None:
        """同步发布广播事件（内部创建 task，适合在同步代码中调用）。"""
        msg = Message(
            type=MsgType.EVENT, sender=sender, topic=topic, payload=payload or {}
        )
        asyncio.get_running_loop().create_task(self.broadcast(msg))

    # ------------------------------------------------------------ 统计
    def stats(self) -> dict[str, int]:
        return {
            "agents": len(self._queues),
            "messages": len(self.message_log),
        }
