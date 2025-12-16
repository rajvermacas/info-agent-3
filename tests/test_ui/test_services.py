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
