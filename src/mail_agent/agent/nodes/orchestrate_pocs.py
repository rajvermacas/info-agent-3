"""
Orchestrate POCs Node - DAG-based scheduler for multi-POC execution.

Core scheduling decision node that determines the next action based on
POC states and dependencies. Controls the multi-POC execution flow.
"""

import logging
from typing import Any

from mail_agent.agent.multi_poc_helpers import (
    all_pocs_terminal,
    get_execution_plan,
    get_failed_pocs,
    get_poc_progress_summary,
    get_ready_pocs,
    get_waiting_pocs,
)
from mail_agent.agent.multi_poc_state import (
    OrchestrationAction,
    OrchestrationDecision,
)
from mail_agent.agent.state import AgentState


logger = logging.getLogger(__name__)


async def orchestrate_pocs(state: AgentState) -> dict[str, Any]:
    """
    Make scheduling decision for multi-POC execution.

    This is the central orchestration node that determines:
    1. Which POCs are ready to execute (dependencies satisfied)
    2. Which POCs are waiting for replies
    3. When to aggregate results (all POCs complete)
    4. When to fail (critical POC failed or deadlock)

    Decision Algorithm:
    1. Check terminal condition (all POCs completed/failed → aggregate)
    2. Find ready POCs (pending with satisfied dependencies)
    3. If ready POCs exist → execute first ready POC
    4. If POCs are waiting → wait for reply
    5. If no progress possible → fail (deadlock)

    Args:
        state: Current agent state with execution_plan and poc_states.

    Returns:
        State update with orchestration_decision indicating next action.
    """
    logger.info("Orchestrating POC execution")

    try:
        execution_plan = get_execution_plan(state)
        progress = get_poc_progress_summary(state)

        logger.info(
            f"POC progress: pending={progress['pending']}, "
            f"in_progress={progress['in_progress']}, "
            f"waiting={progress['waiting']}, "
            f"completed={progress['completed']}, "
            f"failed={progress['failed']}"
        )

        # 1. Check terminal condition: all POCs are in terminal state
        if all_pocs_terminal(state):
            completed = progress["completed"]
            failed = progress["failed"]
            total = len(execution_plan.pocs)

            if failed > 0 and completed == 0:
                # All POCs failed
                logger.warning(f"All {failed} POC(s) failed. Terminating.")
                decision = OrchestrationDecision(
                    action=OrchestrationAction.FAIL,
                    poc_ids=[],
                    reason=f"All {failed} POC(s) failed",
                )
            else:
                # Some or all completed - aggregate results
                logger.info(
                    f"All POCs terminal: {completed} completed, {failed} failed. "
                    "Proceeding to aggregation."
                )
                decision = OrchestrationDecision(
                    action=OrchestrationAction.AGGREGATE,
                    poc_ids=[],
                    reason=f"All {total} POC(s) reached terminal state",
                )

            return {
                "orchestration_decision": decision.to_dict(),
                "current_node": "orchestrate_pocs",
                "progress_messages": [f"Orchestration: {decision.reason}"],
            }

        # 2. Check for ready POCs (pending with satisfied dependencies)
        ready_pocs = get_ready_pocs(state)

        if ready_pocs:
            # Execute first ready POC
            # Note: For true parallel execution, this would return multiple POC IDs
            # Current implementation executes one at a time for simplicity
            next_poc_id = ready_pocs[0]

            logger.info(
                f"Ready POCs: {ready_pocs}. Executing: {next_poc_id}"
            )

            decision = OrchestrationDecision(
                action=OrchestrationAction.EXECUTE,
                poc_ids=[next_poc_id],
                reason=f"Executing POC {next_poc_id} (dependencies satisfied)",
            )

            return {
                "orchestration_decision": decision.to_dict(),
                "current_poc_id": next_poc_id,
                "current_node": "orchestrate_pocs",
                "progress_messages": [
                    f"Orchestration: Executing POC {next_poc_id}"
                ],
            }

        # 3. Check for waiting POCs
        waiting_pocs = get_waiting_pocs(state)

        if waiting_pocs:
            logger.info(f"POCs waiting for replies: {waiting_pocs}")

            decision = OrchestrationDecision(
                action=OrchestrationAction.WAIT,
                poc_ids=waiting_pocs,
                reason=f"Waiting for replies from {len(waiting_pocs)} POC(s)",
            )

            return {
                "orchestration_decision": decision.to_dict(),
                "current_node": "orchestrate_pocs",
                "progress_messages": [
                    f"Orchestration: Waiting for {len(waiting_pocs)} POC reply(s)"
                ],
            }

        # 4. Check for in_progress POCs (shouldn't happen normally)
        in_progress = progress["in_progress"]
        if in_progress > 0:
            logger.warning(
                f"{in_progress} POC(s) in progress but not ready/waiting. "
                "Possible state inconsistency."
            )

            decision = OrchestrationDecision(
                action=OrchestrationAction.WAIT,
                poc_ids=[],
                reason=f"Waiting for {in_progress} in-progress POC(s)",
            )

            return {
                "orchestration_decision": decision.to_dict(),
                "current_node": "orchestrate_pocs",
                "progress_messages": [
                    f"Orchestration: {in_progress} POC(s) in progress"
                ],
            }

        # 5. Deadlock detection: No ready POCs, no waiting POCs, not terminal
        # This indicates a dependency cycle or configuration error
        failed_pocs = get_failed_pocs(state)
        pending = progress["pending"]

        if pending > 0 and failed_pocs:
            # Some POCs pending but their dependencies failed
            logger.error(
                f"Deadlock: {pending} pending POC(s) have failed dependencies"
            )
            decision = OrchestrationDecision(
                action=OrchestrationAction.FAIL,
                poc_ids=[],
                reason=(
                    f"Deadlock: {pending} pending POC(s) cannot execute due to "
                    f"{len(failed_pocs)} failed dependency POC(s)"
                ),
            )
        else:
            logger.error(
                f"Deadlock: No executable POCs. pending={pending}, "
                f"waiting={len(waiting_pocs)}, failed={len(failed_pocs)}"
            )
            decision = OrchestrationDecision(
                action=OrchestrationAction.FAIL,
                poc_ids=[],
                reason="Deadlock: No POCs can make progress",
            )

        return {
            "orchestration_decision": decision.to_dict(),
            "current_node": "orchestrate_pocs",
            "error": decision.reason,
            "progress_messages": [f"ERROR: {decision.reason}"],
        }

    except Exception as e:
        error_msg = f"Orchestration failed: {e}"
        logger.error(error_msg, exc_info=True)

        decision = OrchestrationDecision(
            action=OrchestrationAction.FAIL,
            poc_ids=[],
            reason=error_msg,
        )

        return {
            "orchestration_decision": decision.to_dict(),
            "current_node": "error",
            "error": error_msg,
            "progress_messages": [f"ERROR: {error_msg}"],
        }


