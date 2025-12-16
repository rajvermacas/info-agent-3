# Info Agent - Developer Documentation

## Project Overview

**Info Agent** is a three-component system for autonomous email interactions and testing:

1. **Mock SMTP Server** - Testing tool with SMTP (port 1025) + REST API (port 8025) for email workflows
2. **Mail Agent** - LangGraph-powered autonomous agent that sends requests via email, validates responses, and handles multi-turn conversations with POCs (Points of Contact)
3. **UI Server** - HTMX + Tailwind CSS web interface for Mail Agent (port 8080)

Built with aiosmtpd, FastAPI, LangGraph, HTMX, Tailwind CSS, and Google A2A protocol support.

**Architecture Details:** See `.dev-resources/architecture/` for detailed component docs.

## Quick Navigation by Feature

### Email Sending & Receiving
- **SMTP Protocol**: `src/mock_smtp/smtp/handler.py` - MIME parsing, attachment extraction
- **Send API**: `src/mock_smtp/api/send_routes.py` - REST endpoint for sending emails
- **Agent Send**: `src/mail_agent/agent/nodes/send_email.py` - Agent email sending logic
- **UI Send**: `src/ui/routes/send_request.py` - UI send form handler

### Inbox Management
- **Storage**: `src/mock_smtp/store/inbox_store.py` - Thread-safe in-memory email storage
- **List API**: `src/mock_smtp/api/inbox_routes.py` - Inbox CRUD endpoints
- **Fetch**: `src/mail_agent/agent/nodes/fetch_email.py` - Agent email retrieval
- **UI Inbox**: `src/ui/routes/inbox.py` - UI inbox display and operations

### Task Tracking & Execution
- **A2A Server**: `src/mail_agent/a2a/server.py` - Google A2A protocol server
- **Executor**: `src/mail_agent/a2a/executor.py` - LangGraph agent wrapper
- **Task Manager**: `src/mail_agent/task_manager/manager.py` - Task lifecycle management
- **UI Dashboard**: `src/ui/routes/dashboard.py` - Task status display

### State & Persistence
- **Agent State**: `src/mail_agent/agent/state.py` - AgentState and ConversationState models
- **Checkpointer**: `src/mail_agent/persistence/checkpointer.py` - SQLite-based state persistence
- **Task Store**: `src/mail_agent/persistence/task_store.py` - Task metadata storage

### Webhooks & Notifications
- **Webhook Registry**: `src/mock_smtp/webhooks/registry.py` - Webhook registration
- **Dispatcher**: `src/mock_smtp/webhooks/dispatcher.py` - HTTP POST client with retry
- **Webhook Server**: `src/mail_agent/webhook/server.py` - FastAPI webhook receiver + SSE
- **Wait Node**: `src/mail_agent/agent/nodes/wait_for_reply.py` - Interrupt and wait logic

### LLM & Validation
- **LLM Client**: `src/mail_agent/llm/client.py` - Gemini/Azure OpenAI factory
- **Prompts**: `src/mail_agent/llm/prompts.py` - System prompt templates
- **Parse**: `src/mail_agent/agent/nodes/parse_instruction.py` - Instruction parsing
- **Compose**: `src/mail_agent/agent/nodes/compose_email.py` - Email content generation
- **Validate**: `src/mail_agent/agent/nodes/validate_response.py` - Response validation

### Attachments
- **Parser**: `src/mail_agent/tools/attachment_parser.py` - CSV/Excel parsing
- **Extract**: `src/mail_agent/agent/nodes/extract_content.py` - Attachment extraction node
- **Models**: `src/mock_smtp/store/models.py` - Attachment data model

### Configuration
- **Mock SMTP**: `src/mock_smtp/config.py` - `MOCK_SMTP_*` env vars
- **Mail Agent**: `src/mail_agent/config.py` - `MAIL_AGENT_*` env vars
- **UI Server**: `src/ui/config.py` - `UI_*` env vars

## Integration Points

### UI Server → A2A Server
- **Protocol**: JSON-RPC 2.0 over HTTP
- **Client**: `src/ui/services/a2a_client.py`
- **Endpoints**:
  - `POST /jsonrpc` - Send task (`send_task` method)
  - `GET /api/tasks` - List tasks
  - `GET /api/tasks/{task_id}` - Get task status (SSE streaming)
- **Flow**: User submits request → UI calls A2A → Agent executes → UI polls for updates

### UI Server → Mock SMTP Server
- **Protocol**: REST API
- **Client**: `src/ui/services/smtp_client.py`
- **Endpoints**:
  - `GET /api/inboxes` - List inboxes
  - `GET /api/inboxes/{inbox}/emails` - List emails
  - `GET /api/emails/{email_id}` - Get email detail
  - `POST /api/send` - Send email
