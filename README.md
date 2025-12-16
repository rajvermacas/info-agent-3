# Info Agent

A comprehensive system for autonomous email interactions combining a mock SMTP server for testing and an intelligent LangGraph-powered mail agent.

## Features

### Mock SMTP Server
- **SMTP Server** (port 1025) - Accepts emails via SMTP protocol
- **REST API** (port 8025) - Inspect and manage emails via HTTP
- **In-Memory Storage** - Ephemeral email storage (resets on restart)
- **Webhook Notifications** - HTTP POST notifications when emails arrive
- **Multiple Inboxes** - Implicit inbox creation on first email
- **No Authentication** - Open relay for testing simplicity
- **Swagger UI** - Interactive API documentation at `/docs`

### Mail Agent
- **Autonomous Email Handling** - Sends requests, validates responses, manages multi-turn conversations
- **LangGraph State Machine** - Orchestrates email workflow (parse, compose, send, wait, fetch, validate)
- **LLM Integration** - Supports Google Gemini and Azure OpenAI for intelligent email composition and validation
- **A2A Protocol Support** - Exposes agent via Google Agent-to-Agent protocol (JSON-RPC 2.0 over HTTP)
- **Attachment Parsing** - Handles CSV and Excel files with openpyxl
- **State Persistence** - SQLite-based checkpointing for resumable conversations
- **Webhook Server** - Receives email arrival notifications (port 9000)
- **SSE Streaming** - Real-time task progress updates via Server-Sent Events

## Quick Start

### Installation

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -e .

# Or install with dev dependencies
pip install -e ".[dev]"

# Copy environment template and configure
cp .env.example .env
# Edit .env with your LLM API keys (Gemini or Azure OpenAI)
```

### Running the Servers

#### Mock SMTP Server
```bash
# Start the mock SMTP server
uv run mock-smtp

# Or run directly
python -m mock_smtp.main
```

The server will start with:
- SMTP on `localhost:1025`
- REST API on `0.0.0.0:8025`
- Swagger UI at `http://localhost:8025/docs`

#### Mail Agent - A2A Server
```bash
# Start the A2A protocol server
uv run mail-agent a2a

# With verbose logging
uv run mail-agent a2a --verbose
```

The A2A server will start on `0.0.0.0:8000` with:
- Agent Card: `http://localhost:8000/.well-known/agent.json`
- JSON-RPC endpoint: `POST http://localhost:8000/jsonrpc`
- Task API: `http://localhost:8000/api/tasks`

#### Mail Agent - CLI Mode
```bash
# Run a one-off task
uv run mail-agent run "send mail to raj@gmail.com asking 10 food recipes in csv file"

# Check configuration
uv run mail-agent config

# Check mock SMTP health
uv run mail-agent health
```

## Configuration

Configure via environment variables. See `.env.example` for all options.

### Mock SMTP Server (`MOCK_SMTP_*`)

```bash
MOCK_SMTP_SMTP_HOST=localhost
MOCK_SMTP_SMTP_PORT=1025
MOCK_SMTP_API_HOST=0.0.0.0
MOCK_SMTP_API_PORT=8025
MOCK_SMTP_MAX_EMAILS_PER_INBOX=1000
MOCK_SMTP_MAX_ATTACHMENT_SIZE_MB=10
MOCK_SMTP_LOG_LEVEL=INFO
```

### Mail Agent (`MAIL_AGENT_*`)

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

# LLM Configuration (choose one provider)
MAIL_AGENT_LLM_PROVIDER=gemini  # or "azure-openai"

# Google Gemini (when LLM_PROVIDER=gemini)
MAIL_AGENT_GEMINI_API_KEY=your-gemini-api-key
MAIL_AGENT_GEMINI_MODEL=gemini-2.5-flash

# Azure OpenAI (when LLM_PROVIDER=azure-openai)
# MAIL_AGENT_AZURE_OPENAI_API_KEY=your-key
# MAIL_AGENT_AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
# MAIL_AGENT_AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4

# Agent Behavior
MAIL_AGENT_MAX_ATTEMPTS=5

# A2A Server
MAIL_AGENT_A2A_HOST=0.0.0.0
MAIL_AGENT_A2A_PORT=8000

# Logging
MAIL_AGENT_LOG_LEVEL=INFO
```

## Usage Examples

### Mock SMTP Server

#### Sending Emails via SMTP
```python
import smtplib
from email.message import EmailMessage

msg = EmailMessage()
msg['Subject'] = 'Test Email'
msg['From'] = 'sender@example.com'
msg['To'] = 'recipient@example.com'
msg.set_content('This is a test email.')

with smtplib.SMTP('localhost', 1025) as smtp:
    smtp.send_message(msg)
```

#### Using the REST API
```bash
# List all inboxes
curl http://localhost:8025/api/inboxes

# Get emails for a specific inbox
curl http://localhost:8025/api/inboxes/recipient@example.com

