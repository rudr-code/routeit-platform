"""Dynamic Replanning Controller & Adoption Gate (Q-HGALS 5.0 §6.9 & Phase 5 §12, DYN-01..04).

Enforces:
- Atomic snapshot version validation and GPS freshness check (`DYN-02`).
- Completed deliveries frozen (`completed_order_ids`).
- In-transit vehicles keep their immediate next stop locked (`locked_next_order_id`, `DYN-01`)
  unless `emergency_unlock_next_stop` is explicitly authorized.
- Onboard orders stay with their in-transit vehicle (no mid-route transfer in MVP).
- Depot-idle vehicles can serve pending unassigned depot orders.
- Shift activation ledger (`A_shift`) is preserved: already-activated vehicles have 0 incremental activation charge (`MNY-08`).
- Adoption gate compares candidate vs. current plan re-evaluated on the SAME snapshot (`DYN-03`, `DYN-04`).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from itertools import permutations
from typing import Sequence

from routeit_engine.context.evaluation_context import EvaluationContext
from routeit_engine.contracts.types import (
    DiagnosticEntry,
    EvaluatedPlan,
    ReplanRequest,
    ResultStatus,
    RouteStart,
    SolveRequest,
    TelemetryCounters,
    UnservedReason,
    VehicleLiveState,
    VehicleOperationalState,
    VehicleSpec,
)
from routeit_engine.evaluator.canonical import certify_plan, evaluate_plan, evaluate_route
from routeit_engine.oracle.protocol import RoadOracle
from routeit_engine.policy.comparators import PlanComparator, calibrate_balanced_profile
from routeit_engine.policy.vehicle_assignment import (
    assign_vehicles_to_routes,
    build_sorted_vehicle_pool,
)
from routeit_engine.split.decoder import decode_giant_tour_split


@dataclass(frozen=True)
class ReplanDecisionResult:
    replan_id: str
    adopted: bool
    result_status: ResultStatus
    rejection_reason: str | None
    candidate_plan: EvaluatedPlan | None
    reevaluated_current_plan: EvaluatedPlan | None
    context_hash: str
    telemetry: TelemetryCounters
    diagnostics: tuple[DiagnosticEntry, ...] = ()


def _optimize_single_in_transit_route(
    v_state: VehicleLiveState,
    vehicle: VehicleSpec,
    ctx: EvaluationContext,
    oracle: RoadOracle,
    locked_first: str | None,
    telemetry: TelemetryCounters,
) -> tuple[str, ...]:
    """Optimize remaining onboard sequence for an in-transit vehicle while keeping `locked_first` at index 0."""
    rem_ids = [oid for oid in v_state.assigned_remaining_order_ids if oid in ctx.orders_by_id]
    if not rem_ids:
        return ()

    if locked_first is not None and locked_first in rem_ids:
        tail = [oid for oid in rem_ids if oid != locked_first]
        prefix = [locked_first]
    else:
        tail = list(rem_ids)
        prefix = []

    if len(tail) <= 1:
        return tuple(prefix + tail)

    # For small onboard sets (<= 6), exact enumeration; otherwise 2-opt/relocate greedy
    best_seq = tuple(prefix + tail)
    best_ev = evaluate_route(
        vehicle=vehicle,
        order_ids=best_seq,
        departure_utc_s=v_state.current_time_utc_s,
        ctx=ctx,
        oracle=oracle,
        telemetry=telemetry,
    )

    if len(tail) <= 6:
        for perm in permutations(tail):
            cand_seq = tuple(prefix + list(perm))
            if cand_seq == best_seq:
                continue
            ev = evaluate_route(
                vehicle=vehicle,
                order_ids=cand_seq,
                departure_utc_s=v_state.current_time_utc_s,
                ctx=ctx,
                oracle=oracle,
                telemetry=telemetry,
            )
            if ev.feasible and (
                not best_ev.feasible
                or (ev.route_operating_cost_paise, ev.idle_waiting_seconds)
                < (best_ev.route_operating_cost_paise, best_ev.idle_waiting_seconds)
            ):
                best_seq = cand_seq
                best_ev = ev
    else:
        # Sort tail by window close then refine
        sorted_tail = sorted(tail, key=lambda oid: (ctx.orders_by_id[oid].window_close_utc_s, oid))
        cand_seq = tuple(prefix + sorted_tail)
        ev = evaluate_route(
            vehicle=vehicle,
            order_ids=cand_seq,
            departure_utc_s=v_state.current_time_utc_s,
            ctx=ctx,
            oracle=oracle,
            telemetry=telemetry,
        )
        if ev.feasible and (
            not best_ev.feasible
            or ev.route_operating_cost_paise < best_ev.route_operating_cost_paise
        ):
            best_seq = cand_seq

    return best_seq


def execute_dynamic_replan(
    replan_req: ReplanRequest,
    oracle: RoadOracle,
    expected_snapshot_version: int | None = None,
) -> ReplanDecisionResult:
    """Execute dynamic replanning and evaluate the Adoption Gate (Q-HGALS 5.0 §6.9 & Phase 5 §12)."""
    telemetry = TelemetryCounters()
    diags: list[DiagnosticEntry] = []
    snap = replan_req.snapshot
    base_req = replan_req.base_solve_request

    # 1. Check snapshot version (CAS gate step 1, DYN-03)
    if expected_snapshot_version is not None and snap.snapshot_version != expected_snapshot_version:
        diags.append(
            DiagnosticEntry(
                code="STALE_SNAPSHOT",
                message=f"Snapshot version {snap.snapshot_version} != expected {expected_snapshot_version}",
            )
        )
        return ReplanDecisionResult(
            replan_id=replan_req.replan_id,
            adopted=False,
            result_status=ResultStatus.INVALID_OPERATIONAL_STATE,
            rejection_reason="STALE_SNAPSHOT",
            candidate_plan=None,
            reevaluated_current_plan=None,
            context_hash="",
            telemetry=telemetry,
            diagnostics=tuple(diags),
        )

    # 2. Validate GPS freshness and operational state consistency (DYN-02)
    for vs in snap.vehicle_states:
        if vs.position_timestamp_utc_s is not None:
            staleness = snap.t0_utc_s - vs.position_timestamp_utc_s
            if staleness > snap.max_gps_staleness_seconds or vs.gps_confidence < 0.5:
                diags.append(
                    DiagnosticEntry(
                        code="STALE_OR_UNTRUSTED_GPS",
                        message=(
                            f"Vehicle {vs.vehicle_id} GPS fix is stale ({staleness}s > {snap.max_gps_staleness_seconds}s) "
                            f"or low confidence ({vs.gps_confidence})"
                        ),
                        vehicle_id=vs.vehicle_id,
                    )
                )
                return ReplanDecisionResult(
                    replan_id=replan_req.replan_id,
                    adopted=False,
                    result_status=ResultStatus.INVALID_OPERATIONAL_STATE,
                    rejection_reason="STALE_OR_UNTRUSTED_GPS",
                    candidate_plan=None,
                    reevaluated_current_plan=None,
                    context_hash="",
                    telemetry=telemetry,
                    diagnostics=tuple(diags),
                )

    # 3. Build replan SolveRequest with updated RouteStarts, completed orders, and shift activation set
    route_starts: dict[str, RouteStart] = {}
    updated_vehicles: list[VehicleSpec] = []
    v_state_by_id = {vs.vehicle_id: vs for vs in snap.vehicle_states}

    for v in base_req.vehicles:
        vs = v_state_by_id.get(v.id)
        if vs is None:
            updated_vehicles.append(v)
            continue
        if vs.state in (
            VehicleOperationalState.UNAVAILABLE_BREAKDOWN,
            VehicleOperationalState.COMPLETED_SHIFT,
        ):
            updated_vehicles.append(replace(v, available=False))
        elif vs.state in (
            VehicleOperationalState.EN_ROUTE,
            VehicleOperationalState.WAITING_AT_STOP,
            VehicleOperationalState.SERVICING,
        ):
            updated_vehicles.append(replace(v, available=True))
            locked_stop = None if replan_req.emergency_unlock_next_stop else vs.locked_next_order_id
            route_starts[v.id] = RouteStart(
                node_id=vs.current_node_id,
                start_time_utc_s=vs.current_time_utc_s,
                initial_load_units=vs.remaining_load_units,
                locked_first_stop_order_id=locked_stop,
                is_in_transit=True,
            )
        else:
            updated_vehicles.append(replace(v, available=v.available))

    # Ensure departure_set includes t0_utc_s for depot-idle vehicles
    dep_set = tuple(sorted(set(base_req.planning_config.departure_set_utc_s) | {snap.t0_utc_s}))
    replan_cfg = replace(base_req.planning_config, departure_set_utc_s=dep_set)

    replan_solve_req = SolveRequest(
        request_id=f"{base_req.request_id}_replan_{replan_req.replan_id}",
        shift_id=snap.shift_id,
        depot=base_req.depot,
        orders=base_req.orders,
        vehicles=tuple(updated_vehicles),
        cost_rates=base_req.cost_rates,
        planning_config=replan_cfg,
        activated_vehicle_ids_in_shift=base_req.activated_vehicle_ids_in_shift,
        route_starts_by_vehicle=route_starts,
        completed_order_ids=snap.completed_order_ids,
        sunk_cost_paise=snap.sunk_cost_paise,
        posted_activation_cost_paise_by_vehicle=base_req.posted_activation_cost_paise_by_vehicle,
    )

    ctx = EvaluationContext.build(replan_solve_req, oracle.identity())

    # 4. Re-evaluate the current plan's remaining work against the new snapshot & oracle
    current_remaining_specs: list[tuple[str, int, Sequence[str]]] = []
    for r in replan_req.current_plan.routes:
        vs = v_state_by_id.get(r.vehicle_id)
        if vs is not None and vs.state == VehicleOperationalState.UNAVAILABLE_BREAKDOWN:
            continue
        rem_oids = [s.order_id for s in r.stops if s.order_id not in snap.completed_order_ids]
        if rem_oids:
            dep_t = (
                route_starts[r.vehicle_id].start_time_utc_s
                if r.vehicle_id in route_starts
                else max(snap.t0_utc_s, r.departure_utc_s)
            )
            current_remaining_specs.append((r.vehicle_id, dep_t, rem_oids))

    reevaluated_current = evaluate_plan(
        route_specs=current_remaining_specs,
        ctx=ctx,
        oracle=oracle,
        telemetry=telemetry,
    )

    # 5. Optimize in-transit vehicles (keeping locked next stop and onboard orders)
    candidate_route_specs: list[tuple[str, int, Sequence[str]]] = []
    handled_orders: set[str] = set()

    for vid, r_start in sorted(route_starts.items()):
        vs = v_state_by_id[vid]
        veh = ctx.vehicles_by_id[vid]
        opt_seq = _optimize_single_in_transit_route(
            v_state=vs,
            vehicle=veh,
            ctx=ctx,
            oracle=oracle,
            locked_first=r_start.locked_first_stop_order_id,
            telemetry=telemetry,
        )
        if opt_seq:
            candidate_route_specs.append((vid, r_start.start_time_utc_s, opt_seq))
            handled_orders.update(opt_seq)

    # 6. Optimize pending unassigned orders using depot-idle vehicles
    pending_orders = [
        o for o in base_req.orders if o.id not in snap.completed_order_ids and o.id not in handled_orders
    ]
    if pending_orders:
        depot_idle_vehicles = [
            v for v in updated_vehicles if v.available and v.id not in route_starts
        ]
        if depot_idle_vehicles:
            sub_cfg = replace(replan_cfg, departure_set_utc_s=(snap.t0_utc_s,))
            sub_req = SolveRequest(
                request_id=f"{replan_solve_req.request_id}_depot_sub",
                shift_id=snap.shift_id,
                depot=base_req.depot,
                orders=tuple(pending_orders),
                vehicles=tuple(depot_idle_vehicles),
                cost_rates=base_req.cost_rates,
                planning_config=sub_cfg,
                activated_vehicle_ids_in_shift=base_req.activated_vehicle_ids_in_shift,
                route_starts_by_vehicle={},
                completed_order_ids=frozenset(),
                sunk_cost_paise=0,
                posted_activation_cost_paise_by_vehicle=base_req.posted_activation_cost_paise_by_vehicle,
            )
            sub_ctx = EvaluationContext.build(sub_req, oracle.identity())
            sub_pool = build_sorted_vehicle_pool(
                sub_req.vehicles,
                sub_req.activated_vehicle_ids_in_shift,
                sub_cfg,
                enforce_homogeneous=False,
            )
            sub_comp = PlanComparator(sub_cfg)
            sorted_pending_tour = [
                o.id
                for o in sorted(
                    pending_orders,
                    key=lambda o: (o.window_close_utc_s, o.window_open_utc_s, o.id),
                )
            ]
            sub_plan, _ = decode_giant_tour_split(
                giant_tour_order_ids=sorted_pending_tour,
                ctx=sub_ctx,
                oracle=oracle,
                pool=sub_pool,
                comparator=sub_comp,
                telemetry=telemetry,
            )
            if sub_plan is not None:
                for sr in sub_plan.routes:
                    candidate_route_specs.append((sr.vehicle_id, sr.departure_utc_s, sr.stop_order_ids))

    candidate_plan = evaluate_plan(
        route_specs=candidate_route_specs,
        ctx=ctx,
        oracle=oracle,
        telemetry=telemetry,
    )

    # 7. Adoption Gate evaluation (Q-HGALS 5.0 §6.9 & Phase 5 §12.8)
    bal_cal = calibrate_balanced_profile(
        [p for p in (reevaluated_current, candidate_plan) if p.hard_feasible],
        replan_cfg.planning_mode,
        replan_cfg.balanced_normalization_mode,
    )
    comparator = PlanComparator(replan_cfg, balanced_calibration=bal_cal)

    if not comparator.is_eligible(candidate_plan):
        # DYN-04: If no candidate is feasible under the new snapshot, retain old history marked invalid/replan required; never call new feasible!
        diags.append(
            DiagnosticEntry(
                code="NO_FEASIBLE_REPLAN_FOUND",
                message="Candidate replan violated hard constraints or profile cost cap; never published as feasible",
            )
        )
        return ReplanDecisionResult(
            replan_id=replan_req.replan_id,
            adopted=False,
            result_status=ResultStatus.NO_FEASIBLE_PLAN_FOUND,
            rejection_reason="CANDIDATE_INFEASIBLE_OR_OVER_CAP",
            candidate_plan=candidate_plan,
            reevaluated_current_plan=reevaluated_current,
            context_hash=ctx.context_hash,
            telemetry=telemetry,
            diagnostics=tuple(diags),
        )

    # Certify candidate before adoption
    certified_cand = certify_plan(candidate_plan, ctx, oracle)

    # If current plan became infeasible under the new traffic snapshot, adopt any eligible feasible candidate immediately!
    if not comparator.is_eligible(reevaluated_current):
        res_status = (
            ResultStatus.COMPLETE_FEASIBLE
            if certified_cand.complete_feasible
            else ResultStatus.PARTIAL_FEASIBLE
        )
        return ReplanDecisionResult(
            replan_id=replan_req.replan_id,
            adopted=True,
            result_status=res_status,
            rejection_reason=None,
            candidate_plan=certified_cand,
            reevaluated_current_plan=reevaluated_current,
            context_hash=ctx.context_hash,
            telemetry=telemetry,
            diagnostics=tuple(diags),
        )

    # Both current and candidate are feasible: check strict improvement + hysteresis threshold
    if comparator.compare(certified_cand, reevaluated_current) < 0:
        cost_saving = reevaluated_current.c_dec_paise - certified_cand.c_dec_paise
        if (
            certified_cand.coverage_vector > reevaluated_current.coverage_vector
            or cost_saving >= replan_req.min_cost_improvement_paise
        ):
            res_status = (
                ResultStatus.COMPLETE_FEASIBLE
                if certified_cand.complete_feasible
                else ResultStatus.PARTIAL_FEASIBLE
            )
            return ReplanDecisionResult(
                replan_id=replan_req.replan_id,
                adopted=True,
                result_status=res_status,
                rejection_reason=None,
                candidate_plan=certified_cand,
                reevaluated_current_plan=reevaluated_current,
                context_hash=ctx.context_hash,
                telemetry=telemetry,
                diagnostics=tuple(diags),
            )

    return ReplanDecisionResult(
        replan_id=replan_req.replan_id,
        adopted=False,
        result_status=ResultStatus.COMPLETE_FEASIBLE
        if reevaluated_current.complete_feasible
        else ResultStatus.PARTIAL_FEASIBLE,
        rejection_reason="NO_STRICT_IMPROVEMENT_OVER_CURRENT_PLAN",
        candidate_plan=certified_cand,
        reevaluated_current_plan=reevaluated_current,
        context_hash=ctx.context_hash,
        telemetry=telemetry,
        diagnostics=tuple(diags),
    )
