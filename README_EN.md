# SmartPort-MultiAgent

A multi-agent intelligent scheduling system for container terminals,
addressing peak-hour **berth congestion, long vessel waiting times and
redundant yard reshuffles**. It implements a three-layer decision stack —
**rule engine + optimization solvers + LLM-enhanced arbitration** — and
simulates 24–72 h of terminal operations with quantified schedules and
visual dashboards.

[中文文档](README.md)

## Highlights

- **Layered multi-agent architecture**: an Orchestrator coordinating four
  specialist agents (berth allocation, quay-crane scheduling, yard planning,
  conflict resolution)
- **Three berth-allocation solvers**: FCFS baseline / adaptive NSGA-II GA /
  exact MIP (pulp + CBC with warm start)
- **Async message bus**: request-response, broadcast and arbitration
  protocols over asyncio queues; blackboard (ScheduleBoard) state sharing
- **Closed execution loop**: Observation → Planning → Execution → Review,
  with constraint validation at every stage
- **Optional LLM arbitration**: OpenAI/GLM-compatible API decides gray-zone
  berth conflicts; **runs 100% offline without an API key** (rule fallback)
- **Visual outputs**: berth-time Gantt charts, crane timelines, KPI
  dashboard and a three-mode comparison report

## Quick Start

```bash
pip install -r requirements.txt
python -m examples.demo_basic        # 10-vessel case, Gantt output
python -m examples.demo_full         # 40-vessel case, FCFS vs GA vs MIP
python -m examples.demo_llm_conflict # conflict arbitration demo

# Optional LLM mode
export SMARTPORT_LLM_API_KEY=sk-...  # OpenAI/GLM-compatible
```

## Measured Results (40-vessel instance)

| Metric | FCFS | GA (NSGA-II) | Improvement |
|---|---|---|---|
| Avg port time (h) | 24.4 | 17.5 | **-28%** |
| Peak wait (h) | 45.8 | 38.9 | **-15%** |
| Makespan (h) | 73.3 | 58.8 | -20% |
| Crane utilization | 53% | 67% | +14 pp |
| Solve time (s) | 0.1 | ~5 | within 30 s budget |

## Project Layout

```
smartport/          core (models/bus/blackboard) · agents (5) · algorithms
                    (FCFS/GA/MIP/crane/yard/metrics) · visualization · llm · utils
configs/            parameterized instances, algorithm & LLM config,
                    literature-instance interface
examples/           runnable demos        tests/  pytest suite (33 tests)
docs/               API reference         ARCHITECTURE.md  design decisions
```

## Programmatic Use

```python
import asyncio
from smartport import PortSimulation
from smartport.utils import load_scenario

scenario = load_scenario("configs/port_40.json")

async def main():
    async with PortSimulation(scenario, use_llm=False) as sim:
        schedule = await sim.run("ga")          # fcfs / ga / mip
        schedule.save("schedule.json")

asyncio.run(main())
```

## Tests

```bash
python -m pytest tests/ -q
python -m flake8 smartport tests examples --max-line-length=100
```

## License

MIT
