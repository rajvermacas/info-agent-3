"""
Aggregation helpers for combining extracted POC payloads into a deliverable output.
"""

from __future__ import annotations

import json
from typing import Any


def _clean_cell(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return str(value)
    if not isinstance(value, str):
        return str(value)
    cleaned = value.strip().strip('"').strip("'").strip()
    return cleaned or None


def extract_values_from_payload(payload: str) -> list[str]:
    """
    Extract a flat list of candidate values from an extracted JSON/text payload.

    Prefers AttachmentParser JSON output: {"data":[{...}], "raw_text": "..."}.
    Falls back to parsing raw_text/lines from plain text.
    """
    payload = (payload or "").strip()
    if not payload:
        return []

    try:
        data = json.loads(payload)
    except Exception:
        return _extract_from_text(payload)

    values: list[str] = []
    if isinstance(data, dict):
        for row in data.get("data") or []:
            if isinstance(row, dict):
                for v in row.values():
                    cleaned = _clean_cell(v)
                    if cleaned:
                        values.append(cleaned)
        raw_text = data.get("raw_text")
        if isinstance(raw_text, str) and raw_text.strip():
            values.extend(_extract_from_text(raw_text))
    elif isinstance(data, list):
        for item in data:
            cleaned = _clean_cell(item)
            if cleaned:
                values.append(cleaned)

    return values


def _extract_from_text(text: str) -> list[str]:
    items: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        for part in stripped.split(","):
            cleaned = _clean_cell(part)
            if cleaned:
                items.append(cleaned)
    return items


def unique_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        key = v.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(v.strip())
    return out


def to_single_column_csv(header: str, values: list[str]) -> str:
    lines = [header]
    lines.extend(values)
    return "\n".join(lines) + "\n"

