"""
Tests for ProgressService.

Tests the unified progress event emission and persistence service.
"""

import json
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from mail_agent.a2a.progress_service import ProgressService, ProgressServiceError
from mail_agent.a2a.progress_store import ProgressStore, ProgressEvent
from mail_agent.persistence.database import DatabaseManager
from mail_agent.task_manager.models import TaskState


class TestProgressServiceInit:
    """Tests for ProgressService initialization."""

    def test_init_with_valid_dependencies(self) -> None:
        """Test initialization with valid dependencies."""
        progress_store = MagicMock(spec=ProgressStore)
        db_manager = MagicMock(spec=DatabaseManager)

        service = ProgressService(
            progress_store=progress_store,
            db_manager=db_manager,
        )

        assert service._store == progress_store
        assert service._db == db_manager

    def test_init_with_none_progress_store_raises(self) -> None:
        """Test initialization with None progress_store raises ValueError."""
        db_manager = MagicMock(spec=DatabaseManager)

        with pytest.raises(ValueError, match="progress_store cannot be None"):
            ProgressService(
                progress_store=None,  # type: ignore
                db_manager=db_manager,
            )

    def test_init_with_none_db_manager_raises(self) -> None:
        """Test initialization with None db_manager raises ValueError."""
        progress_store = MagicMock(spec=ProgressStore)

        with pytest.raises(ValueError, match="db_manager cannot be None"):
            ProgressService(
                progress_store=progress_store,
                db_manager=None,  # type: ignore
            )

    def test_progress_store_property(self) -> None:
        """Test progress_store property returns the store."""
        progress_store = MagicMock(spec=ProgressStore)
        db_manager = MagicMock(spec=DatabaseManager)

        service = ProgressService(
            progress_store=progress_store,
            db_manager=db_manager,
        )

        assert service.progress_store == progress_store


class TestEmitEvent:
    """Tests for ProgressService.emit_event()."""

    @pytest.fixture
    def service(self) -> ProgressService:
        """Create a ProgressService with mocked dependencies."""
        progress_store = MagicMock(spec=ProgressStore)
        progress_store.add_event = AsyncMock()

        db_manager = MagicMock(spec=DatabaseManager)
        db_manager.execute = AsyncMock()
        db_manager.commit = AsyncMock()

        return ProgressService(
            progress_store=progress_store,
            db_manager=db_manager,
        )

    @pytest.mark.asyncio
    async def test_emit_event_adds_to_store(self, service: ProgressService) -> None:
        """Test that emit_event adds event to progress store."""
        await service.emit_event(
            task_id="task-123",
            state=TaskState.WORKING,
            message="Test message",
            node="test_node",
        )

        service._store.add_event.assert_called_once()
        call_args = service._store.add_event.call_args[0][0]
        assert isinstance(call_args, ProgressEvent)
        assert call_args.task_id == "task-123"
        assert call_args.state == TaskState.WORKING
        assert call_args.message == "Test message"
        assert call_args.node == "test_node"

    @pytest.mark.asyncio
    async def test_emit_event_persists_to_database(
        self, service: ProgressService
    ) -> None:
        """Test that emit_event persists event to database."""
        await service.emit_event(
            task_id="task-123",
            state=TaskState.WORKING,
            message="Test message",
        )

        service._db.execute.assert_called_once()
        service._db.commit.assert_called_once()

        # Verify SQL and parameters
        call_args = service._db.execute.call_args
        sql = call_args[0][0]
        params = call_args[0][1]

        assert "INSERT INTO progress_events" in sql
        assert params[0] == "task-123"  # task_id
        assert params[2] == "working"  # state value

    @pytest.mark.asyncio
    async def test_emit_event_with_all_fields(self, service: ProgressService) -> None:
        """Test emit_event with all optional fields."""
        result = {"data": "test"}

        await service.emit_event(
            task_id="task-123",
            state=TaskState.COMPLETED,
            message="Task completed",
            node="final_node",
            poc_email="test@example.com",
            result=result,
            error=None,
        )

        service._store.add_event.assert_called_once()
        call_args = service._store.add_event.call_args[0][0]
        assert call_args.poc_email == "test@example.com"
        assert call_args.result == result

    @pytest.mark.asyncio
    async def test_emit_event_with_error(self, service: ProgressService) -> None:
        """Test emit_event with error field."""
        await service.emit_event(
            task_id="task-123",
            state=TaskState.FAILED,
            message="Task failed",
            error="Something went wrong",
        )

        service._store.add_event.assert_called_once()
        call_args = service._store.add_event.call_args[0][0]
        assert call_args.error == "Something went wrong"

    @pytest.mark.asyncio
    async def test_emit_event_returns_event(self, service: ProgressService) -> None:
        """Test that emit_event returns the created event."""
        event = await service.emit_event(
            task_id="task-123",
            state=TaskState.WORKING,
            message="Test message",
        )

        assert isinstance(event, ProgressEvent)
        assert event.task_id == "task-123"

    @pytest.mark.asyncio
    async def test_emit_event_raises_on_store_error(
        self, service: ProgressService
    ) -> None:
        """Test that emit_event raises ProgressServiceError on store error."""
        service._store.add_event = AsyncMock(
            side_effect=Exception("Store error")
        )

        with pytest.raises(ProgressServiceError, match="Failed to emit progress event"):
            await service.emit_event(
                task_id="task-123",
                state=TaskState.WORKING,
                message="Test message",
            )


