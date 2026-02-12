"""
Tests for UI service clients.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime

import httpx

from ui.config import Settings
from ui.services.a2a_client import (
    A2AClientService,
    A2AConnectionError,
    A2ATaskError,
    TaskInfo,
    AgentInfo,
)
from ui.services.smtp_client import (
    SMTPClientService,
    SMTPConnectionError,
    InboxNotFoundError,
    EmailNotFoundError,
    EmailSendError,
    InboxSummary,
    EmailSummary,
    Email,
    Attachment,
)


@pytest.fixture
def settings() -> Settings:
    """Create test settings."""
    return Settings(
        a2a_server_url="http://localhost:8000",
        mock_smtp_api_url="http://localhost:8025",
        http_timeout_seconds=5.0,
    )


class TestA2AClientService:
    """Tests for A2A client service."""

    @pytest.mark.asyncio
    async def test_get_agent_info_success(self, settings: Settings) -> None:
        """Test successful agent info fetch."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "name": "Mail Agent",
            "version": "1.0.0",
            "description": "Test agent",
            "url": "http://localhost:8000",
            "skills": [{"id": "email_communication"}],
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.aclose = AsyncMock()
            mock_client_class.return_value = mock_client

            client = A2AClientService(settings)
            result = await client.get_agent_info()

            assert isinstance(result, AgentInfo)
            assert result.name == "Mail Agent"
            assert result.version == "1.0.0"

            await client.close()

    @pytest.mark.asyncio
    async def test_get_agent_info_connection_error(self, settings: Settings) -> None:
        """Test agent info fetch with connection error."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
            mock_client.aclose = AsyncMock()
            mock_client_class.return_value = mock_client

            client = A2AClientService(settings)

            with pytest.raises(A2AConnectionError):
                await client.get_agent_info()

            await client.close()

    @pytest.mark.asyncio
    async def test_send_task_success(self, settings: Settings) -> None:
        """Test successful task submission."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "id": "test-task-123",
                "state": "submitted",
            },
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.aclose = AsyncMock()
            mock_client_class.return_value = mock_client

            client = A2AClientService(settings)
            result = await client.send_task("Send mail to test@example.com")

            assert isinstance(result, TaskInfo)
            assert result.task_id == "test-task-123"
            assert result.state == "submitted"

            await client.close()

    @pytest.mark.asyncio
    async def test_check_health_success(self, settings: Settings) -> None:
        """Test health check success."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.aclose = AsyncMock()
            mock_client_class.return_value = mock_client

            client = A2AClientService(settings)
            result = await client.check_health()

            assert result is True

            await client.close()

    @pytest.mark.asyncio
    async def test_check_health_failure(self, settings: Settings) -> None:
        """Test health check failure."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=Exception("Connection failed"))
            mock_client.aclose = AsyncMock()
            mock_client_class.return_value = mock_client

            client = A2AClientService(settings)
            result = await client.check_health()

            assert result is False

            await client.close()

    @pytest.mark.asyncio
    async def test_send_task_message_response_with_task_id(self, settings: Settings) -> None:
        """Test parsing Message response when task is suspended.

        When agent suspends (wait_for_reply interrupt), the response contains a Message
        object with task_id embedded in the text.
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "kind": "message",
                "messageId": "msg-abc-123",
                "role": "agent",
                "parts": [
                    {
                        "type": "text",
                        "text": "[suspended] Waiting for reply from raj@gmail.com. Poll GET /tasks/385ddbda-b7af-4663-8461-f1224bb96e4e for result.",
                    }
                ],
            },
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.aclose = AsyncMock()
            mock_client_class.return_value = mock_client

            client = A2AClientService(settings)
            result = await client.send_task("Send mail to raj@gmail.com asking for recipes")

            assert isinstance(result, TaskInfo)
            assert result.task_id == "385ddbda-b7af-4663-8461-f1224bb96e4e"
            assert result.state == "suspended"

            await client.close()

    @pytest.mark.asyncio
    async def test_send_task_message_response_with_non_hex_task_id(self, settings: Settings) -> None:
        """Test parsing Message response with non-hex characters in task_id.

        Task IDs may contain letters beyond hex range (g-z), ensuring regex
        pattern [a-zA-Z0-9-] correctly captures the full ID.
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "kind": "message",
                "messageId": "msg-xyz-789",
                "role": "agent",
                "parts": [
                    {
                        "text": "[suspended] Waiting for reply from test@example.com. Poll GET /tasks/abc123-ghijkl-xyz789 for result.",
                    }
                ],
            },
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.aclose = AsyncMock()
            mock_client_class.return_value = mock_client

            client = A2AClientService(settings)
            result = await client.send_task("Send mail to test@example.com")

            assert isinstance(result, TaskInfo)
            # Task ID contains g, h, i, j, k, l, x, y, z - all outside hex range
            assert result.task_id == "abc123-ghijkl-xyz789"
            assert result.state == "suspended"

            await client.close()

    @pytest.mark.asyncio
    async def test_send_task_message_response_without_task_id(self, settings: Settings) -> None:
        """Test parsing Message response without task_id in text.

        When the message text doesn't contain a task_id, we should get empty string.
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "kind": "message",
                "messageId": "msg-abc-123",
                "role": "agent",
                "parts": [
                    {
                        "type": "text",
                        "text": "[working] Processing request...",
                    }
                ],
            },
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.aclose = AsyncMock()
            mock_client_class.return_value = mock_client

            client = A2AClientService(settings)
            result = await client.send_task("Send mail to test@example.com")

            assert isinstance(result, TaskInfo)
            assert result.task_id == ""
            assert result.state == "working"

            await client.close()

    @pytest.mark.asyncio
    async def test_get_task_status_with_state_field(self, settings: Settings) -> None:
        """Test get_task_status parsing with 'state' field (not 'status').

        The API now returns 'state' field instead of 'status'.
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "task_id": "test-task-123",
            "state": "suspended",
            "message": "Waiting for reply from raj@gmail.com",
            "poc_email": "raj@gmail.com",
            "created_at": "2025-12-16T08:44:31+00:00",
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.aclose = AsyncMock()
            mock_client_class.return_value = mock_client

            client = A2AClientService(settings)
            result = await client.get_task_status("test-task-123")

            assert isinstance(result, TaskInfo)
            assert result.task_id == "test-task-123"
            assert result.state == "suspended"
            assert result.poc_email == "raj@gmail.com"

            await client.close()

    @pytest.mark.asyncio
    async def test_get_task_status_fallback_to_unknown(self, settings: Settings) -> None:
        """Test get_task_status returns 'unknown' when state field is missing."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "task_id": "test-task-123",
            "message": "Some message",
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.aclose = AsyncMock()
            mock_client_class.return_value = mock_client

            client = A2AClientService(settings)
            result = await client.get_task_status("test-task-123")

            assert result.state == "unknown"

            await client.close()

    def test_extract_text_from_part_direct_dict(self, settings: Settings) -> None:
        """Test _extract_text_from_part with direct dict containing text."""
        client = A2AClientService(settings)

        # Direct dict with text key
        part = {"text": "Hello world"}
        assert client._extract_text_from_part(part) == "Hello world"

    def test_extract_text_from_part_nested_root_dict(self, settings: Settings) -> None:
        """Test _extract_text_from_part with nested root structure (dict)."""
        client = A2AClientService(settings)

        # Nested root structure (common in A2A SDK responses)
        part = {"root": {"text": "[suspended] Waiting for reply. Poll GET /tasks/abc-123"}}
        assert client._extract_text_from_part(part) == "[suspended] Waiting for reply. Poll GET /tasks/abc-123"

    def test_extract_text_from_part_empty_cases(self, settings: Settings) -> None:
        """Test _extract_text_from_part with various empty/None cases."""
        client = A2AClientService(settings)

        # None
        assert client._extract_text_from_part(None) == ""

        # Empty dict
        assert client._extract_text_from_part({}) == ""

        # Dict with empty text
        assert client._extract_text_from_part({"text": ""}) == ""

        # Dict with empty root
        assert client._extract_text_from_part({"root": {}}) == ""

    def test_extract_text_from_part_object_with_text_attr(self, settings: Settings) -> None:
        """Test _extract_text_from_part with object having .text attribute."""
        client = A2AClientService(settings)

        # Mock object with .text attribute (like TextPart)
        mock_part = MagicMock()
        mock_part.text = "Text from attribute"
        assert client._extract_text_from_part(mock_part) == "Text from attribute"

    def test_extract_text_from_part_object_with_root_text(self, settings: Settings) -> None:
        """Test _extract_text_from_part with object having .root.text attribute."""
        client = A2AClientService(settings)

        # Mock object with .root.text attribute (like Part wrapper)
        mock_root = MagicMock()
        mock_root.text = "Text from root"
        mock_part = MagicMock()
        mock_part.text = None  # Direct text is None
        mock_part.root = mock_root
        assert client._extract_text_from_part(mock_part) == "Text from root"

    @pytest.mark.asyncio
    async def test_send_task_message_response_with_nested_root(self, settings: Settings) -> None:
        """Test parsing Message response with nested root structure.

        The A2A SDK may return parts with nested 'root' structure containing text.
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "kind": "message",
                "messageId": "msg-xyz-456",
                "role": "agent",
                "parts": [
                    {
                        "root": {
                            "text": "[suspended] Waiting for reply from test@example.com. Poll GET /tasks/ABCD1234-EF56-7890-AB12-CDEF34567890 for result."
                        }
                    }
                ],
            },
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.aclose = AsyncMock()
            mock_client_class.return_value = mock_client

            client = A2AClientService(settings)
            result = await client.send_task("Send mail to test@example.com")

            assert isinstance(result, TaskInfo)
            # UUID with uppercase hex letters (valid hex: 0-9, a-f, A-F)
            assert result.task_id == "ABCD1234-EF56-7890-AB12-CDEF34567890"
            assert result.state == "suspended"

            await client.close()


