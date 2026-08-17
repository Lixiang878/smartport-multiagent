"""LLM 增强冲突仲裁演示。

构造岸桥紧张算例（6 船 / 2 泊位 / 3 岸桥），高峰期岸桥减配导致
在泊船完工延长、与后续船靠泊窗重叠 —— 触发 ConflictResolutionAgent。

- 有 API 密钥（SMARTPORT_LLM_API_KEY）时：灰色地带冲突交由 LLM 仲裁；
- 无密钥时：自动纯规则模式运行（100% 可运行），并打印 LLM prompt 模板
  供人工审阅。

运行：python -m examples.demo_llm_conflict
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from smartport.llm import build_client, build_conflict_prompt
from smartport.llm.client import DEFAULT_BASE_URL, DEFAULT_MODEL
from smartport.simulation import PortSimulation
from smartport.utils.config_loader import load_algorithm_config, load_llm_config
from smartport.utils.instance_gen import generate_scenario
from smartport.utils.logging_config import setup_logging
from smartport.visualization import plot_berth_gantt, print_kpi

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "examples" / "output"

# 岸桥紧张算例：高峰重叠作业迫使 CSP 减配 → 完工延长 → 泊位冲突
SCENARIO = generate_scenario(
    name="smartport-conflict-demo", n_vessels=6, n_berths=2, n_cranes=3,
    n_import_blocks=2, n_export_blocks=2, size_profile="small_port",
    eta_span_hours=6.0, peak_ratio=0.85, peak_window=(1.0, 4.0),
    seed=23, block_bays=15, block_stacks_per_bay=4, block_tiers=4,
)


async def main() -> None:
    setup_logging(log_file=OUTPUT / "demo_llm_conflict.log")
    algo = load_algorithm_config(ROOT / "configs" / "algorithm.json")
    llm_cfg = load_llm_config(ROOT / "configs" / "llm.json")

    client = build_client(llm_cfg)
    if client.is_available():
        print(f"LLM 增强模式: {client.model} @ {client.api_base}")
    else:
        print("未检测到 LLM API 密钥 -> 纯规则模式（系统完全可运行）")
        print(f"  启用方法: set SMARTPORT_LLM_API_KEY=*** "
              f"(base={DEFAULT_BASE_URL}, model={DEFAULT_MODEL})")

    async with PortSimulation(SCENARIO, algo, llm_cfg, use_llm=True) as sim:
        schedule = await sim.run("ga")

    print_kpi(schedule)

    # 展示仲裁过程与 LLM prompt 模板
    arbitration_notes = [n for n in schedule.notes if "arbitration" in n]
    print(f"\n===== 冲突仲裁记录（{len(arbitration_notes)} 起）=====")
    for note in arbitration_notes:
        print(f"  {note}")
    if arbitration_notes:
        demo_conflict = {
            "berth_id": "B1",
            "vessels": [
                {"vessel_id": "V003", "role": "incumbent", "start": 2.5,
                 "end": 9.8, "eta": 2.2, "moves": 520, "priority": 2,
                 "wait_hours": 0.3, "preferred_berth": None},
                {"vessel_id": "V005", "role": "challenger", "start": 8.9,
                 "end": 14.0, "eta": 3.6, "moves": 500, "priority": 2,
                 "wait_hours": 5.3, "preferred_berth": "B1"},
            ],
        }
        print("\nLLM 仲裁 prompt 示例（灰色地带冲突才调用 LLM）:")
        print("-" * 60)
        print(build_conflict_prompt(demo_conflict))
        print("-" * 60)

    plot_berth_gantt(schedule, SCENARIO,
                     OUTPUT / "berth_gantt_conflict_demo.png",
                     title="Conflict Demo — GA + Arbitration")
    print(f"\n甘特图: {OUTPUT / 'berth_gantt_conflict_demo.png'}")


if __name__ == "__main__":
    asyncio.run(main())
