"""Decide next node - determines routing based on conversation status."""

import json
import logging
from datetime import datetime

from mail_agent.agent.state import AgentState
from mail_agent.config import get_settings
from mail_agent.llm.client import GeminiClient, LLMError
from mail_agent.llm.prompts import PromptTemplates

logger = logging.getLogger(__name__)


async def decide_next_node(state: AgentState) -> dict:
    """Decide next action based on conversation states.

    This node:
    1. Checks all conversation statuses
    2. If any "success": continues with next pending POC
    3. If any "pending" (invalid but retries left): send follow-up email
    4. If all "failed" or "success": moves to end (final summary)
    5. Returns control flow dict with next node name

    Control flow:
    - "compose_followup" -> send follow-up email
    - "compose_email" -> send initial email to next POC
    - "end" -> generate final summary

    Args:
        state: Current agent state with all conversation states

    Returns:
        dict: Control flow dict with "next_node" key and updated state

    Raises:
        ValueError: If state structure invalid
    """
    logger.info("decide_next_node: Starting")

    # Validate inputs
    parsed_request = state.get("parsed_request")
    conversations = state.get("conversations", {})

    if not parsed_request:
        error_msg = "parsed_request is required in state"
        logger.error(f"decide_next_node: {error_msg}")
        raise ValueError(error_msg)

    if not conversations:
        error_msg = "conversations is required in state"
        logger.error(f"decide_next_node: {error_msg}")
        raise ValueError(error_msg)

    try:
        logger.debug("decide_next_node: Analyzing conversation states")

        # Count conversation states
        success_count = 0
        failed_count = 0
        pending_count = 0
        validating_count = 0
        waiting_count = 0
        pending_followup_count = 0

        for poc_email, conv in conversations.items():
            status = conv.get("status", "pending")

            if status == "success":
                success_count += 1
            elif status == "failed":
                failed_count += 1
            elif status == "pending":
                # Check if this is first attempt or follow-up
                if conv.get("attempt_count", 0) > 0:
                    pending_followup_count += 1
                else:
                    pending_count += 1
            elif status == "validating":
                validating_count += 1
            elif status == "waiting":
                waiting_count += 1

        logger.info(
            f"decide_next_node: Status summary - "
            f"success={success_count}, failed={failed_count}, "
            f"pending={pending_count}, pending_followup={pending_followup_count}, "
            f"waiting={waiting_count}, validating={validating_count}"
        )

        # Determine next action
        next_node = None

        # Priority 1: Handle follow-ups for invalid responses
        if pending_followup_count > 0:
            logger.info("decide_next_node: Routing to compose_followup for invalid response follow-up")
            next_node = "compose_followup"

        # Priority 2: Send initial emails to pending POCs
        elif pending_count > 0:
            logger.info("decide_next_node: Routing to compose_email for next pending POC")
            next_node = "compose_email"

        # Priority 3: Still processing (waiting or validating)
        elif waiting_count > 0 or validating_count > 0:
            logger.info(
                f"decide_next_node: Still processing emails "
                f"(waiting={waiting_count}, validating={validating_count})"
            )
            # Wait for completion - stay in waiting
            next_node = "wait_for_reply"

        # Priority 4: All conversations complete
        else:
            logger.info("decide_next_node: All conversations complete, routing to end")
            next_node = "end"

        state["current_node"] = "decide_next"
        state["progress_messages"].append(
            f"Decision: {success_count} success, {failed_count} failed, routing to {next_node}"
        )

        logger.info(f"decide_next_node: Completed successfully, next_node={next_node}")

        return {"next_node": next_node, "state": state}

    except Exception as e:
        error_msg = f"Unexpected error deciding next: {str(e)}"
        logger.error(f"decide_next_node: {error_msg}")
        raise


