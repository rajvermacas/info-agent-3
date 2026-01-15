# Info Agent - Developer Quick Reference

## System Overview

**Info Agent** is a four-server autonomous email interaction system with real-time progress tracking:

1. **Mock SMTP Server** (Ports 1025 SMTP, 8025 API) - Email testing infrastructure
2. **Mail Agent A2A Server** (Port 8000) - LangGraph agent with A2A protocol + SSE streaming
3. **Mail Agent Webhook Server** (Port 9000) - Email notification receiver
4. **UI Server** (Port 8080) - Web interface (HTMX + Tailwind CSS + SSE)

**Tech Stack**: aiosmtpd, FastAPI, LangGraph, HTMX, Tailwind CSS, SQLite, Gemini/Azure OpenAI/OpenRouter, SSE

```
┌─────────────────┐         ┌──────────────────────┐
│   UI Server     │◄────────┤   Browser (User)     │
│   Port 8080     │  HTTP   │   - HTMX interface   │
└────────┬────────┘  SSE    │   - Real-time updates│
         │                  └──────────────────────┘
         │ JSON-RPC/SSE
         ▼
┌─────────────────────────────────────────────┐
│   Mail Agent A2A Server (Port 8000)         │
│   - Task execution (LangGraph)              │
│   - Progress events (SSE streaming)         │
│   - A2A protocol (JSON-RPC 2.0)             │
└────┬───────────────────────────────┬────────┘
     │                               │
     │ REST API                      │ Webhook
     ▼                               ▼
┌─────────────────┐         ┌────────────────────┐
│  Mock SMTP      │────────►│  Webhook Server    │
│  Ports 1025/8025│  HTTP   │  Port 9000         │
│  - SMTP + API   │  POST   │  - Email callbacks │
└─────────────────┘         └────────────────────┘
```

---

## Quick Start Commands

```bash
# Setup
python -m venv venv && source venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env  # Configure API keys

# Run servers
uv run mock-smtp                    # Mock SMTP (1025, 8025)
uv run mail-agent a2a               # A2A Server (8000) + Webhook (9000)
uv run ui-server                    # UI Server (8080)

# CLI mode
uv run mail-agent run "send mail to raj@gmail.com asking 10 recipes in csv"

# Testing
pytest
pytest --cov=src --cov-report=html
```

---

## Feature → File Mapping

### Email Sending & Receiving
- **SMTP Handler**: `src/mock_smtp/smtp/handler.py` - MIME parsing, attachments
- **Send API**: `src/mock_smtp/api/send_routes.py` - REST send endpoint
- **Agent Send**: `src/mail_agent/agent/nodes/send_email.py` - Agent send logic
- **UI Send**: `src/ui/routes/send_request.py` - UI send form
- **SMTP Sender**: `src/mail_agent/tools/smtp_sender.py` - Direct SMTP email sending

### Inbox Management
- **Storage**: `src/mock_smtp/store/inbox_store.py` - Thread-safe email store
- **Models**: `src/mock_smtp/store/models.py` - Email/Attachment models
- **Inbox API**: `src/mock_smtp/api/inbox_routes.py` - List inboxes
- **Email API**: `src/mock_smtp/api/email_routes.py` - Get email details
- **Agent Fetch**: `src/mail_agent/agent/nodes/fetch_email.py` - Agent fetch
- **Inbox Client**: `src/mail_agent/tools/inbox_client.py` - Inbox API client
- **UI Inbox**: `src/ui/routes/inbox.py` - UI inbox viewer

### Task Execution & Progress Tracking
- **A2A Server**: `src/mail_agent/a2a/server.py` - JSON-RPC server
- **Executor**: `src/mail_agent/a2a/executor.py` - Agent wrapper with progress events
- **Progress Store**: `src/mail_agent/a2a/progress_store.py` - SSE event storage
- **Task Routes**: `src/mail_agent/a2a/routes/tasks.py` - Task list/status endpoints
- **Progress Routes**: `src/mail_agent/a2a/routes/progress.py` - SSE streaming endpoint
- **Manager**: `src/mail_agent/task_manager/manager.py` - Task lifecycle
- **Task Store**: `src/mail_agent/persistence/task_store.py` - Task persistence
- **UI Dashboard**: `src/ui/routes/dashboard.py` - Task status UI
- **SSE Routes**: `src/ui/routes/sse.py` - SSE proxy for browser
- **SSE Client**: `src/ui/services/sse_client.py` - SSE client service

