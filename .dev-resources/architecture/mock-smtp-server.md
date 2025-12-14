# Mock SMTP Server - Architecture Document

## Overview

A self-contained mock SMTP server for testing purposes that allows sending and receiving emails without any external SMTP dependencies. The system provides both SMTP protocol support (for applications) and REST API (for manual testing and inbox inspection).

---

## Requirements Summary

| Requirement | Decision |
|-------------|----------|
| SMTP Library | `aiosmtpd` |
| REST Interface | FastAPI (Swagger UI for interaction) |
| Authentication | None (open relay for testing) |
| Web UI | None (Swagger only) |
| Webhooks | Yes - notify on email arrival (failures logged to server) |
| Inbox Model | Multi-inbox, implicit creation (auto-create on first email) |
| Email ID Format | UUID |
| Persistence | In-memory (ephemeral) |
| External SMTP | None - fully self-contained |

---

## Technology Stack

| Component | Technology | Version | Purpose |
|-----------|------------|---------|---------|
| SMTP Server | `aiosmtpd` | ^1.4.4 | Receive emails via SMTP protocol |
| REST API | `fastapi` | ^0.109 | REST endpoints + Swagger UI |
| ASGI Server | `uvicorn` | ^0.27 | HTTP server for FastAPI |
| HTTP Client | `httpx` | ^0.26 | Async webhook dispatch |
| Email Parsing | `email` (stdlib) | - | Parse MIME messages |
| Validation | `pydantic` | ^2.5 | Request/response models |
| Settings | `pydantic-settings` | ^2.1 | Environment configuration |

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         MOCK SMTP SERVER (Self-Contained)                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   ┌─────────────┐                                                           │
│   │  Swagger UI │                                                           │
│   │  (Developer)│                                                           │
│   └──────┬──────┘                                                           │
│          │                                                                  │
│          │ HTTP :8025                                                       │
│          ▼                                                                  │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                         FastAPI REST API                            │   │
│   │                                                                     │   │
│   │   POST /api/send              GET /api/inboxes/{email}              │   │
│   │   ───────────────             ────────────────────────              │   │
│   │   Send email                  Read received emails                  │   │
│   │   (writes directly            (reads from store)                    │   │
│   │    to inbox store)                                                  │   │
│   └───────────┬─────────────────────────────┬───────────────────────────┘   │
│               │                             │                               │
│               │ store()                     │ get()                         │
│               ▼                             ▼                               │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                      INBOX STORE (In-Memory)                        │   │
│   │                                                                     │   │
│   │   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │   │
│   │   │ alice@test   │  │ bob@test     │  │ carol@test   │              │   │
│   │   │  [email1]    │  │  [email1]    │  │  [email1]    │              │   │
│   │   │  [email2]    │  │              │  │              │              │   │
│   │   └──────────────┘  └──────────────┘  └──────────────┘              │   │
│   └───────────────────────────────────────────────────────▲─────────────┘   │
│                                                           │                 │
│               ┌───────────────────────────────────────────┘                 │
│               │ store()                                                     │
│               │                                                             │
│   ┌───────────┴─────────────────────────────────────────────────────────┐   │
│   │                         AIOSMTPD Server :1025                       │   │
│   │                         (For apps sending via SMTP)                 │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│               ▲                                                             │
│               │ SMTP                                                        │
│               │                                                             │
│   ┌───────────┴─────┐                                                       │
│   │  Your App       │                                                       │
│   │  (Under Test)   │                                                       │
│   └─────────────────┘                                                       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Component Responsibilities

### AIOSMTPD Server (:1025)

The entry point for applications that send emails using standard SMTP protocol.

| # | Responsibility | Description |
|---|----------------|-------------|
| 1 | Listen for SMTP connections | Binds to port 1025, accepts incoming connections |
| 2 | Speak SMTP protocol | Handles EHLO, MAIL FROM, RCPT TO, DATA, QUIT commands |
| 3 | Receive raw email content | Accepts the full MIME message from client |
| 4 | Parse email | Extract from, to, subject, body, attachments |
| 5 | Route to inbox | Determine recipient → store in correct inbox |
| 6 | Trigger webhook | Fire async HTTP POST to registered webhooks |
| 7 | Return SMTP response | Send "250 OK" back to client |

