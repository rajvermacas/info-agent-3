# Info Agent 3 - Developer Documentation

## Project Overview

Two integrated services:
1. **Mock SMTP Server** - Testing SMTP server with REST API and webhook support
2. **Mail Agent** - Autonomous LangGraph-based email agent for data collection

## Development Commands

### Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
```

### Running

```bash
# Mock SMTP Server
mock-smtp  # SMTP: localhost:1025, API: 0.0.0.0:8025

# Mail Agent
MAIL_AGENT_GEMINI_API_KEY=your-key mail-agent send "instruction"
mail-agent health

# POC Reply Simulator
python scripts/poc_reply_simulator.py --from "alice@company.com" --to "info-agent@gmail.com" \
  --subject "Re: Request" --body "Response" --attachment test_data/sample_recipes.xlsx
```

### Testing

```bash
pytest
pytest --cov=src/mock_smtp --cov=src/mail_agent --cov-report=html
pytest tests/test_mail_agent/test_attachment_parser.py -v
```

## Architecture

### System Integration

```
┌──────────────────────┐                 ┌──────────────────────┐
│   MAIL AGENT         │                 │   MOCK SMTP SERVER   │
│   (LangGraph)        │─────────────────▶  (aiosmtpd+FastAPI) │
│                      │  POST /api/send │                      │
│  - Parse instruction │◀────────────────│  - Email storage     │
│  - Compose email     │  POST /webhook  │  - Webhook dispatch  │
│  - Multi-turn logic  │                 │                      │
└──────────────────────┘                 └──────────────────────┘
```

## Part 1: Mock SMTP Server

### Key Patterns
- **Dual-Server Architecture**: SMTP (aiosmtpd:1025) + REST API (FastAPI:8025)
- **Shared State**: InboxStore (thread-safe), WebhookRegistry, WebhookDispatcher
- **Dependency Injection**: Components receive dependencies via constructor
- **Fire-and-Forget Webhooks**: Async dispatch, failures logged only

### Directory Structure

```
src/mock_smtp/
├── main.py                 # Entrypoint, lifespan management
├── config.py               # Pydantic settings (MOCK_SMTP_ env vars)
├── store/
│   ├── models.py           # Email, Inbox, Attachment models
│   └── inbox_store.py      # Thread-safe in-memory storage
├── webhooks/
│   ├── registry.py         # Webhook URL CRUD
│   └── dispatcher.py       # Async HTTP POST with retry
├── smtp/
│   ├── server.py           # AIOSMTPD lifecycle
│   └── handler.py          # SMTP handler (stores + webhooks)
└── api/
    ├── router.py           # Router factory
    ├── inbox_routes.py     # GET/DELETE inboxes
    ├── email_routes.py     # GET/DELETE emails
    ├── send_routes.py      # POST /api/send
    └── webhook_routes.py   # Webhook CRUD
