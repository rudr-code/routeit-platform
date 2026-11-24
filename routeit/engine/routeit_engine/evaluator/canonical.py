"""Canonical Schedule Simulator, Feasibility Checker, and Plan Evaluator (Q-HGALS 5.0 §4.2, §6.3, §6.4).

This module is the SOLE authority for route schedules, hard-constraint feasibility,
idle waiting seconds, and authoritative monetary cost ledgers.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Sequence

from routeit_engine.context.evaluation_context import EvaluationContext
from routeit_engine.contracts.types import (
    EvaluatedPlan,
    EvaluatedRoute,
    OrderSpec,
    PlanningMode,
    PriorityTier,
    RouteLegRecord,
    RouteStart,
    StopSchedule,
    TelemetryCounters,
    UnservedOrderRecord,
    UnservedReason,
    VehicleSpec,
    Violation,
    ViolationKind,
    WindowType,
)
from routeit_engine.money.ledger import (
    build_plan_cost_ledger,
    compute_order_sla_cost_paise,
    compute_route_distance_cost_paise,
    compute_route_time_cost_paise,
)
from routeit_engine.oracle.protocol import OracleStatus, RoadOracle


@dataclass(frozen=True)
class StepState:
    node_id: str
    current_time_utc_s: int
    remaining_load_units: int


def step_stop(
    state: StepState,
    order: OrderSpec,
    seq: int,
    ctx: EvaluationContext,
    oracle: RoadOracle,
    vehicle_profile: str = "urban_van",
    is_locked: bool = False,
    telemetry: TelemetryCounters | None = None,
) -> tuple[StepState | None, StopSchedule | None, RouteLegRecord | None, Violation | None]:
    """Single canonical stop transition step (Phase 5 §11.2 & Q-HGALS 5.0 §4.2, §6.4).

    Formulas:
        A_i = arrival_utc_s from RoadOracle(state.node_id, order.node_id, state.current_time_utc_s)
        B_i = max(A_i, a_i)
        W_i = max(0, a_i - A_i) = B_i - A_i
        D_i = B_i + s_i
        Hard window: require D_i <= b_i
        Soft window: L_i = max(0, D_i - b_i), C_SLA,i = RoundEven(L_i * p_i / 60)
    """
    if telemetry is not None:
        telemetry.road_oracle_queries += 1
    arr_res = oracle.arrival(state.node_id, order.node_id, state.current_time_utc_s, vehicle_profile)
    if not arr_res.ok or arr_res.arrival_utc_s is None or arr_res.distance_m is None:
        v_kind = (
            ViolationKind.ROAD_PATH_UNAVAILABLE
            if arr_res.status in (OracleStatus.PATH_UNAVAILABLE, OracleStatus.ROAD_CLOSED)
            else ViolationKind.ROAD_ORACLE_ERROR
        )
        return (
            None,
            None,
            None,
            Violation(
                kind=v_kind,
                message=f"Road leg {state.node_id}->{order.node_id} failed with {arr_res.status.value}: {arr_res.message}",
                order_id=order.id,
                detail={"oracle_status": arr_res.status.value},
            ),
        )

    a_i = arr_res.arrival_utc_s
    b_i = max(a_i, order.window_open_utc_s)
    w_i = b_i - a_i
    d_i = b_i + order.service_seconds
    l_i = max(0, d_i - order.window_close_utc_s)

    violation: Violation | None = None
    if order.window_type == WindowType.HARD and l_i > 0:
        violation = Violation(
            kind=ViolationKind.HARD_WINDOW_LATE,
            message=(
                f"Hard time window violated at order {order.id}: completion D_i={d_i} > deadline b_i={order.window_close_utc_s} "
                f"(late by {l_i}s)"
            ),
            order_id=order.id,
            detail={"completion_utc_s": d_i, "deadline_utc_s": order.window_close_utc_s, "lateness_s": l_i},
        )

    sla_paise = compute_order_sla_cost_paise(l_i, order, ctx.request.cost_rates)
    new_load = state.remaining_load_units - order.demand_units

    stop_sched = StopSchedule(
        seq=seq,
        order_id=order.id,
        node_id=order.node_id,
        demand_units=order.demand_units,
        arrival_utc_s=a_i,
        window_open_utc_s=order.window_open_utc_s,
        window_close_utc_s=order.window_close_utc_s,
        window_type=order.window_type,
        priority=order.priority,
        wait_seconds=w_i,
        service_start_utc_s=b_i,
        service_seconds=order.service_seconds,
        service_completion_utc_s=d_i,
        lateness_seconds=l_i,
        sla_cost_paise=sla_paise,
        leg_distance_m=arr_res.distance_m,
        leg_travel_seconds=a_i - state.current_time_utc_s,
        load_after_Units=new_load,
        is_locked=is_locked,
    )
    leg_rec = RouteLegRecord(
        seq=seq,
        from_node_id=state.node_id,
        to_node_id=order.node_id,
        departure_utc_s=state.current_time_utc_s,
        arrival_utc_s=a_i,
        distance_m=arr_res.distance_m,
        travel_seconds=a_i - state.current_time_utc_s,
        path_node_ids=arr_res.path_node_ids,
        path_edge_ids=arr_res.path_edge_ids,
    )
    next_state = StepState(
        node_id=order.node_id,
        current_time_utc_s=d_i,
        remaining_load_units=new_load,
    )
    return next_state, stop_sched, leg_rec, violation


def evaluate_route(
    *,
    vehicle: VehicleSpec,
    order_ids: Sequence[str],
    departure_utc_s: int,
    ctx: EvaluationContext,
    oracle: RoadOracle,
    start_override: RouteStart | None = None,
    telemetry: TelemetryCounters | None = None,
) -> EvaluatedRoute:
    """Canonically evaluate one vehicle route (depot-origin or in-transit RouteStart)."""
    req = ctx.request
    violations: list[Violation] = []

    if not vehicle.available:
        violations.append(
            Violation(
                kind=ViolationKind.VEHICLE_UNAVAILABLE,
                message=f"Vehicle {vehicle.id} is marked unavailable for the shift",
                vehicle_id=vehicle.id,
            )
        )

    start_state_spec = start_override or req.route_starts_by_vehicle.get(vehicle.id)
    if start_state_spec is None:
        start_node = req.depot.node_id
        start_time = departure_utc_s
        if departure_utc_s not in req.planning_config.departure_set_utc_s:
            violations.append(
                Violation(
                    kind=ViolationKind.DEPARTURE_OUTSIDE_DOMAIN,
                    message=f"Departure {departure_utc_s} not in allowed departure set",
                    vehicle_id=vehicle.id,
                )
            )
        if departure_utc_s < req.depot.opening_utc_s:
            violations.append(
                Violation(
                    kind=ViolationKind.DEPARTURE_OUTSIDE_DOMAIN,
                    message=f"Departure {departure_utc_s} precedes depot opening {req.depot.opening_utc_s}",
                    vehicle_id=vehicle.id,
                )
            )
        locked_first_id = None
    else:
        start_node = start_state_spec.node_id
        start_time = start_state_spec.start_time_utc_s
        locked_first_id = start_state_spec.locked_first_stop_order_id

    # Check locked first stop constraint (DYN-01)
    if locked_first_id is not None:
        if not order_ids or order_ids[0] != locked_first_id:
            violations.append(
                Violation(
                    kind=ViolationKind.LOCKED_STOP_VIOLATED,
                    message=f"Vehicle {vehicle.id} locked next stop {locked_first_id} must remain first stop, got {order_ids[:1]}",
                    vehicle_id=vehicle.id,
                    order_id=locked_first_id,
                )
            )

    # Resolve orders and check capacity
    orders: list[OrderSpec] = []
    for oid in order_ids:
        if oid in req.completed_order_ids:
            violations.append(
                Violation(
                    kind=ViolationKind.COMPLETED_ORDER_REASSIGNED,
                    message=f"Completed order {oid} cannot be reassigned",
                    order_id=oid,
                    vehicle_id=vehicle.id,
                )
            )
            continue
        if oid not in ctx.orders_by_id:
            violations.append(
                Violation(
                    kind=ViolationKind.DUPLICATE_OR_MISSING_ORDER,
                    message=f"Unknown order ID {oid} in route for vehicle {vehicle.id}",
                    order_id=oid,
                    vehicle_id=vehicle.id,
                )
            )
            continue
        orders.append(ctx.orders_by_id[oid])

    route_demand = sum(o.demand_units for o in orders)
    if start_state_spec is not None and start_state_spec.initial_load_units is not None:
        initial_load = start_state_spec.initial_load_units
    else:
        initial_load = route_demand

    if route_demand > initial_load or initial_load > vehicle.capacity_units:
        violations.append(
            Violation(
                kind=ViolationKind.CAPACITY_EXCEEDED,
                message=(
                    f"Vehicle {vehicle.id} capacity exceeded: route_demand={route_demand}, "
                    f"initial_load={initial_load}, capacity={vehicle.capacity_units}"
                ),
                vehicle_id=vehicle.id,
                detail={"route_demand": route_demand, "capacity": vehicle.capacity_units},
            )
        )

    state = StepState(node_id=start_node, current_time_utc_s=start_time, remaining_load_units=initial_load)
    stops: list[StopSchedule] = []
    legs: list[RouteLegRecord] = []

    for idx, order in enumerate(orders, start=1):
        is_locked = locked_first_id is not None and idx == 1 and order.id == locked_first_id
        next_state, stop_sched, leg_rec, viol = step_stop(
            state=state,
            order=order,
            seq=idx,
            ctx=ctx,
            oracle=oracle,
            vehicle_profile=vehicle.vehicle_profile,
            is_locked=is_locked,
            telemetry=telemetry,
        )
        if viol is not None:
            violations.append(viol)
        if next_state is None or stop_sched is None or leg_rec is None:
            break
        stops.append(stop_sched)
        legs.append(leg_rec)
        state = next_state

    return_enabled = (
        vehicle.return_to_depot
        if vehicle.return_to_depot is not None
        else req.depot.return_enabled
    )
    return_deadline = (
        vehicle.return_deadline_utc_s
        if vehicle.return_deadline_utc_s is not None
        else req.depot.return_deadline_utc_s
    )
    if return_deadline is None and req.depot.closing_utc_s is not None:
        return_deadline = req.depot.closing_utc_s

    # Evaluate return leg to depot if enabled and route has at least one stop
    if return_enabled and stops and len(stops) == len(orders):
        if telemetry is not None:
            telemetry.road_oracle_queries += 1
        ret_res = oracle.arrival(
            state.node_id,
            req.depot.node_id,
            state.current_time_utc_s,
            vehicle.vehicle_profile,
        )
        if not ret_res.ok or ret_res.arrival_utc_s is None or ret_res.distance_m is None:
            v_kind = (
                ViolationKind.ROAD_PATH_UNAVAILABLE
                if ret_res.status in (OracleStatus.PATH_UNAVAILABLE, OracleStatus.ROAD_CLOSED)
                else ViolationKind.ROAD_ORACLE_ERROR
            )
            violations.append(
                Violation(
                    kind=v_kind,
                    message=f"Return leg {state.node_id}->{req.depot.node_id} failed with {ret_res.status.value}",
                    vehicle_id=vehicle.id,
                )
            )
        else:
            legs.append(
                RouteLegRecord(
                    seq=len(legs) + 1,
                    from_node_id=state.node_id,
                    to_node_id=req.depot.node_id,
                    departure_utc_s=state.current_time_utc_s,
                    arrival_utc_s=ret_res.arrival_utc_s,
                    distance_m=ret_res.distance_m,
                    travel_seconds=ret_res.arrival_utc_s - state.current_time_utc_s,
                    path_node_ids=ret_res.path_node_ids,
                    path_edge_ids=ret_res.path_edge_ids,
                )
            )
            state = StepState(
                node_id=req.depot.node_id,
                current_time_utc_s=ret_res.arrival_utc_s,
                remaining_load_units=state.remaining_load_units,
            )
            if return_deadline is not None and ret_res.arrival_utc_s > return_deadline:
                violations.append(
                    Violation(
                        kind=ViolationKind.DEPOT_RETURN_DEADLINE_LATE,
                        message=(
                            f"Vehicle {vehicle.id} return arrival ({ret_res.arrival_utc_s}) exceeds "
                            f"depot return deadline ({return_deadline})"
                        ),
                        vehicle_id=vehicle.id,
                        detail={"return_arrival_utc_s": ret_res.arrival_utc_s, "deadline_utc_s": return_deadline},
                    )
                )

    completion_time = state.current_time_utc_s
    total_distance_m = sum(leg.distance_m for leg in legs)
    paid_duration_s = max(0, completion_time - start_time) if stops else 0
    # I_idle sums customer-window waiting W_i over served stops in integer seconds (Q-HGALS 5.0 §4.2)
    idle_waiting_s = sum(s.wait_seconds for s in stops)

    dist_cost_paise = compute_route_distance_cost_paise(
        total_distance_m, req.cost_rates.distance_rate_paise_per_km
    )
    time_cost_paise = compute_route_time_cost_paise(
        paid_duration_s, req.cost_rates.time_rate_paise_per_hour
    )
    sla_cost_paise = sum(s.sla_cost_paise for s in stops)
    op_cost_paise = dist_cost_paise + time_cost_paise + sla_cost_paise

    is_new_activation = bool(stops) and (vehicle.id not in req.activated_vehicle_ids_in_shift)
    inc_act_paise = vehicle.activation_cost_paise if is_new_activation else 0

    return EvaluatedRoute(
        vehicle_id=vehicle.id,
        departure_utc_s=start_time,
        start_node_id=start_node,
        stops=tuple(stops),
        legs=tuple(legs),
        return_to_depot=return_enabled,
        completion_utc_s=completion_time,
        total_distance_m=total_distance_m,
        paid_duration_seconds=paid_duration_s,
        idle_waiting_seconds=idle_waiting_s,
        initial_load_units=initial_load,
        capacity_units=vehicle.capacity_units,
        distance_cost_paise=dist_cost_paise,
        time_cost_paise=time_cost_paise,
        sla_cost_paise=sla_cost_paise,
        route_operating_cost_paise=op_cost_paise,
        newly_activated_in_shift=is_new_activation,
        incremental_activation_cost_paise=inc_act_paise,
        total_incremental_route_cost_paise=op_cost_paise + inc_act_paise,
        feasible=(len(violations) == 0 and len(stops) == len(orders)),
        violations=tuple(violations),
    )


def evaluate_plan(
    *,
    route_specs: Sequence[tuple[ str, int, Sequence[str] ]],  # (vehicle_id, departure_utc_s, order_ids)
    ctx: EvaluationContext,
    oracle: RoadOracle,
    unserved_reasons_override: dict[str, tuple[UnservedReason, str]] | None = None,
    default_unserved_reason: UnservedReason = UnservedReason.UNSERVED_BY_OPTIMIZATION_DECISION,
    telemetry: TelemetryCounters | None = None,
) -> EvaluatedPlan:
    """Canonically evaluate a complete or partial fleet delivery plan (Q-HGALS 5.0 §3, §4, §6)."""
    if telemetry is not None:
        telemetry.canonical_evaluations += 1

    req = ctx.request
    violations: list[Violation] = []
    evaluated_routes: list[EvaluatedRoute] = []
    seen_vehicles: set[str] = set()
    served_order_counts: dict[str, int] = {}

    for vid, dep_s, oids in route_specs:
        if not oids:
            # Empty routes are never materialized and do not activate vehicles (Q-HGALS 5.0 §2.1)
            continue
        if vid in seen_vehicles:
            violations.append(
                Violation(
                    kind=ViolationKind.FLEET_LIMIT_EXCEEDED,
                    message=f"Vehicle {vid} assigned to multiple routes in the same shift plan",
                    vehicle_id=vid,
                )
            )
        seen_vehicles.add(vid)
        if vid not in ctx.vehicles_by_id:
            violations.append(
                Violation(
                    kind=ViolationKind.VEHICLE_UNAVAILABLE,
                    message=f"Unknown vehicle ID {vid}",
                    vehicle_id=vid,
                )
            )
            continue
        vehicle = ctx.vehicles_by_id[vid]
        ev_route = evaluate_route(
            vehicle=vehicle,
            order_ids=oids,
            departure_utc_s=dep_s,
            ctx=ctx,
            oracle=oracle,
            telemetry=telemetry,
        )
        evaluated_routes.append(ev_route)
        violations.extend(ev_route.violations)
        for oid in oids:
            served_order_counts[oid] = served_order_counts.get(oid, 0) + 1

    # Check duplicate order visits across routes (AC-02)
    for oid, count in served_order_counts.items():
        if count > 1:
            violations.append(
                Violation(
                    kind=ViolationKind.DUPLICATE_OR_MISSING_ORDER,
                    message=f"Order {oid} is assigned {count} times across routes",
                    order_id=oid,
                )
            )

    # Sort evaluated routes canonically by vehicle_id
    evaluated_routes.sort(key=lambda r: r.vehicle_id)

    served_ids = frozenset(
        s.order_id for r in evaluated_routes for s in r.stops if served_order_counts.get(s.order_id, 0) == 1
    )

    all_requested_orders = [o for o in req.orders if o.id not in req.completed_order_ids]
    unserved_records: list[UnservedOrderRecord] = []
    for o in sorted(all_requested_orders, key=lambda x: x.id):
        if o.id not in served_ids:
            if unserved_reasons_override and o.id in unserved_reasons_override:
                reason, detail = unserved_reasons_override[o.id]
            else:
                reason = default_unserved_reason
                detail = "Order omitted in partial plan"
            unserved_records.append(
                UnservedOrderRecord(
                    order_id=o.id,
                    priority=o.priority,
                    reason=reason,
                    detail=detail,
                )
            )

    # Partition invariant check: S ∩ U = ∅ and S ∪ U = N_active (EVAL-04)
    unserved_ids = {u.order_id for u in unserved_records}
    assert served_ids.isdisjoint(unserved_ids), "Served and unserved sets must be disjoint"
    assert len(served_ids) + len(unserved_ids) == len(all_requested_orders), "Partition must be exhaustive"

    # Fleet count and shift ceiling checks
    selected_vids = tuple(r.vehicle_id for r in evaluated_routes)
    newly_activated_vids = tuple(
        vid for vid in selected_vids if vid not in req.activated_vehicle_ids_in_shift
    )
    shift_after_vids = req.activated_vehicle_ids_in_shift | frozenset(selected_vids)

    m_routes = len(evaluated_routes)
    m_new = len(newly_activated_vids)
    m_shift_after = len(shift_after_vids)

    cfg = req.planning_config
    # For non-in-transit routes, check route count limit
    depot_dispatched_count = sum(
        1 for r in evaluated_routes if r.vehicle_id not in req.route_starts_by_vehicle
    )
    eligible_depot_vehicles = sum(
        1 for v in req.vehicles if v.available and v.id not in req.route_starts_by_vehicle
    )
    max_routes = eligible_depot_vehicles
    if cfg.max_route_count is not None:
        max_routes = min(max_routes, cfg.max_route_count)
    if cfg.fleet_mode.value == "TARGET" and cfg.target_fleet_size is not None:
        max_routes = min(max_routes, cfg.target_fleet_size)
        if cfg.target_fleet_policy.value == "EXACT_ACTIVE_COUNT" and m_routes != cfg.target_fleet_size:
            violations.append(
                Violation(
                    kind=ViolationKind.FLEET_LIMIT_EXCEEDED,
                    message=f"Target Fleet policy EXACT_ACTIVE_COUNT requires {cfg.target_fleet_size} routes, got {m_routes}",
                )
            )

    if depot_dispatched_count > max_routes:
        violations.append(
            Violation(
                kind=ViolationKind.FLEET_LIMIT_EXCEEDED,
                message=f"Routes used ({depot_dispatched_count}) exceeds allowed fleet limit ({max_routes})",
            )
        )

    if cfg.max_shift_activated_vehicles is not None and m_shift_after > cfg.max_shift_activated_vehicles:
        violations.append(
            Violation(
                kind=ViolationKind.SHIFT_CEILING_EXCEEDED,
                message=(
                    f"Shift-activated fleet count ({m_shift_after}) exceeds "
                    f"max_shift_activated_vehicles ({cfg.max_shift_activated_vehicles})"
                ),
            )
        )

    # Coverage vector (N_C, N_S, N_F) over served orders
    n_c = sum(1 for oid in served_ids if ctx.orders_by_id[oid].priority == PriorityTier.CRITICAL)
    n_s = sum(1 for oid in served_ids if ctx.orders_by_id[oid].priority == PriorityTier.STANDARD)
    n_f = sum(1 for oid in served_ids if ctx.orders_by_id[oid].priority == PriorityTier.FLEXIBLE)

    # Build authoritative CostLedger
    r_dist_lines = {r.vehicle_id: r.distance_cost_paise for r in evaluated_routes}
    r_time_lines = {r.vehicle_id: r.time_cost_paise for r in evaluated_routes}
    o_sla_lines = {
        s.order_id: s.sla_cost_paise
        for r in evaluated_routes
        for s in r.stops
        if ctx.orders_by_id[s.order_id].window_type == WindowType.SOFT
    }
    new_act_lines = {
        vid: ctx.vehicles_by_id[vid].activation_cost_paise for vid in newly_activated_vids
    }
    served_soft_count = sum(
        1 for oid in served_ids if ctx.orders_by_id[oid].window_type == WindowType.SOFT
    )

    ledger = build_plan_cost_ledger(
        route_distance_lines_paise=r_dist_lines,
        route_time_lines_paise=r_time_lines,
        order_sla_lines_paise=o_sla_lines,
        newly_activated_vehicle_costs_paise=new_act_lines,
        posted_activation_cost_paise_by_vehicle=req.posted_activation_cost_paise_by_vehicle,
        sunk_cost_before_paise=req.sunk_cost_paise,
        served_soft_orders_count=served_soft_count,
        rounding_policy_version=req.cost_rates.rounding_policy_version,
    )

    # Served signature in Critical -> Standard -> Flexible, ascending order_id
    # Use -1 for served and 0 for unserved so lexicographic minimization prefers inclusion at first differing bit!
    tier_rank = {
        PriorityTier.CRITICAL: 0,
        PriorityTier.STANDARD: 1,
        PriorityTier.FLEXIBLE: 2,
    }
    ordered_for_sig = sorted(all_requested_orders, key=lambda o: (tier_rank[o.priority], o.id))
    served_sig = tuple(-1 if o.id in served_ids else 0 for o in ordered_for_sig)

    # Canonical route signature: ordered by (vehicle_id, departure_second, stop_ids)
    route_sig = tuple(
        sorted((r.vehicle_id, r.departure_utc_s, r.stop_order_ids) for r in evaluated_routes)
    )

    plan_hash_payload = {
        "context_hash": ctx.context_hash,
        "routes": [
            {"v": r.vehicle_id, "dep": r.departure_utc_s, "stops": list(r.stop_order_ids)}
            for r in evaluated_routes
        ],
    }
    plan_hash = hashlib.sha256(
        json.dumps(plan_hash_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    hard_feasible = len(violations) == 0
    complete_feasible = hard_feasible and (len(unserved_records) == 0)

    if req.planning_config.planning_mode == PlanningMode.COMPLETE and len(unserved_records) > 0:
        violations.append(
            Violation(
                kind=ViolationKind.DUPLICATE_OR_MISSING_ORDER,
                message=f"Complete Mode requires all {len(all_requested_orders)} orders served; {len(unserved_records)} unserved",
            )
        )
        hard_feasible = False

    return EvaluatedPlan(
        context_hash=ctx.context_hash,
        routes=tuple(evaluated_routes),
        served_order_ids=served_ids,
        unserved_orders=tuple(unserved_records),
        coverage_vector=(n_c, n_s, n_f),
        idle_waiting_seconds=sum(r.idle_waiting_seconds for r in evaluated_routes),
        total_distance_m=sum(r.total_distance_m for r in evaluated_routes),
        total_paid_seconds=sum(r.paid_duration_seconds for r in evaluated_routes),
        m_routes_used=m_routes,
        m_new_activated=m_new,
        m_shift_activated_after=m_shift_after,
        selected_vehicle_ids=selected_vids,
        newly_activated_vehicle_ids=newly_activated_vids,
        shift_activated_vehicle_ids_after=shift_after_vids,
        ledger=ledger,
        hard_feasible=hard_feasible,
        complete_feasible=complete_feasible,
        violations=tuple(violations),
        served_signature=served_sig,
        canonical_route_signature=route_sig,
        plan_hash=plan_hash,
    )


def certify_plan(plan: EvaluatedPlan, ctx: EvaluationContext, oracle: RoadOracle) -> EvaluatedPlan:
    """Re-evaluate a candidate plan from its genotype-independent route list in the same context (Stage S9).

    Raises ValueError if the re-evaluated plan does not match the cached plan's hash, cost, idle, or feasibility.
    """
    route_specs = [(r.vehicle_id, r.departure_utc_s, r.stop_order_ids) for r in plan.routes]
    unserved_map = {u.order_id: (u.reason, u.detail) for u in plan.unserved_orders}
    re_evaluated = evaluate_plan(
        route_specs=route_specs,
        ctx=ctx,
        oracle=oracle,
        unserved_reasons_override=unserved_map,
    )
    if (
        re_evaluated.plan_hash != plan.plan_hash
        or re_evaluated.c_dec_paise != plan.c_dec_paise
        or re_evaluated.idle_waiting_seconds != plan.idle_waiting_seconds
        or re_evaluated.hard_feasible != plan.hard_feasible
        or re_evaluated.coverage_vector != plan.coverage_vector
    ):
        raise ValueError(
            "INTERNAL_INVARIANT_FAILURE: Certification mismatch between candidate record and fresh canonical evaluation"
        )
    return re_evaluated
