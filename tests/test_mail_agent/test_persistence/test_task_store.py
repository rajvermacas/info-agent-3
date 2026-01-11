"""
Tests for TaskStore - CRUD operations for suspended tasks and results.
"""

import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mail_agent.persistence.database import DatabaseManager
from mail_agent.persistence.task_store import (
    TaskStore,
    TaskStoreError,
    TaskNotFoundError,
    DuplicateTaskError,
    DuplicatePOCError,
)


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


class TestTaskStoreInit:
    """Tests for TaskStore initialization."""

    def test_init_with_db_manager(self, db_manager):
        """Test initialization with database manager."""
        store = TaskStore(db_manager)
        assert store is not None

    def test_init_without_db_manager_raises(self):
        """Test that initialization without db_manager raises."""
        with pytest.raises(ValueError, match="db_manager cannot be None"):
            TaskStore(None)


class TestSuspendTask:
    """Tests for suspend_task operation."""

    @pytest.mark.asyncio
    async def test_suspend_task_creates_record(self, task_store):
        """Test that suspend_task creates a suspended task record."""
        await task_store.suspend_task(
            task_id="task-123",
            poc_email="poc@example.com",
            thread_id="thread-123",
            timeout_seconds=3600,
            interrupt_data={"reason": "waiting"},
        )

        task = await task_store.get_suspended_task("task-123")
        assert task is not None
        assert task["task_id"] == "task-123"
        assert task["poc_email"] == "poc@example.com"
        assert task["thread_id"] == "thread-123"
        assert task["interrupt_data"] == {"reason": "waiting"}

    @pytest.mark.asyncio
    async def test_suspend_task_normalizes_email(self, task_store):
        """Test that suspend_task normalizes email to lowercase."""
        await task_store.suspend_task(
            task_id="task-123",
            poc_email="POC@EXAMPLE.COM",
            thread_id="thread-123",
            timeout_seconds=3600,
        )

        task = await task_store.get_suspended_task("task-123")
        assert task["poc_email"] == "poc@example.com"

    @pytest.mark.asyncio
    async def test_suspend_task_sets_expiration(self, task_store):
        """Test that suspend_task sets correct expiration time."""
        await task_store.suspend_task(
            task_id="task-123",
            poc_email="poc@example.com",
            thread_id="thread-123",
            timeout_seconds=3600,
        )

        task = await task_store.get_suspended_task("task-123")
        created_at = datetime.fromisoformat(task["created_at"])
        expires_at = datetime.fromisoformat(task["expires_at"])

        # Expiration should be roughly 1 hour after creation
        delta = expires_at - created_at
        assert 3590 < delta.total_seconds() < 3610

    @pytest.mark.asyncio
    async def test_suspend_duplicate_task_raises(self, task_store):
        """Test that suspending a duplicate task_id raises."""
        await task_store.suspend_task(
            task_id="task-123",
            poc_email="poc1@example.com",
            thread_id="thread-123",
            timeout_seconds=3600,
        )

        with pytest.raises(DuplicateTaskError):
            await task_store.suspend_task(
                task_id="task-123",
                poc_email="poc2@example.com",
                thread_id="thread-456",
                timeout_seconds=3600,
            )

    @pytest.mark.asyncio
    async def test_suspend_duplicate_poc_raises(self, task_store):
        """Test that suspending for a POC that already has a task raises."""
        await task_store.suspend_task(
            task_id="task-123",
            poc_email="poc@example.com",
            thread_id="thread-123",
            timeout_seconds=3600,
        )

        with pytest.raises(DuplicatePOCError):
            await task_store.suspend_task(
                task_id="task-456",
                poc_email="poc@example.com",
                thread_id="thread-456",
                timeout_seconds=3600,
            )


class TestGetSuspendedTask:
    """Tests for get_suspended_task operation."""

    @pytest.mark.asyncio
    async def test_get_suspended_task_returns_task(self, task_store):
        """Test that get_suspended_task returns the correct task."""
        await task_store.suspend_task(
            task_id="task-123",
            poc_email="poc@example.com",
            thread_id="thread-123",
            timeout_seconds=3600,
        )

        task = await task_store.get_suspended_task("task-123")
        assert task is not None
        assert task["task_id"] == "task-123"

    @pytest.mark.asyncio
    async def test_get_suspended_task_returns_none_for_missing(self, task_store):
        """Test that get_suspended_task returns None for missing task."""
        task = await task_store.get_suspended_task("nonexistent")
        assert task is None


class TestGetTaskByPOC:
    """Tests for get_task_by_poc operation."""

    @pytest.mark.asyncio
    async def test_get_task_by_poc_returns_task(self, task_store):
        """Test that get_task_by_poc returns the correct task."""
        await task_store.suspend_task(
            task_id="task-123",
            poc_email="poc@example.com",
            thread_id="thread-123",
            timeout_seconds=3600,
        )

        task = await task_store.get_task_by_poc("poc@example.com")
        assert task is not None
        assert task["task_id"] == "task-123"

    @pytest.mark.asyncio
    async def test_get_task_by_poc_case_insensitive(self, task_store):
        """Test that get_task_by_poc is case insensitive."""
        await task_store.suspend_task(
            task_id="task-123",
            poc_email="poc@example.com",
            thread_id="thread-123",
            timeout_seconds=3600,
        )

        task = await task_store.get_task_by_poc("POC@EXAMPLE.COM")
        assert task is not None
        assert task["task_id"] == "task-123"

    @pytest.mark.asyncio
    async def test_get_task_by_poc_returns_none_for_missing(self, task_store):
        """Test that get_task_by_poc returns None for missing POC."""
        task = await task_store.get_task_by_poc("nonexistent@example.com")
        assert task is None


