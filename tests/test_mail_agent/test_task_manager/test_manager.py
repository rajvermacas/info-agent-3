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


class TestSaveResult:
    """Tests for save_result method."""

    @pytest.mark.asyncio
    async def test_save_result_completed(self, task_manager, task_store):
        """Test saving a completed task result."""
        await task_manager.start()

        await task_manager.save_result(
            task_id="task-completed-1",
            status="completed",
            result={"data": "test_data", "success": True},
        )

        # Verify result was saved
        result = await task_store.get_result("task-completed-1")
        assert result is not None
        assert result["task_id"] == "task-completed-1"
        assert result["status"] == "completed"
        assert result["result"] == {"data": "test_data", "success": True}
        assert result["error"] is None

        await task_manager.stop()

    @pytest.mark.asyncio
    async def test_save_result_failed(self, task_manager, task_store):
        """Test saving a failed task result."""
        await task_manager.start()

        await task_manager.save_result(
            task_id="task-failed-1",
            status="failed",
            error="Something went wrong",
        )

        # Verify result was saved
        result = await task_store.get_result("task-failed-1")
        assert result is not None
        assert result["task_id"] == "task-failed-1"
        assert result["status"] == "failed"
        assert result["error"] == "Something went wrong"
        assert result["result"] is None

        await task_manager.stop()

    @pytest.mark.asyncio
    async def test_save_result_appears_in_list(self, task_manager, task_store):
        """Test saved results appear in list_all_tasks."""
        await task_manager.start()

        # Save a completed task
        await task_manager.save_result(
            task_id="task-list-test-1",
            status="completed",
            result={"value": 42},
        )

        # Save a failed task
        await task_manager.save_result(
            task_id="task-list-test-2",
            status="failed",
            error="Test error",
        )

        # List all tasks
        tasks = await task_manager.list_all_tasks()

        # Find our tasks
        task_ids = [t.task_id for t in tasks]
        assert "task-list-test-1" in task_ids
        assert "task-list-test-2" in task_ids

        # Verify states
        completed_task = next(t for t in tasks if t.task_id == "task-list-test-1")
        assert completed_task.state == TaskState.COMPLETED

        failed_task = next(t for t in tasks if t.task_id == "task-list-test-2")
        assert failed_task.state == TaskState.FAILED

        await task_manager.stop()

    @pytest.mark.asyncio
    async def test_save_result_replaces_existing(self, task_manager, task_store):
        """Test saving result replaces existing result for same task_id."""
        await task_manager.start()

        # Save initial result
        await task_manager.save_result(
            task_id="task-replace-test",
            status="failed",
            error="Initial error",
        )

        # Replace with completed result
        await task_manager.save_result(
            task_id="task-replace-test",
            status="completed",
            result={"success": True},
        )

        # Verify updated result
        result = await task_store.get_result("task-replace-test")
        assert result["status"] == "completed"
        assert result["result"] == {"success": True}
        assert result["error"] is None

        await task_manager.stop()


class TestSuspendTaskMultiPoc:
    """Tests for multi-POC suspend operation."""

    @pytest.mark.asyncio
    async def test_suspend_task_multi_poc_registers_all_pocs(self, task_manager):
        """Test that suspend_task_multi_poc registers all POC mappings."""
        await task_manager.start()

        poc_emails = ["poc1@example.com", "poc2@example.com", "poc3@example.com"]

        await task_manager.suspend_task_multi_poc(
            task_id="multi-task-123",
            poc_emails=poc_emails,
            thread_id="thread-123",
        )

        # All POCs should be mapped to the same task
        for poc_email in poc_emails:
            assert task_manager.get_task_for_poc(poc_email) == "multi-task-123"

        # All should be in registered POCs
        registered = task_manager.get_registered_pocs()
        for poc_email in poc_emails:
            assert poc_email in registered

        await task_manager.stop()

    @pytest.mark.asyncio
    async def test_suspend_task_multi_poc_persists_to_database(self, task_manager, task_store):
        """Test that suspend_task_multi_poc persists to database."""
        await task_manager.start()

        poc_emails = ["poc1@example.com", "poc2@example.com"]

        await task_manager.suspend_task_multi_poc(
            task_id="multi-task-456",
            poc_emails=poc_emails,
            thread_id="thread-456",
        )

        # Should be in multi-POC database table
        task = await task_store.get_suspended_task_multi_poc("multi-task-456")
        assert task is not None
        assert set(task["poc_emails"]) == set(poc_emails)
        assert set(task["pending_pocs"]) == set(poc_emails)

        await task_manager.stop()

    @pytest.mark.asyncio
    async def test_suspend_task_multi_poc_with_interrupt_data(self, task_manager, task_store):
        """Test that interrupt_data is persisted correctly."""
        await task_manager.start()

        poc_emails = ["poc1@example.com"]
        interrupt_data = {
            "reason": "waiting_for_replies",
            "parallel_mode": True,
            "poc_emails": poc_emails,
        }

        await task_manager.suspend_task_multi_poc(
            task_id="multi-task-789",
            poc_emails=poc_emails,
            thread_id="thread-789",
            interrupt_data=interrupt_data,
        )

        task = await task_store.get_suspended_task_multi_poc("multi-task-789")
        assert task["interrupt_data"]["parallel_mode"] is True

        await task_manager.stop()

    @pytest.mark.asyncio
    async def test_suspend_task_multi_poc_duplicate_poc_raises(self, task_manager):
        """Test that suspending with duplicate POC raises error."""
        await task_manager.start()

        await task_manager.suspend_task_multi_poc(
            task_id="multi-task-a",
            poc_emails=["shared@example.com"],
            thread_id="thread-a",
        )

        with pytest.raises(TaskManagerError, match="already has pending task"):
            await task_manager.suspend_task_multi_poc(
                task_id="multi-task-b",
                poc_emails=["shared@example.com", "other@example.com"],
                thread_id="thread-b",
            )

        await task_manager.stop()


