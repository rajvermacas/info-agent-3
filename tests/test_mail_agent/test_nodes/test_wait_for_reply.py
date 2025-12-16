"""
Unit tests for wait_for_reply node.

Tests cover:
- Interrupt exception propagation (not caught by error handler)
- Normal exception handling (TimeoutError, generic Exception)
- A2A mode interrupt behavior
- CLI mode blocking behavior
"""

import asyncio
import logging
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from langgraph.errors import GraphInterrupt

from mail_agent.agent.nodes.wait_for_reply import (
    wait_for_reply,
    set_a2a_mode,
    set_webhook_server,
    is_a2a_mode,
    _wait_for_reply_interrupt_mode,
)
from mail_agent.agent.state import ConversationState, SentEmail


logger = logging.getLogger(__name__)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_webhook_server() -> MagicMock:
    """Create a mock webhook server."""
    server = MagicMock()
    server.wait_for_event = AsyncMock(return_value=None)
    return server


@pytest.fixture
def sample_state() -> dict:
    """Create a sample agent state for testing."""
    poc_email = "test@example.com"
    sent_email = SentEmail(
        email_id=uuid4(),
        subject="Test Subject",
        body="Test body",
        sent_at=datetime.now(),
    )
    conversation = ConversationState(
        poc_email=poc_email,
        status="waiting",
        sent_emails=[sent_email],
        attempt_count=1,
    )
    return {
        "current_poc": poc_email,
        "task_id": "test-task-id",
        "conversations": {poc_email: conversation.to_dict()},
    }


@pytest.fixture(autouse=True)
def reset_a2a_mode():
    """Reset A2A mode after each test."""
    set_a2a_mode(False)
    yield
    set_a2a_mode(False)


# ============================================================================
# Interrupt Propagation Tests
# ============================================================================


class TestInterruptPropagation:
    """Tests for interrupt exception propagation."""

    @pytest.mark.asyncio
    async def test_interrupt_is_not_caught_in_a2a_mode(
        self, sample_state: dict
    ) -> None:
        """
        Test that GraphInterrupt exceptions are NOT caught by the error handler.

        This is the critical fix - the GraphInterrupt exception must propagate to
        the LangGraph engine so it can checkpoint and suspend execution.
        """
        set_a2a_mode(True)

        # Mock the interrupt function to raise GraphInterrupt
        with patch(
            "mail_agent.agent.nodes.wait_for_reply.interrupt",
            side_effect=GraphInterrupt({"reason": "test"}),
        ):
            # GraphInterrupt should propagate, not be caught
            with pytest.raises(GraphInterrupt):
                await wait_for_reply(sample_state)

    @pytest.mark.asyncio
    async def test_generic_exception_is_caught(self, sample_state: dict) -> None:
        """
        Test that generic Exception is caught and returns error response.

        Only Interrupt should propagate - other exceptions should return
        an error response.
        """
        set_a2a_mode(True)

        # Mock to raise a regular exception
        with patch(
            "mail_agent.agent.nodes.wait_for_reply._wait_for_reply_interrupt_mode",
            side_effect=ValueError("Test error"),
        ):
            result = await wait_for_reply(sample_state)

            assert result["current_node"] == "error"
            assert "Test error" in result["progress_messages"][0]

    @pytest.mark.asyncio
    async def test_timeout_error_is_caught(self, sample_state: dict) -> None:
        """
        Test that TimeoutError is caught and returns error response.
        """
        set_a2a_mode(True)

        # Mock to raise TimeoutError
        with patch(
            "mail_agent.agent.nodes.wait_for_reply._wait_for_reply_interrupt_mode",
            side_effect=asyncio.TimeoutError(),
        ):
            result = await wait_for_reply(sample_state)

            assert result["current_node"] == "error"
            assert "Timeout" in result["progress_messages"][0]

    @pytest.mark.asyncio
    async def test_interrupt_with_value_propagates(
        self, sample_state: dict
    ) -> None:
        """
        Test that GraphInterrupt with payload propagates correctly.
        """
        set_a2a_mode(True)
        interrupt_payload = {
            "reason": "waiting_for_reply",
            "poc_email": "test@example.com",
            "task_id": "test-task-id",
        }

        with patch(
            "mail_agent.agent.nodes.wait_for_reply.interrupt",
            side_effect=GraphInterrupt(interrupt_payload),
        ):
            with pytest.raises(GraphInterrupt) as exc_info:
                await wait_for_reply(sample_state)

            # Verify the interrupt has the correct payload
            # GraphInterrupt stores interrupts in its args
            assert interrupt_payload in exc_info.value.args


# ============================================================================
# A2A Mode Tests
# ============================================================================


class TestA2AMode:
    """Tests for A2A mode behavior."""

    def test_set_a2a_mode_enables(self) -> None:
        """Test that set_a2a_mode enables the mode."""
        set_a2a_mode(True)
        assert is_a2a_mode() is True

    def test_set_a2a_mode_disables(self) -> None:
        """Test that set_a2a_mode disables the mode."""
        set_a2a_mode(True)
        set_a2a_mode(False)
        assert is_a2a_mode() is False


# ============================================================================
# CLI Mode Tests
# ============================================================================


class TestCLIMode:
    """Tests for CLI mode behavior."""

    @pytest.mark.asyncio
    async def test_cli_mode_uses_webhook_server(
        self, sample_state: dict, mock_webhook_server: MagicMock
    ) -> None:
        """Test that CLI mode waits on webhook server."""
        set_a2a_mode(False)
        set_webhook_server(mock_webhook_server)

        # Mock wait_for_event to return an event from the expected POC
        mock_event = MagicMock()
        mock_event.email_id = "reply-email-123"
        mock_event.from_address = "test@example.com"
        mock_event.subject = "Re: Test Subject"
        mock_webhook_server.wait_for_event = AsyncMock(return_value=mock_event)

        result = await wait_for_reply(sample_state)

        # Verify wait_for_event was called
        mock_webhook_server.wait_for_event.assert_called()

        # Verify the email_id is in pending_webhooks
        assert result["pending_webhooks"] == ["reply-email-123"]


# ============================================================================
# Missing POC Tests
# ============================================================================


class TestMissingPOC:
    """Tests for missing current_poc handling."""

    @pytest.mark.asyncio
    async def test_no_current_poc_returns_error(self) -> None:
        """Test that missing current_poc returns error."""
        state = {"task_id": "test-task-id"}  # No current_poc

        result = await wait_for_reply(state)

        assert result["current_node"] == "error"
        assert "No current POC" in result["error"]
