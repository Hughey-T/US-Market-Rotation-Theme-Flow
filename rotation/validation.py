"""Strict JSON Schema and cross-field semantic validation."""
from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from . import INSTRUCTION_VERSION
from .classification import classify_theme, evaluate_priority, evaluate_timing, overheat_breadth_weak, priority_matches
from .provenance import snapshot_source_hash
from .shortlist import apply_shortlist
from .thresholds import equal_weight_led, market_cap_led


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
        periods: dict[str, list[tuple[dt.date, dt.date | None]]] = {}
        for member in theme.get("members", []):
            ticker = member.get("ticker")
            try:
                valid_from = dt.date.fromisoformat(member.get("valid_from", ""))
                valid_to_raw = member.get("valid_to")
                valid_to = dt.date.fromisoformat(valid_to_raw) if valid_to_raw is not None else None
            except (TypeError, ValueError):
                errors.append(f"{theme_id}/{ticker}: malformed membership date")
                continue
            if valid_to is not None and valid_from > valid_to:
                errors.append(f"{theme_id}/{ticker}: valid_from is after valid_to")
            periods.setdefault(ticker, []).append((valid_from, valid_to))
            membership.setdefault(ticker, []).append(theme_id)
        for ticker, ranges in periods.items():
            ordered = sorted(ranges, key=lambda item: (item[0], item[1] or dt.date.max))
            if len(ordered) != len(set(ordered)):
                errors.append(f"{theme_id}/{ticker}: duplicate membership period")
            for previous, current in zip(ordered, ordered[1:]):
                if previous[1] is None or current[0] <= previous[1]:
                    errors.append(f"{theme_id}/{ticker}: overlapping membership periods")
    for ticker, theme_ids in sorted(membership.items()):
        distinct = sorted(set(theme_ids))
        if len(distinct) > 1:
            warnings.append(f"OVERLAP:{ticker}:{','.join(distinct)}")
    if errors:
        raise ContractError("theme master semantic validation failed:\n" + "\n".join(f"- {error}" for error in errors))
    return warnings


