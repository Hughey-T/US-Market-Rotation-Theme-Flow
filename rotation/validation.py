"""Strict JSON Schema and cross-field semantic validation."""
from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from . import INSTRUCTION_VERSION
from .classification import classify_theme, evaluate_priority, evaluate_timing, overheat_breadth_weak, priority_matches
from .decisions import BUCKET_NAMES, _research_lens, build_candidate_buckets, build_theme_decision, select_companies
from .metrics import finite, positive_concentration, ratio_true
from .presentation import build_user_view, render_phase
from .provenance import snapshot_source_hash
from .regime import classify_market_regime
from .shortlist import apply_shortlist
from .thresholds import equal_weight_led, market_cap_led


class ContractError(ValueError):
    pass


_MISSING = object()


def _path_value(value: dict, path: str):
    current = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return _MISSING
        current = current[part]
    return current


def _compatible_scalar(observed, expected) -> bool:
    if isinstance(expected, bool):
        return isinstance(observed, bool)
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        return isinstance(observed, (int, float)) and not isinstance(observed, bool)
    return isinstance(observed, str) and isinstance(expected, str)


def load_json(path: Path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"non-finite JSON constant: {value}")))


def _resolve_local_ref(root: dict, node: dict) -> dict:
    seen = set()
    while isinstance(node, dict) and "$ref" in node:
        reference = node["$ref"]
        if not isinstance(reference, str) or not reference.startswith("#/") or reference in seen:
            return {}
        seen.add(reference)
        resolved = root
        for part in reference[2:].split("/"):
            key = part.replace("~1", "/").replace("~0", "~")
            if not isinstance(resolved, dict) or key not in resolved:
                return {}
            resolved = resolved[key]
        node = resolved
    return node if isinstance(node, dict) else {}


def _schema_types_for_path(root: dict, path: str) -> set[str]:
    node = root
    for part in path.split("."):
        node = _resolve_local_ref(root, node)
        properties = node.get("properties", {})
        if isinstance(properties, dict) and part in properties:
            node = properties[part]
        elif isinstance(node.get("additionalProperties"), dict):
            node = node["additionalProperties"]
        else:
            return set()
    node = _resolve_local_ref(root, node)
    declared = node.get("type", [])
    if isinstance(declared, str):
        return {declared}
    if isinstance(declared, list):
        return {value for value in declared if isinstance(value, str)}
    values = [node["const"]] if "const" in node else node.get("enum", [])
    inferred = set()
    for value in values if isinstance(values, list) else []:
        if isinstance(value, bool):
            inferred.add("boolean")
        elif isinstance(value, (int, float)):
            inferred.add("number")
        elif isinstance(value, str):
            inferred.add("string")
        elif value is None:
            inferred.add("null")
    return inferred


def _scalar_matches_schema(value, schema_types: set[str]) -> bool:
    if isinstance(value, bool):
        return "boolean" in schema_types
    if isinstance(value, (int, float)):
        return not isinstance(value, bool) and bool({"number", "integer"} & schema_types)
    return isinstance(value, str) and "string" in schema_types


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


def _compact_value(value, limit: int = 120) -> str:
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return rendered if len(rendered) <= limit else rendered[: limit - 3] + "..."


