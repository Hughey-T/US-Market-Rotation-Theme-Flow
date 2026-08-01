"""Lossless fragment compaction for the immutable consumer v3 contract."""

from __future__ import annotations

import copy

from .consumer_v2 import _flatten_fragments as _leaf_fragments
from .provenance import canonical_bytes
from .validation import ContractError

FRAGMENT_TARGET_BYTES = 9 * 1024


def _escape_pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def compact_fragments(value, path: str = "") -> list[dict]:
    """Flatten JSON while retaining bounded containers as exact subtrees.

    The established leaf projection remains the fallback for oversized
    containers, scalars, empty containers, and long text.  No field is omitted,
    summarized, reordered, or inferred.
    """
    pointer = path or "/"
    if isinstance(value, (dict, list)) and value:
        candidate = {"field": pointer, "value": copy.deepcopy(value)}
        if len(canonical_bytes(candidate)) <= FRAGMENT_TARGET_BYTES:
            return [candidate]

        fragments: list[dict] = []
        if isinstance(value, dict):
            for key, item in value.items():
                child = f"{path}/{_escape_pointer_token(str(key))}"
                fragments.extend(compact_fragments(item, child))
        else:
            for index, item in enumerate(value):
                child = f"{path}/{index}"
                fragments.extend(compact_fragments(item, child))
        return fragments

    return _leaf_fragments(value, path)


def install(module) -> None:
    """Install compaction and diagnostic wrappers on ``rotation.consumer_v3``."""
    if getattr(module, "_fragment_compaction_installed", False):
        return

    original_chunks = module._chunks
    original_validate_inventory_limits = module._validate_inventory_limits

    module._flatten_fragments = compact_fragments

    def compact_chunks(
        view: dict,
        identity: dict,
        kind: str,
        phase: int,
    ) -> list[dict]:
        fragments = compact_fragments(view)
        if len(fragments) > module.MAX_PHASE_FRAGMENTS:
            raise ContractError(
                f"{kind} fragment limit exceeded for phase {phase}: "
                f"{len(fragments)} > {module.MAX_PHASE_FRAGMENTS}"
            )
        return original_chunks(view, identity, kind, phase)

    def validate_inventory_limits(
        phase_inventory: list[dict],
        detail_inventory: list[dict],
        handoff_inventory: dict | None = None,
    ) -> None:
        for phase_item, detail_item in zip(
            phase_inventory,
            detail_inventory,
        ):
            combined = (
                phase_item["fragment_count"]
                + detail_item["fragment_count"]
            )
            if combined > module.MAX_PHASE_FRAGMENTS:
                raise ContractError(
                    "combined fragment limit exceeded for phase "
                    f"{phase_item['phase']}: {combined} > "
                    f"{module.MAX_PHASE_FRAGMENTS}"
                )
        original_validate_inventory_limits(
            phase_inventory,
            detail_inventory,
            handoff_inventory,
        )

    module._chunks = compact_chunks
    module._validate_inventory_limits = validate_inventory_limits
    module._fragment_compaction_installed = True
