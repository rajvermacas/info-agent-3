"""
Validate Response Node - Check if POC response satisfies the request.

Uses LLM to analyze extracted content against success criteria.
Also detects redirect responses where POC suggests another contact.
"""

import logging
from typing import Any

from mail_agent.agent.state import (
    AgentState,
    ValidationResult,
    get_conversation,
    get_parsed_request,
    update_conversation,
)
from mail_agent.config import get_settings
from mail_agent.llm.client import LLMClient
from mail_agent.llm.prompts import PromptTemplates
from mail_agent.llm.prompts import ValidationResult as ValidationResultSchema


logger = logging.getLogger(__name__)


async def validate_response(state: AgentState) -> dict[str, Any]:
    """
    Validate the POC's response against the original request.

    This node:
    1. Gets the extracted content from state
    2. Calls LLM to validate against success criteria
    3. Records validation result in conversation

    Args:
        state: Current agent state with _extracted_content.

    Returns:
        State update with validation result.
    """
    current_poc = state.get("current_poc")
    if not current_poc:
        logger.error("No current POC set for validate_response")
        return {
            "error": "No current POC set",
            "current_node": "error",
            "progress_messages": ["ERROR: No current POC set for validation"],
        }

    logger.info(f"Validating response from POC: {current_poc}")

    try:
        # Get conversation state
        conversation = get_conversation(state, current_poc)
        conversation.status = "validating"

        # Get parsed request
        parsed_request = get_parsed_request(state)

        # Get extracted content from state
        extracted_content = state.get("_extracted_content", "")
        headers = state.get("_extracted_headers", [])
        row_count = state.get("_extracted_row_count", 0)

        # Get email body text for redirect detection
        email_body_text = state.get("_fetched_body_text", "")

        settings = get_settings()
        llm_client = LLMClient(settings)

        logger.info(
            f"Validating: content_length={len(extracted_content)}, "
            f"max_chars={settings.validation_content_max_chars}, "
            f"truncated={len(extracted_content) > settings.validation_content_max_chars}, "
            f"headers={headers}, row_count={row_count}, "
            f"body_text_length={len(email_body_text)}"
        )

        # Generate validation prompt
        prompt = PromptTemplates.validate_response(
            request_description=parsed_request.request_description,
            success_criteria=parsed_request.success_criteria,
            extracted_content=extracted_content,
            row_count=row_count,
            headers=headers,
            max_content_chars=settings.validation_content_max_chars,
            email_body_text=email_body_text,
        )

        # Call LLM for validation
        validation = await llm_client.generate_structured(
            prompt=prompt,
            output_schema=ValidationResultSchema,
            system_prompt=PromptTemplates.VALIDATE_SYSTEM,
        )

        # Check for redirect
        is_redirect = (
            validation.redirect.is_redirect
            if hasattr(validation, "redirect") and validation.redirect
            else False
        )
        redirect_email = (
            validation.redirect.redirect_email
            if is_redirect and validation.redirect.redirect_email
            else None
        )
        redirect_reason = (
            validation.redirect.redirect_reason
            if is_redirect and validation.redirect.redirect_reason
            else None
        )

        logger.info(
            f"Validation result: is_valid={validation.is_valid}, "
            f"is_redirect={is_redirect}, redirect_email={redirect_email}, "
            f"feedback={validation.feedback[:100]}..."
        )

        # Record validation result
        result = ValidationResult(
            attempt=conversation.attempt_count,
            is_valid=validation.is_valid,
            feedback=validation.feedback,
            missing_items=validation.missing_items,
        )
        conversation.validation_results.append(result)

        if is_redirect and redirect_email:
            # Redirect detected - POC suggested another contact
            progress_msg = (
                f"REDIRECT from {current_poc}: {redirect_reason or 'Not the right contact'}. "
                f"Redirecting to: {redirect_email}"
            )
        elif validation.is_valid:
            # Success!
            conversation.status = "success"
            conversation.final_result = "success"
            progress_msg = f"VALID response from {current_poc}: {validation.feedback}"
        else:
            # Invalid - will need follow-up or fail
            progress_msg = (
                f"INVALID response from {current_poc}: {validation.feedback}"
            )
            if validation.missing_items:
                progress_msg += f" Missing: {', '.join(validation.missing_items)}"

        return {
            "conversations": update_conversation(state, current_poc, conversation),
            "current_node": "validate_response",
            "progress_messages": [progress_msg],
            "_validation_is_valid": validation.is_valid,
            "_validation_feedback": validation.feedback,
            "_validation_missing_items": validation.missing_items,
            # Redirect information
            "_redirect_detected": is_redirect,
            "_redirect_email": redirect_email,
            "_redirect_reason": redirect_reason,
            # Clear extraction data
            "_extracted_content": None,
            "_extracted_headers": None,
            "_extracted_row_count": None,
        }

    except Exception as e:
        error_msg = f"Failed to validate response from {current_poc}: {e}"
        logger.error(error_msg)

        try:
            conversation = get_conversation(state, current_poc)
            conversation.status = "failed"
            conversation.error_message = error_msg
            return {
                "conversations": update_conversation(state, current_poc, conversation),
                "current_node": "error",
                "progress_messages": [f"ERROR: {error_msg}"],
            }
        except Exception:
            return {
                "error": error_msg,
                "current_node": "error",
                "progress_messages": [f"ERROR: {error_msg}"],
            }
