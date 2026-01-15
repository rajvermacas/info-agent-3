"""
Progress Store - Thread-safe storage for task progress events with SSE streaming.

Provides real-time progress tracking for task execution:
- Event storage with per-task queues
- Async subscription for SSE streaming
- Automatic cleanup after task completion
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Optional

from pydantic import BaseModel, Field

from mail_agent.task_manager.models import TaskState

logger = logging.getLogger(__name__)


class POCProgress(BaseModel):
    """POC-level progress for multi-POC orchestration."""

    total: int = Field(default=0, description="Total number of POCs")
    pending: int = Field(default=0, description="Number of pending POCs")
    in_progress: int = Field(default=0, description="Number of POCs in progress")
    waiting: int = Field(default=0, description="Number of POCs waiting for replies")
    completed: int = Field(default=0, description="Number of completed POCs")
    failed: int = Field(default=0, description="Number of failed POCs")


class ProgressEvent(BaseModel):
    """
    Progress event for task execution tracking.

    Emitted by executor nodes during graph execution.
    Supports both single-POC and multi-POC orchestration modes.

    Multi-POC event types:
    - phase_planning: Parsing instruction, building dependency graph
    - phase_execution: Executing POCs (sending emails, waiting for replies)
    - phase_aggregation: Aggregating responses, resolving conflicts
    - phase_completion: Sending success replies, finishing up

    POC-level events:
    - poc_started: A specific POC began execution
    - poc_email_sent: Email sent to a POC
    - poc_waiting: Waiting for POC reply
    - poc_reply_received: Reply received from POC
    - poc_validated: POC response validated
    - poc_retry: POC needs retry (followup)
    - poc_redirect: POC redirected to another contact
    - poc_completed: POC finished successfully
    - poc_failed: POC failed after max attempts
    """

    task_id: str = Field(description="Task identifier")
    state: TaskState = Field(description="Current task state")
    node: Optional[str] = Field(
        default=None,
        description="Current graph node name",
    )
    message: str = Field(description="Progress message")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Event timestamp",
    )
    poc_email: Optional[str] = Field(
        default=None,
        description="POC email (for suspended state or POC-level events)",
    )
    result: Optional[dict[str, Any]] = Field(
        default=None,
        description="Result data (for completed state)",
    )
    error: Optional[str] = Field(
        default=None,
        description="Error message (for failed state)",
    )
    event_id: int = Field(
        default=0,
        description="Sequential event ID for SSE Last-Event-Id",
    )

    # Multi-POC fields
    poc_id: Optional[str] = Field(
        default=None,
        description="POC identifier for multi-POC orchestration",
    )
    phase: Optional[str] = Field(
        default=None,
        description="Current orchestration phase (planning, execution, aggregation, completion)",
    )
    event_type: Optional[str] = Field(
        default=None,
        description="Specific event type for multi-POC (poc_started, poc_completed, etc.)",
    )
    poc_progress: Optional[POCProgress] = Field(
        default=None,
        description="Aggregate POC progress for multi-POC mode",
    )
    dynamic_poc_spawned: Optional[bool] = Field(
        default=None,
        description="Whether this POC was dynamically spawned",
    )

    def to_sse_format(self) -> str:
        """
        Convert to SSE wire format.

        Returns:
            SSE formatted string with id, event, and data fields.
        """
        sse_event_type = self._get_event_type()
        data = self.model_dump_json(exclude_none=True)
        return f"id: {self.event_id}\nevent: {sse_event_type}\ndata: {data}\n\n"

    def _get_event_type(self) -> str:
        """
        Get SSE event type based on task state and multi-POC event_type.

        Returns:
            Event type string.
        """
        # Use specific event_type for multi-POC if provided
        if self.event_type:
            return self.event_type

        # Fall back to state-based event type
        if self.state == TaskState.COMPLETED:
            return "complete"
        elif self.state == TaskState.FAILED:
            return "error"
        elif self.state == TaskState.SUSPENDED:
            return "suspended"
        else:
            return "progress"


class TaskProgressQueue:
    """
    Per-task progress tracking with subscriber management.

    Maintains event history and active subscriber queues.
    """

    def __init__(self, task_id: str) -> None:
        """
        Initialize task progress queue.

        Args:
            task_id: Task identifier.
        """
        self.task_id = task_id
        self.events: list[ProgressEvent] = []
        self.subscribers: list[asyncio.Queue[ProgressEvent]] = []
        self._event_counter = 0
        self._lock = asyncio.Lock()
        self._is_terminal = False
        logger.debug(f"TaskProgressQueue created for task_id={task_id}")

    async def add_event(self, event: ProgressEvent) -> None:
        """
        Add event to history and notify all subscribers.

        Args:
            event: Progress event to add.
        """
        async with self._lock:
            self._event_counter += 1
            event.event_id = self._event_counter

            self.events.append(event)
            logger.debug(
                f"Progress event added: task_id={self.task_id}, "
                f"event_id={event.event_id}, node={event.node}, "
                f"state={event.state.value}, message={event.message}"
            )

            # Check for terminal state
            if event.state in (TaskState.COMPLETED, TaskState.FAILED):
                self._is_terminal = True
                logger.info(
                    f"Task {self.task_id} reached terminal state: {event.state.value}"
                )

            # Notify all subscribers
            for queue in self.subscribers:
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    logger.warning(
                        f"Subscriber queue full for task_id={self.task_id}, "
                        f"dropping event_id={event.event_id}"
                    )

    async def subscribe(
        self, last_event_id: Optional[int] = None
    ) -> AsyncGenerator[ProgressEvent, None]:
        """
        Subscribe to progress events.

        Yields historical events first (if last_event_id provided),
        then streams new events in real-time.

        Args:
            last_event_id: Last received event ID for reconnection.

        Yields:
            Progress events as they arrive.
        """
        queue: asyncio.Queue[ProgressEvent] = asyncio.Queue(maxsize=100)

        async with self._lock:
            # Send historical events for reconnection
            start_index = 0
            if last_event_id is not None:
                for i, event in enumerate(self.events):
                    if event.event_id > last_event_id:
                        start_index = i
                        break
                else:
                    start_index = len(self.events)

            # Replay missed events
            for event in self.events[start_index:]:
                yield event
                logger.debug(
                    f"Replayed event_id={event.event_id} for task_id={self.task_id}"
                )

            # If already terminal, don't subscribe
            if self._is_terminal:
                logger.debug(
                    f"Task {self.task_id} already terminal, not subscribing"
                )
                return

            self.subscribers.append(queue)
            logger.debug(
                f"Subscriber added for task_id={self.task_id}, "
                f"total_subscribers={len(self.subscribers)}"
            )

        try:
            while True:
                try:
                    # Wait for new events with timeout for keepalive
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield event

                    # Stop on terminal state
                    if event.state in (TaskState.COMPLETED, TaskState.FAILED):
                        logger.debug(
                            f"Terminal event received, closing subscription "
                            f"for task_id={self.task_id}"
                        )
                        break
                except asyncio.TimeoutError:
                    # Yield None to trigger keepalive (handled by caller)
                    continue
        finally:
            async with self._lock:
                if queue in self.subscribers:
                    self.subscribers.remove(queue)
                    logger.debug(
                        f"Subscriber removed for task_id={self.task_id}, "
                        f"remaining_subscribers={len(self.subscribers)}"
                    )

    def get_events(self, since_event_id: Optional[int] = None) -> list[ProgressEvent]:
        """
        Get all events, optionally filtered by event ID.

        Args:
            since_event_id: Return events after this ID.

        Returns:
            List of progress events.
        """
        if since_event_id is None:
            return list(self.events)

        return [e for e in self.events if e.event_id > since_event_id]

    @property
    def is_terminal(self) -> bool:
        """Check if task has reached terminal state."""
        return self._is_terminal


class ProgressStore:
    """
    Central store for all task progress tracking.

    Thread-safe storage with:
    - Per-task progress queues
    - Async subscription support
    - Automatic cleanup of completed tasks
    """

    def __init__(self, cleanup_delay_seconds: float = 300.0) -> None:
        """
        Initialize progress store.

        Args:
            cleanup_delay_seconds: Delay before cleaning up completed tasks.
        """
        self._tasks: dict[str, TaskProgressQueue] = {}
        self._lock = asyncio.Lock()
        self._cleanup_delay = cleanup_delay_seconds
        self._cleanup_tasks: dict[str, asyncio.Task[None]] = {}
        logger.info(
            f"ProgressStore initialized with cleanup_delay={cleanup_delay_seconds}s"
        )

    async def add_event(self, event: ProgressEvent) -> None:
        """
        Add event to the appropriate task queue.

        Creates task queue if it doesn't exist.

        Args:
            event: Progress event to add.
        """
        async with self._lock:
            if event.task_id not in self._tasks:
                self._tasks[event.task_id] = TaskProgressQueue(event.task_id)
                logger.info(f"Created progress queue for task_id={event.task_id}")

            task_queue = self._tasks[event.task_id]

        await task_queue.add_event(event)

        # Schedule cleanup for terminal states
        if event.state in (TaskState.COMPLETED, TaskState.FAILED):
            await self._schedule_cleanup(event.task_id)

    async def subscribe(
        self, task_id: str, last_event_id: Optional[int] = None
    ) -> AsyncGenerator[ProgressEvent, None]:
        """
        Subscribe to progress events for a task.

        Args:
            task_id: Task to subscribe to.
            last_event_id: Last received event ID for reconnection.

        Yields:
            Progress events as they arrive.

        Raises:
            KeyError: If task_id not found.
        """
        async with self._lock:
            if task_id not in self._tasks:
                logger.warning(f"Subscription requested for unknown task_id={task_id}")
                raise KeyError(f"Task {task_id} not found in progress store")

            task_queue = self._tasks[task_id]

        async for event in task_queue.subscribe(last_event_id):
            yield event

    def get_events(
        self, task_id: str, since_event_id: Optional[int] = None
    ) -> list[ProgressEvent]:
        """
        Get all events for a task.

        Args:
            task_id: Task identifier.
            since_event_id: Return events after this ID.

        Returns:
            List of progress events.

        Raises:
            KeyError: If task_id not found.
        """
        if task_id not in self._tasks:
            logger.warning(f"Events requested for unknown task_id={task_id}")
            raise KeyError(f"Task {task_id} not found in progress store")

        return self._tasks[task_id].get_events(since_event_id)

    def has_task(self, task_id: str) -> bool:
        """
        Check if task exists in store.

        Args:
            task_id: Task identifier.

        Returns:
            True if task exists.
        """
        return task_id in self._tasks

    def is_terminal(self, task_id: str) -> bool:
        """
        Check if task has reached terminal state.

        Args:
            task_id: Task identifier.

        Returns:
            True if task is completed or failed.

        Raises:
            KeyError: If task_id not found.
        """
        if task_id not in self._tasks:
            raise KeyError(f"Task {task_id} not found in progress store")

        return self._tasks[task_id].is_terminal

    async def _schedule_cleanup(self, task_id: str) -> None:
        """
        Schedule cleanup of completed task after delay.

        Args:
            task_id: Task to clean up.
        """
        if task_id in self._cleanup_tasks:
            return  # Already scheduled

        async def cleanup() -> None:
            await asyncio.sleep(self._cleanup_delay)
            async with self._lock:
                if task_id in self._tasks:
                    del self._tasks[task_id]
                    logger.info(f"Cleaned up progress queue for task_id={task_id}")
                if task_id in self._cleanup_tasks:
                    del self._cleanup_tasks[task_id]

        task = asyncio.create_task(cleanup())
        self._cleanup_tasks[task_id] = task
        logger.debug(
            f"Scheduled cleanup for task_id={task_id} in {self._cleanup_delay}s"
        )

    async def cleanup(self) -> None:
        """
        Cancel all pending cleanup tasks.

        Call this when shutting down the server.
        """
        for task_id, task in list(self._cleanup_tasks.items()):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            logger.debug(f"Cancelled cleanup task for task_id={task_id}")

        self._cleanup_tasks.clear()
        logger.info("ProgressStore cleanup completed")

    def get_task_count(self) -> int:
        """
        Get number of tracked tasks.

        Returns:
            Number of tasks in store.
        """
        return len(self._tasks)