### FastAPI REST API (:8025)

Provides HTTP interface for manual testing and inbox management.

| # | Responsibility | Description |
|---|----------------|-------------|
| 1 | Send emails | POST endpoint to create emails directly in inbox |
| 2 | Read inboxes | GET endpoints to list and retrieve emails |
| 3 | Manage inboxes | DELETE endpoints to clear inboxes |
| 4 | Webhook management | CRUD operations for webhook URLs |
| 5 | Health check | Server status endpoint |
| 6 | Swagger UI | Auto-generated API documentation |

### Inbox Store (Shared Memory)

Thread-safe in-memory storage for all emails.

| # | Responsibility | Description |
|---|----------------|-------------|
| 1 | Store emails | Add emails to recipient inboxes |
| 2 | Auto-create inboxes | Create inbox on first email (implicit) |
| 3 | Retrieve emails | Return emails by inbox or ID |
| 4 | Delete emails | Remove individual emails or clear inboxes |
| 5 | Thread safety | Handle concurrent access from SMTP and REST |

### Webhook Dispatcher

Async notification system for email arrival events.

| # | Responsibility | Description |
|---|----------------|-------------|
| 1 | Registry | Store registered webhook URLs |
| 2 | Dispatch | POST to webhooks when email arrives |
| 3 | Async fire | Non-blocking webhook calls |
| 4 | Error logging | Log failures to server logs |

---

## SMTP vs REST API Comparison

| Operation | SMTP Protocol | REST API (FastAPI) |
|-----------|---------------|-------------------|
| Send email | ✅ Yes | ✅ Yes |
| Read inbox | ❌ No | ✅ Yes |
| List emails | ❌ No | ✅ Yes |
| Delete emails | ❌ No | ✅ Yes |
| Register webhooks | ❌ No | ✅ Yes |

### SMTP Protocol Commands (RFC 5321)

```
┌───────────────────┬─────────────────────────────────────────┐
│  Command          │  Purpose                                │
├───────────────────┼─────────────────────────────────────────┤
│  EHLO/HELO        │  Handshake with server                  │
│  MAIL FROM:<addr> │  Specify sender                         │
│  RCPT TO:<addr>   │  Specify recipient(s)                   │
│  DATA             │  Begin email content                    │
│  QUIT             │  Close connection                       │
│  RSET             │  Reset transaction                      │
│  NOOP             │  Keep-alive ping                        │
└───────────────────┴─────────────────────────────────────────┘
```

---

## Two Entry Points for Sending Emails

| Method | How | Use Case |
|--------|-----|----------|
| REST API | `POST /api/send` via Swagger | Developer manually testing/simulating |
| SMTP | Application connects to port 1025 | Application under test |

Both methods write to the **same inbox store**.

---

## Sequence Diagrams

### 1. Receive Email via SMTP (Application Under Test)

```
┌──────────────┐                         ┌──────────────┐
│  Your App    │                         │   AIOSMTPD   │
│  (smtplib)   │                         │   Handler    │
└──────┬───────┘                         └──────┬───────┘
       │                                        │
       │  TCP Connect :1025                     │
       │───────────────────────────────────────▶│
       │                                        │
       │  "220 Mock SMTP Ready"                 │
       │◀───────────────────────────────────────│
       │                                        │
       │  EHLO myclient                         │
       │───────────────────────────────────────▶│
       │                                        │──┐
       │                                        │  │ Log: client connected
       │  "250-Hello myclient"                  │◀─┘
       │◀───────────────────────────────────────│
       │                                        │
       │  MAIL FROM:<alice@test>                │
       │───────────────────────────────────────▶│
       │                                        │──┐
       │                                        │  │ Store sender
       │  "250 OK"                              │◀─┘
       │◀───────────────────────────────────────│
       │                                        │
       │  RCPT TO:<bob@test>                    │
       │───────────────────────────────────────▶│
       │                                        │──┐
       │                                        │  │ Store recipient
       │  "250 OK"                              │◀─┘
       │◀───────────────────────────────────────│
       │                                        │
       │  DATA                                  │
       │───────────────────────────────────────▶│
       │                                        │
       │  "354 Start mail input"                │
       │◀───────────────────────────────────────│
       │                                        │
       │  Subject: Test Email                   │
       │  From: alice@test                      │
       │  To: bob@test                          │
       │                                        │
       │  Hello Bob!                            │
       │  .                                     │
       │───────────────────────────────────────▶│
       │                                        │──┐
       │                                        │  │ 1. Parse MIME content
       │                                        │  │ 2. Create Email object
       │                                        │  │ 3. Store in bob@test inbox
       │                                        │  │ 4. Trigger webhooks (async)
       │                                        │  │ 5. Log: email received
       │  "250 OK: Message accepted"            │◀─┘
       │◀───────────────────────────────────────│
       │                                        │
       │  QUIT                                  │
       │───────────────────────────────────────▶│
       │                                        │
       │  "221 Bye"                             │
       │◀───────────────────────────────────────│
       │                                        │
```

