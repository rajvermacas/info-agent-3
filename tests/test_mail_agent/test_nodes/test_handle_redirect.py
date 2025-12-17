"""
Tests for the handle_redirect node.
"""

import pytest
from datetime import datetime, timezone
from uuid import UUID

from mail_agent.agent.state import (
    AgentState,
    ConversationState,
    RedirectInfo,
    get_conversation,
    update_conversation,
    all_conversations_complete,
    get_active_poc,
)
from mail_agent.agent.nodes.handle_redirect import handle_redirect


class TestRedirectInfo:
    """Tests for RedirectInfo dataclass."""

    def test_creation(self):
        """Test RedirectInfo creation."""
        redirect = RedirectInfo(
            original_poc="original@example.com",
            redirect_email="new@example.com",
            redirect_reason="Not the right department",
            redirected_at=datetime.now(timezone.utc),
        )

        assert redirect.original_poc == "original@example.com"
        assert redirect.redirect_email == "new@example.com"
        assert redirect.redirect_reason == "Not the right department"
        assert redirect.redirected_at is not None

    def test_creation_minimal(self):
        """Test RedirectInfo with minimal fields."""
        redirect = RedirectInfo(
            original_poc="original@example.com",
            redirect_email="new@example.com",
        )

        assert redirect.original_poc == "original@example.com"
        assert redirect.redirect_email == "new@example.com"
        assert redirect.redirect_reason is None
        assert redirect.redirected_at is None


class TestConversationStateWithRedirect:
    """Tests for ConversationState with redirect fields."""

    def test_redirected_status(self):
        """Test conversation with redirected status."""
        conv = ConversationState(
            poc_email="original@example.com",
            status="redirected",
            final_result="redirected",
            redirected_to="new@example.com",
        )

        assert conv.status == "redirected"
        assert conv.final_result == "redirected"
        assert conv.redirected_to == "new@example.com"

    def test_conversation_from_redirect(self):
        """Test conversation created from a redirect."""
        redirect_info = RedirectInfo(
            original_poc="original@example.com",
            redirect_email="new@example.com",
            redirect_reason="Wrong department",
            redirected_at=datetime.now(timezone.utc),
        )

        conv = ConversationState(
            poc_email="new@example.com",
            status="pending",
            redirected_from=redirect_info,
        )

        assert conv.redirected_from is not None
        assert conv.redirected_from.original_poc == "original@example.com"
        assert conv.redirected_from.redirect_reason == "Wrong department"

    def test_to_dict_with_redirect(self):
        """Test conversion to dictionary with redirect fields."""
        redirect_info = RedirectInfo(
            original_poc="original@example.com",
            redirect_email="new@example.com",
            redirect_reason="Wrong department",
            redirected_at=datetime(2025, 12, 17, 10, 0, 0, tzinfo=timezone.utc),
        )

        conv = ConversationState(
            poc_email="new@example.com",
            status="pending",
            redirected_from=redirect_info,
        )

        result = conv.to_dict()

        assert result["redirected_from"]["original_poc"] == "original@example.com"
        assert result["redirected_from"]["redirect_email"] == "new@example.com"
        assert result["redirected_from"]["redirect_reason"] == "Wrong department"
        assert result["redirected_from"]["redirected_at"] == "2025-12-17T10:00:00+00:00"

    def test_from_dict_with_redirect(self):
        """Test creation from dictionary with redirect fields."""
        data = {
            "poc_email": "new@example.com",
            "status": "pending",
            "attempt_count": 0,
            "sent_emails": [],
            "received_emails": [],
            "validation_results": [],
            "final_result": None,
            "error_message": None,
            "redirected_to": None,
            "redirected_from": {
                "original_poc": "original@example.com",
                "redirect_email": "new@example.com",
                "redirect_reason": "Wrong department",
                "redirected_at": "2025-12-17T10:00:00+00:00",
            },
        }

        conv = ConversationState.from_dict(data)

        assert conv.redirected_from is not None
        assert conv.redirected_from.original_poc == "original@example.com"
        assert conv.redirected_from.redirect_reason == "Wrong department"

    def test_roundtrip_with_redirect(self):
        """Test to_dict -> from_dict roundtrip with redirect."""
        redirect_info = RedirectInfo(
            original_poc="original@example.com",
            redirect_email="new@example.com",
            redirect_reason="Wrong department",
            redirected_at=datetime(2025, 12, 17, 10, 0, 0, tzinfo=timezone.utc),
        )

        original = ConversationState(
            poc_email="new@example.com",
            status="waiting",
            attempt_count=1,
            redirected_from=redirect_info,
        )

        # Roundtrip
        data = original.to_dict()
        restored = ConversationState.from_dict(data)

        assert restored.poc_email == original.poc_email
        assert restored.status == original.status
        assert restored.redirected_from is not None
        assert restored.redirected_from.original_poc == redirect_info.original_poc


