"""
Tests for ProgressStore - Progress event storage and SSE streaming.
"""

import asyncio
import pytest
from datetime import datetime, timezone

from mail_agent.a2a.progress_store import (
    ProgressStore,
    ProgressEvent,
    TaskProgressQueue,
)
from mail_agent.task_manager.models import TaskState


class TestProgressEvent:
    """Tests for ProgressEvent model."""

    def test_create_progress_event(self):
        """Test creating a progress event with required fields."""
        event = ProgressEvent(
            task_id="task-123",
            state=TaskState.WORKING,
            message="Processing...",
        )

        assert event.task_id == "task-123"
        assert event.state == TaskState.WORKING
        assert event.message == "Processing..."
        assert event.node is None
        assert event.timestamp is not None
        assert event.event_id == 0

    def test_create_progress_event_with_all_fields(self):
        """Test creating a progress event with all fields."""
        timestamp = datetime.now(timezone.utc)
        event = ProgressEvent(
            task_id="task-123",
            state=TaskState.COMPLETED,
            node="validate_response",
            message="Task completed",
            timestamp=timestamp,
            poc_email="test@example.com",
            result={"success": True},
            error=None,
            event_id=5,
        )

        assert event.task_id == "task-123"
        assert event.state == TaskState.COMPLETED
        assert event.node == "validate_response"
        assert event.message == "Task completed"
        assert event.timestamp == timestamp
        assert event.poc_email == "test@example.com"
        assert event.result == {"success": True}
        assert event.error is None
        assert event.event_id == 5

    def test_to_sse_format_progress(self):
        """Test SSE format for progress events."""
        event = ProgressEvent(
            task_id="task-123",
            state=TaskState.WORKING,
            node="compose_email",
            message="Composing email...",
            event_id=1,
        )

        sse_output = event.to_sse_format()

        assert "id: 1" in sse_output
        assert "event: progress" in sse_output
        assert "data: " in sse_output
        assert '"task_id":"task-123"' in sse_output
        assert '"state":"working"' in sse_output
        assert '"node":"compose_email"' in sse_output

    def test_to_sse_format_complete(self):
        """Test SSE format for complete events."""
        event = ProgressEvent(
            task_id="task-123",
            state=TaskState.COMPLETED,
            message="Task completed",
            event_id=5,
        )

        sse_output = event.to_sse_format()

        assert "event: complete" in sse_output
        assert '"state":"completed"' in sse_output

    def test_to_sse_format_error(self):
        """Test SSE format for error events."""
        event = ProgressEvent(
            task_id="task-123",
            state=TaskState.FAILED,
            message="Task failed",
            error="Connection error",
            event_id=3,
        )

        sse_output = event.to_sse_format()

        assert "event: error" in sse_output
        assert '"state":"failed"' in sse_output
        assert '"error":"Connection error"' in sse_output

    def test_to_sse_format_suspended(self):
        """Test SSE format for suspended events."""
        event = ProgressEvent(
            task_id="task-123",
            state=TaskState.SUSPENDED,
            message="Waiting for reply",
            poc_email="poc@example.com",
            event_id=4,
        )

        sse_output = event.to_sse_format()

        assert "event: suspended" in sse_output
        assert '"state":"suspended"' in sse_output
        assert '"poc_email":"poc@example.com"' in sse_output


