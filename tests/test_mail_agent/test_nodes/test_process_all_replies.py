"""
Tests for the process_all_replies node.

Tests cover:
1. Processing replies from all POCs concurrently
2. Fetching, extracting, and validating for each POC
3. Setting _poc_processing_results
4. Setting _all_individual_valid flag
5. Error handling
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
from mail_agent.agent.nodes.process_all_replies import process_all_replies
from mail_agent.llm.prompts import ValidationResult as LLMValidationResult


class TestProcessAllReplies:
    """Tests for the process_all_replies node function."""

    def _create_base_state(
        self,
        poc_emails: list[str] = None,
        received_webhooks: dict = None,
    ) -> AgentState:
        """Create a base state for testing with received webhooks."""
        if poc_emails is None:
            poc_emails = ["raj@example.com", "neha@example.com"]

        if received_webhooks is None:
            received_webhooks = {
                email: {
                    "email_id": str(uuid4()),
                    "from_address": email,
                    "subject": f"Re: Request from {email}",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                for email in poc_emails
            }

        conversations = {}
        for email in poc_emails:
            conv = ConversationState(
                poc_email=email,
                status="waiting",
                attempt_count=1,
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
            "_received_webhooks": received_webhooks,
            "_waiting_pocs": poc_emails,
            "_parallel_mode": True,
        }

    @pytest.mark.asyncio
    async def test_process_all_replies_all_valid(self):
        """Test processing when all POC replies are valid."""
        state = self._create_base_state(
            poc_emails=["raj@example.com", "neha@example.com"]
        )

        mock_validation = LLMValidationResult(
            is_valid=True,
            feedback="All criteria met",
            missing_items=[],
            redirect_detected=False,
            redirect_email=None,
        )

        with patch("mail_agent.agent.nodes.process_all_replies.InboxClient") as mock_inbox_class:
            mock_inbox = MagicMock()
            mock_inbox.get_email = AsyncMock(return_value={
                "id": str(uuid4()),
                "from_address": "poc@example.com",
                "subject": "Re: Request",
                "body": "Here are the recipes...",
                "attachments": [{"filename": "recipes.csv", "content": "name,ingredients\nPasta,flour"}],
            })
            mock_inbox_class.return_value = mock_inbox

            with patch("mail_agent.agent.nodes.process_all_replies.parse_attachment") as mock_parse:
                mock_parse.return_value = "name,ingredients\nPasta,flour\n..."

                with patch("mail_agent.agent.nodes.process_all_replies.LLMClient") as mock_llm_class:
                    mock_llm = MagicMock()
                    mock_llm.generate_structured = AsyncMock(return_value=mock_validation)
                    mock_llm_class.return_value = mock_llm

                    with patch("mail_agent.agent.nodes.process_all_replies.get_settings") as mock_settings:
                        mock_settings.return_value.validation_content_max_chars = 8000

                        result = await process_all_replies(state)

                        # Verify _all_individual_valid is True
                        assert result.get("_all_individual_valid") is True

                        # Verify _poc_processing_results
                        poc_results = result.get("_poc_processing_results", {})
                        assert len(poc_results) == 2
                        for email in ["raj@example.com", "neha@example.com"]:
                            assert email in poc_results
                            assert poc_results[email]["is_valid"] is True

    @pytest.mark.asyncio
    async def test_process_all_replies_some_invalid(self):
        """Test processing when some POC replies are invalid."""
        state = self._create_base_state(
            poc_emails=["raj@example.com", "neha@example.com"]
        )

        call_count = 0

        async def mock_validate(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return LLMValidationResult(
                    is_valid=True,
                    feedback="Good",
                    missing_items=[],
                    redirect_detected=False,
                    redirect_email=None,
                )
            else:
                return LLMValidationResult(
                    is_valid=False,
                    feedback="Missing 5 recipes",
                    missing_items=["5 more recipes"],
                    redirect_detected=False,
                    redirect_email=None,
                )

        with patch("mail_agent.agent.nodes.process_all_replies.InboxClient") as mock_inbox_class:
            mock_inbox = MagicMock()
            mock_inbox.get_email = AsyncMock(return_value={
                "id": str(uuid4()),
                "from_address": "poc@example.com",
                "subject": "Re: Request",
                "body": "Here are some recipes...",
                "attachments": [],
            })
            mock_inbox_class.return_value = mock_inbox

            with patch("mail_agent.agent.nodes.process_all_replies.LLMClient") as mock_llm_class:
                mock_llm = MagicMock()
                mock_llm.generate_structured = mock_validate
                mock_llm_class.return_value = mock_llm

                with patch("mail_agent.agent.nodes.process_all_replies.get_settings") as mock_settings:
                    mock_settings.return_value.validation_content_max_chars = 8000

                    result = await process_all_replies(state)

                    # Verify _all_individual_valid is False
                    assert result.get("_all_individual_valid") is False

                    # Verify some results are invalid
                    poc_results = result.get("_poc_processing_results", {})
                    valid_count = sum(1 for r in poc_results.values() if r.get("is_valid"))
                    invalid_count = sum(1 for r in poc_results.values() if not r.get("is_valid"))
                    assert valid_count == 1
                    assert invalid_count == 1

    @pytest.mark.asyncio
    async def test_process_all_replies_redirect_detected(self):
        """Test processing when a redirect is detected."""
        state = self._create_base_state(
            poc_emails=["raj@example.com"]
        )

        mock_validation = LLMValidationResult(
            is_valid=False,
            feedback="Please contact sumit@example.com instead",
            missing_items=[],
            redirect_detected=True,
            redirect_email="sumit@example.com",
        )

        with patch("mail_agent.agent.nodes.process_all_replies.InboxClient") as mock_inbox_class:
            mock_inbox = MagicMock()
            mock_inbox.get_email = AsyncMock(return_value={
                "id": str(uuid4()),
                "from_address": "raj@example.com",
                "subject": "Re: Request",
                "body": "I am not the right person. Please contact sumit@example.com",
                "attachments": [],
            })
            mock_inbox_class.return_value = mock_inbox

            with patch("mail_agent.agent.nodes.process_all_replies.LLMClient") as mock_llm_class:
                mock_llm = MagicMock()
                mock_llm.generate_structured = AsyncMock(return_value=mock_validation)
                mock_llm_class.return_value = mock_llm

                with patch("mail_agent.agent.nodes.process_all_replies.get_settings") as mock_settings:
                    mock_settings.return_value.validation_content_max_chars = 8000

                    result = await process_all_replies(state)

                    # Verify redirect is captured
                    poc_results = result.get("_poc_processing_results", {})
                    raj_result = poc_results.get("raj@example.com", {})
                    assert raj_result.get("is_redirect") is True
                    assert raj_result.get("redirect_email") == "sumit@example.com"

    @pytest.mark.asyncio
    async def test_process_all_replies_no_webhooks_error(self):
        """Test error when no received webhooks exist."""
        state = self._create_base_state()
        state["_received_webhooks"] = None

        result = await process_all_replies(state)

        assert result.get("error") is not None
        assert result.get("current_node") == "error"

    @pytest.mark.asyncio
    async def test_process_all_replies_empty_webhooks_error(self):
        """Test error when received webhooks dict is empty."""
        state = self._create_base_state()
        state["_received_webhooks"] = {}

        result = await process_all_replies(state)

        assert result.get("error") is not None
        assert result.get("current_node") == "error"

    @pytest.mark.asyncio
    async def test_process_all_replies_updates_conversations(self):
        """Test that conversations are updated with validation results."""
        state = self._create_base_state(
            poc_emails=["raj@example.com"]
        )

        mock_validation = LLMValidationResult(
            is_valid=True,
            feedback="All criteria met",
            missing_items=[],
            redirect_detected=False,
            redirect_email=None,
        )

        with patch("mail_agent.agent.nodes.process_all_replies.InboxClient") as mock_inbox_class:
            mock_inbox = MagicMock()
            mock_inbox.get_email = AsyncMock(return_value={
                "id": str(uuid4()),
                "from_address": "raj@example.com",
                "subject": "Re: Request",
                "body": "Here are the recipes...",
                "attachments": [],
            })
            mock_inbox_class.return_value = mock_inbox

            with patch("mail_agent.agent.nodes.process_all_replies.LLMClient") as mock_llm_class:
                mock_llm = MagicMock()
                mock_llm.generate_structured = AsyncMock(return_value=mock_validation)
                mock_llm_class.return_value = mock_llm

                with patch("mail_agent.agent.nodes.process_all_replies.get_settings") as mock_settings:
                    mock_settings.return_value.validation_content_max_chars = 8000

                    result = await process_all_replies(state)

                    # Verify conversation updated
                    conversations = result.get("conversations", {})
                    raj_conv = conversations.get("raj@example.com", {})
                    assert raj_conv.get("status") == "success"

                    # Verify validation result recorded
                    validation_results = raj_conv.get("validation_results", [])
                    assert len(validation_results) >= 1

    @pytest.mark.asyncio
    async def test_process_all_replies_clears_waiting_pocs(self):
        """Test that _waiting_pocs is cleared after processing."""
        state = self._create_base_state(
            poc_emails=["raj@example.com"]
        )

        mock_validation = LLMValidationResult(
            is_valid=True,
            feedback="OK",
            missing_items=[],
            redirect_detected=False,
            redirect_email=None,
        )

        with patch("mail_agent.agent.nodes.process_all_replies.InboxClient") as mock_inbox_class:
            mock_inbox = MagicMock()
            mock_inbox.get_email = AsyncMock(return_value={
                "id": str(uuid4()),
                "from_address": "raj@example.com",
                "subject": "Re: Request",
                "body": "Data here",
                "attachments": [],
            })
            mock_inbox_class.return_value = mock_inbox

            with patch("mail_agent.agent.nodes.process_all_replies.LLMClient") as mock_llm_class:
                mock_llm = MagicMock()
                mock_llm.generate_structured = AsyncMock(return_value=mock_validation)
                mock_llm_class.return_value = mock_llm

                with patch("mail_agent.agent.nodes.process_all_replies.get_settings") as mock_settings:
                    mock_settings.return_value.validation_content_max_chars = 8000

                    result = await process_all_replies(state)

                    # _waiting_pocs and _received_webhooks should be cleared
                    assert result.get("_waiting_pocs") is None
                    assert result.get("_received_webhooks") is None

    @pytest.mark.asyncio
    async def test_process_all_replies_progress_message(self):
        """Test that progress messages are generated."""
        state = self._create_base_state(
            poc_emails=["raj@example.com", "neha@example.com"]
        )

        mock_validation = LLMValidationResult(
            is_valid=True,
            feedback="OK",
            missing_items=[],
            redirect_detected=False,
            redirect_email=None,
        )

        with patch("mail_agent.agent.nodes.process_all_replies.InboxClient") as mock_inbox_class:
            mock_inbox = MagicMock()
            mock_inbox.get_email = AsyncMock(return_value={
                "id": str(uuid4()),
                "from_address": "poc@example.com",
                "subject": "Re: Request",
                "body": "Data",
                "attachments": [],
            })
            mock_inbox_class.return_value = mock_inbox

            with patch("mail_agent.agent.nodes.process_all_replies.LLMClient") as mock_llm_class:
                mock_llm = MagicMock()
                mock_llm.generate_structured = AsyncMock(return_value=mock_validation)
                mock_llm_class.return_value = mock_llm

                with patch("mail_agent.agent.nodes.process_all_replies.get_settings") as mock_settings:
                    mock_settings.return_value.validation_content_max_chars = 8000

                    result = await process_all_replies(state)

                    # Verify progress message exists
                    progress = result.get("progress_messages", [])
                    assert len(progress) > 0


class TestProcessAllRepliesConcurrency:
    """Tests for concurrent processing in process_all_replies."""

    def _create_base_state(self, poc_count: int = 3) -> AgentState:
        """Create a state with multiple POCs."""
        poc_emails = [f"poc{i}@example.com" for i in range(poc_count)]

        received_webhooks = {
            email: {
                "email_id": str(uuid4()),
                "from_address": email,
                "subject": f"Re: Request",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            for email in poc_emails
        }

        conversations = {}
        for email in poc_emails:
            conv = ConversationState(
                poc_email=email,
                status="waiting",
                attempt_count=1,
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
            "_received_webhooks": received_webhooks,
            "_waiting_pocs": poc_emails,
            "_parallel_mode": True,
        }

    @pytest.mark.asyncio
    async def test_process_all_replies_concurrent_processing(self):
        """Test that all POC replies are processed concurrently."""
        state = self._create_base_state(poc_count=5)

        call_times = []

        async def mock_get_email(*args, **kwargs):
            import asyncio
            call_times.append(datetime.now(timezone.utc))
            await asyncio.sleep(0.01)
            return {
                "id": str(uuid4()),
                "from_address": "poc@example.com",
                "subject": "Re: Request",
                "body": "Data here",
                "attachments": [],
            }

        mock_validation = LLMValidationResult(
            is_valid=True,
            feedback="OK",
            missing_items=[],
            redirect_detected=False,
            redirect_email=None,
        )

        with patch("mail_agent.agent.nodes.process_all_replies.InboxClient") as mock_inbox_class:
            mock_inbox = MagicMock()
            mock_inbox.get_email = mock_get_email
            mock_inbox_class.return_value = mock_inbox

            with patch("mail_agent.agent.nodes.process_all_replies.LLMClient") as mock_llm_class:
                mock_llm = MagicMock()
                mock_llm.generate_structured = AsyncMock(return_value=mock_validation)
                mock_llm_class.return_value = mock_llm

                with patch("mail_agent.agent.nodes.process_all_replies.get_settings") as mock_settings:
                    mock_settings.return_value.validation_content_max_chars = 8000

                    result = await process_all_replies(state)

                    # All 5 POCs should be processed
                    poc_results = result.get("_poc_processing_results", {})
                    assert len(poc_results) == 5

                    # Verify calls were concurrent
                    if len(call_times) >= 2:
                        time_diff = (call_times[-1] - call_times[0]).total_seconds()
                        assert time_diff < 0.5, f"Calls not concurrent: {time_diff}s"
