# Info Agent - Developer Quick Reference

## System Overview

**Info Agent** is a four-server system for autonomous email interactions:

1. **Mock SMTP Server** (Ports 1025 SMTP, 8025 API) - Email testing infrastructure
2. **Mail Agent A2A Server** (Port 8000) - LangGraph agent with A2A protocol
3. **Mail Agent Webhook Server** (Port 9000) - Email notification receiver
4. **UI Server** (Port 8080) - Web interface (HTMX + Tailwind CSS)

**Tech Stack**: aiosmtpd, FastAPI, LangGraph, HTMX, Tailwind CSS, SQLite, Gemini/Azure OpenAI

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
- **SMTP Sender**: `src/ui/services/smtp_sender.py` - Direct SMTP email sending

### Inbox Management
- **Storage**: `src/mock_smtp/store/inbox_store.py` - Thread-safe email store
- **Models**: `src/mock_smtp/store/models.py` - Email/Attachment models
- **List API**: `src/mock_smtp/api/inbox_routes.py` - Inbox CRUD
- **Fetch**: `src/mail_agent/agent/nodes/fetch_email.py` - Agent fetch
- **UI Inbox**: `src/ui/routes/inbox.py` - UI inbox viewer

### Task Execution & Tracking
- **A2A Server**: `src/mail_agent/a2a/server.py` - JSON-RPC server
- **Executor**: `src/mail_agent/a2a/executor.py` - Agent wrapper
- **Manager**: `src/mail_agent/task_manager/manager.py` - Task lifecycle
- **Store**: `src/mail_agent/persistence/task_store.py` - Task persistence
- **UI Dashboard**: `src/ui/routes/dashboard.py` - Task status UI

### State & Persistence
- **Agent State**: `src/mail_agent/agent/state.py` - AgentState, ConversationState
- **Checkpointer**: `src/mail_agent/persistence/checkpointer.py` - SQLite checkpoints
- **Database**: `src/mail_agent/persistence/database.py` - DB initialization

### Webhooks & Notifications
- **Registry**: `src/mock_smtp/webhooks/registry.py` - Webhook registration
- **Dispatcher**: `src/mock_smtp/webhooks/dispatcher.py` - HTTP POST with retry
- **Server**: `src/mail_agent/webhook/server.py` - FastAPI webhook receiver
- **Wait Node**: `src/mail_agent/agent/nodes/wait_for_reply.py` - Interrupt + wait

### LLM & Validation
- **Client**: `src/mail_agent/llm/client.py` - Gemini/Azure factory
- **Prompts**: `src/mail_agent/llm/prompts.py` - System prompts
- **Parse**: `src/mail_agent/agent/nodes/parse_instruction.py` - Extract POC/requirements
- **Compose**: `src/mail_agent/agent/nodes/compose_email.py` - Generate email
- **Validate**: `src/mail_agent/agent/nodes/validate_response.py` - Check response

### Attachments
- **Parser**: `src/mail_agent/tools/attachment_parser.py` - CSV/Excel parsing
- **Extract**: `src/mail_agent/agent/nodes/extract_content.py` - Extraction node

### Configuration
- **Mock SMTP**: `src/mock_smtp/config.py` - `MOCK_SMTP_*` vars
- **Mail Agent**: `src/mail_agent/config.py` - `MAIL_AGENT_*` vars
- **UI Server**: `src/ui/config.py` - `UI_*` vars

---

## Integration Points

### UI Server → A2A Server
**Protocol**: JSON-RPC 2.0 over HTTP
**Client**: `src/ui/services/a2a_client.py`
**Endpoints**:
- `POST /jsonrpc` - Send task (`send_task` method)
- `GET /api/tasks` - List all tasks
- `GET /api/tasks/{task_id}` - Task status (SSE streaming)

**Flow**: User submits → A2A creates task → Agent executes → UI streams updates

### UI Server → Mock SMTP Server
**Protocol**: REST API
**Client**: `src/ui/services/smtp_client.py`
**Endpoints**:
- `GET /api/inboxes` - List inboxes
- `GET /api/inboxes/{inbox}/emails` - List emails
- `GET /api/emails/{email_id}` - Email detail
- `POST /api/send` - Send email

**Flow**: UI fetches inbox → displays emails → sends replies

### Mail Agent → Mock SMTP Server
**Protocol**: REST API
**Client**: `src/mail_agent/tools/smtp_client.py`
**Endpoints**:
- `POST /api/send` - Send email
- `POST /api/webhooks` - Register webhook
- `DELETE /api/webhooks/{webhook_id}` - Unregister
- `GET /api/inboxes/{inbox}/emails` - Fetch emails

**Flow**: Agent sends → registers webhook → waits → fetches reply

