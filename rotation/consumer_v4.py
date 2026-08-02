"""Consumer contract v4: deterministic blind/mechanical package publication.

The producer owns facts and mechanical signals. AI-authored artifacts are never
created by this module. Blind packages are physically separated from
reconciliation packages and recursively checked for rank leakage.
"""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .provenance import atomic_write_json, canonical_bytes, stable_hash
from .validation import ContractError

CONSUMER_V4_CONTRACT_VERSION = "4.0"
POINTER_VERSION = "1.0"
MANIFEST_VERSION = "1.0"
CHUNK_VERSION = "1.0"
PACKAGE_ORDER = (
    "facts", "blind", "companies", "blind-handoff",
    "mechanical", "reconciliation-handoff",
)
BLIND_PACKAGES = frozenset({"facts", "blind", "companies", "blind-handoff"})
RECONCILIATION_PACKAGES = frozenset({"mechanical", "reconciliation-handoff"})
FORBIDDEN_BLIND_KEYS = frozenset({
    "mechanical_rank", "mechanical_priority", "candidate_bucket",
    "integrated_rank", "integrated_decision", "final_shortlist",
    "final_theme_recommendation", "producer_conclusion",
    "previous_ai_assessment", "ai_confidence", "final_company_priority",
    "current_generation_outcome", "future_outcome",
})
TARGET_FRAGMENT_BYTES = 8 * 1024
MAX_PARTS = 32
MAX_PACKAGE_BYTES = 256 * 1024


def _strict_object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, child in pairs:
        if key in value:
            raise ContractError(f"duplicate JSON key: {key}")
        value[key] = child
    return value


def strict_json_loads(raw: str) -> Any:
    return json.loads(
        raw,
        object_pairs_hook=_strict_object_pairs,
        parse_constant=lambda value: (_ for _ in ()).throw(
            ContractError(f"non-finite JSON constant: {value}")
        ),
    )


def _generation_id(snapshot: dict) -> str:
    source = str(snapshot.get("meta", {}).get("source_snapshot", ""))
    parts = Path(source).as_posix().split("/")
    if len(parts) == 4 and parts[:2] == ["output", "generations"] and parts[3] == "archive.json":
        value = parts[2]
    else:
        value = stable_hash({
            "analysis_id": snapshot.get("meta", {}).get("run_id"),
            "generated_at": snapshot.get("meta", {}).get("generated_at"),
            "source_sha256": snapshot.get("meta", {}).get("source_sha256"),
        })
    if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ContractError("consumer v4 generation_id must be lowercase 64-hex")
    return value


def _analysis_id(snapshot: dict) -> str:
    value = snapshot.get("meta", {}).get("run_id")
    if not isinstance(value, str) or not value:
        raise ContractError("consumer v4 requires meta.run_id")
    return value


def _theme_ids(snapshot: dict) -> list[str]:
    themes = snapshot.get("themes")
    if not isinstance(themes, dict) or not themes:
        raise ContractError("consumer v4 requires non-empty themes")
    return sorted(themes)


def _company_key(item: dict) -> str:
    return f"{item.get('theme_id', '')}:{item.get('ticker', '')}"


def _company_ids(snapshot: dict) -> list[str]:
    rows = snapshot.get("company_candidates") or []
    if not isinstance(rows, list):
        raise ContractError("company_candidates must be an array")
    values = [_company_key(item) for item in rows if isinstance(item, dict)]
    if len(values) != len(set(values)):
        raise ContractError("consumer v4 company identity is duplicated")
    return sorted(values)


def _common_identity(snapshot: dict) -> dict:
    meta = snapshot["meta"]
    theme_ids = _theme_ids(snapshot)
    company_ids = _company_ids(snapshot)
    return {
        "consumer_contract_version": CONSUMER_V4_CONTRACT_VERSION,
        "generation_id": _generation_id(snapshot),
        "analysis_id": _analysis_id(snapshot),
        "data_date": meta.get("data_date"),
        "generated_at": meta.get("generated_at"),
        "source_cutoff": meta.get("data_date"),
        "source_sha256": meta.get("source_sha256"),
        "theme_set_identity": stable_hash(theme_ids),
        "company_candidate_set_identity": stable_hash(company_ids),
        "theme_ids": theme_ids,
        "company_candidate_ids": company_ids,
    }


