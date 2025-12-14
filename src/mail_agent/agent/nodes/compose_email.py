"""
Compose Email Node - Generate professional email using LLM.

Composes initial request emails and follow-up correction emails.
"""

import logging
from typing import Any

from mail_agent.agent.state import (
    AgentState,
    ConversationState,
    get_conversation,
    get_parsed_request,
    update_conversation,
)
from mail_agent.config import get_settings
from mail_agent.llm.client import LLMClient
from mail_agent.llm.prompts import ComposedEmail, FollowUpEmail, PromptTemplates


logger = logging.getLogger(__name__)


async def compose_email(state: AgentState) -> dict[str, Any]:
    """
    Compose email for current POC.

    If this is the first attempt, composes initial request email.
    If follow-up, composes correction request email based on validation feedback.

    Args:
        state: Current agent state with parsed_request and current_poc.

    Returns:
        State update with composed email stored in conversation.
    """
    current_poc = state.get("current_poc")
    if not current_poc:
        logger.error("No current POC set for compose_email")
        return {
            "error": "No current POC set",
            "current_node": "error",
            "progress_messages": ["ERROR: No current POC set for composing email"],
        }

    logger.info(f"Composing email for POC: {current_poc}")

    try:
        # Get conversation state
        conversation = get_conversation(state, current_poc)
        parsed_request = get_parsed_request(state)

        # Update status
        conversation.status = "composing"

        settings = get_settings()
        llm_client = LLMClient(settings)

        # Determine if this is initial or follow-up email
        is_followup = conversation.attempt_count > 0

        if is_followup:
            # Compose follow-up email
            logger.info(f"Composing follow-up email (attempt {conversation.attempt_count + 1})")

            # Get last validation result
            if not conversation.validation_results:
                raise ValueError("No validation results for follow-up")

            last_validation = conversation.validation_results[-1]
            original_subject = (
                conversation.sent_emails[-1].subject
                if conversation.sent_emails
                else "Request"
            )

            prompt = PromptTemplates.compose_followup(
                request_description=parsed_request.request_description,
                validation_feedback=last_validation.feedback,
                missing_items=last_validation.missing_items,
                attempt_count=conversation.attempt_count + 1,
                max_attempts=settings.max_attempts,
                original_subject=original_subject,
            )

            composed = await llm_client.generate_structured(
                prompt=prompt,
                output_schema=FollowUpEmail,
                system_prompt=PromptTemplates.FOLLOWUP_SYSTEM,
            )

            logger.info(f"Composed follow-up email: subject={composed.subject}")

        else:
            # Compose initial email
            logger.info("Composing initial request email")

            prompt = PromptTemplates.compose_email(
                poc_email=current_poc,
                request_description=parsed_request.request_description,
                expected_format=parsed_request.expected_format,
                success_criteria=parsed_request.success_criteria,
            )

            composed = await llm_client.generate_structured(
                prompt=prompt,
                output_schema=ComposedEmail,
                system_prompt=PromptTemplates.COMPOSE_SYSTEM,
            )

            logger.info(f"Composed initial email: subject={composed.subject}")

        # Store composed email temporarily in state for send_email node
        # The actual SentEmail record will be created after successful send
        conversation.status = "sending"

        progress_msg = (
            f"{'Follow-up' if is_followup else 'Initial'} email composed for {current_poc}: "
            f"'{composed.subject}'"
        )

        return {
            "conversations": update_conversation(state, current_poc, conversation),
            "current_node": "compose_email",
            "progress_messages": [progress_msg],
            # Store composed email for send_email node
            "_composed_subject": composed.subject,
            "_composed_body": composed.body,
        }

    except Exception as e:
        error_msg = f"Failed to compose email for {current_poc}: {e}"
        logger.error(error_msg)

        # Update conversation status
        try:
            conversation = get_conversation(state, current_poc)
            conversation.status = "failed"
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
