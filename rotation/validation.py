"""Strict JSON Schema and cross-field semantic validation."""
from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from .classification import evaluate_priority, evaluate_timing, overheat_breadth_weak, priority_matches
from .provenance import snapshot_source_hash
from .shortlist import apply_shortlist


class ContractError(ValueError):
    pass


def load_json(path: Path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"non-finite JSON constant: {value}")))


def schema_errors(instance, schema: dict) -> list[str]:
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    return [f"{'/'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}" for error in sorted(validator.iter_errors(instance), key=lambda error: list(error.absolute_path))]


def validate_schema(instance, schema: dict, label: str = "document") -> None:
    errors = schema_errors(instance, schema)
    if errors:
        raise ContractError(f"{label} failed JSON Schema validation:\n" + "\n".join(f"- {error}" for error in errors))


def _walk_finite(value, path="<root>"):
    if isinstance(value, float) and not math.isfinite(value):
        raise ContractError(f"{path}: non-finite number")
    if isinstance(value, dict):
        for key, child in value.items():
            _walk_finite(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _walk_finite(child, f"{path}[{index}]")


def validate_theme_master_semantics(master: dict) -> list[str]:
    errors, warnings, seen_ids = [], [], set()
    membership: dict[str, list[str]] = {}
    for theme in master.get("themes", []):
        theme_id = theme.get("theme_id")
        if theme_id in seen_ids:
            errors.append(f"duplicate theme_id: {theme_id}")
        seen_ids.add(theme_id)
        tickers = [member.get("ticker") for member in theme.get("members", [])]
        if len(tickers) != len(set(tickers)):
            errors.append(f"{theme_id}: duplicate ticker within theme")
        for ticker in tickers:
            membership.setdefault(ticker, []).append(theme_id)
    for ticker, theme_ids in sorted(membership.items()):
        if len(theme_ids) > 1:
            warnings.append(f"OVERLAP:{ticker}:{','.join(sorted(theme_ids))}")
    if errors:
        raise ContractError("theme master semantic validation failed:\n" + "\n".join(f"- {error}" for error in errors))
    return warnings


def validate_latest_semantics(latest: dict, verify_source_hash: bool = False) -> None:
    _walk_finite(latest)
    errors = []
    if "previous_predictions" in latest:
        errors.append("legacy previous_predictions is not accepted as previous_judgments")
    themes = latest.get("themes", {})
    for theme_id, theme in themes.items():
        if theme.get("theme_id") != theme_id:
            errors.append(f"themes.{theme_id}.theme_id does not match object key")
        expected_priority, expected_rule, _ = evaluate_priority(theme)
        classifications = theme.get("classifications", {})
        if (classifications.get("research_priority"), classifications.get("research_priority_rule")) != (expected_priority, expected_rule):
            errors.append(f"{theme_id}: priority mismatch; expected {expected_priority}/{expected_rule}")
        expected_timing, expected_timing_rule, _ = evaluate_timing(theme)
        if (classifications.get("timing_status"), classifications.get("timing_rule")) != (expected_timing, expected_timing_rule):
            errors.append(f"{theme_id}: theme market state mismatch; expected {expected_timing}/{expected_timing_rule}")
        matches = priority_matches(theme)
        if matches["P1"] and matches["P2"]:
            errors.append(f"{theme_id}: P1 and P2 both match")
        evidence = classifications.get("evidence", {})
        if classifications.get("research_priority_rule") in {"P1", "P2", "P3"} and evidence.get("direction") != "inflow":
            errors.append(f"{theme_id}: P1/P2/P3 requires evidence.direction=inflow")
        if not evidence.get("direct_flow_data_available") and evidence.get("level") == "direct_flow_confirmed":
            errors.append(f"{theme_id}: direct_flow_confirmed without direct-flow data")
        flags, metrics = theme.get("condition_flags", {}), theme.get("metrics", {})
        expected_weak = overheat_breadth_weak(flags.get("phase_price_overheat"), metrics.get("advance_ratio_4w"), metrics.get("pct_above_50dma"))
        if flags.get("overheat_breadth_weak") != expected_weak:
            errors.append(f"{theme_id}: overheat_breadth_weak mismatch; expected {expected_weak}")
        selected, rank = theme.get("selected_for_deep_dive"), theme.get("shortlist_rank")
        if selected != (rank is not None):
            errors.append(f"{theme_id}: selected_for_deep_dive and shortlist_rank disagree")
        top1 = metrics.get("top1_contribution_ratio")
        if top1 is not None and metrics.get("single_name_concentrated") != (top1 > 0.60):
            errors.append(f"{theme_id}: single_name_concentrated mismatch")
    recomputed, shortlist = apply_shortlist(themes)
    stored_ids = latest.get("theme_shortlist", {}).get("selected_theme_ids", [])
    if shortlist["selected_theme_ids"] != stored_ids:
        errors.append(f"theme_shortlist order mismatch; expected {shortlist['selected_theme_ids']}")
    for theme_id in themes:
        for field in ("relative_strength_rank_4w", "selected_for_deep_dive", "shortlist_rank"):
            if recomputed[theme_id].get(field) != themes[theme_id].get(field):
                errors.append(f"{theme_id}: {field} mismatch")
    if verify_source_hash and latest.get("meta", {}).get("source_sha256") != snapshot_source_hash(latest):
        errors.append("meta.source_sha256 mismatch")
    if errors:
        raise ContractError("latest semantic validation failed:\n" + "\n".join(f"- {error}" for error in errors))


def freshness_status(latest: dict, now: dt.datetime) -> str:
    if latest.get("meta", {}).get("status") != "success":
        return "failed"
    valid_until = dt.datetime.fromisoformat(latest["meta"]["valid_until"].replace("Z", "+00:00"))
    hard_stop = dt.datetime.fromisoformat(latest["meta"]["hard_stop_after"].replace("Z", "+00:00"))
    if now > hard_stop:
        return "hard_stop"
    if now > valid_until:
        return "stale"
    return "fresh"


def validate_run_identity(locked_meta: dict, candidate_meta: dict) -> None:
    """Reject mixed inputs after a consumer has locked stage-1 identity."""
    fields = ("run_id", "data_date", "source_snapshot", "source_sha256")
    changed = [field for field in fields if locked_meta.get(field) != candidate_meta.get(field)]
    if changed:
        raise ContractError(f"run identity changed during analysis: {', '.join(changed)}")
