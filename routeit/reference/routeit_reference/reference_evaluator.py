"""Independent Reference Evaluator for Differential Testing (Q-HGALS 5.0 §6.3, Phase 5 §11.6, AC-10).

IMPORTANT: This module MUST NOT import `routeit_engine.evaluator` or `routeit_engine.money`.
It implements a completely independent calculation path using Python's `fractions.Fraction`
and `round(Fraction)` (which implements exact round-half-to-even in Python 3).
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Sequence

from routeit_engine.contracts.types import (
    PlanningMode,
    PriorityTier,
    SolveRequest,
    WindowType,
)
from routeit_engine.oracle.protocol import RoadOracle


@dataclass(frozen=True)
class ReferenceRouteResult:
    vehicle_id: str
    departure_utc_s: int
    stop_arrivals: tuple[int, ...]
    stop_waits: tuple[int, ...]
    stop_starts: tuple[int, ...]
    stop_completions: tuple[int, ...]
    stop_lateness: tuple[int, ...]
    stop_sla_paise: tuple[int, ...]
    total_distance_m: int
    paid_duration_s: int
    idle_waiting_s: int
    distance_cost_paise: int
    time_cost_paise: int
    sla_cost_paise: int
    incremental_activation_paise: int
    feasible: bool


@dataclass(frozen=True)
class ReferencePlanResult:
    routes: tuple[ReferenceRouteResult, ...]
    coverage_vector: tuple[int, int, int]
    total_distance_m: int
    total_paid_seconds: int
    idle_waiting_seconds: int
    distance_cost_paise: int
    time_cost_paise: int
    sla_cost_paise: int
    operating_cost_paise: int
    incremental_activation_cost_paise: int
    incremental_decision_cost_paise: int
    m_routes_used: int
    m_new_activated: int
    m_shift_activated_after: int
    hard_feasible: bool
    complete_feasible: bool


def _fraction_round_even(val: Fraction) -> int:
    """Use Python 3 built-in round(Fraction) which implements exact round-half-to-even."""
    if val < 0:
        raise ValueError("Negative monetary fraction not allowed")
    return int(round(val))


def reference_evaluate_plan(
    req: SolveRequest,
    route_specs: Sequence[tuple[str, int, Sequence[str]]],
    oracle: RoadOracle,
) -> ReferencePlanResult:
    """Evaluate a plan via an independent Fraction-based code path."""
    orders_map = {o.id: o for o in req.orders if o.id not in req.completed_order_ids}
    vehicles_map = {v.id: v for v in req.vehicles}

    r_d = Fraction(
        req.cost_rates.distance_rate_paise_per_km.numerator,
        req.cost_rates.distance_rate_paise_per_km.denominator,
    )
    r_t = Fraction(
        req.cost_rates.time_rate_paise_per_hour.numerator,
        req.cost_rates.time_rate_paise_per_hour.denominator,
    )

    ref_routes: list[ReferenceRouteResult] = []
    all_served: list[str] = []
    plan_feasible = True

    for vid, dep_s, oids in sorted(route_specs, key=lambda item: item[0]):
        if not oids:
            continue
        veh = vehicles_map[vid]
        r_feasible = veh.available
        start_override = req.route_starts_by_vehicle.get(vid)
        if start_override is None:
            curr_node = req.depot.node_id
            curr_time = dep_s
            if dep_s not in req.planning_config.departure_set_utc_s or dep_s < req.depot.opening_utc_s:
                r_feasible = False
        else:
            curr_node = start_override.node_id
            curr_time = start_override.start_time_utc_s
            if start_override.locked_first_stop_order_id is not None:
                if oids[0] != start_override.locked_first_stop_order_id:
                    r_feasible = False

        start_time = curr_time
        dem_sum = sum(orders_map[oid].demand_units for oid in oids if oid in orders_map)
        if start_override is not None and start_override.initial_load_units is not None:
            init_load = start_override.initial_load_units
        else:
            init_load = dem_sum
        if dem_sum > init_load or init_load > veh.capacity_units:
            r_feasible = False

        arrivals: list[int] = []
        waits: list[int] = []
        starts: list[int] = []
        completions: list[int] = []
        latenesses: list[int] = []
        slas: list[int] = []
        dist_m = 0

        for oid in oids:
            if oid not in orders_map:
                r_feasible = False
                break
            order = orders_map[oid]
            leg = oracle.arrival(curr_node, order.node_id, curr_time, veh.vehicle_profile)
            if not leg.ok or leg.arrival_utc_s is None or leg.distance_m is None:
                r_feasible = False
                break
            a_i = leg.arrival_utc_s
            b_i = max(a_i, order.window_open_utc_s)
            w_i = max(0, order.window_open_utc_s - a_i)
            d_i = b_i + order.service_seconds
            l_i = max(0, d_i - order.window_close_utc_s)

            if order.window_type == WindowType.HARD and l_i > 0:
                r_feasible = False

            if order.window_type == WindowType.SOFT and l_i > 0:
                p_rate = req.cost_rates.sla_rate_for(order)
                p_frac = Fraction(p_rate.numerator, p_rate.denominator)
                sla_p = _fraction_round_even(Fraction(l_i, 60) * p_frac)
            else:
                sla_p = 0

            arrivals.append(a_i)
            waits.append(w_i)
            starts.append(b_i)
            completions.append(d_i)
            latenesses.append(l_i)
            slas.append(sla_p)
            dist_m += leg.distance_m
            curr_node = order.node_id
            curr_time = d_i
            all_served.append(oid)

        ret_enabled = veh.return_to_depot if veh.return_to_depot is not None else req.depot.return_enabled
        ret_deadline = (
            veh.return_deadline_utc_s
            if veh.return_deadline_utc_s is not None
            else (req.depot.return_deadline_utc_s or req.depot.closing_utc_s)
        )
        if ret_enabled and len(arrivals) == len(oids):
            ret_leg = oracle.arrival(curr_node, req.depot.node_id, curr_time, veh.vehicle_profile)
            if not ret_leg.ok or ret_leg.arrival_utc_s is None or ret_leg.distance_m is None:
                r_feasible = False
            else:
                dist_m += ret_leg.distance_m
                curr_time = ret_leg.arrival_utc_s
                if ret_deadline is not None and curr_time > ret_deadline:
                    r_feasible = False

        paid_s = curr_time - start_time if arrivals else 0
        idle_s = sum(waits)
        dist_cost = _fraction_round_even(Fraction(dist_m, 1000) * r_d)
        time_cost = _fraction_round_even(Fraction(paid_s, 3600) * r_t)
        sla_cost = sum(slas)
        inc_act = 0 if vid in req.activated_vehicle_ids_in_shift else veh.activation_cost_paise

        if not r_feasible:
            plan_feasible = False

        ref_routes.append(
            ReferenceRouteResult(
                vehicle_id=vid,
                departure_utc_s=start_time,
                stop_arrivals=tuple(arrivals),
                stop_waits=tuple(waits),
                stop_starts=tuple(starts),
                stop_completions=tuple(completions),
                stop_lateness=tuple(latenesses),
                stop_sla_paise=tuple(slas),
                total_distance_m=dist_m,
                paid_duration_s=paid_s,
                idle_waiting_s=idle_s,
                distance_cost_paise=dist_cost,
                time_cost_paise=time_cost,
                sla_cost_paise=sla_cost,
                incremental_activation_paise=inc_act,
                feasible=r_feasible,
            )
        )

    if len(set(all_served)) != len(all_served):
        plan_feasible = False

    served_set = set(all_served)
    n_c = sum(1 for oid in served_set if orders_map[oid].priority == PriorityTier.CRITICAL)
    n_s = sum(1 for oid in served_set if orders_map[oid].priority == PriorityTier.STANDARD)
    n_f = sum(1 for oid in served_set if orders_map[oid].priority == PriorityTier.FLEXIBLE)

    complete_ok = plan_feasible and (len(served_set) == len(orders_map))
    if req.planning_config.planning_mode == PlanningMode.COMPLETE and not complete_ok:
        plan_feasible = False

    selected_vids = {r.vehicle_id for r in ref_routes}
    new_vids = selected_vids - set(req.activated_vehicle_ids_in_shift)
    shift_after = set(req.activated_vehicle_ids_in_shift) | selected_vids

    d_tot = sum(r.distance_cost_paise for r in ref_routes)
    t_tot = sum(r.time_cost_paise for r in ref_routes)
    s_tot = sum(r.sla_cost_paise for r in ref_routes)
    op_tot = d_tot + t_tot + s_tot
    act_tot = sum(r.incremental_activation_paise for r in ref_routes)

    return ReferencePlanResult(
        routes=tuple(ref_routes),
        coverage_vector=(n_c, n_s, n_f),
        total_distance_m=sum(r.total_distance_m for r in ref_routes),
        total_paid_seconds=sum(r.paid_duration_s for r in ref_routes),
        idle_waiting_seconds=sum(r.idle_waiting_s for r in ref_routes),
        distance_cost_paise=d_tot,
        time_cost_paise=t_tot,
        sla_cost_paise=s_tot,
        operating_cost_paise=op_tot,
        incremental_activation_cost_paise=act_tot,
        incremental_decision_cost_paise=op_tot + act_tot,
        m_routes_used=len(ref_routes),
        m_new_activated=len(new_vids),
        m_shift_activated_after=len(shift_after),
        hard_feasible=plan_feasible,
        complete_feasible=complete_ok,
    )