class TestHandleWebhookMultiPoc:
    """Tests for multi-POC webhook handling."""

    @pytest.mark.asyncio
    async def test_handle_webhook_multi_poc_collects_webhooks(self, task_manager, task_store):
        """Test that webhooks are collected until all POCs respond."""
        await task_manager.start()

        poc_emails = ["poc1@example.com", "poc2@example.com", "poc3@example.com"]

        await task_manager.suspend_task_multi_poc(
            task_id="multi-webhook-task",
            poc_emails=poc_emails,
            thread_id="thread-webhook",
        )

        # First webhook - should NOT resume yet
        payload1 = WebhookPayload(
            event="email.received",
            email_id="email-1",
            from_address="poc1@example.com",
            to=["agent@mail.local"],
            subject="Re: Request",
            has_attachments=False,
            attachment_count=0,
            received_at="2025-12-15T10:30:00Z",
        )

        result1 = await task_manager.handle_webhook(payload1)
        assert result1 is True

        # Task should still be suspended (waiting for more webhooks)
        task = await task_store.get_suspended_task_multi_poc("multi-webhook-task")
        assert task is not None
        assert "poc1@example.com" not in task["pending_pocs"]
        assert "poc2@example.com" in task["pending_pocs"]
        assert "poc3@example.com" in task["pending_pocs"]

        await task_manager.stop()

    @pytest.mark.asyncio
    async def test_handle_webhook_multi_poc_resumes_when_all_received(self, task_manager, task_store):
        """Test that task resumes when all POCs have responded."""
        await task_manager.start()

        poc_emails = ["poc1@example.com", "poc2@example.com"]

        await task_manager.suspend_task_multi_poc(
            task_id="multi-resume-task",
            poc_emails=poc_emails,
            thread_id="thread-resume",
        )

        # Mock the graph to avoid actual execution
        task_manager._graph.astream = AsyncMock(
            return_value=iter([{"process_all_replies": {"success": True}}])
        )

        # First webhook
        payload1 = WebhookPayload(
            event="email.received",
            email_id="email-1",
            from_address="poc1@example.com",
            to=["agent@mail.local"],
            subject="Re: Request",
            has_attachments=False,
            attachment_count=0,
            received_at="2025-12-15T10:30:00Z",
        )
        await task_manager.handle_webhook(payload1)

        # Second (last) webhook - should trigger resume
        payload2 = WebhookPayload(
            event="email.received",
            email_id="email-2",
            from_address="poc2@example.com",
            to=["agent@mail.local"],
            subject="Re: Request",
            has_attachments=False,
            attachment_count=0,
            received_at="2025-12-15T10:31:00Z",
        )
        result2 = await task_manager.handle_webhook(payload2)
        assert result2 is True

        # Allow background task to run
        await asyncio.sleep(0.1)

        # Task should no longer be in suspended state
        task = await task_store.get_suspended_task_multi_poc("multi-resume-task")
        assert task is None

        # POCs should be removed from mapping
        assert task_manager.get_task_for_poc("poc1@example.com") is None
        assert task_manager.get_task_for_poc("poc2@example.com") is None

        await task_manager.stop()

    @pytest.mark.asyncio
    async def test_handle_webhook_multi_poc_stores_all_webhooks(self, task_manager, task_store):
        """Test that all webhook data is stored for resumption."""
        await task_manager.start()

        poc_emails = ["poc1@example.com", "poc2@example.com"]

        await task_manager.suspend_task_multi_poc(
            task_id="multi-store-task",
            poc_emails=poc_emails,
            thread_id="thread-store",
        )

        # First webhook with specific data
        payload1 = WebhookPayload(
            event="email.received",
            email_id="email-unique-1",
            from_address="poc1@example.com",
            to=["agent@mail.local"],
            subject="Re: Request from POC1",
            has_attachments=True,
            attachment_count=2,
            received_at="2025-12-15T10:30:00Z",
        )
        await task_manager.handle_webhook(payload1)

        # Check stored webhooks
        webhooks = await task_store.get_all_webhooks_for_task("multi-store-task")
        assert "poc1@example.com" in webhooks
        assert webhooks["poc1@example.com"]["email_id"] == "email-unique-1"
        assert webhooks["poc1@example.com"]["subject"] == "Re: Request from POC1"

        await task_manager.stop()

    @pytest.mark.asyncio
    async def test_handle_webhook_multi_poc_case_insensitive(self, task_manager, task_store):
        """Test that POC matching is case-insensitive."""
        await task_manager.start()

        # Register with lowercase
        await task_manager.suspend_task_multi_poc(
            task_id="multi-case-task",
            poc_emails=["poc@example.com"],
            thread_id="thread-case",
        )

        # Webhook comes with different case
        payload = WebhookPayload(
            event="email.received",
            email_id="email-case",
            from_address="POC@EXAMPLE.COM",  # Different case
            to=["agent@mail.local"],
            subject="Re: Request",
            has_attachments=False,
            attachment_count=0,
            received_at="2025-12-15T10:30:00Z",
        )

        result = await task_manager.handle_webhook(payload)
        assert result is True

        await task_manager.stop()


