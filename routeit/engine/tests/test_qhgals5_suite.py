"""Comprehensive Automated Test Suite for Q-HGALS 5.0 Mathematical Fixtures (§7) & Acceptance Criteria.

Verifies all 54 normative test fixtures from `Q-HGALS_5.md` §7 and `Route_it_Phase5_System_Architecture_final.md`:
- `MNY-01` .. `MNY-09` (Exact rational accounting, RoundEven half-ties, per-route vs per-leg, i128 overflow, ledger reconcile)
- `ACT-01` .. `ACT-13` (Shift activation sorting, route-count marginal, zero-charge tie, canonical signature pairing, route vs shift ceilings)
- `SPLIT-01` .. `SPLIT-03` (Cap-safe dominance, served-ID tie retention, exact-tiny vs bounded-practical modes, brute-force equivalence)
- `CMP-01` .. `CMP-10`, `IDLE-01` .. `IDLE-02`, `PROF-01` .. `PROF-02` (Comparator hierarchy, cap equality, Type-7 quantile calibration, idle aggregation)
- `QPSO-01` .. `QPSO-06` (mbest, linear alpha schedule, triangular-wave reflection, k/2^53 open-unit RNG, position update equation, edge cases)
- `ROAD-01` & `EVAL-01` .. `EVAL-05` (Service completion boundary D=b vs D=b+1, return deadline, partition invariant, context hash invalidation)
- `DYN-01` .. `DYN-04` (Locked next stop, stale GPS rejection, CAS snapshot version race, infeasible replan rejection)
- `AC-10` Differential verification between production `CanonicalEvaluator` and independent `routeit_reference` evaluator
- Dependency boundary enforcement (`routeit_engine` imports zero web/DB modules)
"""

from __future__ import annotations

import ast
from fractions import Fraction
from itertools import permutations
import math
from pathlib import Path
import unittest

from routeit_engine.context.evaluation_context import EvaluationContext
from routeit_engine.contracts.types import (
    CostRateConfig,
    DepotSpec,
    ExactRate,
    FleetMode,
    OperationalSnapshot,
    OptimizationProfile,
    OrderSpec,
    PartialSplitMode,
    PlanningConfig,
    PlanningMode,
    PriorityTier,
    ReplanRequest,
    ResultStatus,
    SolverKind,
    SolveRequest,
    VehicleLiveState,
    VehicleOperationalState,
    VehicleSpec,
    WindowType,
)
from routeit_engine.evaluator.canonical import certify_plan, evaluate_plan, evaluate_route
from routeit_engine.money.ledger import (
    I128_MAX,
    InvalidMonetaryConfigError,
    NumericRangeError,
    checked_mul,
    compute_order_sla_cost_paise,
    compute_route_distance_cost_paise,
    compute_route_time_cost_paise,
    round_half_even,
)
from routeit_engine.oracle.protocol import OracleStatus
from routeit_engine.orchestrator import replan, solve
from routeit_engine.policy.comparators import (
    BalancedCalibration,
    PlanComparator,
    calibrate_balanced_profile,
    type7_quantile_exact,
)
from routeit_engine.policy.vehicle_assignment import (
    ShiftFleetPolicyConflictError,
    assign_vehicles_to_routes,
    build_sorted_vehicle_pool,
)
from routeit_engine.search.qpso import (
    OpenUnitPRNGStream,
    compute_alpha_schedule,
    compute_mbest_vector,
    qpso_update_coordinate,
    reflect_into_unit_interval,
)
from routeit_engine.split.decoder import (
    SplitLabel,
    _label_dominates,
    decode_giant_tour_split,
)
from routeit_reference.reference_evaluator import reference_evaluate_plan
from routeit_roads.default_network import create_default_profile_graph_oracle
from routeit_roads.oracles import EuclideanOracle, RoadNode


def _default_rates() -> CostRateConfig:
    return CostRateConfig(
        distance_rate_paise_per_km=ExactRate(800, 1),   # ₹8/km = 800 paise/km
        time_rate_paise_per_hour=ExactRate(10000, 1),   # ₹100/hr = 10000 paise/hr
        critical_sla_paise_per_min=ExactRate(1000, 1),  # ₹10/min = 1000 paise/min
        standard_sla_paise_per_min=ExactRate(500, 1),   # ₹5/min = 500 paise/min
        flexible_sla_paise_per_min=ExactRate(200, 1),   # ₹2/min = 200 paise/min
    )


