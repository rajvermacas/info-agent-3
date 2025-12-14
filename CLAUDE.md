# Mock SMTP Server - Developer Documentation

## Project Overview

A self-contained mock SMTP server for testing email functionality. Provides both SMTP protocol support (port 1025) and REST API (port 8025) for sending, receiving, and inspecting emails. Built with aiosmtpd and FastAPI, designed for local development and integration testing.

## Development Commands

### Setup

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install with dev dependencies
pip install -e ".[dev]"
```

### Running

```bash
# Start server (both SMTP and API)
mock-smtp

# Or run directly
python -m mock_smtp.main

# Server will bind to:
# - SMTP: localhost:1025
# - API: 0.0.0.0:8025
# - Swagger UI: http://localhost:8025/docs
```

### Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src/mock_smtp --cov-report=html

# Run specific test file
pytest tests/test_models.py

# Run with verbose output
pytest -v
```

## Architecture

### High-Level Design

**Dual-Server Architecture:** Two concurrent async servers sharing in-memory state:

1. **SMTP Server (aiosmtpd)** - Receives emails via SMTP protocol
2. **REST API (FastAPI)** - Provides HTTP interface for inspection and testing

**Shared State (Singleton Pattern):**
- `InboxStore` - Thread-safe in-memory email storage
- `WebhookRegistry` - Webhook URL registrations
- `WebhookDispatcher` - Async HTTP client for webhook notifications

**Key Patterns:**
- **Dependency Injection** - Components receive dependencies via constructor
- **Factory Pattern** - `create_api_router()` assembles dependencies
- **Singleton Store** - Single `InboxStore` instance shared across both servers
- **Async/Await** - Full async operation (no blocking I/O)
- **Fire-and-Forget Webhooks** - Async dispatch, failures logged only

### Directory Structure

```
/workspaces/info-agent-3/
├── src/
│   └── mock_smtp/
│       ├── __init__.py
│       ├── main.py                 # Entrypoint, lifespan management
│       ├── config.py               # Pydantic settings with env vars
│       │
│       ├── store/
│       │   ├── __init__.py
│       │   ├── models.py           # Pydantic models (Email, Inbox, Attachment)
│       │   └── inbox_store.py      # Thread-safe in-memory storage
│       │
│       ├── webhooks/
│       │   ├── __init__.py
│       │   ├── registry.py         # Webhook URL CRUD (in-memory)
│       │   └── dispatcher.py       # Async HTTP POST with retry/timeout
│       │
│       ├── smtp/
│       │   ├── __init__.py
│       │   ├── server.py           # AIOSMTPD server lifecycle
│       │   └── handler.py          # Custom SMTP handler (stores + webhooks)
│       │
│       └── api/
│           ├── __init__.py
│           ├── router.py           # Router factory with dependency injection
│           ├── inbox_routes.py     # GET/DELETE inboxes
│           ├── email_routes.py     # GET/DELETE emails
│           ├── send_routes.py      # POST /api/send
│           └── webhook_routes.py   # Webhook registration CRUD
│
├── tests/
│   ├── conftest.py                 # Pytest fixtures
│   ├── test_models.py              # Pydantic model tests
│   ├── test_inbox_store.py         # Storage tests
│   └── test_api_inboxes.py         # API integration tests
│
├── .dev-resources/
│   ├── architecture/
│   │   └── mock-smtp-server.md     # Full architecture specification
│   ├── contracts/
│   │   └── mock-smtp.json          # OpenAPI schema (exported from /openapi.json)
│   └── prompts/
│       └── mock-smtp.txt           # Original requirements
│
├── pyproject.toml                  # Project metadata, dependencies, test config
├── README.md                       # User-facing documentation
├── CLAUDE.md                       # This file (developer documentation)
└── .gitignore
```

### Key Components

#### main.py

**Responsibilities:**
- Initialize all shared resources (`InboxStore`, `WebhookRegistry`, `WebhookDispatcher`)
- Start SMTP server in background task
- Start webhook dispatcher HTTP client
- Create FastAPI app with lifespan context manager
- Run uvicorn ASGI server

