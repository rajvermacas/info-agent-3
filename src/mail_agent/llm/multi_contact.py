"""
Multi-contact contract and validation schemas + prompts.

This module keeps multi-contact structured output models separate from the
single-POC prompts in prompts.py to keep files manageable.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


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
        description="Plans for each POC (one per email address)"
    )
    global_success_criteria: str = Field(
        description="Success criteria for the final merged/validated result"
    )
    assumptions: list[str] = Field(
        default_factory=list,
        description="Inferred assumptions made from ambiguous user wording",
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
- If the request is ambiguous, make reasonable assumptions and list them explicitly.
- Produce concrete, testable success criteria (counts, required columns, constraints).
- Partition the request across contacts when it improves completeness/verification.
- Keep the plan minimal and actionable for email communication.
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
1) Create one plan per POC email (poc_plans).
2) Each plan must specify request_description, expected_format (excel/csv/text), and success_criteria.
3) Provide global_success_criteria for the final merged outcome.
4) If you infer assumptions (e.g., uniqueness), list them.
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

