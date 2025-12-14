# Info Agent 3 - Developer Documentation

## Project Overview

This project contains two integrated services:

1. **Mock SMTP Server** - A testing SMTP server with REST API and webhook support
2. **Mail Agent** - An autonomous LangGraph-based email agent for data collection

Both services work together to enable autonomous email-based data collection workflows. The Mock SMTP Server provides email infrastructure, while the Mail Agent orchestrates multi-turn conversations with contacts to gather data.

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
# Start Mock SMTP Server (both SMTP and API)
mock-smtp

# Or run directly
python -m mock_smtp.main

# Server will bind to:
# - SMTP: localhost:1025
# - API: 0.0.0.0:8025
# - Swagger UI: http://localhost:8025/docs

# Start Mail Agent (requires Mock SMTP running)
MAIL_AGENT_GEMINI_API_KEY=your-key \
mail-agent send "Email alice@company.com requesting Q4 sales data in Excel"

# Or run directly
python -m mail_agent.main

# Check Mail Agent health
mail-agent health
```

### Testing

```bash
# Run all tests (both Mock SMTP and Mail Agent)
pytest

# Run with coverage
pytest --cov=src/mock_smtp --cov=src/mail_agent --cov-report=html

# Run specific test file
pytest tests/test_models.py
pytest tests/test_mail_agent/test_attachment_parser.py

# Run with verbose output
pytest -v

# Simulate POC reply (for testing Mail Agent)
python scripts/poc_reply_simulator.py \
  --from "alice@company.com" \
  --to "info-agent@gmail.com" \
  --subject "Re: Request for sales data" \
  --body "Here is the data you requested." \
  --attachment test_data/sample_recipes.xlsx
```

## Architecture

### System Integration

The project consists of two services that integrate via REST API and webhooks:

```
┌─────────────────────────────────────────────────────────────────┐
│                      SYSTEM ARCHITECTURE                         │
└─────────────────────────────────────────────────────────────────┘