def validate_latest_semantics(latest: dict, verify_source_hash: bool = False) -> None:
    _walk_finite(latest)
    errors = []
    meta = latest.get("meta", {})
    status = meta.get("status")
    failure_reason = meta.get("failure_reason")
    critical_missing = meta.get("global_quality", {}).get("critical_missing", [])
    if status == "success":
        if critical_missing:
            errors.append("successful artifact has critical_missing inputs")
        if failure_reason not in (None, ""):
            errors.append("successful artifact has failure_reason")
    elif status == "failed" and (not isinstance(failure_reason, str) or not failure_reason.strip()):
        errors.append("failed artifact requires a non-empty failure_reason")
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
        expected_flags, expected_classifications = classify_theme(metrics, theme.get("trends", {}), theme.get("quality", {}), theme.get("by_role", {}))
        for field in ("phase_initial", "phase_diffusion", "phase_price_overheat", "direction_improving", "direction_worsening", "direction_outflow_signal", "broad_concentration_pass", "overheat_breadth_weak"):
            if flags.get(field) != expected_flags.get(field):
                errors.append(f"{theme_id}: {field} mismatch; expected {expected_flags.get(field)}")
        for field in ("phase", "direction", "research_priority", "research_priority_rule", "timing_status", "timing_rule"):
            if classifications.get(field) != expected_classifications.get(field):
                errors.append(f"{theme_id}: classifications.{field} mismatch; expected {expected_classifications.get(field)}")
        for field in ("level", "direction", "positioning_hypothesis", "direct_flow_data_available"):
            if evidence.get(field) != expected_classifications["evidence"].get(field):
                errors.append(f"{theme_id}: evidence.{field} mismatch; expected {expected_classifications['evidence'].get(field)}")
        for field in ("matched_conditions", "unmatched_conditions", "contrary_evidence"):
            if flags.get(field) != expected_flags.get(field):
                errors.append(f"{theme_id}: condition_flags.{field} mismatch; expected {expected_flags.get(field)}")
        if evidence.get("matched_conditions") != expected_classifications["evidence"].get("matched_conditions"):
            errors.append(f"{theme_id}: evidence.matched_conditions mismatch; expected {expected_classifications['evidence'].get('matched_conditions')}")
        expected_weak = overheat_breadth_weak(flags.get("phase_price_overheat"), metrics.get("advance_ratio_4w"), metrics.get("pct_above_50dma"))
        if flags.get("overheat_breadth_weak") != expected_weak:
            errors.append(f"{theme_id}: overheat_breadth_weak mismatch; expected {expected_weak}")
        selected, rank = theme.get("selected_for_deep_dive"), theme.get("shortlist_rank")
        if selected != (rank is not None):
            errors.append(f"{theme_id}: selected_for_deep_dive and shortlist_rank disagree")
        top1 = metrics.get("top1_contribution_ratio")
        if top1 is not None and metrics.get("single_name_concentrated") != (top1 > 0.60):
            errors.append(f"{theme_id}: single_name_concentrated mismatch")
        divergence = metrics.get("weighting_divergence_4w")
        if divergence is not None:
            if metrics.get("market_cap_led") != market_cap_led(divergence):
                errors.append(f"{theme_id}: market_cap_led mismatch")
            if metrics.get("equal_weight_led") != equal_weight_led(divergence):
                errors.append(f"{theme_id}: equal_weight_led mismatch")
        above_count = metrics.get("above_50dma_count")
        above_ratio = metrics.get("pct_above_50dma")
        above_valid = theme.get("quality", {}).get("metric_valid_counts", {}).get("above_50dma")
        if isinstance(above_valid, int) and above_valid >= 5:
            if above_count is None or above_ratio is None or abs(above_ratio - above_count / above_valid) > 1e-4:
                errors.append(f"{theme_id}: above_50dma_count/pct_above_50dma mismatch")
        elif above_count is not None or above_ratio is not None:
            errors.append(f"{theme_id}: 50DMA breadth exists without valid observations")
    recomputed, shortlist = apply_shortlist(themes)
    stored_ids = latest.get("theme_shortlist", {}).get("selected_theme_ids", [])
    if shortlist["selected_theme_ids"] != stored_ids:
        errors.append(f"theme_shortlist order mismatch; expected {shortlist['selected_theme_ids']}")
    for theme_id in themes:
        for field in ("relative_strength_rank_4w", "selected_for_deep_dive", "shortlist_rank", "shortlist_reason_codes"):
            if recomputed[theme_id].get(field) != themes[theme_id].get(field):
                errors.append(f"{theme_id}: {field} mismatch")
    if verify_source_hash and latest.get("meta", {}).get("source_sha256") != snapshot_source_hash(latest):
        errors.append("meta.source_sha256 mismatch")
    if errors:
        raise ContractError("latest semantic validation failed:\n" + "\n".join(f"- {error}" for error in errors))


def validate_public_latest(latest: dict, verify_source_hash: bool = True) -> None:
    """Validate an artifact intended for the public current/latest position."""
    validate_latest_semantics(latest, verify_source_hash=verify_source_hash)
    meta = latest.get("meta", {})
    errors = []
    if meta.get("status") != "success":
        errors.append("public latest requires status=success")
    if meta.get("failure_reason") not in (None, ""):
        errors.append("public latest cannot contain failure_reason")
    if meta.get("global_quality", {}).get("critical_missing") != []:
        errors.append("public latest requires critical_missing=[]")
    if not latest.get("themes"):
        errors.append("public latest requires at least one theme")
    if errors:
        raise ContractError("public latest validation failed:\n" + "\n".join(f"- {error}" for error in errors))


