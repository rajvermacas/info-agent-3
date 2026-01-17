"""
Send Clarification Email Node - Send a clarification reply without consuming an attempt.
"""

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from mail_agent.agent.state import AgentState, SentEmail, get_conversation, update_conversation
from mail_agent.config import get_settings
from mail_agent.tools.smtp_sender import SMTPSenderService

logger = logging.getLogger(__name__)


async def send_clarification_email(state: AgentState) -> dict[str, Any]:
    current_poc = state.get("current_poc")
    if not current_poc:
        return {
            "error": "No current POC set",
            "current_node": "error",
            "progress_messages": ["ERROR: No current POC set for clarification email"],
        }

    subject = state.get("_composed_subject")
    body = state.get("_composed_body")
    if not subject or not body:
        return {
            "error": "No composed email found",
            "current_node": "error",
            "progress_messages": ["ERROR: No composed clarification email found to send"],
        }

    logger.info("Sending clarification email to %s", current_poc)

    conversation = get_conversation(state, current_poc)
    conversation.status = "sending"

    settings = get_settings()
    smtp_sender = SMTPSenderService(settings)
    email_id = uuid4()

    await smtp_sender.send_email(
        to_addresses=[current_poc],
        subject=subject,
        body_text=body,
    )

    conversation.sent_emails.append(
        SentEmail(
            email_id=email_id,
            subject=subject,
            body=body,
            sent_at=datetime.now(timezone.utc),
        )
    )
    conversation.status = "waiting"

    return {
        "conversations": update_conversation(state, current_poc, conversation),
        "current_node": "send_clarification_email",
        "progress_messages": [f"Clarification reply sent to {current_poc}: '{subject}'"],
        "_composed_subject": None,
        "_composed_body": None,
    }

