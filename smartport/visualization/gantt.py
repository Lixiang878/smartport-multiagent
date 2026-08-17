"""甘特图与岸桥时序可视化（matplotlib，Agg 后端，输出 PNG）。"""
from __future__ import annotations

import logging
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402  (需先切换 Agg 后端)

from smartport.core.models import Schedule, Scenario  # noqa: E402

logger = logging.getLogger("smartport.viz")

TAB20 = [plt.cm.tab20(i) for i in range(20)]


def _vessel_colors(vessel_ids: list[str]) -> dict[str, tuple]:
    """船舶配色：按 id 排序稳定映射 tab20。"""
    return {vid: TAB20[i % 20] for i, vid in enumerate(sorted(vessel_ids))}


def plot_berth_gantt(
    schedule: Schedule,
    scenario: Scenario,
    path: str | Path,
    title: str | None = None,
) -> Path:
    """泊位-时间甘特图：泊位为行、时间为横轴，等待期以浅红阴影标注。"""
    vmap = scenario.vessel_map()
    berth_ids = [b.id for b in scenario.berths]
    ypos = {bid: len(berth_ids) - 1 - i for i, bid in enumerate(berth_ids)}
    colors = _vessel_colors([v.id for v in scenario.vessels])

    fig, ax = plt.subplots(figsize=(13, 0.9 * len(berth_ids) + 2.2))
    for a in schedule.berth_plan:
        y = ypos[a.berth_id]
        v = vmap[a.vessel_id]
        ax.barh(y, a.end - a.start, left=a.start, height=0.62,
                color=colors[a.vessel_id], edgecolor="black", linewidth=0.6)
        label = f"{a.vessel_id}"
        if a.wait_hours > 0.05:
            label += f" (+{a.wait_hours:.1f}h wait)"
            # 锚地等待期（eta -> start）
            ax.barh(y + 0.42, a.wait_hours, left=a.start - a.wait_hours,
                    height=0.14, color="crimson", alpha=0.35, hatch="//")
        ax.text(a.start + (a.end - a.start) / 2, y, label,
                ha="center", va="center", fontsize=7.5)
        if v.priority <= 2:
            ax.text(a.start, y - 0.52, f"P{v.priority}",
                    ha="left", va="top", fontsize=6.5, color="crimson")

    ax.set_yticks(range(len(berth_ids)))
    ax.set_yticklabels(list(reversed(berth_ids)))
    ax.set_xlabel("Time (hours)")
    ax.set_title(title or f"Berth Allocation Gantt — {schedule.mode.upper()} "
                          f"({len(schedule.berth_plan)} vessels)")
    ax.grid(axis="x", alpha=0.3)
    ax.set_xlim(0, max((a.end for a in schedule.berth_plan), default=1) * 1.02)
    fig.tight_layout()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150)
    plt.close(fig)
    logger.info("saved berth gantt: %s", path)
    return Path(path)


def plot_crane_timeline(
    schedule: Schedule,
    scenario: Scenario,
    path: str | Path,
    title: str | None = None,
) -> Path:
    """岸桥作业时序图：每台岸桥一行，色块对应对服务船舶。"""
    crane_ids = [c.id for c in scenario.cranes]
    ypos = {cid: len(crane_ids) - 1 - i for i, cid in enumerate(crane_ids)}
    colors = _vessel_colors(list(scenario.vessel_map()))

    fig, ax = plt.subplots(figsize=(13, 0.55 * len(crane_ids) + 2.0))
    for r in schedule.crane_plan:
        y = ypos[r.crane_id]
        ax.barh(y, r.end - r.start, left=r.start, height=0.6,
                color=colors.get(r.vessel_id, "gray"),
                edgecolor="black", linewidth=0.4)
    # 右侧标注各岸桥任务数
    counts: dict[str, int] = {}
    for r in schedule.crane_plan:
        counts[r.crane_id] = counts.get(r.crane_id, 0) + 1
    for cid, y in ypos.items():
        ax.text(1.005, y, f"{counts.get(cid, 0)} tasks", transform=ax.get_yaxis_transform(),
                ha="left", va="center", fontsize=6.5, color="dimgray")

    ax.set_yticks(range(len(crane_ids)))
    ax.set_yticklabels(list(reversed(crane_ids)))
    ax.set_xlabel("Time (hours)")
    ax.set_title(title or f"Quay Crane Timeline — {schedule.mode.upper()} "
                          f"({len(schedule.crane_plan)} assignments)")
    ax.grid(axis="x", alpha=0.3)
    fig.tight_layout()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info("saved crane timeline: %s", path)
    return Path(path)
