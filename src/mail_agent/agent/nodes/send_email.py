"""Send email node - sends email via SMTPClient."""

import logging
from datetime import datetime

import httpx

from mail_agent.agent.state import AgentState, SentEmail
from mail_agent.config import get_settings
from mail_agent.tools.smtp_client import SMTPClient, EmailSendError

logger = logging.getLogger(__name__)


async def send_email_node(state: AgentState) -> AgentState:
    """Send email via Mock SMTP Server REST API.

    This node:
    1. Retrieves composed email from state (_composed_email)
    2. Uses SMTPClient to send email via Mock SMTP API
    3. Records sent email in conversation state
    4. Marks conversation as "waiting" for reply
    5. Returns updated state

    Args:
        state: Current agent state with _composed_email temporary data

    Returns:
        AgentState: Updated state with sent email recorded

    Raises:
        ValueError: If _composed_email is missing
        EmailSendError: If email sending fails
    """
    logger.info("send_email_node: Starting")

    # Validate inputs
    composed_email = state.get("_composed_email")
    if not composed_email:
        error_msg = "_composed_email not found in state (compose_email node must run first)"
        logger.error(f"send_email_node: {error_msg}")
        raise ValueError(error_msg)

    parsed_request = state.get("parsed_request")
    conversations = state.get("conversations", {})

    if not parsed_request:
        error_msg = "parsed_request is required in state"
        logger.error(f"send_email_node: {error_msg}")
        raise ValueError(error_msg)

    poc_email = composed_email.get("poc_email")
    subject = composed_email.get("subject")
    body = composed_email.get("body")

    if not poc_email or not subject or not body:
        error_msg = f"Invalid _composed_email: missing required fields"
        logger.error(f"send_email_node: {error_msg}")
        raise ValueError(error_msg)

    logger.debug(f"send_email_node: Sending email to {poc_email}, subject={subject[:50]}")

    try:
        # Get settings
        settings = get_settings()
        agent_email = settings.agent_email

        if not agent_email:
            error_msg = "agent_email is required in settings"
            logger.error(f"send_email_node: {error_msg}")
            raise ValueError(error_msg)

        # Create SMTP client and send email
        async with httpx.AsyncClient(timeout=30.0) as http_client:
            smtp_client = SMTPClient(settings, http_client)
            async with smtp_client:
                response = await smtp_client.send_email(
                    from_address=agent_email,
                    to_addresses=[poc_email],
                    subject=subject,
                    body_text=body,
                    body_html=None,
                )

        # Extract email ID from response
        email_id = response.get("id")
        if not email_id:
            error_msg = "No email_id in send_email response"
            logger.error(f"send_email_node: {error_msg}")
            raise ValueError(error_msg)

        logger.info(f"send_email_node: Email sent successfully: id={email_id}, to={poc_email}")

        # Record sent email in conversation state
        sent_email_record: SentEmail = {
            "email_id": str(email_id),
            "subject": subject,
            "body": body,
            "sent_at": datetime.utcnow().isoformat(),
        }

        # Update conversation state
        conversation = conversations.get(poc_email, {})
        sent_emails = conversation.get("sent_emails", [])
        sent_emails.append(sent_email_record)

        conversation["sent_emails"] = sent_emails
        conversation["status"] = "waiting"
        conversation["attempt_count"] = conversation.get("attempt_count", 0) + 1

        conversations[poc_email] = conversation

        logger.debug(
            f"send_email_node: Updated conversation for {poc_email}: "
            f"status=waiting, attempt={conversation['attempt_count']}"
        )

        # Update state
        state["conversations"] = conversations
        state["current_node"] = "send_email"
        state["progress_messages"].append(f"Sent email to {poc_email} (attempt {conversation['attempt_count']})")

        # Clean up temporary data
        if "_composed_email" in state:
            del state["_composed_email"]

        logger.info("send_email_node: Completed successfully")

        return state

    except EmailSendError as e:
        error_msg = f"Email send error: {str(e)}"
        logger.error(f"send_email_node: {error_msg}")
        raise

    except Exception as e:
        error_msg = f"Unexpected error sending email: {str(e)}"
        logger.error(f"send_email_node: {error_msg}")
        raise
