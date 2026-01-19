from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.requests import Request

from ui.routes.send_request import submit_plan_decision


@pytest.mark.asyncio
async def test_submit_plan_decision_reject_renders_polling_partial() -> None:
    templates = MagicMock()
    templates.TemplateResponse = MagicMock(return_value=MagicMock())

    resources = MagicMock()
    resources.a2a_client.submit_plan_decision = AsyncMock(return_value=None)
    resources.templates = templates

    request = Request({"type": "http", "method": "POST", "path": "/"})

    with patch("ui.routes.send_request.get_resources", return_value=resources):
        await submit_plan_decision(
            request=request,
            task_id="test-task-123",
            decision="reject",
            feedback="Please regenerate.",
        )

    templates.TemplateResponse.assert_called()
    template_name = templates.TemplateResponse.call_args.args[0]
    assert template_name == "partials/task_plan_pending.html"

