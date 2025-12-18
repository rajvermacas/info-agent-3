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
    MultiPocSuspendedTaskInfo,
    SuspendedTaskInfo,
    TaskResult,
    TaskState,
    TaskStatus,
    WebhookPayload,
)

# Import ProgressService type for type hinting (avoid circular import)
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mail_agent.a2a.progress_service import ProgressService


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

    Responsibilities:
    - Track suspended tasks (task_id ↔ poc_email mapping)
    - Handle webhook routing to correct suspended task
    - Resume graph execution when webhook arrives
    - Store task results for polling
    - Manage task expiration (configurable timeout)

    Attributes:
        _settings: Application settings.
        _db: Database manager for persistence.
        _task_store: Task state CRUD operations.
        _checkpointer: LangGraph checkpointer for state persistence.
        _graph: Compiled LangGraph state machine.
        _poc_to_task: In-memory mapping of POC email to task ID.
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
        self._poc_to_task: dict[str, str] = {}
        self._lock = asyncio.Lock()

        # In-memory tracking for tasks actively resuming (visibility during processing)
        # Maps task_id -> {task_id, thread_id, started_at, poc_emails, state}
        self._resuming_tasks: dict[str, dict[str, Any]] = {}

        # Background cleanup task
        self._cleanup_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()

        # Progress service for emitting events (set via set_progress_service)
        self._progress_service: Optional["ProgressService"] = None

        logger.info("TaskManager initialized")

    def set_progress_service(self, progress_service: "ProgressService") -> None:
        """
        Set the progress service for event emission.

        Called during application setup after both TaskManager and
        ProgressService are created.

        Args:
            progress_service: ProgressService instance for emitting events.
        """
        if progress_service is None:
            raise ValueError("progress_service cannot be None")
        self._progress_service = progress_service
        logger.info("ProgressService attached to TaskManager")

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
        """Restore suspended tasks from database into memory."""
        logger.info("Restoring suspended tasks from database")

        tasks = await self._task_store.get_all_suspended_tasks()
        now = datetime.now(timezone.utc)

        restored = 0
        expired = 0

        for task in tasks:
            expires_at = datetime.fromisoformat(task["expires_at"])
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)

            if now > expires_at:
                # Task expired while server was down
                logger.warning(
                    f"Task {task['task_id']} expired during downtime, marking failed"
                )
                await self._handle_expired_task(task["task_id"], task["poc_email"])
                expired += 1
            else:
                # Restore to in-memory mapping
                async with self._lock:
                    self._poc_to_task[task["poc_email"]] = task["task_id"]
                restored += 1

        logger.info(f"Restored {restored} suspended tasks, cleaned up {expired} expired")

    # =========================================================================
    # Task Suspension
    # =========================================================================

    async def suspend_task(
        self,
        task_id: str,
        poc_email: str,
        thread_id: str,
        interrupt_data: Optional[dict[str, Any]] = None,
    ) -> None:
        """
        Suspend a task waiting for POC reply.

        Called when the graph reaches an interrupt point (wait_for_reply node).
        Registers the task for webhook routing and persists to database.

        Args:
            task_id: A2A task identifier.
            poc_email: POC email the task is waiting for.
            thread_id: LangGraph thread ID (same as task_id typically).
            interrupt_data: Data from the interrupt point.

        Raises:
            TaskManagerError: If task cannot be suspended.
        """
        poc_email_lower = poc_email.lower()

        logger.info(
            f"Suspending task {task_id} waiting for reply from {poc_email}"
        )

        async with self._lock:
            # Check for duplicate POC registration
            if poc_email_lower in self._poc_to_task:
                existing_task = self._poc_to_task[poc_email_lower]
                if existing_task != task_id:
                    raise TaskManagerError(
                        f"POC {poc_email} already has pending task {existing_task}"
                    )

            # Register in memory
            self._poc_to_task[poc_email_lower] = task_id

        # Persist to database
        try:
            await self._task_store.suspend_task(
                task_id=task_id,
                poc_email=poc_email_lower,
                thread_id=thread_id,
                timeout_seconds=self._settings.task_suspend_timeout_seconds,
                interrupt_data=interrupt_data,
            )
            logger.info(f"Task {task_id} suspended successfully")

        except Exception as e:
            # Rollback in-memory registration on failure
            async with self._lock:
                if self._poc_to_task.get(poc_email_lower) == task_id:
                    del self._poc_to_task[poc_email_lower]
            raise TaskManagerError(f"Failed to suspend task: {e}") from e

    # =========================================================================
    # Multi-POC Task Suspension (Parallel Processing)
    # =========================================================================

    async def suspend_task_multi_poc(
        self,
        task_id: str,
        poc_emails: list[str],
        thread_id: str,
        interrupt_data: Optional[dict[str, Any]] = None,
    ) -> None:
        """
        Suspend a task waiting for multiple POC replies (parallel processing).

        Called when the graph reaches wait_for_all_replies node.
        Registers all POCs for webhook routing and persists to database.

        Args:
            task_id: A2A task identifier.
            poc_emails: List of POC email addresses to wait for.
            thread_id: LangGraph thread ID (same as task_id typically).
            interrupt_data: Data from the interrupt point.

        Raises:
            TaskManagerError: If task cannot be suspended.
        """
        poc_emails_lower = [poc.lower() for poc in poc_emails]

        logger.info(
            f"Suspending multi-POC task {task_id} waiting for {len(poc_emails)} POCs: "
            f"{poc_emails_lower}"
        )

        async with self._lock:
            # Check for duplicate POC registrations
            for poc_email in poc_emails_lower:
                if poc_email in self._poc_to_task:
                    existing_task = self._poc_to_task[poc_email]
                    if existing_task != task_id:
                        raise TaskManagerError(
                            f"POC {poc_email} already has pending task {existing_task}"
                        )

            # Register all POCs in memory
            for poc_email in poc_emails_lower:
                self._poc_to_task[poc_email] = task_id

        # Persist to database
        try:
            await self._task_store.suspend_task_multi_poc(
                task_id=task_id,
                poc_emails=poc_emails_lower,
                thread_id=thread_id,
                timeout_seconds=self._settings.task_suspend_timeout_seconds,
                interrupt_data=interrupt_data,
            )
            logger.info(
                f"Multi-POC task {task_id} suspended successfully, "
                f"waiting for {len(poc_emails)} POCs"
            )

        except Exception as e:
            # Rollback in-memory registrations on failure
            async with self._lock:
                for poc_email in poc_emails_lower:
                    if self._poc_to_task.get(poc_email) == task_id:
                        del self._poc_to_task[poc_email]
            raise TaskManagerError(f"Failed to suspend multi-POC task: {e}") from e

    # =========================================================================
    # Webhook Handling
    # =========================================================================

    async def handle_webhook(self, payload: WebhookPayload) -> bool:
        """
        Handle incoming webhook and route to correct suspended task.

        Supports both single-POC (legacy) and multi-POC (parallel) modes.
        For multi-POC, collects webhooks and only resumes when all POCs respond.

        Args:
            payload: Webhook payload with email notification.

        Returns:
            True if webhook was handled (task found, collected or resumed),
            False if no matching suspended task.
        """
        sender = payload.from_address.lower()
        logger.info(f"Handling webhook from {sender}, email_id={payload.email_id}")

        # Lookup task by sender
        async with self._lock:
            task_id = self._poc_to_task.get(sender)

        if task_id is None:
            logger.warning(f"No suspended task for sender: {sender}")
            return False

        # First check if this is a multi-POC task
        multi_poc_task = await self._task_store.get_suspended_task_multi_poc(task_id)
        if multi_poc_task is not None:
            return await self._handle_webhook_multi_poc(
                task_id, sender, payload, multi_poc_task
            )

        # Otherwise handle as single-POC (legacy)
        return await self._handle_webhook_single_poc(task_id, sender, payload)

    async def _handle_webhook_single_poc(
        self,
        task_id: str,
        sender: str,
        payload: WebhookPayload,
    ) -> bool:
        """
        Handle webhook for single-POC task (legacy mode).

        Args:
            task_id: Task identifier.
            sender: Sender email address (lowercase).
            payload: Webhook payload.

        Returns:
            True if handled successfully.
        """
        logger.debug(f"Handling single-POC webhook for task {task_id}")

        # Get suspended task info
        task_info = await self._task_store.get_suspended_task(task_id)
        if task_info is None:
            logger.error(f"Single-POC task {task_id} in memory but not in database")
            async with self._lock:
                if sender in self._poc_to_task:
                    del self._poc_to_task[sender]
            return False

        # Check expiration
        expires_at = datetime.fromisoformat(task_info["expires_at"])
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        if datetime.now(timezone.utc) > expires_at:
            logger.warning(f"Single-POC task {task_id} expired, ignoring webhook")
            await self._handle_expired_task(task_id, sender)
            return False

        # Remove from suspended state and add to resuming tasks for visibility
        async with self._lock:
            if sender in self._poc_to_task:
                del self._poc_to_task[sender]

            # Track as resuming task for visibility during processing
            self._resuming_tasks[task_id] = {
                "task_id": task_id,
                "thread_id": task_info["thread_id"],
                "started_at": datetime.now(timezone.utc),
                "poc_emails": [task_info["poc_email"]],
                "state": "resuming",
            }
            logger.debug(
                f"Task {task_id} added to resuming tasks for visibility during processing"
            )

        await self._task_store.remove_suspended_task(task_id)

        # Emit webhook received event for single-POC
        if self._progress_service is not None:
            try:
                await self._progress_service.emit_webhook_received(
                    task_id=task_id,
                    poc_email=sender,
                    received_count=1,
                    total_count=1,
                )
                logger.debug(f"Emitted webhook received event for single-POC {sender}")
            except Exception as e:
                logger.error(f"Failed to emit webhook received event: {e}")

        # Resume task in background
        logger.info(f"Resuming single-POC task {task_id} with webhook data")
        asyncio.create_task(
            self._resume_task(task_id, task_info["thread_id"], payload)
        )

        return True

    async def _handle_webhook_multi_poc(
        self,
        task_id: str,
        sender: str,
        payload: WebhookPayload,
        task_info: dict[str, Any],
    ) -> bool:
        """
        Handle webhook for multi-POC task (parallel mode).

        Collects webhooks from each POC and only resumes when all have responded.

        Args:
            task_id: Task identifier.
            sender: Sender email address (lowercase).
            payload: Webhook payload.
            task_info: Multi-POC task info dict.

        Returns:
            True if handled successfully.
        """
        logger.debug(
            f"Handling multi-POC webhook for task {task_id} from {sender}, "
            f"pending={len(task_info['pending_pocs'])}"
        )

        # Check expiration
        expires_at = datetime.fromisoformat(task_info["expires_at"])
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        if datetime.now(timezone.utc) > expires_at:
            logger.warning(f"Multi-POC task {task_id} expired, ignoring webhook")
            await self._handle_expired_task_multi_poc(
                task_id, task_info["poc_emails"]
            )
            return False

        # Record this webhook
        webhook_data = payload.to_resume_data()
        all_received, remaining = await self._task_store.record_webhook_received(
            task_id=task_id,
            poc_email=sender,
            webhook_data=webhook_data,
        )

        logger.info(
            f"Webhook from {sender} recorded for task {task_id}, "
            f"all_received={all_received}, remaining={remaining}"
        )

        # Emit progress event for webhook received
        total_count = len(task_info["poc_emails"])
        received_count = total_count - remaining
        if self._progress_service is not None:
            try:
                await self._progress_service.emit_webhook_received(
                    task_id=task_id,
                    poc_email=sender,
                    received_count=received_count,
                    total_count=total_count,
                )
                logger.debug(
                    f"Emitted webhook received event for {sender} ({received_count}/{total_count})"
                )
            except Exception as e:
                logger.error(f"Failed to emit webhook received event: {e}")

        if not all_received:
            # Still waiting for more POCs - don't resume yet
            logger.info(
                f"Task {task_id} still waiting for {remaining} more POC(s)"
            )
            return True

        # All POCs have responded - prepare to resume
        logger.info(
            f"All {len(task_info['poc_emails'])} POCs have responded for task {task_id}, "
            "preparing to resume"
        )

        # Emit "all webhooks received" event
        if self._progress_service is not None:
            try:
                await self._progress_service.emit_all_webhooks_received(
                    task_id=task_id,
                    poc_emails=task_info["poc_emails"],
                )
                logger.debug(
                    f"Emitted all webhooks received event for task {task_id}"
                )
            except Exception as e:
                logger.error(f"Failed to emit all webhooks received event: {e}")

        # Get all collected webhooks
        all_webhooks = await self._task_store.get_all_webhooks_for_task(task_id)

        # Remove from in-memory POC mapping and add to resuming tasks
        # This ensures task visibility during processing
        async with self._lock:
            for poc_email in task_info["poc_emails"]:
                poc_lower = poc_email.lower()
                if poc_lower in self._poc_to_task:
                    del self._poc_to_task[poc_lower]

            # Track as resuming task for visibility during processing
            self._resuming_tasks[task_id] = {
                "task_id": task_id,
                "thread_id": task_info["thread_id"],
                "started_at": datetime.now(timezone.utc),
                "poc_emails": task_info["poc_emails"],
                "state": "resuming",
            }
            logger.debug(
                f"Task {task_id} added to resuming tasks for visibility during processing"
            )

        # Remove from database
        await self._task_store.remove_suspended_task_multi_poc(task_id)

        # Resume task in background with all webhook data
        logger.info(
            f"Resuming multi-POC task {task_id} with {len(all_webhooks)} webhooks"
        )
        asyncio.create_task(
            self._resume_task_multi_poc(
                task_id, task_info["thread_id"], all_webhooks
            )
        )

        return True

    async def _resume_task(
        self,
        task_id: str,
        thread_id: str,
        payload: WebhookPayload,
    ) -> None:
        """
        Resume a suspended task from checkpoint.

        Runs the graph from the interrupt point with the webhook data.
        Stores the result when complete.

        Args:
            task_id: Task identifier.
            thread_id: LangGraph thread ID.
            payload: Webhook payload with resume data.
        """
        logger.info(f"Resuming task {task_id} from checkpoint")

        # Emit "task resumed" progress event
        poc_email = payload.from_address
        if self._progress_service is not None:
            try:
                await self._progress_service.emit_task_resumed(
                    task_id=task_id,
                    poc_emails=[poc_email],
                )
                logger.debug(f"Emitted task resumed event for task {task_id}")
            except Exception as e:
                logger.error(f"Failed to emit task resumed event: {e}")

        config = {"configurable": {"thread_id": thread_id}}
        resume_data = payload.to_resume_data()

        try:
            # Create resume command
            command = Command(resume=resume_data)

            # Stream resumed execution
            final_state: Optional[dict[str, Any]] = None

            async for event in self._graph.astream(command, config=config):
                for node_name, node_output in event.items():
                    logger.debug(f"Task {task_id}: Node {node_name} completed")

                    # Check for another interrupt (retry scenario)
                    if self._is_interrupt_event(event):
                        logger.info(f"Task {task_id} interrupted again (retry)")
                        # Remove from resuming tasks since it's going back to suspended
                        async with self._lock:
                            self._resuming_tasks.pop(task_id, None)
                            logger.debug(
                                f"Task {task_id} removed from resuming tasks "
                                "(re-suspended for retry)"
                            )
                        await self._handle_re_suspend(task_id, event, thread_id)
                        return

                    # Emit progress event for resumed execution
                    if self._progress_service is not None and node_name != "__interrupt__":
                        try:
                            # Extract message from node output
                            message = f"Completed {node_name}"
                            if isinstance(node_output, dict):
                                progress_msgs = node_output.get("progress_messages", [])
                                if progress_msgs:
                                    message = progress_msgs[-1]
                            # Extract POC email if available
                            current_poc = None
                            if isinstance(node_output, dict):
                                current_poc = node_output.get("current_poc")
                            await self._progress_service.emit_event(
                                task_id=task_id,
                                state=TaskState.WORKING,
                                node=node_name,
                                message=message,
                                poc_email=current_poc,
                            )
                            logger.debug(
                                f"Emitted progress event for node {node_name} "
                                f"in resumed task {task_id}"
                            )
                        except Exception as e:
                            logger.error(
                                f"Failed to emit progress event for node "
                                f"{node_name}: {e}"
                            )

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
                logger.info(f"Task {task_id} resumed and completed with status: {status}")

                # Emit final completed/failed event
                if self._progress_service is not None:
                    try:
                        final_summary = final_state.get("final_summary", "")
                        error_msg = final_state.get("error")
                        await self._progress_service.emit_event(
                            task_id=task_id,
                            state=TaskState.COMPLETED if success else TaskState.FAILED,
                            node="end",
                            message=final_summary if success else f"Task failed: {error_msg}",
                            result=final_state if success else None,
                            error=error_msg,
                        )
                        logger.debug(
                            f"Emitted final {status} event for resumed task {task_id}"
                        )
                    except Exception as e:
                        logger.error(f"Failed to emit final event: {e}")
            else:
                await self._task_store.save_result(
                    task_id=task_id,
                    status="failed",
                    error="Graph completed without final state",
                )
                logger.error(f"Task {task_id} completed without final state")

                # Emit failed event for missing final state
                if self._progress_service is not None:
                    try:
                        await self._progress_service.emit_event(
                            task_id=task_id,
                            state=TaskState.FAILED,
                            node="end",
                            message="Task failed: Graph completed without final state",
                            error="Graph completed without final state",
                        )
                    except Exception as e:
                        logger.error(f"Failed to emit final event: {e}")

            # Remove from resuming tasks after result is saved
            async with self._lock:
                self._resuming_tasks.pop(task_id, None)
                logger.debug(f"Task {task_id} removed from resuming tasks")

        except Exception as e:
            logger.exception(f"Task {task_id} failed during resume: {e}")
            await self._task_store.save_result(
                task_id=task_id,
                status="failed",
                error=str(e),
            )

            # Emit failed event for exception
            if self._progress_service is not None:
                try:
                    await self._progress_service.emit_event(
                        task_id=task_id,
                        state=TaskState.FAILED,
                        node="end",
                        message=f"Task failed during resume: {e}",
                        error=str(e),
                    )
                except Exception as emit_err:
                    logger.error(f"Failed to emit failure event: {emit_err}")

            # Remove from resuming tasks even on error
            async with self._lock:
                self._resuming_tasks.pop(task_id, None)
                logger.debug(f"Task {task_id} removed from resuming tasks after error")

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

    async def _resume_task_multi_poc(
        self,
        task_id: str,
        thread_id: str,
        all_webhooks: dict[str, dict[str, Any]],
    ) -> None:
        """
        Resume a multi-POC suspended task from checkpoint.

        Runs the graph from the interrupt point with all collected webhook data.

        Args:
            task_id: Task identifier.
            thread_id: LangGraph thread ID.
            all_webhooks: Dict mapping POC email to webhook data.
        """
        logger.info(
            f"Resuming multi-POC task {task_id} from checkpoint with "
            f"{len(all_webhooks)} webhooks"
        )

        # Emit "task resumed" progress event
        poc_emails = list(all_webhooks.keys())
        if self._progress_service is not None:
            try:
                await self._progress_service.emit_task_resumed(
                    task_id=task_id,
                    poc_emails=poc_emails,
                )
                logger.debug(f"Emitted task resumed event for task {task_id}")
            except Exception as e:
                logger.error(f"Failed to emit task resumed event: {e}")

        config = {"configurable": {"thread_id": thread_id}}

        # Multi-POC resume data includes all webhook payloads
        resume_data = {
            "webhooks": all_webhooks,
            "parallel_mode": True,
            "poc_count": len(all_webhooks),
        }

        try:
            # Create resume command
            command = Command(resume=resume_data)

            # Stream resumed execution
            final_state: Optional[dict[str, Any]] = None

            async for event in self._graph.astream(command, config=config):
                for node_name, node_output in event.items():
                    logger.debug(f"Multi-POC task {task_id}: Node {node_name} completed")

                    # Check for another interrupt (parallel retry scenario)
                    if self._is_interrupt_event(event):
                        logger.info(
                            f"Multi-POC task {task_id} interrupted again (retry)"
                        )
                        # Remove from resuming tasks since it's going back to suspended
                        async with self._lock:
                            self._resuming_tasks.pop(task_id, None)
                            logger.debug(
                                f"Task {task_id} removed from resuming tasks "
                                "(re-suspended for retry)"
                            )
                        await self._handle_re_suspend_multi_poc(
                            task_id, event, thread_id
                        )
                        return

                    # Emit progress event for resumed execution
                    if self._progress_service is not None and node_name != "__interrupt__":
                        try:
                            # Extract message from node output
                            message = f"Completed {node_name}"
                            if isinstance(node_output, dict):
                                progress_msgs = node_output.get("progress_messages", [])
                                if progress_msgs:
                                    message = progress_msgs[-1]
                            # Extract POC email if available
                            current_poc = None
                            if isinstance(node_output, dict):
                                current_poc = node_output.get("current_poc")
                            await self._progress_service.emit_event(
                                task_id=task_id,
                                state=TaskState.WORKING,
                                node=node_name,
                                message=message,
                                poc_email=current_poc,
                            )
                            logger.debug(
                                f"Emitted progress event for node {node_name} "
                                f"in resumed multi-POC task {task_id}"
                            )
                        except Exception as e:
                            logger.error(
                                f"Failed to emit progress event for node "
                                f"{node_name}: {e}"
                            )

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
                    f"Multi-POC task {task_id} resumed and completed with status: {status}"
                )

                # Emit final completed/failed event
                if self._progress_service is not None:
                    try:
                        final_summary = final_state.get("final_summary", "")
                        error_msg = final_state.get("error")
                        await self._progress_service.emit_event(
                            task_id=task_id,
                            state=TaskState.COMPLETED if success else TaskState.FAILED,
                            node="end",
                            message=final_summary if success else f"Task failed: {error_msg}",
                            result=final_state if success else None,
                            error=error_msg,
                        )
                        logger.debug(
                            f"Emitted final {status} event for resumed "
                            f"multi-POC task {task_id}"
                        )
                    except Exception as e:
                        logger.error(f"Failed to emit final event: {e}")
            else:
                await self._task_store.save_result(
                    task_id=task_id,
                    status="failed",
                    error="Graph completed without final state",
                )
                logger.error(f"Multi-POC task {task_id} completed without final state")

                # Emit failed event for missing final state
                if self._progress_service is not None:
                    try:
                        await self._progress_service.emit_event(
                            task_id=task_id,
                            state=TaskState.FAILED,
                            node="end",
                            message="Task failed: Graph completed without final state",
                            error="Graph completed without final state",
                        )
                    except Exception as e:
                        logger.error(f"Failed to emit final event: {e}")

            # Remove from resuming tasks after result is saved
            async with self._lock:
                self._resuming_tasks.pop(task_id, None)
                logger.debug(f"Task {task_id} removed from resuming tasks")

        except Exception as e:
            logger.exception(f"Multi-POC task {task_id} failed during resume: {e}")
            await self._task_store.save_result(
                task_id=task_id,
                status="failed",
                error=str(e),
            )

            # Emit failed event for exception
            if self._progress_service is not None:
                try:
                    await self._progress_service.emit_event(
                        task_id=task_id,
                        state=TaskState.FAILED,
                        node="end",
                        message=f"Multi-POC task failed during resume: {e}",
                        error=str(e),
                    )
                except Exception as emit_err:
                    logger.error(f"Failed to emit failure event: {emit_err}")

            # Remove from resuming tasks even on error
            async with self._lock:
                self._resuming_tasks.pop(task_id, None)
                logger.debug(f"Task {task_id} removed from resuming tasks after error")

    async def _handle_re_suspend_multi_poc(
        self,
        task_id: str,
        event: dict[str, Any],
        thread_id: str,
    ) -> None:
        """Handle re-suspension during multi-POC retry scenario."""
        raw_interrupt = event.get("__interrupt__", {})
        interrupt_data = self._parse_interrupt_info(raw_interrupt)

        # Check for multi-POC interrupt
        poc_emails = interrupt_data.get("poc_emails")
        if poc_emails and isinstance(poc_emails, list):
            await self.suspend_task_multi_poc(
                task_id=task_id,
                poc_emails=poc_emails,
                thread_id=thread_id,
                interrupt_data=interrupt_data,
            )
            return

        # Fall back to single-POC if only one POC in interrupt
        poc_email = interrupt_data.get("poc_email")
        if poc_email:
            await self.suspend_task(
                task_id=task_id,
                poc_email=poc_email,
                thread_id=thread_id,
                interrupt_data=interrupt_data,
            )
        else:
            logger.error(f"Multi-POC re-suspend without POC email(s) for task {task_id}")
            await self._task_store.save_result(
                task_id=task_id,
                status="failed",
                error="Re-suspend without POC email(s)",
            )

    async def _handle_expired_task_multi_poc(
        self,
        task_id: str,
        poc_emails: list[str],
    ) -> None:
        """Handle an expired multi-POC task - remove from state and store failure."""
        logger.info(f"Handling expired multi-POC task {task_id}")

        # Remove all POCs from in-memory mapping
        async with self._lock:
            for poc_email in poc_emails:
                poc_lower = poc_email.lower()
                if poc_lower in self._poc_to_task:
                    del self._poc_to_task[poc_lower]

        # Remove from database
        await self._task_store.remove_suspended_task_multi_poc(task_id)

        # Store failure result
        await self._task_store.save_result(
            task_id=task_id,
            status="failed",
            error=(
                f"Multi-POC task expired: no complete reply received within "
                f"{self._settings.task_suspend_timeout_seconds} seconds"
            ),
        )

        logger.info(f"Expired multi-POC task {task_id} cleaned up")

    # =========================================================================
    # Task Status
    # =========================================================================

    async def get_task_status(self, task_id: str) -> TaskStatus:
        """
        Get current status of a task.

        Checks suspended tasks (single and multi-POC), then results.

        Args:
            task_id: Task identifier.

        Returns:
            TaskStatus with current state and relevant data.

        Raises:
            TaskNotFoundError: If task is not found.
        """
        logger.debug(f"Getting status for task {task_id}")

        # Check single-POC suspended tasks first
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

        # Check multi-POC suspended tasks
        multi_suspended = await self._task_store.get_suspended_task_multi_poc(task_id)
        if multi_suspended:
            created_at = datetime.fromisoformat(multi_suspended["created_at"])
            expires_at = datetime.fromisoformat(multi_suspended["expires_at"])
            pending_count = len(multi_suspended["pending_pocs"])
            total_count = len(multi_suspended["poc_emails"])
            received_count = total_count - pending_count

            return TaskStatus(
                task_id=task_id,
                state=TaskState.SUSPENDED,
                message=(
                    f"Waiting for {pending_count} of {total_count} POC replies "
                    f"({received_count} received)"
                ),
                poc_email=", ".join(multi_suspended["pending_pocs"]),
                created_at=created_at,
                expires_at=expires_at,
            )

        # Check resuming tasks (in-flight processing after webhooks received)
        async with self._lock:
            if task_id in self._resuming_tasks:
                info = self._resuming_tasks[task_id]
                poc_count = len(info["poc_emails"])
                return TaskStatus(
                    task_id=task_id,
                    state=TaskState.WORKING,
                    message=f"Processing replies from {poc_count} POC(s)",
                    poc_email=", ".join(info["poc_emails"]),
                    created_at=info["started_at"],
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

    async def save_result(
        self,
        task_id: str,
        status: str,
        result: Optional[dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        """
        Save a task result to persistent storage.

        Called by the executor when a task completes without suspension,
        or when a task fails during execution.

        Args:
            task_id: Task identifier.
            status: Task status ('completed' or 'failed').
            result: Optional result data for completed tasks.
            error: Optional error message for failed tasks.
        """
        logger.info(f"Saving result for task {task_id}: status={status}")
        await self._task_store.save_result(
            task_id=task_id,
            status=status,
            result=result,
            error=error,
        )

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

        # Get multi-POC suspended tasks (parallel processing mode)
        suspended_multi = await self._task_store.get_all_suspended_tasks_multi_poc()
        logger.debug(f"Found {len(suspended_multi)} multi-POC suspended tasks")
        for task in suspended_multi:
            created_at = datetime.fromisoformat(task["created_at"])
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)

            expires_at = datetime.fromisoformat(task["expires_at"])
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)

            # Calculate progress: how many POCs have replied vs total
            poc_emails = task["poc_emails"]
            pending_pocs = task["pending_pocs"]
            received_count = len(poc_emails) - len(pending_pocs)
            total_count = len(poc_emails)

            # Build informative message showing progress
            message = f"Waiting for replies: {received_count}/{total_count} received"

            tasks.append(TaskStatus(
                task_id=task["task_id"],
                state=TaskState.SUSPENDED,
                message=message,
                poc_email=", ".join(poc_emails),
                created_at=created_at,
                expires_at=expires_at,
            ))

        # Get resuming tasks (in-flight processing after webhooks received)
        async with self._lock:
            for task_id, info in self._resuming_tasks.items():
                poc_count = len(info["poc_emails"])
                tasks.append(TaskStatus(
                    task_id=task_id,
                    state=TaskState.WORKING,
                    message=f"Processing replies from {poc_count} POC(s)",
                    poc_email=", ".join(info["poc_emails"]),
                    created_at=info["started_at"],
                ))
        logger.debug(f"Found {len(self._resuming_tasks)} resuming tasks")

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
        """Clean up expired suspended tasks (both single-POC and multi-POC)."""
        logger.debug("Running expired task cleanup")

        try:
            # Handle single-POC expired tasks
            expired_tasks = await self._task_store.get_expired_tasks()

            for task in expired_tasks:
                await self._handle_expired_task(
                    task["task_id"],
                    task["poc_email"],
                )

            if expired_tasks:
                logger.info(f"Cleaned up {len(expired_tasks)} expired single-POC tasks")

            # Handle multi-POC expired tasks
            expired_multi_tasks = await self._task_store.get_expired_tasks_multi_poc()

            for task in expired_multi_tasks:
                await self._handle_expired_task_multi_poc(
                    task["task_id"],
                    task["poc_emails"],
                )

            if expired_multi_tasks:
                logger.info(f"Cleaned up {len(expired_multi_tasks)} expired multi-POC tasks")

        except Exception as e:
            logger.error(f"Error during expired task cleanup: {e}")

    async def _handle_expired_task(self, task_id: str, poc_email: str) -> None:
        """Handle an expired task - remove from state and store failure."""
        logger.info(f"Handling expired task {task_id}")

        # Remove from in-memory mapping
        async with self._lock:
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

        logger.info(f"Expired task {task_id} cleaned up")

    async def _handle_expired_task_multi_poc(
        self, task_id: str, poc_emails: list[str]
    ) -> None:
        """Handle an expired multi-POC task - remove from state and store failure."""
        logger.info(f"Handling expired multi-POC task {task_id} with POCs: {poc_emails}")

        # Remove all POCs from in-memory mapping
        async with self._lock:
            for poc_email in poc_emails:
                poc_lower = poc_email.lower()
                if poc_lower in self._poc_to_task:
                    del self._poc_to_task[poc_lower]
                    logger.debug(f"Removed expired POC mapping: {poc_lower}")

        # Remove from suspended_tasks_multi table
        await self._task_store.remove_suspended_task_multi_poc(task_id)

        # Store failure result
        await self._task_store.save_result(
            task_id=task_id,
            status="failed",
            error=f"Task expired: no replies received within {self._settings.task_suspend_timeout_seconds} seconds",
        )

        logger.info(f"Expired multi-POC task {task_id} cleaned up")

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def get_registered_pocs(self) -> list[str]:
        """
        Get list of POC emails with suspended tasks.

        Returns:
            List of POC email addresses (lowercase).
        """
        return list(self._poc_to_task.keys())

    def get_task_for_poc(self, poc_email: str) -> Optional[str]:
        """
        Get task ID for a POC email.

        Args:
            poc_email: POC email address.

        Returns:
            Task ID or None if not found.
        """
        return self._poc_to_task.get(poc_email.lower())

    @property
    def suspended_task_count(self) -> int:
        """Get number of suspended tasks."""
        return len(self._poc_to_task)
