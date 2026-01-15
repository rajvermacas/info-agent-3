"""
Global Validation Node - Validate the combined outcome across multiple POCs.

This node runs after all POCs have individually reached "success". It validates
the merged/cross-POC completeness against the original user request and the
contract's global_success_criteria. On failure, it assigns targeted follow-up
items to specific POCs to chase (up to max_attempts per POC).
"""

import logging
from typing import Any

from mail_agent.agent.state import (
    AgentState,
    ValidationResult,
    get_conversation,
    update_conversation,
)
from mail_agent.config import get_settings
from mail_agent.llm.client import LLMClient
from mail_agent.llm.multi_contact import (
    GlobalValidationOutput,
    MultiContactPrompts,
)


logger = logging.getLogger(__name__)


def _latest_extracted_payload(conv_dict: dict[str, Any]) -> str:
    emails = conv_dict.get("received_emails") or []
    if not emails:
        return ""
    last_email = emails[-1]
    return last_email.get("attachment_content") or last_email.get("body_text") or ""


async def validate_global(state: AgentState) -> dict[str, Any]:
    contract = state.get("contract") or {}
    global_success = contract.get("global_success_criteria") or ""
    user_instruction = state.get("user_instruction") or ""

    conversations = state.get("conversations") or {}
    poc_payloads = {poc: _latest_extracted_payload(conv) for poc, conv in conversations.items()}

    settings = get_settings()
    llm_client = LLMClient(settings)

    prompt = MultiContactPrompts.validate_global(
        user_instruction=user_instruction,
        global_success_criteria=global_success,
        poc_payloads=poc_payloads,
    )
    validation = await llm_client.generate_structured(
        prompt=prompt,
        output_schema=GlobalValidationOutput,
        system_prompt=MultiContactPrompts.GLOBAL_VALIDATE_SYSTEM,
    )

    if validation.is_valid:
        summary = f"SUCCESS: Global validation passed. {validation.feedback}"
        return {
            "global_valid": True,
            "global_validation": validation.model_dump(),
            "final_summary": summary,
            "current_node": "validate_global",
            "progress_messages": [summary],
        }

    updated_conversations: dict[str, dict[str, Any]] = dict(conversations)
    for poc_email, missing_items in (validation.per_poc_missing_items or {}).items():
        if not missing_items:
            continue
        if poc_email not in conversations:
            continue
        conversation = get_conversation(state, poc_email)
        conversation.status = "pending"
        conversation.validation_results.append(
            ValidationResult(
                attempt=conversation.attempt_count,
                is_valid=False,
                feedback=validation.feedback,
                missing_items=missing_items,
            )
        )
        updated_conversations[poc_email] = conversation.to_dict()

    feedback = f"Global validation failed: {validation.feedback}"
    if validation.conflicts:
        feedback += f" Conflicts: {'; '.join(validation.conflicts[:3])}"

    return {
        "conversations": updated_conversations,
        "global_valid": False,
        "global_validation": validation.model_dump(),
        "current_node": "validate_global",
        "progress_messages": [feedback],
    }

