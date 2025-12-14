"""Fetch email node - fetches full email from Mock SMTP inbox."""

import json
import logging

import httpx

from mail_agent.agent.state import AgentState
from mail_agent.config import get_settings
from mail_agent.tools.inbox_client import InboxClient, EmailFetchError

logger = logging.getLogger(__name__)


async def fetch_email_node(state: AgentState) -> AgentState:
    """Fetch full email details including attachments.

    This node:
    1. Gets received email metadata from state (_received_email)
    2. Uses InboxClient to fetch full email with attachments
    3. Stores full email in state for extract_content node
    4. Returns updated state

    Args:
        state: Current agent state with _received_email from wait_for_reply node

    Returns:
        AgentState: Updated state with _full_email temporary data

    Raises:
        ValueError: If _received_email is missing
        EmailFetchError: If email fetch fails
    """
    logger.info("fetch_email_node: Starting")

    # Validate inputs
    received_email = state.get("_received_email")
    if not received_email:
        error_msg = "_received_email not found in state (wait_for_reply node must run first)"
        logger.error(f"fetch_email_node: {error_msg}")
        raise ValueError(error_msg)

    email_id = received_email.get("email_id")
    from_address = received_email.get("from_address")

    if not email_id or not from_address:
        error_msg = f"Invalid _received_email: missing required fields"
        logger.error(f"fetch_email_node: {error_msg}")
        raise ValueError(error_msg)

    logger.debug(f"fetch_email_node: Fetching email {email_id} from {from_address}")

    try:
        # Get settings and agent email
        settings = get_settings()
        agent_email = settings.agent_email

        if not agent_email:
            error_msg = "agent_email is required in settings"
            logger.error(f"fetch_email_node: {error_msg}")
            raise ValueError(error_msg)

        # Create inbox client and fetch email
        async with httpx.AsyncClient(timeout=30.0) as http_client:
            inbox_client = InboxClient(settings, http_client)
            async with inbox_client:
                full_email = await inbox_client.fetch_email(agent_email, email_id)

        logger.info(
            f"fetch_email_node: Successfully fetched email {email_id}: "
            f"from={from_address}, "
            f"attachments={len(full_email.get('attachments', []))}"
        )

        logger.debug(f"fetch_email_node: Full email keys: {list(full_email.keys())}")

        # Store full email in state
        state["_full_email"] = full_email
        state["current_node"] = "fetch_email"
        state["progress_messages"].append(f"Fetched full email from {from_address}")

        logger.info("fetch_email_node: Completed successfully")

        return state

    except EmailFetchError as e:
        error_msg = f"Email fetch error: {str(e)}"
        logger.error(f"fetch_email_node: {error_msg}")
        raise

    except Exception as e:
        error_msg = f"Unexpected error fetching email: {str(e)}"
        logger.error(f"fetch_email_node: {error_msg}")
        raise