┌──────────────────────┐                 ┌──────────────────────┐
│   MAIL AGENT         │                 │   MOCK SMTP SERVER   │
│   (LangGraph)        │                 │   (aiosmtpd+FastAPI) │
│                      │                 │                      │
│  - Parse instruction │                 │  - SMTP :1025        │
│  - Compose email     │─────────────────▶  - REST API :8025   │
│  - Send via API      │  POST /api/send │  - Webhook dispatch  │
│  - Wait for webhook  │◀────────────────│  - Email storage     │
│  - Validate response │  POST /webhook  │                      │
│  - Multi-turn logic  │                 │                      │
└──────────────────────┘                 └──────────────────────┘
```

---

## Part 1: Mock SMTP Server

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
│   ├── mock_smtp/                  # Mock SMTP Server
│   │   ├── __init__.py
│   │   ├── main.py                 # Entrypoint, lifespan management
│   │   ├── config.py               # Pydantic settings with env vars
│   │   │
│   │   ├── store/
│   │   │   ├── __init__.py
│   │   │   ├── models.py           # Pydantic models (Email, Inbox, Attachment)
│   │   │   └── inbox_store.py      # Thread-safe in-memory storage
│   │   │
│   │   ├── webhooks/
│   │   │   ├── __init__.py
│   │   │   ├── registry.py         # Webhook URL CRUD (in-memory)
│   │   │   └── dispatcher.py       # Async HTTP POST with retry/timeout
│   │   │
│   │   ├── smtp/
│   │   │   ├── __init__.py
│   │   │   ├── server.py           # AIOSMTPD server lifecycle
│   │   │   └── handler.py          # Custom SMTP handler (stores + webhooks)
│   │   │
│   │   └── api/
│   │       ├── __init__.py
│   │       ├── router.py           # Router factory with dependency injection
│   │       ├── inbox_routes.py     # GET/DELETE inboxes
│   │       ├── email_routes.py     # GET/DELETE emails
│   │       ├── send_routes.py      # POST /api/send
│   │       └── webhook_routes.py   # Webhook registration CRUD
│   │
│   └── mail_agent/                 # Mail Agent (LangGraph)
│       ├── __init__.py
│       ├── main.py                 # Typer CLI entrypoint
│       ├── config.py               # Pydantic settings (MAIL_AGENT_ prefix)
│       │
│       ├── agent/
│       │   ├── __init__.py
│       │   ├── graph.py            # LangGraph state machine definition
│       │   ├── state.py            # TypedDict state schema
│       │   └── nodes/
│       │       ├── __init__.py
│       │       ├── parse_instruction.py
│       │       ├── compose_email.py
│       │       ├── compose_followup.py
│       │       ├── send_email.py
│       │       ├── wait_for_reply.py
│       │       ├── fetch_email.py
│       │       ├── extract_content.py
│       │       ├── validate_response.py
│       │       └── decide_next.py
│       │
│       ├── webhook/
│       │   ├── __init__.py
│       │   └── server.py           # FastAPI webhook receiver
│       │
│       ├── tools/
│       │   ├── __init__.py
│       │   ├── smtp_client.py      # Send email via REST API
│       │   ├── inbox_client.py     # Fetch emails via REST API
│       │   └── attachment_parser.py # Excel/CSV extraction
│       │
│       └── llm/
│           ├── __init__.py
│           ├── client.py           # Gemini 2.0 Flash client
│           └── prompts.py          # Prompt templates
│
├── scripts/
│   └── poc_reply_simulator.py      # POC reply simulator (SMTP client)
│
├── tests/
│   ├── conftest.py                 # Pytest fixtures
│   ├── test_models.py              # Mock SMTP Pydantic model tests
│   ├── test_inbox_store.py         # Mock SMTP storage tests
│   ├── test_api_inboxes.py         # Mock SMTP API integration tests
│   └── test_mail_agent/            # Mail Agent tests
│       ├── test_attachment_parser.py
│       └── test_integration.py
│
├── test_data/                      # Test fixtures
│   ├── sample_recipes.xlsx
│   ├── sample_recipes.csv
│   └── sample_invalid.xlsx
│
├── .dev-resources/
│   ├── architecture/
│   │   ├── mock-smtp-server.md     # Mock SMTP architecture
│   │   └── mail-agent.md           # Mail Agent architecture
│   ├── contracts/
│   │   └── mock-smtp.json          # OpenAPI schema
│   └── prompts/
│       ├── mock-smtp.txt           # Mock SMTP requirements
│       └── mail-agent.txt          # Mail Agent requirements
│
├── pyproject.toml                  # Project metadata, dependencies, test config
├── README.md                       # User-facing documentation
├── CLAUDE.md                       # This file (developer documentation)
├── IMPLEMENTATION_SUMMARY.md       # Implementation summary
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

## Contributing (Mock SMTP Server)

Follow coding guidelines from `/root/.claude/CLAUDE.md`:

- Files must not exceed 800 lines
- Use strict test-driven development
- Add comprehensive logging
- No fallback/default values (raise exceptions)
- Update README.md for user-facing changes
- Create test data in `test_data/` folder
- Create debug scripts in `scripts/` folder

---

## Part 2: Mail Agent

### Overview

The Mail Agent is an autonomous LangGraph-based email agent that orchestrates multi-turn email conversations to collect data from contacts. It uses Google Gemini 2.0 Flash for natural language understanding, email composition, and response validation.

**Core Capabilities:**
- Parse natural language instructions
- Compose professional emails
- Send emails via Mock SMTP REST API
- Monitor for replies via webhook
- Parse Excel/CSV attachments
- Validate responses with LLM
- Handle multi-turn conversations (up to 5 attempts)
- Support multiple POCs in parallel

**Technology Stack:**
- **Agent Framework:** LangGraph (state machine orchestration)
- **LLM:** Google Gemini 2.0 Flash via langchain-google-genai
- **State Persistence:** SQLite via langgraph-checkpoint-sqlite
- **Webhook Server:** FastAPI + Uvicorn
- **Attachment Parsing:** openpyxl (Excel) + csv (CSV)
- **CLI:** Typer + Rich
- **HTTP Client:** httpx (async)

### High-Level Architecture

**LangGraph State Machine:**

The agent is built as a LangGraph StateGraph with 9 nodes that execute sequentially based on conditional routing:

```
START → parse_instruction → decide_next
                                ↓
                    ┌───────────┴───────────┐
                    ↓                       ↓
              compose_email         compose_followup
                    ↓                       ↓
                    └───────────┬───────────┘
                                ↓
                          send_email
                                ↓
                         wait_for_reply
                                ↓
                          fetch_email
                                ↓
                        extract_content
                                ↓
                      validate_response
                                ↓
                          decide_next ──→ (loop or end)
                                ↓
                              END
