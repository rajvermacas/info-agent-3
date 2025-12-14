# Mock SMTP Server - Developer Documentation

## Project Overview

Mock SMTP server for testing email functionality. Dual-server architecture: SMTP (port 1025) + REST API (port 8025). Built with aiosmtpd and FastAPI for local development and integration testing.

## Development Commands

### Setup
```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -e ".[dev]"
```

### Running
```bash
mock-smtp  # or: python -m mock_smtp.main
# SMTP: localhost:1025
# API: 0.0.0.0:8025
# Swagger: http://localhost:8025/docs
```

### Testing
```bash
pytest
pytest --cov=src/mock_smtp --cov-report=html
```

## Architecture

### High-Level Design

**Dual-Server Architecture:** Two concurrent async servers sharing in-memory state:
1. **SMTP Server (aiosmtpd)** - Receives emails via SMTP protocol
2. **REST API (FastAPI)** - HTTP interface for inspection

**Shared State (Singleton):**
- `InboxStore` - Thread-safe in-memory email storage
- `WebhookRegistry` - Webhook URL registrations
- `WebhookDispatcher` - Async HTTP client for webhook notifications

**Key Patterns:** Dependency Injection, Factory Pattern, Async/Await, Fire-and-Forget Webhooks

### Directory Structure

```
/workspaces/info-agent-3/
├── src/mock_smtp/
│   ├── main.py                 # Entrypoint, lifespan management
│   ├── config.py               # Pydantic settings with env vars
│   ├── store/
│   │   ├── models.py           # Pydantic models (Email, Inbox, Attachment)
│   │   └── inbox_store.py      # Thread-safe in-memory storage
│   ├── webhooks/
│   │   ├── registry.py         # Webhook URL CRUD (in-memory)
│   │   └── dispatcher.py       # Async HTTP POST with retry/timeout
│   ├── smtp/
│   │   ├── server.py           # AIOSMTPD server lifecycle
│   │   └── handler.py          # Custom SMTP handler (stores + webhooks)
│   └── api/
│       ├── router.py           # Router factory with dependency injection
│       ├── inbox_routes.py     # GET/DELETE inboxes
│       ├── email_routes.py     # GET/DELETE emails
│       ├── send_routes.py      # POST /api/send
│       └── webhook_routes.py   # Webhook registration CRUD
├── tests/
│   ├── conftest.py             # Pytest fixtures
│   ├── test_models.py
│   ├── test_inbox_store.py
│   └── test_api_inboxes.py
├── .dev-resources/
│   ├── architecture/mock-smtp-server.md
│   ├── contracts/mock-smtp.json
│   └── prompts/mock-smtp.txt
├── pyproject.toml
├── README.md
└── CLAUDE.md
```

### Key Components