### 2. Send + Receive via Swagger (Manual Testing)

```
┌──────────┐                    ┌──────────────┐              ┌─────────────┐
│  You     │                    │   FastAPI    │              │ InboxStore  │
│ (Swagger)│                    │   :8025      │              │ (In-Memory) │
└────┬─────┘                    └──────┬───────┘              └──────┬──────┘
     │                                 │                             │
     │  POST /api/send                 │                             │
     │  {                              │                             │
     │    "from": "alice@test",        │                             │
     │    "to": ["bob@test"],          │                             │
     │    "subject": "Hello",          │                             │
     │    "body": "Hi Bob!"            │                             │
     │  }                              │                             │
     │────────────────────────────────▶│                             │
     │                                 │                             │
     │                                 │  store("bob@test", email)   │
     │                                 │────────────────────────────▶│
     │                                 │                             │
     │                                 │  ✓ stored (id: uuid-123)    │
     │                                 │◀────────────────────────────│
     │                                 │                             │
     │  200 OK {"id": "uuid-123"}      │                             │
     │◀────────────────────────────────│                             │
     │                                 │                             │
     │                                 │                             │
     │  GET /api/inboxes/bob@test      │                             │
     │────────────────────────────────▶│                             │
     │                                 │                             │
     │                                 │  get_emails("bob@test")     │
     │                                 │────────────────────────────▶│
     │                                 │                             │
     │                                 │  [email1, ...]              │
     │                                 │◀────────────────────────────│
     │                                 │                             │
     │  200 OK {emails: [...]}         │                             │
     │◀────────────────────────────────│                             │
     │                                 │                             │
```

### 3. Webhook Notification Flow

```
┌─────────────┐      SMTP       ┌─────────────┐      POST       ┌─────────────┐
│  Your App   │ ───────────────▶│  AIOSMTPD   │ ───────────────▶│  Your       │
│  sends email│                 │  receives   │   (automatic)   │  Webhook    │
└─────────────┘                 └─────────────┘                 │  Endpoint   │
                                                                └──────┬──────┘
                                                                       │
                                                                       ▼
                                                                ┌─────────────┐
                                                                │  Your Code  │
                                                                │  Executes   │
                                                                └─────────────┘
```

### 4. Server Startup (Concurrent Services)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              main.py                                        │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ asyncio.gather()
                                    │
                    ┌───────────────┴───────────────┐
                    │                               │
                    ▼                               ▼
        ┌───────────────────┐           ┌───────────────────┐
        │   AIOSMTPD        │           │   UVICORN         │
        │   SMTP Server     │           │   ASGI Server     │
        │   Port: 1025      │           │   Port: 8025      │
        │                   │           │                   │
        │   - Receives mail │           │   - REST API      │
        │   - Stores inbox  │           │   - Swagger UI    │
        │   - Triggers hook │           │   - Health check  │
        └───────────────────┘           └───────────────────┘
                    │                               │
                    │                               │
                    └───────────────┬───────────────┘
                                    │
                                    ▼
                        ┌───────────────────┐
                        │   SHARED STATE    │
                        │                   │
                        │   - InboxStore    │
                        │   - WebhookRegistry│
                        │   - Config        │
                        │                   │
                        │   (Thread-safe    │
                        │    in-memory)     │
                        └───────────────────┘
