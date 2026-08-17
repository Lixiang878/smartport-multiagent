# SmartPort-MultiAgent 架构设计文档

本文档说明系统的设计决策、模块职责、数据流与扩展指南。

## 1. 总体架构

「协调器 + 专业 Agent」分层架构，三层决策栈：

```
Layer 3  LLM 增强决策   ConflictResolutionAgent 的灰色地带仲裁（可选，可降级）
Layer 2  算法求解       BAP（FCFS / NSGA-II GA / MIP）、CSP 启发式、堆场启发式
Layer 1  规则引擎       约束校验、优先级规则、贪心插空、事件驱动模拟
```

```
                     ┌────────────────────────────┐
船舶到港计划 ───────▶ │ OrchestratorAgent (协调器)   │
                     │ 任务分解/监控/Review/仲裁调度 │
                     └──────┬─────────────┬───────┘
        request-response    │             │  broadcast (STATE_UPDATED 等)
        ┌───────────────────┼─────────────┼──────────────────┐
        ▼                   ▼             ▼                  ▼
 ┌─────────────┐   ┌──────────────┐ ┌─────────────┐  ┌──────────────┐
 │ BerthAlloc  │   │ CraneSched   │ │ YardPlanning│  │ ConflictReso │
 │ (BAP 求解)  │   │ (岸桥指派)    │ │ (分箱区/翻箱)│  │ (规则+LLM)   │
 └──────┬──────┘   └──────┬───────┘ └──────┬──────┘  └──────┬───────┘
        └──────────── ScheduleBoard 黑板（订阅/发布） ────────┘
                     MessageBus（asyncio Queue，请求-响应/广播/仲裁）
```

## 2. 模块职责

| 模块 | 文件 | 职责 |
|---|---|---|
| 数据模型 | `core/models.py` | Pydantic v2 实体（Vessel/Berth/QuayCrane/ContainerBlock/Container）与方案（BerthAssignment/CraneAssignment/YardPlanItem/KPI/Schedule） |
| 消息总线 | `core/bus.py` | asyncio Queue 单播/广播；correlation_id + Future 实现请求-响应；全量消息日志 |
| 黑板 | `core/board.py` | 分区状态存储，update 即广播 STATE_UPDATED，changelog 支持回溯 |
| 协调器 | `agents/orchestrator.py` | 调度闭环驱动：泊位→岸桥→冲突仲裁循环→堆场→KPI；每阶段 Review |
| 泊位 Agent | `agents/berth_allocation.py` | 三种 BAP 模式分派；MIP 失败自动回退 GA |
| 岸桥 Agent | `agents/crane_scheduling.py` | 事件驱动模拟：指派/减配/借调恢复/移机统计 |
| 堆场 Agent | `agents/yard_planning.py` | 重叠感知分箱区 + 栈级堆存 + 翻箱模拟 |
| 仲裁 Agent | `agents/conflict_resolution.py` | 规则字典序仲裁；灰色地带交 LLM；输出败方新靠泊时刻 |
| LLM 层 | `llm/client.py` `llm/prompts.py` | urllib 实现 OpenAI 兼容 chat；结构化冲突 prompt；JSON 决策解析 |
| 算法层 | `algorithms/*` | 见下节 |
| 可视化 | `visualization/*` | 甘特图/岸桥时序/看板/对比报告（Agg 后端 PNG） |

## 3. 关键算法

### 3.1 泊位分配（BAP，离散泊位模型）

- **共享解码器**（`bap_common.decode_schedule`）：给定船舶顺序与偏好，
  贪心插空选最早可开工泊位；FCFS 即「顺序=ETA、偏好优先」的解码特例
- **FCFS**（`bap_fcfs.py`）：基准，顺序固定
- **NSGA-II GA**（`bap_ga.py`）：
  - 染色体 =（船舶服务顺序排列, 每船偏好泊位表）；OX 交叉 + swap/inversion 变异
  - 三目标非支配排序 + 拥挤距离：加权平均在港 / 等待峰值 / 偏好违反
  - **自适应变异**：第一前沿唯一解比例下降 → 变异率 0.15→0.45 上浮
  - **岸桥容量感知惩罚**：同时在泊船数超过 `n_cranes//3` 时按超额船·小时
    计入目标（关键设计，见 §5.1）