- **Flow**: UI displays inbox → fetches emails via API → displays in templates

### Mail Agent (A2A Server) → Mock SMTP Server
- **Protocol**: REST API
- **Client**: `src/mail_agent/tools/smtp_client.py`
- **Endpoints**:
  - `POST /api/send` - Send email (via send_email node)
  - `POST /api/webhooks` - Register webhook (on agent start)
  - `DELETE /api/webhooks/{webhook_id}` - Unregister webhook
  - `GET /api/inboxes/{inbox}/emails` - Fetch emails (via fetch_email node)
- **Flow**: Agent sends email → registers webhook → waits for notification → fetches reply

### Mock SMTP Server → Mail Agent (Webhook Server)
- **Protocol**: HTTP POST (fire-and-forget)
- **Target**: `http://localhost:9000/webhook/email-received`
- **Dispatcher**: `src/mock_smtp/webhooks/dispatcher.py`
- **Receiver**: `src/mail_agent/webhook/server.py`
- **Payload**: `{"inbox": "...", "email_id": "...", "metadata": {...}}`
- **Flow**: Email arrives → webhook dispatched → agent resumes from wait_for_reply node

## Development Commands

### Setup
```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env  # Edit with your API keys
```

### Running
```bash
# Mock SMTP Server (SMTP: 1025, API: 8025)
uv run mock-smtp

# Mail Agent A2A Server (Port 8000)
uv run mail-agent a2a

# Mail Agent CLI (Direct run)
uv run mail-agent run "send mail to raj@gmail.com asking 10 food recipes in csv file"

# UI Server (Port 8080)
uv run ui-server

# Test Tools
python scripts/a2a_client.py info
uv run python scripts/poc_reply_simulator.py --from "raj@gmail.com" --to "info-agent@gmail.com" --subject "Re: Request" --body "Attached." --attachment ./test_data/sample_actors.csv
```

### Testing
```bash
pytest
pytest --cov=src --cov-report=html
pytest tests/test_mail_agent/  # Mail agent tests
pytest tests/test_models.py    # Mock SMTP tests
```

## Architecture

### High-Level Design

**Four-Server Architecture:**
1. **Mock SMTP Server** (Ports 1025, 8025) - Email testing tool
2. **Mail Agent A2A Server** (Port 8000) - LangGraph agent via A2A protocol
3. **Mail Agent Webhook Server** (Port 9000) - Email notification receiver
4. **UI Server** (Port 8080) - Web interface (HTMX + Tailwind)

**Mail Agent Flow:**
```
User Instruction → Parse → Compose → Send → Wait for Reply
                                                    ↓
                                       Webhook triggers resume
                                                    ↓
                             Fetch → Extract → Validate
                                                    ↓
                                    Valid? → End : Retry (max 5)
```

**Key Patterns:** Dependency Injection, Factory Pattern, Async/Await, State Machines (LangGraph), A2A Protocol, SQLite Checkpointing, Fire-and-Forget Webhooks

### Directory Structure
```
/workspaces/info-agent-3/
├── src/
│   ├── mock_smtp/              # Mock SMTP Server
│   │   ├── main.py, config.py
│   │   ├── store/              # Email storage (models.py, inbox_store.py)
│   │   ├── webhooks/           # Webhook system (registry.py, dispatcher.py)
│   │   ├── smtp/               # SMTP server (server.py, handler.py)
│   │   └── api/                # REST API (router.py, *_routes.py)
│   │
│   ├── mail_agent/             # Mail Agent
│   │   ├── main.py, config.py
│   │   ├── agent/              # LangGraph agent (graph.py, state.py, nodes/)
│   │   ├── llm/                # LLM integration (client.py, prompts.py)
│   │   ├── tools/              # Agent tools (smtp_client.py, inbox_client.py, attachment_parser.py)
│   │   ├── webhook/            # Webhook server (server.py)
│   │   ├── persistence/        # State persistence (checkpointer.py, database.py, task_store.py)
│   │   ├── task_manager/       # Task lifecycle (manager.py, models.py)
│   │   └── a2a/                # A2A protocol (server.py, executor.py, agent_card.py, routes/tasks.py)
│   │
│   └── ui/                     # UI Server
│       ├── main.py, config.py
│       ├── routes/             # Route handlers (pages.py, send_request.py, inbox.py, dashboard.py)
│       ├── services/           # Service clients (a2a_client.py, smtp_client.py)
│       ├── templates/          # Jinja2 templates (base.html, *.html, partials/)
│       └── static/             # CSS files
│
├── tests/                      # Test suites
├── scripts/                    # Debug/test scripts (a2a_client.py, poc_reply_simulator.py)
├── .dev-resources/             # Architecture docs (architecture/, contracts/, prompts/)
├── pyproject.toml, .env.example, README.md
```