class TestTaskProgressQueue:
    """Tests for TaskProgressQueue."""

    @pytest.mark.asyncio
    async def test_add_event(self):
        """Test adding events to queue."""
        queue = TaskProgressQueue("task-123")

        event = ProgressEvent(
            task_id="task-123",
            state=TaskState.WORKING,
            message="Processing...",
        )

        await queue.add_event(event)

        assert len(queue.events) == 1
        assert queue.events[0].event_id == 1
        assert queue.events[0].message == "Processing..."

    @pytest.mark.asyncio
    async def test_event_id_increments(self):
        """Test that event IDs increment properly."""
        queue = TaskProgressQueue("task-123")

        for i in range(5):
            event = ProgressEvent(
                task_id="task-123",
                state=TaskState.WORKING,
                message=f"Message {i}",
            )
            await queue.add_event(event)

        assert len(queue.events) == 5
        for i, event in enumerate(queue.events):
            assert event.event_id == i + 1

    @pytest.mark.asyncio
    async def test_terminal_state_sets_flag(self):
        """Test that terminal states set the is_terminal flag."""
        queue = TaskProgressQueue("task-123")

        working_event = ProgressEvent(
            task_id="task-123",
            state=TaskState.WORKING,
            message="Working...",
        )
        await queue.add_event(working_event)
        assert not queue.is_terminal

        completed_event = ProgressEvent(
            task_id="task-123",
            state=TaskState.COMPLETED,
            message="Done",
        )
        await queue.add_event(completed_event)
        assert queue.is_terminal

    @pytest.mark.asyncio
    async def test_get_events_all(self):
        """Test getting all events."""
        queue = TaskProgressQueue("task-123")

        for i in range(3):
            event = ProgressEvent(
                task_id="task-123",
                state=TaskState.WORKING,
                message=f"Message {i}",
            )
            await queue.add_event(event)

        events = queue.get_events()
        assert len(events) == 3

    @pytest.mark.asyncio
    async def test_get_events_since_id(self):
        """Test getting events after a specific ID."""
        queue = TaskProgressQueue("task-123")

        for i in range(5):
            event = ProgressEvent(
                task_id="task-123",
                state=TaskState.WORKING,
                message=f"Message {i}",
            )
            await queue.add_event(event)

        events = queue.get_events(since_event_id=3)
        assert len(events) == 2
        assert events[0].event_id == 4
        assert events[1].event_id == 5

    @pytest.mark.asyncio
    async def test_subscribe_receives_events(self):
        """Test that subscribers receive events."""
        queue = TaskProgressQueue("task-123")

        received_events = []

        async def collect_events():
            async for event in queue.subscribe():
                received_events.append(event)
                if len(received_events) >= 3:
                    break

        # Start subscription in background
        subscription_task = asyncio.create_task(collect_events())

        # Give subscription time to start
        await asyncio.sleep(0.01)

        # Add events
        for i in range(3):
            event = ProgressEvent(
                task_id="task-123",
                state=TaskState.WORKING,
                message=f"Message {i}",
            )
            await queue.add_event(event)

        # Wait for subscription to receive events
        await asyncio.wait_for(subscription_task, timeout=1.0)

        assert len(received_events) == 3

    @pytest.mark.asyncio
    async def test_subscribe_replays_missed_events(self):
        """Test that subscription replays events missed during reconnection."""
        queue = TaskProgressQueue("task-123")

        # Add some events first
        for i in range(5):
            event = ProgressEvent(
                task_id="task-123",
                state=TaskState.WORKING,
                message=f"Message {i}",
            )
            await queue.add_event(event)

        # Subscribe from event ID 2
        received_events = []
        async for event in queue.subscribe(last_event_id=2):
            received_events.append(event)
            if event.event_id == 5:
                break

        # Should receive events 3, 4, 5
        assert len(received_events) == 3
        assert received_events[0].event_id == 3
        assert received_events[1].event_id == 4
        assert received_events[2].event_id == 5


