"""
Tests for inject_poc_context node - Legacy Bridge functionality.

Tests the multi-POC to legacy single-POC state bridge that initializes
conversations and parsed_request for downstream nodes.
"""

import pytest
from mail_agent.agent.nodes.inject_poc_context import (
    inject_poc_context,
    _initialize_legacy_bridge,
)
from mail_agent.agent.multi_poc_state import (
    POCExecutionPlan,
    POCRequirement,
    POCState,
    POCStatus,
)
from mail_agent.agent.state import AgentState, ConversationState


class TestInitializeLegacyBridge:
    """Tests for the _initialize_legacy_bridge helper function."""

    def test_initializes_new_conversation(self) -> None:
        """Should create new conversation when POC email not in state."""
        state: AgentState = {
            "user_instruction": "test",
            "conversations": {},
            "current_node": "test",
        }
        requirement = POCRequirement(
            id="poc_test",
            email="test@example.com",
            request="Get 10 actor names",
            success_criteria="Receive list of 10 actor names",
            dependencies=[],
            execution_order=0,
        )

        conversations, parsed_request = _initialize_legacy_bridge(
            state, "test@example.com", requirement
        )

        # Verify conversation was created
        assert "test@example.com" in conversations
        conv = ConversationState.from_dict(conversations["test@example.com"])
        assert conv.poc_email == "test@example.com"
        assert conv.status == "pending"
        assert conv.attempt_count == 0

        # Verify parsed_request was created
        assert parsed_request["poc_emails"] == ["test@example.com"]
        assert parsed_request["request_description"] == "Get 10 actor names"
        assert parsed_request["success_criteria"] == "Receive list of 10 actor names"

    def test_preserves_existing_conversation(self) -> None:
        """Should not overwrite existing conversation."""
        existing_conv = ConversationState(
            poc_email="test@example.com",
            status="sending",
            attempt_count=2,
        )
        state: AgentState = {
            "user_instruction": "test",
            "conversations": {"test@example.com": existing_conv.to_dict()},
            "current_node": "test",
        }
        requirement = POCRequirement(
            id="poc_test",
            email="test@example.com",
            request="Get 10 actor names",
            success_criteria="Receive list of 10 actor names",
            dependencies=[],
            execution_order=0,
        )

        conversations, _ = _initialize_legacy_bridge(
            state, "test@example.com", requirement
        )

        # Verify existing conversation was preserved
        conv = ConversationState.from_dict(conversations["test@example.com"])
        assert conv.status == "sending"
        assert conv.attempt_count == 2


