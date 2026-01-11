"""
Tests for TaskManager models.
"""

from datetime import datetime, timezone, timedelta

import pytest

from mail_agent.task_manager.models import (
    TaskState,
    TaskStatus,
    SuspendedTaskInfo,
    TaskResult,
    WebhookPayload,
    SSEEvent,
)


class TestTaskState:
    """Tests for TaskState enum."""

    def test_task_states_exist(self):
        """Test that all expected task states exist."""
        assert TaskState.CREATED == "created"
        assert TaskState.WORKING == "working"
        assert TaskState.SUSPENDED == "suspended"
        assert TaskState.RESUMED == "resumed"
        assert TaskState.COMPLETED == "completed"
        assert TaskState.FAILED == "failed"


class TestTaskStatus:
    """Tests for TaskStatus model."""

    def test_create_suspended_status(self):
        """Test creating a suspended task status."""
        status = TaskStatus(
            task_id="task-123",
            state=TaskState.SUSPENDED,
            message="Waiting for reply from poc@example.com",
            poc_email="poc@example.com",
            created_at=datetime(2025, 12, 15, 10, 0, 0, tzinfo=timezone.utc),
            expires_at=datetime(2025, 12, 15, 11, 0, 0, tzinfo=timezone.utc),
        )

        assert status.task_id == "task-123"
        assert status.state == TaskState.SUSPENDED
        assert status.poc_email == "poc@example.com"
        assert status.result is None
        assert status.error is None

    def test_create_completed_status(self):
        """Test creating a completed task status."""
        status = TaskStatus(
            task_id="task-123",
            state=TaskState.COMPLETED,
            message="Task completed",
            completed_at=datetime(2025, 12, 15, 10, 35, 0, tzinfo=timezone.utc),
            result={"success": True, "data": "test"},
        )

        assert status.task_id == "task-123"
        assert status.state == TaskState.COMPLETED
        assert status.result == {"success": True, "data": "test"}

    def test_create_failed_status(self):
        """Test creating a failed task status."""
        status = TaskStatus(
            task_id="task-123",
            state=TaskState.FAILED,
            message="Task failed",
            error="Timeout waiting for reply",
        )

        assert status.state == TaskState.FAILED
        assert status.error == "Timeout waiting for reply"


class TestSuspendedTaskInfo:
    """Tests for SuspendedTaskInfo model."""

    def test_create_suspended_task_info(self):
        """Test creating suspended task info."""
        now = datetime.now(timezone.utc)
        info = SuspendedTaskInfo(
            task_id="task-123",
            poc_email="poc@example.com",
            thread_id="thread-123",
            created_at=now,
            expires_at=now + timedelta(hours=1),
            interrupt_data={"reason": "waiting_for_reply"},
        )

        assert info.task_id == "task-123"
        assert info.poc_email == "poc@example.com"
        assert info.thread_id == "thread-123"
        assert info.interrupt_data == {"reason": "waiting_for_reply"}

    def test_is_expired_returns_false_for_active(self):
        """Test is_expired returns False for active tasks."""
        now = datetime.now(timezone.utc)
        info = SuspendedTaskInfo(
            task_id="task-123",
            poc_email="poc@example.com",
            thread_id="thread-123",
            created_at=now,
            expires_at=now + timedelta(hours=1),
        )

        assert info.is_expired() is False

    def test_is_expired_returns_true_for_expired(self):
        """Test is_expired returns True for expired tasks."""
        now = datetime.now(timezone.utc)
        info = SuspendedTaskInfo(
            task_id="task-123",
            poc_email="poc@example.com",
            thread_id="thread-123",
            created_at=now - timedelta(hours=2),
            expires_at=now - timedelta(hours=1),
        )

        assert info.is_expired() is True


