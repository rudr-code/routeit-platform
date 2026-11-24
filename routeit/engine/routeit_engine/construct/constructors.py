"""Deterministic and Seeded Constructive Heuristics (Q-HGALS 5.0 §6.8 & Phase 5 §7.5).

Implements:
1. Spatial Clarke-Wright Parallel Savings Heuristic (`_clarke_wright_savings_construct`)
2. Spatial Polar-Angle & Sector Sweep Tours (`generate_initial_giant_tours`)
3. Cost-Greedy Insertion (`construct_cost_greedy`)
4. Idle-Aware Earliest-Deadline Insertion (`construct_idle_aware`)
5. Regret-2 Insertion (`construct_regret2`)
6. Seeded Randomized Priority-Aware Insertion (`construct_randomized_feasible`)
"""

from __future__ import annotations

import math
import random
from typing import Sequence

from routeit_engine.context.evaluation_context import EvaluationContext
from routeit_engine.contracts.types import (
    EvaluatedPlan,
    PlanningMode,
    PriorityTier,
    TelemetryCounters,
    UnservedReason,
)
from routeit_engine.evaluator.canonical import evaluate_plan, evaluate_route
from routeit_engine.oracle.protocol import RoadOracle
from routeit_engine.policy.comparators import PlanComparator
from routeit_engine.policy.vehicle_assignment import (
    SortedVehiclePool,
    assign_vehicles_to_routes,
)
from routeit_engine.split.decoder import decode_giant_tour_split


def _priority_rank(tier: PriorityTier) -> int:
    if tier == PriorityTier.CRITICAL:
        return 0
    if tier == PriorityTier.STANDARD:
        return 1
    return 2


def generate_initial_giant_tours(ctx: EvaluationContext, oracle: RoadOracle, seed: int = 42) -> list[list[str]]:
    """Generate diverse spatial, polar-sweep, nearest-neighbor, and priority-ordered giant tours for Split decoding."""
    orders = list(ctx.orders_by_id.values())
    if not orders:
        return [[]]

    dep_node = ctx.request.depot.node_id
    dep_time = min(ctx.request.planning_config.departure_set_utc_s)

    def _node_lon_lat(node_id: str, fallback_lon: float | None, fallback_lat: float | None) -> tuple[float, float]:
        if fallback_lon is not None and fallback_lat is not None:
            return (float(fallback_lon), float(fallback_lat))
        geom = oracle.path(node_id, node_id, dep_time)
        if geom.coordinates_lon_lat:
            return geom.coordinates_lon_lat[0]
        return (0.0, 0.0)

    dep_lon, dep_lat = _node_lon_lat(dep_node, ctx.request.depot.lon, ctx.request.depot.lat)

    # Tour 1: Pure Geographic Polar-Angle Sweep around Depot (Counter-Clockwise from East)
    def polar_angle(o) -> float:
        o_lon, o_lat = _node_lon_lat(o.node_id, o.lon, o.lat)
        return math.atan2(o_lat - dep_lat, o_lon - dep_lon)

    t_polar_0 = [o.id for o in sorted(orders, key=lambda o: (round(polar_angle(o), 6), o.id))]

    # Tour 2: Rotated Polar-Angle Sweep (starting from North-West +135 deg so northern/western clusters are never split at +-pi)
    def rotated_angle(o, offset_rad: float) -> float:
        ang = polar_angle(o) + offset_rad
        while ang <= -math.pi:
            ang += 2.0 * math.pi
        while ang > math.pi:
            ang -= 2.0 * math.pi
        return ang

    t_polar_nw = [o.id for o in sorted(orders, key=lambda o: (round(rotated_angle(o, 0.75 * math.pi), 6), o.id))]
    t_polar_ne = [o.id for o in sorted(orders, key=lambda o: (round(rotated_angle(o, 0.25 * math.pi), 6), o.id))]

    # Tour 3: Pure Spatial Road-Distance Nearest-Neighbor Sweep from Depot (no artificial priority segregation)
    rem_spatial = {o.id: o for o in orders}
    curr_node = dep_node
    curr_t = dep_time
    t_nn_spatial: list[str] = []
    while rem_spatial:
        def spatial_nn_key(oid: str) -> tuple[int, int, str]:
            o = rem_spatial[oid]
            arr = oracle.arrival(curr_node, o.node_id, curr_t)
            dist = arr.distance_m if (arr.ok and arr.distance_m is not None) else 10**9
            return (dist, o.window_close_utc_s, o.id)

        best_oid = min(rem_spatial, key=spatial_nn_key)
        t_nn_spatial.append(best_oid)
        o_chosen = rem_spatial.pop(best_oid)
        arr = oracle.arrival(curr_node, o_chosen.node_id, curr_t)
        curr_t = max((arr.arrival_utc_s if arr.ok and arr.arrival_utc_s else curr_t), o_chosen.window_open_utc_s) + o_chosen.service_seconds
        curr_node = o_chosen.node_id

    # Tour 4: Priority tier -> earliest deadline -> earliest window open -> order ID (critical for Partial Mode)
    t_prio = [
        o.id
        for o in sorted(
            orders,
            key=lambda o: (_priority_rank(o.priority), o.window_close_utc_s, o.window_open_utc_s, o.id),
        )
    ]

    # Tour 5: Earliest window open -> earliest deadline -> spatial proximity (Idle-aware ordering)
    t_idle = [
        o.id
        for o in sorted(
            orders,
            key=lambda o: (o.window_open_utc_s, o.window_close_utc_s, _priority_rank(o.priority), o.id),
        )
    ]

    # Tour 6: Seeded randomized priority-stratified tour
    rng = random.Random(seed ^ 0xA5A5_5A5A)
    by_tier: dict[int, list[str]] = {0: [], 1: [], 2: []}
    for o in sorted(orders, key=lambda x: x.id):
        by_tier[_priority_rank(o.priority)].append(o.id)
    t_rand: list[str] = []
    for tier_idx in (0, 1, 2):
        tier_list = list(by_tier[tier_idx])
        rng.shuffle(tier_list)
        t_rand.extend(tier_list)

    unique_tours: list[list[str]] = []
    for t in (t_polar_0, t_polar_nw, t_polar_ne, t_nn_spatial, t_prio, t_idle, t_rand):
        if t not in unique_tours:
            unique_tours.append(t)
    return unique_tours


