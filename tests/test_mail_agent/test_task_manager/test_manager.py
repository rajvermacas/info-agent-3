"""
Tests for TaskManager - task lifecycle management.
"""

import asyncio
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mail_agent.persistence.database import DatabaseManager
from mail_agent.persistence.task_store import TaskStore
from mail_agent.task_manager.manager import (
    TaskManager,
    TaskManagerError,
    TaskNotFoundError,
    TaskExpiredError,
)
from mail_agent.task_manager.models import TaskState, WebhookPayload


@pytest.fixture
def temp_db_path():
    """Create a temporary database path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir) / "test.db"


@pytest.fixture
def mock_settings(temp_db_path):
    """Create mock settings with temporary database path."""
    settings = MagicMock()
    settings.sqlite_db_path = str(temp_db_path)
    settings.task_suspend_timeout_seconds = 3600
    settings.expired_task_cleanup_interval_seconds = 300
    return settings


@pytest.fixture
async def db_manager(mock_settings):
    """Create and connect a database manager."""
    db = DatabaseManager(settings=mock_settings)
    await db.connect()
    yield db
    await db.close()


@pytest.fixture
def task_store(db_manager):
    """Create a task store."""
    return TaskStore(db_manager)


@pytest.fixture
def mock_checkpointer():
    """Create a mock checkpointer."""
    return MagicMock()


@pytest.fixture
def mock_graph():
    """Create a mock LangGraph."""
    graph = MagicMock()
    graph.astream = AsyncMock(return_value=AsyncMock())
    return graph


@pytest.fixture
async def task_manager(db_manager, task_store, mock_checkpointer, mock_graph, mock_settings):
    """Create a task manager (not started)."""
    manager = TaskManager(
        db_manager=db_manager,
        task_store=task_store,
        checkpointer=mock_checkpointer,
        graph=mock_graph,
        settings=mock_settings,
    )
    yield manager
    # Cleanup: ensure stopped
    try:
        await manager.stop()
    except Exception:
        pass


class TestTaskManagerInit:
    """Tests for TaskManager initialization."""

    def test_init_with_all_args(self, db_manager, task_store, mock_checkpointer, mock_graph, mock_settings):
        """Test initialization with all required arguments."""
        manager = TaskManager(
            db_manager=db_manager,
            task_store=task_store,
            checkpointer=mock_checkpointer,
            graph=mock_graph,
            settings=mock_settings,
        )
        assert manager is not None
        assert manager.graph == mock_graph
        assert manager.checkpointer == mock_checkpointer

    def test_init_without_db_manager_raises(self, task_store, mock_checkpointer, mock_graph, mock_settings):
        """Test that initialization without db_manager raises."""
        with pytest.raises(ValueError, match="db_manager cannot be None"):
            TaskManager(
                db_manager=None,
                task_store=task_store,
                checkpointer=mock_checkpointer,
                graph=mock_graph,
                settings=mock_settings,
            )

    def test_init_without_task_store_raises(self, db_manager, mock_checkpointer, mock_graph, mock_settings):
        """Test that initialization without task_store raises."""
        with pytest.raises(ValueError, match="task_store cannot be None"):
            TaskManager(
                db_manager=db_manager,
                task_store=None,
                checkpointer=mock_checkpointer,
                graph=mock_graph,
                settings=mock_settings,
            )

    def test_init_without_checkpointer_raises(self, db_manager, task_store, mock_graph, mock_settings):
        """Test that initialization without checkpointer raises."""
        with pytest.raises(ValueError, match="checkpointer cannot be None"):
            TaskManager(
                db_manager=db_manager,
                task_store=task_store,
                checkpointer=None,
                graph=mock_graph,
                settings=mock_settings,
            )

    def test_init_without_graph_raises(self, db_manager, task_store, mock_checkpointer, mock_settings):
        """Test that initialization without graph raises."""
        with pytest.raises(ValueError, match="graph cannot be None"):
            TaskManager(
                db_manager=db_manager,
                task_store=task_store,
                checkpointer=mock_checkpointer,
                graph=None,
                settings=mock_settings,
            )


class TestTaskManagerLifecycle:
    """Tests for TaskManager start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_initializes_cleanup_task(self, task_manager):
        """Test that start initializes the background cleanup task."""
        await task_manager.start()

        # Should have a cleanup task running
        assert task_manager._cleanup_task is not None
        assert not task_manager._cleanup_task.done()

        await task_manager.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_cleanup_task(self, task_manager):
        """Test that stop cancels the background cleanup task."""
        await task_manager.start()
        await task_manager.stop()

        # Cleanup task should be done
        assert task_manager._cleanup_task.done()


