"""
Reminder Scheduler - Sends periodic reminder emails for suspended tasks.

This module is intentionally independent from LangGraph execution. It operates
only on persisted suspended task rows (interrupt_data) and uses Mock SMTP to
send reminder emails while tasks are waiting for POC replies.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from mail_agent.config import Settings
from mail_agent.persistence.task_store import TaskStore
from mail_agent.tools.smtp_client import SMTPClient

logger = logging.getLogger(__name__)


def _clamp_interval(value: int, settings: Settings) -> int:
    return max(settings.reminder_min_interval_seconds, min(settings.reminder_max_interval_seconds, value))


def _effective_policy(interrupt_data: dict[str, Any], settings: Settings) -> dict[str, Any]:
    policy = interrupt_data.get("reminder_policy") or {}
    enabled = bool(policy.get("enabled", settings.reminder_default_enabled))

    interval = int(policy.get("interval_seconds", settings.reminder_default_interval_seconds))
    interval = _clamp_interval(interval, settings)

    max_per_poc = int(policy.get("max_reminders_per_poc", settings.reminder_max_per_poc))
    first_delay = policy.get("first_reminder_delay_seconds")
    first_delay_s = _clamp_interval(int(first_delay), settings) if first_delay is not None else None

    return {
        "enabled": enabled,
        "interval_seconds": interval,
        "max_reminders_per_poc": max_per_poc,
        "first_reminder_delay_seconds": first_delay_s,
    }


def _parse_iso(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _should_remind(
    now: datetime,
    created_at: datetime,
    last_sent_at: datetime | None,
    policy: dict[str, Any],
) -> bool:
    if last_sent_at is not None:
        return (now - last_sent_at).total_seconds() >= float(policy["interval_seconds"])

    first_delay = policy.get("first_reminder_delay_seconds")
    delay = float(first_delay) if first_delay is not None else float(policy["interval_seconds"])
    return (now - created_at).total_seconds() >= delay


async def send_due_reminders(task_store: TaskStore, settings: Settings) -> int:
    """
    Send due reminder emails for suspended tasks waiting for replies.

    Reads suspended task interrupt_data to determine reminder policy, targets,
    and state. Persists updated reminder counters/timestamps back to the DB.

    Returns:
        Number of reminder emails sent.
    """
    suspended = await task_store.get_all_suspended_tasks()
    if not suspended:
        return 0

    now = datetime.now(timezone.utc)
    sent_count = 0
    smtp_client = SMTPClient(settings)

    try:
        for task in suspended:
            interrupt_data = task.get("interrupt_data") or {}
            if interrupt_data.get("reason") != "waiting_for_any_reply":
                continue

            policy = _effective_policy(interrupt_data, settings)
            if not policy["enabled"]:
                continue

            targets: dict[str, Any] = interrupt_data.get("reminder_targets") or {}
            if not targets:
                continue

            state: dict[str, Any] = interrupt_data.get("reminder_state") or {"sent_counts": {}, "last_sent_at": {}}
            sent_counts: dict[str, int] = state.get("sent_counts") or {}
            last_sent_at_map: dict[str, str] = state.get("last_sent_at") or {}

            created_at = _parse_iso(task["created_at"])
            updated = False

            for poc_email, target in targets.items():
                max_per_poc = int(policy["max_reminders_per_poc"])
                if max_per_poc <= 0:
                    continue

                already_sent = int(sent_counts.get(poc_email, 0))
                if already_sent >= max_per_poc:
                    continue

                last_sent_at = last_sent_at_map.get(poc_email)
                last_sent_dt = _parse_iso(last_sent_at) if last_sent_at else None
                if not _should_remind(now, created_at, last_sent_dt, policy):
                    continue

                to_addresses = target.get("to_addresses") or [poc_email]
                subject = str(target.get("subject") or "Reminder: Information Request")
                body_text = str(target.get("body_text") or "Reminder: please reply with the requested information.")

                await smtp_client.send_email(
                    to_addresses=list(to_addresses),
                    subject=subject,
                    body_text=body_text,
                )

                sent_counts[poc_email] = already_sent + 1
                last_sent_at_map[poc_email] = now.isoformat()
                updated = True
                sent_count += 1

            if updated:
                state["sent_counts"] = sent_counts
                state["last_sent_at"] = last_sent_at_map
                interrupt_data["reminder_state"] = state
                await task_store.update_interrupt_data(task["task_id"], interrupt_data)

    finally:
        await smtp_client.close()

    return sent_count

