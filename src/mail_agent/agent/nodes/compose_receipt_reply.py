"""
Compose Receipt Reply Node - Acknowledge receipt when global validation is pending.

This reply is sent after a POC provides a valid partial contribution, but before
the overall multi-contact/global validation is complete.
"""

import logging
from typing import Any

from mail_agent.agent.state import AgentState, get_conversation, update_conversation


logger = logging.getLogger(__name__)


def _reply_subject(conversation: Any) -> str:
    if conversation.sent_emails:
        subject = conversation.sent_emails[-1].subject
    elif conversation.received_emails:
        subject = conversation.received_emails[-1].subject
    else:
        subject = "Information Request"
    return subject if subject.lower().startswith("re:") else f"Re: {subject}"


def _receipt_body() -> str:
    return (
        "Dear Sir/Madam,\n\n"
        "Thank you for sharing the requested information.\n\n"
        "I have received your response and will validate it against the full request. "
        "Once the overall validation is complete, I will confirm whether everything looks correct "
        "or if anything needs adjustment.\n\n"
        "Best regards,\n"
        "info-agent"
    )


async def compose_receipt_reply(state: AgentState) -> dict[str, Any]:
    current_poc = state.get("current_poc")
    if not current_poc:
        return {
            "error": "No current POC set",
            "current_node": "error",
            "progress_messages": ["ERROR: No current POC set for composing receipt reply"],
        }

    conversation = get_conversation(state, current_poc)
    subject = _reply_subject(conversation)
    body = _receipt_body()

    progress = f"Receipt acknowledgment composed for {current_poc}: '{subject}'"

    return {
        "conversations": update_conversation(state, current_poc, conversation),
        "current_node": "compose_receipt_reply",
        "progress_messages": [progress],
        "_composed_subject": subject,
        "_composed_body": body,
    }