### State & Persistence
- **Agent State**: `src/mail_agent/agent/state.py` - AgentState, ConversationState
- **Checkpointer**: `src/mail_agent/persistence/checkpointer.py` - SQLite checkpoints
- **Database**: `src/mail_agent/persistence/database.py` - DB initialization

### Webhooks & Notifications
- **Registry**: `src/mock_smtp/webhooks/registry.py` - Webhook registration
- **Dispatcher**: `src/mock_smtp/webhooks/dispatcher.py` - HTTP POST with retry
- **Webhook Routes**: `src/mock_smtp/api/webhook_routes.py` - Webhook CRUD API
- **Webhook Server**: `src/mail_agent/webhook/server.py` - FastAPI webhook receiver
- **Wait Node**: `src/mail_agent/agent/nodes/wait_for_reply.py` - Interrupt + wait

### LLM & Validation
- **Client**: `src/mail_agent/llm/client.py` - Gemini/Azure/OpenRouter factory
- **Prompts**: `src/mail_agent/llm/prompts.py` - System prompts
- **Parse**: `src/mail_agent/agent/nodes/parse_instruction.py` - Extract POC/requirements
- **Compose**: `src/mail_agent/agent/nodes/compose_email.py` - Generate email
- **Validate**: `src/mail_agent/agent/nodes/validate_response.py` - Check response
- **Success Reply**: `src/mail_agent/agent/nodes/compose_success_reply.py` - Generate acknowledgment
- **Send Success**: `src/mail_agent/agent/nodes/send_success_reply.py` - Send acknowledgment

### Attachments & Email Redirects
- **Parser**: `src/mail_agent/tools/attachment_parser.py` - CSV/Excel parsing
- **Extract**: `src/mail_agent/agent/nodes/extract_content.py` - Extraction node
- **Redirect Handler**: `src/mail_agent/agent/nodes/handle_redirect.py` - POC redirect logic

### Configuration
- **Mock SMTP**: `src/mock_smtp/config.py` - `MOCK_SMTP_*` vars
- **Mail Agent**: `src/mail_agent/config.py` - `MAIL_AGENT_*` vars
- **UI Server**: `src/ui/config.py` - `UI_*` vars

---

## All Key Features

### 1. Autonomous Email Workflows
**Description**: LangGraph-powered agent executes multi-step email interactions with POCs.
**Files**:
- `src/mail_agent/agent/graph.py` - Agent graph definition
- `src/mail_agent/agent/nodes/` - All workflow nodes
- `src/mail_agent/agent/state.py` - State management

### 2. Real-Time Progress Tracking (SSE)
**Description**: Server-Sent Events provide live task progress updates to the UI.
**Files**:
- `src/mail_agent/a2a/progress_store.py` - Event storage
- `src/mail_agent/a2a/routes/progress.py` - SSE streaming endpoint
- `src/ui/routes/sse.py` - SSE proxy
- `src/ui/services/sse_client.py` - SSE client
- `src/ui/templates/partials/progress_log.html` - Progress display

### 3. A2A Protocol Support
**Description**: Google Agent-to-Agent protocol for standardized agent communication.
**Files**:
- `src/mail_agent/a2a/server.py` - A2A JSON-RPC server
- `src/mail_agent/a2a/agent_card.py` - Agent card (RFC 8615)
- `src/ui/services/a2a_client.py` - A2A client

### 4. Mock SMTP Server
**Description**: Full SMTP server with REST API for testing email workflows.
**Files**:
- `src/mock_smtp/smtp/server.py` - SMTP protocol server
- `src/mock_smtp/smtp/handler.py` - Email handler
- `src/mock_smtp/api/` - REST API routes
- `src/mock_smtp/store/inbox_store.py` - In-memory storage

### 5. Webhook-Based Task Resumption
**Description**: Email arrivals trigger webhooks to resume suspended agent tasks.
**Files**:
- `src/mock_smtp/webhooks/dispatcher.py` - Webhook dispatcher
- `src/mail_agent/webhook/server.py` - Webhook receiver
- `src/mail_agent/agent/nodes/wait_for_reply.py` - Interruptible wait

