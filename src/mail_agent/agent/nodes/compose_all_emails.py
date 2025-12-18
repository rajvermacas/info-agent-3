"""
Compose All Emails Node - Generate emails for all POCs in parallel.

Used in parallel processing mode to compose emails for all POCs
at once using concurrent LLM calls.
"""

import asyncio
import logging
from typing import Any

from mail_agent.agent.state import (
    AgentState,
    ConversationState,
    get_conversation,
    get_parsed_request,
    get_pending_pocs,
)
from mail_agent.config import get_settings
from mail_agent.llm.client import LLMClient
from mail_agent.llm.prompts import ComposedEmail, FollowUpEmail, PromptTemplates


logger = logging.getLogger(__name__)


async def compose_all_emails(state: AgentState) -> dict[str, Any]:
    """
    Compose emails for ALL POCs in parallel.

    Uses asyncio.gather for concurrent LLM calls to compose emails
    for all pending POCs simultaneously.

    Args:
        state: Current agent state with parsed_request and conversations.

    Returns:
        State update with all composed emails in _composed_emails list.
    """
    logger.info("Starting parallel email composition for all POCs")

    try:
        parsed_request = get_parsed_request(state)

        # Get POCs that need emails composed
        # If this is a retry (followup), check _followup_pocs
        followup_pocs = state.get("_followup_pocs")
        if followup_pocs:
            poc_emails = followup_pocs
            logger.info(f"Composing follow-up emails for {len(poc_emails)} POCs")
        else:
            # Initial send - get all pending POCs
            poc_emails = get_pending_pocs(state)
            if not poc_emails:
                # Fall back to all POC emails from parsed request
                poc_emails = parsed_request.poc_emails
            logger.info(f"Composing initial emails for {len(poc_emails)} POCs")

        if not poc_emails:
            logger.warning("No POCs to compose emails for")
            return {
                "error": "No POCs to compose emails for",
                "current_node": "error",
                "progress_messages": ["ERROR: No POCs found to send emails to"],
            }

        settings = get_settings()
        llm_client = LLMClient(settings)

        # Compose all emails concurrently
        async def compose_for_poc(poc_email: str) -> dict[str, Any]:
            """Compose email for a single POC."""
            try:
                conversation = get_conversation(state, poc_email)
                is_followup = conversation.attempt_count > 0

                if is_followup:
                    # Get last validation result
                    if not conversation.validation_results:
                        raise ValueError(f"No validation results for follow-up to {poc_email}")

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

                    followup_system_prompt = PromptTemplates.FOLLOWUP_SYSTEM.format(
                        agent_email=settings.agent_email
                    )

                    composed = await llm_client.generate_structured(
                        prompt=prompt,
                        output_schema=FollowUpEmail,
                        system_prompt=followup_system_prompt,
                    )

                    logger.info(
                        f"Composed follow-up email for {poc_email}: "
                        f"subject={composed.subject}"
                    )

                else:
                    # Initial email
                    prompt = PromptTemplates.compose_email(
                        poc_email=poc_email,
                        request_description=parsed_request.request_description,
                        expected_format=parsed_request.expected_format,
                        success_criteria=parsed_request.success_criteria,
                    )

                    compose_system_prompt = PromptTemplates.COMPOSE_SYSTEM.format(
                        agent_email=settings.agent_email
                    )

                    composed = await llm_client.generate_structured(
                        prompt=prompt,
                        output_schema=ComposedEmail,
                        system_prompt=compose_system_prompt,
                    )

                    logger.info(
                        f"Composed initial email for {poc_email}: "
                        f"subject={composed.subject}"
                    )

                return {
                    "poc_email": poc_email,
                    "subject": composed.subject,
                    "body": composed.body,
                    "success": True,
                    "error": None,
                }

            except Exception as e:
                error_msg = f"Failed to compose email for {poc_email}: {e}"
                logger.error(error_msg)
                return {
                    "poc_email": poc_email,
                    "subject": None,
                    "body": None,
                    "success": False,
                    "error": error_msg,
                }

        # Run all compositions concurrently
        logger.info(f"Composing emails for {len(poc_emails)} POCs concurrently")
        compose_results = await asyncio.gather(
            *[compose_for_poc(poc) for poc in poc_emails]
        )

        # Process results
        composed_emails = []
        failed_pocs = []
        conversations = dict(state.get("conversations", {}))

        for result in compose_results:
            poc_email = result["poc_email"]

            if result["success"]:
                composed_emails.append({
                    "poc_email": poc_email,
                    "subject": result["subject"],
                    "body": result["body"],
                })

                # Update conversation status to "composing"
                if poc_email in conversations:
                    conv = ConversationState.from_dict(conversations[poc_email])
                    conv.status = "composing"
                    conversations[poc_email] = conv.to_dict()
            else:
                failed_pocs.append(poc_email)
                logger.error(f"Failed to compose for {poc_email}: {result['error']}")

                # Mark conversation as failed
                if poc_email in conversations:
                    conv = ConversationState.from_dict(conversations[poc_email])
                    conv.status = "failed"
                    conv.error_message = result["error"]
                    conversations[poc_email] = conv.to_dict()

        # Check if we have at least some composed emails
        if not composed_emails:
            error_msg = f"All {len(poc_emails)} email compositions failed"
            logger.error(error_msg)
            return {
                "error": error_msg,
                "current_node": "error",
                "progress_messages": [f"ERROR: {error_msg}"],
                "conversations": conversations,
            }

        # Build progress message
        if failed_pocs:
            progress_msg = (
                f"Composed {len(composed_emails)} emails "
                f"({len(failed_pocs)} failed: {', '.join(failed_pocs)})"
            )
        else:
            progress_msg = f"Composed emails for all {len(composed_emails)} POCs"

        logger.info(progress_msg)

        return {
            "conversations": conversations,
            "current_node": "compose_all_emails",
            "progress_messages": [progress_msg],
            "_composed_emails": composed_emails,
            "_parallel_mode": True,
        }

    except Exception as e:
        error_msg = f"Failed to compose all emails: {e}"
        logger.exception(error_msg)
        return {
            "error": error_msg,
            "current_node": "error",
            "progress_messages": [f"ERROR: {error_msg}"],
        }
