"""
Agent Card - A2A protocol metadata configuration.

Creates the AgentCard that describes the Mail Agent's capabilities
for the A2A protocol discovery endpoint.
"""

import logging
from typing import Optional

from a2a.types import AgentCard, AgentCapabilities, AgentSkill

from mail_agent.config import Settings, get_settings


logger = logging.getLogger(__name__)


def create_agent_card(settings: Optional[Settings] = None) -> AgentCard:
    """
    Create an AgentCard for the Mail Agent.

    The AgentCard provides metadata about the agent for the A2A protocol,
    including its name, description, capabilities, and endpoint URL.

    Args:
        settings: Configuration settings. Uses get_settings() if not provided.

    Returns:
        AgentCard configured with Mail Agent metadata.
    """
    if settings is None:
        settings = get_settings()

    logger.info(
        f"Creating AgentCard: name={settings.a2a_agent_name}, "
        f"version={settings.a2a_agent_version}"
    )

    # Define the email_communication skill
    email_skill = AgentSkill(
        id="email_communication",
        name="Email Communication",
        description=(
            "Send emails to POCs (Points of Contact), wait for replies, "
            "extract data from attachments (Excel, CSV), and validate responses. "
            "Supports multi-turn conversations with follow-up emails if the "
            "initial response doesn't meet the success criteria."
        ),
        tags=["email", "communication", "data-extraction", "automation"],
        examples=[
            "Email raj@example.com asking for 10 food recipes in an Excel file",
            "Send mail to john@company.com requesting sales data for Q4",
            "Contact support@vendor.com asking for product specifications",
        ],
    )

    # Build agent URL
    agent_url = f"http://{settings.a2a_host}:{settings.a2a_port}"

    # Create agent capabilities (skills go on AgentCard, not here)
    capabilities = AgentCapabilities(
        streaming=False,  # We don't support streaming yet
        push_notifications=False,  # No push notifications
        state_transition_history=False,  # No state history
    )

    # Supported content types for input/output
    supported_content_types = ["text", "text/plain"]

    # Create and return the AgentCard
    agent_card = AgentCard(
        name=settings.a2a_agent_name,
        description=settings.a2a_agent_description,
        url=agent_url,
        version=settings.a2a_agent_version,
        default_input_modes=supported_content_types,
        default_output_modes=supported_content_types,
        capabilities=capabilities,
        skills=[email_skill],
    )

    logger.info(f"AgentCard created: url={agent_url}")
    return agent_card
