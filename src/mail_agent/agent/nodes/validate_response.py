"""Validate response node - validates POC response with LLM."""

import json
import logging

from mail_agent.agent.state import AgentState, ValidationResult
from mail_agent.config import get_settings
from mail_agent.llm.client import GeminiClient, LLMError
from mail_agent.llm.prompts import PromptTemplates

logger = logging.getLogger(__name__)


async def validate_response_node(state: AgentState) -> AgentState:
    """Validate POC response against success criteria.

    This node:
    1. Gets extracted content from state (_extracted_content)
    2. Gets success criteria from parsed_request
    3. Uses LLM to validate if response meets criteria
    4. Records validation result in conversation state
    5. If valid: marks as "success", continues to decide_next
    6. If invalid and attempts left: goes to decide_next to send follow-up
    7. If invalid and no attempts: marks as "failed"

    Args:
        state: Current agent state with _extracted_content and parsed_request

    Returns:
        AgentState: Updated state with validation result recorded

    Raises:
        ValueError: If required data missing
        LLMError: If LLM validation fails
    """
    logger.info("validate_response_node: Starting")

    # Validate inputs
    extracted_content = state.get("_extracted_content")
    parsed_request = state.get("parsed_request")
    conversations = state.get("conversations", {})

    if not extracted_content:
        error_msg = "_extracted_content not found in state (extract_content node must run first)"
        logger.error(f"validate_response_node: {error_msg}")
        raise ValueError(error_msg)

    if not parsed_request:
        error_msg = "parsed_request is required in state"
        logger.error(f"validate_response_node: {error_msg}")
        raise ValueError(error_msg)

    if not conversations:
        error_msg = "conversations is required in state"
        logger.error(f"validate_response_node: {error_msg}")
        raise ValueError(error_msg)

    # Find POC in "validating" status
    validating_poc = None
    for poc_email in parsed_request["poc_emails"]:
        conv = conversations.get(poc_email, {})
        if conv.get("status") == "validating":
            validating_poc = poc_email
            break

    if not validating_poc:
        error_msg = "No POC found in 'validating' status"
        logger.error(f"validate_response_node: {error_msg}")
        raise ValueError(error_msg)

    logger.info(f"validate_response_node: Validating response from {validating_poc}")

    try:
        # Get validation data
        content = extracted_content.get("content")
        error = extracted_content.get("error")
        request_description = parsed_request.get("request_description", "")
        success_criteria = parsed_request.get("success_criteria", "")

        # If extraction failed, mark validation as invalid
        if error:
            logger.warning(f"validate_response_node: Extraction error: {error}")
            validation_result: ValidationResult = {
                "attempt": conversations[validating_poc].get("attempt_count", 1),
                "is_valid": False,
                "feedback": f"Extraction failed: {error}",
            }
        else:
            # Use LLM to validate content
            if not content:
                logger.warning("validate_response_node: No content to validate")
                validation_result: ValidationResult = {
                    "attempt": conversations[validating_poc].get("attempt_count", 1),
                    "is_valid": False,
                    "feedback": "No content received in response",
                }
            else:
                # Get LLM client
                settings = get_settings()
                llm_client = GeminiClient(settings)

                logger.debug("validate_response_node: Invoking LLM to validate response")

                # Generate validation prompt
                prompt = PromptTemplates.validate_response(
                    request_description,
                    success_criteria,
                    content
                )

                # Call LLM
                response = await llm_client.ainvoke(prompt)

                logger.debug(f"validate_response_node: LLM response received")

                # Parse validation result
                validation_data = PromptTemplates.parse_llm_json_response(response)

                validation_result: ValidationResult = {
                    "attempt": conversations[validating_poc].get("attempt_count", 1),
                    "is_valid": validation_data.get("is_valid", False),
                    "feedback": validation_data.get("feedback", "No feedback provided"),
                }

                logger.debug(f"validate_response_node: Validation result: {validation_result}")

        # Record validation result
        conversation = conversations[validating_poc]
        validation_results = conversation.get("validation_results", [])
        validation_results.append(validation_result)
        conversation["validation_results"] = validation_results

        # Update conversation status based on validation
        if validation_result["is_valid"]:
            logger.info(f"validate_response_node: Response is valid!")
            conversation["status"] = "success"
            conversation["final_result"] = "success"

        else:
            # Check if we have more attempts left
            settings = get_settings()
            max_attempts = settings.max_attempts
            current_attempt = conversation.get("attempt_count", 0)

            if current_attempt >= max_attempts:
                logger.warning(
                    f"validate_response_node: Max attempts ({max_attempts}) reached"
                )
                conversation["status"] = "failed"
                conversation["final_result"] = "failed_max_attempts"
                conversation["error"] = validation_result["feedback"]

            else:
                logger.info(
                    f"validate_response_node: Response invalid, will send follow-up "
                    f"({current_attempt}/{max_attempts})"
                )
                conversation["status"] = "pending"  # Back to pending for follow-up

        conversations[validating_poc] = conversation

        # Update state
        state["conversations"] = conversations
        state["current_node"] = "validate_response"
        state["progress_messages"].append(
            f"Validation: {'PASSED' if validation_result['is_valid'] else 'FAILED'} - "
            f"{validation_result['feedback'][:100]}"
        )

        # Clean up temporary data
        if "_extracted_content" in state:
            del state["_extracted_content"]
        if "_full_email" in state:
            del state["_full_email"]
        if "_received_email" in state:
            del state["_received_email"]

        logger.info("validate_response_node: Completed successfully")

        return state

    except LLMError as e:
        error_msg = f"LLM error validating response: {str(e)}"
        logger.error(f"validate_response_node: {error_msg}")
        raise

    except (ValueError, json.JSONDecodeError) as e:
        error_msg = f"Invalid response validating: {str(e)}"
        logger.error(f"validate_response_node: {error_msg}")
        raise

    except Exception as e:
        error_msg = f"Unexpected error validating response: {str(e)}"
        logger.error(f"validate_response_node: {error_msg}")
        raise
