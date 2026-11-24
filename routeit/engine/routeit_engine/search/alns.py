"""Adaptive Large Neighborhood Search (ALNS) & Genetic Algorithm (GA) (Q-HGALS 5.0 §6.8).

Both algorithms share the same `EvaluationContext`, `VehicleAwareSplit` / route evaluator,
`PlanComparator`, and `TelemetryCounters` budget accounting.
"""

from __future__ import annotations

import random
import time
from typing import Callable, Sequence

from routeit_engine.context.evaluation_context import EvaluationContext
from routeit_engine.contracts.types import (
    EvaluatedPlan,
    PriorityTier,
    StopReason,
    TelemetryCounters,
    UnservedReason,
)
from routeit_engine.oracle.protocol import RoadOracle
from routeit_engine.policy.comparators import PlanComparator
from routeit_engine.policy.vehicle_assignment import SortedVehiclePool
from routeit_engine.search.ls import improve_plan_local_search
from routeit_engine.split.decoder import decode_giant_tour_split


def _extract_tour_from_plan(plan: EvaluatedPlan, all_order_ids: Sequence[str]) -> list[str]:
    tour = [s.order_id for r in plan.routes for s in r.stops]
    for oid in all_order_ids:
        if oid not in tour:
            tour.append(oid)
    return tour


