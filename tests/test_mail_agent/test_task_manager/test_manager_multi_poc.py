"""
Tests for multi-POC TaskManager functionality.

Tests the enhanced TaskManager for multi-POC orchestration:
- Multi-POC suspension/resumption
- POC-specific webhook routing
- Task-to-POC mappings
"""

import asyncio
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from mail_agent.task_manager.manager import (
    TaskManager,
    TaskManagerError,
    TaskNotFoundError,
)
from mail_agent.task_manager.models import WebhookPayload


@pytest.fixture
def mock_db_manager():
    """Create a mock database manager."""
    return MagicMock()


@pytest.fixture
def mock_task_store():
    """Create a mock task store."""
    store = AsyncMock()
    store.get_all_suspended_tasks.return_value = []
    store.suspend_task.return_value = None
    store.get_suspended_task.return_value = None
    store.remove_suspended_task.return_value = None
    store.save_result.return_value = None
    return store


@pytest.fixture
def mock_checkpointer():
    """Create a mock checkpointer."""
    return MagicMock()


@pytest.fixture
def mock_graph():
    """Create a mock LangGraph state machine."""
    graph = MagicMock()
    graph.astream = AsyncMock(return_value=AsyncMock(__aiter__=lambda self: iter([])))
    return graph


@pytest.fixture
def mock_settings():
    """Create mock settings."""
    settings = MagicMock()
    settings.task_suspend_timeout_seconds = 3600
    settings.expired_task_cleanup_interval_seconds = 300
    return settings


@pytest.fixture
async def task_manager(
    mock_db_manager,
    mock_task_store,
    mock_checkpointer,
    mock_graph,
    mock_settings,
):
    """Create a TaskManager instance for testing."""
    manager = TaskManager(
        db_manager=mock_db_manager,
        task_store=mock_task_store,
        checkpointer=mock_checkpointer,
        graph=mock_graph,
        settings=mock_settings,
    )
    return manager


class TestMultiPOCSuspension:
    """Tests for multi-POC suspension functionality."""

    @pytest.mark.asyncio
    async def test_suspend_task_with_poc_id(self, task_manager, mock_task_store):
        """Test suspending a task with POC ID for multi-POC mode."""
        task_id = "task_123"
        poc_email = "poc1@test.com"
        poc_id = "poc_001"
        thread_id = "thread_123"

        await task_manager.suspend_task(
            task_id=task_id,
            poc_email=poc_email,
            thread_id=thread_id,
            poc_id=poc_id,
        )

        # Verify task store was called with poc_id in interrupt_data
        mock_task_store.suspend_task.assert_called_once()
        call_args = mock_task_store.suspend_task.call_args
        assert call_args.kwargs["interrupt_data"]["poc_id"] == poc_id

        # Verify multi-POC mappings
        assert task_manager._poc_to_task_poc["poc1@test.com"] == (task_id, poc_id)
        assert poc_id in task_manager._task_pocs[task_id]

    @pytest.mark.asyncio
    async def test_suspend_multiple_pocs_for_same_task(
        self, task_manager, mock_task_store
    ):
        """Test suspending multiple POCs for the same task."""
        task_id = "task_123"
        thread_id = "thread_123"

        # Suspend first POC
        await task_manager.suspend_task(
            task_id=task_id,
            poc_email="poc1@test.com",
            thread_id=thread_id,
            poc_id="poc_001",
        )

        # Suspend second POC
        await task_manager.suspend_task(
            task_id=task_id,
            poc_email="poc2@test.com",
            thread_id=thread_id,
            poc_id="poc_002",
        )

        # Verify both POCs are tracked
        assert task_manager._poc_to_task_poc["poc1@test.com"] == (task_id, "poc_001")
        assert task_manager._poc_to_task_poc["poc2@test.com"] == (task_id, "poc_002")
        assert task_manager._task_pocs[task_id] == {"poc_001", "poc_002"}

    @pytest.mark.asyncio
    async def test_suspend_fails_for_duplicate_poc_email(
        self, task_manager, mock_task_store
    ):
        """Test that suspending duplicate POC email raises error."""
        task_id = "task_123"
        thread_id = "thread_123"

        # Suspend first POC
        await task_manager.suspend_task(
            task_id=task_id,
            poc_email="poc1@test.com",
            thread_id=thread_id,
            poc_id="poc_001",
        )

        # Attempt to suspend same email for different POC should fail
        with pytest.raises(TaskManagerError) as exc_info:
            await task_manager.suspend_task(
                task_id="task_456",
                poc_email="poc1@test.com",
                thread_id="thread_456",
                poc_id="poc_002",
            )

        assert "already registered" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_legacy_suspend_still_works(self, task_manager, mock_task_store):
        """Test that legacy single-POC suspension still works."""
        task_id = "task_123"
        poc_email = "poc@test.com"
        thread_id = "thread_123"

        # Suspend without poc_id (legacy mode)
        await task_manager.suspend_task(
            task_id=task_id,
            poc_email=poc_email,
            thread_id=thread_id,
        )

        # Verify legacy mapping
        assert task_manager._poc_to_task["poc@test.com"] == task_id
        # No multi-POC mapping
        assert "poc@test.com" not in task_manager._poc_to_task_poc