class TestEmitWebhookReceived:
    """Tests for ProgressService.emit_webhook_received()."""

    @pytest.fixture
    def service(self) -> ProgressService:
        """Create a ProgressService with mocked dependencies."""
        progress_store = MagicMock(spec=ProgressStore)
        progress_store.add_event = AsyncMock()

        db_manager = MagicMock(spec=DatabaseManager)
        db_manager.execute = AsyncMock()
        db_manager.commit = AsyncMock()

        return ProgressService(
            progress_store=progress_store,
            db_manager=db_manager,
        )

    @pytest.mark.asyncio
    async def test_emit_webhook_received_correct_message(
        self, service: ProgressService
    ) -> None:
        """Test webhook received event has correct message format."""
        await service.emit_webhook_received(
            task_id="task-123",
            poc_email="test@example.com",
            received_count=1,
            total_count=3,
        )

        call_args = service._store.add_event.call_args[0][0]
        assert "Received reply from test@example.com" in call_args.message
        assert "(1/3 POCs responded)" in call_args.message

    @pytest.mark.asyncio
    async def test_emit_webhook_received_uses_suspended_state(
        self, service: ProgressService
    ) -> None:
        """Test webhook received event uses SUSPENDED state."""
        await service.emit_webhook_received(
            task_id="task-123",
            poc_email="test@example.com",
            received_count=1,
            total_count=2,
        )

        call_args = service._store.add_event.call_args[0][0]
        assert call_args.state == TaskState.SUSPENDED

    @pytest.mark.asyncio
    async def test_emit_webhook_received_sets_poc_email(
        self, service: ProgressService
    ) -> None:
        """Test webhook received event sets poc_email field."""
        await service.emit_webhook_received(
            task_id="task-123",
            poc_email="poc@example.com",
            received_count=2,
            total_count=2,
        )

        call_args = service._store.add_event.call_args[0][0]
        assert call_args.poc_email == "poc@example.com"

    @pytest.mark.asyncio
    async def test_emit_webhook_received_sets_node(
        self, service: ProgressService
    ) -> None:
        """Test webhook received event sets node to 'webhook_received'."""
        await service.emit_webhook_received(
            task_id="task-123",
            poc_email="poc@example.com",
            received_count=1,
            total_count=1,
        )

        call_args = service._store.add_event.call_args[0][0]
        assert call_args.node == "webhook_received"


class TestEmitAllWebhooksReceived:
    """Tests for ProgressService.emit_all_webhooks_received()."""

    @pytest.fixture
    def service(self) -> ProgressService:
        """Create a ProgressService with mocked dependencies."""
        progress_store = MagicMock(spec=ProgressStore)
        progress_store.add_event = AsyncMock()

        db_manager = MagicMock(spec=DatabaseManager)
        db_manager.execute = AsyncMock()
        db_manager.commit = AsyncMock()

        return ProgressService(
            progress_store=progress_store,
            db_manager=db_manager,
        )

    @pytest.mark.asyncio
    async def test_emit_all_webhooks_received_message(
        self, service: ProgressService
    ) -> None:
        """Test all webhooks received has correct message."""
        await service.emit_all_webhooks_received(
            task_id="task-123",
            poc_emails=["a@example.com", "b@example.com"],
        )

        call_args = service._store.add_event.call_args[0][0]
        assert "All 2 POC(s) have replied" in call_args.message

    @pytest.mark.asyncio
    async def test_emit_all_webhooks_received_joins_emails(
        self, service: ProgressService
    ) -> None:
        """Test all webhooks received joins POC emails."""
        await service.emit_all_webhooks_received(
            task_id="task-123",
            poc_emails=["a@example.com", "b@example.com"],
        )

        call_args = service._store.add_event.call_args[0][0]
        assert call_args.poc_email == "a@example.com, b@example.com"