class TestMultiPocTaskStatus:
    """Tests for multi-POC task status queries."""

    @pytest.mark.asyncio
    async def test_get_status_for_multi_poc_suspended_task(self, task_manager):
        """Test getting status of a multi-POC suspended task."""
        await task_manager.start()

        poc_emails = ["poc1@example.com", "poc2@example.com", "poc3@example.com"]

        await task_manager.suspend_task_multi_poc(
            task_id="multi-status-task",
            poc_emails=poc_emails,
            thread_id="thread-status",
        )

        status = await task_manager.get_task_status("multi-status-task")

        assert status.task_id == "multi-status-task"
        assert status.state == TaskState.SUSPENDED
        # Should mention multiple POCs
        assert "3" in status.message or "POC" in status.message

        await task_manager.stop()

    @pytest.mark.asyncio
    async def test_get_status_shows_received_count(self, task_manager, task_store):
        """Test that status shows how many webhooks have been received."""
        await task_manager.start()

        poc_emails = ["poc1@example.com", "poc2@example.com", "poc3@example.com"]

        await task_manager.suspend_task_multi_poc(
            task_id="multi-count-task",
            poc_emails=poc_emails,
            thread_id="thread-count",
        )

        # Receive one webhook
        payload = WebhookPayload(
            event="email.received",
            email_id="email-count",
            from_address="poc1@example.com",
            to=["agent@mail.local"],
            subject="Re: Request",
            has_attachments=False,
            attachment_count=0,
            received_at="2025-12-15T10:30:00Z",
        )
        await task_manager.handle_webhook(payload)

        status = await task_manager.get_task_status("multi-count-task")

        # Should show progress (1 of 3)
        assert status.state == TaskState.SUSPENDED
        # Message should indicate partial progress
        assert "1" in status.message or "2" in status.message  # 1 received or 2 pending

        await task_manager.stop()


class TestMultiPocResumeData:
    """Tests for resume data construction in multi-POC mode."""

    @pytest.mark.asyncio
    async def test_resume_data_contains_all_webhooks(self, task_manager, task_store):
        """Test that resume data includes all collected webhooks."""
        await task_manager.start()

        # Use 3 POCs so we can receive 2 webhooks without triggering resume
        poc_emails = ["poc1@example.com", "poc2@example.com", "poc3@example.com"]

        await task_manager.suspend_task_multi_poc(
            task_id="multi-data-task",
            poc_emails=poc_emails,
            thread_id="thread-data",
        )

        # Receive webhooks from first 2 POCs (task stays suspended waiting for poc3)
        for i, poc in enumerate(poc_emails[:2]):
            payload = WebhookPayload(
                event="email.received",
                email_id=f"email-data-{i}",
                from_address=poc,
                to=["agent@mail.local"],
                subject=f"Re: Request from {poc}",
                has_attachments=False,
                attachment_count=0,
                received_at="2025-12-15T10:30:00Z",
            )
            await task_manager.handle_webhook(payload)

        # Check webhooks are stored (task still suspended, waiting for poc3)
        webhooks = await task_store.get_all_webhooks_for_task("multi-data-task")
        assert len(webhooks) == 2
        assert "poc1@example.com" in webhooks
        assert "poc2@example.com" in webhooks

        await task_manager.stop()


class TestMultiPocCleanup:
    """Tests for multi-POC task cleanup."""

    @pytest.mark.asyncio
    async def test_expired_multi_poc_task_cleanup(self, task_manager, task_store, mock_settings):
        """Test that expired multi-POC tasks are cleaned up."""
        # Set very short expiration for testing - MUST be set before start()
        # because _cleanup_loop reads interval at startup
        mock_settings.task_suspend_timeout_seconds = 1
        mock_settings.expired_task_cleanup_interval_seconds = 1

        await task_manager.start()

        poc_emails = ["poc1@example.com", "poc2@example.com"]

        await task_manager.suspend_task_multi_poc(
            task_id="multi-expire-task",
            poc_emails=poc_emails,
            thread_id="thread-expire",
        )

        # Wait for expiration and cleanup (1s timeout + 1s interval + generous buffer)
        # The cleanup loop checks every 1s, task expires after 1s, so ~3-4s should be enough
        await asyncio.sleep(4.0)

        # Task should be expired and cleaned up
        task = await task_store.get_suspended_task_multi_poc("multi-expire-task")
        assert task is None

        # POCs should be removed from mapping
        assert task_manager.get_task_for_poc("poc1@example.com") is None
        assert task_manager.get_task_for_poc("poc2@example.com") is None

        # Should have a failed result
        result = await task_store.get_result("multi-expire-task")
        assert result is not None
        assert result["status"] == "failed"
        assert "expired" in result["error"].lower()

        await task_manager.stop()


