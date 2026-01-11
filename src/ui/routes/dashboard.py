"""
Dashboard API routes.

Handles task monitoring and results display.
"""

import logging

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ui.main import get_resources
from ui.services.a2a_client import A2AClientError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/tasks", response_class=HTMLResponse)
async def list_tasks(request: Request) -> HTMLResponse:
    """
    List all tasks.

    Returns HTML partial with task list.
    """
    logger.info("Listing all tasks")
    resources = get_resources()

    try:
        tasks = await resources.a2a_client.list_tasks()

        return resources.templates.TemplateResponse(
            "partials/task_list.html",
            {
                "request": request,
                "tasks": tasks,
            },
        )
    except A2AClientError as e:
        logger.error("A2A error listing tasks: %s", e)
        return resources.templates.TemplateResponse(
            "partials/error.html",
            {
                "request": request,
                "error": str(e),
                "title": "Failed to Load Tasks",
            },
        )


@router.get("/task/{task_id}", response_class=HTMLResponse)
async def get_task_detail(request: Request, task_id: str) -> HTMLResponse:
    """
    Get task detail.

    Args:
        task_id: The task ID.

    Returns HTML partial with task detail.
    """
    logger.info("Getting task detail: %s", task_id)
    resources = get_resources()

    try:
        task = await resources.a2a_client.get_task_status(task_id)

        return resources.templates.TemplateResponse(
            "dashboard/task_detail.html",
            {
                "request": request,
                "task": task,
            },
        )
    except A2AClientError as e:
        logger.error("A2A error getting task: %s", e)
        return resources.templates.TemplateResponse(
            "partials/error.html",
            {
                "request": request,
                "error": str(e),
                "title": "Failed to Load Task",
            },
        )


@router.get("/task/{task_id}/status", response_class=HTMLResponse)
async def get_task_status(request: Request, task_id: str) -> HTMLResponse:
    """
    Get task status (for polling).

    Args:
        task_id: The task ID.

    Returns HTML partial with task status badge.
    """
    logger.debug("Getting task status: %s", task_id)
    resources = get_resources()

    try:
        task = await resources.a2a_client.get_task_status(task_id)

        return resources.templates.TemplateResponse(
            "partials/task_status.html",
            {
                "request": request,
                "task": task,
            },
        )
    except A2AClientError as e:
        logger.error("A2A error getting task status: %s", e)
        return resources.templates.TemplateResponse(
            "partials/task_status.html",
            {
                "request": request,
                "task": None,
                "error": str(e),
            },
        )
