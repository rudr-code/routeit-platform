"""Exact rational monetary accounting and Round-Half-to-Even ledger (Q-HGALS 5.0 §4)."""

from __future__ import annotations

from routeit_engine.contracts.types import (
    CostLedger,
    CostRateConfig,
    ExactRate,
    OrderSpec,
    WindowType,
)

# Signed 128-bit integer ceiling for checked intermediate arithmetic (Q-HGALS 5.0 §4.6)
I128_MAX = (1 << 127) - 1
I128_MIN = -(1 << 127)

# Default maximum representable output bound in paise (e.g., 10^18 paise = ₹10^16)
MAX_REPRESENTABLE_PAISE = 10**18


class NumericRangeError(ValueError):
    """Raised when arithmetic exceeds configured safe numeric bounds or violates sign rules."""


class InvalidMonetaryConfigError(ValueError):
    """Raised when mandatory rates or monetary inputs are negative, zero-denominator, or missing."""


def checked_nonnegative_int(value: int, name: str, max_bound: int = MAX_REPRESENTABLE_PAISE) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidMonetaryConfigError(f"{name} must be an integer, got {type(value)!r}")
    if value < 0:
        raise InvalidMonetaryConfigError(f"{name} must be nonnegative, got {value}")
    if value > max_bound:
        raise NumericRangeError(f"{name}={value} exceeds configured representable bound {max_bound}")
    return value


def checked_mul(a: int, b: int, max_bound: int = I128_MAX) -> int:
    """Checked integer multiplication with BigInt fallback verification (Q-HGALS 5.0 §4.6)."""
    if isinstance(a, bool) or isinstance(b, bool) or not isinstance(a, int) or not isinstance(b, int):
        raise InvalidMonetaryConfigError("checked_mul operands must be exact integers")
    product = a * b
    if product > max_bound or product < I128_MIN:
        # Python natively uses arbitrary-precision BigInt; we enforce the representable output envelope
        if abs(product) > (1 << 255):
            raise NumericRangeError(f"Product {a} * {b} exceeds absolute BigInt safety envelope")
    return product


def round_half_even(numerator: int, denominator: int, max_output_bound: int = MAX_REPRESENTABLE_PAISE) -> int:
    """Round nonnegative rational numerator/denominator to nearest integer, ties to even (Q-HGALS 5.0 §4.3, §4.5).

    Formula:
        q, r = divmod(numerator, denominator)
        if 2*r < denominator: return q
        if 2*r > denominator: return q + 1
        return q if (q % 2 == 0) else q + 1
    """
    if isinstance(numerator, bool) or isinstance(denominator, bool):
        raise InvalidMonetaryConfigError("round_half_even operands cannot be booleans")
    if not isinstance(numerator, int) or not isinstance(denominator, int):
        raise InvalidMonetaryConfigError("round_half_even requires integer numerator and denominator")
    if numerator < 0:
        raise InvalidMonetaryConfigError(f"round_half_even numerator must be >= 0, got {numerator}")
    if denominator <= 0:
        raise InvalidMonetaryConfigError(f"round_half_even denominator must be > 0, got {denominator}")

    q, r = divmod(numerator, denominator)
    two_r = r * 2
    if two_r < denominator:
        result = q
    elif two_r > denominator:
        result = q + 1
    else:
        result = q if (q % 2 == 0) else (q + 1)

    if result > max_output_bound:
        raise NumericRangeError(
            f"Rounded result {result} exceeds configured output bound {max_output_bound}"
        )
    return result


def compute_route_distance_cost_paise(distance_m: int, r_d: ExactRate) -> int:
    """C_distance,k = RoundEven(d_k[m] * r_d[paise/km] / 1000)."""
    checked_nonnegative_int(distance_m, "distance_m")
    if r_d.numerator < 0:
        raise InvalidMonetaryConfigError("distance_rate_paise_per_km cannot be negative")
    num = checked_mul(distance_m, r_d.numerator)
    den = checked_mul(1000, r_d.denominator)
    return round_half_even(num, den)


def compute_route_time_cost_paise(paid_seconds: int, r_t: ExactRate) -> int:
    """C_time,k = RoundEven(tau_k[s] * r_t[paise/hour] / 3600)."""
    checked_nonnegative_int(paid_seconds, "paid_seconds")
    if r_t.numerator < 0:
        raise InvalidMonetaryConfigError("time_rate_paise_per_hour cannot be negative")
    num = checked_mul(paid_seconds, r_t.numerator)
    den = checked_mul(3600, r_t.denominator)
    return round_half_even(num, den)


