"""Honest Multi-Solver Benchmarking Suite for Route.it (Phase 5 §15.4 & Q-HGALS 5.0 §6.10)."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import statistics
import time

from routeit_engine.adapters.solomon_and_ortools import (
    build_solomon_c101_25_sample,
    translate_solomon_instance_to_solve_request,
)
from routeit_engine.contracts.types import (
    CostRateConfig,
    DepotSpec,
    ExactRate,
    FleetMode,
    OptimizationProfile,
    OrderSpec,
    PlanningConfig,
    PlanningMode,
    PriorityTier,
    SolverKind,
    SolveRequest,
    VehicleSpec,
    WindowType,
)
from routeit_engine.orchestrator import solve
from routeit_roads.default_network import create_default_profile_graph_oracle
from routeit_roads.oracles import EuclideanOracle, RoadNode


def build_vadodara_benchmark_instance() -> tuple[SolveRequest, object]:
    oracle = create_default_profile_graph_oracle()
    base_t = 1794882600  # 2026-11-17 08:00 IST
    depot = DepotSpec(
        id="DEP_VAD_1",
        node_id="N_DEPOT_ALKAPURI",
        return_enabled=True,
        return_deadline_utc_s=base_t + 36000,
        opening_utc_s=base_t,
        closing_utc_s=base_t + 36000,
    )
    orders = (
        OrderSpec("ORD_01", "N_SAYAJIGUNJ", 18, 300, base_t + 600, base_t + 7200, WindowType.HARD, PriorityTier.CRITICAL),
        OrderSpec("ORD_02", "N_FATEHGUNJ", 20, 300, base_t + 900, base_t + 9000, WindowType.HARD, PriorityTier.CRITICAL),
        OrderSpec("ORD_03", "N_KARELIBAUG", 22, 360, base_t + 1200, base_t + 10800, WindowType.SOFT, PriorityTier.STANDARD),
        OrderSpec("ORD_04", "N_MANDVI", 15, 300, base_t + 1500, base_t + 12600, WindowType.SOFT, PriorityTier.STANDARD),
        OrderSpec("ORD_05", "N_MANJALPUR", 25, 420, base_t + 1800, base_t + 14400, WindowType.HARD, PriorityTier.CRITICAL),
        OrderSpec("ORD_06", "N_GOTRI", 16, 240, base_t + 600, base_t + 8400, WindowType.HARD, PriorityTier.CRITICAL),
        OrderSpec("ORD_07", "N_AKOTA", 14, 240, base_t + 1200, base_t + 16200, WindowType.SOFT, PriorityTier.FLEXIBLE),
        OrderSpec("ORD_08", "N_NIZAMPURA", 18, 300, base_t + 2400, base_t + 18000, WindowType.SOFT, PriorityTier.FLEXIBLE),
    )
    vehicles = (
        VehicleSpec("VAN_101", 60, 30000, available=True),
        VehicleSpec("VAN_102", 60, 30000, available=True),
        VehicleSpec("VAN_103", 60, 35000, available=True),
        VehicleSpec("VAN_104", 60, 35000, available=True),
    )
    rates = CostRateConfig(
        distance_rate_paise_per_km=ExactRate(800, 1),
        time_rate_paise_per_hour=ExactRate(10000, 1),
        critical_sla_paise_per_min=ExactRate(1000, 1),
        standard_sla_paise_per_min=ExactRate(500, 1),
        flexible_sla_paise_per_min=ExactRate(200, 1),
    )
    cfg = PlanningConfig(
        planning_mode=PlanningMode.COMPLETE,
        fleet_mode=FleetMode.AUTO,
        profile=OptimizationProfile.COST_FOCUSED,
        departure_set_utc_s=(base_t,),
        max_canonical_evaluations=120,
        qpso_particles=8,
        qpso_generations=10,
    )
    return SolveRequest("BENCH_VAD_8", "SHIFT_BENCH", depot, orders, vehicles, rates, cfg), oracle


def run_suite_on_instance(
    name: str,
    base_req: SolveRequest,
    oracle,
    solvers: list[SolverKind],
    seeds: list[int],
    budget: int,
) -> dict[str, object]:
    solver_summaries = []
    all_feasible_costs: list[int] = []

    for sk in solvers:
        runs = []
        for s in seeds:
            cfg = replace(
                base_req.planning_config,
                solver_kind=sk,
                max_canonical_evaluations=budget,
                seed=s,
                qpso_particles=8,
                qpso_generations=10,
            )
            req = replace(base_req, planning_config=cfg)
            res = solve(req, oracle)
            if res.plan is not None and res.plan.hard_feasible:
                all_feasible_costs.append(res.plan.c_dec_paise)
                runs.append(
                    {
                        "seed": s,
                        "status": res.result_status.value,
                        "c_dec_paise": res.plan.c_dec_paise,
                        "idle_seconds": res.plan.idle_waiting_seconds,
                        "distance_m": res.plan.total_distance_m,
                        "routes_used": res.plan.m_routes_used,
                        "evaluations": res.telemetry.canonical_evaluations,
                        "elapsed_ms": round(res.telemetry.elapsed_seconds * 1000.0, 2),
                    }
                )
            else:
                runs.append(
                    {
                        "seed": s,
                        "status": res.result_status.value,
                        "c_dec_paise": None,
                        "idle_seconds": None,
                        "distance_m": None,
                        "routes_used": None,
                        "evaluations": res.telemetry.canonical_evaluations,
                        "elapsed_ms": round(res.telemetry.elapsed_seconds * 1000.0, 2),
                    }
                )

        costs = [r["c_dec_paise"] for r in runs if r["c_dec_paise"] is not None]
        best_c = min(costs) if costs else None
        mean_c = round(statistics.mean(costs), 1) if costs else None
        std_c = round(statistics.pstdev(costs), 1) if len(costs) >= 2 else 0.0
        mean_ms = round(statistics.mean(r["elapsed_ms"] for r in runs), 2)

        solver_summaries.append(
            {
                "solver": sk.value,
                "feasibility_rate_pct": round(100.0 * len(costs) / len(runs), 1),
                "best_cost_paise": best_c,
                "mean_cost_paise": mean_c,
                "std_cost_paise": std_c,
                "mean_elapsed_ms": mean_ms,
                "runs": runs,
            }
        )

    ref_best = min(all_feasible_costs) if all_feasible_costs else None
    for entry in solver_summaries:
        if ref_best and entry["best_cost_paise"] is not None:
            entry["gap_vs_best_observed_pct"] = round(
                100.0 * (entry["best_cost_paise"] - ref_best) / ref_best, 2
            )
        else:
            entry["gap_vs_best_observed_pct"] = None

    return {
        "instance_name": name,
        "evaluation_budget": budget,
        "seeds": seeds,
        "reference_best_observed_paise": ref_best,
        "solvers": solver_summaries,
    }


def main() -> None:
    solvers = [
        SolverKind.CONSTRUCTIVE,
        SolverKind.LOCAL_SEARCH,
        SolverKind.ALNS,
        SolverKind.GA,
        SolverKind.QPSO,
        SolverKind.ORTOOLS_ADAPTER,
    ]
    seeds = [42, 101]

    vad_req, vad_oracle = build_vadodara_benchmark_instance()
    vad_report = run_suite_on_instance("Vadodara_TD_CVRPTW_8", vad_req, vad_oracle, solvers, seeds, budget=120)

    depot_row, cust_rows = build_solomon_c101_25_sample()
    sol_nodes = [RoadNode(f"N_{depot_row.cust_no}", depot_row.x, depot_row.y)] + [
        RoadNode(f"N_{c.cust_no}", c.x, c.y) for c in cust_rows[:12]
    ]
    sol_oracle = EuclideanOracle(sol_nodes, speed_mps=1000.0, coordinate_scale_m=1000.0)
    sol_req = translate_solomon_instance_to_solve_request(
        instance_name="Solomon_C101_12",
        vehicle_count=5,
        vehicle_capacity=200,
        depot_row=depot_row,
        customer_rows=cust_rows[:12],
        max_evaluations=120,
    )
    sol_report = run_suite_on_instance("Solomon_C101_12", sol_req, sol_oracle, solvers, seeds, budget=120)

    full_report = {
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "engine_version": "Q-HGALS-5.0-REV-2026-11-16",
        "methodology_note": (
            "All algorithms evaluated through the identical CanonicalEvaluator under matched canonical evaluation "
            "budgets (120 evaluations per run) across independent seeds (42, 101). "
            "No global optimality or unconditional algorithmic superiority is claimed."
        ),
        "benchmarks": [vad_report, sol_report],
    }

    out_dir = Path(__file__).resolve().parent / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "benchmark_report.json"
    json_path.write_text(json.dumps(full_report, indent=2), encoding="utf-8")

    md_lines = [
        "# Route.it — Executed Multi-Solver Benchmark Report",
        "",
        f"- **Engine Specification**: `{full_report['engine_version']}`",
        f"- **Canonical Evaluation Budget**: `120` evaluations per run",
        f"- **Independent Seeds**: `{seeds}`",
        f"- **Methodology Note**: {full_report['methodology_note']}",
        "",
    ]

    for b in [vad_report, sol_report]:
        md_lines.append(f"## Instance: `{b['instance_name']}` (Best Observed Reference: `{b['reference_best_observed_paise']}` paise)")
        md_lines.append("")
        md_lines.append("| Solver Strategy | Feasibility Rate | Best Cost (paise) | Mean Cost (paise) | Std Dev (paise) | Gap vs Best Observed | Mean Runtime (ms) |")
        md_lines.append("|---|---:|---:|---:|---:|---:|---:|")
        for s in b["solvers"]:
            md_lines.append(
                f"| `{s['solver']}` | {s['feasibility_rate_pct']}% | {s['best_cost_paise']} | {s['mean_cost_paise']} | {s['std_cost_paise']} | +{s['gap_vs_best_observed_pct']}% | {s['mean_elapsed_ms']} ms |"
            )
        md_lines.append("")

    md_path = out_dir / "BENCHMARK_REPORT.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"Benchmark execution completed. Saved {json_path} and {md_path}.")


if __name__ == "__main__":
    main()