class TestListAllTasksMultiPoc:
    """Tests for list_all_tasks() including multi-POC suspended tasks."""

    @pytest.mark.asyncio
    async def test_list_all_tasks_includes_multi_poc_suspended(
        self, task_manager, task_store
    ):
        """Verify multi-POC suspended tasks appear in list_all_tasks()."""
        await task_manager.start()

        poc_emails = ["alice@example.com", "bob@example.com"]

        # Create a multi-POC suspended task
        await task_manager.suspend_task_multi_poc(
            task_id="multi-list-task-1",
            poc_emails=poc_emails,
            thread_id="thread-list-1",
        )

        # Call list_all_tasks()
        tasks = await task_manager.list_all_tasks()

        # Assert task is in returned list
        assert len(tasks) >= 1
        task_ids = [t.task_id for t in tasks]
        assert "multi-list-task-1" in task_ids

        # Find the task and verify properties
        multi_task = next(t for t in tasks if t.task_id == "multi-list-task-1")
        assert multi_task.state == TaskState.SUSPENDED
        assert "alice@example.com" in multi_task.poc_email
        assert "bob@example.com" in multi_task.poc_email
        assert "0/2" in multi_task.message  # Waiting for replies: 0/2 received

        await task_manager.stop()

    @pytest.mark.asyncio
    async def test_list_all_tasks_shows_partial_progress(
        self, task_manager, task_store
    ):
        """Verify progress message shows received/total count after partial webhook."""
        await task_manager.start()

        poc_emails = ["poc1@example.com", "poc2@example.com", "poc3@example.com"]

        # Create a multi-POC suspended task with 3 POCs
        await task_manager.suspend_task_multi_poc(
            task_id="multi-progress-task",
            poc_emails=poc_emails,
            thread_id="thread-progress",
        )

        # Record 1 webhook received (simulating 1 of 3 POCs replied)
        await task_store.record_webhook_received(
            task_id="multi-progress-task",
            poc_email="poc1@example.com",
            webhook_data={"email_id": "email-1", "from_address": "poc1@example.com"},
        )

        # Call list_all_tasks()
        tasks = await task_manager.list_all_tasks()

        # Find the task
        multi_task = next(t for t in tasks if t.task_id == "multi-progress-task")

        # Assert progress message shows 1/3 received
        assert multi_task.state == TaskState.SUSPENDED
        assert "1/3" in multi_task.message  # Waiting for replies: 1/3 received

        await task_manager.stop()

    @pytest.mark.asyncio
    async def test_list_all_tasks_includes_both_single_and_multi_poc(
        self, task_manager, task_store
    ):
        """Verify both single-POC and multi-POC suspended tasks appear."""
        await task_manager.start()

        # Create a single-POC suspended task (legacy mode)
        await task_manager.suspend_task(
            task_id="single-poc-task",
            poc_email="single@example.com",
            thread_id="thread-single",
        )

        # Create a multi-POC suspended task
        await task_manager.suspend_task_multi_poc(
            task_id="multi-poc-task",
            poc_emails=["multi1@example.com", "multi2@example.com"],
            thread_id="thread-multi",
        )

        # Call list_all_tasks()
        tasks = await task_manager.list_all_tasks()

        # Both tasks should be in the list
        task_ids = [t.task_id for t in tasks]
        assert "single-poc-task" in task_ids
        assert "multi-poc-task" in task_ids

        # Verify single-POC task
        single_task = next(t for t in tasks if t.task_id == "single-poc-task")
        assert single_task.state == TaskState.SUSPENDED
        assert "single@example.com" in single_task.poc_email

        # Verify multi-POC task
        multi_task = next(t for t in tasks if t.task_id == "multi-poc-task")
        assert multi_task.state == TaskState.SUSPENDED
        assert "multi1@example.com" in multi_task.poc_email
        assert "multi2@example.com" in multi_task.poc_email

        await task_manager.stop()


class TestResumingTasksVisibility:
    """Tests for task visibility during resumption (in-flight processing)."""

    @pytest.mark.asyncio
    async def test_resuming_task_visible_in_list_all_tasks(self, task_manager):
        """Test that resuming tasks appear in list_all_tasks."""
        await task_manager.start()

        # Manually add a task to _resuming_tasks (simulating in-flight processing)
        task_id = "test-resuming-task"
        async with task_manager._lock:
            task_manager._resuming_tasks[task_id] = {
                "task_id": task_id,
                "thread_id": "thread-123",
                "started_at": datetime.now(timezone.utc),
                "poc_emails": ["poc1@example.com", "poc2@example.com"],
                "state": "resuming",
            }

        # Call list_all_tasks()
        tasks = await task_manager.list_all_tasks()

        # Resuming task should be in the list
        task_ids = [t.task_id for t in tasks]
        assert task_id in task_ids

        # Verify resuming task details
        resuming_task = next(t for t in tasks if t.task_id == task_id)
        assert resuming_task.state == TaskState.WORKING
        assert "Processing replies from 2 POC(s)" in resuming_task.message
        assert "poc1@example.com" in resuming_task.poc_email
        assert "poc2@example.com" in resuming_task.poc_email

        await task_manager.stop()

    @pytest.mark.asyncio
    async def test_resuming_task_visible_in_get_task_status(self, task_manager):
        """Test that resuming tasks can be queried via get_task_status."""
        await task_manager.start()

        # Manually add a task to _resuming_tasks
        task_id = "test-resuming-status"
        started_at = datetime.now(timezone.utc)
        async with task_manager._lock:
            task_manager._resuming_tasks[task_id] = {
                "task_id": task_id,
                "thread_id": "thread-456",
                "started_at": started_at,
                "poc_emails": ["poc@example.com"],
                "state": "resuming",
            }

        # Call get_task_status()
        status = await task_manager.get_task_status(task_id)

        # Verify status
        assert status.task_id == task_id
        assert status.state == TaskState.WORKING
        assert "Processing replies from 1 POC(s)" in status.message
        assert status.created_at == started_at

        await task_manager.stop()

    @pytest.mark.asyncio
    async def test_resuming_task_not_found_after_removal(self, task_manager):
        """Test that task is not found after removal from _resuming_tasks."""
        await task_manager.start()

        task_id = "test-removed-task"

        # Add and then remove
        async with task_manager._lock:
            task_manager._resuming_tasks[task_id] = {
                "task_id": task_id,
                "thread_id": "thread-789",
                "started_at": datetime.now(timezone.utc),
                "poc_emails": ["poc@example.com"],
                "state": "resuming",
            }
            task_manager._resuming_tasks.pop(task_id, None)

        # Should raise TaskNotFoundError
        with pytest.raises(TaskNotFoundError):
            await task_manager.get_task_status(task_id)

        await task_manager.stop()

    @pytest.mark.asyncio
    async def test_single_poc_webhook_adds_to_resuming_tasks(
        self, task_manager, task_store
    ):
        """Test that single-POC webhook handling adds task to _resuming_tasks."""
        await task_manager.start()

        # Create a suspended task first
        task_id = "single-poc-webhook-task"
        poc_email = "poc@example.com"
        await task_manager.suspend_task(
            task_id=task_id,
            poc_email=poc_email,
            thread_id="thread-single-webhook",
        )

        # Mock the graph to return immediately without processing
        task_manager._graph.astream = AsyncMock(
            return_value=iter([{"final_node": {"final_summary": "done"}}])
        )

        # Create webhook payload
        payload = WebhookPayload(
            event="email.received",
            email_id="email-123",
            from_address=poc_email,
            to=["agent@example.com"],
            subject="Re: Test",
            received_at=datetime.now(timezone.utc).isoformat(),
        )

        # Handle webhook - this should add to _resuming_tasks before resuming
        result = await task_manager.handle_webhook(payload)
        assert result is True

        # Give background task a moment to start
        await asyncio.sleep(0.1)

        # Task should have been in _resuming_tasks during processing
        # (it may be removed already if processing was fast, so we just verify
        # the webhook was handled successfully)

        await task_manager.stop()

    @pytest.mark.asyncio
    async def test_multi_poc_all_webhooks_adds_to_resuming_tasks(
        self, task_manager, task_store
    ):
        """Test that multi-POC webhook handling adds task to _resuming_tasks when all POCs respond."""
        await task_manager.start()

        # Create a multi-POC suspended task
        task_id = "multi-poc-webhook-task"
        poc_emails = ["poc1@example.com", "poc2@example.com"]
        await task_manager.suspend_task_multi_poc(
            task_id=task_id,
            poc_emails=poc_emails,
            thread_id="thread-multi-webhook",
        )

        # Mock the graph to simulate slow processing
        async def slow_astream(*args, **kwargs):
            # Yield some events
            yield {"node1": {"data": "processing"}}
            await asyncio.sleep(0.2)  # Simulate slow processing
            yield {"final_node": {"final_summary": "done"}}

        task_manager._graph.astream = slow_astream

        # First webhook
        payload1 = WebhookPayload(
            event="email.received",
            email_id="email-1",
            from_address="poc1@example.com",
            to=["agent@example.com"],
            subject="Re: Test",
            received_at=datetime.now(timezone.utc).isoformat(),
        )
        await task_manager.handle_webhook(payload1)

        # Task should still be suspended (waiting for POC2)
        async with task_manager._lock:
            assert task_id not in task_manager._resuming_tasks

        # Second webhook - all POCs responded
        payload2 = WebhookPayload(
            event="email.received",
            email_id="email-2",
            from_address="poc2@example.com",
            to=["agent@example.com"],
            subject="Re: Test",
            received_at=datetime.now(timezone.utc).isoformat(),
        )
        await task_manager.handle_webhook(payload2)

        # Give background task a moment to be added to _resuming_tasks
        await asyncio.sleep(0.05)

        # Task should be in _resuming_tasks during processing
        async with task_manager._lock:
            assert task_id in task_manager._resuming_tasks
            info = task_manager._resuming_tasks[task_id]
            assert info["poc_emails"] == poc_emails
            assert info["state"] == "resuming"

        # Wait for processing to complete
        await asyncio.sleep(0.3)

        # Task should be removed from _resuming_tasks after completion
        async with task_manager._lock:
            assert task_id not in task_manager._resuming_tasks

        await task_manager.stop()


