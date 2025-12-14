# Mock SMTP Server

A self-contained mock SMTP server for testing email functionality with a REST API and webhook support.

## Features

- **SMTP Server** (port 1025) - Accepts emails via SMTP protocol
- **REST API** (port 8025) - Inspect and manage emails via HTTP
- **In-Memory Storage** - Ephemeral email storage (resets on restart)
- **Webhook Notifications** - HTTP POST notifications when emails arrive
- **Multiple Inboxes** - Implicit inbox creation on first email
- **No Authentication** - Open relay for testing simplicity
- **Swagger UI** - Interactive API documentation at `/docs`

## Quick Start

### Installation

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -e .

# Or install with dev dependencies
pip install -e ".[dev]"
```

### Running the Server

```bash
# Start the server
mock-smtp

# Or run directly
python -m mock_smtp.main
```

The server will start with:
- SMTP on `localhost:1025`
- REST API on `0.0.0.0:8025`
- Swagger UI at `http://localhost:8025/docs`

### Configuration

Configure via environment variables with the `MOCK_SMTP_` prefix:

```bash
# Example .env file
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

## Usage Examples

### Sending Emails via SMTP

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

### Using the REST API

```bash
# List all inboxes
curl http://localhost:8025/api/inboxes

# Get emails for a specific inbox
curl http://localhost:8025/api/inboxes/recipient@example.com

# Get a specific email
curl http://localhost:8025/api/inboxes/recipient@example.com/emails/{email_id}

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
    "url": "http://localhost:9000/webhook",
    "inbox_filter": null
  }'

# List webhooks
curl http://localhost:8025/api/webhooks

# Clear all emails
curl -X DELETE http://localhost:8025/api/clear

# Health check
curl http://localhost:8025/api/health
```

### Webhook Payload Example

When an email arrives, registered webhooks receive:

```json
{
  "event": "email.received",
  "email_id": "550e8400-e29b-41d4-a716-446655440000",
  "from": "sender@example.com",
  "to": ["recipient@example.com"],
  "subject": "Test Email",
  "has_attachments": false,
  "attachment_count": 0,
  "received_at": "2025-12-14T10:30:00.000000",
  "body_preview": "This is a test email..."
}
```

## API Endpoints

### Inboxes

- `GET /api/inboxes` - List all inboxes
- `GET /api/inboxes/{email}` - Get emails for an inbox
- `DELETE /api/inboxes/{email}` - Clear an inbox

### Emails

- `GET /api/inboxes/{email}/emails/{email_id}` - Get specific email
- `DELETE /api/inboxes/{email}/emails/{email_id}` - Delete email
- `DELETE /api/clear` - Clear all inboxes

### Send

- `POST /api/send` - Send email directly

### Webhooks

- `POST /api/webhooks` - Register webhook
- `GET /api/webhooks` - List webhooks
- `GET /api/webhooks/{webhook_id}` - Get webhook
- `DELETE /api/webhooks/{webhook_id}` - Unregister webhook

### Health

- `GET /api/health` - Health check

## Development

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src/mock_smtp --cov-report=html

# Run specific test file
pytest tests/test_models.py

# Run with verbose output
pytest -v
```

### Project Structure

```
mock-smtp-server/
├── src/
│   └── mock_smtp/
│       ├── __init__.py
│       ├── main.py              # Entrypoint
│       ├── config.py            # Settings
│       ├── store/
│       │   ├── models.py        # Data models
│       │   └── inbox_store.py   # Storage
│       ├── webhooks/
│       │   ├── registry.py      # Webhook storage
│       │   └── dispatcher.py    # HTTP POST
│       ├── smtp/
│       │   ├── handler.py       # SMTP handler
│       │   └── server.py        # SMTP server
│       └── api/
│           ├── inbox_routes.py
│           ├── email_routes.py
│           ├── send_routes.py
│           ├── webhook_routes.py
│           └── router.py
├── tests/
│   ├── conftest.py
│   ├── test_models.py
│   ├── test_inbox_store.py
│   └── test_api_inboxes.py
├── pyproject.toml
├── README.md
└── .gitignore
```

## Design Decisions

### Why In-Memory Storage?

This is a **testing tool**, not a production email server. In-memory storage ensures:
- Fast operation
- No persistence concerns
- Clean state on restart
- Simple deployment

### Why No Authentication?

For testing environments, authentication adds unnecessary complexity. The server is designed to run locally or in isolated test environments.

### Attachment Size Limits

Default 10MB limit prevents memory exhaustion. Adjust via `MOCK_SMTP_MAX_ATTACHMENT_SIZE_MB`.

### Webhook Behavior

- Webhooks are dispatched **asynchronously** (fire-and-forget)
- Failed webhooks are logged but **not persisted**
- Retries use exponential backoff (configurable)
- Timeouts prevent hanging requests

## Limitations

- **Ephemeral storage** - All data lost on restart
- **No TLS/SSL** - Plain text only
- **No authentication** - Open relay
- **Limited SMTP commands** - Basic implementation
- **No queue persistence** - Webhooks not retried after restart