class TestEmitTaskResumed:
    """Tests for ProgressService.emit_task_resumed()."""

    @pytest.fixture
    def service(self) -> ProgressService:
        """Create a ProgressService with mocked dependencies."""
        progress_store = MagicMock(spec=ProgressStore)
        progress_store.add_event = AsyncMock()

        db_manager = MagicMock(spec=DatabaseManager)
        db_manager.execute = AsyncMock()
        db_manager.commit = AsyncMock()

        return ProgressService(
            progress_store=progress_store,
            db_manager=db_manager,
        )

    @pytest.mark.asyncio
    async def test_emit_task_resumed_uses_resumed_state(
        self, service: ProgressService
    ) -> None:
        """Test task resumed event uses RESUMED state."""
        await service.emit_task_resumed(
            task_id="task-123",
            poc_emails=["test@example.com"],
        )

        call_args = service._store.add_event.call_args[0][0]
        assert call_args.state == TaskState.RESUMED

    @pytest.mark.asyncio
    async def test_emit_task_resumed_message_format(
        self, service: ProgressService
    ) -> None:
        """Test task resumed event has correct message format."""
        await service.emit_task_resumed(
            task_id="task-123",
            poc_emails=["a@example.com", "b@example.com"],
        )

        call_args = service._store.add_event.call_args[0][0]
        assert "Task resuming with replies from 2 POC(s)" in call_args.message

    @pytest.mark.asyncio
    async def test_emit_task_resumed_sets_node(
        self, service: ProgressService
    ) -> None:
        """Test task resumed event sets node to 'resume'."""
        await service.emit_task_resumed(
            task_id="task-123",
            poc_emails=["test@example.com"],
        )

        call_args = service._store.add_event.call_args[0][0]
        assert call_args.node == "resume"


class TestEmitValidationResult:
    """Tests for ProgressService.emit_validation_result()."""

    @pytest.fixture
    def service(self) -> ProgressService:
        """Create a ProgressService with mocked dependencies."""
        progress_store = MagicMock(spec=ProgressStore)
        progress_store.add_event = AsyncMock()

        db_manager = MagicMock(spec=DatabaseManager)
        db_manager.execute = AsyncMock()
        db_manager.commit = AsyncMock()

        return ProgressService(
            progress_store=progress_store,
            db_manager=db_manager,
        )

    @pytest.mark.asyncio
    async def test_emit_validation_passed(self, service: ProgressService) -> None:
        """Test validation passed event message."""
        await service.emit_validation_result(
            task_id="task-123",
            poc_email="test@example.com",
            is_valid=True,
        )

        call_args = service._store.add_event.call_args[0][0]
        assert "Validation passed for test@example.com" in call_args.message

    @pytest.mark.asyncio
    async def test_emit_validation_failed(self, service: ProgressService) -> None:
        """Test validation failed event message."""
        await service.emit_validation_result(
            task_id="task-123",
            poc_email="test@example.com",
            is_valid=False,
            feedback="Missing required fields",
        )

        call_args = service._store.add_event.call_args[0][0]
        assert "Validation failed for test@example.com" in call_args.message
        assert "Missing required fields" in call_args.message

    @pytest.mark.asyncio
    async def test_emit_validation_uses_working_state(
        self, service: ProgressService
    ) -> None:
        """Test validation result uses WORKING state."""
        await service.emit_validation_result(
            task_id="task-123",
            poc_email="test@example.com",
            is_valid=True,
        )

        call_args = service._store.add_event.call_args[0][0]
        assert call_args.state == TaskState.WORKING


