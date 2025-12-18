"""
Tests for the compose_all_emails node.

Tests cover:
1. Composing emails for all pending POCs concurrently
2. Handling follow-up emails for specific POCs
3. Error handling when no pending POCs
4. Progress message generation
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from mail_agent.agent.state import (
    AgentState,
    ConversationState,
    ParsedRequest,
)
from mail_agent.agent.nodes.compose_all_emails import compose_all_emails
from mail_agent.llm.prompts import ComposedEmail


class TestComposeAllEmails:
    """Tests for the compose_all_emails node function."""

    def _create_base_state(
        self,
        poc_emails: list[str] = None,
        statuses: dict[str, str] = None,
        followup_pocs: list[str] = None,
    ) -> AgentState:
        """Create a base state for testing with multiple POCs."""
        if poc_emails is None:
            poc_emails = ["raj@example.com", "neha@example.com"]
        if statuses is None:
            statuses = {email: "pending" for email in poc_emails}

        conversations = {}
        for email in poc_emails:
            conv = ConversationState(
                poc_email=email,
                status=statuses.get(email, "pending"),
                attempt_count=0,
            )
            conversations[email] = conv.to_dict()

        parsed = ParsedRequest(
            poc_emails=poc_emails,
            request_type="data_request",
            request_description="Get 10 food recipes",
            success_criteria="10 rows of recipes",
            expected_format="csv",
        )

        return {
            "conversations": conversations,
            "parsed_request": parsed.to_dict(),
            "_followup_pocs": followup_pocs,
        }

    @pytest.mark.asyncio
    async def test_compose_all_emails_for_pending_pocs(self):
        """Test composing emails for all pending POCs."""
        state = self._create_base_state(
            poc_emails=["raj@example.com", "neha@example.com"]
        )

        mock_composed = ComposedEmail(
            subject="Request for 10 Food Recipes",
            body="Dear Contact,\n\nPlease send recipes.\n\nBest regards,\ninfo-agent"
        )

        with patch("mail_agent.agent.nodes.compose_all_emails.LLMClient") as mock_llm_class:
            mock_llm = MagicMock()
            mock_llm.generate_structured = AsyncMock(return_value=mock_composed)
            mock_llm_class.return_value = mock_llm

            with patch("mail_agent.agent.nodes.compose_all_emails.get_settings") as mock_settings:
                mock_settings.return_value.agent_email = "info-agent@gmail.com"
                mock_settings.return_value.max_attempts = 5

                result = await compose_all_emails(state)

                # Verify composed emails were generated
                assert "_composed_emails" in result
                composed = result["_composed_emails"]
                assert len(composed) == 2

                # Verify both POCs have composed emails
                poc_emails_in_result = [e["poc_email"] for e in composed]
                assert "raj@example.com" in poc_emails_in_result
                assert "neha@example.com" in poc_emails_in_result

                # Verify email content
                for email in composed:
                    assert email["subject"] == "Request for 10 Food Recipes"
                    assert "recipes" in email["body"].lower()

    @pytest.mark.asyncio
    async def test_compose_all_emails_for_followup_pocs_only(self):
        """Test composing follow-up emails only for specified POCs."""
        state = self._create_base_state(
            poc_emails=["raj@example.com", "neha@example.com", "sumit@example.com"],
            followup_pocs=["neha@example.com"],  # Only neha needs follow-up
        )
        # Set statuses appropriately
        state["conversations"]["raj@example.com"]["status"] = "success"
        state["conversations"]["neha@example.com"]["status"] = "pending"
        state["conversations"]["sumit@example.com"]["status"] = "success"

        mock_composed = ComposedEmail(
            subject="Re: Request for 10 Food Recipes",
            body="Following up on my previous request...\n\nBest regards,\ninfo-agent"
        )

        with patch("mail_agent.agent.nodes.compose_all_emails.LLMClient") as mock_llm_class:
            mock_llm = MagicMock()
            mock_llm.generate_structured = AsyncMock(return_value=mock_composed)
            mock_llm_class.return_value = mock_llm

            with patch("mail_agent.agent.nodes.compose_all_emails.get_settings") as mock_settings:
                mock_settings.return_value.agent_email = "info-agent@gmail.com"
                mock_settings.return_value.max_attempts = 5

                result = await compose_all_emails(state)

                # Only neha should have a composed email
                composed = result["_composed_emails"]
                assert len(composed) == 1
                assert composed[0]["poc_email"] == "neha@example.com"

    @pytest.mark.asyncio
    async def test_compose_all_emails_skips_non_pending(self):
        """Test that compose_all_emails skips POCs not in pending status."""
        state = self._create_base_state(
            poc_emails=["raj@example.com", "neha@example.com", "sumit@example.com"],
        )
        # Set different statuses
        state["conversations"]["raj@example.com"]["status"] = "pending"
        state["conversations"]["neha@example.com"]["status"] = "success"
        state["conversations"]["sumit@example.com"]["status"] = "failed"

        mock_composed = ComposedEmail(
            subject="Request for 10 Food Recipes",
            body="Dear Contact,\n\nPlease send recipes.\n\nBest regards,\ninfo-agent"
        )

        with patch("mail_agent.agent.nodes.compose_all_emails.LLMClient") as mock_llm_class:
            mock_llm = MagicMock()
            mock_llm.generate_structured = AsyncMock(return_value=mock_composed)
            mock_llm_class.return_value = mock_llm

            with patch("mail_agent.agent.nodes.compose_all_emails.get_settings") as mock_settings:
                mock_settings.return_value.agent_email = "info-agent@gmail.com"
                mock_settings.return_value.max_attempts = 5

                result = await compose_all_emails(state)

                # Only raj (pending) should have composed email
                composed = result["_composed_emails"]
                assert len(composed) == 1
                assert composed[0]["poc_email"] == "raj@example.com"

    @pytest.mark.asyncio
    async def test_compose_all_emails_no_pending_pocs_error(self):
        """Test error handling when no pending POCs exist."""
        state = self._create_base_state(
            poc_emails=["raj@example.com"],
        )
        state["conversations"]["raj@example.com"]["status"] = "success"

        result = await compose_all_emails(state)

        assert result.get("error") is not None
        assert "No POCs" in result.get("error", "") or "no pending" in result.get("error", "").lower()
        assert result.get("current_node") == "error"

    @pytest.mark.asyncio
    async def test_compose_all_emails_sets_parallel_mode(self):
        """Test that compose_all_emails sets _parallel_mode to True."""
        state = self._create_base_state(
            poc_emails=["raj@example.com", "neha@example.com"]
        )

        mock_composed = ComposedEmail(
            subject="Request",
            body="Body\n\nBest regards,\ninfo-agent"
        )

        with patch("mail_agent.agent.nodes.compose_all_emails.LLMClient") as mock_llm_class:
            mock_llm = MagicMock()
            mock_llm.generate_structured = AsyncMock(return_value=mock_composed)
            mock_llm_class.return_value = mock_llm

            with patch("mail_agent.agent.nodes.compose_all_emails.get_settings") as mock_settings:
                mock_settings.return_value.agent_email = "info-agent@gmail.com"
                mock_settings.return_value.max_attempts = 5

                result = await compose_all_emails(state)

                assert result.get("_parallel_mode") is True

    @pytest.mark.asyncio
    async def test_compose_all_emails_clears_followup_pocs(self):
        """Test that compose_all_emails clears _followup_pocs after processing."""
        state = self._create_base_state(
            poc_emails=["raj@example.com", "neha@example.com"],
            followup_pocs=["neha@example.com"],
        )
        state["conversations"]["neha@example.com"]["status"] = "pending"

        mock_composed = ComposedEmail(
            subject="Request",
            body="Body\n\nBest regards,\ninfo-agent"
        )

        with patch("mail_agent.agent.nodes.compose_all_emails.LLMClient") as mock_llm_class:
            mock_llm = MagicMock()
            mock_llm.generate_structured = AsyncMock(return_value=mock_composed)
            mock_llm_class.return_value = mock_llm

            with patch("mail_agent.agent.nodes.compose_all_emails.get_settings") as mock_settings:
                mock_settings.return_value.agent_email = "info-agent@gmail.com"
                mock_settings.return_value.max_attempts = 5

                result = await compose_all_emails(state)

                # _followup_pocs should be cleared (None)
                assert result.get("_followup_pocs") is None

    @pytest.mark.asyncio
    async def test_compose_all_emails_progress_message(self):
        """Test that progress messages are generated correctly."""
        state = self._create_base_state(
            poc_emails=["raj@example.com", "neha@example.com", "sumit@example.com"]
        )

        mock_composed = ComposedEmail(
            subject="Request",
            body="Body\n\nBest regards,\ninfo-agent"
        )

        with patch("mail_agent.agent.nodes.compose_all_emails.LLMClient") as mock_llm_class:
            mock_llm = MagicMock()
            mock_llm.generate_structured = AsyncMock(return_value=mock_composed)
            mock_llm_class.return_value = mock_llm

            with patch("mail_agent.agent.nodes.compose_all_emails.get_settings") as mock_settings:
                mock_settings.return_value.agent_email = "info-agent@gmail.com"
                mock_settings.return_value.max_attempts = 5

                result = await compose_all_emails(state)

                # Verify progress message
                progress = result.get("progress_messages", [])
                assert len(progress) > 0
                assert "3" in progress[0] or "POC" in progress[0]

    @pytest.mark.asyncio
    async def test_compose_all_emails_handles_llm_error(self):
        """Test error handling when LLM fails for one POC."""
        state = self._create_base_state(
            poc_emails=["raj@example.com", "neha@example.com"]
        )

        with patch("mail_agent.agent.nodes.compose_all_emails.LLMClient") as mock_llm_class:
            mock_llm = MagicMock()
            # Simulate LLM error
            mock_llm.generate_structured = AsyncMock(side_effect=Exception("LLM API error"))
            mock_llm_class.return_value = mock_llm

            with patch("mail_agent.agent.nodes.compose_all_emails.get_settings") as mock_settings:
                mock_settings.return_value.agent_email = "info-agent@gmail.com"
                mock_settings.return_value.max_attempts = 5

                result = await compose_all_emails(state)

                # Should return error state
                assert result.get("error") is not None
                assert result.get("current_node") == "error"


class TestComposeAllEmailsConcurrency:
    """Tests for concurrent execution in compose_all_emails."""

    def _create_base_state(self, poc_count: int = 3) -> AgentState:
        """Create a state with multiple POCs."""
        poc_emails = [f"poc{i}@example.com" for i in range(poc_count)]

        conversations = {}
        for email in poc_emails:
            conv = ConversationState(
                poc_email=email,
                status="pending",
                attempt_count=0,
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
            "_followup_pocs": None,
        }

    @pytest.mark.asyncio
    async def test_compose_all_emails_concurrent_calls(self):
        """Test that LLM is called concurrently for all POCs."""
        state = self._create_base_state(poc_count=5)

        call_times = []

        async def mock_generate(*args, **kwargs):
            import asyncio
            call_times.append(datetime.now(timezone.utc))
            await asyncio.sleep(0.01)  # Small delay to simulate LLM call
            return ComposedEmail(
                subject="Request",
                body="Body\n\nBest regards,\ninfo-agent"
            )

        with patch("mail_agent.agent.nodes.compose_all_emails.LLMClient") as mock_llm_class:
            mock_llm = MagicMock()
            mock_llm.generate_structured = mock_generate
            mock_llm_class.return_value = mock_llm

            with patch("mail_agent.agent.nodes.compose_all_emails.get_settings") as mock_settings:
                mock_settings.return_value.agent_email = "info-agent@gmail.com"
                mock_settings.return_value.max_attempts = 5

                result = await compose_all_emails(state)

                # All 5 POCs should have composed emails
                assert len(result["_composed_emails"]) == 5

                # Verify calls were concurrent (all started within a short window)
                if len(call_times) >= 2:
                    time_diff = (call_times[-1] - call_times[0]).total_seconds()
                    # All calls should start within 0.1 seconds if concurrent
                    assert time_diff < 0.5, f"Calls not concurrent: {time_diff}s between first and last"
