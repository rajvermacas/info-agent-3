"""
Tests for the send_success_reply node.

Tests cover:
1. Email sent via SMTP
2. Email recorded in conversation history
3. Attempt count NOT incremented (acknowledgment, not request)
4. Composed state cleared after send
5. Progress message emitted
6. Error handling
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone
from uuid import uuid4

from mail_agent.agent.state import (
    AgentState,
    ConversationState,
    ParsedRequest,
    ValidationResult,
    SentEmail,
)
from mail_agent.agent.nodes.send_success_reply import send_success_reply


class TestSendSuccessReplyNode:
    """Tests for the send_success_reply node function."""

    def _create_base_state(
        self,
        poc_email: str = "test@example.com",
        composed_subject: str = "Re: Request for 10 Food Recipes",
        composed_body: str = "Thank you for the recipes.\n\nBest regards,\ninfo-agent",
        attempt_count: int = 1,
    ) -> AgentState:
        """Create a base state for testing."""
        validation_results = [
            ValidationResult(
                attempt=1,
                is_valid=True,
                feedback="All 10 recipes provided with correct format",
                missing_items=[],
            )
        ]

        sent_emails = [
            SentEmail(
                email_id=uuid4(),
                subject="Request for 10 Food Recipes",
                body="Please send 10 food recipes.",
                sent_at=datetime.now(timezone.utc),
            )
        ]

        conv = ConversationState(
            poc_email=poc_email,
            status="success",
            final_result="success",
            attempt_count=attempt_count,
            validation_results=validation_results,
            sent_emails=sent_emails,
        )

        parsed = ParsedRequest(
            poc_emails=[poc_email],
            request_type="data_request",
            request_description="Get 10 food recipes",
            success_criteria="10 rows of recipes in CSV format",
            expected_format="csv",
        )

        return {
            "conversations": {poc_email: conv.to_dict()},
            "current_poc": poc_email,
            "parsed_request": parsed.to_dict(),
            "_composed_subject": composed_subject,
            "_composed_body": composed_body,
        }

    @pytest.mark.asyncio
    async def test_send_success_reply_sends_email(self):
        """Test that send_success_reply sends email via SMTP."""
        state = self._create_base_state()

        with patch("mail_agent.agent.nodes.send_success_reply.SMTPSenderService") as mock_smtp_class:
            mock_smtp = MagicMock()
            mock_smtp.send_email = AsyncMock()
            mock_smtp_class.return_value = mock_smtp

            with patch("mail_agent.agent.nodes.send_success_reply.get_settings") as mock_settings:
                mock_settings.return_value.agent_email = "info-agent@gmail.com"

                await send_success_reply(state)

                # Verify SMTP send was called
                mock_smtp.send_email.assert_called_once()
                call_kwargs = mock_smtp.send_email.call_args.kwargs
                assert call_kwargs["to_addresses"] == ["test@example.com"]
                assert call_kwargs["subject"] == "Re: Request for 10 Food Recipes"
                assert "Thank you for the recipes" in call_kwargs["body_text"]

    @pytest.mark.asyncio
    async def test_send_success_reply_records_sent_email(self):
        """Test that sent email is recorded in conversation history."""
        state = self._create_base_state()
        original_email_count = len(state["conversations"]["test@example.com"]["sent_emails"])

        with patch("mail_agent.agent.nodes.send_success_reply.SMTPSenderService") as mock_smtp_class:
            mock_smtp = MagicMock()
            mock_smtp.send_email = AsyncMock()
            mock_smtp_class.return_value = mock_smtp

            with patch("mail_agent.agent.nodes.send_success_reply.get_settings") as mock_settings:
                mock_settings.return_value.agent_email = "info-agent@gmail.com"

                result = await send_success_reply(state)

                # Verify email was added to sent_emails
                conversations = result.get("conversations", {})
                conv_data = conversations.get("test@example.com", {})
                sent_emails = conv_data.get("sent_emails", [])
                assert len(sent_emails) == original_email_count + 1

                # Verify the new email has correct content
                new_email = sent_emails[-1]
                assert new_email["subject"] == "Re: Request for 10 Food Recipes"

    @pytest.mark.asyncio
    async def test_send_success_reply_does_not_increment_attempt_count(self):
        """Test that attempt_count is NOT incremented (acknowledgment, not request)."""
        original_attempt_count = 1
        state = self._create_base_state(attempt_count=original_attempt_count)

        with patch("mail_agent.agent.nodes.send_success_reply.SMTPSenderService") as mock_smtp_class:
            mock_smtp = MagicMock()
            mock_smtp.send_email = AsyncMock()
            mock_smtp_class.return_value = mock_smtp

            with patch("mail_agent.agent.nodes.send_success_reply.get_settings") as mock_settings:
                mock_settings.return_value.agent_email = "info-agent@gmail.com"

                result = await send_success_reply(state)

                # Verify attempt_count was NOT incremented
                conversations = result.get("conversations", {})
                conv_data = conversations.get("test@example.com", {})
                assert conv_data.get("attempt_count") == original_attempt_count

    @pytest.mark.asyncio
    async def test_send_success_reply_clears_composed_state(self):
        """Test that _composed_subject and _composed_body are cleared after send."""
        state = self._create_base_state()

        with patch("mail_agent.agent.nodes.send_success_reply.SMTPSenderService") as mock_smtp_class:
            mock_smtp = MagicMock()
            mock_smtp.send_email = AsyncMock()
            mock_smtp_class.return_value = mock_smtp

            with patch("mail_agent.agent.nodes.send_success_reply.get_settings") as mock_settings:
                mock_settings.return_value.agent_email = "info-agent@gmail.com"

                result = await send_success_reply(state)

                # Verify composed state is cleared
                assert result.get("_composed_subject") is None
                assert result.get("_composed_body") is None

    @pytest.mark.asyncio
    async def test_send_success_reply_progress_message(self):
        """Test that send_success_reply emits progress message."""
        state = self._create_base_state()

        with patch("mail_agent.agent.nodes.send_success_reply.SMTPSenderService") as mock_smtp_class:
            mock_smtp = MagicMock()
            mock_smtp.send_email = AsyncMock()
            mock_smtp_class.return_value = mock_smtp

            with patch("mail_agent.agent.nodes.send_success_reply.get_settings") as mock_settings:
                mock_settings.return_value.agent_email = "info-agent@gmail.com"

                result = await send_success_reply(state)

                # Verify progress message
                assert "progress_messages" in result
                assert len(result["progress_messages"]) > 0
                progress_msg = result["progress_messages"][0]
                assert "SUCCESS" in progress_msg
                assert "test@example.com" in progress_msg

    @pytest.mark.asyncio
    async def test_send_success_reply_no_current_poc_error(self):
        """Test error handling when no current POC is set."""
        state: AgentState = {
            "conversations": {},
            "current_poc": None,
            "parsed_request": None,
            "_composed_subject": "Re: Test",
            "_composed_body": "Test body",
        }

        result = await send_success_reply(state)

        assert result.get("error") == "No current POC set"
        assert result.get("current_node") == "error"

    @pytest.mark.asyncio
    async def test_send_success_reply_no_composed_email_error(self):
        """Test error handling when no composed email is in state."""
        conv = ConversationState(
            poc_email="test@example.com",
            status="success",
        )

        parsed = ParsedRequest(
            poc_emails=["test@example.com"],
            request_type="data_request",
            request_description="Get data",
            success_criteria="10 items",
            expected_format="csv",
        )

        state: AgentState = {
            "conversations": {"test@example.com": conv.to_dict()},
            "current_poc": "test@example.com",
            "parsed_request": parsed.to_dict(),
            "_composed_subject": None,
            "_composed_body": None,
        }

        result = await send_success_reply(state)

        assert result.get("error") == "No composed success acknowledgment found"
        assert result.get("current_node") == "error"

    @pytest.mark.asyncio
    async def test_send_success_reply_smtp_failure(self):
        """Test error handling when SMTP send fails."""
        state = self._create_base_state()

        with patch("mail_agent.agent.nodes.send_success_reply.SMTPSenderService") as mock_smtp_class:
            mock_smtp = MagicMock()
            mock_smtp.send_email = AsyncMock(side_effect=Exception("SMTP connection failed"))
            mock_smtp_class.return_value = mock_smtp

            with patch("mail_agent.agent.nodes.send_success_reply.get_settings") as mock_settings:
                mock_settings.return_value.agent_email = "info-agent@gmail.com"

                result = await send_success_reply(state)

                # Should handle error gracefully
                assert result.get("current_node") == "error"
                assert "progress_messages" in result
                assert "SMTP connection failed" in str(result["progress_messages"])

    @pytest.mark.asyncio
    async def test_send_success_reply_correct_current_node(self):
        """Test that current_node is set correctly on success."""
        state = self._create_base_state()

        with patch("mail_agent.agent.nodes.send_success_reply.SMTPSenderService") as mock_smtp_class:
            mock_smtp = MagicMock()
            mock_smtp.send_email = AsyncMock()
            mock_smtp_class.return_value = mock_smtp

            with patch("mail_agent.agent.nodes.send_success_reply.get_settings") as mock_settings:
                mock_settings.return_value.agent_email = "info-agent@gmail.com"

                result = await send_success_reply(state)

                assert result.get("current_node") == "send_success_reply"


class TestSendSuccessReplyLogging:
    """Tests for send_success_reply logging behavior."""

    @pytest.mark.asyncio
    async def test_logs_send_info(self):
        """Test that send_success_reply logs appropriate info."""
        conv = ConversationState(
            poc_email="test@example.com",
            status="success",
        )

        parsed = ParsedRequest(
            poc_emails=["test@example.com"],
            request_type="data_request",
            request_description="Get data",
            success_criteria="10 items",
            expected_format="csv",
        )

        state: AgentState = {
            "conversations": {"test@example.com": conv.to_dict()},
            "current_poc": "test@example.com",
            "parsed_request": parsed.to_dict(),
            "_composed_subject": "Re: Request",
            "_composed_body": "Thank you.\n\nBest regards,\ninfo-agent",
        }

        with patch("mail_agent.agent.nodes.send_success_reply.SMTPSenderService") as mock_smtp_class:
            mock_smtp = MagicMock()
            mock_smtp.send_email = AsyncMock()
            mock_smtp_class.return_value = mock_smtp

            with patch("mail_agent.agent.nodes.send_success_reply.get_settings") as mock_settings:
                mock_settings.return_value.agent_email = "info-agent@gmail.com"

                with patch("mail_agent.agent.nodes.send_success_reply.logger") as mock_logger:
                    await send_success_reply(state)

                    # Check that logging happened
                    log_calls = [str(call) for call in mock_logger.info.call_args_list]
                    send_log_found = any(
                        "send" in str(call).lower() or "acknowledgment" in str(call).lower()
                        for call in log_calls
                    )
                    assert send_log_found, f"Expected send/acknowledgment log, got: {log_calls}"
