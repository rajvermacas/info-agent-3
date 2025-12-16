# Info Agent - Developer Documentation

## Project Overview

**Info Agent** is a three-component system for autonomous email interactions and testing:

1. **Mock SMTP Server** - Testing tool with SMTP (port 1025) + REST API (port 8025) for email workflows
2. **Mail Agent** - LangGraph-powered autonomous agent that sends requests via email, validates responses, and handles multi-turn conversations with POCs (Points of Contact)
3. **UI Server** - HTMX + Tailwind CSS web interface for Mail Agent (port 8080)

Built with aiosmtpd, FastAPI, LangGraph, HTMX, Tailwind CSS, and Google A2A protocol support.

## Development Commands

### Setup
```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -e ".[dev]"

# Copy environment template
cp .env.example .env
# Edit .env with your API keys
```

### Running

```bash
# Mock SMTP Server
uv run mock-smtp
# SMTP: localhost:1025, API: 0.0.0.0:8025
# Swagger: http://localhost:8025/docs

# Mail Agent (A2A Server)
uv run mail-agent a2a
# A2A Server: 0.0.0.0:8000
# Agent Card: http://localhost:8000/.well-known/agent.json

# Mail Agent (CLI - Direct Run)
uv run mail-agent run "send mail to raj@gmail.com asking 10 food recipes in csv file"

# A2A Client (Test Client)
python scripts/a2a_client.py info
uv run python scripts/a2a_client.py interactive

# Reply Simulator (POC Email Simulator)
uv run python scripts/poc_reply_simulator.py --from "raj@gmail.com" --to "info-agent@gmail.com" --subject "Re: Request: 10 Actor names" --body "Please find attached." --attachment ./test_data/sample_actors.csv

# UI Server
uv run ui-server
# UI: http://localhost:8080
# Send Request: http://localhost:8080/send
# Inbox: http://localhost:8080/inbox
# Dashboard: http://localhost:8080/dashboard
```

### Testing
```bash
pytest
pytest --cov=src --cov-report=html
pytest tests/test_mail_agent/  # Mail agent tests only
pytest tests/test_models.py    # Mock SMTP tests only
```

## Architecture

### High-Level Design

**Four-Server Architecture:**

1. **Mock SMTP Server** (Ports 1025, 8025)
   - Receives emails via SMTP protocol
   - REST API for email inspection
   - Webhook notifications

2. **Mail Agent - A2A Server** (Port 8000)
   - Exposes LangGraph agent via Google A2A protocol
   - JSON-RPC 2.0 over HTTP
   - Non-blocking task execution with SQLite persistence

3. **Mail Agent - Webhook Server** (Port 9000)
   - Receives email arrival notifications from Mock SMTP
   - Routes webhooks to active agent tasks
   - FastAPI + SSE streaming

4. **UI Server** (Port 8080)
   - Web interface for Mail Agent
   - HTMX + Tailwind CSS frontend
   - Communicates with A2A and Mock SMTP servers

**Mail Agent Flow:**
```
User Instruction → Parse → Compose Email → Send → Wait for Reply
                                                          ↓
                                              Webhook triggers resume
                                                          ↓
                                       Fetch Email → Extract Content → Validate
                                                          ↓
                                              Valid? → End : Retry (max 5)
```

**Key Patterns:**
- Dependency Injection
- Factory Pattern
- Async/Await
- State Machines (LangGraph)
- A2A Protocol (Agent-to-Agent)
- SQLite Checkpointing (Persistence)
- Fire-and-Forget Webhooks

### Directory Structure

