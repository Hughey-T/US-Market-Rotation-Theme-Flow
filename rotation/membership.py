"""Point-in-time theme membership predicates shared by acquisition and analysis."""
from __future__ import annotations

import datetime as dt


def member_is_effective(member: dict, data_date: str | dt.date) -> bool:
    """Return whether a member belongs to the theme on ``data_date``."""
    date = dt.date.fromisoformat(data_date) if isinstance(data_date, str) else data_date
    if not member.get("active", False):
        return False
    valid_from = dt.date.fromisoformat(member["valid_from"])
    valid_to_raw = member.get("valid_to")
    valid_to = dt.date.fromisoformat(valid_to_raw) if valid_to_raw is not None else None
    if valid_to is not None and valid_from > valid_to:
        raise ValueError(f"membership valid_from {valid_from} is after valid_to {valid_to}")
    return valid_from <= date and (valid_to is None or date <= valid_to)
