"""
Send Email Node - Send composed email via mock SMTP REST API.

Sends the email composed by compose_email node and records the sent email.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from mail_agent.agent.state import (
    AgentState,
    ConversationState,
    SentEmail,
    get_conversation,
    update_conversation,
)
from mail_agent.config import get_settings
from mail_agent.tools.smtp_client import SMTPClient


logger = logging.getLogger(__name__)


async def send_email(state: AgentState) -> dict[str, Any]:
    """
    Send composed email to current POC.

    This node:
    1. Retrieves the composed email from state
    2. Sends via mock SMTP REST API
    3. Records the sent email in conversation state

    Args:
        state: Current agent state with _composed_subject and _composed_body.

    Returns:
        State update with sent email recorded and status updated.
    """
    current_poc = state.get("current_poc")
    if not current_poc:
        logger.error("No current POC set for send_email")
        return {
            "error": "No current POC set",
            "current_node": "error",
            "progress_messages": ["ERROR: No current POC set for sending email"],
        }

    # Get composed email from state (set by compose_email node)
    subject = state.get("_composed_subject")
    body = state.get("_composed_body")

    if not subject or not body:
        logger.error("No composed email found in state")
        return {
            "error": "No composed email found",
            "current_node": "error",
            "progress_messages": ["ERROR: No composed email found to send"],
        }

    logger.info(f"Sending email to POC: {current_poc}")

    try:
        # Get conversation state
        conversation = get_conversation(state, current_poc)
        conversation.status = "sending"

        settings = get_settings()
        smtp_client = SMTPClient(settings)

        try:
            # Send email via REST API
            response = await smtp_client.send_email(
                to_addresses=[current_poc],
                subject=subject,
                body_text=body,
            )

            # Record sent email
            sent_email = SentEmail(
                email_id=response.email_id,
                subject=subject,
                body=body,
                sent_at=datetime.now(timezone.utc),
            )
            conversation.sent_emails.append(sent_email)
            conversation.attempt_count += 1
            conversation.status = "waiting"

            logger.info(
                f"Email sent successfully: id={response.email_id}, "
                f"attempt={conversation.attempt_count}"
            )

            progress_msg = (
                f"Email sent to {current_poc} (attempt {conversation.attempt_count}): "
                f"'{subject}'"
            )

            return {
                "conversations": update_conversation(state, current_poc, conversation),
                "current_node": "send_email",
                "progress_messages": [progress_msg],
                # Clear composed email from state
                "_composed_subject": None,
                "_composed_body": None,
            }

        finally:
            await smtp_client.close()

    except Exception as e:
        error_msg = f"Failed to send email to {current_poc}: {e}"
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