```
/workspaces/info-agent-3/
├── src/
│   ├── mock_smtp/              # Mock SMTP Server
│   │   ├── main.py             # Entrypoint
│   │   ├── config.py           # Settings
│   │   ├── store/              # Email storage
│   │   │   ├── models.py       # Email, Inbox, Attachment models
│   │   │   └── inbox_store.py  # Thread-safe in-memory storage
│   │   ├── webhooks/           # Webhook system
│   │   │   ├── registry.py     # Webhook registration
│   │   │   └── dispatcher.py   # HTTP POST client
│   │   ├── smtp/               # SMTP server
│   │   │   ├── server.py       # aiosmtpd lifecycle
│   │   │   └── handler.py      # SMTP protocol handler
│   │   └── api/                # REST API
│   │       ├── router.py       # Router factory
│   │       ├── inbox_routes.py
│   │       ├── email_routes.py
│   │       ├── send_routes.py
│   │       └── webhook_routes.py
│   │
│   └── mail_agent/             # Mail Agent
│       ├── main.py             # Typer CLI entrypoint
│       ├── config.py           # Settings (LLM, SMTP, A2A)
│       ├── agent/              # LangGraph agent
│       │   ├── graph.py        # StateGraph definition
│       │   ├── state.py        # AgentState model
│       │   └── nodes/          # Graph nodes
│       │       ├── parse_instruction.py
│       │       ├── compose_email.py
│       │       ├── send_email.py
│       │       ├── wait_for_reply.py
│       │       ├── fetch_email.py
│       │       ├── extract_content.py
│       │       ├── validate_response.py
│       │       └── decide_next.py
│       ├── llm/                # LLM integration
│       │   ├── client.py       # Gemini/Azure OpenAI
│       │   └── prompts.py      # System prompts
│       ├── tools/              # Agent tools
│       │   ├── smtp_client.py  # Mock SMTP API client
│       │   ├── inbox_client.py # Email fetching
│       │   └── attachment_parser.py  # CSV/Excel parser
│       ├── webhook/            # Webhook server
│       │   └── server.py       # FastAPI + SSE
│       ├── persistence/        # State persistence
│       │   ├── checkpointer.py # SQLite checkpointer
│       │   ├── database.py     # DB initialization
│       │   └── task_store.py   # Task metadata
│       ├── task_manager/       # Task lifecycle
│       │   ├── manager.py      # Task CRUD
│       │   └── models.py       # Task models
│       └── a2a/                # A2A protocol server
│           ├── server.py       # Starlette + A2A SDK
│           ├── executor.py     # Agent executor wrapper
│           ├── agent_card.py   # Agent discovery card
│           └── routes/
│               └── tasks.py    # Task status endpoints
│
│   └── ui/                     # UI Server
│       ├── main.py             # FastAPI entrypoint
│       ├── config.py           # Settings (UI_* prefix)
│       ├── routes/             # Route handlers
│       │   ├── pages.py        # Page routes (GET /, /send, /inbox, /dashboard)
│       │   ├── send_request.py # Send request API
│       │   ├── inbox.py        # Inbox operations API
│       │   └── dashboard.py    # Dashboard API
│       ├── services/           # Backend service clients
│       │   ├── a2a_client.py   # A2A server communication
│       │   └── smtp_client.py  # Mock SMTP API communication
│       ├── templates/          # Jinja2 templates
│       │   ├── base.html       # Base template (Tailwind + HTMX)
│       │   ├── index.html      # Home page
│       │   ├── send_request.html
│       │   ├── inbox/          # Inbox templates
│       │   ├── dashboard/      # Dashboard templates
│       │   └── partials/       # HTMX partial templates
│       └── static/             # Static files (CSS)
│
├── tests/
│   ├── conftest.py
│   ├── test_models.py          # Mock SMTP tests
│   ├── test_inbox_store.py
│   ├── test_api_inboxes.py
│   ├── test_api_send.py
│   └── test_mail_agent/        # Mail agent tests
│       ├── conftest.py
│       ├── test_config.py
│       ├── test_integration.py
│       ├── test_a2a_server.py
│       ├── test_a2a_executor.py
│       ├── test_attachment_parser.py
│       ├── test_prompts.py
│       ├── test_state.py
│       ├── test_nodes/
│       ├── test_persistence/
│       └── test_task_manager/
│
├── scripts/                    # Debug/test scripts
│   ├── a2a_client.py           # A2A test client
│   ├── poc_reply_simulator.py  # Simulates POC replies
│   └── generate_test_data.py
│
├── test_data/                  # Test files (gitignored)
├── resources/reports/          # Generated reports (gitignored)
├── .dev-resources/             # Architecture docs
│   ├── architecture/
│   │   ├── mock-smtp-server.md
│   │   ├── mail-agent.md
│   │   ├── mail-agent-async.md
│   │   └── mail-agent-a2a.md
│   ├── contracts/mock-smtp.json
│   └── prompts/
├── pyproject.toml
├── .env.example
├── README.md
└── CLAUDE.md
```

### Key Components

#### Mock SMTP Server