def _copy(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _copy(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_copy(child) for child in value]
    return copy.deepcopy(value)


def _theme_facts(theme_id: str, theme: dict) -> dict:
    return {
        "theme_id": theme_id,
        "display_name": theme.get("label", theme_id),
        "description": theme.get("description"),
        "metrics": _copy(theme.get("metrics") or {}),
        "quality": _copy(theme.get("quality") or {}),
        "trends": _copy(theme.get("trends") or {}),
        "classifications_observed": _copy({
            key: value for key, value in (theme.get("classifications") or {}).items()
            if key in {"phase", "direction", "evidence"}
        }),
        "constituents": _copy(theme.get("constituents") or []),
        "structural_context": _copy(theme.get("structural_context")),
    }


def _dynamic_industry_facts(snapshot: dict) -> list[dict]:
    dynamic = snapshot.get("dynamic_discovery") or {}
    rows = dynamic if isinstance(dynamic, list) else (
        dynamic.get("industries") or dynamic.get("candidates") or []
        if isinstance(dynamic, dict) else []
    )
    result = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        result.append({
            "industry_id": row.get("industry_id") or row.get("theme_id") or row.get("id"),
            "display_name": row.get("label") or row.get("display_name"),
            "observations": _copy({
                key: value for key, value in row.items()
                if key not in {"mechanical_rank", "mechanical_priority", "candidate_bucket", "integrated_rank"}
            }),
        })
    return result


def _price_confirmation(theme: dict) -> dict:
    metrics = theme.get("metrics") or {}
    quality = theme.get("quality") or {}
    relative = metrics.get("equal_weight_rel_spy_4w")
    breadth = metrics.get("advance_ratio_4w")
    above = metrics.get("pct_above_50dma")
    available = all(
        isinstance(value, (int, float)) and not isinstance(value, bool)
        for value in (relative, breadth, above)
    )
    return {
        "data_available": available,
        "relative_threshold_pass": bool(available and relative >= 0.05),
        "breadth_pass": bool(available and breadth >= 0.60 and above >= 0.50),
        "quality_pass": quality.get("classification_eligible") is True,
    }


def _company_facts(snapshot: dict) -> list[dict]:
    theme_map = snapshot.get("themes") or {}
    result = []
    for item in snapshot.get("company_candidates") or []:
        if not isinstance(item, dict):
            continue
        theme_id, ticker = item.get("theme_id"), item.get("ticker")
        theme = theme_map.get(theme_id, {})
        constituent_tickers = [
            row.get("ticker") for row in theme.get("constituents") or []
            if isinstance(row, dict) and row.get("ticker")
        ]
        centrality = (
            1.0 / max(1, constituent_tickers.index(ticker) + 1)
            if ticker in constituent_tickers else None
        )
        duplicate_themes = sorted(
            other_id for other_id, other in theme_map.items()
            if ticker and any(
                isinstance(row, dict) and row.get("ticker") == ticker
                for row in (other.get("constituents") or [])
            )
        )
        market_cap_available = isinstance(item.get("market_cap"), (int, float))
        result.append({
            "company_candidate_id": _company_key(item),
            "theme_id": theme_id,
            "ticker": ticker,
            "company_name": item.get("company_name"),
            "company_role": item.get("selection_role") or item.get("candidate_role") or "other",
            "constituent_centrality": centrality,
            "revenue_exposure": {"status": "not_available", "value": None},
            "earnings_exposure": {"status": "not_available", "value": None},
            "operating_leverage": {"status": "not_available", "value": None},
            "financial_quality": {"status": "not_available", "value": None},
            "liquidity": {
                "status": "available" if isinstance(item.get("dollar_volume_20d"), (int, float)) else "not_available",
                "value": item.get("dollar_volume_20d"),
            },
            "market_cap": {
                "status": "available" if market_cap_available else "not_available",
                "value": item.get("market_cap"),
            },
            "price_confirmation": _price_confirmation(theme),
            "duplicate_theme_exposure": duplicate_themes,
            "inclusion_reason": item.get("why") or item.get("selection_reason"),
            "exclusion_reason": item.get("exclusion_reason"),
            "missingness": [
                "revenue_exposure", "earnings_exposure",
                "operating_leverage", "financial_quality",
                *([] if market_cap_available else ["market_cap"]),
            ],
        })
    return sorted(result, key=lambda row: row["company_candidate_id"])


def _mechanical_signals(snapshot: dict) -> list[dict]:
    rows = []
    for theme_id, theme in (snapshot.get("themes") or {}).items():
        rows.append((theme_id, theme, (theme.get("metrics") or {}).get("equal_weight_rel_spy_4w")))
    rows.sort(key=lambda row: (
        not isinstance(row[2], (int, float)),
        -(row[2] if isinstance(row[2], (int, float)) else 0.0), row[0],
    ))
    result = []
    fundamentals = ((snapshot.get("v3_inputs") or {}).get("fundamentals") or {}).get("themes", {})
    for rank, (theme_id, theme, _) in enumerate(rows, 1):
        decision, quality = theme.get("decision") or {}, theme.get("quality") or {}
        bucket = decision.get("candidate_bucket") or "unavailable"
        hard = quality.get("classification_eligible") is False or bucket == "avoid_now"
        result.append({
            "theme_id": theme_id,
            "mechanical_rank": rank,
            "mechanical_priority": (theme.get("classifications") or {}).get("research_priority"),
            "candidate_bucket": bucket,
            "price_confirmation": _price_confirmation(theme),
            "fundamental_confirmation": _copy(fundamentals.get(theme_id)),
            "hard_exclusion": hard,
            "hard_exclusion_reason": (
                "quality_ineligible" if quality.get("classification_eligible") is False
                else "avoid_now" if bucket == "avoid_now" else None
            ),
            "machine_reason_components": _copy({
                "condition_flags": theme.get("condition_flags"),
                "quality": quality, "decision": decision,
            }),
        })
    return result


def assert_blind_safe(value: Any, path: str = "<root>") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FORBIDDEN_BLIND_KEYS:
                raise ContractError(f"blind projection rank leakage at {path}.{key}")
            assert_blind_safe(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            assert_blind_safe(child, f"{path}[{index}]")


def build_consumer_v4_packages(snapshot: dict) -> dict[str, dict]:
    common = _common_identity(snapshot)
    themes = [_theme_facts(theme_id, snapshot["themes"][theme_id]) for theme_id in common["theme_ids"]]
    companies = _company_facts(snapshot)
    dynamic = _dynamic_industry_facts(snapshot)
    quality = {
        "global_quality": _copy(snapshot.get("meta", {}).get("global_quality")),
        "coverage": _copy(snapshot.get("coverage") or {}),
        "warnings": _copy(snapshot.get("warnings") or []),
    }
    facts = {
        **common, "artifact_type": "FACTS",
        "market_regime": _copy(snapshot.get("market_regime") or {}),
        "style_analysis": _copy(snapshot.get("style_analysis") or {}),
        "sector_analysis": _copy(snapshot.get("sector_analysis") or {}),
        "industry_analysis": _copy(snapshot.get("industry_analysis") or {}),
        "themes": themes, "dynamic_industries": dynamic,
        "data_quality": quality,
        "source_refs": [snapshot.get("meta", {}).get("source_snapshot")],
    }
    blind = {
        **common, "artifact_type": "BLIND_THEME_PROJECTION",
        "themes": themes, "dynamic_industries": dynamic,
        "market_context": {
            "market_regime": _copy(snapshot.get("market_regime") or {}),
            "style_analysis": _copy(snapshot.get("style_analysis") or {}),
        },
        "data_quality": quality,
        "source_refs": [snapshot.get("meta", {}).get("source_snapshot")],
        "disclosure_stage": "blind",
    }
    company_package = {
        **common, "artifact_type": "COMPANY_CANDIDATE_FACTS",
        "companies": companies, "data_quality": quality,
        "disclosure_stage": "blind",
    }
    blind_handoff = {
        **common, "artifact_type": "BLIND_COMPARISON_HANDOFF",
        "themes": [{
            "theme_id": row["theme_id"], "display_name": row["display_name"],
            "constituents": row["constituents"], "metrics": row["metrics"],
            "quality": row["quality"],
        } for row in themes],
        "companies": companies, "beneficiary_characteristics": [],
        "required_company_checks": [
            "revenue exposure", "earnings exposure", "operating leverage",
            "financial quality", "valuation",
        ],
        "unresolved_factual_questions": [], "disclosure_stage": "blind",
    }
    mechanical = {
        **common, "artifact_type": "MECHANICAL_SIGNALS",
        "signals": _mechanical_signals(snapshot),
        "disclosure_stage": "reconciliation",
    }
    reconciliation_handoff = {
        **common, "artifact_type": "COMPARISON_RECONCILIATION_HANDOFF",
        "mechanical_signals": mechanical["signals"],
        "theme_context": [{
            "theme_id": row["theme_id"], "display_name": row["display_name"],
            "structural_context": row["structural_context"],
        } for row in themes],
        "disclosure_order": {
            "blind_packages_first": sorted(BLIND_PACKAGES),
            "reconciliation_packages_after_assessment_fix": sorted(RECONCILIATION_PACKAGES),
        },
        "disclosure_stage": "reconciliation",
    }
    packages = {
        "facts": facts, "blind": blind, "companies": company_package,
        "blind-handoff": blind_handoff, "mechanical": mechanical,
        "reconciliation-handoff": reconciliation_handoff,
    }
    for name in BLIND_PACKAGES:
        assert_blind_safe(packages[name])
    return packages


def _split_text(text: str, target_bytes: int = TARGET_FRAGMENT_BYTES) -> list[str]:
    parts, current, size = [], [], 0
    for character in text:
        encoded = character.encode("utf-8")
        if current and size + len(encoded) > target_bytes:
            parts.append("".join(current)); current, size = [], 0
        current.append(character); size += len(encoded)
    if current or not parts:
        parts.append("".join(current))
    return parts


def _chunk_objects(package: str, payload: dict, generation_id: str) -> tuple[list[dict], dict]:
    raw = canonical_bytes(payload)
    if len(raw) > MAX_PACKAGE_BYTES:
        raise ContractError(f"consumer v4 package {package} exceeds {MAX_PACKAGE_BYTES} bytes")
    fragments = _split_text(raw.decode("utf-8"))
    if len(fragments) > MAX_PARTS:
        raise ContractError(f"consumer v4 package {package} exceeds {MAX_PARTS} parts")
    chunks = []
    for index, fragment in enumerate(fragments, 1):
        fragment_bytes = fragment.encode("utf-8")
        chunks.append({
            "consumer_contract_version": CONSUMER_V4_CONTRACT_VERSION,
            "chunk_version": CHUNK_VERSION, "generation_id": generation_id,
            "package": package, "part": index, "part_count": len(fragments),
            "fragment": fragment, "fragment_byte_length": len(fragment_bytes),
            "fragment_sha256": hashlib.sha256(fragment_bytes).hexdigest(),
        })
    inventory = {
        "package": package, "part_count": len(chunks),
        "total_payload_bytes": len(raw),
        "canonical_sha256": hashlib.sha256(raw).hexdigest(),
        "parts": [{
            "part": chunk["part"], "path": f"{package}/part-{chunk['part']}.json",
            "fragment_byte_length": chunk["fragment_byte_length"],
            "fragment_sha256": chunk["fragment_sha256"],
            "file_sha256": hashlib.sha256(canonical_bytes(chunk)).hexdigest(),
        } for chunk in chunks],
    }
    return chunks, inventory


def build_consumer_v4_transport(snapshot: dict) -> tuple[dict, dict, dict[str, list[dict]]]:
    packages, common = build_consumer_v4_packages(snapshot), _common_identity(snapshot)
    chunk_map, inventory = {}, []
    for package in PACKAGE_ORDER:
        chunks, package_inventory = _chunk_objects(package, packages[package], common["generation_id"])
        chunk_map[package] = chunks; inventory.append(package_inventory)
    manifest = {
        "consumer_contract_version": CONSUMER_V4_CONTRACT_VERSION,
        "manifest_version": MANIFEST_VERSION,
        **{key: common[key] for key in (
            "generation_id", "analysis_id", "data_date", "source_sha256",
            "theme_set_identity", "company_candidate_set_identity",
        )},
        "package_order": list(PACKAGE_ORDER),
        "blind_packages": sorted(BLIND_PACKAGES),
        "reconciliation_packages": sorted(RECONCILIATION_PACKAGES),
        "packages": inventory,
    }
    pointer = {
        "consumer_contract_version": CONSUMER_V4_CONTRACT_VERSION,
        "pointer_version": POINTER_VERSION,
        "generation_id": common["generation_id"], "analysis_id": common["analysis_id"],
        "data_date": common["data_date"],
        "generation": f"generations/{common['generation_id']}",
        "generation_manifest_sha256": stable_hash(manifest),
    }
    return pointer, manifest, chunk_map


def _write_generation(root: Path, manifest: dict, chunks: dict[str, list[dict]]) -> Path:
    generation_id = manifest["generation_id"]
    generations, target = root / "generations", root / "generations" / generation_id
    if target.exists():
        loaded = _load_generation(root, generation_id)
        if loaded[0] != manifest:
            raise ContractError(f"consumer v4 generation collision: {generation_id}")
        return target
    generations.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".staging-{generation_id}-", dir=generations))
    try:
        atomic_write_json(staging / "manifest.json", manifest)
        for package in PACKAGE_ORDER:
            for chunk in chunks[package]:
                atomic_write_json(staging / package / f"part-{chunk['part']}.json", chunk)
        _validate_generation_directory(staging, manifest)
        staging.replace(target)
    finally:
        if staging.exists(): shutil.rmtree(staging)
    return target


