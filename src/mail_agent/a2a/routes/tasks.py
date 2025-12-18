"""
Tasks Route - REST API for polling task status.

Provides GET /tasks/{task_id} endpoint for clients to check on
suspended or completed tasks.
"""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from mail_agent.task_manager import TaskManager, TaskStatus, TaskState


# Import TYPE_CHECKING to avoid circular imports
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mail_agent.a2a.progress_store import ProgressStore
    from mail_agent.a2a.progress_service import ProgressService


logger = logging.getLogger(__name__)


# ============================================================================
# Response Models
# ============================================================================


class TaskStatusResponse(BaseModel):
    """Response model for task status endpoint."""

    task_id: str = Field(description="Unique task identifier")
    state: str = Field(description="Current task state")
    message: str = Field(description="Human-readable status message")
    poc_email: str | None = Field(
        default=None,
        description="POC email if task is waiting for reply",
    )
    created_at: str | None = Field(
        default=None,
        description="Task creation timestamp (ISO format)",
    )
    expires_at: str | None = Field(
        default=None,
        description="Expiration timestamp for suspended tasks (ISO format)",
    )
    completed_at: str | None = Field(
        default=None,
        description="Completion timestamp (ISO format)",
    )
    result: dict[str, Any] | None = Field(
        default=None,
        description="Task result data (for completed tasks)",
    )
    error: str | None = Field(
        default=None,
        description="Error message (for failed tasks)",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "task_id": "task-abc-123",
                    "state": "suspended",
                    "message": "Waiting for reply from poc@example.com",
                    "poc_email": "poc@example.com",
                    "created_at": "2025-12-15T10:00:00+00:00",
                    "expires_at": "2025-12-15T11:00:00+00:00",
                },
                {
                    "task_id": "task-def-456",
                    "state": "completed",
                    "message": "Task completed",
                    "completed_at": "2025-12-15T10:35:00+00:00",
                    "result": {
                        "success": True,
                        "data": "Q4 sales data...",
                    },
                },
            ]
        }
    )


class TaskNotFoundResponse(BaseModel):
    """Response model for task not found error."""

    error: str = Field(description="Error message")
    task_id: str = Field(description="The task ID that was not found")


class ActivityEventResponse(BaseModel):
    """Response model for a single activity event."""

    event_id: int = Field(description="Sequential event ID")
    task_id: str = Field(description="Task identifier")
    state: str = Field(description="Task state at this event")
    node: str | None = Field(default=None, description="Graph node name")
    message: str = Field(description="Progress message")
    poc_email: str | None = Field(default=None, description="POC email")
    result: dict[str, Any] | None = Field(default=None, description="Result data")
    error: str | None = Field(default=None, description="Error message")
    timestamp: str = Field(description="Event timestamp (ISO format)")


class TaskActivityResponse(BaseModel):
    """Response model for task activity history."""

    task_id: str = Field(description="Task identifier")
    events: list[ActivityEventResponse] = Field(description="Activity events")
    event_count: int = Field(description="Total number of events")


# ============================================================================
# Router Factory
# ============================================================================