def validate_judgment_semantics(record: dict, source_latest: dict | None) -> None:
    """Reject judgment records that do not faithfully project a validated source snapshot."""
    _walk_finite(record)
    if source_latest is None:
        raise ContractError("judgment source latest is unavailable")
    errors = []
    source_meta = source_latest.get("meta", {})
    try:
        validate_public_latest(source_latest, verify_source_hash=False)
    except ContractError as error:
        errors.append(f"judgment source latest is not publishable: {error}")
    identity = {
        "run_id": "run_id", "data_date": "data_date", "source_commit": "source_commit",
        "source_snapshot": "source_snapshot", "source_sha256": "source_sha256",
    }
    for record_field, source_field in identity.items():
        if record.get(record_field) != source_meta.get(source_field):
            errors.append(f"judgment {record_field} does not match source latest")
    versions = {
        "data_schema_version": source_meta.get("schema_version"),
        "methodology_version": source_meta.get("methodology_version"),
        "instruction_version": INSTRUCTION_VERSION,
    }
    for field, expected in versions.items():
        if record.get(field) != expected:
            errors.append(f"judgment {field} does not match source latest contract")
    source_regime = source_latest.get("market_regime", {}).get("classification", {})
    for field in ("primary_regime", "secondary_regimes", "confidence", "matched_conditions", "contrary_evidence"):
        if record.get("regime", {}).get(field) != source_regime.get(field):
            errors.append(f"judgment regime.{field} does not match source latest")
    priority_by_rule = {"P0": "unclassifiable", "P1": "dd_priority", "P2": "dd_priority", "P3": "dd_candidate", "P4": "watch", "P5": "low_priority", "fallback": "watch"}
    timing_by_rule = {"T0": "unclassifiable", "T1": "price_overheat", "T2": "deteriorating", "T3": "early_unconfirmed", "T4": "favorable", "fallback": "unclassifiable"}
    ranks, seen_theme_ids = [], set()
    source_themes = source_latest.get("themes", {})
    record_theme_ids = [theme.get("theme_id") for theme in record.get("theme_judgments", [])]
    if set(record_theme_ids) != set(source_themes):
        missing = sorted(set(source_themes) - set(record_theme_ids))
        extra = sorted(set(record_theme_ids) - set(source_themes))
        errors.append(f"judgment theme set does not match source latest; missing={missing}, extra={extra}")
    key_metric_fields = (
        "equal_weight_rel_spy_1w", "equal_weight_rel_spy_4w", "equal_weight_rel_spy_13w",
        "market_cap_weight_rel_spy_4w", "advance_ratio_4w", "pct_above_50dma",
        "volume_ratio_20d_60d", "top1_contribution_ratio", "top3_contribution_ratio",
    )
    for theme in record.get("theme_judgments", []):
        theme_id = theme.get("theme_id")
        if theme_id in seen_theme_ids:
            errors.append(f"duplicate judgment theme_id: {theme_id}")
        seen_theme_ids.add(theme_id)
        source_theme = source_themes.get(theme_id)
        if source_theme is None:
            errors.append(f"judgment theme_id not found in source latest: {theme_id}")
            continue
        rule = theme.get("research_priority_rule")
        if theme.get("research_priority") != priority_by_rule.get(rule):
            errors.append(f"{theme_id}: research_priority is inconsistent with {rule}")
        timing_rule = theme.get("timing_rule")
        if theme.get("timing_status") != timing_by_rule.get(timing_rule):
            errors.append(f"{theme_id}: timing_status is inconsistent with {timing_rule}")
        if rule in {"P1", "P2", "P3"} and theme.get("evidence", {}).get("direction") != "inflow":
            errors.append(f"{theme_id}: {rule} requires evidence.direction=inflow")
        if rule == "P1" and theme.get("phase") != "diffusion":
            errors.append(f"{theme_id}: P1 requires phase=diffusion")
        if rule == "P2" and (theme.get("phase") != "price_overheat" or source_theme.get("condition_flags", {}).get("phase_diffusion") is not True):
            errors.append(f"{theme_id}: P2 requires price_overheat with diffusion flag")
        selected, rank = theme.get("selected_for_deep_dive"), theme.get("shortlist_rank")
        if selected != (rank is not None):
            errors.append(f"{theme_id}: selected_for_deep_dive and shortlist_rank disagree")
        if selected and theme.get("research_priority") not in {"dd_priority", "dd_candidate", "watch"}:
            errors.append(f"{theme_id}: shortlist-ineligible priority is selected")
        if rank is not None:
            ranks.append(rank)
        source_cls = source_theme.get("classifications", {})
        copied = {
            "phase": source_cls.get("phase"), "direction": source_cls.get("direction"),
            "research_priority": source_cls.get("research_priority"), "research_priority_rule": source_cls.get("research_priority_rule"),
            "timing_status": source_cls.get("timing_status"), "timing_rule": source_cls.get("timing_rule"),
            "selected_for_deep_dive": source_theme.get("selected_for_deep_dive"), "shortlist_rank": source_theme.get("shortlist_rank"),
            "shortlist_reason_codes": source_theme.get("shortlist_reason_codes"),
        }
        for field, expected in copied.items():
            if theme.get(field) != expected:
                errors.append(f"{theme_id}: {field} does not match source latest")
        for field in ("level", "direction", "positioning_hypothesis", "matched_conditions"):
            if theme.get("evidence", {}).get(field) != source_cls.get("evidence", {}).get(field):
                errors.append(f"{theme_id}: evidence.{field} does not match source latest")
        source_quality = source_theme.get("quality", {})
        expected_quality = {
            "classification_eligible": source_quality.get("classification_eligible"),
            "coverage_ratio": source_quality.get("coverage_ratio"),
            "valid_constituent_count": source_quality.get("valid_constituent_count"),
            "history_weeks": source_quality.get("history_weeks"),
            "missing_required_fields": source_quality.get("missing_required_fields"),
            "quality_reasons": source_quality.get("quality_reasons"),
        }
        if theme.get("data_quality") != expected_quality:
            errors.append(f"{theme_id}: data_quality does not match source latest")
        for field in ("matched_conditions", "unmatched_conditions"):
            if theme.get(field) != source_theme.get("condition_flags", {}).get(field):
                errors.append(f"{theme_id}: {field} does not match source latest")
        for field in key_metric_fields:
            if theme.get("key_metrics", {}).get(field) != source_theme.get("metrics", {}).get(field):
                errors.append(f"{theme_id}: key_metrics.{field} does not match source latest")
    if len(ranks) != len(set(ranks)):
        errors.append("judgment shortlist ranks are duplicated")
    source_selected = source_latest.get("theme_shortlist", {}).get("selected_theme_ids", [])
    record_selected = [
        theme.get("theme_id")
        for theme in sorted(record.get("theme_judgments", []), key=lambda item: item.get("shortlist_rank") or 10**9)
        if theme.get("selected_for_deep_dive")
    ]
    if record_selected != source_selected:
        errors.append(f"judgment shortlist selection/order does not match source latest; expected {source_selected}")
    if sorted(ranks) != list(range(1, len(ranks) + 1)):
        errors.append("judgment shortlist ranks must be contiguous from 1")
    source_rank = {theme_id: rank for rank, theme_id in enumerate(source_selected, 1)}
    source_constituents = {
        theme_id: {row.get("ticker"): (row.get("role"), position) for position, row in enumerate(theme.get("constituents", []))}
        for theme_id, theme in source_themes.items()
    }
    seen_tickers, seen_pairs, ordering = set(), set(), []
    for candidate in record.get("dd_handoff", []):
        theme_id, ticker = candidate.get("theme_id"), candidate.get("ticker")
        pair = (theme_id, ticker)
        source_theme = source_themes.get(theme_id)
        if source_theme is None:
            errors.append(f"dd_handoff theme is absent from source latest: {theme_id}")
            continue
        if not source_theme.get("selected_for_deep_dive") or theme_id not in source_rank:
            errors.append(f"dd_handoff theme is not selected in source shortlist: {theme_id}")
        constituent = source_constituents.get(theme_id, {}).get(ticker)
        if constituent is None:
            errors.append(f"dd_handoff ticker is not an active source constituent: {theme_id}/{ticker}")
        else:
            role, position = constituent
            if candidate.get("role") != role:
                errors.append(f"dd_handoff role does not match source constituent: {theme_id}/{ticker}")
            ordering.append((source_rank.get(theme_id, 10**9), position, ticker))
        if ticker in seen_tickers:
            errors.append(f"duplicate dd_handoff ticker: {ticker}")
        if pair in seen_pairs:
            errors.append(f"duplicate dd_handoff theme/ticker: {theme_id}/{ticker}")
        seen_tickers.add(ticker); seen_pairs.add(pair)
    if ordering != sorted(ordering):
        errors.append("dd_handoff order must follow shortlist rank, source constituent order, then ticker")
    if errors:
        raise ContractError("judgment semantic validation failed:\n" + "\n".join(f"- {error}" for error in errors))


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
