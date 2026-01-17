"""
Send Final Outputs Node - Send final confirmations to POCs and deliver merged output.
"""

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from mail_agent.agent.state import AgentState, SentEmail, get_conversation, update_conversation
from mail_agent.config import get_settings
from mail_agent.tools.aggregate_payloads import (
    extract_values_from_payload,
    to_single_column_csv,
    unique_preserve_order,
)
from mail_agent.tools.smtp_sender import SMTPSenderService


logger = logging.getLogger(__name__)


def _reply_subject(original: str) -> str:
    s = (original or "Information Request").strip()
    return s if s.lower().startswith("re:") else f"Re: {s}"


def _final_poc_body() -> str:
    return (
        "Dear Sir/Madam,\n\n"
        "Thank you for sharing the requested information.\n\n"
        "We have now validated your data against the full request and it looks correct.\n\n"
        "Best regards,\n"
        "info-agent"
    )


def _delivery_body(csv_text: str) -> str:
    return (
        "Dear Sir/Madam,\n\n"
        "Here are the validated animal names in CSV format:\n\n"
        f"{csv_text}\n"
        "Best regards,\n"
        "info-agent"
    )


def _collect_latest_payloads(conversations: dict[str, dict[str, Any]]) -> list[str]:
    payloads: list[str] = []
    for conv in conversations.values():
        emails = conv.get("received_emails") or []
        if not emails:
            continue
        last = emails[-1]
        payload = last.get("attachment_content") or last.get("body_text") or ""
        if payload:
            payloads.append(payload)
    return payloads


async def send_final_outputs(state: AgentState) -> dict[str, Any]:
    conversations = state.get("conversations") or {}
    delivery_recipients = state.get("delivery_recipients") or []
    settings = get_settings()
    smtp_sender = SMTPSenderService(settings)

    payloads = _collect_latest_payloads(conversations)
    merged_values = unique_preserve_order([v for p in payloads for v in extract_values_from_payload(p)])
    csv_text = to_single_column_csv("animal_name", merged_values)

    updated_conversations: dict[str, dict[str, Any]] = dict(conversations)
    for poc_email in conversations.keys():
        conversation = get_conversation(state, poc_email)
        subject = _reply_subject(conversation.sent_emails[-1].subject if conversation.sent_emails else "")
        body = _final_poc_body()
        await smtp_sender.send_email(to_addresses=[poc_email], subject=subject, body_text=body)
        conversation.sent_emails.append(
            SentEmail(
                email_id=uuid4(),
                subject=subject,
                body=body,
                sent_at=datetime.now(timezone.utc),
            )
        )
        updated_conversations[poc_email] = conversation.to_dict()

    for recipient in delivery_recipients:
        subject = "Validated animal names (CSV)"
        body = _delivery_body(csv_text)
        await smtp_sender.send_email(to_addresses=[recipient], subject=subject, body_text=body)

    msgs = [f"Final confirmations sent to {len(conversations)} POC(s)."]
    if delivery_recipients:
        msgs.append(f"Delivered merged result to {', '.join(delivery_recipients)}.")

    return {
        "conversations": updated_conversations,
        "_final_outputs_sent": True,
        "current_node": "send_final_outputs",
        "progress_messages": msgs,
    }
