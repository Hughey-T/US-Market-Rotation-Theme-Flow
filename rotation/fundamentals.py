"""Offline point-in-time fundamental source adapter.

The adapter consumes repository or fixture JSON only.  It intentionally has no
credential or network path and preserves field-level missingness.
"""
from __future__ import annotations
from pathlib import Path
from .analysis_v3 import FUNDAMENTAL_FIELDS, unavailable
from .validation import ContractError, load_json


def load_point_in_time_fundamentals(path: Path, data_date: str) -> dict:
    value = load_json(path)
    if value.get("adapter_version") != "1.0": raise ContractError("unsupported fundamental adapter version")
    if value.get("as_of") != data_date: raise ContractError("fundamentals are not point-in-time aligned")
    output={}
    for theme_id, record in sorted((value.get("themes") or {}).items()):
        output[theme_id]={name: record.get(name,unavailable(f"{path.as_posix()}#/{theme_id}/{name}")) for name in FUNDAMENTAL_FIELDS}
    return output
