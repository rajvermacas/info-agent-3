# Clear All Inboxes Button Design

Date: 2026-02-12
Status: Validated
Owner: UI + Mock SMTP integration

## Goal
Add a button on the inbox page that clears all inboxes and emails in one action.

## Validated Decisions
- Scope: Global hard reset of all inboxes and emails.
- UX: No confirmation step before execution.
- Backend path: Reuse existing Mock SMTP endpoint `DELETE /api/clear`.
- UI integration: Route request through UI backend (`/api/inbox/clear-all`) instead of calling Mock SMTP directly from the browser.

## Current Context
- Inbox page template: `src/ui/templates/inbox/list.html`
- UI inbox API routes: `src/ui/routes/inbox.py`
- UI SMTP service: `src/ui/services/smtp_client.py`
- Existing clear-all endpoint: `src/mock_smtp/api/email_routes.py` (`DELETE /api/clear`)

## Proposed Architecture
1. Add a destructive button in the inbox page header near `Refresh`:
   - Label: `Clear All Inboxes`
   - HTMX request: `hx-delete="/api/inbox/clear-all"`
   - Target a dedicated status container for success/error feedback.

2. Add a UI route in `src/ui/routes/inbox.py`:
   - `@router.delete("/clear-all", response_class=HTMLResponse)`
   - Calls `resources.smtp_client.clear_all_inboxes()`
   - Returns success partial on success and existing error partial on failure.

3. Add service method in `src/ui/services/smtp_client.py`:
   - `async def clear_all_inboxes(self) -> int`
   - Sends `DELETE /api/clear` to Mock SMTP
   - Parses and validates response payload strictly.

## Data Flow
1. User clicks `Clear All Inboxes`.
2. Browser sends DELETE to `/api/inbox/clear-all`.
3. UI route calls SMTP client service.
4. Service calls Mock SMTP `DELETE /api/clear`.
5. Mock SMTP returns JSON including `deleted_count`.
6. UI returns success HTML and refresh triggers for inbox/email containers.
7. UI clears or hides email detail and reply containers.

## Error Handling and Fail-Fast Rules
- No fallback/default values for clear response parsing.
- Required contract: response JSON contains integer `deleted_count`.
- If HTTP status is non-2xx, JSON is malformed, or `deleted_count` is missing/invalid:
  - Raise clear, typed exception (`SMTPConnectionError`).
  - Return explicit error partial with title and message.
- Log each stage with details: action start, status code, deleted count, failure reason.

## UI Behavior Details
- Button is visually destructive (red styling) to reduce accidental clicks.
- Disable button while request is in flight to reduce duplicate requests.
- After success:
  - Reload `#inbox-list-container` (`/api/inbox/list`)
  - Reload `#email-list-container` for current/default inbox
  - Hide and clear:
    - `#email-detail-container`
    - `#reply-form-container`

## Testing Plan
1. Service tests (`tests/test_ui/test_services.py`):
   - Success case returns `deleted_count`.
   - Non-2xx raises `SMTPConnectionError`.
   - Missing/invalid `deleted_count` raises `SMTPConnectionError`.

2. Route tests (new or existing UI route test module):
   - `DELETE /api/inbox/clear-all` success returns success partial.
   - Failure returns `partials/error.html` with explicit error message.

3. Optional template verification:
   - Assert clear button exists with expected HTMX attributes.

## Risks
- No confirmation increases accidental-clear risk.
- Mitigation is visual emphasis, destructive label, and in-flight disable.

## Out of Scope
- Per-inbox clear controls.
- Typed or modal confirmation.
- Undo/restore capability.
