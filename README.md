# Info Agent

Autonomous email interaction system with LangGraph agent, real-time progress tracking, and web UI.

## Overview

Info Agent is a four-server system that automates email-based data collection workflows. It uses a LangGraph state machine to orchestrate multi-turn conversations with Points of Contact (POCs), validate responses against requirements, and retry until success or max attempts.

### Key Features

- **Autonomous Email Workflows** - Send requests, wait for replies, validate responses, retry on failure
- **LangGraph State Machine** - Persistent state with checkpointing and interrupt-based suspension
- **Real-Time Progress Tracking** - Server-Sent Events (SSE) stream task execution to web UI
- **A2A Protocol Support** - Google Agent-to-Agent protocol (JSON-RPC 2.0)
- **Webhook-Based Resumption** - Email arrivals trigger task resumption from checkpoints
- **LLM Integration** - Gemini, Azure OpenAI, or OpenRouter for email composition and validation
- **Attachment Processing** - CSV and Excel parsing with structured data extraction
- **Mock SMTP Server** - Local email testing with REST API and webhook notifications
- **Web UI** - HTMX + Tailwind CSS interface for task submission and monitoring

### Architecture

```
┌──────────┐  HTTP/SSE  ┌──────────┐  JSON-RPC  ┌────────────────┐
│ Browser  │◄──────────►│ UI Server│◄──────────►│ A2A Server     │
│          │            │ (8080)   │            │ (8000)         │
└──────────┘            └────┬─────┘            │ - LangGraph    │
                             │                  │ - Task Manager │
                             │                  │ - SSE Progress │
                             ▼                  └───────┬────────┘
                        ┌──────────┐                    │
                        │ Mock SMTP│◄───────────────────┤
                        │ 1025/8025│  Webhook (9000)    │
                        └──────────┘                    │
```

**Four Servers:**
1. **Mock SMTP Server** (Ports 1025 SMTP, 8025 API) - Email testing infrastructure
2. **Mail Agent A2A Server** (Port 8000) - LangGraph agent with task management
3. **Mail Agent Webhook Server** (Port 9000) - Email notification receiver
4. **UI Server** (Port 8080) - Web interface with real-time updates

---

## Quick Start

### Prerequisites

- Python 3.12+
- LLM API key (Gemini, Azure OpenAI, or OpenRouter)

### Installation

```bash
# Clone or navigate to project directory
cd info-agent-3

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -e ".[dev]"

# Configure environment
cp .env.example .env
# Edit .env with your LLM API key
```

### Running the System

**Start all servers (3 separate terminals):**

```bash
# Terminal 1: Mock SMTP Server
uv run mock-smtp

# Terminal 2: Mail Agent A2A Server (includes webhook server)
uv run mail-agent a2a

# Terminal 3: UI Server
uv run ui-server
```

**Access the UI:**
```
http://localhost:8080
```

---

## Configuration

### Required Configuration (.env)

**Choose LLM Provider:**

**Option 1: Google Gemini** (recommended)
```bash
MAIL_AGENT_LLM_PROVIDER=gemini
MAIL_AGENT_GEMINI_API_KEY=your-gemini-api-key
MAIL_AGENT_GEMINI_MODEL=gemini-2.5-flash
```

**Option 2: Azure OpenAI**
```bash
MAIL_AGENT_LLM_PROVIDER=azure-openai
MAIL_AGENT_AZURE_OPENAI_API_KEY=your-azure-key
MAIL_AGENT_AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
MAIL_AGENT_AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4
MAIL_AGENT_AZURE_OPENAI_API_VERSION=2024-02-15-preview
```

**Option 3: OpenRouter**
```bash
MAIL_AGENT_LLM_PROVIDER=openrouter
MAIL_AGENT_OPENROUTER_API_KEY=your-openrouter-key
MAIL_AGENT_OPENROUTER_MODEL=anthropic/claude-3.5-sonnet
```

### Optional Configuration

See `.env.example` for all available configuration options including:
- Agent behavior (max attempts, timeouts)
- Server ports
- Database path
- Logging levels

---

## Usage

### Web UI (Recommended)

1. Open http://localhost:8080
2. Click **"Send Request"**
3. Enter instruction: `"send mail to chef@example.com asking 20 recipes in csv"`
4. Click **"Submit Task"**
5. View real-time progress on **Dashboard**
6. Check **Inbox** for received emails

### CLI Mode

Execute one-off tasks from command line:

```bash
# Run a task
uv run mail-agent run "send mail to data@example.com asking 50 cities with population in csv"

# Check configuration
uv run mail-agent config

# Health check
uv run mail-agent health
```