## Use Cases

- Testing email sending in applications
- Local development without real SMTP servers
- Integration testing for email workflows
- Webhook testing and debugging
- Email UI/UX development

## Mail Agent

An autonomous email agent that uses LangGraph and Google Gemini to:
1. Parse user instructions to extract POC email addresses and request details
2. Compose professional emails using LLM
3. Send emails via Mock SMTP
4. Wait for and receive POC replies via webhooks
5. Validate responses against success criteria
6. Send follow-up emails if needed (up to max attempts)
7. Generate final summary of results

### Quick Start

```bash
# Terminal 1: Start Mock SMTP Server
mock-smtp

# Terminal 2: Run Mail Agent
MAIL_AGENT_GEMINI_API_KEY=your-api-key \
mail-agent send "Send email to alice@company.com and bob@company.com requesting Q4 sales data in Excel"

# Terminal 3 (optional): Simulate POC replies
python scripts/poc_reply_simulator.py info-agent@gmail.com \
  --from alice@company.com \
  --rows 10 \
  --attachment sales_data.csv
```

### Configuration

Mail Agent configuration via `MAIL_AGENT_` environment variables:

```bash
# Required
MAIL_AGENT_GEMINI_API_KEY=sk-xxx-xxx

# Optional
MAIL_AGENT_MOCK_SMTP_API_URL=http://localhost:8025
MAIL_AGENT_AGENT_EMAIL=info-agent@gmail.com
MAIL_AGENT_WEBHOOK_HOST=localhost
MAIL_AGENT_WEBHOOK_PORT=9000
MAIL_AGENT_MAX_ATTEMPTS=5
MAIL_AGENT_WEBHOOK_WAIT_TIMEOUT=300
MAIL_AGENT_LOG_LEVEL=INFO
MAIL_AGENT_SQLITE_DB_PATH=./mail_agent_state.db
```

### Usage

#### Check Health

```bash
mail-agent health
```

#### Send Email Request

```bash
# Single POC
mail-agent send "Email alice@company.com requesting employee directory"

# Multiple POCs
mail-agent send "Email alice@company.com and bob@company.com requesting product roadmap"

# With timeout and logging
mail-agent send "Email poc@company.com asking for data" \
  --webhook-timeout 600 \
  --log-level DEBUG
```

#### POC Reply Simulator

Used to test Mail Agent without real POC responses:

```bash
# Send single reply
python scripts/poc_reply_simulator.py info-agent@gmail.com \
  --from alice@company.com \
  --subject "Re: Data Request" \
  --body "Here is the requested data" \
  --rows 5

# Send multiple replies in sequence
python scripts/poc_reply_simulator.py info-agent@gmail.com \
  --count 3 \
  --delay 2
```

### Architecture

**LangGraph State Machine:**
1. `parse_instruction` - Extract POC emails and criteria
2. `decide_next` - Route to next action
3. `compose_email` / `compose_followup` - Generate email
4. `send_email` - Send via Mock SMTP
5. `wait_for_reply` - Wait for webhook notification
6. `fetch_email` - Fetch full email with attachments
7. `extract_content` - Parse CSV/Excel attachments
8. `validate_response` - LLM validation against criteria
9. `end` - Generate summary

**Webhook Flow:**
- Agent registers webhook with Mock SMTP
- When POC replies arrive at agent inbox, Mock SMTP sends webhook
- Agent graph processes reply and validates content
- If valid: success. If invalid: compose follow-up (if attempts left)

**State Persistence:**
- SQLite checkpointer saves graph state
- Enables resuming interrupted executions
- Configurable database path

### Features

- **Multi-turn Conversations** - Automatically sends follow-ups for incomplete responses
- **LLM-Powered** - Uses Gemini to parse, compose, and validate
- **Webhook-Based** - Efficient async reply handling
- **Logging** - Comprehensive debug logging throughout
- **Error Recovery** - Timeout handling and max attempt limits
- **Type-Safe** - Full TypedDict state schema

### Development

```bash
# Run tests
pytest

# Run with coverage
pytest --cov=src/mail_agent --cov-report=html

# Run specific test
pytest tests/test_mail_agent.py -v
```

### Example Conversation Flow

**User Request:**
```
"Email alice@company.com requesting Q4 2024 sales data in Excel format"
```

**Agent Actions:**
1. Parses: POCs=[alice@company.com], criteria="Excel with Q4 2024 sales"
2. Composes: Professional email requesting Excel file
3. Sends: Via Mock SMTP to alice@company.com
4. Waits: For webhook with reply from alice@company.com
5. Fetches: Full email with attachments
6. Extracts: Parses Excel file
7. Validates: Checks if data matches Q4 2024 sales criteria
8. If valid: Success! | If invalid: Composes follow-up (max 5 attempts)

## License

MIT

## Contributing

Contributions welcome! Please ensure:
- All tests pass (`pytest`)
- Code follows project structure guidelines
- Files stay under 800 lines
- Comprehensive logging is maintained
