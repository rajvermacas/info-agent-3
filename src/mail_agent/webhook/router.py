"""
Task Router - Routes webhook events to correct A2A tasks based on sender email.

Enables concurrent A2A requests where each task communicates with a different POC.
When a webhook arrives, the router identifies the correct task by matching the
sender's email address.
"""

import asyncio
import logging
from typing import Any, Optional


logger = logging.getLogger(__name__)


class TaskRouterError(Exception):
    """Base exception for TaskRouter errors."""

    pass


class DuplicatePOCRegistrationError(TaskRouterError):
    """Raised when attempting to register a POC that is already registered."""

    pass


class TaskNotFoundError(TaskRouterError):
    """Raised when a task is not found in the router."""

    pass


class TaskRouter:
    """
    Routes webhook events to correct A2A tasks based on sender email.

    Each A2A task registers its POC email address. When a webhook arrives,
    the router looks up the sender email to find the correct task and delivers
    the event to that task's queue.

    Thread-safe via asyncio.Lock for concurrent access.

    Attributes:
        _poc_to_task: Maps POC email addresses to task IDs.
        _queues: Maps task IDs to their event queues.
        _lock: Async lock for thread-safe access.
    """

    def __init__(self) -> None:
        """Initialize the TaskRouter with empty mappings."""
        self._poc_to_task: dict[str, str] = {}
        self._queues: dict[str, asyncio.Queue[dict[str, Any]]] = {}
        self._lock = asyncio.Lock()
        logger.info("TaskRouter initialized")

    async def register(self, task_id: str, poc_email: str) -> None:
        """
        Register a task to receive events from a specific POC.

        Args:
            task_id: The A2A task identifier.
            poc_email: The POC email address to route events from.

        Raises:
            DuplicatePOCRegistrationError: If the POC is already registered.
            ValueError: If task_id or poc_email is empty.
        """
        if not task_id:
            raise ValueError("task_id cannot be empty")
        if not poc_email:
            raise ValueError("poc_email cannot be empty")

        poc_email_lower = poc_email.lower()

        async with self._lock:
            if poc_email_lower in self._poc_to_task:
                existing_task = self._poc_to_task[poc_email_lower]
                logger.error(
                    f"POC {poc_email} is already registered to task {existing_task}. "
                    f"Cannot register to task {task_id}"
                )
                raise DuplicatePOCRegistrationError(
                    f"POC {poc_email} is already registered to task {existing_task}"
                )

            self._poc_to_task[poc_email_lower] = task_id
            self._queues[task_id] = asyncio.Queue()

            logger.info(
                f"Registered task {task_id} for POC {poc_email}. "
                f"Total registrations: {len(self._poc_to_task)}"
            )

    async def unregister(self, task_id: str, poc_email: str) -> None:
        """
        Unregister a task and clean up its queue.

        Safe to call even if the task is not registered.

        Args:
            task_id: The A2A task identifier.
            poc_email: The POC email address to unregister.
        """
        poc_email_lower = poc_email.lower()

        async with self._lock:
            if poc_email_lower in self._poc_to_task:
                del self._poc_to_task[poc_email_lower]
                logger.debug(f"Removed POC mapping for {poc_email}")

            if task_id in self._queues:
                del self._queues[task_id]
                logger.debug(f"Removed queue for task {task_id}")

            logger.info(
                f"Unregistered task {task_id}. "
                f"Remaining registrations: {len(self._poc_to_task)}"
            )

    async def route_event(self, webhook_payload: dict[str, Any]) -> bool:
        """
        Route an incoming webhook event to the correct task queue.

        Args:
            webhook_payload: The webhook payload containing 'from' field.

        Returns:
            True if the event was successfully routed, False otherwise.
        """
        sender = webhook_payload.get("from")
        if not sender:
            # Try alternative field name used in WebhookPayload
            sender = webhook_payload.get("from_address")

        if not sender:
            logger.warning(
                f"Webhook payload missing 'from' field: {webhook_payload.keys()}"
            )
            return False

        sender_lower = sender.lower()

        async with self._lock:
            if sender_lower not in self._poc_to_task:
                logger.warning(
                    f"No task registered for sender {sender}. "
                    f"Registered POCs: {list(self._poc_to_task.keys())}"
                )
                return False

            task_id = self._poc_to_task[sender_lower]
            queue = self._queues.get(task_id)

            if queue is None:
                logger.error(
                    f"Task {task_id} registered but queue not found. "
                    "This indicates a bug in TaskRouter."
                )
                return False

            await queue.put(webhook_payload)
            logger.info(
                f"Routed event from {sender} to task {task_id}. "
                f"Queue size: {queue.qsize()}"
            )
            return True

    async def wait_for_event(
        self, task_id: str, timeout: Optional[float] = None
    ) -> dict[str, Any]:
        """
        Wait for an event for a specific task.

        Args:
            task_id: The A2A task identifier.
            timeout: Maximum time to wait in seconds. None for indefinite wait.

        Returns:
            The webhook payload when an event arrives.

        Raises:
            TaskNotFoundError: If the task is not registered.
            asyncio.TimeoutError: If timeout expires before event arrives.
        """
        async with self._lock:
            if task_id not in self._queues:
                logger.error(f"Task {task_id} not registered with TaskRouter")
                raise TaskNotFoundError(f"Task {task_id} not registered")
            queue = self._queues[task_id]

        logger.debug(f"Waiting for event for task {task_id} (timeout={timeout}s)")

        try:
            if timeout is not None:
                event = await asyncio.wait_for(queue.get(), timeout=timeout)
            else:
                event = await queue.get()

            queue.task_done()
            logger.info(f"Task {task_id} received event: {event.get('email_id', 'unknown')}")
            return event

        except asyncio.TimeoutError:
            logger.warning(f"Timeout waiting for event for task {task_id} after {timeout}s")
            raise

    def is_registered(self, task_id: str) -> bool:
        """
        Check if a task is registered.

        Args:
            task_id: The A2A task identifier.

        Returns:
            True if the task is registered, False otherwise.
        """
        return task_id in self._queues

    def get_registered_pocs(self) -> list[str]:
        """
        Get list of currently registered POC email addresses.

        Returns:
            List of registered POC emails (lowercase).
        """
        return list(self._poc_to_task.keys())

    def get_task_for_poc(self, poc_email: str) -> Optional[str]:
        """
        Get the task ID registered for a specific POC.

        Args:
            poc_email: The POC email address.

        Returns:
            The task ID if registered, None otherwise.
        """
        return self._poc_to_task.get(poc_email.lower())

    @property
    def registration_count(self) -> int:
        """Get the number of registered task-POC mappings."""
        return len(self._poc_to_task)