```

### Key Components

**main.py**: Initialize InboxStore/WebhookRegistry/WebhookDispatcher → Start SMTP + FastAPI → Lifespan management

**config.py**: Pydantic Settings with `MOCK_SMTP_*` env vars. Key settings: ports, max_emails_per_inbox (1000), max_attachment_size_mb (10), webhook_timeout_seconds (10), log_level.

**store/models.py**:
- Email: id, from_address, to_addresses, subject, body_text/html, attachments, headers, received_at
- Inbox: email_address, emails[], methods: add_email(), get_email_by_id(), delete_email(), clear()
- Attachment: filename, content_type, size_bytes, content_base64

**store/inbox_store.py**: Thread-safe storage with `threading.Lock`. Auto-creates inboxes. FIFO eviction at max_emails_per_inbox.

**webhooks/dispatcher.py**: Async HTTP POST with retry/timeout. Payload: event, email_id, from, to, subject, has_attachments, received_at. Headers: X-Webhook-Event, X-Email-ID, X-Webhook-Timestamp.

**smtp/handler.py**: Parses MIME → validates sizes → stores Email → triggers webhooks → returns "250 OK"

**api/router.py**: Factory pattern for dependency injection

### Configuration

```bash
MOCK_SMTP_SMTP_PORT=1025
MOCK_SMTP_API_PORT=8025
MOCK_SMTP_MAX_EMAILS_PER_INBOX=1000
MOCK_SMTP_MAX_ATTACHMENT_SIZE_MB=10
MOCK_SMTP_WEBHOOK_TIMEOUT_SECONDS=10.0
MOCK_SMTP_LOG_LEVEL=INFO
```

### Development Patterns

**Add API Endpoint**: Create route in `api/*_routes.py` → use dependency injection → add tests → update OpenAPI schema

**Add Config Option**: Add field to Settings with Field() → add validation → update docs

**Thread Safety**: Always use `with self._lock:` for state modifications

**Testing**: Use fixtures from conftest.py. Fresh InboxStore/WebhookRegistry per test.

### Anti-Patterns
- Don't add persistent storage (in-memory is intentional)
- Don't add authentication (open relay by design)
- Don't make webhooks blocking
- Don't use global variables

### Error Handling
- SMTP: Catch all exceptions, log, return SMTP error code
- API: FastAPI/Pydantic handles validation (422). 404 for not found.
- Webhooks: Log failures, don't retry, don't block

---

## Part 2: Mail Agent

### Overview

LangGraph-based autonomous email agent using Google Gemini 2.0 Flash.

**Capabilities**: Parse instructions → compose emails → send via API → monitor webhooks → parse attachments (Excel/CSV) → validate with LLM → multi-turn conversations (max 5 attempts)

**Tech Stack**: LangGraph, Gemini 2.0 Flash, SQLite checkpointing, FastAPI webhook server, openpyxl, httpx

### Architecture

```
START → parse_instruction → decide_next
           ↓                      ↓
    compose_email/compose_followup
           ↓
    send_email → wait_for_reply → fetch_email
           ↓
    extract_content → validate_response → decide_next → (loop/end)
```

### Directory Structure

```
src/mail_agent/
├── main.py                 # Typer CLI (send, health)
├── config.py               # Pydantic Settings (MAIL_AGENT_ env vars)
├── agent/
│   ├── graph.py            # StateGraph definition
│   ├── state.py            # AgentState TypedDict
│   └── nodes/              # 9 node functions
├── webhook/
│   └── server.py           # FastAPI webhook receiver (:9000)
├── tools/
│   ├── smtp_client.py      # Send email via API
│   ├── inbox_client.py     # Fetch emails via API
│   └── attachment_parser.py # Excel/CSV → JSON
└── llm/
    ├── client.py           # GeminiClient wrapper
    └── prompts.py          # Prompt templates
```

### Key Components

**agent/state.py**:
- AgentState: user_instruction, parsed_request, conversations{}, pending_webhooks[], progress_messages[], final_summary
- ConversationState (per POC): status, attempt_count, sent_emails[], received_emails[], validation_results[], final_result

**agent/graph.py**: Creates StateGraph with 9 nodes + SQLite checkpointing. Routing logic in decide_next.

**9 Nodes**:
1. parse_instruction: LLM extracts POCs, request, criteria
2. compose_email: LLM generates initial email
3. compose_followup: LLM generates correction request
4. send_email: POST /api/send
5. wait_for_reply: Polls webhook server
6. fetch_email: GET email with attachments
7. extract_content: Parse Excel/CSV
8. validate_response: LLM validates content
9. decide_next: Routes to next action

**webhook/server.py**: FastAPI on :9000. POST /webhook/email-received stores payloads. Agent polls get_pending_webhooks().

**tools/attachment_parser.py**:
- parse_excel(): openpyxl → list[dict]
- parse_csv(): csv.DictReader → list[dict]
- Exceptions: UnsupportedFormatError, CorruptedFileError

**llm/client.py**: GeminiClient wrapper with invoke(prompt) → str. Uses langchain-google-genai.

**llm/prompts.py**: 4 templates: PARSE_INSTRUCTION, COMPOSE_EMAIL, VALIDATE_RESPONSE, COMPOSE_FOLLOWUP (all return JSON)

### Configuration

```bash
# Required
MAIL_AGENT_GEMINI_API_KEY=your-key

# Optional
MAIL_AGENT_MOCK_SMTP_API_URL=http://localhost:8025
MAIL_AGENT_WEBHOOK_PORT=9000
MAIL_AGENT_MAX_ATTEMPTS=5
MAIL_AGENT_LOG_LEVEL=INFO
MAIL_AGENT_SQLITE_DB_PATH=./mail_agent_state.db
```

### Development Patterns

**Add Node**: Create in `agent/nodes/` → add to graph.py → update routing → add tests

**Modify Prompts**: Define in prompts.py → use JSON output → validate before parsing → log prompts/responses

**Add Attachment Type**: Add to SUPPORTED_EXTENSIONS → implement parse_<format>() → dispatch in parse() → add test data/tests

**Extend State**: Update TypedDict in state.py → initialize in graph.py → test with fresh DB

### Anti-Patterns
- Don't modify state outside nodes
- Don't use blocking I/O
- Don't hardcode prompts in nodes
- Don't skip LLM validation
- Don't commit SQLite database

### Error Handling

| Category | Strategy |
|----------|----------|
| LLM API Error | Retry once, then fail node |
| Mock SMTP API Error | Fail immediately with message |
| Webhook Server Error | Log, continue waiting |
| Attachment Parse Error | Mark validation failed, request re-send |
| Invalid User Instruction | Fail immediately |
| State Persistence Error | Critical error, abort |

### Common Issues

**GEMINI_API_KEY required**: Export MAIL_AGENT_GEMINI_API_KEY before running

**Webhook not received**: Check Mock SMTP running, webhook registered, URL reachable, inbox filter matches

**LLM invalid JSON**: Check logs, verify prompt format, test in Gemini console, add validation

**Agent stuck in wait_for_reply**: Check webhook server health, pending webhooks, set webhook_wait_timeout

**SQLite locked**: `pkill -f mail-agent && rm mail_agent_state.db`

## Key Files Reference

### Mock SMTP
| File | Purpose | Modify When |
|------|---------|-------------|
| main.py | Server entrypoint | Adding shared resources |
| config.py | Settings | Adding config options |
| store/models.py | Data models | Changing structure |
| smtp/handler.py | SMTP processing | Changing parsing logic |
| webhooks/dispatcher.py | Webhook client | Changing payload/behavior |
| api/*_routes.py | API endpoints | Adding endpoints |

### Mail Agent
| File | Purpose | Modify When |
|------|---------|-------------|
| main.py | CLI entrypoint | Adding commands |
| agent/graph.py | State machine | Adding/removing nodes |
| agent/state.py | State schema | Changing structure |
| agent/nodes/*.py | Node logic | Modifying behavior |
| tools/attachment_parser.py | File parsing | Supporting new formats |
| llm/prompts.py | LLM prompts | Improving instructions |

## Testing Checklist

Before submitting:
- [ ] All tests pass: `pytest`
- [ ] Coverage maintained: `pytest --cov=src --cov-report=term-missing`
- [ ] No files exceed 800 lines
- [ ] Logging added for operations
- [ ] Environment variables documented
- [ ] README.md updated (if user-facing)
- [ ] Test with real Gemini API (Mail Agent)
- [ ] Test Mock SMTP integration

## Contributing

Follow `/root/.claude/CLAUDE.md`:
- Files must not exceed 800 lines
- Use strict TDD
- Add comprehensive logging
- No fallback/default values (raise exceptions)
- Create test data in `test_data/`
- Create scripts in `scripts/`
- Keep project root clean