# Send an email directly (bypass SMTP)
curl -X POST http://localhost:8025/api/send \
  -H "Content-Type: application/json" \
  -d '{
    "from_address": "sender@example.com",
    "to_addresses": ["recipient@example.com"],
    "subject": "Test Email",
    "body_text": "This is a test email."
  }'

# Register a webhook
curl -X POST http://localhost:8025/api/webhooks \
  -H "Content-Type: application/json" \
  -d '{
    "url": "http://localhost:9000/webhook/email-received",
    "inbox_filter": null
  }'

# Clear all emails
curl -X DELETE http://localhost:8025/api/clear

# Health check
curl http://localhost:8025/api/health
```

### Mail Agent

#### CLI Mode
```bash
# Send a request for recipes
uv run mail-agent run "send mail to chef@example.com asking for 20 Italian recipes in excel format"

# Send a request for data
uv run mail-agent run "send mail to data@example.com asking for list of 50 cities with population in csv"
```

#### A2A Protocol
```python
import requests

# Execute a task via A2A protocol
response = requests.post(
    "http://localhost:8000/jsonrpc",
    json={
        "jsonrpc": "2.0",
        "method": "tasks.execute",
        "params": {
            "instruction": "send mail to raj@gmail.com asking 10 food recipes in csv file"
        },
        "id": 1
    }
)

task_id = response.json()["result"]["task_id"]

# Check task status
status = requests.get(f"http://localhost:8000/api/tasks/{task_id}")
print(status.json())

# Stream task progress (SSE)
import sseclient
events = sseclient.SSEClient(f"http://localhost:8000/api/tasks/{task_id}")
for event in events:
    print(event.data)
```

#### Using the Test Client
```bash
# Get agent info
python scripts/a2a_client.py info

# Interactive mode
uv run python scripts/a2a_client.py interactive
```

#### Simulating POC Replies
```bash
# Simulate a reply with CSV attachment
uv run python scripts/poc_reply_simulator.py \
  --from "raj@gmail.com" \
  --to "info-agent@gmail.com" \
  --subject "Re: Request: 10 food recipes" \
  --body "Please find attached the recipes you requested." \
  --attachment ./test_data/sample_recipes.csv

# Simulate a reply with Excel attachment
uv run python scripts/poc_reply_simulator.py \
  --from "data@example.com" \
  --to "info-agent@gmail.com" \
  --subject "Re: Request: City data" \
  --body "Here's the data." \
  --attachment ./test_data/sample_data.xlsx
```

## API Endpoints

### Mock SMTP Server

#### Inboxes
- `GET /api/inboxes` - List all inboxes
- `GET /api/inboxes/{email}` - Get emails for an inbox
- `DELETE /api/inboxes/{email}` - Clear an inbox

#### Emails
- `GET /api/inboxes/{email}/emails/{email_id}` - Get specific email
- `DELETE /api/inboxes/{email}/emails/{email_id}` - Delete email
- `DELETE /api/clear` - Clear all inboxes

#### Send
- `POST /api/send` - Send email directly

#### Webhooks
- `POST /api/webhooks` - Register webhook
- `GET /api/webhooks` - List webhooks
- `GET /api/webhooks/{webhook_id}` - Get webhook
- `DELETE /api/webhooks/{webhook_id}` - Unregister webhook

#### Health
- `GET /api/health` - Health check

### Mail Agent A2A Server

#### Agent Discovery
- `GET /.well-known/agent.json` - Agent card (RFC 8615)

#### JSON-RPC
- `POST /jsonrpc` - JSON-RPC 2.0 endpoint
  - Method: `tasks.execute` - Execute a new task
  - Method: `tasks.status` - Get task status

#### Task API
- `GET /api/tasks` - List all tasks
- `GET /api/tasks/{task_id}` - Get task status (with SSE streaming)

## Development

### Running Tests
```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src --cov-report=html

# Run specific test suite
pytest tests/test_mail_agent/  # Mail agent tests
pytest tests/test_models.py    # Mock SMTP tests

# Run with verbose output
pytest -v
```

### Project Structure
```
info-agent/
├── src/
│   ├── mock_smtp/        # Mock SMTP server implementation
│   └── mail_agent/       # LangGraph mail agent implementation
├── tests/                # Test suite
├── scripts/              # Helper scripts (A2A client, POC simulator)
├── test_data/            # Test files (gitignored)
├── resources/reports/    # Generated reports (gitignored)
├── .dev-resources/       # Architecture docs and prompts
├── pyproject.toml
├── .env.example
├── README.md
└── CLAUDE.md             # Developer documentation
```

## Architecture

### Three-Server Architecture

1. **Mock SMTP Server** (Ports 1025, 8025)
   - SMTP protocol handler
   - REST API for inspection
   - Webhook notifications

2. **Mail Agent - A2A Server** (Port 8000)
   - Google A2A protocol (JSON-RPC 2.0)
   - Non-blocking task execution
   - SQLite state persistence

3. **Mail Agent - Webhook Server** (Port 9000)
   - Email arrival notifications
   - Webhook routing to tasks
   - SSE streaming

### Mail Agent Workflow

```
User Instruction
     ↓
