"""
Integration tests for the mail agent.

These tests verify the end-to-end flow of the agent components.
"""

import asyncio
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

from mail_agent.agent.graph import create_mail_agent_graph, compile_mail_agent_graph
from mail_agent.agent.state import (
    AgentState,
    ConversationState,
    ParsedRequest,
    create_initial_state,
)
from mail_agent.webhook.server import WebhookEvent, WebhookPayload, WebhookServer


class TestWebhookServer:
    """Integration tests for webhook server."""

    @pytest.mark.asyncio
    async def test_webhook_event_from_payload(self):
        """Test converting webhook payload to event."""
        payload = WebhookPayload(
            event="email.received",
            email_id="12345678-1234-1234-1234-123456789012",
            from_address="sender@test.com",
            to=["receiver@test.com"],
            subject="Test Subject",
            has_attachments=True,
            attachment_count=1,
            received_at="2025-12-14T12:00:00.000000",
            body_preview="Hello...",
        )

        event = WebhookEvent.from_payload(payload)

        assert event.email_id == UUID("12345678-1234-1234-1234-123456789012")
        assert event.from_address == "sender@test.com"
        assert event.to_addresses == ["receiver@test.com"]
        assert event.subject == "Test Subject"
        assert event.has_attachments is True
        assert event.attachment_count == 1

    @pytest.mark.asyncio
    async def test_webhook_server_queue(self, mock_settings):
        """Test webhook server event queue."""
        queue = asyncio.Queue()
        server = WebhookServer(settings=mock_settings, event_queue=queue)

        # Put event directly on queue
        event = WebhookEvent(
            email_id=UUID("12345678-1234-1234-1234-123456789012"),
            from_address="test@test.com",
            to_addresses=["agent@test.com"],
            subject="Test",
            has_attachments=False,
            attachment_count=0,
            received_at=datetime.now(timezone.utc),
            body_preview="",
        )

        await queue.put(event)

        # Retrieve from server's queue
        assert server.has_pending_events()
        retrieved = await server.wait_for_event(timeout=1.0)

        assert retrieved is not None
        assert retrieved.email_id == event.email_id

    @pytest.mark.asyncio
    async def test_webhook_server_timeout(self, mock_settings):
        """Test webhook server wait timeout."""
        server = WebhookServer(settings=mock_settings)

        # Wait with short timeout, should return None
        result = await server.wait_for_event(timeout=0.1)

        assert result is None


class TestGraphCreation:
    """Tests for LangGraph creation."""

    def test_create_graph(self):
        """Test creating the mail agent graph."""
        graph = create_mail_agent_graph()

        assert graph is not None
        # Check nodes were added
        assert len(graph.nodes) > 0

    def test_compile_graph(self):
        """Test compiling the mail agent graph."""
        compiled = compile_mail_agent_graph()

        assert compiled is not None

    def test_graph_has_required_nodes(self):
        """Test graph contains all required nodes for multi-POC orchestration."""
        graph = create_mail_agent_graph()

        expected_nodes = [
            # Planning phase
            "parse_multi_poc_instruction",
            "build_dependency_graph",
            # Orchestration
            "orchestrate_pocs",
            "inject_poc_context",
            # POC execution
            "compose_email",
            "send_email",
            "wait_for_reply",
            "fetch_email",
            "extract_content",
            "validate_poc_response",
            "handle_redirect",
            "mark_poc_success",
            "mark_poc_failed",
            # Aggregation
            "aggregate_poc_responses",
            "detect_conflicts",
            "resolve_conflicts",
            # Completion
            "validate_global_criteria",
            "send_multi_success_replies",
            "finalize_success",
            "finalize_failure",
        ]

        for node_name in expected_nodes:
            assert node_name in graph.nodes, f"Missing node: {node_name}"


class TestAgentStateFlow:
    """Tests for agent state transitions."""

    def test_initial_state_structure(self):
        """Test initial state has correct structure."""
        state = create_initial_state("test instruction")

        assert state["user_instruction"] == "test instruction"
        assert state["parsed_request"] is None
        assert state["conversations"] == {}
        assert state["current_node"] == "start"
        assert state["pending_webhooks"] == []
        assert state["error"] is None

    def test_parsed_request_flow(self):
        """Test state after parsing instruction."""
        # Simulate parsed request
        parsed = ParsedRequest(
            poc_emails=["poc@test.com"],
            request_type="data_request",
            request_description="Get 10 recipes",
            success_criteria="10 rows of recipes",
            expected_format="excel",
        )

        state = create_initial_state("send mail to poc@test.com asking 10 recipes")
        state["parsed_request"] = parsed.to_dict()
        state["conversations"] = {
            "poc@test.com": ConversationState(poc_email="poc@test.com").to_dict()
        }

        assert state["parsed_request"]["poc_emails"] == ["poc@test.com"]
        assert "poc@test.com" in state["conversations"]

    def test_conversation_state_transitions(self):
        """Test conversation state transitions."""
        conv = ConversationState(poc_email="test@test.com")

        # Initial state
        assert conv.status == "pending"
        assert conv.attempt_count == 0

        # After composing
        conv.status = "composing"
        assert conv.status == "composing"

        # After sending
        conv.status = "sending"
        conv.status = "waiting"
        conv.attempt_count = 1
        assert conv.attempt_count == 1

        # After validation success
        conv.status = "success"
        conv.final_result = "success"
        assert conv.final_result == "success"


