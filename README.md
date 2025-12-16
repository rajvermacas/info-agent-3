# Info Agent

Autonomous email interaction system with Mock SMTP server, LangGraph-powered mail agent, and web UI.

## Features

### Mock SMTP Server
- **SMTP Server** (port 1025) - Standard SMTP protocol
- **REST API** (port 8025) - HTTP interface with Swagger UI at `/docs`
- **Webhook Notifications** - HTTP callbacks on email arrival
- **In-Memory Storage** - Fast, ephemeral (resets on restart)
- **Multiple Inboxes** - Auto-created on first email

### Mail Agent
- **Autonomous Workflows** - Send requests, validate responses, retry on failure
- **LangGraph State Machine** - Parse → Compose → Send → Wait → Fetch → Validate → Decide
- **LLM Integration** - Google Gemini or Azure OpenAI
- **Attachment Handling** - CSV and Excel parsing
- **State Persistence** - SQLite checkpointing for resumable tasks
- **A2A Protocol** - Google Agent-to-Agent protocol (JSON-RPC 2.0)

### UI Server
- **Web Interface** - HTMX + Tailwind CSS
- **Send Requests** - Submit tasks via web form
- **Inbox Management** - View emails, download attachments, send replies
- **Task Dashboard** - Real-time task monitoring with SSE

## Quick Start

### Installation

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install
pip install -e ".[dev]"

# Configure
cp .env.example .env
# Edit .env with your LLM API key (Gemini or Azure OpenAI)
```

### Running

```bash
# Start Mock SMTP Server (SMTP: 1025, API: 8025)
uv run mock-smtp

# Start Mail Agent A2A Server (Port 8000 + Webhook 9000)
uv run mail-agent a2a

# Start UI Server (Port 8080)
uv run ui-server

# Access Web UI
open http://localhost:8080

# CLI mode (one-off task)
uv run mail-agent run "send mail to chef@example.com asking 20 recipes in csv"
```

## Configuration

Configure via `.env` file. See `.env.example` for all options.

### Required Configuration

```bash
# LLM Provider (choose one)
MAIL_AGENT_LLM_PROVIDER=gemini  # or "azure-openai"

# Google Gemini
MAIL_AGENT_GEMINI_API_KEY=your-gemini-api-key
MAIL_AGENT_GEMINI_MODEL=gemini-2.5-flash

# OR Azure OpenAI
# MAIL_AGENT_AZURE_OPENAI_API_KEY=your-key
# MAIL_AGENT_AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
# MAIL_AGENT_AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4
```

### Optional Configuration

```bash
# Mock SMTP
MOCK_SMTP_SMTP_PORT=1025
MOCK_SMTP_API_PORT=8025

# Mail Agent
MAIL_AGENT_AGENT_EMAIL=info-agent@gmail.com
MAIL_AGENT_MAX_ATTEMPTS=5

# UI Server
UI_PORT=8080
UI_DEFAULT_INBOX_EMAIL=info-agent@gmail.com
```

## Usage

### Web UI (Recommended)

1. Start all servers (see Running section)
2. Open http://localhost:8080
3. **Send Request**: Submit task instruction
4. **Dashboard**: Monitor task progress
5. **Inbox**: View emails and replies

### CLI Mode

```bash
# Execute task
uv run mail-agent run "send mail to data@example.com asking list of 50 cities with population in csv"

# Check configuration
uv run mail-agent config

# Health check
uv run mail-agent health
```

### A2A Protocol

```python
import requests

# Execute task
response = requests.post(
    "http://localhost:8000/jsonrpc",
    json={
        "jsonrpc": "2.0",
        "method": "tasks.execute",
        "params": {"instruction": "send mail to raj@gmail.com asking 10 recipes in csv"},
        "id": 1
    }
)

task_id = response.json()["result"]["task_id"]

# Check status
status = requests.get(f"http://localhost:8000/api/tasks/{task_id}")
```

### Simulating POC Replies

```bash
# Reply with CSV attachment
uv run python scripts/poc_reply_simulator.py \
  --from "raj@gmail.com" \
  --to "info-agent@gmail.com" \
  --subject "Re: Request" \
  --body "Here's the data you requested." \
  --attachment ./test_data/sample_recipes.csv
```

## API Endpoints

### Mock SMTP Server (Port 8025)

```bash
# List inboxes
curl http://localhost:8025/api/inboxes

# Get inbox emails
curl http://localhost:8025/api/inboxes/info-agent@gmail.com

# Send email
curl -X POST http://localhost:8025/api/send \
  -H "Content-Type: application/json" \
  -d '{
    "from_address": "sender@example.com",
    "to_addresses": ["recipient@example.com"],
    "subject": "Test",
    "body_text": "Hello"
  }'

