"""Stable decimal contracts for persisted metrics and threshold decisions."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN


METRIC_QUANTUM = Decimal("0.0000000001")
WEIGHTING_LED_THRESHOLD = Decimal("0.03")


def decimal_metric(value) -> Decimal | None:
    """Convert a finite JSON number through its decimal string representation."""
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not result.is_finite():
        return None
    return result


def quantized_metric(value) -> float | None:
    result = decimal_metric(value)
    if result is None:
        return None
    return float(result.quantize(METRIC_QUANTUM, rounding=ROUND_HALF_EVEN))


def weighting_divergence(cap_relative, equal_relative) -> float | None:
    cap = decimal_metric(cap_relative)
    equal = decimal_metric(equal_relative)
    if cap is None or equal is None:
        return None
    return float((cap - equal).quantize(METRIC_QUANTUM, rounding=ROUND_HALF_EVEN))


def market_cap_led(divergence) -> bool | None:
    value = decimal_metric(divergence)
    return None if value is None else value >= WEIGHTING_LED_THRESHOLD


def equal_weight_led(divergence) -> bool | None:
    value = decimal_metric(divergence)
    return None if value is None else value <= -WEIGHTING_LED_THRESHOLD
