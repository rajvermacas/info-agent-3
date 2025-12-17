"""
Tests for the compose_email node.

Tests cover:
1. Initial email composition with proper agent signature (no placeholders)
2. Follow-up email composition with proper agent signature
3. Redirect email composition mentioning the referrer
4. System prompt formatting with agent_email
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from mail_agent.agent.state import (
    AgentState,
    ConversationState,
    RedirectInfo,
    ParsedRequest,
    ValidationResult,
    SentEmail,
)
from mail_agent.agent.nodes.compose_email import compose_email
from mail_agent.llm.prompts import PromptTemplates, ComposedEmail, FollowUpEmail


class TestPromptTemplates:
    """Tests for the PromptTemplates class updates."""

    def test_compose_system_has_agent_email_placeholder(self):
        """Test that COMPOSE_SYSTEM prompt has {agent_email} placeholder."""
        assert "{agent_email}" in PromptTemplates.COMPOSE_SYSTEM
        assert "Information Gathering Agent" in PromptTemplates.COMPOSE_SYSTEM
        assert "info-agent" in PromptTemplates.COMPOSE_SYSTEM.lower()

    def test_compose_system_forbids_placeholders(self):
        """Test that COMPOSE_SYSTEM explicitly forbids placeholder text."""
        prompt = PromptTemplates.COMPOSE_SYSTEM
        assert "[Your Name]" in prompt or "NEVER use placeholder" in prompt
        assert "Do NOT include any bracketed placeholders" in prompt

    def test_followup_system_has_agent_email_placeholder(self):
        """Test that FOLLOWUP_SYSTEM prompt has {agent_email} placeholder."""
        assert "{agent_email}" in PromptTemplates.FOLLOWUP_SYSTEM
        assert "Information Gathering Agent" in PromptTemplates.FOLLOWUP_SYSTEM

    def test_followup_system_forbids_placeholders(self):
        """Test that FOLLOWUP_SYSTEM explicitly forbids placeholder text."""
        prompt = PromptTemplates.FOLLOWUP_SYSTEM
        assert "NEVER use placeholder" in prompt
        assert "info-agent" in prompt.lower()

    def test_compose_system_format_with_agent_email(self):
        """Test that COMPOSE_SYSTEM can be formatted with agent_email."""
        formatted = PromptTemplates.COMPOSE_SYSTEM.format(
            agent_email="test-agent@example.com"
        )
        assert "test-agent@example.com" in formatted
        assert "{agent_email}" not in formatted

    def test_followup_system_format_with_agent_email(self):
        """Test that FOLLOWUP_SYSTEM can be formatted with agent_email."""
        formatted = PromptTemplates.FOLLOWUP_SYSTEM.format(
            agent_email="test-agent@example.com"
        )
        assert "test-agent@example.com" in formatted
        assert "{agent_email}" not in formatted


class TestComposeEmailForRedirectPrompt:
    """Tests for the compose_email_for_redirect prompt template."""

    def test_compose_email_for_redirect_basic(self):
        """Test compose_email_for_redirect with basic parameters."""
        prompt = PromptTemplates.compose_email_for_redirect(
            poc_email="new-contact@example.com",
            request_description="Get 10 food recipes",
            expected_format="csv",
            success_criteria="10 rows of recipes",
            referrer_email="original@example.com",
        )

        assert "new-contact@example.com" in prompt
        assert "Get 10 food recipes" in prompt
        assert "csv" in prompt
        assert "10 rows of recipes" in prompt
        assert "original@example.com" in prompt
        # Check that redirect context is included
        assert "REDIRECT" in prompt
        assert "referred" in prompt.lower() or "redirected" in prompt.lower()

    def test_compose_email_for_redirect_with_reason(self):
        """Test compose_email_for_redirect includes redirect reason when provided."""
        prompt = PromptTemplates.compose_email_for_redirect(
            poc_email="new-contact@example.com",
            request_description="Get 10 food recipes",
            expected_format="csv",
            success_criteria="10 rows of recipes",
            referrer_email="original@example.com",
            redirect_reason="I am not the right point of contact",
        )

        assert "I am not the right point of contact" in prompt

    def test_compose_email_for_redirect_without_reason(self):
        """Test compose_email_for_redirect works without redirect reason."""
        prompt = PromptTemplates.compose_email_for_redirect(
            poc_email="new-contact@example.com",
            request_description="Get 10 food recipes",
            expected_format="csv",
            success_criteria="10 rows of recipes",
            referrer_email="original@example.com",
            redirect_reason=None,
        )

        assert "new-contact@example.com" in prompt
        assert "original@example.com" in prompt
        # Should not have "They mentioned:" when no reason
        assert "They mentioned:" not in prompt

    def test_compose_email_for_redirect_mentions_referrer_explicitly(self):
        """Test that prompt explicitly instructs to mention referrer."""
        prompt = PromptTemplates.compose_email_for_redirect(
            poc_email="sumit@ubs.com",
            request_description="Send 10 food recipes",
            expected_format="csv",
            success_criteria="10 recipes",
            referrer_email="raj@gmail.com",
        )

        # Check that the prompt instructs to mention the referrer
        assert "raj@gmail.com" in prompt
        assert "MUST mention" in prompt or "Start by mentioning" in prompt
        # Check that it warns against forwarding back to original
        assert "Do NOT ask" in prompt or "forward" in prompt.lower()


class TestComposeEmailNode:
    """Tests for the compose_email node function."""

    def _create_base_state(
        self,
        poc_email: str = "test@example.com",
        redirected_from: RedirectInfo = None,
        attempt_count: int = 0,
        validation_results: list = None,
        sent_emails: list = None,
    ) -> AgentState:
        """Create a base state for testing."""
        conv = ConversationState(
            poc_email=poc_email,
            status="pending",
            attempt_count=attempt_count,
            redirected_from=redirected_from,
            validation_results=validation_results or [],
            sent_emails=sent_emails or [],
        )

        parsed = ParsedRequest(
            poc_emails=[poc_email],
            request_type="data_request",
            request_description="Get 10 food recipes",
            success_criteria="10 rows of recipes",
            expected_format="csv",
        )

        return {
            "conversations": {poc_email: conv.to_dict()},
            "current_poc": poc_email,
            "parsed_request": parsed.to_dict(),
        }

    @pytest.mark.asyncio
    async def test_compose_initial_email_uses_formatted_system_prompt(self):
        """Test that initial email composition formats system prompt with agent_email."""
        state = self._create_base_state()

        mock_composed = ComposedEmail(
            subject="Request for 10 Food Recipes",
            body="Dear Test,\n\nPlease send recipes.\n\nBest regards,\ninfo-agent"
        )

        with patch("mail_agent.agent.nodes.compose_email.LLMClient") as mock_llm_class:
            mock_llm = MagicMock()
            mock_llm.generate_structured = AsyncMock(return_value=mock_composed)
            mock_llm_class.return_value = mock_llm

            with patch("mail_agent.agent.nodes.compose_email.get_settings") as mock_settings:
                mock_settings.return_value.agent_email = "info-agent@gmail.com"
                mock_settings.return_value.max_attempts = 5

                result = await compose_email(state)

                # Verify system prompt was formatted with agent_email
                call_args = mock_llm.generate_structured.call_args
                system_prompt = call_args.kwargs.get("system_prompt", "")
                assert "info-agent@gmail.com" in system_prompt
                assert "{agent_email}" not in system_prompt

    @pytest.mark.asyncio
    async def test_compose_redirect_email_uses_redirect_prompt(self):
        """Test that redirect email uses compose_email_for_redirect prompt."""
        redirect_info = RedirectInfo(
            original_poc="raj@gmail.com",
            redirect_email="sumit@ubs.com",
            redirect_reason="I am not the right point of contact",
            redirected_at=datetime.now(timezone.utc),
        )

        state = self._create_base_state(
            poc_email="sumit@ubs.com",
            redirected_from=redirect_info,
        )

        mock_composed = ComposedEmail(
            subject="Request for Food Recipes (Referred by raj@gmail.com)",
            body="Dear Sumit,\n\nI was referred to you by raj@gmail.com...\n\nBest regards,\ninfo-agent"
        )

        with patch("mail_agent.agent.nodes.compose_email.LLMClient") as mock_llm_class:
            mock_llm = MagicMock()
            mock_llm.generate_structured = AsyncMock(return_value=mock_composed)
            mock_llm_class.return_value = mock_llm

            with patch("mail_agent.agent.nodes.compose_email.get_settings") as mock_settings:
                mock_settings.return_value.agent_email = "info-agent@gmail.com"
                mock_settings.return_value.max_attempts = 5

                result = await compose_email(state)

                # Verify the prompt contains redirect context
                call_args = mock_llm.generate_structured.call_args
                prompt = call_args.kwargs.get("prompt", call_args.args[0] if call_args.args else "")
                assert "raj@gmail.com" in prompt
                assert "REDIRECT" in prompt

    @pytest.mark.asyncio
    async def test_compose_redirect_email_with_reason(self):
        """Test redirect email includes the redirect reason in prompt."""
        redirect_info = RedirectInfo(
            original_poc="raj@gmail.com",
            redirect_email="sumit@ubs.com",
            redirect_reason="Please connect with sumit instead",
            redirected_at=datetime.now(timezone.utc),
        )

        state = self._create_base_state(
            poc_email="sumit@ubs.com",
            redirected_from=redirect_info,
        )

        mock_composed = ComposedEmail(
            subject="Request for Food Recipes",
            body="Dear Sumit,\n\nI was referred...\n\nBest regards,\ninfo-agent"
        )

        with patch("mail_agent.agent.nodes.compose_email.LLMClient") as mock_llm_class:
            mock_llm = MagicMock()
            mock_llm.generate_structured = AsyncMock(return_value=mock_composed)
            mock_llm_class.return_value = mock_llm

            with patch("mail_agent.agent.nodes.compose_email.get_settings") as mock_settings:
                mock_settings.return_value.agent_email = "info-agent@gmail.com"
                mock_settings.return_value.max_attempts = 5

                result = await compose_email(state)

                # Verify redirect reason is in the prompt
                call_args = mock_llm.generate_structured.call_args
                prompt = call_args.kwargs.get("prompt", call_args.args[0] if call_args.args else "")
                assert "Please connect with sumit instead" in prompt

    @pytest.mark.asyncio
    async def test_compose_redirect_email_without_reason(self):
        """Test redirect email works without a redirect reason."""
        redirect_info = RedirectInfo(
            original_poc="raj@gmail.com",
            redirect_email="sumit@ubs.com",
            redirect_reason=None,  # No reason provided
            redirected_at=datetime.now(timezone.utc),
        )

        state = self._create_base_state(
            poc_email="sumit@ubs.com",
            redirected_from=redirect_info,
        )

        mock_composed = ComposedEmail(
            subject="Request for Food Recipes",
            body="Dear Sumit,\n\nBest regards,\ninfo-agent"
        )

        with patch("mail_agent.agent.nodes.compose_email.LLMClient") as mock_llm_class:
            mock_llm = MagicMock()
            mock_llm.generate_structured = AsyncMock(return_value=mock_composed)
            mock_llm_class.return_value = mock_llm

            with patch("mail_agent.agent.nodes.compose_email.get_settings") as mock_settings:
                mock_settings.return_value.agent_email = "info-agent@gmail.com"
                mock_settings.return_value.max_attempts = 5

                result = await compose_email(state)

                # Should succeed without error
                assert result.get("error") is None
                assert result.get("_composed_subject") == "Request for Food Recipes"

    @pytest.mark.asyncio
    async def test_compose_followup_email_uses_formatted_system_prompt(self):
        """Test that follow-up email composition formats system prompt with agent_email."""
        from uuid import uuid4

        validation_result = ValidationResult(
            attempt=1,
            is_valid=False,
            feedback="Only 5 recipes provided instead of 10",
            missing_items=["5 more recipes"],
        )

        sent_email = SentEmail(
            email_id=uuid4(),
            subject="Request for 10 Food Recipes",
            body="Original email body",
            sent_at=datetime.now(timezone.utc),
        )

        state = self._create_base_state(
            attempt_count=1,
            validation_results=[validation_result],
            sent_emails=[sent_email],
        )

        mock_composed = FollowUpEmail(
            subject="Re: Request for 10 Food Recipes",
            body="Thank you for your response...\n\nBest regards,\ninfo-agent"
        )

        with patch("mail_agent.agent.nodes.compose_email.LLMClient") as mock_llm_class:
            mock_llm = MagicMock()
            mock_llm.generate_structured = AsyncMock(return_value=mock_composed)
            mock_llm_class.return_value = mock_llm

            with patch("mail_agent.agent.nodes.compose_email.get_settings") as mock_settings:
                mock_settings.return_value.agent_email = "info-agent@gmail.com"
                mock_settings.return_value.max_attempts = 5

                result = await compose_email(state)

                # Verify system prompt was formatted with agent_email
                call_args = mock_llm.generate_structured.call_args
                system_prompt = call_args.kwargs.get("system_prompt", "")
                assert "info-agent@gmail.com" in system_prompt
                assert "{agent_email}" not in system_prompt

    @pytest.mark.asyncio
    async def test_compose_email_no_current_poc_error(self):
        """Test error handling when no current POC is set."""
        state: AgentState = {
            "conversations": {},
            "current_poc": None,
            "parsed_request": None,
        }

        result = await compose_email(state)

        assert result.get("error") == "No current POC set"
        assert result.get("current_node") == "error"

    @pytest.mark.asyncio
    async def test_compose_initial_email_stores_result(self):
        """Test that composed email is stored in state for send_email node."""
        state = self._create_base_state()

        mock_composed = ComposedEmail(
            subject="Test Subject",
            body="Test Body\n\nBest regards,\ninfo-agent"
        )

        with patch("mail_agent.agent.nodes.compose_email.LLMClient") as mock_llm_class:
            mock_llm = MagicMock()
            mock_llm.generate_structured = AsyncMock(return_value=mock_composed)
            mock_llm_class.return_value = mock_llm

            with patch("mail_agent.agent.nodes.compose_email.get_settings") as mock_settings:
                mock_settings.return_value.agent_email = "info-agent@gmail.com"
                mock_settings.return_value.max_attempts = 5

                result = await compose_email(state)

                assert result.get("_composed_subject") == "Test Subject"
                assert result.get("_composed_body") == "Test Body\n\nBest regards,\ninfo-agent"


class TestComposeEmailLogging:
    """Tests for compose_email logging behavior."""

    @pytest.mark.asyncio
    async def test_logs_redirect_email_info(self):
        """Test that redirect email composition logs appropriate info."""
        redirect_info = RedirectInfo(
            original_poc="raj@gmail.com",
            redirect_email="sumit@ubs.com",
            redirect_reason="Not the right contact",
            redirected_at=datetime.now(timezone.utc),
        )

        conv = ConversationState(
            poc_email="sumit@ubs.com",
            status="pending",
            redirected_from=redirect_info,
        )

        parsed = ParsedRequest(
            poc_emails=["sumit@ubs.com"],
            request_type="data_request",
            request_description="Get recipes",
            success_criteria="10 recipes",
            expected_format="csv",
        )

        state: AgentState = {
            "conversations": {"sumit@ubs.com": conv.to_dict()},
            "current_poc": "sumit@ubs.com",
            "parsed_request": parsed.to_dict(),
        }

        mock_composed = ComposedEmail(
            subject="Request",
            body="Body\n\nBest regards,\ninfo-agent"
        )

        with patch("mail_agent.agent.nodes.compose_email.LLMClient") as mock_llm_class:
            mock_llm = MagicMock()
            mock_llm.generate_structured = AsyncMock(return_value=mock_composed)
            mock_llm_class.return_value = mock_llm

            with patch("mail_agent.agent.nodes.compose_email.get_settings") as mock_settings:
                mock_settings.return_value.agent_email = "info-agent@gmail.com"
                mock_settings.return_value.max_attempts = 5

                with patch("mail_agent.agent.nodes.compose_email.logger") as mock_logger:
                    result = await compose_email(state)

                    # Check that redirect logging happened
                    log_calls = [str(call) for call in mock_logger.info.call_args_list]
                    redirect_log_found = any(
                        "redirect" in str(call).lower() for call in log_calls
                    )
                    assert redirect_log_found, f"Expected redirect log, got: {log_calls}"
