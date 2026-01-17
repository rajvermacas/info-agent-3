"""
Tests for the compose_success_reply node.

Tests cover:
1. Success acknowledgment email composition with proper agent signature
2. Validation feedback inclusion in LLM prompt
3. System prompt formatting with agent_email
4. Error handling when no current POC
5. Re: subject format for replies
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
from mail_agent.agent.nodes.compose_success_reply import compose_success_reply
from mail_agent.llm.prompts import PromptTemplates, SuccessAcknowledgmentEmail


class TestSuccessAcknowledgmentPrompts:
    """Tests for the success acknowledgment prompt templates."""

    def test_success_acknowledgment_system_has_agent_email_placeholder(self):
        """Test that SUCCESS_ACKNOWLEDGMENT_SYSTEM has {agent_email} placeholder."""
        assert "{agent_email}" in PromptTemplates.SUCCESS_ACKNOWLEDGMENT_SYSTEM
        assert "Information Gathering Agent" in PromptTemplates.SUCCESS_ACKNOWLEDGMENT_SYSTEM
        assert "info-agent" in PromptTemplates.SUCCESS_ACKNOWLEDGMENT_SYSTEM.lower()

    def test_success_acknowledgment_system_forbids_placeholders(self):
        """Test that SUCCESS_ACKNOWLEDGMENT_SYSTEM explicitly forbids placeholder text."""
        prompt = PromptTemplates.SUCCESS_ACKNOWLEDGMENT_SYSTEM
        assert "NEVER use placeholder" in prompt
        assert "Do NOT include any bracketed placeholders" in prompt

    def test_success_acknowledgment_system_format_with_agent_email(self):
        """Test that SUCCESS_ACKNOWLEDGMENT_SYSTEM can be formatted with agent_email."""
        formatted = PromptTemplates.SUCCESS_ACKNOWLEDGMENT_SYSTEM.format(
            agent_email="test-agent@example.com"
        )
        assert "test-agent@example.com" in formatted
        assert "{agent_email}" not in formatted

    def test_compose_success_acknowledgment_includes_all_fields(self):
        """Test that compose_success_acknowledgment includes all required fields."""
        prompt = PromptTemplates.compose_success_acknowledgment(
            poc_email="test@example.com",
            request_description="Get 10 food recipes",
            success_criteria="10 rows of recipes in CSV format",
            validation_feedback="All 10 recipes received with correct format",
            original_subject="Request for Food Recipes",
        )

        assert "test@example.com" in prompt
        assert "Get 10 food recipes" in prompt
        assert "10 rows of recipes in CSV format" in prompt
        assert "All 10 recipes received with correct format" in prompt
        assert "Request for Food Recipes" in prompt

    def test_compose_success_acknowledgment_mentions_criteria(self):
        """Test that prompt instructs to confirm success criteria."""
        prompt = PromptTemplates.compose_success_acknowledgment(
            poc_email="test@example.com",
            request_description="Get data",
            success_criteria="10 items",
            validation_feedback="Data received",
            original_subject="Request",
        )

        assert "success criteria" in prompt.lower() or "criteria" in prompt.lower()
        assert "10 items" in prompt

    def test_compose_success_acknowledgment_re_subject_format(self):
        """Test that prompt instructs to use Re: subject format."""
        prompt = PromptTemplates.compose_success_acknowledgment(
            poc_email="test@example.com",
            request_description="Get data",
            success_criteria="10 items",
            validation_feedback="Data received",
            original_subject="Request for Data",
        )

        assert 'Re: Request for Data' in prompt


class TestComposeSuccessReplyNode:
    """Tests for the compose_success_reply node function."""

    def _create_base_state(
        self,
        poc_email: str = "test@example.com",
        validation_results: list = None,
        sent_emails: list = None,
    ) -> AgentState:
        """Create a base state for testing."""
        if validation_results is None:
            validation_results = [
                ValidationResult(
                    attempt=1,
                    is_valid=True,
                    feedback="All 10 recipes provided with correct format and content",
                    missing_items=[],
                )
            ]

        if sent_emails is None:
            sent_emails = [
                SentEmail(
                    email_id=uuid4(),
                    subject="Request for 10 Food Recipes",
                    body="Please send 10 food recipes in CSV format.",
                    sent_at=datetime.now(timezone.utc),
                )
            ]

        conv = ConversationState(
            poc_email=poc_email,
            status="success",
            final_result="success",
            attempt_count=1,
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
        }

    @pytest.mark.asyncio
    async def test_compose_success_reply_uses_formatted_system_prompt(self):
        """Test that compose_success_reply formats system prompt with agent_email."""
        state = self._create_base_state()

        mock_composed = SuccessAcknowledgmentEmail(
            subject="Re: Request for 10 Food Recipes",
            body="Thank you for the recipes.\n\nBest regards,\ninfo-agent"
        )

        with patch("mail_agent.agent.nodes.compose_success_reply.LLMClient") as mock_llm_class:
            mock_llm = MagicMock()
            mock_llm.generate_structured = AsyncMock(return_value=mock_composed)
            mock_llm_class.return_value = mock_llm

            with patch("mail_agent.agent.nodes.compose_success_reply.get_settings") as mock_settings:
                mock_settings.return_value.agent_email = "info-agent@gmail.com"

                result = await compose_success_reply(state)

                # Verify system prompt was formatted with agent_email
                call_args = mock_llm.generate_structured.call_args
                system_prompt = call_args.kwargs.get("system_prompt", "")
                assert "info-agent@gmail.com" in system_prompt
                assert "{agent_email}" not in system_prompt

    @pytest.mark.asyncio
    async def test_compose_success_reply_includes_validation_feedback(self):
        """Test that compose_success_reply includes validation feedback in prompt."""
        validation_feedback = "All 10 recipes provided with correct format"
        validation_results = [
            ValidationResult(
                attempt=1,
                is_valid=True,
                feedback=validation_feedback,
                missing_items=[],
            )
        ]
        state = self._create_base_state(validation_results=validation_results)

        mock_composed = SuccessAcknowledgmentEmail(
            subject="Re: Request",
            body="Thank you.\n\nBest regards,\ninfo-agent"
        )

        with patch("mail_agent.agent.nodes.compose_success_reply.LLMClient") as mock_llm_class:
            mock_llm = MagicMock()
            mock_llm.generate_structured = AsyncMock(return_value=mock_composed)
            mock_llm_class.return_value = mock_llm

            with patch("mail_agent.agent.nodes.compose_success_reply.get_settings") as mock_settings:
                mock_settings.return_value.agent_email = "info-agent@gmail.com"

                await compose_success_reply(state)

                # Verify validation feedback is in the prompt
                call_args = mock_llm.generate_structured.call_args
                prompt = call_args.kwargs.get("prompt", call_args.args[0] if call_args.args else "")
                assert validation_feedback in prompt

    @pytest.mark.asyncio
    async def test_compose_success_reply_uses_per_poc_success_criteria(self):
        """Test that per-POC context is used instead of global parsed_request fields."""
        poc_email = "raj@gmail.com"
        state = self._create_base_state(poc_email=poc_email)
        state["parsed_request"]["success_criteria"] = "10 rows of recipes in CSV format"
        state["poc_request_contexts"] = {
            poc_email: {
                "request_description": "Provide 10 animal names",
                "success_criteria": "CSV with exactly 10 distinct animal names",
                "expected_format": "csv",
            }
        }

        mock_composed = SuccessAcknowledgmentEmail(
            subject="Re: Request",
            body="Thank you.\n\nBest regards,\ninfo-agent"
        )

        with patch("mail_agent.agent.nodes.compose_success_reply.LLMClient") as mock_llm_class:
            mock_llm = MagicMock()
            mock_llm.generate_structured = AsyncMock(return_value=mock_composed)
            mock_llm_class.return_value = mock_llm

            with patch("mail_agent.agent.nodes.compose_success_reply.get_settings") as mock_settings:
                mock_settings.return_value.agent_email = "info-agent@gmail.com"

                await compose_success_reply(state)

                call_args = mock_llm.generate_structured.call_args
                prompt = call_args.kwargs.get("prompt", call_args.args[0] if call_args.args else "")
                assert "CSV with exactly 10 distinct animal names" in prompt
                assert "10 rows of recipes" not in prompt

    @pytest.mark.asyncio
    async def test_compose_success_reply_stores_result(self):
        """Test that composed email is stored in state for send_success_reply node."""
        state = self._create_base_state()

        mock_composed = SuccessAcknowledgmentEmail(
            subject="Re: Request for 10 Food Recipes",
            body="Thank you for the recipes.\n\nBest regards,\ninfo-agent"
        )

        with patch("mail_agent.agent.nodes.compose_success_reply.LLMClient") as mock_llm_class:
            mock_llm = MagicMock()
            mock_llm.generate_structured = AsyncMock(return_value=mock_composed)
            mock_llm_class.return_value = mock_llm

            with patch("mail_agent.agent.nodes.compose_success_reply.get_settings") as mock_settings:
                mock_settings.return_value.agent_email = "info-agent@gmail.com"

                result = await compose_success_reply(state)

                assert result.get("_composed_subject") == "Re: Request for 10 Food Recipes"
                assert result.get("_composed_body") == "Thank you for the recipes.\n\nBest regards,\ninfo-agent"

    @pytest.mark.asyncio
    async def test_compose_success_reply_no_current_poc_error(self):
        """Test error handling when no current POC is set."""
        state: AgentState = {
            "conversations": {},
            "current_poc": None,
            "parsed_request": None,
        }

        result = await compose_success_reply(state)

        assert result.get("error") == "No current POC set"
        assert result.get("current_node") == "error"

    @pytest.mark.asyncio
    async def test_compose_success_reply_uses_original_subject(self):
        """Test that compose_success_reply uses original subject for Re: format."""
        original_subject = "Important Data Request"
        sent_emails = [
            SentEmail(
                email_id=uuid4(),
                subject=original_subject,
                body="Please send data.",
                sent_at=datetime.now(timezone.utc),
            )
        ]
        state = self._create_base_state(sent_emails=sent_emails)

        mock_composed = SuccessAcknowledgmentEmail(
            subject=f"Re: {original_subject}",
            body="Thank you.\n\nBest regards,\ninfo-agent"
        )

        with patch("mail_agent.agent.nodes.compose_success_reply.LLMClient") as mock_llm_class:
            mock_llm = MagicMock()
            mock_llm.generate_structured = AsyncMock(return_value=mock_composed)
            mock_llm_class.return_value = mock_llm

            with patch("mail_agent.agent.nodes.compose_success_reply.get_settings") as mock_settings:
                mock_settings.return_value.agent_email = "info-agent@gmail.com"

                await compose_success_reply(state)

                # Verify original subject is in the prompt
                call_args = mock_llm.generate_structured.call_args
                prompt = call_args.kwargs.get("prompt", call_args.args[0] if call_args.args else "")
                assert original_subject in prompt

    @pytest.mark.asyncio
    async def test_compose_success_reply_progress_message(self):
        """Test that compose_success_reply emits progress message."""
        state = self._create_base_state()

        mock_composed = SuccessAcknowledgmentEmail(
            subject="Re: Request for 10 Food Recipes",
            body="Thank you.\n\nBest regards,\ninfo-agent"
        )

        with patch("mail_agent.agent.nodes.compose_success_reply.LLMClient") as mock_llm_class:
            mock_llm = MagicMock()
            mock_llm.generate_structured = AsyncMock(return_value=mock_composed)
            mock_llm_class.return_value = mock_llm

            with patch("mail_agent.agent.nodes.compose_success_reply.get_settings") as mock_settings:
                mock_settings.return_value.agent_email = "info-agent@gmail.com"

                result = await compose_success_reply(state)

                assert "progress_messages" in result
                assert len(result["progress_messages"]) > 0
                assert "test@example.com" in result["progress_messages"][0]

    @pytest.mark.asyncio
    async def test_compose_success_reply_handles_no_validation_results(self):
        """Test that compose_success_reply handles missing validation results gracefully."""
        state = self._create_base_state(validation_results=[])

        mock_composed = SuccessAcknowledgmentEmail(
            subject="Re: Request",
            body="Thank you.\n\nBest regards,\ninfo-agent"
        )

        with patch("mail_agent.agent.nodes.compose_success_reply.LLMClient") as mock_llm_class:
            mock_llm = MagicMock()
            mock_llm.generate_structured = AsyncMock(return_value=mock_composed)
            mock_llm_class.return_value = mock_llm

            with patch("mail_agent.agent.nodes.compose_success_reply.get_settings") as mock_settings:
                mock_settings.return_value.agent_email = "info-agent@gmail.com"

                result = await compose_success_reply(state)

                # Should succeed with default feedback
                assert result.get("error") is None
                assert result.get("_composed_subject") == "Re: Request"


class TestComposeSuccessReplyLogging:
    """Tests for compose_success_reply logging behavior."""

    @pytest.mark.asyncio
    async def test_logs_success_acknowledgment_info(self):
        """Test that compose_success_reply logs appropriate info."""
        validation_results = [
            ValidationResult(
                attempt=1,
                is_valid=True,
                feedback="Valid response",
                missing_items=[],
            )
        ]
        sent_emails = [
            SentEmail(
                email_id=uuid4(),
                subject="Request",
                body="Body",
                sent_at=datetime.now(timezone.utc),
            )
        ]

        conv = ConversationState(
            poc_email="test@example.com",
            status="success",
            validation_results=validation_results,
            sent_emails=sent_emails,
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
        }

        mock_composed = SuccessAcknowledgmentEmail(
            subject="Re: Request",
            body="Thank you.\n\nBest regards,\ninfo-agent"
        )

        with patch("mail_agent.agent.nodes.compose_success_reply.LLMClient") as mock_llm_class:
            mock_llm = MagicMock()
            mock_llm.generate_structured = AsyncMock(return_value=mock_composed)
            mock_llm_class.return_value = mock_llm

            with patch("mail_agent.agent.nodes.compose_success_reply.get_settings") as mock_settings:
                mock_settings.return_value.agent_email = "info-agent@gmail.com"

                with patch("mail_agent.agent.nodes.compose_success_reply.logger") as mock_logger:
                    await compose_success_reply(state)

                    # Check that acknowledgment logging happened
                    log_calls = [str(call) for call in mock_logger.info.call_args_list]
                    acknowledgment_log_found = any(
                        "success" in str(call).lower() or "acknowledgment" in str(call).lower()
                        for call in log_calls
                    )
                    assert acknowledgment_log_found, f"Expected success/acknowledgment log, got: {log_calls}"
