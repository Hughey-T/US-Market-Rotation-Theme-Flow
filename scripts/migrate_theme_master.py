#!/usr/bin/env python3
"""Explicitly migrate the provisional object-map theme file to master 1.0."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def migrate(value: dict, effective_date: str) -> dict:
    themes = []
    for theme_id, theme in sorted(value["themes"].items()):
        members = []
        for ticker, role in sorted(theme["members"].items()):
            members.append({
                "ticker": ticker, "role": role, "active": True, "valid_from": effective_date, "valid_to": None,
                "rationale": f"Legacy provisional master assigned {ticker} the {role} role; role denotes theme centrality only.",
            })
        themes.append({
            "theme_id": theme_id, "label": theme["label"],
            "definition": f"{theme['label']}に直接または周辺的に関連する企業群。roleは企業品質・投資魅力度を表さない。",
            "reference_etfs": theme.get("reference_etfs", []), "members": members,
        })
    return {
        "theme_master_schema_version": "1.0", "theme_master_version": "2026-Q3-r1", "effective_date": effective_date,
        "review_cycle": "quarterly", "overlap_policy": "allow_with_warning", "themes": themes,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--effective-date", required=True)
    args = parser.parse_args()
    source = json.loads(args.input.read_text(encoding="utf-8"))
    result = migrate(source, args.effective_date)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
