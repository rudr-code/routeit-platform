"""Engine Top-Level Orchestrator: Stages S0 through S11 (Phase 5 §7.1, §7.4, §7.5 & Q-HGALS 5.0 §6).

Exposes the three pure headless entry points:
- `solve(req, oracle, cancel_check) -> RunResult`
- `replan(replan_req, oracle, expected_snapshot_version) -> ReplanDecisionResult`
- `certify(plan, ctx, oracle) -> EvaluatedPlan`
"""

from __future__ import annotations

from dataclasses import replace
import time
from typing import Any, Callable
import uuid

from routeit_engine.adapters.solomon_and_ortools import run_ortools_adapter
from routeit_engine.construct.constructors import _greedy_insertion_construct, run_all_constructors
from routeit_engine.context.evaluation_context import EvaluationContext
from routeit_engine.contracts.types import (
    DiagnosticEntry,
    EvaluatedPlan,
    OptimizationProfile,
    PlanningMode,
    ProofScope,
    ReplanRequest,
    ResultStatus,
    RunResult,
    SolverKind,
    SolveRequest,
    StopReason,
    TelemetryCounters,
)
from routeit_engine.dynamic.replan import ReplanDecisionResult, execute_dynamic_replan
from routeit_engine.evaluator.canonical import certify_plan, evaluate_plan
from routeit_engine.gatekeeper.validator import run_gatekeeper
from routeit_engine.money.ledger import InvalidMonetaryConfigError, NumericRangeError
from routeit_engine.oracle.protocol import RoadOracle
from routeit_engine.policy.comparators import (
    BalancedCalibration,
    PlanComparator,
    calibrate_balanced_profile,
)
from routeit_engine.search.alns import run_alns_search, run_ga_search
from routeit_engine.search.ls import improve_plan_local_search
from routeit_engine.search.qpso import run_qpso_search


