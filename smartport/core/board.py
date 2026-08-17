"""ScheduleBoard：全局共享黑板（Blackboard 模式）。

各 Agent 通过 publish/subscribe 感知全局状态：
- update(): 写入某一分区并广播 STATE_UPDATED 事件；
- snapshot(): 深拷贝当前全局状态（Observation 阶段的数据来源）；
- changelog: 记录每次变更（时间、来源、分区），支持决策回溯。
"""
from __future__ import annotations

import copy
import logging
import time

from smartport.core import topics
from smartport.core.bus import MessageBus

logger = logging.getLogger("smartport.board")

# 黑板分区
SECTION_SCENARIO = "scenario"        # 算例与港口资源
SECTION_BERTH_PLAN = "berth_plan"    # 泊位分配方案
SECTION_CRANE_PLAN = "crane_plan"    # 岸桥调度方案
SECTION_YARD_PLAN = "yard_plan"      # 堆场规划方案
SECTION_KPI = "kpi"                  # 全局指标
SECTION_CONFLICTS = "conflicts"      # 活跃冲突
SECTION_PHASE = "phase"              # 当前调度阶段


class ScheduleBoard:
    """黑板：Agent 间共享的全局状态。"""

    def __init__(self, bus: MessageBus | None = None) -> None:
        self._bus = bus
        self._sections: dict[str, object] = {}
        self.version: int = 0
        self.changelog: list[dict] = []

    # ------------------------------------------------------------ 写
    def update(self, section: str, value: object, source: str) -> None:
        """写入分区、递增版本号并广播状态变更。"""
        self._sections[section] = value
        self.version += 1
        entry = {"ts": time.time(), "source": source, "section": section,
                 "version": self.version}
        self.changelog.append(entry)
        logger.info("board: [%s] section='%s' updated by '%s' (v%d)",
                    source, section, source, self.version)
        if self._bus is not None:
            self._bus.publish(source, topics.STATE_UPDATED,
                              {"section": section, "version": self.version})

    # ------------------------------------------------------------ 读
    def get(self, section: str, default: object = None) -> object:
        return self._sections.get(section, default)

    def snapshot(self) -> dict:
        """全局状态深拷贝（Observation 阶段入口）。"""
        return copy.deepcopy(self._sections)
