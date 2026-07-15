"""Deterministic analysis identity and execution-specific generation identity."""
from __future__ import annotations

import re
from pathlib import Path

from . import DATA_SCHEMA_VERSION, INSTRUCTION_VERSION, METHODOLOGY_VERSION
from .provenance import stable_hash
from .validation import ContractError


SAFE_ID_RE = re.compile(r"^[a-f0-9]{64}$")


def validate_safe_id(value: str | None, label: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not SAFE_ID_RE.fullmatch(value):
        raise ContractError(f"{label} must be a 64-character lowercase hexadecimal identifier")
    return value


def safe_generation_path(output: Path, generation_id: str) -> Path:
    validate_safe_id(generation_id, "generation_id")
    root = (output / "generations").resolve()
    candidate = (root / generation_id).resolve()
    if candidate.parent != root:
        raise ContractError("generation path escapes output/generations")
    return candidate


def analysis_identity(*, data_date: str, observations: dict, theme_master: dict, config: dict,
                      source_commit: str, quantitative: dict) -> str:
    return stable_hash({
        "data_date": data_date,
        "raw_input_identity": stable_hash(observations),
        "theme_master_identity": stable_hash(theme_master),
        "schema_version": DATA_SCHEMA_VERSION,
        "methodology_version": METHODOLOGY_VERSION,
        "instruction_version": INSTRUCTION_VERSION,
        "config_version": stable_hash(config),
        "source_commit": source_commit,
        "quantitative_content": quantitative,
    })


def generation_identity(analysis_id: str, generated_at: str, source_commit: str) -> str:
    validate_safe_id(analysis_id, "analysis_id")
    return stable_hash({"analysis_id": analysis_id, "generated_at": generated_at, "source_commit": source_commit})
