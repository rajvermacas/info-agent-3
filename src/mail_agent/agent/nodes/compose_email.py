"""
Compose Email Node - Generate professional email using LLM.

Composes initial request emails and follow-up correction emails.
"""

import logging
from typing import Any

from mail_agent.agent.state import (
    AgentState,
    ConversationState,
    RedirectInfo,
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

        # Check if this is a cross-POC follow-up (from prepare_targeted_followup)
        conv_dict = state.get("conversations", {}).get(current_poc, {})
        cross_poc_followup_context = conv_dict.get("_cross_poc_followup_context")

        # Determine if this is initial or follow-up email
        is_followup = conversation.attempt_count > 0
        is_cross_poc_followup = cross_poc_followup_context is not None and cross_poc_followup_context.get("is_cross_poc_followup", False)

        if is_cross_poc_followup:
            # Compose cross-POC follow-up email
            logger.info(f"Composing CROSS-POC follow-up email for {current_poc}")

            original_subject = (
                conversation.sent_emails[-1].subject
                if conversation.sent_emails
                else "Request"
            )

            prompt = PromptTemplates.compose_cross_poc_followup(
                poc_email=current_poc,
                request_description=parsed_request.request_description,
                cross_poc_issues=cross_poc_followup_context.get("issues", []),
                missing_items=cross_poc_followup_context.get("missing_items", []),
                related_pocs=cross_poc_followup_context.get("related_pocs", []),
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

            logger.info(f"Composed cross-POC follow-up email: subject={composed.subject}")

        elif is_followup:
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

                prompt = PromptTemplates.compose_email_for_redirect(
                    poc_email=current_poc,
                    request_description=parsed_request.request_description,
                    expected_format=parsed_request.expected_format,
                    success_criteria=parsed_request.success_criteria,
                    referrer_email=conversation.redirected_from.original_poc,
                    redirect_reason=conversation.redirected_from.redirect_reason,
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

        # Build progress message based on email type
        if is_cross_poc_followup:
            email_type = "Cross-POC follow-up"
        elif is_followup:
            email_type = "Follow-up"
        else:
            email_type = "Initial"

        progress_msg = (
            f"{email_type} email composed for {current_poc}: "
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