class TestProgressStore:
    """Tests for ProgressStore."""

    @pytest.mark.asyncio
    async def test_add_event_creates_queue(self):
        """Test that adding an event creates a task queue."""
        store = ProgressStore()

        event = ProgressEvent(
            task_id="task-123",
            state=TaskState.WORKING,
            message="Processing...",
        )

        await store.add_event(event)

        assert store.has_task("task-123")
        assert store.get_task_count() == 1

    @pytest.mark.asyncio
    async def test_add_multiple_events_same_task(self):
        """Test adding multiple events to same task."""
        store = ProgressStore()

        for i in range(5):
            event = ProgressEvent(
                task_id="task-123",
                state=TaskState.WORKING,
                message=f"Message {i}",
            )
            await store.add_event(event)

        events = store.get_events("task-123")
        assert len(events) == 5

    @pytest.mark.asyncio
    async def test_add_events_different_tasks(self):
        """Test adding events to different tasks."""
        store = ProgressStore()

        for task_id in ["task-1", "task-2", "task-3"]:
            event = ProgressEvent(
                task_id=task_id,
                state=TaskState.WORKING,
                message="Processing...",
            )
            await store.add_event(event)

        assert store.get_task_count() == 3
        assert store.has_task("task-1")
        assert store.has_task("task-2")
        assert store.has_task("task-3")

    @pytest.mark.asyncio
    async def test_get_events_unknown_task_raises(self):
        """Test that getting events for unknown task raises KeyError."""
        store = ProgressStore()

        with pytest.raises(KeyError):
            store.get_events("unknown-task")

    @pytest.mark.asyncio
    async def test_is_terminal_true_for_completed(self):
        """Test is_terminal returns True for completed tasks."""
        store = ProgressStore()

        await store.add_event(
            ProgressEvent(
                task_id="task-123",
                state=TaskState.COMPLETED,
                message="Done",
            )
        )

        assert store.is_terminal("task-123")

    @pytest.mark.asyncio
    async def test_is_terminal_false_for_working(self):
        """Test is_terminal returns False for working tasks."""
        store = ProgressStore()

        await store.add_event(
            ProgressEvent(
                task_id="task-123",
                state=TaskState.WORKING,
                message="Processing...",
            )
        )

        assert not store.is_terminal("task-123")

    @pytest.mark.asyncio
    async def test_subscribe_unknown_task_raises(self):
        """Test that subscribing to unknown task raises KeyError."""
        store = ProgressStore()

        with pytest.raises(KeyError):
            async for _ in store.subscribe("unknown-task"):
                pass

    @pytest.mark.asyncio
    async def test_cleanup_cancels_pending_tasks(self):
        """Test that cleanup cancels pending cleanup tasks."""
        store = ProgressStore(cleanup_delay_seconds=0.1)

        await store.add_event(
            ProgressEvent(
                task_id="task-123",
                state=TaskState.COMPLETED,
                message="Done",
            )
        )

        # Cleanup scheduled
        assert store.has_task("task-123")

        # Cancel cleanup
        await store.cleanup()

        # Task should still be there (cleanup was cancelled)
        assert store.has_task("task-123")

    @pytest.mark.asyncio
    async def test_automatic_cleanup_after_delay(self):
        """Test that completed tasks are cleaned up after delay."""
        store = ProgressStore(cleanup_delay_seconds=0.05)

        await store.add_event(
            ProgressEvent(
                task_id="task-123",
                state=TaskState.COMPLETED,
                message="Done",
            )
        )

        assert store.has_task("task-123")

        # Wait for cleanup
        await asyncio.sleep(0.1)

        assert not store.has_task("task-123")

    @pytest.mark.asyncio
    async def test_subscribe_and_receive_events(self):
        """Integration test for subscribing and receiving events."""
        store = ProgressStore()

        # Create task first
        await store.add_event(
            ProgressEvent(
                task_id="task-123",
                state=TaskState.WORKING,
                message="Starting...",
            )
        )

        received = []

        async def collect():
            async for event in store.subscribe("task-123"):
                received.append(event)
                if event.state == TaskState.COMPLETED:
                    break

        task = asyncio.create_task(collect())
        await asyncio.sleep(0.01)

        # Add more events
        await store.add_event(
            ProgressEvent(
                task_id="task-123",
                state=TaskState.WORKING,
                message="Processing...",
            )
        )
        await store.add_event(
            ProgressEvent(
                task_id="task-123",
                state=TaskState.COMPLETED,
                message="Done",
            )
        )

        await asyncio.wait_for(task, timeout=1.0)

        # Should have received: initial (replay) + 2 new events
        assert len(received) >= 2
        assert received[-1].state == TaskState.COMPLETED


