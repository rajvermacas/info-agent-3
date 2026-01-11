"""Tests for send API endpoints including webhook integration."""

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, status
from fastapi.testclient import TestClient

from mock_smtp.api.router import create_api_router
from mock_smtp.store.inbox_store import InboxStore
from mock_smtp.store.models import Email
from mock_smtp.webhooks.dispatcher import WebhookDispatcher
from mock_smtp.webhooks.registry import WebhookRegistry

logger = logging.getLogger(__name__)


@pytest.fixture
def mock_webhook_dispatcher():
    """Create a mock WebhookDispatcher for testing."""
    dispatcher = MagicMock(spec=WebhookDispatcher)
    dispatcher.dispatch_batch = AsyncMock(return_value=[
        {"status": "sent", "url": "http://example.com/webhook", "status_code": 200}
    ])
    return dispatcher


@pytest.fixture
def api_client_with_mock_dispatcher(inbox_store, webhook_registry, mock_webhook_dispatcher):
    """Create a TestClient with a mock webhook dispatcher."""
    app = FastAPI()

    app.state.inbox_store = inbox_store
    app.state.webhook_registry = webhook_registry
    app.state.webhook_dispatcher = mock_webhook_dispatcher

    api_router = create_api_router(
        inbox_store=inbox_store,
        webhook_registry=webhook_registry,
        webhook_dispatcher=mock_webhook_dispatcher
    )
    app.include_router(api_router)

    return TestClient(app)