```

---

## Directory Structure

```
src/mock_smtp/
├── __init__.py
├── main.py                 # Entrypoint: runs both servers concurrently
├── config.py               # Pydantic Settings
│
├── smtp/
│   ├── __init__.py
│   ├── server.py           # AIOSMTPD server setup & lifecycle
│   └── handler.py          # Custom handler → InboxStore + Webhooks
│
├── store/
│   ├── __init__.py
│   ├── models.py           # Email, Inbox, Attachment dataclasses
│   └── inbox_store.py      # Thread-safe in-memory storage
│
├── webhooks/
│   ├── __init__.py
│   ├── dispatcher.py       # Async POST to webhook URLs
│   └── registry.py         # Webhook URL CRUD
│
└── api/
    ├── __init__.py
    ├── router.py           # Aggregate all routers
    ├── inbox_routes.py     # GET/DELETE inboxes
    ├── email_routes.py     # GET/DELETE emails
    ├── webhook_routes.py   # Webhook registration
    └── send_routes.py      # POST /api/send
```

---

## API Contracts

### Inboxes

#### `GET /api/inboxes`
List all inboxes with email counts.

```json
// Response 200
{
  "inboxes": [
    {
      "email": "user1@localhost",
      "email_count": 5,
      "created_at": "2025-01-15T10:30:00Z",
      "last_email_at": "2025-01-15T11:45:00Z"
    }
  ]
}
```

#### `GET /api/inboxes/{email}`
Get all emails for a specific inbox.

```json
// Response 200
{
  "email": "user1@localhost",
  "emails": [
    {
      "id": "uuid-1234",
      "from": "sender@example.com",
      "to": ["user1@localhost"],
      "subject": "Test Email",
      "body_text": "Plain text content",
      "body_html": "<html>...</html>",
      "attachments": [
        {
          "filename": "doc.pdf",
          "content_type": "application/pdf",
          "size_bytes": 1024,
          "content_base64": "..."
        }
      ],
      "headers": {"X-Custom": "value"},
      "received_at": "2025-01-15T11:45:00Z"
    }
  ]
}
```

#### `DELETE /api/inboxes/{email}`
Clear all emails from an inbox.

```json
// Response 200
{
  "message": "Inbox cleared",
  "deleted_count": 5
}
```

### Emails

#### `GET /api/inboxes/{email}/emails/{email_id}`
Get a single email by ID.

```json
// Response 200
{
  "id": "uuid-1234",
  "from": "sender@example.com",
  "to": ["user1@localhost"],
  "subject": "Test Email",
  "body_text": "...",
  "body_html": "...",
  "attachments": [],
  "raw": "Full raw MIME content...",
  "received_at": "2025-01-15T11:45:00Z"
}
```

#### `DELETE /api/inboxes/{email}/emails/{email_id}`
Delete a specific email.

```json
// Response 200
{
  "message": "Email deleted"
}
```

### Send Email

#### `POST /api/send`
Send an email (stores directly in recipient inbox).

```json
// Request
{
  "from_email": "alice@test",
  "to": ["bob@test"],
  "cc": [],
  "subject": "Hello Bob",
  "body_text": "Hi Bob, how are you?",
  "body_html": "<p>Hi Bob!</p>",
  "attachments": []
}

// Response 201
{
  "id": "uuid-123",
  "from": "alice@test",
  "to": ["bob@test"],
  "subject": "Hello Bob",
  "stored_in_inboxes": ["bob@test"],
  "created_at": "2025-01-15T10:30:00Z"
}
```

### Webhooks

#### `POST /api/webhooks`
Register a webhook URL.

```json
// Request
{
  "url": "https://your-service.com/email-webhook",
  "inbox_filter": null
}