def get_orchestration_decision(state: AgentState) -> OrchestrationDecision:
    """
    Helper to retrieve OrchestrationDecision from state.

    Args:
        state: Current agent state.

    Returns:
        OrchestrationDecision object.

    Raises:
        ValueError: If orchestration_decision not in state.
    """
    decision_dict = state.get("orchestration_decision")
    if not decision_dict:
        raise ValueError("No orchestration_decision in state")
    return OrchestrationDecision.from_dict(decision_dict)


def should_execute(state: AgentState) -> bool:
    """Check if orchestration decision is EXECUTE."""
    try:
        decision = get_orchestration_decision(state)
        return decision.action == OrchestrationAction.EXECUTE
    except ValueError:
        return False


def should_wait(state: AgentState) -> bool:
    """Check if orchestration decision is WAIT."""
    try:
        decision = get_orchestration_decision(state)
        return decision.action == OrchestrationAction.WAIT
    except ValueError:
        return False


def should_aggregate(state: AgentState) -> bool:
    """Check if orchestration decision is AGGREGATE."""
    try:
        decision = get_orchestration_decision(state)
        return decision.action == OrchestrationAction.AGGREGATE
    except ValueError:
        return False


def should_fail(state: AgentState) -> bool:
    """Check if orchestration decision is FAIL."""
    try:
        decision = get_orchestration_decision(state)
        return decision.action == OrchestrationAction.FAIL
    except ValueError:
        return False