**Lifespan Flow:**
1. Load settings from environment
2. Create shared `InboxStore` (thread-safe, in-memory)
3. Create `WebhookRegistry` (in-memory list)
4. Create and start `WebhookDispatcher` (async httpx client)
5. Create and start `SMTPServer` (aiosmtpd)
6. Yield control to FastAPI
7. On shutdown: stop SMTP, stop dispatcher, cleanup

**Important:** SMTP server runs concurrently with FastAPI in the same asyncio event loop.

#### config.py

**Pattern:** Pydantic Settings with environment variable override

**Configuration Loading:**
- Reads from `.env` file (if present)
- Overrides with `MOCK_SMTP_*` environment variables
- Case-insensitive env var names
- Uses `@lru_cache` to ensure singleton settings instance

**Key Settings:**
- `smtp_host`, `smtp_port` (default: localhost:1025)
- `api_host`, `api_port` (default: 0.0.0.0:8025)
- `max_emails_per_inbox` (default: 1000)
- `max_attachment_size_mb` (default: 10MB)
- `webhook_timeout_seconds` (default: 10.0)
- `webhook_max_retries` (default: 3)
- `log_level` (default: INFO)

#### store/models.py

**Pydantic Models:**

**Email** - Full email with headers, body, attachments
- `id` (UUID, auto-generated)
- `from_address` (required)
- `to_addresses` (list, min 1)
- `subject`, `body_text`, `body_html` (optional)
- `attachments` (list of `Attachment`)
- `headers` (dict)
- `received_at` (datetime, auto-set to UTC)
- `raw_content` (optional raw MIME)

**Inbox** - Collection of emails for one recipient
- `email_address` (unique per inbox)
- `emails` (list of `Email`)
- `created_at`, `last_email_at` (timestamps)
- Methods: `add_email()`, `get_email_by_id()`, `delete_email()`, `clear()`

**Attachment** - Base64-encoded file
- `filename`, `content_type`, `size_bytes`
- `content_base64` (base64 string)
- Factory: `Attachment.from_bytes()`

**EmailSummary** - Lightweight email metadata (for list endpoints)
**InboxSummary** - Lightweight inbox metadata (for list endpoints)

#### store/inbox_store.py

**Thread-Safe In-Memory Storage:**
- Uses `threading.Lock` for concurrent access (SMTP + API)
- Stores inboxes in `dict[str, Inbox]`
- Auto-creates inboxes on first email (implicit creation)
- Enforces `max_emails_per_inbox` limit (FIFO eviction)

**Key Methods:**
- `store_email(email: Email)` - Store in all recipient inboxes
- `get_inbox(email_address: str)` - Get or create inbox
- `get_email(email_address: str, email_id: UUID)` - Fetch specific email
- `delete_email(email_address: str, email_id: UUID)` - Delete email
- `clear_inbox(email_address: str)` - Delete all emails in inbox
- `clear_all()` - Reset entire store

**Thread Safety Pattern:**
```python
with self._lock:
    # All modifications happen inside lock
```

#### webhooks/registry.py

**In-Memory Webhook Storage:**
- Stores list of `WebhookRegistration` (URL + optional inbox filter)
- Thread-safe with `threading.Lock`
- No persistence (lost on restart)

**WebhookRegistration:**
- `id` (UUID)
- `url` (validated HTTP/HTTPS URL)
- `inbox_filter` (optional - only notify for specific inbox)
- `created_at` (timestamp)

#### webhooks/dispatcher.py

**Async HTTP Webhook Dispatcher:**
- Uses `httpx.AsyncClient` for non-blocking HTTP
- Retry logic with exponential backoff
- Timeout handling (configurable)
- Semaphore for max concurrent dispatches

**Webhook Payload (sent via POST):**
```json
{
  "event": "email.received",
  "email_id": "uuid",
  "from": "sender@example.com",
  "to": ["recipient@example.com"],
  "subject": "Email subject",
  "has_attachments": true,
  "attachment_count": 2,
  "received_at": "2025-12-14T10:30:00.000000",
  "body_preview": "First 100 chars of body text..."
}
```

