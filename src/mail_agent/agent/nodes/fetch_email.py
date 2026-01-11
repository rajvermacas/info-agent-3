"""
Fetch Email Node - Retrieve full email with attachments from inbox.

Uses the inbox client to fetch the complete email data.
"""

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from mail_agent.agent.state import (
    AgentState,
    ReceivedEmail,
    get_conversation,
    update_conversation,
)
from mail_agent.config import get_settings
from mail_agent.tools.inbox_client import InboxClient


logger = logging.getLogger(__name__)


async def fetch_email(state: AgentState) -> dict[str, Any]:
    """
    Fetch full email from the agent's inbox.

    This node:
    1. Gets the email ID from pending_webhooks
    2. Fetches the complete email via REST API
    3. Records the received email in conversation state

    Args:
        state: Current agent state with pending_webhooks.

    Returns:
        State update with fetched email recorded.
    """
    current_poc = state.get("current_poc")
    if not current_poc:
        logger.error("No current POC set for fetch_email")
        return {
            "error": "No current POC set",
            "current_node": "error",
            "progress_messages": ["ERROR: No current POC set for fetching email"],
        }

    # Get pending webhook (email ID)
    pending_webhooks = state.get("pending_webhooks", [])
    if not pending_webhooks:
        logger.error("No pending webhooks to fetch")
        return {
            "error": "No pending webhooks",
            "current_node": "error",
            "progress_messages": ["ERROR: No pending email to fetch"],
        }

    email_id_str = pending_webhooks[-1]  # Get most recent
    email_id = UUID(email_id_str)

    logger.info(f"Fetching email: id={email_id}")

    try:
        # Get conversation state
        conversation = get_conversation(state, current_poc)
        conversation.status = "fetching"

        settings = get_settings()
        inbox_client = InboxClient(settings)

        try:
            # Fetch full email
            email = await inbox_client.get_email(
                inbox_address=settings.agent_email,
                email_id=email_id,
            )

            # Create received email record
            received_email = ReceivedEmail(
                email_id=email.email_id,
                from_address=email.from_address,
                subject=email.subject,
                received_at=datetime.now(timezone.utc),
                has_attachment=email.has_attachments,
                body_text=email.body_text,
            )

            # Store attachment info if present
            if email.attachments:
                attachment = email.attachments[0]  # Use first attachment
                received_email.attachment_filename = attachment.filename
                # Store base64 content for extraction
                # We'll store it temporarily and extract in next node
                logger.info(
                    f"Email has attachment: {attachment.filename} "
                    f"({attachment.size_bytes} bytes)"
                )

            conversation.received_emails.append(received_email)
            conversation.status = "extracting"

            logger.info(
                f"Email fetched successfully: from={email.from_address}, "
                f"subject={email.subject}, attachments={len(email.attachments)}"
            )

            progress_msg = (
                f"Fetched email from {current_poc}: '{email.subject}'"
                f"{f' with attachment: {email.attachments[0].filename}' if email.attachments else ''}"
            )

            # Store email data for extract_content node
            return {
                "conversations": update_conversation(state, current_poc, conversation),
                "current_node": "fetch_email",
                "progress_messages": [progress_msg],
                # Store email data for extraction
                "_fetched_email_id": str(email.email_id),
                "_fetched_attachments": [
                    {
                        "filename": att.filename,
                        "content_type": att.content_type,
                        "content_base64": att.content_base64,
                        "size_bytes": att.size_bytes,
                    }
                    for att in email.attachments
                ],
                "_fetched_body_text": email.body_text,
            }

        finally:
            await inbox_client.close()

    except Exception as e:
        error_msg = f"Failed to fetch email {email_id}: {e}"
        logger.error(error_msg)

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