### 6. LLM-Powered Content Generation & Validation
**Description**: Gemini/Azure OpenAI/OpenRouter for email composition and response validation.
**Files**: `src/mail_agent/llm/client.py`, `src/mail_agent/agent/nodes/compose_email.py`, `src/mail_agent/agent/nodes/validate_response.py`, `src/mail_agent/agent/nodes/compose_success_reply.py`

### 7. Attachment Processing
**Description**: Parse CSV and Excel attachments from POC emails.
**Files**: `src/mail_agent/tools/attachment_parser.py`, `src/mail_agent/agent/nodes/extract_content.py`

### 8. Email Redirect Handling
**Description**: When POC suggests alternate contact, agent automatically redirects request.
**Files**: `src/mail_agent/agent/nodes/handle_redirect.py`, `src/mail_agent/agent/nodes/validate_response.py`

### 9. Web UI (HTMX + Tailwind)
**Description**: Interactive web interface for task submission and monitoring.
**Files**: `src/ui/routes/*`, `src/ui/templates/*`, `src/ui/static/css/*`

### 10. Task Management & Persistence
**Description**: SQLite-backed task storage with state checkpointing.
**Files**: `src/mail_agent/task_manager/manager.py`, `src/mail_agent/persistence/task_store.py`, `src/mail_agent/persistence/checkpointer.py`

---

## Integration Points

### UI Server → A2A Server
**Protocol**: JSON-RPC 2.0 over HTTP + SSE
**Client**: `src/ui/services/a2a_client.py`, `src/ui/services/sse_client.py`
**Endpoints**:
- `POST /jsonrpc` - Execute task (`tasks.execute` method)
- `GET /api/tasks` - List all tasks
- `GET /api/tasks/{task_id}` - Get task status
- `GET /api/tasks/{task_id}/progress` - SSE progress stream

**Flow**: User submits → A2A creates task → Agent executes → UI streams real-time updates via SSE

### UI Server → Mock SMTP Server
**Protocol**: REST API + Direct SMTP
**Clients**: `src/ui/services/smtp_client.py`, `src/ui/services/smtp_sender.py`
**Endpoints**:
- `GET /api/inboxes` - List inboxes
- `GET /api/inboxes/{inbox}/emails` - List emails
- `GET /api/emails/{email_id}` - Email detail
- `POST /api/send` - Send email (REST)
- SMTP protocol (port 1025) - Send email (direct)

**Flow**: UI fetches inbox → displays emails → sends replies via SMTP

### Mail Agent → Mock SMTP Server
**Protocol**: REST API
**Client**: `src/mail_agent/tools/smtp_client.py`, `src/mail_agent/tools/inbox_client.py`
**Endpoints**:
- `POST /api/send` - Send email
- `POST /api/webhooks` - Register webhook
- `DELETE /api/webhooks/{webhook_id}` - Unregister
- `GET /api/inboxes/{inbox}/emails` - Fetch emails

**Flow**: Agent sends → registers webhook → waits (interrupt) → webhook triggers resume → fetches reply

### Mock SMTP → Mail Agent Webhook
**Protocol**: HTTP POST (fire-and-forget with retry)
**Target**: `http://localhost:9000/webhook/email-received`
**Dispatcher**: `src/mock_smtp/webhooks/dispatcher.py`
**Receiver**: `src/mail_agent/webhook/server.py`
**Payload**: `{"inbox": "...", "email_id": "...", "metadata": {...}}`

**Flow**: Email arrives → webhook fired (async) → agent resumes from wait state

---

## Servers Architecture

### Server 1: Mock SMTP Server
**Ports**: 1025 (SMTP), 8025 (API)
**Purpose**: Email testing infrastructure
**Components**:
- SMTP protocol handler (`src/mock_smtp/smtp/`)
- REST API (`src/mock_smtp/api/`)
- In-memory email storage (`src/mock_smtp/store/`)
- Webhook dispatcher (`src/mock_smtp/webhooks/`)

**Talks to**:
- Mail Agent Webhook Server (HTTP POST for email notifications)

### Server 2: Mail Agent A2A Server
**Port**: 8000
**Purpose**: Agent execution and task management
**Components**:
- JSON-RPC 2.0 endpoint (`src/mail_agent/a2a/server.py`)
- LangGraph agent executor (`src/mail_agent/a2a/executor.py`)
- Progress event store (`src/mail_agent/a2a/progress_store.py`)
- Task manager (`src/mail_agent/task_manager/`)
- SSE streaming (`src/mail_agent/a2a/routes/progress.py`)