### API Access (A2A Protocol)

```python
import requests

# Execute task
response = requests.post(
    "http://localhost:8000/jsonrpc",
    json={
        "jsonrpc": "2.0",
        "method": "tasks.execute",
        "params": {
            "instruction": "send mail to raj@gmail.com asking 10 recipes in csv"
        },
        "id": 1
    }
)

task_id = response.json()["result"]["task_id"]

# Check status
status = requests.get(f"http://localhost:8000/api/tasks/{task_id}")
print(status.json())

# Stream progress (SSE)
import sseclient
events = sseclient.SSEClient(f"http://localhost:8000/api/tasks/{task_id}/progress")
for event in events:
    print(event.data)
```

### Simulating POC Replies

Use the reply simulator script to test the system:

```bash
uv run python scripts/poc_reply_simulator.py \
  --from "chef@example.com" \
  --to "info-agent@gmail.com" \
  --subject "Re: Request: 20 recipes" \
  --body "Please find the recipes attached." \
  --attachment ./test_data/sample_recipes.csv
```

---

## How It Works

### Agent Workflow

```
User Instruction
     ↓
1. Parse (extract POC emails + requirements)
     ↓
2. Compose (LLM generates email)
     ↓
3. Send (via Mock SMTP)
     ↓
4. Wait for Reply (task suspends, webhook-triggered resume)
     ↓ [Email arrives → Webhook → Resume]
5. Fetch (retrieve email)
     ↓
6. Extract (parse CSV/Excel attachments)
     ↓
7. Validate (LLM checks against requirements)
     ↓
8. Decide (retry up to 5 times or complete/fail)
     ↓
9. Send Acknowledgment (on success)
```

### Interrupt & Resume Mechanism

1. **Suspend:** `wait_for_reply` node triggers LangGraph interrupt
2. **Persist:** State saved to SQLite checkpoint
3. **Webhook:** Mock SMTP notifies webhook server on email arrival
4. **Resume:** Task resumes from checkpoint with email data
5. **Continue:** Graph executes remaining nodes

### Real-Time Progress

- **SSE Streaming:** UI subscribes to progress events
- **Event Types:** progress, complete, error, suspended
- **Reconnection:** Last-Event-Id for resuming streams
- **Keepalive:** 15s timeout for connection health

---

## API Endpoints

### Mock SMTP Server (Port 8025)

```bash
# Health check
GET http://localhost:8025/api/health

# List inboxes
GET http://localhost:8025/api/inboxes

# Get inbox emails
GET http://localhost:8025/api/inboxes/info-agent@gmail.com/emails

# Get email details
GET http://localhost:8025/api/emails/{email_id}

# Send email
POST http://localhost:8025/api/send
Content-Type: application/json
{
  "from_address": "sender@example.com",
  "to_addresses": ["recipient@example.com"],
  "subject": "Test Email",
  "body_text": "Hello, World!"
}

# Register webhook
POST http://localhost:8025/api/webhooks
{
  "url": "http://localhost:9000/webhook/email-received"
}

# Swagger UI
http://localhost:8025/docs
```

### Mail Agent A2A Server (Port 8000)

```bash
# Agent card (RFC 8615)
GET http://localhost:8000/.well-known/agent.json

# List all tasks
GET http://localhost:8000/api/tasks

# Get task status
GET http://localhost:8000/api/tasks/{task_id}

# Stream progress (SSE)
GET http://localhost:8000/api/tasks/{task_id}/progress
```

---

## Development

### Running Tests

```bash
# All tests
pytest

# With coverage
pytest --cov=src --cov-report=html
open htmlcov/index.html

# Specific module
pytest tests/test_mail_agent/
pytest tests/test_ui/
```

### Project Structure

```
info-agent/
├── src/
│   ├── mock_smtp/        # Mock SMTP server (SMTP + REST API)
│   ├── mail_agent/       # LangGraph mail agent (A2A + Webhook)
│   └── ui/               # Web UI (HTMX + Tailwind CSS)
├── tests/                # Test suites
├── scripts/              # Utilities (A2A client, POC simulator)
├── test_data/            # Sample CSV/Excel files
├── .env.example          # Environment template
├── pyproject.toml        # Package configuration
├── README.md             # This file (user documentation)
└── CLAUDE.md             # Developer documentation
```

---

## Troubleshooting

### Mock SMTP not responding

```bash
# Check health
curl http://localhost:8025/api/health

# Check if port is in use
lsof -i :1025

# Restart server
uv run mock-smtp
```

