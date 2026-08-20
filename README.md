# SmartPort-MultiAgent 港口多 Agent 智能调度系统

面向集装箱码头高峰期**泊位资源紧张、船舶待港时间长、堆场翻箱冗余**的真实痛点，
构建的「协调器 + 专业 Agent」多 Agent 协作调度系统。
支持**规则引擎 + 算法求解 + LLM 增强决策**三层架构，
可模拟港口 24–72 小时运营，输出可量化的调度方案与可视化看板。

[English README](README_EN.md)

> **二合一说明**：原 [Berth-Scheduler](https://github.com/Lixiang878/Berth-Scheduler) 仓库已并入本项目：
> **HiGHS 精确解**（`algorithms/bap_milp_highs`，小规模 ground truth）、**文献基准算例**
> （`utils/benchmarks`，Imai 风格转录）、**灵敏度分析**（`utils/sensitivity`，岸桥数量扫描）。
> Berth-Scheduler 已归档，不再更新。

## 核心特性

- **分层多 Agent 架构**：OrchestratorAgent 协调 4 个专业 Agent（泊位分配 / 岸桥调度 / 堆场规划 / 冲突仲裁），任务分解、状态监控、冲突处理
- **四种泊位分配算法**：FCFS 基准 / 自适应 NSGA-II 遗传算法 / MIP（pulp + CBC，带 warm start）/ **HiGHS 精确解**（scipy.optimize.milp，≤10 船 ground truth，吸收自 Berth-Scheduler）
- **文献基准对照**：Imai et al. (2001/2005) 风格算例转录（`imai_5_2` / `imai_10_3` / `dense_20_5`），可与公开数字交叉校验；`examples/demo_benchmark.py` 一键对比 FCFS/GA/MIP
- **灵敏度分析**：岸桥数量扫描，量化加设备的边际收益（`utils/sensitivity`）
- **异步消息总线**：基于 asyncio Queue 的请求-响应、广播、仲裁三种协作协议，事件驱动
- **黑板模式状态共享**：全局 ScheduleBoard，各 Agent 订阅/发布状态变更
- **执行闭环**：Observation → Planning → Execution → Review，每阶段约束校验
- **LLM 增强仲裁（可选）**：OpenAI/GLM 兼容接口，规则难以裁决的灰色地带冲突交由 LLM 推理；**无 API 密钥时 100% 纯规则可运行**
- **可视化输出**：泊位-时间甘特图、岸桥作业时序图、指标看板、三模式对比报告
- **轻量依赖**：核心仅 pydantic + numpy + matplotlib；求解器 pulp 可选

## 架构

```
                        ┌──────────────────────────┐
   船舶到港计划 ───────▶ │  OrchestratorAgent 协调器 │
                        └──────────┬───────────────┘
              request/response     │      broadcast / arbitration
        ┌────────────┬────────────┼────────────┬─────────────┐
        ▼            ▼            ▼            ▼             ▼
 ┌────────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────┐
 │ BerthAlloc │ │ CraneSch │ │ YardPlan │ │ Conflict │ │ Schedule  │
 │ FCFS/GA/MIP│ │ 岸桥指派  │ │ 分箱区    │ │ 规则+LLM  │ │ Board黑板 │
 │ 泊位分配    │ │ 时序/移机 │ │ 翻箱最小化│ │ 冲突仲裁  │ │ 状态共享   │
 └────────────┘ └──────────┘ └──────────┘ └──────────┘ └───────────┘
        └────────────┴──── MessageBus (asyncio Queue) ───┴────────────┘
```

## 快速开始

### 安装

```bash
git clone https://github.com/Lixiang878/smartport-multiagent.git
cd smartport-multiagent
pip install -r requirements.txt   # 或 pip install -e ".[dev]"
```

要求 Python 3.10+。未安装 pulp 时 MIP 模式自动回退遗传算法（FCFS/GA 不受影响）。

### 基础演示（10 船）

```bash
python -m examples.demo_basic
```

### 文献基准对比（吸收自 Berth-Scheduler）

```bash
python -m examples.demo_benchmark --name imai_5_2   # FCFS/GA/HiGHS 精确解对照
```

输出 `examples/output/`：泊位甘特图 `berth_gantt_10v.png`、岸桥时序图
`crane_timeline_10v.png`、调度方案 `schedule_10v_ga.json`、结构化日志。

### 完整演示（40 船三模式对比）

```bash
python -m examples.demo_full
```

运行 FCFS / 遗传算法 / MIP 三组方案，输出对比表、对比图
`kpi_comparison_40v.png`、各模式甘特图与 Markdown 对比报告。

### LLM 增强冲突仲裁演示

```bash
python -m examples.demo_llm_conflict

# 启用 LLM（GLM / OpenAI 兼容接口均可）：
set SMARTPORT_LLM_API_KEY=你的密钥          # Windows
export SMARTPORT_LLM_API_KEY=你的密钥       # Linux/macOS
# 可选：SMARTPORT_LLM_BASE_URL（默认 GLM 开放平台）、SMARTPORT_LLM_MODEL
```

## 40 船标准算例实测指标（RTX 5060 Laptop / Python 3.12）

| 指标 | FCFS 基准 | 遗传算法(NSGA-II) | 改进 |
|---|---|---|---|
| 平均在港时间 (h) | 24.4 | **17.5** | **-28%** |
| 等待时间峰值 (h) | 45.8 | **38.9** | **-15%** |
| 总完工时刻 (h) | 73.3 | 58.8 | -20% |
| 岸桥利用率 | 53% | 67% | +14pp |
| 求解耗时 (s) | 0.1 | ~5 | < 30s 预算 |

> 注：GA 高并行度会略增集港期混堆（翻箱与在港时间存在业务权衡），
> 堆场规划通过重叠感知分箱区缓解；详见 `ARCHITECTURE.md` 的权衡说明。

## 项目结构

```
smartport-multiagent/
├── smartport/
│   ├── core/                 # 数据模型 / 消息总线 / 事件主题 / 黑板
│   ├── agents/               # 5 个 Agent（orchestrator + 4 专业 Agent）
│   ├── algorithms/           # FCFS / NSGA-II GA / MIP(pulp) / HiGHS 精确解 / 岸桥 / 堆场启发式 / KPI
│   ├── visualization/        # 甘特图 / 岸桥时序 / 指标看板 / 对比报告
│   ├── llm/                  # OpenAI/GLM 兼容客户端 + 仲裁 prompt 模板
│   ├── utils/                # 日志 / 配置加载 / 算例生成 / 文献算例接口 / 文献基准 / 灵敏度分析
│   └── simulation.py         # PortSimulation 一键组装
├── configs/                  # 标准算例（10/40 船）、算法超参、LLM、文献算例
├── examples/                 # demo_basic / demo_full / demo_llm_conflict / demo_benchmark
├── tests/                    # pytest（数据模型 / 算法 / 总线 / Agent 闭环 / LLM 降级）
├── docs/                     # API 文档
├── ARCHITECTURE.md           # 设计决策与扩展指南
├── README.md / README_EN.md
├── requirements.txt / setup.py / LICENSE (MIT)
```

## 编程接口

```python
import asyncio
from smartport import PortSimulation
from smartport.utils import load_scenario, generate_scenario

scenario = load_scenario("configs/port_40.json")   # 或 generate_scenario(...)

async def main():
    async with PortSimulation(scenario, use_llm=False) as sim:
        schedule = await sim.run("ga")             # fcfs / ga / mip
        print(schedule.kpi.avg_port_time_hours)
        schedule.save("schedule.json")             # 甘特图结构 → JSON

asyncio.run(main())
```

## 配置驱动

- `configs/port_10.json` / `port_40.json`：参数化算例（船舶数、泊位/岸桥/箱区、
  高峰聚簇、随机种子），亦可显式给出完整船舶计划
- `configs/algorithm.json`：GA / MIP / 岸桥 / 堆场超参数
- `configs/llm.json`：LLM 接口配置（留空则读环境变量，无密钥纯规则模式）
- `configs/literature/`：公开文献 BAP 算例接口（JSON/CSV 转录格式）

## 测试

```bash
python -m pytest tests/ -q        # 42 个测试：模型/算法(含 HiGHS)/总线/Agent 闭环/LLM 降级/基准/灵敏度
python -m flake8 smartport tests examples --max-line-length=100
```

> 可选依赖：未装 pulp 时 MIP-CBC 测试自动跳过；未装 scipy 时 HiGHS 测试自动跳过
> （均为可选 extra：`pip install -e '.[dev]'` 全装）。

## 简化与边界（如实声明）

- 离散泊位模型（同一泊位同时一船），不做泊位内空间装箱
- 岸桥 non-crossing 采用「就近指派 + 泊位次序」近似，未严格建模不可穿越约束
- BAP 与岸桥调度两级解耦：GA 目标内置岸桥容量超载惩罚以感知下游瓶颈
- 堆场翻箱由「混堆交错 + 乱序到场」驱动（重量级堆垛约束简化）；配置容量不足时自动使用可追踪 overflow block，并校验全部箱子已分配
- 不对接真实 TOS 系统，`PortResourceConfig` / `load_instance_file` 预留接入接口

## 引用与致谢

 berth allocation 问题建模参考公开文献（Imai et al. 系列及综述），
 文献算例接口见 `configs/literature/README.md`。

## License

MIT License
