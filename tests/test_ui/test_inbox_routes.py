"""
Tests for inbox API routes.
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.responses import HTMLResponse
from starlette.requests import Request

from ui.routes.inbox import clear_all_inboxes
from ui.services.smtp_client import SMTPConnectionError


def _build_request() -> Request:
    """Build a minimal request object for route unit tests."""
    return Request(
        {
            "type": "http",
            "method": "DELETE",
            "path": "/api/inbox/clear-all",
            "headers": [],
        }
    )


@pytest.mark.asyncio
async def test_clear_all_inboxes_route_success() -> None:
    """Test clear-all route returns success partial."""
    request = _build_request()
    smtp_client = AsyncMock()
    smtp_client.clear_all_inboxes = AsyncMock(return_value=5)

    templates = MagicMock()
    templates.TemplateResponse = MagicMock(
        return_value=HTMLResponse("Cleared all inboxes. Deleted 5 email(s).")
    )
    resources = SimpleNamespace(smtp_client=smtp_client, templates=templates)

    with patch("ui.routes.inbox.get_resources", return_value=resources):
        response = await clear_all_inboxes(request)

    assert response.status_code == 200
    assert "Cleared all inboxes" in response.body.decode()
    assert "Deleted 5 email(s)." in response.body.decode()
    smtp_client.clear_all_inboxes.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_clear_all_inboxes_route_error() -> None:
    """Test clear-all route returns error partial on SMTP failure."""
    request = _build_request()
    smtp_client = AsyncMock()
    smtp_client.clear_all_inboxes = AsyncMock(
        side_effect=SMTPConnectionError("mock smtp unavailable")
    )

    templates = MagicMock()
    templates.TemplateResponse = MagicMock(
        return_value=HTMLResponse("Failed to Clear Inboxes: mock smtp unavailable")
    )
    resources = SimpleNamespace(smtp_client=smtp_client, templates=templates)

    with patch("ui.routes.inbox.get_resources", return_value=resources):
        response = await clear_all_inboxes(request)

    assert response.status_code == 200
    assert "Failed to Clear Inboxes" in response.body.decode()
    assert "mock smtp unavailable" in response.body.decode()
    smtp_client.clear_all_inboxes.assert_awaited_once_with()


def test_inbox_template_contains_clear_all_button() -> None:
    """Test inbox template contains clear-all button and status target."""
    template_path = Path("src/ui/templates/inbox/list.html")
    content = template_path.read_text(encoding="utf-8")

    assert "Clear All Inboxes" in content
    assert 'hx-delete="/api/inbox/clear-all"' in content
    assert 'id="inbox-action-status"' in content