```

**Key Patterns:**
- **State Machine Pattern** - LangGraph manages execution flow
- **Dependency Injection** - All components receive dependencies via constructors
- **Fire-and-Forget Webhooks** - Agent polls webhook server state
- **LLM-Driven Logic** - Gemini handles parsing, composition, validation
- **SQLite Checkpointing** - State persisted across interruptions

### Directory Structure Detail

```
src/mail_agent/
├── main.py                     # Typer CLI app with 2 commands (send, health)
├── config.py                   # Pydantic Settings (MAIL_AGENT_ env vars)
│
├── agent/
│   ├── graph.py                # create_agent_graph() - StateGraph definition
│   ├── state.py                # AgentState TypedDict schema
│   └── nodes/
│       ├── parse_instruction.py    # Extract POCs, request type, criteria
│       ├── compose_email.py        # LLM generates initial email
│       ├── compose_followup.py     # LLM generates follow-up email
│       ├── send_email.py           # POST to /api/send
│       ├── wait_for_reply.py       # Poll webhook server state
│       ├── fetch_email.py          # GET /api/inboxes/{email}/emails/{id}
│       ├── extract_content.py      # Parse Excel/CSV attachments
│       ├── validate_response.py    # LLM validates content
│       └── decide_next.py          # Route to next node or end
│
├── webhook/
│   └── server.py               # FastAPI server on :9000
│                               # POST /webhook/email-received
│                               # GET /health
│
├── tools/
│   ├── smtp_client.py          # SMTPClient (send email, register webhook)
│   ├── inbox_client.py         # InboxClient (fetch emails)
│   └── attachment_parser.py    # AttachmentParser (Excel/CSV → JSON)
│
└── llm/
    ├── client.py               # GeminiClient wrapper
    └── prompts.py              # Prompt templates (parse, compose, validate)
```

### Key Components

#### main.py

**CLI Commands:**
- `mail-agent send <instruction>` - Run agent with user instruction
- `mail-agent health` - Check configuration and connectivity

**Execution Flow:**
1. Load settings (validate GEMINI_API_KEY)
2. Create WebhookServer instance
3. Register webhook with Mock SMTP (POST /api/webhooks)
4. Start webhook server in background (asyncio task)
5. Create and run LangGraph state machine
6. Display progress with Rich console
7. Clean up webhook server on exit

**Important:** Webhook server runs concurrently with agent graph using asyncio.

#### config.py

**Settings Schema:**
```python
class Settings(BaseSettings):
    # Mock SMTP Connection
    mock_smtp_api_url: str = "http://localhost:8025"
    mock_smtp_host: str = "localhost"
    mock_smtp_port: int = 1025

    # Agent Identity
    agent_email: str = "info-agent@gmail.com"

    # Webhook Server
    webhook_host: str = "localhost"
    webhook_port: int = 9000
    webhook_path: str = "/webhook/email-received"

    # LLM Configuration
    gemini_api_key: str  # REQUIRED (raises error if not set)
    gemini_model: str = "gemini-2.0-flash-exp"
    gemini_temperature: float = 0.7
    gemini_max_tokens: int = 2048
    gemini_timeout: float = 60.0

    # Agent Behavior
    max_attempts: int = 5
    webhook_wait_timeout: Optional[float] = None

    # State Persistence
    sqlite_db_path: str = "./mail_agent_state.db"

    # Logging
    log_level: str = "INFO"
```

**Environment Variable Override:** All settings use `MAIL_AGENT_` prefix.

**Validation:**
- `gemini_api_key` must be non-empty (raises ValueError)
- `log_level` must be valid logging level
- `sqlite_db_path` parent directory created if missing

#### agent/state.py

**TypedDict State Schema:**

```python
class AgentState(TypedDict, total=False):
    user_instruction: str                      # Raw user input
    parsed_request: Optional[ParsedRequest]    # Extracted POCs, criteria
    conversations: dict[str, ConversationState] # Per-POC state
    current_node: str                          # Current node name
    pending_webhooks: list[dict]               # Webhook payloads
    progress_messages: list[str]               # Status messages
    final_summary: Optional[str]               # End result
    started_at: str                            # ISO timestamp
    completed_at: Optional[str]                # ISO timestamp
