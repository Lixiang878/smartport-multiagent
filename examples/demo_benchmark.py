"""文献基准对比演示（吸收自 Berth-Scheduler）。

在 Imai 风格文献算例上运行 FCFS / 自适应 GA / MIP 精确解（HiGHS；
可选 pulp-CBC），输出约束校验与指标对比表。

用法：
    python -m examples.demo_benchmark [--name imai_5_2] [--ga-gens 300]
"""
from __future__ import annotations

import argparse

from smartport.algorithms.bap_common import (estimate_service_hours,
                                             validate_berth_plan)
from smartport.algorithms.bap_fcfs import solve_bap_fcfs
from smartport.algorithms.bap_ga import solve_bap_ga
from smartport.algorithms.bap_milp_highs import solve_bap_milp_highs
from smartport.utils.benchmarks import BENCHMARK_NAMES, benchmark_scenario


def _kpi_row(plan, vessels) -> dict:
    n = len(vessels)
    waits = [a.wait_hours for a in plan]
    ports = [a.wait_hours + a.service_hours for a in plan]
    return {
        "avg_wait": sum(waits) / n,
        "avg_port": sum(ports) / n,
        "makespan": max(a.end for a in plan),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="literature benchmark comparison")
    ap.add_argument("--name", default="imai_5_2", choices=list(BENCHMARK_NAMES))
    ap.add_argument("--ga-gens", type=int, default=300)
    args = ap.parse_args()

    sc = benchmark_scenario(args.name)
    print(f"=== {args.name}: {len(sc.vessels)} vessels / "
          f"{len(sc.berths)} berths / {len(sc.cranes)} cranes ===")
    service = estimate_service_hours(sc.vessels)

    results = {}
    fcfs_plan, _ = solve_bap_fcfs(sc.vessels, sc.berths, service)
    results["FCFS"] = fcfs_plan
    ga_plan, _ = solve_bap_ga(sc.vessels, sc.berths, service,
                              config={"generations": args.ga_gens}, seed=42,
                              n_cranes=len(sc.cranes))
    results["GA"] = ga_plan
    if len(sc.vessels) <= 10:
        highs_plan, meta = solve_bap_milp_highs(sc.vessels, sc.berths, service)
        if highs_plan is not None:
            results["MIP-HiGHS"] = highs_plan
            print(f"(HiGHS exact: {meta['solve_seconds']:.2f}s)")

    print(f"{'method':<10} {'avg_wait':>9} {'avg_port':>9} "
          f"{'makespan':>9} {'valid':>6}")
    for name, plan in results.items():
        issues = validate_berth_plan(plan, sc.vessels, sc.berths)
        row = _kpi_row(plan, sc.vessels)
        print(f"{name:<10} {row['avg_wait']:>9.2f} {row['avg_port']:>9.2f} "
              f"{row['makespan']:>9.2f} {str(not issues):>6}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
