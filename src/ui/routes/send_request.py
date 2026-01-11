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
        task_info = await resources.a2a_client.send_task(instruction)

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