class TestMultiPOCWebhookHandling:
    """Tests for multi-POC webhook handling."""

    @pytest.mark.asyncio
    async def test_handle_webhook_with_poc_id(self, task_manager, mock_task_store):
        """Test webhook handling with POC ID routing."""
        task_id = "task_123"
        poc_id = "poc_001"
        poc_email = "poc@test.com"
        thread_id = "thread_123"

        # Setup suspended task
        await task_manager.suspend_task(
            task_id=task_id,
            poc_email=poc_email,
            thread_id=thread_id,
            poc_id=poc_id,
        )

        # Configure mock for webhook handling
        mock_task_store.get_suspended_task.return_value = {
            "task_id": task_id,
            "poc_email": poc_email,
            "thread_id": thread_id,
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            "interrupt_data": {"poc_id": poc_id},
        }

        # Create webhook payload
        payload = WebhookPayload(
            event="email.received",
            email_id="email_123",
            from_address=poc_email,
            to=["agent@test.com"],
            subject="Reply",
            has_attachments=False,
            attachment_count=0,
            received_at=datetime.now(timezone.utc).isoformat(),
        )

        # Handle webhook with poc_id
        result = await task_manager.handle_webhook(payload, poc_id=poc_id)

        assert result is True

        # Verify POC was removed from mappings
        assert poc_email not in task_manager._poc_to_task_poc
        assert task_id not in task_manager._task_pocs or poc_id not in task_manager._task_pocs.get(task_id, set())

    @pytest.mark.asyncio
    async def test_handle_webhook_auto_resolves_poc_id(
        self, task_manager, mock_task_store
    ):
        """Test webhook handling auto-resolves POC ID from stored mapping."""
        task_id = "task_123"
        poc_id = "poc_001"
        poc_email = "poc@test.com"
        thread_id = "thread_123"

        # Setup suspended task
        await task_manager.suspend_task(
            task_id=task_id,
            poc_email=poc_email,
            thread_id=thread_id,
            poc_id=poc_id,
        )

        # Configure mock
        mock_task_store.get_suspended_task.return_value = {
            "task_id": task_id,
            "poc_email": poc_email,
            "thread_id": thread_id,
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            "interrupt_data": {"poc_id": poc_id},
        }

        # Create webhook payload without explicit poc_id
        payload = WebhookPayload(
            event="email.received",
            email_id="email_123",
            from_address=poc_email,
            to=["agent@test.com"],
            subject="Reply",
            has_attachments=False,
            attachment_count=0,
            received_at=datetime.now(timezone.utc).isoformat(),
        )

        # Handle webhook without poc_id - should auto-resolve
        result = await task_manager.handle_webhook(payload)

        assert result is True

    @pytest.mark.asyncio
    async def test_handle_webhook_removes_only_specific_poc(
        self, task_manager, mock_task_store
    ):
        """Test webhook handling removes only the specific POC, not all."""
        task_id = "task_123"
        thread_id = "thread_123"

        # Setup two POCs
        await task_manager.suspend_task(
            task_id=task_id,
            poc_email="poc1@test.com",
            thread_id=thread_id,
            poc_id="poc_001",
        )
        await task_manager.suspend_task(
            task_id=task_id,
            poc_email="poc2@test.com",
            thread_id=thread_id,
            poc_id="poc_002",
        )

        # Configure mock for first POC
        mock_task_store.get_suspended_task.return_value = {
            "task_id": task_id,
            "poc_email": "poc1@test.com",
            "thread_id": thread_id,
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            "interrupt_data": {"poc_id": "poc_001"},
        }

        payload = WebhookPayload(
            event="email.received",
            email_id="email_123",
            from_address="poc1@test.com",
            to=["agent@test.com"],
            subject="Reply",
            has_attachments=False,
            attachment_count=0,
            received_at=datetime.now(timezone.utc).isoformat(),
        )

        await task_manager.handle_webhook(payload, poc_id="poc_001")

        # POC 1 should be removed
        assert "poc1@test.com" not in task_manager._poc_to_task_poc

        # POC 2 should still be there
        assert "poc2@test.com" in task_manager._poc_to_task_poc
        assert "poc_002" in task_manager._task_pocs[task_id]