- **MIP**（`bap_mip.py`）：x[i,b] 泊位指派 + t[i] 开始时刻 + y[i,j] 同泊位先后，
  大 M 互斥线性化；目标 = 加权完工 + 偏好惩罚；FCFS 解 warm start；
  时限内无可行解 → 上层回退 GA

### 3.2 岸桥调度（CSP）

`crane_heuristic.plan_cranes` 事件驱动模拟：

1. 靠泊事件：为船分配「就近」空闲岸桥，配额 = BAP 估计值（≤4 台）；
2. 高峰岸桥不足 → **减配** → 作业延长（`end` 后移，可能侵入后船靠泊窗 → 冲突源）；
3. 完工事件：空闲岸桥**优先借调恢复**被减配船只（完工时刻回移）；
4. 岸桥换泊位记一次移机。

### 3.3 堆场规划

`yard_heuristic.plan_yard`：

- 进口/出口箱分区池；出口箱占用窗 = 集港提前期 → 船舶离泊（bay 释放），
  进口箱计划期内驻场
- **重叠感知轮转**：与前船作业窗重叠 → 错开下一箱区；不重叠 → 复用 bay
  （因此泊位计划越平滑、重叠越少，可用 bay 越多 → 翻箱越低，与 BAP 模式联动）
- 独占 bay 按取箱序倒序**完美堆存**（零翻箱）；容量不足回退**混堆**
  （乱序到场 + 重下轻上约束入栈，与他船箱交错 → 翻箱）
- 配置箱区容量不足时自动创建可追踪的 `YOVERFLOW_IMPORT/EXPORT` 动态箱区，
  禁止静默丢箱；规划结束强制校验 import/export 已分配数量与输入箱量一致
- 翻箱模拟：按 seq 升序取箱，障碍箱吊至「栈顶 seq 不大于自身」的最优栈

## 4. 多 Agent 协作机制

### 4.1 消息协议

| 协议 | 实现 | 用途 |
|---|---|---|
| 请求-响应 | `bus.request()/reply()`，correlation_id + Future | Orchestrator → 专业 Agent 的计划请求 |
| 广播 | `bus.broadcast()/publish()` | STATE_UPDATED / CONFLICT_DETECTED / ARBITRATION_DECIDED / SIM_COMPLETE |
| 仲裁 | Orchestrator 检测重叠 → CONFLICT_DETECTED 广播 → ARBITRATION_REQUEST → 决策 → Execution 平移 → 循环直至无冲突 |

### 4.2 执行闭环（Orchestrator.plan）

```
Observation  board 快照 / phase 更新
Planning     berth_agent → crane_agent → (conflict loop) → yard_agent
Review       validate_berth_plan（约束）+ 同泊位重叠检测（每阶段）
Execution    仲裁决策应用：败方及同泊位后续船级联平移，岸桥时序同步平移
Output       KPI → 黑板 → Schedule(JSON) → SIM_COMPLETE 广播
```

### 4.3 冲突闭环示例（真实发生，非注入）

岸桥减配 → 在泊船完工延长 → 侵入同泊位后船靠泊窗 → 仲裁 →
败方平移 → 级联检查 → 直至方案一致（`demo_llm_conflict` 可复现）。

### 4.4 LLM 增强层

- 触发条件：两船优先级相同且作业量差 < 20%（规则灰色地带）且密钥可用
- Prompt：结构化冲突 JSON（船舶属性/时刻/优先级/偏好），要求仅输出
  `{"winner": ..., "reason": ...}`
- 鲁棒性：无密钥 / 调用失败 / 输出非法 → 规则引擎兜底，系统 100% 可运行

## 5. 关键设计决策与权衡

### 5.1 BAP 与 CSP 两级解耦 + 容量感知惩罚（最重要的设计决策）

