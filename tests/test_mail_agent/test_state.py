"""
Tests for the agent state module.
"""

import pytest
from datetime import datetime, timezone
from uuid import UUID

from mail_agent.agent.state import (
    AgentState,
    ConversationState,
    ParsedRequest,
    ReceivedEmail,
    RedirectInfo,
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

    def test_to_dict(self):
        """Test SentEmail to_dict method."""
        sent_at = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        sent = SentEmail(
            email_id=UUID("12345678-1234-1234-1234-123456789012"),
            subject="Test Subject",
            body="Test Body",
            sent_at=sent_at,
        )

        result = sent.to_dict()

        assert result["email_id"] == "12345678-1234-1234-1234-123456789012"
        assert result["subject"] == "Test Subject"
        assert result["body"] == "Test Body"
        assert result["sent_at"] == "2025-01-15T10:30:00+00:00"

    def test_from_dict(self):
        """Test SentEmail from_dict method."""
        data = {
            "email_id": "12345678-1234-1234-1234-123456789012",
            "subject": "Test Subject",
            "body": "Test Body",
            "sent_at": "2025-01-15T10:30:00+00:00",
        }

        sent = SentEmail.from_dict(data)

        assert sent.email_id == UUID("12345678-1234-1234-1234-123456789012")
        assert sent.subject == "Test Subject"
        assert sent.body == "Test Body"
        assert sent.sent_at == datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)

    def test_roundtrip_serialization(self):
        """Test SentEmail to_dict -> from_dict roundtrip."""
        original = SentEmail(
            email_id=UUID("12345678-1234-1234-1234-123456789012"),
            subject="Test Subject",
            body="Test Body",
            sent_at=datetime.now(timezone.utc),
        )

        data = original.to_dict()
        restored = SentEmail.from_dict(data)

        assert restored.email_id == original.email_id
        assert restored.subject == original.subject
        assert restored.body == original.body
        assert restored.sent_at == original.sent_at


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

    def test_to_dict(self):
        """Test ReceivedEmail to_dict method."""
        received_at = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        received = ReceivedEmail(
            email_id=UUID("12345678-1234-1234-1234-123456789012"),
            from_address="sender@test.com",
            subject="Re: Test",
            received_at=received_at,
            has_attachment=True,
            attachment_content='{"data": []}',
            attachment_filename="data.xlsx",
            body_text="Email body text",
        )

        result = received.to_dict()

        assert result["email_id"] == "12345678-1234-1234-1234-123456789012"
        assert result["from_address"] == "sender@test.com"
        assert result["subject"] == "Re: Test"
        assert result["received_at"] == "2025-01-15T10:30:00+00:00"
        assert result["has_attachment"] is True
        assert result["attachment_content"] == '{"data": []}'
        assert result["attachment_filename"] == "data.xlsx"
        assert result["body_text"] == "Email body text"

    def test_to_dict_optional_fields_none(self):
        """Test ReceivedEmail to_dict with None optional fields."""
        received = ReceivedEmail(
            email_id=UUID("12345678-1234-1234-1234-123456789012"),
            from_address="sender@test.com",
            subject="Re: Test",
            received_at=datetime.now(timezone.utc),
            has_attachment=False,
        )

        result = received.to_dict()

        assert result["attachment_content"] is None
        assert result["attachment_filename"] is None
        assert result["body_text"] is None

    def test_from_dict(self):
        """Test ReceivedEmail from_dict method."""
        data = {
            "email_id": "12345678-1234-1234-1234-123456789012",
            "from_address": "sender@test.com",
            "subject": "Re: Test",
            "received_at": "2025-01-15T10:30:00+00:00",
            "has_attachment": True,
            "attachment_content": '{"data": []}',
            "attachment_filename": "data.xlsx",
            "body_text": "Email body text",
        }

        received = ReceivedEmail.from_dict(data)

        assert received.email_id == UUID("12345678-1234-1234-1234-123456789012")
        assert received.from_address == "sender@test.com"
        assert received.subject == "Re: Test"
        assert received.received_at == datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        assert received.has_attachment is True
        assert received.attachment_content == '{"data": []}'
        assert received.attachment_filename == "data.xlsx"
        assert received.body_text == "Email body text"

    def test_from_dict_missing_optional_fields(self):
        """Test ReceivedEmail from_dict with missing optional fields."""
        data = {
            "email_id": "12345678-1234-1234-1234-123456789012",
            "from_address": "sender@test.com",
            "subject": "Re: Test",
            "received_at": "2025-01-15T10:30:00+00:00",
            "has_attachment": False,
        }

        received = ReceivedEmail.from_dict(data)

        assert received.attachment_content is None
        assert received.attachment_filename is None
        assert received.body_text is None

    def test_roundtrip_serialization(self):
        """Test ReceivedEmail to_dict -> from_dict roundtrip."""
        original = ReceivedEmail(
            email_id=UUID("12345678-1234-1234-1234-123456789012"),
            from_address="sender@test.com",
            subject="Re: Test",
            received_at=datetime.now(timezone.utc),
            has_attachment=True,
            attachment_content='{"data": [1, 2, 3]}',
            attachment_filename="data.csv",
            body_text="Body text here",
        )

        data = original.to_dict()
        restored = ReceivedEmail.from_dict(data)

        assert restored.email_id == original.email_id
        assert restored.from_address == original.from_address
        assert restored.subject == original.subject
        assert restored.received_at == original.received_at
        assert restored.has_attachment == original.has_attachment
        assert restored.attachment_content == original.attachment_content
        assert restored.attachment_filename == original.attachment_filename
        assert restored.body_text == original.body_text


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

    def test_to_dict(self):
        """Test ValidationResult to_dict method."""
        result = ValidationResult(
            attempt=2,
            is_valid=True,
            feedback="All items received",
            missing_items=[],
        )

        data = result.to_dict()

        assert data["attempt"] == 2
        assert data["is_valid"] is True
        assert data["feedback"] == "All items received"
        assert data["missing_items"] == []

    def test_from_dict(self):
        """Test ValidationResult from_dict method."""
        data = {
            "attempt": 3,
            "is_valid": False,
            "feedback": "Missing items",
            "missing_items": ["item1", "item2"],
        }

        result = ValidationResult.from_dict(data)

        assert result.attempt == 3
        assert result.is_valid is False
        assert result.feedback == "Missing items"
        assert result.missing_items == ["item1", "item2"]

    def test_from_dict_missing_items_default(self):
        """Test ValidationResult from_dict with missing missing_items field."""
        data = {
            "attempt": 1,
            "is_valid": True,
            "feedback": "OK",
        }

        result = ValidationResult.from_dict(data)

        assert result.missing_items == []

    def test_roundtrip_serialization(self):
        """Test ValidationResult to_dict -> from_dict roundtrip."""
        original = ValidationResult(
            attempt=5,
            is_valid=False,
            feedback="Incomplete data",
            missing_items=["field1", "field2", "field3"],
        )

        data = original.to_dict()
        restored = ValidationResult.from_dict(data)

        assert restored.attempt == original.attempt
        assert restored.is_valid == original.is_valid
        assert restored.feedback == original.feedback
        assert restored.missing_items == original.missing_items


