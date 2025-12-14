"""
Parse Instruction Node - Extract structured data from user instruction.

Uses LLM to parse natural language instruction into POC emails,
request description, and success criteria.
"""

import logging
from typing import Any

from mail_agent.agent.state import AgentState, ConversationState, ParsedRequest
from mail_agent.config import get_settings
from mail_agent.llm.client import LLMClient
from mail_agent.llm.prompts import ParsedInstruction, PromptTemplates


logger = logging.getLogger(__name__)


async def parse_instruction(state: AgentState) -> dict[str, Any]:
    """
    Parse user instruction to extract structured request data.

    This node:
    1. Sends the user instruction to LLM for parsing
    2. Extracts POC emails, request description, success criteria
    3. Initializes conversation state for each POC

    Args:
        state: Current agent state with user_instruction.

    Returns:
        State update with parsed_request and initialized conversations.
    """
    logger.info("Parsing user instruction")

    user_instruction = state.get("user_instruction")
    if not user_instruction:
        logger.error("No user instruction provided")
        return {
            "error": "No user instruction provided",
            "current_node": "error",
            "progress_messages": ["ERROR: No user instruction provided"],
        }

    logger.debug(f"User instruction: {user_instruction}")

    try:
        settings = get_settings()
        llm_client = LLMClient(settings)

        # Generate prompt and call LLM
        prompt = PromptTemplates.parse_instruction(user_instruction)
        parsed = await llm_client.generate_structured(
            prompt=prompt,
            output_schema=ParsedInstruction,
            system_prompt=PromptTemplates.PARSE_SYSTEM,
        )

        logger.info(
            f"Parsed instruction: poc_emails={parsed.poc_emails}, "
            f"request_type={parsed.request_type}, "
            f"expected_format={parsed.expected_format}"
        )
        logger.debug(f"Success criteria: {parsed.success_criteria}")

        # Validate we have at least one POC
        if not parsed.poc_emails:
            logger.error("No POC emails found in instruction")
            return {
                "error": "No email addresses found in instruction",
                "current_node": "error",
                "progress_messages": [
                    "ERROR: Could not find any email addresses in the instruction"
                ],
            }

        # Create parsed request
        parsed_request = ParsedRequest(
            poc_emails=parsed.poc_emails,
            request_type=parsed.request_type,
            request_description=parsed.request_description,
            success_criteria=parsed.success_criteria,
            expected_format=parsed.expected_format,
        )

        # Initialize conversation state for each POC
        conversations = {}
        for poc_email in parsed.poc_emails:
            conv = ConversationState(poc_email=poc_email, status="pending")
            conversations[poc_email] = conv.to_dict()
            logger.debug(f"Initialized conversation for POC: {poc_email}")

        progress_msg = (
            f"Parsed instruction: {len(parsed.poc_emails)} POC(s) found. "
            f"Request: {parsed.request_description[:50]}..."
        )

        return {
            "parsed_request": parsed_request.to_dict(),
            "conversations": conversations,
            "current_node": "parse_instruction",
            "current_poc": parsed.poc_emails[0],  # Start with first POC
            "progress_messages": [progress_msg],
        }

    except Exception as e:
        error_msg = f"Failed to parse instruction: {e}"
        logger.error(error_msg)
        return {
            "error": error_msg,
            "current_node": "error",
            "progress_messages": [f"ERROR: {error_msg}"],
        }