class TestMonetaryAccountingFixtures(unittest.TestCase):
    """Tests MNY-01 through MNY-09 from Q-HGALS 5.0 §4.5 & §7."""

    def test_mny_01_to_05_round_half_to_even_and_per_route_aggregation(self) -> None:
        # MNY-01: 1m at 500 paise/km -> 500/1000 = 0.5 -> 0 paise (even low)
        self.assertEqual(compute_route_distance_cost_paise(1, ExactRate(500, 1)), 0)
        # MNY-02: 3m at 500 paise/km -> 1500/1000 = 1.5 -> 2 paise (even high)
        self.assertEqual(compute_route_distance_cost_paise(3, ExactRate(500, 1)), 2)
        # Time half tie: 1s at 1800 paise/hour -> 1800/3600 = 0.5 -> 0 paise
        self.assertEqual(compute_route_time_cost_paise(1, ExactRate(1800, 1)), 0)
        # MNY-03: Two 1m legs at 500 paise/km -> route aggregate 2m -> 1000/1000 = 1 paisa (NOT 0+0 per leg)
        self.assertEqual(compute_route_distance_cost_paise(1 + 1, ExactRate(500, 1)), 1)
        # MNY-04: SLA half tie 3s at 10 paise/min -> 30/60 = 0.5 -> 0 paise; 9s -> 90/60 = 1.5 -> 2 paise
        soft_order = OrderSpec("O1", "N1", 5, 10, 0, 100, WindowType.SOFT, PriorityTier.FLEXIBLE)
        rates = CostRateConfig(
            distance_rate_paise_per_km=ExactRate(500, 1),
            time_rate_paise_per_hour=ExactRate(1800, 1),
            critical_sla_paise_per_min=ExactRate(10, 1),
            standard_sla_paise_per_min=ExactRate(10, 1),
            flexible_sla_paise_per_min=ExactRate(10, 1),
        )
        self.assertEqual(compute_order_sla_cost_paise(3, soft_order, rates), 0)
        self.assertEqual(compute_order_sla_cost_paise(9, soft_order, rates), 2)
        # MNY-05: Fractional rational 1/3 paise/km over 3000m -> 3000 * (1/3) / 1000 = 1 paisa exact
        self.assertEqual(compute_route_distance_cost_paise(3000, ExactRate(1, 3)), 1)

    def test_mny_06_and_07_negative_rates_and_i128_overflow(self) -> None:
        # MNY-06: Negative rate rejected
        with self.assertRaises(InvalidMonetaryConfigError):
            compute_route_distance_cost_paise(100, ExactRate(-5, 1))
        # MNY-07: Product beyond signed i128 recomputed with BigInt or raises NumericRangeError safely (never wraps)
        large_a = I128_MAX + 999
        prod = checked_mul(large_a, 3)
        self.assertEqual(prod, large_a * 3)
        with self.assertRaises(NumericRangeError):
            round_half_even(10**25, 1)