def export_consumer_v4(snapshot: dict, root: Path) -> dict:
    pointer, manifest, chunks = build_consumer_v4_transport(snapshot)
    root.mkdir(parents=True, exist_ok=True)
    _write_generation(root, manifest, chunks)
    atomic_write_json(root / "manifest.json", pointer)
    loaded = load_and_validate_consumer_v4(root)
    if loaded["pointer"] != pointer:
        raise ContractError("consumer v4 moving manifest verification failed")
    return pointer


def _load_json_file(path: Path) -> Any:
    if path.is_symlink() or not path.is_file():
        raise ContractError(f"consumer v4 invalid file: {path}")
    try:
        return strict_json_loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ContractError(f"consumer v4 invalid JSON: {path}") from error


def _validate_generation_directory(directory: Path, expected_manifest: dict | None = None) -> dict:
    if directory.is_symlink() or not directory.is_dir():
        raise ContractError("consumer v4 generation directory is invalid")
    manifest = _load_json_file(directory / "manifest.json")
    if expected_manifest is not None and manifest != expected_manifest:
        raise ContractError("consumer v4 immutable manifest mismatch")
    if manifest.get("consumer_contract_version") != CONSUMER_V4_CONTRACT_VERSION:
        raise ContractError("consumer v4 manifest contract mismatch")
    if manifest.get("package_order") != list(PACKAGE_ORDER):
        raise ContractError("consumer v4 package order mismatch")
    if {entry.name for entry in directory.iterdir()} != {"manifest.json", *PACKAGE_ORDER}:
        raise ContractError("consumer v4 generation inventory mismatch")
    return manifest


