# Route.it — Shared Contracts Specification

## 1. Canonical Units & Exact Representation (`Q-HGALS 5.0 §4.1`)
- **Distance**: Nonnegative integer meters (`int`).
- **Timestamps**: Signed UTC epoch seconds (`int`).
- **Durations / Waiting / Lateness**: Nonnegative integer seconds (`int`).
- **Demand / Capacity**: Nonnegative integer base units (`int`).
- **Monetary Amounts**: Nonnegative integer paise (`int`, where `100 paise = ₹1.00`).
- **Cost Rates**: Exact rational numbers (`ExactRate(numerator: int, denominator: int)` with `numerator >= 0, denominator > 0`):
  - `distance_rate_paise_per_km`: Exact rational paise per km.
  - `time_rate_paise_per_hour`: Exact rational paise per paid operating hour.
  - `critical_sla_paise_per_min`: Exact rational paise per minute of soft-window completion lateness.
  - `standard_sla_paise_per_min`: Exact rational paise per minute of soft-window completion lateness.
  - `flexible_sla_paise_per_min`: Exact rational paise per minute of soft-window completion lateness.
  - `activation_cost_paise`: Nonnegative integer paise per vehicle per operating shift (`shift_id`).

## 2. Core Engine Data Contracts (`routeit_engine.contracts`)
- `SolveRequest`:
  - `request_id: str`
  - `shift_id: str`
  - `depot: DepotSpec` (`id`, `node_id`, `return_enabled`, `return_deadline_utc_s`, `opening_utc_s`, `closing_utc_s`)
  - `orders: tuple[OrderSpec, ...]` (`id`, `node_id`, `demand_units`, `service_seconds`, `window_open_utc_s`, `window_close_utc_s`, `window_type: HARD|SOFT`, `priority: CRITICAL|STANDARD|FLEXIBLE`)
  - `vehicles: tuple[VehicleSpec, ...]` (`id`, `capacity_units`, `activation_cost_paise`, `available`, `return_to_depot`, `return_deadline_utc_s`)
  - `activated_vehicle_ids_in_shift: frozenset[str]` (`A_shift`)
  - `cost_rates: CostRateConfig`
  - `planning_config: PlanningConfig` (`planning_mode: COMPLETE|PARTIAL`, `fleet_mode: TARGET|AUTO`, `target_fleet_size`, `max_route_count`, `max_shift_activated_vehicles`, `profile: COST_FOCUSED|BALANCED|DRIVER_PRODUCTIVITY`, `max_extra_cost_paise`, `reference_cost_paise`, `departure_set_utc_s`, `partial_split_mode: EXACT_TINY|BOUNDED_PRACTICAL`, `solver_kind`, `max_canonical_evaluations`, `max_wall_seconds`, `stagnation_evaluations`, `seed`, `qpso_particles`, `qpso_generations`, `qpso_alpha_max`, `qpso_alpha_min`, `qpso_memory_mode`)
- `RunResult`:
  - `run_id: str`
  - `context_hash: str`
  - `result_status: ResultStatus` (`COMPLETE_FEASIBLE`, `PARTIAL_FEASIBLE`, `NO_FEASIBLE_PLAN_FOUND`, `PROVEN_INFEASIBLE`, `SEARCH_BUDGET_EXHAUSTED`, `DATA_INSUFFICIENT`, `INVALID_INPUT`, `INVALID_CONFIG`, `ROAD_ORACLE_FAILURE`, `NUMERIC_RANGE_ERROR`, `PROFILE_REFERENCE_UNAVAILABLE`, `PROFILE_CAP_UNSATISFIED`, `SHIFT_FLEET_POLICY_CONFLICT`)
  - `stop_reason: StopReason` (`CONVERGED_PROVEN_EXACT`, `EVALUATION_BUDGET`, `WALL_LIMIT`, `STAGNATION`, `CANCELLED`, `PRECHECK_REJECTED`, `ORACLE_ERROR`)
  - `proof_scope: ProofScope` (`EXACT_DECLARED_SUBPROBLEM`, `SOUND_PRECHECK_PROOF`, `HEURISTIC_NO_PROOF`, `NONE`)
  - `plan: EvaluatedPlan | None`
  - `telemetry: TelemetryCounters`
  - `diagnostics: list[DiagnosticEntry]`
  - `approximation_flags: dict[str, bool]`

## 3. REST API Contract (`/v1`)
- `GET /v1/healthz` -> Liveness, engine version, database connectivity, and road oracle status.
- `GET /v1/dashboard/summary` -> Real operational metrics from the database (or structured onboarding guidance when empty).
- `POST /v1/depots`, `GET /v1/depots`, `PUT /v1/depots/{id}` -> Depot management with road-network snapping & SCC check.
- `POST /v1/customers`, `GET /v1/customers`, `PUT /v1/customers/{id}`, `POST /v1/customers/{id}/confirm-location` -> Customer and map pin verification workflow.
- `POST /v1/geocoding/search`, `POST /v1/geocoding/reverse` -> Configurable geocoding gateway (Mapbox temporary/permanent or local Vadodara/urban offline gazetteer).
- `POST /v1/orders`, `GET /v1/orders`, `PUT /v1/orders/{id}`, `DELETE /v1/orders/{id}`, `POST /v1/orders/bulk` -> Delivery order management & validation.
- `POST /v1/vehicles`, `GET /v1/vehicles`, `PUT /v1/vehicles/{id}`, `DELETE /v1/vehicles/{id}` -> Homogeneous fleet management.
- `POST /v1/cost-profiles`, `GET /v1/cost-profiles` -> Exact rational cost rate profiles.
- `POST /v1/traffic-scenarios`, `GET /v1/traffic-scenarios` -> Time-dependent speed multipliers & incident overlays.
- `POST /v1/planning-requests`, `GET /v1/planning-requests/{id}`, `POST /v1/planning-requests/{id}/validate` -> Immutable planning snapshot creation & Gatekeeper validation.
- `POST /v1/optimization-runs`, `GET /v1/optimization-runs`, `GET /v1/optimization-runs/{id}`, `POST /v1/optimization-runs/{id}/cancel`, `GET /v1/optimization-runs/{id}/result` -> Asynchronous/synchronous solver job execution, live telemetry progress, cancellation, and result retrieval.
- `GET /v1/plans/{id}`, `GET /v1/plans/{id}/cost-breakdown`, `GET /v1/plans/{id}/unserved`, `POST /v1/plans/{id}/replan`, `GET /v1/shifts/{shift_id}/ledger` -> Certified plan inspection, shift activation ledger, and dynamic replanning with atomic CAS adoption.
- `POST /v1/benchmarks/run` -> Multi-solver comparative benchmark execution under matched budgets and seeds.