### Mail Agent connection errors

```bash
# Verify Mock SMTP is running
curl http://localhost:8025/api/health

# Check configuration
uv run mail-agent config

# View logs with debug level
MAIL_AGENT_LOG_LEVEL=DEBUG uv run mail-agent a2a
```

### LLM API errors

```bash
# Verify API key is set
cat .env | grep LLM_PROVIDER
cat .env | grep API_KEY

# Test LLM connection
uv run mail-agent health
```

### Webhook not firing

```bash
# Check webhook registration
curl http://localhost:8025/api/webhooks

# Verify webhook server is running
curl http://localhost:9000/health

# Check webhook server logs
```

### SSE not streaming

```bash
# Test SSE endpoint directly
curl -N http://localhost:8000/api/tasks/{task_id}/progress

# Check browser console for SSE connection errors
# Verify UI_A2A_SERVER_URL in .env matches A2A server
```

### Task stuck in suspended state

```bash
# Check database
sqlite3 mail_agent_state.db "SELECT * FROM suspended_tasks;"

# Manually trigger webhook (simulate POC reply)
curl -X POST http://localhost:9000/webhook/email-received \
  -H "Content-Type: application/json" \
  -d '{
    "inbox": "info-agent@gmail.com",
    "email_id": "test-email-id",
    "from_address": "poc@example.com",
    "subject": "Re: Request",
    "timestamp": "2025-12-17T10:00:00Z"
  }'
```

---

## Use Cases

### Automated Data Collection
Request structured data (CSV/Excel) from POCs via email. Agent validates responses and retries until success.

**Example:** Collect quarterly sales data from regional managers.

### Multi-Turn Conversations
Handle follow-ups when POC's initial response is incomplete. Agent composes contextual follow-up emails.

**Example:** Request product inventory, retry if missing required fields.

### POC Redirects
Automatically handle redirects when POC suggests another contact ("Email Sarah instead").

**Example:** Agent creates new conversation with redirected POC.

### Email Workflow Testing
Use Mock SMTP server for local email testing without external SMTP services.

**Example:** Integration tests for email-based features.

---

## Limitations

### Mock SMTP
- In-memory storage (no persistence, resets on restart)
- No TLS/SSL support
- No authentication
- Not suitable for production use

### Mail Agent
- Requires Mock SMTP server running
- LLM API key required (paid services)
- CSV/Excel attachments only
- Max 5 retry attempts per POC
- Single language (English)
- Task timeout: 1 hour default

### UI
- Single user (no authentication)
- Basic inbox management (no folders, search)
- No email composition (use CLI or API)

---

## Technology Stack

- **Backend:** FastAPI, aiosmtpd, aiosqlite
- **Agent:** LangGraph, LangChain
- **LLM:** Google Gemini / Azure OpenAI / OpenRouter
- **Database:** SQLite (state checkpointing)
- **Protocol:** A2A (JSON-RPC 2.0), SSE
- **Frontend:** HTMX, Tailwind CSS, Jinja2
- **Testing:** pytest, pytest-asyncio

---

## Contributing

Contributions welcome! Please ensure:

- All tests pass: `pytest`
- Files stay under 800 lines
- Environment variables documented in `.env.example`
- See `CLAUDE.md` for developer guidelines

---

## License

MIT

---

## Documentation

- **README.md** (this file) - User documentation
- **CLAUDE.md** - Developer quick reference
- **.env.example** - Configuration template

---

## Quick Commands Reference

```bash
# Setup
python -m venv venv && source venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env

# Run servers
uv run mock-smtp            # Mock SMTP (1025, 8025)
uv run mail-agent a2a       # A2A + Webhook (8000, 9000)
uv run ui-server            # UI (8080)

# CLI
uv run mail-agent run "send mail to user@example.com asking 10 recipes in csv"
uv run mail-agent config
uv run mail-agent health

# Simulate reply
uv run python scripts/poc_reply_simulator.py \
  --from "poc@example.com" \
  --to "info-agent@gmail.com" \
  --subject "Re: Request" \
  --body "Data attached" \
  --attachment ./test_data/sample_recipes.csv

# Test A2A client
python scripts/a2a_client.py info
python scripts/a2a_client.py interactive

# Tests
pytest
pytest --cov=src --cov-report=html
```

---

## Support

For issues or questions:
1. Check this README and CLAUDE.md
2. Review logs with `MAIL_AGENT_LOG_LEVEL=DEBUG`
3. Inspect database: `sqlite3 mail_agent_state.db`
4. Test Mock SMTP: `curl http://localhost:8025/api/health`