class TestRemoveSuspendedTask:
    """Tests for remove_suspended_task operation."""

    @pytest.mark.asyncio
    async def test_remove_suspended_task_deletes_record(self, task_store):
        """Test that remove_suspended_task deletes the record."""
        await task_store.suspend_task(
            task_id="task-123",
            poc_email="poc@example.com",
            thread_id="thread-123",
            timeout_seconds=3600,
        )

        removed = await task_store.remove_suspended_task("task-123")
        assert removed is True

        task = await task_store.get_suspended_task("task-123")
        assert task is None

    @pytest.mark.asyncio
    async def test_remove_suspended_task_returns_false_for_missing(self, task_store):
        """Test that remove_suspended_task returns False for missing task."""
        removed = await task_store.remove_suspended_task("nonexistent")
        assert removed is False


class TestGetExpiredTasks:
    """Tests for get_expired_tasks operation."""

    @pytest.mark.asyncio
    async def test_get_expired_tasks_returns_expired(self, task_store, db_manager):
        """Test that get_expired_tasks returns expired tasks."""
        # Insert a task that's already expired
        past_time = datetime.now(timezone.utc) - timedelta(hours=1)
        await db_manager.execute(
            """
            INSERT INTO suspended_tasks
                (task_id, poc_email, thread_id, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "expired-task",
                "poc@example.com",
                "thread-123",
                (past_time - timedelta(hours=1)).isoformat(),
                past_time.isoformat(),
            ),
        )
        await db_manager.commit()

        expired = await task_store.get_expired_tasks()
        assert len(expired) == 1
        assert expired[0]["task_id"] == "expired-task"

    @pytest.mark.asyncio
    async def test_get_expired_tasks_excludes_active(self, task_store):
        """Test that get_expired_tasks excludes active tasks."""
        await task_store.suspend_task(
            task_id="active-task",
            poc_email="poc@example.com",
            thread_id="thread-123",
            timeout_seconds=3600,  # 1 hour in future
        )

        expired = await task_store.get_expired_tasks()
        assert len(expired) == 0


class TestGetAllSuspendedTasks:
    """Tests for get_all_suspended_tasks operation."""

    @pytest.mark.asyncio
    async def test_get_all_suspended_tasks_returns_all(self, task_store):
        """Test that get_all_suspended_tasks returns all suspended tasks."""
        for i in range(3):
            await task_store.suspend_task(
                task_id=f"task-{i}",
                poc_email=f"poc{i}@example.com",
                thread_id=f"thread-{i}",
                timeout_seconds=3600,
            )

        tasks = await task_store.get_all_suspended_tasks()
        assert len(tasks) == 3


class TestSaveResult:
    """Tests for save_result operation."""

    @pytest.mark.asyncio
    async def test_save_result_creates_record(self, task_store):
        """Test that save_result creates a result record."""
        await task_store.save_result(
            task_id="task-123",
            status="completed",
            result={"data": "test"},
        )

        result = await task_store.get_result("task-123")
        assert result is not None
        assert result["task_id"] == "task-123"
        assert result["status"] == "completed"
        assert result["result"] == {"data": "test"}

    @pytest.mark.asyncio
    async def test_save_result_with_error(self, task_store):
        """Test that save_result stores error message."""
        await task_store.save_result(
            task_id="task-123",
            status="failed",
            error="Something went wrong",
        )

        result = await task_store.get_result("task-123")
        assert result is not None
        assert result["status"] == "failed"
        assert result["error"] == "Something went wrong"

    @pytest.mark.asyncio
    async def test_save_result_replaces_existing(self, task_store):
        """Test that save_result replaces existing result."""
        await task_store.save_result(
            task_id="task-123",
            status="failed",
            error="First error",
        )
        await task_store.save_result(
            task_id="task-123",
            status="completed",
            result={"data": "success"},
        )

        result = await task_store.get_result("task-123")
        assert result["status"] == "completed"
        assert result["result"] == {"data": "success"}


class TestGetResult:
    """Tests for get_result operation."""

    @pytest.mark.asyncio
    async def test_get_result_returns_result(self, task_store):
        """Test that get_result returns the result."""
        await task_store.save_result(
            task_id="task-123",
            status="completed",
            result={"data": "test"},
        )

        result = await task_store.get_result("task-123")
        assert result is not None
        assert result["task_id"] == "task-123"

    @pytest.mark.asyncio
    async def test_get_result_returns_none_for_missing(self, task_store):
        """Test that get_result returns None for missing result."""
        result = await task_store.get_result("nonexistent")
        assert result is None


class TestDeleteResult:
    """Tests for delete_result operation."""

    @pytest.mark.asyncio
    async def test_delete_result_removes_record(self, task_store):
        """Test that delete_result removes the record."""
        await task_store.save_result(
            task_id="task-123",
            status="completed",
        )

        deleted = await task_store.delete_result("task-123")
        assert deleted is True

        result = await task_store.get_result("task-123")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_result_returns_false_for_missing(self, task_store):
        """Test that delete_result returns False for missing result."""
        deleted = await task_store.delete_result("nonexistent")
        assert deleted is False
