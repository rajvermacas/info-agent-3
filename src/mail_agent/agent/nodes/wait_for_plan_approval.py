"""
Wait For Plan Approval Node - Suspend until the end user approves the agent plan.

In A2A mode this node interrupts with a structured plan payload so the UI can
render an Approve/Reject flow. On resume it either continues execution or
triggers a re-plan using user feedback.
"""

import logging
from typing import Any, Literal

from langgraph.errors import GraphInterrupt
from langgraph.types import interrupt

from mail_agent.agent.nodes.wait_for_reply import is_a2a_mode
from mail_agent.agent.state import AgentState

logger = logging.getLogger(__name__)


def _build_plan_payload(state: AgentState) -> dict[str, Any]:
    contract = state.get("contract") or {}
    return {
        "agent_plan_steps": contract.get("agent_plan_steps") or [],
        "assumptions": contract.get("assumptions") or [],
        "poc_plans": contract.get("poc_plans") or [],
        "delivery_recipients": state.get("delivery_recipients") or contract.get("delivery_recipients") or [],
        "delivery_description": contract.get("delivery_description"),
        "global_success_criteria": contract.get("global_success_criteria", ""),
        "reminder_policy": state.get("reminder_policy") or {},
    }


def _normalize_decision(decision: Any) -> Literal["approve", "reject", "unknown"]:
    if not isinstance(decision, str):
        return "unknown"
    lowered = decision.strip().lower()
    if lowered in ("approve", "approved", "confirm", "confirmed", "yes"):
        return "approve"
    if lowered in ("reject", "rejected", "no"):
        return "reject"
    return "unknown"


async def wait_for_plan_approval(state: AgentState) -> dict[str, Any]:
    task_id = state.get("task_id")
    base_instruction = state.get("base_user_instruction") or state.get("user_instruction") or ""
    user_instruction = state.get("user_instruction") or ""
    if not is_a2a_mode():
        return {
            "plan_status": "approved",
            "current_node": "wait_for_plan_approval",
            "progress_messages": ["Plan auto-approved (non-A2A mode)."],
        }
    if not task_id:
        return {
            "error": "Missing task_id for plan approval interrupt",
            "current_node": "error",
            "progress_messages": ["ERROR: Missing task_id for plan approval interrupt"],
        }
    plan_payload = _build_plan_payload(state)
    try:
        resume_data = interrupt(
            {
                "reason": "awaiting_plan_approval",
                "task_id": task_id,
                "routing_key": f"ui:{task_id}",
                "poc_email": "ui",
                "user_instruction": user_instruction,
                "plan": plan_payload,
            }
        )
        decision = _normalize_decision(resume_data.get("decision"))
        feedback = resume_data.get("feedback")

        if decision == "approve":
            return {
                "plan_status": "approved",
                "current_node": "wait_for_plan_approval",
                "progress_messages": ["Plan approved by user; continuing execution."],
            }

        if decision == "reject":
            feedback_text = (feedback or "").strip()
            updated_instruction = base_instruction
            if feedback_text:
                updated_instruction = (
                    f"{base_instruction}\n\n"
                    "User feedback (plan rejected):\n"
                    f"{feedback_text}\n"
                )
            return {
                "plan_status": "rejected",
                "plan_feedback": feedback_text or None,
                "user_instruction": updated_instruction,
                "parsed_request": None,
                "contract": None,
                "poc_request_contexts": None,
                "delivery_recipients": None,
                "conversations": {},
                "global_validation": None,
                "global_valid": None,
                "current_node": "wait_for_plan_approval",
                "progress_messages": ["Plan rejected by user; regenerating plan from feedback."],
            }

        return {
            "plan_status": "pending_approval",
            "current_node": "wait_for_plan_approval",
            "progress_messages": ["No valid plan decision received; still awaiting approval."],
        }

    except GraphInterrupt:
        raise
    except Exception as e:
        error_msg = f"Plan approval handling failed: {e}"
        logger.error(error_msg)
        return {
            "error": error_msg,
            "current_node": "error",
            "progress_messages": [f"ERROR: {error_msg}"],
        }
