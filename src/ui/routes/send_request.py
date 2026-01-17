"""
Send request API routes.

Handles sending tasks to the A2A server.
"""

import logging

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from ui.main import get_resources
from ui.services.a2a_client import A2AClientError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/send", tags=["Send Request"])


@router.post("/submit", response_class=HTMLResponse)
async def submit_request(
    request: Request,
    instruction: str = Form(...),
) -> HTMLResponse:
    """
    Submit a mail request to the A2A server.

    Args:
        request: FastAPI request object.
        instruction: The user instruction (e.g., "Send mail to x@y.com asking for 10 recipes").

    Returns:
        HTML response with task status or error message.
    """
    logger.info("Received send request: %s", instruction[:100])
    resources = get_resources()

    try:
        # Send task to A2A server
        task_info = await resources.a2a_client.send_task(instruction.strip())

        logger.info("Task submitted: %s (state: %s)", task_info.task_id, task_info.state)

        # Return success response with task info
        return resources.templates.TemplateResponse(
            "partials/task_submitted.html",
            {
                "request": request,
                "task_id": task_info.task_id,
                "state": task_info.state,
                "message": task_info.message or "Task submitted successfully",
                "success": True,
            },
        )
    except A2AClientError as e:
        logger.error("A2A error submitting task: %s", e)
        return resources.templates.TemplateResponse(
            "partials/task_submitted.html",
            {
                "request": request,
                "error": str(e),
                "success": False,
            },
        )
    except Exception as e:
        logger.error("Unexpected error submitting task: %s", e)
        return resources.templates.TemplateResponse(
            "partials/task_submitted.html",
            {
                "request": request,
                "error": f"Unexpected error: {e}",
                "success": False,
            },
        )


@router.get("/plan/{task_id}", response_class=HTMLResponse)
async def get_task_plan(request: Request, task_id: str) -> HTMLResponse:
    """
    Render the agent-proposed plan (if available) for a task.
    """
    resources = get_resources()
    try:
        plan = await resources.a2a_client.get_task_plan(task_id)
        return resources.templates.TemplateResponse(
            "partials/task_plan.html",
            {"request": request, "task_id": task_id, "plan": plan},
        )
    except A2AClientError:
        # Plan may not be ready yet; poll for it.
        try:
            task = await resources.a2a_client.get_task_status(task_id)
        except A2AClientError:
            task = None
        return resources.templates.TemplateResponse(
            "partials/task_plan_pending.html",
            {"request": request, "task_id": task_id, "task": task},
        )


@router.post("/plan/{task_id}/decision", response_class=HTMLResponse)
async def submit_plan_decision(
    request: Request,
    task_id: str,
    decision: str = Form(...),
    feedback: str | None = Form(default=None),
) -> HTMLResponse:
    """
    Approve or reject a plan. When rejecting, feedback is required.
    """
    resources = get_resources()
    try:
        await resources.a2a_client.submit_plan_decision(
            task_id=task_id,
            decision=decision,
            feedback=feedback,
        )
        return resources.templates.TemplateResponse(
            "partials/task_plan_decision_submitted.html",
            {
                "request": request,
                "task_id": task_id,
                "decision": decision,
            },
        )
    except A2AClientError as e:
        return resources.templates.TemplateResponse(
            "partials/error.html",
            {
                "request": request,
                "error": str(e),
                "title": "Failed to Submit Plan Decision",
            },
        )
