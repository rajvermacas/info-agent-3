"""
Tests for check_more_pocs node.

Tests the node that determines if more POCs need processing
or if all are complete for cross-POC validation.
"""

import pytest
from mail_agent.agent.nodes.check_more_pocs import check_more_pocs
from mail_agent.agent.state import AgentState, ConversationState


class TestCheckMorePocs:
    """Test cases for check_more_pocs node."""

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
    async def test_more_pocs_pending(self, base_state: AgentState) -> None:
        """Should indicate more POCs pending when not all complete."""
        # Setup: First POC complete, second pending
        base_state["conversations"] = {
            "poc1@test.com": ConversationState(poc_email="poc1@test.com", status="success").to_dict(),
            "poc2@test.com": ConversationState(poc_email="poc2@test.com", status="pending").to_dict(),
        }

        result = await check_more_pocs(base_state)

        assert result["_all_pocs_individual_complete"] is False
        assert result["current_node"] == "check_more_pocs"
        assert "Processing next POC" in result["progress_messages"][0]

    @pytest.mark.asyncio
    async def test_all_pocs_complete_success(self, base_state: AgentState) -> None:
        """Should indicate all complete when all POCs succeeded."""
        # Setup: Both POCs success
        base_state["conversations"] = {
            "poc1@test.com": ConversationState(poc_email="poc1@test.com", status="success").to_dict(),
            "poc2@test.com": ConversationState(poc_email="poc2@test.com", status="success").to_dict(),
        }

        result = await check_more_pocs(base_state)

        assert result["_all_pocs_individual_complete"] is True
        assert "cross-poc validation" in result["progress_messages"][0].lower()

    @pytest.mark.asyncio
    async def test_all_pocs_complete_mixed_terminal(self, base_state: AgentState) -> None:
        """Should indicate all complete with mixed terminal states."""
        # Setup: One success, one failed, one redirected
        base_state["conversations"] = {
            "poc1@test.com": ConversationState(poc_email="poc1@test.com", status="success").to_dict(),
            "poc2@test.com": ConversationState(poc_email="poc2@test.com", status="failed").to_dict(),
            "poc3@test.com": ConversationState(poc_email="poc3@test.com", status="redirected").to_dict(),
        }

        result = await check_more_pocs(base_state)

        assert result["_all_pocs_individual_complete"] is True

    @pytest.mark.asyncio
    async def test_poc_in_intermediate_state_not_complete(self, base_state: AgentState) -> None:
        """Should indicate not complete when POC in intermediate state."""
        # Setup: First complete, second in "waiting"
        base_state["conversations"] = {
            "poc1@test.com": ConversationState(poc_email="poc1@test.com", status="success").to_dict(),
            "poc2@test.com": ConversationState(poc_email="poc2@test.com", status="waiting").to_dict(),
        }

        result = await check_more_pocs(base_state)

        assert result["_all_pocs_individual_complete"] is False

    @pytest.mark.asyncio
    async def test_all_intermediate_states(self, base_state: AgentState) -> None:
        """Should indicate not complete when all in intermediate states."""
        # Setup: Various intermediate states
        base_state["conversations"] = {
            "poc1@test.com": ConversationState(poc_email="poc1@test.com", status="composing").to_dict(),
            "poc2@test.com": ConversationState(poc_email="poc2@test.com", status="sending").to_dict(),
        }

        result = await check_more_pocs(base_state)

        assert result["_all_pocs_individual_complete"] is False

    @pytest.mark.asyncio
    async def test_empty_conversations(self, base_state: AgentState) -> None:
        """Should handle empty conversations gracefully."""
        base_state["conversations"] = {}

        result = await check_more_pocs(base_state)

        # Empty is technically "complete" (nothing to process)
        assert result["_all_pocs_individual_complete"] is False  # all_conversations_complete returns False for empty

    @pytest.mark.asyncio
    async def test_single_poc_complete(self, base_state: AgentState) -> None:
        """Should handle single POC case correctly."""
        base_state["conversations"] = {
            "poc1@test.com": ConversationState(poc_email="poc1@test.com", status="success").to_dict(),
        }

        result = await check_more_pocs(base_state)

        assert result["_all_pocs_individual_complete"] is True
        assert "1" in result["progress_messages"][0]  # Should mention 1 POC

    @pytest.mark.asyncio
    async def test_progress_message_lists_pending_pocs(self, base_state: AgentState) -> None:
        """Should list pending POCs in progress message."""
        base_state["conversations"] = {
            "poc1@test.com": ConversationState(poc_email="poc1@test.com", status="success").to_dict(),
            "poc2@test.com": ConversationState(poc_email="poc2@test.com", status="pending").to_dict(),
            "poc3@test.com": ConversationState(poc_email="poc3@test.com", status="pending").to_dict(),
        }

        result = await check_more_pocs(base_state)

        # Progress message should mention pending POCs
        assert "poc2@test.com" in result["progress_messages"][0]
        assert "poc3@test.com" in result["progress_messages"][0]
