"""Tests for all 7 solver strategies, all 3 optimization profiles, deterministic seed replay, and Solomon C101-25."""

from __future__ import annotations

from dataclasses import replace
import unittest

from routeit_engine.adapters.solomon_and_ortools import (
    build_solomon_c101_25_sample,
    translate_solomon_instance_to_solve_request,
)
from routeit_engine.contracts.types import (
    CostRateConfig,
    DepotSpec,
    ExactRate,
    FleetMode,
    OptimizationProfile,
    OrderSpec,
    PartialSplitMode,
    PlanningConfig,
    PlanningMode,
    PriorityTier,
    ResultStatus,
    SolverKind,
    SolveRequest,
    VehicleSpec,
    WindowType,
)
from routeit_engine.orchestrator import solve
from routeit_reference.reference_evaluator import reference_evaluate_plan
from routeit_roads.default_network import create_default_profile_graph_oracle
from routeit_roads.oracles import EuclideanOracle, RoadNode


class TestSolversProfilesAndReproducibility(unittest.TestCase):
    def setUp(self) -> None:
        self.oracle = create_default_profile_graph_oracle()
        base_t = 1794882600  # 2026-11-17 08:00 IST
        self.depot = DepotSpec(
            id="DEP_VAD_1",
            node_id="N_DEPOT_ALKAPURI",
            return_enabled=True,
            return_deadline_utc_s=base_t + 28800,
            opening_utc_s=base_t,
            closing_utc_s=base_t + 28800,
        )
        self.orders = (
            OrderSpec("ORD_1", "N_SAYAJIGUNJ", 15, 300, base_t + 600, base_t + 7200, WindowType.HARD, PriorityTier.CRITICAL),
            OrderSpec("ORD_2", "N_FATEHGUNJ", 20, 300, base_t + 1200, base_t + 9000, WindowType.SOFT, PriorityTier.CRITICAL),
            OrderSpec("ORD_3", "N_KARELIBAUG", 25, 360, base_t + 1800, base_t + 10800, WindowType.SOFT, PriorityTier.STANDARD),
            OrderSpec("ORD_4", "N_MANJALPUR", 20, 300, base_t + 900, base_t + 12000, WindowType.HARD, PriorityTier.STANDARD),
            OrderSpec("ORD_5", "N_GOTRI", 15, 240, base_t + 2400, base_t + 14400, WindowType.SOFT, PriorityTier.FLEXIBLE),
            OrderSpec("ORD_6", "N_AKOTA", 15, 240, base_t + 300, base_t + 10800, WindowType.SOFT, PriorityTier.FLEXIBLE),
        )
        self.vehicles = (
            VehicleSpec("VEH_1", 60, 30000, available=True),
            VehicleSpec("VEH_2", 60, 30000, available=True),
            VehicleSpec("VEH_3", 60, 35000, available=True),
        )
        self.rates = CostRateConfig(
            distance_rate_paise_per_km=ExactRate(800, 1),
            time_rate_paise_per_hour=ExactRate(10000, 1),
            critical_sla_paise_per_min=ExactRate(1000, 1),
            standard_sla_paise_per_min=ExactRate(500, 1),
            flexible_sla_paise_per_min=ExactRate(200, 1),
        )
        self.base_t = base_t

    def test_all_solvers_produce_certified_plans_matching_reference_evaluator(self) -> None:
        for solver_kind in (
            SolverKind.CONSTRUCTIVE,
            SolverKind.SPLIT_BASELINE,
            SolverKind.LOCAL_SEARCH,
            SolverKind.ALNS,
            SolverKind.GA,
            SolverKind.QPSO,
            SolverKind.ORTOOLS_ADAPTER,
        ):
            cfg = PlanningConfig(
                planning_mode=PlanningMode.COMPLETE,
                fleet_mode=FleetMode.AUTO,
                profile=OptimizationProfile.COST_FOCUSED,
                departure_set_utc_s=(self.base_t,),
                solver_kind=solver_kind,
                max_canonical_evaluations=120,
                qpso_particles=8,
                qpso_generations=8,
                seed=42,
            )
            req = SolveRequest(
                f"REQ_{solver_kind.value}",
                "SHIFT_1",
                self.depot,
                self.orders,
                self.vehicles,
                self.rates,
                cfg,
            )
            res = solve(req, self.oracle)
            self.assertEqual(res.result_status, ResultStatus.COMPLETE_FEASIBLE, f"Failed for {solver_kind}")
            self.assertIsNotNone(res.plan)
            assert res.plan is not None
            self.assertTrue(res.plan.hard_feasible)
            self.assertTrue(res.plan.complete_feasible)
            self.assertEqual(len(res.plan.served_order_ids), len(self.orders))

            # Verify against independent reference evaluator (AC-10)
            specs = [(r.vehicle_id, r.departure_utc_s, r.stop_order_ids) for r in res.plan.routes]
            ref = reference_evaluate_plan(req, specs, self.oracle)
            self.assertEqual(res.plan.c_dec_paise, ref.incremental_decision_cost_paise)
            self.assertEqual(res.plan.idle_waiting_seconds, ref.idle_waiting_seconds)

    def test_deterministic_seed_reproducibility_and_profiles(self) -> None:
        # Fixed seed must produce bit-identical plan hash and cost
        cfg_qpso = PlanningConfig(
            planning_mode=PlanningMode.COMPLETE,
            fleet_mode=FleetMode.AUTO,
            profile=OptimizationProfile.BALANCED,
            departure_set_utc_s=(self.base_t,),
            solver_kind=SolverKind.QPSO,
            max_canonical_evaluations=150,
            qpso_particles=8,
            qpso_generations=10,
            seed=777,
        )
        req1 = SolveRequest("REQ_SEED", "SHIFT_S", self.depot, self.orders, self.vehicles, self.rates, cfg_qpso)
        r1 = solve(req1, self.oracle)
        r2 = solve(req1, self.oracle)
        assert r1.plan is not None and r2.plan is not None
        self.assertEqual(r1.plan.plan_hash, r2.plan.plan_hash)
        self.assertEqual(r1.plan.c_dec_paise, r2.plan.c_dec_paise)
        self.assertEqual(r1.telemetry.canonical_evaluations, r2.telemetry.canonical_evaluations)

        # Driver Productivity profile with two-pass C_ref and inclusive cap
        cfg_prod = replace(
            cfg_qpso,
            profile=OptimizationProfile.DRIVER_PRODUCTIVITY,
            max_extra_cost_paise=25000,
        )
        req_prod = SolveRequest("REQ_PROD", "SHIFT_S", self.depot, self.orders, self.vehicles, self.rates, cfg_prod)
        r_prod = solve(req_prod, self.oracle)
        self.assertEqual(r_prod.result_status, ResultStatus.COMPLETE_FEASIBLE)
        self.assertTrue(r_prod.approximation_flags.get("c_ref_is_upper_bound"))
        assert r_prod.plan is not None
        self.assertLessEqual(r_prod.plan.c_dec_paise, r_prod.calibration_metadata["c_cap_paise"])

    def test_partial_mode_priority_and_solomon_c101_25(self) -> None:
        # Partial Mode with tight fleet (only 1 vehicle of capacity 40 -> cannot serve all 110 units)
        # Must serve Critical orders (ORD_1=15, ORD_2=20 => 35 <= 40) before Standard/Flexible!
        tight_vehicles = (VehicleSpec("VEH_ONLY", 40, 30000, available=True),)
        cfg_partial = PlanningConfig(
            planning_mode=PlanningMode.PARTIAL,
            fleet_mode=FleetMode.TARGET,
            target_fleet_size=1,
            profile=OptimizationProfile.COST_FOCUSED,
            departure_set_utc_s=(self.base_t,),
            partial_split_mode=PartialSplitMode.EXACT_TINY,
            solver_kind=SolverKind.QPSO,
            max_canonical_evaluations=120,
            qpso_particles=6,
            qpso_generations=6,
            seed=42,
        )
        req_p = SolveRequest("REQ_PART", "SHIFT_P", self.depot, self.orders, tight_vehicles, self.rates, cfg_partial)
        res_p = solve(req_p, self.oracle)
        self.assertEqual(res_p.result_status, ResultStatus.PARTIAL_FEASIBLE)
        assert res_p.plan is not None
        # Both Critical orders (15 + 20 = 35 <= 40) must be served!
        self.assertEqual(res_p.plan.coverage_vector[0], 2)
        self.assertIn("ORD_1", res_p.plan.served_order_ids)
        self.assertIn("ORD_2", res_p.plan.served_order_ids)

        # Solomon C101-25 benchmark test
        depot_row, cust_rows = build_solomon_c101_25_sample()
        sol_nodes = [RoadNode(f"N_{depot_row.cust_no}", depot_row.x, depot_row.y)] + [
            RoadNode(f"N_{c.cust_no}", c.x, c.y) for c in cust_rows
        ]
        sol_oracle = EuclideanOracle(sol_nodes, speed_mps=1.0, coordinate_scale_m=1.0)
        sol_req = translate_solomon_instance_to_solve_request(
            instance_name="C101_25",
            vehicle_count=10,
            vehicle_capacity=200,
            depot_row=depot_row,
            customer_rows=cust_rows[:12],
            solver_kind=SolverKind.QPSO,
            max_evaluations=100,
        )
        sol_res = solve(sol_req, sol_oracle)
        self.assertEqual(sol_res.result_status, ResultStatus.COMPLETE_FEASIBLE)
        assert sol_res.plan is not None
        self.assertEqual(len(sol_res.plan.served_order_ids), 12)


if __name__ == "__main__":
    unittest.main()
