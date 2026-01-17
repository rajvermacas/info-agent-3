"""
Compose Clarification Reply Node - Answer a POC clarification question.
"""

import logging
from typing import Any

from mail_agent.agent.state import AgentState, get_conversation, get_request_context, update_conversation
from mail_agent.config import get_settings
from mail_agent.llm.client import LLMClient
from mail_agent.llm.clarifications import ClarificationPrompts, ClarificationReply

logger = logging.getLogger(__name__)


def _reply_subject(conversation: Any) -> str:
    if conversation.sent_emails:
        subject = conversation.sent_emails[-1].subject
    elif conversation.received_emails:
        subject = conversation.received_emails[-1].subject
    else:
        subject = "Information Request"
    return subject if subject.lower().startswith("re:") else f"Re: {subject}"


async def compose_clarification_reply(state: AgentState) -> dict[str, Any]:
    current_poc = state.get("current_poc")
    if not current_poc:
        return {
            "error": "No current POC set",
            "current_node": "error",
            "progress_messages": ["ERROR: No current POC set for clarification reply"],
        }

    question = (state.get("_clarification_question") or "").strip()
    if not question:
        return {
            "current_node": "compose_clarification_reply",
            "progress_messages": ["No clarification question present; skipping clarification reply."],
        }

    conversation = get_conversation(state, current_poc)
    subject = _reply_subject(conversation)

    user_instruction = state.get("user_instruction") or ""
    request_description, success_criteria, expected_format = get_request_context(state, current_poc)

    settings = get_settings()
    llm_client = LLMClient(settings)

    prompt = ClarificationPrompts.reply(
        user_instruction=user_instruction,
        request_description=request_description,
        expected_format=expected_format,
        success_criteria=success_criteria,
        question=question,
    )
    reply = await llm_client.generate_structured(
        prompt=prompt,
        output_schema=ClarificationReply,
        system_prompt=ClarificationPrompts.REPLY_SYSTEM,
    )

    conversation.status = "composing"
    progress = f"Composed clarification reply to {current_poc}: '{subject}'"

    return {
        "conversations": update_conversation(state, current_poc, conversation),
        "current_node": "compose_clarification_reply",
        "progress_messages": [progress],
        "_composed_subject": subject,
        "_composed_body": reply.body,
        "_clarification_detected": None,
        "_clarification_question": None,
        "_extracted_content": None,
        "_extracted_headers": None,
        "_extracted_row_count": None,
    }

