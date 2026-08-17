"""核心数据模型（Pydantic v2 严格定义）。

实体：Vessel / Berth / QuayCrane / ContainerBlock / Container
方案：BerthAssignment / CraneAssignment / YardPlanItem / KPI / Schedule

约定：
- 时间单位为小时（h），计划期起点为 0；
- 长度单位为米（m）；
- priority 数值越小优先级越高（1 为最高，VIP 船舶）。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

# 优先级 → 调度权重映射（目标函数中加权在港时间使用）
PRIORITY_WEIGHTS: dict[int, float] = {1: 5.0, 2: 3.0, 3: 2.0, 4: 1.5, 5: 1.0}


class Vessel(BaseModel):
    """船舶：到港计划的基本实体。"""

    id: str
    name: str = ""
    size: str = "medium"                       # feeder / medium / large
    length_m: float = Field(gt=0)             # 船长
    draft_m: float = Field(gt=0)              # 吃水
    eta: float = Field(ge=0)                  # 预计到港时间 (h)
    moves: int = Field(gt=0)                  # 装卸量（自然箱移动数）
    import_moves: int = Field(default=0, ge=0)    # 卸船箱数（进口箱）
    export_moves: int = Field(default=0, ge=0)    # 装船箱数（出口箱）
    priority: int = Field(ge=1, le=5)         # 1 最高
    preferred_berth: str | None = None        # 偏好泊位（航运合约约束）

    @field_validator("import_moves", "export_moves")
    @classmethod
    def _check_split(cls, v: int) -> int:
        return max(v, 0)

    @model_validator(mode="after")
    def _check_moves(self) -> "Vessel":
        # 未显式拆分时按 40% 进口 / 60% 出口拆分（集装箱码头典型比例）
        if self.import_moves == 0 and self.export_moves == 0:
            object.__setattr__(self, "import_moves", int(self.moves * 0.4))
            object.__setattr__(self, "export_moves", self.moves - self.import_moves)
        if self.import_moves + self.export_moves > self.moves:
            raise ValueError(
                f"vessel {self.id}: import+export moves exceed total moves"
            )
        return self

    @property
    def weight(self) -> float:
        """调度权重：由优先级映射。"""
        return PRIORITY_WEIGHTS.get(self.priority, 1.0)

    @property
    def port_time_hint(self) -> str:
        return f"{self.id}@eta={self.eta:.1f}h"


class Berth(BaseModel):
    """泊位：离散泊位模型，同一时刻仅服务一艘船。"""

    id: str
    name: str = ""
    length_m: float = Field(gt=0)
    depth_m: float = Field(gt=0)
    position_m: float = 0.0                   # 沿岸线起点位置（岸桥 non-crossing 排序用）
    available_from: float = 0.0               # 可用时段
    available_to: float = Field(default=1e6)  # 默认长期可用

    def can_host(self, vessel: Vessel) -> bool:
        """静态可行性：长度、水深、可用时段。"""
        return (
            self.length_m >= vessel.length_m
            and self.depth_m >= vessel.draft_m
            and self.available_to - self.available_from > 0
        )


class QuayCrane(BaseModel):
    """岸桥（Quay Crane）：效率 moves/hour。"""

    id: str
    position_m: float = 0.0                   # 当前锚定位置（沿岸线）
    efficiency: float = Field(default=30.0, gt=0)
    status: str = "idle"                      # idle / busy / maintenance


class ContainerBlock(BaseModel):
    """堆场箱区（Block）：由若干 bay 组成，每个 bay 含多个栈（stack）。"""

    id: str
    block_type: str = "mixed"                 # import / export / mixed
    bays: int = Field(default=10, gt=0)
    tiers: int = Field(default=4, gt=0)       # 单栈最大堆高
    stacks_per_bay: int = Field(default=6, gt=0)

    @property
    def capacity(self) -> int:
        return self.bays * self.stacks_per_bay * self.tiers


class Container(BaseModel):
    """集装箱：堆场规划的最小单元。

    seq 为取箱顺序号：
    - export 箱：装船顺序（小号先装船）；
    - import 箱：外集卡提箱顺序（小号先提走）。
    """

    id: str
    vessel_id: str
    kind: str                                  # import / export
    weight_class: str = "medium"               # light / medium / heavy
    seq: int = 0
    destination: str = ""

    @field_validator("kind")
    @classmethod
    def _check_kind(cls, v: str) -> str:
        if v not in ("import", "export"):
            raise ValueError(f"kind must be import/export, got {v}")
        return v


# ---------------------------------------------------------------- 调度方案

class BerthAssignment(BaseModel):
    """泊位分配结果（甘特图的一个条块）。"""

    vessel_id: str
    berth_id: str
    start: float                               # 靠泊开始
    end: float                                 # 离泊（岸桥调整后）
    planned_end: float                         # BAP 计划完工（岸桥调整前）
    wait_hours: float = 0.0                    # start - eta
    service_hours: float = 0.0                 # 实际作业时长

    @property
    def port_time(self) -> float:
        return self.wait_hours + self.service_hours


class CraneAssignment(BaseModel):
    """岸桥指派：一台岸桥服务一艘船的一个时段。"""

    crane_id: str
    vessel_id: str
    berth_id: str
    start: float
    end: float
    moves: int = 0                             # 该时段完成箱量（统计用）


class YardPlanItem(BaseModel):
    """堆场计划：每艘船的箱区/贝位占用与翻箱统计。"""

    vessel_id: str
    block_id: str
    bays_used: list[int] = Field(default_factory=list)
    import_containers: int = 0
    export_containers: int = 0
    reshuffles: int = 0                        # 装船/提箱前翻箱次数
    shared_bays: int = 0                       # 与他船混堆的 bay 数


class KPI(BaseModel):
    """调度方案量化指标看板。"""

    n_vessels: int = 0
    avg_wait_hours: float = 0.0                # 平均等待
    max_wait_hours: float = 0.0                # 等待峰值
    avg_port_time_hours: float = 0.0           # 平均在港（等待+作业）
    weighted_port_time_hours: float = 0.0      # 优先级加权在港
    total_reshuffles: int = 0                  # 总翻箱次数
    reshuffles_per_1000: float = 0.0           # 每千箱翻箱率
    crane_utilization: float = 0.0             # 岸桥利用率
    berth_utilization: float = 0.0             # 泊位利用率
    makespan_hours: float = 0.0                # 全部完工时刻
    crane_moves_count: int = 0                 # 岸桥移机次数
    solve_seconds: float = 0.0                 # 求解耗时

    def to_row(self) -> dict[str, Any]:
        return self.model_dump()


class Schedule(BaseModel):
    """完整调度方案：甘特图结构，支持 JSON 序列化。"""

    mode: str                                  # fcfs / ga / mip
    berth_plan: list[BerthAssignment] = Field(default_factory=list)
    crane_plan: list[CraneAssignment] = Field(default_factory=list)
    yard_plan: list[YardPlanItem] = Field(default_factory=list)
    kpi: KPI | None = None
    notes: list[str] = Field(default_factory=list)   # 仲裁/降级等过程记录
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_json(self) -> str:
        return self.model_dump_json(indent=2)

    def save(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.to_json(), encoding="utf-8")
        return p

    @classmethod
    def load(cls, path: str | Path) -> "Schedule":
        return cls.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))


# ---------------------------------------------------------------- 场景

class PortResourceConfig(BaseModel):
    """港口静态资源配置。"""

    berths: list[Berth]
    cranes: list[QuayCrane]
    blocks: list[ContainerBlock]


class Scenario(BaseModel):
    """一个完整算例：船舶到港计划 + 港口资源 + 集装箱明细。"""

    name: str
    horizon_hours: float = 48.0
    vessels: list[Vessel]
    berths: list[Berth]
    cranes: list[QuayCrane]
    blocks: list[ContainerBlock]
    containers: list[Container] = Field(default_factory=list)

    def vessel_map(self) -> dict[str, Vessel]:
        return {v.id: v for v in self.vessels}

    def berth_map(self) -> dict[str, Berth]:
        return {b.id: b for b in self.berths}
