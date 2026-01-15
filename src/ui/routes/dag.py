"""
DAG Visualization Route - REST API for multi-POC DAG display.

Handles fetching and rendering DAG visualization for tasks.
"""

import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ui.main import get_resources
from ui.services.a2a_client import A2AClientError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["DAG"])


@router.get("/task/{task_id}/dag", response_class=HTMLResponse)
async def get_task_dag(request: Request, task_id: str) -> HTMLResponse:
    """
    Get DAG visualization for a task.

    Fetches the DAG data from A2A server and renders the visualization.

    Args:
        request: FastAPI request object.
        task_id: The task identifier.

    Returns:
        HTML partial with DAG visualization component.
    """
    logger.info("GET /dashboard/task/%s/dag - fetching DAG", task_id)
    resources = get_resources()

    try:
        # Fetch DAG data from A2A server
        dag_data = await _fetch_dag_data(task_id)

        logger.info(
            "GET /dashboard/task/%s/dag - nodes=%d, edges=%d",
            task_id,
            len(dag_data.get("nodes", [])),
            len(dag_data.get("edges", [])),
        )

        return resources.templates.TemplateResponse(
            "partials/dag_visualization.html",
            {
                "request": request,
                "task_id": task_id,
                "dag": dag_data,
            },
        )
    except A2AClientError as e:
        logger.error("A2A error fetching DAG for task %s: %s", task_id, e)
        return resources.templates.TemplateResponse(
            "partials/error.html",
            {
                "request": request,
                "error": str(e),
                "title": "Failed to Load DAG",
            },
        )
    except Exception as e:
        logger.error("Unexpected error fetching DAG for task %s: %s", task_id, e)
        return resources.templates.TemplateResponse(
            "partials/error.html",
            {
                "request": request,
                "error": f"Unexpected error: {e}",
                "title": "Failed to Load DAG",
            },
        )


@router.get("/task/{task_id}/dag/data")
async def get_task_dag_data(task_id: str) -> dict[str, Any]:
    """
    Get raw DAG data for a task (JSON response).

    Used by JavaScript for real-time updates via polling.

    Args:
        task_id: The task identifier.

    Returns:
        DAG data dictionary with nodes, edges, phase, and progress.
    """
    logger.debug("GET /dashboard/task/%s/dag/data - fetching raw DAG data", task_id)

    try:
        dag_data = await _fetch_dag_data(task_id)
        return dag_data
    except Exception as e:
        logger.error("Error fetching DAG data for task %s: %s", task_id, e)
        return {
            "error": str(e),
            "task_id": task_id,
            "nodes": [],
            "edges": [],
            "phase": "unknown",
            "global_status": "error",
            "progress": {},
        }


async def _fetch_dag_data(task_id: str) -> dict[str, Any]:
    """
    Fetch DAG data from A2A server.

    Args:
        task_id: The task identifier.

    Returns:
        DAG data dictionary.

    Raises:
        A2AClientError: If request fails.
    """
    import httpx

    resources = get_resources()
    base_url = resources.settings.a2a_server_url.rstrip("/")
    url = f"{base_url}/api/tasks/{task_id}/dag"

    logger.debug("Fetching DAG from: %s", url)

    async with httpx.AsyncClient(timeout=resources.settings.http_timeout_seconds) as client:
        response = await client.get(url)

        if response.status_code == 404:
            logger.warning("DAG not found for task: %s", task_id)
            # Return empty DAG structure for tasks without multi-POC data
            return {
                "task_id": task_id,
                "phase": "unknown",
                "global_status": "unknown",
                "nodes": [],
                "edges": [],
                "progress": {},
            }

        response.raise_for_status()
        return response.json()
