"""Comprehensive Backend API, Shift Activation Ledger (`T-ACT-5..11`), and End-to-End Integration Tests."""

from __future__ import annotations

import unittest
from fastapi.testclient import TestClient

from app.main import create_app
from app.persistence.database import (
    IdempotencyConflictError,
    PlanVersionConflictError,
    StaleSnapshotConflictError,
)
from routeit_engine.context.evaluation_context import EvaluationContext
from routeit_engine.contracts.types import (
    CostRateConfig,
    DepotSpec,
    ExactRate,
    OrderSpec,
    PlanningConfig,
    PriorityTier,
    SolveRequest,
    VehicleSpec,
    WindowType,
)
from routeit_engine.evaluator.canonical import evaluate_plan
from routeit_roads.default_network import create_default_profile_graph_oracle


class TestBackendAPIAndShiftLedger(unittest.TestCase):
    def setUp(self) -> None:
        self.app = create_app(":memory:")
        self.client = TestClient(self.app)
        self.db = self.app.state.db

    def test_health_and_end_to_end_workflow_with_replanning(self) -> None:
        # 1. Health check
        r_health = self.client.get("/v1/healthz")
        self.assertEqual(r_health.status_code, 200)
        self.assertEqual(r_health.json()["status"], "ok")

        # 2. Empty dashboard check (no fake statistics!)
        r_dash0 = self.client.get("/v1/dashboard/summary")
        self.assertEqual(r_dash0.status_code, 200)
        self.assertTrue(r_dash0.json()["is_empty"])
        self.assertEqual(r_dash0.json()["counts"]["orders"], 0)

        # 3. Seed Vadodara pilot or create entities via API
        r_seed = self.client.post("/v1/demo/seed-vadodara")
        self.assertEqual(r_seed.status_code, 201)
        seeded = r_seed.json()
        depot_id = seeded["depot_id"]
        order_ids = seeded["order_ids"]
        vehicle_ids = seeded["vehicle_ids"]
        cp_id = seeded["cost_profile_id"]
        ts_id = seeded["traffic_scenario_id"]
        base_t = seeded["base_departure_utc_s"]

        # 4. Geocoding & reverse geocoding
        r_geo = self.client.post("/v1/geocoding/search", json={"query": "Fatehgunj"})
        self.assertEqual(r_geo.status_code, 200)
        self.assertGreaterEqual(len(r_geo.json()["results"]), 1)

        r_rev = self.client.post("/v1/geocoding/reverse", json={"lat": 22.3081, "lon": 73.1812})
        self.assertEqual(r_rev.status_code, 200)
        self.assertEqual(r_rev.json()["status"], "OK")
        self.assertTrue(r_rev.json()["in_depot_scc"])

        # 5. Create planning request snapshot
        r_pr = self.client.post(
            "/v1/planning-requests",
            json={
                "depot_id": depot_id,
                "order_ids": order_ids,
                "vehicle_ids": vehicle_ids,
                "cost_profile_id": cp_id,
                "traffic_scenario_id": ts_id,
                "planning_mode": "COMPLETE",
                "fleet_mode": "AUTO",
                "profile": "COST_FOCUSED",
                "departure_set_utc_s": [base_t],
            },
        )
        self.assertEqual(r_pr.status_code, 201)
        pr_data = r_pr.json()
        pr_id = pr_data["planning_request_id"]
        shift_id = pr_data["shift_id"]
        self.assertEqual(pr_data["status"], "VALIDATED")

        # 6. Execute optimization run with QPSO (Q-HGALS 5.0)
        r_run = self.client.post(
            "/v1/optimization-runs",
            json={
                "planning_request_id": pr_id,
                "solver_kind": "QPSO",
                "max_canonical_evaluations": 120,
                "qpso_particles": 8,
                "qpso_generations": 8,
                "seed": 42,
                "execute_synchronously": True,
            },
        )
        self.assertEqual(r_run.status_code, 202)
        run_data = r_run.json()
        self.assertEqual(run_data["job_status"], "COMPLETED")
        self.assertEqual(run_data["result_status"], "COMPLETE_FEASIBLE")
        plan_id = run_data["plan_id"]
        self.assertIsNotNone(plan_id)

        # 7. Retrieve full plan, cost breakdown, and shift activation ledger
        r_plan = self.client.get(f"/v1/plans/{plan_id}")
        self.assertEqual(r_plan.status_code, 200)
        plan_json = r_plan.json()
        self.assertGreaterEqual(len(plan_json["routes"]), 1)
        self.assertEqual(len(plan_json["unserved_orders"]), 0)

        r_ledger = self.client.get(f"/v1/shifts/{shift_id}/ledger")
        self.assertEqual(r_ledger.status_code, 200)
        ledger_before = r_ledger.json()
        self.assertEqual(ledger_before["activated_vehicle_count"], plan_json["m_new_activated"])
        posted_before = ledger_before["total_posted_activation_paise"]
        self.assertGreater(posted_before, 0)

        # 8. Trigger dynamic replanning (T-ACT-5: already-activated vehicles are NOT re-charged!)
        r_replan = self.client.post(
            f"/v1/plans/{plan_id}/replan",
            json={
                "t0_utc_s": base_t + 900,
                "edge_multipliers_override": {"E_N_SAYAJIGUNJ_TO_N_FATEHGUNJ": 0.4},
                "min_cost_improvement_paise": 0,
            },
        )
        self.assertEqual(r_replan.status_code, 200)
        rep_json = r_replan.json()
        self.assertIn("vehicle_states", rep_json)

        # Verify shift ledger has no duplicate charges for already-activated vehicles
        r_ledger_after = self.client.get(f"/v1/shifts/{shift_id}/ledger").json()
        self.assertGreaterEqual(r_ledger_after["total_posted_activation_paise"], posted_before)

        # 9. Run multi-solver benchmark comparison
        r_bench = self.client.post(
            "/v1/benchmarks/run",
            json={
                "planning_request_id": pr_id,
                "solvers": ["CONSTRUCTIVE", "LOCAL_SEARCH", "ALNS", "QPSO"],
                "max_canonical_evaluations": 60,
                "seeds": [42],
            },
        )
        self.assertEqual(r_bench.status_code, 200)
        bench_data = r_bench.json()
        self.assertEqual(len(bench_data["results"]), 4)

    def test_t_act_6_to_9_ledger_immutability_idempotency_cas_and_rollback(self) -> None:
        """Verify T-ACT-6 (idempotency), T-ACT-7 (CAS conflict), T-ACT-8 (trigger immutability), and T-ACT-9 (rollback)."""
        r_seed = self.client.post("/v1/demo/seed-vadodara").json()
        r_pr = self.client.post(
            "/v1/planning-requests",
            json={
                "depot_id": r_seed["depot_id"],
                "order_ids": r_seed["order_ids"][:2],
                "vehicle_ids": r_seed["vehicle_ids"][:2],
                "cost_profile_id": r_seed["cost_profile_id"],
                "traffic_scenario_id": r_seed["traffic_scenario_id"],
                "planning_mode": "COMPLETE",
                "fleet_mode": "AUTO",
                "profile": "COST_FOCUSED",
                "departure_set_utc_s": [r_seed["base_departure_utc_s"]],
            },
        ).json()
        shift_id = r_pr["shift_id"]
        pr_id = r_pr["planning_request_id"]

        # Create a queued run
        r_run = self.client.post(
            "/v1/optimization-runs",
            json={
                "planning_request_id": pr_id,
                "solver_kind": "CONSTRUCTIVE",
                "execute_synchronously": True,
                "idempotency_key": "idem_test_key_1",
            },
        ).json()
        plan_id = r_run["plan_id"]
        self.assertIsNotNone(plan_id)

        # T-ACT-8: UPDATE or DELETE on shift_activation_ledger MUST be rejected by SQLite trigger!
        with self.db.connection() as conn:
            with self.assertRaises(Exception) as ctx_upd:
                conn.execute("UPDATE shift_activation_ledger SET posted_paise = 0 WHERE shift_id = ?", (shift_id,))
            self.assertIn("immutable", str(ctx_upd.exception))

            with self.assertRaises(Exception) as ctx_del:
                conn.execute("DELETE FROM shift_activation_ledger WHERE shift_id = ?", (shift_id,))
            self.assertIn("immutable", str(ctx_del.exception))

        # T-ACT-9: Forced failure after ledger insert before COMMIT leaves zero partial ledger rows
        shift_rollback = "shift_rollback_test"
        oracle = create_default_profile_graph_oracle()
        with self.db.connection() as conn:
            v_row = conn.execute("SELECT * FROM vehicle WHERE id = ?", (r_seed["vehicle_ids"][0],)).fetchone()
            o_row = conn.execute(
                "SELECT o.*, c.snapped_node_id FROM delivery_order o JOIN customer c ON o.customer_id = c.id WHERE o.id = ?",
                (r_seed["order_ids"][0],),
            ).fetchone()

        depot = DepotSpec(r_seed["depot_id"], "N_DEPOT_ALKAPURI", True)
        order = OrderSpec(o_row["id"], o_row["snapped_node_id"], 10, 60, 0, 2000000000, WindowType.SOFT, PriorityTier.CRITICAL)
        veh = VehicleSpec(v_row["id"], 60, 30000, True)
        rates = CostRateConfig(
            ExactRate(800, 1), ExactRate(10000, 1), ExactRate(1000, 1), ExactRate(500, 1), ExactRate(200, 1)
        )
        s_req = SolveRequest("REQ_RB", shift_rollback, depot, (order,), (veh,), rates, PlanningConfig(departure_set_utc_s=(r_seed["base_departure_utc_s"],)))
        ctx = EvaluationContext.build(s_req, oracle.identity())
        ev_plan = evaluate_plan(route_specs=[(veh.id, r_seed["base_departure_utc_s"], [order.id])], ctx=ctx, oracle=oracle)

        with self.assertRaises(RuntimeError):
            self.db.publish_plan_atomic(
                run_id=r_run["run_id"],
                shift_id=shift_rollback,
                evaluated_plan=ev_plan,
                result_status="COMPLETE_FEASIBLE",
                expected_activated_in_shift=frozenset(),
                idempotency_key="idem_rb_1",
                simulate_failure_after_ledger_insert=True,
            )
        # Verify zero ledger rows remain for shift_rollback!
        self.assertEqual(len(self.db.get_shift_ledger_rows(shift_rollback)), 0)

        # Now publish cleanly and verify T-ACT-6 (idempotency replay returns same plan, different content raises IdempotencyConflictError)
        pub1 = self.db.publish_plan_atomic(
            run_id=r_run["run_id"],
            shift_id=shift_rollback,
            evaluated_plan=ev_plan,
            result_status="COMPLETE_FEASIBLE",
            expected_activated_in_shift=frozenset(),
            idempotency_key="idem_rb_clean",
        )
        pub_replay = self.db.publish_plan_atomic(
            run_id=r_run["run_id"],
            shift_id=shift_rollback,
            evaluated_plan=ev_plan,
            result_status="COMPLETE_FEASIBLE",
            expected_activated_in_shift=frozenset(),
            idempotency_key="idem_rb_clean",
        )
        self.assertEqual(pub1["id"], pub_replay["id"])
        self.assertEqual(len(self.db.get_shift_ledger_rows(shift_rollback)), 1)

        with self.assertRaises(IdempotencyConflictError):
            self.db.publish_plan_atomic(
                run_id=r_run["run_id"],
                shift_id="different_shift_id",
                evaluated_plan=ev_plan,
                result_status="COMPLETE_FEASIBLE",
                expected_activated_in_shift=frozenset(),
                idempotency_key="idem_rb_clean",
            )

        # T-ACT-7: Stale A_shift or wrong parent version raises StaleSnapshotConflictError / PlanVersionConflictError
        with self.assertRaises(StaleSnapshotConflictError):
            self.db.publish_plan_atomic(
                run_id=r_run["run_id"],
                shift_id=shift_rollback,
                evaluated_plan=ev_plan,
                result_status="COMPLETE_FEASIBLE",
                expected_activated_in_shift=frozenset(),  # Stale! V1 is now in shift_rollback ledger!
                idempotency_key="idem_stale_test",
                parent_plan_id=pub1["id"],
                expected_parent_version=1,
            )

        with self.assertRaises(PlanVersionConflictError):
            self.db.publish_plan_atomic(
                run_id=r_run["run_id"],
                shift_id=shift_rollback,
                evaluated_plan=ev_plan,
                result_status="COMPLETE_FEASIBLE",
                expected_activated_in_shift=frozenset({veh.id}),
                idempotency_key="idem_ver_conflict",
                parent_plan_id=pub1["id"],
                expected_parent_version=99,  # Wrong version!
            )


if __name__ == "__main__":
    unittest.main()
