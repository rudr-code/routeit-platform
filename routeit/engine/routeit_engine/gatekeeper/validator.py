"""Gatekeeper input validator & sound precheck proofs (Q-HGALS 5.0 §6.5 & Phase 5 §7.5)."""

from __future__ import annotations

from dataclasses import dataclass, field
import math

from routeit_engine.contracts.types import (
    DiagnosticEntry,
    OptimizationProfile,
    OrderSpec,
    PlanningMode,
    ResultStatus,
    SolveRequest,
    UnservedReason,
    WindowType,
)
from routeit_engine.money.ledger import MAX_REPRESENTABLE_PAISE
from routeit_engine.oracle.protocol import OracleStatus, RoadOracle
from routeit_engine.policy.vehicle_assignment import (
    ShiftFleetPolicyConflictError,
    SortedVehiclePool,
    build_sorted_vehicle_pool,
)


@dataclass(frozen=True)
class GatekeeperReport:
    valid_input: bool
    status_if_rejected: ResultStatus | None
    vehicle_pool: SortedVehiclePool | None
    proven_unserviceable_orders: dict[str, tuple[UnservedReason, str]] = field(default_factory=dict)
    capacity_lower_bound_all_orders: int = 0
    capacity_lower_bound_serviceable_orders: int = 0
    diagnostics: tuple[DiagnosticEntry, ...] = ()


def compute_homogeneous_fleet_lower_bound(demands: list[int], capacity_q: int) -> int:
    """Valid homogeneous fleet lower bound per Q-HGALS 5.0 §6.5:
    LB = max(ceil(sum_i d_i / Q), count_i[d_i > Q / 2]).
    """
    if not demands or capacity_q <= 0:
        return 0
    total_d = sum(demands)
    lb_sum = math.ceil(total_d / capacity_q)
    lb_half = sum(1 for d in demands if 2 * d > capacity_q)
    return max(lb_sum, lb_half)


def compute_fleet_capacity_lower_bound(demands: list[int], sorted_capacities: list[int]) -> int:
    """Compute sound vehicle count lower bound for either homogeneous or heterogeneous fleets."""
    if not demands or not sorted_capacities:
        return 0
    unique_caps = set(sorted_capacities)
    if len(unique_caps) == 1:
        return compute_homogeneous_fleet_lower_bound(demands, sorted_capacities[0])
    total_d = sum(demands)
    desc_caps = sorted(sorted_capacities, reverse=True)
    running = 0
    for idx, cap in enumerate(desc_caps, start=1):
        running += cap
        if running >= total_d:
            return idx
    # Even all available vehicles combined cannot hold total_d: estimate additional vehicles using max capacity
    max_q = desc_caps[0]
    shortfall = total_d - running
    return len(desc_caps) + math.ceil(shortfall / max(1, max_q))