BAP 阶段以「估计岸桥配额」折算固定服务时长，使泊位计划可独立求解；
但纯 BAP 最优解往往过度并行（同时靠泊船数远超岸桥能力），下游岸桥减配
+ 仲裁级联反而恶化全局指标（实测 GA 曾比 FCFS 差 37%）。
解决：GA 目标内置「超额在泊船·小时 × 0.5」惩罚，使泊位计划天然尊重
岸桥容量；修复后 GA 平均在港较 FCFS 改进 28%。

### 5.2 效率与翻箱的权衡（如实声明）

GA 计划并行度高 → 单位时间在泊船多 → 集港期重叠多 → 混堆与翻箱上升。
这是真实业务权衡（快周转 vs 少翻箱），系统通过重叠感知分箱区缓解；
堆场箱区容量是可调参数（configs 中 `n_*_blocks`），可按业务偏好校准。

### 5.3 为什么翻箱由混堆驱动而非重量堆垛

重量分层（重下轻上）与「重箱先装」的配载序存在结构性冲突，逐箱建模会
使翻箱率虚高（实测 >1800‰）；学术标准建模为按取箱序倒序完美堆存 +
混堆扰动，翻箱率落在可解释区间且与泊位计划平滑度联动。

### 5.4 离散泊位模型

同一泊位同一时刻一船，不做泊位内空间装箱（BAP 文献中 continuous 模型），
换来：MIP 规模可控（40 船 25s 内）、解码器简单共享、甘特图语义清晰。

### 5.5 岸桥 non-crossing 近似

就近指派 + 泊位次序保持，不做严格不可穿越约束建模（接口预留），
对演示规模（5 泊位 12 桥）误差有限。

### 5.6 MIP 的定位

MIP 求解「纯 BAP 视角」最优（无岸桥容量感知），在全链路中可能劣于 GA
（分层优化的次优性，本身是有价值的结论）；其价值在于小规模精确基准
与 warm start 工程实践。

## 6. 扩展指南

### 新增专业 Agent

1. 继承 `BaseAgent`，`name` 唯一，`__init__` 中
   `register_handler(topic, handler)`；
2. 在 `core/topics.py` 声明主题常量；
3. 在 `simulation.PortSimulation.__init__` 组装并加入 `self.agents`；
4. Orchestrator 的 Planning 序列中通过 `bus.request()` 接入。

### 新增 BAP 求解算法

实现 `solve(vessels, berths, service_hours) -> (plan, meta)`，
在 `BerthAllocationAgent.handle_plan_request` 注册新模式分支即可。

### 对接真实 TOS / 数据源

- `utils/config_loader.load_scenario` 支持显式算例 JSON；
- `utils/instance_gen.load_instance_file` 支持文献 CSV/JSON；
- 替换 Scenario 构造来源即可接入生产数据（模型字段见 `core/models.py`）。

### LLM 提供商切换

任意 OpenAI 兼容接口：`SMARTPORT_LLM_BASE_URL` + `SMARTPORT_LLM_API_KEY`
+ `SMARTPORT_LLM_MODEL`（默认 GLM 开放平台 glm-4-flash）。

## 7. 性能与规模

- 40 船 / 5 泊位 / 12 岸桥 / 14149 箱：GA ~5s、MIP ≤26s（时限 25s+）、
  全链路（含堆场与可视化）单模式 <15s
- GA 复杂度 O(pop × gen × N²)，50×60×40² ≈ 秒级
- 堆场逐箱模拟 O(N log N + 翻箱深度)，1.4 万箱 <2s

## 8. 目录与测试映射

```
tests/test_models.py       数据模型校验与序列化
tests/test_bap.py          三种 BAP 正确性 / 30s 预算 / 拥堵改进 / 精英保留
tests/test_crane.py        岸桥并发上限 / 全船服务
tests/test_yard.py         翻箱计数单元 / 完美堆存零翻箱 / 混堆产生翻箱
tests/test_bus_agents.py   请求-响应 / 广播 / 端到端闭环 / 多模式对比
tests/test_llm_fallback.py 无密钥降级 / 决策解析 / 纯规则仲裁
```
