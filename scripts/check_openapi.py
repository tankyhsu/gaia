"""Fail when the committed OpenAPI document differs from the application contract."""

from __future__ import annotations

import json
from pathlib import Path

from export_openapi import build_schema

ROOT = Path(__file__).parents[1]


def main() -> int:
    target = ROOT / "specs" / "openapi.json"
    expected = json.dumps(build_schema(), ensure_ascii=False, indent=2) + "\n"
    if target.read_text(encoding="utf-8") == expected:
        print("OpenAPI contract is current.")
        return 0
    print("OpenAPI contract drift detected. Run: uv run python scripts/export_openapi.py")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