| Component | Responsibility |
|-----------|---------------|
| **main.py** | Initializes shared resources, starts SMTP + API concurrently |
| **config.py** | Pydantic Settings with `MOCK_SMTP_*` env vars |
| **store/inbox_store.py** | Thread-safe in-memory storage, FIFO eviction |
| **smtp/handler.py** | Parses MIME, extracts attachments, stores emails, triggers webhooks |
| **webhooks/dispatcher.py** | Async httpx client with retry + exponential backoff |
| **api/router.py** | Router factory with dependency injection |

#### Mail Agent

| Component | Responsibility |
|-----------|---------------|
| **main.py** | Typer CLI with `run` and `a2a` commands |
| **config.py** | Pydantic Settings with `MAIL_AGENT_*` env vars, supports Gemini + Azure OpenAI |
| **agent/graph.py** | StateGraph with nodes: parse → compose → send → wait → fetch → extract → validate → decide |
| **agent/state.py** | AgentState model (instruction, conversations, attempts, errors, etc.) |
| **llm/client.py** | LLM client factory, supports Gemini (default) and Azure OpenAI |
| **tools/smtp_client.py** | Async httpx client for Mock SMTP API |
| **tools/attachment_parser.py** | Parses CSV/Excel attachments with openpyxl |
| **webhook/server.py** | FastAPI webhook receiver, SSE streaming for task updates |
| **persistence/checkpointer.py** | SQLite-based LangGraph checkpointer for state persistence |
| **task_manager/manager.py** | Task lifecycle (create, update, get, list) |
| **a2a/server.py** | Starlette app with A2A SDK, non-blocking execution |
| **a2a/executor.py** | Wraps LangGraph agent, handles task lifecycle |

#### UI Server