def run_gatekeeper(req: SolveRequest, oracle: RoadOracle | None = None) -> GatekeeperReport:
    """Validate SolveRequest and compute sound precheck infeasibility proofs."""
    diags: list[DiagnosticEntry] = []

    if not req.depot.id or not req.depot.node_id:
        diags.append(DiagnosticEntry(code="INVALID_DEPOT", message="Depot ID and node_id are required"))
        return GatekeeperReport(False, ResultStatus.INVALID_INPUT, None, diagnostics=tuple(diags))

    if (
        req.depot.closing_utc_s is not None
        and req.depot.closing_utc_s < req.depot.opening_utc_s
    ):
        diags.append(
            DiagnosticEntry(
                code="INVALID_DEPOT_WINDOW",
                message="Depot closing time cannot precede opening time",
            )
        )
        return GatekeeperReport(False, ResultStatus.INVALID_INPUT, None, diagnostics=tuple(diags))

    # Validate cost rates (missing or negative rates -> INVALID_CONFIG, MNY-06)
    rates = req.cost_rates
    for rate_name, rate_val in [
        ("distance_rate_paise_per_km", rates.distance_rate_paise_per_km),
        ("time_rate_paise_per_hour", rates.time_rate_paise_per_hour),
        ("critical_sla_paise_per_min", rates.critical_sla_paise_per_min),
        ("standard_sla_paise_per_min", rates.standard_sla_paise_per_min),
        ("flexible_sla_paise_per_min", rates.flexible_sla_paise_per_min),
    ]:
        if rate_val is None or rate_val.numerator < 0 or rate_val.denominator <= 0:
            diags.append(
                DiagnosticEntry(
                    code="INVALID_COST_RATE",
                    message=f"Cost rate {rate_name} must be present and nonnegative",
                )
            )
            return GatekeeperReport(False, ResultStatus.INVALID_CONFIG, None, diagnostics=tuple(diags))

    # Validate departure set
    cfg = req.planning_config
    if not cfg.departure_set_utc_s:
        diags.append(
            DiagnosticEntry(
                code="EMPTY_DEPARTURE_SET",
                message="departure_set_utc_s must contain at least one finite departure timestamp",
            )
        )
        return GatekeeperReport(False, ResultStatus.INVALID_CONFIG, None, diagnostics=tuple(diags))

    # Validate QPSO parameters if QPSO is selected
    if (
        not math.isfinite(cfg.qpso_alpha_min)
        or not math.isfinite(cfg.qpso_alpha_max)
        or cfg.qpso_alpha_min <= 0.0
        or cfg.qpso_alpha_max < cfg.qpso_alpha_min
        or cfg.qpso_particles < 1
        or cfg.qpso_generations < 1
    ):
        diags.append(
            DiagnosticEntry(
                code="INVALID_QPSO_CONFIG",
                message="QPSO requires P >= 1, T >= 1, and finite 0 < alpha_min <= alpha_max",
            )
        )
        return GatekeeperReport(False, ResultStatus.INVALID_CONFIG, None, diagnostics=tuple(diags))

    # Validate Driver Productivity config
    if cfg.profile == OptimizationProfile.DRIVER_PRODUCTIVITY:
        if cfg.max_extra_cost_paise is None or cfg.max_extra_cost_paise < 0:
            diags.append(
                DiagnosticEntry(
                    code="INVALID_PRODUCTIVITY_CAP",
                    message="DRIVER_PRODUCTIVITY requires nonnegative integer max_extra_cost_paise",
                )
            )
            return GatekeeperReport(False, ResultStatus.INVALID_CONFIG, None, diagnostics=tuple(diags))

    # Validate vehicles
    seen_vids: set[str] = set()
    for v in req.vehicles:
        if not v.id or v.id in seen_vids:
            diags.append(
                DiagnosticEntry(
                    code="DUPLICATE_OR_EMPTY_VEHICLE_ID",
                    message=f"Duplicate or empty vehicle ID: {v.id!r}",
                    vehicle_id=v.id,
                )
            )
            return GatekeeperReport(False, ResultStatus.INVALID_INPUT, None, diagnostics=tuple(diags))
        seen_vids.add(v.id)
        if v.capacity_units <= 0:
            diags.append(
                DiagnosticEntry(
                    code="NON_POSITIVE_CAPACITY",
                    message=f"Vehicle {v.id} capacity must be > 0, got {v.capacity_units}",
                    vehicle_id=v.id,
                )
            )
            return GatekeeperReport(False, ResultStatus.INVALID_INPUT, None, diagnostics=tuple(diags))
        if v.activation_cost_paise < 0 or v.activation_cost_paise > MAX_REPRESENTABLE_PAISE:
            diags.append(
                DiagnosticEntry(
                    code="INVALID_ACTIVATION_COST",
                    message=f"Vehicle {v.id} activation cost out of valid range",
                    vehicle_id=v.id,
                )
            )
            return GatekeeperReport(
                False,
                ResultStatus.NUMERIC_RANGE_ERROR
                if v.activation_cost_paise > MAX_REPRESENTABLE_PAISE
                else ResultStatus.INVALID_CONFIG,
                None,
                diagnostics=tuple(diags),
            )

    try:
        pool = build_sorted_vehicle_pool(
            req.vehicles,
            req.activated_vehicle_ids_in_shift,
            req.planning_config,
            req.posted_activation_cost_paise_by_vehicle,
            enforce_homogeneous=False,
        )
    except ShiftFleetPolicyConflictError as exc:
        diags.append(DiagnosticEntry(code="SHIFT_FLEET_POLICY_CONFLICT", message=str(exc)))
        return GatekeeperReport(
            False, ResultStatus.SHIFT_FLEET_POLICY_CONFLICT, None, diagnostics=tuple(diags)
        )
    except ValueError as exc:
        diags.append(DiagnosticEntry(code="VEHICLE_POOL_INVALID", message=str(exc)))
        return GatekeeperReport(False, ResultStatus.INVALID_CONFIG, None, diagnostics=tuple(diags))

    # Validate orders
    seen_oids: set[str] = set()
    active_orders: list[OrderSpec] = []
    for o in req.orders:
        if not o.id or o.id in seen_oids:
            diags.append(
                DiagnosticEntry(
                    code="DUPLICATE_OR_EMPTY_ORDER_ID",
                    message=f"Duplicate or empty order ID: {o.id!r}",
                    order_id=o.id,
                )
            )
            return GatekeeperReport(False, ResultStatus.INVALID_INPUT, None, diagnostics=tuple(diags))
        seen_oids.add(o.id)
        if not o.node_id:
            diags.append(
                DiagnosticEntry(
                    code="INVALID_ORDER_LOCATION",
                    message=f"Order {o.id} has empty node_id",
                    order_id=o.id,
                )
            )
            return GatekeeperReport(False, ResultStatus.INVALID_INPUT, None, diagnostics=tuple(diags))
        if o.demand_units <= 0 or o.service_seconds < 0:
            diags.append(
                DiagnosticEntry(
                    code="INVALID_ORDER_DEMAND_OR_SERVICE",
                    message=f"Order {o.id} requires demand > 0 and service_seconds >= 0",
                    order_id=o.id,
                )
            )
            return GatekeeperReport(False, ResultStatus.INVALID_INPUT, None, diagnostics=tuple(diags))
        if o.window_open_utc_s > o.window_close_utc_s:
            diags.append(
                DiagnosticEntry(
                    code="INVALID_TIME_WINDOW",
                    message=f"Order {o.id} window_open ({o.window_open_utc_s}) > window_close ({o.window_close_utc_s})",
                    order_id=o.id,
                )
            )
            return GatekeeperReport(False, ResultStatus.INVALID_INPUT, None, diagnostics=tuple(diags))
        if o.custom_sla_rate_paise_per_min is not None and o.custom_sla_rate_paise_per_min.numerator < 0:
            diags.append(
                DiagnosticEntry(
                    code="NEGATIVE_CUSTOM_SLA_RATE",
                    message=f"Order {o.id} has negative custom SLA rate",
                    order_id=o.id,
                )
            )
            return GatekeeperReport(False, ResultStatus.INVALID_CONFIG, None, diagnostics=tuple(diags))
        if o.id not in req.completed_order_ids:
            active_orders.append(o)

    # If all orders are already completed, valid empty remaining work
    if not active_orders:
        return GatekeeperReport(True, None, pool, diagnostics=tuple(diags))

    if pool.max_routes_allowed == 0 and not req.route_starts_by_vehicle:
        diags.append(
            DiagnosticEntry(
                code="NO_AVAILABLE_VEHICLES",
                message="No available vehicles to serve remaining orders",
            )
        )
        if cfg.planning_mode == PlanningMode.COMPLETE:
            return GatekeeperReport(False, ResultStatus.PROVEN_INFEASIBLE, pool, diagnostics=tuple(diags))
        return GatekeeperReport(True, None, pool, diagnostics=tuple(diags))

    max_vehicle_q = max((v.capacity_units for v in pool.sorted_vehicles), default=0)
    proven_unserviceable: dict[str, tuple[UnservedReason, str]] = {}

    # Sound proof 1: Individual order capacity d_i > max_vehicle_q
    for o in active_orders:
        if o.demand_units > max_vehicle_q:
            msg = f"Order {o.id} weight ({o.demand_units} kg) exceeds maximum single vehicle capacity ({max_vehicle_q} kg)"
            proven_unserviceable[o.id] = (UnservedReason.PROVEN_UNSERVICEABLE_CAPACITY, msg)
            diags.append(
                DiagnosticEntry(
                    code="PROVEN_UNSERVICEABLE_CAPACITY",
                    message=msg,
                    order_id=o.id,
                )
            )

    # Sound proof 2: Singleton reachability & hard-window feasibility over earliest departure in T (when FIFO holds)
    if oracle is not None and not req.route_starts_by_vehicle:
        earliest_dep = min(cfg.departure_set_utc_s)
        oracle_id = oracle.identity()
        for o in active_orders:
            if o.id in proven_unserviceable:
                continue
            arr_res = oracle.arrival(req.depot.node_id, o.node_id, earliest_dep)
            if arr_res.status in (OracleStatus.PATH_UNAVAILABLE, OracleStatus.ROAD_CLOSED):
                msg = f"No valid road path from depot to order {o.id} ({arr_res.status.value})"
                proven_unserviceable[o.id] = (UnservedReason.PROVEN_UNSERVICEABLE_UNREACHABLE, msg)
                diags.append(
                    DiagnosticEntry(
                        code="PROVEN_UNSERVICEABLE_UNREACHABLE",
                        message=msg,
                        order_id=o.id,
                    )
                )
                continue
            if arr_res.status in (OracleStatus.ORACLE_FAILURE, OracleStatus.TRAFFIC_DATA_INSUFFICIENT):
                diags.append(
                    DiagnosticEntry(
                        code=arr_res.status.value,
                        message=f"Road oracle error checking order {o.id}: {arr_res.message}",
                        order_id=o.id,
                    )
                )
                return GatekeeperReport(
                    False,
                    ResultStatus.DATA_INSUFFICIENT
                    if arr_res.status == OracleStatus.TRAFFIC_DATA_INSUFFICIENT
                    else ResultStatus.ROAD_ORACLE_FAILURE,
                    pool,
                    diagnostics=tuple(diags),
                )
            if arr_res.ok and oracle_id.fifo_validated and arr_res.arrival_utc_s is not None:
                earliest_start = max(arr_res.arrival_utc_s, o.window_open_utc_s)
                earliest_completion = earliest_start + o.service_seconds
                if o.window_type == WindowType.HARD and earliest_completion > o.window_close_utc_s:
                    msg = (
                        f"Order {o.id} earliest possible delivery completion exceeds its strict window deadline"
                    )
                    proven_unserviceable[o.id] = (UnservedReason.PROVEN_UNSERVICEABLE_HARD_WINDOW, msg)
                    diags.append(
                        DiagnosticEntry(
                            code="PROVEN_UNSERVICEABLE_HARD_WINDOW",
                            message=msg,
                            order_id=o.id,
                        )
                    )
                    continue
                if req.depot.return_enabled:
                    ret_res = oracle.arrival(o.node_id, req.depot.node_id, earliest_completion)
                    if ret_res.status in (OracleStatus.PATH_UNAVAILABLE, OracleStatus.ROAD_CLOSED):
                        msg = f"No valid return road path from order {o.id} to depot"
                        proven_unserviceable[o.id] = (UnservedReason.PROVEN_UNSERVICEABLE_UNREACHABLE, msg)
                        diags.append(
                            DiagnosticEntry(
                                code="PROVEN_UNSERVICEABLE_UNREACHABLE",
                                message=msg,
                                order_id=o.id,
                            )
                        )
                        continue
                    if (
                        ret_res.ok
                        and req.depot.return_deadline_utc_s is not None
                        and ret_res.arrival_utc_s is not None
                        and ret_res.arrival_utc_s > req.depot.return_deadline_utc_s
                    ):
                        msg = (
                            f"Order {o.id} return arrival to depot exceeds depot closing deadline"
                        )
                        proven_unserviceable[o.id] = (
                            UnservedReason.PROVEN_UNSERVICEABLE_HARD_WINDOW,
                            msg,
                        )
                        diags.append(
                            DiagnosticEntry(
                                code="PROVEN_UNSERVICEABLE_RETURN_DEADLINE",
                                message=msg,
                                order_id=o.id,
                            )
                        )

    all_demands = [o.demand_units for o in active_orders]
    serviceable_demands = [o.demand_units for o in active_orders if o.id not in proven_unserviceable]
    pool_caps = [v.capacity_units for v in pool.sorted_vehicles]
    lb_all = compute_fleet_capacity_lower_bound(all_demands, pool_caps)
    lb_srv = compute_fleet_capacity_lower_bound(serviceable_demands, pool_caps)

    diags.append(
        DiagnosticEntry(
            code="CAPACITY_LOWER_BOUNDS",
            message=f"Minimum vehicles needed by cargo weight: {lb_all} vehicle(s) (allowed fleet limit: {pool.max_routes_allowed} vehicle(s))",
            detail={"lb_all": lb_all, "lb_serviceable": lb_srv, "max_routes_allowed": pool.max_routes_allowed},
        )
    )

    # Check if selected vehicle count capacity is less than total order weight
    allowed_vehicles_slice = pool.sorted_vehicles[: pool.max_routes_allowed]
    allowed_total_cap = sum(v.capacity_units for v in allowed_vehicles_slice)
    total_order_weight = sum(all_demands)

    if cfg.planning_mode == PlanningMode.COMPLETE:
        if proven_unserviceable:
            return GatekeeperReport(
                True,
                ResultStatus.PROVEN_INFEASIBLE,
                pool,
                proven_unserviceable_orders=proven_unserviceable,
                capacity_lower_bound_all_orders=lb_all,
                capacity_lower_bound_serviceable_orders=lb_srv,
                diagnostics=tuple(diags),
            )
        if not req.route_starts_by_vehicle and (lb_all > pool.max_routes_allowed or total_order_weight > allowed_total_cap):
            diags.append(
                DiagnosticEntry(
                    code="PROVEN_INFEASIBLE_AGGREGATE_CAPACITY",
                    message=(
                        f"Complete Plan requires at least {lb_all} vehicles for {total_order_weight} kg total cargo, "
                        f"but only {pool.max_routes_allowed} vehicle(s) ({allowed_total_cap} kg capacity) are selected."
                    ),
                )
            )
            return GatekeeperReport(
                True,
                ResultStatus.PROVEN_INFEASIBLE,
                pool,
                proven_unserviceable_orders=proven_unserviceable,
                capacity_lower_bound_all_orders=lb_all,
                capacity_lower_bound_serviceable_orders=lb_srv,
                diagnostics=tuple(diags),
            )

    return GatekeeperReport(
        True,
        None,
        pool,
        proven_unserviceable_orders=proven_unserviceable,
        capacity_lower_bound_all_orders=lb_all,
        capacity_lower_bound_serviceable_orders=lb_srv,
        diagnostics=tuple(diags),
    )
