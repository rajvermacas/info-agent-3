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
    update_conversation,
)
from mail_agent.config import get_settings
from mail_agent.llm.client import LLMClient
from mail_agent.llm.prompts import PromptTemplates, SuccessAcknowledgmentEmail


logger = logging.getLogger(__name__)


async def compose_success_reply(state: AgentState) -> dict[str, Any]:
    """
    Compose success acknowledgment email for current POC.

    This node is called after validation succeeds. It composes a thank-you email
    that summarizes what was received and confirms the success criteria were met.

    Args:
        state: Current agent state with validated conversation.

    Returns:
        State update with composed email stored for send_success_reply node.
    """
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
        # Get conversation state
        conversation = get_conversation(state, current_poc)
        parsed_request = get_parsed_request(state)

        settings = get_settings()
        llm_client = LLMClient(settings)

        # Get original subject from last sent email
        original_subject = (
            conversation.sent_emails[-1].subject
            if conversation.sent_emails
            else "Information Request"
        )

        # Get validation feedback from last validation result
        validation_feedback = ""
        if conversation.validation_results:
            last_validation = conversation.validation_results[-1]
            validation_feedback = last_validation.feedback
        else:
            logger.warning(
                f"No validation results found for {current_poc}, using default feedback"
            )
            validation_feedback = "Response meets all requirements."

        # Compose success acknowledgment prompt
        prompt = PromptTemplates.compose_success_acknowledgment(
            poc_email=current_poc,
            request_description=parsed_request.request_description,
            success_criteria=parsed_request.success_criteria,
            validation_feedback=validation_feedback,
            original_subject=original_subject,
        )

        # Format system prompt with agent email identity
        success_system_prompt = PromptTemplates.SUCCESS_ACKNOWLEDGMENT_SYSTEM.format(
            agent_email=settings.agent_email
        )

        logger.debug(f"Calling LLM to compose success acknowledgment for {current_poc}")

        composed = await llm_client.generate_structured(
            prompt=prompt,
            output_schema=SuccessAcknowledgmentEmail,
            system_prompt=success_system_prompt,
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