def _clarke_wright_savings_construct(
    ctx: EvaluationContext,
    oracle: RoadOracle,
    pool: SortedVehiclePool,
    unserved_reasons_override: dict[str, tuple[UnservedReason, str]] | None,
    telemetry: TelemetryCounters | None = None,
) -> EvaluatedPlan | None:
    """Spatial Clarke-Wright Parallel Savings heuristic producing compact, non-overlapping geographic clusters."""
    orders = [
        o
        for o in sorted(ctx.orders_by_id.values(), key=lambda x: x.id)
        if not unserved_reasons_override or o.id not in unserved_reasons_override
    ]
    if not orders or not pool.sorted_vehicles:
        return None

    dep_node = ctx.request.depot.node_id
    dep_s = min(ctx.request.planning_config.departure_set_utc_s)
    max_cap = max(v.capacity_units for v in pool.sorted_vehicles)
    rep_veh = pool.sorted_vehicles[0]

    # Start with each serviceable order in its own singleton route
    routes: list[list[str]] = []
    for o in orders:
        if o.demand_units <= max_cap:
            ev = evaluate_route(
                vehicle=rep_veh,
                order_ids=[o.id],
                departure_utc_s=dep_s,
                ctx=ctx,
                oracle=oracle,
                telemetry=telemetry,
            )
            if ev.feasible:
                routes.append([o.id])

    if not routes:
        return None

    # Compute Clarke-Wright road distance savings S(i, j) = d(Depot, i) + d(j, Depot) - d(i, j)
    savings_list: list[tuple[int, str, str]] = []
    for o1 in orders:
        d_dep_i = oracle.arrival(dep_node, o1.node_id, dep_s).distance_m or 0
        for o2 in orders:
            if o1.id == o2.id:
                continue
            d_j_dep = oracle.arrival(o2.node_id, dep_node, dep_s).distance_m or 0
            d_i_j = oracle.arrival(o1.node_id, o2.node_id, dep_s).distance_m or 10**8
            sav = d_dep_i + d_j_dep - d_i_j
            savings_list.append((sav, o1.id, o2.id))

    # Sort savings descending
    savings_list.sort(key=lambda item: (-item[0], item[1], item[2]))

    for _, oid_i, oid_j in savings_list:
        # Find route ending with oid_i and distinct route starting with oid_j
        r_i_idx: int | None = None
        r_j_idx: int | None = None
        for idx, r in enumerate(routes):
            if r[-1] == oid_i:
                r_i_idx = idx
            if r[0] == oid_j:
                r_j_idx = idx
        if r_i_idx is None or r_j_idx is None or r_i_idx == r_j_idx:
            continue

        merged_oids = routes[r_i_idx] + routes[r_j_idx]
        merged_load = sum(ctx.orders_by_id[oid].demand_units for oid in merged_oids)
        if merged_load > max_cap:
            continue

        ev_merged = evaluate_route(
            vehicle=rep_veh,
            order_ids=merged_oids,
            departure_utc_s=dep_s,
            ctx=ctx,
            oracle=oracle,
            telemetry=telemetry,
        )
        if ev_merged.feasible:
            routes[r_i_idx] = merged_oids
            routes.pop(r_j_idx)

    # If more routes remain than pool.max_routes_allowed, try merging smallest routes or keep top-priority routes in Partial Mode
    while len(routes) > pool.max_routes_allowed:
        merged_any = False
        for i in range(len(routes)):
            for j in range(len(routes)):
                if i == j:
                    continue
                cand_oids = routes[i] + routes[j]
                if sum(ctx.orders_by_id[oid].demand_units for oid in cand_oids) <= max_cap:
                    ev_c = evaluate_route(
                        vehicle=rep_veh,
                        order_ids=cand_oids,
                        departure_utc_s=dep_s,
                        ctx=ctx,
                        oracle=oracle,
                        telemetry=telemetry,
                    )
                    if ev_c.feasible:
                        routes[i] = cand_oids
                        routes.pop(j)
                        merged_any = True
                        break
            if merged_any:
                break
        if not merged_any:
            if ctx.request.planning_config.planning_mode == PlanningMode.PARTIAL:
                # Keep routes with highest priority coverage, then highest load
                routes.sort(
                    key=lambda r: (
                        -sum(1 for oid in r if ctx.orders_by_id[oid].priority == PriorityTier.CRITICAL),
                        -sum(1 for oid in r if ctx.orders_by_id[oid].priority == PriorityTier.STANDARD),
                        -sum(1 for oid in r if ctx.orders_by_id[oid].priority == PriorityTier.FLEXIBLE),
                    )
                )
                routes = routes[: pool.max_routes_allowed]
            else:
                return None

    nonempty_descriptors = [(dep_s, tuple(r)) for r in routes if r]
    if not pool.is_route_count_admissible(len(nonempty_descriptors), is_terminal=True):
        return None
    assign_res = assign_vehicles_to_routes(nonempty_descriptors, pool)
    route_specs = [
        (assign_res.vehicle_id_by_route_index[idx], desc[0], desc[1])
        for idx, desc in enumerate(nonempty_descriptors)
    ]
    return evaluate_plan(
        route_specs=route_specs,
        ctx=ctx,
        oracle=oracle,
        unserved_reasons_override=unserved_reasons_override,
        telemetry=telemetry,
    )