# Register webhook
curl -X POST http://localhost:8025/api/webhooks \
  -H "Content-Type: application/json" \
  -d '{"url": "http://localhost:9000/webhook/email-received"}'

# Health check
curl http://localhost:8025/api/health

# Swagger UI
open http://localhost:8025/docs
```

### Mail Agent A2A Server (Port 8000)

```bash
# Agent card (RFC 8615)
curl http://localhost:8000/.well-known/agent.json

# List tasks
curl http://localhost:8000/api/tasks

# Get task status
curl http://localhost:8000/api/tasks/{task_id}
```

## Architecture

### Four-Server System

1. **Mock SMTP Server** (Ports 1025, 8025)
   - SMTP protocol + REST API
   - In-memory email storage
   - Webhook notifications

2. **Mail Agent A2A Server** (Port 8000)
   - JSON-RPC 2.0 endpoint
   - LangGraph agent execution
   - Task management

3. **Mail Agent Webhook Server** (Port 9000)
   - Email arrival notifications
   - Task resumption triggers

4. **UI Server** (Port 8080)
   - Web interface
   - Task submission and monitoring
   - Inbox management

### Mail Agent Workflow

```
User Instruction
     ↓
Parse (extract POC emails + requirements)
     ↓
Compose (LLM generates email)
     ↓
Send (via Mock SMTP)
     ↓
Wait for Reply (interrupt, webhook-triggered resume)
     ↓
Fetch (retrieve email)
     ↓
Extract (parse CSV/Excel attachments)
     ↓
Validate (LLM checks against requirements)
     ↓
Decide (retry up to 5 times or complete)
```

## Development

### Running Tests

```bash
# All tests
pytest

# With coverage
pytest --cov=src --cov-report=html

# Specific suite
pytest tests/test_mail_agent/
pytest tests/test_ui/
```

### Project Structure

```
info-agent/
├── src/
│   ├── mock_smtp/        # Mock SMTP server
│   ├── mail_agent/       # LangGraph mail agent
│   └── ui/               # Web UI (HTMX + Tailwind)
├── tests/                # Test suites
├── scripts/              # Utilities (A2A client, POC simulator)
├── .env.example          # Environment template
├── pyproject.toml        # Package config
├── README.md             # This file
└── CLAUDE.md             # Developer documentation
```

## Troubleshooting

### Mock SMTP not responding
```bash
curl http://localhost:8025/api/health
uv run mock-smtp  # Check startup logs
```

### Mail Agent connection errors
```bash
curl http://localhost:8025/api/health  # Verify Mock SMTP is running
uv run mail-agent config               # Check configuration
```

### LLM API errors
```bash
echo $MAIL_AGENT_GEMINI_API_KEY        # Verify API key is set
uv run mail-agent config               # Validate configuration
```

### Webhook not received
```bash
curl http://localhost:8025/api/webhooks  # Check webhook registration
# Ensure Mail Agent is running (starts webhook server)
```

## Limitations

### Mock SMTP
- No persistent storage (in-memory only)
- No TLS/SSL
- No authentication
- No email queue persistence

### Mail Agent
- Requires Mock SMTP server
- LLM API key required
- CSV/Excel attachments only
- Max 5 retry attempts per POC
- English language only

## Use Cases

- **Automated Data Collection** - Request structured data via email
- **POC Follow-ups** - Multi-turn conversations with validation
- **Email Workflow Testing** - Local SMTP server for development
- **Agent Prototyping** - A2A protocol experimentation

## License

MIT

## Contributing

Contributions welcome! Please ensure:
- All tests pass (`pytest`)
- Files stay under 800 lines
- Environment variables documented in `.env.example`
- See `CLAUDE.md` for developer guidelines

## Documentation

- **README.md** (this file) - User documentation
- **CLAUDE.md** - Developer quick reference
- **.dev-resources/architecture/** - Detailed architecture docs
- **.dev-resources/contracts/** - API contracts

# Execution steps:
## mock smtp
uv run mock-smtp

## mail agent
uv run mail-agent a2a
uv run mail-agent run "send mail to raj@gmail.com asking 10 food recipes in csv file"

# ui
uv run ui-server

## a2aclient
python scripts/a2a_client.py info
uv run python scripts/a2a_client.py interactive

## reply simulator
uv run python scripts/poc_reply_simulator.py --from "raj@gmail.com" --to "info-agent@gmail.com" --subject "Re: Request: 10 Actor names" --body "Please find attached." --attachment ./test_data/sample_actors.csv