async def compose_followup_node(state: AgentState) -> AgentState:
    """Compose follow-up email for invalid response.

    This node:
    1. Finds POC with "pending" status and previous attempts
    2. Gets validation feedback from previous attempt
    3. Uses LLM to compose follow-up email
    4. Returns state for send_email node

    Args:
        state: Current agent state

    Returns:
        AgentState: Updated state with _composed_email for follow-up

    Raises:
        ValueError: If no follow-up candidate found
        LLMError: If LLM composition fails
    """
    logger.info("compose_followup_node: Starting")

    # Validate inputs
    parsed_request = state.get("parsed_request")
    conversations = state.get("conversations", {})

    if not parsed_request:
        error_msg = "parsed_request is required in state"
        logger.error(f"compose_followup_node: {error_msg}")
        raise ValueError(error_msg)

    if not conversations:
        error_msg = "conversations is required in state"
        logger.error(f"compose_followup_node: {error_msg}")
        raise ValueError(error_msg)

    # Find POC needing follow-up
    followup_poc = None
    for poc_email in parsed_request["poc_emails"]:
        conv = conversations.get(poc_email, {})
        status = conv.get("status", "pending")
        attempt = conv.get("attempt_count", 0)

        if status == "pending" and attempt > 0:
            followup_poc = poc_email
            break

    if not followup_poc:
        error_msg = "No POC found needing follow-up"
        logger.error(f"compose_followup_node: {error_msg}")
        raise ValueError(error_msg)

    logger.info(f"compose_followup_node: Composing follow-up for {followup_poc}")

    try:
        # Get conversation data
        conversation = conversations[followup_poc]
        validation_results = conversation.get("validation_results", [])

        if not validation_results:
            error_msg = f"No validation results for {followup_poc}"
            logger.error(f"compose_followup_node: {error_msg}")
            raise ValueError(error_msg)

        # Get feedback from last validation
        last_validation = validation_results[-1]
        feedback = last_validation.get("feedback", "Response was incomplete")

        # Get LLM client
        settings = get_settings()
        llm_client = GeminiClient(settings)

        # Generate follow-up prompt
        request_description = parsed_request.get("request_description", "")
        attempt_count = conversation.get("attempt_count", 1)
        max_attempts = settings.max_attempts

        logger.debug(
            f"compose_followup_node: attempt={attempt_count}, max={max_attempts}, "
            f"feedback={feedback[:100]}"
        )

        prompt = PromptTemplates.compose_followup(
            request_description,
            feedback,
            attempt_count,
            max_attempts
        )

        logger.debug("compose_followup_node: Invoking LLM to compose follow-up")

        # Call LLM
        response = await llm_client.ainvoke(prompt)

        logger.debug("compose_followup_node: LLM response received")

        # Parse JSON response
        email_data = PromptTemplates.parse_llm_json_response(response)

        # Validate response
        if "subject" not in email_data or not email_data["subject"].strip():
            error_msg = "LLM response missing or empty 'subject' field"
            logger.error(f"compose_followup_node: {error_msg}")
            raise ValueError(error_msg)

        if "body" not in email_data or not email_data["body"].strip():
            error_msg = "LLM response missing or empty 'body' field"
            logger.error(f"compose_followup_node: {error_msg}")
            raise ValueError(error_msg)

        logger.info(
            f"compose_followup_node: Successfully composed follow-up for {followup_poc}: "
            f"subject_len={len(email_data['subject'])}"
        )

        # Store in state
        state["_composed_email"] = {
            "poc_email": followup_poc,
            "subject": email_data["subject"],
            "body": email_data["body"],
        }

        state["current_node"] = "compose_followup"
        state["progress_messages"].append(f"Composed follow-up email for {followup_poc}")

        logger.info("compose_followup_node: Completed successfully")

        return state

    except LLMError as e:
        error_msg = f"LLM error composing follow-up: {str(e)}"
        logger.error(f"compose_followup_node: {error_msg}")
        raise

    except (ValueError, json.JSONDecodeError) as e:
        error_msg = f"Invalid response composing follow-up: {str(e)}"
        logger.error(f"compose_followup_node: {error_msg}")
        raise

    except Exception as e:
        error_msg = f"Unexpected error composing follow-up: {str(e)}"
        logger.error(f"compose_followup_node: {error_msg}")
        raise