| Component | Responsibility |
|-----------|---------------|
| **main.py** | FastAPI entrypoint with lifespan, creates app |
| **config.py** | Pydantic Settings with `UI_*` env vars |
| **routes/pages.py** | Page routes (/, /send, /inbox, /dashboard) |
| **routes/send_request.py** | Send request API (POST /api/send/submit) |
| **routes/inbox.py** | Inbox operations (list, view, reply with attachments) |
| **routes/dashboard.py** | Dashboard operations (list tasks, view task detail) |
| **services/a2a_client.py** | A2A server communication (send tasks, get status) |
| **services/smtp_client.py** | Mock SMTP API communication (list inboxes, send emails) |
| **templates/base.html** | Base template with Tailwind CSS CDN + HTMX |
| **templates/partials/*.html** | HTMX partial templates for dynamic updates |

### Mail Agent State Machine

**AgentState Fields:**
- `instruction` - User instruction (e.g., "send mail to x@y.com asking 10 recipes")
- `conversations` - Dict[poc_email, ConversationState] tracking each POC interaction
- `current_poc` - Current POC being processed
- `progress_messages` - User-facing progress updates
- `error` - Error message if any
- `webhook_id` - Registered webhook ID

**ConversationState Fields:**
- `poc_email` - POC email address
- `status` - pending/waiting/completed/failed
- `attempt_count` - Current attempt number (max 5)
- `sent_emails` - List of sent email IDs
- `received_emails` - List of received email IDs
- `validation_results` - List of validation outcomes
- `final_result` - valid/invalid/error/pending
- `attachments` - List of parsed attachments

**Node Flow:**
1. **parse_instruction** - Extract POC emails and requirements from instruction
2. **compose_email** - Generate email content using LLM
3. **send_email** - Send via Mock SMTP API
4. **wait_for_reply** - Interrupt, wait for webhook notification
5. **fetch_email** - Retrieve reply from Mock SMTP
6. **extract_content** - Parse attachments (CSV/Excel)
7. **validate_response** - Verify response meets requirements using LLM
8. **decide_next** - Retry if invalid (max 5 attempts) or end

### A2A Protocol Integration

**Endpoints:**
- `GET /.well-known/agent.json` - Agent discovery card (RFC 8615)
- `POST /jsonrpc` - JSON-RPC 2.0 endpoint for task execution
- `GET /api/tasks` - List all tasks
- `GET /api/tasks/{task_id}` - Get task status + SSE streaming

**Agent Card:**
```json
{
  "name": "Mail Agent",
  "version": "1.0.0",
  "description": "Intelligent email assistant powered by LangGraph",
  "url": "http://localhost:8000",
  "capabilities": ["email_request", "data_validation", "attachment_parsing"]
}
```

**Task Execution:**
- Non-blocking: Task runs in background
- Persistent: State saved to SQLite
- Resumable: Can interrupt and resume on webhook
- SSE Streaming: Real-time progress updates

## Configuration

### Environment Variables

#### Mock SMTP Server (`MOCK_SMTP_*`)

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

#### Mail Agent (`MAIL_AGENT_*`)

```bash
# Mock SMTP Connection
MAIL_AGENT_MOCK_SMTP_API_URL=http://localhost:8025
MAIL_AGENT_MOCK_SMTP_HOST=localhost
MAIL_AGENT_MOCK_SMTP_PORT=1025

# Agent Identity
MAIL_AGENT_AGENT_EMAIL=info-agent@gmail.com

# Webhook Server
MAIL_AGENT_WEBHOOK_HOST=localhost
MAIL_AGENT_WEBHOOK_PORT=9000
MAIL_AGENT_WEBHOOK_PATH=/webhook/email-received

# LLM (Gemini default)
MAIL_AGENT_LLM_PROVIDER=gemini  # or "azure-openai"
MAIL_AGENT_GEMINI_API_KEY=your-key
MAIL_AGENT_GEMINI_MODEL=gemini-2.5-flash
MAIL_AGENT_LLM_TEMPERATURE=0.0
MAIL_AGENT_LLM_MAX_TOKENS=4096

# Azure OpenAI (alternative)
# MAIL_AGENT_AZURE_OPENAI_API_KEY=your-key
# MAIL_AGENT_AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
# MAIL_AGENT_AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4
# MAIL_AGENT_AZURE_OPENAI_API_VERSION=2024-02-15-preview

# Agent Behavior
MAIL_AGENT_MAX_ATTEMPTS=5

# State Persistence
MAIL_AGENT_SQLITE_DB_PATH=./mail_agent_state.db

# A2A Server
MAIL_AGENT_A2A_HOST=0.0.0.0
MAIL_AGENT_A2A_PORT=8000
MAIL_AGENT_A2A_AGENT_NAME=Mail Agent
MAIL_AGENT_A2A_AGENT_VERSION=1.0.0

# Logging
MAIL_AGENT_LOG_LEVEL=INFO
```

#### UI Server (`UI_*`)

```bash
# Server settings
UI_HOST=0.0.0.0                            # Default: 0.0.0.0
UI_PORT=8080                               # Default: 8080

# External service URLs
UI_A2A_SERVER_URL=http://localhost:8000    # A2A server URL
UI_MOCK_SMTP_API_URL=http://localhost:8025 # Mock SMTP API URL

# Default inbox
UI_DEFAULT_INBOX_EMAIL=info-agent@gmail.com

# HTTP client settings
UI_HTTP_TIMEOUT_SECONDS=30.0               # Default: 30.0
UI_HTTP_LONG_POLL_TIMEOUT_SECONDS=300.0    # Default: 300.0

# Logging
UI_LOG_LEVEL=INFO                          # Default: INFO
```

## Key Files Reference

| File | Purpose | Modify When |
|------|---------|-------------|
| **Mock SMTP** | | |
| `mock_smtp/main.py` | Server entrypoint | Adding shared resources |
| `mock_smtp/store/inbox_store.py` | Storage logic | Changing storage behavior |
| `mock_smtp/smtp/handler.py` | Email parsing | Changing MIME handling |
| `mock_smtp/api/*_routes.py` | API endpoints | Adding endpoints |
| **Mail Agent** | | |
| `mail_agent/main.py` | CLI entrypoint | Adding commands |
| `mail_agent/config.py` | Settings | Adding config options |
| `mail_agent/agent/graph.py` | State graph | Adding/removing nodes |
| `mail_agent/agent/nodes/*.py` | Graph nodes | Changing agent behavior |
| `mail_agent/llm/prompts.py` | LLM prompts | Changing prompt templates |
| `mail_agent/tools/attachment_parser.py` | Attachment parsing | Adding file formats |
| `mail_agent/a2a/server.py` | A2A server | Changing A2A integration |
| `mail_agent/persistence/checkpointer.py` | State persistence | Changing persistence logic |
| **UI Server** | | |
| `ui/main.py` | Server entrypoint | Adding routes, lifespan |
| `ui/config.py` | Settings | Adding config options |
| `ui/routes/*.py` | Route handlers | Adding pages or API endpoints |
| `ui/services/*.py` | Service clients | Changing A2A/SMTP communication |
| `ui/templates/*.html` | Jinja2 templates | Changing UI |
| `ui/templates/partials/*.html` | HTMX partials | Adding dynamic updates |

## Development Patterns

### Adding LangGraph Node

1. Create `agent/nodes/my_node.py` with function signature: `def my_node(state: AgentState) -> AgentState`
2. Import in `agent/nodes/__init__.py`
3. Add to graph in `agent/graph.py`: `.add_node("my_node", my_node)`
4. Add edge: `.add_edge("previous_node", "my_node")`
5. Add tests in `tests/test_mail_agent/test_nodes/test_my_node.py`

### Adding LLM Prompt

1. Add template to `llm/prompts.py` (use `PromptTemplate` or `ChatPromptTemplate`)
2. Export in `llm/__init__.py`
3. Use in node: `prompt.format(**kwargs)`

### Adding Configuration

1. Add field to `Settings` in `config.py` with `Field()` descriptor
2. Add validation if needed (`@field_validator`)
3. Update `.env.example`
4. Update CLAUDE.md Configuration section

### Testing

**Unit Tests:** Isolated components (use pytest fixtures)
**Integration Tests:** End-to-end flows (use TestClient for APIs)
**Fixtures:** Defined in `conftest.py` at root and `test_mail_agent/conftest.py`

## Anti-Patterns to Avoid

1. **No persistent storage in Mock SMTP** - In-memory is intentional
2. **No blocking webhooks** - Fire-and-forget by design
3. **No global LLM client** - Use dependency injection via config
4. **No direct state mutation** - Return new state dict from nodes
5. **No hardcoded POC emails** - Extract from instruction
6. **No missing locks in InboxStore** - Always `with self._lock:`

## Important Constraints

### Fail-Fast Behavior

**Mock SMTP:**
- Invalid config → `ValueError` on startup
- Attachment too large → SMTP 552 error
- Inbox full → FIFO eviction

**Mail Agent:**
- No LLM API key → Raise exception on startup
- Mock SMTP unreachable → Warning, continue anyway
- Max attempts reached → Mark conversation as failed
- Invalid instruction → Error in parse_instruction node

### Error Handling

**Mock SMTP:**
- SMTP: Catch all exceptions, log, return SMTP error code
- API: FastAPI/Pydantic validation (422), 404, 500
- Webhooks: Log failures, don't block storage

**Mail Agent:**
- Nodes: Return error in state, don't raise exceptions
- LLM failures: Log and retry (handled by LangChain)
- Webhook timeout: Continue waiting (configurable timeout)
- A2A executor: Catch all exceptions, update task status

### Data Access

**InboxStore (Mock SMTP):**
```python
# BAD: inbox_store._inboxes[email].emails.append(email)
# GOOD: inbox_store.store_email(email)
```

**AgentState (Mail Agent):**
```python
# BAD: state["conversations"][poc]["status"] = "waiting"
# GOOD: return {"conversations": updated_conversations}
```

### Logging

- **DEBUG** - Detailed flow (LLM requests, webhook routing)
- **INFO** - Important events (email sent, task created, node transitions)
- **WARNING** - Recoverable issues (webhook timeout, retry attempt)
- **ERROR** - Failures (validation failed, LLM error)
- **CRITICAL** - Server failures (startup errors)

### Memory Management

**Mock SMTP:**
- `max_emails_per_inbox=1000` prevents unbounded growth
- FIFO eviction when limit reached

**Mail Agent:**
- SQLite checkpoints prevent in-memory state growth
- Attachment content stored as base64 (consider limits)

## Testing Checklist

Before submitting changes:

- [ ] All tests pass: `pytest`
- [ ] Coverage maintained: `pytest --cov=src --cov-report=term-missing`
- [ ] No files exceed 800 lines
- [ ] Logging added for new operations
- [ ] Environment variables documented in `.env.example`
- [ ] README.md updated (if user-facing changes)
- [ ] Architecture docs updated (if structural changes)

## Contributing

Follow coding guidelines from `/root/.claude/CLAUDE.md`:
- Files ≤ 800 lines
- Strict test-driven development
- Comprehensive logging
- No fallback/default values (raise exceptions)
- Test data in `test_data/`, debug scripts in `scripts/`
- Update documentation for user-facing changes
