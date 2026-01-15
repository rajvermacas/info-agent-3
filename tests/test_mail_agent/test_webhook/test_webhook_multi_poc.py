"""
Tests for multi-POC webhook functionality.

Tests:
- Webhook metadata for POC routing
- Webhook server POC extraction
- Progress event multi-POC fields
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from mock_smtp.webhooks.registry import WebhookMetadata, WebhookRegistry
from mail_agent.webhook.server import WebhookMetadata as ServerWebhookMetadata
from mail_agent.webhook.server import WebhookPayload as ServerWebhookPayload
from mail_agent.a2a.progress_store import POCProgress, ProgressEvent
from mail_agent.task_manager.models import TaskState

# Use WORKING state for in-progress tasks
WORKING_STATE = TaskState.WORKING


class TestWebhookMetadata:
    """Tests for webhook metadata."""

    def test_webhook_metadata_creation(self):
        """Test creating webhook metadata with all fields."""
        metadata = WebhookMetadata(
            task_id="task_123",
            poc_id="poc_001",
            poc_email="poc@test.com",
            extra={"key": "value"},
        )

        assert metadata.task_id == "task_123"
        assert metadata.poc_id == "poc_001"
        assert metadata.poc_email == "poc@test.com"
        assert metadata.extra == {"key": "value"}

    def test_webhook_metadata_optional_fields(self):
        """Test creating metadata with optional fields."""
        metadata = WebhookMetadata()

        assert metadata.task_id is None
        assert metadata.poc_id is None
        assert metadata.poc_email is None
        assert metadata.extra is None

    def test_webhook_metadata_partial(self):
        """Test creating metadata with partial fields."""
        metadata = WebhookMetadata(
            task_id="task_123",
            poc_id="poc_001",
        )

        assert metadata.task_id == "task_123"
        assert metadata.poc_id == "poc_001"
        assert metadata.poc_email is None


class TestWebhookRegistryWithMetadata:
    """Tests for webhook registry with metadata."""

    def test_register_with_metadata(self):
        """Test registering webhook with metadata."""
        registry = WebhookRegistry()

        metadata = WebhookMetadata(
            task_id="task_123",
            poc_id="poc_001",
            poc_email="poc@test.com",
        )

        registration = registry.register(
            url="http://localhost:9000/webhook",
            inbox_filter="poc@test.com",
            metadata=metadata,
        )

        assert registration.metadata is not None
        assert registration.metadata.task_id == "task_123"
        assert registration.metadata.poc_id == "poc_001"
        assert registration.metadata.poc_email == "poc@test.com"

    def test_register_without_metadata(self):
        """Test registering webhook without metadata (backward compatible)."""
        registry = WebhookRegistry()

        registration = registry.register(
            url="http://localhost:9000/webhook",
            inbox_filter="poc@test.com",
        )

        assert registration.metadata is None

    def test_get_webhook_preserves_metadata(self):
        """Test that get_webhook preserves metadata."""
        registry = WebhookRegistry()

        metadata = WebhookMetadata(
            task_id="task_123",
            poc_id="poc_001",
        )

        registration = registry.register(
            url="http://localhost:9000/webhook",
            metadata=metadata,
        )

        retrieved = registry.get_webhook(registration.id)

        assert retrieved is not None
        assert retrieved.metadata is not None
        assert retrieved.metadata.task_id == "task_123"
        assert retrieved.metadata.poc_id == "poc_001"


class TestServerWebhookPayload:
    """Tests for server webhook payload with metadata."""

    def test_payload_with_metadata(self):
        """Test webhook payload with metadata."""
        metadata = ServerWebhookMetadata(
            task_id="task_123",
            poc_id="poc_001",
            poc_email="poc@test.com",
        )

        payload = ServerWebhookPayload(
            event="email.received",
            email_id="email_123",
            from_address="poc@test.com",
            to=["agent@test.com"],
            subject="Test",
            has_attachments=False,
            attachment_count=0,
            received_at=datetime.now(timezone.utc).isoformat(),
            metadata=metadata,
        )

        assert payload.metadata is not None
        assert payload.metadata.task_id == "task_123"
        assert payload.metadata.poc_id == "poc_001"

    def test_payload_without_metadata(self):
        """Test webhook payload without metadata."""
        payload = ServerWebhookPayload(
            event="email.received",
            email_id="email_123",
            from_address="poc@test.com",
            to=["agent@test.com"],
            subject="Test",
            has_attachments=False,
            attachment_count=0,
            received_at=datetime.now(timezone.utc).isoformat(),
        )

        assert payload.metadata is None


class TestPOCProgress:
    """Tests for POC progress model."""

    def test_poc_progress_defaults(self):
        """Test POC progress with defaults."""
        progress = POCProgress()

        assert progress.total == 0
        assert progress.pending == 0
        assert progress.in_progress == 0
        assert progress.waiting == 0
        assert progress.completed == 0
        assert progress.failed == 0

    def test_poc_progress_with_values(self):
        """Test POC progress with values."""
        progress = POCProgress(
            total=5,
            pending=1,
            in_progress=1,
            waiting=2,
            completed=1,
            failed=0,
        )

        assert progress.total == 5
        assert progress.pending == 1
        assert progress.in_progress == 1
        assert progress.waiting == 2
        assert progress.completed == 1
        assert progress.failed == 0


class TestProgressEventMultiPOC:
    """Tests for multi-POC progress event fields."""

    def test_progress_event_with_poc_id(self):
        """Test progress event with POC ID."""
        event = ProgressEvent(
            task_id="task_123",
            state=WORKING_STATE,
            message="Processing POC",
            poc_id="poc_001",
            poc_email="poc@test.com",
        )

        assert event.poc_id == "poc_001"
        assert event.poc_email == "poc@test.com"

    def test_progress_event_with_phase(self):
        """Test progress event with orchestration phase."""
        event = ProgressEvent(
            task_id="task_123",
            state=WORKING_STATE,
            message="Building dependency graph",
            phase="planning",
        )

        assert event.phase == "planning"

    def test_progress_event_with_event_type(self):
        """Test progress event with specific event type."""
        event = ProgressEvent(
            task_id="task_123",
            state=WORKING_STATE,
            message="Email sent to POC",
            event_type="poc_email_sent",
            poc_id="poc_001",
        )

        assert event.event_type == "poc_email_sent"
        assert event._get_event_type() == "poc_email_sent"

    def test_progress_event_with_poc_progress(self):
        """Test progress event with aggregate POC progress."""
        poc_progress = POCProgress(
            total=3,
            completed=1,
            waiting=2,
        )

        event = ProgressEvent(
            task_id="task_123",
            state=WORKING_STATE,
            message="Orchestrating POCs",
            poc_progress=poc_progress,
        )

        assert event.poc_progress is not None
        assert event.poc_progress.total == 3
        assert event.poc_progress.completed == 1
        assert event.poc_progress.waiting == 2

    def test_progress_event_dynamic_poc_flag(self):
        """Test progress event with dynamic POC flag."""
        event = ProgressEvent(
            task_id="task_123",
            state=WORKING_STATE,
            message="Dynamic POC spawned",
            poc_id="poc_dynamic_001",
            dynamic_poc_spawned=True,
        )

        assert event.dynamic_poc_spawned is True

    def test_sse_format_with_custom_event_type(self):
        """Test SSE format uses custom event type when provided."""
        event = ProgressEvent(
            task_id="task_123",
            state=WORKING_STATE,
            message="POC started",
            event_type="poc_started",
        )
        event.event_id = 5

        sse = event.to_sse_format()

        assert "event: poc_started" in sse
        assert "id: 5" in sse

    def test_sse_format_falls_back_to_state(self):
        """Test SSE format falls back to state when no event_type."""
        event = ProgressEvent(
            task_id="task_123",
            state=TaskState.COMPLETED,
            message="Task completed",
        )
        event.event_id = 10

        sse = event.to_sse_format()

        assert "event: complete" in sse

    def test_progress_event_serialization(self):
        """Test progress event JSON serialization."""
        event = ProgressEvent(
            task_id="task_123",
            state=WORKING_STATE,
            message="Processing",
            poc_id="poc_001",
            phase="execution",
            poc_progress=POCProgress(total=2, waiting=1, completed=1),
        )

        # Should serialize without errors
        json_str = event.model_dump_json(exclude_none=True)

        assert "poc_001" in json_str
        assert "execution" in json_str
        assert "poc_progress" in json_str