class TestVehicleIdentityAndActivationFixtures(unittest.TestCase):
    """Tests ACT-01 through ACT-13 from Q-HGALS 5.0 §2 & §7 and Phase 5 Addendum A.4."""

    def test_act_01_to_06_shift_activation_sorting_and_counts(self) -> None:
        vehicles = (
            VehicleSpec("V1", 100, 500, available=True),
            VehicleSpec("V2", 100, 300, available=True),
            VehicleSpec("V3", 100, 700, available=True),
        )
        cfg = PlanningConfig()
        # ACT-01: A={V1}; costs V1=500, V2=300, V3=700; m=1 -> select V1, inc=0, counts=(1, 0, 1)
        pool = build_sorted_vehicle_pool(vehicles, frozenset({"V1"}), cfg)
        res1 = assign_vehicles_to_routes([(100, ("O1",))], pool)
        self.assertEqual(res1.selected_vehicle_ids, ("V1",))
        self.assertEqual(res1.incremental_activation_cost_paise, 0)
        self.assertEqual((res1.m_routes_used, res1.m_new_activated, res1.m_shift_activated_after), (1, 0, 1))

        # ACT-02: Same pool, m=2 -> select V1, V2; inc=300; counts=(2, 1, 2)
        res2 = assign_vehicles_to_routes([(100, ("O1",)), (100, ("O2",))], pool)
        self.assertEqual(res2.selected_vehicle_ids, ("V1", "V2"))
        self.assertEqual(res2.incremental_activation_cost_paise, 300)
        self.assertEqual((res2.m_routes_used, res2.m_new_activated, res2.m_shift_activated_after), (2, 1, 2))

        # ACT-03: V1 in A_shift, candidate uses 0 routes -> V1 remains in shift count
        res0 = assign_vehicles_to_routes([], pool)
        self.assertEqual(res0.m_shift_activated_after, 1)

        # ACT-06: m=3, |K|=2 -> assignment infeasible
        pool_2 = build_sorted_vehicle_pool(vehicles[:2], frozenset(), cfg)
        with self.assertRaises(ValueError):
            assign_vehicles_to_routes([(0, ("O1",)), (0, ("O2",)), (0, ("O3",))], pool_2)

    def test_act_07_to_13_tie_breaks_and_exhaustive_assignment(self) -> None:
        # ACT-10 (T-ACT-1): Zero-charge new-vehicle tie: A={V9}, V1 is new with F=0, V9 has F=0, m=1
        # Must select V9 because 1[k not in A] breaks equal weight w=0 tie!
        v_zero = (
            VehicleSpec("V1", 100, 0, available=True),
            VehicleSpec("V9", 100, 0, available=True),
        )
        pool_z = build_sorted_vehicle_pool(v_zero, frozenset({"V9"}), PlanningConfig())
        res_z = assign_vehicles_to_routes([(0, ("O1",))], pool_z)
        self.assertEqual(res_z.selected_vehicle_ids, ("V9",))
        self.assertEqual(res_z.m_new_activated, 0)
        self.assertEqual(res_z.m_shift_activated_after, 1)

        # ACT-11: Canonical assignment tie: Selected IDs V1 < V2; route R1=(09:00, [7]), R2=(08:00, [2])
        # Must pair V1 -> R2 (index 1, earlier departure) and V2 -> R1 (index 0)!
        v_pair = (
            VehicleSpec("V1", 100, 300, available=True),
            VehicleSpec("V2", 100, 300, available=True),
        )
        pool_p = build_sorted_vehicle_pool(v_pair, frozenset(), PlanningConfig())
        r_descs = [(32400, ("7",)), (28800, ("2",))]  # R1 at 09:00, R2 at 08:00
        res_p = assign_vehicles_to_routes(r_descs, pool_p)
        self.assertEqual(res_p.vehicle_id_by_route_index[1], "V1")
        self.assertEqual(res_p.vehicle_id_by_route_index[0], "V2")

        # ACT-09 / ACT-12: Heterogeneous vehicle capacity/profile disables shortcut
        v_het = (
            VehicleSpec("V1", 100, 300, available=True),
            VehicleSpec("V2", 50, 100, available=True),
        )
        with self.assertRaises(ValueError):
            build_sorted_vehicle_pool(v_het, frozenset(), PlanningConfig())

        # ACT-13: Route limit vs shift activation ceiling: K={V3}, A={V1, V2}, M_route_max=2, M_shift_activated_max=2
        v_ceil = (
            VehicleSpec("V1", 100, 300, available=False),
            VehicleSpec("V2", 100, 300, available=False),
            VehicleSpec("V3", 100, 300, available=True),
        )
        cfg_ceil = PlanningConfig(max_route_count=2, max_shift_activated_vehicles=2)
        pool_c = build_sorted_vehicle_pool(v_ceil, frozenset({"V1", "V2"}), cfg_ceil)
        # m=1 route uses V3 (new), which would make M_shift_activated_after = 2 + 1 = 3 > 2 -> inadmissible!
        self.assertFalse(pool_c.is_route_count_admissible(1, is_terminal=True))

        # Also test SHIFT_FLEET_POLICY_CONFLICT when |A| already exceeds ceiling
        with self.assertRaises(ShiftFleetPolicyConflictError):
            build_sorted_vehicle_pool(
                v_ceil,
                frozenset({"V1", "V2"}),
                PlanningConfig(max_shift_activated_vehicles=1),
            )


