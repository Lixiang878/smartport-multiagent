"""基础演示：10 船算例的完整多 Agent 调度闭环。

运行：python -m examples.demo_basic
输出：examples/output/ 下的甘特图、岸桥时序图、调度方案 JSON、运行日志。
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from smartport.simulation import PortSimulation
from smartport.utils.config_loader import (
    load_algorithm_config,
    load_llm_config,
    load_scenario,
)
from smartport.utils.logging_config import setup_logging
from smartport.visualization import (
    plot_berth_gantt,
    plot_crane_timeline,
    print_kpi,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "examples" / "output"


async def main() -> None:
    setup_logging(log_file=OUTPUT / "demo_basic.log")
    scenario = load_scenario(ROOT / "configs" / "port_10.json")
    algo = load_algorithm_config(ROOT / "configs" / "algorithm.json")
    llm = load_llm_config(ROOT / "configs" / "llm.json")

    print(f"算例: {scenario.name} | 船舶 {len(scenario.vessels)} | "
          f"泊位 {len(scenario.berths)} | 岸桥 {len(scenario.cranes)} | "
          f"箱区 {len(scenario.blocks)} | 集装箱 {len(scenario.containers)}")

    async with PortSimulation(scenario, algo, llm, use_llm=False) as sim:
        schedule = await sim.run("ga")

    print_kpi(schedule)
    plot_berth_gantt(schedule, scenario, OUTPUT / "berth_gantt_10v.png")
    plot_crane_timeline(schedule, scenario, OUTPUT / "crane_timeline_10v.png")
    saved = schedule.save(OUTPUT / "schedule_10v_ga.json")
    print(f"\n输出文件:\n  {OUTPUT / 'berth_gantt_10v.png'}\n"
          f"  {OUTPUT / 'crane_timeline_10v.png'}\n  {saved}")


if __name__ == "__main__":
    asyncio.run(main())
