"""
Wait For Any Reply Node - Suspend until any waiting POC replies.

This is the multi-contact counterpart to wait_for_reply. In A2A mode it
interrupts with a list of expected POCs so the TaskManager can route any of
those senders back to this task.
"""

import asyncio
import logging
from typing import Any, Optional

from langgraph.errors import GraphInterrupt
from langgraph.types import interrupt

from mail_agent.agent.state import AgentState, get_conversation, update_conversation
from mail_agent.agent.nodes.wait_for_reply import is_a2a_mode, get_webhook_server


logger = logging.getLogger(__name__)


def _find_matching_poc(state: AgentState, from_address: str) -> Optional[str]:
    from_lower = from_address.lower()
    for poc_email in state.get("conversations", {}).keys():
        if poc_email.lower() == from_lower:
            return poc_email
    return None


async def wait_for_any_reply(state: AgentState) -> dict[str, Any]:
    task_id = state.get("task_id")
    waiting_pocs = [
        poc
        for poc, conv in (state.get("conversations") or {}).items()
        if conv.get("status") == "waiting"
    ]

    if not waiting_pocs:
        return {
            "error": "No POCs in waiting state",
            "current_node": "error",
            "progress_messages": ["ERROR: No POCs in waiting state"],
        }

    progress_msg = f"Waiting for replies from {len(waiting_pocs)} POC(s)..."
    logger.info(progress_msg)

    try:
        if is_a2a_mode():
            resume_data = interrupt(
                {
                    "reason": "waiting_for_any_reply",
                    "task_id": task_id,
                    "poc_emails": waiting_pocs,
                    "routing_key": f"task:{task_id}",
                    "poc_email": waiting_pocs[0],
                }
            )
            email_id = resume_data.get("email_id")
            from_address = resume_data.get("from_address")
        else:
            webhook_server = get_webhook_server()
            event = await webhook_server.wait_for_event(timeout=3600.0)
            if event is None:
                raise asyncio.TimeoutError("Timed out waiting for webhook event")
            email_id = str(event.email_id)
            from_address = event.from_address

        if not email_id or not from_address:
            raise ValueError("Missing resume data: email_id or from_address")

        matched_poc = _find_matching_poc(state, from_address)
        if matched_poc is None:
            raise ValueError(f"Received reply from unexpected sender: {from_address}")

        conversation = get_conversation(state, matched_poc)
        conversation.status = "fetching"

        return {
            "conversations": update_conversation(state, matched_poc, conversation),
            "current_node": "wait_for_any_reply",
            "current_poc": matched_poc,
            "pending_webhooks": [str(email_id)],
            "progress_messages": [f"Reply received from {matched_poc} (email_id: {email_id})"],
        }

    except GraphInterrupt:
        raise
    except Exception as e:
        error_msg = f"Error waiting for reply: {e}"
        logger.error(error_msg)
        return {
            "error": error_msg,
            "current_node": "error",
            "progress_messages": [f"ERROR: {error_msg}"],
        }