**Talks to**:
- Mock SMTP Server (REST API for sending/fetching emails, registering webhooks)

### Server 3: Mail Agent Webhook Server
**Port**: 9000
**Purpose**: Receive email arrival notifications
**Components**:
- FastAPI webhook receiver (`src/mail_agent/webhook/server.py`)
- Resume suspended tasks

**Talks to**:
- Mail Agent A2A Server (internal - resumes agent tasks)

### Server 4: UI Server
**Port**: 8080
**Purpose**: Web interface for users
**Components**:
- HTMX + Tailwind CSS frontend (`src/ui/templates/`)
- FastAPI backend (`src/ui/routes/`)
- A2A client (`src/ui/services/a2a_client.py`)
- SSE proxy (`src/ui/routes/sse.py`)
- SMTP client (`src/ui/services/smtp_client.py`)

**Talks to**:
- Mail Agent A2A Server (JSON-RPC for tasks, SSE for progress)
- Mock SMTP Server (REST API for inbox/emails, SMTP for sending)

---

## LangGraph Agent Flow

**State**: `AgentState` → instruction, conversations (POC→ConversationState), current_poc, progress_messages, error, webhook_id

**Node Sequence**:
```
User Instruction
     ↓
┌────────────────────┐
│ parse_instruction  │  Extract POC emails + requirements
└─────────┬──────────┘
          ↓
┌────────────────────┐
│  compose_email     │  LLM generates email content
└─────────┬──────────┘
          ↓
┌────────────────────┐
│   send_email       │  Send via Mock SMTP API
└─────────┬──────────┘
          ↓
┌────────────────────┐
│ wait_for_reply     │  INTERRUPT (webhook-triggered resume)
└─────────┬──────────┘  Registers webhook, suspends task
          ↓
    [Email arrives → Webhook fires → Task resumes]
          ↓
┌────────────────────┐
│  fetch_email       │  Retrieve reply from inbox
└─────────┬──────────┘
          ↓
┌────────────────────┐
│ extract_content    │  Parse CSV/Excel attachments
└─────────┬──────────┘
          ↓
┌────────────────────┐
│ validate_response  │  LLM validates against requirements
└─────────┬──────────┘
          ↓
┌────────────────────┐
│   decide_next      │  Success / Retry (max 5) / Redirect / Failure
└────────┬───────────┘
         ├─[Success]──────────────────────┐
         │                                 ↓
         │                    ┌────────────────────────┐
         │                    │ compose_success_reply  │  LLM generates acknowledgment
         │                    └────────────┬───────────┘
         │                                 ↓
         │                    ┌────────────────────────┐
         │                    │  send_success_reply    │  Send thank-you email
         │                    └────────────────────────┘
         │
         ├─[Redirect]─────► handle_redirect ──► compose_email (new POC)
         │
         ├─[Retry]───────────► compose_email (followup)
         │
         └─[Failure]─────────► END
```

**Graph File**: `src/mail_agent/agent/graph.py`
**Nodes Dir**: `src/mail_agent/agent/nodes/`

---

## Directory Index