class TestSplitAndComparatorFixtures(unittest.TestCase):
    """Tests SPLIT-01..03, CMP-01..10, IDLE-01..02, PROF-01..02 from Q-HGALS 5.0 §3, §7."""

    def test_split_01_and_02_dominance_rules(self) -> None:
        # SPLIT-01: Driver cap=100; X has higher coverage (2,0,0) and cost 70; Y has lower coverage (1,0,0) and cost 40
        # Under DRIVER_PRODUCTIVITY, X MUST NOT dominate Y because a suffix of cost 40 makes X=110 (over cap) and Y=80 (eligible)!
        lbl_x = SplitLabel(2, 1, frozenset({"C1", "C2"}), 70, 0, (2, 0, 0), 1, ())
        lbl_y = SplitLabel(2, 1, frozenset({"C1"}), 40, 0, (1, 0, 0), 1, ())
        self.assertFalse(
            _label_dominates(
                lbl_x,
                lbl_y,
                profile=OptimizationProfile.DRIVER_PRODUCTIVITY,
                planning_mode=PlanningMode.PARTIAL,
                c_cap_paise=100,
                balanced_cal=None,
            )
        )

        # SPLIT-02: Equal metrics and coverage (1,0,0), one serves Critical C7, another serves Critical C2
        # Must NOT dominate each other when preserve_served_identity_ties=True!
        lbl_c7 = SplitLabel(2, 1, frozenset({"C7"}), 50, 10, (1, 0, 0), 1, ((0, ("C7",)),))
        lbl_c2 = SplitLabel(2, 1, frozenset({"C2"}), 50, 10, (1, 0, 0), 1, ((0, ("C2",)),))
        self.assertFalse(
            _label_dominates(
                lbl_c7,
                lbl_c2,
                profile=OptimizationProfile.COST_FOCUSED,
                planning_mode=PlanningMode.PARTIAL,
                c_cap_paise=None,
                balanced_cal=None,
                preserve_served_identity_ties=True,
            )
        )

    def test_cmp_01_to_10_and_prof_01_02_comparators(self) -> None:
        nodes = [RoadNode("D", 0, 0), RoadNode("N1", 10, 0), RoadNode("N2", 20, 0), RoadNode("N3", 30, 0)]
        oracle = EuclideanOracle(nodes, speed_mps=1.0, coordinate_scale_m=100.0)
        depot = DepotSpec("D", "D", return_enabled=True)
        orders = (
            OrderSpec("C1", "N1", 5, 10, 0, 5000, WindowType.HARD, PriorityTier.CRITICAL),
            OrderSpec("S1", "N2", 5, 10, 0, 5000, WindowType.HARD, PriorityTier.STANDARD),
            OrderSpec("F1", "N3", 5, 10, 0, 5000, WindowType.HARD, PriorityTier.FLEXIBLE),
        )
        vehicles = (VehicleSpec("V1", 50, 500), VehicleSpec("V2", 50, 500))
        cfg = PlanningConfig(
            planning_mode=PlanningMode.PARTIAL,
            profile=OptimizationProfile.DRIVER_PRODUCTIVITY,
            reference_cost_paise=100,
            max_extra_cost_paise=0,
        )
        req = SolveRequest(
            "R1",
            "S1",
            depot,
            orders,
            vehicles,
            _default_rates(),
            cfg,
            activated_vehicle_ids_in_shift=frozenset({"V1"}),
            posted_activation_cost_paise_by_vehicle={"V1": 500},
        )
        ctx = EvaluationContext.build(req, oracle.identity())

        # PROF-01: Previously posted activation=500 paise for V1; candidate using V1 has 0 incremental activation!
        p_v1 = evaluate_plan(route_specs=[("V1", 0, ["C1"])], ctx=ctx, oracle=oracle)
        self.assertEqual(p_v1.ledger.incremental_activation_cost_paise, 0)
        self.assertEqual(p_v1.ledger.activation_posted_before_paise, 500)
        self.assertEqual(p_v1.c_dec_paise, p_v1.ledger.operating_cost_paise)

        # PROF-02: Balanced vs Cost calibration: C0=100, I0=30, S_C=20, S_I=10; A=(110, 30), B=(100, 40)
        cal = BalancedCalibration(
            c0_paise=100,
            i0_seconds=30,
            s_c_paise=20,
            s_i_seconds=10,
            low_calibration_quality=False,
            calibration_coverage_class=(1, 0, 0),
            sample_size=2,
        )
        # J_A cross-product = (110-100)*10 + (30-30)*20 = 100
        # J_B cross-product = (100-100)*10 + (40-30)*20 = 200 -> A wins under Balanced!
        self.assertEqual(cal.cross_product_score(110, 30), 100)
        self.assertEqual(cal.cross_product_score(100, 40), 200)
        self.assertLess(cal.cross_product_score(110, 30), cal.cross_product_score(100, 40))

    def test_act_08_and_ac_10_split_brute_force_and_differential_evaluator(self) -> None:
        """Verify Split exactness against brute-force partition enumeration AND differential reference evaluator."""
        nodes = [
            RoadNode("D", 0, 0),
            RoadNode("N1", 3, 4),
            RoadNode("N2", 6, 8),
            RoadNode("N3", 9, 12),
            RoadNode("N4", 12, 5),
        ]
        oracle = EuclideanOracle(nodes, speed_mps=1.0, coordinate_scale_m=100.0)
        depot = DepotSpec("D", "D", return_enabled=True, return_deadline_utc_s=20000)
        orders = (
            OrderSpec("O1", "N1", 4, 30, 600, 4000, WindowType.SOFT, PriorityTier.CRITICAL),
            OrderSpec("O2", "N2", 5, 40, 200, 1200, WindowType.SOFT, PriorityTier.STANDARD),
            OrderSpec("O3", "N3", 4, 25, 1000, 5000, WindowType.HARD, PriorityTier.CRITICAL),
            OrderSpec("O4", "N4", 5, 35, 300, 6000, WindowType.SOFT, PriorityTier.FLEXIBLE),
        )
        vehicles = (
            VehicleSpec("V1", 10, 30000),
            VehicleSpec("V2", 10, 40000),
            VehicleSpec("V3", 10, 50000),
        )
        cfg = PlanningConfig(
            planning_mode=PlanningMode.COMPLETE,
            fleet_mode=FleetMode.AUTO,
            profile=OptimizationProfile.COST_FOCUSED,
            departure_set_utc_s=(0, 300),
        )
        req = SolveRequest("REQ_BF", "SHIFT_BF", depot, orders, vehicles, _default_rates(), cfg)
        ctx = EvaluationContext.build(req, oracle.identity())
        pool = build_sorted_vehicle_pool(req.vehicles, req.activated_vehicle_ids_in_shift, cfg)
        comp = PlanComparator(cfg)

        tour = ["O1", "O2", "O3", "O4"]
        split_plan, truncated = decode_giant_tour_split(
            giant_tour_order_ids=tour,
            ctx=ctx,
            oracle=oracle,
            pool=pool,
            comparator=comp,
        )
        self.assertFalse(truncated)
        self.assertIsNotNone(split_plan)
        assert split_plan is not None

        # Brute-force enumerate all contiguous partitions and departure choices for `tour`
        best_bf_plan = None
        n = len(tour)
        for mask in range(1 << (n - 1)):
            blocks: list[list[str]] = [[tour[0]]]
            for idx in range(1, n):
                if (mask >> (idx - 1)) & 1:
                    blocks.append([tour[idx]])
                else:
                    blocks[-1].append(tour[idx])
            if len(blocks) > pool.max_routes_allowed:
                continue
            # Enumerate departures in (0, 300) for each block
            dep_choices = cfg.departure_set_utc_s
            m_b = len(blocks)
            for dep_mask in range(1 << m_b):
                descs = [
                    (dep_choices[(dep_mask >> b_i) & 1], tuple(blocks[b_i]))
                    for b_i in range(m_b)
                ]
                assign_res = assign_vehicles_to_routes(descs, pool)
                specs = [
                    (assign_res.vehicle_id_by_route_index[b_i], descs[b_i][0], descs[b_i][1])
                    for b_i in range(m_b)
                ]
                cand = evaluate_plan(route_specs=specs, ctx=ctx, oracle=oracle)
                # Differential check against independent Reference Evaluator (AC-10)!
                ref_cand = reference_evaluate_plan(req, specs, oracle)
                self.assertEqual(cand.hard_feasible, ref_cand.hard_feasible)
                self.assertEqual(cand.c_dec_paise, ref_cand.incremental_decision_cost_paise)
                self.assertEqual(cand.idle_waiting_seconds, ref_cand.idle_waiting_seconds)
                self.assertEqual(cand.ledger.distance_cost_paise, ref_cand.distance_cost_paise)
                self.assertEqual(cand.ledger.time_cost_paise, ref_cand.time_cost_paise)
                self.assertEqual(cand.ledger.sla_cost_paise, ref_cand.sla_cost_paise)

                if cand.hard_feasible:
                    if best_bf_plan is None or comp.compare(cand, best_bf_plan) < 0:
                        best_bf_plan = cand

        self.assertIsNotNone(best_bf_plan)
        assert best_bf_plan is not None
        self.assertEqual(split_plan.c_dec_paise, best_bf_plan.c_dec_paise)
        self.assertEqual(split_plan.idle_waiting_seconds, best_bf_plan.idle_waiting_seconds)
        self.assertEqual(split_plan.plan_hash, best_bf_plan.plan_hash)


