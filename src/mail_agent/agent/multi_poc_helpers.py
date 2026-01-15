"""
Multi-POC Orchestration Helper Functions.

Provides utility functions for multi-POC state management and orchestration:
- State initialization for multi-POC mode
- POC state access and update functions
- Execution plan queries
- Progress tracking utilities

These functions work with AgentState and the multi-POC models defined in
multi_poc_state.py.
"""

from typing import Any

from mail_agent.agent.multi_poc_state import (
    POCExecutionPlan,
    POCRequirement,
    POCState,
    POCStatus,
)

# Import AgentState type for type hints (avoid circular import at runtime)
if False:  # TYPE_CHECKING equivalent without importing typing
    from mail_agent.agent.state import AgentState


def create_initial_multi_poc_state(user_instruction: str) -> "AgentState":
    """
    Create initial agent state for multi-POC orchestration.

    Args:
        user_instruction: Raw user input string.

    Returns:
        Initial AgentState dictionary configured for multi-POC mode.
    """
    # Import here to avoid circular import
    from mail_agent.agent.state import AgentState

    return AgentState(
        user_instruction=user_instruction,
        # Legacy fields (kept for backward compatibility)
        parsed_request=None,
        conversations={},
        current_poc=None,
        # Multi-POC fields
        execution_plan=None,
        poc_states={},
        current_poc_id=None,
        aggregated_data={},
        conflicts=[],
        global_validation_result=None,
        orchestration_phase="planning",
        # Common fields
        current_node="start",
        pending_webhooks=[],
        progress_messages=[f"Starting multi-POC orchestration: {user_instruction}"],
        final_summary=None,
        error=None,
        webhook_id=None,
        _composed_subject=None,
        _composed_body=None,
    )


def get_execution_plan(state: "AgentState") -> POCExecutionPlan:
    """
    Get POCExecutionPlan from state.

    Args:
        state: Current agent state.

    Returns:
        POCExecutionPlan object.

    Raises:
        ValueError: If execution_plan is not set.
    """
    plan_dict = state.get("execution_plan")
    if plan_dict is None:
        raise ValueError("execution_plan is not set in state")
    return POCExecutionPlan.from_dict(plan_dict)


def get_poc_state(state: "AgentState", poc_id: str) -> POCState:
    """
    Get POCState for a POC from state.

    Args:
        state: Current agent state.
        poc_id: POC identifier.

    Returns:
        POCState object.

    Raises:
        KeyError: If POC not found in state.
    """
    poc_states = state.get("poc_states", {})
    poc_dict = poc_states.get(poc_id)
    if poc_dict is None:
        raise KeyError(f"No POC state found for: {poc_id}")
    return POCState.from_dict(poc_dict)


def update_poc_state(
    state: "AgentState",
    poc_id: str,
    poc_state: POCState,
) -> dict[str, dict[str, Any]]:
    """
    Create updated poc_states dict with modified POC state.

    Args:
        state: Current agent state.
        poc_id: POC identifier.
        poc_state: Updated POCState.

    Returns:
        New poc_states dictionary (for state update).
    """
    poc_states = dict(state.get("poc_states", {}))
    poc_states[poc_id] = poc_state.to_dict()
    return poc_states


def get_poc_requirement(state: "AgentState", poc_id: str) -> POCRequirement:
    """
    Get POCRequirement for a POC from execution plan.

    Args:
        state: Current agent state.
        poc_id: POC identifier.

    Returns:
        POCRequirement object.

    Raises:
        KeyError: If POC not found in execution plan.
    """
    plan = get_execution_plan(state)
    for poc in plan.pocs:
        if poc.id == poc_id:
            return poc
    raise KeyError(f"No POC requirement found for: {poc_id}")


def get_all_poc_states(state: "AgentState") -> dict[str, POCState]:
    """
    Get all POC states as POCState objects.

    Args:
        state: Current agent state.

    Returns:
        Dictionary of poc_id → POCState.
    """
    poc_states_dict = state.get("poc_states", {})
    return {
        poc_id: POCState.from_dict(poc_dict)
        for poc_id, poc_dict in poc_states_dict.items()
    }