```
info-agent-3-docker/
├── src/
│   ├── mock_smtp/              # Mock SMTP Server
│   │   ├── main.py             # Entry point
│   │   ├── config.py           # Settings (MOCK_SMTP_*)
│   │   ├── smtp/               # SMTP protocol
│   │   │   ├── server.py       # SMTP server
│   │   │   └── handler.py      # Email handler
│   │   ├── api/                # REST API
│   │   │   ├── router.py       # Main router
│   │   │   ├── send_routes.py  # Send email
│   │   │   ├── inbox_routes.py # List inboxes
│   │   │   ├── email_routes.py # Get email details
│   │   │   └── webhook_routes.py # Webhook CRUD
│   │   ├── store/              # Email storage
│   │   │   ├── inbox_store.py  # Thread-safe store
│   │   │   └── models.py       # Email/Attachment models
│   │   └── webhooks/           # Webhooks
│   │       ├── registry.py     # Registration
│   │       └── dispatcher.py   # HTTP POST with retry
│   │
│   ├── mail_agent/             # Mail Agent
│   │   ├── main.py             # CLI entry point
│   │   ├── config.py           # Settings (MAIL_AGENT_*)
│   │   ├── agent/              # LangGraph agent
│   │   │   ├── graph.py        # Graph definition
│   │   │   ├── state.py        # State models
│   │   │   └── nodes/          # Node implementations
│   │   │       ├── parse_instruction.py
│   │   │       ├── compose_email.py
│   │   │       ├── send_email.py
│   │   │       ├── wait_for_reply.py
│   │   │       ├── fetch_email.py
│   │   │       ├── extract_content.py
│   │   │       ├── validate_response.py
│   │   │       ├── decide_next.py
│   │   │       ├── handle_redirect.py
│   │   │       ├── compose_success_reply.py
│   │   │       └── send_success_reply.py
│   │   ├── llm/                # LLM
│   │   │   ├── client.py       # Gemini/Azure/OpenRouter factory
│   │   │   └── prompts.py      # System prompts
│   │   ├── tools/              # Tools
│   │   │   ├── smtp_client.py  # SMTP API client
│   │   │   ├── smtp_sender.py  # SMTP protocol sender
│   │   │   ├── inbox_client.py # Inbox API client
│   │   │   └── attachment_parser.py # CSV/Excel parser
│   │   ├── webhook/            # Webhook server
│   │   │   └── server.py       # FastAPI webhook receiver
│   │   ├── persistence/        # State persistence
│   │   │   ├── checkpointer.py # SQLite checkpoints
│   │   │   ├── database.py     # DB initialization
│   │   │   └── task_store.py   # Task storage
│   │   ├── task_manager/       # Task management
│   │   │   ├── manager.py      # Task lifecycle
│   │   │   └── models.py       # Task models
│   │   └── a2a/                # A2A protocol
│   │       ├── server.py       # JSON-RPC server
│   │       ├── executor.py     # Agent wrapper
│   │       ├── agent_card.py   # Agent card (RFC 8615)
│   │       ├── progress_store.py # SSE event storage
│   │       └── routes/         # A2A routes
│   │           ├── tasks.py    # Task list/status
│   │           └── progress.py # SSE streaming
│   │
│   └── ui/                     # UI Server
│       ├── main.py             # FastAPI app
│       ├── config.py           # Settings (UI_*)
│       ├── routes/             # Route handlers
│       │   ├── pages.py        # Main pages
│       │   ├── send_request.py # Send form
│       │   ├── inbox.py        # Inbox viewer
│       │   ├── dashboard.py    # Task dashboard
│       │   └── sse.py          # SSE proxy
│       ├── services/           # API clients
│       │   ├── a2a_client.py   # A2A client
│       │   ├── sse_client.py   # SSE client
│       │   ├── smtp_client.py  # SMTP API client
│       │   └── smtp_sender.py  # SMTP protocol sender
│       ├── templates/          # Jinja2 templates
│       │   ├── base.html       # Base layout
│       │   ├── index.html      # Home page
│       │   ├── send_request.html # Send form
│       │   ├── partials/       # HTMX partials
│       │   ├── inbox/          # Inbox templates
│       │   └── dashboard/      # Dashboard templates
│       └── static/css/         # Tailwind CSS
│
├── tests/                      # Test suites
│   ├── test_mail_agent/        # Mail agent tests
│   │   ├── test_a2a/           # A2A tests
│   │   ├── test_nodes/         # Node tests
│   │   ├── test_persistence/   # Persistence tests
│   │   ├── test_task_manager/  # Task manager tests
│   │   └── test_tools/         # Tools tests
│   ├── test_ui/                # UI tests
│   └── test_*.py               # Mock SMTP tests
│
├── scripts/                    # Utilities
│   ├── a2a_client.py           # A2A test client
│   ├── poc_reply_simulator.py  # POC reply simulator
│   └── generate_test_data.py   # Test data generator
│
├── test_data/                  # Test data files
│   ├── sample_recipes.csv
│   ├── sample_recipes.xlsx
│   └── ...
│
├── .env.example                # Environment template
├── pyproject.toml              # Package config
├── README.md                   # User documentation
└── CLAUDE.md                   # This file
```

---

## Common Development Tasks

### Add LangGraph Node
1. Create `src/mail_agent/agent/nodes/my_node.py`
2. Implement: `async def my_node(state: AgentState) -> dict[str, Any]`
3. Import in `src/mail_agent/agent/nodes/__init__.py`
4. Add to graph in `src/mail_agent/agent/graph.py`: `.add_node("my_node", my_node)`
5. Add tests: `tests/test_mail_agent/test_nodes/test_my_node.py`

