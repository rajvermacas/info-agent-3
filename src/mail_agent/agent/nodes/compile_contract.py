"""
Compile Contract Node - Convert free-text request into a multi-contact contract.

Uses LLM structured output to generate per-POC request contexts and a global
success criteria used for cross-POC validation.
"""

import logging
import re
from typing import Any

from mail_agent.agent.state import AgentState, get_parsed_request
from mail_agent.config import get_settings
from mail_agent.llm.client import LLMClient
from mail_agent.llm.multi_contact import (
    MultiContactContract,
    MultiContactPrompts,
)


logger = logging.getLogger(__name__)


def _infer_delivery_recipients(user_instruction: str, emails: list[str]) -> list[str]:
    text = user_instruction.lower()
    inferred: list[str] = []
    for email in emails:
        e = email.lower()
        pattern = rf"(send|share|forward).{{0,120}}{re.escape(e)}"
        if re.search(pattern, text):
            inferred.append(email)
    return inferred


def _clamp_interval_seconds(value: int, settings) -> int:
    min_s = int(getattr(settings, "reminder_min_interval_seconds", 60))
    max_s = int(getattr(settings, "reminder_max_interval_seconds", 86400))
    return max(min_s, min(max_s, int(value)))


def _compile_effective_reminder_policy(contract: MultiContactContract, settings) -> dict[str, Any]:
    policy = contract.reminder_policy

    enabled = bool(getattr(settings, "reminder_default_enabled", True))
    if policy and policy.enabled is not None:
        enabled = bool(policy.enabled)

    interval = int(getattr(settings, "reminder_default_interval_seconds", 7200))
    if policy and policy.interval_seconds is not None:
        interval = int(policy.interval_seconds)
    interval = _clamp_interval_seconds(interval, settings)

    max_per_poc = int(getattr(settings, "reminder_max_per_poc", 3))
    if policy and policy.max_reminders_per_poc is not None:
        max_per_poc = int(policy.max_reminders_per_poc)

    first_delay = None
    if policy and policy.first_reminder_delay_seconds is not None:
        first_delay = _clamp_interval_seconds(int(policy.first_reminder_delay_seconds), settings)

    return {
        "enabled": enabled,
        "interval_seconds": interval,
        "max_reminders_per_poc": max_per_poc,
        "first_reminder_delay_seconds": first_delay,
        "source": "llm" if policy else "default",
    }


async def compile_contract(state: AgentState) -> dict[str, Any]:
    user_instruction = state.get("user_instruction", "")
    if not user_instruction:
        return {
            "error": "No user instruction provided",
            "current_node": "error",
            "progress_messages": ["ERROR: No user instruction provided"],
        }

    parsed = get_parsed_request(state)
    if not parsed.poc_emails:
        return {
            "error": "No POC emails available to compile contract",
            "current_node": "error",
            "progress_messages": ["ERROR: No POC emails available to compile contract"],
        }

    settings = get_settings()
    llm_client = LLMClient(settings)

    prompt = MultiContactPrompts.compile_contract(user_instruction, parsed.poc_emails)
    contract = await llm_client.generate_structured(
        prompt=prompt,
        output_schema=MultiContactContract,
        system_prompt=MultiContactPrompts.COMPILE_SYSTEM,
    )

    if not contract.delivery_recipients:
        contract.delivery_recipients = _infer_delivery_recipients(user_instruction, parsed.poc_emails)

    delivery_set = set(contract.delivery_recipients or [])
    if delivery_set:
        contract.poc_plans = [p for p in contract.poc_plans if p.poc_email not in delivery_set]

    poc_contexts: dict[str, dict[str, str]] = {}
    for plan in contract.poc_plans:
        poc_contexts[plan.poc_email] = {
            "request_description": plan.request_description,
            "success_criteria": plan.success_criteria,
            "expected_format": plan.expected_format,
        }

    # Prune conversations to DATA SOURCE POCs only (delivery recipients should not be emailed for data).
    data_pocs = [p.poc_email for p in contract.poc_plans]
    existing_conversations = state.get("conversations") or {}
    conversations: dict[str, dict[str, Any]] = {}
    for poc_email in data_pocs:
        if poc_email in existing_conversations:
            conversations[poc_email] = existing_conversations[poc_email]
        else:
            conversations[poc_email] = {"poc_email": poc_email, "status": "pending", "attempt_count": 0}

    plan_lines = contract.agent_plan_steps or []
    plan_preview = "\n".join(f"- {line}" for line in plan_lines[:10]) if plan_lines else "- (none)"

    reminder_policy = _compile_effective_reminder_policy(contract, settings)

    progress = (
        f"Contract compiled for {len(contract.poc_plans)} POC(s). "
        f"Assumptions: {len(contract.assumptions)}"
    )

    return {
        "contract": contract.model_dump(),
        "poc_request_contexts": poc_contexts,
        "delivery_recipients": contract.delivery_recipients,
        "conversations": conversations,
        "current_poc": data_pocs[0] if data_pocs else None,
        "reminder_policy": reminder_policy,
        "current_node": "compile_contract",
        "progress_messages": [
            progress,
            f"Execution plan:\n{plan_preview}",
            (
                "Reminders: enabled"
                if reminder_policy["enabled"]
                else "Reminders: disabled"
            )
            + f", interval={reminder_policy['interval_seconds']}s, max_per_poc={reminder_policy['max_reminders_per_poc']}",
        ],
    }
