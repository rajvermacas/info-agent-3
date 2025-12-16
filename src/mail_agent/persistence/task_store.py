"""
Task Store - CRUD operations for suspended tasks and task results.

Provides database operations for:
- Suspended tasks: Tasks waiting for POC replies
- Task results: Completed/failed task outcomes
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from mail_agent.persistence.database import DatabaseManager, DatabaseError


logger = logging.getLogger(__name__)


class TaskStoreError(Exception):
    """Base exception for task store operations."""

    pass


class TaskNotFoundError(TaskStoreError):
    """Raised when a task is not found."""

    pass


class DuplicateTaskError(TaskStoreError):
    """Raised when attempting to create a duplicate task."""

    pass


class DuplicatePOCError(TaskStoreError):
    """Raised when a POC already has a suspended task."""

    pass


class TaskStore:
    """
    CRUD operations for task state persistence.

    Manages suspended tasks (waiting for POC replies) and task results
    (completed/failed task outcomes).

    Attributes:
        _db: Database manager instance.
    """

    def __init__(self, db_manager: DatabaseManager) -> None:
        """
        Initialize task store.

        Args:
            db_manager: Database manager instance (must be connected).

        Raises:
            ValueError: If db_manager is None.
        """
        if db_manager is None:
            raise ValueError("db_manager cannot be None")

        self._db = db_manager
        logger.info("TaskStore initialized")

    # =========================================================================
    # Suspended Tasks Operations
    # =========================================================================

    async def suspend_task(
        self,
        task_id: str,
        poc_email: str,
        thread_id: str,
        timeout_seconds: int,
        interrupt_data: Optional[dict[str, Any]] = None,
    ) -> None:
        """
        Record a suspended task waiting for POC reply.

        Args:
            task_id: Unique task identifier.
            poc_email: POC email address the task is waiting for.
            thread_id: LangGraph thread ID for checkpoint retrieval.
            timeout_seconds: Seconds until task expires.
            interrupt_data: Optional interrupt payload data.

        Raises:
            DuplicateTaskError: If task_id already exists.
            DuplicatePOCError: If poc_email already has a pending task.
            TaskStoreError: If database operation fails.
        """
        logger.info(
            f"Suspending task {task_id} waiting for {poc_email}, "
            f"timeout={timeout_seconds}s"
        )

        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=timeout_seconds)
        interrupt_json = json.dumps(interrupt_data) if interrupt_data else None

        try:
            # Check for duplicate POC
            existing = await self._db.fetch_one(
                "SELECT task_id FROM suspended_tasks WHERE poc_email = ?",
                (poc_email.lower(),),
            )
            if existing:
                existing_task_id = existing[0]
                logger.error(
                    f"POC {poc_email} already has suspended task {existing_task_id}"
                )
                raise DuplicatePOCError(
                    f"POC {poc_email} already has suspended task {existing_task_id}"
                )

            # Check for duplicate task_id
            existing_task = await self._db.fetch_one(
                "SELECT task_id FROM suspended_tasks WHERE task_id = ?",
                (task_id,),
            )
            if existing_task:
                logger.error(f"Task {task_id} already suspended")
                raise DuplicateTaskError(f"Task {task_id} already suspended")

            # Insert suspended task
            await self._db.execute(
                """
                INSERT INTO suspended_tasks
                    (task_id, poc_email, thread_id, created_at, expires_at, interrupt_data)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    poc_email.lower(),
                    thread_id,
                    now.isoformat(),
                    expires_at.isoformat(),
                    interrupt_json,
                ),
            )
            await self._db.commit()

            logger.info(
                f"Task {task_id} suspended successfully, expires at {expires_at.isoformat()}"
            )

        except (DuplicateTaskError, DuplicatePOCError):
            raise
        except Exception as e:
            logger.error(f"Failed to suspend task {task_id}: {e}")
            raise TaskStoreError(f"Failed to suspend task: {e}") from e

    async def get_suspended_task(
        self, task_id: str
    ) -> Optional[dict[str, Any]]:
        """
        Get a suspended task by task ID.

        Args:
            task_id: Task identifier.

        Returns:
            Task dict with keys: task_id, poc_email, thread_id, created_at,
            expires_at, interrupt_data. Returns None if not found.

        Raises:
            TaskStoreError: If database operation fails.
        """
        logger.debug(f"Getting suspended task: {task_id}")

        try:
            row = await self._db.fetch_one(
                """
                SELECT task_id, poc_email, thread_id, created_at, expires_at, interrupt_data
                FROM suspended_tasks
                WHERE task_id = ?
                """,
                (task_id,),
            )

            if row is None:
                logger.debug(f"Suspended task not found: {task_id}")
                return None

            task = {
                "task_id": row[0],
                "poc_email": row[1],
                "thread_id": row[2],
                "created_at": row[3],
                "expires_at": row[4],
                "interrupt_data": json.loads(row[5]) if row[5] else None,
            }
            logger.debug(f"Found suspended task: {task_id}")
            return task

        except Exception as e:
            logger.error(f"Failed to get suspended task {task_id}: {e}")
            raise TaskStoreError(f"Failed to get suspended task: {e}") from e

    async def get_task_by_poc(self, poc_email: str) -> Optional[dict[str, Any]]:
        """
        Get a suspended task by POC email address.

        Args:
            poc_email: POC email address.

        Returns:
            Task dict or None if not found.

        Raises:
            TaskStoreError: If database operation fails.
        """
        logger.debug(f"Getting suspended task for POC: {poc_email}")

        try:
            row = await self._db.fetch_one(
                """
                SELECT task_id, poc_email, thread_id, created_at, expires_at, interrupt_data
                FROM suspended_tasks
                WHERE poc_email = ?
                """,
                (poc_email.lower(),),
            )

            if row is None:
                logger.debug(f"No suspended task for POC: {poc_email}")
                return None

            task = {
                "task_id": row[0],
                "poc_email": row[1],
                "thread_id": row[2],
                "created_at": row[3],
                "expires_at": row[4],
                "interrupt_data": json.loads(row[5]) if row[5] else None,
            }
            logger.debug(f"Found suspended task for POC: {poc_email} -> {task['task_id']}")
            return task

        except Exception as e:
            logger.error(f"Failed to get task for POC {poc_email}: {e}")
            raise TaskStoreError(f"Failed to get task for POC: {e}") from e

    async def remove_suspended_task(self, task_id: str) -> bool:
        """
        Remove a suspended task after resumption or expiration.

        Args:
            task_id: Task identifier.

        Returns:
            True if task was removed, False if not found.

        Raises:
            TaskStoreError: If database operation fails.
        """
        logger.info(f"Removing suspended task: {task_id}")

        try:
            cursor = await self._db.execute(
                "DELETE FROM suspended_tasks WHERE task_id = ?",
                (task_id,),
            )
            await self._db.commit()

            removed = cursor.rowcount > 0
            if removed:
                logger.info(f"Suspended task {task_id} removed")
            else:
                logger.debug(f"Suspended task {task_id} not found for removal")

            return removed

        except Exception as e:
            logger.error(f"Failed to remove suspended task {task_id}: {e}")
            raise TaskStoreError(f"Failed to remove suspended task: {e}") from e

    async def get_expired_tasks(self) -> list[dict[str, Any]]:
        """
        Get all expired suspended tasks.

        Returns:
            List of expired task dicts.

        Raises:
            TaskStoreError: If database operation fails.
        """
        logger.debug("Getting expired suspended tasks")

        try:
            now = datetime.now(timezone.utc).isoformat()
            rows = await self._db.fetch_all(
                """
                SELECT task_id, poc_email, thread_id, created_at, expires_at, interrupt_data
                FROM suspended_tasks
                WHERE expires_at < ?
                """,
                (now,),
            )

            tasks = [
                {
                    "task_id": row[0],
                    "poc_email": row[1],
                    "thread_id": row[2],
                    "created_at": row[3],
                    "expires_at": row[4],
                    "interrupt_data": json.loads(row[5]) if row[5] else None,
                }
                for row in rows
            ]

            logger.info(f"Found {len(tasks)} expired suspended tasks")
            return tasks

        except Exception as e:
            logger.error(f"Failed to get expired tasks: {e}")
            raise TaskStoreError(f"Failed to get expired tasks: {e}") from e

    async def get_all_suspended_tasks(self) -> list[dict[str, Any]]:
        """
        Get all suspended tasks (for recovery on startup).

        Returns:
            List of all suspended task dicts.

        Raises:
            TaskStoreError: If database operation fails.
        """
        logger.debug("Getting all suspended tasks")

        try:
            rows = await self._db.fetch_all(
                """
                SELECT task_id, poc_email, thread_id, created_at, expires_at, interrupt_data
                FROM suspended_tasks
                ORDER BY created_at ASC
                """
            )

            tasks = [
                {
                    "task_id": row[0],
                    "poc_email": row[1],
                    "thread_id": row[2],
                    "created_at": row[3],
                    "expires_at": row[4],
                    "interrupt_data": json.loads(row[5]) if row[5] else None,
                }
                for row in rows
            ]

            logger.info(f"Retrieved {len(tasks)} suspended tasks")
            return tasks

        except Exception as e:
            logger.error(f"Failed to get all suspended tasks: {e}")
            raise TaskStoreError(f"Failed to get suspended tasks: {e}") from e

    # =========================================================================
    # Task Results Operations
    # =========================================================================

    async def get_all_task_results(self) -> list[dict[str, Any]]:
        """
        Get all task results (for listing tasks).

        Returns:
            List of all task result dicts.

        Raises:
            TaskStoreError: If database operation fails.
        """
        logger.debug("Getting all task results")

        try:
            rows = await self._db.fetch_all(
                """
                SELECT task_id, status, result, error, completed_at
                FROM task_results
                ORDER BY completed_at DESC
                """
            )

            results = [
                {
                    "task_id": row[0],
                    "status": row[1],
                    "result": json.loads(row[2]) if row[2] else None,
                    "error": row[3],
                    "completed_at": row[4],
                }
                for row in rows
            ]

            logger.info(f"Retrieved {len(results)} task results")
            return results

        except Exception as e:
            logger.error(f"Failed to get all task results: {e}")
            raise TaskStoreError(f"Failed to get task results: {e}") from e

    async def save_result(
        self,
        task_id: str,
        status: str,
        result: Optional[dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        """
        Save a task result (completed or failed).

        Args:
            task_id: Task identifier.
            status: Task status (completed, failed).
            result: Optional result data.
            error: Optional error message.

        Raises:
            TaskStoreError: If database operation fails.
        """
        logger.info(f"Saving result for task {task_id}: status={status}")

        completed_at = datetime.now(timezone.utc).isoformat()
        result_json = json.dumps(result) if result else None

        try:
            # Use INSERT OR REPLACE to handle duplicate task_ids
            await self._db.execute(
                """
                INSERT OR REPLACE INTO task_results
                    (task_id, status, result, error, completed_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (task_id, status, result_json, error, completed_at),
            )
            await self._db.commit()

            logger.info(f"Result saved for task {task_id}")

        except Exception as e:
            logger.error(f"Failed to save result for task {task_id}: {e}")
            raise TaskStoreError(f"Failed to save result: {e}") from e

    async def get_result(self, task_id: str) -> Optional[dict[str, Any]]:
        """
        Get a task result by task ID.

        Args:
            task_id: Task identifier.

        Returns:
            Result dict with keys: task_id, status, result, error, completed_at.
            Returns None if not found.

        Raises:
            TaskStoreError: If database operation fails.
        """
        logger.debug(f"Getting result for task: {task_id}")

        try:
            row = await self._db.fetch_one(
                """
                SELECT task_id, status, result, error, completed_at
                FROM task_results
                WHERE task_id = ?
                """,
                (task_id,),
            )

            if row is None:
                logger.debug(f"Result not found for task: {task_id}")
                return None

            result = {
                "task_id": row[0],
                "status": row[1],
                "result": json.loads(row[2]) if row[2] else None,
                "error": row[3],
                "completed_at": row[4],
            }
            logger.debug(f"Found result for task: {task_id}")
            return result

        except Exception as e:
            logger.error(f"Failed to get result for task {task_id}: {e}")
            raise TaskStoreError(f"Failed to get result: {e}") from e

    async def delete_result(self, task_id: str) -> bool:
        """
        Delete a task result.

        Args:
            task_id: Task identifier.

        Returns:
            True if result was deleted, False if not found.

        Raises:
            TaskStoreError: If database operation fails.
        """
        logger.info(f"Deleting result for task: {task_id}")

        try:
            cursor = await self._db.execute(
                "DELETE FROM task_results WHERE task_id = ?",
                (task_id,),
            )
            await self._db.commit()

            deleted = cursor.rowcount > 0
            if deleted:
                logger.info(f"Result deleted for task {task_id}")
            else:
                logger.debug(f"Result not found for task {task_id}")

            return deleted

        except Exception as e:
            logger.error(f"Failed to delete result for task {task_id}: {e}")
            raise TaskStoreError(f"Failed to delete result: {e}") from e

    async def cleanup_old_results(self, max_age_days: int = 7) -> int:
        """
        Delete task results older than specified age.

        Args:
            max_age_days: Maximum age in days for results to keep.

        Returns:
            Number of results deleted.

        Raises:
            TaskStoreError: If database operation fails.
        """
        logger.info(f"Cleaning up results older than {max_age_days} days")

        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
            cursor = await self._db.execute(
                "DELETE FROM task_results WHERE completed_at < ?",
                (cutoff.isoformat(),),
            )
            await self._db.commit()

            deleted = cursor.rowcount
            logger.info(f"Cleaned up {deleted} old results")
            return deleted

        except Exception as e:
            logger.error(f"Failed to cleanup old results: {e}")
            raise TaskStoreError(f"Failed to cleanup results: {e}") from e