### Add LLM Prompt
1. Add template to `src/mail_agent/llm/prompts.py`
2. Export in `src/mail_agent/llm/__init__.py`
3. Use in node: `prompt.format(**kwargs)`

### Add API Endpoint (Mock SMTP)
1. Add route to `src/mock_smtp/api/*_routes.py`
2. Include in `src/mock_smtp/api/router.py`
3. Add tests: `tests/test_api_*.py`

### Add UI Route
1. Add handler to `src/ui/routes/*.py`
2. Create template in `src/ui/templates/`
3. Register in `src/ui/main.py`
4. Add tests: `tests/test_ui/test_*.py`

### Add SSE Event Type
1. Update `ProgressEvent` model in `src/mail_agent/a2a/progress_store.py`
2. Emit event in `src/mail_agent/a2a/executor.py`
3. Handle in `src/ui/services/sse_client.py`
4. Display in `src/ui/templates/partials/progress_log.html`

### Add Configuration
1. Add field to `Settings` in `config.py` with `Field()`
2. Add validator if needed (`@field_validator`)
3. Update `.env.example`
4. Document in this file

### Debug Agent Flow
1. Enable debug logging: `MAIL_AGENT_LOG_LEVEL=DEBUG`
2. Check SQLite DB: `sqlite3 mail_agent_state.db`
3. View checkpoints: `SELECT * FROM checkpoints;`
4. Inspect state: Check `checkpoint_blobs` table

### Debug SSE Streaming
1. Check browser console for SSE errors
2. Test A2A endpoint directly: `curl http://localhost:8000/api/tasks/{task_id}/progress`
3. Check UI proxy logs: `UI_LOG_LEVEL=DEBUG`
4. Verify progress_store events: Check executor logging

---

## Environment Variables

### Mock SMTP (`MOCK_SMTP_*`)
```bash
MOCK_SMTP_SMTP_HOST=localhost         # SMTP bind address
MOCK_SMTP_SMTP_PORT=1025              # SMTP port
MOCK_SMTP_API_HOST=0.0.0.0            # API bind address
MOCK_SMTP_API_PORT=8025               # API port
MOCK_SMTP_MAX_EMAILS_PER_INBOX=1000   # FIFO eviction threshold
MOCK_SMTP_MAX_ATTACHMENT_SIZE_MB=10   # Attachment size limit
MOCK_SMTP_WEBHOOK_TIMEOUT_SECONDS=10.0
MOCK_SMTP_WEBHOOK_MAX_RETRIES=3
MOCK_SMTP_LOG_LEVEL=INFO
```

### Mail Agent (`MAIL_AGENT_*`)
```bash
# Mock SMTP Connection
MAIL_AGENT_MOCK_SMTP_API_URL=http://localhost:8025
MAIL_AGENT_MOCK_SMTP_HOST=localhost
MAIL_AGENT_MOCK_SMTP_PORT=1025
MAIL_AGENT_AGENT_EMAIL=info-agent@gmail.com

# Webhook Server
MAIL_AGENT_WEBHOOK_HOST=localhost
MAIL_AGENT_WEBHOOK_PORT=9000
MAIL_AGENT_WEBHOOK_PATH=/webhook/email-received

# LLM
MAIL_AGENT_LLM_PROVIDER=gemini  # or "azure-openai" or "openrouter"
MAIL_AGENT_GEMINI_API_KEY=your-key
MAIL_AGENT_GEMINI_MODEL=gemini-2.5-flash
# MAIL_AGENT_AZURE_OPENAI_API_KEY=...
# MAIL_AGENT_AZURE_OPENAI_ENDPOINT=...
# MAIL_AGENT_AZURE_OPENAI_DEPLOYMENT_NAME=...
# MAIL_AGENT_OPENROUTER_API_KEY=...
# MAIL_AGENT_OPENROUTER_MODEL=anthropic/claude-3.5-sonnet
MAIL_AGENT_LLM_TEMPERATURE=0.0
MAIL_AGENT_LLM_MAX_TOKENS=4096

# Agent Behavior
MAIL_AGENT_MAX_ATTEMPTS=5
MAIL_AGENT_SQLITE_DB_PATH=./mail_agent_state.db
MAIL_AGENT_HTTP_TIMEOUT_SECONDS=30.0

# A2A Server
MAIL_AGENT_A2A_HOST=0.0.0.0
MAIL_AGENT_A2A_PORT=8000
MAIL_AGENT_A2A_AGENT_NAME=Mail Agent
MAIL_AGENT_A2A_AGENT_DESCRIPTION=Intelligent email assistant powered by LangGraph
MAIL_AGENT_A2A_AGENT_VERSION=1.0.0

MAIL_AGENT_LOG_LEVEL=INFO
```