### Mock SMTP → Mail Agent Webhook
**Protocol**: HTTP POST (fire-and-forget)
**Target**: `http://localhost:9000/webhook/email-received`
**Dispatcher**: `src/mock_smtp/webhooks/dispatcher.py`
**Receiver**: `src/mail_agent/webhook/server.py`
**Payload**: `{"inbox": "...", "email_id": "...", "metadata": {...}}`

**Flow**: Email arrives → webhook fired → agent resumes from wait state

---

## LangGraph Agent Flow

**State**: `AgentState` → instruction, conversations (POC→ConversationState), current_poc, progress_messages, error, webhook_id

**Node Sequence**:
1. `parse_instruction` - Extract POC emails + requirements
2. `compose_email` - LLM generates email content
3. `send_email` - Send via Mock SMTP API
4. `wait_for_reply` - **INTERRUPT** (webhook-triggered resume)
5. `fetch_email` - Retrieve reply from inbox
6. `extract_content` - Parse CSV/Excel attachments
7. `validate_response` - LLM validates against requirements
8. `decide_next` - Retry (max 5) or end

**Graph File**: `src/mail_agent/agent/graph.py`
**Nodes Dir**: `src/mail_agent/agent/nodes/`

---

## Directory Index

```
/workspaces/info-agent-3/
├── src/
│   ├── mock_smtp/              # Mock SMTP Server
│   │   ├── main.py             # Entry point
│   │   ├── config.py           # Settings (MOCK_SMTP_*)
│   │   ├── smtp/               # SMTP protocol (server.py, handler.py)
│   │   ├── api/                # REST API (router.py, *_routes.py)
│   │   ├── store/              # Email storage (inbox_store.py, models.py)
│   │   └── webhooks/           # Webhooks (registry.py, dispatcher.py)
│   │
│   ├── mail_agent/             # Mail Agent
│   │   ├── main.py             # CLI entry point
│   │   ├── config.py           # Settings (MAIL_AGENT_*)
│   │   ├── agent/              # LangGraph agent
│   │   │   ├── graph.py        # Graph definition
│   │   │   ├── state.py        # State models
│   │   │   └── nodes/          # Node implementations
│   │   ├── llm/                # LLM (client.py, prompts.py)
│   │   ├── tools/              # Tools (smtp_client.py, attachment_parser.py, inbox_client.py)
│   │   ├── webhook/            # Webhook server (server.py)
│   │   ├── persistence/        # State persistence (checkpointer.py, database.py, task_store.py)
│   │   ├── task_manager/       # Task management (manager.py, models.py)
│   │   └── a2a/                # A2A protocol (server.py, executor.py, agent_card.py, routes/)
│   │
│   └── ui/                     # UI Server
│       ├── main.py             # FastAPI app
│       ├── config.py           # Settings (UI_*)
│       ├── routes/             # Route handlers (pages.py, send_request.py, inbox.py, dashboard.py)
│       ├── services/           # API clients (a2a_client.py, smtp_client.py, smtp_sender.py)
│       ├── templates/          # Jinja2 templates (base.html, index.html, send_request.html, partials/, inbox/, dashboard/)
│       └── static/css/         # Tailwind CSS
│
├── tests/                      # Test suites
│   ├── test_mail_agent/        # Mail agent tests
│   ├── test_ui/                # UI tests
│   └── test_*.py               # Mock SMTP tests
│
├── scripts/                    # Utilities
│   ├── a2a_client.py           # A2A test client
│   ├── poc_reply_simulator.py  # POC reply simulator
│   └── generate_test_data.py   # Test data generator
│
├── .dev-resources/             # Architecture docs
│   ├── architecture/           # Component docs
│   └── contracts/              # API specs
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
2. Implement: `def my_node(state: AgentState) -> AgentState`
3. Import in `src/mail_agent/agent/nodes/__init__.py`
4. Add to graph in `src/mail_agent/agent/graph.py`:
   ```python
   .add_node("my_node", my_node)
   .add_edge("previous_node", "my_node")
   ```
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
MAIL_AGENT_LLM_PROVIDER=gemini  # or "azure-openai"
MAIL_AGENT_GEMINI_API_KEY=your-key
MAIL_AGENT_GEMINI_MODEL=gemini-2.5-flash
# MAIL_AGENT_AZURE_OPENAI_API_KEY=...
# MAIL_AGENT_AZURE_OPENAI_ENDPOINT=...
# MAIL_AGENT_AZURE_OPENAI_DEPLOYMENT_NAME=...
# MAIL_AGENT_AZURE_OPENAI_API_VERSION=...
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

---

## Key Design Decisions

### Why In-Memory Storage (Mock SMTP)?
Testing tool, not production server. Fast, simple, clean state on restart.

### Why LangGraph?
State machine modeling, built-in checkpointing, interruptible workflows for `wait_for_reply`.

### Why A2A Protocol?
Standardized agent communication, discovery, task-based execution, non-blocking.

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
  --attachment ./test_data/sample_data.csv
```