**Design Decision:** Payload is lightweight. Webhook receivers fetch full email via API if needed.

**HTTP Headers Added:**
- `Content-Type: application/json`
- `X-Webhook-Event: email.received`
- `X-Email-ID: {email_id}`
- `X-Webhook-Timestamp: {iso_timestamp}`

**Retry Behavior:**
- On timeout: Retry up to `max_retries` times with exponential backoff
- On HTTP error (4xx/5xx): Log and fail (no retry)
- On network error: Retry up to `max_retries` times

#### smtp/server.py

**AIOSMTPD Server Wrapper:**
- Creates and manages `aiosmtpd.smtp.SMTP` instance
- Runs in asyncio background task
- Provides `start()` and `stop()` lifecycle methods

**Dependencies Injected:**
- `InboxStore` - For storing received emails
- `WebhookRegistry` - For webhook URL list
- `WebhookDispatcher` - For sending webhook notifications
- `max_attachment_size` - Size limit enforcement

#### smtp/handler.py

**Custom SMTP Handler (aiosmtpd.smtp.AsyncMessage):**

**SMTP Protocol Flow:**
1. Receive envelope (sender, recipients, raw MIME message)
2. Parse MIME content using `email.message_from_bytes()`
3. Extract headers, body parts, attachments
4. Validate attachment sizes
5. Create `Email` instance
6. Store in `InboxStore` for each recipient
7. Trigger async webhook dispatch (fire-and-forget)
8. Return SMTP response "250 OK"

**Key Method:** `handle_DATA(server, session, envelope)`
- Called when SMTP client sends email data
- Must return "250 OK" or error code

**Parsing:**
- Handles multipart MIME (text/plain, text/html, attachments)
- Decodes base64/quoted-printable encodings
- Extracts all headers (From, To, Subject, Date, etc.)
- Stores raw MIME in `Email.raw_content`

#### api/router.py

**Router Factory Pattern:**
```python
def create_api_router(
    inbox_store: InboxStore,
    webhook_registry: WebhookRegistry
) -> APIRouter:
    # Create router with injected dependencies
    # Include all sub-routers
```

**Why Factory?** Enables dependency injection for testing (mock stores).

#### api/inbox_routes.py

**Endpoints:**
- `GET /api/inboxes` - List all inboxes (returns `InboxSummary[]`)
- `GET /api/inboxes/{email}` - Get all emails in inbox (returns `EmailSummary[]`)
- `DELETE /api/inboxes/{email}` - Clear inbox

#### api/email_routes.py

**Endpoints:**
- `GET /api/inboxes/{email}/emails/{email_id}` - Get full email
- `DELETE /api/inboxes/{email}/emails/{email_id}` - Delete email
- `DELETE /api/clear` - Clear all inboxes (reset server)

#### api/send_routes.py

**Endpoint:**
- `POST /api/send` - Send email directly (bypass SMTP)

**Request Body:**
```json
{
  "from_address": "sender@example.com",
  "to_addresses": ["recipient@example.com"],
  "subject": "Test",
  "body_text": "Plain text",
  "body_html": "<p>HTML</p>"
}
```

**Flow:**
1. Validate request (pydantic)
2. Create `Email` instance
3. Store in `InboxStore` for each recipient
4. Trigger webhooks
5. Return `Email` response (201 Created)

#### api/webhook_routes.py

**Endpoints:**
- `POST /api/webhooks` - Register webhook
- `GET /api/webhooks` - List all webhooks
- `GET /api/webhooks/{id}` - Get webhook details
- `DELETE /api/webhooks/{id}` - Unregister webhook

**Health Check:**
- `GET /api/health` - Server status

## Configuration

### Environment Variables

All settings support environment variable override with `MOCK_SMTP_` prefix:

