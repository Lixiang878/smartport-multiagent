"""完整演示：40 船算例，FCFS / 遗传算法 / 精确求解 三组方案对比。

运行：python -m examples.demo_full
输出：examples/output/ 下的三组甘特图、指标对比图、Markdown 对比报告、
各方案 JSON 与运行日志。
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
    kpi_table_lines,
    plot_berth_gantt,
    plot_kpi_comparison,
    save_comparison_report,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "examples" / "output"
MODES = ["fcfs", "ga", "mip"]


async def main() -> None:
    setup_logging(log_file=OUTPUT / "demo_full.log")
    scenario = load_scenario(ROOT / "configs" / "port_40.json")
    algo = load_algorithm_config(ROOT / "configs" / "algorithm.json")
    llm = load_llm_config(ROOT / "configs" / "llm.json")

    print(f"算例: {scenario.name} | 船舶 {len(scenario.vessels)} | "
          f"泊位 {len(scenario.berths)} | 岸桥 {len(scenario.cranes)} | "
          f"集装箱 {len(scenario.containers)}")
    print(f"对比模式: {MODES}\n")

    async with PortSimulation(scenario, algo, llm, use_llm=False) as sim:
        schedules = await sim.run_comparison(MODES)

    # ---- 控制台对比表
    print("\n".join(kpi_table_lines(schedules)))

    # ---- 可视化与报告
    for mode, sch in schedules.items():
        plot_berth_gantt(sch, scenario, OUTPUT / f"berth_gantt_40v_{mode}.png")
        sch.save(OUTPUT / f"schedule_40v_{mode}.json")
    plot_kpi_comparison(schedules, OUTPUT / "kpi_comparison_40v.png")
    report = save_comparison_report(
        schedules, OUTPUT / "comparison_report_40v.md")

    print(f"\n对比报告: {report}")
    print(f"对比图:   {OUTPUT / 'kpi_comparison_40v.png'}")
    for mode in MODES:
        print(f"  {mode}: {OUTPUT / f'berth_gantt_40v_{mode}.png'}")


if __name__ == "__main__":
    asyncio.run(main())