def _load_generation(root: Path, generation_id: str) -> tuple[dict, dict[str, dict]]:
    directory = root / "generations" / generation_id
    manifest = _validate_generation_directory(directory)
    if manifest.get("generation_id") != generation_id or directory.name != generation_id:
        raise ContractError("consumer v4 generation identity mismatch")
    package_inventory = {row["package"]: row for row in manifest["packages"]}
    if set(package_inventory) != set(PACKAGE_ORDER):
        raise ContractError("consumer v4 package manifest inventory mismatch")
    packages: dict[str, dict] = {}
    for package in PACKAGE_ORDER:
        package_dir, item = directory / package, package_inventory[package]
        if package_dir.is_symlink() or not package_dir.is_dir():
            raise ContractError(f"consumer v4 package directory invalid: {package}")
        expected_names = {f"part-{part}.json" for part in range(1, item["part_count"] + 1)}
        if {entry.name for entry in package_dir.iterdir()} != expected_names:
            raise ContractError(f"consumer v4 part inventory mismatch: {package}")
        fragments, total = [], 0
        for part_meta in item["parts"]:
            path, chunk = directory / part_meta["path"], _load_json_file(directory / part_meta["path"])
            if (
                chunk.get("consumer_contract_version") != CONSUMER_V4_CONTRACT_VERSION
                or chunk.get("generation_id") != generation_id
                or chunk.get("package") != package
                or chunk.get("part") != part_meta["part"]
                or chunk.get("part_count") != item["part_count"]
            ):
                raise ContractError(f"consumer v4 chunk identity mismatch: {path}")
            raw = chunk.get("fragment", "").encode("utf-8")
            if (
                len(raw) != chunk.get("fragment_byte_length")
                or hashlib.sha256(raw).hexdigest() != chunk.get("fragment_sha256")
                or chunk.get("fragment_sha256") != part_meta["fragment_sha256"]
                or hashlib.sha256(canonical_bytes(chunk)).hexdigest() != part_meta["file_sha256"]
            ):
                raise ContractError(f"consumer v4 chunk hash mismatch: {path}")
            total += len(raw); fragments.append(chunk["fragment"])
        if total != item["total_payload_bytes"]:
            raise ContractError(f"consumer v4 package byte length mismatch: {package}")
        raw_text = "".join(fragments)
        if hashlib.sha256(raw_text.encode("utf-8")).hexdigest() != item["canonical_sha256"]:
            raise ContractError(f"consumer v4 package reconstruction hash mismatch: {package}")
        payload = strict_json_loads(raw_text)
        if canonical_bytes(payload) != raw_text.encode("utf-8"):
            raise ContractError(f"consumer v4 package is not canonical JSON: {package}")
        for identity in ("generation_id", "analysis_id", "theme_set_identity", "company_candidate_set_identity"):
            if payload.get(identity) != manifest.get(identity):
                raise ContractError(f"consumer v4 package {identity} mismatch: {package}")
        if package in BLIND_PACKAGES: assert_blind_safe(payload)
        packages[package] = payload
    return manifest, packages


