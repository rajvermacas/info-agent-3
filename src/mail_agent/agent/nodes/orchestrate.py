"""
Orchestrate Node - Decide the next step for multi-contact execution.

This node enables:
- Dispatching emails to multiple POCs without waiting after each send.
- Waiting for any reply among currently waiting POCs.
- Triggering global validation once all POCs have individually succeeded.
"""

import logging
from typing import Any, Optional

from mail_agent.agent.state import AgentState, get_active_poc


logger = logging.getLogger(__name__)


def _any_failed(state: AgentState) -> Optional[str]:
    for poc_email, conv in (state.get("conversations") or {}).items():
        if conv.get("status") == "failed":
            return poc_email
    return None


def _all_success(state: AgentState) -> bool:
    conversations = state.get("conversations") or {}
    return bool(conversations) and all(
        conv.get("status") == "success" for conv in conversations.values()
    )


def _next_poc_to_email(state: AgentState) -> Optional[str]:
    for poc_email, conv in (state.get("conversations") or {}).items():
        if conv.get("status") == "pending":
            return poc_email
    return None


def _waiting_pocs(state: AgentState) -> list[str]:
    return [
        poc
        for poc, conv in (state.get("conversations") or {}).items()
        if conv.get("status") == "waiting"
    ]


async def orchestrate(state: AgentState) -> dict[str, Any]:
    failed_poc = _any_failed(state)
    if failed_poc:
        msg = f"FAILED: POC {failed_poc} exceeded max attempts"
        return {
            "error": msg,
            "final_summary": msg,
            "orchestrator_next": "end",
            "current_node": "orchestrate",
            "progress_messages": [msg],
        }

    if state.get("global_valid") is True and not state.get("_final_outputs_sent"):
        return {
            "orchestrator_next": "send_final_outputs",
            "current_node": "orchestrate",
            "progress_messages": ["Global validation passed; sending final confirmations and delivery email(s)."],
        }

    if state.get("global_valid") is True:
        return {
            "orchestrator_next": "end",
            "current_node": "orchestrate",
            "progress_messages": ["Global validation complete."],
        }

    poc_to_email = _next_poc_to_email(state)
    if poc_to_email:
        return {
            "current_poc": poc_to_email,
            "orchestrator_next": "compose_email",
            "current_node": "orchestrate",
            "progress_messages": [f"Dispatching email to {poc_to_email}"],
        }

    if _all_success(state):
        return {
            "orchestrator_next": "validate_global",
            "current_node": "orchestrate",
            "progress_messages": ["All POCs succeeded; running global validation."],
        }

    waiting = _waiting_pocs(state)
    if waiting:
        return {
            "orchestrator_next": "wait_for_any_reply",
            "current_node": "orchestrate",
            "progress_messages": [f"Waiting for replies from {len(waiting)} POC(s)."],
        }

    # Fallback: if some POC is mid-flight, resume by selecting an active POC.
    active = get_active_poc(state)
    if active:
        return {
            "current_poc": active,
            "orchestrator_next": "wait_for_any_reply",
            "current_node": "orchestrate",
            "progress_messages": [f"Waiting for replies (active POC: {active})."],
        }

    msg = "No active conversations to process."
    logger.warning(msg)
    return {
        "orchestrator_next": "end",
        "current_node": "orchestrate",
        "progress_messages": [msg],
    }