class TestDecideNextLogic:
    """Tests for decision routing logic."""

    def test_decide_success_route(self):
        """Test routing to success."""
        from mail_agent.agent.nodes.decide_next import decide_next

        conv = ConversationState(
            poc_email="test@test.com",
            status="validating",
            attempt_count=1,
        )

        state: AgentState = {
            "current_poc": "test@test.com",
            "conversations": {"test@test.com": conv.to_dict()},
            "_validation_is_valid": True,
        }

        with patch("mail_agent.agent.nodes.decide_next.get_settings") as mock_settings:
            mock_settings.return_value.max_attempts = 5
            result = decide_next(state)

        assert result == "success"

    def test_decide_followup_route(self):
        """Test routing to followup."""
        from mail_agent.agent.nodes.decide_next import decide_next

        conv = ConversationState(
            poc_email="test@test.com",
            status="validating",
            attempt_count=2,
        )

        state: AgentState = {
            "current_poc": "test@test.com",
            "conversations": {"test@test.com": conv.to_dict()},
            "_validation_is_valid": False,
        }

        with patch("mail_agent.agent.nodes.decide_next.get_settings") as mock_settings:
            mock_settings.return_value.max_attempts = 5
            result = decide_next(state)

        assert result == "followup"

    def test_decide_failure_route(self):
        """Test routing to failure after max attempts."""
        from mail_agent.agent.nodes.decide_next import decide_next

        conv = ConversationState(
            poc_email="test@test.com",
            status="validating",
            attempt_count=5,
        )

        state: AgentState = {
            "current_poc": "test@test.com",
            "conversations": {"test@test.com": conv.to_dict()},
            "_validation_is_valid": False,
        }

        with patch("mail_agent.agent.nodes.decide_next.get_settings") as mock_settings:
            mock_settings.return_value.max_attempts = 5
            result = decide_next(state)

        assert result == "failure"


class TestParseInstructionNode:
    """Tests for parse_instruction node."""

    @pytest.mark.asyncio
    async def test_parse_instruction_missing_instruction(self):
        """Test parse_instruction with missing instruction."""
        from mail_agent.agent.nodes.parse_instruction import parse_instruction

        state: AgentState = {"user_instruction": ""}

        result = await parse_instruction(state)

        assert result.get("error") is not None
        assert result["current_node"] == "error"

    @pytest.mark.asyncio
    async def test_parse_instruction_success(self, mock_settings):
        """Test parse_instruction with valid instruction (mocked LLM)."""
        from mail_agent.agent.nodes.parse_instruction import parse_instruction
        from mail_agent.llm.prompts import ParsedInstruction

        state: AgentState = {
            "user_instruction": "send mail to test@example.com asking 10 recipes"
        }

        mock_parsed = ParsedInstruction(
            poc_emails=["test@example.com"],
            request_type="data_request",
            request_description="10 food recipes",
            success_criteria="10 rows of recipes",
            expected_format="excel",
        )

        with patch("mail_agent.agent.nodes.parse_instruction.get_settings") as mock_get_settings:
            mock_get_settings.return_value = mock_settings

            with patch("mail_agent.agent.nodes.parse_instruction.LLMClient") as mock_llm:
                mock_instance = AsyncMock()
                mock_instance.generate_structured = AsyncMock(return_value=mock_parsed)
                mock_llm.return_value = mock_instance

                result = await parse_instruction(state)

        assert result.get("error") is None
        assert result["parsed_request"] is not None
        assert "test@example.com" in result["conversations"]


class TestComposeEmailNode:
    """Tests for compose_email node."""

    @pytest.mark.asyncio
    async def test_compose_email_no_poc(self):
        """Test compose_email with no POC set."""
        from mail_agent.agent.nodes.compose_email import compose_email

        state: AgentState = {"current_poc": None}

        result = await compose_email(state)

        assert result.get("error") is not None

    @pytest.mark.asyncio
    async def test_compose_email_success(self, mock_settings):
        """Test compose_email success (mocked LLM)."""
        from mail_agent.agent.nodes.compose_email import compose_email
        from mail_agent.llm.prompts import ComposedEmail

        conv = ConversationState(poc_email="test@test.com", status="pending")
        parsed = ParsedRequest(
            poc_emails=["test@test.com"],
            request_type="data_request",
            request_description="10 recipes",
            success_criteria="10 rows",
            expected_format="excel",
        )

        state: AgentState = {
            "current_poc": "test@test.com",
            "conversations": {"test@test.com": conv.to_dict()},
            "parsed_request": parsed.to_dict(),
        }

        mock_composed = ComposedEmail(
            subject="Request: 10 Recipes",
            body="Dear Sir, please provide...",
        )

        with patch("mail_agent.agent.nodes.compose_email.get_settings") as mock_get_settings:
            mock_get_settings.return_value = mock_settings

            with patch("mail_agent.agent.nodes.compose_email.LLMClient") as mock_llm:
                mock_instance = AsyncMock()
                mock_instance.generate_structured = AsyncMock(return_value=mock_composed)
                mock_llm.return_value = mock_instance

                result = await compose_email(state)

        assert result.get("error") is None
        assert result.get("_composed_subject") == "Request: 10 Recipes"
        assert result.get("_composed_body") is not None


class TestSendEmailNode:
    """Tests for send_email node."""

    @pytest.mark.asyncio
    async def test_send_email_no_poc(self):
        """Test send_email with no POC set."""
        from mail_agent.agent.nodes.send_email import send_email

        state: AgentState = {"current_poc": None}

        result = await send_email(state)

        assert result.get("error") is not None

    @pytest.mark.asyncio
    async def test_send_email_no_composed(self):
        """Test send_email with no composed email."""
        from mail_agent.agent.nodes.send_email import send_email

        conv = ConversationState(poc_email="test@test.com")

        state: AgentState = {
            "current_poc": "test@test.com",
            "conversations": {"test@test.com": conv.to_dict()},
            "_composed_subject": None,
            "_composed_body": None,
        }

        result = await send_email(state)

        assert result.get("error") is not None
