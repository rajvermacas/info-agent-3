"""
Validate POC Response Node - Per-POC validation against specific success criteria.

Validates a single POC's response against their individual success criteria,
detecting redirects and determining if retry is needed.
"""

import logging
from typing import Any

from mail_agent.agent.multi_poc_helpers import (
    get_poc_requirement,
    get_poc_state,
    update_poc_state,
)
from mail_agent.agent.multi_poc_state import (
    POCStatus,
    POCValidationResult,
)
from mail_agent.agent.state import AgentState
from mail_agent.config import get_settings
from mail_agent.llm.client import LLMClient
from mail_agent.llm.multi_poc_prompts import (
    MultiPOCPromptTemplates,
    POCValidationResultSchema,
)


logger = logging.getLogger(__name__)


async def validate_poc_response(state: AgentState) -> dict[str, Any]:
    """
    Validate current POC's response against their specific success criteria.

    This node:
    1. Gets the current POC's extracted content and success criteria
    2. Uses LLM to validate response against criteria
    3. Detects redirect suggestions in the response
    4. Updates POCState with validation result

    Args:
        state: Current agent state with current_poc_id and extracted content.

    Returns:
        State update with POCValidationResult in poc_states.
    """
    current_poc_id = state.get("current_poc_id")
    if not current_poc_id:
        error_msg = "No current_poc_id set for validate_poc_response"
        logger.error(error_msg)
        return {
            "error": error_msg,
            "current_node": "error",
            "progress_messages": [f"ERROR: {error_msg}"],
        }

    logger.info(f"Validating response for POC: {current_poc_id}")

    try:
        poc_requirement = get_poc_requirement(state, current_poc_id)
        poc_state = get_poc_state(state, current_poc_id)

        # Get extracted content from state or POC state
        extracted_content = state.get("_extracted_content", "")
        row_count = state.get("_extracted_row_count", 0)
        headers = state.get("_extracted_headers", [])
        email_body = state.get("_email_body_text", "")

        # Also check POC state for extracted data
        if not extracted_content and poc_state.extracted_data:
            extracted_content = str(poc_state.extracted_data)

        if not extracted_content:
            logger.warning(f"No extracted content for POC {current_poc_id}")
            extracted_content = "(No content extracted)"

        logger.debug(
            f"Validating: content_len={len(extracted_content)}, "
            f"rows={row_count}, headers={headers}"
        )

        settings = get_settings()
        llm_client = LLMClient(settings)

        # Generate validation prompt
        prompt = MultiPOCPromptTemplates.validate_poc_response(
            poc_id=current_poc_id,
            poc_email=poc_requirement.email,
            request=poc_requirement.request,
            success_criteria=poc_requirement.success_criteria,
            extracted_content=extracted_content,
            row_count=row_count,
            headers=headers,
            email_body_text=email_body if email_body else None,
        )

        # Call LLM for validation
        validation_result: POCValidationResultSchema = await llm_client.generate_structured(
            prompt=prompt,
            output_schema=POCValidationResultSchema,
            system_prompt=MultiPOCPromptTemplates.POC_VALIDATION_SYSTEM,
        )

        logger.info(
            f"Validation result for {current_poc_id}: "
            f"valid={validation_result.valid}, "
            f"should_retry={validation_result.should_retry}, "
            f"should_redirect={validation_result.should_redirect}"
        )

        # Convert to internal POCValidationResult
        poc_validation = POCValidationResult(
            valid=validation_result.valid,
            criteria_met=list(validation_result.criteria_met),
            criteria_missing=list(validation_result.criteria_missing),
            should_retry=validation_result.should_retry,
            should_redirect=validation_result.should_redirect,
            redirect_email=validation_result.redirect_email,
            reasoning=validation_result.reasoning,
        )

        # Update POC state with validation result
        poc_state.validation_result = poc_validation

        # Determine new status based on validation
        if validation_result.valid:
            poc_state.status = POCStatus.COMPLETED
            logger.info(f"POC {current_poc_id} completed successfully")
        elif validation_result.should_redirect:
            # Status will be updated by handle_redirect node
            logger.info(
                f"POC {current_poc_id} suggests redirect to "
                f"{validation_result.redirect_email}"
            )
        elif validation_result.should_retry:
            # Check attempt count
            poc_state.attempts += 1
            if poc_state.attempts >= poc_state.max_attempts:
                poc_state.status = POCStatus.FAILED
                logger.warning(
                    f"POC {current_poc_id} exceeded max attempts "
                    f"({poc_state.max_attempts})"
                )
            else:
                # Will retry - keep in WAITING or IN_PROGRESS
                logger.info(
                    f"POC {current_poc_id} needs retry "
                    f"(attempt {poc_state.attempts}/{poc_state.max_attempts})"
                )
        else:
            # Not valid but no retry/redirect - mark as failed
            poc_state.status = POCStatus.FAILED
            logger.warning(
                f"POC {current_poc_id} validation failed with no retry option"
            )

        updated_poc_states = update_poc_state(state, current_poc_id, poc_state)

        # Create progress message
        if validation_result.valid:
            criteria_summary = ", ".join(validation_result.criteria_met[:3])
            if len(validation_result.criteria_met) > 3:
                criteria_summary += f" (+{len(validation_result.criteria_met) - 3} more)"
            progress_msg = (
                f"POC {current_poc_id} validated successfully: {criteria_summary}"
            )
        elif validation_result.should_redirect:
            progress_msg = (
                f"POC {current_poc_id} suggests redirect to "
                f"{validation_result.redirect_email}"
            )
        elif validation_result.should_retry:
            missing_summary = ", ".join(validation_result.criteria_missing[:2])
            if len(validation_result.criteria_missing) > 2:
                missing_summary += f" (+{len(validation_result.criteria_missing) - 2})"
            progress_msg = (
                f"POC {current_poc_id} needs retry. Missing: {missing_summary}"
            )
        else:
            progress_msg = f"POC {current_poc_id} validation failed: {validation_result.reasoning[:100]}"

        return {
            "poc_states": updated_poc_states,
            "current_node": "validate_poc_response",
            "progress_messages": [progress_msg],
            # Store validation result for decision nodes
            "_poc_validation_valid": validation_result.valid,
            "_poc_validation_should_retry": validation_result.should_retry,
            "_poc_validation_should_redirect": validation_result.should_redirect,
            "_poc_validation_redirect_email": validation_result.redirect_email,
        }

    except Exception as e:
        error_msg = f"Failed to validate response for {current_poc_id}: {e}"
        logger.error(error_msg, exc_info=True)

        # Mark POC as failed
        try:
            poc_state = get_poc_state(state, current_poc_id)
            poc_state.status = POCStatus.FAILED
            updated_poc_states = update_poc_state(state, current_poc_id, poc_state)
            return {
                "poc_states": updated_poc_states,
                "error": error_msg,
                "current_node": "error",
                "progress_messages": [f"ERROR: {error_msg}"],
            }
        except Exception:
            return {
                "error": error_msg,
                "current_node": "error",
                "progress_messages": [f"ERROR: {error_msg}"],
            }