class TestSuspendTask:
    """Tests for suspend_task operation."""

    @pytest.mark.asyncio
    async def test_suspend_task_registers_mapping(self, task_manager):
        """Test that suspend_task registers in-memory mapping."""
        await task_manager.start()

        await task_manager.suspend_task(
            task_id="task-123",
            poc_email="poc@example.com",
            thread_id="thread-123",
        )

        # Should be in memory mapping
        assert task_manager.get_task_for_poc("poc@example.com") == "task-123"
        assert "poc@example.com" in task_manager.get_registered_pocs()

        await task_manager.stop()

    @pytest.mark.asyncio
    async def test_suspend_task_persists_to_database(self, task_manager, task_store):
        """Test that suspend_task persists to database."""
        await task_manager.start()

        await task_manager.suspend_task(
            task_id="task-123",
            poc_email="poc@example.com",
            thread_id="thread-123",
        )

        # Should be in database
        task = await task_store.get_suspended_task("task-123")
        assert task is not None
        assert task["poc_email"] == "poc@example.com"

        await task_manager.stop()

    @pytest.mark.asyncio
    async def test_suspend_duplicate_poc_raises(self, task_manager):
        """Test that suspending for a duplicate POC raises error."""
        await task_manager.start()

        await task_manager.suspend_task(
            task_id="task-123",
            poc_email="poc@example.com",
            thread_id="thread-123",
        )

        with pytest.raises(TaskManagerError, match="already has pending task"):
            await task_manager.suspend_task(
                task_id="task-456",
                poc_email="poc@example.com",
                thread_id="thread-456",
            )

        await task_manager.stop()


class TestGetTaskStatus:
    """Tests for get_task_status operation."""

    @pytest.mark.asyncio
    async def test_get_status_for_suspended_task(self, task_manager):
        """Test getting status of a suspended task."""
        await task_manager.start()

        await task_manager.suspend_task(
            task_id="task-123",
            poc_email="poc@example.com",
            thread_id="thread-123",
        )

        status = await task_manager.get_task_status("task-123")

        assert status.task_id == "task-123"
        assert status.state == TaskState.SUSPENDED
        assert status.poc_email == "poc@example.com"
        assert "poc@example.com" in status.message

        await task_manager.stop()

    @pytest.mark.asyncio
    async def test_get_status_for_completed_task(self, task_manager, task_store):
        """Test getting status of a completed task."""
        await task_manager.start()

        # Save a completed result
        await task_store.save_result(
            task_id="task-123",
            status="completed",
            result={"data": "test"},
        )

        status = await task_manager.get_task_status("task-123")

        assert status.task_id == "task-123"
        assert status.state == TaskState.COMPLETED
        assert status.result == {"data": "test"}

        await task_manager.stop()

    @pytest.mark.asyncio
    async def test_get_status_for_failed_task(self, task_manager, task_store):
        """Test getting status of a failed task."""
        await task_manager.start()

        await task_store.save_result(
            task_id="task-123",
            status="failed",
            error="Something went wrong",
        )

        status = await task_manager.get_task_status("task-123")

        assert status.state == TaskState.FAILED
        assert status.error == "Something went wrong"

        await task_manager.stop()

    @pytest.mark.asyncio
    async def test_get_status_for_unknown_task_raises(self, task_manager):
        """Test that getting status of unknown task raises."""
        await task_manager.start()

        with pytest.raises(TaskNotFoundError):
            await task_manager.get_task_status("nonexistent")

        await task_manager.stop()


