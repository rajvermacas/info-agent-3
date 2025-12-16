"""
Page routes for UI.

Handles rendering of HTML pages.
"""

import logging

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ui.main import get_resources

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Pages"])


@router.get("/", response_class=HTMLResponse)
async def home_page(request: Request) -> HTMLResponse:
    """Render the home page."""
    logger.info("Rendering home page")
    resources = get_resources()

    return resources.templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "active_page": "home",
        },
    )


@router.get("/send", response_class=HTMLResponse)
async def send_request_page(request: Request) -> HTMLResponse:
    """Render the send request page."""
    logger.info("Rendering send request page")
    resources = get_resources()

    return resources.templates.TemplateResponse(
        "send_request.html",
        {
            "request": request,
            "active_page": "send",
        },
    )


@router.get("/inbox", response_class=HTMLResponse)
async def inbox_page(request: Request) -> HTMLResponse:
    """Render the inbox page."""
    logger.info("Rendering inbox page")
    resources = get_resources()

    # Get default inbox email from settings
    default_inbox = resources.settings.default_inbox_email

    return resources.templates.TemplateResponse(
        "inbox/list.html",
        {
            "request": request,
            "active_page": "inbox",
            "default_inbox": default_inbox,
        },
    )


@router.get("/inbox/{email_address}", response_class=HTMLResponse)
async def inbox_detail_page(request: Request, email_address: str) -> HTMLResponse:
    """Render the inbox detail page for a specific email address."""
    logger.info("Rendering inbox page for: %s", email_address)
    resources = get_resources()

    return resources.templates.TemplateResponse(
        "inbox/list.html",
        {
            "request": request,
            "active_page": "inbox",
            "default_inbox": email_address,
        },
    )


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request) -> HTMLResponse:
    """Render the dashboard page."""
    logger.info("Rendering dashboard page")
    resources = get_resources()

    return resources.templates.TemplateResponse(
        "dashboard/index.html",
        {
            "request": request,
            "active_page": "dashboard",
        },
    )