class TestInjectPocContextLegacyBridge:
    """Tests for inject_poc_context node's legacy bridge behavior."""

    @pytest.mark.asyncio
    async def test_no_dependencies_initializes_bridge(self) -> None:
        """With no dependencies, should initialize conversations and parsed_request."""
        poc_requirement = POCRequirement(
            id="poc_raj",
            email="raj@gmail.com",
            request="Get 10 actor names",
            success_criteria="Receive list of 10 actor names",
            dependencies=[],
            execution_order=0,
        )
        execution_plan = POCExecutionPlan(
            global_success_criteria="Get actor names",
            pocs=[poc_requirement],
            dependency_graph={},
        )
        poc_state = POCState(poc_id="poc_raj", status=POCStatus.PENDING)

        state: AgentState = {
            "user_instruction": "send mail to raj@gmail.com and ask for 10 actor names",
            "execution_plan": execution_plan.to_dict(),
            "poc_states": {"poc_raj": poc_state.to_dict()},
            "current_poc_id": "poc_raj",
            "conversations": {},
            "current_node": "orchestrate_pocs",
        }

        result = await inject_poc_context(state)

        # Verify legacy bridge data is set
        assert "conversations" in result
        assert "raj@gmail.com" in result["conversations"]
        conv = ConversationState.from_dict(result["conversations"]["raj@gmail.com"])
        assert conv.poc_email == "raj@gmail.com"
        assert conv.status == "pending"

        assert "parsed_request" in result
        assert result["parsed_request"]["poc_emails"] == ["raj@gmail.com"]
        assert result["parsed_request"]["request_description"] == "Get 10 actor names"

        # Verify current_poc is set
        assert result["current_poc"] == "raj@gmail.com"

    @pytest.mark.asyncio
    async def test_with_dependencies_initializes_bridge(self) -> None:
        """With dependencies, should also initialize conversations and parsed_request."""
        poc_req_1 = POCRequirement(
            id="poc_alice",
            email="alice@example.com",
            request="Get list of contacts",
            success_criteria="Receive contact list",
            dependencies=[],
            execution_order=0,
        )
        poc_req_2 = POCRequirement(
            id="poc_bob",
            email="bob@example.com",
            request="Email contacts from alice",
            success_criteria="Email sent to contacts",
            dependencies=["poc_alice"],
            execution_order=1,
        )
        execution_plan = POCExecutionPlan(
            global_success_criteria="Complete contact workflow",
            pocs=[poc_req_1, poc_req_2],
            dependency_graph={"poc_bob": ["poc_alice"]},
        )
        alice_state = POCState(
            poc_id="poc_alice",
            status=POCStatus.COMPLETED,
            extracted_data={"contacts": ["c1@example.com", "c2@example.com"]},
        )
        bob_state = POCState(poc_id="poc_bob", status=POCStatus.PENDING)

        state: AgentState = {
            "user_instruction": "test multi-poc workflow",
            "execution_plan": execution_plan.to_dict(),
            "poc_states": {
                "poc_alice": alice_state.to_dict(),
                "poc_bob": bob_state.to_dict(),
            },
            "current_poc_id": "poc_bob",
            "conversations": {},
            "current_node": "orchestrate_pocs",
        }

        result = await inject_poc_context(state)

        # Verify legacy bridge data is set
        assert "conversations" in result
        assert "bob@example.com" in result["conversations"]

        assert "parsed_request" in result
        assert result["parsed_request"]["poc_emails"] == ["bob@example.com"]

        # Verify current_poc is set
        assert result["current_poc"] == "bob@example.com"

    @pytest.mark.asyncio
    async def test_no_current_poc_id_returns_error(self) -> None:
        """Should return error if current_poc_id is not set."""
        state: AgentState = {
            "user_instruction": "test",
            "current_node": "orchestrate_pocs",
        }

        result = await inject_poc_context(state)

        assert "error" in result
        assert "No current_poc_id" in result["error"]

    @pytest.mark.asyncio
    async def test_preserves_existing_conversation_on_retry(self) -> None:
        """On retry, should preserve existing conversation state."""
        poc_requirement = POCRequirement(
            id="poc_raj",
            email="raj@gmail.com",
            request="Get 10 actor names",
            success_criteria="Receive list of 10 actor names",
            dependencies=[],
            execution_order=0,
        )
        execution_plan = POCExecutionPlan(
            global_success_criteria="Get actor names",
            pocs=[poc_requirement],
            dependency_graph={},
        )
        poc_state = POCState(poc_id="poc_raj", status=POCStatus.PENDING)

        # Simulate existing conversation from previous attempt
        existing_conv = ConversationState(
            poc_email="raj@gmail.com",
            status="validating",
            attempt_count=2,
        )

        state: AgentState = {
            "user_instruction": "send mail to raj@gmail.com and ask for 10 actor names",
            "execution_plan": execution_plan.to_dict(),
            "poc_states": {"poc_raj": poc_state.to_dict()},
            "current_poc_id": "poc_raj",
            "conversations": {"raj@gmail.com": existing_conv.to_dict()},
            "current_node": "orchestrate_pocs",
        }

        result = await inject_poc_context(state)

        # Verify existing conversation was preserved
        conv = ConversationState.from_dict(result["conversations"]["raj@gmail.com"])
        assert conv.status == "validating"
        assert conv.attempt_count == 2
