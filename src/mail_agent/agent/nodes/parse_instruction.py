"""Parse instruction node - parses user instruction into structured request."""

import json
import logging
from typing import Optional

from mail_agent.agent.state import AgentState, ParsedRequest
from mail_agent.config import get_settings
from mail_agent.llm.client import GeminiClient, LLMError
from mail_agent.llm.prompts import PromptTemplates

logger = logging.getLogger(__name__)


async def parse_instruction_node(state: AgentState) -> AgentState:
    """Parse user instruction into structured request.

    This node:
    1. Takes user_instruction from state
    2. Uses LLM to extract structure (POC emails, request type, etc.)
    3. Validates and stores parsed_request in state
    4. Initializes conversation state for each POC email
    5. Returns updated state

    Args:
        state: Current agent state with user_instruction

    Returns:
        AgentState: Updated state with parsed_request and initialized conversations

    Raises:
        ValueError: If user_instruction is missing or empty
        LLMError: If LLM parsing fails
        json.JSONDecodeError: If LLM response is not valid JSON
    """
    logger.info("parse_instruction_node: Starting")

    # Validate input
    user_instruction = state.get("user_instruction")
    if not user_instruction or not user_instruction.strip():
        error_msg = "user_instruction is required"
        logger.error(f"parse_instruction_node: {error_msg}")
        raise ValueError(error_msg)

    logger.debug(f"parse_instruction_node: Parsing instruction (length={len(user_instruction)})")

    try:
        # Get settings and LLM client
        settings = get_settings()
        llm_client = GeminiClient(settings)

        # Generate prompt
        prompt = PromptTemplates.parse_instruction(user_instruction)

        logger.debug("parse_instruction_node: Invoking LLM to parse instruction")

        # Call LLM
        response = await llm_client.ainvoke(prompt)

        logger.debug(f"parse_instruction_node: LLM response received (length={len(response)})")

        # Parse JSON response
        parsed_data = PromptTemplates.parse_llm_json_response(response)

        logger.debug(f"parse_instruction_node: Parsed data: {parsed_data}")

        # Validate required fields
        if "poc_emails" not in parsed_data:
            error_msg = "LLM response missing 'poc_emails' field"
            logger.error(f"parse_instruction_node: {error_msg}")
            raise ValueError(error_msg)

        if not parsed_data["poc_emails"] or len(parsed_data["poc_emails"]) == 0:
            error_msg = "LLM response contains no POC emails"
            logger.error(f"parse_instruction_node: {error_msg}")
            raise ValueError(error_msg)

        # Create ParsedRequest
        parsed_request: ParsedRequest = {
            "poc_emails": parsed_data.get("poc_emails", []),
            "request_type": parsed_data.get("request_type", "unknown"),
            "request_description": parsed_data.get("request_description", ""),
            "success_criteria": parsed_data.get("success_criteria", ""),
        }

        logger.info(
            f"parse_instruction_node: Successfully parsed instruction: "
            f"poc_emails={len(parsed_request['poc_emails'])}, "
            f"request_type={parsed_request['request_type']}"
        )

        # Initialize conversation state for each POC email
        conversations = {}
        for poc_email in parsed_request["poc_emails"]:
            conversations[poc_email] = {
                "status": "pending",
                "attempt_count": 0,
                "sent_emails": [],
                "received_emails": [],
                "validation_results": [],
                "final_result": None,
                "error": None,
            }

        logger.debug(f"parse_instruction_node: Initialized {len(conversations)} conversations")

        # Update state
        state["parsed_request"] = parsed_request
        state["conversations"] = conversations
        state["progress_messages"].append(
            f"Parsed request: {parsed_request['request_type']} for {len(parsed_request['poc_emails'])} POCs"
        )

        logger.info("parse_instruction_node: Completed successfully")

        return state

    except LLMError as e:
        error_msg = f"LLM error parsing instruction: {str(e)}"
        logger.error(f"parse_instruction_node: {error_msg}")
        raise

    except (ValueError, json.JSONDecodeError) as e:
        error_msg = f"Invalid response parsing instruction: {str(e)}"
        logger.error(f"parse_instruction_node: {error_msg}")
        raise

    except Exception as e:
        error_msg = f"Unexpected error parsing instruction: {str(e)}"
        logger.error(f"parse_instruction_node: {error_msg}")
        raise
