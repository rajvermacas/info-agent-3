"""
Progress Service - Unified event emission and persistence.

Coordinates:
- ProgressStore (in-memory for SSE streaming)
- Database persistence (for activity history)
- Event emission from TaskManager and Executor

This service acts as the single point for all progress tracking operations,
ensuring events are both streamed to subscribers in real-time AND persisted
to the database for later retrieval.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from mail_agent.a2a.progress_store import ProgressEvent, ProgressStore
from mail_agent.persistence.database import DatabaseManager
from mail_agent.task_manager.models import TaskState

logger = logging.getLogger(__name__)


class ProgressServiceError(Exception):
    """Base exception for progress service operations."""

    pass


class ProgressService:
    """
    Unified progress tracking service.

    Provides single point for:
    - Emitting progress events (in-memory and database)
    - Querying activity history from database
    - Managing event lifecycle

    All progress events go through this service, which ensures they are:
    1. Added to ProgressStore for real-time SSE streaming
    2. Persisted to database for historical retrieval

    Attributes:
        _store: In-memory ProgressStore for SSE streaming.
        _db: DatabaseManager for persistent storage.
    """

    def __init__(
        self,
        progress_store: ProgressStore,
        db_manager: DatabaseManager,
    ) -> None:
        """
        Initialize progress service.

        Args:
            progress_store: In-memory store for SSE streaming.
            db_manager: Database manager for persistence.

        Raises:
            ValueError: If progress_store or db_manager is None.
        """
        if progress_store is None:
            raise ValueError("progress_store cannot be None")
        if db_manager is None:
            raise ValueError("db_manager cannot be None")

        self._store = progress_store
        self._db = db_manager
        logger.info("ProgressService initialized with store and database")

    async def emit_event(
        self,
        task_id: str,
        state: TaskState,
        message: str,
        node: Optional[str] = None,
        poc_email: Optional[str] = None,
        result: Optional[dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> ProgressEvent:
        """
        Emit a progress event to both in-memory store and database.

        This is the primary method for emitting progress events. It ensures
        events are both available for real-time SSE streaming and persisted
        for historical retrieval.

        Args:
            task_id: Task identifier.
            state: Current task state.
            message: Human-readable progress message.
            node: Current graph node name (optional).
            poc_email: POC email address (optional).
            result: Result data for completed tasks (optional).
            error: Error message for failed tasks (optional).

        Returns:
            The created ProgressEvent with assigned event_id.

        Raises:
            ProgressServiceError: If event emission fails.
        """
        logger.info(
            f"Emitting progress event: task_id={task_id}, state={state.value}, "
            f"node={node}, message={message[:80]}{'...' if len(message) > 80 else ''}"
        )

        # Create event
        event = ProgressEvent(
            task_id=task_id,
            state=state,
            node=node,
            message=message,
            poc_email=poc_email,
            result=result,
            error=error,
        )

        try:
            # Add to in-memory store (assigns event_id via add_event)
            await self._store.add_event(event)
            logger.debug(
                f"Event added to store: task_id={task_id}, event_id={event.event_id}"
            )

            # Persist to database
            await self._persist_event(event)
            logger.debug(
                f"Event persisted to database: task_id={task_id}, "
                f"event_id={event.event_id}"
            )

            return event

        except Exception as e:
            logger.error(
                f"Failed to emit progress event: task_id={task_id}, "
                f"state={state.value}, error={e}"
            )
            raise ProgressServiceError(f"Failed to emit progress event: {e}") from e

    async def emit_webhook_received(
        self,
        task_id: str,
        poc_email: str,
        received_count: int,
        total_count: int,
    ) -> ProgressEvent:
        """
        Emit event when webhook is received from a POC.

        This specialized method is called by TaskManager when a webhook
        arrives, indicating that a POC has replied to an email.

        Args:
            task_id: Task identifier.
            poc_email: Email address of the POC who replied.
            received_count: Number of POCs who have now replied.
            total_count: Total number of POCs expected to reply.

        Returns:
            The created ProgressEvent.
        """
        message = (
            f"Received reply from {poc_email} "
            f"({received_count}/{total_count} POCs responded)"
        )

        logger.info(
            f"Emitting webhook received event: task_id={task_id}, "
            f"poc_email={poc_email}, progress={received_count}/{total_count}"
        )

        return await self.emit_event(
            task_id=task_id,
            state=TaskState.SUSPENDED,  # Still suspended until all received
            node="webhook_received",
            message=message,
            poc_email=poc_email,
        )

    async def emit_all_webhooks_received(
        self,
        task_id: str,
        poc_emails: list[str],
    ) -> ProgressEvent:
        """
        Emit event when all POC webhooks have been received.

        Called just before task resumption when all expected POCs
        have replied.

        Args:
            task_id: Task identifier.
            poc_emails: List of all POC emails that replied.

        Returns:
            The created ProgressEvent.
        """
        poc_count = len(poc_emails)
        message = f"All {poc_count} POC(s) have replied, preparing to resume"

        logger.info(
            f"Emitting all webhooks received event: task_id={task_id}, "
            f"poc_count={poc_count}"
        )

        return await self.emit_event(
            task_id=task_id,
            state=TaskState.SUSPENDED,
            node="all_webhooks_received",
            message=message,
            poc_email=", ".join(poc_emails) if poc_emails else None,
        )

    async def emit_task_resumed(
        self,
        task_id: str,
        poc_emails: list[str],
    ) -> ProgressEvent:
        """
        Emit event when task resumes from checkpoint.

        Called by TaskManager when task resumption begins after
        webhook(s) have been received.

        Args:
            task_id: Task identifier.
            poc_emails: List of POC emails whose replies triggered resumption.

        Returns:
            The created ProgressEvent.
        """
        poc_count = len(poc_emails)
        message = f"Task resuming with replies from {poc_count} POC(s)"

        logger.info(
            f"Emitting task resumed event: task_id={task_id}, "
            f"poc_emails={poc_emails}"
        )

        return await self.emit_event(
            task_id=task_id,
            state=TaskState.RESUMED,
            node="resume",
            message=message,
            poc_email=", ".join(poc_emails) if poc_emails else None,
        )

    async def emit_validation_result(
        self,
        task_id: str,
        poc_email: str,
        is_valid: bool,
        feedback: Optional[str] = None,
    ) -> ProgressEvent:
        """
        Emit event for validation result of a POC reply.

        Called after validating a POC's response to show the validation
        outcome in the activity timeline.

        Args:
            task_id: Task identifier.
            poc_email: Email address of the POC whose reply was validated.
            is_valid: Whether the validation passed.
            feedback: Validation feedback message (optional).

        Returns:
            The created ProgressEvent.
        """
        if is_valid:
            message = f"Validation passed for {poc_email}"
        else:
            message = f"Validation failed for {poc_email}"
            if feedback:
                message += f": {feedback[:100]}{'...' if len(feedback) > 100 else ''}"

        logger.info(
            f"Emitting validation result event: task_id={task_id}, "
            f"poc_email={poc_email}, is_valid={is_valid}"
        )

        return await self.emit_event(
            task_id=task_id,
            state=TaskState.WORKING,
            node="validation_result",
            message=message,
            poc_email=poc_email,
        )

    async def get_activity_history(
        self,
        task_id: str,
    ) -> list[dict[str, Any]]:
        """
        Get full activity history for a task from database.

        Retrieves all progress events stored in the database for the
        specified task, ordered by event_id.

        Args:
            task_id: Task identifier.

        Returns:
            List of event dictionaries with all event details.

        Raises:
            ProgressServiceError: If query fails.
        """
        logger.debug(f"Fetching activity history for task_id={task_id}")

        try:
            rows = await self._db.fetch_all(
                """
                SELECT
                    event_id, task_id, state, node, message,
                    poc_email, result, error, timestamp, created_at
                FROM progress_events
                WHERE task_id = ?
                ORDER BY event_id ASC
                """,
                (task_id,),
            )

            events = []
            for row in rows:
                event_dict = {
                    "event_id": row[0],
                    "task_id": row[1],
                    "state": row[2],
                    "node": row[3],
                    "message": row[4],
                    "poc_email": row[5],
                    "result": json.loads(row[6]) if row[6] else None,
                    "error": row[7],
                    "timestamp": row[8],
                    "created_at": row[9],
                }
                events.append(event_dict)

            logger.info(
                f"Retrieved {len(events)} activity events for task_id={task_id}"
            )
            return events

        except Exception as e:
            logger.error(
                f"Failed to fetch activity history: task_id={task_id}, error={e}"
            )
            raise ProgressServiceError(
                f"Failed to fetch activity history: {e}"
            ) from e

    async def delete_activity_history(
        self,
        task_id: str,
    ) -> int:
        """
        Delete all activity history for a task from database.

        Used for cleanup operations when tasks are deleted.

        Args:
            task_id: Task identifier.

        Returns:
            Number of events deleted.

        Raises:
            ProgressServiceError: If deletion fails.
        """
        logger.info(f"Deleting activity history for task_id={task_id}")

        try:
            cursor = await self._db.execute(
                "DELETE FROM progress_events WHERE task_id = ?",
                (task_id,),
            )
            await self._db.commit()
            deleted_count = cursor.rowcount

            logger.info(
                f"Deleted {deleted_count} events for task_id={task_id}"
            )
            return deleted_count

        except Exception as e:
            logger.error(
                f"Failed to delete activity history: task_id={task_id}, error={e}"
            )
            raise ProgressServiceError(
                f"Failed to delete activity history: {e}"
            ) from e

    async def _persist_event(self, event: ProgressEvent) -> None:
        """
        Persist a progress event to the database.

        Args:
            event: ProgressEvent to persist.

        Raises:
            Exception: If database operation fails.
        """
        result_json = json.dumps(event.result) if event.result else None
        now = datetime.now(timezone.utc).isoformat()

        await self._db.execute(
            """
            INSERT INTO progress_events (
                task_id, event_id, state, node, message,
                poc_email, result, error, timestamp, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.task_id,
                event.event_id,
                event.state.value,
                event.node,
                event.message,
                event.poc_email,
                result_json,
                event.error,
                event.timestamp.isoformat(),
                now,
            ),
        )
        await self._db.commit()

    @property
    def progress_store(self) -> ProgressStore:
        """
        Get the underlying ProgressStore.

        Used when direct access to the store is needed (e.g., for SSE streaming).

        Returns:
            The ProgressStore instance.
        """
        return self._store
