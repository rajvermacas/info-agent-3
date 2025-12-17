"""
Tests for select_next_poc node.

Tests the node that selects the next pending POC for processing
in multi-POC scenarios.
"""

import pytest
from mail_agent.agent.nodes.select_next_poc import select_next_poc
from mail_agent.agent.state import AgentState, ConversationState


class TestSelectNextPoc:
    """Test cases for select_next_poc node."""

    @pytest.fixture
    def base_state(self) -> AgentState:
        """Create base state with parsed request."""
        return AgentState(
            user_instruction="Send mail to poc1@test.com and poc2@test.com",
            parsed_request={
                "poc_emails": ["poc1@test.com", "poc2@test.com"],
                "request_type": "data_request",
                "request_description": "Request data",
                "success_criteria": "Data received",
                "expected_format": "csv",
            },
            conversations={},
            current_poc=None,
            progress_messages=[],
        )

    @pytest.mark.asyncio
    async def test_select_first_pending_poc(self, base_state: AgentState) -> None:
        """Should select the first pending POC when all are pending."""
        # Setup: Two POCs, both pending
        base_state["conversations"] = {
            "poc1@test.com": ConversationState(poc_email="poc1@test.com", status="pending").to_dict(),
            "poc2@test.com": ConversationState(poc_email="poc2@test.com", status="pending").to_dict(),
        }

        result = await select_next_poc(base_state)

        assert result["current_poc"] == "poc1@test.com"
        assert result["current_node"] == "select_next_poc"
        assert "Switching to next POC" in result["progress_messages"][0]

    @pytest.mark.asyncio
    async def test_select_second_poc_when_first_complete(self, base_state: AgentState) -> None:
        """Should select second POC when first is complete."""
        # Setup: First POC complete, second pending
        base_state["conversations"] = {
            "poc1@test.com": ConversationState(poc_email="poc1@test.com", status="success").to_dict(),
            "poc2@test.com": ConversationState(poc_email="poc2@test.com", status="pending").to_dict(),
        }

        result = await select_next_poc(base_state)

        assert result["current_poc"] == "poc2@test.com"
        assert "poc2@test.com" in result["progress_messages"][0]

    @pytest.mark.asyncio
    async def test_returns_none_when_all_complete(self, base_state: AgentState) -> None:
        """Should return None when all POCs are complete."""
        # Setup: Both POCs complete
        base_state["conversations"] = {
            "poc1@test.com": ConversationState(poc_email="poc1@test.com", status="success").to_dict(),
            "poc2@test.com": ConversationState(poc_email="poc2@test.com", status="failed").to_dict(),
        }

        result = await select_next_poc(base_state)

        assert result["current_poc"] is None
        assert "All POCs have been processed" in result["progress_messages"][0]

    @pytest.mark.asyncio
    async def test_skip_redirected_poc(self, base_state: AgentState) -> None:
        """Should skip redirected POCs and select next pending."""
        # Setup: First POC redirected, second pending
        base_state["conversations"] = {
            "poc1@test.com": ConversationState(poc_email="poc1@test.com", status="redirected").to_dict(),
            "poc2@test.com": ConversationState(poc_email="poc2@test.com", status="pending").to_dict(),
        }

        result = await select_next_poc(base_state)

        assert result["current_poc"] == "poc2@test.com"

    @pytest.mark.asyncio
    async def test_select_poc_in_intermediate_status(self, base_state: AgentState) -> None:
        """Should select POC that is in intermediate status (composing, sending, etc.)."""
        # Setup: First POC success, second in "waiting" state
        base_state["conversations"] = {
            "poc1@test.com": ConversationState(poc_email="poc1@test.com", status="success").to_dict(),
            "poc2@test.com": ConversationState(poc_email="poc2@test.com", status="waiting").to_dict(),
        }

        result = await select_next_poc(base_state)

        # "waiting" is not terminal, so it should be selected
        assert result["current_poc"] == "poc2@test.com"

    @pytest.mark.asyncio
    async def test_empty_conversations(self, base_state: AgentState) -> None:
        """Should return None when no conversations exist."""
        base_state["conversations"] = {}

        result = await select_next_poc(base_state)

        assert result["current_poc"] is None
        assert "All POCs have been processed" in result["progress_messages"][0]

    @pytest.mark.asyncio
    async def test_three_pocs_various_statuses(self, base_state: AgentState) -> None:
        """Should handle multiple POCs with various statuses correctly."""
        # Setup: 3 POCs - success, failed, pending
        base_state["conversations"] = {
            "poc1@test.com": ConversationState(poc_email="poc1@test.com", status="success").to_dict(),
            "poc2@test.com": ConversationState(poc_email="poc2@test.com", status="failed").to_dict(),
            "poc3@test.com": ConversationState(poc_email="poc3@test.com", status="pending").to_dict(),
        }

        result = await select_next_poc(base_state)

        assert result["current_poc"] == "poc3@test.com"