def _greedy_insertion_construct(
    ctx: EvaluationContext,
    oracle: RoadOracle,
    pool: SortedVehiclePool,
    unserved_reasons_override: dict[str, tuple[UnservedReason, str]] | None,
    mode: str,
    seed: int = 42,
    telemetry: TelemetryCounters | None = None,
) -> EvaluatedPlan | None:
    """Direct multi-route insertion heuristic (Spatial-Greedy, Cost-Greedy, Idle-Aware, Regret-2, or Randomized)."""
    orders = [
        o
        for o in ctx.orders_by_id.values()
        if not unserved_reasons_override or o.id not in unserved_reasons_override
    ]
    if not orders or not pool.sorted_vehicles:
        return evaluate_plan(
            route_specs=(),
            ctx=ctx,
            oracle=oracle,
            unserved_reasons_override=unserved_reasons_override,
            telemetry=telemetry,
        )

    q_max = pool.max_routes_allowed
    dep_s = min(ctx.request.planning_config.departure_set_utc_s)
    dep_node = ctx.request.depot.node_id
    rng = random.Random(seed)
    is_partial = ctx.request.planning_config.planning_mode == PlanningMode.PARTIAL

    if mode == "spatial_farthest":
        # Farthest-from-depot first (prevents stranding distant peripheral customers at the end!)
        unassigned = sorted(
            orders,
            key=lambda o: (
                _priority_rank(o.priority) if is_partial else 0,
                -(oracle.arrival(dep_node, o.node_id, dep_s).distance_m or 0),
                o.window_close_utc_s,
                o.id,
            ),
        )
    elif mode == "spatial_deadline":
        # Pure deadline & demand ordering without artificial priority grouping in Complete Mode
        unassigned = sorted(
            orders,
            key=lambda o: (
                _priority_rank(o.priority) if is_partial else 0,
                o.window_close_utc_s,
                -o.demand_units,
                o.id,
            ),
        )
    elif mode == "idle_aware":
        unassigned = sorted(
            orders,
            key=lambda o: (_priority_rank(o.priority), o.window_open_utc_s, o.window_close_utc_s, o.id),
        )
    elif mode == "randomized":
        unassigned = sorted(orders, key=lambda o: o.id)
        rng.shuffle(unassigned)
        if is_partial:
            unassigned.sort(key=lambda o: _priority_rank(o.priority))
    else:
        unassigned = sorted(
            orders,
            key=lambda o: (_priority_rank(o.priority), o.window_close_utc_s, -o.demand_units, o.id),
        )

    routes: list[list[str]] = []
    route_costs: list[int] = []
    route_idles: list[int] = []

    if mode == "regret2":
        remaining_ids = [o.id for o in unassigned]
        while remaining_ids:
            if is_partial:
                top_tier = min(_priority_rank(ctx.orders_by_id[oid].priority) for oid in remaining_ids)
                tier_candidates = [
                    oid for oid in remaining_ids if _priority_rank(ctx.orders_by_id[oid].priority) == top_tier
                ]
            else:
                tier_candidates = list(remaining_ids)

            best_choice: tuple[tuple[int, int, str], str, int, int, int, int] | None = None
            for oid in tier_candidates:
                insertion_options: list[tuple[int, int, int, int, int]] = []
                for r_idx, r_list in enumerate(routes):
                    slot_veh = pool.sorted_vehicles[r_idx]
                    for pos in range(len(r_list) + 1):
                        trial = r_list[:pos] + [oid] + r_list[pos:]
                        ev = evaluate_route(
                            vehicle=slot_veh,
                            order_ids=trial,
                            departure_utc_s=dep_s,
                            ctx=ctx,
                            oracle=oracle,
                            telemetry=telemetry,
                        )
                        if ev.feasible:
                            delta_c = ev.route_operating_cost_paise - route_costs[r_idx]
                            insertion_options.append(
                                (delta_c, r_idx, pos, ev.route_operating_cost_paise, ev.idle_waiting_seconds)
                            )
                if len(routes) < q_max and pool.is_route_count_admissible(len(routes) + 1, is_terminal=False):
                    new_slot_veh = pool.sorted_vehicles[len(routes)]
                    ev_new = evaluate_route(
                        vehicle=new_slot_veh,
                        order_ids=[oid],
                        departure_utc_s=dep_s,
                        ctx=ctx,
                        oracle=oracle,
                        telemetry=telemetry,
                    )
                    if ev_new.feasible:
                        marg_act = pool.marginal_activation_cost(len(routes) + 1)
                        delta_c = ev_new.route_operating_cost_paise + marg_act
                        insertion_options.append(
                            (delta_c, len(routes), 0, ev_new.route_operating_cost_paise, ev_new.idle_waiting_seconds)
                        )
                if not insertion_options:
                    continue
                insertion_options.sort(key=lambda x: (x[0], x[1], x[2]))
                best_opt = insertion_options[0]
                second_cost = insertion_options[1][0] if len(insertion_options) > 1 else best_opt[0] + 10**7
                regret = second_cost - best_opt[0]
                rank_key = (-regret, best_opt[0], oid)
                if best_choice is None or rank_key < best_choice[0]:
                    best_choice = (rank_key, oid, best_opt[1], best_opt[2], best_opt[3], best_opt[4])

            if best_choice is None:
                for oid in tier_candidates:
                    remaining_ids.remove(oid)
                continue

            _, chosen_oid, r_idx, pos, new_c, new_i = best_choice
            remaining_ids.remove(chosen_oid)
            if r_idx == len(routes):
                routes.append([chosen_oid])
                route_costs.append(new_c)
                route_idles.append(new_i)
            else:
                routes[r_idx].insert(pos, chosen_oid)
                route_costs[r_idx] = new_c
                route_idles[r_idx] = new_i
    else:
        for order in unassigned:
            best_ins: tuple[tuple[int, int, int, int], int, int, int, int] | None = None
            for r_idx, r_list in enumerate(routes):
                slot_veh = pool.sorted_vehicles[r_idx]
                for pos in range(len(r_list) + 1):
                    trial = r_list[:pos] + [order.id] + r_list[pos:]
                    ev = evaluate_route(
                        vehicle=slot_veh,
                        order_ids=trial,
                        departure_utc_s=dep_s,
                        ctx=ctx,
                        oracle=oracle,
                        telemetry=telemetry,
                    )
                    if ev.feasible:
                        delta_c = ev.route_operating_cost_paise - route_costs[r_idx]
                        delta_i = ev.idle_waiting_seconds - route_idles[r_idx]
                        score = (
                            (delta_i, delta_c, r_idx, pos)
                            if mode == "idle_aware"
                            else (delta_c, delta_i, r_idx, pos)
                        )
                        if best_ins is None or score < best_ins[0]:
                            best_ins = (score, r_idx, pos, ev.route_operating_cost_paise, ev.idle_waiting_seconds)

            if len(routes) < q_max and pool.is_route_count_admissible(len(routes) + 1, is_terminal=False):
                new_slot_veh = pool.sorted_vehicles[len(routes)]
                ev_new = evaluate_route(
                    vehicle=new_slot_veh,
                    order_ids=[order.id],
                    departure_utc_s=dep_s,
                    ctx=ctx,
                    oracle=oracle,
                    telemetry=telemetry,
                )
                if ev_new.feasible:
                    marg_act = pool.marginal_activation_cost(len(routes) + 1)
                    delta_c = ev_new.route_operating_cost_paise + marg_act
                    delta_i = ev_new.idle_waiting_seconds
                    score = (
                        (delta_i, delta_c, len(routes), 0)
                        if mode == "idle_aware"
                        else (delta_c, delta_i, len(routes), 0)
                    )
                    if best_ins is None or score < best_ins[0]:
                        best_ins = (score, len(routes), 0, ev_new.route_operating_cost_paise, ev_new.idle_waiting_seconds)

            if best_ins is not None:
                _, r_idx, pos, new_c, new_i = best_ins
                if r_idx == len(routes):
                    routes.append([order.id])
                    route_costs.append(new_c)
                    route_idles.append(new_i)
                else:
                    routes[r_idx].insert(pos, order.id)
                    route_costs[r_idx] = new_c
                    route_idles[r_idx] = new_i

    nonempty_descriptors = [(dep_s, tuple(r)) for r in routes if r]
    if not pool.is_route_count_admissible(len(nonempty_descriptors), is_terminal=True):
        return None
    assign_res = assign_vehicles_to_routes(nonempty_descriptors, pool)
    route_specs = [
        (assign_res.vehicle_id_by_route_index[idx], desc[0], desc[1])
        for idx, desc in enumerate(nonempty_descriptors)
    ]
    return evaluate_plan(
        route_specs=route_specs,
        ctx=ctx,
        oracle=oracle,
        unserved_reasons_override=unserved_reasons_override,
        telemetry=telemetry,
    )


