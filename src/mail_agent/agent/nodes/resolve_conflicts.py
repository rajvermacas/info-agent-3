"""
Resolve Conflicts Node - Use LLM to resolve data conflicts between POCs.

When multiple POCs provide conflicting values for the same field,
uses LLM to determine which source is most trustworthy.
"""

import logging
from typing import Any

from mail_agent.agent.multi_poc_helpers import (
    get_execution_plan,
    get_poc_requirement,
)
from mail_agent.agent.multi_poc_state import DataConflict
from mail_agent.agent.state import AgentState
from mail_agent.config import get_settings
from mail_agent.llm.client import LLMClient
from mail_agent.llm.multi_poc_prompts import (
    ConflictResolutionSchema,
    MultiPOCPromptTemplates,
)


logger = logging.getLogger(__name__)


async def resolve_conflicts(state: AgentState) -> dict[str, Any]:
    """
    Resolve data conflicts using LLM judgment.

    This node:
    1. Gets unresolved conflicts from state
    2. For each conflict, calls LLM to determine correct source
    3. Updates conflict records with resolution
    4. Returns list of POC IDs that need to re-provide data

    Args:
        state: Current agent state with conflicts list.

    Returns:
        State update with resolved conflicts and list of POC IDs needing retry.
    """
    logger.info("Resolving data conflicts")

    try:
        conflicts_raw = state.get("conflicts", [])

        if not conflicts_raw:
            logger.info("No conflicts to resolve")
            return {
                "current_node": "resolve_conflicts",
                "progress_messages": ["No conflicts to resolve"],
            }

        conflicts = [DataConflict.from_dict(c) for c in conflicts_raw]
        logger.info(f"Resolving {len(conflicts)} conflict(s)")

        execution_plan = get_execution_plan(state)
        settings = get_settings()
        llm_client = LLMClient(settings)

        resolved_conflicts: list[DataConflict] = []
        all_incorrect_pocs: set[str] = set()

        for conflict in conflicts:
            logger.info(f"Resolving conflict for field: {conflict.field}")

            # Build context for LLM
            context_parts: list[str] = []
            for poc_id in conflict.poc_values.keys():
                try:
                    req = get_poc_requirement(state, poc_id)
                    context_parts.append(
                        f"{poc_id}: {req.email} - requested '{req.request}'"
                    )
                except (KeyError, ValueError):
                    context_parts.append(f"{poc_id}: (unknown)")

            context = "; ".join(context_parts)

            # Call LLM for resolution
            prompt = MultiPOCPromptTemplates.resolve_conflict(
                field_name=conflict.field,
                poc_values=conflict.poc_values,
                context=context,
            )

            resolution: ConflictResolutionSchema = await llm_client.generate_structured(
                prompt=prompt,
                output_schema=ConflictResolutionSchema,
                system_prompt=MultiPOCPromptTemplates.CONFLICT_RESOLUTION_SYSTEM,
            )

            logger.info(
                f"Conflict '{conflict.field}' resolved: "
                f"correct={resolution.correct_poc_id}, "
                f"incorrect={resolution.incorrect_poc_ids}"
            )

            # Create resolved conflict
            resolved = DataConflict(
                field=conflict.field,
                poc_values=conflict.poc_values,
                resolution_reasoning=resolution.reasoning,
                correct_poc_id=resolution.correct_poc_id,
                incorrect_poc_ids=list(resolution.incorrect_poc_ids),
            )
            resolved_conflicts.append(resolved)

            # Track POCs that provided incorrect data
            all_incorrect_pocs.update(resolution.incorrect_poc_ids)

        # Create progress message
        correct_pocs = {c.correct_poc_id for c in resolved_conflicts if c.correct_poc_id}
        progress_msg = (
            f"Resolved {len(resolved_conflicts)} conflict(s). "
            f"Correct sources: {', '.join(correct_pocs)}. "
            f"POCs needing correction: {len(all_incorrect_pocs)}"
        )

        logger.info(
            f"Conflict resolution complete: {len(all_incorrect_pocs)} POCs "
            "may need to re-provide data"
        )

        return {
            "conflicts": [c.to_dict() for c in resolved_conflicts],
            "poc_ids_needing_retry": list(all_incorrect_pocs),
            "current_node": "resolve_conflicts",
            "progress_messages": [progress_msg],
        }

    except Exception as e:
        error_msg = f"Failed to resolve conflicts: {e}"
        logger.error(error_msg, exc_info=True)
        return {
            "error": error_msg,
            "current_node": "error",
            "progress_messages": [f"ERROR: {error_msg}"],
        }


def needs_conflict_retry(state: AgentState) -> bool:
    """Check if any POCs need to retry due to conflicts."""
    poc_ids = state.get("poc_ids_needing_retry", [])
    return len(poc_ids) > 0