Parse Instruction (extract POC emails, requirements)
     ↓
Compose Email (LLM generates content)
     ↓
Send Email (via Mock SMTP API)
     ↓
Wait for Reply (interrupt, webhook-triggered resume)
     ↓
Fetch Email (retrieve from Mock SMTP)
     ↓
Extract Content (parse CSV/Excel attachments)
     ↓
Validate Response (LLM checks against requirements)
     ↓
Decide Next (retry if invalid, max 5 attempts)
     ↓
End (mark as completed or failed)
```

### State Persistence

- **LangGraph Checkpointing**: SQLite-based state persistence
- **Database**: `mail_agent_state.db` (gitignored)
- **Resumable**: Tasks can be interrupted and resumed
- **Thread-Safe**: Supports concurrent task execution

## Design Decisions

### Why In-Memory Storage (Mock SMTP)?
This is a testing tool, not a production email server. In-memory storage ensures:
- Fast operation
- No persistence concerns
- Clean state on restart
- Simple deployment

### Why LangGraph?
LangGraph provides:
- Clear state machine modeling
- Built-in checkpointing for persistence
- Easy node composition
- Interruptible workflows (critical for wait_for_reply)

### Why A2A Protocol?
Google's Agent-to-Agent protocol enables:
- Standardized agent communication
- Agent discovery via well-known endpoints
- Task-based execution model
- Non-blocking, resumable tasks

### Webhook Behavior
- Webhooks are dispatched asynchronously (fire-and-forget)
- Failed webhooks are logged but not persisted
- Retries use exponential backoff (configurable)
- Timeouts prevent hanging requests

## Limitations

### Mock SMTP Server
- Ephemeral storage (all data lost on restart)
- No TLS/SSL (plain text only)
- No authentication (open relay)
- Limited SMTP commands (basic implementation)
- No queue persistence (webhooks not retried after restart)

### Mail Agent
- Requires external Mock SMTP server
- LLM API key required (Gemini or Azure OpenAI)
- CSV/Excel parsing only (no other attachment formats)
- Max 5 retry attempts per POC
- English language only (LLM prompts)

## Use Cases

### Mock SMTP Server
- Testing email sending in applications
- Local development without real SMTP servers
- Integration testing for email workflows
- Webhook testing and debugging
- Email UI/UX development

### Mail Agent
- Automated data collection via email
- POC follow-ups with validation
- Email-based surveys with structured responses
- Testing autonomous agent workflows
- Prototyping agent-to-agent communication

## License

MIT

## Contributing

Contributions welcome! Please ensure:
- All tests pass (`pytest`)
- Code follows project structure guidelines (see `CLAUDE.md`)
- Files stay under 800 lines
- Comprehensive logging is maintained
- Environment variables documented in `.env.example`
- README.md and CLAUDE.md updated for user-facing changes

## Troubleshooting

### Mock SMTP server not responding
```bash
# Check if server is running
curl http://localhost:8025/api/health

# Check logs for errors
uv run mock-smtp  # Look for startup errors
```

### Mail Agent can't connect to Mock SMTP
```bash
# Verify Mock SMTP is running
curl http://localhost:8025/api/health

# Check .env configuration
uv run mail-agent config
```

### LLM API errors
```bash
# Verify API key is set
echo $MAIL_AGENT_GEMINI_API_KEY  # or MAIL_AGENT_AZURE_OPENAI_API_KEY

# Check .env file
cat .env | grep MAIL_AGENT_LLM

# Test with config command
uv run mail-agent config
```

### Webhook not received
```bash
# Check webhook is registered
curl http://localhost:8025/api/webhooks

# Verify webhook server is running (starts with mail-agent a2a or mail-agent run)
# Check webhook URL in .env
cat .env | grep WEBHOOK
```

## Documentation

- **CLAUDE.md** - Comprehensive developer documentation
- **.dev-resources/architecture/** - Architecture design documents
- **.dev-resources/contracts/** - API contracts (OpenAPI specs)
- **.dev-resources/prompts/** - System prompts and requirements

# Execution steps:
## mock smtp
uv run mock-smtp

## mail agent
uv run mail-agent a2a
uv run mail-agent run "send mail to raj@gmail.com asking 10 food recipes in csv file"

## a2aclient
python scripts/a2a_client.py info
uv run python scripts/a2a_client.py interactive

## reply simulator
uv run python scripts/poc_reply_simulator.py --from "raj@gmail.com" --to "info-agent@gmail.com" --subject "Re: Request: 10 Actor names" --body "Please find attached." --attachment ./test_data/sample_actors.csv