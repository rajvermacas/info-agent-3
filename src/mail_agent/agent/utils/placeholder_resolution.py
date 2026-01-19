"""
Placeholder resolution for dependent multi-contact requests.

Some user requests have an explicit dependency chain, e.g.:
1) Ask POC A for two city names.
2) After receiving those names, ask POC B about local foods in those cities.

The LLM contract often encodes the dependency using placeholders like
"city 1 and city 2". This module replaces those placeholders using the latest
successful response from other POCs.
"""

from __future__ import annotations

import re
from typing import Iterable, Optional

from mail_agent.agent.state import AgentState, ConversationState


_CITY_1_RE = re.compile(r"\bcity\s*(?:#\s*)?1\b|\bcity\s*one\b", re.IGNORECASE)
_CITY_2_RE = re.compile(r"\bcity\s*(?:#\s*)?2\b|\bcity\s*two\b", re.IGNORECASE)
_CITY_1_BRACKET_RE = re.compile(r"\[\s*city\s*(?:#\s*)?1\s*\]", re.IGNORECASE)
_CITY_2_BRACKET_RE = re.compile(r"\[\s*city\s*(?:#\s*)?2\s*\]", re.IGNORECASE)
_CITY_1_TOKEN_RE = re.compile(r"\bCITY_1\b|\{\{\s*city_1\s*\}\}", re.IGNORECASE)
_CITY_2_TOKEN_RE = re.compile(r"\bCITY_2\b|\{\{\s*city_2\s*\}\}", re.IGNORECASE)
_CITY_PAIR_RE = re.compile(
    r"\bcity\s*(?:#\s*)?1\s*(?:and|&)\s*city\s*(?:#\s*)?2\b", re.IGNORECASE
)
_THOSE_CITIES_RE = re.compile(r"\b(those|these)\s+cities\b", re.IGNORECASE)


def _normalize_item(item: str) -> str:
    cleaned = item.strip().strip(" .;")
    if not cleaned:
        return ""
    if cleaned.lower() == cleaned:
        return cleaned.title()
    return cleaned


def _split_inline_list(text: str) -> list[str]:
    cleaned = text.strip()
    cleaned = re.sub(r"^(cities|city names|city)\s*:\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.replace(";", ",")
    cleaned = re.sub(r"\s+(and|&)\s+", ", ", cleaned, flags=re.IGNORECASE)
    parts = [p.strip() for p in cleaned.split(",") if p.strip()]
    return [_normalize_item(p) for p in parts if _normalize_item(p)]


def extract_list_items(text: str) -> list[str]:
    """
    Extract an ordered list of items from a short free-text reply.

    Handles common reply formats:
    - "Mumbai, Delhi"
    - "Mumbai and Delhi"
    - "1) Mumbai\\n2) Delhi"
    - "- Mumbai\\n- Delhi"
    """
    if not text:
        return []

    lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith(">")]
    bullet_items: list[str] = []
    for line in lines:
        m = re.match(r"^(?:[-*•]|\\d+[.)])\\s*(.+)$", line)
        if m:
            normalized = _normalize_item(m.group(1))
            if normalized:
                bullet_items.append(normalized)

    if bullet_items:
        return bullet_items

    return _split_inline_list(" ".join(lines))


def _latest_success_texts(state: AgentState, exclude_poc: str | None) -> Iterable[tuple[str, str]]:
    conversations = state.get("conversations") or {}
    for poc_email, conv_dict in conversations.items():
        if exclude_poc and poc_email == exclude_poc:
            continue
        if conv_dict.get("status") != "success":
            continue
        conv = ConversationState.from_dict(conv_dict)
        if not conv.received_emails:
            continue
        latest = conv.received_emails[-1]
        text = latest.attachment_content or latest.body_text or ""
        if text.strip():
            yield poc_email, text


def _pick_items_from_successes(
    state: AgentState, exclude_poc: str | None, min_count: int
) -> Optional[list[str]]:
    best: Optional[list[str]] = None
    for _poc_email, text in _latest_success_texts(state, exclude_poc):
        items = extract_list_items(text)
        if len(items) < min_count:
            continue
        if best is None:
            best = items
            continue
        if len(items) == min_count and len(best) != min_count:
            best = items
            continue
        if len(items) > len(best):
            best = items
    return best


def needs_city_pair_placeholders(text: str) -> bool:
    if not text:
        return False
    return bool(
        _CITY_1_RE.search(text)
        or _CITY_2_RE.search(text)
        or _CITY_1_BRACKET_RE.search(text)
        or _CITY_2_BRACKET_RE.search(text)
        or _CITY_1_TOKEN_RE.search(text)
        or _CITY_2_TOKEN_RE.search(text)
        or _THOSE_CITIES_RE.search(text)
    )


def can_resolve_city_pair(state: AgentState, exclude_poc: str | None = None) -> bool:
    items = _pick_items_from_successes(state, exclude_poc=exclude_poc, min_count=2)
    return bool(items and len(items) >= 2)


def resolve_city_placeholders(
    state: AgentState,
    current_poc: str,
    request_description: str,
    success_criteria: str,
) -> tuple[str, str, Optional[list[str]]]:
    """
    Replace "city 1/city 2/those cities" placeholders using latest successful items.
    """
    combined = f"{request_description}\n{success_criteria}".strip()
    if not needs_city_pair_placeholders(combined):
        return request_description, success_criteria, None

    items = _pick_items_from_successes(state, exclude_poc=current_poc, min_count=2)
    if not items or len(items) < 2:
        return request_description, success_criteria, None

    city_1, city_2 = items[0], items[1]
    cities_joined = f"{city_1} and {city_2}"

    def _apply(text: str) -> str:
        updated = _CITY_PAIR_RE.sub(cities_joined, text)
        updated = _CITY_1_RE.sub(city_1, updated)
        updated = _CITY_2_RE.sub(city_2, updated)
        updated = _CITY_1_BRACKET_RE.sub(city_1, updated)
        updated = _CITY_2_BRACKET_RE.sub(city_2, updated)
        updated = _CITY_1_TOKEN_RE.sub(city_1, updated)
        updated = _CITY_2_TOKEN_RE.sub(city_2, updated)
        updated = _THOSE_CITIES_RE.sub(cities_joined, updated)
        return updated

    return _apply(request_description), _apply(success_criteria), [city_1, city_2]
