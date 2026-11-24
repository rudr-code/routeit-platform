"""Profile calibration, Type-7 quantiles, and lexicographic PlanComparator (Q-HGALS 5.0 §3, §6.7)."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Sequence

from routeit_engine.contracts.types import (
    BalancedNormalizationMode,
    EvaluatedPlan,
    OptimizationProfile,
    PlanningConfig,
    PlanningMode,
)
from routeit_engine.money.ledger import checked_mul, round_half_even


def type7_quantile_exact(sorted_values: Sequence[int], q: Fraction) -> Fraction:
    """Exact Type-7 quantile per Q-HGALS 5.0 §6.7:
    h = 1 + (N - 1)*q, j = floor(h), gamma = h - j,
    Q_q = (1 - gamma)*X_(j) + gamma*X_(min(j+1, N)) using 1-based order statistics.
    """
    n = len(sorted_values)
    if n == 0:
        raise ValueError("Cannot compute Type-7 quantile on empty sample")
    if n == 1:
        return Fraction(sorted_values[0], 1)
    h = Fraction(1, 1) + Fraction(n - 1, 1) * q
    j = int(h.numerator // h.denominator)  # floor(h) since h >= 1
    gamma = h - Fraction(j, 1)
    # Convert 1-based index j to 0-based index j-1
    idx_j = j - 1
    idx_next = min(j, n - 1)
    x_j = Fraction(sorted_values[idx_j], 1)
    x_next = Fraction(sorted_values[idx_next], 1)
    return (Fraction(1, 1) - gamma) * x_j + gamma * x_next


@dataclass(frozen=True)
class BalancedCalibration:
    """Frozen calibration anchors and scales for the Balanced profile (Q-HGALS 5.0 §6.7)."""

    c0_paise: int
    i0_seconds: int
    s_c_paise: int
    s_i_seconds: int
    low_calibration_quality: bool
    calibration_coverage_class: tuple[int, int, int]
    sample_size: int
    mode: BalancedNormalizationMode = BalancedNormalizationMode.QUANTILE_TYPE7

    def cross_product_score(self, c_dec_paise: int, i_idle_seconds: int) -> int:
        """Exact integer numerator of J_B * (S_C * S_I):
        (C_dec - C0) * S_I + (I_idle - I0) * S_C.
        Uses checked BigInt multiplication with zero floating-point error.
        """
        term_c = checked_mul(c_dec_paise - self.c0_paise, self.s_i_seconds)
        term_i = checked_mul(i_idle_seconds - self.i0_seconds, self.s_c_paise)
        return term_c + term_i

    def normalized_float_preview(self, c_dec_paise: int, i_idle_seconds: int) -> float:
        """Display-only normalized scalar; never used for authoritative ordering."""
        c_norm = (c_dec_paise - self.c0_paise) / max(1, self.s_c_paise)
        i_norm = (i_idle_seconds - self.i0_seconds) / max(1, self.s_i_seconds)
        return 0.5 * c_norm + 0.5 * i_norm

    def to_dict(self) -> dict[str, object]:
        return {
            "c0_paise": self.c0_paise,
            "i0_seconds": self.i0_seconds,
            "s_c_paise": self.s_c_paise,
            "s_i_seconds": self.s_i_seconds,
            "low_calibration_quality": self.low_calibration_quality,
            "calibration_coverage_class": list(self.calibration_coverage_class),
            "sample_size": self.sample_size,
            "mode": self.mode.value,
        }


def calibrate_balanced_profile(
    seed_plans: Sequence[EvaluatedPlan],
    planning_mode: PlanningMode,
    norm_mode: BalancedNormalizationMode = BalancedNormalizationMode.QUANTILE_TYPE7,
) -> BalancedCalibration | None:
    """Derive frozen Balanced calibration from best-observed initial coverage class (Q-HGALS 5.0 §6.7)."""
    if planning_mode == PlanningMode.COMPLETE:
        eligible = [p for p in seed_plans if p.hard_feasible and p.complete_feasible]
    else:
        eligible = [p for p in seed_plans if p.hard_feasible]

    if not eligible:
        return None

    best_coverage = max(p.coverage_vector for p in eligible)
    class_sample = [p for p in eligible if p.coverage_vector == best_coverage]

    c_vals = sorted(p.c_dec_paise for p in class_sample)
    i_vals = sorted(p.idle_waiting_seconds for p in class_sample)

    c0 = c_vals[0]
    i0 = i_vals[0]

    if norm_mode == BalancedNormalizationMode.MIN_MAX:
        raw_sc = c_vals[-1] - c_vals[0]
        raw_si = i_vals[-1] - i_vals[0]
        low_quality = (raw_sc < 1) or (raw_si < 1) or (len(class_sample) < 2)
        s_c = max(1, raw_sc)
        s_i = max(1, raw_si)
    else:
        q10_c = type7_quantile_exact(c_vals, Fraction(1, 10))
        q90_c = type7_quantile_exact(c_vals, Fraction(9, 10))
        spread_c = q90_c - q10_c
        rounded_c = round_half_even(spread_c.numerator, spread_c.denominator)

        q10_i = type7_quantile_exact(i_vals, Fraction(1, 10))
        q90_i = type7_quantile_exact(i_vals, Fraction(9, 10))
        spread_i = q90_i - q10_i
        rounded_i = round_half_even(spread_i.numerator, spread_i.denominator)

        low_quality = (rounded_c < 1) or (rounded_i < 1) or (len(class_sample) < 2)
        s_c = max(1, rounded_c)
        s_i = max(1, rounded_i)

    return BalancedCalibration(
        c0_paise=c0,
        i0_seconds=i0,
        s_c_paise=s_c,
        s_i_seconds=s_i,
        low_calibration_quality=low_quality,
        calibration_coverage_class=best_coverage,
        sample_size=len(class_sample),
        mode=norm_mode,
    )


class PlanComparator:
    """Authoritative lexicographic comparator across all profiles and modes (Q-HGALS 5.0 §3.1–§3.5)."""

    def __init__(
        self,
        config: PlanningConfig,
        balanced_calibration: BalancedCalibration | None = None,
        c_cap_paise: int | None = None,
    ) -> None:
        self.config = config
        self.balanced_calibration = balanced_calibration
        if c_cap_paise is not None:
            self.c_cap_paise: int | None = c_cap_paise
        elif (
            config.profile == OptimizationProfile.DRIVER_PRODUCTIVITY
            and config.reference_cost_paise is not None
            and config.max_extra_cost_paise is not None
        ):
            if config.max_extra_cost_paise < 0 or config.reference_cost_paise < 0:
                raise ValueError("Driver Productivity reference_cost_paise and max_extra_cost_paise must be >= 0")
            self.c_cap_paise = config.reference_cost_paise + config.max_extra_cost_paise
        else:
            self.c_cap_paise = None

    def is_eligible(self, plan: EvaluatedPlan) -> bool:
        """Check hard feasibility, mode completeness, and Driver Productivity cost-cap gate."""
        if not plan.hard_feasible:
            return False
        if self.config.planning_mode == PlanningMode.COMPLETE and not plan.complete_feasible:
            return False
        if self.config.profile == OptimizationProfile.DRIVER_PRODUCTIVITY:
            if self.c_cap_paise is None:
                return False
            # Inclusive cap check: C_dec <= C_cap passes (Q-HGALS 5.0 §3.1, CMP-07)
            if plan.c_dec_paise > self.c_cap_paise:
                return False
        return True

    def sort_key(self, plan: EvaluatedPlan) -> tuple[object, ...]:
        """Return a tuple where strictly smaller values are strictly preferred (minimization key).

        Ordering hierarchy (Q-HGALS 5.0 §3.1, §3.3, §3.4):
        1. Eligibility gate: 0 if eligible (hard-feasible + mode-valid + cap-eligible), 1 otherwise.
        2. Hard feasibility gate (if ineligible): 0 if hard-feasible, 1 otherwise.
        3. Coverage tuple in Partial Mode: (-N_C, -N_S, -N_F) so higher coverage sorts first.
        4. Profile objective tuple:
           - COST_FOCUSED: (C_dec, I_idle, M_shift_activated_after)
           - BALANCED: (J_B_cross_product, C_dec, I_idle, M_shift_activated_after)
           - DRIVER_PRODUCTIVITY: (I_idle, C_dec, M_shift_activated_after)
        5. Common deterministic fallback (Q-HGALS 5.0 §3.3):
           - served_signature: tuple of (-1 if served else 0) in Critical -> Standard -> Flexible, ascending ID
             so inclusion (served=-1 < unserved=0) wins at the first differing bit!
           - canonical_route_signature: sorted by (vehicle_id, departure_s, stop_ids)
           - plan_hash ascending
        """
        eligible_rank = 0 if self.is_eligible(plan) else 1
        hard_rank = 0 if plan.hard_feasible else 1
        complete_rank = (
            0
            if (self.config.planning_mode != PlanningMode.COMPLETE or plan.complete_feasible)
            else 1
        )
        cap_rank = 0
        if self.config.profile == OptimizationProfile.DRIVER_PRODUCTIVITY:
            if self.c_cap_paise is None or plan.c_dec_paise > self.c_cap_paise:
                cap_rank = 1

        n_c, n_s, n_f = plan.coverage_vector
        coverage_key = (-n_c, -n_s, -n_f)

        if self.config.profile == OptimizationProfile.COST_FOCUSED:
            profile_key: tuple[int, ...] = (
                plan.c_dec_paise,
                plan.idle_waiting_seconds,
                plan.m_shift_activated_after,
            )
        elif self.config.profile == OptimizationProfile.BALANCED:
            if self.balanced_calibration is not None:
                jb = self.balanced_calibration.cross_product_score(
                    plan.c_dec_paise, plan.idle_waiting_seconds
                )
            else:
                jb = plan.c_dec_paise + plan.idle_waiting_seconds
            profile_key = (
                jb,
                plan.c_dec_paise,
                plan.idle_waiting_seconds,
                plan.m_shift_activated_after,
            )
        else:  # DRIVER_PRODUCTIVITY
            profile_key = (
                plan.idle_waiting_seconds,
                plan.c_dec_paise,
                plan.m_shift_activated_after,
            )

        return (
            eligible_rank,
            hard_rank,
            cap_rank,
            complete_rank,
            coverage_key,
            profile_key,
            plan.served_signature,
            plan.canonical_route_signature,
            plan.plan_hash,
        )

    def compare(self, x: EvaluatedPlan, y: EvaluatedPlan) -> int:
        """Compare two plans in the same context: returns -1 if x < y (x is better), +1 if y < x, 0 if identical."""
        if x.context_hash != y.context_hash:
            raise ValueError("Cannot compare plans from different EvaluationContexts")
        kx = self.sort_key(x)
        ky = self.sort_key(y)
        if kx < ky:
            return -1
        if kx > ky:
            return 1
        return 0

    def is_better(self, candidate: EvaluatedPlan, incumbent: EvaluatedPlan | None) -> bool:
        if not self.is_eligible(candidate):
            return False
        if incumbent is None or not self.is_eligible(incumbent):
            return True
        return self.compare(candidate, incumbent) < 0
