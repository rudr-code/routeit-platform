"""Deterministic Local Search Refinement (Q-HGALS 5.0 §6.8 & Phase 5 §7.3).

Operators:
1. Within-route Relocate (1-point move) & Optimal Small-Route Ordering
2. Within-route Swap (2-point exchange)
3. Within-route 2-Opt (segment reversal)
4. Cross-route Relocate (inter-route customer transfer with intra-route best insertion/reordering)
5. Cross-route Swap (inter-route customer exchange with intra-route best reordering)
6. Cross-route 2-Opt* (tail exchange uncrossing overlapping routes)
7. Unserved Order Insertion (in Partial Mode)

Preserves locked stops (`is_locked`) and re-evaluates every accepted candidate through the
Canonical Evaluator and `PlanComparator`.
"""

from __future__ import annotations

from itertools import permutations
from typing import Sequence

from routeit_engine.context.evaluation_context import EvaluationContext
from routeit_engine.contracts.types import (
    EvaluatedPlan,
    OptimizationProfile,
    PlanningMode,
    TelemetryCounters,
    UnservedReason,
    VehicleSpec,
)
from routeit_engine.evaluator.canonical import evaluate_plan, evaluate_route
from routeit_engine.oracle.protocol import RoadOracle
from routeit_engine.policy.comparators import PlanComparator
from routeit_engine.policy.vehicle_assignment import (
    SortedVehiclePool,
    assign_vehicles_to_routes,
)


def _start_index_for_route(vehicle_id: str, ctx: EvaluationContext) -> int:
    """Return 1 if the first stop of `vehicle_id` is locked in replanning, else 0."""
    st = ctx.request.route_starts_by_vehicle.get(vehicle_id)
    if st is not None and st.locked_first_stop_order_id is not None:
        return 1
    return 0


def _build_plan_from_mutable_routes(
    routes_data: list[tuple[str, int, list[str]]],
    ctx: EvaluationContext,
    oracle: RoadOracle,
    pool: SortedVehiclePool,
    unserved_reasons_override: dict[str, tuple[UnservedReason, str]] | None,
    telemetry: TelemetryCounters | None,
) -> EvaluatedPlan | None:
    nonempty = [(vid, dep, list(stops)) for vid, dep, stops in routes_data if stops]
    if not ctx.request.route_starts_by_vehicle:
        descriptors = [(dep, tuple(stops)) for _, dep, stops in nonempty]
        if not pool.is_route_count_admissible(len(descriptors), is_terminal=True):
            return None
        assign_res = assign_vehicles_to_routes(descriptors, pool)
        specs: list[tuple[str, int, Sequence[str]]] = [
            (assign_res.vehicle_id_by_route_index[idx], desc[0], desc[1])
            for idx, desc in enumerate(descriptors)
        ]
    else:
        specs = [(vid, dep, tuple(stops)) for vid, dep, stops in nonempty]

    if telemetry is not None:
        telemetry.local_search_evaluations += 1
    return evaluate_plan(
        route_specs=specs,
        ctx=ctx,
        oracle=oracle,
        unserved_reasons_override=unserved_reasons_override,
        telemetry=telemetry,
    )