def run_alns_search(
    *,
    initial_plan: EvaluatedPlan,
    initial_tours: Sequence[Sequence[str]],
    ctx: EvaluationContext,
    oracle: RoadOracle,
    pool: SortedVehiclePool,
    comparator: PlanComparator,
    unserved_reasons_override: dict[str, tuple[UnservedReason, str]] | None,
    telemetry: TelemetryCounters,
    cancel_check: Callable[[], bool] | None = None,
    start_wall_time: float | None = None,
) -> tuple[EvaluatedPlan, StopReason, bool]:
    """Run Adaptive Large Neighborhood Search (ALNS) with roulette destroy/repair weights."""
    cfg = ctx.request.planning_config
    t_start = start_wall_time or time.monotonic()
    rng = random.Random(cfg.seed ^ 0x1357_9BDF)

    all_active_ids = sorted(
        oid
        for oid in ctx.orders_by_id
        if not unserved_reasons_override or oid not in unserved_reasons_override
    )
    if not all_active_ids:
        return initial_plan, StopReason.EVALUATION_BUDGET, False

    incumbent = initial_plan
    current_tour = _extract_tour_from_plan(incumbent, all_active_ids)

    # Destroy operators: 0=random_remove, 1=worst_window_slack, 2=shaw_related, 3=segment_remove
    destroy_weights = [1.0, 1.0, 1.0, 1.0]
    # Repair operators: 0=greedy_window_insert, 1=priority_deadline_insert, 2=randomized_insert
    repair_weights = [1.0, 1.0, 1.0]
    reaction_factor = 0.2

    seen_tours: set[tuple[str, ...]] = {tuple(current_tour)}
    no_improve_evals = 0
    any_truncated = False
    stop_reason = StopReason.EVALUATION_BUDGET

    while True:
        if cancel_check is not None and cancel_check():
            stop_reason = StopReason.CANCELLED
            break
        if time.monotonic() - t_start >= cfg.max_wall_seconds:
            stop_reason = StopReason.WALL_LIMIT
            break
        if telemetry.canonical_evaluations >= cfg.max_canonical_evaluations:
            stop_reason = StopReason.EVALUATION_BUDGET
            break
        if no_improve_evals >= cfg.stagnation_evaluations:
            stop_reason = StopReason.STAGNATION
            break

        telemetry.iterations_completed += 1
        telemetry.candidates_generated += 1

        # Select destroy and repair operators via seeded roulette wheel
        d_op = rng.choices([0, 1, 2, 3], weights=destroy_weights, k=1)[0]
        r_op = rng.choices([0, 1, 2], weights=repair_weights, k=1)[0]

        n = len(current_tour)
        k_remove = max(1, min(n - 1, rng.randint(1, max(1, n // 3)))) if n > 1 else 1
        working_tour = list(current_tour)

        if d_op == 0 or n <= 2:
            removed_indices = sorted(rng.sample(range(n), k_remove), reverse=True)
            removed = [working_tour.pop(idx) for idx in removed_indices]
        elif d_op == 1:
            # Remove orders with widest or most slack windows to re-position around tight ones
            ranked = sorted(
                working_tour,
                key=lambda oid: -(
                    ctx.orders_by_id[oid].window_close_utc_s - ctx.orders_by_id[oid].window_open_utc_s
                ),
            )
            removed = ranked[:k_remove]
            working_tour = [oid for oid in working_tour if oid not in set(removed)]
        elif d_op == 2:
            seed_oid = rng.choice(working_tour)
            seed_o = ctx.orders_by_id[seed_oid]
            ranked = sorted(
                working_tour,
                key=lambda oid: abs(ctx.orders_by_id[oid].window_open_utc_s - seed_o.window_open_utc_s)
                + abs(ctx.orders_by_id[oid].demand_units - seed_o.demand_units) * 60,
            )
            removed = ranked[:k_remove]
            working_tour = [oid for oid in working_tour if oid not in set(removed)]
        else:
            start_pos = rng.randint(0, max(0, n - k_remove))
            removed = working_tour[start_pos : start_pos + k_remove]
            del working_tour[start_pos : start_pos + k_remove]

        # Repair step
        if r_op == 0:
            removed.sort(key=lambda oid: (ctx.orders_by_id[oid].window_open_utc_s, oid))
        elif r_op == 1:
            removed.sort(
                key=lambda oid: (
                    0
                    if ctx.orders_by_id[oid].priority == PriorityTier.CRITICAL
                    else (1 if ctx.orders_by_id[oid].priority == PriorityTier.STANDARD else 2),
                    ctx.orders_by_id[oid].window_close_utc_s,
                    oid,
                )
            )
        else:
            rng.shuffle(removed)

        for oid in removed:
            o = ctx.orders_by_id[oid]
            best_pos = len(working_tour)
            for idx, existing_id in enumerate(working_tour):
                ex = ctx.orders_by_id[existing_id]
                if o.window_close_utc_s <= ex.window_close_utc_s:
                    best_pos = idx
                    break
            if r_op == 2 and working_tour:
                best_pos = rng.randint(0, len(working_tour))
            working_tour.insert(best_pos, oid)

        tour_tuple = tuple(working_tour)
        if tour_tuple in seen_tours:
            telemetry.evaluation_cache_hits += 1
            no_improve_evals += 1
            continue

        seen_tours.add(tour_tuple)
        telemetry.unique_permutations_decoded += 1
        telemetry.evaluation_cache_misses += 1

        evals_before = telemetry.canonical_evaluations
        cand_plan, trunc = decode_giant_tour_split(
            giant_tour_order_ids=working_tour,
            ctx=ctx,
            oracle=oracle,
            pool=pool,
            comparator=comparator,
            unserved_reasons_override=unserved_reasons_override,
            telemetry=telemetry,
        )
        any_truncated = any_truncated or trunc
        evals_delta = max(1, telemetry.canonical_evaluations - evals_before)

        reward = 0.1
        if cand_plan is not None and comparator.is_eligible(cand_plan):
            if comparator.is_better(cand_plan, incumbent):
                incumbent = cand_plan
                current_tour = _extract_tour_from_plan(incumbent, all_active_ids)
                telemetry.incumbent_updates += 1
                telemetry.convergence_trace.append(
                    {
                        "iteration": telemetry.iterations_completed,
                        "evaluations": telemetry.canonical_evaluations,
                        "c_dec_paise": incumbent.c_dec_paise,
                        "idle_seconds": incumbent.idle_waiting_seconds,
                        "coverage": list(incumbent.coverage_vector),
                    }
                )
                reward = 5.0
                no_improve_evals = 0
            else:
                no_improve_evals += evals_delta
                reward = 1.0
        else:
            no_improve_evals += evals_delta

        destroy_weights[d_op] = (1.0 - reaction_factor) * destroy_weights[d_op] + reaction_factor * reward
        repair_weights[r_op] = (1.0 - reaction_factor) * repair_weights[r_op] + reaction_factor * reward

    return incumbent, stop_reason, any_truncated


def _order_crossover_ox(p1: Sequence[str], p2: Sequence[str], rng: random.Random) -> list[str]:
    """Standard Order Crossover (OX) preserving relative order from p2 outside cut segment of p1."""
    n = len(p1)
    if n <= 2:
        return list(p1)
    a, b = sorted(rng.sample(range(n), 2))
    slice_p1 = p1[a : b + 1]
    slice_set = set(slice_p1)
    remaining = [x for x in p2 if x not in slice_set]
    child = remaining[:a] + list(slice_p1) + remaining[a:]
    return child


def run_ga_search(
    *,
    initial_plan: EvaluatedPlan,
    initial_tours: Sequence[Sequence[str]],
    ctx: EvaluationContext,
    oracle: RoadOracle,
    pool: SortedVehiclePool,
    comparator: PlanComparator,
    unserved_reasons_override: dict[str, tuple[UnservedReason, str]] | None,
    telemetry: TelemetryCounters,
    cancel_check: Callable[[], bool] | None = None,
    start_wall_time: float | None = None,
) -> tuple[EvaluatedPlan, StopReason, bool]:
    """Run Genetic Algorithm (GA) with Order Crossover (OX), swap/inversion mutation, and elitism."""
    cfg = ctx.request.planning_config
    t_start = start_wall_time or time.monotonic()
    rng = random.Random(cfg.seed ^ 0x2468_ACE0)

    all_active_ids = sorted(
        oid
        for oid in ctx.orders_by_id
        if not unserved_reasons_override or oid not in unserved_reasons_override
    )
    if not all_active_ids:
        return initial_plan, StopReason.EVALUATION_BUDGET, False

    pop_size = max(6, min(20, cfg.qpso_particles))
    population: list[tuple[list[str], EvaluatedPlan]] = [
        (_extract_tour_from_plan(initial_plan, all_active_ids), initial_plan)
    ]
    seen_tours: dict[tuple[str, ...], EvaluatedPlan | None] = {
        tuple(population[0][0]): initial_plan
    }
    any_truncated = False

    # Seed population from initial tours and random perturbations
    for tour in initial_tours:
        if len(population) >= pop_size or telemetry.canonical_evaluations >= cfg.max_canonical_evaluations:
            break
        filtered = [oid for oid in tour if oid in all_active_ids]
        for oid in all_active_ids:
            if oid not in filtered:
                filtered.append(oid)
        t_key = tuple(filtered)
        if t_key in seen_tours:
            continue
        p, trunc = decode_giant_tour_split(
            giant_tour_order_ids=filtered,
            ctx=ctx,
            oracle=oracle,
            pool=pool,
            comparator=comparator,
            unserved_reasons_override=unserved_reasons_override,
            telemetry=telemetry,
        )
        any_truncated = any_truncated or trunc
        seen_tours[t_key] = p
        if p is not None and comparator.is_eligible(p):
            population.append((filtered, p))

    while len(population) < pop_size:
        base_t = list(population[0][0])
        if len(base_t) > 1:
            i, j = rng.sample(range(len(base_t)), 2)
            base_t[i], base_t[j] = base_t[j], base_t[i]
        population.append((base_t, population[0][1]))

    incumbent = min((p for _, p in population), key=comparator.sort_key)
    no_improve_evals = 0
    stop_reason = StopReason.EVALUATION_BUDGET

    for _gen in range(cfg.qpso_generations):
        if cancel_check is not None and cancel_check():
            stop_reason = StopReason.CANCELLED
            break
        if time.monotonic() - t_start >= cfg.max_wall_seconds:
            stop_reason = StopReason.WALL_LIMIT
            break
        if telemetry.canonical_evaluations >= cfg.max_canonical_evaluations:
            stop_reason = StopReason.EVALUATION_BUDGET
            break
        if no_improve_evals >= cfg.stagnation_evaluations:
            stop_reason = StopReason.STAGNATION
            break

        telemetry.iterations_completed += 1
        population.sort(key=lambda item: comparator.sort_key(item[1]))
        next_pop: list[tuple[list[str], EvaluatedPlan]] = population[:2]  # Elitism

        while len(next_pop) < pop_size:
            if telemetry.canonical_evaluations >= cfg.max_canonical_evaluations:
                break
            # Binary tournament selection
            c1, c2 = rng.sample(population, 2)
            p1 = c1[0] if comparator.compare(c1[1], c2[1]) <= 0 else c2[0]
            c3, c4 = rng.sample(population, 2)
            p2 = c3[0] if comparator.compare(c3[1], c4[1]) <= 0 else c4[0]

            child = _order_crossover_ox(p1, p2, rng)
            if len(child) >= 2 and rng.random() < 0.35:
                i, j = sorted(rng.sample(range(len(child)), 2))
                if rng.random() < 0.5:
                    child[i], child[j] = child[j], child[i]
                else:
                    child[i : j + 1] = reversed(child[i : j + 1])

            telemetry.candidates_generated += 1
            t_key = tuple(child)
            if t_key in seen_tours:
                telemetry.evaluation_cache_hits += 1
                cached_p = seen_tours[t_key]
                if cached_p is not None:
                    next_pop.append((child, cached_p))
                else:
                    next_pop.append(population[0])
                continue

            telemetry.unique_permutations_decoded += 1
            telemetry.evaluation_cache_misses += 1
            evals_before = telemetry.canonical_evaluations
            cand_p, trunc = decode_giant_tour_split(
                giant_tour_order_ids=child,
                ctx=ctx,
                oracle=oracle,
                pool=pool,
                comparator=comparator,
                unserved_reasons_override=unserved_reasons_override,
                telemetry=telemetry,
            )
            any_truncated = any_truncated or trunc
            evals_delta = max(1, telemetry.canonical_evaluations - evals_before)

            if cand_p is not None and comparator.is_eligible(cand_p):
                if comparator.is_better(cand_p, incumbent):
                    # Pure GA chromosome evaluation via Split decoder
                    incumbent = cand_p
                    telemetry.incumbent_updates += 1
                    telemetry.convergence_trace.append(
                        {
                            "iteration": telemetry.iterations_completed,
                            "evaluations": telemetry.canonical_evaluations,
                            "c_dec_paise": incumbent.c_dec_paise,
                            "idle_seconds": incumbent.idle_waiting_seconds,
                            "coverage": list(incumbent.coverage_vector),
                        }
                    )
                    no_improve_evals = 0
                else:
                    no_improve_evals += evals_delta
                seen_tours[t_key] = cand_p
                next_pop.append((child, cand_p))
            else:
                seen_tours[t_key] = None
                no_improve_evals += evals_delta
                next_pop.append(population[0])

        population = next_pop

    return incumbent, stop_reason, any_truncated
