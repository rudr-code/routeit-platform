"""Traffic scenario incident overlays and world-truth execution simulator (Phase 5 §10.4, §12)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from routeit_engine.contracts.types import (
    EvaluatedPlan,
    OperationalSnapshot,
    SolveRequest,
    VehicleLiveState,
    VehicleOperationalState,
)
from routeit_engine.money.ledger import (
    compute_order_sla_cost_paise,
    compute_route_distance_cost_paise,
    compute_route_time_cost_paise,
)
from routeit_roads.oracles import TrafficScenarioSpec


@dataclass(frozen=True)
class TrafficIncidentEvent:
    incident_id: str
    occurred_at_utc_s: int
    affected_edge_ids: tuple[str, ...]
    speed_multiplier: float = 0.4
    is_closure: bool = False
    description: str = "Traffic congestion incident"


def apply_incident_to_scenario(
    base_scenario: TrafficScenarioSpec,
    incident: TrafficIncidentEvent,
) -> TrafficScenarioSpec:
    """Produce a new immutable TrafficScenarioSpec revision incorporating an incident."""
    new_closed = set(base_scenario.closed_edge_ids)
    new_mults = dict(base_scenario.edge_multipliers_override)

    for eid in incident.affected_edge_ids:
        if incident.is_closure:
            new_closed.add(eid)
        else:
            new_mults[eid] = new_mults.get(eid, 1.0) * max(0.05, incident.speed_multiplier)

    return TrafficScenarioSpec(
        scenario_id=f"{base_scenario.scenario_id}_r{base_scenario.revision + 1}",
        name=f"{base_scenario.name} (Rev {base_scenario.revision + 1}: {incident.description})",
        revision=base_scenario.revision + 1,
        horizon_start_utc_s=base_scenario.horizon_start_utc_s,
        horizon_end_utc_s=base_scenario.horizon_end_utc_s,
        grid_seconds=base_scenario.grid_seconds,
        intervals=base_scenario.intervals,
        edge_multipliers_override=new_mults,
        closed_edge_ids=frozenset(new_closed),
        allow_boundary_clamp=base_scenario.allow_boundary_clamp,
    )


def build_operational_snapshot_at_time(
    *,
    snapshot_id: str,
    shift_id: str,
    plan_id: str,
    plan_version: int,
    snapshot_version: int,
    t0_utc_s: int,
    traffic_scenario_revision: int,
    base_request: SolveRequest,
    current_plan: EvaluatedPlan,
    breakdown_vehicle_ids: Sequence[str] = (),
) -> OperationalSnapshot:
    """Advance vehicles along `current_plan` up to `t0_utc_s` and capture an atomic OperationalSnapshot.

    Enforces:
    - Completed stops (`service_completion_utc_s <= t0_utc_s`) are frozen in `completed_order_ids`.
    - In-transit vehicles have their immediate next stop locked (`locked_next_order_id`)
      and their residual route starts at that locked stop's arrival/completion state.
    - Sunk costs (distance, paid time, completed SLA, and posted shift activations) are tallied.
    """
    orders_map = {o.id: o for o in base_request.orders}
    breakdown_set = set(breakdown_vehicle_ids)

    completed_orders: set[str] = set(base_request.completed_order_ids)
    vehicle_states: list[VehicleLiveState] = []

    sunk_op_paise = 0
    for r in current_plan.routes:
        if not r.stops:
            continue

        comp_stops = [s for s in r.stops if s.service_completion_utc_s <= t0_utc_s]
        rem_stops = [s for s in r.stops if s.service_completion_utc_s > t0_utc_s]

        for s in comp_stops:
            completed_orders.add(s.order_id)
            sunk_op_paise += compute_order_sla_cost_paise(
                s.lateness_seconds, orders_map[s.order_id], base_request.cost_rates
            )

        sunk_dist_m = sum(s.leg_distance_m for s in comp_stops)
        if not rem_stops:
            state_kind = VehicleOperationalState.COMPLETED_SHIFT
            curr_node = base_request.depot.node_id if r.return_to_depot else r.stops[-1].node_id
            curr_time = max(t0_utc_s, r.completion_utc_s)
            rem_load = 0
            locked_next = None
            sunk_paid_s = r.paid_duration_seconds
        elif r.departure_utc_s >= t0_utc_s and not comp_stops:
            state_kind = (
                VehicleOperationalState.UNAVAILABLE_BREAKDOWN
                if r.vehicle_id in breakdown_set
                else VehicleOperationalState.DEPOT_IDLE
            )
            curr_node = base_request.depot.node_id
            curr_time = max(t0_utc_s, r.departure_utc_s)
            rem_load = sum(s.demand_units for s in rem_stops)
            locked_next = None
            sunk_paid_s = 0
        else:
            # Vehicle has departed and is in transit or servicing
            if r.vehicle_id in breakdown_set:
                state_kind = VehicleOperationalState.UNAVAILABLE_BREAKDOWN
            elif rem_stops[0].arrival_utc_s <= t0_utc_s:
                state_kind = (
                    VehicleOperationalState.SERVICING
                    if rem_stops[0].service_start_utc_s <= t0_utc_s
                    else VehicleOperationalState.WAITING_AT_STOP
                )
            else:
                state_kind = VehicleOperationalState.EN_ROUTE

            if comp_stops:
                curr_node = comp_stops[-1].node_id
                curr_time = comp_stops[-1].service_completion_utc_s
            else:
                curr_node = r.start_node_id
                curr_time = r.departure_utc_s

            rem_load = sum(s.demand_units for s in rem_stops)
            locked_next = rem_stops[0].order_id if state_kind != VehicleOperationalState.UNAVAILABLE_BREAKDOWN else None
            sunk_paid_s = max(0, curr_time - r.departure_utc_s)

        sunk_op_paise += compute_route_distance_cost_paise(
            sunk_dist_m, base_request.cost_rates.distance_rate_paise_per_km
        )
        sunk_op_paise += compute_route_time_cost_paise(
            sunk_paid_s, base_request.cost_rates.time_rate_paise_per_hour
        )

        vehicle_states.append(
            VehicleLiveState(
                vehicle_id=r.vehicle_id,
                state=state_kind,
                current_node_id=curr_node,
                current_time_utc_s=curr_time,
                remaining_load_units=rem_load,
                locked_next_order_id=locked_next,
                assigned_remaining_order_ids=tuple(s.order_id for s in rem_stops),
                completed_order_ids=tuple(s.order_id for s in comp_stops),
                sunk_distance_m=sunk_dist_m,
                sunk_paid_seconds=sunk_paid_s,
                position_timestamp_utc_s=t0_utc_s,
                gps_confidence=1.0,
            )
        )

    # Also include available depot-idle vehicles not in `current_plan.routes`
    routed_vids = {r.vehicle_id for r in current_plan.routes}
    for v in base_request.vehicles:
        if v.id not in routed_vids:
            v_state = (
                VehicleOperationalState.UNAVAILABLE_BREAKDOWN
                if (not v.available or v.id in breakdown_set)
                else VehicleOperationalState.DEPOT_IDLE
            )
            vehicle_states.append(
                VehicleLiveState(
                    vehicle_id=v.id,
                    state=v_state,
                    current_node_id=base_request.depot.node_id,
                    current_time_utc_s=t0_utc_s,
                    remaining_load_units=0,
                    locked_next_order_id=None,
                    assigned_remaining_order_ids=(),
                    completed_order_ids=(),
                    sunk_distance_m=0,
                    sunk_paid_seconds=0,
                    position_timestamp_utc_s=t0_utc_s,
                    gps_confidence=1.0,
                )
            )

    in_transit_remaining = {
        oid
        for vs in vehicle_states
        if vs.state in (
            VehicleOperationalState.EN_ROUTE,
            VehicleOperationalState.WAITING_AT_STOP,
            VehicleOperationalState.SERVICING,
        )
        for oid in vs.assigned_remaining_order_ids
    }
    all_order_ids = {o.id for o in base_request.orders}
    pending_unassigned = frozenset(all_order_ids - completed_orders - in_transit_remaining)

    posted_act_total = sum(base_request.posted_activation_cost_paise_by_vehicle.values())
    total_sunk_paise = base_request.sunk_cost_paise + sunk_op_paise + posted_act_total

    return OperationalSnapshot(
        snapshot_id=snapshot_id,
        shift_id=shift_id,
        plan_id=plan_id,
        plan_version=plan_version,
        snapshot_version=snapshot_version,
        t0_utc_s=t0_utc_s,
        traffic_scenario_revision=traffic_scenario_revision,
        vehicle_states=tuple(sorted(vehicle_states, key=lambda x: x.vehicle_id)),
        completed_order_ids=frozenset(completed_orders),
        pending_unassigned_order_ids=pending_unassigned,
        sunk_cost_paise=total_sunk_paise,
    )