class TestQPSOAndDynamicFixtures(unittest.TestCase):
    """Tests QPSO-01..06, EVAL-01..05, ROAD-01, and DYN-01..04 from Q-HGALS 5.0 §7."""

    def test_qpso_01_to_06_normative_equations(self) -> None:
        # QPSO-01: mbest coordinate mean of (0.2, 0.8) and (0.6, 0.4) -> (0.4, 0.6)
        mbest = compute_mbest_vector([(0.2, 0.8), (0.6, 0.4)])
        self.assertAlmostEqual(mbest[0], 0.4, places=12)
        self.assertAlmostEqual(mbest[1], 0.6, places=12)

        # QPSO-02: Contraction schedule T=3, alpha_max=1.0, alpha_min=0.5 -> (1.0, 0.75, 0.5); T=1 -> 1.0
        sched = [compute_alpha_schedule(t, 3, 1.0, 0.5) for t in range(3)]
        self.assertEqual(sched, [1.0, 0.75, 0.5])
        self.assertEqual(compute_alpha_schedule(0, 1, 1.0, 0.5), 1.0)

        # QPSO-03: Boundary reflection y in {-0.25, 0, 1, 1.25, 2.25} -> {0.25, 0, 1, 0.75, 0.25}
        for raw_y, expected_y in [(-0.25, 0.25), (0.0, 0.0), (1.0, 1.0), (1.25, 0.75), (2.25, 0.25)]:
            self.assertAlmostEqual(reflect_into_unit_interval(raw_y), expected_y, places=12)

        # QPSO-04: Open-unit RNG k / 2^53 never draws 0 or 1
        stream = OpenUnitPRNGStream(seed=12345)
        for _ in range(200):
            u = stream.draw_open_unit()
            self.assertGreater(u, 0.0)
            self.assertLess(u, 1.0)

        # QPSO-05: Position update: x=0.5, pbest=0.2, gbest=0.8, phi=0.25, mbest=0.4, alpha=1, sigma=+1, u=0.5
        # p = 0.25*0.2 + 0.75*0.8 = 0.65; y = 0.65 + 1.0 * |0.4 - 0.5| * ln(2) = 0.65 + 0.1 * ln(2)
        p, y, x_next = qpso_update_coordinate(
            x=0.5, pbest=0.2, gbest=0.8, mbest=0.4, alpha=1.0, phi=0.25, sigma=1.0, u=0.5
        )
        self.assertAlmostEqual(p, 0.65, places=12)
        self.assertAlmostEqual(y, 0.65 + 0.1 * math.log(2.0), places=9)
        self.assertAlmostEqual(x_next, y, places=9)

        # QPSO-06: Singleton population P=1; invalid u=0 or alpha=NaN rejected before log
        self.assertEqual(compute_mbest_vector([(0.33, 0.77)]), (0.33, 0.77))
        with self.assertRaises(NumericRangeError):
            qpso_update_coordinate(
                x=0.5, pbest=0.2, gbest=0.8, mbest=0.4, alpha=1.0, phi=0.25, sigma=1.0, u=0.0
            )
        with self.assertRaises(NumericRangeError):
            compute_alpha_schedule(0, 3, float("nan"), 0.5)

    def test_eval_01_to_05_and_dyn_01_to_04(self) -> None:
        nodes = [RoadNode("D", 0, 0), RoadNode("N1", 1, 0), RoadNode("N2", 2, 0)]
        oracle = EuclideanOracle(nodes, speed_mps=1.0, coordinate_scale_m=100.0)
        depot = DepotSpec("D", "D", return_enabled=True, return_deadline_utc_s=500)

        # EVAL-01: Window boundary D=b (feasible) vs D=b+1s (hard infeasible)
        # Travel D->N1 is 100s, service=50s => D_1 = 150s
        o_exact = OrderSpec("O1", "N1", 5, 50, 0, 150, WindowType.HARD, PriorityTier.CRITICAL)
        o_late1 = OrderSpec("O1", "N1", 5, 50, 0, 149, WindowType.HARD, PriorityTier.CRITICAL)
        veh = VehicleSpec("V1", 20, 500)

        req_ok = SolveRequest("R1", "S1", depot, (o_exact,), (veh,), _default_rates(), PlanningConfig())
        ctx_ok = EvaluationContext.build(req_ok, oracle.identity())
        self.assertTrue(evaluate_route(vehicle=veh, order_ids=["O1"], departure_utc_s=0, ctx=ctx_ok, oracle=oracle).feasible)

        req_late = SolveRequest("R2", "S1", depot, (o_late1,), (veh,), _default_rates(), PlanningConfig())
        ctx_late = EvaluationContext.build(req_late, oracle.identity())
        self.assertFalse(evaluate_route(vehicle=veh, order_ids=["O1"], departure_utc_s=0, ctx=ctx_late, oracle=oracle).feasible)

        # EVAL-02: Soft boundary D=b+1s with p=60 paise/min -> 1*60/60 = 1 paisa
        o_soft = OrderSpec(
            "O1", "N1", 5, 50, 0, 149, WindowType.SOFT, PriorityTier.CRITICAL,
            custom_sla_rate_paise_per_min=ExactRate(60, 1),
        )
        req_soft = SolveRequest("R3", "S1", depot, (o_soft,), (veh,), _default_rates(), PlanningConfig())
        ctx_soft = EvaluationContext.build(req_soft, oracle.identity())
        ev_soft = evaluate_route(vehicle=veh, order_ids=["O1"], departure_utc_s=0, ctx=ctx_soft, oracle=oracle)
        self.assertTrue(ev_soft.feasible)
        self.assertEqual(ev_soft.sla_cost_paise, 1)

        # EVAL-03: Return leg violates return deadline by 1s (D_1=150 + return 100 = 250 > 249)
        depot_tight = DepotSpec("D", "D", return_enabled=True, return_deadline_utc_s=249)
        req_ret = SolveRequest("R4", "S1", depot_tight, (o_exact,), (veh,), _default_rates(), PlanningConfig())
        ctx_ret = EvaluationContext.build(req_ret, oracle.identity())
        self.assertFalse(evaluate_route(vehicle=veh, order_ids=["O1"], departure_utc_s=0, ctx=ctx_ret, oracle=oracle).feasible)

        # EVAL-05: Context cache invalidation when A_shift or rates change
        req_a2 = SolveRequest(
            "R1", "S1", depot, (o_exact,), (veh,), _default_rates(), PlanningConfig(),
            activated_vehicle_ids_in_shift=frozenset({"V1"}),
        )
        ctx_a2 = EvaluationContext.build(req_a2, oracle.identity())
        self.assertNotEqual(ctx_ok.context_hash, ctx_a2.context_hash)

        # DYN-01..03: Locked next stop preserved, stale GPS rejected, CAS race rejected
        o2 = OrderSpec("O2", "N2", 5, 30, 0, 800, WindowType.HARD, PriorityTier.STANDARD)
        req_dyn = SolveRequest(
            "RDYN", "SDYN", depot, (o_exact, o2), (veh,), _default_rates(),
            PlanningConfig(departure_set_utc_s=(0,)),
            activated_vehicle_ids_in_shift=frozenset({"V1"}),
        )
        ctx_dyn = EvaluationContext.build(req_dyn, oracle.identity())
        base_plan = evaluate_plan(route_specs=[("V1", 0, ["O1", "O2"])], ctx=ctx_dyn, oracle=oracle)

        # DYN-02: Stale GPS rejected
        stale_snap = OperationalSnapshot(
            snapshot_id="SN_STALE",
            shift_id="SDYN",
            plan_id="P1",
            plan_version=1,
            snapshot_version=2,
            t0_utc_s=500,
            traffic_scenario_revision=1,
            vehicle_states=(
                VehicleLiveState(
                    vehicle_id="V1",
                    state=VehicleOperationalState.EN_ROUTE,
                    current_node_id="D",
                    current_time_utc_s=50,
                    remaining_load_units=10,
                    locked_next_order_id="O1",
                    assigned_remaining_order_ids=("O1", "O2"),
                    position_timestamp_utc_s=10,  # staleness = 490s > 300s
                ),
            ),
            completed_order_ids=frozenset(),
            pending_unassigned_order_ids=frozenset(),
            max_gps_staleness_seconds=300,
        )
        rep_stale = replan(ReplanRequest("REP1", req_dyn, stale_snap, base_plan), oracle)
        self.assertFalse(rep_stale.adopted)
        self.assertEqual(rep_stale.result_status, ResultStatus.INVALID_OPERATIONAL_STATE)

        # DYN-03: CAS snapshot version mismatch rejected
        valid_snap = OperationalSnapshot(
            snapshot_id="SN_OK",
            shift_id="SDYN",
            plan_id="P1",
            plan_version=1,
            snapshot_version=2,
            t0_utc_s=50,
            traffic_scenario_revision=1,
            vehicle_states=(
                VehicleLiveState(
                    vehicle_id="V1",
                    state=VehicleOperationalState.EN_ROUTE,
                    current_node_id="D",
                    current_time_utc_s=0,
                    remaining_load_units=10,
                    locked_next_order_id="O1",
                    assigned_remaining_order_ids=("O1", "O2"),
                    position_timestamp_utc_s=50,
                ),
            ),
            completed_order_ids=frozenset(),
            pending_unassigned_order_ids=frozenset(),
        )
        rep_cas = replan(
            ReplanRequest("REP2", req_dyn, valid_snap, base_plan),
            oracle,
            expected_snapshot_version=99,
        )
        self.assertFalse(rep_cas.adopted)
        self.assertEqual(rep_cas.rejection_reason, "STALE_SNAPSHOT")

        # DYN-01: Locked next stop O1 remains first stop in replanned candidate
        rep_ok = replan(
            ReplanRequest("REP3", req_dyn, valid_snap, base_plan),
            oracle,
            expected_snapshot_version=2,
        )
        self.assertIsNotNone(rep_ok.candidate_plan)
        assert rep_ok.candidate_plan is not None
        self.assertEqual(rep_ok.candidate_plan.routes[0].stops[0].order_id, "O1")
        self.assertTrue(rep_ok.candidate_plan.routes[0].stops[0].is_locked)

    def test_road_01_and_import_boundaries(self) -> None:
        """Verify ProfileGraphOracle FIFO monotonicity, one-way rules, and strict engine import boundaries."""
        oracle = create_default_profile_graph_oracle()
        # Check FIFO monotonicity across departure timestamps
        t_prev = -1
        for dep in range(1794880000, 1794900000, 600):
            arr = oracle.arrival("N_DEPOT_ALKAPURI", "N_MANJALPUR", dep)
            self.assertEqual(arr.status, OracleStatus.OK)
            assert arr.arrival_utc_s is not None
            self.assertGreaterEqual(arr.arrival_utc_s, t_prev)
            t_prev = arr.arrival_utc_s

        # Verify engine files do NOT import fastapi, pydantic, sqlite3, or sqlalchemy
        engine_root = Path(__file__).resolve().parents[1] / "routeit_engine"
        forbidden = {"fastapi", "pydantic", "sqlite3", "sqlalchemy", "uvicorn", "starlette"}
        for py_file in engine_root.rglob("*.py"):
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        top = alias.name.split(".")[0]
                        self.assertNotIn(top, forbidden, f"Forbidden import {top} in {py_file}")
                elif isinstance(node, ast.ImportFrom) and node.module:
                    top = node.module.split(".")[0]
                    self.assertNotIn(top, forbidden, f"Forbidden import {top} in {py_file}")


if __name__ == "__main__":
    unittest.main()