```bash
MOCK_SMTP_SMTP_HOST=localhost
MOCK_SMTP_SMTP_PORT=1025
MOCK_SMTP_API_HOST=0.0.0.0
MOCK_SMTP_API_PORT=8025
MOCK_SMTP_MAX_EMAILS_PER_INBOX=1000
MOCK_SMTP_MAX_ATTACHMENT_SIZE_MB=10
MOCK_SMTP_WEBHOOK_TIMEOUT_SECONDS=10.0
MOCK_SMTP_WEBHOOK_MAX_RETRIES=3
MOCK_SMTP_LOG_LEVEL=INFO
```

### .env File

Create `.env` in project root (ignored by git):

```bash
MOCK_SMTP_LOG_LEVEL=DEBUG
MOCK_SMTP_MAX_EMAILS_PER_INBOX=500
```

## Key Files Reference

| File | Purpose | Modify When |
|------|---------|-------------|
| `src/mock_smtp/main.py` | Server entrypoint, lifespan | Adding new shared resources |
| `src/mock_smtp/config.py` | Settings | Adding new configuration options |
| `src/mock_smtp/store/models.py` | Data models | Changing email/inbox structure |
| `src/mock_smtp/store/inbox_store.py` | Storage logic | Changing storage behavior |
| `src/mock_smtp/smtp/handler.py` | SMTP email processing | Changing email parsing logic |
| `src/mock_smtp/webhooks/dispatcher.py` | Webhook HTTP client | Changing webhook payload/behavior |
| `src/mock_smtp/api/router.py` | API router factory | Adding new API route modules |
| `src/mock_smtp/api/*_routes.py` | API endpoints | Adding new endpoints |
| `tests/*` | Test suite | Adding new features (TDD) |
| `pyproject.toml` | Dependencies, metadata | Adding dependencies |

## Development Patterns

### Adding a New API Endpoint

1. Create route in appropriate `api/*_routes.py` file (or new file)
2. Use dependency injection from router factory
3. Add tests in `tests/test_api_*.py`
4. Update OpenAPI schema export: `curl http://localhost:8025/openapi.json > .dev-resources/contracts/mock-smtp.json`

Example:
```python
# In api/inbox_routes.py
@router.get("/api/inboxes/{email}/count")
async def get_inbox_count(email: str):
    inbox = inbox_store.get_inbox(email)
    return {"email": email, "count": inbox.email_count}
```

### Adding a New Configuration Option

1. Add field to `Settings` class in `config.py` with `Field()` descriptor
2. Add validation if needed (using `@field_validator`)
3. Update `.dev-resources/architecture/mock-smtp-server.md` (config section)
4. Update `README.md` (configuration section)

Example:
```python
class Settings(BaseSettings):
    max_subject_length: int = Field(
        default=200,
        ge=1,
        description="Maximum email subject length"
    )
```

### Adding a New Pydantic Model

1. Define in `store/models.py`
2. Use `Field()` for all attributes with descriptions
3. Add validation methods if needed
4. Export in `store/__init__.py`
5. Add tests in `tests/test_models.py`

### Modifying Email Storage

**Important:** Changes to `InboxStore` must preserve thread safety.

**Pattern:**
```python
def new_method(self):
    with self._lock:
        # All state modifications here
        pass
```

### Testing Pattern

**Unit Tests:** Test individual components in isolation
**Integration Tests:** Test API endpoints (use `TestClient` from FastAPI)

**Fixtures in conftest.py:**
- `inbox_store` - Fresh InboxStore for each test
- `webhook_registry` - Fresh WebhookRegistry
- `sample_email` - Test email instance

**Example Test:**
```python
def test_store_email(inbox_store, sample_email):
    inbox_store.store_email(sample_email)
    inbox = inbox_store.get_inbox(sample_email.to_addresses[0])
    assert inbox.email_count == 1
```

## Anti-Patterns to Avoid

1. **Don't add persistent storage** - This is a testing tool, in-memory is intentional
2. **Don't add authentication** - Open relay is by design for testing
3. **Don't make webhooks blocking** - Fire-and-forget is intentional
4. **Don't retry failed email storage** - If storage fails, SMTP should return error
5. **Don't use global variables** - Use dependency injection instead
6. **Don't add complex email routing** - This is a mock server, not a real MTA
7. **Don't parse email content beyond MIME structure** - Keep it simple

