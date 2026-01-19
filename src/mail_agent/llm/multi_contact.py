"""
Multi-contact contract and validation schemas + prompts.

This module keeps multi-contact structured output models separate from the
single-POC prompts in prompts.py to keep files manageable.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class ReminderPolicy(BaseModel):
    """Reminder policy parsed from user request (optional) and/or defaults."""

    enabled: Optional[bool] = Field(
        default=None,
        description="Whether reminders should be sent while waiting for replies",
    )
    interval_seconds: Optional[int] = Field(
        default=None,
        description="Reminder interval in seconds (e.g., 7200 for 2 hours)",
    )
    max_reminders_per_poc: Optional[int] = Field(
        default=None,
        description="Maximum reminders per POC before escalation",
    )
    first_reminder_delay_seconds: Optional[int] = Field(
        default=None,
        description="Optional delay before the first reminder is sent (seconds)",
    )


class PocPlan(BaseModel):
    """Per-POC plan inferred from the user prompt."""

    poc_email: str = Field(description="POC email address")
    request_description: str = Field(
        description="What to ask this POC for (subset of the overall request)"
    )
    expected_format: str = Field(
        description="Expected response format: excel, csv, or text"
    )
    success_criteria: str = Field(
        description="Concrete success criteria for this POC's response"
    )
    notes: Optional[str] = Field(
        default=None,
        description="Optional extra context for how to interpret or merge this POC's data",
    )


class MultiContactContract(BaseModel):
    """Contract compiled from the user's free-text request."""

    poc_plans: list[PocPlan] = Field(
        description="Plans for data-providing POCs (do not include delivery recipients)"
    )
    delivery_recipients: list[str] = Field(
        default_factory=list,
        description=(
            "Email addresses that should receive the final combined result (do not request data from them)"
        ),
    )
    delivery_description: Optional[str] = Field(
        default=None,
        description=(
            "What to deliver to delivery_recipients (format/content), e.g. 'send merged CSV with 5 unique animal names'"
        ),
    )
    global_success_criteria: str = Field(
        description="Success criteria for the final merged/validated result"
    )
    agent_plan_steps: list[str] = Field(
        default_factory=list,
        description="Human-readable step-by-step plan for UI display",
    )
    assumptions: list[str] = Field(
        default_factory=list,
        description="Inferred assumptions made from ambiguous user wording",
    )
    reminder_policy: Optional[ReminderPolicy] = Field(
        default=None,
        description=(
            "Optional reminder policy extracted from the user request, e.g. "
            "'remind every 2 hours' or 'wait 2 minutes then remind every 2 minutes'"
        ),
    )


class GlobalValidationOutput(BaseModel):
    """Global validation output across all POCs."""

    is_valid: bool = Field(description="Whether the combined result satisfies the request")
    feedback: str = Field(description="Short explanation of pass/fail and why")
    per_poc_missing_items: dict[str, list[str]] = Field(
        default_factory=dict,
        description=(
            "Mapping from POC email to missing/correction items that POC should address"
        ),
    )
    conflicts: list[str] = Field(
        default_factory=list,
        description=(
            "Human-readable list of conflicts between POCs (used to trigger conflict emails)"
        ),
    )


class MultiContactPrompts:
    """Prompt templates for multi-contact contract compilation and global validation."""

    COMPILE_SYSTEM = """You are an intelligent mail agent planner.
Convert the user's free-text request into a deterministic execution plan across contacts.

Rules:
- Use ONLY the email addresses present in the user's request.
- Identify whether an email address is a DATA SOURCE (we must ask them for data) or a DELIVERY RECIPIENT (they should receive the final combined result).
- Never request data from delivery recipients. Delivery recipients are usually referenced with phrases like "send it to X", "once done send to X", or "forward the final result to X".
- If a later email depends on information returned by an earlier email, reflect that dependency clearly in agent_plan_steps (e.g., "Wait for Raj's reply, extract the two city names, then email Neha using those exact city names").
- When encoding dependent values inside request_description/success_criteria, use ONLY these placeholders (never bracketed): CITY_1, CITY_2 (or "city 1", "city 2"). Do NOT use placeholders like [City 1], [City 2].
- If the user provides an "Expected execution plan", follow it closely unless it contradicts the request.
- If the request is ambiguous, make reasonable assumptions and list them explicitly.
- Produce concrete, testable success criteria (counts, required columns, constraints).
- Partition the request across contacts when it improves completeness/verification.
- Keep the plan minimal and actionable for email communication.
- If the user mentions timing instructions for reminders (e.g., "remind every 2 hours", "wait 2 minutes then resend"),
  extract them into reminder_policy. If no reminder instructions are present, set reminder_policy to null.
Return ONLY valid JSON per the requested schema."""

    GLOBAL_VALIDATE_SYSTEM = """You are a strict validation assistant.
Decide whether the combined data from multiple contacts satisfies the user's request.

Rules:
- Be strict: if a constraint isn't met (counts, required fields, structure), mark invalid.
- Be flexible on CSV representation: header variants, order, quoting, currency symbols.
- If there are conflicts between contacts, list them and identify which POCs must be re-emailed.
- Output per-POC missing/correction items so the agent can chase autonomously.
Return ONLY valid JSON per the requested schema."""

    @staticmethod
    def compile_contract(user_instruction: str, poc_emails: list[str]) -> str:
        return f"""User request:
"{user_instruction}"

Email addresses found:
{poc_emails}

Task:
1) Identify which emails are data sources vs delivery recipients.
2) Create one plan per DATA SOURCE email (poc_plans).
3) Each plan must specify request_description, expected_format (excel/csv/text), and success_criteria.
4) Provide global_success_criteria for the final merged outcome.
5) Provide delivery_recipients and delivery_description (what to send them).
6) Provide agent_plan_steps as an ordered checklist the UI can display.
7) If you infer assumptions (e.g., uniqueness, disjointness), list them.
"""

    @staticmethod
    def validate_global(
        user_instruction: str,
        global_success_criteria: str,
        poc_payloads: dict[str, str],
    ) -> str:
        return f"""User request:
"{user_instruction}"

Global success criteria:
{global_success_criteria}

POC responses (each is extracted JSON/text from the POC's latest reply):
{poc_payloads}

Validate whether the combined responses satisfy the user request.
If not valid, produce per_poc_missing_items mapping with targeted corrections."""