class TestGetActiveTasks:
    """Tests for get_active_tasks method."""

    @pytest.mark.asyncio
    async def test_get_active_tasks_returns_working_tasks(self):
        """Test that working tasks are returned as active."""
        store = ProgressStore()

        # Add a working task
        await store.add_event(
            ProgressEvent(
                task_id="task-working-1",
                state=TaskState.WORKING,
                node="compose_email",
                message="Composing email...",
            )
        )

        active = store.get_active_tasks()

        assert len(active) == 1
        assert active[0]["task_id"] == "task-working-1"
        assert active[0]["state"] == "working"
        assert active[0]["latest_message"] == "Composing email..."
        assert active[0]["latest_node"] == "compose_email"

    @pytest.mark.asyncio
    async def test_get_active_tasks_excludes_completed_tasks(self):
        """Test that completed tasks are not returned as active."""
        store = ProgressStore()

        # Add a task that completes
        await store.add_event(
            ProgressEvent(
                task_id="task-completed-1",
                state=TaskState.WORKING,
                message="Starting...",
            )
        )
        await store.add_event(
            ProgressEvent(
                task_id="task-completed-1",
                state=TaskState.COMPLETED,
                message="Done",
            )
        )

        active = store.get_active_tasks()

        # Should not include completed task
        task_ids = [t["task_id"] for t in active]
        assert "task-completed-1" not in task_ids

    @pytest.mark.asyncio
    async def test_get_active_tasks_excludes_suspended_tasks(self):
        """Test that suspended tasks are not returned as active."""
        store = ProgressStore()

        # Add a task that gets suspended
        await store.add_event(
            ProgressEvent(
                task_id="task-suspended-1",
                state=TaskState.WORKING,
                message="Starting...",
            )
        )
        await store.add_event(
            ProgressEvent(
                task_id="task-suspended-1",
                state=TaskState.SUSPENDED,
                message="Waiting for reply from poc@example.com",
                poc_email="poc@example.com",
            )
        )

        active = store.get_active_tasks()

        # Should not include suspended task (tracked in suspended_tasks table)
        task_ids = [t["task_id"] for t in active]
        assert "task-suspended-1" not in task_ids

    @pytest.mark.asyncio
    async def test_get_active_tasks_multiple_working_tasks(self):
        """Test that multiple working tasks are returned."""
        store = ProgressStore()

        # Add multiple working tasks
        await store.add_event(
            ProgressEvent(
                task_id="task-a",
                state=TaskState.WORKING,
                node="node-a",
                message="Task A working",
            )
        )
        await store.add_event(
            ProgressEvent(
                task_id="task-b",
                state=TaskState.WORKING,
                node="node-b",
                message="Task B working",
            )
        )

        active = store.get_active_tasks()

        assert len(active) == 2
        task_ids = {t["task_id"] for t in active}
        assert task_ids == {"task-a", "task-b"}

    @pytest.mark.asyncio
    async def test_get_active_tasks_empty_store(self):
        """Test that empty store returns empty list."""
        store = ProgressStore()

        active = store.get_active_tasks()

        assert active == []

    @pytest.mark.asyncio
    async def test_get_active_tasks_excludes_failed_tasks(self):
        """Test that failed tasks are not returned as active."""
        store = ProgressStore()

        # Add a task that fails
        await store.add_event(
            ProgressEvent(
                task_id="task-failed-1",
                state=TaskState.WORKING,
                message="Starting...",
            )
        )
        await store.add_event(
            ProgressEvent(
                task_id="task-failed-1",
                state=TaskState.FAILED,
                message="Task failed",
                error="Some error",
            )
        )

        active = store.get_active_tasks()

        # Should not include failed task
        task_ids = [t["task_id"] for t in active]
        assert "task-failed-1" not in task_ids
