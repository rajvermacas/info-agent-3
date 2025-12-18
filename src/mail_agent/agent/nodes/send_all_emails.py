"""
Send All Emails Node - Send composed emails to all POCs.

Used in parallel processing mode to send all composed emails
simultaneously (or in rapid sequence).
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from mail_agent.agent.state import (
    AgentState,
    ConversationState,
    SentEmail,
)
from mail_agent.config import get_settings
from mail_agent.tools.smtp_sender import SMTPSenderService


logger = logging.getLogger(__name__)


async def send_all_emails(state: AgentState) -> dict[str, Any]:
    """
    Send composed emails to ALL POCs.

    Takes the composed emails from _composed_emails (set by compose_all_emails)
    and sends them all via SMTP (concurrently or in rapid sequence).
    Updates all conversation states to "waiting".

    Args:
        state: Current agent state with _composed_emails list.

    Returns:
        State update with emails sent and _waiting_pocs set.
    """
    composed_emails = state.get("_composed_emails", [])

    if not composed_emails:
        logger.error("No composed emails found in state for send_all_emails")
        return {
            "error": "No composed emails found",
            "current_node": "error",
            "progress_messages": ["ERROR: No composed emails found to send"],
        }

    logger.info(f"Sending emails to {len(composed_emails)} POCs")

    try:
        settings = get_settings()
        smtp_sender = SMTPSenderService(settings)

        # Send all emails concurrently
        async def send_to_poc(email_data: dict[str, Any]) -> dict[str, Any]:
            """Send email to a single POC."""
            poc_email = email_data["poc_email"]
            subject = email_data["subject"]
            body = email_data["body"]

            try:
                # Generate email_id client-side
                email_id = uuid4()
                sent_at = datetime.now(timezone.utc)

                logger.debug(
                    f"Sending email via SMTP: to={poc_email}, subject={subject}, "
                    f"email_id={email_id}"
                )

                await smtp_sender.send_email(
                    to_addresses=[poc_email],
                    subject=subject,
                    body_text=body,
                )

                logger.info(f"Email sent successfully to {poc_email}: id={email_id}")

                return {
                    "poc_email": poc_email,
                    "email_id": email_id,
                    "subject": subject,
                    "body": body,
                    "sent_at": sent_at,
                    "success": True,
                    "error": None,
                }

            except Exception as e:
                error_msg = f"Failed to send email to {poc_email}: {e}"
                logger.error(error_msg)
                return {
                    "poc_email": poc_email,
                    "email_id": None,
                    "subject": subject,
                    "body": body,
                    "sent_at": None,
                    "success": False,
                    "error": error_msg,
                }

        # Run all sends concurrently
        logger.info(f"Sending {len(composed_emails)} emails concurrently")
        send_results = await asyncio.gather(
            *[send_to_poc(email) for email in composed_emails]
        )

        # Process results and update conversation states
        conversations = dict(state.get("conversations", {}))
        waiting_pocs: list[str] = []
        failed_pocs: list[str] = []

        for result in send_results:
            poc_email = result["poc_email"]

            if poc_email not in conversations:
                logger.warning(f"No conversation found for POC {poc_email}")
                continue

            conv = ConversationState.from_dict(conversations[poc_email])

            if result["success"]:
                # Record sent email
                sent_email = SentEmail(
                    email_id=result["email_id"],
                    subject=result["subject"],
                    body=result["body"],
                    sent_at=result["sent_at"],
                )
                conv.sent_emails.append(sent_email)
                conv.attempt_count += 1
                conv.status = "waiting"
                waiting_pocs.append(poc_email)

                logger.info(
                    f"Email recorded for {poc_email}: "
                    f"attempt={conv.attempt_count}, id={result['email_id']}"
                )
            else:
                conv.status = "failed"
                conv.error_message = result["error"]
                failed_pocs.append(poc_email)
                logger.error(f"Send failed for {poc_email}: {result['error']}")

            conversations[poc_email] = conv.to_dict()

        # Check if we have at least some emails sent
        if not waiting_pocs:
            error_msg = f"All {len(composed_emails)} email sends failed"
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
                f"Sent emails to {len(waiting_pocs)} POCs "
                f"({len(failed_pocs)} failed: {', '.join(failed_pocs)})"
            )
        else:
            progress_msg = f"Sent emails to all {len(waiting_pocs)} POCs"

        logger.info(progress_msg)
        logger.info(f"Waiting POCs: {waiting_pocs}")

        return {
            "conversations": conversations,
            "current_node": "send_all_emails",
            "progress_messages": [progress_msg],
            "_waiting_pocs": waiting_pocs,
            "_composed_emails": None,  # Clear composed emails
            "_parallel_mode": True,
        }

    except Exception as e:
        error_msg = f"Failed to send all emails: {e}"
        logger.exception(error_msg)
        return {
            "error": error_msg,
            "current_node": "error",
            "progress_messages": [f"ERROR: {error_msg}"],
        }