class TestTaskResult:
    """Tests for TaskResult model."""

    def test_create_completed_result(self):
        """Test creating a completed task result."""
        result = TaskResult(
            task_id="task-123",
            status="completed",
            result={"data": "Q4 sales data..."},
            completed_at=datetime(2025, 12, 15, 10, 35, 0, tzinfo=timezone.utc),
        )

        assert result.task_id == "task-123"
        assert result.status == "completed"
        assert result.result == {"data": "Q4 sales data..."}
        assert result.error is None

    def test_create_failed_result(self):
        """Test creating a failed task result."""
        result = TaskResult(
            task_id="task-123",
            status="failed",
            error="Task expired",
            completed_at=datetime(2025, 12, 15, 11, 0, 0, tzinfo=timezone.utc),
        )

        assert result.status == "failed"
        assert result.error == "Task expired"
        assert result.result is None


class TestWebhookPayload:
    """Tests for WebhookPayload model."""

    def test_create_webhook_payload(self):
        """Test creating a webhook payload."""
        payload = WebhookPayload(
            event="email.received",
            email_id="email-456",
            from_address="poc@example.com",
            to=["agent@mail.local"],
            subject="Re: Q4 Sales Data Request",
            has_attachments=True,
            attachment_count=1,
            received_at="2025-12-15T10:30:00Z",
            body_preview="Hi, here's the Q4 data...",
        )

        assert payload.event == "email.received"
        assert payload.email_id == "email-456"
        assert payload.from_address == "poc@example.com"
        assert payload.has_attachments is True

    def test_webhook_payload_from_alias(self):
        """Test creating webhook payload with 'from' alias."""
        # When receiving JSON with 'from' field
        payload = WebhookPayload.model_validate({
            "event": "email.received",
            "email_id": "email-456",
            "from": "poc@example.com",  # Using alias
            "to": ["agent@mail.local"],
            "subject": "Test",
            "has_attachments": False,
            "attachment_count": 0,
            "received_at": "2025-12-15T10:30:00Z",
        })

        assert payload.from_address == "poc@example.com"

    def test_to_resume_data(self):
        """Test converting webhook payload to resume data."""
        payload = WebhookPayload(
            event="email.received",
            email_id="email-456",
            from_address="poc@example.com",
            to=["agent@mail.local"],
            subject="Re: Test",
            has_attachments=True,
            attachment_count=1,
            received_at="2025-12-15T10:30:00Z",
        )

        resume_data = payload.to_resume_data()

        assert resume_data["email_id"] == "email-456"
        assert resume_data["from_address"] == "poc@example.com"
        assert resume_data["subject"] == "Re: Test"
        assert resume_data["has_attachments"] is True


class TestSSEEvent:
    """Tests for SSEEvent model."""

    def test_create_working_event(self):
        """Test creating a working SSE event."""
        event = SSEEvent(
            task_id="task-123",
            state=TaskState.WORKING,
            message="Composing email...",
            node="compose_email",
        )

        assert event.task_id == "task-123"
        assert event.state == TaskState.WORKING
        assert event.node == "compose_email"

    def test_create_suspended_event(self):
        """Test creating a suspended SSE event."""
        event = SSEEvent(
            task_id="task-123",
            state=TaskState.SUSPENDED,
            message="Waiting for reply from poc@example.com",
            poc_email="poc@example.com",
        )

        assert event.state == TaskState.SUSPENDED
        assert event.poc_email == "poc@example.com"

    def test_to_sse_data(self):
        """Test converting SSE event to JSON string."""
        event = SSEEvent(
            task_id="task-123",
            state=TaskState.WORKING,
            message="Processing...",
        )

        data = event.to_sse_data()

        # Should be valid JSON
        import json
        parsed = json.loads(data)
        assert parsed["task_id"] == "task-123"
        assert parsed["state"] == "working"
        assert parsed["message"] == "Processing..."

    def test_to_sse_data_excludes_none(self):
        """Test that to_sse_data excludes None values."""
        event = SSEEvent(
            task_id="task-123",
            state=TaskState.WORKING,
            message="Processing...",
        )

        data = event.to_sse_data()

        import json
        parsed = json.loads(data)
        assert "poc_email" not in parsed
        assert "result" not in parsed
        assert "error" not in parsed
