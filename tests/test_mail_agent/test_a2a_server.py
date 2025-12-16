"""
Unit tests for A2A server application creation.

Tests cover:
- WebhookServer-TaskManager connection after create_a2a_application
- Webhook routing through TaskManager (not queue)
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from mail_agent.a2a.server import create_a2a_application
from mail_agent.config import Settings
from mail_agent.persistence import DatabaseManager


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_settings() -> Settings:
    """Create mock settings for testing."""
    return Settings(
        mock_smtp_api_url="http://localhost:8025",
        mock_smtp_host="localhost",
        mock_smtp_port=1025,
        agent_email="test-agent@gmail.com",
        webhook_host="localhost",
        webhook_port=9000,
        webhook_path="/webhook/email-received",
        gemini_api_key="test-api-key",
        gemini_model="gemini-2.5-flash",
        llm_temperature=0.0,
        llm_max_tokens=4096,
        max_attempts=5,
        sqlite_db_path=":memory:",
        http_timeout_seconds=30.0,
        log_level="DEBUG",
        a2a_host="localhost",
        a2a_port=8080,
        task_suspend_timeout_seconds=3600,
        expired_task_cleanup_interval_seconds=60,
    )


@pytest.fixture
def mock_db_manager() -> MagicMock:
    """Create a mock DatabaseManager."""
    db = MagicMock(spec=DatabaseManager)
    db.execute = AsyncMock()
    db.fetchone = AsyncMock(return_value=None)
    db.fetchall = AsyncMock(return_value=[])
    return db


@pytest.fixture
def mock_checkpointer() -> MagicMock:
    """Create a mock LangGraph checkpointer."""
    return MagicMock()


# ============================================================================
# Tests for WebhookServer-TaskManager Connection
# ============================================================================


class TestWebhookServerTaskManagerConnection:
    """Test that WebhookServer is connected to TaskManager after creation."""

    @pytest.mark.asyncio
    async def test_webhook_server_has_task_manager_after_creation(
        self,
        mock_settings: Settings,
        mock_db_manager: MagicMock,
        mock_checkpointer: MagicMock,
    ) -> None:
        """
        Test that create_a2a_application connects WebhookServer to TaskManager.

        This is the bug fix test - previously WebhookServer was created without
        TaskManager, causing webhooks to be queued instead of routed.
        """
        with patch(
            "mail_agent.a2a.server.compile_mail_agent_graph"
        ) as mock_compile:
            # Mock the graph compilation
            mock_graph = MagicMock()
            mock_compile.return_value = mock_graph

            # Create application
            resources = await create_a2a_application(
                settings=mock_settings,
                db_manager=mock_db_manager,
                checkpointer=mock_checkpointer,
            )

            # Verify WebhookServer has TaskManager set
            assert resources.webhook_server is not None
            assert resources.webhook_server.task_manager is not None
            assert resources.webhook_server.task_manager is resources.task_manager

    @pytest.mark.asyncio
    async def test_webhook_server_can_route_to_task_manager(
        self,
        mock_settings: Settings,
        mock_db_manager: MagicMock,
        mock_checkpointer: MagicMock,
    ) -> None:
        """
        Test that webhook routing goes through TaskManager when task exists.
        """
        with patch(
            "mail_agent.a2a.server.compile_mail_agent_graph"
        ) as mock_compile:
            # Mock the graph compilation
            mock_graph = MagicMock()
            mock_compile.return_value = mock_graph

            # Create application
            resources = await create_a2a_application(
                settings=mock_settings,
                db_manager=mock_db_manager,
                checkpointer=mock_checkpointer,
            )

            # Verify the _task_manager attribute is set (internal check)
            assert resources.webhook_server._task_manager is not None


# ============================================================================
# Tests for Webhook Routing Logic
# ============================================================================


class TestWebhookRouting:
    """Test webhook routing behavior."""

    @pytest.mark.asyncio
    async def test_webhook_routes_to_task_manager_when_task_exists(
        self,
        mock_settings: Settings,
    ) -> None:
        """
        Test that webhooks are routed to TaskManager when a suspended task exists.
        """
        from mail_agent.webhook.server import WebhookServer
        from mail_agent.task_manager.models import WebhookPayload

        # Create webhook server
        webhook_server = WebhookServer(settings=mock_settings)

        # Create mock TaskManager
        mock_task_manager = MagicMock()
        mock_task_manager.handle_webhook = AsyncMock(return_value=True)

        # Connect TaskManager to WebhookServer
        webhook_server.set_task_manager(mock_task_manager)

        # Create a webhook payload
        from mail_agent.webhook.server import WebhookPayload as WSPayload
        payload = WSPayload(
            event="email.received",
            email_id="test-email-id",
            from_address="poc@example.com",
            to=["agent@example.com"],
            subject="Re: Request",
            has_attachments=True,
            attachment_count=1,
            received_at=datetime.now(timezone.utc).isoformat(),
            body_preview="Here is the data.",
        )

        # Route the payload
        handled = await webhook_server._route_to_task_manager(payload)

        # Verify TaskManager was called
        assert handled is True
        mock_task_manager.handle_webhook.assert_called_once()

    @pytest.mark.asyncio
    async def test_webhook_falls_back_to_queue_when_no_task(
        self,
        mock_settings: Settings,
    ) -> None:
        """
        Test that webhooks fall back to queue when no matching task exists.
        """
        from mail_agent.webhook.server import WebhookServer

        # Create webhook server
        webhook_server = WebhookServer(settings=mock_settings)

        # Create mock TaskManager that returns False (no matching task)
        mock_task_manager = MagicMock()
        mock_task_manager.handle_webhook = AsyncMock(return_value=False)

        # Connect TaskManager to WebhookServer
        webhook_server.set_task_manager(mock_task_manager)

        # Create a webhook payload
        from mail_agent.webhook.server import WebhookPayload as WSPayload
        payload = WSPayload(
            event="email.received",
            email_id="test-email-id",
            from_address="unknown@example.com",
            to=["agent@example.com"],
            subject="Random email",
            has_attachments=False,
            attachment_count=0,
            received_at=datetime.now(timezone.utc).isoformat(),
            body_preview="Hello",
        )

        # Route the payload
        handled = await webhook_server._route_to_task_manager(payload)

        # Verify TaskManager was called but returned False
        assert handled is False
        mock_task_manager.handle_webhook.assert_called_once()

    @pytest.mark.asyncio
    async def test_webhook_uses_queue_when_no_task_manager(
        self,
        mock_settings: Settings,
    ) -> None:
        """
        Test that webhooks go to queue when TaskManager is not set (CLI mode).
        """
        from mail_agent.webhook.server import WebhookServer

        # Create webhook server without TaskManager
        webhook_server = WebhookServer(settings=mock_settings)

        # Verify TaskManager is not set
        assert webhook_server.task_manager is None

        # Create a webhook payload
        from mail_agent.webhook.server import WebhookPayload as WSPayload
        payload = WSPayload(
            event="email.received",
            email_id="test-email-id",
            from_address="poc@example.com",
            to=["agent@example.com"],
            subject="Re: Request",
            has_attachments=True,
            attachment_count=1,
            received_at=datetime.now(timezone.utc).isoformat(),
            body_preview="Here is the data.",
        )

        # Route the payload - should return False (not handled by TaskManager)
        handled = await webhook_server._route_to_task_manager(payload)

        assert handled is False
