"""Continuation-safe Vehicle-Aware Split Decoder (Q-HGALS 5.0 §2.5–§2.7).

Implements:
- Complete Mode and Partial Mode (`EXACT_TINY` and `BOUNDED_PRACTICAL`).
- Route-count activation marginal `g^C_m = G_C(m) - G_C(m-1)` and `Delta G_N(m)`.
- Profile-specific and cap-safe continuation dominance (`SPLIT-01`, `SPLIT-02`, `SPLIT-03`).
- Deterministic minimum-cost vehicle identity assignment (`assign_vehicles_to_routes`).
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Sequence

from routeit_engine.context.evaluation_context import EvaluationContext
from routeit_engine.contracts.types import (
    EvaluatedPlan,
    OptimizationProfile,
    PartialSplitMode,
    PlanningMode,
    PriorityTier,
    TelemetryCounters,
    UnservedReason,
    VehicleSpec,
)
from routeit_engine.evaluator.canonical import evaluate_plan, evaluate_route
from routeit_engine.oracle.protocol import RoadOracle
from routeit_engine.policy.comparators import BalancedCalibration, PlanComparator
from routeit_engine.policy.vehicle_assignment import (
    SortedVehiclePool,
    assign_vehicles_to_routes,
)


@dataclass(frozen=True)
class SegmentEvaluation:
    """Canonical evaluation of a single route segment serving `served_order_ids` at `departure_utc_s`."""

    departure_utc_s: int
    served_order_ids: tuple[str, ...]
    operating_cost_paise: int
    idle_waiting_seconds: int
    coverage_delta: tuple[int, int, int]


@dataclass(frozen=True)
class SplitLabel:
    """DP label at state (j, m) per Q-HGALS 5.0 §2.5."""

    j: int
    m: int
    served_set: frozenset[str]
    c_dec_paise: int
    i_idle_seconds: int
    coverage: tuple[int, int, int]
    g_n_new_activations: int
    route_descriptors: tuple[tuple[int, tuple[str, ...]], ...]  # ((departure_s, stop_ids), ...)

    @property
    def m_shift_after(self) -> int:
        return self.g_n_new_activations  # relative to constant |A_shift|


def _label_dominates(
    a: SplitLabel,
    b: SplitLabel,
    *,
    profile: OptimizationProfile,
    planning_mode: PlanningMode,
    c_cap_paise: int | None,
    balanced_cal: BalancedCalibration | None,
    preserve_served_identity_ties: bool = True,
) -> bool:
    """Continuation-safe dominance check at identical (j, m) state (Q-HGALS 5.0 §2.7, SPLIT-01, SPLIT-02)."""
    if a.j != b.j or a.m != b.m:
        return False

    if planning_mode == PlanningMode.PARTIAL and a.coverage != b.coverage:
        if (
            a.coverage[0] >= b.coverage[0]
            and a.coverage[1] >= b.coverage[1]
            and a.coverage[2] >= b.coverage[2]
            and a.coverage > b.coverage
        ):
            if profile == OptimizationProfile.DRIVER_PRODUCTIVITY:
                return a.c_dec_paise <= b.c_dec_paise and a.i_idle_seconds <= b.i_idle_seconds
            if profile == OptimizationProfile.COST_FOCUSED:
                return a.c_dec_paise <= b.c_dec_paise and a.i_idle_seconds <= b.i_idle_seconds
            if profile == OptimizationProfile.BALANCED:
                return a.c_dec_paise <= b.c_dec_paise and a.i_idle_seconds <= b.i_idle_seconds
        return False

    if a.coverage != b.coverage:
        return False

    if a.c_dec_paise == b.c_dec_paise and a.i_idle_seconds == b.i_idle_seconds:
        if preserve_served_identity_ties:
            if a.served_set != b.served_set:
                return False
            if sorted(a.route_descriptors) != sorted(b.route_descriptors):
                return False
        return True

    if profile == OptimizationProfile.COST_FOCUSED:
        return a.c_dec_paise <= b.c_dec_paise and a.i_idle_seconds <= b.i_idle_seconds

    if profile == OptimizationProfile.DRIVER_PRODUCTIVITY:
        if c_cap_paise is not None and a.c_dec_paise > c_cap_paise:
            return False
        return a.i_idle_seconds <= b.i_idle_seconds and a.c_dec_paise <= b.c_dec_paise

    # BALANCED
    if balanced_cal is not None:
        jb_a = balanced_cal.cross_product_score(a.c_dec_paise, a.i_idle_seconds)
        jb_b = balanced_cal.cross_product_score(b.c_dec_paise, b.i_idle_seconds)
        return jb_a <= jb_b and a.c_dec_paise <= b.c_dec_paise and a.i_idle_seconds <= b.i_idle_seconds
    return a.c_dec_paise <= b.c_dec_paise and a.i_idle_seconds <= b.i_idle_seconds


def _prune_frontier(
    labels: list[SplitLabel],
    *,
    profile: OptimizationProfile,
    planning_mode: PlanningMode,
    c_cap_paise: int | None,
    balanced_cal: BalancedCalibration | None,
    max_labels: int | None,
    preserve_served_identity_ties: bool,
    telemetry: TelemetryCounters | None = None,
) -> tuple[list[SplitLabel], bool]:
    """Prune dominated labels at a single (j, m) state and apply optional bounded frontier cap."""
    kept: list[SplitLabel] = []
    pruned_count = 0
    for cand in labels:
        if (
            profile == OptimizationProfile.DRIVER_PRODUCTIVITY
            and c_cap_paise is not None
            and cand.c_dec_paise > c_cap_paise
        ):
            pruned_count += 1
            continue
        dominated = False
        new_kept: list[SplitLabel] = []
        for existing in kept:
            if _label_dominates(
                existing,
                cand,
                profile=profile,
                planning_mode=planning_mode,
                c_cap_paise=c_cap_paise,
                balanced_cal=balanced_cal,
                preserve_served_identity_ties=preserve_served_identity_ties,
            ):
                dominated = True
                new_kept.append(existing)
            elif _label_dominates(
                cand,
                existing,
                profile=profile,
                planning_mode=planning_mode,
                c_cap_paise=c_cap_paise,
                balanced_cal=balanced_cal,
                preserve_served_identity_ties=preserve_served_identity_ties,
            ):
                pruned_count += 1
            else:
                new_kept.append(existing)
        if not dominated:
            new_kept.append(cand)
        else:
            pruned_count += 1
        kept = new_kept

    truncated = False
    if max_labels is not None and len(kept) > max_labels:
        truncated = True
        kept.sort(
            key=lambda lbl: (
                (-lbl.coverage[0], -lbl.coverage[1], -lbl.coverage[2]),
                lbl.c_dec_paise if profile != OptimizationProfile.DRIVER_PRODUCTIVITY else lbl.i_idle_seconds,
                lbl.i_idle_seconds if profile != OptimizationProfile.DRIVER_PRODUCTIVITY else lbl.c_dec_paise,
                sorted(lbl.served_set),
            )
        )
        pruned_count += len(kept) - max_labels
        kept = kept[:max_labels]

    if telemetry is not None:
        telemetry.split_labels_pruned += pruned_count
        if len(kept) > telemetry.split_max_frontier_size:
            telemetry.split_max_frontier_size = len(kept)
        if truncated:
            telemetry.split_frontier_truncations += 1

    return kept, truncated


def decode_giant_tour_split(
    *,
    giant_tour_order_ids: Sequence[str],
    ctx: EvaluationContext,
    oracle: RoadOracle,
    pool: SortedVehiclePool,
    comparator: PlanComparator,
    unserved_reasons_override: dict[str, tuple[UnservedReason, str]] | None = None,
    telemetry: TelemetryCounters | None = None,
) -> tuple[EvaluatedPlan | None, bool]:
    """Decode a giant tour permutation into an EvaluatedPlan using Vehicle-Aware Split (Q-HGALS 5.0 §2.6)."""
    if telemetry is not None:
        telemetry.decode_attempts += 1

    cfg = ctx.request.planning_config
    tour = [oid for oid in giant_tour_order_ids if oid in ctx.orders_by_id]
    n = len(tour)

    if n == 0:
        empty_plan = evaluate_plan(
            route_specs=(),
            ctx=ctx,
            oracle=oracle,
            unserved_reasons_override=unserved_reasons_override,
            telemetry=telemetry,
        )
        return empty_plan, False

    if not pool.sorted_vehicles:
        if cfg.planning_mode == PlanningMode.PARTIAL:
            empty_plan = evaluate_plan(
                route_specs=(),
                ctx=ctx,
                oracle=oracle,
                unserved_reasons_override=unserved_reasons_override,
                default_unserved_reason=UnservedReason.UNSERVED_BY_OPTIMIZATION_DECISION,
                telemetry=telemetry,
            )
            return empty_plan, False
        return None, False

    departures = cfg.departure_set_utc_s
    is_partial = cfg.planning_mode == PlanningMode.PARTIAL
    exact_tiny = (not is_partial) or (cfg.partial_split_mode == PartialSplitMode.EXACT_TINY and n <= 12)
    max_labels = None if exact_tiny else cfg.bounded_max_labels_per_state
    any_truncated = not exact_tiny and is_partial

    # Segment evaluation cache keyed by (served_order_ids_tuple, departure_s, vehicle_capacity, vehicle_profile, return_to_depot, return_deadline)
    seg_cache: dict[tuple[tuple[str, ...], int, int, str, bool | None, int | None], SegmentEvaluation | None] = {}

    def eval_segment(subseq: tuple[str, ...], dep_s: int, slot_vehicle: VehicleSpec) -> SegmentEvaluation | None:
        key = (
            subseq,
            dep_s,
            slot_vehicle.capacity_units,
            slot_vehicle.vehicle_profile,
            slot_vehicle.return_to_depot,
            slot_vehicle.return_deadline_utc_s,
        )
        if key in seg_cache:
            return seg_cache[key]
        total_d = sum(ctx.orders_by_id[oid].demand_units for oid in subseq)
        if total_d > slot_vehicle.capacity_units:
            seg_cache[key] = None
            return None
        ev_r = evaluate_route(
            vehicle=slot_vehicle,
            order_ids=subseq,
            departure_utc_s=dep_s,
            ctx=ctx,
            oracle=oracle,
            telemetry=telemetry,
        )
        if not ev_r.feasible:
            seg_cache[key] = None
            return None
        nc = sum(1 for oid in subseq if ctx.orders_by_id[oid].priority == PriorityTier.CRITICAL)
        ns = sum(1 for oid in subseq if ctx.orders_by_id[oid].priority == PriorityTier.STANDARD)
        nf = sum(1 for oid in subseq if ctx.orders_by_id[oid].priority == PriorityTier.FLEXIBLE)
        res = SegmentEvaluation(
            departure_utc_s=dep_s,
            served_order_ids=subseq,
            operating_cost_paise=ev_r.route_operating_cost_paise,
            idle_waiting_seconds=ev_r.idle_waiting_seconds,
            coverage_delta=(nc, ns, nf),
        )
        seg_cache[key] = res
        return res

    def candidate_subsequences(i_idx: int, j_idx: int) -> list[tuple[str, ...]]:
        """Generate canonical route-block subsequences on tour[i_idx:j_idx] with both endpoints served (§2.5)."""
        block = tour[i_idx:j_idx]
        if len(block) <= 2 or not is_partial:
            return [tuple(block)]
        first_oid = block[0]
        last_oid = block[-1]
        interior = block[1:-1]
        k_int = len(interior)
        if exact_tiny:
            out: list[tuple[str, ...]] = []
            for r_len in range(k_int, -1, -1):
                for comb in combinations(interior, r_len):
                    out.append((first_oid, *comb, last_oid))
            return out
        non_Location_priority = sorted(
            range(k_int),
            key=lambda idx: (
                0
                if ctx.orders_by_id[interior[idx]].priority == PriorityTier.CRITICAL
                else (1 if ctx.orders_by_id[interior[idx]].priority == PriorityTier.STANDARD else 2),
                idx,
            ),
        )
        out_set: list[tuple[str, ...]] = [tuple(block), (first_oid, last_oid)]
        for drop_idx in reversed(non_Location_priority):
            sub = (first_oid, *(interior[k] for k in range(k_int) if k != drop_idx), last_oid)
            if sub not in out_set:
                out_set.append(sub)
            if len(out_set) >= cfg.bounded_max_skip_subsets_per_segment:
                break
        return out_set

    q_max = min(pool.max_routes_allowed, n)
    dp: list[list[list[SplitLabel]]] = [[[] for _ in range(q_max + 1)] for _ in range(n + 1)]
    init_label = SplitLabel(
        j=0,
        m=0,
        served_set=frozenset(),
        c_dec_paise=0,
        i_idle_seconds=0,
        coverage=(0, 0, 0),
        g_n_new_activations=0,
        route_descriptors=(),
    )
    dp[0][0] = [init_label]
    if telemetry is not None:
        telemetry.split_labels_created += 1

    for i_pos in range(n):
        for m_used in range(q_max + 1):
            curr_labels = dp[i_pos][m_used]
            if not curr_labels:
                continue

            if is_partial:
                next_skip_labels = [
                    SplitLabel(
                        j=i_pos + 1,
                        m=lbl.m,
                        served_set=lbl.served_set,
                        c_dec_paise=lbl.c_dec_paise,
                        i_idle_seconds=lbl.i_idle_seconds,
                        coverage=lbl.coverage,
                        g_n_new_activations=lbl.g_n_new_activations,
                        route_descriptors=lbl.route_descriptors,
                    )
                    for lbl in curr_labels
                ]
                if telemetry is not None:
                    telemetry.split_labels_created += len(next_skip_labels)
                merged, trunc = _prune_frontier(
                    dp[i_pos + 1][m_used] + next_skip_labels,
                    profile=cfg.profile,
                    planning_mode=cfg.planning_mode,
                    c_cap_paise=comparator.c_cap_paise,
                    balanced_cal=comparator.balanced_calibration,
                    max_labels=max_labels,
                    preserve_served_identity_ties=exact_tiny,
                    telemetry=telemetry,
                )
                dp[i_pos + 1][m_used] = merged
                any_truncated = any_truncated or trunc

            m_next = m_used + 1
            if m_next > q_max or not pool.is_route_count_admissible(m_next, is_terminal=False):
                continue

            slot_vehicle: VehicleSpec = pool.sorted_vehicles[m_next - 1]
            marg_act_cost = pool.marginal_activation_cost(m_next)
            marg_new_count = pool.marginal_new_activation_count(m_next)

            for j_pos in range(i_pos + 1, n + 1):
                subseqs = candidate_subsequences(i_pos, j_pos)
                any_feasible_for_block = False
                for subseq in subseqs:
                    for dep_s in departures:
                        seg = eval_segment(subseq, dep_s, slot_vehicle)
                        if seg is None:
                            continue
                        any_feasible_for_block = True
                        new_labels_batch: list[SplitLabel] = []
                        for lbl in curr_labels:
                            new_cov = (
                                lbl.coverage[0] + seg.coverage_delta[0],
                                lbl.coverage[1] + seg.coverage_delta[1],
                                lbl.coverage[2] + seg.coverage_delta[2],
                            )
                            new_labels_batch.append(
                                SplitLabel(
                                    j=j_pos,
                                    m=m_next,
                                    served_set=lbl.served_set | frozenset(seg.served_order_ids),
                                    c_dec_paise=lbl.c_dec_paise + seg.operating_cost_paise + marg_act_cost,
                                    i_idle_seconds=lbl.i_idle_seconds + seg.idle_waiting_seconds,
                                    coverage=new_cov,
                                    g_n_new_activations=lbl.g_n_new_activations + marg_new_count,
                                    route_descriptors=lbl.route_descriptors + ((dep_s, seg.served_order_ids),),
                                )
                            )
                        if telemetry is not None:
                            telemetry.split_labels_created += len(new_labels_batch)
                        merged, trunc = _prune_frontier(
                            dp[j_pos][m_next] + new_labels_batch,
                            profile=cfg.profile,
                            planning_mode=cfg.planning_mode,
                            c_cap_paise=comparator.c_cap_paise,
                            balanced_cal=comparator.balanced_calibration,
                            max_labels=max_labels,
                            preserve_served_identity_ties=exact_tiny,
                            telemetry=telemetry,
                        )
                        dp[j_pos][m_next] = merged
                        any_truncated = any_truncated or trunc

                if not is_partial and not any_feasible_for_block:
                    block_demand = sum(ctx.orders_by_id[oid].demand_units for oid in tour[i_pos:j_pos])
                    if block_demand > slot_vehicle.capacity_units:
                        break

    terminal_labels: list[SplitLabel] = []
    for m_used in range(0 if is_partial else 1, q_max + 1):
        if pool.is_route_count_admissible(m_used, is_terminal=True):
            terminal_labels.extend(dp[n][m_used])

    if not terminal_labels:
        return None, any_truncated

    best_plan: EvaluatedPlan | None = None
    default_unserved = (
        UnservedReason.UNSERVED_BY_DECODER_LIMIT
        if any_truncated
        else UnservedReason.UNSERVED_BY_OPTIMIZATION_DECISION
    )

    for lbl in terminal_labels:
        assign_res = assign_vehicles_to_routes(lbl.route_descriptors, pool)
        route_specs = [
            (
                assign_res.vehicle_id_by_route_index[r_idx],
                desc[0],
                desc[1],
            )
            for r_idx, desc in enumerate(lbl.route_descriptors)
        ]
        cand_plan = evaluate_plan(
            route_specs=route_specs,
            ctx=ctx,
            oracle=oracle,
            unserved_reasons_override=unserved_reasons_override,
            default_unserved_reason=default_unserved,
            telemetry=telemetry,
        )
        assert cand_plan.c_dec_paise == lbl.c_dec_paise, (
            f"Split DP cost {lbl.c_dec_paise} != canonical cost {cand_plan.c_dec_paise}"
        )
        assert cand_plan.idle_waiting_seconds == lbl.i_idle_seconds, (
            f"Split DP idle {lbl.i_idle_seconds} != canonical idle {cand_plan.idle_waiting_seconds}"
        )
        if best_plan is None or comparator.compare(cand_plan, best_plan) < 0:
            best_plan = cand_plan

    return best_plan, any_truncated