```

**ConversationState (per POC):**
```python
class ConversationState(TypedDict, total=False):
    status: str                         # "pending", "waiting", "success", "failed"
    attempt_count: int                  # 0-5
    sent_emails: list[SentEmail]        # All sent emails
    received_emails: list[ReceivedEmail] # All received emails
    validation_results: list[ValidationResult]
    final_result: Optional[str]         # "success" | "failed_max_attempts"
    error: Optional[str]                # Error message
```

**State Persistence:** LangGraph checkpointer saves state to SQLite after each node.

#### agent/graph.py

**Graph Construction:**

```python
def create_agent_graph():
    graph = StateGraph(AgentState)

    # Add all nodes
    graph.add_node("parse_instruction", parse_instruction_node)
    graph.add_node("compose_email", compose_email_node)
    graph.add_node("compose_followup", compose_followup_node)
    graph.add_node("send_email", send_email_node)
    graph.add_node("wait_for_reply", wait_for_reply_node)
    graph.add_node("fetch_email", fetch_email_node)
    graph.add_node("extract_content", extract_content_node)
    graph.add_node("validate_response", validate_response_node)
    graph.add_node("decide_next", decide_next_node)
    graph.add_node("end", end_node)

    # Add edges (linear + conditional)
    graph.add_edge(START, "parse_instruction")
    graph.add_edge("parse_instruction", "decide_next")
    graph.add_conditional_edges("decide_next", route_from_decide)
    # ... more edges

    # Compile with SQLite checkpointer
    checkpointer = SqliteSaver(settings.sqlite_db_path)
    return graph.compile(checkpointer=checkpointer)
```

**Routing Logic (decide_next):**
- If no POCs pending → end
- If POC needs initial email → compose_email
- If POC needs follow-up → compose_followup
- If validation passed → mark success, continue to next POC
- If max attempts reached → mark failed, continue to next POC

#### agent/nodes/ (9 Node Functions)

**Node Signature:** All nodes have the same signature:
```python
async def node_name(state: AgentState) -> AgentState:
    # Modify and return state
    return state
```

**1. parse_instruction.py**
- Calls LLM with user instruction
- Extracts: POC emails, request type, request description, success criteria
- Initializes conversation state for each POC
- Updates `state["parsed_request"]` and `state["conversations"]`

**2. compose_email.py**
- Calls LLM to generate professional email
- Uses POC email and request description
- Generates: subject, body_text
- Stores composed email in conversation state

**3. compose_followup.py**
- Calls LLM to generate correction request
- Uses validation feedback from previous attempt
- Generates polite follow-up email
- Increments attempt count

**4. send_email.py**
- Calls SMTPClient.send_email() (POST /api/send)
- Sends to all POCs with pending emails
- Stores email_id in conversation state
- Updates status to "waiting"

**5. wait_for_reply.py**
- Polls WebhookServer.get_pending_webhooks()
- Matches webhook email_id to conversation
- Returns when webhook received for current POC
- Updates `state["pending_webhooks"]`

**6. fetch_email.py**
- Calls InboxClient.get_email() (GET /api/inboxes/{email}/emails/{id})
- Retrieves full email with attachments
- Stores in conversation state

**7. extract_content.py**
- Calls AttachmentParser.parse()
- Converts Excel → JSON (list of dicts)
- Converts CSV → JSON (list of dicts)
- Stores extracted content as string in conversation state

**8. validate_response.py**
- Calls LLM with original request + extracted content
- LLM checks: matches request, complete data, correct format, good quality
- Returns: is_valid (bool), feedback (str)
- Stores validation result in conversation state

**9. decide_next.py**
- Examines all conversation states
- Determines next action:
  - "compose_email" if POC needs initial email
  - "compose_followup" if validation failed and attempts < 5
  - "end" if all POCs complete or failed
- Returns routing decision in output

#### webhook/server.py

**WebhookServer Class:**

**Purpose:** Receive webhook notifications from Mock SMTP Server when emails arrive.

**Architecture:**
- FastAPI app with 2 endpoints
- Stores webhook payloads in `app.state.pending_webhooks` list
- Agent nodes poll this list via `get_pending_webhooks()`

**Endpoints:**
- `POST /webhook/email-received` - Receive notification
  - Validates payload structure
  - Stores in pending_webhooks list
  - Returns 200 OK immediately
- `GET /health` - Health check

**Lifecycle:**
```python
server = WebhookServer(host, port, webhook_path)
await server.start()  # Blocking call (runs uvicorn)
await server.stop()   # Graceful shutdown
```

**Important:** Server runs in background asyncio task while agent executes.

#### tools/smtp_client.py

**SMTPClient Class:**

**Methods:**
- `async send_email(from_addr, to_addrs, subject, body_text)` → Email
  - POST to /api/send
  - Returns created Email object
- `async register_webhook(url, inbox_filter)` → WebhookRegistration
  - POST to /api/webhooks
  - Returns registration with ID

**Usage:**
```python
async with SMTPClient(settings, http_client) as client:
    email = await client.send_email(
        from_address="info-agent@gmail.com",
        to_addresses=["poc@example.com"],
        subject="Request for data",
        body_text="..."
    )
