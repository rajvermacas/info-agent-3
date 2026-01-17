"""
Send Receipt Reply Node - Send receipt acknowledgment email via SMTP.

Sends the email composed by compose_receipt_reply node.
Does NOT increment attempt_count as this is an acknowledgment, not a request.
"""

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from mail_agent.agent.state import AgentState, SentEmail, get_conversation, update_conversation
from mail_agent.config import get_settings
from mail_agent.tools.smtp_sender import SMTPSenderService


logger = logging.getLogger(__name__)


async def send_receipt_reply(state: AgentState) -> dict[str, Any]:
    current_poc = state.get("current_poc")
    if not current_poc:
        return {
            "error": "No current POC set",
            "current_node": "error",
            "progress_messages": ["ERROR: No current POC set for sending receipt reply"],
        }

    subject = state.get("_composed_subject")
    body = state.get("_composed_body")
    if not subject or not body:
        return {
            "error": "No composed receipt reply found",
            "current_node": "error",
            "progress_messages": ["ERROR: No composed receipt reply to send"],
        }

    try:
        conversation = get_conversation(state, current_poc)
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

        return {
            "conversations": update_conversation(state, current_poc, conversation),
            "current_node": "send_receipt_reply",
            "progress_messages": [f"Receipt acknowledgment sent to {current_poc}: '{subject}'"],
            "_composed_subject": None,
            "_composed_body": None,
        }
    except Exception as e:
        msg = f"Failed to send receipt acknowledgment to {current_poc}: {e}"
        logger.error(msg)
        try:
            conversation = get_conversation(state, current_poc)
            conversation.error_message = f"Receipt acknowledgment failed: {msg}"
            return {
                "conversations": update_conversation(state, current_poc, conversation),
                "current_node": "error",
                "progress_messages": [f"WARNING: {msg}"],
            }
        except Exception:
            return {
                "error": msg,
                "current_node": "error",
                "progress_messages": [f"WARNING: {msg}"],
            }