class TestMultiPOCUtilityMethods:
    """Tests for multi-POC utility methods."""

    @pytest.mark.asyncio
    async def test_get_registered_pocs_includes_multi_poc(
        self, task_manager, mock_task_store
    ):
        """Test get_registered_pocs includes both legacy and multi-POC."""
        # Add legacy POC
        await task_manager.suspend_task(
            task_id="task_1",
            poc_email="legacy@test.com",
            thread_id="thread_1",
        )

        # Add multi-POC
        await task_manager.suspend_task(
            task_id="task_2",
            poc_email="multi@test.com",
            thread_id="thread_2",
            poc_id="poc_001",
        )

        pocs = task_manager.get_registered_pocs()

        assert "legacy@test.com" in pocs
        assert "multi@test.com" in pocs
        assert len(pocs) == 2

    @pytest.mark.asyncio
    async def test_get_task_for_poc_prefers_multi_poc(
        self, task_manager, mock_task_store
    ):
        """Test get_task_for_poc returns correct task for multi-POC."""
        await task_manager.suspend_task(
            task_id="task_123",
            poc_email="poc@test.com",
            thread_id="thread_123",
            poc_id="poc_001",
        )

        task_id = task_manager.get_task_for_poc("poc@test.com")

        assert task_id == "task_123"

    @pytest.mark.asyncio
    async def test_get_task_poc_for_email(self, task_manager, mock_task_store):
        """Test get_task_poc_for_email returns both task_id and poc_id."""
        await task_manager.suspend_task(
            task_id="task_123",
            poc_email="poc@test.com",
            thread_id="thread_123",
            poc_id="poc_001",
        )

        result = task_manager.get_task_poc_for_email("poc@test.com")

        assert result == ("task_123", "poc_001")

    @pytest.mark.asyncio
    async def test_get_task_poc_for_email_legacy(self, task_manager, mock_task_store):
        """Test get_task_poc_for_email returns None poc_id for legacy."""
        await task_manager.suspend_task(
            task_id="task_123",
            poc_email="poc@test.com",
            thread_id="thread_123",
        )

        result = task_manager.get_task_poc_for_email("poc@test.com")

        assert result == ("task_123", None)

    @pytest.mark.asyncio
    async def test_get_waiting_pocs_for_task(self, task_manager, mock_task_store):
        """Test get_waiting_pocs_for_task returns all waiting POCs."""
        task_id = "task_123"

        await task_manager.suspend_task(
            task_id=task_id,
            poc_email="poc1@test.com",
            thread_id="thread_123",
            poc_id="poc_001",
        )
        await task_manager.suspend_task(
            task_id=task_id,
            poc_email="poc2@test.com",
            thread_id="thread_123",
            poc_id="poc_002",
        )

        waiting_pocs = task_manager.get_waiting_pocs_for_task(task_id)

        assert waiting_pocs == {"poc_001", "poc_002"}

    @pytest.mark.asyncio
    async def test_get_task_waiting_count(self, task_manager, mock_task_store):
        """Test get_task_waiting_count returns correct count."""
        task_id = "task_123"

        await task_manager.suspend_task(
            task_id=task_id,
            poc_email="poc1@test.com",
            thread_id="thread_123",
            poc_id="poc_001",
        )
        await task_manager.suspend_task(
            task_id=task_id,
            poc_email="poc2@test.com",
            thread_id="thread_123",
            poc_id="poc_002",
        )

        count = task_manager.get_task_waiting_count(task_id)

        assert count == 2

    @pytest.mark.asyncio
    async def test_suspended_task_count_includes_multi_poc(
        self, task_manager, mock_task_store
    ):
        """Test suspended_task_count includes both legacy and multi-POC."""
        # Add legacy
        await task_manager.suspend_task(
            task_id="task_1",
            poc_email="legacy@test.com",
            thread_id="thread_1",
        )

        # Add multi-POC
        await task_manager.suspend_task(
            task_id="task_2",
            poc_email="multi@test.com",
            thread_id="thread_2",
            poc_id="poc_001",
        )

        assert task_manager.suspended_task_count == 2

    @pytest.mark.asyncio
    async def test_multi_poc_task_count(self, task_manager, mock_task_store):
        """Test multi_poc_task_count returns correct count."""
        # Add task with multiple POCs
        await task_manager.suspend_task(
            task_id="task_1",
            poc_email="poc1@test.com",
            thread_id="thread_1",
            poc_id="poc_001",
        )
        await task_manager.suspend_task(
            task_id="task_1",
            poc_email="poc2@test.com",
            thread_id="thread_1",
            poc_id="poc_002",
        )

        # Add another task
        await task_manager.suspend_task(
            task_id="task_2",
            poc_email="poc3@test.com",
            thread_id="thread_2",
            poc_id="poc_003",
        )

        assert task_manager.multi_poc_task_count == 2