```

#### tools/inbox_client.py

**InboxClient Class:**

**Methods:**
- `async get_email(email_address, email_id)` → Email
  - GET /api/inboxes/{email}/emails/{id}
  - Returns full Email with attachments
- `async list_emails(email_address)` → list[EmailSummary]
  - GET /api/inboxes/{email}
  - Returns list of email metadata

**Usage:**
```python
async with InboxClient(settings, http_client) as client:
    email = await client.get_email(
        "info-agent@gmail.com",
        "550e8400-e29b-41d4-a716-446655440000"
    )
```

#### tools/attachment_parser.py

**AttachmentParser Class:**

**Static Methods:**
- `parse_excel(content_base64, filename)` → list[dict]
  - Decodes base64
  - Uses openpyxl to load workbook
  - Extracts headers from row 1
  - Converts rows to list of dicts
  - Returns JSON-serializable structure

- `parse_csv(content_base64, filename)` → list[dict]
  - Decodes base64
  - Uses csv.DictReader
  - Returns list of dicts

- `parse(content_base64, filename)` → list[dict]
  - Dispatches to parse_excel or parse_csv based on extension
  - Raises UnsupportedFormatError if not .xlsx or .csv

**Exception Hierarchy:**
```python
AttachmentParseError (base)
├── UnsupportedFormatError    # File extension not supported
└── CorruptedFileError        # File cannot be parsed
```

**Example:**
```python
rows = AttachmentParser.parse(
    attachment["content_base64"],
    attachment["filename"]
)
# Returns: [{"col1": "val1", "col2": "val2"}, ...]
```

#### llm/client.py

**GeminiClient Class:**

**Initialization:**
```python
from langchain_google_genai import ChatGoogleGenerativeAI

client = GeminiClient(settings)
# Creates ChatGoogleGenerativeAI instance with:
# - model: gemini-2.0-flash-exp
# - temperature: 0.7
# - max_tokens: 2048
# - timeout: 60.0
```

**Methods:**
- `async invoke(prompt: str)` → str
  - Sends prompt to Gemini
  - Returns text response
  - Handles retries and errors

**Usage in Nodes:**
```python
llm = GeminiClient(settings)
response = await llm.invoke(prompt)
parsed = json.loads(response)
```

#### llm/prompts.py

**Prompt Templates:**

**1. PARSE_INSTRUCTION_PROMPT**
```
Extract the following from this instruction:
"{user_instruction}"

Return JSON:
{
  "poc_emails": ["email1@example.com"],
  "request_type": "data_request|information_request",
  "request_description": "brief description",
  "success_criteria": "specific validation criteria"
}
```

**2. COMPOSE_EMAIL_PROMPT**
```
Compose an email to request:
- Recipient: {poc_email}
- Request: {request_description}

