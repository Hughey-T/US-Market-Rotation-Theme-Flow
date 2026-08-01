"""Dynamic-industry compatibility for authoritative consumer v3 output."""

from __future__ import annotations

import copy

from . import analysis_v3 as _base

_ORIGINAL_BUILD = _base.build_authoritative_v3
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
            "theme_id": theme_id,
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


def _dynamic_v3_input(theme: dict) -> dict:
    membership = []
    for row in theme.get("constituents") or []:
        ticker = row.get("ticker")
        if not ticker:
            continue
        membership.append(
            {
                "ticker": ticker,
                "active": True,
                "effective": True,
                "reason": "included",
                "data_available": isinstance(row.get("return_4w"), (int, float)),
            }
        )
    return {
        "theme_returns": [],
        "benchmark_returns": [],
        "history": [],
        "forward_samples": [],
        "factor_exposures": [],
        "membership": membership,
    }


def build_authoritative_v3(
    snapshot: dict, *, evaluation_at: str | None = None
) -> dict:
    """Add dynamic handoffs without changing fixed-theme analysis semantics."""
    fixed_ids = set((snapshot.get("themes") or {}).keys())
    dynamic_themes = dynamic_signal_themes(snapshot)
    dynamic_ids = set(dynamic_themes)

    candidate_ids = {
        item.get("theme_id")
        for item in snapshot.get("company_candidates") or []
        if item.get("theme_id")
    }
    unsupported = sorted(candidate_ids - fixed_ids - dynamic_ids)
    if unsupported:
        raise ValueError(
            "company candidate has no authoritative price signal: "
            + ", ".join(unsupported)
        )

    if not dynamic_ids:
        return _ORIGINAL_BUILD(snapshot, evaluation_at=evaluation_at)

    fixed_snapshot = copy.deepcopy(snapshot)
    fixed_snapshot["company_candidates"] = [
        item
        for item in fixed_snapshot.get("company_candidates") or []
        if item.get("theme_id") in fixed_ids
    ]
    fixed_projection = _ORIGINAL_BUILD(
        fixed_snapshot, evaluation_at=evaluation_at
    )

    augmented = copy.deepcopy(snapshot)
    augmented.setdefault("themes", {}).update(copy.deepcopy(dynamic_themes))
    v3_themes = augmented.setdefault("v3_inputs", {}).setdefault(
        "themes", {}
    )
    for theme_id, theme in dynamic_themes.items():
        v3_themes[theme_id] = _dynamic_v3_input(theme)

    candidate_projection = _ORIGINAL_BUILD(
        augmented, evaluation_at=evaluation_at
    )

    fixed_projection["phases"][5] = candidate_projection["phases"][5]
    fixed_projection["phases"][6] = candidate_projection["phases"][6]
    fixed_projection["phases"][6]["main_cautions"] = [_base.FLOW_NOTICE] + (
        [fixed_projection["coverage"]["warning"]]
        if fixed_projection["coverage"]["warning"]
        else []
    )
    fixed_projection["handoffs"] = candidate_projection["handoffs"]
    return fixed_projection