class TestMultiPOCRestore:
    """Tests for restoring multi-POC tasks from database."""

    @pytest.mark.asyncio
    async def test_restore_multi_poc_tasks(
        self, mock_db_manager, mock_task_store, mock_checkpointer, mock_graph, mock_settings
    ):
        """Test restoring multi-POC tasks from database."""
        # Configure mock to return multi-POC suspended tasks
        mock_task_store.get_all_suspended_tasks.return_value = [
            {
                "task_id": "task_123",
                "poc_email": "poc1@test.com",
                "thread_id": "thread_123",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                "interrupt_data": {"poc_id": "poc_001"},
            },
            {
                "task_id": "task_123",
                "poc_email": "poc2@test.com",
                "thread_id": "thread_123",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                "interrupt_data": {"poc_id": "poc_002"},
            },
        ]

        manager = TaskManager(
            db_manager=mock_db_manager,
            task_store=mock_task_store,
            checkpointer=mock_checkpointer,
            graph=mock_graph,
            settings=mock_settings,
        )

        await manager._restore_suspended_tasks()

        # Verify multi-POC mappings restored
        assert manager._poc_to_task_poc["poc1@test.com"] == ("task_123", "poc_001")
        assert manager._poc_to_task_poc["poc2@test.com"] == ("task_123", "poc_002")
        assert manager._task_pocs["task_123"] == {"poc_001", "poc_002"}

    @pytest.mark.asyncio
    async def test_restore_legacy_tasks(
        self, mock_db_manager, mock_task_store, mock_checkpointer, mock_graph, mock_settings
    ):
        """Test restoring legacy tasks without poc_id."""
        # Configure mock to return legacy suspended task
        mock_task_store.get_all_suspended_tasks.return_value = [
            {
                "task_id": "task_123",
                "poc_email": "poc@test.com",
                "thread_id": "thread_123",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                "interrupt_data": {},  # No poc_id
            },
        ]

        manager = TaskManager(
            db_manager=mock_db_manager,
            task_store=mock_task_store,
            checkpointer=mock_checkpointer,
            graph=mock_graph,
            settings=mock_settings,
        )

        await manager._restore_suspended_tasks()

        # Verify legacy mapping restored
        assert manager._poc_to_task["poc@test.com"] == "task_123"
        # No multi-POC mapping
        assert "poc@test.com" not in manager._poc_to_task_poc
