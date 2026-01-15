"""
DAG Route - REST API for multi-POC dependency graph visualization.

Provides GET /tasks/{task_id}/dag endpoint for retrieving the
DAG structure for multi-POC orchestration visualization.
"""

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from mail_agent.a2a.progress_store import ProgressStore
from mail_agent.task_manager import TaskManager


logger = logging.getLogger(__name__)


# ============================================================================
# Response Models
# ============================================================================


class DAGNode(BaseModel):
    """A node in the DAG representing a POC."""

    id: str = Field(description="POC identifier")
    email: str = Field(description="POC email address")
    status: str = Field(description="POC status (pending, in_progress, waiting, completed, failed)")
    label: str = Field(description="Display label for the node")
    is_dynamic: bool = Field(default=False, description="Whether this POC was dynamically spawned")
    attempts: int = Field(default=0, description="Number of attempts made")
    max_attempts: int = Field(default=15, description="Maximum attempts allowed")


class DAGEdge(BaseModel):
    """An edge in the DAG representing a dependency."""

    source: str = Field(description="Source POC ID (dependency)")
    target: str = Field(description="Target POC ID (dependent)")


class DAGResponse(BaseModel):
    """Response model for DAG endpoint."""

    task_id: str = Field(description="Task identifier")
    phase: str = Field(description="Current orchestration phase")
    global_status: str = Field(description="Overall task status")
    nodes: list[DAGNode] = Field(description="POC nodes in the DAG")
    edges: list[DAGEdge] = Field(description="Dependency edges in the DAG")
    progress: dict[str, int] = Field(description="Aggregate progress counts")
    global_success_criteria: Optional[str] = Field(
        default=None,
        description="Global success criteria for the task"
    )


class DAGNotFoundResponse(BaseModel):
    """Response model for DAG not found error."""

    error: str = Field(description="Error message")
    task_id: str = Field(description="The task ID that was not found")


# ============================================================================
# Router Factory
# ============================================================================


def create_dag_router(
    task_manager: TaskManager,
    progress_store: ProgressStore,
) -> APIRouter:
    """
    Create the DAG router with dependency injection.

    Args:
        task_manager: TaskManager instance for querying task state.
        progress_store: ProgressStore for getting latest progress events.

    Returns:
        Configured APIRouter with DAG endpoint.
    """
    router = APIRouter(prefix="/tasks", tags=["dag"])

    @router.get(
        "/{task_id}/dag",
        response_model=DAGResponse,
        responses={
            200: {"description": "DAG retrieved successfully"},
            404: {
                "description": "Task not found",
                "model": DAGNotFoundResponse,
            },
        },
        summary="Get task DAG",
        description="Get the dependency graph for a multi-POC task visualization.",
    )
    async def get_task_dag(task_id: str) -> DAGResponse:
        """
        Get the DAG structure for a task.

        Returns the POC nodes, dependency edges, and current status
        for visualization with Cytoscape.js or similar libraries.

        Args:
            task_id: The unique task identifier.

        Returns:
            DAGResponse with nodes, edges, and status information.

        Raises:
            HTTPException 404: If task is not found.
        """
        logger.info(f"GET /tasks/{task_id}/dag - retrieving DAG")

        try:
            # Try to get DAG from progress store events
            dag_data = await _extract_dag_from_progress(task_id, progress_store)

            if dag_data:
                logger.info(
                    f"GET /tasks/{task_id}/dag - "
                    f"nodes={len(dag_data['nodes'])}, edges={len(dag_data['edges'])}"
                )
                return DAGResponse(**dag_data)

            # Fall back to task manager state if no progress events
            dag_data = await _extract_dag_from_task_manager(task_id, task_manager)

            if dag_data:
                logger.info(
                    f"GET /tasks/{task_id}/dag (from task_manager) - "
                    f"nodes={len(dag_data['nodes'])}, edges={len(dag_data['edges'])}"
                )
                return DAGResponse(**dag_data)

            # Task not found
            logger.warning(f"GET /tasks/{task_id}/dag - not found")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "Task not found", "task_id": task_id},
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"GET /tasks/{task_id}/dag - error: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"error": str(e), "task_id": task_id},
            )

    return router


