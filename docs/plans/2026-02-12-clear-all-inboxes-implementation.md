# Clear All Inboxes Button Implementation Plan

**Goal:** Add a destructive button on the Inbox page that clears all inboxes/emails by calling Mock SMTP `DELETE /api/clear`, with explicit success/error feedback and fail-fast error handling.

**Architecture:** Add one UI API endpoint (`/api/inbox/clear-all`) that proxies to a new SMTP client service method (`clear_all_inboxes`). The page button calls the UI endpoint via HTMX and then refreshes inbox/email panels client-side on success. Errors are surfaced through existing error partials and detailed logs.

**Tech Stack:** FastAPI, Jinja2 templates, HTMX, httpx, pytest (+ pytest-asyncio), unittest.mock

---

### Task 1: SMTP Client Clear-All Method (TDD)

**Files:**
- Modify: `tests/test_ui/test_services.py`
- Modify: `src/ui/services/smtp_client.py`

**Step 1: Write the failing tests (success + fail-fast validation)**

```python
@pytest.mark.asyncio
async def test_clear_all_inboxes_success(self, settings: Settings) -> None:
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"message": "Cleared all inboxes", "deleted_count": 8}
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.delete = AsyncMock(return_value=mock_response)
        mock_client.aclose = AsyncMock()
        mock_client_class.return_value = mock_client

        client = SMTPClientService(settings)
        result = await client.clear_all_inboxes()

        assert result == 8
        mock_client.delete.assert_awaited_once_with("/api/clear")
        await client.close()


@pytest.mark.asyncio
async def test_clear_all_inboxes_missing_deleted_count_fails_fast(self, settings: Settings) -> None:
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"message": "Cleared all inboxes"}
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.delete = AsyncMock(return_value=mock_response)
        mock_client.aclose = AsyncMock()
        mock_client_class.return_value = mock_client

        client = SMTPClientService(settings)
        with pytest.raises(SMTPConnectionError, match="deleted_count"):
            await client.clear_all_inboxes()
        await client.close()
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ui/test_services.py -k clear_all_inboxes -v`
Expected: FAIL with `AttributeError: 'SMTPClientService' object has no attribute 'clear_all_inboxes'`

**Step 3: Write minimal implementation in service**

```python
async def clear_all_inboxes(self) -> int:
    """Clear all inboxes from Mock SMTP and return deleted email count."""
    logger.warning("Clearing all inboxes via Mock SMTP API")
    client = await self._get_client()

    try:
        response = await client.delete("/api/clear")
        response.raise_for_status()
        data = response.json()

        if "deleted_count" not in data:
            raise SMTPConnectionError(
                "Invalid clear-all response: missing required field 'deleted_count'"
            )

        deleted_count = data["deleted_count"]
        if not isinstance(deleted_count, int):
            raise SMTPConnectionError(
                "Invalid clear-all response: 'deleted_count' must be an integer"
            )

        logger.warning("Cleared all inboxes successfully (deleted_count=%d)", deleted_count)
        return deleted_count
    except httpx.HTTPStatusError as e:
        logger.error("HTTP error clearing all inboxes: %s", e)
        raise SMTPConnectionError(f"HTTP error: {e.response.status_code}") from e
    except ValueError as e:
        logger.error("Invalid JSON while clearing all inboxes: %s", e)
        raise SMTPConnectionError("Invalid JSON response from clear-all endpoint") from e
    except SMTPConnectionError:
        raise
    except Exception as e:
        logger.error("Unexpected error clearing all inboxes: %s", e)
        raise SMTPConnectionError(f"Unexpected error: {e}") from e
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ui/test_services.py -k clear_all_inboxes -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_ui/test_services.py src/ui/services/smtp_client.py
git commit -m "feat(ui): add clear-all inboxes smtp client method"
```

### Task 2: UI Route for Clear-All (TDD)

**Files:**
- Create: `tests/test_ui/test_inbox_routes.py`
- Modify: `src/ui/routes/inbox.py`
- Modify: `tests/test_ui/test_pages.py`

**Step 1: Write failing route tests**

```python
from ui.services.smtp_client import SMTPConnectionError


def test_clear_all_inboxes_route_success(test_client, mock_smtp_client):
    mock_smtp_client.clear_all_inboxes = AsyncMock(return_value=5)

    response = test_client.delete("/api/inbox/clear-all")

    assert response.status_code == 200
    assert "Cleared all inboxes" in response.text


def test_clear_all_inboxes_route_error(test_client, mock_smtp_client):
    mock_smtp_client.clear_all_inboxes = AsyncMock(
        side_effect=SMTPConnectionError("mock smtp unavailable")
    )

    response = test_client.delete("/api/inbox/clear-all")

    assert response.status_code == 200
    assert "Failed to Clear Inboxes" in response.text
```

Also extend router configuration test:

```python
def test_inbox_router_has_routes(self) -> None:
    from ui.routes.inbox import router
    route_paths = [r.path for r in router.routes]
    assert any("/clear-all" in p for p in route_paths)
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ui/test_inbox_routes.py tests/test_ui/test_pages.py::TestUIRouterConfiguration::test_inbox_router_has_routes -v`
Expected: FAIL with 404 or missing route assertion.

**Step 3: Write minimal route implementation**