class TestSMTPClientService:
    """Tests for SMTP client service."""

    @pytest.mark.asyncio
    async def test_list_inboxes_success(self, settings: Settings) -> None:
        """Test successful inbox listing."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        # API returns List[InboxSummary] directly, not wrapped in a dict
        mock_response.json.return_value = [
            {
                "email_address": "test@example.com",
                "email_count": 5,
                "last_email_at": "2024-01-01T12:00:00",
            },
        ]
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.aclose = AsyncMock()
            mock_client_class.return_value = mock_client

            client = SMTPClientService(settings)
            result = await client.list_inboxes()

            assert len(result) == 1
            assert isinstance(result[0], InboxSummary)
            assert result[0].email_address == "test@example.com"
            assert result[0].email_count == 5

            await client.close()

    @pytest.mark.asyncio
    async def test_get_inbox_success(self, settings: Settings) -> None:
        """Test successful inbox retrieval."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        # API returns List[EmailSummary] directly, not wrapped in a dict
        mock_response.json.return_value = [
            {
                "id": "email-1",
                "from_address": "sender@example.com",
                "subject": "Test Subject",
                "received_at": "2024-01-01T12:00:00",
                "has_attachments": False,
            },
        ]
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.aclose = AsyncMock()
            mock_client_class.return_value = mock_client

            client = SMTPClientService(settings)
            result = await client.get_inbox("test@example.com")

            assert len(result) == 1
            assert isinstance(result[0], EmailSummary)
            assert result[0].id == "email-1"
            assert result[0].subject == "Test Subject"

            await client.close()

    @pytest.mark.asyncio
    async def test_get_inbox_not_found(self, settings: Settings) -> None:
        """Test inbox not found error."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "Not Found",
                request=MagicMock(),
                response=mock_response,
            )
        )

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.aclose = AsyncMock()
            mock_client_class.return_value = mock_client

            client = SMTPClientService(settings)

            with pytest.raises(InboxNotFoundError):
                await client.get_inbox("nonexistent@example.com")

            await client.close()

    @pytest.mark.asyncio
    async def test_send_email_success(self, settings: Settings) -> None:
        """Test successful email sending."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"email_id": "new-email-123"}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.aclose = AsyncMock()
            mock_client_class.return_value = mock_client

            client = SMTPClientService(settings)
            result = await client.send_email(
                from_address="sender@example.com",
                to_addresses=["recipient@example.com"],
                subject="Test Subject",
                body="Test body",
            )

            assert result == "new-email-123"

            await client.close()

    @pytest.mark.asyncio
    async def test_send_email_with_attachment(self, settings: Settings) -> None:
        """Test email sending with attachment."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"email_id": "new-email-123"}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.aclose = AsyncMock()
            mock_client_class.return_value = mock_client

            client = SMTPClientService(settings)
            result = await client.send_email(
                from_address="sender@example.com",
                to_addresses=["recipient@example.com"],
                subject="Test Subject",
                body="Test body",
                attachments=[("test.csv", "text/csv", b"test,data\n1,2")],
            )

            assert result == "new-email-123"
            # Verify POST was called with attachments
            call_args = mock_client.post.call_args
            assert "attachments" in call_args.kwargs["json"]

            await client.close()

    @pytest.mark.asyncio
    async def test_clear_all_inboxes_success(self, settings: Settings) -> None:
        """Test successful clear-all request."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "message": "Cleared all inboxes",
            "deleted_count": 8,
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.delete = AsyncMock(return_value=mock_response)
            mock_client.aclose = AsyncMock()
            mock_client_class.return_value = mock_client

            client = SMTPClientService(settings)
            deleted_count = await client.clear_all_inboxes()

            assert deleted_count == 8
            mock_client.delete.assert_awaited_once_with("/api/clear")

            await client.close()

    @pytest.mark.asyncio
    async def test_clear_all_inboxes_http_error(self, settings: Settings) -> None:
        """Test clear-all HTTP status failure."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "Server Error",
                request=MagicMock(),
                response=mock_response,
            )
        )

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.delete = AsyncMock(return_value=mock_response)
            mock_client.aclose = AsyncMock()
            mock_client_class.return_value = mock_client

            client = SMTPClientService(settings)

            with pytest.raises(SMTPConnectionError, match="HTTP error"):
                await client.clear_all_inboxes()

            await client.close()

    @pytest.mark.asyncio
    async def test_clear_all_inboxes_missing_deleted_count(self, settings: Settings) -> None:
        """Test clear-all response validation when deleted_count is missing."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"message": "Cleared all inboxes"}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.delete = AsyncMock(return_value=mock_response)
            mock_client.aclose = AsyncMock()
            mock_client_class.return_value = mock_client

            client = SMTPClientService(settings)

            with pytest.raises(SMTPConnectionError, match="deleted_count"):
                await client.clear_all_inboxes()

            await client.close()

    @pytest.mark.asyncio
    async def test_check_health_success(self, settings: Settings) -> None:
        """Test health check success."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.aclose = AsyncMock()
            mock_client_class.return_value = mock_client

            client = SMTPClientService(settings)
            result = await client.check_health()

            assert result is True

            await client.close()
