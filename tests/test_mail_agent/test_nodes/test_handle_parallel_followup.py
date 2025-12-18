"""
Tests for the handle_parallel_followup node.

Tests cover:
1. Identifying POCs needing follow-up
2. Handling max attempts reached
3. Setting _followup_pocs list
4. Progress message generation
5. Skipping valid and redirected POCs
"""

import pytest
from unittest.mock import patch
from datetime import datetime, timezone

from mail_agent.agent.state import (
    AgentState,
    ConversationState,
    ParsedRequest,
)
from mail_agent.agent.nodes.handle_parallel_followup import handle_parallel_followup


class TestHandleParallelFollowup:
    """Tests for the handle_parallel_followup node function."""

    def _create_base_state(
        self,
        poc_emails: list[str] = None,
        poc_results: dict = None,
        attempt_counts: dict[str, int] = None,
    ) -> AgentState:
        """Create a base state for testing with POC processing results."""
        if poc_emails is None:
            poc_emails = ["raj@example.com", "neha@example.com"]

        if poc_results is None:
            # Default: all invalid
            poc_results = {
                email: {
                    "is_valid": False,
                    "is_redirect": False,
                    "feedback": "Missing data",
                }
                for email in poc_emails
            }

        if attempt_counts is None:
            attempt_counts = {email: 1 for email in poc_emails}

        conversations = {}
        for email in poc_emails:
            conv = ConversationState(
                poc_email=email,
                status="validating",
                attempt_count=attempt_counts.get(email, 1),
            )
            conversations[email] = conv.to_dict()

        parsed = ParsedRequest(
            poc_emails=poc_emails,
            request_type="data_request",
            request_description="Get data",
            success_criteria="Complete data",
            expected_format="csv",
        )

        return {
            "conversations": conversations,
            "parsed_request": parsed.to_dict(),
            "_poc_processing_results": poc_results,
            "_parallel_mode": True,
        }

    @pytest.mark.asyncio
    async def test_handle_parallel_followup_all_need_followup(self):
        """Test when all POCs need follow-up."""
        state = self._create_base_state(
            poc_emails=["raj@example.com", "neha@example.com"],
            poc_results={
                "raj@example.com": {"is_valid": False, "is_redirect": False, "feedback": "Missing"},
                "neha@example.com": {"is_valid": False, "is_redirect": False, "feedback": "Incomplete"},
            },
        )

        with patch("mail_agent.agent.nodes.handle_parallel_followup.get_settings") as mock_settings:
            mock_settings.return_value.max_attempts = 5

            result = await handle_parallel_followup(state)

            # Verify _followup_pocs
            followup_pocs = result.get("_followup_pocs", [])
            assert len(followup_pocs) == 2
            assert "raj@example.com" in followup_pocs
            assert "neha@example.com" in followup_pocs

            # Verify conversations reset to pending
            conversations = result.get("conversations", {})
            for email in ["raj@example.com", "neha@example.com"]:
                assert conversations[email]["status"] == "pending"

    @pytest.mark.asyncio
    async def test_handle_parallel_followup_skips_valid(self):
        """Test that valid POCs are skipped."""
        state = self._create_base_state(
            poc_emails=["raj@example.com", "neha@example.com"],
            poc_results={
                "raj@example.com": {"is_valid": True, "is_redirect": False},
                "neha@example.com": {"is_valid": False, "is_redirect": False, "feedback": "Missing"},
            },
        )

        with patch("mail_agent.agent.nodes.handle_parallel_followup.get_settings") as mock_settings:
            mock_settings.return_value.max_attempts = 5

            result = await handle_parallel_followup(state)

            # Only neha should need follow-up
            followup_pocs = result.get("_followup_pocs", [])
            assert len(followup_pocs) == 1
            assert "neha@example.com" in followup_pocs
            assert "raj@example.com" not in followup_pocs

    @pytest.mark.asyncio
    async def test_handle_parallel_followup_skips_redirected(self):
        """Test that redirected POCs are skipped."""
        state = self._create_base_state(
            poc_emails=["raj@example.com", "neha@example.com"],
            poc_results={
                "raj@example.com": {
                    "is_valid": False,
                    "is_redirect": True,
                    "redirect_email": "sumit@example.com",
                },
                "neha@example.com": {"is_valid": False, "is_redirect": False, "feedback": "Missing"},
            },
        )

        with patch("mail_agent.agent.nodes.handle_parallel_followup.get_settings") as mock_settings:
            mock_settings.return_value.max_attempts = 5

            result = await handle_parallel_followup(state)

            # Only neha should need follow-up (raj redirected)
            followup_pocs = result.get("_followup_pocs", [])
            assert len(followup_pocs) == 1
            assert "neha@example.com" in followup_pocs
            assert "raj@example.com" not in followup_pocs

    @pytest.mark.asyncio
    async def test_handle_parallel_followup_max_attempts_reached(self):
        """Test handling when max attempts reached."""
        state = self._create_base_state(
            poc_emails=["raj@example.com", "neha@example.com"],
            poc_results={
                "raj@example.com": {"is_valid": False, "is_redirect": False, "feedback": "Missing"},
                "neha@example.com": {"is_valid": False, "is_redirect": False, "feedback": "Missing"},
            },
            attempt_counts={
                "raj@example.com": 5,  # Max attempts reached
                "neha@example.com": 2,  # Still has attempts
            },
        )

        with patch("mail_agent.agent.nodes.handle_parallel_followup.get_settings") as mock_settings:
            mock_settings.return_value.max_attempts = 5

            result = await handle_parallel_followup(state)

            # Only neha should need follow-up (raj hit max)
            followup_pocs = result.get("_followup_pocs", [])
            assert len(followup_pocs) == 1
            assert "neha@example.com" in followup_pocs

            # Raj should be marked as failed
            conversations = result.get("conversations", {})
            raj_conv = conversations.get("raj@example.com", {})
            assert raj_conv["status"] == "failed"
            assert raj_conv["final_result"] == "failed_max_attempts"

    @pytest.mark.asyncio
    async def test_handle_parallel_followup_all_max_attempts(self):
        """Test when all POCs reach max attempts."""
        state = self._create_base_state(
            poc_emails=["raj@example.com", "neha@example.com"],
            poc_results={
                "raj@example.com": {"is_valid": False, "is_redirect": False},
                "neha@example.com": {"is_valid": False, "is_redirect": False},
            },
            attempt_counts={
                "raj@example.com": 5,
                "neha@example.com": 5,
            },
        )

        with patch("mail_agent.agent.nodes.handle_parallel_followup.get_settings") as mock_settings:
            mock_settings.return_value.max_attempts = 5

            result = await handle_parallel_followup(state)

            # No follow-ups needed
            followup_pocs = result.get("_followup_pocs")
            assert followup_pocs is None or len(followup_pocs) == 0

            # Both should be marked as failed
            conversations = result.get("conversations", {})
            for email in ["raj@example.com", "neha@example.com"]:
                assert conversations[email]["status"] == "failed"

    @pytest.mark.asyncio
    async def test_handle_parallel_followup_no_results_error(self):
        """Test error when no processing results exist."""
        state = self._create_base_state()
        state["_poc_processing_results"] = None

        result = await handle_parallel_followup(state)

        # With no results, should return empty followup list or handle gracefully
        assert result.get("_followup_pocs") is None or len(result.get("_followup_pocs", [])) == 0

    @pytest.mark.asyncio
    async def test_handle_parallel_followup_clears_poc_results(self):
        """Test that _poc_processing_results is cleared after handling."""
        state = self._create_base_state(
            poc_emails=["raj@example.com"],
            poc_results={
                "raj@example.com": {"is_valid": False, "is_redirect": False},
            },
        )

        with patch("mail_agent.agent.nodes.handle_parallel_followup.get_settings") as mock_settings:
            mock_settings.return_value.max_attempts = 5

            result = await handle_parallel_followup(state)

            # _poc_processing_results should be cleared
            assert result.get("_poc_processing_results") is None

    @pytest.mark.asyncio
    async def test_handle_parallel_followup_progress_message_followup(self):
        """Test progress message when follow-ups are needed."""
        state = self._create_base_state(
            poc_emails=["raj@example.com", "neha@example.com"],
            poc_results={
                "raj@example.com": {"is_valid": False, "is_redirect": False},
                "neha@example.com": {"is_valid": False, "is_redirect": False},
            },
        )

        with patch("mail_agent.agent.nodes.handle_parallel_followup.get_settings") as mock_settings:
            mock_settings.return_value.max_attempts = 5

            result = await handle_parallel_followup(state)

            # Verify progress message mentions follow-up
            progress = result.get("progress_messages", [])
            assert len(progress) > 0
            assert "follow" in progress[0].lower() or "2" in progress[0]

    @pytest.mark.asyncio
    async def test_handle_parallel_followup_progress_message_max_attempts(self):
        """Test progress message when all POCs reach max attempts."""
        state = self._create_base_state(
            poc_emails=["raj@example.com"],
            poc_results={
                "raj@example.com": {"is_valid": False, "is_redirect": False},
            },
            attempt_counts={"raj@example.com": 5},
        )

        with patch("mail_agent.agent.nodes.handle_parallel_followup.get_settings") as mock_settings:
            mock_settings.return_value.max_attempts = 5

            result = await handle_parallel_followup(state)

            # Verify progress message mentions max attempts
            progress = result.get("progress_messages", [])
            assert len(progress) > 0
            assert "max" in progress[0].lower() or "attempt" in progress[0].lower()

    @pytest.mark.asyncio
    async def test_handle_parallel_followup_mixed_results(self):
        """Test with mixed valid, invalid, and max attempts POCs."""
        state = self._create_base_state(
            poc_emails=["poc1@example.com", "poc2@example.com", "poc3@example.com", "poc4@example.com"],
            poc_results={
                "poc1@example.com": {"is_valid": True, "is_redirect": False},  # Valid - skip
                "poc2@example.com": {"is_valid": False, "is_redirect": True},  # Redirect - skip
                "poc3@example.com": {"is_valid": False, "is_redirect": False},  # Invalid - followup
                "poc4@example.com": {"is_valid": False, "is_redirect": False},  # Max attempts - fail
            },
            attempt_counts={
                "poc1@example.com": 1,
                "poc2@example.com": 1,
                "poc3@example.com": 2,
                "poc4@example.com": 5,  # Max
            },
        )

        with patch("mail_agent.agent.nodes.handle_parallel_followup.get_settings") as mock_settings:
            mock_settings.return_value.max_attempts = 5

            result = await handle_parallel_followup(state)

            # Only poc3 should need follow-up
            followup_pocs = result.get("_followup_pocs", [])
            assert len(followup_pocs) == 1
            assert "poc3@example.com" in followup_pocs

            # poc4 should be marked as failed
            conversations = result.get("conversations", {})
            assert conversations["poc4@example.com"]["status"] == "failed"


