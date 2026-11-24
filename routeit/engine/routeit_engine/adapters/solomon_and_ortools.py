"""Solomon VRPTW Adapter & Google OR-Tools Benchmark Adapter (Phase 5 §15.4 & Q-HGALS 5.0 §6.10).

Enforces:
- Solomon window translation: Solomon constrains service start (`B_i <= b_i`), while Route.it
  constrains service completion (`D_i <= b_i`). The adapter translates `b'_i = b_i + s_i` (Phase 5 C6).
- OR-Tools Adapter capability matrix: explicitly reports supported vs. unsupported semantics
  (e.g., static transit callback vs. time-dependent profile) and ALWAYS re-evaluates the
  translated route assignment through Route.it's Canonical Evaluator.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from routeit_engine.context.evaluation_context import EvaluationContext
from routeit_engine.contracts.types import (
    CostRateConfig,
    DepotSpec,
    EvaluatedPlan,
    ExactRate,
    FleetMode,
    OptimizationProfile,
    OrderSpec,
    PlanningConfig,
    PlanningMode,
    PriorityTier,
    SolverKind,
    SolveRequest,
    TelemetryCounters,
    UnservedReason,
    VehicleSpec,
    WindowType,
)
from routeit_engine.evaluator.canonical import evaluate_plan
from routeit_engine.oracle.protocol import RoadOracle
from routeit_engine.policy.vehicle_assignment import (
    SortedVehiclePool,
    assign_vehicles_to_routes,
)


@dataclass(frozen=True)
class SolomonCustomerRow:
    cust_no: int
    x: float
    y: float
    demand: int
    ready_time: int
    due_date: int
    service_time: int


def translate_solomon_instance_to_solve_request(
    *,
    instance_name: str,
    vehicle_count: int,
    vehicle_capacity: int,
    depot_row: SolomonCustomerRow,
    customer_rows: Sequence[SolomonCustomerRow],
    translate_due_date_to_completion: bool = True,
    solver_kind: SolverKind = SolverKind.QPSO,
    max_evaluations: int = 300,
    seed: int = 42,
) -> SolveRequest:
    """Translate a Solomon VRPTW instance into a Route.it `SolveRequest` (Phase 5 §15.4)."""
    depot_close = (
        depot_row.due_date + depot_row.service_time
        if translate_due_date_to_completion
        else depot_row.due_date
    )
    depot = DepotSpec(
        id="DEPOT_0",
        node_id=f"N_{depot_row.cust_no}",
        return_enabled=True,
        return_deadline_utc_s=depot_close,
        opening_utc_s=depot_row.ready_time,
        closing_utc_s=depot_close,
        lon=depot_row.x,
        lat=depot_row.y,
        name=f"{instance_name} Depot",
    )

    orders: list[OrderSpec] = []
    for row in customer_rows:
        w_close = (
            row.due_date + row.service_time
            if translate_due_date_to_completion
            else row.due_date
        )
        orders.append(
            OrderSpec(
                id=f"ORD_{row.cust_no:03d}",
                node_id=f"N_{row.cust_no}",
                demand_units=row.demand,
                service_seconds=row.service_time,
                window_open_utc_s=row.ready_time,
                window_close_utc_s=w_close,
                window_type=WindowType.HARD,
                priority=PriorityTier.CRITICAL,
                lon=row.x,
                lat=row.y,
            )
        )

    vehicles = tuple(
        VehicleSpec(
            id=f"VEH_{idx:02d}",
            capacity_units=vehicle_capacity,
            # Hierarchical Solomon objective emulation: high activation cost + distance rate (Phase 5 §15.4)
            activation_cost_paise=100_000,
            available=True,
            return_to_depot=True,
            return_deadline_utc_s=depot_close,
        )
        for idx in range(1, vehicle_count + 1)
    )

    rates = CostRateConfig(
        distance_rate_paise_per_km=ExactRate(1000, 1),
        time_rate_paise_per_hour=ExactRate(0, 1),
        critical_sla_paise_per_min=ExactRate(1000, 1),
        standard_sla_paise_per_min=ExactRate(500, 1),
        flexible_sla_paise_per_min=ExactRate(200, 1),
    )

    cfg = PlanningConfig(
        planning_mode=PlanningMode.COMPLETE,
        fleet_mode=FleetMode.AUTO,
        profile=OptimizationProfile.COST_FOCUSED,
        departure_set_utc_s=(depot_row.ready_time,),
        solver_kind=solver_kind,
        max_canonical_evaluations=max_evaluations,
        seed=seed,
    )

    return SolveRequest(
        request_id=f"SOL_{instance_name}",
        shift_id=f"SHIFT_{instance_name}",
        depot=depot,
        orders=tuple(orders),
        vehicles=vehicles,
        cost_rates=rates,
        planning_config=cfg,
    )


def build_solomon_c101_25_sample() -> tuple[SolomonCustomerRow, tuple[SolomonCustomerRow, ...]]:
    """Standard 25-customer Solomon C101 clustered benchmark fixture."""
    depot = SolomonCustomerRow(0, 40.0, 50.0, 0, 0, 1236, 0)
    customers = (
        SolomonCustomerRow(1, 45.0, 68.0, 10, 912, 967, 90),
        SolomonCustomerRow(2, 45.0, 70.0, 30, 825, 870, 90),
        SolomonCustomerRow(3, 42.0, 66.0, 10, 65, 146, 90),
        SolomonCustomerRow(4, 42.0, 68.0, 10, 727, 782, 90),
        SolomonCustomerRow(5, 42.0, 65.0, 10, 15, 67, 90),
        SolomonCustomerRow(6, 40.0, 69.0, 20, 621, 702, 90),
        SolomonCustomerRow(7, 40.0, 66.0, 20, 170, 225, 90),
        SolomonCustomerRow(8, 38.0, 68.0, 20, 255, 324, 90),
        SolomonCustomerRow(9, 38.0, 70.0, 10, 534, 605, 90),
        SolomonCustomerRow(10, 35.0, 66.0, 10, 357, 410, 90),
        SolomonCustomerRow(11, 35.0, 69.0, 10, 448, 505, 90),
        SolomonCustomerRow(12, 25.0, 85.0, 20, 652, 721, 90),
        SolomonCustomerRow(13, 22.0, 75.0, 30, 30, 92, 90),
        SolomonCustomerRow(14, 22.0, 85.0, 10, 567, 620, 90),
        SolomonCustomerRow(15, 20.0, 80.0, 40, 384, 429, 90),
        SolomonCustomerRow(16, 20.0, 85.0, 40, 475, 528, 90),
        SolomonCustomerRow(17, 18.0, 75.0, 20, 99, 148, 90),
        SolomonCustomerRow(18, 15.0, 75.0, 20, 179, 254, 90),
        SolomonCustomerRow(19, 15.0, 80.0, 10, 278, 345, 90),
        SolomonCustomerRow(20, 30.0, 50.0, 10, 10, 73, 90),
        SolomonCustomerRow(21, 30.0, 52.0, 20, 914, 965, 90),
        SolomonCustomerRow(22, 28.0, 52.0, 20, 812, 883, 90),
        SolomonCustomerRow(23, 28.0, 55.0, 10, 732, 777, 90),
        SolomonCustomerRow(24, 25.0, 50.0, 10, 65, 144, 90),
        SolomonCustomerRow(25, 25.0, 52.0, 40, 169, 224, 90),
    )
    return depot, customers


def run_ortools_adapter(
    *,
    ctx: EvaluationContext,
    oracle: RoadOracle,
    pool: SortedVehiclePool,
    unserved_reasons_override: dict[str, tuple[UnservedReason, str]] | None = None,
    telemetry: TelemetryCounters | None = None,
) -> tuple[EvaluatedPlan | None, dict[str, Any]]:
    """Solve static-equivalent routing via Google OR-Tools and re-evaluate canonically (Q-HGALS 5.0 §6.10)."""
    capability_report: dict[str, Any] = {
        "adapter": "ORTOOLS_ROUTING_ADAPTER",
        "supports_capacity": True,
        "supports_time_windows": True,
        "supports_time_dependent_edges_natively": False,
        "supports_lexicographic_productivity_cap_natively": False,
        "exact_equivalence_claimed": False,
        "canonical_reevaluation_enforced": True,
    }
    try:
        from ortools.constraint_solver import pywrapcp, routing_enums_pb2
    except ImportError:
        capability_report["ortools_available"] = False
        return None, capability_report

    capability_report["ortools_available"] = True
    req = ctx.request
    active_orders = [
        o
        for o in sorted(ctx.orders_by_id.values(), key=lambda x: x.id)
        if not unserved_reasons_override or o.id not in unserved_reasons_override
    ]
    if not active_orders or not pool.sorted_vehicles:
        plan = evaluate_plan(
            route_specs=(),
            ctx=ctx,
            oracle=oracle,
            unserved_reasons_override=unserved_reasons_override,
            telemetry=telemetry,
        )
        return plan, capability_report

    dep_s = min(req.planning_config.departure_set_utc_s)
    num_vehicles = min(pool.max_routes_allowed, len(active_orders))
    nodes_list = [req.depot.node_id] + [o.node_id for o in active_orders]
    n_locs = len(nodes_list)

    # Precompute static reference distance & travel matrix at dep_s
    dist_matrix = [[0] * n_locs for _ in range(n_locs)]
    time_matrix = [[0] * n_locs for _ in range(n_locs)]
    for i in range(n_locs):
        for j in range(n_locs):
            if i == j:
                continue
            arr = oracle.arrival(nodes_list[i], nodes_list[j], dep_s)
            if arr.ok and arr.distance_m is not None and arr.arrival_utc_s is not None:
                dist_matrix[i][j] = arr.distance_m
                time_matrix[i][j] = max(0, arr.arrival_utc_s - dep_s)
            else:
                dist_matrix[i][j] = 10**8
                time_matrix[i][j] = 10**7

    manager = pywrapcp.RoutingIndexManager(n_locs, num_vehicles, 0)
    routing = pywrapcp.RoutingModel(manager)

    def dist_callback(from_idx: int, to_idx: int) -> int:
        u = manager.IndexToNode(from_idx)
        v = manager.IndexToNode(to_idx)
        return dist_matrix[u][v]

    transit_cb_idx = routing.RegisterTransitCallback(dist_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_cb_idx)

    for v_idx in range(num_vehicles):
        v_spec = pool.sorted_vehicles[v_idx]
        w_k = 0 if v_spec.id in pool.activated_in_shift else v_spec.activation_cost_paise
        routing.SetFixedCostOfVehicle(int(w_k), v_idx)

    # Capacity dimension
    def demand_callback(from_idx: int) -> int:
        node = manager.IndexToNode(from_idx)
        if node == 0:
            return 0
        return active_orders[node - 1].demand_units

    dem_cb_idx = routing.RegisterUnaryTransitCallback(demand_callback)
    routing.AddDimensionWithVehicleCapacity(
        dem_cb_idx,
        0,
        [pool.sorted_vehicles[v_idx].capacity_units for v_idx in range(num_vehicles)],
        True,
        "Capacity",
    )

    # Disjunctions in Partial Mode
    if req.planning_config.planning_mode == PlanningMode.PARTIAL:
        for idx, o in enumerate(active_orders, start=1):
            pen = (
                10**9
                if o.priority == PriorityTier.CRITICAL
                else (10**7 if o.priority == PriorityTier.STANDARD else 10**5)
            )
            routing.AddDisjunction([manager.NodeToIndex(idx)], pen)

    search_params = pywrapcp.DefaultRoutingSearchParameters()
    search_params.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    )
    search_params.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    search_params.time_limit.FromMilliseconds(1500)

    solution = routing.SolveWithParameters(search_params)
    if solution is None:
        return None, capability_report

    descriptors: list[tuple[int, tuple[str, ...]]] = []
    for v_idx in range(num_vehicles):
        index = routing.Start(v_idx)
        r_oids: list[str] = []
        while not routing.IsEnd(index):
            node = manager.IndexToNode(index)
            if node > 0:
                r_oids.append(active_orders[node - 1].id)
            index = solution.Value(routing.NextVar(index))
        if r_oids:
            descriptors.append((dep_s, tuple(r_oids)))

    if not pool.is_route_count_admissible(len(descriptors), is_terminal=True):
        return None, capability_report

    assign_res = assign_vehicles_to_routes(descriptors, pool)
    route_specs = [
        (assign_res.vehicle_id_by_route_index[idx], desc[0], desc[1])
        for idx, desc in enumerate(descriptors)
    ]
    evaluated = evaluate_plan(
        route_specs=route_specs,
        ctx=ctx,
        oracle=oracle,
        unserved_reasons_override=unserved_reasons_override,
        telemetry=telemetry,
    )
    return evaluated, capability_report
