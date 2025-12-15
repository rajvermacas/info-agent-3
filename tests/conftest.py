"""Pytest configuration and shared fixtures."""

import pytest
from datetime import datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from mock_smtp.store.inbox_store import InboxStore
from mock_smtp.store.models import Attachment, Email, Inbox
from mock_smtp.webhooks.dispatcher import WebhookDispatcher
from mock_smtp.webhooks.registry import WebhookRegistry


@pytest.fixture
def inbox_store():
    """Create a fresh InboxStore for each test."""
    return InboxStore(max_emails_per_inbox=100)


@pytest.fixture
def webhook_registry():
    """Create a fresh WebhookRegistry for each test."""
    return WebhookRegistry()


@pytest.fixture
async def webhook_dispatcher():
    """Create and start a WebhookDispatcher for each test."""
    dispatcher = WebhookDispatcher(
        timeout_seconds=5.0,
        max_retries=1
    )
    await dispatcher.start()
    yield dispatcher
    await dispatcher.stop()


@pytest.fixture
def sample_email():
    """Create a sample Email for testing."""
    return Email(
        from_address="sender@example.com",
        to_addresses=["recipient@example.com"],
        subject="Test Email",
        body_text="This is a test email body.",
        body_html="<p>This is a test email body.</p>"
    )


@pytest.fixture
def sample_attachment():
    """Create a sample Attachment for testing."""
    return Attachment.from_bytes(
        filename="test.txt",
        content_type="text/plain",
        content=b"Test file content"
    )


@pytest.fixture
def sample_inbox(sample_email):
    """Create a sample Inbox with one email."""
    inbox = Inbox(email_address="test@example.com")
    inbox.add_email(sample_email)
    return inbox


@pytest.fixture
def webhook_dispatcher_sync():
    """
    Create a WebhookDispatcher for sync tests.

    Note: This dispatcher is NOT started - for sync tests that don't need
    actual HTTP dispatch. Use webhook_dispatcher for async tests.
    """
    return WebhookDispatcher(
        timeout_seconds=5.0,
        max_retries=1
    )


@pytest.fixture
def api_client(inbox_store, webhook_registry, webhook_dispatcher_sync):
    """Create a TestClient for API testing."""
    from mock_smtp.api.router import create_api_router
    from fastapi import FastAPI

    app = FastAPI()

    # Store references in app state so routes can access them
    app.state.inbox_store = inbox_store
    app.state.webhook_registry = webhook_registry
    app.state.webhook_dispatcher = webhook_dispatcher_sync

    api_router = create_api_router(
        inbox_store=inbox_store,
        webhook_registry=webhook_registry,
        webhook_dispatcher=webhook_dispatcher_sync
    )
    app.include_router(api_router)

    return TestClient(app)