class TestRedirectInfo:
    """Tests for RedirectInfo dataclass."""

    def test_creation(self):
        """Test RedirectInfo creation."""
        redirect = RedirectInfo(
            original_poc="original@test.com",
            redirect_email="new@test.com",
            redirect_reason="Department change",
            redirected_at=datetime.now(timezone.utc),
        )

        assert redirect.original_poc == "original@test.com"
        assert redirect.redirect_email == "new@test.com"
        assert redirect.redirect_reason == "Department change"

    def test_to_dict(self):
        """Test RedirectInfo to_dict method."""
        redirected_at = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        redirect = RedirectInfo(
            original_poc="original@test.com",
            redirect_email="new@test.com",
            redirect_reason="Department change",
            redirected_at=redirected_at,
        )

        data = redirect.to_dict()

        assert data["original_poc"] == "original@test.com"
        assert data["redirect_email"] == "new@test.com"
        assert data["redirect_reason"] == "Department change"
        assert data["redirected_at"] == "2025-01-15T10:30:00+00:00"

    def test_to_dict_optional_fields_none(self):
        """Test RedirectInfo to_dict with None optional fields."""
        redirect = RedirectInfo(
            original_poc="original@test.com",
            redirect_email="new@test.com",
        )

        data = redirect.to_dict()

        assert data["redirect_reason"] is None
        assert data["redirected_at"] is None

    def test_from_dict(self):
        """Test RedirectInfo from_dict method."""
        data = {
            "original_poc": "original@test.com",
            "redirect_email": "new@test.com",
            "redirect_reason": "Department change",
            "redirected_at": "2025-01-15T10:30:00+00:00",
        }

        redirect = RedirectInfo.from_dict(data)

        assert redirect.original_poc == "original@test.com"
        assert redirect.redirect_email == "new@test.com"
        assert redirect.redirect_reason == "Department change"
        assert redirect.redirected_at == datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)

    def test_from_dict_missing_optional_fields(self):
        """Test RedirectInfo from_dict with missing optional fields."""
        data = {
            "original_poc": "original@test.com",
            "redirect_email": "new@test.com",
        }

        redirect = RedirectInfo.from_dict(data)

        assert redirect.redirect_reason is None
        assert redirect.redirected_at is None

    def test_roundtrip_serialization(self):
        """Test RedirectInfo to_dict -> from_dict roundtrip."""
        original = RedirectInfo(
            original_poc="original@test.com",
            redirect_email="new@test.com",
            redirect_reason="Department change",
            redirected_at=datetime.now(timezone.utc),
        )

        data = original.to_dict()
        restored = RedirectInfo.from_dict(data)

        assert restored.original_poc == original.original_poc
        assert restored.redirect_email == original.redirect_email
        assert restored.redirect_reason == original.redirect_reason
        assert restored.redirected_at == original.redirected_at
