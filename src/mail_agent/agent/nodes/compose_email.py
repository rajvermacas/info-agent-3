"""
Compose Email Node - Generate professional email using LLM.

Composes initial request emails and follow-up correction emails.
"""

import logging
from typing import Any

import re

from mail_agent.agent.state import (
    AgentState,
    ConversationState,
    RedirectInfo,
    get_conversation,
    get_parsed_request,
    get_received_items_summary,
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

            # Format system prompt with agent email identity
            followup_system_prompt = PromptTemplates.FOLLOWUP_SYSTEM.format(
                agent_email=settings.agent_email
            )

            composed = await llm_client.generate_structured(
                prompt=prompt,
                output_schema=FollowUpEmail,
                system_prompt=followup_system_prompt,
            )

            logger.info(f"Composed follow-up email: subject={composed.subject}")

        else:
            # Check if this is a redirect (new conversation created from a redirect)
            is_redirect_email = conversation.redirected_from is not None

            if is_redirect_email:
                # Compose redirect email - mentioning the referrer
                logger.info(
                    f"Composing redirect email for {current_poc} "
                    f"(redirected from {conversation.redirected_from.original_poc})"
                )

                # Get summary of what was already received from previous contacts
                received_summary = get_received_items_summary(state, current_poc)
                items_received = received_summary["total_items_received"]

                # Try to parse the original number requested from success criteria
                # Look for patterns like "10 recipes", "10 rows", "10 items", etc.
                original_total = None
                remaining_needed = None
                criteria_match = re.search(
                    r'(\d+)\s*(?:rows?|items?|recipes?|entries?|records?)',
                    parsed_request.success_criteria,
                    re.IGNORECASE
                )
                if criteria_match:
                    original_total = int(criteria_match.group(1))
                    remaining_needed = max(0, original_total - items_received)
                    logger.info(
                        f"Original request: {original_total} items, "
                        f"already received: {items_received}, "
                        f"remaining needed: {remaining_needed}"
                    )

                prompt = PromptTemplates.compose_email_for_redirect(
                    poc_email=current_poc,
                    request_description=parsed_request.request_description,
                    expected_format=parsed_request.expected_format,
                    success_criteria=parsed_request.success_criteria,
                    referrer_email=conversation.redirected_from.original_poc,
                    redirect_reason=conversation.redirected_from.redirect_reason,
                    already_received_summary=received_summary["items_summary"] if items_received > 0 else None,
                    remaining_items_needed=remaining_needed,
                )
            else:
                # Compose initial email (no redirect)
                logger.info("Composing initial request email")

                prompt = PromptTemplates.compose_email(
                    poc_email=current_poc,
                    request_description=parsed_request.request_description,
                    expected_format=parsed_request.expected_format,
                    success_criteria=parsed_request.success_criteria,
                )

            # Format system prompt with agent email identity
            compose_system_prompt = PromptTemplates.COMPOSE_SYSTEM.format(
                agent_email=settings.agent_email
            )

            composed = await llm_client.generate_structured(
                prompt=prompt,
                output_schema=ComposedEmail,
                system_prompt=compose_system_prompt,
            )

            email_type = "redirect" if is_redirect_email else "initial"
            logger.info(f"Composed {email_type} email: subject={composed.subject}")

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
