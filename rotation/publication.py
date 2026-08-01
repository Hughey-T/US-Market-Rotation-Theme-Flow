"""Publication API with read compatibility for pre-v3 immutable histories."""

from __future__ import annotations

from . import publication_core as _core

_LEGACY_THEME_HISTORY_FIELDS = frozenset(
    {
        "equal_weight_rel_spy_4w",
        "advance_count_4w",
        "above_50dma_count",
        "pct_above_50dma",
        "volume_ratio_20d_60d",
    }
)
_ORIGINAL_EXPECTED_HISTORY = _core._expected_history


def _expected_history(snapshot: dict) -> dict:
    """Rebuild history using the contract active when the snapshot was created."""
    expected = _ORIGINAL_EXPECTED_HISTORY(snapshot)
    if "v3_inputs" in snapshot:
        return expected

    for theme in expected["themes"].values():
        for field in tuple(theme):
            if field not in _LEGACY_THEME_HISTORY_FIELDS:
                del theme[field]
    return expected


_core._expected_history = _expected_history

for _name in dir(_core):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_core, _name)

globals()["_expected_history"] = _expected_history