class TestSendAPI:
    """Tests for send API endpoints."""

    def test_send_email_basic(self, api_client):
        """Test sending a basic email via REST API."""
        response = api_client.post(
            "/api/send",
            json={
                "from_address": "sender@example.com",
                "to_addresses": ["recipient@example.com"],
                "subject": "Test Subject",
                "body_text": "Hello, World!"
            }
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["message"] == "Email sent successfully"
        assert data["from_address"] == "sender@example.com"
        assert data["to_addresses"] == ["recipient@example.com"]
        assert data["subject"] == "Test Subject"
        assert "id" in data
        assert "received_at" in data

    def test_send_email_stored_in_inbox(self, api_client):
        """Test that sent email is stored in recipient inbox."""
        inbox_store = api_client.app.state.inbox_store

        api_client.post(
            "/api/send",
            json={
                "from_address": "sender@example.com",
                "to_addresses": ["recipient@example.com"],
                "subject": "Stored Test",
                "body_text": "This should be stored"
            }
        )

        # Verify email was stored
        inbox = inbox_store.get_inbox("recipient@example.com")
        assert inbox is not None
        assert inbox.email_count == 1
        assert inbox.emails[0].subject == "Stored Test"

    def test_send_email_multiple_recipients(self, api_client):
        """Test sending email to multiple recipients."""
        inbox_store = api_client.app.state.inbox_store

        response = api_client.post(
            "/api/send",
            json={
                "from_address": "sender@example.com",
                "to_addresses": [
                    "recipient1@example.com",
                    "recipient2@example.com",
                    "recipient3@example.com"
                ],
                "subject": "Multi-recipient Test",
                "body_text": "Hello everyone!"
            }
        )

        assert response.status_code == status.HTTP_201_CREATED

        # Verify stored in all inboxes
        for i in range(1, 4):
            inbox = inbox_store.get_inbox(f"recipient{i}@example.com")
            assert inbox is not None
            assert inbox.email_count == 1

    def test_send_email_html_only(self, api_client):
        """Test sending email with HTML body only."""
        response = api_client.post(
            "/api/send",
            json={
                "from_address": "sender@example.com",
                "to_addresses": ["recipient@example.com"],
                "subject": "HTML Only",
                "body_html": "<h1>Hello</h1><p>World</p>"
            }
        )

        assert response.status_code == status.HTTP_201_CREATED

    def test_send_email_both_bodies(self, api_client):
        """Test sending email with both text and HTML bodies."""
        response = api_client.post(
            "/api/send",
            json={
                "from_address": "sender@example.com",
                "to_addresses": ["recipient@example.com"],
                "subject": "Both Bodies",
                "body_text": "Plain text version",
                "body_html": "<p>HTML version</p>"
            }
        )

        assert response.status_code == status.HTTP_201_CREATED

    def test_send_email_missing_body(self, api_client):
        """Test that sending email without any body fails."""
        response = api_client.post(
            "/api/send",
            json={
                "from_address": "sender@example.com",
                "to_addresses": ["recipient@example.com"],
                "subject": "No Body"
            }
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "body_text or body_html" in response.json()["detail"]

    def test_send_email_empty_to_addresses(self, api_client):
        """Test that empty to_addresses fails validation."""
        response = api_client.post(
            "/api/send",
            json={
                "from_address": "sender@example.com",
                "to_addresses": [],
                "subject": "No Recipients",
                "body_text": "Hello"
            }
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_send_email_missing_from_address(self, api_client):
        """Test that missing from_address fails validation."""
        response = api_client.post(
            "/api/send",
            json={
                "to_addresses": ["recipient@example.com"],
                "subject": "No Sender",
                "body_text": "Hello"
            }
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


class TestSendAPIWebhookIntegration:
    """Tests for webhook integration when sending emails via REST API."""

    def test_send_email_triggers_webhook(self, api_client_with_mock_dispatcher):
        """Test that sending email via REST API triggers registered webhooks."""
        client = api_client_with_mock_dispatcher
        webhook_registry = client.app.state.webhook_registry
        mock_dispatcher = client.app.state.webhook_dispatcher

        # Register a webhook for the recipient inbox
        webhook = webhook_registry.register(
            url="http://example.com/webhook",
            inbox_filter="recipient@example.com"
        )
        logger.info(f"Registered webhook: {webhook.id}")

        # Send email
        response = client.post(
            "/api/send",
            json={
                "from_address": "sender@example.com",
                "to_addresses": ["recipient@example.com"],
                "subject": "Webhook Test",
                "body_text": "This should trigger a webhook"
            }
        )

        assert response.status_code == status.HTTP_201_CREATED

        # Give async task time to execute
        import time
        time.sleep(0.1)

        # Verify webhook dispatcher was called
        mock_dispatcher.dispatch_batch.assert_called()
        call_args = mock_dispatcher.dispatch_batch.call_args[0][0]

        # Should have one webhook task (url, email) tuple
        assert len(call_args) == 1
        url, email = call_args[0]
        assert url == "http://example.com/webhook"
        assert email.subject == "Webhook Test"

    def test_send_email_triggers_multiple_webhooks(self, api_client_with_mock_dispatcher):
        """Test that multiple webhooks are triggered for matching recipients."""
        client = api_client_with_mock_dispatcher
        webhook_registry = client.app.state.webhook_registry
        mock_dispatcher = client.app.state.webhook_dispatcher

        # Register multiple webhooks
        webhook_registry.register(
            url="http://webhook1.example.com",
            inbox_filter="recipient@example.com"
        )
        webhook_registry.register(
            url="http://webhook2.example.com",
            inbox_filter="recipient@example.com"
        )
        webhook_registry.register(
            url="http://webhook-all.example.com",
            inbox_filter=None  # Global webhook
        )

        # Send email
        response = client.post(
            "/api/send",
            json={
                "from_address": "sender@example.com",
                "to_addresses": ["recipient@example.com"],
                "subject": "Multi-webhook Test",
                "body_text": "This should trigger multiple webhooks"
            }
        )

        assert response.status_code == status.HTTP_201_CREATED

        # Give async task time to execute
        import time
        time.sleep(0.1)

        # Verify dispatcher was called with all webhooks
        mock_dispatcher.dispatch_batch.assert_called()
        call_args = mock_dispatcher.dispatch_batch.call_args[0][0]

        # Should have 3 webhook tasks
        assert len(call_args) == 3
        urls = {task[0] for task in call_args}
        # Note: Pydantic HttpUrl may add trailing slash
        assert any("webhook1.example.com" in url for url in urls)
        assert any("webhook2.example.com" in url for url in urls)
        assert any("webhook-all.example.com" in url for url in urls)

    def test_send_email_no_matching_webhooks(self, api_client_with_mock_dispatcher):
        """Test that no webhooks are called when none match the recipient."""
        client = api_client_with_mock_dispatcher
        webhook_registry = client.app.state.webhook_registry
        mock_dispatcher = client.app.state.webhook_dispatcher

        # Register webhook for different inbox
        webhook_registry.register(
            url="http://example.com/webhook",
            inbox_filter="other@example.com"
        )

        # Send email to different recipient
        response = client.post(
            "/api/send",
            json={
                "from_address": "sender@example.com",
                "to_addresses": ["recipient@example.com"],
                "subject": "No Webhook Match",
                "body_text": "No webhooks should trigger"
            }
        )

        assert response.status_code == status.HTTP_201_CREATED

        # Give async task time to execute
        import time
        time.sleep(0.1)

        # Dispatcher should not be called (no matching webhooks)
        mock_dispatcher.dispatch_batch.assert_not_called()

    def test_send_email_global_webhook_matches_all(self, api_client_with_mock_dispatcher):
        """Test that global webhooks (no inbox_filter) match all emails."""
        client = api_client_with_mock_dispatcher
        webhook_registry = client.app.state.webhook_registry
        mock_dispatcher = client.app.state.webhook_dispatcher

        # Register global webhook (no inbox filter)
        webhook_registry.register(
            url="http://global.example.com/webhook",
            inbox_filter=None
        )

        # Send email to any recipient
        response = client.post(
            "/api/send",
            json={
                "from_address": "sender@example.com",
                "to_addresses": ["anyone@example.com"],
                "subject": "Global Webhook Test",
                "body_text": "Global webhook should trigger"
            }
        )

        assert response.status_code == status.HTTP_201_CREATED

        # Give async task time to execute
        import time
        time.sleep(0.1)

        # Verify global webhook was triggered
        mock_dispatcher.dispatch_batch.assert_called()
        call_args = mock_dispatcher.dispatch_batch.call_args[0][0]
        assert len(call_args) == 1
        assert call_args[0][0] == "http://global.example.com/webhook"

    def test_send_email_webhook_for_each_recipient(self, api_client_with_mock_dispatcher):
        """Test that webhooks are triggered for each recipient inbox."""
        client = api_client_with_mock_dispatcher
        webhook_registry = client.app.state.webhook_registry
        mock_dispatcher = client.app.state.webhook_dispatcher

        # Register webhooks for different recipients
        webhook_registry.register(
            url="http://webhook-r1.example.com",
            inbox_filter="recipient1@example.com"
        )
        webhook_registry.register(
            url="http://webhook-r2.example.com",
            inbox_filter="recipient2@example.com"
        )

        # Send email to both recipients
        response = client.post(
            "/api/send",
            json={
                "from_address": "sender@example.com",
                "to_addresses": ["recipient1@example.com", "recipient2@example.com"],
                "subject": "Multi-recipient Webhook Test",
                "body_text": "Webhooks for both recipients"
            }
        )

        assert response.status_code == status.HTTP_201_CREATED

        # Give async task time to execute
        import time
        time.sleep(0.1)

        # Verify both webhooks were triggered
        mock_dispatcher.dispatch_batch.assert_called()
        call_args = mock_dispatcher.dispatch_batch.call_args[0][0]

        # Should have 2 webhook tasks (one per recipient)
        assert len(call_args) == 2
        urls = {task[0] for task in call_args}
        # Note: Pydantic HttpUrl may add trailing slash
        assert any("webhook-r1.example.com" in url for url in urls)
        assert any("webhook-r2.example.com" in url for url in urls)

    def test_send_email_webhook_does_not_block_response(self, api_client_with_mock_dispatcher):
        """Test that webhook dispatch doesn't block the API response."""
        client = api_client_with_mock_dispatcher
        webhook_registry = client.app.state.webhook_registry
        mock_dispatcher = client.app.state.webhook_dispatcher

        # Make dispatcher slow
        async def slow_dispatch(webhooks):
            await asyncio.sleep(1)
            return [{"status": "sent"}]

        mock_dispatcher.dispatch_batch = AsyncMock(side_effect=slow_dispatch)

        webhook_registry.register(
            url="http://slow.example.com/webhook",
            inbox_filter="recipient@example.com"
        )

        import time
        start_time = time.time()

        response = client.post(
            "/api/send",
            json={
                "from_address": "sender@example.com",
                "to_addresses": ["recipient@example.com"],
                "subject": "Non-blocking Test",
                "body_text": "Response should be fast"
            }
        )

        elapsed_time = time.time() - start_time

        assert response.status_code == status.HTTP_201_CREATED
        # Response should be much faster than the slow webhook (fire-and-forget)
        assert elapsed_time < 0.5

    def test_send_email_webhook_error_does_not_fail_request(
        self,
        api_client_with_mock_dispatcher
    ):
        """Test that webhook errors don't cause the API request to fail."""
        client = api_client_with_mock_dispatcher
        webhook_registry = client.app.state.webhook_registry
        mock_dispatcher = client.app.state.webhook_dispatcher

        # Make dispatcher raise an exception
        mock_dispatcher.dispatch_batch = AsyncMock(
            side_effect=Exception("Webhook service unavailable")
        )

        webhook_registry.register(
            url="http://failing.example.com/webhook",
            inbox_filter="recipient@example.com"
        )

        # Email should still be sent successfully
        response = client.post(
            "/api/send",
            json={
                "from_address": "sender@example.com",
                "to_addresses": ["recipient@example.com"],
                "subject": "Webhook Error Test",
                "body_text": "Email should succeed despite webhook failure"
            }
        )

        assert response.status_code == status.HTTP_201_CREATED

        # Verify email was stored
        inbox_store = client.app.state.inbox_store
        inbox = inbox_store.get_inbox("recipient@example.com")
        assert inbox is not None
        assert inbox.email_count == 1
