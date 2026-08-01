"""Dynamic-industry compatibility helpers for authoritative consumer v3 output."""

from __future__ import annotations

from . import analysis_v3 as _base

_BUCKET_NAMES = (
    "research_now",
    "watch_recovery",
    "long_term_context_price_weak",
    "avoid_now",
)


def dynamic_signal_themes(snapshot: dict) -> dict[str, dict]:
    """Project dynamic industries into the existing price-signal contract.

    Dynamic industries remain outside fixed-theme assessments and coverage. The
    projection exists only so producer-selected company candidates can receive
    authoritative and auditable handoffs.
    """
    bucket_by_id: dict[str, str] = {}
    buckets = snapshot.get("candidate_buckets") or {}
    for bucket in _BUCKET_NAMES:
        for item in buckets.get(bucket) or []:
            if item.get("source") != "dynamic_industry" or not item.get("id"):
                continue
            theme_id = item["id"]
            previous = bucket_by_id.get(theme_id)
            if previous is not None and previous != bucket:
                raise ValueError(
                    f"dynamic industry appears in multiple buckets: {theme_id}"
                )
            bucket_by_id[theme_id] = bucket

    candidates = (
        (snapshot.get("dynamic_discovery") or {}).get("candidates") or {}
    )
    projected: dict[str, dict] = {}
    for theme_id, bucket in sorted(bucket_by_id.items()):
        candidate = candidates.get(theme_id)
        if not isinstance(candidate, dict):
            raise ValueError(f"dynamic industry candidate is missing: {theme_id}")
        eligible = candidate.get("eligible") is True
        projected[theme_id] = {
            "label": candidate.get("label") or theme_id,
            "metrics": candidate.get("metrics") or {},
            "quality": {
                "classification_eligible": eligible,
                "status": "eligible" if eligible else "ineligible",
            },
            "decision": {"candidate_bucket": bucket},
            "constituents": candidate.get("constituents") or [],
        }
    return projected


def candidate_signal_maps(snapshot: dict, fixed_themes: list[tuple[str, dict]]):
    """Return fixed coverage inputs plus all candidate handoff inputs."""
    fixed_signals = {
        theme_id: _base.price_signal(theme)
        for theme_id, theme in fixed_themes
    }
    dynamic_themes = dynamic_signal_themes(snapshot)
    candidate_signals = {
        **fixed_signals,
        **{
            theme_id: _base.price_signal(theme)
            for theme_id, theme in dynamic_themes.items()
        },
    }
    return fixed_signals, dynamic_themes, candidate_signals