Return JSON:
{
  "subject": "email subject",
  "body": "email body text"
}
```

**3. VALIDATE_RESPONSE_PROMPT**
```
Original request: "{request_description}"
Success criteria: "{success_criteria}"
Received content: {extracted_content}

Analyze:
1. Contains requested information?
2. Data complete?
3. Format correct?
4. Quality acceptable?

Return JSON:
{
  "is_valid": true|false,
  "feedback": "detailed explanation"
}
```

**4. COMPOSE_FOLLOWUP_PROMPT**
```
Original request: "{request_description}"
Previous response issue: "{feedback}"
Attempt: {attempt_count} of 5

Compose follow-up email requesting corrections.

Return JSON:
{
  "subject": "Re: {original_subject}",
  "body": "follow-up email body"
}
```

### Configuration

#### Environment Variables

All settings use `MAIL_AGENT_` prefix:

```bash
# Required
MAIL_AGENT_GEMINI_API_KEY=your-api-key-here

# Optional (with defaults)
MAIL_AGENT_MOCK_SMTP_API_URL=http://localhost:8025
MAIL_AGENT_WEBHOOK_PORT=9000
MAIL_AGENT_MAX_ATTEMPTS=5
MAIL_AGENT_LOG_LEVEL=INFO
MAIL_AGENT_SQLITE_DB_PATH=./mail_agent_state.db
```

#### Configuration Validation

**Startup Checks:**
- GEMINI_API_KEY must be set (raises ValueError if missing)
- Log level must be valid (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- SQLite database parent directory created if missing
- Ports must be in range 1-65535

### Key Files Reference (Mail Agent)

| File | Purpose | Modify When |
|------|---------|-------------|
| `src/mail_agent/main.py` | CLI entrypoint | Adding new commands |
| `src/mail_agent/config.py` | Settings | Adding configuration options |
| `src/mail_agent/agent/graph.py` | State machine | Adding/removing nodes |
| `src/mail_agent/agent/state.py` | State schema | Changing state structure |
| `src/mail_agent/agent/nodes/*.py` | Node logic | Modifying node behavior |
| `src/mail_agent/webhook/server.py` | Webhook receiver | Changing webhook handling |
| `src/mail_agent/tools/attachment_parser.py` | File parsing | Supporting new formats |
| `src/mail_agent/llm/prompts.py` | LLM prompts | Improving LLM instructions |
| `src/mail_agent/llm/client.py` | LLM client | Changing LLM provider |
| `tests/test_mail_agent/*.py` | Tests | Adding new features (TDD) |

### Development Patterns (Mail Agent)

#### Adding a New LangGraph Node

1. Create node file in `agent/nodes/`
2. Define async function: `async def node_name(state: AgentState) -> AgentState`
3. Import and add node in `graph.py`: `graph.add_node("node_name", node_name)`
4. Add edges to/from new node
5. Update routing logic in `decide_next.py` if needed
6. Add tests in `tests/test_mail_agent/`

Example:
```python
# agent/nodes/save_result.py
async def save_result_node(state: AgentState) -> AgentState:
    logger.info("save_result_node: Starting")

    # Save result to file
    final_summary = state.get("final_summary", "")
    with open("result.txt", "w") as f:
        f.write(final_summary)

    logger.info("save_result_node: Completed")
    return state
```

#### Modifying LLM Prompts

**Best Practices:**
- Use structured output (JSON) for parsing
- Be specific about expected format
- Include examples in prompt
- Test with various inputs
- Log prompts and responses for debugging

**Pattern:**
```python
# In llm/prompts.py
CUSTOM_PROMPT = """
Task: {task_description}

Rules:
1. Rule one
2. Rule two

Return JSON:
{
  "field1": "value1",
  "field2": "value2"
}
"""

# In node
prompt = CUSTOM_PROMPT.format(task_description=...)
response = await llm_client.invoke(prompt)
parsed = json.loads(response)
```

#### Adding Support for New Attachment Types

1. Add extension to `AttachmentParser.SUPPORTED_EXTENSIONS`
2. Implement `parse_<format>()` static method
3. Update `parse()` method to dispatch to new parser
4. Add test data file in `test_data/`
5. Add tests in `tests/test_mail_agent/test_attachment_parser.py`

Example:
```python
# In tools/attachment_parser.py
SUPPORTED_EXTENSIONS = {".xlsx", ".csv", ".json"}

@staticmethod
def parse_json(content_base64: str, filename: str) -> list[dict]:
    file_bytes = base64.b64decode(content_base64)
    text = file_bytes.decode("utf-8")
    data = json.loads(text)
    return data if isinstance(data, list) else [data]
```

#### Extending Agent State

**Important:** Changes to state schema affect checkpointing.

**Pattern:**
1. Update TypedDict in `agent/state.py`
2. Initialize new field in `initialize_agent_state()` in `graph.py`
3. Update nodes that use the new field
4. Test with fresh SQLite database (delete old one)

Example:
```python
# In agent/state.py
class AgentState(TypedDict, total=False):
    # ... existing fields
    retry_count: int  # NEW FIELD

# In agent/graph.py
def initialize_agent_state(user_instruction: str) -> AgentState:
    return AgentState(
        # ... existing fields
        retry_count=0,  # Initialize new field
    )
```

### Testing Patterns (Mail Agent)

#### Unit Testing Nodes

**Fixtures:**
```python
@pytest.fixture
def sample_state():
    return AgentState(
        user_instruction="test instruction",
        conversations={},
        # ... more fields
    )

@pytest.mark.asyncio
async def test_parse_instruction_node(sample_state, mocker):
    # Mock LLM response
    mock_llm = mocker.patch("mail_agent.llm.client.GeminiClient.invoke")
    mock_llm.return_value = '{"poc_emails": ["test@example.com"]}'

    # Run node
    result = await parse_instruction_node(sample_state)

    # Assert
    assert result["parsed_request"]["poc_emails"] == ["test@example.com"]
```

#### Integration Testing with Mock SMTP

**Full Flow Test:**
```python
@pytest.mark.asyncio
async def test_full_agent_flow():
    # 1. Start Mock SMTP in background
    # 2. Start Mail Agent
    # 3. Simulate POC reply with attachment
    # 4. Verify agent completes successfully
    # 5. Check final state
```

**Use POC Reply Simulator:**
```python
subprocess.run([
    "python", "scripts/poc_reply_simulator.py",
    "--from", "poc@example.com",
    "--to", "info-agent@gmail.com",
    "--subject", "Re: Request",
    "--body", "Here is the data",
    "--attachment", "test_data/sample_recipes.xlsx"
])
```

### Anti-Patterns to Avoid (Mail Agent)

1. **Don't modify state outside nodes** - All state changes must happen in nodes
2. **Don't use blocking I/O** - Use async/await for all HTTP calls
3. **Don't ignore LLM errors** - Handle and log all LLM failures
4. **Don't hardcode prompts in nodes** - Define in `llm/prompts.py`
5. **Don't skip validation** - Always validate LLM responses before parsing
6. **Don't use global state** - Use dependency injection
7. **Don't bypass AttachmentParser** - Always use the parser, don't implement inline
8. **Don't commit SQLite database** - Add to .gitignore

### Important Constraints (Mail Agent)

#### LLM Behavior

**Temperature Setting:**
- 0.7 by default (balanced creativity/consistency)
- Use 0.1 for deterministic tasks (parsing)
- Use 1.0 for creative tasks (email composition)

**Token Limits:**
- Max 2048 tokens per response
- Truncate large attachments before sending to LLM
- Use summarization for very large data

**Timeout Handling:**
- 60s timeout for LLM calls
- Retry once on timeout
- Fail node if retry fails

#### State Persistence

**SQLite Checkpointing:**
- State saved after each node execution
- Thread ID: "default" (single conversation)
- Database grows with each execution
- Periodic cleanup recommended

**Migration Strategy:**
- State schema changes require new database
- Delete old database or migrate manually
- No automatic migration support

#### Webhook Timing

**Race Condition Prevention:**
- wait_for_reply polls every 1 second
- Webhook server buffers all incoming webhooks
- No timeout by default (waits indefinitely)
- Use `webhook_wait_timeout` setting to limit wait time

### Error Handling (Mail Agent)

#### Error Categories

| Category | Handling Strategy |
|----------|-------------------|
| LLM API Error | Retry once with exponential backoff, then fail node |
| Mock SMTP API Error | Fail node immediately with clear error message |
| Webhook Server Error | Log error, continue waiting |
| Attachment Parse Error | Mark validation as failed, request re-send |
| Invalid User Instruction | Fail immediately, display error to user |
| State Persistence Error | Critical error, abort execution |

#### Exception Hierarchy

```python
MailAgentError (base)
├── InstructionParseError      # LLM failed to parse instruction
├── EmailSendError             # Failed to send email via API
├── WebhookRegistrationError   # Failed to register webhook
├── EmailFetchError            # Failed to fetch email
├── AttachmentParseError       # Attachment parsing failed
│   ├── UnsupportedFormatError
│   └── CorruptedFileError
├── LLMError                   # LLM API error
│   ├── LLMConnectionError
│   └── LLMResponseParseError
└── StateError                 # Checkpointer error
```

### Testing Checklist (Mail Agent)

Before submitting changes:

- [ ] All tests pass: `pytest tests/test_mail_agent/`
- [ ] Coverage maintained: `pytest --cov=src/mail_agent --cov-report=term-missing`
- [ ] No files exceed 800 lines
- [ ] Logging added for all LLM calls
- [ ] Environment variables documented (if added)
- [ ] README.md updated (if user-facing changes)
- [ ] Architecture doc updated (if graph structure changes)
- [ ] Test with real Gemini API (not just mocks)
- [ ] Test with Mock SMTP integration
- [ ] Test multi-turn conversation flow

### Common Issues (Mail Agent)

#### "GEMINI_API_KEY is required" error

**Cause:** Environment variable not set

**Solution:** Export environment variable before running:
```bash
export MAIL_AGENT_GEMINI_API_KEY=your-key-here
mail-agent send "..."
```

#### Webhook not received

**Check:**
1. Mock SMTP Server running (check `http://localhost:8025/api/health`)
2. Webhook registered: `curl http://localhost:8025/api/webhooks`
3. Webhook URL reachable from Mock SMTP (localhost:9000)
4. Check Mail Agent logs for webhook reception
5. Verify POC reply sent to correct inbox (info-agent@gmail.com)

#### LLM returns invalid JSON

**Debug:**
1. Check logs for full LLM response
2. Verify prompt includes clear JSON format instructions
3. Test prompt directly in Gemini API console
4. Add response validation before parsing
5. Increase temperature if response too rigid

#### Agent stuck in wait_for_reply

**Cause:** No webhook received or webhook filtering issue

**Debug:**
1. Check webhook server: `curl http://localhost:9000/health`
2. Check pending webhooks in server state
3. Verify inbox filter matches agent email
4. Send test email via POC simulator
5. Set `webhook_wait_timeout` to avoid infinite wait

#### SQLite database locked

**Cause:** Multiple agent instances or unclean shutdown

**Solution:**
```bash
# Stop all agent processes
pkill -f mail-agent

# Delete database and restart
rm mail_agent_state.db
mail-agent send "..."
```

### Deployment Notes (Mail Agent)

**Prerequisites:**
- Mock SMTP Server running and accessible
- Google Cloud API key with Gemini API enabled
- Python 3.12+
- Network access to Mock SMTP ports (8025, 1025)

**Environment Setup:**
```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -e ".[dev]"

# Configure environment
export MAIL_AGENT_GEMINI_API_KEY=your-key
export MAIL_AGENT_LOG_LEVEL=INFO

# Test configuration
mail-agent health
```

**Running in Production:**

Mail Agent is designed for development/testing, not production use. For production:
- Add authentication to webhook endpoint
- Implement webhook signature verification
- Add rate limiting for LLM calls
- Use managed database instead of SQLite
- Add monitoring and alerting
- Implement timeout handling
- Add retry logic for transient failures

### Contributing (Mail Agent)

Follow coding guidelines from `/root/.claude/CLAUDE.md`:

- Files must not exceed 800 lines
- Use strict test-driven development
- Add comprehensive logging (especially for LLM calls)
- No fallback/default values (raise exceptions)
- Update README.md for user-facing changes
- Create test data in `test_data/` folder
- Create debug scripts in `scripts/` folder
- Test with real Gemini API before committing