def _semantic_differences(observed, expected, path: str) -> list[str]:
    """Return deterministic field-level differences; object key order is immaterial."""
    if isinstance(observed, dict) and isinstance(expected, dict):
        differences = []
        for key in sorted(observed.keys() | expected.keys()):
            child_path = f"{path}.{key}"
            if key not in observed:
                differences.append(f"{child_path} is missing; expected {_compact_value(expected[key])}")
            elif key not in expected:
                differences.append(f"{child_path} is unexpected")
            else:
                differences.extend(_semantic_differences(observed[key], expected[key], child_path))
        return differences
    if observed != expected:
        return [f"{path} mismatch; stored {_compact_value(observed)}, expected {_compact_value(expected)}"]
    return []


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
    version_pair = (meta.get("schema_version"), meta.get("methodology_version"))
    if version_pair not in {("1.1", "1.1.0"), ("1.2", "1.2.0")}:
        errors.append(f"unsupported schema/methodology version pair: {version_pair}")
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
    market_regime = latest.get("market_regime")
    if isinstance(market_regime, dict) and isinstance(market_regime.get("inputs"), dict):
        expected_regime = classify_market_regime(market_regime["inputs"])
        errors.extend(_semantic_differences(market_regime, expected_regime, "market_regime"))
    else:
        errors.append("market_regime.inputs is required for canonical regime validation")
    themes = latest.get("themes", {})
    for theme_id, theme in themes.items():
        if theme.get("theme_id") != theme_id:
            errors.append(f"themes.{theme_id}.theme_id does not match object key")
        if meta.get("schema_version") == "1.2":
            context = theme.get("structural_context")
            if not isinstance(context, dict) or context.get("status") not in {"supported", "uncertain", "unsupported", "not_assessed"}:
                errors.append(f"{theme_id}: versioned structural_context is required")
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
    dynamic = latest.get("dynamic_discovery")
    buckets = latest.get("candidate_buckets")
    companies = latest.get("company_candidates")
    user_view = latest.get("user_view")
    additive_fields = (dynamic, buckets, companies, user_view)
    if meta.get("schema_version") == "1.2" and not all(value is not None for value in additive_fields):
        errors.append("schema 1.2 requires dynamic_discovery, candidate_buckets, company_candidates, and user_view")
    if any(value is not None for value in additive_fields) and not all(value is not None for value in additive_fields):
        errors.append("decision and presentation contracts must be published together")
    if all(value is not None for value in additive_fields) and meta.get("schema_version") == "1.2":
        expected_buckets = build_candidate_buckets(themes, dynamic)
        errors.extend(_semantic_differences(buckets, expected_buckets, "candidate_buckets"))
        config = load_json(Path(__file__).resolve().parents[1] / "config" / "universe.json")
        configured_context_ids = set(config.get("structural_contexts", {}))
        configured_dynamic_ids = set(config.get("dynamic_industries", {}))
        configured_fixed_ids = configured_context_ids - configured_dynamic_ids
        repository_configuration = bool(themes) and set(themes) == configured_fixed_ids
        if repository_configuration:
            if set(dynamic.get("candidates", {})) != configured_dynamic_ids:
                errors.append("dynamic discovery must evaluate every configured industry exactly once")
            known_ids = set(themes) | configured_dynamic_ids
            missing_contexts = sorted(known_ids - configured_context_ids)
            missing_lenses = sorted(known_ids - set(config.get("research_lenses", {})))
            if missing_contexts:
                errors.append(f"configured candidates missing structural context: {missing_contexts}")
            if missing_lenses:
                errors.append(f"configured candidates missing research lenses: {missing_lenses}")
            for theme_id, theme in themes.items():
                if theme.get("structural_context") != config.get("structural_contexts", {}).get(theme_id):
                    errors.append(f"{theme_id}: structural context does not match versioned configuration")
        expected_companies = select_companies(themes, dynamic, expected_buckets, {})
        projection_fields = ("theme_id", "theme_label", "source", "ticker", "selection_role", "why")
        observed_projection = [{key: item.get(key) for key in projection_fields} for item in companies]
        expected_projection = [{key: item.get(key) for key in projection_fields} for item in expected_companies]
        errors.extend(_semantic_differences(observed_projection, expected_projection, "company_candidates"))
        for item in companies:
            lens_source = item.get("research_lens_source", "")
            source = themes.get(item.get("theme_id"), {}) if item.get("source") == "fixed_theme" else dynamic.get("candidates", {}).get(item.get("theme_id"), {})
            row = next((row for row in source.get("constituents", []) if row.get("ticker") == item.get("ticker")), {})
            known_configured_lens = item.get("theme_id") in config.get("research_lenses", {}) or item.get("ticker") in config.get("company_research_overrides", {})
            lens_config = config if known_configured_lens or lens_source.startswith("role:") else {}
            expected_lens, expected_source = _research_lens(lens_config, item.get("theme_id"), item.get("ticker"), row.get("role", "core"), item.get("selection_role"))
            if lens_source != expected_source or item.get("key_check") != expected_lens.get("key_check") or item.get("counter_evidence") != expected_lens.get("counter_evidence"):
                errors.append(f"{item.get('ticker')}: company research lens does not match its declared source")
        if set(buckets) != {"selection_version", "max_research_items", *BUCKET_NAMES}:
            errors.append("candidate_buckets must expose exactly the four canonical buckets")
        known = {(theme_id, "fixed_theme") for theme_id in themes} | {(candidate_id, "dynamic_industry") for candidate_id in dynamic.get("candidates", {})}
        memberships: dict[tuple[str, str], list[str]] = {}
        for bucket_name in BUCKET_NAMES:
            for item in buckets.get(bucket_name, []):
                key = (item.get("id"), item.get("source"))
                memberships.setdefault(key, []).append(bucket_name)
        for key in sorted(known):
            if len(memberships.get(key, [])) != 1:
                errors.append(f"candidate membership must be exactly one bucket: {key}")
        for key in sorted(set(memberships) - known):
            errors.append(f"unknown candidate in buckets: {key}")
        for item in buckets.get("long_term_context_price_weak", []):
            source = themes.get(item.get("id")) if item.get("source") == "fixed_theme" else dynamic.get("candidates", {}).get(item.get("id"))
            if not source or source.get("structural_context", {}).get("status") != "supported":
                errors.append(f"{item.get('id')}: long-term bucket requires supported structural context")
        company_texts = [(item.get("key_check"), item.get("counter_evidence")) for item in companies]
        if len(company_texts) > 1 and len(set(company_texts)) == 1:
            errors.append("all company research lenses are identical")
        dynamic_ids = dynamic.get("candidate_ids", [])
        expected_thresholds = {"etf_rel_spy_4w_min": 0.03, "minimum_companies": 3, "pct_above_50dma_min": 0.50, "median_rel_spy_4w_min_exclusive": 0.0}
        if dynamic.get("thresholds") != expected_thresholds:
            errors.append("dynamic discovery thresholds do not match methodology")
        candidate_map = dynamic.get("candidates", {})
        expected_dynamic_ids = sorted(
            (key for key, candidate in candidate_map.items() if candidate.get("eligible") is True),
            key=lambda key: (-candidate_map[key].get("metrics", {}).get("equal_weight_rel_spy_4w", 0), key),
        )
        if dynamic_ids != expected_dynamic_ids:
            errors.append("dynamic candidate_ids must be the ordered eligible subset")
        for candidate_id, candidate in candidate_map.items():
            metrics = candidate.get("metrics", {})
            if candidate.get("candidate_id") != candidate_id:
                errors.append(f"dynamic candidate key mismatch: {candidate_id}")
            if candidate.get("eligible") != (not candidate.get("rejection_reasons", [])):
                errors.append(f"{candidate_id}: eligibility and rejection reasons disagree")
            if dynamic.get("rejected", {}).get(candidate_id, []) != candidate.get("rejection_reasons", []):
                errors.append(f"{candidate_id}: rejected index does not match candidate reasons")
            if repository_configuration and candidate.get("structural_context") != config.get("structural_contexts", {}).get(candidate_id):
                errors.append(f"{candidate_id}: structural context does not match versioned configuration")
            if candidate.get("eligible") and (finite(candidate.get("reference_etf_rel_spy_4w")) is None or candidate["reference_etf_rel_spy_4w"] < 0.03):
                errors.append(f"{candidate_id}: reference ETF threshold failed")
            if candidate.get("eligible") and len([row for row in candidate.get("constituents", []) if finite(row.get("rel_spy_4w")) is not None]) < 3:
                errors.append(f"{candidate_id}: dynamic candidate requires three usable companies")
            constituent_rels = [row.get("rel_spy_4w") for row in candidate.get("constituents", [])]
            usable_rels = sorted(float(value) for value in constituent_rels if finite(value) is not None)
            if usable_rels:
                middle = len(usable_rels) // 2
                expected_median = usable_rels[middle] if len(usable_rels) % 2 else (usable_rels[middle - 1] + usable_rels[middle]) / 2
                if metrics.get("median_rel_spy_4w") != expected_median:
                    errors.append(f"{candidate_id}: median relative strength does not match constituents")
            expected_above = ratio_true(row.get("above_50dma") for row in candidate.get("constituents", []))
            if metrics.get("pct_above_50dma") != expected_above:
                errors.append(f"{candidate_id}: 50DMA breadth does not match constituents")
            expected_top1, expected_top3, _ = positive_concentration(constituent_rels)
            if metrics.get("top1_contribution_ratio") != expected_top1 or metrics.get("top3_contribution_ratio") != expected_top3:
                errors.append(f"{candidate_id}: contribution concentration does not match constituents")
            for field, predicate in (
                ("median_rel_spy_4w", lambda value: value > 0),
                ("pct_above_50dma", lambda value: value >= 0.50),
            ):
                value = metrics.get(field)
                if candidate.get("eligible") and (finite(value) is None or not predicate(value)):
                    errors.append(f"{candidate_id}: dynamic candidate {field} threshold failed")
            if candidate.get("eligible") and metrics.get("single_name_concentrated") is not False:
                errors.append(f"{candidate_id}: concentrated dynamic candidate cannot advance")
            if candidate.get("eligible") and not any(item.get("id") == candidate_id and item.get("source") == "dynamic_industry" for item in buckets.get("research_now", []) + buckets.get("avoid_now", [])):
                errors.append(f"{candidate_id}: dynamic candidate was lost before research queue")
        for theme_id, theme in themes.items():
            decision = theme.get("decision")
            if not isinstance(decision, dict):
                errors.append(f"{theme_id}: decision projection is required")
                continue
            expected_bucket = next((name for name in BUCKET_NAMES if any(item.get("id") == theme_id and item.get("source") == "fixed_theme" for item in buckets.get(name, []))), None)
            if decision.get("candidate_bucket") != expected_bucket:
                errors.append(f"{theme_id}: candidate bucket mismatch")
            expected_decision = build_theme_decision(theme, expected_bucket)
            errors.extend(_semantic_differences(decision, expected_decision, f"themes.{theme_id}.decision"))
            if decision.get("direct_flow_confirmation") != "unavailable":
                errors.append(f"{theme_id}: direct flow cannot be confirmed without direct-flow data")
            if expected_bucket == "research_now":
                metrics = theme.get("metrics", {})
                if not (finite(metrics.get("equal_weight_rel_spy_4w")) is not None and metrics["equal_weight_rel_spy_4w"] > 0 and finite(metrics.get("advance_ratio_4w")) is not None and metrics["advance_ratio_4w"] >= 0.60 and theme.get("condition_flags", {}).get("broad_concentration_pass") is True):
                    errors.append(f"{theme_id}: weak or concentrated theme cannot enter research queue")
            if expected_bucket == "long_term_context_price_weak" and theme.get("structural_context", {}).get("status") != "supported":
                errors.append(f"{theme_id}: unsupported structural context cannot enter long-term bucket")
        history_weeks = min((theme.get("quality", {}).get("history_weeks", 0) for theme in themes.values()), default=0)
        view_companies = companies if all(
            all(item.get(field) for field in ("ticker", "theme_label", "selection_role", "why", "key_check", "counter_evidence"))
            for item in companies
        ) else expected_companies
        presentation_version = user_view.get("presentation_version")
        if presentation_version not in {"1.1", "1.2"}:
            errors.append(f"unsupported schema 1.2 presentation version: {presentation_version}")
            presentation_version = "1.2"
        expected_view = build_user_view(
            regime=latest.get("market_regime", {}), style_factor=latest.get("style_factor", {}),
            sectors=latest.get("sectors", {}), industries=latest.get("industries", {}), themes=themes,
            dynamic=dynamic, buckets=expected_buckets, companies=view_companies, history_weeks=history_weeks,
            presentation_version=presentation_version,
        )
        errors.extend(_semantic_differences(user_view, expected_view, "user_view"))
        forbidden = ("classification_eligible", "direction_eligible", "condition_flags", "matched_conditions", "source_sha256", "run_id", "EV_", "SL_", "Q_", "P1", "P2", "P3", "P4", "P5")
        rendered = "\n".join(render_phase(user_view, phase) for phase in range(1, 7))
        for token in forbidden:
            if token in rendered:
                errors.append(f"user presentation contains internal token: {token}")
        if user_view.get("analysis_mode") == "initial_observation":
            for token in ("初動", "拡散", "失速", "悪化", "反転", "流入継続", "流出継続", "加速", "減速"):
                if token in rendered:
                    errors.append(f"initial-observation presentation contains forbidden trend claim: {token}")
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
    latest_schema = load_json(Path(__file__).resolve().parents[1] / "schemas" / "rotation_snapshot.schema.json")
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
    }
    for field, expected in versions.items():
        if record.get(field) != expected:
            errors.append(f"judgment {field} does not match source latest contract")
    allowed_instruction_versions = {"1.3.0", "1.4.0", "1.5.0", INSTRUCTION_VERSION} if source_meta.get("schema_version") == "1.2" else {"1.1.1"}
    if record.get("instruction_version") not in allowed_instruction_versions:
        errors.append("judgment instruction_version does not match source latest contract")
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
        seen_condition_ids = set()
        expected_prefix = f"themes.{theme_id}."
        for condition in theme.get("withdrawal_conditions", []):
            condition_id = condition.get("condition_id")
            if condition_id in seen_condition_ids:
                errors.append(f"{theme_id}: duplicate withdrawal condition_id: {condition_id}")
            seen_condition_ids.add(condition_id)
            field_path = condition.get("field_path", "")
            if not field_path.startswith(expected_prefix):
                errors.append(f"{theme_id}/{condition_id}: withdrawal field_path must target the same source theme")
                continue
            observed = _path_value(source_latest, field_path)
            if observed is _MISSING:
                errors.append(f"{theme_id}/{condition_id}: withdrawal field_path is absent from source latest")
                continue
            operator, expected = condition.get("operator"), condition.get("value")
            schema_types = _schema_types_for_path(latest_schema, field_path) - {"null"}
            if not schema_types or not _scalar_matches_schema(expected, schema_types):
                errors.append(f"{theme_id}/{condition_id}: withdrawal value type does not match the source field schema")
            if operator in {"<", "<=", ">", ">="}:
                if isinstance(expected, bool) or not isinstance(expected, (int, float)):
                    errors.append(f"{theme_id}/{condition_id}: ordered withdrawal comparison requires a numeric value")
                if not ({"number", "integer"} & schema_types) or (observed is not None and (isinstance(observed, bool) or not isinstance(observed, (int, float)))):
                    errors.append(f"{theme_id}/{condition_id}: ordered withdrawal comparison targets a non-numeric field")
            elif observed is not None and not _compatible_scalar(observed, expected):
                errors.append(f"{theme_id}/{condition_id}: withdrawal value type does not match the source field")
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
