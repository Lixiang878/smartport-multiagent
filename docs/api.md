# SmartPort-MultiAgent API 参考

核心公共接口速查。所有模型均为 Pydantic v2，完整字段定义见
`smartport/core/models.py`。

## smartport（顶层）

| 符号 | 说明 |
|---|---|
| `PortSimulation(scenario, algo_config=None, llm_config=None, use_llm=True)` | 一键组装总线 + 黑板 + 5 个 Agent |
| `PortSimulation.run(mode) -> Schedule` | 运行单个模式（fcfs/ga/mip）完整闭环 |
| `PortSimulation.run_comparison(modes=None) -> dict[str, Schedule]` | 多模式对比（默认三种） |
| 异步上下文 | `async with PortSimulation(...) as sim:` 自动启停全部 Agent |

## smartport.core.models

| 模型 | 关键字段 |
|---|---|
| `Vessel` | id, size, length_m, draft_m, eta, moves, import_moves, export_moves, priority(1 最高), preferred_berth；属性 `weight` |
| `Berth` | id, length_m, depth_m, position_m, available_from/to；方法 `can_host(vessel)` |
| `QuayCrane` | id, position_m, efficiency(moves/h), status |
| `ContainerBlock` | id, block_type(import/export/mixed), bays, tiers, stacks_per_bay；属性 `capacity` |
| `Container` | id, vessel_id, kind, weight_class, seq（取箱顺序）, destination |
| `BerthAssignment` | vessel_id, berth_id, start, end, planned_end, wait_hours, service_hours；属性 `port_time` |
| `CraneAssignment` | crane_id, vessel_id, berth_id, start, end, moves |
| `YardPlanItem` | vessel_id, block_id, bays_used, import/export_containers, reshuffles, shared_bays |
| `KPI` | avg/max_wait, avg/weighted_port_time, total_reshuffles, reshuffles_per_1000, crane/berth_utilization, makespan_hours, crane_moves_count, solve_seconds |
| `Schedule` | mode, berth_plan, crane_plan, yard_plan, kpi, notes；`save(path)` / `load(path)` / `to_json()` |
| `Scenario` | name, horizon_hours, vessels, berths, cranes, blocks, containers；`vessel_map()` / `berth_map()` |

## smartport.core.bus / board

| 符号 | 说明 |
|---|---|
| `MessageBus.register(name) -> Queue` | 注册 Agent 队列（重名抛 ValueError） |
| `await bus.request(sender, receiver, topic, payload, timeout) -> Message` | 请求-响应 |
| `await bus.reply(request_msg, payload)` | 响应请求 |
| `await bus.broadcast(msg)` / `bus.publish(sender, topic, payload)` | 广播事件 |
| `bus.message_log` | 全量消息（回溯/断言） |
| `ScheduleBoard.update(section, value, source)` | 写分区 + 广播 STATE_UPDATED |
| `ScheduleBoard.get(section)` / `snapshot()` | 读分区 / 全局深拷贝 |

## smartport.agents

| Agent | name | 请求主题 |
|---|---|---|
| `OrchestratorAgent` | orchestrator | —（驱动方）；`await plan(mode) -> Schedule` |
| `BerthAllocationAgent` | berth_agent | `plan.berth.request`，payload `{mode}` |
| `CraneSchedulingAgent` | crane_agent | `plan.crane.request`，payload `{berth_plan}` |
| `YardPlanningAgent` | yard_agent | `plan.yard.request`，payload `{berth_plan}` |
| `ConflictResolutionAgent` | conflict_agent | `arbitration.request`，payload `{berth_id, vessels[2]}` |

自定义 Agent：继承 `BaseAgent`，实现 `description()`，
`register_handler(topic, fn)`（fn: payload → dict，可异步）。

## smartport.algorithms

| 函数 | 说明 |
|---|---|
| `solve_bap_fcfs(vessels, berths, service_hours)` | FCFS 基准 |
| `solve_bap_ga(..., config, seed, n_cranes)` | NSGA-II（容量感知惩罚） |
| `solve_bap_mip(..., config, warm_start_plan)` | pulp+CBC；无解返回 `(None, meta)` |
| `estimate_service_hours(vessels, crane_efficiency)` | BAP 服务时长估计 |
| `validate_berth_plan(plan, vessels, berths) -> list[str]` | 约束校验（空=通过） |
| `plan_cranes(berth_plan, vessels, berths, cranes, config)` | 岸桥调度 → (crane_plan, revised, stats) |
| `plan_yard(vessels, blocks, containers, berth_plan, config, seed)` | 堆场规划 → (items, stats) |
| `evaluate(scenario, berth_plan, crane_plan, yard_plan, ...)` | KPI 计算 |

## smartport.llm

| 符号 | 说明 |
|---|---|
| `LLMClient(api_base, api_key, model, timeout)` | OpenAI/GLM 兼容客户端（urllib） |
| `client.is_available() / client.chat(system, user)` | 密钥检测 / 调用（失败返回 None） |
| `build_conflict_prompt(conflict)` | 冲突场景结构化 prompt |
| `parse_llm_decision(text, valid_ids)` | 解析 `{"winner","reason"}`，非法返回 None |

## smartport.utils

| 符号 | 说明 |
|---|---|
| `generate_scenario(**params)` | 参数化算例生成（40 船默认） |
| `load_scenario(path)` | 加载算例 JSON（显式或 generate 参数） |
| `load_literature_instance(name)` / `register_literature_instance(name, file)` | 文献算例接口 |
| `load_algorithm_config / load_llm_config` | 配置加载 |
| `setup_logging(level, log_file)` | 控制台 + JSONL 结构化日志 |

## smartport.visualization

| 函数 | 说明 |
|---|---|
| `plot_berth_gantt(schedule, scenario, path)` | 泊位-时间甘特图 PNG |
| `plot_crane_timeline(schedule, scenario, path)` | 岸桥作业时序图 PNG |
| `plot_kpi_comparison(schedules, path)` | 多模式指标对比图 |
| `kpi_table_lines(schedules)` / `print_kpi(schedule)` | 对齐文本表 / 控制台看板 |
| `save_comparison_report(schedules, path)` | Markdown 对比报告 |