def improve_plan_local_search(
    plan: EvaluatedPlan,
    ctx: EvaluationContext,
    oracle: RoadOracle,
    pool: SortedVehiclePool,
    comparator: PlanComparator,
    *,
    max_evaluations: int = 120,
    unserved_reasons_override: dict[str, tuple[UnservedReason, str]] | None = None,
    telemetry: TelemetryCounters | None = None,
) -> EvaluatedPlan:
    """Apply deterministic local search across within-route and cross-route neighborhoods with fast route caching."""
    best = plan
    evals_used = 0
    profile = ctx.request.planning_config.profile

    # Per-route evaluation cache: (vid, dep_s, stops_tuple) -> (feasible, op_cost_paise, idle_s)
    route_cache: dict[tuple[str, int, tuple[str, ...]], tuple[bool, int, int]] = {}

    def eval_single_route_fast(vid: str, dep_s: int, stops_seq: Sequence[str]) -> tuple[bool, int, int]:
        if not stops_seq:
            return (True, 0, 0)
        st_tuple = tuple(stops_seq)
        key = (vid, dep_s, st_tuple)
        if key in route_cache:
            return route_cache[key]
        veh: VehicleSpec = ctx.vehicles_by_id.get(vid) or pool.sorted_vehicles[0]
        tot_d = sum(ctx.orders_by_id[oid].demand_units for oid in st_tuple if oid in ctx.orders_by_id)
        if tot_d > veh.capacity_units:
            route_cache[key] = (False, 10**15, 10**9)
            return route_cache[key]
        ev = evaluate_route(
            vehicle=veh,
            order_ids=st_tuple,
            departure_utc_s=dep_s,
            ctx=ctx,
            oracle=oracle,
            telemetry=telemetry,
        )
        res = (ev.feasible, ev.route_operating_cost_paise, ev.idle_waiting_seconds)
        route_cache[key] = res
        return res

    def optimize_stop_order_for_route(vid: str, dep_s: int, stops_list: list[str]) -> tuple[bool, list[str], int, int]:
        """Find optimal feasible stop sequence for a single route (exact for <= 4 unlocked stops, 2-opt for larger)."""
        if not stops_list:
            return (True, [], 0, 0)
        s_min = _start_index_for_route(vid, ctx)
        locked_prefix = stops_list[:s_min]
        unlocked = stops_list[s_min:]
        if len(unlocked) <= 1:
            feas, cost, idle = eval_single_route_fast(vid, dep_s, stops_list)
            return (feas, stops_list, cost, idle)

        best_seq: list[str] | None = None
        best_key: tuple[int, int] | None = None
        best_cost = 10**15
        best_idle = 10**9

        if len(unlocked) <= 4:
            for perm in permutations(unlocked):
                cand_seq = locked_prefix + list(perm)
                feas, c, idl = eval_single_route_fast(vid, dep_s, cand_seq)
                if not feas:
                    continue
                k = (idl, c) if profile == OptimizationProfile.DRIVER_PRODUCTIVITY else (c, idl)
                if best_key is None or k < best_key:
                    best_key = k
                    best_seq = cand_seq
                    best_cost = c
                    best_idle = idl
        else:
            # Check original and all 2-opt reversals
            candidates = [stops_list]
            for i in range(s_min, len(stops_list) - 1):
                for j in range(i + 1, len(stops_list)):
                    candidates.append(stops_list[:i] + list(reversed(stops_list[i : j + 1])) + stops_list[j + 1 :])
            for cand_seq in candidates:
                feas, c, idl = eval_single_route_fast(vid, dep_s, cand_seq)
                if not feas:
                    continue
                k = (idl, c) if profile == OptimizationProfile.DRIVER_PRODUCTIVITY else (c, idl)
                if best_key is None or k < best_key:
                    best_key = k
                    best_seq = cand_seq
                    best_cost = c
                    best_idle = idl

        if best_seq is None:
            return (False, stops_list, 10**15, 10**9)
        return (True, best_seq, best_cost, best_idle)

    while evals_used < max_evaluations:
        improved = False
        routes_data = [
            (r.vehicle_id, r.departure_utc_s, [s.order_id for s in r.stops])
            for r in best.routes
        ]

        # 0. In Partial Mode, try inserting any currently unserved serviceable order
        if ctx.request.planning_config.planning_mode == PlanningMode.PARTIAL and best.unserved_orders:
            for u_rec in best.unserved_orders:
                if unserved_reasons_override and u_rec.order_id in unserved_reasons_override:
                    continue
                for r_idx, (vid, dep, stops) in enumerate(routes_data):
                    if telemetry is not None:
                        telemetry.local_search_moves_considered += 1
                    feas, opt_stops, _, _ = optimize_stop_order_for_route(
                        vid, dep, stops + [u_rec.order_id]
                    )
                    if not feas or evals_used >= max_evaluations:
                        continue
                    trial_routes = [(v, d, list(st)) for v, d, st in routes_data]
                    trial_routes[r_idx] = (vid, dep, opt_stops)
                    cand = _build_plan_from_mutable_routes(
                        trial_routes, ctx, oracle, pool, unserved_reasons_override, telemetry
                    )
                    evals_used += 1
                    if cand is not None and comparator.is_better(cand, best):
                        best = cand
                        improved = True
                        break
                if improved or evals_used >= max_evaluations:
                    break
            if improved:
                continue

        # 1. Intra-route optimal ordering pass across all routes simultaneously
        any_intra_changed = False
        intra_routes = [(v, d, list(st)) for v, d, st in routes_data]
        for r_idx, (vid, dep, stops) in enumerate(routes_data):
            if telemetry is not None:
                telemetry.local_search_moves_considered += 1
            feas, opt_stops, _, _ = optimize_stop_order_for_route(vid, dep, stops)
            if feas and opt_stops != stops:
                intra_routes[r_idx] = (vid, dep, opt_stops)
                any_intra_changed = True
        if any_intra_changed and evals_used < max_evaluations:
            cand = _build_plan_from_mutable_routes(
                intra_routes, ctx, oracle, pool, unserved_reasons_override, telemetry
            )
            evals_used += 1
            if cand is not None and comparator.is_better(cand, best):
                best = cand
                continue

        # 2. Cross-route Relocate, Cross-route Swap (with optimal intra-route reordering), and 2-Opt*
        if len(routes_data) >= 2 and not ctx.request.route_starts_by_vehicle:
            curr_op_costs = [
                eval_single_route_fast(vid, dep, stops)[1] for vid, dep, stops in routes_data
            ]
            curr_idles = [
                eval_single_route_fast(vid, dep, stops)[2] for vid, dep, stops in routes_data
            ]

            for r1 in range(len(routes_data)):
                vid1, dep1, stops1 = routes_data[r1]
                s1_min = _start_index_for_route(vid1, ctx)
                for r2 in range(len(routes_data)):
                    if r1 == r2:
                        continue
                    vid2, dep2, stops2 = routes_data[r2]
                    s2_min = _start_index_for_route(vid2, ctx)
                    base_pair_cost = curr_op_costs[r1] + curr_op_costs[r2]
                    base_pair_idle = curr_idles[r1] + curr_idles[r2]

                    # 2a. Cross-route Relocate: move stops1[i] into stops2 with optimal intra-route ordering
                    for i in range(s1_min, len(stops1)):
                        if evals_used >= max_evaluations:
                            break
                        if telemetry is not None:
                            telemetry.local_search_moves_considered += 1
                        moved_oid = stops1[i]
                        rem_stops1 = stops1[:i] + stops1[i + 1 :]
                        new_stops2 = stops2 + [moved_oid]

                        feas1, opt1, c1, idl1 = optimize_stop_order_for_route(vid1, dep1, rem_stops1)
                        if not feas1:
                            continue
                        feas2, opt2, c2, idl2 = optimize_stop_order_for_route(vid2, dep2, new_stops2)
                        if not feas2:
                            continue

                        # Route-eliminate bonus if rem_stops1 becomes empty!
                        saves_route = len(opt1) == 0
                        if not saves_route and (c1 + c2 > base_pair_cost and idl1 + idl2 >= base_pair_idle):
                            continue

                        trial_routes = [(v, d, list(st)) for v, d, st in routes_data]
                        trial_routes[r1] = (vid1, dep1, opt1)
                        trial_routes[r2] = (vid2, dep2, opt2)
                        cand = _build_plan_from_mutable_routes(
                            trial_routes, ctx, oracle, pool, unserved_reasons_override, telemetry
                        )
                        evals_used += 1
                        if cand is not None and comparator.is_better(cand, best):
                            best = cand
                            improved = True
                            break
                    if improved or evals_used >= max_evaluations:
                        break

                    # 2b. Cross-route Swap (1-for-1 exchange with optimal intra-route ordering)
                    if r1 < r2:
                        for i in range(s1_min, len(stops1)):
                            for j in range(s2_min, len(stops2)):
                                if evals_used >= max_evaluations:
                                    break
                                if telemetry is not None:
                                    telemetry.local_search_moves_considered += 1
                                cand_s1 = stops1[:i] + [stops2[j]] + stops1[i + 1 :]
                                cand_s2 = stops2[:j] + [stops1[i]] + stops2[j + 1 :]

                                feas1, opt1, c1, idl1 = optimize_stop_order_for_route(vid1, dep1, cand_s1)
                                if not feas1:
                                    continue
                                feas2, opt2, c2, idl2 = optimize_stop_order_for_route(vid2, dep2, cand_s2)
                                if not feas2:
                                    continue

                                if c1 + c2 > base_pair_cost and idl1 + idl2 >= base_pair_idle:
                                    continue

                                trial_routes = [(v, d, list(st)) for v, d, st in routes_data]
                                trial_routes[r1] = (vid1, dep1, opt1)
                                trial_routes[r2] = (vid2, dep2, opt2)
                                cand = _build_plan_from_mutable_routes(
                                    trial_routes, ctx, oracle, pool, unserved_reasons_override, telemetry
                                )
                                evals_used += 1
                                if cand is not None and comparator.is_better(cand, best):
                                    best = cand
                                    improved = True
                                    break
                            if improved or evals_used >= max_evaluations:
                                break
                        if improved or evals_used >= max_evaluations:
                            break

                        # 2c. Cross-route 2-Opt* (tail exchange between route r1 and route r2)
                        for i in range(s1_min, len(stops1)):
                            for j in range(s2_min, len(stops2)):
                                if evals_used >= max_evaluations:
                                    break
                                if telemetry is not None:
                                    telemetry.local_search_moves_considered += 1
                                cand_s1 = stops1[:i] + stops2[j:]
                                cand_s2 = stops2[:j] + stops1[i:]
                                if not cand_s1 or not cand_s2:
                                    continue

                                feas1, opt1, c1, idl1 = optimize_stop_order_for_route(vid1, dep1, cand_s1)
                                if not feas1:
                                    continue
                                feas2, opt2, c2, idl2 = optimize_stop_order_for_route(vid2, dep2, cand_s2)
                                if not feas2:
                                    continue

                                if c1 + c2 > base_pair_cost and idl1 + idl2 >= base_pair_idle:
                                    continue

                                trial_routes = [(v, d, list(st)) for v, d, st in routes_data]
                                trial_routes[r1] = (vid1, dep1, opt1)
                                trial_routes[r2] = (vid2, dep2, opt2)
                                cand = _build_plan_from_mutable_routes(
                                    trial_routes, ctx, oracle, pool, unserved_reasons_override, telemetry
                                )
                                evals_used += 1
                                if cand is not None and comparator.is_better(cand, best):
                                    best = cand
                                    improved = True
                                    break
                            if improved or evals_used >= max_evaluations:
                                break
                        if improved or evals_used >= max_evaluations:
                            break
                if improved or evals_used >= max_evaluations:
                    break

        if not improved:
            break

    return best
