"""Compose email node - generates email with LLM."""

import json
import logging
from typing import Optional

from mail_agent.agent.state import AgentState, SentEmail
from mail_agent.config import get_settings
from mail_agent.llm.client import GeminiClient, LLMError
from mail_agent.llm.prompts import PromptTemplates

logger = logging.getLogger(__name__)


async def compose_email_node(state: AgentState) -> AgentState:
    """Compose email for next POC using LLM.

    This node:
    1. Finds next POC email in pending status
    2. Uses LLM to generate email subject and body
    3. Returns email composition without sending (sending done in next node)
    4. Stores composed email in state for send_email node to use

    Args:
        state: Current agent state with parsed_request

    Returns:
        AgentState: Updated state with composed_email (temporary, used by next node)

    Raises:
        ValueError: If no pending POC found or parsed_request missing
        LLMError: If LLM email composition fails
    """
    logger.info("compose_email_node: Starting")

    # Validate inputs
    parsed_request = state.get("parsed_request")
    conversations = state.get("conversations", {})

    if not parsed_request:
        error_msg = "parsed_request is required in state"
        logger.error(f"compose_email_node: {error_msg}")
        raise ValueError(error_msg)

    if not conversations:
        error_msg = "conversations is required in state"
        logger.error(f"compose_email_node: {error_msg}")
        raise ValueError(error_msg)

    # Find next pending POC email
    current_poc = None
    for poc_email in parsed_request["poc_emails"]:
        conv = conversations.get(poc_email, {})
        status = conv.get("status", "pending")

        if status == "pending":
            current_poc = poc_email
            break
        elif status == "waiting":
            # Still waiting on a previous email - try this one
            attempt = conv.get("attempt_count", 0)
            if attempt > 0:
                # This is a follow-up, skip for now
                continue
            current_poc = poc_email
            break

    if not current_poc:
        logger.debug("compose_email_node: No pending POC found, using first POC for next attempt")
        current_poc = parsed_request["poc_emails"][0]

    logger.info(f"compose_email_node: Composing email for POC: {current_poc}")

    try:
        # Get LLM client
        settings = get_settings()
        llm_client = GeminiClient(settings)

        # Get request description
        request_description = parsed_request.get("request_description", "")
        if not request_description:
            error_msg = "request_description missing from parsed_request"
            logger.error(f"compose_email_node: {error_msg}")
            raise ValueError(error_msg)

        logger.debug(f"compose_email_node: Request description: {request_description}")

        # Generate prompt for composing email
        prompt = PromptTemplates.compose_email(current_poc, request_description)

        logger.debug("compose_email_node: Invoking LLM to compose email")

        # Call LLM
        response = await llm_client.ainvoke(prompt)

        logger.debug(f"compose_email_node: LLM response received (length={len(response)})")

        # Parse JSON response
        email_data = PromptTemplates.parse_llm_json_response(response)

        logger.debug(f"compose_email_node: Parsed email data: subject={email_data.get('subject')}")

        # Validate response
        if "subject" not in email_data or not email_data["subject"].strip():
            error_msg = "LLM response missing or empty 'subject' field"
            logger.error(f"compose_email_node: {error_msg}")
            raise ValueError(error_msg)

        if "body" not in email_data or not email_data["body"].strip():
            error_msg = "LLM response missing or empty 'body' field"
            logger.error(f"compose_email_node: {error_msg}")
            raise ValueError(error_msg)

        logger.info(
            f"compose_email_node: Successfully composed email for {current_poc}: "
            f"subject_len={len(email_data['subject'])}, body_len={len(email_data['body'])}"
        )

        # Store in state as temporary data for send_email node
        state["_composed_email"] = {
            "poc_email": current_poc,
            "subject": email_data["subject"],
            "body": email_data["body"],
        }

        state["current_node"] = "compose_email"
        state["progress_messages"].append(f"Composed email for {current_poc}")

        logger.info("compose_email_node: Completed successfully")

        return state

    except LLMError as e:
        error_msg = f"LLM error composing email: {str(e)}"
        logger.error(f"compose_email_node: {error_msg}")
        raise

    except (ValueError, json.JSONDecodeError) as e:
        error_msg = f"Invalid response composing email: {str(e)}"
        logger.error(f"compose_email_node: {error_msg}")
        raise

    except Exception as e:
        error_msg = f"Unexpected error composing email: {str(e)}"
        logger.error(f"compose_email_node: {error_msg}")
        raise
