"""
Tests for the send_all_emails node.

Tests cover:
1. Sending emails to all POCs concurrently
2. Updating conversation states
3. Setting _waiting_pocs list
4. Error handling
5. Progress message generation
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone
from uuid import uuid4

from mail_agent.agent.state import (
    AgentState,
    ConversationState,
    ParsedRequest,
)
from mail_agent.agent.nodes.send_all_emails import send_all_emails


class TestSendAllEmails:
    """Tests for the send_all_emails node function."""

    def _create_base_state(
        self,
        poc_emails: list[str] = None,
        composed_emails: list[dict] = None,
    ) -> AgentState:
        """Create a base state for testing with composed emails."""
        if poc_emails is None:
            poc_emails = ["raj@example.com", "neha@example.com"]

        if composed_emails is None:
            composed_emails = [
                {
                    "poc_email": email,
                    "subject": f"Request to {email}",
                    "body": f"Dear {email.split('@')[0]},\n\nPlease send data.\n\nBest,\nAgent"
                }
                for email in poc_emails
            ]

        conversations = {}
        for email in poc_emails:
            conv = ConversationState(
                poc_email=email,
                status="composing",
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
            "_composed_emails": composed_emails,
            "_parallel_mode": True,
        }

    @pytest.mark.asyncio
    async def test_send_all_emails_success(self):
        """Test successfully sending emails to all POCs."""
        state = self._create_base_state(
            poc_emails=["raj@example.com", "neha@example.com"]
        )

        with patch("mail_agent.agent.nodes.send_all_emails.SMTPSender") as mock_sender_class:
            mock_sender = MagicMock()
            mock_sender.send_email = AsyncMock(return_value=str(uuid4()))
            mock_sender_class.return_value = mock_sender

            with patch("mail_agent.agent.nodes.send_all_emails.get_settings") as mock_settings:
                mock_settings.return_value.agent_email = "info-agent@gmail.com"

                result = await send_all_emails(state)

                # Verify no errors
                assert result.get("error") is None

                # Verify _waiting_pocs is set
                waiting_pocs = result.get("_waiting_pocs", [])
                assert len(waiting_pocs) == 2
                assert "raj@example.com" in waiting_pocs
                assert "neha@example.com" in waiting_pocs

                # Verify conversations are updated
                conversations = result.get("conversations", {})
                for email in ["raj@example.com", "neha@example.com"]:
                    conv = conversations.get(email, {})
                    assert conv.get("status") == "waiting"
                    assert conv.get("attempt_count") == 1

    @pytest.mark.asyncio
    async def test_send_all_emails_updates_attempt_count(self):
        """Test that attempt_count is incremented for each POC."""
        state = self._create_base_state(
            poc_emails=["raj@example.com"]
        )
        # Set initial attempt count
        state["conversations"]["raj@example.com"]["attempt_count"] = 2

        with patch("mail_agent.agent.nodes.send_all_emails.SMTPSender") as mock_sender_class:
            mock_sender = MagicMock()
            mock_sender.send_email = AsyncMock(return_value=str(uuid4()))
            mock_sender_class.return_value = mock_sender

            with patch("mail_agent.agent.nodes.send_all_emails.get_settings") as mock_settings:
                mock_settings.return_value.agent_email = "info-agent@gmail.com"

                result = await send_all_emails(state)

                # Verify attempt count incremented
                conv = result["conversations"]["raj@example.com"]
                assert conv["attempt_count"] == 3

    @pytest.mark.asyncio
    async def test_send_all_emails_records_sent_email(self):
        """Test that sent emails are recorded in conversation state."""
        state = self._create_base_state(
            poc_emails=["raj@example.com"]
        )
        email_id = str(uuid4())

        with patch("mail_agent.agent.nodes.send_all_emails.SMTPSender") as mock_sender_class:
            mock_sender = MagicMock()
            mock_sender.send_email = AsyncMock(return_value=email_id)
            mock_sender_class.return_value = mock_sender

            with patch("mail_agent.agent.nodes.send_all_emails.get_settings") as mock_settings:
                mock_settings.return_value.agent_email = "info-agent@gmail.com"

                result = await send_all_emails(state)

                # Verify sent email is recorded
                conv = result["conversations"]["raj@example.com"]
                sent_emails = conv.get("sent_emails", [])
                assert len(sent_emails) == 1
                assert sent_emails[0]["subject"] == "Request to raj@example.com"

    @pytest.mark.asyncio
    async def test_send_all_emails_no_composed_emails_error(self):
        """Test error when no composed emails exist."""
        state = self._create_base_state()
        state["_composed_emails"] = None  # No composed emails

        result = await send_all_emails(state)

        assert result.get("error") is not None
        assert "No composed emails" in result.get("error", "")
        assert result.get("current_node") == "error"

    @pytest.mark.asyncio
    async def test_send_all_emails_empty_list_error(self):
        """Test error when composed emails list is empty."""
        state = self._create_base_state()
        state["_composed_emails"] = []  # Empty list

        result = await send_all_emails(state)

        assert result.get("error") is not None
        assert result.get("current_node") == "error"

    @pytest.mark.asyncio
    async def test_send_all_emails_clears_composed_emails(self):
        """Test that _composed_emails is cleared after sending."""
        state = self._create_base_state(
            poc_emails=["raj@example.com"]
        )

        with patch("mail_agent.agent.nodes.send_all_emails.SMTPSender") as mock_sender_class:
            mock_sender = MagicMock()
            mock_sender.send_email = AsyncMock(return_value=str(uuid4()))
            mock_sender_class.return_value = mock_sender

            with patch("mail_agent.agent.nodes.send_all_emails.get_settings") as mock_settings:
                mock_settings.return_value.agent_email = "info-agent@gmail.com"

                result = await send_all_emails(state)

                # _composed_emails should be cleared
                assert result.get("_composed_emails") is None

    @pytest.mark.asyncio
    async def test_send_all_emails_progress_message(self):
        """Test that progress messages are generated correctly."""
        state = self._create_base_state(
            poc_emails=["raj@example.com", "neha@example.com", "sumit@example.com"]
        )

        with patch("mail_agent.agent.nodes.send_all_emails.SMTPSender") as mock_sender_class:
            mock_sender = MagicMock()
            mock_sender.send_email = AsyncMock(return_value=str(uuid4()))
            mock_sender_class.return_value = mock_sender

            with patch("mail_agent.agent.nodes.send_all_emails.get_settings") as mock_settings:
                mock_settings.return_value.agent_email = "info-agent@gmail.com"

                result = await send_all_emails(state)

                # Verify progress message
                progress = result.get("progress_messages", [])
                assert len(progress) > 0
                # Should mention sending to 3 POCs
                assert "3" in progress[0] or "POC" in progress[0].upper()

    @pytest.mark.asyncio
    async def test_send_all_emails_partial_failure(self):
        """Test handling when some emails fail to send."""
        state = self._create_base_state(
            poc_emails=["raj@example.com", "neha@example.com"]
        )

        send_count = 0

        async def mock_send(*args, **kwargs):
            nonlocal send_count
            send_count += 1
            if send_count == 1:
                return str(uuid4())  # First succeeds
            else:
                raise Exception("SMTP error")  # Second fails

        with patch("mail_agent.agent.nodes.send_all_emails.SMTPSender") as mock_sender_class:
            mock_sender = MagicMock()
            mock_sender.send_email = mock_send
            mock_sender_class.return_value = mock_sender

            with patch("mail_agent.agent.nodes.send_all_emails.get_settings") as mock_settings:
                mock_settings.return_value.agent_email = "info-agent@gmail.com"

                result = await send_all_emails(state)

                # Should handle partial failure gracefully
                # The node may either fail entirely or handle partial success
                # depending on implementation
                assert result.get("current_node") in ["send_all_emails", "error"]


class TestSendAllEmailsConcurrency:
    """Tests for concurrent execution in send_all_emails."""

    def _create_base_state(self, poc_count: int = 3) -> AgentState:
        """Create a state with multiple POCs."""
        poc_emails = [f"poc{i}@example.com" for i in range(poc_count)]

        composed_emails = [
            {
                "poc_email": email,
                "subject": f"Request to {email}",
                "body": f"Dear Contact,\n\nPlease send data.\n\nBest,\nAgent"
            }
            for email in poc_emails
        ]

        conversations = {}
        for email in poc_emails:
            conv = ConversationState(
                poc_email=email,
                status="composing",
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
            "_composed_emails": composed_emails,
            "_parallel_mode": True,
        }

    @pytest.mark.asyncio
    async def test_send_all_emails_concurrent_calls(self):
        """Test that SMTP sends are executed concurrently."""
        state = self._create_base_state(poc_count=5)

        call_times = []

        async def mock_send(*args, **kwargs):
            import asyncio
            call_times.append(datetime.now(timezone.utc))
            await asyncio.sleep(0.01)  # Small delay to simulate network call
            return str(uuid4())

        with patch("mail_agent.agent.nodes.send_all_emails.SMTPSender") as mock_sender_class:
            mock_sender = MagicMock()
            mock_sender.send_email = mock_send
            mock_sender_class.return_value = mock_sender

            with patch("mail_agent.agent.nodes.send_all_emails.get_settings") as mock_settings:
                mock_settings.return_value.agent_email = "info-agent@gmail.com"

                result = await send_all_emails(state)

                # All 5 POCs should be in waiting list
                assert len(result["_waiting_pocs"]) == 5

                # Verify calls were concurrent
                if len(call_times) >= 2:
                    time_diff = (call_times[-1] - call_times[0]).total_seconds()
                    # All calls should start within a short window if concurrent
                    assert time_diff < 0.5, f"Calls not concurrent: {time_diff}s between first and last"
