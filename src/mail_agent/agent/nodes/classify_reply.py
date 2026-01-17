"""
Classify Reply Node - Detect clarification questions before validation.

If a POC replies asking questions about the request, the agent should answer
and continue waiting, rather than treating it as an invalid data response.
"""

import logging
from typing import Any

from mail_agent.agent.state import AgentState
from mail_agent.config import get_settings
from mail_agent.llm.client import LLMClient
from mail_agent.llm.clarifications import (
    ClarificationDetection,
    ClarificationPrompts,
)

logger = logging.getLogger(__name__)


async def classify_reply(state: AgentState) -> dict[str, Any]:
    current_poc = state.get("current_poc")
    if not current_poc:
        return {
            "error": "No current POC set",
            "current_node": "error",
            "progress_messages": ["ERROR: No current POC set for reply classification"],
        }

    body_text = state.get("_fetched_body_text") or ""
    settings = get_settings()
    llm_client = LLMClient(settings)

    try:
        prompt = ClarificationPrompts.detect(body_text)
        detection = await llm_client.generate_structured(
            prompt=prompt,
            output_schema=ClarificationDetection,
            system_prompt=ClarificationPrompts.DETECT_SYSTEM,
        )

        detected = bool(detection.is_clarification_question)
        question = (detection.question or "").strip() or None

        msg = (
            f"Clarification question detected from {current_poc}: {question}"
            if detected
            else f"No clarification question detected from {current_poc}; proceeding to validation."
        )

        return {
            "current_node": "classify_reply",
            "progress_messages": [msg],
            "_clarification_detected": detected,
            "_clarification_question": question,
        }
    except Exception as e:
        logger.error("Reply classification failed: %s", e)
        return {
            "current_node": "classify_reply",
            "progress_messages": ["Reply classification failed; proceeding to validation."],
            "_clarification_detected": False,
            "_clarification_question": None,
        }

