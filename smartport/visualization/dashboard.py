"""指标看板：控制台输出、三模式对比报告（Markdown）与对比图（PNG）。"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402  (需先切换 Agg 后端)

from smartport.core.models import KPI, Schedule  # noqa: E402

# 对比表列定义：(KPI 字段, 中文名, 数值格式)
KPI_COLUMNS: list[tuple[str, str, str]] = [
    ("avg_port_time_hours", "平均在港时间(h)", "{:.2f}"),
    ("avg_wait_hours", "平均等待时间(h)", "{:.2f}"),
    ("max_wait_hours", "等待峰值(h)", "{:.2f}"),
    ("total_reshuffles", "翻箱次数", "{:d}"),
    ("reshuffles_per_1000", "千箱翻箱率", "{:.1f}"),
    ("crane_utilization", "岸桥利用率", "{:.1%}"),
    ("berth_utilization", "泊位利用率", "{:.1%}"),
    ("makespan_hours", "总完工时刻(h)", "{:.2f}"),
    ("solve_seconds", "求解耗时(s)", "{:.1f}"),
]

MODE_LABELS = {"fcfs": "FCFS 基准", "ga": "遗传算法(NSGA-II)", "mip": "精确求解(MIP)"}
# 图内标签（matplotlib 默认字体无中文字形，图表一律用英文）
MODE_LABELS_EN = {"fcfs": "FCFS", "ga": "GA (NSGA-II)", "mip": "MIP (exact)"}


def kpi_table_lines(schedules: dict[str, Schedule]) -> list[str]:
    """生成对齐文本对比表（同时适合控制台与 Markdown 代码块）。"""
    modes = list(schedules)
    header = f"{'指标':<14}" + "".join(f"{MODE_LABELS.get(m, m):>18}" for m in modes)
    sep = "-" * len(header)
    lines = [sep, header, sep]
    for field, label, fmt in KPI_COLUMNS:
        row = f"{label:<14}"
        for m in modes:
            kpi: KPI | None = schedules[m].kpi
            val = getattr(kpi, field, 0) if kpi else 0
            text = fmt.format(val) if field != "total_reshuffles" else f"{int(val):d}"
            row += f"{text:>18}"
        lines.append(row)
    lines.append(sep)
    return lines


def print_kpi(schedule: Schedule) -> None:
    """控制台打印单方案指标看板。"""
    kpi = schedule.kpi
    print(f"\n===== 指标看板 [{MODE_LABELS.get(schedule.mode, schedule.mode)}] =====")
    if kpi is None:
        print("(no KPI)")
        return
    for field, label, fmt in KPI_COLUMNS:
        print(f"  {label:<16} {fmt.format(getattr(kpi, field))}")
    for note in schedule.notes:
        print(f"  · {note}")


def save_comparison_report(
    schedules: dict[str, Schedule], path: str | Path
) -> Path:
    """保存 Markdown 对比报告（含各模式说明与仲裁记录）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# SmartPort 调度方案对比报告", ""]
    lines.append(f"- 算例船舶数：{next(iter(schedules.values())).kpi.n_vessels if schedules else 0}")
    lines.append(f"- 对比模式：{', '.join(MODE_LABELS.get(m, m) for m in schedules)}")
    lines.append("")
    lines.append("## 指标对比")
    lines.append("```")
    lines.extend(kpi_table_lines(schedules))
    lines.append("```")
    if "fcfs" in schedules:
        base = schedules["fcfs"].kpi
        lines.append("")
        lines.append("## 相对 FCFS 基准的改进")
        lines.append("")
        lines.append("| 指标 | " + " | ".join(
            MODE_LABELS.get(m, m) for m in schedules if m != "fcfs") + " |")
        lines.append("|---|" + "---|" * (len(schedules) - 1))
        for field, label, fmt in KPI_COLUMNS[:4]:
            row = [label]
            for m, sch in schedules.items():
                if m == "fcfs" or sch.kpi is None or base is None:
                    continue
                cur = getattr(sch.kpi, field)
                ref = getattr(base, field)
                if ref > 0:
                    row.append(f"{(cur - ref) / ref:+.1%}")
                else:
                    row.append("n/a")
            lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    lines.append("## 过程记录（仲裁 / 降级）")
    for m, sch in schedules.items():
        for note in sch.notes:
            lines.append(f"- [{MODE_LABELS.get(m, m)}] {note}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def plot_kpi_comparison(
    schedules: dict[str, Schedule], path: str | Path
) -> Path:
    """关键指标分组柱状图（4 子图）。"""
    metrics = [
        ("avg_port_time_hours", "Avg port time (h)", "{:.1f}"),
        ("max_wait_hours", "Max wait (h)", "{:.1f}"),
        ("total_reshuffles", "Reshuffles", "{:.0f}"),
        ("crane_utilization", "Crane utilization", "{:.0%}"),
    ]
    modes = list(schedules)
    colors = ["#9aa5b1", "#2f6fde", "#2fa84f"]
    fig, axes = plt.subplots(1, 4, figsize=(13, 3.4))
    for ax, (field, label, fmt) in zip(axes, metrics):
        vals = [getattr(schedules[m].kpi, field, 0) if schedules[m].kpi else 0
                for m in modes]
        bars = ax.bar([MODE_LABELS_EN.get(m, m) for m in modes], vals,
                      color=colors[: len(modes)])
        ax.set_title(label, fontsize=10)
        ax.grid(axis="y", alpha=0.3)
        for bar, v in zip(bars, vals):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                    fmt.format(v), ha="center", va="bottom", fontsize=8)
        ax.tick_params(axis="x", labelsize=7.5, rotation=12)
    fig.suptitle("SmartPort scheduling comparison (lower is better except utilization)")
    fig.tight_layout()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return Path(path)