async def _extract_dag_from_progress(
    task_id: str,
    progress_store: ProgressStore,
) -> Optional[dict[str, Any]]:
    """
    Extract DAG data from progress store events.

    Looks for the latest events with poc_progress and phase information
    to reconstruct the DAG state.

    Args:
        task_id: Task identifier.
        progress_store: Progress store instance.

    Returns:
        DAG data dictionary or None if not available.
    """
    if not progress_store.has_task(task_id):
        return None

    try:
        events = progress_store.get_events(task_id)
    except KeyError:
        return None

    if not events:
        return None

    # Find the latest event with relevant data
    latest_phase = "unknown"
    latest_poc_progress = None
    global_status = "running"
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    poc_states: dict[str, dict[str, Any]] = {}

    for event in events:
        if event.phase:
            latest_phase = event.phase

        if event.poc_progress:
            latest_poc_progress = event.poc_progress

        # Track POC states from events
        if event.poc_id and event.poc_email:
            poc_states[event.poc_id] = {
                "id": event.poc_id,
                "email": event.poc_email,
                "status": _infer_status_from_event(event),
                "is_dynamic": event.dynamic_poc_spawned or False,
            }

        # Check for terminal states
        if event.state.value == "completed":
            global_status = "completed"
        elif event.state.value == "failed":
            global_status = "failed"

    # Build nodes from tracked POC states
    for poc_id, poc_data in poc_states.items():
        nodes.append(DAGNode(
            id=poc_data["id"],
            email=poc_data["email"],
            status=poc_data["status"],
            label=_make_label(poc_data["email"]),
            is_dynamic=poc_data["is_dynamic"],
        ).model_dump())

    # Build progress dict
    progress = {}
    if latest_poc_progress:
        progress = {
            "total": latest_poc_progress.total,
            "pending": latest_poc_progress.pending,
            "in_progress": latest_poc_progress.in_progress,
            "waiting": latest_poc_progress.waiting,
            "completed": latest_poc_progress.completed,
            "failed": latest_poc_progress.failed,
        }

    # Only return if we have meaningful data
    if not nodes and not latest_poc_progress:
        return None

    return {
        "task_id": task_id,
        "phase": latest_phase,
        "global_status": global_status,
        "nodes": nodes,
        "edges": edges,
        "progress": progress,
    }


async def _extract_dag_from_task_manager(
    task_id: str,
    task_manager: TaskManager,
) -> Optional[dict[str, Any]]:
    """
    Extract DAG data from task manager state.

    Creates a minimal DAG representation based on waiting POCs.

    Args:
        task_id: Task identifier.
        task_manager: Task manager instance.

    Returns:
        DAG data dictionary or None if task not found.
    """
    # Check if task has any waiting POCs
    waiting_pocs = task_manager.get_waiting_pocs_for_task(task_id)

    if not waiting_pocs:
        # Check if task exists in any form
        try:
            status = await task_manager.get_task_status(task_id)
        except Exception:
            return None

        # Task exists but no multi-POC data - return minimal response
        return {
            "task_id": task_id,
            "phase": "execution",
            "global_status": status.state.value,
            "nodes": [],
            "edges": [],
            "progress": {"total": 1, "pending": 0, "in_progress": 0, "waiting": 0, "completed": 0, "failed": 0},
        }

    # Build nodes from waiting POCs
    nodes = []
    for poc_id in waiting_pocs:
        # Try to find the email from registered POCs
        email = _find_email_for_poc(task_id, poc_id, task_manager)
        nodes.append(DAGNode(
            id=poc_id,
            email=email or f"POC {poc_id}",
            status="waiting",
            label=_make_label(email) if email else poc_id,
        ).model_dump())

    return {
        "task_id": task_id,
        "phase": "execution",
        "global_status": "running",
        "nodes": nodes,
        "edges": [],
        "progress": {
            "total": len(nodes),
            "pending": 0,
            "in_progress": 0,
            "waiting": len(nodes),
            "completed": 0,
            "failed": 0,
        },
    }


def _infer_status_from_event(event) -> str:
    """Infer POC status from event type."""
    if event.event_type:
        event_to_status = {
            "poc_started": "in_progress",
            "poc_email_sent": "in_progress",
            "poc_waiting": "waiting",
            "poc_reply_received": "in_progress",
            "poc_validated": "in_progress",
            "poc_retry": "in_progress",
            "poc_redirect": "in_progress",
            "poc_completed": "completed",
            "poc_failed": "failed",
        }
        return event_to_status.get(event.event_type, "pending")
    return "pending"


def _make_label(email: str) -> str:
    """Create a display label from email address."""
    if not email:
        return "Unknown"
    # Use the local part of the email
    local_part = email.split("@")[0]
    # Capitalize first letter
    return local_part.capitalize() if local_part else email


def _find_email_for_poc(task_id: str, poc_id: str, task_manager: TaskManager) -> Optional[str]:
    """Find the email address for a POC ID."""
    # Search through registered POCs
    for email in task_manager.get_registered_pocs():
        result = task_manager.get_task_poc_for_email(email)
        if result and result[0] == task_id and result[1] == poc_id:
            return email
    return None
