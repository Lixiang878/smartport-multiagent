"""消息主题常量：Agent 间协作协议的事件名。"""
from __future__ import annotations

# 请求-响应模式（Orchestrator → 专业 Agent）
BERTH_PLAN_REQUEST = "plan.berth.request"      # 请求泊位分配方案
CRANE_PLAN_REQUEST = "plan.crane.request"      # 请求岸桥调度方案
YARD_PLAN_REQUEST = "plan.yard.request"        # 请求堆场规划方案
ARBITRATION_REQUEST = "arbitration.request"    # 请求冲突仲裁

# 广播模式（状态变更通知）
STATE_UPDATED = "state.updated"                # 黑板状态变更
CONFLICT_DETECTED = "conflict.detected"        # 检测到资源冲突
ARBITRATION_DECIDED = "arbitration.decided"    # 仲裁结果通知
SIM_COMPLETE = "sim.complete"                  # 本轮调度闭环完成
