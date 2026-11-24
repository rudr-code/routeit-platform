-- Route.it Phase 5 v0.2 & Addendum A Normative PostgreSQL + PostGIS Schema
-- Enforces data integrity, partition invariants, and immutable shift_activation_ledger.

CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TYPE window_type AS ENUM ('HARD', 'SOFT');
CREATE TYPE priority_tier AS ENUM ('CRITICAL', 'STANDARD', 'FLEXIBLE');
CREATE TYPE job_status AS ENUM (
    'QUEUED', 'VALIDATING', 'RUNNING', 'CANCELLING',
    'COMPLETED', 'FAILED', 'CANCELLED', 'TIMED_OUT'
);

CREATE TABLE road_network_ref (
    id              uuid PRIMARY KEY,
    source          text NOT NULL,
    extract_date    date NOT NULL,
    graph_hash      text NOT NULL UNIQUE,
    artifact_path   text NOT NULL,
    node_count      integer NOT NULL CHECK (node_count > 0),
    edge_count      integer NOT NULL CHECK (edge_count > 0),
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE depot (
    id                      uuid PRIMARY KEY,
    name                    text NOT NULL,
    lat                     double precision NOT NULL,
    lon                     double precision NOT NULL,
    location                geography(Point, 4326),
    snapped_node_id         text NOT NULL,
    snap_distance_m         integer NOT NULL CHECK (snap_distance_m >= 0),
    opening_time_utc_s      bigint NOT NULL,
    closing_time_utc_s      bigint,
    return_enabled          boolean NOT NULL DEFAULT true,
    return_deadline_utc_s   bigint,
    created_at              timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE vehicle (
    id                      uuid PRIMARY KEY,
    depot_id                uuid NOT NULL REFERENCES depot(id),
    code                    text NOT NULL,
    capacity_units          integer NOT NULL CHECK (capacity_units > 0),
    activation_cost_paise   bigint NOT NULL CHECK (activation_cost_paise >= 0),
    available               boolean NOT NULL DEFAULT true,
    return_to_depot         boolean,
    vehicle_profile         text NOT NULL DEFAULT 'urban_van',
    created_at              timestamptz NOT NULL DEFAULT now(),
    UNIQUE (depot_id, code)
);

CREATE TABLE customer (
    id                      uuid PRIMARY KEY,
    name                    text NOT NULL,
    lat                     double precision NOT NULL,
    lon                     double precision NOT NULL,
    location                geography(Point, 4326),
    snapped_node_id         text NOT NULL,
    snap_distance_m         integer NOT NULL CHECK (snap_distance_m >= 0),
    address_text            text NOT NULL,
    address_source          text NOT NULL DEFAULT 'DISPATCHER_TYPED',
    delivery_instructions   text NOT NULL DEFAULT '',
    confirmation_status     text NOT NULL DEFAULT 'CONFIRMED',
    confirmed_at            timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE delivery_order (
    id                      uuid PRIMARY KEY,
    customer_id             uuid NOT NULL REFERENCES customer(id),
    external_ref            text NOT NULL UNIQUE,
    demand_units            integer NOT NULL CHECK (demand_units > 0),
    service_seconds         integer NOT NULL CHECK (service_seconds >= 0),
    window_open_utc_s       bigint NOT NULL,
    window_close_utc_s      bigint NOT NULL,
    window_type             window_type NOT NULL,
    priority                priority_tier NOT NULL,
    status                  text NOT NULL DEFAULT 'NEW',
    created_at              timestamptz NOT NULL DEFAULT now(),
    CHECK (window_open_utc_s <= window_close_utc_s)
);

CREATE TABLE cost_profile (
    id                                  uuid PRIMARY KEY,
    name                                text NOT NULL,
    version                             integer NOT NULL DEFAULT 1,
    distance_rate_paise_per_km_json     jsonb NOT NULL,
    time_rate_paise_per_hour_json       jsonb NOT NULL,
    critical_sla_paise_per_min_json     jsonb NOT NULL,
    standard_sla_paise_per_min_json     jsonb NOT NULL,
    flexible_sla_paise_per_min_json     jsonb NOT NULL,
    rounding_policy_version             text NOT NULL DEFAULT 'ROUND_POLICY_V1_ROUTE_ORDER_EVEN',
    created_at                          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE traffic_scenario (
    id              uuid PRIMARY KEY,
    name            text NOT NULL,
    kind            text NOT NULL DEFAULT 'TIME_PROFILE',
    revision        integer NOT NULL DEFAULT 1,
    params_json     jsonb NOT NULL,
    scenario_hash   text NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE planning_request (
    id                      uuid PRIMARY KEY,
    shift_id                uuid NOT NULL,
    depot_id                uuid NOT NULL REFERENCES depot(id),
    cost_profile_id         uuid NOT NULL REFERENCES cost_profile(id),
    traffic_scenario_id     uuid NOT NULL REFERENCES traffic_scenario(id),
    planning_mode           text NOT NULL,
    fleet_mode              text NOT NULL,
    target_fleet_size       integer,
    profile                 text NOT NULL,
    profile_params_json     jsonb NOT NULL,
    departure_set_json      jsonb NOT NULL,
    instance_snapshot_json  jsonb NOT NULL,
    context_hash            char(64) NOT NULL,
    validation_report_json  jsonb NOT NULL,
    status                  text NOT NULL,
    created_at              timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE optimization_run (
    id                      uuid PRIMARY KEY,
    planning_request_id     uuid NOT NULL REFERENCES planning_request(id),
    parent_run_id           uuid REFERENCES optimization_run(id),
    solver_kind             text NOT NULL,
    solver_config_json      jsonb NOT NULL,
    seed                    bigint NOT NULL,
    job_status              job_status NOT NULL DEFAULT 'QUEUED',
    result_status           text,
    stop_reason             text,
    proof_scope             text,
    cancel_requested        boolean NOT NULL DEFAULT false,
    heartbeat_at            timestamptz,
    counters_json           jsonb,
    diagnostics_json        jsonb,
    approximation_flags_json jsonb,
    calibration_json        jsonb,
    error_json              jsonb,
    plan_id                 uuid,
    started_at              timestamptz,
    finished_at             timestamptz,
    created_at              timestamptz NOT NULL DEFAULT now(),
    CHECK ((job_status = 'COMPLETED') = (result_status IS NOT NULL))
);

CREATE TABLE plan (
    id                          uuid PRIMARY KEY,
    run_id                      uuid NOT NULL REFERENCES optimization_run(id),
    shift_id                    uuid NOT NULL,
    version                     integer NOT NULL DEFAULT 1,
    parent_plan_id              uuid REFERENCES plan(id),
    status                      text NOT NULL DEFAULT 'PUBLISHED',
    result_status               text NOT NULL,
    context_hash                char(64) NOT NULL,
    coverage_critical           integer NOT NULL,
    coverage_standard           integer NOT NULL,
    coverage_flexible           integer NOT NULL,
    total_cost_paise            bigint NOT NULL,
    idle_seconds                integer NOT NULL,
    total_distance_m            integer NOT NULL,
    total_paid_seconds          integer NOT NULL,
    m_routes_used               integer NOT NULL,
    m_new_activated             integer NOT NULL,
    m_shift_activated_after     integer NOT NULL,
    plan_hash                   char(64) NOT NULL,
    created_at                  timestamptz NOT NULL DEFAULT now()
);

-- Normative Shift Activation Ledger (Phase 5 v0.2 Addendum A.2)
CREATE TABLE shift_activation_ledger (
    shift_id            uuid NOT NULL,
    vehicle_id          uuid NOT NULL REFERENCES vehicle(id),
    posted_paise        bigint NOT NULL CHECK (posted_paise >= 0),
    posted_by_plan_id   uuid NOT NULL REFERENCES plan(id),
    idempotency_key     text NOT NULL,
    posted_at           timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (shift_id, vehicle_id),
    UNIQUE (idempotency_key, vehicle_id)
);

CREATE OR REPLACE FUNCTION forbid_shift_ledger_mutation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'shift_activation_ledger is immutable: UPDATE and DELETE are forbidden';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_shift_activation_ledger_immutable
BEFORE UPDATE OR DELETE ON shift_activation_ledger
FOR EACH ROW EXECUTE FUNCTION forbid_shift_ledger_mutation();

CREATE TABLE route (
    id                                  uuid PRIMARY KEY,
    plan_id                             uuid NOT NULL REFERENCES plan(id),
    vehicle_id                          uuid NOT NULL REFERENCES vehicle(id),
    departure_utc_s                     bigint NOT NULL,
    return_utc_s                        bigint NOT NULL,
    distance_m                          integer NOT NULL,
    paid_seconds                        integer NOT NULL,
    idle_seconds                        integer NOT NULL,
    initial_load_units                  integer NOT NULL,
    capacity_units                      integer NOT NULL,
    distance_cost_paise                 bigint NOT NULL,
    time_cost_paise                     bigint NOT NULL,
    sla_cost_paise                      bigint NOT NULL,
    activation_paise                    bigint NOT NULL, -- display-only newly posted amount
    path_coords_json                    jsonb NOT NULL,
    UNIQUE (plan_id, vehicle_id)
);

CREATE TABLE route_stop (
    id                      uuid PRIMARY KEY,
    plan_id                 uuid NOT NULL REFERENCES plan(id),
    route_id                uuid NOT NULL REFERENCES route(id),
    seq                     integer NOT NULL,
    order_id                uuid NOT NULL REFERENCES delivery_order(id),
    arrival_utc_s           bigint NOT NULL,
    wait_s                  integer NOT NULL CHECK (wait_s >= 0),
    service_start_utc_s     bigint NOT NULL,
    service_end_utc_s       bigint NOT NULL,
    lateness_s              integer NOT NULL CHECK (lateness_s >= 0),
    sla_cost_paise          bigint NOT NULL CHECK (sla_cost_paise >= 0),
    stop_state              text NOT NULL DEFAULT 'PENDING',
    UNIQUE (route_id, seq),
    UNIQUE (plan_id, order_id)
);

CREATE TABLE unserved_order (
    plan_id     uuid NOT NULL REFERENCES plan(id),
    order_id    uuid NOT NULL REFERENCES delivery_order(id),
    priority    text NOT NULL,
    reason      text NOT NULL,
    detail      text NOT NULL DEFAULT '',
    PRIMARY KEY (plan_id, order_id)
);

CREATE TABLE cost_breakdown (
    plan_id                             uuid PRIMARY KEY REFERENCES plan(id),
    distance_cost_paise                 bigint NOT NULL,
    time_cost_paise                     bigint NOT NULL,
    sla_cost_paise                      bigint NOT NULL,
    operating_cost_paise                bigint NOT NULL,
    incremental_activation_cost_paise   bigint NOT NULL,
    incremental_decision_cost_paise     bigint NOT NULL,
    activation_posted_before_paise      bigint NOT NULL,
    activation_posted_after_paise       bigint NOT NULL,
    sunk_cost_before_paise              bigint NOT NULL,
    shift_forecast_total_after_paise    bigint NOT NULL,
    rounding_policy_version             text NOT NULL,
    ledger_json                         jsonb NOT NULL
);

CREATE TABLE replan_event (
    id                  uuid PRIMARY KEY,
    plan_id             uuid NOT NULL REFERENCES plan(id),
    shift_id            uuid NOT NULL,
    kind                text NOT NULL,
    occurred_at_utc_s   bigint NOT NULL,
    state               text NOT NULL,
    snapshot_version    integer NOT NULL,
    payload_json        jsonb NOT NULL,
    result_plan_id      uuid REFERENCES plan(id),
    rejection_reason    text,
    created_at          timestamptz NOT NULL DEFAULT now()
);
