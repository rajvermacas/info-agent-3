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

class TaskPlanResponse(BaseModel):
    """Response model for a task's proposed plan (when awaiting approval)."""

    task_id: str = Field(description="Unique task identifier")
    plan_status: str = Field(description="Plan status: pending_approval, approved, rejected")
    plan: dict[str, Any] = Field(description="Plan payload (agent_plan_steps, poc_plans, etc.)")


class PlanDecisionRequest(BaseModel):
    """Request model for approving or rejecting an agent plan."""

    decision: str = Field(description="approve or reject")
    feedback: str | None = Field(
        default=None,
        description="Required when decision=reject; user feedback for regenerating the plan",
    )


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
        "/{task_id}/plan",
        response_model=TaskPlanResponse,
        summary="Get proposed plan for a task",
        description="Return the agent-proposed plan when the task is suspended awaiting user approval.",
    )
    async def get_task_plan(task_id: str) -> TaskPlanResponse:
        task_info = await task_manager.get_suspended_task_info(task_id)
        if task_info is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "Task not found or not suspended", "task_id": task_id},
            )

        interrupt_data = task_info.get("interrupt_data") or {}
        if interrupt_data.get("reason") != "awaiting_plan_approval":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "Task is not awaiting plan approval", "task_id": task_id},
            )

        plan = interrupt_data.get("plan") or {}
        plan_status = "pending_approval"
        return TaskPlanResponse(task_id=task_id, plan_status=plan_status, plan=plan)

    @router.post(
        "/{task_id}/plan/decision",
        summary="Approve or reject the proposed plan",
        description="Resume the suspended task using the user's plan decision.",
    )
    async def submit_plan_decision(task_id: str, request: PlanDecisionRequest) -> dict[str, Any]:
        decision = request.decision.strip().lower()
        if decision not in ("approve", "reject"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "decision must be 'approve' or 'reject'", "task_id": task_id},
            )
        if decision == "reject" and not (request.feedback or "").strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "feedback is required when rejecting a plan", "task_id": task_id},
            )

        task_info = await task_manager.get_suspended_task_info(task_id)
        if task_info is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "Task not found or not suspended", "task_id": task_id},
            )

        interrupt_data = task_info.get("interrupt_data") or {}
        if interrupt_data.get("reason") != "awaiting_plan_approval":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"error": "Task is not awaiting plan approval", "task_id": task_id},
            )

        resume_data = {"decision": decision, "feedback": request.feedback}
        resumed = await task_manager.resume_suspended_task(task_id, resume_data)
        if not resumed:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "Task not found or not suspended", "task_id": task_id},
            )

        return {"task_id": task_id, "state": "resumed", "message": "Plan decision received; resuming task."}

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
        description="Get a list of all tasks (suspended, completed, and failed).",
    )
    async def list_all_tasks_endpoint() -> dict[str, Any]:
        """
        List all tasks.

        Returns all tasks from the system including suspended (waiting for reply),
        completed, and failed tasks.

        Returns:
            Dictionary with tasks list containing task details.
        """
        logger.info("GET /tasks - listing all tasks")

        all_tasks = await task_manager.list_all_tasks()

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

        logger.info(f"GET /tasks - returning {len(tasks_list)} tasks")

        return {"tasks": tasks_list}

    return router
