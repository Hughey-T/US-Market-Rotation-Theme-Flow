"""Explicit read-only adapter for unsupported Market Rotation 1.0 data."""
from __future__ import annotations

import copy


class UnsupportedLegacyVersion(ValueError):
    pass


PHASE_MAP = {
    "初動": ("initial", "unclassifiable"),
    "拡散": ("diffusion", "unclassifiable"),
    "過熱": ("price_overheat", "unclassifiable"),
    "流出": ("unclassifiable", "outflow_signal"),
    "判定不能": ("unclassifiable", "unclassifiable"),
}


def read_legacy_snapshot(value: dict, *, explicit: bool = False) -> dict:
    version = value.get("meta", {}).get("schema_version")
    if version != "1.0":
        raise UnsupportedLegacyVersion(f"expected Market Rotation schema 1.0, got {version!r}")
    if not explicit:
        raise UnsupportedLegacyVersion("schema 1.0 is unsupported by default; use the explicit migration command")
    mappings = []
    for theme_id, theme in value.get("themes", {}).items():
        old_phase = theme.get("phase_assessment", {}).get("phase", "判定不能")
        phase, direction = PHASE_MAP.get(old_phase, ("unclassifiable", "unclassifiable"))
        mappings.append({
            "theme_id": theme_id, "legacy_phase": old_phase, "phase": phase, "direction": direction,
            "classification_eligible": False,
            "migration_warning": "1.0 lacks required trend, concentration, quality, priority, timing, and shortlist fields; regenerate from source data",
        })
    return {
        "migration_report_version": "1.0", "source_schema_version": "1.0", "target_schema_version": "1.1",
        "publishable": False, "automatic_judgment_conversion": False, "theme_mappings": mappings,
    }