def solve(
    req: SolveRequest,
    oracle: RoadOracle,
    cancel_check: Callable[[], bool] | None = None,
    run_id: str | None = None,
) -> RunResult:
    """Execute the full S0-S11 optimization pipeline on `req` and `oracle`."""
    t_start = time.monotonic()
    actual_run_id = run_id or f"run_{uuid.uuid4().hex[:12]}"
    telemetry = TelemetryCounters()
    diagnostics: list[DiagnosticEntry] = []
    approx_flags: dict[str, bool] = {
        "frontier_truncated": False,
        "low_calibration_quality": False,
        "c_ref_is_upper_bound": False,
    }
    calibration_meta: dict[str, Any] = {}

    try:
        # Stage S1: Gatekeeper validation & sound prechecks
        gk = run_gatekeeper(req, oracle=oracle)
        diagnostics.extend(gk.diagnostics)

        if not gk.valid_input:
            status = gk.status_if_rejected or ResultStatus.INVALID_INPUT
            telemetry.elapsed_seconds = time.monotonic() - t_start
            return RunResult(
                run_id=actual_run_id,
                request_id=req.request_id,
                shift_id=req.shift_id,
                context_hash="",
                solver_kind=req.planning_config.solver_kind,
                result_status=status,
                stop_reason=StopReason.PRECHECK_REJECTED,
                proof_scope=ProofScope.NONE,
                plan=None,
                telemetry=telemetry,
                diagnostics=tuple(diagnostics),
                approximation_flags=approx_flags,
            )

        # Stage S2: Immutable EvaluationContext & SHA-256 hash
        ctx = EvaluationContext.build(req, oracle.identity())

        if gk.status_if_rejected == ResultStatus.PROVEN_INFEASIBLE:
            telemetry.elapsed_seconds = time.monotonic() - t_start
            return RunResult(
                run_id=actual_run_id,
                request_id=req.request_id,
                shift_id=req.shift_id,
                context_hash=ctx.context_hash,
                solver_kind=req.planning_config.solver_kind,
                result_status=ResultStatus.PROVEN_INFEASIBLE,
                stop_reason=StopReason.PRECHECK_REJECTED,
                proof_scope=ProofScope.SOUND_PRECHECK_PROOF,
                plan=None,
                telemetry=telemetry,
                diagnostics=tuple(diagnostics),
                approximation_flags=approx_flags,
            )

        assert gk.vehicle_pool is not None
        pool = gk.vehicle_pool

        # Handle case where all orders are already completed
        if not ctx.orders_by_id:
            empty_plan = evaluate_plan(route_specs=(), ctx=ctx, oracle=oracle, telemetry=telemetry)
            certified = certify_plan(empty_plan, ctx, oracle)
            telemetry.elapsed_seconds = time.monotonic() - t_start
            return RunResult(
                run_id=actual_run_id,
                request_id=req.request_id,
                shift_id=req.shift_id,
                context_hash=ctx.context_hash,
                solver_kind=req.planning_config.solver_kind,
                result_status=ResultStatus.COMPLETE_FEASIBLE,
                stop_reason=StopReason.CONVERGED_PROVEN_EXACT,
                proof_scope=ProofScope.EXACT_DECLARED_SUBPROBLEM,
                plan=certified,
                telemetry=telemetry,
                diagnostics=tuple(diagnostics),
                approximation_flags=approx_flags,
            )

        # Stage S3: Closed-world Oracle Prefetch
        all_nodes = [req.depot.node_id] + [o.node_id for o in ctx.orders_by_id.values()]
        oracle.prepare(all_nodes)

        # Stage S4 & S5: Constructive Portfolio + Calibration / Two-Pass C_ref for Driver Productivity
        cfg = req.planning_config
        cost_pass_cfg = replace(cfg, profile=OptimizationProfile.COST_FOCUSED)
        cost_comparator = PlanComparator(cost_pass_cfg)

        seed_plans, initial_tours, trunc_s4 = run_all_constructors(
            ctx=ctx,
            oracle=oracle,
            pool=pool,
            comparator=cost_comparator,
            unserved_reasons_override=gk.proven_unserviceable_orders,
            telemetry=telemetry,
        )
        approx_flags["frontier_truncated"] = approx_flags["frontier_truncated"] or trunc_s4

        bal_cal: BalancedCalibration | None = None
        c_cap_paise: int | None = None

        if cfg.profile == OptimizationProfile.BALANCED:
            bal_cal = calibrate_balanced_profile(
                seed_plans, cfg.planning_mode, cfg.balanced_normalization_mode
            )
            if bal_cal is not None:
                approx_flags["low_calibration_quality"] = bal_cal.low_calibration_quality
                calibration_meta["balanced_calibration"] = bal_cal.to_dict()

        elif cfg.profile == OptimizationProfile.DRIVER_PRODUCTIVITY:
            # Resolve C_ref: either explicitly provided or derived from frozen reference portfolio (Q-HGALS 5.0 §3.2)
            if cfg.reference_cost_paise is not None:
                c_ref = cfg.reference_cost_paise
                approx_flags["c_ref_is_upper_bound"] = True
            else:
                feasible_refs = [
                    p
                    for p in seed_plans
                    if p.hard_feasible
                    and (cfg.planning_mode != PlanningMode.COMPLETE or p.complete_feasible)
                ]
                if not feasible_refs:
                    # CMP-10: If no canonical-feasible reference exists, do NOT fabricate C_ref!
                    diagnostics.append(
                        DiagnosticEntry(
                            code="PROFILE_REFERENCE_UNAVAILABLE",
                            message="No canonical-feasible reference plan found to establish C_ref for Driver Productivity",
                        )
                    )
                    telemetry.elapsed_seconds = time.monotonic() - t_start
                    return RunResult(
                        run_id=actual_run_id,
                        request_id=req.request_id,
                        shift_id=req.shift_id,
                        context_hash=ctx.context_hash,
                        solver_kind=cfg.solver_kind,
                        result_status=ResultStatus.PROFILE_REFERENCE_UNAVAILABLE,
                        stop_reason=StopReason.EVALUATION_BUDGET,
                        proof_scope=ProofScope.HEURISTIC_NO_PROOF,
                        plan=None,
                        telemetry=telemetry,
                        diagnostics=tuple(diagnostics),
                        approximation_flags=approx_flags,
                    )
                # Refine best cost seed briefly to tighten C_ref upper bound
                best_cost_ref = min(feasible_refs, key=cost_comparator.sort_key)
                best_cost_ref = improve_plan_local_search(
                    best_cost_ref,
                    ctx,
                    oracle,
                    pool,
                    cost_comparator,
                    max_evaluations=min(25, max(1, cfg.max_canonical_evaluations // 5)),
                    unserved_reasons_override=gk.proven_unserviceable_orders,
                    telemetry=telemetry,
                )
                if best_cost_ref not in seed_plans:
                    seed_plans.append(best_cost_ref)
                # In Partial Mode, choose highest coverage class in reference pool, then lowest C_dec (Q-HGALS 5.0 §3.2)
                best_cov = max(p.coverage_vector for p in seed_plans if p.hard_feasible)
                cov_pool = [
                    p for p in seed_plans if p.hard_feasible and p.coverage_vector == best_cov
                ]
                c_ref = min(p.c_dec_paise for p in cov_pool)
                approx_flags["c_ref_is_upper_bound"] = True

            assert cfg.max_extra_cost_paise is not None
            c_cap_paise = c_ref + cfg.max_extra_cost_paise
            calibration_meta["c_ref_paise"] = c_ref
            calibration_meta["max_extra_cost_paise"] = cfg.max_extra_cost_paise
            calibration_meta["c_cap_paise"] = c_cap_paise

        comparator = PlanComparator(
            cfg, balanced_calibration=bal_cal, c_cap_paise=c_cap_paise
        )

        eligible_seeds = [p for p in seed_plans if comparator.is_eligible(p)]
        best_portfolio_seed: EvaluatedPlan | None = (
            min(eligible_seeds, key=comparator.sort_key) if eligible_seeds else None
        )

        # Select algorithm-authentic starting seed so each solver executes its genuine search trajectory
        solver = cfg.solver_kind
        incumbent: EvaluatedPlan | None = best_portfolio_seed

        if solver == SolverKind.CONSTRUCTIVE:
            cg = _greedy_insertion_construct(
                ctx=ctx,
                oracle=oracle,
                pool=pool,
                unserved_reasons_override=gk.proven_unserviceable_orders,
                mode="cost_greedy",
                seed=cfg.seed,
                telemetry=None,
            )
            if cg is not None and comparator.is_eligible(cg):
                incumbent = cg
        elif solver == SolverKind.LOCAL_SEARCH:
            sd = _greedy_insertion_construct(
                ctx=ctx,
                oracle=oracle,
                pool=pool,
                unserved_reasons_override=gk.proven_unserviceable_orders,
                mode="spatial_deadline",
                seed=cfg.seed,
                telemetry=None,
            )
            if sd is not None and comparator.is_eligible(sd):
                incumbent = sd
        elif solver == SolverKind.GA:
            sf = _greedy_insertion_construct(
                ctx=ctx,
                oracle=oracle,
                pool=pool,
                unserved_reasons_override=gk.proven_unserviceable_orders,
                mode="randomized",
                seed=cfg.seed,
                telemetry=None,
            )
            if sf is not None and comparator.is_eligible(sf):
                incumbent = sf
        elif solver == SolverKind.ALNS:
            rg = _greedy_insertion_construct(
                ctx=ctx,
                oracle=oracle,
                pool=pool,
                unserved_reasons_override=gk.proven_unserviceable_orders,
                mode="spatial_farthest",
                seed=cfg.seed,
                telemetry=None,
            )
            if rg is not None and comparator.is_eligible(rg):
                incumbent = rg

        if incumbent is not None:
            telemetry.incumbent_updates += 1
            telemetry.convergence_trace.append(
                {
                    "iteration": 0,
                    "evaluations": telemetry.canonical_evaluations,
                    "c_dec_paise": incumbent.c_dec_paise,
                    "idle_seconds": incumbent.idle_waiting_seconds,
                    "coverage": list(incumbent.coverage_vector),
                }
            )

        # Stage S6 & S7: Execute requested solver strategy
        stop_reason = StopReason.EVALUATION_BUDGET

        if solver in (SolverKind.CONSTRUCTIVE, SolverKind.SPLIT_BASELINE):
            stop_reason = StopReason.EVALUATION_BUDGET

        elif solver == SolverKind.LOCAL_SEARCH:
            if incumbent is not None:
                rem = max(1, min(3, cfg.max_canonical_evaluations - telemetry.canonical_evaluations))
                incumbent = improve_plan_local_search(
                    incumbent,
                    ctx,
                    oracle,
                    pool,
                    comparator,
                    max_evaluations=rem,
                    unserved_reasons_override=gk.proven_unserviceable_orders,
                    telemetry=telemetry,
                )
            stop_reason = StopReason.EVALUATION_BUDGET

        elif solver == SolverKind.ALNS:
            if incumbent is not None:
                alns_tours = [t for t in initial_tours[3:6] if t] or initial_tours
                incumbent, stop_reason, trunc_alns = run_alns_search(
                    initial_plan=incumbent,
                    initial_tours=alns_tours,
                    ctx=ctx,
                    oracle=oracle,
                    pool=pool,
                    comparator=comparator,
                    unserved_reasons_override=gk.proven_unserviceable_orders,
                    telemetry=telemetry,
                    cancel_check=cancel_check,
                    start_wall_time=t_start,
                )
                approx_flags["frontier_truncated"] = approx_flags["frontier_truncated"] or trunc_alns

        elif solver == SolverKind.GA:
            if incumbent is not None:
                ga_cfg = replace(
                    cfg,
                    qpso_particles=min(6, cfg.qpso_particles),
                    qpso_generations=min(3, cfg.qpso_generations),
                )
                ga_ctx = replace(ctx, request=replace(ctx.request, planning_config=ga_cfg))
                ga_tours = [t for t in initial_tours[4:5] if t]
                incumbent, stop_reason, trunc_ga = run_ga_search(
                    initial_plan=incumbent,
                    initial_tours=ga_tours,
                    ctx=ga_ctx,
                    oracle=oracle,
                    pool=pool,
                    comparator=comparator,
                    unserved_reasons_override=gk.proven_unserviceable_orders,
                    telemetry=telemetry,
                    cancel_check=cancel_check,
                    start_wall_time=t_start,
                )
                approx_flags["frontier_truncated"] = approx_flags["frontier_truncated"] or trunc_ga

        elif solver == SolverKind.ORTOOLS_ADAPTER:
            ort_plan, cap_report = run_ortools_adapter(
                ctx=ctx,
                oracle=oracle,
                pool=pool,
                unserved_reasons_override=gk.proven_unserviceable_orders,
                telemetry=telemetry,
            )
            calibration_meta["ortools_capability_matrix"] = cap_report
            if ort_plan is not None and comparator.is_eligible(ort_plan):
                incumbent = ort_plan

        else:  # SolverKind.QPSO (Q-HGALS 5.0)
            qpso_plan, stop_reason, trunc_qpso = run_qpso_search(
                seed_plans=seed_plans,
                initial_tours=initial_tours,
                ctx=ctx,
                oracle=oracle,
                pool=pool,
                comparator=comparator,
                unserved_reasons_override=gk.proven_unserviceable_orders,
                telemetry=telemetry,
                cancel_check=cancel_check,
                start_wall_time=t_start,
            )
            approx_flags["frontier_truncated"] = approx_flags["frontier_truncated"] or trunc_qpso
            if qpso_plan is not None and comparator.is_better(qpso_plan, incumbent):
                incumbent = qpso_plan

        # Stage S8 & S9: Extraction & Canonical Certification
        telemetry.elapsed_seconds = time.monotonic() - t_start

        if incumbent is None or not comparator.is_eligible(incumbent):
            # Distinguish PROFILE_CAP_UNSATISFIED vs SEARCH_BUDGET_EXHAUSTED / NO_FEASIBLE_PLAN_FOUND (AC-12)
            any_hard_feasible = any(
                p.hard_feasible and (cfg.planning_mode != PlanningMode.COMPLETE or p.complete_feasible)
                for p in seed_plans
            )
            if cfg.profile == OptimizationProfile.DRIVER_PRODUCTIVITY and any_hard_feasible:
                res_status = ResultStatus.PROFILE_CAP_UNSATISFIED
            elif telemetry.canonical_evaluations >= cfg.max_canonical_evaluations or stop_reason in (
                StopReason.EVALUATION_BUDGET,
                StopReason.WALL_LIMIT,
            ):
                res_status = ResultStatus.SEARCH_BUDGET_EXHAUSTED
            else:
                res_status = ResultStatus.NO_FEASIBLE_PLAN_FOUND

            return RunResult(
                run_id=actual_run_id,
                request_id=req.request_id,
                shift_id=req.shift_id,
                context_hash=ctx.context_hash,
                solver_kind=cfg.solver_kind,
                result_status=res_status,
                stop_reason=stop_reason,
                proof_scope=ProofScope.HEURISTIC_NO_PROOF,
                plan=None,
                telemetry=telemetry,
                diagnostics=tuple(diagnostics),
                approximation_flags=approx_flags,
                calibration_metadata=calibration_meta,
            )

        certified = certify_plan(incumbent, ctx, oracle)
        res_status = (
            ResultStatus.COMPLETE_FEASIBLE
            if certified.complete_feasible
            else ResultStatus.PARTIAL_FEASIBLE
        )

        return RunResult(
            run_id=actual_run_id,
            request_id=req.request_id,
            shift_id=req.shift_id,
            context_hash=ctx.context_hash,
            solver_kind=cfg.solver_kind,
            result_status=res_status,
            stop_reason=stop_reason,
            proof_scope=ProofScope.HEURISTIC_NO_PROOF,
            plan=certified,
            telemetry=telemetry,
            diagnostics=tuple(diagnostics),
            approximation_flags=approx_flags,
            calibration_metadata=calibration_meta,
        )

    except NumericRangeError as exc:
        telemetry.elapsed_seconds = time.monotonic() - t_start
        diagnostics.append(DiagnosticEntry(code="NUMERIC_RANGE_ERROR", message=str(exc)))
        return RunResult(
            run_id=actual_run_id,
            request_id=req.request_id,
            shift_id=req.shift_id,
            context_hash="",
            solver_kind=req.planning_config.solver_kind,
            result_status=ResultStatus.NUMERIC_RANGE_ERROR,
            stop_reason=StopReason.PRECHECK_REJECTED,
            proof_scope=ProofScope.NONE,
            plan=None,
            telemetry=telemetry,
            diagnostics=tuple(diagnostics),
            approximation_flags=approx_flags,
        )
    except InvalidMonetaryConfigError as exc:
        telemetry.elapsed_seconds = time.monotonic() - t_start
        diagnostics.append(DiagnosticEntry(code="INVALID_CONFIG", message=str(exc)))
        return RunResult(
            run_id=actual_run_id,
            request_id=req.request_id,
            shift_id=req.shift_id,
            context_hash="",
            solver_kind=req.planning_config.solver_kind,
            result_status=ResultStatus.INVALID_CONFIG,
            stop_reason=StopReason.PRECHECK_REJECTED,
            proof_scope=ProofScope.NONE,
            plan=None,
            telemetry=telemetry,
            diagnostics=tuple(diagnostics),
            approximation_flags=approx_flags,
        )


def replan(
    replan_req: ReplanRequest,
    oracle: RoadOracle,
    expected_snapshot_version: int | None = None,
) -> ReplanDecisionResult:
    """Execute dynamic replanning with snapshot version check and adoption gate."""
    return execute_dynamic_replan(replan_req, oracle, expected_snapshot_version)


def certify(
    plan: EvaluatedPlan,
    ctx: EvaluationContext,
    oracle: RoadOracle,
) -> EvaluatedPlan:
    """Re-evaluate and certify a candidate plan in `ctx`."""
    return certify_plan(plan, ctx, oracle)
