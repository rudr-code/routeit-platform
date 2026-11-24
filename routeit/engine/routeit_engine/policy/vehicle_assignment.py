"""Vehicle Identity Assignment & Route-Count Activation Marginal (Q-HGALS 5.0 §2 & Phase 5 Addendum A.3)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from routeit_engine.contracts.types import (
    FleetMode,
    PlanningConfig,
    TargetFleetPolicy,
    VehicleSpec,
)


class ShiftFleetPolicyConflictError(ValueError):
    """Raised when |A_shift| already exceeds an approved M_shift_activated_max ceiling."""


@dataclass(frozen=True)
class SortedVehiclePool:
    """Sorted eligible vehicle pool and exact prefix sums G_C(m) and G_N(m) (Q-HGALS 5.0 §2.3)."""

    sorted_vehicles: tuple[VehicleSpec, ...]
    weights_paise: tuple[int, ...]
    is_new_flags: tuple[int, ...]
    prefix_g_c_paise: tuple[int, ...]  # G_C(0..|K|), index m is sum of first m weights
    prefix_g_n_count: tuple[int, ...]  # G_N(0..|K|), index m is sum of first m new flags
    activated_in_shift: frozenset[str]
    max_routes_allowed: int
    max_shift_activated_allowed: int | None
    exact_route_count_required: int | None

    def marginal_activation_cost(self, m: int) -> int:
        """g^C_m = G_C(m) - G_C(m-1) for route count transition m-1 -> m."""
        if m <= 0 or m > len(self.sorted_vehicles):
            raise IndexError(f"Route count m={m} out of bounds [1, {len(self.sorted_vehicles)}]")
        return self.prefix_g_c_paise[m] - self.prefix_g_c_paise[m - 1]

    def marginal_new_activation_count(self, m: int) -> int:
        """Delta G_N(m) = G_N(m) - G_N(m-1) for route count transition m-1 -> m."""
        if m <= 0 or m > len(self.sorted_vehicles):
            raise IndexError(f"Route count m={m} out of bounds [1, {len(self.sorted_vehicles)}]")
        return self.prefix_g_n_count[m] - self.prefix_g_n_count[m - 1]

    def is_route_count_admissible(self, m: int, is_terminal: bool = False) -> bool:
        """Check whether m routes satisfy route limits and optional shift-activation ceiling."""
        if m < 0 or m > self.max_routes_allowed:
            return False
        if self.max_shift_activated_allowed is not None:
            if len(self.activated_in_shift) + self.prefix_g_n_count[m] > self.max_shift_activated_allowed:
                return False
        if is_terminal and self.exact_route_count_required is not None:
            if m != self.exact_route_count_required:
                return False
        return True


def build_sorted_vehicle_pool(
    vehicles: Sequence[VehicleSpec],
    activated_in_shift: frozenset[str],
    config: PlanningConfig,
    posted_activation_by_vehicle: dict[str, int] | None = None,
    *,
    enforce_homogeneous: bool = True,
) -> SortedVehiclePool:
    """Sort eligible vehicles by (w_k, 1[k not in A_shift], vehicle_id) per Q-HGALS 5.0 §2.3 & Addendum A.3."""
    if config.max_shift_activated_vehicles is not None:
        if len(activated_in_shift) > config.max_shift_activated_vehicles:
            raise ShiftFleetPolicyConflictError(
                f"Historical shift activations |A_shift|={len(activated_in_shift)} already exceed "
                f"max_shift_activated_vehicles={config.max_shift_activated_vehicles}"
            )

    eligible = [v for v in vehicles if v.available]
    caps = {v.capacity_units for v in eligible}
    profiles = {v.vehicle_profile for v in eligible}
    is_heterogeneous = len(caps) > 1 or len(profiles) > 1

    if enforce_homogeneous and len(eligible) > 1 and is_heterogeneous:
        raise ValueError(
            "Homogeneous fleet interchangeability violated: eligible vehicles have heterogeneous "
            "capacities or profiles, invalidating the route-count activation shortcut G_C(m)."
        )

    def sort_key(v: VehicleSpec) -> tuple[int, int, int, str]:
        in_a = v.id in activated_in_shift
        w_k = 0 if in_a else v.activation_cost_paise
        not_in_a_flag = 0 if in_a else 1
        cap_tie = -v.capacity_units if len(caps) > 1 else 0
        return (cap_tie, w_k, not_in_a_flag, v.id)

    sorted_v = tuple(sorted(eligible, key=sort_key))
    weights: list[int] = []
    new_flags: list[int] = []
    g_c = [0]
    g_n = [0]

    for v in sorted_v:
        in_a = v.id in activated_in_shift
        w_k = 0 if in_a else v.activation_cost_paise
        nf = 0 if in_a else 1
        weights.append(w_k)
        new_flags.append(nf)
        g_c.append(g_c[-1] + w_k)
        g_n.append(g_n[-1] + nf)

    q = len(sorted_v)
    if config.max_route_count is not None:
        q = min(q, config.max_route_count)

    exact_req: int | None = None
    if config.fleet_mode == FleetMode.TARGET and config.target_fleet_size is not None:
        q = min(q, config.target_fleet_size)
        if config.target_fleet_policy == TargetFleetPolicy.EXACT_ACTIVE_COUNT:
            exact_req = config.target_fleet_size

    return SortedVehiclePool(
        sorted_vehicles=sorted_v,
        weights_paise=tuple(weights),
        is_new_flags=tuple(new_flags),
        prefix_g_c_paise=tuple(g_c),
        prefix_g_n_count=tuple(g_n),
        activated_in_shift=activated_in_shift,
        max_routes_allowed=q,
        max_shift_activated_allowed=config.max_shift_activated_vehicles,
        exact_route_count_required=exact_req,
    )


@dataclass(frozen=True)
class VehicleAssignmentResult:
    """Result of deterministic minimum-cost injective vehicle matching (Q-HGALS 5.0 §2.2, §2.3)."""

    paired_vehicle_ids_in_descriptor_order: tuple[str, ...]
    sorted_route_indices: tuple[int, ...]
    vehicle_id_by_route_index: dict[int, str]
    selected_vehicle_ids: tuple[str, ...]
    newly_activated_vehicle_ids: tuple[str, ...]
    shift_activated_vehicle_ids_after: frozenset[str]
    incremental_activation_cost_paise: int
    m_routes_used: int
    m_new_activated: int
    m_shift_activated_after: int


def assign_vehicles_to_routes(
    route_descriptors: Sequence[tuple[int, tuple[str, ...]]],
    pool: SortedVehiclePool,
) -> VehicleAssignmentResult:
    """Assign m nonempty routes to the first m vehicles in sorted pool, minimizing canonical route signature.

    Per Q-HGALS 5.0 §2.2 & ACT-11:
    1. Select the first m vehicles from `pool.sorted_vehicles` (minimizing sum w_k, then new activations, then IDs).
    2. When chosen vehicles are homogeneous in capacity, sort selected vehicle IDs ascending and pair
       with route descriptors sorted by `(departure_second, stop_id_sequence)` ascending.
    3. When chosen vehicles have heterogeneous capacities, preserve slot-to-vehicle pairing `route_idx -> chosen_vehicles[route_idx].id`
       so each route stays matched with the exact vehicle capacity slot validated during Split/Construction.
    """
    m = len(route_descriptors)
    if not pool.is_route_count_admissible(m, is_terminal=True):
        raise ValueError(
            f"Route count m={m} is inadmissible for pool (max_routes={pool.max_routes_allowed}, "
            f"exact_required={pool.exact_route_count_required}, "
            f"shift_ceiling={pool.max_shift_activated_allowed})"
        )

    chosen_vehicles = pool.sorted_vehicles[:m]
    sorted_selected_ids = tuple(sorted(v.id for v in chosen_vehicles))
    chosen_caps = {v.capacity_units for v in chosen_vehicles}

    vehicle_id_by_route_index: dict[int, str] = {}
    if len(chosen_caps) <= 1:
        # Sort route indices by (departure_second, stop_id_sequence, original_index)
        indexed_descriptors = list(enumerate(route_descriptors))
        indexed_descriptors.sort(key=lambda item: (item[1][0], item[1][1], item[0]))
        sorted_route_indices = tuple(idx for idx, _ in indexed_descriptors)

        for rank, route_idx in enumerate(sorted_route_indices):
            vehicle_id_by_route_index[route_idx] = sorted_selected_ids[rank]
    else:
        sorted_route_indices = tuple(range(m))
        for route_idx in range(m):
            vehicle_id_by_route_index[route_idx] = chosen_vehicles[route_idx].id

    newly_activated = tuple(
        vid for vid in sorted_selected_ids if vid not in pool.activated_in_shift
    )
    shift_after = pool.activated_in_shift | frozenset(sorted_selected_ids)
    inc_cost = pool.prefix_g_c_paise[m]
    m_new = len(newly_activated)
    assert m_new == pool.prefix_g_n_count[m], "G_N(m) must equal |Selected \\ A_shift|"

    return VehicleAssignmentResult(
        paired_vehicle_ids_in_descriptor_order=sorted_selected_ids,
        sorted_route_indices=sorted_route_indices,
        vehicle_id_by_route_index=vehicle_id_by_route_index,
        selected_vehicle_ids=sorted_selected_ids,
        newly_activated_vehicle_ids=newly_activated,
        shift_activated_vehicle_ids_after=shift_after,
        incremental_activation_cost_paise=inc_cost,
        m_routes_used=m,
        m_new_activated=m_new,
        m_shift_activated_after=len(shift_after),
    )