def all_pocs_terminal(state: "AgentState") -> bool:
    """
    Check if all POCs have reached terminal state (completed or failed).

    Args:
        state: Current agent state.

    Returns:
        True if all POCs are in completed or failed state.
    """
    poc_states = state.get("poc_states", {})
    if not poc_states:
        return False

    terminal_statuses = {POCStatus.COMPLETED.value, POCStatus.FAILED.value}
    for poc_dict in poc_states.values():
        status = poc_dict.get("status")
        if status not in terminal_statuses:
            return False

    return True


def get_ready_pocs(state: "AgentState") -> list[str]:
    """
    Get POC IDs that are ready to execute (dependencies satisfied, not started).

    Args:
        state: Current agent state.

    Returns:
        List of POC IDs ready for execution.
    """
    plan = get_execution_plan(state)
    poc_states = state.get("poc_states", {})

    ready_pocs = []
    completed_pocs = set()

    # Find all completed POCs
    for poc_id, poc_dict in poc_states.items():
        if poc_dict.get("status") == POCStatus.COMPLETED.value:
            completed_pocs.add(poc_id)

    # Find POCs with satisfied dependencies that are still pending
    for poc in plan.pocs:
        poc_dict = poc_states.get(poc.id, {})
        status = poc_dict.get("status", POCStatus.PENDING.value)

        if status == POCStatus.PENDING.value:
            # Check if all dependencies are completed
            deps_satisfied = all(dep_id in completed_pocs for dep_id in poc.dependencies)
            if deps_satisfied:
                ready_pocs.append(poc.id)

    return ready_pocs


def get_waiting_pocs(state: "AgentState") -> list[str]:
    """
    Get POC IDs that are waiting for email replies.

    Args:
        state: Current agent state.

    Returns:
        List of POC IDs in waiting state.
    """
    poc_states = state.get("poc_states", {})
    return [
        poc_id
        for poc_id, poc_dict in poc_states.items()
        if poc_dict.get("status") == POCStatus.WAITING.value
    ]


def get_poc_progress_summary(state: "AgentState") -> dict[str, int]:
    """
    Get summary of POC progress counts.

    Args:
        state: Current agent state.

    Returns:
        Dictionary with counts: total, pending, in_progress, waiting, completed, failed.
    """
    poc_states = state.get("poc_states", {})

    summary = {
        "total": len(poc_states),
        "pending": 0,
        "in_progress": 0,
        "waiting": 0,
        "completed": 0,
        "failed": 0,
    }

    for poc_dict in poc_states.values():
        status = poc_dict.get("status", POCStatus.PENDING.value)
        if status == POCStatus.PENDING.value:
            summary["pending"] += 1
        elif status == POCStatus.IN_PROGRESS.value:
            summary["in_progress"] += 1
        elif status == POCStatus.WAITING.value:
            summary["waiting"] += 1
        elif status == POCStatus.COMPLETED.value:
            summary["completed"] += 1
        elif status == POCStatus.FAILED.value:
            summary["failed"] += 1

    return summary


def add_poc_to_plan(
    state: "AgentState",
    poc_requirement: POCRequirement,
    initial_status: POCStatus = POCStatus.PENDING,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """
    Add a new POC to the execution plan and initialize its state.

    Used for dynamic POC spawning.

    Args:
        state: Current agent state.
        poc_requirement: New POC requirement to add.
        initial_status: Initial status for the new POC.

    Returns:
        Tuple of (updated execution_plan dict, updated poc_states dict).
    """
    # Update execution plan
    plan = get_execution_plan(state)
    plan.pocs.append(poc_requirement)
    plan.dependency_graph[poc_requirement.id] = poc_requirement.dependencies
    updated_plan = plan.to_dict()

    # Initialize POC state
    new_poc_state = POCState(
        poc_id=poc_requirement.id,
        status=initial_status,
        attempts=0,
        max_attempts=15,
        original_email=poc_requirement.email,
    )
    poc_states = dict(state.get("poc_states", {}))
    poc_states[poc_requirement.id] = new_poc_state.to_dict()

    return updated_plan, poc_states
