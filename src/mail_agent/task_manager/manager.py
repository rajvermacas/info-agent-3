"""
Task Manager - Orchestrates non-blocking task lifecycle for A2A mode.

Manages:
- Task suspension with checkpoint persistence
- Webhook routing to correct suspended tasks
- Task resumption from checkpoints
- Expired task cleanup
- Task status queries
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from mail_agent.config import Settings, get_settings
from mail_agent.persistence.database import DatabaseManager
from mail_agent.persistence.task_store import TaskStore
from mail_agent.task_manager.models import (
    TaskState,
    TaskStatus,
    SuspendedTaskInfo,
    TaskResult,
    WebhookPayload,
)


logger = logging.getLogger(__name__)


class TaskManagerError(Exception):
    """Base exception for TaskManager operations."""

    pass


class TaskNotFoundError(TaskManagerError):
    """Raised when a task is not found."""

    pass


class TaskExpiredError(TaskManagerError):
    """Raised when attempting to resume an expired task."""

    pass


class TaskManager:
    """
    Manages non-blocking task lifecycle for A2A protocol.

    Supports both single-POC and multi-POC orchestration modes.

    Responsibilities:
    - Track suspended tasks (task_id ↔ poc_email mapping)
    - Handle webhook routing to correct suspended task and POC
    - Resume graph execution when webhook arrives
    - Store task results for polling
    - Manage task expiration (configurable timeout)

    Multi-POC Support:
    - Multiple POCs can be waiting per task (parallel execution)
    - Each POC has its own suspension state within a task
    - Webhook routing includes poc_id for targeted resumption

    Attributes:
        _settings: Application settings.
        _db: Database manager for persistence.
        _task_store: Task state CRUD operations.
        _checkpointer: LangGraph checkpointer for state persistence.
        _graph: Compiled LangGraph state machine.
        _poc_to_task: In-memory mapping of POC email to (task_id, poc_id).
        _task_pocs: In-memory mapping of task_id to set of waiting poc_ids.
        _cleanup_task: Background task for expired task cleanup.
    """

    def __init__(
        self,
        db_manager: DatabaseManager,
        task_store: TaskStore,
        checkpointer: AsyncSqliteSaver,
        graph: CompiledStateGraph,
        settings: Optional[Settings] = None,
    ) -> None:
        """
        Initialize TaskManager.

        Args:
            db_manager: Database manager (must be connected).
            task_store: Task store for persistence.
            checkpointer: LangGraph checkpointer.
            graph: Compiled LangGraph state machine.
            settings: Configuration settings.

        Raises:
            ValueError: If required arguments are None.
        """
        if db_manager is None:
            raise ValueError("db_manager cannot be None")
        if task_store is None:
            raise ValueError("task_store cannot be None")
        if checkpointer is None:
            raise ValueError("checkpointer cannot be None")
        if graph is None:
            raise ValueError("graph cannot be None")

        self._settings = settings or get_settings()
        self._db = db_manager
        self._task_store = task_store
        self._checkpointer = checkpointer
        self._graph = graph

        # In-memory mapping for fast POC lookup
        # Legacy: poc_email -> task_id (backward compatible)
        self._poc_to_task: dict[str, str] = {}
        # Multi-POC: poc_email -> (task_id, poc_id)
        self._poc_to_task_poc: dict[str, tuple[str, str]] = {}
        # Multi-POC: task_id -> set of waiting poc_ids
        self._task_pocs: dict[str, set[str]] = {}
        self._lock = asyncio.Lock()

        # Background cleanup task
        self._cleanup_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()

        logger.info("TaskManager initialized (multi-POC support enabled)")

    @property
    def graph(self) -> CompiledStateGraph:
        """Get the compiled LangGraph state machine."""
        return self._graph

    @property
    def checkpointer(self) -> AsyncSqliteSaver:
        """Get the LangGraph checkpointer."""
        return self._checkpointer

    # =========================================================================
    # Lifecycle Management
    # =========================================================================

    async def start(self) -> None:
        """
        Start the TaskManager and restore state from database.

        Loads suspended tasks from database into memory and starts
        the background cleanup task.
        """
        logger.info("Starting TaskManager")

        # Restore suspended tasks from database
        await self._restore_suspended_tasks()

        # Start background cleanup task
        self._shutdown_event.clear()
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("TaskManager started with background cleanup")

    async def stop(self) -> None:
        """
        Stop the TaskManager gracefully.

        Stops the background cleanup task.
        """
        logger.info("Stopping TaskManager")

        self._shutdown_event.set()

        if self._cleanup_task is not None:
            try:
                await asyncio.wait_for(self._cleanup_task, timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("Cleanup task did not stop gracefully, cancelling")
                self._cleanup_task.cancel()
                try:
                    await self._cleanup_task
                except asyncio.CancelledError:
                    pass

        logger.info("TaskManager stopped")

    async def _restore_suspended_tasks(self) -> None:
        """Restore suspended tasks from database into memory.

        Handles both legacy single-POC and multi-POC suspended tasks.
        POC ID is recovered from interrupt_data if present.
        """
        logger.info("Restoring suspended tasks from database")

        tasks = await self._task_store.get_all_suspended_tasks()
        now = datetime.now(timezone.utc)

        restored = 0
        restored_multi_poc = 0
        expired = 0

        for task in tasks:
            expires_at = datetime.fromisoformat(task["expires_at"])
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)

            # Extract poc_id from interrupt_data if present
            interrupt_data = task.get("interrupt_data") or {}
            poc_id = interrupt_data.get("poc_id")

            if now > expires_at:
                # Task expired while server was down
                logger.warning(
                    f"Task {task['task_id']} expired during downtime, marking failed"
                )
                await self._handle_expired_task(
                    task["task_id"],
                    task["poc_email"],
                    poc_id=poc_id,
                )
                expired += 1
            else:
                # Restore to in-memory mapping
                async with self._lock:
                    if poc_id:
                        # Multi-POC mode
                        self._poc_to_task_poc[task["poc_email"]] = (
                            task["task_id"],
                            poc_id,
                        )
                        if task["task_id"] not in self._task_pocs:
                            self._task_pocs[task["task_id"]] = set()
                        self._task_pocs[task["task_id"]].add(poc_id)
                        restored_multi_poc += 1
                    else:
                        # Legacy single-POC mode
                        self._poc_to_task[task["poc_email"]] = task["task_id"]
                    restored += 1

        logger.info(
            f"Restored {restored} suspended tasks "
            f"({restored_multi_poc} multi-POC), "
            f"cleaned up {expired} expired"
        )

    # =========================================================================
    # Task Suspension
    # =========================================================================

    async def suspend_task(
        self,
        task_id: str,
        poc_email: str,
        thread_id: str,
        interrupt_data: Optional[dict[str, Any]] = None,
        poc_id: Optional[str] = None,
    ) -> None:
        """
        Suspend a task waiting for POC reply.

        Called when the graph reaches an interrupt point (wait_for_reply node).
        Registers the task for webhook routing and persists to database.

        Supports both single-POC (legacy) and multi-POC orchestration.

        Args:
            task_id: A2A task identifier.
            poc_email: POC email the task is waiting for.
            thread_id: LangGraph thread ID (same as task_id typically).
            interrupt_data: Data from the interrupt point.
            poc_id: Optional POC identifier for multi-POC orchestration.
                    If not provided, uses legacy single-POC mode.

        Raises:
            TaskManagerError: If task cannot be suspended.
        """
        poc_email_lower = poc_email.lower()

        logger.info(
            f"Suspending task {task_id} waiting for reply from {poc_email}"
            f" (poc_id={poc_id})"
        )

        async with self._lock:
            if poc_id:
                # Multi-POC mode: Allow multiple POCs per task
                if poc_email_lower in self._poc_to_task_poc:
                    existing_task, existing_poc = self._poc_to_task_poc[poc_email_lower]
                    if existing_task != task_id or existing_poc != poc_id:
                        raise TaskManagerError(
                            f"POC email {poc_email} already registered to "
                            f"task={existing_task}, poc_id={existing_poc}"
                        )

                # Register multi-POC mappings
                self._poc_to_task_poc[poc_email_lower] = (task_id, poc_id)

                if task_id not in self._task_pocs:
                    self._task_pocs[task_id] = set()
                self._task_pocs[task_id].add(poc_id)

                logger.debug(
                    f"Multi-POC: Registered {poc_email_lower} -> "
                    f"(task={task_id}, poc={poc_id}). "
                    f"Task {task_id} now has {len(self._task_pocs[task_id])} waiting POCs"
                )

            else:
                # Legacy single-POC mode
                if poc_email_lower in self._poc_to_task:
                    existing_task = self._poc_to_task[poc_email_lower]
                    if existing_task != task_id:
                        raise TaskManagerError(
                            f"POC {poc_email} already has pending task {existing_task}"
                        )

                self._poc_to_task[poc_email_lower] = task_id

        # Persist to database (include poc_id in interrupt_data for recovery)
        try:
            persist_data = dict(interrupt_data or {})
            if poc_id:
                persist_data["poc_id"] = poc_id

            await self._task_store.suspend_task(
                task_id=task_id,
                poc_email=poc_email_lower,
                thread_id=thread_id,
                timeout_seconds=self._settings.task_suspend_timeout_seconds,
                interrupt_data=persist_data,
            )
            logger.info(
                f"Task {task_id} suspended successfully"
                f" (poc_id={poc_id}, poc_email={poc_email_lower})"
            )

        except Exception as e:
            # Rollback in-memory registration on failure
            async with self._lock:
                if poc_id:
                    if self._poc_to_task_poc.get(poc_email_lower) == (task_id, poc_id):
                        del self._poc_to_task_poc[poc_email_lower]
                    if task_id in self._task_pocs:
                        self._task_pocs[task_id].discard(poc_id)
                        if not self._task_pocs[task_id]:
                            del self._task_pocs[task_id]
                else:
                    if self._poc_to_task.get(poc_email_lower) == task_id:
                        del self._poc_to_task[poc_email_lower]
            raise TaskManagerError(f"Failed to suspend task: {e}") from e

    # =========================================================================
    # Webhook Handling
    # =========================================================================

    async def handle_webhook(
        self,
        payload: WebhookPayload,
        poc_id: Optional[str] = None,
    ) -> bool:
        """
        Handle incoming webhook and route to correct suspended task.

        Looks up the task by sender email (and optional poc_id for multi-POC).
        Triggers task resumption with POC context.

        Args:
            payload: Webhook payload with email notification.
            poc_id: Optional POC identifier from webhook metadata.
                    Used for multi-POC routing to specific POC within task.

        Returns:
            True if webhook was handled (task found and resumed),
            False if no matching suspended task.
        """
        sender = payload.from_address.lower()
        logger.info(
            f"Handling webhook from {sender}, email_id={payload.email_id}, "
            f"poc_id={poc_id}"
        )

        task_id: Optional[str] = None
        resolved_poc_id: Optional[str] = poc_id

        # Lookup task: try multi-POC first, then legacy
        async with self._lock:
            if sender in self._poc_to_task_poc:
                # Multi-POC mode lookup
                task_id, stored_poc_id = self._poc_to_task_poc[sender]
                # Prefer stored poc_id if incoming is None
                resolved_poc_id = poc_id or stored_poc_id
                logger.debug(
                    f"Multi-POC lookup: {sender} -> task={task_id}, "
                    f"poc_id={resolved_poc_id}"
                )
            elif sender in self._poc_to_task:
                # Legacy single-POC mode
                task_id = self._poc_to_task[sender]
                logger.debug(f"Legacy lookup: {sender} -> task={task_id}")

        if task_id is None:
            logger.warning(f"No suspended task for sender: {sender}")
            return False

        # Get suspended task info
        task_info = await self._task_store.get_suspended_task(task_id)
        if task_info is None:
            logger.error(f"Task {task_id} in memory but not in database")
            await self._cleanup_stale_mappings(sender, task_id, resolved_poc_id)
            return False

        # Check expiration
        expires_at = datetime.fromisoformat(task_info["expires_at"])
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        if datetime.now(timezone.utc) > expires_at:
            logger.warning(f"Task {task_id} expired, ignoring webhook")
            await self._handle_expired_task(task_id, sender, resolved_poc_id)
            return False

        # Remove POC from suspended state
        async with self._lock:
            if resolved_poc_id and sender in self._poc_to_task_poc:
                del self._poc_to_task_poc[sender]
                if task_id in self._task_pocs:
                    self._task_pocs[task_id].discard(resolved_poc_id)
                    if not self._task_pocs[task_id]:
                        del self._task_pocs[task_id]
                logger.debug(
                    f"Removed multi-POC mapping: {sender}, poc_id={resolved_poc_id}"
                )
            elif sender in self._poc_to_task:
                del self._poc_to_task[sender]

        await self._task_store.remove_suspended_task(task_id)

        # Resume task in background with POC context
        logger.info(
            f"Resuming task {task_id} with webhook data (poc_id={resolved_poc_id})"
        )
        asyncio.create_task(
            self._resume_task(
                task_id,
                task_info["thread_id"],
                payload,
                poc_id=resolved_poc_id,
            )
        )

        return True

    async def _cleanup_stale_mappings(
        self,
        poc_email: str,
        task_id: str,
        poc_id: Optional[str],
    ) -> None:
        """Clean up stale in-memory mappings when DB is inconsistent."""
        async with self._lock:
            if poc_id and poc_email in self._poc_to_task_poc:
                del self._poc_to_task_poc[poc_email]
                if task_id in self._task_pocs:
                    self._task_pocs[task_id].discard(poc_id)
                    if not self._task_pocs[task_id]:
                        del self._task_pocs[task_id]
            if poc_email in self._poc_to_task:
                del self._poc_to_task[poc_email]

    async def _resume_task(
        self,
        task_id: str,
        thread_id: str,
        payload: WebhookPayload,
        poc_id: Optional[str] = None,
    ) -> None:
        """
        Resume a suspended task from checkpoint.

        Runs the graph from the interrupt point with the webhook data.
        Stores the result when complete.

        Args:
            task_id: Task identifier.
            thread_id: LangGraph thread ID.
            payload: Webhook payload with resume data.
            poc_id: Optional POC identifier for multi-POC orchestration.
        """
        logger.info(
            f"Resuming task {task_id} from checkpoint (poc_id={poc_id})"
        )

        config = {"configurable": {"thread_id": thread_id}}
        resume_data = payload.to_resume_data()

        # Include poc_id in resume data for multi-POC orchestration
        if poc_id:
            resume_data["poc_id"] = poc_id

        try:
            # Create resume command
            command = Command(resume=resume_data)

            # Stream resumed execution
            final_state: Optional[dict[str, Any]] = None

            async for event in self._graph.astream(command, config=config):
                for node_name, node_output in event.items():
                    logger.debug(
                        f"Task {task_id}: Node {node_name} completed "
                        f"(poc_id={poc_id})"
                    )

                    # Check for another interrupt (retry scenario or next POC)
                    if self._is_interrupt_event(event):
                        logger.info(
                            f"Task {task_id} interrupted again "
                            f"(retry or next POC, poc_id={poc_id})"
                        )
                        await self._handle_re_suspend(task_id, event, thread_id)
                        return

                    # Track final state
                    if final_state is None:
                        final_state = {}
                    final_state.update(node_output)

            # Store result
            if final_state:
                success = not final_state.get("error")
                status = "completed" if success else "failed"
                await self._task_store.save_result(
                    task_id=task_id,
                    status=status,
                    result=final_state if success else None,
                    error=final_state.get("error"),
                )
                logger.info(
                    f"Task {task_id} resumed and completed with status: {status} "
                    f"(poc_id={poc_id})"
                )
            else:
                await self._task_store.save_result(
                    task_id=task_id,
                    status="failed",
                    error="Graph completed without final state",
                )
                logger.error(f"Task {task_id} completed without final state")

        except Exception as e:
            logger.exception(f"Task {task_id} failed during resume: {e}")
            await self._task_store.save_result(
                task_id=task_id,
                status="failed",
                error=str(e),
            )

    def _is_interrupt_event(self, event: dict[str, Any]) -> bool:
        """Check if an event indicates an interrupt."""
        # LangGraph interrupt events have special structure
        # Check for __interrupt__ key or interrupt metadata
        if "__interrupt__" in event:
            return True
        for node_output in event.values():
            if isinstance(node_output, dict) and node_output.get("__interrupt__"):
                return True
        return False

    def _parse_interrupt_info(self, interrupt_info: Any) -> dict[str, Any]:
        """
        Parse interrupt info from various possible formats.

        LangGraph returns different formats during initial execution vs resume:
        - Initial: [Interrupt(value={...})] - list of Interrupt dataclass objects
        - Resume: [(dict, interrupt_id), ...] - list of tuples

        Handles:
        1. List of Interrupt objects with .value attribute
        2. List of tuples (value, id)
        3. List of dicts directly
        4. Direct dict

        Args:
            interrupt_info: Raw interrupt information from the event.

        Returns:
            Extracted interrupt payload dict, or empty dict if parsing fails.
        """
        logger.debug(
            f"Parsing interrupt info: type={type(interrupt_info).__name__}"
        )

        # Case 1: List/tuple of items
        if isinstance(interrupt_info, (list, tuple)) and len(interrupt_info) > 0:
            first_item = interrupt_info[0]
            logger.debug(
                f"First interrupt item: type={type(first_item).__name__}, "
                f"has_value_attr={hasattr(first_item, 'value')}"
            )

            # Interrupt dataclass with .value attribute
            if hasattr(first_item, 'value'):
                value = first_item.value
                if isinstance(value, dict):
                    logger.debug(f"Extracted from .value attribute: {list(value.keys())}")
                    return value
                logger.warning(
                    f"Interrupt.value is not a dict: type={type(value).__name__}"
                )
                return {}

            # Tuple format: (value, id)
            if isinstance(first_item, tuple) and len(first_item) > 0:
                value = first_item[0]
                if isinstance(value, dict):
                    logger.debug(f"Extracted from tuple[0]: {list(value.keys())}")
                    return value
                return {}

            # Dict directly in list
            if isinstance(first_item, dict):
                logger.debug(f"First interrupt is dict: {list(first_item.keys())}")
                return first_item

            logger.warning(
                f"Unknown first_item type: {type(first_item).__name__}"
            )
            return {}

        # Case 2: Direct dict
        if isinstance(interrupt_info, dict):
            logger.debug(f"Interrupt info is direct dict: {list(interrupt_info.keys())}")
            return interrupt_info

        logger.warning(
            f"Unknown interrupt_info structure: type={type(interrupt_info).__name__}"
        )
        return {}

    async def _handle_re_suspend(
        self,
        task_id: str,
        event: dict[str, Any],
        thread_id: str,
    ) -> None:
        """Handle re-suspension during retry scenario."""
        # Extract POC email from interrupt data
        # LangGraph returns different formats during resume vs initial execution
        raw_interrupt = event.get("__interrupt__", {})
        interrupt_data = self._parse_interrupt_info(raw_interrupt)
        poc_email = interrupt_data.get("poc_email")

        if poc_email:
            await self.suspend_task(
                task_id=task_id,
                poc_email=poc_email,
                thread_id=thread_id,
                interrupt_data=interrupt_data,
            )
        else:
            logger.error(f"Re-suspend without POC email for task {task_id}")
            await self._task_store.save_result(
                task_id=task_id,
                status="failed",
                error="Re-suspend without POC email",
            )

    # =========================================================================
    # Task Status
    # =========================================================================

    async def get_task_status(self, task_id: str) -> TaskStatus:
        """
        Get current status of a task.

        Checks suspended tasks, then results, to determine task state.

        Args:
            task_id: Task identifier.

        Returns:
            TaskStatus with current state and relevant data.

        Raises:
            TaskNotFoundError: If task is not found.
        """
        logger.debug(f"Getting status for task {task_id}")

        # Check suspended tasks first
        suspended = await self._task_store.get_suspended_task(task_id)
        if suspended:
            created_at = datetime.fromisoformat(suspended["created_at"])
            expires_at = datetime.fromisoformat(suspended["expires_at"])

            return TaskStatus(
                task_id=task_id,
                state=TaskState.SUSPENDED,
                message=f"Waiting for reply from {suspended['poc_email']}",
                poc_email=suspended["poc_email"],
                created_at=created_at,
                expires_at=expires_at,
            )

        # Check results
        result = await self._task_store.get_result(task_id)
        if result:
            completed_at = datetime.fromisoformat(result["completed_at"])
            state = TaskState.COMPLETED if result["status"] == "completed" else TaskState.FAILED

            return TaskStatus(
                task_id=task_id,
                state=state,
                message="Task completed" if state == TaskState.COMPLETED else "Task failed",
                completed_at=completed_at,
                result=result.get("result"),
                error=result.get("error"),
            )

        # Task not found
        raise TaskNotFoundError(f"Task not found: {task_id}")

    async def list_all_tasks(self) -> list[TaskStatus]:
        """
        List all tasks (suspended and completed/failed).

        Returns:
            List of TaskStatus for all known tasks.
        """
        logger.debug("Listing all tasks")

        tasks = []

        # Get suspended tasks
        suspended = await self._task_store.get_all_suspended_tasks()
        for task in suspended:
            created_at = datetime.fromisoformat(task["created_at"])
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)

            expires_at = datetime.fromisoformat(task["expires_at"])
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)

            tasks.append(TaskStatus(
                task_id=task["task_id"],
                state=TaskState.SUSPENDED,
                message=f"Waiting for reply from {task['poc_email']}",
                poc_email=task["poc_email"],
                created_at=created_at,
                expires_at=expires_at,
            ))

        # Get completed/failed tasks
        results = await self._task_store.get_all_task_results()
        for result in results:
            completed_at = datetime.fromisoformat(result["completed_at"])
            if completed_at.tzinfo is None:
                completed_at = completed_at.replace(tzinfo=timezone.utc)

            state = (
                TaskState.COMPLETED
                if result["status"] == "completed"
                else TaskState.FAILED
            )

            tasks.append(TaskStatus(
                task_id=result["task_id"],
                state=state,
                message="Task completed" if state == TaskState.COMPLETED else "Task failed",
                completed_at=completed_at,
                result=result.get("result"),
                error=result.get("error"),
            ))

        logger.info(f"Listed {len(tasks)} total tasks")
        return tasks

    # =========================================================================
    # Cleanup
    # =========================================================================

    async def _cleanup_loop(self) -> None:
        """Background loop for cleaning up expired tasks."""
        interval = self._settings.expired_task_cleanup_interval_seconds
        logger.info(f"Starting cleanup loop with interval {interval}s")

        while not self._shutdown_event.is_set():
            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=interval,
                )
                # Shutdown requested
                break
            except asyncio.TimeoutError:
                # Normal timeout, run cleanup
                await self._cleanup_expired_tasks()

        logger.info("Cleanup loop stopped")

    async def _cleanup_expired_tasks(self) -> None:
        """Clean up expired suspended tasks."""
        logger.debug("Running expired task cleanup")

        try:
            expired_tasks = await self._task_store.get_expired_tasks()

            for task in expired_tasks:
                await self._handle_expired_task(
                    task["task_id"],
                    task["poc_email"],
                )

            if expired_tasks:
                logger.info(f"Cleaned up {len(expired_tasks)} expired tasks")

        except Exception as e:
            logger.error(f"Error during expired task cleanup: {e}")

    async def _handle_expired_task(
        self,
        task_id: str,
        poc_email: str,
        poc_id: Optional[str] = None,
    ) -> None:
        """Handle an expired task - remove from state and store failure."""
        logger.info(
            f"Handling expired task {task_id} (poc_email={poc_email}, poc_id={poc_id})"
        )

        # Remove from in-memory mappings
        async with self._lock:
            if poc_id and poc_email in self._poc_to_task_poc:
                del self._poc_to_task_poc[poc_email]
                if task_id in self._task_pocs:
                    self._task_pocs[task_id].discard(poc_id)
                    if not self._task_pocs[task_id]:
                        del self._task_pocs[task_id]
            if poc_email in self._poc_to_task:
                del self._poc_to_task[poc_email]

        # Remove from suspended tasks
        await self._task_store.remove_suspended_task(task_id)

        # Store failure result
        await self._task_store.save_result(
            task_id=task_id,
            status="failed",
            error=f"Task expired: no reply received within {self._settings.task_suspend_timeout_seconds} seconds",
        )

        logger.info(f"Expired task {task_id} cleaned up (poc_id={poc_id})")

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def get_registered_pocs(self) -> list[str]:
        """
        Get list of POC emails with suspended tasks (legacy + multi-POC).

        Returns:
            List of POC email addresses (lowercase).
        """
        # Combine both legacy and multi-POC registrations
        legacy_pocs = set(self._poc_to_task.keys())
        multi_pocs = set(self._poc_to_task_poc.keys())
        return list(legacy_pocs | multi_pocs)

    def get_task_for_poc(self, poc_email: str) -> Optional[str]:
        """
        Get task ID for a POC email.

        Args:
            poc_email: POC email address.

        Returns:
            Task ID or None if not found.
        """
        email_lower = poc_email.lower()

        # Check multi-POC first, then legacy
        if email_lower in self._poc_to_task_poc:
            task_id, _ = self._poc_to_task_poc[email_lower]
            return task_id

        return self._poc_to_task.get(email_lower)

    def get_task_poc_for_email(
        self,
        poc_email: str,
    ) -> Optional[tuple[str, Optional[str]]]:
        """
        Get task ID and POC ID for a POC email.

        Args:
            poc_email: POC email address.

        Returns:
            Tuple of (task_id, poc_id) or None if not found.
            poc_id will be None for legacy single-POC registrations.
        """
        email_lower = poc_email.lower()

        # Check multi-POC first
        if email_lower in self._poc_to_task_poc:
            return self._poc_to_task_poc[email_lower]

        # Fall back to legacy
        task_id = self._poc_to_task.get(email_lower)
        if task_id:
            return (task_id, None)

        return None

    def get_waiting_pocs_for_task(self, task_id: str) -> set[str]:
        """
        Get set of POC IDs waiting for replies in a task.

        Args:
            task_id: Task identifier.

        Returns:
            Set of POC IDs currently waiting, empty if none.
        """
        return self._task_pocs.get(task_id, set()).copy()

    def get_task_waiting_count(self, task_id: str) -> int:
        """
        Get number of POCs waiting for replies in a task.

        Args:
            task_id: Task identifier.

        Returns:
            Number of POCs in waiting state.
        """
        return len(self._task_pocs.get(task_id, set()))

    @property
    def suspended_task_count(self) -> int:
        """Get number of suspended task registrations (legacy + multi-POC)."""
        return len(self._poc_to_task) + len(self._poc_to_task_poc)

    @property
    def multi_poc_task_count(self) -> int:
        """Get number of tasks with multiple waiting POCs."""
        return len(self._task_pocs)