// Response 201
{
  "id": "webhook-uuid",
  "url": "https://your-service.com/email-webhook",
  "inbox_filter": null,
  "created_at": "2025-01-15T10:00:00Z"
}
```

#### `GET /api/webhooks`
List all registered webhooks.

#### `DELETE /api/webhooks/{webhook_id}`
Remove a webhook.

### Webhook Payload (Outgoing)

When an email arrives, POST to registered webhooks:

```json
{
  "event": "email.received",
  "timestamp": "2025-01-15T11:45:00Z",
  "email": {
    "id": "uuid-1234",
    "inbox": "user1@localhost",
    "from": "sender@example.com",
    "to": ["user1@localhost"],
    "subject": "Test Email",
    "body_text": "Plain text...",
    "body_html": "<html>...</html>",
    "attachments": [
      {
        "filename": "doc.pdf",
        "content_type": "application/pdf",
        "size_bytes": 1024,
        "content_base64": "base64-encoded-content"
      }
    ]
  }
}
```

### Server Management

#### `DELETE /api/clear`
Clear ALL inboxes (reset server state).

```json
// Response 200
{
  "message": "All inboxes cleared",
  "deleted_inboxes": 3,
  "deleted_emails": 15
}
```

#### `GET /api/health`
Health check endpoint.

```json
// Response 200
{
  "status": "healthy",
  "smtp_port": 1025,
  "api_port": 8025,
  "uptime_seconds": 3600
}
```

---

## Algorithms

### Email Reception Flow (SMTP)

```
FUNCTION handle_incoming_email(envelope):
    1. EXTRACT sender, recipients, raw_message from envelope

    2. PARSE raw_message using email.message_from_bytes()
       - Extract headers (Subject, From, To, Date, etc.)
       - Extract body (text/plain and text/html parts)
       - Extract attachments (decode base64, store metadata)

    3. FOR EACH recipient in recipients:
        a. NORMALIZE email address (lowercase, strip whitespace)
        b. CREATE inbox if not exists in INBOX_STORE
        c. GENERATE unique email_id (UUID)
        d. STORE parsed email in inbox
        e. LOG email received for {recipient}

    4. ASYNC dispatch webhooks:
        a. FOR EACH registered webhook:
            - IF webhook.inbox_filter is None OR matches recipient:
                - POST payload to webhook.url
                - LOG webhook result (success/failure)

    5. RETURN "250 OK" to SMTP client
```

### Email Send Flow (REST API)

```
FUNCTION send_email(request: SendRequest) -> SendResponse:
    1. VALIDATE request
       - At least one recipient (to/cc)
       - At least body_text OR body_html provided
       - Valid email formats

    2. GENERATE unique email_id (UUID)

    3. CREATE Email object with:
       - id, from, to, cc, subject, body_text, body_html
       - attachments (if any)
       - created_at timestamp

    4. FOR EACH recipient in (to + cc):
        a. NORMALIZE email address
        b. CREATE inbox if not exists
        c. STORE email in inbox
        d. LOG email stored for {recipient}

    5. ASYNC dispatch webhooks (same as SMTP flow)

    6. RETURN SendResponse with email_id and stored_in_inboxes
```

---

## Configuration

### Environment Variables

```
MOCK_SMTP_SMTP_HOST=0.0.0.0
MOCK_SMTP_SMTP_PORT=1025
MOCK_SMTP_API_HOST=0.0.0.0
MOCK_SMTP_API_PORT=8025
MOCK_SMTP_LOG_LEVEL=INFO
MOCK_SMTP_MAX_EMAILS_PER_INBOX=100
MOCK_SMTP_MAX_ATTACHMENT_SIZE_MB=25
MOCK_SMTP_WEBHOOK_TIMEOUT_SECONDS=10
```

---

## Webhook vs Polling

| Approach | How | Pros | Cons |
|----------|-----|------|------|
| Polling | Keep calling `GET /api/inboxes` | Simple | Delayed, wasteful |
| Webhook | Server POSTs to you instantly | Real-time, efficient | Need endpoint |

---

## Summary

This architecture provides:

- ✅ Receive emails via SMTP (aiosmtpd) - for applications under test
- ✅ Send emails via REST API - for manual testing via Swagger
- ✅ Read emails via REST API - inspect inbox contents
- ✅ Multiple inboxes - one per recipient email (auto-created)
- ✅ Webhook notifications - real-time email arrival events
- ✅ No authentication - open relay for testing simplicity
- ✅ Fully self-contained - no external SMTP dependencies
- ✅ In-memory storage - ephemeral, resets on restart
