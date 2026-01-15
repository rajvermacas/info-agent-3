"""
Tests for the legacy single-POC agent state module.

For multi-POC orchestration state tests, see test_multi_poc_state.py.
"""

import pytest
from datetime import datetime, timezone
from uuid import UUID

from mail_agent.agent.state import (
    AgentState,
    ConversationState,
    ParsedRequest,
    ReceivedEmail,
    SentEmail,
    ValidationResult,
    create_initial_state,
    get_conversation,
    update_conversation,
    get_parsed_request,
    all_conversations_complete,
    get_active_poc,
)


class TestConversationState:
    """Tests for ConversationState dataclass."""

    def test_default_values(self):
        """Test default initialization."""
        conv = ConversationState(poc_email="test@example.com")

        assert conv.poc_email == "test@example.com"
        assert conv.status == "pending"
        assert conv.attempt_count == 0
        assert conv.sent_emails == []
        assert conv.received_emails == []
        assert conv.validation_results == []
        assert conv.final_result is None
        assert conv.error_message is None

    def test_to_dict(self):
        """Test conversion to dictionary."""
        conv = ConversationState(
            poc_email="test@example.com",
            status="waiting",
            attempt_count=2,
        )

        result = conv.to_dict()

        assert result["poc_email"] == "test@example.com"
        assert result["status"] == "waiting"
        assert result["attempt_count"] == 2
        assert result["sent_emails"] == []
        assert result["received_emails"] == []

    def test_from_dict(self):
        """Test creation from dictionary."""
        data = {
            "poc_email": "test@example.com",
            "status": "success",
            "attempt_count": 3,
            "sent_emails": [],
            "received_emails": [],
            "validation_results": [],
            "final_result": "success",
            "error_message": None,
        }

        conv = ConversationState.from_dict(data)

        assert conv.poc_email == "test@example.com"
        assert conv.status == "success"
        assert conv.attempt_count == 3
        assert conv.final_result == "success"

    def test_roundtrip_serialization(self):
        """Test to_dict -> from_dict roundtrip."""
        original = ConversationState(
            poc_email="test@example.com",
            status="validating",
            attempt_count=2,
        )

        # Add some data
        original.sent_emails.append(
            SentEmail(
                email_id=UUID("12345678-1234-1234-1234-123456789012"),
                subject="Test Subject",
                body="Test Body",
                sent_at=datetime.now(timezone.utc),
            )
        )

        # Roundtrip
        data = original.to_dict()
        restored = ConversationState.from_dict(data)

        assert restored.poc_email == original.poc_email
        assert restored.status == original.status
        assert restored.attempt_count == original.attempt_count
        assert len(restored.sent_emails) == 1
        assert restored.sent_emails[0].subject == "Test Subject"


class TestParsedRequest:
    """Tests for ParsedRequest dataclass."""

    def test_to_dict(self):
        """Test conversion to dictionary."""
        request = ParsedRequest(
            poc_emails=["a@test.com", "b@test.com"],
            request_type="data_request",
            request_description="Get 10 recipes",
            success_criteria="10 rows of recipes",
            expected_format="excel",
        )

        result = request.to_dict()

        assert result["poc_emails"] == ["a@test.com", "b@test.com"]
        assert result["request_type"] == "data_request"
        assert result["expected_format"] == "excel"

    def test_from_dict(self):
        """Test creation from dictionary."""
        data = {
            "poc_emails": ["test@example.com"],
            "request_type": "information_request",
            "request_description": "Ask for info",
            "success_criteria": "Response received",
            "expected_format": "text",
        }

        request = ParsedRequest.from_dict(data)

        assert request.poc_emails == ["test@example.com"]
        assert request.request_type == "information_request"
        assert request.expected_format == "text"


