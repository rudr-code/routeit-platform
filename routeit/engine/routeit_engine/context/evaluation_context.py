"""Immutable EvaluationContext and canonical SHA-256 hashing (Q-HGALS 5.0 §6.2 & Phase 5 Addendum A)."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any

from routeit_engine.contracts.types import SolveRequest
from routeit_engine.oracle.protocol import OracleIdentity


def canonical_context_dict(req: SolveRequest, oracle_identity: OracleIdentity) -> dict[str, Any]:
    """Build deterministic canonical dictionary of all evaluation-affecting inputs."""
    orders_payload = [
        {
            "id": o.id,
            "node_id": o.node_id,
            "demand_units": o.demand_units,
            "service_seconds": o.service_seconds,
            "window_open_utc_s": o.window_open_utc_s,
            "window_close_utc_s": o.window_close_utc_s,
            "window_type": o.window_type.value,
            "priority": o.priority.value,
            "custom_sla": o.custom_sla_rate_paise_per_min.to_dict()
            if o.custom_sla_rate_paise_per_min is not None
            else None,
        }
        for o in sorted(req.orders, key=lambda x: x.id)
    ]
    vehicles_payload = [
        {
            "id": v.id,
            "capacity_units": v.capacity_units,
            "activation_cost_paise": v.activation_cost_paise,
            "available": v.available,
            "return_to_depot": v.return_to_depot,
            "return_deadline_utc_s": v.return_deadline_utc_s,
            "vehicle_profile": v.vehicle_profile,
        }
        for v in sorted(req.vehicles, key=lambda x: x.id)
    ]
    starts_payload = {
        vid: {
            "node_id": st.node_id,
            "start_time_utc_s": st.start_time_utc_s,
            "initial_load_units": st.initial_load_units,
            "locked_first_stop_order_id": st.locked_first_stop_order_id,
            "is_in_transit": st.is_in_transit,
        }
        for vid, st in sorted(req.route_starts_by_vehicle.items())
    }
    cfg = req.planning_config
    return {
        "engine_spec_version": "Q-HGALS-5.0-REV-2026-11-16",
        "shift_id": req.shift_id,
        "activated_vehicle_ids_in_shift": sorted(req.activated_vehicle_ids_in_shift),
        "completed_order_ids": sorted(req.completed_order_ids),
        "sunk_cost_paise": req.sunk_cost_paise,
        "posted_activation_cost_paise_by_vehicle": {
            k: req.posted_activation_cost_paise_by_vehicle[k]
            for k in sorted(req.posted_activation_cost_paise_by_vehicle)
        },
        "depot": {
            "id": req.depot.id,
            "node_id": req.depot.node_id,
            "return_enabled": req.depot.return_enabled,
            "return_deadline_utc_s": req.depot.return_deadline_utc_s,
            "opening_utc_s": req.depot.opening_utc_s,
            "closing_utc_s": req.depot.closing_utc_s,
        },
        "orders": orders_payload,
        "vehicles": vehicles_payload,
        "route_starts_by_vehicle": starts_payload,
        "cost_rates": {
            "distance_rate_paise_per_km": req.cost_rates.distance_rate_paise_per_km.to_dict(),
            "time_rate_paise_per_hour": req.cost_rates.time_rate_paise_per_hour.to_dict(),
            "critical_sla_paise_per_min": req.cost_rates.critical_sla_paise_per_min.to_dict(),
            "standard_sla_paise_per_min": req.cost_rates.standard_sla_paise_per_min.to_dict(),
            "flexible_sla_paise_per_min": req.cost_rates.flexible_sla_paise_per_min.to_dict(),
            "rounding_policy_version": req.cost_rates.rounding_policy_version,
        },
        "planning_config": {
            "planning_mode": cfg.planning_mode.value,
            "fleet_mode": cfg.fleet_mode.value,
            "target_fleet_size": cfg.target_fleet_size,
            "target_fleet_policy": cfg.target_fleet_policy.value,
            "max_route_count": cfg.max_route_count,
            "max_shift_activated_vehicles": cfg.max_shift_activated_vehicles,
            "profile": cfg.profile.value,
            "balanced_normalization_mode": cfg.balanced_normalization_mode.value,
            "max_extra_cost_paise": cfg.max_extra_cost_paise,
            "reference_cost_paise": cfg.reference_cost_paise,
            "departure_set_utc_s": list(cfg.departure_set_utc_s),
            "tie_policy_version": cfg.tie_policy_version,
        },
        "oracle_identity": oracle_identity.to_dict(),
    }


def compute_context_hash(req: SolveRequest, oracle_identity: OracleIdentity) -> str:
    payload = canonical_context_dict(req, oracle_identity)
    canonical_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical_bytes).hexdigest()


@dataclass(frozen=True)
class EvaluationContext:
    request: SolveRequest
    oracle_identity: OracleIdentity
    context_hash: str
    orders_by_id: dict[str, Any]
    vehicles_by_id: dict[str, Any]
    eligible_vehicles: tuple[Any, ...]

    @classmethod
    def build(cls, req: SolveRequest, oracle_identity: OracleIdentity) -> "EvaluationContext":
        ctx_hash = compute_context_hash(req, oracle_identity)
        orders_by_id = {o.id: o for o in req.orders if o.id not in req.completed_order_ids}
        vehicles_by_id = {v.id: v for v in req.vehicles}
        eligible = tuple(v for v in req.vehicles if v.available)
        return cls(
            request=req,
            oracle_identity=oracle_identity,
            context_hash=ctx_hash,
            orders_by_id=orders_by_id,
            vehicles_by_id=vehicles_by_id,
            eligible_vehicles=eligible,
        )
