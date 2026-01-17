"""
Compose Success Reply Node - Generate success acknowledgment email using LLM.

Composes an acknowledgment email when POC's response has been validated as satisfactory.
"""

import logging
from typing import Any

from mail_agent.agent.state import (
    AgentState,
    get_conversation,
    get_parsed_request,
    get_request_context,
    update_conversation,
)
from mail_agent.config import get_settings
from mail_agent.llm.client import LLMClient
from mail_agent.llm.prompts import PromptTemplates, SuccessAcknowledgmentEmail


logger = logging.getLogger(__name__)


def _get_success_ack_inputs(
    state: AgentState, current_poc: str
) -> tuple[str, str, str, str]:
    conversation = get_conversation(state, current_poc)
    parsed_request = get_parsed_request(state)
    request_description, success_criteria, _expected_format = get_request_context(
        state, current_poc
    )
    if not request_description:
        request_description = parsed_request.request_description
    if not success_criteria:
        success_criteria = parsed_request.success_criteria

    original_subject = (
        conversation.sent_emails[-1].subject
        if conversation.sent_emails
        else "Information Request"
    )

    validation_feedback = "Response meets all requirements."
    if conversation.validation_results:
        validation_feedback = conversation.validation_results[-1].feedback

    return request_description, success_criteria, original_subject, validation_feedback


async def _compose_success_ack_email(
    poc_email: str,
    request_description: str,
    success_criteria: str,
    validation_feedback: str,
    original_subject: str,
) -> SuccessAcknowledgmentEmail:
    settings = get_settings()
    llm_client = LLMClient(settings)

    prompt = PromptTemplates.compose_success_acknowledgment(
        poc_email=poc_email,
        request_description=request_description,
        success_criteria=success_criteria,
        validation_feedback=validation_feedback,
        original_subject=original_subject,
    )

    success_system_prompt = PromptTemplates.SUCCESS_ACKNOWLEDGMENT_SYSTEM.format(
        agent_email=settings.agent_email
    )

    return await llm_client.generate_structured(
        prompt=prompt,
        output_schema=SuccessAcknowledgmentEmail,
        system_prompt=success_system_prompt,
    )


async def compose_success_reply(state: AgentState) -> dict[str, Any]:
    """Compose and store a success acknowledgment email for the current POC."""
    current_poc = state.get("current_poc")
    if not current_poc:
        logger.error("No current POC set for compose_success_reply")
        return {
            "error": "No current POC set",
            "current_node": "error",
            "progress_messages": ["ERROR: No current POC set for composing success reply"],
        }

    logger.info(f"Composing success acknowledgment email for POC: {current_poc}")

    try:
        conversation = get_conversation(state, current_poc)
        request_description, success_criteria, original_subject, validation_feedback = (
            _get_success_ack_inputs(state, current_poc)
        )

        logger.debug(f"Calling LLM to compose success acknowledgment for {current_poc}")
        composed = await _compose_success_ack_email(
            poc_email=current_poc,
            request_description=request_description,
            success_criteria=success_criteria,
            validation_feedback=validation_feedback,
            original_subject=original_subject,
        )

        logger.info(f"Composed success acknowledgment email: subject={composed.subject}")

        progress_msg = (
            f"Success acknowledgment composed for {current_poc}: '{composed.subject}'"
        )

        return {
            "conversations": update_conversation(state, current_poc, conversation),
            "current_node": "compose_success_reply",
            "progress_messages": [progress_msg],
            # Store composed email for send_success_reply node
            "_composed_subject": composed.subject,
            "_composed_body": composed.body,
        }

    except Exception as e:
        error_msg = f"Failed to compose success acknowledgment for {current_poc}: {e}"
        logger.error(error_msg)

        # Update conversation status on failure
        try:
            conversation = get_conversation(state, current_poc)
            conversation.error_message = error_msg
            return {
                "conversations": update_conversation(state, current_poc, conversation),
                "current_node": "error",
                "progress_messages": [f"ERROR: {error_msg}"],
            }
        except Exception:
            return {
                "error": error_msg,
                "current_node": "error",
                "progress_messages": [f"ERROR: {error_msg}"],
            }