| Component | Responsibility | Key Details |
|-----------|---------------|-------------|
| **main.py** | Server entrypoint, lifespan | Initializes shared resources, starts SMTP + API concurrently |
| **config.py** | Pydantic Settings | `.env` + `MOCK_SMTP_*` env vars, `@lru_cache` singleton |
| **store/models.py** | Pydantic models | `Email`, `Inbox`, `Attachment`, `EmailSummary`, `InboxSummary` |
| **store/inbox_store.py** | Thread-safe storage | `threading.Lock`, FIFO eviction, `max_emails_per_inbox` limit |
| **webhooks/registry.py** | Webhook storage | In-memory `WebhookRegistration` (URL + inbox filter) |
| **webhooks/dispatcher.py** | HTTP webhook sender | Async `httpx`, retry with exponential backoff, timeout handling |
| **smtp/server.py** | SMTP server wrapper | Manages aiosmtpd lifecycle |
| **smtp/handler.py** | SMTP protocol handler | Parses MIME, extracts attachments, stores emails, triggers webhooks |
| **api/router.py** | Router factory | Dependency injection for testing |
| **api/*_routes.py** | REST endpoints | Inbox/email CRUD, send, webhook management |

#### Email Models (store/models.py)

**Email:** `id`, `from_address`, `to_addresses`, `subject`, `body_text`, `body_html`, `attachments`, `headers`, `received_at`, `raw_content`

**Inbox:** `email_address`, `emails[]`, `created_at`, `last_email_at` + methods: `add_email()`, `get_email_by_id()`, `delete_email()`, `clear()`

**Attachment:** `filename`, `content_type`, `size_bytes`, `content_base64` + factory: `Attachment.from_bytes()`

#### InboxStore Methods

- `store_email(email)` - Store in all recipient inboxes
- `get_inbox(email_address)` - Get or create inbox
- `get_email(email_address, email_id)` - Fetch specific email
- `delete_email(email_address, email_id)` - Delete email
- `clear_inbox(email_address)` - Delete all emails in inbox
- `clear_all()` - Reset entire store

**Thread Safety:** All modifications inside `with self._lock:`

#### Webhook Payload

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
  "body_preview": "First 100 chars..."
}
```

**HTTP Headers:** `Content-Type`, `X-Webhook-Event`, `X-Email-ID`, `X-Webhook-Timestamp`

**Retry:** Timeout → retry with backoff, HTTP error → fail, network error → retry

#### SMTP Handler Flow

1. Receive envelope (sender, recipients, MIME)
2. Parse MIME using `email.message_from_bytes()`
3. Extract headers, body, attachments
4. Validate attachment sizes
5. Create `Email` instance
6. Store in `InboxStore`
7. Trigger webhooks (async, fire-and-forget)
8. Return "250 OK"

## Configuration

### Environment Variables

All settings use `MOCK_SMTP_*` prefix:

```bash
MOCK_SMTP_SMTP_HOST=localhost          # Default: localhost
MOCK_SMTP_SMTP_PORT=1025               # Default: 1025
MOCK_SMTP_API_HOST=0.0.0.0             # Default: 0.0.0.0
MOCK_SMTP_API_PORT=8025                # Default: 8025
MOCK_SMTP_MAX_EMAILS_PER_INBOX=1000    # Default: 1000
MOCK_SMTP_MAX_ATTACHMENT_SIZE_MB=10    # Default: 10
MOCK_SMTP_WEBHOOK_TIMEOUT_SECONDS=10.0 # Default: 10.0
MOCK_SMTP_WEBHOOK_MAX_RETRIES=3        # Default: 3
MOCK_SMTP_LOG_LEVEL=INFO               # Default: INFO
```

Create `.env` in project root (gitignored) to override defaults.

## Key Files Reference

| File | Purpose | Modify When |
|------|---------|-------------|
| `main.py` | Server entrypoint | Adding shared resources |
| `config.py` | Settings | Adding config options |
| `store/models.py` | Data models | Changing email/inbox structure |
| `store/inbox_store.py` | Storage logic | Changing storage behavior |
| `smtp/handler.py` | SMTP processing | Changing email parsing |
| `webhooks/dispatcher.py` | Webhook client | Changing webhook payload/behavior |
| `api/router.py` | Router factory | Adding route modules |
| `api/*_routes.py` | API endpoints | Adding endpoints |
| `tests/*` | Test suite | Adding features (TDD) |

## Development Patterns

### Adding API Endpoint

1. Create route in `api/*_routes.py` (or new file)
2. Use dependency injection from router factory
3. Add tests in `tests/test_api_*.py`
4. Update OpenAPI: `curl http://localhost:8025/openapi.json > .dev-resources/contracts/mock-smtp.json`

### Adding Configuration

1. Add field to `Settings` in `config.py` with `Field()` descriptor
2. Add validation if needed (`@field_validator`)
3. Update architecture docs and README

### Adding Pydantic Model

1. Define in `store/models.py` with `Field()` descriptions
2. Export in `store/__init__.py`
3. Add tests in `tests/test_models.py`

### Modifying InboxStore

**Critical:** Preserve thread safety - all modifications inside `with self._lock:`

### Testing

**Unit Tests:** Isolated components
**Integration Tests:** API endpoints (use FastAPI `TestClient`)

**Fixtures (conftest.py):** `inbox_store`, `webhook_registry`, `sample_email`

## Anti-Patterns to Avoid

1. **No persistent storage** - In-memory is intentional (testing tool)
2. **No authentication** - Open relay by design
3. **No blocking webhooks** - Fire-and-forget is intentional
4. **No retry on failed storage** - SMTP should return error
5. **No global variables** - Use dependency injection
6. **No complex routing** - Keep it simple (mock server)

## Important Constraints

### Fail-Fast Behavior

- Invalid config → `ValueError` on startup
- Attachment too large → SMTP 552 error
- Inbox full → FIFO eviction (oldest emails)
- Webhook failure → log only, don't block storage

### Error Handling

**SMTP:** Catch all exceptions, log, return SMTP error code (never crash)
**API:** FastAPI/Pydantic validation (422), 404 for not found, 500 for unexpected
**Webhooks:** Log failures, no retry storage, async fire-and-forget

### Data Access

**Never bypass InboxStore:**
```python
# BAD: inbox_store._inboxes[email].emails.append(email)
# GOOD: inbox_store.store_email(email)
```

**Always use locks:**
```python
# BAD: self.emails.append(email)
# GOOD: with self._lock: self.emails.append(email)
```

### Logging

- **DEBUG** - Detailed flow (webhook retries, MIME parsing)
- **INFO** - Important events (email received, server start/stop)
- **WARNING** - Recoverable issues (webhook timeout)
- **ERROR** - Failures (webhook failed, parse error)
- **CRITICAL** - Server failures

### Memory Management

- `max_emails_per_inbox` prevents unbounded growth
- FIFO eviction when limit reached
- Size validation during SMTP receipt only

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

## Contributing

Follow coding guidelines from `/root/.claude/CLAUDE.md`:
- Files ≤ 800 lines
- Strict test-driven development
- Comprehensive logging
- No fallback/default values (raise exceptions)
- Update README.md for user-facing changes
- Test data in `test_data/`, debug scripts in `scripts/`