class TestHandleWebhook:
    """Tests for handle_webhook operation."""

    @pytest.mark.asyncio
    async def test_handle_webhook_returns_false_for_unknown_sender(self, task_manager):
        """Test that handle_webhook returns False for unknown sender."""
        await task_manager.start()

        payload = WebhookPayload(
            event="email.received",
            email_id="email-456",
            from_address="unknown@example.com",
            to=["agent@mail.local"],
            subject="Test",
            has_attachments=False,
            attachment_count=0,
            received_at="2025-12-15T10:30:00Z",
        )

        result = await task_manager.handle_webhook(payload)
        assert result is False

        await task_manager.stop()

    @pytest.mark.asyncio
    async def test_handle_webhook_removes_from_suspended(self, task_manager, task_store):
        """Test that handle_webhook removes task from suspended state."""
        await task_manager.start()

        await task_manager.suspend_task(
            task_id="task-123",
            poc_email="poc@example.com",
            thread_id="thread-123",
        )

        # Mock the graph to avoid actual execution
        task_manager._graph.astream = AsyncMock(
            return_value=iter([{"handle_success": {"success": True}}])
        )

        payload = WebhookPayload(
            event="email.received",
            email_id="email-456",
            from_address="poc@example.com",
            to=["agent@mail.local"],
            subject="Re: Test",
            has_attachments=False,
            attachment_count=0,
            received_at="2025-12-15T10:30:00Z",
        )

        result = await task_manager.handle_webhook(payload)
        assert result is True

        # Should no longer be in memory
        assert task_manager.get_task_for_poc("poc@example.com") is None

        # Should no longer be in database
        suspended = await task_store.get_suspended_task("task-123")
        assert suspended is None

        await task_manager.stop()


class TestUtilityMethods:
    """Tests for utility methods."""

    @pytest.mark.asyncio
    async def test_get_registered_pocs(self, task_manager):
        """Test getting list of registered POCs."""
        await task_manager.start()

        await task_manager.suspend_task(
            task_id="task-1",
            poc_email="poc1@example.com",
            thread_id="thread-1",
        )
        await task_manager.suspend_task(
            task_id="task-2",
            poc_email="poc2@example.com",
            thread_id="thread-2",
        )

        pocs = task_manager.get_registered_pocs()
        assert len(pocs) == 2
        assert "poc1@example.com" in pocs
        assert "poc2@example.com" in pocs

        await task_manager.stop()

    @pytest.mark.asyncio
    async def test_suspended_task_count(self, task_manager):
        """Test getting suspended task count."""
        await task_manager.start()

        assert task_manager.suspended_task_count == 0

        await task_manager.suspend_task(
            task_id="task-1",
            poc_email="poc1@example.com",
            thread_id="thread-1",
        )

        assert task_manager.suspended_task_count == 1

        await task_manager.stop()

    @pytest.mark.asyncio
    async def test_get_task_for_poc_case_insensitive(self, task_manager):
        """Test that get_task_for_poc is case insensitive."""
        await task_manager.start()

        await task_manager.suspend_task(
            task_id="task-123",
            poc_email="poc@example.com",
            thread_id="thread-123",
        )

        assert task_manager.get_task_for_poc("POC@EXAMPLE.COM") == "task-123"
        assert task_manager.get_task_for_poc("Poc@Example.Com") == "task-123"

        await task_manager.stop()


