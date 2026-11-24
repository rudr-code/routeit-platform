"""Typed data contracts and status taxonomies for Q-HGALS 5.0."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from fractions import Fraction
import math
from typing import Any


class WindowType(str, Enum):
    HARD = "HARD"
    SOFT = "SOFT"


class PriorityTier(str, Enum):
    CRITICAL = "CRITICAL"
    STANDARD = "STANDARD"
    FLEXIBLE = "FLEXIBLE"


class PlanningMode(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"


class FleetMode(str, Enum):
    TARGET = "TARGET"
    AUTO = "AUTO"


class TargetFleetPolicy(str, Enum):
    ELIGIBLE_POOL_AT_MOST = "ELIGIBLE_POOL_AT_MOST"
    EXACT_ACTIVE_COUNT = "EXACT_ACTIVE_COUNT"


class OptimizationProfile(str, Enum):
    COST_FOCUSED = "COST_FOCUSED"
    BALANCED = "BALANCED"
    DRIVER_PRODUCTIVITY = "DRIVER_PRODUCTIVITY"


class BalancedNormalizationMode(str, Enum):
    QUANTILE_TYPE7 = "QUANTILE_TYPE7"
    MIN_MAX = "MIN_MAX"


class PartialSplitMode(str, Enum):
    EXACT_TINY = "EXACT_TINY"
    BOUNDED_PRACTICAL = "BOUNDED_PRACTICAL"


class SolverKind(str, Enum):
    CONSTRUCTIVE = "CONSTRUCTIVE"
    SPLIT_BASELINE = "SPLIT_BASELINE"
    LOCAL_SEARCH = "LOCAL_SEARCH"
    ALNS = "ALNS"
    GA = "GA"
    QPSO = "QPSO"
    ORTOOLS_ADAPTER = "ORTOOLS_ADAPTER"


class QPSOMemoryMode(str, Enum):
    ARCHIVE_ONLY = "ARCHIVE_ONLY"
    BALDWINIAN = "BALDWINIAN"
    OS_RELABEL = "OS_RELABEL"


class ResultStatus(str, Enum):
    COMPLETE_FEASIBLE = "COMPLETE_FEASIBLE"
    PARTIAL_FEASIBLE = "PARTIAL_FEASIBLE"
    NO_FEASIBLE_PLAN_FOUND = "NO_FEASIBLE_PLAN_FOUND"
    PROVEN_INFEASIBLE = "PROVEN_INFEASIBLE"
    SEARCH_BUDGET_EXHAUSTED = "SEARCH_BUDGET_EXHAUSTED"
    DATA_INSUFFICIENT = "DATA_INSUFFICIENT"
    INVALID_INPUT = "INVALID_INPUT"
    INVALID_CONFIG = "INVALID_CONFIG"
    ROAD_ORACLE_FAILURE = "ROAD_ORACLE_FAILURE"
    NUMERIC_RANGE_ERROR = "NUMERIC_RANGE_ERROR"
    PROFILE_REFERENCE_UNAVAILABLE = "PROFILE_REFERENCE_UNAVAILABLE"
    PROFILE_CAP_UNSATISFIED = "PROFILE_CAP_UNSATISFIED"
    SHIFT_FLEET_POLICY_CONFLICT = "SHIFT_FLEET_POLICY_CONFLICT"
    INVALID_OPERATIONAL_STATE = "INVALID_OPERATIONAL_STATE"


class StopReason(str, Enum):
    CONVERGED_PROVEN_EXACT = "CONVERGED_PROVEN_EXACT"
    EVALUATION_BUDGET = "EVALUATION_BUDGET"
    WALL_LIMIT = "WALL_LIMIT"
    STAGNATION = "STAGNATION"
    CANCELLED = "CANCELLED"
    PRECHECK_REJECTED = "PRECHECK_REJECTED"
    ORACLE_ERROR = "ORACLE_ERROR"


class ProofScope(str, Enum):
    EXACT_DECLARED_SUBPROBLEM = "EXACT_DECLARED_SUBPROBLEM"
    SOUND_PRECHECK_PROOF = "SOUND_PRECHECK_PROOF"
    HEURISTIC_NO_PROOF = "HEURISTIC_NO_PROOF"
    NONE = "NONE"


class UnservedReason(str, Enum):
    PROVEN_UNSERVICEABLE_CAPACITY = "PROVEN_UNSERVICEABLE_CAPACITY"
    PROVEN_UNSERVICEABLE_HARD_WINDOW = "PROVEN_UNSERVICEABLE_HARD_WINDOW"
    PROVEN_UNSERVICEABLE_UNREACHABLE = "PROVEN_UNSERVICEABLE_UNREACHABLE"
    UNSERVED_BY_OPTIMIZATION_DECISION = "UNSERVED_BY_OPTIMIZATION_DECISION"
    UNSERVED_BY_DECODER_LIMIT = "UNSERVED_BY_DECODER_LIMIT"
    UNSERVED_BY_SEARCH_BUDGET = "UNSERVED_BY_SEARCH_BUDGET"
    UNSERVED_BY_ROAD_DATA_FAILURE = "UNSERVED_BY_ROAD_DATA_FAILURE"
    NOT_EVALUATED = "NOT_EVALUATED"


class ViolationKind(str, Enum):
    CAPACITY_EXCEEDED = "CAPACITY_EXCEEDED"
    HARD_WINDOW_LATE = "HARD_WINDOW_LATE"
    DEPOT_RETURN_DEADLINE_LATE = "DEPOT_RETURN_DEADLINE_LATE"
    ROAD_PATH_UNAVAILABLE = "ROAD_PATH_UNAVAILABLE"
    ROAD_ORACLE_ERROR = "ROAD_ORACLE_ERROR"
    DUPLICATE_OR_MISSING_ORDER = "DUPLICATE_OR_MISSING_ORDER"
    FLEET_LIMIT_EXCEEDED = "FLEET_LIMIT_EXCEEDED"
    SHIFT_CEILING_EXCEEDED = "SHIFT_CEILING_EXCEEDED"
    VEHICLE_UNAVAILABLE = "VEHICLE_UNAVAILABLE"
    DEPARTURE_OUTSIDE_DOMAIN = "DEPARTURE_OUTSIDE_DOMAIN"
    LOCKED_STOP_VIOLATED = "LOCKED_STOP_VIOLATED"
    COMPLETED_ORDER_REASSIGNED = "COMPLETED_ORDER_REASSIGNED"


class VehicleOperationalState(str, Enum):
    DEPOT_IDLE = "DEPOT_IDLE"
    EN_ROUTE = "EN_ROUTE"
    WAITING_AT_STOP = "WAITING_AT_STOP"
    SERVICING = "SERVICING"
    RETURNING_TO_DEPOT = "RETURNING_TO_DEPOT"
    COMPLETED_SHIFT = "COMPLETED_SHIFT"
    UNAVAILABLE_BREAKDOWN = "UNAVAILABLE_BREAKDOWN"


@dataclass(frozen=True)
class ExactRate:
    """Exact rational rate represented as reduced numerator / positive denominator."""

    numerator: int
    denominator: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.numerator, int) or not isinstance(self.denominator, int):
            raise TypeError("ExactRate numerator and denominator must be integers")
        if isinstance(self.numerator, bool) or isinstance(self.denominator, bool):
            raise TypeError("Booleans are not valid integer rate operands")
        if self.denominator <= 0:
            raise ValueError("ExactRate denominator must be strictly positive")
        g = math.gcd(abs(self.numerator), self.denominator)
        object.__setattr__(self, "numerator", self.numerator // g)
        object.__setattr__(self, "denominator", self.denominator // g)

    @classmethod
    def from_value(cls, val: int | str | Fraction | "ExactRate" | dict[str, int]) -> "ExactRate":
        if isinstance(val, ExactRate):
            return val
        if isinstance(val, dict):
            return cls(int(val["n"]), int(val.get("d", 1)))
        if isinstance(val, int) and not isinstance(val, bool):
            return cls(val, 1)
        if isinstance(val, Fraction):
            return cls(val.numerator, val.denominator)
        if isinstance(val, str):
            f = Fraction(val.strip())
            return cls(f.numerator, f.denominator)
        raise TypeError(f"Unsupported rate type: {type(val)!r}; floating-point rates are forbidden")

    def to_fraction(self) -> Fraction:
        return Fraction(self.numerator, self.denominator)

    def to_dict(self) -> dict[str, int]:
        return {"n": self.numerator, "d": self.denominator}


@dataclass(frozen=True)
class DepotSpec:
    id: str
    node_id: str
    return_enabled: bool = True
    return_deadline_utc_s: int | None = None
    opening_utc_s: int = 0
    closing_utc_s: int | None = None
    lat: float | None = None
    lon: float | None = None
    name: str = "Central Depot"


@dataclass(frozen=True)
class OrderSpec:
    id: str
    node_id: str
    demand_units: int
    service_seconds: int
    window_open_utc_s: int
    window_close_utc_s: int
    window_type: WindowType = WindowType.HARD
    priority: PriorityTier = PriorityTier.STANDARD
    custom_sla_rate_paise_per_min: ExactRate | None = None
    customer_id: str | None = None
    lat: float | None = None
    lon: float | None = None


@dataclass(frozen=True)
class VehicleSpec:
    id: str
    capacity_units: int
    activation_cost_paise: int
    available: bool = True
    return_to_depot: bool | None = None
    return_deadline_utc_s: int | None = None
    vehicle_profile: str = "urban_van"


@dataclass(frozen=True)
class CostRateConfig:
    distance_rate_paise_per_km: ExactRate
    time_rate_paise_per_hour: ExactRate
    critical_sla_paise_per_min: ExactRate
    standard_sla_paise_per_min: ExactRate
    flexible_sla_paise_per_min: ExactRate
    rounding_policy_version: str = "ROUND_POLICY_V1_ROUTE_ORDER_EVEN"

    def sla_rate_for(self, order: OrderSpec) -> ExactRate:
        if order.custom_sla_rate_paise_per_min is not None:
            return order.custom_sla_rate_paise_per_min
        if order.priority == PriorityTier.CRITICAL:
            return self.critical_sla_paise_per_min
        if order.priority == PriorityTier.STANDARD:
            return self.standard_sla_paise_per_min
        return self.flexible_sla_paise_per_min


@dataclass(frozen=True)
class RouteStart:
    """Generalized route start state (E1): depot start is a special case."""

    node_id: str
    start_time_utc_s: int
    initial_load_units: int | None = None
    locked_first_stop_order_id: str | None = None
    is_in_transit: bool = False


@dataclass(frozen=True)
class PlanningConfig:
    planning_mode: PlanningMode = PlanningMode.COMPLETE
    fleet_mode: FleetMode = FleetMode.AUTO
    target_fleet_size: int | None = None
    target_fleet_policy: TargetFleetPolicy = TargetFleetPolicy.ELIGIBLE_POOL_AT_MOST
    max_route_count: int | None = None
    max_shift_activated_vehicles: int | None = None
    profile: OptimizationProfile = OptimizationProfile.COST_FOCUSED
    balanced_normalization_mode: BalancedNormalizationMode = BalancedNormalizationMode.QUANTILE_TYPE7
    max_extra_cost_paise: int | None = None
    reference_cost_paise: int | None = None
    departure_set_utc_s: tuple[int, ...] = (0,)
    partial_split_mode: PartialSplitMode = PartialSplitMode.EXACT_TINY
    bounded_max_labels_per_state: int = 32
    bounded_max_skip_subsets_per_segment: int = 16
    solver_kind: SolverKind = SolverKind.QPSO
    max_canonical_evaluations: int = 500
    max_wall_seconds: float = 30.0
    stagnation_evaluations: int = 200
    seed: int = 42
    tie_policy_version: str = "TIE_POLICY_V1_CANONICAL_SIGNATURE"
    qpso_particles: int = 16
    qpso_generations: int = 25
    qpso_alpha_max: float = 1.0
    qpso_alpha_min: float = 0.5
    qpso_memory_mode: QPSOMemoryMode = QPSOMemoryMode.BALDWINIAN
    enable_local_search_refinement: bool = True


@dataclass(frozen=True)
class SolveRequest:
    request_id: str
    shift_id: str
    depot: DepotSpec
    orders: tuple[OrderSpec, ...]
    vehicles: tuple[VehicleSpec, ...]
    cost_rates: CostRateConfig
    planning_config: PlanningConfig
    activated_vehicle_ids_in_shift: frozenset[str] = frozenset()
    route_starts_by_vehicle: dict[str, RouteStart] = field(default_factory=dict)
    completed_order_ids: frozenset[str] = frozenset()
    sunk_cost_paise: int = 0
    posted_activation_cost_paise_by_vehicle: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class VehicleLiveState:
    vehicle_id: str
    state: VehicleOperationalState
    current_node_id: str
    current_time_utc_s: int
    remaining_load_units: int
    locked_next_order_id: str | None = None
    assigned_remaining_order_ids: tuple[str, ...] = ()
    completed_order_ids: tuple[str, ...] = ()
    sunk_distance_m: int = 0
    sunk_paid_seconds: int = 0
    position_timestamp_utc_s: int | None = None
    gps_confidence: float = 1.0


@dataclass(frozen=True)
class OperationalSnapshot:
    snapshot_id: str
    shift_id: str
    plan_id: str
    plan_version: int
    snapshot_version: int
    t0_utc_s: int
    traffic_scenario_revision: int
    vehicle_states: tuple[VehicleLiveState, ...]
    completed_order_ids: frozenset[str]
    pending_unassigned_order_ids: frozenset[str]
    sunk_cost_paise: int = 0
    max_gps_staleness_seconds: int = 300


@dataclass(frozen=True)
class ReplanRequest:
    replan_id: str
    base_solve_request: SolveRequest
    snapshot: OperationalSnapshot
    current_plan: "EvaluatedPlan"
    emergency_unlock_next_stop: bool = False
    min_cost_improvement_paise: int = 0


@dataclass(frozen=True)
class Violation:
    kind: ViolationKind
    message: str
    order_id: str | None = None
    vehicle_id: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StopSchedule:
    seq: int
    order_id: str
    node_id: str
    demand_units: int
    arrival_utc_s: int
    window_open_utc_s: int
    window_close_utc_s: int
    window_type: WindowType
    priority: PriorityTier
    wait_seconds: int
    service_start_utc_s: int
    service_seconds: int
    service_completion_utc_s: int
    lateness_seconds: int
    sla_cost_paise: int
    leg_distance_m: int
    leg_travel_seconds: int
    load_after_Units: int
    is_locked: bool = False


@dataclass(frozen=True)
class RouteLegRecord:
    seq: int
    from_node_id: str
    to_node_id: str
    departure_utc_s: int
    arrival_utc_s: int
    distance_m: int
    travel_seconds: int
    path_node_ids: tuple[str, ...] = ()
    path_edge_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvaluatedRoute:
    vehicle_id: str
    departure_utc_s: int
    start_node_id: str
    stops: tuple[StopSchedule, ...]
    legs: tuple[RouteLegRecord, ...]
    return_to_depot: bool
    completion_utc_s: int
    total_distance_m: int
    paid_duration_seconds: int
    idle_waiting_seconds: int
    initial_load_units: int
    capacity_units: int
    distance_cost_paise: int
    time_cost_paise: int
    sla_cost_paise: int
    route_operating_cost_paise: int
    newly_activated_in_shift: bool
    incremental_activation_cost_paise: int
    total_incremental_route_cost_paise: int
    feasible: bool
    violations: tuple[Violation, ...] = ()

    @property
    def stop_order_ids(self) -> tuple[str, ...]:
        return tuple(s.order_id for s in self.stops)

    @property
    def canonical_descriptor(self) -> tuple[int, tuple[str, ...]]:
        return (self.departure_utc_s, self.stop_order_ids)


@dataclass(frozen=True)
class CostLedger:
    distance_cost_paise: int
    time_cost_paise: int
    sla_cost_paise: int
    operating_cost_paise: int
    incremental_activation_cost_paise: int
    incremental_decision_cost_paise: int
    activation_posted_before_paise: int
    activation_proposed_new_paise: int
    activation_posted_after_paise: int
    sunk_cost_before_paise: int
    shift_forecast_total_after_paise: int
    rounding_policy_version: str
    max_rounding_deviation_paise: ExactRate
    route_distance_lines_paise: dict[str, int] = field(default_factory=dict)
    route_time_lines_paise: dict[str, int] = field(default_factory=dict)
    order_sla_lines_paise: dict[str, int] = field(default_factory=dict)
    vehicle_activation_lines_paise: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class UnservedOrderRecord:
    order_id: str
    priority: PriorityTier
    reason: UnservedReason
    detail: str = ""


@dataclass(frozen=True)
class EvaluatedPlan:
    context_hash: str
    routes: tuple[EvaluatedRoute, ...]
    served_order_ids: frozenset[str]
    unserved_orders: tuple[UnservedOrderRecord, ...]
    coverage_vector: tuple[int, int, int]  # (N_C, N_S, N_F)
    idle_waiting_seconds: int
    total_distance_m: int
    total_paid_seconds: int
    m_routes_used: int
    m_new_activated: int
    m_shift_activated_after: int
    selected_vehicle_ids: tuple[str, ...]
    newly_activated_vehicle_ids: tuple[str, ...]
    shift_activated_vehicle_ids_after: frozenset[str]
    ledger: CostLedger
    hard_feasible: bool
    complete_feasible: bool
    violations: tuple[Violation, ...]
    served_signature: tuple[int, ...]
    canonical_route_signature: tuple[tuple[str, int, tuple[str, ...]], ...]
    plan_hash: str

    @property
    def c_dec_paise(self) -> int:
        return self.ledger.incremental_decision_cost_paise


@dataclass
class TelemetryCounters:
    candidates_generated: int = 0
    unique_permutations_decoded: int = 0
    decode_attempts: int = 0
    canonical_evaluations: int = 0
    evaluation_cache_hits: int = 0
    evaluation_cache_misses: int = 0
    local_search_moves_considered: int = 0
    local_search_evaluations: int = 0
    road_oracle_queries: int = 0
    road_oracle_cache_hits: int = 0
    split_labels_created: int = 0
    split_labels_pruned: int = 0
    split_max_frontier_size: int = 0
    split_frontier_truncations: int = 0
    iterations_completed: int = 0
    incumbent_updates: int = 0
    elapsed_seconds: float = 0.0
    convergence_trace: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class DiagnosticEntry:
    code: str
    message: str
    order_id: str | None = None
    vehicle_id: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RunResult:
    run_id: str
    request_id: str
    shift_id: str
    context_hash: str
    solver_kind: SolverKind
    result_status: ResultStatus
    stop_reason: StopReason
    proof_scope: ProofScope
    plan: EvaluatedPlan | None
    telemetry: TelemetryCounters
    diagnostics: tuple[DiagnosticEntry, ...] = ()
    approximation_flags: dict[str, bool] = field(default_factory=dict)
    calibration_metadata: dict[str, Any] = field(default_factory=dict)
