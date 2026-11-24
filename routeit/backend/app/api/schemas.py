"""Pydantic API Request and Response Schemas for Route.it (/v1)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class DepotCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, description="Human-readable depot name")
    lat: float = Field(..., ge=-90.0, le=90.0, description="Latitude in decimal degrees")
    lon: float = Field(..., ge=-180.0, le=180.0, description="Longitude in decimal degrees")
    opening_time_utc_s: int = Field(default=1794882600, description="Depot opening UTC epoch seconds")
    closing_time_utc_s: int | None = Field(default=1794925800, description="Depot closing UTC epoch seconds")
    return_enabled: bool = Field(default=True, description="Whether vehicles must return to depot")
    return_deadline_utc_s: int | None = Field(default=1794925800, description="Latest permitted return timestamp")


class CustomerCreateRequest(BaseModel):
    name: str = Field(..., min_length=1)
    lat: float = Field(..., ge=-90.0, le=90.0)
    lon: float = Field(..., ge=-180.0, le=180.0)
    address_text: str = Field(..., min_length=1)
    address_source: str = Field(default="DISPATCHER_TYPED")
    delivery_instructions: str = Field(default="")
    confirmed: bool = Field(default=True)


class LocationConfirmRequest(BaseModel):
    lat: float = Field(..., ge=-90.0, le=90.0)
    lon: float = Field(..., ge=-180.0, le=180.0)
    address_text: str = Field(..., min_length=1)
    delivery_instructions: str = Field(default="")


class OrderCreateRequest(BaseModel):
    customer_id: str
    external_ref: str = Field(..., min_length=1)
    demand_units: int = Field(..., gt=0, description="Order weight in kg (integer units)")
    service_seconds: int = Field(..., ge=0, description="On-site unloading duration in seconds")
    window_open_utc_s: int = Field(..., description="Earliest permitted service start timestamp (UTC s)")
    window_close_utc_s: int = Field(..., description="Latest permitted service completion timestamp (UTC s)")
    window_type: str = Field(default="HARD", pattern="^(HARD|SOFT)$")
    priority: str = Field(default="STANDARD", pattern="^(CRITICAL|STANDARD|FLEXIBLE)$")
    promised_date: str | None = Field(default=None, description="Promised delivery deadline date (YYYY-MM-DD)")
    is_overdue: bool = Field(default=False, description="Whether the promised deadline has already passed")
    has_fixed_time_window: bool = Field(default=True, description="Whether customer requested a specific time slot")


class OrderUpdateRequest(BaseModel):
    demand_units: int | None = Field(default=None, gt=0)
    service_seconds: int | None = Field(default=None, ge=0)
    window_open_utc_s: int | None = Field(default=None)
    window_close_utc_s: int | None = Field(default=None)
    window_type: str | None = Field(default=None, pattern="^(HARD|SOFT)$")
    priority: str | None = Field(default=None, pattern="^(CRITICAL|STANDARD|FLEXIBLE)$")
    status: str | None = Field(default=None, pattern="^(NEW|IN_TRANSIT|CANCELLED|RETURNED|DELIVERED)$")
    promised_date: str | None = Field(default=None)
    is_overdue: bool | None = Field(default=None)
    address_text: str | None = Field(default=None)
    delivery_instructions: str | None = Field(default=None)
    lat: float | None = Field(default=None, ge=-90.0, le=90.0)
    lon: float | None = Field(default=None, ge=-180.0, le=180.0)


class VehicleCreateRequest(BaseModel):
    depot_id: str
    code: str = Field(..., min_length=1)
    capacity_units: int = Field(..., gt=0)
    activation_cost_paise: int = Field(..., ge=0, description="Shift activation fee in integer paise (₹1 = 100 paise)")
    available: bool = Field(default=True)
    return_to_depot: bool | None = Field(default=None)
    driver_name: str = Field(default="")
    driver_username: str = Field(default="")
    driver_password: str = Field(default="")
    in_transit: bool = Field(default=False)


class VehicleUpdateRequest(BaseModel):
    code: str | None = Field(default=None, min_length=1)
    capacity_units: int | None = Field(default=None, gt=0)
    activation_cost_paise: int | None = Field(default=None, ge=0)
    available: bool | None = Field(default=None)
    driver_name: str | None = Field(default=None)
    driver_username: str | None = Field(default=None)
    driver_password: str | None = Field(default=None)
    in_transit: bool | None = Field(default=None)


class RationalRateSchema(BaseModel):
    n: int = Field(..., ge=0, description="Numerator in paise")
    d: int = Field(default=1, gt=0, description="Denominator (> 0)")


class CostProfileCreateRequest(BaseModel):
    name: str = Field(..., min_length=1)
    distance_rate_paise_per_km: RationalRateSchema
    time_rate_paise_per_hour: RationalRateSchema
    critical_sla_paise_per_min: RationalRateSchema
    standard_sla_paise_per_min: RationalRateSchema
    flexible_sla_paise_per_min: RationalRateSchema
    rounding_policy_version: str = Field(default="ROUND_POLICY_V1_ROUTE_ORDER_EVEN")


class TrafficScenarioCreateRequest(BaseModel):
    name: str = Field(..., min_length=1)
    kind: str = Field(default="TIME_PROFILE", pattern="^(STATIC|TIME_PROFILE|INCIDENT_OVERLAY)$")
    revision: int = Field(default=1, ge=1)
    closed_edge_ids: list[str] = Field(default_factory=list)
    edge_multipliers_override: dict[str, float] = Field(default_factory=dict)


class PlanningRequestCreate(BaseModel):
    shift_id: str | None = Field(default=None, description="Operating shift UUID (auto-generated if omitted)")
    depot_id: str
    order_ids: list[str]
    vehicle_ids: list[str]
    cost_profile_id: str
    traffic_scenario_id: str
    planning_mode: str = Field(default="COMPLETE", pattern="^(COMPLETE|PARTIAL)$")
    fleet_mode: str = Field(default="AUTO", pattern="^(TARGET|AUTO)$")
    target_fleet_size: int | None = Field(default=None)
    target_fleet_policy: str = Field(default="ELIGIBLE_POOL_AT_MOST")
    max_route_count: int | None = Field(default=None)
    max_shift_activated_vehicles: int | None = Field(default=None)
    profile: str = Field(default="COST_FOCUSED", pattern="^(COST_FOCUSED|BALANCED|DRIVER_PRODUCTIVITY)$")
    max_extra_cost_paise: int | None = Field(default=None)
    reference_cost_paise: int | None = Field(default=None)
    departure_set_utc_s: list[int] = Field(default_factory=lambda: [1794882600])
    partial_split_mode: str = Field(default="EXACT_TINY", pattern="^(EXACT_TINY|BOUNDED_PRACTICAL)$")


class OptimizationRunCreate(BaseModel):
    planning_request_id: str
    solver_kind: str = Field(
        default="QPSO",
        pattern="^(CONSTRUCTIVE|SPLIT_BASELINE|LOCAL_SEARCH|ALNS|GA|QPSO|ORTOOLS_ADAPTER)$",
    )
    max_canonical_evaluations: int = Field(default=200, ge=10, le=50000)
    max_wall_seconds: float = Field(default=30.0, gt=0.0, le=600.0)
    stagnation_evaluations: int = Field(default=100, ge=5)
    seed: int = Field(default=42)
    qpso_particles: int = Field(default=12, ge=1, le=200)
    qpso_generations: int = Field(default=15, ge=1, le=500)
    qpso_alpha_max: float = Field(default=1.0, gt=0.0)
    qpso_alpha_min: float = Field(default=0.5, gt=0.0)
    qpso_memory_mode: str = Field(default="BALDWINIAN")
    execute_synchronously: bool = Field(default=True, description="Execute immediately in worker or queue")
    idempotency_key: str | None = Field(default=None)


class ReplanTriggerRequest(BaseModel):
    t0_utc_s: int = Field(..., description="Timestamp of dynamic event / replanning snapshot")
    closed_edge_ids: list[str] = Field(default_factory=list)
    edge_multipliers_override: dict[str, float] = Field(default_factory=dict)
    breakdown_vehicle_ids: list[str] = Field(default_factory=list)
    emergency_unlock_next_stop: bool = Field(default=False)
    min_cost_improvement_paise: int = Field(default=0, ge=0)
    idempotency_key: str | None = Field(default=None)


class BenchmarkSuiteRequest(BaseModel):
    planning_request_id: str | None = Field(default=None)
    optimization_run_id: str | None = Field(default=None)
    dataset_source: str | None = Field(default=None, description="LIVE_WORKSPACE | RECENT_RUN | VADODARA_PILOT_8")
    solvers: list[str] = Field(
        default_factory=lambda: ["CONSTRUCTIVE", "LOCAL_SEARCH", "ALNS", "GA", "QPSO", "ORTOOLS_ADAPTER"]
    )
    max_canonical_evaluations: int = Field(default=120, ge=10, le=5000)
    seeds: list[int] = Field(default_factory=lambda: [42, 101])


class GeocodeSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)


class ReverseGeocodeRequest(BaseModel):
    lat: float = Field(..., ge=-90.0, le=90.0)
    lon: float = Field(..., ge=-180.0, le=180.0)
