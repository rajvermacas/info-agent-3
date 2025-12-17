"""
Send Success Reply Node - Send success acknowledgment email via SMTP.

Sends the acknowledgment email composed by compose_success_reply node.
Does NOT increment attempt_count as this is an acknowledgment, not a request.
"""

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from mail_agent.agent.state import (
    AgentState,
    SentEmail,
    get_conversation,
    update_conversation,
)
from mail_agent.config import get_settings
from mail_agent.tools.smtp_sender import SMTPSenderService


logger = logging.getLogger(__name__)


async def send_success_reply(state: AgentState) -> dict[str, Any]:
    """
    Send success acknowledgment email to current POC.

    This node:
    1. Retrieves the composed acknowledgment email from state
    2. Sends via SMTP protocol directly to the mock SMTP server
    3. Records the sent email in conversation state (for audit trail)
    4. Does NOT increment attempt_count (this is acknowledgment, not request)

    Args:
        state: Current agent state with _composed_subject and _composed_body.

    Returns:
        State update with sent email recorded.
    """
    current_poc = state.get("current_poc")
    if not current_poc:
        logger.error("No current POC set for send_success_reply")
        return {
            "error": "No current POC set",
            "current_node": "error",
            "progress_messages": ["ERROR: No current POC set for sending success reply"],
        }

    # Get composed email from state (set by compose_success_reply node)
    subject = state.get("_composed_subject")
    body = state.get("_composed_body")

    if not subject or not body:
        logger.error("No composed success acknowledgment found in state")
        return {
            "error": "No composed success acknowledgment found",
            "current_node": "error",
            "progress_messages": ["ERROR: No composed success acknowledgment to send"],
        }

    logger.info(f"Sending success acknowledgment to POC: {current_poc}")

    try:
        # Get conversation state
        conversation = get_conversation(state, current_poc)

        settings = get_settings()
        smtp_sender = SMTPSenderService(settings)

        # Generate email_id client-side (SMTP protocol doesn't return one)
        email_id = uuid4()

        # Send email via SMTP protocol
        logger.debug(
            f"Sending success acknowledgment via SMTP: to={current_poc}, "
            f"subject={subject}, email_id={email_id}"
        )
        await smtp_sender.send_email(
            to_addresses=[current_poc],
            subject=subject,
            body_text=body,
        )

        # Record sent email for audit trail
        # Note: We do NOT increment attempt_count - this is acknowledgment, not request
        sent_email = SentEmail(
            email_id=email_id,
            subject=subject,
            body=body,
            sent_at=datetime.now(timezone.utc),
        )
        conversation.sent_emails.append(sent_email)

        logger.info(
            f"Success acknowledgment sent via SMTP: id={email_id}, to={current_poc}"
        )

        progress_msg = (
            f"SUCCESS: Acknowledgment sent to {current_poc}: '{subject}'"
        )

        return {
            "conversations": update_conversation(state, current_poc, conversation),
            "current_node": "send_success_reply",
            "progress_messages": [progress_msg],
            # Clear composed email from state
            "_composed_subject": None,
            "_composed_body": None,
        }

    except Exception as e:
        error_msg = f"Failed to send success acknowledgment to {current_poc}: {e}"
        logger.error(error_msg)

        # Update conversation on failure (but don't fail the overall task)
        # The validation already succeeded, so we log the error but don't mark as failed
        try:
            conversation = get_conversation(state, current_poc)
            conversation.error_message = f"Success acknowledgment failed: {error_msg}"
            return {
                "conversations": update_conversation(state, current_poc, conversation),
                "current_node": "error",
                "progress_messages": [f"WARNING: {error_msg}"],
            }
        except Exception:
            return {
                "error": error_msg,
                "current_node": "error",
                "progress_messages": [f"WARNING: {error_msg}"],
            }