class TestHandleParallelFollowupCaseInsensitive:
    """Tests for case-insensitive POC email matching."""

    def _create_state_with_case_mismatch(self) -> AgentState:
        """Create a state with case mismatches between results and conversations."""
        conversations = {
            "Raj@Example.com": ConversationState(
                poc_email="Raj@Example.com",
                status="validating",
                attempt_count=1,
            ).to_dict(),
        }

        parsed = ParsedRequest(
            poc_emails=["Raj@Example.com"],
            request_type="data_request",
            request_description="Get data",
            success_criteria="Complete data",
            expected_format="csv",
        )

        # Results use different case
        poc_results = {
            "raj@example.com": {"is_valid": False, "is_redirect": False, "feedback": "Missing"},
        }

        return {
            "conversations": conversations,
            "parsed_request": parsed.to_dict(),
            "_poc_processing_results": poc_results,
            "_parallel_mode": True,
        }

    @pytest.mark.asyncio
    async def test_handle_parallel_followup_case_insensitive_matching(self):
        """Test that POC email matching is case-insensitive."""
        state = self._create_state_with_case_mismatch()

        with patch("mail_agent.agent.nodes.handle_parallel_followup.get_settings") as mock_settings:
            mock_settings.return_value.max_attempts = 5

            result = await handle_parallel_followup(state)

            # Should find and process the conversation despite case mismatch
            followup_pocs = result.get("_followup_pocs", [])
            # The POC should be identified for follow-up
            assert len(followup_pocs) == 1