### UI Server (`UI_*`)
```bash
UI_HOST=0.0.0.0
UI_PORT=8080
UI_A2A_SERVER_URL=http://localhost:8000
UI_MOCK_SMTP_API_URL=http://localhost:8025
UI_DEFAULT_INBOX_EMAIL=info-agent@gmail.com
UI_HTTP_TIMEOUT_SECONDS=30.0
UI_HTTP_LONG_POLL_TIMEOUT_SECONDS=300.0
UI_SMTP_HOST=localhost
UI_SMTP_PORT=1025
UI_LOG_LEVEL=INFO
```

---

## Anti-Patterns

1. **No persistent storage in Mock SMTP** - In-memory only (by design)
2. **No blocking webhooks** - Fire-and-forget (async)
3. **No global LLM client** - Use dependency injection
4. **No direct state mutation** - Return new state dict from nodes
5. **No hardcoded POC emails** - Extract from instruction
6. **No missing locks in InboxStore** - Always `with self._lock:`
7. **No synchronous SSE clients** - Use async generators

---

## Fail-Fast Behaviors

### Mock SMTP
- Invalid config → `ValueError` on startup
- Attachment too large → SMTP 552 error
- Inbox full → FIFO eviction (oldest removed)

### Mail Agent
- No LLM API key → Exception on startup
- Max attempts reached → Mark task as failed
- Invalid instruction → Error in `parse_instruction` node
- Webhook registration fails → Log error, continue

### UI Server
- A2A server unreachable → Display connection error
- SSE connection drops → Auto-reconnect with last event ID

---

## Testing Checklist

Before committing:
- [ ] `pytest` passes
- [ ] `pytest --cov=src --cov-report=term-missing` shows coverage
- [ ] No files exceed 800 lines
- [ ] Logging added for new operations
- [ ] `.env.example` updated
- [ ] README.md updated (if user-facing)
- [ ] CLAUDE.md updated (if structural)

---

## Troubleshooting

### Mock SMTP not responding
```bash
curl http://localhost:8025/api/health
uv run mock-smtp  # Check logs
```

### Mail Agent can't connect
```bash
curl http://localhost:8025/api/health
uv run mail-agent config
```

### LLM errors
```bash
echo $MAIL_AGENT_GEMINI_API_KEY
uv run mail-agent config
```

### Webhook not received
```bash
curl http://localhost:8025/api/webhooks  # Verify registration
cat .env | grep WEBHOOK
```

### SSE not streaming
```bash
# Test direct connection
curl -N http://localhost:8000/api/tasks/{task_id}/progress

# Check browser console for SSE errors
# Verify UI_A2A_SERVER_URL is correct
```

---

## Key Design Decisions

### Why In-Memory Storage (Mock SMTP)?
Testing tool, not production server. Fast, simple, clean state on restart.

### Why LangGraph?
State machine modeling, built-in checkpointing, interruptible workflows for `wait_for_reply`.

### Why A2A Protocol?
Standardized agent communication, discovery, task-based execution, non-blocking.

### Why SSE for Progress?
Real-time updates, browser-native, no WebSocket complexity, automatic reconnection.

### Webhook Fire-and-Forget
Async dispatch, no persistence, exponential backoff retry, timeout protection.

---

## Scripts & Utilities

- **`scripts/a2a_client.py`** - A2A protocol test client
- **`scripts/poc_reply_simulator.py`** - Simulate POC email replies with attachments
- **`scripts/generate_test_data.py`** - Generate test CSV/Excel files

```bash
# A2A client
python scripts/a2a_client.py info
python scripts/a2a_client.py interactive

# POC simulator
uv run python scripts/poc_reply_simulator.py \
  --from "raj@gmail.com" \
  --to "info-agent@gmail.com" \
  --subject "Re: Request" \
  --body "Attached." \
  --attachment ./test_data/sample_recipes.csv
```
