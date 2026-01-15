"""
Inject POC Context Node - Inject data from completed dependencies.

Merges extracted_data from completed dependency POCs into the current POC's
context_from_deps field, enabling context-aware email composition.
"""

import logging
from typing import Any

from mail_agent.agent.multi_poc_helpers import (
    get_execution_plan,
    get_poc_requirement,
    get_poc_state,
    update_poc_state,
)
from mail_agent.agent.multi_poc_state import POCStatus
from mail_agent.agent.state import AgentState


logger = logging.getLogger(__name__)


async def inject_poc_context(state: AgentState) -> dict[str, Any]:
    """
    Inject context from completed dependencies into current POC.

    This node:
    1. Gets the current POC's dependencies
    2. Collects extracted_data from completed dependency POCs
    3. Merges data into current POC's context_from_deps
    4. Updates the POC requirement with context

    Args:
        state: Current agent state with current_poc_id set.

    Returns:
        State update with context injected into POC requirement.
    """
    current_poc_id = state.get("current_poc_id")
    if not current_poc_id:
        error_msg = "No current_poc_id set for inject_poc_context"
        logger.error(error_msg)
        return {
            "error": error_msg,
            "current_node": "error",
            "progress_messages": [f"ERROR: {error_msg}"],
        }

    logger.info(f"Injecting context for POC: {current_poc_id}")

    try:
        execution_plan = get_execution_plan(state)
        current_requirement = get_poc_requirement(state, current_poc_id)
        current_poc_state = get_poc_state(state, current_poc_id)

        # Get list of dependencies
        dependencies = current_requirement.dependencies

        if not dependencies:
            logger.info(f"POC {current_poc_id} has no dependencies. No context to inject.")
            return {
                "current_node": "inject_poc_context",
                "progress_messages": [
                    f"POC {current_poc_id}: No dependencies, skipping context injection"
                ],
            }

        # Collect context from completed dependencies
        context: dict[str, Any] = {}
        missing_deps: list[str] = []

        for dep_id in dependencies:
            try:
                dep_state = get_poc_state(state, dep_id)

                if dep_state.status != POCStatus.COMPLETED:
                    logger.warning(
                        f"Dependency {dep_id} not completed "
                        f"(status={dep_state.status}). Skipping."
                    )
                    missing_deps.append(dep_id)
                    continue

                if dep_state.extracted_data:
                    # Merge extracted data into context
                    # Prefix with POC ID to avoid collisions
                    for key, value in dep_state.extracted_data.items():
                        context_key = f"{dep_id}_{key}" if len(dependencies) > 1 else key
                        context[context_key] = value
                        logger.debug(
                            f"Injected context: {context_key} from {dep_id}"
                        )
                else:
                    logger.debug(f"Dependency {dep_id} has no extracted_data")

            except (KeyError, ValueError) as e:
                logger.warning(f"Could not get state for dependency {dep_id}: {e}")
                missing_deps.append(dep_id)

        if missing_deps:
            logger.warning(
                f"POC {current_poc_id}: Missing context from dependencies: {missing_deps}"
            )

        # Update POC requirement with context
        # Note: We need to update the execution_plan with new requirement
        updated_pocs = []
        for poc in execution_plan.pocs:
            if poc.id == current_poc_id:
                # Merge new context with existing
                merged_context = dict(poc.context_from_deps or {})
                merged_context.update(context)

                # Create updated requirement
                from mail_agent.agent.multi_poc_state import POCRequirement
                updated_poc = POCRequirement(
                    id=poc.id,
                    email=poc.email,
                    request=poc.request,
                    success_criteria=poc.success_criteria,
                    dependencies=poc.dependencies,
                    execution_order=poc.execution_order,
                    spawns_dynamic_pocs=poc.spawns_dynamic_pocs,
                    context_from_deps=merged_context,
                )
                updated_pocs.append(updated_poc)
                logger.debug(
                    f"Updated POC {current_poc_id} with context: "
                    f"{list(merged_context.keys())}"
                )
            else:
                updated_pocs.append(poc)

        # Create updated execution plan
        from mail_agent.agent.multi_poc_state import POCExecutionPlan
        updated_plan = POCExecutionPlan(
            global_success_criteria=execution_plan.global_success_criteria,
            pocs=updated_pocs,
            dependency_graph=execution_plan.dependency_graph,
        )

        # Update POC state to in_progress
        current_poc_state.status = POCStatus.IN_PROGRESS
        updated_poc_states = update_poc_state(state, current_poc_id, current_poc_state)

        # Create progress message
        if context:
            context_keys = list(context.keys())[:5]  # Limit for readability
            context_summary = ", ".join(context_keys)
            if len(context.keys()) > 5:
                context_summary += f", ... (+{len(context.keys()) - 5} more)"
            progress_msg = (
                f"POC {current_poc_id}: Injected context from "
                f"{len(dependencies) - len(missing_deps)} dependency(s): {context_summary}"
            )
        else:
            progress_msg = f"POC {current_poc_id}: No context data available from dependencies"

        logger.info(
            f"Context injection complete for {current_poc_id}: "
            f"{len(context)} data items from {len(dependencies) - len(missing_deps)} deps"
        )

        return {
            "execution_plan": updated_plan.to_dict(),
            "poc_states": updated_poc_states,
            "current_node": "inject_poc_context",
            "progress_messages": [progress_msg],
        }

    except Exception as e:
        error_msg = f"Failed to inject context for {current_poc_id}: {e}"
        logger.error(error_msg, exc_info=True)
        return {
            "error": error_msg,
            "current_node": "error",
            "progress_messages": [f"ERROR: {error_msg}"],
        }