def run_all_constructors(
    *,
    ctx: EvaluationContext,
    oracle: RoadOracle,
    pool: SortedVehiclePool,
    comparator: PlanComparator,
    unserved_reasons_override: dict[str, tuple[UnservedReason, str]] | None = None,
    telemetry: TelemetryCounters | None = None,
) -> tuple[list[EvaluatedPlan], list[list[str]], bool]:
    """Run constructive heuristics (including Clarke-Wright Savings) + Split on spatial & priority giant tours (Stage S4)."""
    seed = ctx.request.planning_config.seed
    plans: list[EvaluatedPlan] = []
    any_truncated = False

    cw_plan = _clarke_wright_savings_construct(
        ctx=ctx,
        oracle=oracle,
        pool=pool,
        unserved_reasons_override=unserved_reasons_override,
        telemetry=telemetry,
    )
    if cw_plan is not None and cw_plan.hard_feasible:
        plans.append(cw_plan)

    for mode in ("spatial_farthest", "spatial_deadline", "cost_greedy", "idle_aware", "regret2", "randomized"):
        p = _greedy_insertion_construct(
            ctx=ctx,
            oracle=oracle,
            pool=pool,
            unserved_reasons_override=unserved_reasons_override,
            mode=mode,
            seed=seed,
            telemetry=telemetry,
        )
        if p is not None and p.hard_feasible:
            plans.append(p)

    initial_tours = generate_initial_giant_tours(ctx, oracle, seed=seed)
    for tour in initial_tours:
        sp_plan, trunc = decode_giant_tour_split(
            giant_tour_order_ids=tour,
            ctx=ctx,
            oracle=oracle,
            pool=pool,
            comparator=comparator,
            unserved_reasons_override=unserved_reasons_override,
            telemetry=telemetry,
        )
        any_truncated = any_truncated or trunc
        if sp_plan is not None and sp_plan.hard_feasible:
            plans.append(sp_plan)

    for p in list(plans):
        induced_tour = [s.order_id for r in p.routes for s in r.stops]
        for u in p.unserved_orders:
            if u.order_id not in induced_tour:
                induced_tour.append(u.order_id)
        if induced_tour and induced_tour not in initial_tours:
            initial_tours.append(induced_tour)

    return plans, initial_tours, any_truncated