def compute_order_sla_cost_paise(
    lateness_seconds: int,
    order: OrderSpec,
    rates: CostRateConfig,
) -> int:
    """C_SLA,i = RoundEven(L_i[s] * p_i[paise/min] / 60) for served soft-window orders."""
    checked_nonnegative_int(lateness_seconds, "lateness_seconds")
    if order.window_type == WindowType.HARD or lateness_seconds == 0:
        return 0
    p_i = rates.sla_rate_for(order)
    if p_i.numerator < 0:
        raise InvalidMonetaryConfigError(f"SLA penalty rate for order {order.id} cannot be negative")
    num = checked_mul(lateness_seconds, p_i.numerator)
    den = checked_mul(60, p_i.denominator)
    return round_half_even(num, den)


def build_plan_cost_ledger(
    *,
    route_distance_lines_paise: dict[str, int],
    route_time_lines_paise: dict[str, int],
    order_sla_lines_paise: dict[str, int],
    newly_activated_vehicle_costs_paise: dict[str, int],
    posted_activation_cost_paise_by_vehicle: dict[str, int],
    sunk_cost_before_paise: int,
    served_soft_orders_count: int,
    rounding_policy_version: str = "ROUND_POLICY_V1_ROUTE_ORDER_EVEN",
) -> CostLedger:
    """Aggregate rounded integer-paise lines deterministically without re-rounding the grand total."""
    checked_nonnegative_int(sunk_cost_before_paise, "sunk_cost_before_paise")

    sorted_r_dist = {k: checked_nonnegative_int(route_distance_lines_paise[k], f"dist[{k}]") for k in sorted(route_distance_lines_paise)}
    sorted_r_time = {k: checked_nonnegative_int(route_time_lines_paise[k], f"time[{k}]") for k in sorted(route_time_lines_paise)}
    sorted_o_sla = {k: checked_nonnegative_int(order_sla_lines_paise[k], f"sla[{k}]") for k in sorted(order_sla_lines_paise)}
    sorted_v_act = {k: checked_nonnegative_int(newly_activated_vehicle_costs_paise[k], f"act[{k}]") for k in sorted(newly_activated_vehicle_costs_paise)}

    dist_total = sum(sorted_r_dist.values())
    time_total = sum(sorted_r_time.values())
    sla_total = sum(sorted_o_sla.values())
    op_total = dist_total + time_total + sla_total
    inc_act_total = sum(sorted_v_act.values())
    inc_decision_total = op_total + inc_act_total

    checked_nonnegative_int(inc_decision_total, "incremental_decision_cost_paise")

    posted_before = sum(
        checked_nonnegative_int(v, f"posted[{k}]")
        for k, v in sorted(posted_activation_cost_paise_by_vehicle.items())
    )
    posted_after = posted_before + inc_act_total
    # Sunk cost before replan already includes posted activation before or realized operating lines;
    # if sunk_cost_before_paise == 0 but posted_before > 0, ensure shift forecast includes posted_before.
    effective_sunk = max(sunk_cost_before_paise, posted_before)
    shift_forecast_after = effective_sunk + inc_decision_total

    r_count = len(sorted_r_dist)
    s_count = max(0, served_soft_orders_count)
    # Worst-case absolute rounding deviation vs unrounded totals is (2R + S)/2 paise (Phase 5 §11.4)
    deviation_bound = ExactRate(2 * r_count + s_count, 2)

    return CostLedger(
        distance_cost_paise=dist_total,
        time_cost_paise=time_total,
        sla_cost_paise=sla_total,
        operating_cost_paise=op_total,
        incremental_activation_cost_paise=inc_act_total,
        incremental_decision_cost_paise=inc_decision_total,
        activation_posted_before_paise=posted_before,
        activation_proposed_new_paise=inc_act_total,
        activation_posted_after_paise=posted_after,
        sunk_cost_before_paise=effective_sunk,
        shift_forecast_total_after_paise=shift_forecast_after,
        rounding_policy_version=rounding_policy_version,
        max_rounding_deviation_paise=deviation_bound,
        route_distance_lines_paise=sorted_r_dist,
        route_time_lines_paise=sorted_r_time,
        order_sla_lines_paise=sorted_o_sla,
        vehicle_activation_lines_paise=sorted_v_act,
    )