```python
@router.delete("/clear-all", response_class=HTMLResponse)
async def clear_all_inboxes(request: Request) -> HTMLResponse:
    """Clear all inboxes and return status partial."""
    logger.warning("Clear-all inbox request received")
    resources = get_resources()

    try:
        deleted_count = await resources.smtp_client.clear_all_inboxes()
        return resources.templates.TemplateResponse(
            "partials/inbox_clear_result.html",
            {
                "request": request,
                "success": True,
                "deleted_count": deleted_count,
            },
        )
    except SMTPClientError as e:
        logger.error("SMTP error clearing all inboxes: %s", e)
        return resources.templates.TemplateResponse(
            "partials/error.html",
            {
                "request": request,
                "error": str(e),
                "title": "Failed to Clear Inboxes",
            },
        )
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ui/test_inbox_routes.py tests/test_ui/test_pages.py::TestUIRouterConfiguration::test_inbox_router_has_routes -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_ui/test_inbox_routes.py tests/test_ui/test_pages.py src/ui/routes/inbox.py
git commit -m "feat(ui): add clear-all inbox route"
```

### Task 3: Inbox UI Button + Status Partial (TDD)

**Files:**
- Modify: `src/ui/templates/inbox/list.html`
- Create: `src/ui/templates/partials/inbox_clear_result.html`
- Modify: `tests/test_ui/test_inbox_routes.py`

**Step 1: Write failing UI assertions**

```python
def test_inbox_page_contains_clear_all_button(test_client):
    response = test_client.get("/inbox")
    assert response.status_code == 200
    assert "Clear All Inboxes" in response.text
    assert "hx-delete=\"/api/inbox/clear-all\"" in response.text
    assert "id=\"inbox-action-status\"" in response.text
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_ui/test_inbox_routes.py::test_inbox_page_contains_clear_all_button -v`
Expected: FAIL because button/status container do not exist.

**Step 3: Write minimal template changes + success partial**

`src/ui/templates/inbox/list.html` (add button + status region):

```html
<div class="ml-4 self-end flex items-center space-x-2">
    <button
        type="button"
        hx-delete="/api/inbox/clear-all"
        hx-target="#inbox-action-status"
        hx-swap="innerHTML"
        hx-disabled-elt="this"
        hx-on::after-request="if (event.detail.successful) { refreshAfterClearAll(); }"
        class="inline-flex items-center px-3 py-2 border border-red-300 shadow-sm text-sm leading-4 font-medium rounded-md text-red-700 bg-red-50 hover:bg-red-100 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-red-500"
    >
        Clear All Inboxes
    </button>
    <button type="button" hx-get="/api/inbox/list" hx-target="#inbox-list-container" hx-swap="innerHTML" class="...">
        Refresh
    </button>
</div>

<div id="inbox-action-status" class="mt-4"></div>
```

`src/ui/templates/inbox/list.html` (add JS helper):

```html
<script>
function refreshAfterClearAll() {
    const email = document.getElementById('inbox-select').value;
    htmx.ajax('GET', '/api/inbox/list', '#inbox-list-container');
    htmx.ajax('GET', '/api/inbox/' + encodeURIComponent(email) + '/emails', '#email-list-container');

    const detailContainer = document.getElementById('email-detail-container');
    detailContainer.classList.add('hidden');
    detailContainer.innerHTML = '';

    const replyContainer = document.getElementById('reply-form-container');
    replyContainer.classList.add('hidden');
    replyContainer.innerHTML = '';
}
</script>
```

`src/ui/templates/partials/inbox_clear_result.html`:

```html
{% if success %}
<div class="bg-green-50 border border-green-200 rounded-lg p-4">
    <h3 class="text-sm font-medium text-green-800">Cleared all inboxes</h3>
    <p class="mt-1 text-sm text-green-700">Deleted {{ deleted_count }} email(s).</p>
</div>
{% endif %}
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ui/test_inbox_routes.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/ui/templates/inbox/list.html src/ui/templates/partials/inbox_clear_result.html tests/test_ui/test_inbox_routes.py
git commit -m "feat(ui): add clear-all button to inbox page"
```

### Task 4: Regression Run + Final Commit Hygiene

**Files:**
- Modify: `src/ui/routes/inbox.py` (if import ordering/log polish needed)
- Modify: `src/ui/services/smtp_client.py` (if lint/test polish needed)
- Modify: `tests/test_ui/test_services.py`
- Modify: `tests/test_ui/test_inbox_routes.py`

**Step 1: Run targeted regression suite**

Run: `pytest tests/test_ui/test_services.py tests/test_ui/test_inbox_routes.py tests/test_ui/test_pages.py -v`
Expected: PASS

**Step 2: Run full UI test suite**

Run: `pytest tests/test_ui -v`
Expected: PASS

**Step 3: Check working tree and diff**

Run: `git status --short && git diff --stat`
Expected: only intended files changed.

**Step 4: Squash/fixups only if explicitly requested (default: keep commits)**

Run: `git log --oneline -n 5`
Expected: clear sequence of small commits for service, route, and UI.

**Step 5: Final commit (if Task 4 introduced additional edits)**

```bash
git add -A
git commit -m "test(ui): finalize clear-all inbox coverage"
```

## Notes for Execution
- Keep route/service functions under 80 lines each by extracting helper validation function if needed.
- Do not use fallback/default values for `deleted_count`; missing/invalid data must raise explicit exception.
- Keep logs detailed at info/warning/error levels for action start, API status, validation outcome, and result counts.
- Keep modified files under 800 lines.