class TestInterruptParsing:
    """Tests for _parse_interrupt_info method used in re-suspend scenarios."""

    def test_parse_interrupt_with_interrupt_object(self, task_manager):
        """Test extracting data from LangGraph Interrupt dataclass."""
        from langgraph.types import Interrupt

        payload = {
            "reason": "waiting_for_reply",
            "poc_email": "poc@example.com",
            "task_id": "task-123",
            "sent_email_id": "email-456",
            "attempt": 1,
        }
        interrupt_info = [Interrupt(value=payload)]

        result = task_manager._parse_interrupt_info(interrupt_info)

        assert result == payload
        assert result["poc_email"] == "poc@example.com"
        assert result["task_id"] == "task-123"

    def test_parse_interrupt_with_tuple_format(self, task_manager):
        """Test extracting data from tuple format (value, id) - resume scenario."""
        payload = {
            "reason": "waiting_for_reply",
            "poc_email": "poc@example.com",
            "task_id": "task-123",
        }
        # This is the format that caused the original bug
        interrupt_info = [(payload, "interrupt-id-abc123")]

        result = task_manager._parse_interrupt_info(interrupt_info)

        assert result == payload
        assert result["poc_email"] == "poc@example.com"

    def test_parse_interrupt_with_list_of_dicts(self, task_manager):
        """Test extracting data from list of dicts directly."""
        payload = {"poc_email": "test@example.com", "reason": "waiting"}
        interrupt_info = [payload]

        result = task_manager._parse_interrupt_info(interrupt_info)

        assert result == payload
        assert result["poc_email"] == "test@example.com"

    def test_parse_interrupt_with_direct_dict(self, task_manager):
        """Test extracting data from direct dict."""
        payload = {"poc_email": "test@example.com", "reason": "waiting"}

        result = task_manager._parse_interrupt_info(payload)

        assert result == payload
        assert result["poc_email"] == "test@example.com"

    def test_parse_interrupt_with_empty_list(self, task_manager):
        """Test extracting from empty interrupt list returns empty dict."""
        interrupt_info = []

        result = task_manager._parse_interrupt_info(interrupt_info)

        assert result == {}

    def test_parse_interrupt_with_invalid_format(self, task_manager):
        """Test extracting from unknown format returns empty dict."""
        result = task_manager._parse_interrupt_info("unknown format")

        assert result == {}

    def test_parse_interrupt_with_mock_interrupt_object(self, task_manager):
        """Test extracting from object with .value attribute (mock)."""

        class MockInterrupt:
            def __init__(self, value: dict):
                self.value = value

        payload = {"poc_email": "test@example.com", "reason": "waiting"}
        interrupt_info = [MockInterrupt(payload)]

        result = task_manager._parse_interrupt_info(interrupt_info)

        assert result == payload
        assert result["poc_email"] == "test@example.com"

    def test_parse_interrupt_with_invalid_value_type(self, task_manager):
        """Test extracting when Interrupt.value is not a dict."""

        class InvalidInterrupt:
            def __init__(self, value):
                self.value = value

        interrupt_info = [InvalidInterrupt("not a dict")]

        result = task_manager._parse_interrupt_info(interrupt_info)

        assert result == {}


class TestHandleReSuspend:
    """Tests for _handle_re_suspend method."""

    @pytest.mark.asyncio
    async def test_handle_re_suspend_with_tuple_format(self, task_manager, task_store):
        """Test re-suspend handles tuple format from resumed graph execution."""
        await task_manager.start()

        # Simulate the event structure from a resumed graph
        payload = {
            "reason": "waiting_for_reply",
            "poc_email": "poc@example.com",
            "task_id": "task-123",
            "sent_email_id": "email-789",
            "attempt": 2,
        }
        event = {"__interrupt__": [(payload, "interrupt-id-xyz")]}

        await task_manager._handle_re_suspend(
            task_id="task-123",
            event=event,
            thread_id="thread-123",
        )

        # Should have suspended the task
        assert task_manager.get_task_for_poc("poc@example.com") == "task-123"
        suspended = await task_store.get_suspended_task("task-123")
        assert suspended is not None
        assert suspended["poc_email"] == "poc@example.com"

        await task_manager.stop()

    @pytest.mark.asyncio
    async def test_handle_re_suspend_with_interrupt_object(self, task_manager, task_store):
        """Test re-suspend handles LangGraph Interrupt object."""
        from langgraph.types import Interrupt

        await task_manager.start()

        payload = {
            "reason": "waiting_for_reply",
            "poc_email": "poc2@example.com",
            "task_id": "task-456",
        }
        event = {"__interrupt__": [Interrupt(value=payload)]}

        await task_manager._handle_re_suspend(
            task_id="task-456",
            event=event,
            thread_id="thread-456",
        )

        # Should have suspended the task
        assert task_manager.get_task_for_poc("poc2@example.com") == "task-456"

        await task_manager.stop()

    @pytest.mark.asyncio
    async def test_handle_re_suspend_without_poc_email(self, task_manager, task_store):
        """Test re-suspend fails gracefully when POC email missing."""
        await task_manager.start()

        # Missing poc_email in payload
        payload = {"reason": "waiting_for_reply", "task_id": "task-789"}
        event = {"__interrupt__": [(payload, "interrupt-id")]}

        await task_manager._handle_re_suspend(
            task_id="task-789",
            event=event,
            thread_id="thread-789",
        )

        # Should have saved a failed result
        result = await task_store.get_result("task-789")
        assert result is not None
        assert result["status"] == "failed"
        assert "POC email" in result["error"]

        await task_manager.stop()