### Mail Agent State Machine

**AgentState:** instruction, conversations (Dict[poc_email, ConversationState]), current_poc, progress_messages, error, webhook_id

**ConversationState:** poc_email, status (pending/waiting/completed/failed), attempt_count, sent_emails, received_emails, validation_results, final_result, attachments

**Node Flow:**
1. **parse_instruction** - Extract POC emails + requirements
2. **compose_email** - Generate content via LLM
3. **send_email** - Send via Mock SMTP API
4. **wait_for_reply** - Interrupt, wait for webhook
5. **fetch_email** - Retrieve reply
6. **extract_content** - Parse attachments (CSV/Excel)
7. **validate_response** - Verify using LLM
8. **decide_next** - Retry if invalid (max 5) or end

## Configuration

### Environment Variables

**Mock SMTP Server (`MOCK_SMTP_*`):**
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

**Mail Agent (`MAIL_AGENT_*`):**
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
MAIL_AGENT_LLM_TEMPERATURE=0.0
MAIL_AGENT_LLM_MAX_TOKENS=4096

# Azure OpenAI (alternative)
# MAIL_AGENT_AZURE_OPENAI_API_KEY=...
# MAIL_AGENT_AZURE_OPENAI_ENDPOINT=...
# MAIL_AGENT_AZURE_OPENAI_DEPLOYMENT_NAME=...
# MAIL_AGENT_AZURE_OPENAI_API_VERSION=...

# Agent Behavior
MAIL_AGENT_MAX_ATTEMPTS=5
MAIL_AGENT_SQLITE_DB_PATH=./mail_agent_state.db

# A2A Server
MAIL_AGENT_A2A_HOST=0.0.0.0
MAIL_AGENT_A2A_PORT=8000
MAIL_AGENT_A2A_AGENT_NAME=Mail Agent
MAIL_AGENT_A2A_AGENT_VERSION=1.0.0

MAIL_AGENT_LOG_LEVEL=INFO
```

**UI Server (`UI_*`):**
```bash
UI_HOST=0.0.0.0
UI_PORT=8080
UI_A2A_SERVER_URL=http://localhost:8000
UI_MOCK_SMTP_API_URL=http://localhost:8025
UI_DEFAULT_INBOX_EMAIL=info-agent@gmail.com
UI_HTTP_TIMEOUT_SECONDS=30.0
UI_HTTP_LONG_POLL_TIMEOUT_SECONDS=300.0
UI_LOG_LEVEL=INFO
```

## Development Patterns

### Adding LangGraph Node
1. Create `agent/nodes/my_node.py`: `def my_node(state: AgentState) -> AgentState`
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
3. Update `.env.example` and CLAUDE.md

### Testing
- **Unit Tests**: Isolated components (pytest fixtures)
- **Integration Tests**: End-to-end flows (TestClient for APIs)
- **Fixtures**: `conftest.py` at root and `test_mail_agent/conftest.py`

## Anti-Patterns to Avoid

1. No persistent storage in Mock SMTP (in-memory is intentional)
2. No blocking webhooks (fire-and-forget by design)
3. No global LLM client (use dependency injection)
4. No direct state mutation (return new state dict from nodes)
5. No hardcoded POC emails (extract from instruction)
6. No missing locks in InboxStore (always `with self._lock:`)

## Important Constraints

### Fail-Fast Behavior
**Mock SMTP:** Invalid config → ValueError on startup, Attachment too large → SMTP 552, Inbox full → FIFO eviction
**Mail Agent:** No LLM API key → Exception on startup, Max attempts → Mark failed, Invalid instruction → Error in parse_instruction

### Error Handling
**Mock SMTP:** SMTP (catch all, log, return error code), API (422/404/500), Webhooks (log, don't block)
**Mail Agent:** Nodes (return error in state), LLM (log + retry), A2A executor (catch all, update task status)

### Data Access Patterns
**InboxStore:** Use `inbox_store.store_email(email)` not `inbox_store._inboxes[email].emails.append()`
**AgentState:** Return `{"conversations": updated_conversations}` not `state["conversations"][poc]["status"] = "waiting"`

### Logging Levels
- **DEBUG**: Detailed flow (LLM requests, webhook routing)
- **INFO**: Important events (email sent, task created, node transitions)
- **WARNING**: Recoverable issues (webhook timeout, retry)
- **ERROR**: Failures (validation failed, LLM error)
- **CRITICAL**: Server failures (startup errors)

### Memory Management
**Mock SMTP:** `max_emails_per_inbox=1000` prevents unbounded growth, FIFO eviction
**Mail Agent:** SQLite checkpoints prevent in-memory state growth, attachments stored as base64

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
