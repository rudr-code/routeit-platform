"""Relational Database Persistence Layer & Atomic Shift Activation Ledger (Phase 5 §8 & Addendum A.2).

Enforces:
- Foreign keys and check constraints on all entities.
- Immutable `shift_activation_ledger` via SQL triggers (`BEFORE UPDATE` and `BEFORE DELETE` raise ABORT).
- Atomic compare-and-swap plan publication (`publish_plan_atomic`), verifying:
  1. Snapshot/plan lineage version (`PLAN_VERSION_CONFLICT`).
  2. Re-reading `A_shift` inside the transaction (`STALE_SNAPSHOT`).
  3. Idempotency key replay (`IDEMPOTENCY_CONFLICT` if content differs, no-op return if identical).
  4. Partition invariant (`served ∩ unserved = ∅` and `served ∪ unserved = N_active`) and money integrity.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator
import uuid

from routeit_engine.contracts.types import EvaluatedPlan
from routeit_roads.oracles import RoadOracle


class PlanVersionConflictError(RuntimeError):
    """Raised when concurrent plan publication fails CAS on expected_parent_version."""


class StaleSnapshotConflictError(RuntimeError):
    """Raised when A_shift in the database changed after candidate evaluation."""


class IdempotencyConflictError(RuntimeError):
    """Raised when an idempotency key is reused with different activation or plan content."""


class LedgerImmutabilityError(RuntimeError):
    """Raised when an UPDATE or DELETE is attempted on shift_activation_ledger."""


SQLITE_SCHEMA_DDL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS depot (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    snapped_node_id TEXT NOT NULL,
    snap_distance_m INTEGER NOT NULL CHECK (snap_distance_m >= 0),
    opening_time_utc_s INTEGER NOT NULL,
    closing_time_utc_s INTEGER,
    return_enabled INTEGER NOT NULL DEFAULT 1,
    return_deadline_utc_s INTEGER,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS vehicle (
    id TEXT PRIMARY KEY,
    depot_id TEXT NOT NULL REFERENCES depot(id),
    code TEXT NOT NULL,
    capacity_units INTEGER NOT NULL CHECK (capacity_units > 0),
    activation_cost_paise INTEGER NOT NULL CHECK (activation_cost_paise >= 0),
    available INTEGER NOT NULL DEFAULT 1,
    return_to_depot INTEGER,
    vehicle_profile TEXT NOT NULL DEFAULT 'urban_van',
    driver_name TEXT NOT NULL DEFAULT '',
    driver_username TEXT NOT NULL DEFAULT '',
    driver_password TEXT NOT NULL DEFAULT '',
    in_transit INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE (depot_id, code)
);

CREATE TABLE IF NOT EXISTS customer (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    snapped_node_id TEXT NOT NULL,
    snap_distance_m INTEGER NOT NULL CHECK (snap_distance_m >= 0),
    address_text TEXT NOT NULL,
    address_source TEXT NOT NULL DEFAULT 'DISPATCHER_TYPED',
    delivery_instructions TEXT NOT NULL DEFAULT '',
    confirmation_status TEXT NOT NULL DEFAULT 'CONFIRMED',
    confirmed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS delivery_order (
    id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customer(id),
    external_ref TEXT NOT NULL UNIQUE,
    demand_units INTEGER NOT NULL CHECK (demand_units > 0),
    service_seconds INTEGER NOT NULL CHECK (service_seconds >= 0),
    window_open_utc_s INTEGER NOT NULL,
    window_close_utc_s INTEGER NOT NULL,
    window_type TEXT NOT NULL CHECK (window_type IN ('HARD', 'SOFT')),
    priority TEXT NOT NULL CHECK (priority IN ('CRITICAL', 'STANDARD', 'FLEXIBLE')),
    status TEXT NOT NULL DEFAULT 'NEW',
    promised_date TEXT NOT NULL DEFAULT '',
    is_overdue INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    CHECK (window_open_utc_s <= window_close_utc_s)
);

CREATE TABLE IF NOT EXISTS cost_profile (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    rates_json TEXT NOT NULL,
    rounding_policy_version TEXT NOT NULL DEFAULT 'ROUND_POLICY_V1_ROUTE_ORDER_EVEN',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS traffic_scenario (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'TIME_PROFILE',
    revision INTEGER NOT NULL DEFAULT 1,
    params_json TEXT NOT NULL,
    scenario_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS planning_request (
    id TEXT PRIMARY KEY,
    shift_id TEXT NOT NULL,
    depot_id TEXT NOT NULL REFERENCES depot(id),
    cost_profile_id TEXT NOT NULL REFERENCES cost_profile(id),
    traffic_scenario_id TEXT NOT NULL REFERENCES traffic_scenario(id),
    planning_mode TEXT NOT NULL,
    fleet_mode TEXT NOT NULL,
    target_fleet_size INTEGER,
    profile TEXT NOT NULL,
    profile_params_json TEXT NOT NULL,
    departure_set_json TEXT NOT NULL,
    instance_snapshot_json TEXT NOT NULL,
    context_hash TEXT NOT NULL,
    validation_report_json TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS optimization_run (
    id TEXT PRIMARY KEY,
    planning_request_id TEXT NOT NULL REFERENCES planning_request(id),
    parent_run_id TEXT REFERENCES optimization_run(id),
    solver_kind TEXT NOT NULL,
    solver_config_json TEXT NOT NULL,
    seed INTEGER NOT NULL,
    job_status TEXT NOT NULL DEFAULT 'QUEUED',
    result_status TEXT,
    stop_reason TEXT,
    proof_scope TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    heartbeat_at TEXT,
    counters_json TEXT,
    diagnostics_json TEXT,
    approximation_flags_json TEXT,
    calibration_json TEXT,
    error_json TEXT,
    plan_id TEXT,
    started_at TEXT,
    finished_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS plan (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES optimization_run(id),
    shift_id TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    parent_plan_id TEXT REFERENCES plan(id),
    status TEXT NOT NULL DEFAULT 'PUBLISHED',
    result_status TEXT NOT NULL,
    context_hash TEXT NOT NULL,
    coverage_critical INTEGER NOT NULL,
    coverage_standard INTEGER NOT NULL,
    coverage_flexible INTEGER NOT NULL,
    total_cost_paise INTEGER NOT NULL,
    idle_seconds INTEGER NOT NULL,
    total_distance_m INTEGER NOT NULL,
    total_paid_seconds INTEGER NOT NULL,
    m_routes_used INTEGER NOT NULL,
    m_new_activated INTEGER NOT NULL,
    m_shift_activated_after INTEGER NOT NULL,
    plan_hash TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS shift_activation_ledger (
    shift_id TEXT NOT NULL,
    vehicle_id TEXT NOT NULL REFERENCES vehicle(id),
    posted_paise INTEGER NOT NULL CHECK (posted_paise >= 0),
    posted_by_plan_id TEXT NOT NULL REFERENCES plan(id),
    idempotency_key TEXT NOT NULL,
    posted_at TEXT NOT NULL,
    PRIMARY KEY (shift_id, vehicle_id),
    UNIQUE (idempotency_key, vehicle_id)
);

CREATE TRIGGER IF NOT EXISTS trg_shift_ledger_no_update
BEFORE UPDATE ON shift_activation_ledger
BEGIN
    SELECT RAISE(ABORT, 'shift_activation_ledger is immutable: UPDATE is forbidden');
END;

CREATE TRIGGER IF NOT EXISTS trg_shift_ledger_no_delete
BEFORE DELETE ON shift_activation_ledger
BEGIN
    SELECT RAISE(ABORT, 'shift_activation_ledger is immutable: DELETE is forbidden');
END;

CREATE TABLE IF NOT EXISTS route (
    id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL REFERENCES plan(id),
    vehicle_id TEXT NOT NULL REFERENCES vehicle(id),
    departure_utc_s INTEGER NOT NULL,
    return_utc_s INTEGER NOT NULL,
    distance_m INTEGER NOT NULL,
    paid_seconds INTEGER NOT NULL,
    idle_seconds INTEGER NOT NULL,
    initial_load_units INTEGER NOT NULL,
    capacity_units INTEGER NOT NULL,
    distance_cost_paise INTEGER NOT NULL,
    time_cost_paise INTEGER NOT NULL,
    sla_cost_paise INTEGER NOT NULL,
    activation_paise INTEGER NOT NULL,
    path_coords_json TEXT NOT NULL,
    UNIQUE (plan_id, vehicle_id)
);

CREATE TABLE IF NOT EXISTS route_stop (
    id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL REFERENCES plan(id),
    route_id TEXT NOT NULL REFERENCES route(id),
    seq INTEGER NOT NULL,
    order_id TEXT NOT NULL REFERENCES delivery_order(id),
    arrival_utc_s INTEGER NOT NULL,
    wait_s INTEGER NOT NULL CHECK (wait_s >= 0),
    service_start_utc_s INTEGER NOT NULL,
    service_end_utc_s INTEGER NOT NULL,
    lateness_s INTEGER NOT NULL CHECK (lateness_s >= 0),
    sla_cost_paise INTEGER NOT NULL CHECK (sla_cost_paise >= 0),
    stop_state TEXT NOT NULL DEFAULT 'PENDING',
    UNIQUE (route_id, seq),
    UNIQUE (plan_id, order_id)
);

CREATE TABLE IF NOT EXISTS unserved_order (
    plan_id TEXT NOT NULL REFERENCES plan(id),
    order_id TEXT NOT NULL REFERENCES delivery_order(id),
    priority TEXT NOT NULL,
    reason TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (plan_id, order_id)
);

CREATE TABLE IF NOT EXISTS cost_breakdown (
    plan_id TEXT PRIMARY KEY REFERENCES plan(id),
    distance_cost_paise INTEGER NOT NULL,
    time_cost_paise INTEGER NOT NULL,
    sla_cost_paise INTEGER NOT NULL,
    operating_cost_paise INTEGER NOT NULL,
    incremental_activation_cost_paise INTEGER NOT NULL,
    incremental_decision_cost_paise INTEGER NOT NULL,
    activation_posted_before_paise INTEGER NOT NULL,
    activation_posted_after_paise INTEGER NOT NULL,
    sunk_cost_before_paise INTEGER NOT NULL,
    shift_forecast_total_after_paise INTEGER NOT NULL,
    rounding_policy_version TEXT NOT NULL,
    ledger_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS replan_event (
    id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL REFERENCES plan(id),
    shift_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    occurred_at_utc_s INTEGER NOT NULL,
    state TEXT NOT NULL,
    snapshot_version INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    result_plan_id TEXT REFERENCES plan(id),
    rejection_reason TEXT,
    created_at TEXT NOT NULL
);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RouteItDatabase:
    """Transactional relational repository for Route.it."""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self.db_path = str(db_path)
        self._persistent_conn: sqlite3.Connection | None = None
        if self.db_path == ":memory:":
            self._persistent_conn = sqlite3.connect(
                ":memory:", check_same_thread=False, isolation_level=None
            )
            self._persistent_conn.row_factory = sqlite3.Row
            self._persistent_conn.executescript(SQLITE_SCHEMA_DDL)
        else:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            with self.connection() as conn:
                conn.executescript(SQLITE_SCHEMA_DDL)
                for col_ddl in [
                    "ALTER TABLE vehicle ADD COLUMN driver_name TEXT NOT NULL DEFAULT ''",
                    "ALTER TABLE vehicle ADD COLUMN driver_username TEXT NOT NULL DEFAULT ''",
                    "ALTER TABLE vehicle ADD COLUMN driver_password TEXT NOT NULL DEFAULT ''",
                    "ALTER TABLE vehicle ADD COLUMN in_transit INTEGER NOT NULL DEFAULT 0",
                    "ALTER TABLE delivery_order ADD COLUMN promised_date TEXT NOT NULL DEFAULT ''",
                    "ALTER TABLE delivery_order ADD COLUMN is_overdue INTEGER NOT NULL DEFAULT 0",
                ]:
                    try:
                        conn.execute(col_ddl)
                    except Exception:
                        pass

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        if self._persistent_conn is not None:
            self._persistent_conn.execute("PRAGMA foreign_keys = ON;")
            yield self._persistent_conn
        else:
            conn = sqlite3.connect(
                self.db_path, timeout=15.0, check_same_thread=False, isolation_level=None
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON;")
            try:
                yield conn
            finally:
                conn.close()

    def get_shift_activated_vehicles(self, shift_id: str) -> dict[str, int]:
        """Return `{vehicle_id: posted_paise}` from `shift_activation_ledger` for `shift_id`."""
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT vehicle_id, posted_paise FROM shift_activation_ledger WHERE shift_id = ? ORDER BY vehicle_id",
                (shift_id,),
            ).fetchall()
            return {row["vehicle_id"]: int(row["posted_paise"]) for row in rows}

    def get_shift_ledger_rows(self, shift_id: str) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM shift_activation_ledger WHERE shift_id = ? ORDER BY posted_at, vehicle_id",
                (shift_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def publish_plan_atomic(
        self,
        *,
        run_id: str,
        shift_id: str,
        evaluated_plan: EvaluatedPlan,
        result_status: str,
        expected_activated_in_shift: frozenset[str],
        idempotency_key: str,
        parent_plan_id: str | None = None,
        expected_parent_version: int | None = None,
        oracle: RoadOracle | None = None,
        simulate_failure_after_ledger_insert: bool = False,
    ) -> dict[str, Any]:
        """Execute the 6-step atomic publication & ledger transaction (Phase 5 Addendum A.2)."""
        with self.connection() as conn:
            if conn.in_transaction:
                conn.execute("ROLLBACK;")
            try:
                conn.execute("BEGIN IMMEDIATE;")

                # Step 0: Check idempotency key replay first (T-ACT-6)
                existing_plan = conn.execute(
                    "SELECT * FROM plan WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
                if existing_plan is not None:
                    if (
                        existing_plan["plan_hash"] == evaluated_plan.plan_hash
                        and existing_plan["shift_id"] == shift_id
                        and int(existing_plan["total_cost_paise"]) == evaluated_plan.c_dec_paise
                    ):
                        conn.execute("COMMIT;")
                        return dict(existing_plan)
                    conn.execute("ROLLBACK;")
                    raise IdempotencyConflictError(
                        f"IDEMPOTENCY_CONFLICT: Key {idempotency_key} already used with different plan content"
                    )

                # Step 1 & 2: Compare-and-swap on parent plan version (T-ACT-7)
                new_version = 1
                if parent_plan_id is not None:
                    parent_row = conn.execute(
                        "SELECT id, version, status FROM plan WHERE id = ?",
                        (parent_plan_id,),
                    ).fetchone()
                    if parent_row is None:
                        conn.execute("ROLLBACK;")
                        raise PlanVersionConflictError(f"Parent plan {parent_plan_id} not found")
                    if (
                        expected_parent_version is not None
                        and int(parent_row["version"]) != expected_parent_version
                    ):
                        conn.execute("ROLLBACK;")
                        raise PlanVersionConflictError(
                            f"PLAN_VERSION_CONFLICT: expected version {expected_parent_version}, got {parent_row['version']}"
                        )
                    if parent_row["status"] != "PUBLISHED":
                        conn.execute("ROLLBACK;")
                        raise PlanVersionConflictError(
                            f"PLAN_VERSION_CONFLICT: parent plan {parent_plan_id} is already {parent_row['status']}"
                        )
                    new_version = int(parent_row["version"]) + 1
                    conn.execute(
                        "UPDATE plan SET status = 'SUPERSEDED' WHERE id = ? AND status = 'PUBLISHED'",
                        (parent_plan_id,),
                    )
                else:
                    existing_pub = conn.execute(
                        "SELECT id, version FROM plan WHERE shift_id = ? AND status = 'PUBLISHED'",
                        (shift_id,),
                    ).fetchone()
                    if existing_pub is not None:
                        if expected_parent_version is not None and int(existing_pub["version"]) != expected_parent_version:
                            conn.execute("ROLLBACK;")
                            raise PlanVersionConflictError(
                                "PLAN_VERSION_CONFLICT: Another plan was published concurrently for this shift"
                            )
                        new_version = int(existing_pub["version"]) + 1
                        conn.execute(
                            "UPDATE plan SET status = 'SUPERSEDED' WHERE id = ?",
                            (existing_pub["id"],),
                        )

                # Step 3: Re-read A_shift inside the transaction (T-ACT-7, Addendum A.2 Step 3)
                current_ledger_rows = conn.execute(
                    "SELECT vehicle_id, posted_paise FROM shift_activation_ledger WHERE shift_id = ?",
                    (shift_id,),
                ).fetchall()
                current_a_shift = frozenset(r["vehicle_id"] for r in current_ledger_rows)
                if current_a_shift != expected_activated_in_shift:
                    conn.execute("ROLLBACK;")
                    raise StaleSnapshotConflictError(
                        f"STALE_SNAPSHOT: shift_activation_ledger changed during optimization "
                        f"(expected {sorted(expected_activated_in_shift)}, found {sorted(current_a_shift)})"
                    )

                plan_id = str(uuid.uuid4())
                now = _now_iso()

                # Step 5a: Insert the plan row first so FK from shift_activation_ledger -> plan(id) is satisfied
                conn.execute(
                    """
                    INSERT INTO plan (
                        id, run_id, shift_id, version, parent_plan_id, status, result_status,
                        context_hash, coverage_critical, coverage_standard, coverage_flexible,
                        total_cost_paise, idle_seconds, total_distance_m, total_paid_seconds,
                        m_routes_used, m_new_activated, m_shift_activated_after,
                        plan_hash, idempotency_key, created_at
                    ) VALUES (?, ?, ?, ?, ?, 'PUBLISHED', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        plan_id,
                        run_id,
                        shift_id,
                        new_version,
                        parent_plan_id,
                        result_status,
                        evaluated_plan.context_hash,
                        evaluated_plan.coverage_vector[0],
                        evaluated_plan.coverage_vector[1],
                        evaluated_plan.coverage_vector[2],
                        evaluated_plan.c_dec_paise,
                        evaluated_plan.idle_waiting_seconds,
                        evaluated_plan.total_distance_m,
                        evaluated_plan.total_paid_seconds,
                        evaluated_plan.m_routes_used,
                        evaluated_plan.m_new_activated,
                        evaluated_plan.m_shift_activated_after,
                        evaluated_plan.plan_hash,
                        idempotency_key,
                        now,
                    ),
                )

                # Step 4: Insert ledger rows for vehicles in active \ A_shift (Addendum A.2 Step 4)
                newly_posted_sum = 0
                for vid in evaluated_plan.newly_activated_vehicle_ids:
                    fee_paise = evaluated_plan.ledger.vehicle_activation_lines_paise[vid]
                    conn.execute(
                        """
                        INSERT INTO shift_activation_ledger (
                            shift_id, vehicle_id, posted_paise, posted_by_plan_id, idempotency_key, posted_at
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (shift_id, vid, fee_paise, plan_id, idempotency_key, now),
                    )
                    newly_posted_sum += fee_paise

                # Test hook for T-ACT-9 (forced failure after ledger insert, before COMMIT)
                if simulate_failure_after_ledger_insert:
                    raise RuntimeError("Simulated mid-transaction failure after ledger insert (T-ACT-9)")

                # Step 5b: Insert routes, stops, unserved_order, and cost_breakdown
                for r in evaluated_plan.routes:
                    route_id = str(uuid.uuid4())
                    path_coords: list[list[float]] = []
                    if oracle is not None:
                        for leg in r.legs:
                            geom = oracle.path(leg.from_node_id, leg.to_node_id, leg.departure_utc_s)
                            for lon, lat in geom.coordinates_lon_lat:
                                pt = [lon, lat]
                                if not path_coords or path_coords[-1] != pt:
                                    path_coords.append(pt)

                    conn.execute(
                        """
                        INSERT INTO route (
                            id, plan_id, vehicle_id, departure_utc_s, return_utc_s,
                            distance_m, paid_seconds, idle_seconds, initial_load_units, capacity_units,
                            distance_cost_paise, time_cost_paise, sla_cost_paise, activation_paise, path_coords_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            route_id,
                            plan_id,
                            r.vehicle_id,
                            r.departure_utc_s,
                            r.completion_utc_s,
                            r.total_distance_m,
                            r.paid_duration_seconds,
                            r.idle_waiting_seconds,
                            r.initial_load_units,
                            r.capacity_units,
                            r.distance_cost_paise,
                            r.time_cost_paise,
                            r.sla_cost_paise,
                            r.incremental_activation_cost_paise,
                            json.dumps(path_coords),
                        ),
                    )

                    for s in r.stops:
                        conn.execute(
                            """
                            INSERT INTO route_stop (
                                id, plan_id, route_id, seq, order_id,
                                arrival_utc_s, wait_s, service_start_utc_s, service_end_utc_s,
                                lateness_s, sla_cost_paise, stop_state
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                str(uuid.uuid4()),
                                plan_id,
                                route_id,
                                s.seq,
                                s.order_id,
                                s.arrival_utc_s,
                                s.wait_seconds,
                                s.service_start_utc_s,
                                s.service_completion_utc_s,
                                s.lateness_seconds,
                                s.sla_cost_paise,
                                "LOCKED" if s.is_locked else "PENDING",
                            ),
                        )

                for u in evaluated_plan.unserved_orders:
                    conn.execute(
                        """
                        INSERT INTO unserved_order (plan_id, order_id, priority, reason, detail)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (plan_id, u.order_id, u.priority.value, u.reason.value, u.detail),
                    )

                ldg = evaluated_plan.ledger
                ledger_detail = {
                    "route_distance_lines_paise": ldg.route_distance_lines_paise,
                    "route_time_lines_paise": ldg.route_time_lines_paise,
                    "order_sla_lines_paise": ldg.order_sla_lines_paise,
                    "vehicle_activation_lines_paise": ldg.vehicle_activation_lines_paise,
                    "max_rounding_deviation_paise": ldg.max_rounding_deviation_paise.to_dict(),
                }
                conn.execute(
                    """
                    INSERT INTO cost_breakdown (
                        plan_id, distance_cost_paise, time_cost_paise, sla_cost_paise,
                        operating_cost_paise, incremental_activation_cost_paise,
                        incremental_decision_cost_paise, activation_posted_before_paise,
                        activation_posted_after_paise, sunk_cost_before_paise,
                        shift_forecast_total_after_paise, rounding_policy_version, ledger_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        plan_id,
                        ldg.distance_cost_paise,
                        ldg.time_cost_paise,
                        ldg.sla_cost_paise,
                        ldg.operating_cost_paise,
                        ldg.incremental_activation_cost_paise,
                        ldg.incremental_decision_cost_paise,
                        ldg.activation_posted_before_paise,
                        ldg.activation_posted_after_paise,
                        ldg.sunk_cost_before_paise,
                        ldg.shift_forecast_total_after_paise,
                        ldg.rounding_policy_version,
                        json.dumps(ledger_detail),
                    ),
                )

                # Step 6: Verify Consistency Rules 1, 4, 7 before COMMIT (Phase 5 §8.7 & Addendum A.2)
                if newly_posted_sum != ldg.incremental_activation_cost_paise:
                    raise RuntimeError("Consistency Rule 7 failed: ledger posted sum != fleet component")
                if (
                    ldg.distance_cost_paise
                    + ldg.time_cost_paise
                    + ldg.sla_cost_paise
                    + ldg.incremental_activation_cost_paise
                    != ldg.incremental_decision_cost_paise
                ):
                    raise RuntimeError("Consistency Rule 4 failed: component sum != total decision cost")

                conn.execute(
                    "UPDATE optimization_run SET plan_id = ? WHERE id = ?",
                    (plan_id, run_id),
                )

                conn.execute("COMMIT;")
                row = conn.execute("SELECT * FROM plan WHERE id = ?", (plan_id,)).fetchone()
                return dict(row)
            except sqlite3.IntegrityError as exc:
                if conn.in_transaction:
                    conn.execute("ROLLBACK;")
                if "idempotency_key" in str(exc):
                    raise IdempotencyConflictError(str(exc)) from exc
                raise
            except Exception:
                if conn.in_transaction:
                    conn.execute("ROLLBACK;")
                raise
