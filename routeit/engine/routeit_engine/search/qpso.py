"""Quantum-Behaved Particle Swarm Optimization (QPSO / Q-HGALS 5.0 §6.8.1 & §7 QPSO-01..06).

Implements the exact normative Q-HGALS 5.0 QPSO specification:
- Random-key representation `x_i in [0, 1]^n`, decoded by sorting `(key, stable_order_id)` ascending.
- Reproducible open-unit pseudo-uniform draw mapping `k / 2^53` for `k in {1, ..., 2^53 - 1}` (never 0.0 or 1.0).
- Mean best position `mbest_d = (1 / P) * sum_{i=1..P} pbest_{i,d}` in stable particle-ID order (`QPSO-01`).
- Contraction-expansion coefficient schedule `alpha_t = alpha_max - (alpha_max - alpha_min) * t / (T - 1)` for `T > 1`,
  and `alpha_0 = alpha_max` for `T == 1` (`QPSO-02`).
- Local attractor `p_{i,d} = phi * pbest_{i,d} + (1 - phi) * gbest_d`.
- Position update `y_{i,d} = p_{i,d} + sigma * alpha_t * |mbest_d - x_{i,d}| * ln(1 / u)` (`QPSO-05`).
- Triangular-wave reflection into `[0, 1]` (`Reflect(-0.25)=0.25, Reflect(1.25)=0.75, Reflect(2.25)=0.25`, `QPSO-03`).
- Synchronous generation updates, deduplication of decoded permutations, and `ARCHIVE_ONLY`, `BALDWINIAN`, and `OS_RELABEL` memory modes.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import random
import time
from typing import Callable, Sequence

from routeit_engine.context.evaluation_context import EvaluationContext
from routeit_engine.contracts.types import (
    EvaluatedPlan,
    QPSOMemoryMode,
    StopReason,
    TelemetryCounters,
    UnservedReason,
)
from routeit_engine.money.ledger import NumericRangeError
from routeit_engine.oracle.protocol import RoadOracle
from routeit_engine.policy.comparators import PlanComparator
from routeit_engine.policy.vehicle_assignment import SortedVehiclePool
from routeit_engine.search.ls import improve_plan_local_search
from routeit_engine.split.decoder import decode_giant_tour_split

TWO_POW_53 = 1 << 53


class OpenUnitPRNGStream:
    """Deterministic PRNG stream producing open-unit draws u in (0, 1) via k / 2^53 (Q-HGALS 5.0 §6.8.1, QPSO-04)."""

    def __init__(self, seed: int, stream_id: int = 0) -> None:
        combined_seed = ((seed & 0xFFFF_FFFF_FFFF_FFFF) * 6364136223846793005 + (stream_id + 1) * 1442695040888963407) & 0xFFFF_FFFF_FFFF_FFFF
        self._rng = random.Random(combined_seed)

    def draw_open_unit(self) -> float:
        """Sample integer k uniformly in {1, ..., 2^53 - 1} and return k / 2^53 in (0, 1)."""
        k = self._rng.randint(1, TWO_POW_53 - 1)
        val = float(k) / float(TWO_POW_53)
        assert 0.0 < val < 1.0, "Open-unit draw must be strictly in (0, 1)"
        return val

    def draw_sigma(self) -> float:
        """Draw sigma in {-1.0, +1.0} with P(-1) = P(+1) = 1/2."""
        return -1.0 if self._rng.getrandbits(1) == 0 else 1.0


def compute_mbest_vector(pbest_vectors: Sequence[Sequence[float]]) -> tuple[float, ...]:
    """Compute coordinate-wise mean best position `mbest` in stable particle-ID order (QPSO-01, QPSO-06)."""
    p_count = len(pbest_vectors)
    if p_count < 1:
        raise ValueError("Cannot compute mbest on empty particle population (require P >= 1)")
    dim = len(pbest_vectors[0])
    out: list[float] = []
    for d in range(dim):
        total = 0.0
        for i in range(p_count):
            val = pbest_vectors[i][d]
            if not math.isfinite(val):
                raise NumericRangeError(f"Non-finite pbest coordinate at particle {i}, dim {d}")
            total += val
        out.append(total / float(p_count))
    return tuple(out)


def compute_alpha_schedule(t_index: int, total_generations: int, alpha_max: float, alpha_min: float) -> float:
    """Linear contraction schedule per Q-HGALS 5.0 §6.8.1 (QPSO-02, QPSO-06):
    For T > 1: alpha_t = alpha_max - (alpha_max - alpha_min) * t / (T - 1), t = 0, ..., T - 1.
    For T == 1: alpha_0 = alpha_max.
    """
    if (
        not math.isfinite(alpha_max)
        or not math.isfinite(alpha_min)
        or alpha_min <= 0.0
        or alpha_max < alpha_min
    ):
        raise NumericRangeError(f"Invalid alpha bounds: alpha_min={alpha_min}, alpha_max={alpha_max}")
    if total_generations < 1 or t_index < 0 or t_index >= total_generations:
        raise ValueError(f"Invalid generation index t={t_index} for T={total_generations}")
    if total_generations == 1:
        return float(alpha_max)
    return float(alpha_max - (alpha_max - alpha_min) * (float(t_index) / float(total_generations - 1)))


def reflect_into_unit_interval(y: float) -> float:
    """Triangular-wave reflection into [0, 1] per Q-HGALS 5.0 §6.8.1 (QPSO-03):
    Reflect(-0.25) = 0.25, Reflect(0.0) = 0.0, Reflect(1.0) = 1.0,
    Reflect(1.25) = 0.75, Reflect(2.25) = 0.25.
    """
    if not math.isfinite(y) or abs(y) > 1e12:
        raise NumericRangeError(f"Non-finite or unrepresentable particle coordinate y={y}")
    if 0.0 <= y <= 1.0:
        return float(y)
    # Period-2 triangular wave: r = y mod 2.0 in [0, 2); return r if r <= 1 else 2 - r
    r = math.fmod(y, 2.0)
    if r < 0.0:
        r += 2.0
    reflected = r if r <= 1.0 else (2.0 - r)
    # Guard against tiny IEEE-754 rounding near 0 or 1
    return max(0.0, min(1.0, reflected))


def qpso_update_coordinate(
    *,
    x: float,
    pbest: float,
    gbest: float,
    mbest: float,
    alpha: float,
    phi: float,
    sigma: float,
    u: float,
) -> tuple[float, float, float]:
    """Single-coordinate QPSO update per Q-HGALS 5.0 §6.8.1 (QPSO-05, QPSO-06).

    Equations:
        p = phi * pbest + (1 - phi) * gbest
        y = p + sigma * alpha * |mbest - x| * ln(1 / u)
        x_next = Reflect(y)
    Returns `(p, y, x_next)`.
    """
    for name, val in [
        ("x", x),
        ("pbest", pbest),
        ("gbest", gbest),
        ("mbest", mbest),
        ("alpha", alpha),
        ("phi", phi),
        ("sigma", sigma),
        ("u", u),
    ]:
        if not math.isfinite(val):
            raise NumericRangeError(f"Non-finite QPSO operand {name}={val}")

    if alpha <= 0.0:
        raise NumericRangeError(f"alpha must be > 0, got {alpha}")
    if u <= 0.0 or u >= 1.0:
        raise NumericRangeError(f"Uniform draw u must be in open interval (0, 1), got {u}")
    if sigma not in (-1.0, 1.0):
        raise NumericRangeError(f"sigma must be -1.0 or +1.0, got {sigma}")

    p = phi * pbest + (1.0 - phi) * gbest
    dist = abs(mbest - x)
    if dist == 0.0:
        y = p
    else:
        y = p + sigma * alpha * dist * math.log(1.0 / u)
    x_next = reflect_into_unit_interval(y)
    return (p, y, x_next)


def decode_random_keys_to_tour(keys: Sequence[float], sorted_order_ids: Sequence[str]) -> tuple[str, ...]:
    """Decode random-key vector into a giant-tour permutation by sorting (key, stable_order_id) ascending."""
    if len(keys) != len(sorted_order_ids):
        raise ValueError("Key vector length must equal number of active orders")
    paired = [(keys[idx], sorted_order_ids[idx]) for idx in range(len(keys))]
    paired.sort(key=lambda item: (item[0], item[1]))
    return tuple(oid for _, oid in paired)


def encode_tour_to_random_keys(tour: Sequence[str], sorted_order_ids: Sequence[str]) -> tuple[float, ...]:
    """Invert a permutation into evenly spaced rank keys in (0, 1) for OS_RELABEL or seed initialization."""
    n = len(sorted_order_ids)
    if n == 0:
        return ()
    rank_by_oid: dict[str, int] = {oid: rank for rank, oid in enumerate(tour)}
    keys: list[float] = []
    for idx, oid in enumerate(sorted_order_ids):
        r = rank_by_oid.get(oid, idx)
        keys.append((float(r) + 1.0) / float(n + 1))
    return tuple(keys)


@dataclass
class ParticleRecord:
    particle_id: int
    position_keys: tuple[float, ...]
    decoded_permutation: tuple[str, ...]
    current_plan: EvaluatedPlan | None
    pbest_keys: tuple[float, ...]
    pbest_permutation: tuple[str, ...]
    pbest_plan: EvaluatedPlan
    context_hash: str


def run_qpso_search(
    *,
    seed_plans: Sequence[EvaluatedPlan],
    initial_tours: Sequence[Sequence[str]],
    ctx: EvaluationContext,
    oracle: RoadOracle,
    pool: SortedVehiclePool,
    comparator: PlanComparator,
    unserved_reasons_override: dict[str, tuple[UnservedReason, str]] | None,
    telemetry: TelemetryCounters,
    cancel_check: Callable[[], bool] | None = None,
    start_wall_time: float | None = None,
) -> tuple[EvaluatedPlan | None, StopReason, bool]:
    """Execute synchronous QPSO search per Q-HGALS 5.0 §6.8.1."""
    cfg = ctx.request.planning_config
    t_start = start_wall_time or time.monotonic()

    # Validate alpha bounds and population parameters upfront (QPSO-06)
    _ = compute_alpha_schedule(0, cfg.qpso_generations, cfg.qpso_alpha_max, cfg.qpso_alpha_min)

    eligible_seeds = [p for p in seed_plans if comparator.is_eligible(p)]
    if not eligible_seeds:
        # Q-HGALS 5.0 §6.8.1 & QPSO-04: If there is no eligible feasible seed, do NOT launch QPSO without an attractor!
        return None, StopReason.EVALUATION_BUDGET, False

    sorted_order_ids = tuple(
        sorted(
            oid
            for oid in ctx.orders_by_id
            if not unserved_reasons_override or oid not in unserved_reasons_override
        )
    )
    n_dim = len(sorted_order_ids)
    best_seed = min(eligible_seeds, key=comparator.sort_key)
    if n_dim == 0:
        return best_seed, StopReason.EVALUATION_BUDGET, False

    p_count = max(1, cfg.qpso_particles)
    t_max = max(1, cfg.qpso_generations)
    prng = OpenUnitPRNGStream(cfg.seed, stream_id=1)

    # Deduplication cache for decoded permutations within the frozen context
    decoded_cache: dict[tuple[str, ...], EvaluatedPlan | None] = {}
    any_truncated = False

    # Initialize particles
    particles: list[ParticleRecord] = []
    for p_idx in range(p_count):
        if p_idx < len(eligible_seeds):
            seed_plan = eligible_seeds[p_idx]
            seed_tour = [s.order_id for r in seed_plan.routes for s in r.stops]
            for oid in sorted_order_ids:
                if oid not in seed_tour:
                    seed_tour.append(oid)
            keys = encode_tour_to_random_keys(seed_tour, sorted_order_ids)
            perm = decode_random_keys_to_tour(keys, sorted_order_ids)
            decoded_cache[perm] = seed_plan
            particles.append(
                ParticleRecord(
                    particle_id=p_idx,
                    position_keys=keys,
                    decoded_permutation=perm,
                    current_plan=seed_plan,
                    pbest_keys=keys,
                    pbest_permutation=perm,
                    pbest_plan=seed_plan,
                    context_hash=ctx.context_hash,
                )
            )
        else:
            keys = tuple(prng.draw_open_unit() for _ in range(n_dim))
            perm = decode_random_keys_to_tour(keys, sorted_order_ids)
            # Per Q-HGALS 5.0 §6.8.1: copy the best eligible seed key vector/evaluation so every pbest is defined
            best_seed_tour = [s.order_id for r in best_seed.routes for s in r.stops]
            for oid in sorted_order_ids:
                if oid not in best_seed_tour:
                    best_seed_tour.append(oid)
            best_seed_keys = encode_tour_to_random_keys(best_seed_tour, sorted_order_ids)
            particles.append(
                ParticleRecord(
                    particle_id=p_idx,
                    position_keys=keys,
                    decoded_permutation=perm,
                    current_plan=None,
                    pbest_keys=best_seed_keys,
                    pbest_permutation=tuple(best_seed_tour),
                    pbest_plan=best_seed,
                    context_hash=ctx.context_hash,
                )
            )

    gbest_plan = min((pt.pbest_plan for pt in particles), key=comparator.sort_key)
    gbest_particle = min(particles, key=lambda pt: (comparator.sort_key(pt.pbest_plan), pt.particle_id))
    gbest_keys = gbest_particle.pbest_keys

    no_improve_evals = 0
    stop_reason = StopReason.EVALUATION_BUDGET

    # Synchronous QPSO generation loop
    for gen_t in range(t_max):
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

        # 1. Snapshot pbest, gbest, mbest, and alpha_t before updating any particle
        frozen_pbest_vectors = [pt.pbest_keys for pt in particles]
        frozen_gbest_keys = gbest_keys
        mbest = compute_mbest_vector(frozen_pbest_vectors)
        alpha_t = compute_alpha_schedule(gen_t, t_max, cfg.qpso_alpha_max, cfg.qpso_alpha_min)

        # 2. Generate all new particle coordinate vectors synchronously
        proposed_keys_by_particle: list[tuple[float, ...]] = []
        proposed_perms_by_particle: list[tuple[str, ...]] = []
        for p_idx, pt in enumerate(particles):
            new_coords: list[float] = []
            for d in range(n_dim):
                phi = prng.draw_open_unit()
                u = prng.draw_open_unit()
                sigma = prng.draw_sigma()
                _, _, x_next = qpso_update_coordinate(
                    x=pt.position_keys[d],
                    pbest=frozen_pbest_vectors[p_idx][d],
                    gbest=frozen_gbest_keys[d],
                    mbest=mbest[d],
                    alpha=alpha_t,
                    phi=phi,
                    sigma=sigma,
                    u=u,
                )
                new_coords.append(x_next)
            k_tuple = tuple(new_coords)
            perm = decode_random_keys_to_tour(k_tuple, sorted_order_ids)
            proposed_keys_by_particle.append(k_tuple)
            proposed_perms_by_particle.append(perm)
            telemetry.candidates_generated += 1

        # 3. Decode unique permutations and canonical-evaluate in stable candidate order
        gen_improved = False
        evals_before_gen = telemetry.canonical_evaluations

        for p_idx, pt in enumerate(particles):
            if telemetry.canonical_evaluations >= cfg.max_canonical_evaluations:
                break
            k_tuple = proposed_keys_by_particle[p_idx]
            perm = proposed_perms_by_particle[p_idx]

            if perm in decoded_cache:
                telemetry.evaluation_cache_hits += 1
                cand_plan = decoded_cache[perm]
            else:
                telemetry.unique_permutations_decoded += 1
                telemetry.evaluation_cache_misses += 1
                cand_plan, trunc = decode_giant_tour_split(
                    giant_tour_order_ids=perm,
                    ctx=ctx,
                    oracle=oracle,
                    pool=pool,
                    comparator=comparator,
                    unserved_reasons_override=unserved_reasons_override,
                    telemetry=telemetry,
                )
                any_truncated = any_truncated or trunc

                if (
                    cand_plan is not None
                    and comparator.is_eligible(cand_plan)
                    and cfg.enable_local_search_refinement
                    and telemetry.canonical_evaluations < cfg.max_canonical_evaluations
                ):
                    # Refine top candidates with bounded local search
                    if comparator.is_better(cand_plan, pt.pbest_plan) or p_idx == 0:
                        rem_ls = max(1, min(12, cfg.max_canonical_evaluations - telemetry.canonical_evaluations))
                        refined = improve_plan_local_search(
                            cand_plan,
                            ctx,
                            oracle,
                            pool,
                            comparator,
                            max_evaluations=rem_ls,
                            unserved_reasons_override=unserved_reasons_override,
                            telemetry=telemetry,
                        )
                        if comparator.is_better(refined, cand_plan):
                            cand_plan = refined
                            if cfg.qpso_memory_mode == QPSOMemoryMode.OS_RELABEL:
                                relabeled_tour = [s.order_id for r in refined.routes for s in r.stops]
                                for oid in sorted_order_ids:
                                    if oid not in relabeled_tour:
                                        relabeled_tour.append(oid)
                                k_tuple = encode_tour_to_random_keys(relabeled_tour, sorted_order_ids)

                decoded_cache[perm] = cand_plan

            pt.position_keys = k_tuple
            pt.decoded_permutation = perm
            pt.current_plan = cand_plan

            # 4. Update pbest only if candidate is hard-feasible, profile-eligible, and strictly better under comparator
            if cand_plan is not None and comparator.is_eligible(cand_plan):
                if comparator.compare(cand_plan, pt.pbest_plan) < 0:
                    pt.pbest_keys = k_tuple
                    pt.pbest_permutation = perm
                    pt.pbest_plan = cand_plan

                if comparator.compare(cand_plan, gbest_plan) < 0:
                    gbest_plan = cand_plan
                    gbest_keys = k_tuple
                    gen_improved = True
                    telemetry.incumbent_updates += 1
                    telemetry.convergence_trace.append(
                        {
                            "iteration": telemetry.iterations_completed,
                            "evaluations": telemetry.canonical_evaluations,
                            "alpha_t": round(alpha_t, 4),
                            "c_dec_paise": gbest_plan.c_dec_paise,
                            "idle_seconds": gbest_plan.idle_waiting_seconds,
                            "coverage": list(gbest_plan.coverage_vector),
                        }
                    )

        evals_delta = max(1, telemetry.canonical_evaluations - evals_before_gen)
        if gen_improved:
            no_improve_evals = 0
        else:
            no_improve_evals += evals_delta

    return gbest_plan, stop_reason, any_truncated