def create_tasks_router(
    task_manager: TaskManager,
    progress_store: "ProgressStore | None" = None,
    progress_service: "ProgressService | None" = None,
) -> APIRouter:
    """
    Create the tasks router with dependency injection.

    Args:
        task_manager: TaskManager instance for querying task status.
        progress_store: Optional ProgressStore for tracking in-flight tasks.
        progress_service: Optional ProgressService for activity history queries.

    Returns:
        Configured APIRouter with task endpoints.
    """
    router = APIRouter(prefix="/tasks", tags=["tasks"])

    @router.get(
        "/{task_id}",
        response_model=TaskStatusResponse,
        responses={
            200: {"description": "Task status retrieved successfully"},
            404: {
                "description": "Task not found",
                "model": TaskNotFoundResponse,
            },
        },
        summary="Get task status",
        description="Poll the status of a task. Use this endpoint after receiving a 'suspended' SSE event to check when the task completes.",
    )
    async def get_task_status(task_id: str) -> TaskStatusResponse:
        """
        Get the current status of a task.

        Use this endpoint to poll for task completion after the SSE stream
        closes (when task is suspended waiting for POC reply).

        Args:
            task_id: The unique task identifier returned in SSE events.

        Returns:
            TaskStatusResponse with current status and any available result.

        Raises:
            HTTPException 404: If task is not found.
        """
        logger.info(f"GET /tasks/{task_id} - checking status")

        try:
            task_status: TaskStatus = await task_manager.get_task_status(task_id)

            response = TaskStatusResponse(
                task_id=task_status.task_id,
                state=task_status.state.value,
                message=task_status.message,
                poc_email=task_status.poc_email,
                created_at=task_status.created_at.isoformat() if task_status.created_at else None,
                expires_at=task_status.expires_at.isoformat() if task_status.expires_at else None,
                completed_at=task_status.completed_at.isoformat() if task_status.completed_at else None,
                result=task_status.result,
                error=task_status.error,
            )

            logger.info(
                f"GET /tasks/{task_id} - status={task_status.state.value}, "
                f"message={task_status.message}"
            )
            return response

        except Exception as e:
            # Check if it's a not found error
            error_msg = str(e)
            if "not found" in error_msg.lower():
                logger.warning(f"GET /tasks/{task_id} - not found")
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={"error": "Task not found", "task_id": task_id},
                )

            # Other errors
            logger.error(f"GET /tasks/{task_id} - error: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"error": str(e), "task_id": task_id},
            )

    @router.get(
        "",
        summary="List all tasks",
        description="Get a list of all tasks (active, suspended, completed, and failed).",
    )
    async def list_all_tasks_endpoint() -> dict[str, Any]:
        """
        List all tasks.

        Returns all tasks from the system including active (in-flight),
        suspended (waiting for reply), completed, and failed tasks.

        Returns:
            Dictionary with tasks list containing task details.
        """
        logger.info("GET /tasks - listing all tasks")

        # Get suspended and completed/failed tasks from task manager
        all_tasks = await task_manager.list_all_tasks()

        # Convert to list of dicts
        tasks_list = [
            {
                "task_id": task.task_id,
                "state": task.state.value,
                "message": task.message,
                "poc_email": task.poc_email,
                "created_at": task.created_at.isoformat() if task.created_at else None,
                "completed_at": task.completed_at.isoformat() if task.completed_at else None,
                "result": task.result,
                "error": task.error,
            }
            for task in all_tasks
        ]

        # Get active (in-flight) tasks from progress store
        if progress_store is not None:
            active_tasks = progress_store.get_active_tasks()
            existing_task_ids = {t["task_id"] for t in tasks_list}

            for active_task in active_tasks:
                # Skip if already in list (shouldn't happen, but be safe)
                if active_task["task_id"] in existing_task_ids:
                    continue

                tasks_list.append({
                    "task_id": active_task["task_id"],
                    "state": active_task["state"],
                    "message": active_task["latest_message"],
                    "poc_email": None,
                    "created_at": active_task["started_at"],
                    "completed_at": None,
                    "result": None,
                    "error": None,
                })

            logger.info(
                f"GET /tasks - found {len(active_tasks)} active tasks, "
                f"{len(all_tasks)} persisted tasks"
            )

        logger.info(f"GET /tasks - returning {len(tasks_list)} tasks")

        return {"tasks": tasks_list}

    @router.get(
        "/{task_id}/activity",
        response_model=TaskActivityResponse,
        responses={
            200: {"description": "Activity history retrieved successfully"},
            404: {
                "description": "Task not found or no activity recorded",
                "model": TaskNotFoundResponse,
            },
            503: {
                "description": "Progress service not available",
            },
        },
        summary="Get task activity history",
        description=(
            "Get the full activity history for a task. Returns all progress events "
            "from task start to completion, including webhook arrivals and validation results."
        ),
    )
    async def get_task_activity(task_id: str) -> TaskActivityResponse:
        """
        Get the full activity history for a task.

        Returns all progress events from the database, providing a complete
        audit trail of task execution including:
        - Initial task creation
        - Node executions (parse, compose, send, etc.)
        - Webhook arrivals (POC replies)
        - Validation results
        - Task completion or failure

        Args:
            task_id: The unique task identifier.

        Returns:
            TaskActivityResponse with list of activity events.

        Raises:
            HTTPException 404: If task not found or no activity recorded.
            HTTPException 503: If progress service not available.
        """
        logger.info(f"GET /tasks/{task_id}/activity - fetching activity history")

        if progress_service is None:
            logger.error(
                f"GET /tasks/{task_id}/activity - progress service not available"
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "error": "Progress service not available",
                    "task_id": task_id,
                },
            )

        try:
            events = await progress_service.get_activity_history(task_id)

            if not events:
                # Check if task exists at all
                try:
                    await task_manager.get_task_status(task_id)
                    # Task exists but no events - return empty list
                    logger.info(
                        f"GET /tasks/{task_id}/activity - task exists but no events"
                    )
                except Exception:
                    logger.warning(f"GET /tasks/{task_id}/activity - task not found")
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail={"error": "Task not found", "task_id": task_id},
                    )

            # Convert to response model
            event_responses = [
                ActivityEventResponse(
                    event_id=event["event_id"],
                    task_id=event["task_id"],
                    state=event["state"],
                    node=event.get("node"),
                    message=event["message"],
                    poc_email=event.get("poc_email"),
                    result=event.get("result"),
                    error=event.get("error"),
                    timestamp=event["timestamp"],
                )
                for event in events
            ]

            logger.info(
                f"GET /tasks/{task_id}/activity - returning {len(event_responses)} events"
            )

            return TaskActivityResponse(
                task_id=task_id,
                events=event_responses,
                event_count=len(event_responses),
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"GET /tasks/{task_id}/activity - error: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"error": str(e), "task_id": task_id},
            )

    return router
