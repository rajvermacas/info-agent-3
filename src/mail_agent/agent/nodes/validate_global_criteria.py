"""
Validate Global Criteria Node - Validate aggregated data against global success criteria.

Checks if the combined data from all POCs satisfies the overall request
requirements defined in global_success_criteria.
"""

import json
import logging
from typing import Any

from mail_agent.agent.multi_poc_helpers import (
    get_completed_pocs,
    get_execution_plan,
    get_poc_state,
)
from mail_agent.agent.multi_poc_state import GlobalValidationResult
from mail_agent.agent.state import AgentState
from mail_agent.config import get_settings
from mail_agent.llm.client import LLMClient
from mail_agent.llm.multi_poc_prompts import (
    GlobalValidationResultSchema,
    MultiPOCPromptTemplates,
)


logger = logging.getLogger(__name__)


async def validate_global_criteria(state: AgentState) -> dict[str, Any]:
    """
    Validate aggregated data against global success criteria.

    This node:
    1. Gets aggregated_data and global_success_criteria
    2. Builds summary of each POC's contribution
    3. Uses LLM to validate if overall request is satisfied
    4. Returns GlobalValidationResult

    Args:
        state: Current agent state with aggregated_data and execution_plan.

    Returns:
        State update with global_validation_result.
    """
    logger.info("Validating against global success criteria")

    try:
        execution_plan = get_execution_plan(state)
        aggregated_data = state.get("aggregated_data", {})
        completed_poc_ids = get_completed_pocs(state)

        global_criteria = execution_plan.global_success_criteria

        if not global_criteria:
            logger.warning("No global success criteria defined")
            # Assume success if all POCs completed
            result = GlobalValidationResult(
                valid=True,
                all_criteria_met=True,
                reasoning="No global criteria defined - all POCs completed",
            )
            return {
                "global_validation_result": result.to_dict(),
                "current_node": "validate_global_criteria",
                "progress_messages": ["Global validation: All POCs completed"],
            }

        # Build POC summaries for LLM context
        poc_summaries: list[dict[str, str]] = []

        for poc_id in completed_poc_ids:
            try:
                poc_state = get_poc_state(state, poc_id)
                poc = next(
                    (p for p in execution_plan.pocs if p.id == poc_id),
                    None
                )

                extracted_data = poc_state.extracted_data or {}
                data_summary = _summarize_data(extracted_data)

                poc_summaries.append({
                    "poc_id": poc_id,
                    "email": poc.email if poc else "unknown",
                    "status": poc_state.status.value,
                    "data_summary": data_summary,
                })

            except (KeyError, ValueError) as e:
                logger.warning(f"Could not get summary for POC {poc_id}: {e}")
                poc_summaries.append({
                    "poc_id": poc_id,
                    "email": "unknown",
                    "status": "error",
                    "data_summary": f"Error: {e}",
                })

        # Create aggregated data summary
        aggregated_summary = _summarize_data(aggregated_data, max_items=20)

        logger.debug(f"Aggregated summary: {aggregated_summary[:200]}...")

        settings = get_settings()
        llm_client = LLMClient(settings)

        # Generate validation prompt
        prompt = MultiPOCPromptTemplates.validate_global_criteria(
            global_success_criteria=global_criteria,
            aggregated_data_summary=aggregated_summary,
            poc_summaries=poc_summaries,
        )

        # Call LLM for validation
        validation_result: GlobalValidationResultSchema = await llm_client.generate_structured(
            prompt=prompt,
            output_schema=GlobalValidationResultSchema,
            system_prompt=MultiPOCPromptTemplates.GLOBAL_VALIDATION_SYSTEM,
        )

        logger.info(
            f"Global validation result: valid={validation_result.valid}, "
            f"all_criteria_met={validation_result.all_criteria_met}"
        )

        # Convert to internal GlobalValidationResult
        result = GlobalValidationResult(
            valid=validation_result.valid,
            all_criteria_met=validation_result.all_criteria_met,
            missing_data=list(validation_result.missing_data),
            poc_ids_needing_retry=list(validation_result.poc_ids_needing_retry),
            reasoning=validation_result.reasoning,
        )

        # Create progress message
        if validation_result.valid:
            progress_msg = "Global validation passed: All criteria satisfied"
        else:
            missing_summary = ", ".join(validation_result.missing_data[:3])
            if len(validation_result.missing_data) > 3:
                missing_summary += f" (+{len(validation_result.missing_data) - 3})"
            progress_msg = f"Global validation failed. Missing: {missing_summary}"

        logger.info(
            f"Global validation complete: valid={result.valid}, "
            f"missing={len(result.missing_data)}, "
            f"retry_pocs={len(result.poc_ids_needing_retry)}"
        )

        return {
            "global_validation_result": result.to_dict(),
            "current_node": "validate_global_criteria",
            "progress_messages": [progress_msg],
        }

    except Exception as e:
        error_msg = f"Failed to validate global criteria: {e}"
        logger.error(error_msg, exc_info=True)

        # Return failure result
        result = GlobalValidationResult(
            valid=False,
            all_criteria_met=False,
            reasoning=f"Validation error: {e}",
        )

        return {
            "global_validation_result": result.to_dict(),
            "error": error_msg,
            "current_node": "error",
            "progress_messages": [f"ERROR: {error_msg}"],
        }


def _summarize_data(data: dict[str, Any], max_items: int = 10) -> str:
    """
    Create a concise summary of data dictionary.

    Args:
        data: Dictionary to summarize.
        max_items: Maximum number of items to include.

    Returns:
        String summary of the data.
    """
    if not data:
        return "(empty)"

    try:
        # Try JSON formatting for simple data
        if len(data) <= max_items:
            return json.dumps(data, indent=2, default=str)[:2000]

        # Truncate for large data
        items = list(data.items())[:max_items]
        summary = json.dumps(dict(items), indent=2, default=str)
        return f"{summary}... (+{len(data) - max_items} more items)"

    except Exception:
        # Fallback to simple string representation
        return str(data)[:2000]


def is_global_valid(state: AgentState) -> bool:
    """Check if global validation passed."""
    result = state.get("global_validation_result")
    if not result:
        return False
    return result.get("valid", False)


def get_global_validation_result(state: AgentState) -> GlobalValidationResult | None:
    """Get GlobalValidationResult from state."""
    result = state.get("global_validation_result")
    if not result:
        return None
    return GlobalValidationResult.from_dict(result)
