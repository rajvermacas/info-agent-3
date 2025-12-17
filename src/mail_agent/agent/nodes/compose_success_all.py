"""
Compose Success All Node - Composes success acknowledgment for all POCs.

This node generates thank-you emails for all successful POCs after
cross-POC validation passes. Each POC receives a personalized acknowledgment
summarizing the data they provided and confirming the overall success.
"""

import logging
from typing import Any

from mail_agent.agent.state import (
    AgentState,
    ConversationState,
    get_parsed_request,
)
from mail_agent.config import get_settings
from mail_agent.llm.client import LLMClient
from mail_agent.llm.prompts import PromptTemplates


logger = logging.getLogger(__name__)


async def compose_success_all(state: AgentState) -> dict[str, Any]:
    """
    Compose success acknowledgment emails for all successful POCs.

    This node is called after cross-POC validation passes. It generates
    personalized thank-you emails for each POC that successfully provided data.

    The composed emails are stored in state for send_success_all to dispatch.

    Args:
        state: Current agent state with validated POC data.

    Returns:
        State update with:
        - _success_emails: List of {poc_email, subject, body} for sending
        - current_node: "compose_success_all"
        - progress_messages: Composition status
    """
    logger.info("Composing success acknowledgment for all POCs")

    # Get all conversations
    conversations = state.get("conversations", {})

    # Identify successful POCs
    successful_pocs = []
    for poc_email, conv_dict in conversations.items():
        status = conv_dict.get("status", "unknown")
        if status == "success":
            successful_pocs.append(poc_email)

    logger.info(f"Composing success emails for {len(successful_pocs)} POC(s)")

    if not successful_pocs:
        logger.warning("No successful POCs to acknowledge")
        return {
            "_success_emails": [],
            "current_node": "compose_success_all",
            "progress_messages": ["No successful POCs to acknowledge."],
        }

    # Get parsed request for context
    try:
        parsed_request = get_parsed_request(state)
        request_description = parsed_request.request_description
    except ValueError:
        logger.warning("No parsed request found - using instruction")
        request_description = state.get("user_instruction", "your request")

    # Compose emails for each successful POC
    success_emails = []
    settings = get_settings()
    llm_client = LLMClient(settings)

    for poc_email in successful_pocs:
        conv_dict = conversations[poc_email]

        # Get the data they provided (for personalization)
        received_emails = conv_dict.get("received_emails", [])
        provided_data_summary = ""
        if received_emails:
            last_email = received_emails[-1]
            if last_email.get("has_attachment"):
                filename = last_email.get("attachment_filename", "attachment")
                provided_data_summary = f"the {filename} you sent"
            else:
                provided_data_summary = "the information you provided"

        try:
            # Generate personalized thank-you email
            prompt = PromptTemplates.compose_multi_poc_success_acknowledgment(
                poc_email=poc_email,
                request_description=request_description,
                provided_data_summary=provided_data_summary,
                total_pocs=len(successful_pocs),
            )

            response = await llm_client.generate_structured(
                prompt=prompt,
                output_schema=SuccessEmailResponse,
            )

            success_emails.append({
                "poc_email": poc_email,
                "subject": response.subject,
                "body": response.body,
            })

            logger.debug(f"Composed success email for {poc_email}")

        except Exception as e:
            logger.exception(f"Failed to compose success email for {poc_email}: {e}")
            # Use fallback template
            success_emails.append({
                "poc_email": poc_email,
                "subject": f"Re: {request_description[:50]}... - Thank You",
                "body": (
                    f"Dear {poc_email},\n\n"
                    f"Thank you for providing {provided_data_summary}. "
                    "We have successfully received and validated all the information.\n\n"
                    "Best regards,\n"
                    "Info Agent"
                ),
            })

    logger.info(f"Composed {len(success_emails)} success acknowledgment email(s)")

    return {
        "_success_emails": success_emails,
        "current_node": "compose_success_all",
        "progress_messages": [
            f"Composed success acknowledgment for {len(success_emails)} POC(s)"
        ],
    }


# ============================================================================
# Response Schema for LLM
# ============================================================================

from pydantic import BaseModel, Field


class SuccessEmailResponse(BaseModel):
    """Response schema for success acknowledgment email."""

    subject: str = Field(
        description="Email subject line"
    )
    body: str = Field(
        description="Email body text (plain text, professional tone)"
    )