class TestStateHelpersWithRedirect:
    """Tests for state helper functions with redirect status."""

    def test_all_conversations_complete_with_redirected(self):
        """Test all_conversations_complete handles redirected status."""
        state: AgentState = {
            "conversations": {
                "a@test.com": {"status": "success"},
                "b@test.com": {"status": "redirected"},
                "c@test.com": {"status": "failed"},
            }
        }

        assert all_conversations_complete(state) is True

    def test_all_conversations_incomplete_with_redirect_target(self):
        """Test all_conversations_complete with pending redirect target."""
        state: AgentState = {
            "conversations": {
                "a@test.com": {"status": "redirected"},
                "b@test.com": {"status": "waiting"},  # redirect target still waiting
            }
        }

        assert all_conversations_complete(state) is False

    def test_get_active_poc_skips_redirected(self):
        """Test get_active_poc skips redirected conversations."""
        state: AgentState = {
            "conversations": {
                "a@test.com": {"status": "redirected"},
                "b@test.com": {"status": "waiting"},
            }
        }

        result = get_active_poc(state)

        assert result == "b@test.com"

    def test_get_active_poc_all_redirected_or_done(self):
        """Test get_active_poc when all are terminal or redirected."""
        state: AgentState = {
            "conversations": {
                "a@test.com": {"status": "redirected"},
                "b@test.com": {"status": "success"},
            }
        }

        result = get_active_poc(state)

        assert result is None


class TestHandleRedirectNode:
    """Tests for the handle_redirect node function."""

    @pytest.mark.asyncio
    async def test_handle_redirect_success(self):
        """Test successful redirect handling."""
        # Set up initial state
        original_conv = ConversationState(
            poc_email="original@example.com",
            status="validating",
            attempt_count=1,
        )

        state: AgentState = {
            "conversations": {"original@example.com": original_conv.to_dict()},
            "current_poc": "original@example.com",
            "_redirect_detected": True,
            "_redirect_email": "new@example.com",
            "_redirect_reason": "I am not the right contact",
        }

        result = await handle_redirect(state)

        # Check original conversation is marked as redirected
        assert result["conversations"]["original@example.com"]["status"] == "redirected"
        assert result["conversations"]["original@example.com"]["final_result"] == "redirected"
        assert result["conversations"]["original@example.com"]["redirected_to"] == "new@example.com"

        # Check new conversation is created
        assert "new@example.com" in result["conversations"]
        assert result["conversations"]["new@example.com"]["status"] == "pending"
        assert result["conversations"]["new@example.com"]["redirected_from"]["original_poc"] == "original@example.com"

        # Check current_poc is updated
        assert result["current_poc"] == "new@example.com"

        # Check redirect data is cleared
        assert result["_redirect_detected"] is None
        assert result["_redirect_email"] is None
        assert result["_redirect_reason"] is None

    @pytest.mark.asyncio
    async def test_handle_redirect_no_current_poc(self):
        """Test handle_redirect with no current POC."""
        state: AgentState = {
            "conversations": {},
            "current_poc": None,
            "_redirect_email": "new@example.com",
        }

        result = await handle_redirect(state)

        assert "error" in result
        assert "No current POC set" in result["error"]

    @pytest.mark.asyncio
    async def test_handle_redirect_no_redirect_email(self):
        """Test handle_redirect with no redirect email."""
        state: AgentState = {
            "conversations": {"original@example.com": {"status": "validating"}},
            "current_poc": "original@example.com",
            "_redirect_email": None,
        }

        result = await handle_redirect(state)

        assert "error" in result
        assert "No redirect email found" in result["error"]

    @pytest.mark.asyncio
    async def test_handle_redirect_loop_detection(self):
        """Test redirect loop detection."""
        # Set up state where redirect target already has terminal status
        original_conv = ConversationState(
            poc_email="original@example.com",
            status="validating",
        )
        target_conv = ConversationState(
            poc_email="new@example.com",
            status="failed",  # Already processed
        )

        state: AgentState = {
            "conversations": {
                "original@example.com": original_conv.to_dict(),
                "new@example.com": target_conv.to_dict(),
            },
            "current_poc": "original@example.com",
            "_redirect_detected": True,
            "_redirect_email": "new@example.com",
            "_redirect_reason": "Try someone else",
        }

        result = await handle_redirect(state)

        # Original should be marked as failed due to loop
        assert result["conversations"]["original@example.com"]["status"] == "failed"
        assert "loop detected" in result["conversations"]["original@example.com"]["error_message"].lower()