class TestAgentStateHelpers:
    """Tests for agent state helper functions."""

    def test_create_initial_state(self):
        """Test create_initial_state function."""
        instruction = "send mail to test@example.com asking for recipes"

        state = create_initial_state(instruction)

        assert state["user_instruction"] == instruction
        assert state["parsed_request"] is None
        assert state["conversations"] == {}
        assert state["current_node"] == "start"
        assert state["current_poc"] is None
        assert state["pending_webhooks"] == []
        assert len(state["progress_messages"]) == 1
        assert state["error"] is None

    def test_get_conversation_exists(self):
        """Test get_conversation with existing conversation."""
        conv = ConversationState(poc_email="test@example.com", status="waiting")
        state: AgentState = {
            "conversations": {"test@example.com": conv.to_dict()},
        }

        result = get_conversation(state, "test@example.com")

        assert result.poc_email == "test@example.com"
        assert result.status == "waiting"

    def test_get_conversation_not_found(self):
        """Test get_conversation with missing conversation."""
        state: AgentState = {"conversations": {}}

        with pytest.raises(KeyError):
            get_conversation(state, "nonexistent@example.com")

    def test_update_conversation(self):
        """Test update_conversation function."""
        conv = ConversationState(poc_email="test@example.com", status="pending")
        state: AgentState = {
            "conversations": {"test@example.com": conv.to_dict()},
        }

        # Update the conversation
        conv.status = "success"
        conv.attempt_count = 3

        result = update_conversation(state, "test@example.com", conv)

        assert result["test@example.com"]["status"] == "success"
        assert result["test@example.com"]["attempt_count"] == 3

    def test_get_parsed_request_exists(self):
        """Test get_parsed_request with existing request."""
        request = ParsedRequest(
            poc_emails=["test@example.com"],
            request_type="data_request",
            request_description="Test",
            success_criteria="Test criteria",
            expected_format="excel",
        )
        state: AgentState = {"parsed_request": request.to_dict()}

        result = get_parsed_request(state)

        assert result.poc_emails == ["test@example.com"]
        assert result.request_type == "data_request"

    def test_get_parsed_request_not_set(self):
        """Test get_parsed_request when not set."""
        state: AgentState = {"parsed_request": None}

        with pytest.raises(ValueError):
            get_parsed_request(state)

    def test_all_conversations_complete_empty(self):
        """Test all_conversations_complete with no conversations."""
        state: AgentState = {"conversations": {}}

        assert all_conversations_complete(state) is False

    def test_all_conversations_complete_true(self):
        """Test all_conversations_complete when all complete."""
        state: AgentState = {
            "conversations": {
                "a@test.com": {"status": "success"},
                "b@test.com": {"status": "failed"},
            }
        }

        assert all_conversations_complete(state) is True

    def test_all_conversations_complete_false(self):
        """Test all_conversations_complete when some incomplete."""
        state: AgentState = {
            "conversations": {
                "a@test.com": {"status": "success"},
                "b@test.com": {"status": "waiting"},
            }
        }

        assert all_conversations_complete(state) is False

    def test_get_active_poc_found(self):
        """Test get_active_poc with active POC."""
        state: AgentState = {
            "conversations": {
                "a@test.com": {"status": "success"},
                "b@test.com": {"status": "waiting"},
            }
        }

        result = get_active_poc(state)

        assert result == "b@test.com"

    def test_get_active_poc_none(self):
        """Test get_active_poc when all complete."""
        state: AgentState = {
            "conversations": {
                "a@test.com": {"status": "success"},
                "b@test.com": {"status": "failed"},
            }
        }

        result = get_active_poc(state)

        assert result is None


class TestSentEmail:
    """Tests for SentEmail dataclass."""

    def test_creation(self):
        """Test SentEmail creation."""
        sent = SentEmail(
            email_id=UUID("12345678-1234-1234-1234-123456789012"),
            subject="Test Subject",
            body="Test Body",
            sent_at=datetime.now(timezone.utc),
        )

        assert sent.subject == "Test Subject"
        assert sent.body == "Test Body"


class TestReceivedEmail:
    """Tests for ReceivedEmail dataclass."""

    def test_creation(self):
        """Test ReceivedEmail creation."""
        received = ReceivedEmail(
            email_id=UUID("12345678-1234-1234-1234-123456789012"),
            from_address="sender@test.com",
            subject="Re: Test",
            received_at=datetime.now(timezone.utc),
            has_attachment=True,
            attachment_content='{"data": []}',
            attachment_filename="data.xlsx",
        )

        assert received.from_address == "sender@test.com"
        assert received.has_attachment is True
        assert received.attachment_filename == "data.xlsx"


class TestValidationResult:
    """Tests for ValidationResult dataclass."""

    def test_creation(self):
        """Test ValidationResult creation."""
        result = ValidationResult(
            attempt=1,
            is_valid=False,
            feedback="Missing 2 recipes",
            missing_items=["Recipe 9", "Recipe 10"],
        )

        assert result.attempt == 1
        assert result.is_valid is False
        assert len(result.missing_items) == 2