def load_and_validate_consumer_v4(root: Path) -> dict:
    if root.is_symlink() or not root.is_dir():
        raise ContractError("consumer v4 root is invalid")
    if {entry.name for entry in root.iterdir()} != {"manifest.json", "generations"}:
        raise ContractError("consumer v4 root inventory mismatch")
    pointer = _load_json_file(root / "manifest.json")
    if pointer.get("consumer_contract_version") != CONSUMER_V4_CONTRACT_VERSION:
        raise ContractError("consumer v4 pointer contract mismatch")
    generation_id = pointer.get("generation_id")
    if not isinstance(generation_id, str) or pointer.get("generation") != f"generations/{generation_id}":
        raise ContractError("consumer v4 pointer generation path mismatch")
    generations = root / "generations"
    if generations.is_symlink() or not generations.is_dir():
        raise ContractError("consumer v4 generations directory is invalid")
    for entry in generations.iterdir():
        if entry.is_symlink() or not entry.is_dir():
            raise ContractError("consumer v4 generation symlink/file is forbidden")
        if len(entry.name) != 64 or any(c not in "0123456789abcdef" for c in entry.name):
            raise ContractError("consumer v4 generation directory name is invalid")
    manifest, packages = _load_generation(root, generation_id)
    if stable_hash(manifest) != pointer.get("generation_manifest_sha256"):
        raise ContractError("consumer v4 moving/immutable manifest hash mismatch")
    for field in ("generation_id", "analysis_id", "data_date"):
        if pointer.get(field) != manifest.get(field):
            raise ContractError(f"consumer v4 pointer {field} mismatch")
    if packages["facts"]["theme_ids"] != packages["mechanical"]["theme_ids"]:
        raise ContractError("consumer v4 mixed theme set")
    if packages["companies"]["company_candidate_ids"] != packages["reconciliation-handoff"]["company_candidate_ids"]:
        raise ContractError("consumer v4 mixed company candidate set")
    return {"pointer": pointer, "manifest": manifest, "packages": packages}


def compare_consumer_v4_trees(left: Path, right: Path) -> None:
    if load_and_validate_consumer_v4(left) != load_and_validate_consumer_v4(right):
        raise ContractError("consumer v4 remote-equivalent reload mismatch")