## Important Constraints

### Fail-Fast Behavior

- Invalid configuration → raise ValueError on startup
- SMTP attachment too large → return 552 SMTP error
- Inbox exceeds max emails → auto-evict oldest (FIFO)
- Webhook failures → log only, don't block email storage

### Error Handling Philosophy

**SMTP Handler:**
- Catch all exceptions, log, return SMTP error code
- Never crash server on bad email

**API Endpoints:**
- Let FastAPI/Pydantic handle validation errors (422 responses)
- Return 404 for not found (inbox/email doesn't exist)
- Return 500 only for unexpected errors

**Webhooks:**
- Log all failures (timeout, HTTP error, network error)
- Don't store failed webhooks for retry
- Don't block on webhook dispatch (async fire-and-forget)

### Data Access Patterns

**Never bypass InboxStore:**
```python
# BAD
inbox_store._inboxes[email].emails.append(email)

# GOOD
inbox_store.store_email(email)
```

**Always use locks for thread safety:**
```python
# BAD
self.emails.append(email)

# GOOD
with self._lock:
    self.emails.append(email)
```

### Logging Guidelines

**Log levels:**
- `DEBUG` - Detailed flow (webhook retries, MIME parsing steps)
- `INFO` - Important events (email received, webhook sent, server start/stop)
- `WARNING` - Recoverable issues (webhook timeout on retry)
- `ERROR` - Failures (webhook failed after retries, email parse error)
- `CRITICAL` - Server failures (should not happen in normal operation)

**Log format:**
```python
logger.info(f"Email received: from={email.from_address} to={email.to_addresses} id={email.id}")
```

### Memory Management

**Email Limit Enforcement:**
- `max_emails_per_inbox` prevents unbounded growth
- FIFO eviction when limit reached
- Log when eviction occurs

**No Attachment Size Limits in Storage:**
- Size validation happens during SMTP receipt
- Already-stored attachments are not size-checked

## Testing Checklist

Before submitting changes:

- [ ] All tests pass: `pytest`
- [ ] Coverage maintained: `pytest --cov=src/mock_smtp --cov-report=term-missing`
- [ ] No files exceed 800 lines
- [ ] Logging added for new operations
- [ ] Environment variables documented (if added)
- [ ] README.md updated (if user-facing changes)
- [ ] Architecture doc updated (if structural changes)
- [ ] API contract updated: `curl http://localhost:8025/openapi.json > .dev-resources/contracts/mock-smtp.json`

## Deployment Notes

**This is a development/testing tool, not for production use.**

**Running in Docker:**
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install -e .
CMD ["mock-smtp"]
```

**Exposing Ports:**
- SMTP: 1025
- API: 8025

**No Persistence:**
- All data lost on container restart
- This is intentional behavior

## Common Issues

### "Address already in use" error

**Cause:** Port 1025 or 8025 already bound

**Solution:** Change ports via environment variables or kill existing process

### Emails not appearing in inbox

**Check:**
1. SMTP client connected successfully (check logs)
2. Recipient email matches exactly (case-sensitive)
3. Email stored without error (check server logs)
4. Polling correct inbox endpoint

### Webhooks not firing

**Check:**
1. Webhook registered: `GET /api/webhooks`
2. Webhook URL reachable from server
3. Check server logs for dispatch errors
4. Webhook endpoint returns 2xx status

### Tests failing

**Common causes:**
1. Port already in use (stop server before running tests)
2. Async fixtures not awaited properly
3. Shared state between tests (use fresh fixtures)

## Contributing

Follow coding guidelines from `/root/.claude/CLAUDE.md`:

- Files must not exceed 800 lines
- Use strict test-driven development
- Add comprehensive logging
- No fallback/default values (raise exceptions)
- Update README.md for user-facing changes
- Create test data in `test_data/` folder
- Create debug scripts in `scripts/` folder
