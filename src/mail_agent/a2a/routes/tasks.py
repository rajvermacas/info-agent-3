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


logger = logging.getLogger(__name__)


# ============================================================================
# Response Models
# ============================================================================


class TaskStatusResponse(BaseModel):
    """Response model for task status endpoint."""

    task_id: str = Field(description="Unique task identifier")
    status: str = Field(description="Current task status")
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
                    "status": "suspended",
                    "message": "Waiting for reply from poc@example.com",
                    "poc_email": "poc@example.com",
                    "created_at": "2025-12-15T10:00:00+00:00",
                    "expires_at": "2025-12-15T11:00:00+00:00",
                },
                {
                    "task_id": "task-def-456",
                    "status": "completed",
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


# ============================================================================
# Router Factory
# ============================================================================


def create_tasks_router(task_manager: TaskManager) -> APIRouter:
    """
    Create the tasks router with dependency injection.

    Args:
        task_manager: TaskManager instance for querying task status.

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
                status=task_status.state.value,
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
        summary="List suspended tasks",
        description="Get a list of currently suspended tasks (for debugging/monitoring).",
    )
    async def list_suspended_tasks() -> dict[str, Any]:
        """
        List all currently suspended tasks.

        This endpoint is primarily for debugging and monitoring purposes.

        Returns:
            Dictionary with count and list of POC emails with pending tasks.
        """
        logger.info("GET /tasks - listing suspended tasks")

        pocs = task_manager.get_registered_pocs()
        count = task_manager.suspended_task_count

        logger.info(f"GET /tasks - {count} suspended tasks")

        return {
            "count": count,
            "suspended_pocs": pocs,
        }

    return router