class TestGetActivityHistory:
    """Tests for ProgressService.get_activity_history()."""

    @pytest.fixture
    def service(self) -> ProgressService:
        """Create a ProgressService with mocked dependencies."""
        progress_store = MagicMock(spec=ProgressStore)

        db_manager = MagicMock(spec=DatabaseManager)

        return ProgressService(
            progress_store=progress_store,
            db_manager=db_manager,
        )

    @pytest.mark.asyncio
    async def test_get_activity_history_returns_events(
        self, service: ProgressService
    ) -> None:
        """Test get_activity_history returns events from database."""
        mock_rows = [
            (1, "task-123", "working", "node1", "Message 1", None, None, None, "2025-01-01T10:00:00", "2025-01-01T10:00:00"),
            (2, "task-123", "completed", "node2", "Message 2", "poc@example.com", None, None, "2025-01-01T10:01:00", "2025-01-01T10:01:00"),
        ]
        service._db.fetch_all = AsyncMock(return_value=mock_rows)

        events = await service.get_activity_history("task-123")

        assert len(events) == 2
        assert events[0]["event_id"] == 1
        assert events[0]["state"] == "working"
        assert events[0]["message"] == "Message 1"
        assert events[1]["poc_email"] == "poc@example.com"

    @pytest.mark.asyncio
    async def test_get_activity_history_empty(self, service: ProgressService) -> None:
        """Test get_activity_history returns empty list when no events."""
        service._db.fetch_all = AsyncMock(return_value=[])

        events = await service.get_activity_history("task-123")

        assert events == []

    @pytest.mark.asyncio
    async def test_get_activity_history_parses_result_json(
        self, service: ProgressService
    ) -> None:
        """Test get_activity_history parses JSON result field."""
        result_json = json.dumps({"data": "test"})
        mock_rows = [
            (1, "task-123", "completed", "node1", "Done", None, result_json, None, "2025-01-01T10:00:00", "2025-01-01T10:00:00"),
        ]
        service._db.fetch_all = AsyncMock(return_value=mock_rows)

        events = await service.get_activity_history("task-123")

        assert events[0]["result"] == {"data": "test"}

    @pytest.mark.asyncio
    async def test_get_activity_history_handles_null_result(
        self, service: ProgressService
    ) -> None:
        """Test get_activity_history handles null result field."""
        mock_rows = [
            (1, "task-123", "working", "node1", "Working", None, None, None, "2025-01-01T10:00:00", "2025-01-01T10:00:00"),
        ]
        service._db.fetch_all = AsyncMock(return_value=mock_rows)

        events = await service.get_activity_history("task-123")

        assert events[0]["result"] is None

    @pytest.mark.asyncio
    async def test_get_activity_history_raises_on_error(
        self, service: ProgressService
    ) -> None:
        """Test get_activity_history raises ProgressServiceError on error."""
        service._db.fetch_all = AsyncMock(side_effect=Exception("DB error"))

        with pytest.raises(ProgressServiceError, match="Failed to fetch activity"):
            await service.get_activity_history("task-123")


class TestDeleteActivityHistory:
    """Tests for ProgressService.delete_activity_history()."""

    @pytest.fixture
    def service(self) -> ProgressService:
        """Create a ProgressService with mocked dependencies."""
        progress_store = MagicMock(spec=ProgressStore)

        db_manager = MagicMock(spec=DatabaseManager)
        db_manager.commit = AsyncMock()

        return ProgressService(
            progress_store=progress_store,
            db_manager=db_manager,
        )

    @pytest.mark.asyncio
    async def test_delete_activity_history_executes_delete(
        self, service: ProgressService
    ) -> None:
        """Test delete_activity_history executes DELETE query."""
        mock_cursor = MagicMock()
        mock_cursor.rowcount = 5
        service._db.execute = AsyncMock(return_value=mock_cursor)

        count = await service.delete_activity_history("task-123")

        assert count == 5
        service._db.execute.assert_called_once()
        service._db.commit.assert_called_once()

        call_args = service._db.execute.call_args
        sql = call_args[0][0]
        assert "DELETE FROM progress_events" in sql
        assert call_args[0][1] == ("task-123",)

    @pytest.mark.asyncio
    async def test_delete_activity_history_returns_zero_when_none(
        self, service: ProgressService
    ) -> None:
        """Test delete_activity_history returns 0 when no events to delete."""
        mock_cursor = MagicMock()
        mock_cursor.rowcount = 0
        service._db.execute = AsyncMock(return_value=mock_cursor)

        count = await service.delete_activity_history("task-123")

        assert count == 0

    @pytest.mark.asyncio
    async def test_delete_activity_history_raises_on_error(
        self, service: ProgressService
    ) -> None:
        """Test delete_activity_history raises ProgressServiceError on error."""
        service._db.execute = AsyncMock(side_effect=Exception("DB error"))

        with pytest.raises(ProgressServiceError, match="Failed to delete activity"):
            await service.delete_activity_history("task-123")