class TestProgressServiceIntegration:
    """Tests for ProgressService integration with TaskManager."""

    @pytest.mark.asyncio
    async def test_set_progress_service(self, task_manager):
        """Test that set_progress_service attaches the service."""
        from mail_agent.a2a.progress_service import ProgressService
        from mail_agent.a2a.progress_store import ProgressStore

        await task_manager.start()

        # Initially no progress service
        assert task_manager._progress_service is None

        # Create a mock progress service
        mock_progress_service = MagicMock(spec=ProgressService)

        # Attach it
        task_manager.set_progress_service(mock_progress_service)

        assert task_manager._progress_service is mock_progress_service

        await task_manager.stop()

    @pytest.mark.asyncio
    async def test_webhook_multi_poc_emits_webhook_received_event(
        self, task_manager, task_store
    ):
        """Test that webhook handling emits webhook_received event via ProgressService."""
        await task_manager.start()

        # Create mock progress service
        mock_progress_service = MagicMock()
        mock_progress_service.emit_webhook_received = AsyncMock()
        task_manager.set_progress_service(mock_progress_service)

        # Suspend multi-POC task
        poc_emails = ["poc1@example.com", "poc2@example.com", "poc3@example.com"]
        await task_manager.suspend_task_multi_poc(
            task_id="progress-multi-task",
            poc_emails=poc_emails,
            thread_id="thread-progress",
        )

        # First webhook arrives
        payload1 = WebhookPayload(
            event="email.received",
            email_id="email-progress-1",
            from_address="poc1@example.com",
            to=["agent@mail.local"],
            subject="Re: Request",
            has_attachments=False,
            attachment_count=0,
            received_at="2025-12-15T10:30:00Z",
        )
        await task_manager.handle_webhook(payload1)

        # Verify emit_webhook_received was called
        mock_progress_service.emit_webhook_received.assert_called_once_with(
            task_id="progress-multi-task",
            poc_email="poc1@example.com",
            received_count=1,
            total_count=3,
        )

        await task_manager.stop()

    @pytest.mark.asyncio
    async def test_webhook_multi_poc_emits_multiple_webhook_received_events(
        self, task_manager, task_store
    ):
        """Test that each webhook arrival emits a webhook_received event."""
        await task_manager.start()

        # Create mock progress service
        mock_progress_service = MagicMock()
        mock_progress_service.emit_webhook_received = AsyncMock()
        mock_progress_service.emit_all_webhooks_received = AsyncMock()
        mock_progress_service.emit_task_resumed = AsyncMock()
        task_manager.set_progress_service(mock_progress_service)

        # Suspend multi-POC task
        poc_emails = ["poc1@example.com", "poc2@example.com"]
        await task_manager.suspend_task_multi_poc(
            task_id="progress-multi-task-2",
            poc_emails=poc_emails,
            thread_id="thread-progress-2",
        )

        # Mock graph to avoid actual execution
        task_manager._graph.astream = AsyncMock(
            return_value=iter([{"final_node": {"success": True}}])
        )

        # First webhook
        payload1 = WebhookPayload(
            event="email.received",
            email_id="email-p1",
            from_address="poc1@example.com",
            to=["agent@mail.local"],
            subject="Re: Request",
            has_attachments=False,
            attachment_count=0,
            received_at="2025-12-15T10:30:00Z",
        )
        await task_manager.handle_webhook(payload1)

        # Second webhook (last one)
        payload2 = WebhookPayload(
            event="email.received",
            email_id="email-p2",
            from_address="poc2@example.com",
            to=["agent@mail.local"],
            subject="Re: Request",
            has_attachments=False,
            attachment_count=0,
            received_at="2025-12-15T10:31:00Z",
        )
        await task_manager.handle_webhook(payload2)

        # Wait for background task
        await asyncio.sleep(0.1)

        # Verify emit_webhook_received was called twice (once per POC)
        assert mock_progress_service.emit_webhook_received.call_count == 2

        # Check first call arguments
        first_call = mock_progress_service.emit_webhook_received.call_args_list[0]
        assert first_call.kwargs["task_id"] == "progress-multi-task-2"
        assert first_call.kwargs["poc_email"] == "poc1@example.com"
        assert first_call.kwargs["received_count"] == 1
        assert first_call.kwargs["total_count"] == 2

        # Check second call arguments
        second_call = mock_progress_service.emit_webhook_received.call_args_list[1]
        assert second_call.kwargs["task_id"] == "progress-multi-task-2"
        assert second_call.kwargs["poc_email"] == "poc2@example.com"
        assert second_call.kwargs["received_count"] == 2
        assert second_call.kwargs["total_count"] == 2

        await task_manager.stop()

    @pytest.mark.asyncio
    async def test_all_webhooks_received_emits_event(self, task_manager, task_store):
        """Test that emit_all_webhooks_received is called when all POCs respond."""
        await task_manager.start()

        # Create mock progress service
        mock_progress_service = MagicMock()
        mock_progress_service.emit_webhook_received = AsyncMock()
        mock_progress_service.emit_all_webhooks_received = AsyncMock()
        mock_progress_service.emit_task_resumed = AsyncMock()
        task_manager.set_progress_service(mock_progress_service)

        # Suspend multi-POC task
        poc_emails = ["poc1@example.com", "poc2@example.com"]
        await task_manager.suspend_task_multi_poc(
            task_id="all-webhooks-task",
            poc_emails=poc_emails,
            thread_id="thread-all",
        )

        # Mock graph
        task_manager._graph.astream = AsyncMock(
            return_value=iter([{"final_node": {"success": True}}])
        )

        # First webhook
        payload1 = WebhookPayload(
            event="email.received",
            email_id="email-all-1",
            from_address="poc1@example.com",
            to=["agent@mail.local"],
            subject="Re: Request",
            has_attachments=False,
            attachment_count=0,
            received_at="2025-12-15T10:30:00Z",
        )
        await task_manager.handle_webhook(payload1)

        # emit_all_webhooks_received should NOT be called yet
        mock_progress_service.emit_all_webhooks_received.assert_not_called()

        # Second webhook (last one)
        payload2 = WebhookPayload(
            event="email.received",
            email_id="email-all-2",
            from_address="poc2@example.com",
            to=["agent@mail.local"],
            subject="Re: Request",
            has_attachments=False,
            attachment_count=0,
            received_at="2025-12-15T10:31:00Z",
        )
        await task_manager.handle_webhook(payload2)

        # Wait for background task
        await asyncio.sleep(0.1)

        # emit_all_webhooks_received should be called now
        mock_progress_service.emit_all_webhooks_received.assert_called_once_with(
            task_id="all-webhooks-task",
            poc_emails=poc_emails,
        )

        await task_manager.stop()

    @pytest.mark.asyncio
    async def test_task_resumed_event_emitted_multi_poc(self, task_manager, task_store):
        """Test that emit_task_resumed is called when resuming multi-POC task."""
        await task_manager.start()

        # Create mock progress service
        mock_progress_service = MagicMock()
        mock_progress_service.emit_webhook_received = AsyncMock()
        mock_progress_service.emit_all_webhooks_received = AsyncMock()
        mock_progress_service.emit_task_resumed = AsyncMock()
        task_manager.set_progress_service(mock_progress_service)

        # Suspend multi-POC task
        poc_emails = ["poc1@example.com", "poc2@example.com"]
        await task_manager.suspend_task_multi_poc(
            task_id="resumed-task-multi",
            poc_emails=poc_emails,
            thread_id="thread-resumed",
        )

        # Mock graph
        task_manager._graph.astream = AsyncMock(
            return_value=iter([{"final_node": {"success": True}}])
        )

        # First and second webhook to trigger resume
        for i, poc in enumerate(poc_emails):
            payload = WebhookPayload(
                event="email.received",
                email_id=f"email-resume-{i}",
                from_address=poc,
                to=["agent@mail.local"],
                subject="Re: Request",
                has_attachments=False,
                attachment_count=0,
                received_at="2025-12-15T10:30:00Z",
            )
            await task_manager.handle_webhook(payload)

        # Wait for background task
        await asyncio.sleep(0.1)

        # emit_task_resumed should be called with poc_emails list
        mock_progress_service.emit_task_resumed.assert_called_once_with(
            task_id="resumed-task-multi",
            poc_emails=poc_emails,
        )

        await task_manager.stop()

    @pytest.mark.asyncio
    async def test_single_poc_webhook_emits_webhook_received_event(
        self, task_manager, task_store
    ):
        """Test that single-POC webhook handling emits webhook_received event."""
        await task_manager.start()

        # Create mock progress service
        mock_progress_service = MagicMock()
        mock_progress_service.emit_webhook_received = AsyncMock()
        mock_progress_service.emit_task_resumed = AsyncMock()
        task_manager.set_progress_service(mock_progress_service)

        # Suspend single-POC task
        await task_manager.suspend_task(
            task_id="progress-single-task",
            poc_email="single-poc@example.com",
            thread_id="thread-single-progress",
        )

        # Mock graph
        task_manager._graph.astream = AsyncMock(
            return_value=iter([{"final_node": {"success": True}}])
        )

        # Webhook arrives
        payload = WebhookPayload(
            event="email.received",
            email_id="email-single-progress",
            from_address="single-poc@example.com",
            to=["agent@mail.local"],
            subject="Re: Request",
            has_attachments=False,
            attachment_count=0,
            received_at="2025-12-15T10:30:00Z",
        )
        await task_manager.handle_webhook(payload)

        # Wait for background task
        await asyncio.sleep(0.1)

        # Verify emit_webhook_received was called
        mock_progress_service.emit_webhook_received.assert_called_once_with(
            task_id="progress-single-task",
            poc_email="single-poc@example.com",
            received_count=1,
            total_count=1,
        )

        await task_manager.stop()

    @pytest.mark.asyncio
    async def test_single_poc_task_resumed_event_emitted(
        self, task_manager, task_store
    ):
        """Test that emit_task_resumed is called when resuming single-POC task."""
        await task_manager.start()

        # Create mock progress service
        mock_progress_service = MagicMock()
        mock_progress_service.emit_webhook_received = AsyncMock()
        mock_progress_service.emit_task_resumed = AsyncMock()
        task_manager.set_progress_service(mock_progress_service)

        # Suspend single-POC task
        await task_manager.suspend_task(
            task_id="resumed-task-single",
            poc_email="resume-poc@example.com",
            thread_id="thread-resumed-single",
        )

        # Mock graph
        task_manager._graph.astream = AsyncMock(
            return_value=iter([{"final_node": {"success": True}}])
        )

        # Webhook arrives
        payload = WebhookPayload(
            event="email.received",
            email_id="email-resumed-single",
            from_address="resume-poc@example.com",
            to=["agent@mail.local"],
            subject="Re: Request",
            has_attachments=False,
            attachment_count=0,
            received_at="2025-12-15T10:30:00Z",
        )
        await task_manager.handle_webhook(payload)

        # Wait for background task
        await asyncio.sleep(0.1)

        # emit_task_resumed should be called with poc_emails list
        mock_progress_service.emit_task_resumed.assert_called_once_with(
            task_id="resumed-task-single",
            poc_emails=["resume-poc@example.com"],
        )

        await task_manager.stop()

    @pytest.mark.asyncio
    async def test_no_event_emitted_without_progress_service(
        self, task_manager, task_store
    ):
        """Test that no error occurs when progress_service is not set."""
        await task_manager.start()

        # Don't set progress service - should be None
        assert task_manager._progress_service is None

        # Suspend multi-POC task
        poc_emails = ["poc1@example.com", "poc2@example.com"]
        await task_manager.suspend_task_multi_poc(
            task_id="no-service-task",
            poc_emails=poc_emails,
            thread_id="thread-no-service",
        )

        # Mock graph
        task_manager._graph.astream = AsyncMock(
            return_value=iter([{"final_node": {"success": True}}])
        )

        # Webhooks should work without errors even without progress service
        for i, poc in enumerate(poc_emails):
            payload = WebhookPayload(
                event="email.received",
                email_id=f"email-no-service-{i}",
                from_address=poc,
                to=["agent@mail.local"],
                subject="Re: Request",
                has_attachments=False,
                attachment_count=0,
                received_at="2025-12-15T10:30:00Z",
            )
            result = await task_manager.handle_webhook(payload)
            assert result is True

        await asyncio.sleep(0.1)

        await task_manager.stop()

    @pytest.mark.asyncio
    async def test_resume_task_emits_node_progress_events(
        self, task_manager, task_store
    ):
        """Test that resumed task execution emits progress events for each node."""
        await task_manager.start()

        # Create mock progress service
        mock_progress_service = MagicMock()
        mock_progress_service.emit_webhook_received = AsyncMock()
        mock_progress_service.emit_task_resumed = AsyncMock()
        mock_progress_service.emit_event = AsyncMock()
        task_manager.set_progress_service(mock_progress_service)

        # Suspend single-POC task
        await task_manager.suspend_task(
            task_id="node-events-task",
            poc_email="node-poc@example.com",
            thread_id="thread-node-events",
        )

        # Mock graph to return multiple node events
        async def mock_astream(*args, **kwargs):
            # Simulate multiple nodes executing during resume
            yield {"fetch_email": {"progress_messages": ["Fetching email from POC"]}}
            yield {"extract_content": {"progress_messages": ["Extracting CSV content"]}}
            yield {"validate_response": {"progress_messages": ["Validating response"]}}
            yield {"end": {"final_summary": "Task completed successfully"}}

        task_manager._graph.astream = mock_astream

        # Webhook arrives
        payload = WebhookPayload(
            event="email.received",
            email_id="email-node-events",
            from_address="node-poc@example.com",
            to=["agent@mail.local"],
            subject="Re: Request",
            has_attachments=False,
            attachment_count=0,
            received_at="2025-12-15T10:30:00Z",
        )
        await task_manager.handle_webhook(payload)

        # Wait for background task
        await asyncio.sleep(0.2)

        # Verify emit_event was called for each node (4 nodes + 1 final)
        # The final completed event is also emitted
        assert mock_progress_service.emit_event.call_count >= 4

        # Check that node names appear in the emit_event calls
        call_nodes = [
            call.kwargs.get("node")
            for call in mock_progress_service.emit_event.call_args_list
        ]
        assert "fetch_email" in call_nodes
        assert "extract_content" in call_nodes
        assert "validate_response" in call_nodes

        await task_manager.stop()

    @pytest.mark.asyncio
    async def test_resume_task_multi_poc_emits_node_progress_events(
        self, task_manager, task_store
    ):
        """Test that resumed multi-POC task execution emits progress events."""
        await task_manager.start()

        # Create mock progress service
        mock_progress_service = MagicMock()
        mock_progress_service.emit_webhook_received = AsyncMock()
        mock_progress_service.emit_all_webhooks_received = AsyncMock()
        mock_progress_service.emit_task_resumed = AsyncMock()
        mock_progress_service.emit_event = AsyncMock()
        task_manager.set_progress_service(mock_progress_service)

        # Suspend multi-POC task
        poc_emails = ["poc1@example.com", "poc2@example.com"]
        await task_manager.suspend_task_multi_poc(
            task_id="multi-node-events-task",
            poc_emails=poc_emails,
            thread_id="thread-multi-node",
        )

        # Mock graph to return multiple node events
        async def mock_astream(*args, **kwargs):
            yield {"process_all_replies": {"progress_messages": ["Processing all replies"]}}
            yield {"validate_cross_poc": {"progress_messages": ["Cross-POC validation passed"]}}
            yield {"compose_success_all": {"progress_messages": ["Composing success emails"]}}
            yield {"send_success_all": {"progress_messages": ["Sent acknowledgments"]}}
            yield {"end": {"final_summary": "Task completed for 2 POCs"}}

        task_manager._graph.astream = mock_astream

        # Both webhooks arrive
        for i, poc in enumerate(poc_emails):
            payload = WebhookPayload(
                event="email.received",
                email_id=f"email-multi-node-{i}",
                from_address=poc,
                to=["agent@mail.local"],
                subject="Re: Request",
                has_attachments=False,
                attachment_count=0,
                received_at="2025-12-15T10:30:00Z",
            )
            await task_manager.handle_webhook(payload)

        # Wait for background task
        await asyncio.sleep(0.2)

        # Verify emit_event was called for each node
        assert mock_progress_service.emit_event.call_count >= 4

        # Check that node names appear in the emit_event calls
        call_nodes = [
            call.kwargs.get("node")
            for call in mock_progress_service.emit_event.call_args_list
        ]
        assert "process_all_replies" in call_nodes
        assert "validate_cross_poc" in call_nodes
        assert "compose_success_all" in call_nodes

        await task_manager.stop()

    @pytest.mark.asyncio
    async def test_resume_task_emits_final_completed_event(
        self, task_manager, task_store
    ):
        """Test that resumed task emits a final completed event with result."""
        await task_manager.start()

        # Create mock progress service
        mock_progress_service = MagicMock()
        mock_progress_service.emit_webhook_received = AsyncMock()
        mock_progress_service.emit_task_resumed = AsyncMock()
        mock_progress_service.emit_event = AsyncMock()
        task_manager.set_progress_service(mock_progress_service)

        # Suspend single-POC task
        await task_manager.suspend_task(
            task_id="final-event-task",
            poc_email="final-poc@example.com",
            thread_id="thread-final-event",
        )

        # Mock graph
        async def mock_astream(*args, **kwargs):
            yield {"end": {"final_summary": "Successfully processed data"}}

        task_manager._graph.astream = mock_astream

        # Webhook arrives
        payload = WebhookPayload(
            event="email.received",
            email_id="email-final-event",
            from_address="final-poc@example.com",
            to=["agent@mail.local"],
            subject="Re: Request",
            has_attachments=False,
            attachment_count=0,
            received_at="2025-12-15T10:30:00Z",
        )
        await task_manager.handle_webhook(payload)

        # Wait for background task
        await asyncio.sleep(0.2)

        # Find the final completed event
        final_event_calls = [
            call for call in mock_progress_service.emit_event.call_args_list
            if call.kwargs.get("node") == "end"
        ]
        assert len(final_event_calls) >= 1

        # Verify the final event has COMPLETED state
        from mail_agent.task_manager.models import TaskState
        final_call = final_event_calls[-1]
        assert final_call.kwargs.get("state") == TaskState.COMPLETED
        assert "Successfully processed data" in final_call.kwargs.get("message", "")

        await task_manager.stop()

    @pytest.mark.asyncio
    async def test_resume_task_emits_failed_event_on_error(
        self, task_manager, task_store
    ):
        """Test that resumed task emits a failed event when graph fails."""
        await task_manager.start()

        # Create mock progress service
        mock_progress_service = MagicMock()
        mock_progress_service.emit_webhook_received = AsyncMock()
        mock_progress_service.emit_task_resumed = AsyncMock()
        mock_progress_service.emit_event = AsyncMock()
        task_manager.set_progress_service(mock_progress_service)

        # Suspend single-POC task
        await task_manager.suspend_task(
            task_id="error-event-task",
            poc_email="error-poc@example.com",
            thread_id="thread-error-event",
        )

        # Mock graph to raise exception
        async def mock_astream_error(*args, **kwargs):
            raise RuntimeError("Graph execution failed")

        task_manager._graph.astream = mock_astream_error

        # Webhook arrives
        payload = WebhookPayload(
            event="email.received",
            email_id="email-error-event",
            from_address="error-poc@example.com",
            to=["agent@mail.local"],
            subject="Re: Request",
            has_attachments=False,
            attachment_count=0,
            received_at="2025-12-15T10:30:00Z",
        )
        await task_manager.handle_webhook(payload)

        # Wait for background task
        await asyncio.sleep(0.2)

        # Find the failed event
        failed_event_calls = [
            call for call in mock_progress_service.emit_event.call_args_list
            if call.kwargs.get("node") == "end"
        ]
        assert len(failed_event_calls) >= 1

        # Verify the final event has FAILED state
        from mail_agent.task_manager.models import TaskState
        final_call = failed_event_calls[-1]
        assert final_call.kwargs.get("state") == TaskState.FAILED
        assert final_call.kwargs.get("error") is not None

        await task_manager.stop()
