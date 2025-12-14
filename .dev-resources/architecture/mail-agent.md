# Mail Agent Architecture

## Overview

The Mail Agent is a LangGraph-based autonomous agent that sends email requests to points of contact (POCs), monitors for replies, validates response content using LLM, and handles multi-turn conversations until the request is satisfied or max attempts are reached.

## Requirements Summary

- Accept user instructions like `"send mail to raj@gmail.com asking 10 food recipes in excel file"`
- Send email to POC via mock SMTP server REST API
- Monitor for replies via webhook (POC replies via SMTP)
- Validate reply content (attachments) using LLM
- Support multi-turn conversations (up to 5 attempts)
- Support multiple POCs simultaneously
- Provide real-time progress updates

---

## Consolidated Design Decisions

| Decision | Choice |
|----------|--------|
| Agent Framework | LangGraph with Gemini 2.5 Flash |
| Reply Detection | Webhook (POC replies via SMTP triggers webhook) |
| State Persistence | SQLite via LangGraph checkpointer |
| Progress Updates | Real-time CLI output |
| Autonomy | Fully autonomous (no human-in-the-loop) |
| Email Composition | LLM-generated |
| Multi-POC Support | Yes - single graph, parallel state per POC |
| Outbound Attachments | No - not in scope |
| Inbound Attachments | Excel (.xlsx) + CSV only |
| Validation Method | LLM-based content analysis |
| Max Conversation Turns | 5 attempts before giving up |
| Agent Email Address | `info-agent@gmail.com` |
| Webhook Receiver | Embedded FastAPI server in agent process |

---

## System Architecture

### High-Level System Overview

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              SYSTEM OVERVIEW                                         │
└─────────────────────────────────────────────────────────────────────────────────────┘

     ┌────────────────┐          ┌────────────────┐          ┌────────────────┐
     │     USER       │          │   MAIL AGENT   │          │   POC REPLY    │
     │    (CLI)       │          │   (LangGraph)  │          │   SIMULATOR    │
     └───────┬────────┘          └───────┬────────┘          └───────┬────────┘
             │                           │                           │
             │ 1. Instruction            │                           │
             │─────────────────────────▶ │                           │
             │                           │                           │
             │                           │ 2. Send Email             │
             │                           │ (REST API)                │
             │                           │───────────┐               │
             │                           │           │               │
             │                           │           ▼               │
             │                           │    ┌─────────────┐        │
             │                           │    │ Mock SMTP   │        │
             │                           │    │ Server      │        │
             │                           │    │ :8025/:1025 │        │
             │                           │    └──────┬──────┘        │
             │                           │           │               │
             │                           │           │ 3. Email      │
             │                           │           │    stored     │
             │                           │           │               │
             │                           │    ┌──────▼──────┐        │
             │                           │    │ POC Inbox   │        │
             │                           │    │raj@gmail.com│◀───────┤
             │                           │    └─────────────┘        │
             │                           │                           │
             │                           │                           │ 4. POC sends
             │                           │                           │    reply with
             │                           │                           │    attachment
             │                           │                           │    (SMTP :1025)
             │                           │           ┌───────────────┤
             │                           │           │               │
             │                           │           ▼               │
             │                           │    ┌─────────────┐        │
             │                           │    │ Agent Inbox │        │
             │                           │    │info-agent@  │        │
             │                           │    │gmail.com    │        │
             │                           │    └──────┬──────┘        │
             │                           │           │               │
             │                           │           │ 5. Webhook    │
             │                           │           │    triggered  │
             │                           │    ┌──────▼──────┐        │
             │                           │◀───│ POST /webhook│       │
             │                           │    │ email-received       │
             │                           │    └─────────────┘        │
             │                           │                           │
             │                           │ 6. Fetch full email       │
             │                           │    + attachment           │
             │                           │───────────┐               │
             │                           │           ▼               │
             │                           │    ┌─────────────┐        │
             │                           │    │GET /api/    │        │
             │                           │    │inboxes/.../│        │
             │                           │    │emails/{id}  │        │
             │                           │    └─────────────┘        │
             │                           │                           │
             │                           │ 7. Validate with LLM      │
             │                           │                           │
             │ 8. Result                 │                           │
             │◀──────────────────────────│                           │
             │                           │                           │
```

### Component Interaction Flow

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                           COMPONENT INTERACTION                                      │
└─────────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   CLI (typer)   │     │  LangGraph      │     │  Webhook Server │
│                 │     │  Agent          │     │  (FastAPI)      │
└────────┬────────┘     └────────┬────────┘     └────────┬────────┘
         │                       │                       │
         │ 1. Run agent          │                       │
         │──────────────────────▶│                       │
         │                       │                       │
         │                       │ 2. Start webhook      │
         │                       │    server             │
         │                       │──────────────────────▶│
         │                       │                       │
         │                       │ 3. Register webhook   │
         │                       │    with mock SMTP     │
         │                       │─────────┐             │
         │                       │         │             │
         │                       │         ▼             │
         │                       │  ┌─────────────┐      │
         │                       │  │ Mock SMTP   │      │
         │                       │  │ Server      │      │
         │                       │  └──────┬──────┘      │
         │                       │         │             │
         │                       │ 4. Send email         │
         │                       │    (REST API)         │
         │                       │────────▶│             │
         │                       │         │             │
         │                       │         │ 5. POC      │
         │                       │         │    replies  │
         │                       │         │    (SMTP)   │
         │                       │         │             │
         │                       │         │ 6. Webhook  │
         │                       │         │    POST     │
         │                       │         │────────────▶│
         │                       │         │             │
         │                       │◀────────────────────── │ 7. Notify
         │                       │         │             │    agent
         │                       │         │             │
         │                       │ 8. Fetch│full email   │
         │                       │────────▶│             │
         │                       │         │             │
         │                       │◀────────│             │
         │                       │         │             │
         │                       │ 9. Validate with LLM  │
         │                       │                       │
         │ 10. Progress/Result   │                       │
         │◀──────────────────────│                       │
         │                       │                       │
```

---

## LangGraph State Machine

### State Machine Diagram

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                         LANGGRAPH STATE MACHINE                                      │
└─────────────────────────────────────────────────────────────────────────────────────┘

                                    ┌─────────┐
                                    │  START  │
                                    └────┬────┘
                                         │
                                         ▼
                              ┌─────────────────────┐
                              │   PARSE_INSTRUCTION │
                              │                     │
                              │ Extract:            │
                              │ - POC emails[]      │
                              │ - Request type      │
                              │ - Success criteria  │
                              └──────────┬──────────┘
                                         │
                                         ▼
                              ┌─────────────────────┐
                              │   COMPOSE_EMAIL     │
                              │                     │
                              │ LLM generates:      │
                              │ - Subject line      │
                              │ - Email body        │
                              │ - Professional tone │
                              └──────────┬──────────┘
                                         │
                                         ▼
                              ┌─────────────────────┐
                              │   SEND_EMAIL        │
                              │                     │
                              │ POST /api/send      │
                              │ For each POC        │
                              └──────────┬──────────┘
                                         │
                                         ▼
                              ┌─────────────────────┐
                              │   WAIT_FOR_REPLY    │◀─────────────────────┐
                              │                     │                      │
                              │ Async wait for      │                      │
                              │ webhook callback    │                      │
                              └──────────┬──────────┘                      │
                                         │                                 │
                                         │ Webhook received                │
                                         ▼                                 │
                              ┌─────────────────────┐                      │
                              │   FETCH_EMAIL       │                      │
                              │                     │                      │
                              │ GET /api/inboxes/   │                      │
                              │ {email}/emails/{id} │                      │
                              └──────────┬──────────┘                      │
                                         │                                 │
                                         ▼                                 │
                              ┌─────────────────────┐                      │
                              │   EXTRACT_CONTENT   │                      │
                              │                     │                      │
                              │ - Decode base64     │                      │
                              │ - Excel -> JSON     │                      │
                              │ - CSV -> Text       │                      │
                              └──────────┬──────────┘                      │
                                         │                                 │
                                         ▼                                 │
                              ┌─────────────────────┐                      │
                              │   VALIDATE_WITH_LLM │                      │
                              │                     │                      │
                              │ LLM checks:         │                      │
                              │ - Matches request?  │                      │
                              │ - Complete data?    │                      │
                              │ - Quality OK?       │                      │
                              └──────────┬──────────┘                      │
                                         │                                 │
                                         ▼                                 │
                              ┌─────────────────────┐                      │
                              │   DECIDE_NEXT       │                      │
                              │                     │                      │
                              │ Valid? ───────────▶ SUCCESS               │
                              │ Invalid + attempts  │                      │
                              │   < 5? ───────────▶ COMPOSE_FOLLOWUP ─────┘
                              │ Invalid + attempts  │
                              │   >= 5? ──────────▶ FAILURE
                              └──────────┬──────────┘
                                         │
                          ┌──────────────┼──────────────┐
                          │              │              │
                          ▼              ▼              ▼
                    ┌──────────┐  ┌──────────┐  ┌──────────┐
                    │ SUCCESS  │  │ FAILURE  │  │ FOLLOWUP │
                    │          │  │          │  │          │
                    │ Report   │  │ Report   │  │ Compose  │
                    │ to user  │  │ to user  │  │ correction│
                    │          │  │ (max     │  │ request  │
                    │          │  │ attempts)│  │          │
                    └──────────┘  └──────────┘  └────┬─────┘
                                                     │
                                                     │ Back to SEND_EMAIL
                                                     └─────────────────────▶
```

### Node Descriptions

| Node | Purpose | Input | Output |
|------|---------|-------|--------|
| `parse_instruction` | Extract structured data from user input | Raw instruction string | POC emails, request description, success criteria |
| `compose_email` | Generate professional email using LLM | Parsed request, POC email | Subject, body text |
| `send_email` | Send email via REST API | Email content, POC address | Email ID, status |
| `wait_for_reply` | Async wait for webhook notification | None | Webhook payload |
| `fetch_email` | Retrieve full email with attachments | Email ID | Full email object |
| `extract_content` | Parse attachment content | Attachment bytes | JSON/text representation |
| `validate_with_llm` | Check if response satisfies request | Original request, extracted content | is_valid, feedback |
| `decide_next` | Determine next action based on validation | Validation result, attempt count | Next node to execute |
| `compose_followup` | Generate correction request email | Validation feedback | Follow-up email content |

---

## Agent State Schema

```
AgentState = {
    # Original request
    "user_instruction": str,              # Raw user input

    # Parsed request
    "parsed_request": {
        "poc_emails": List[str],          # ["raj@gmail.com", "priya@gmail.com"]
        "request_type": str,              # "data_request", "information_request"
        "request_description": str,       # "10 food recipes in excel format"
        "success_criteria": str,          # "Excel file with 10 rows of recipes"
    },

    # Per-POC conversation state
    "conversations": Dict[str, {          # Keyed by POC email
        "status": str,                    # "pending", "waiting", "validating",
                                          # "success", "failed"
        "attempt_count": int,             # 0-5
        "sent_emails": List[{
            "email_id": str,
            "subject": str,
            "sent_at": datetime,
        }],
        "received_emails": List[{
            "email_id": str,
            "from": str,
            "subject": str,
            "received_at": datetime,
            "has_attachment": bool,
            "attachment_content": str,    # Extracted text/JSON
        }],
        "validation_results": List[{
            "attempt": int,
            "is_valid": bool,
            "feedback": str,              # LLM explanation
        }],
        "final_result": Optional[str],    # "success" | "failed_max_attempts"
    }],

    # Current processing
    "current_node": str,                  # For debugging/progress
    "pending_webhooks": List[str],        # Email IDs awaiting processing

    # Output
    "progress_messages": List[str],       # Real-time status updates
    "final_summary": Optional[str],       # End result for user
}
```

---

## Technology Stack

| Component | Package | Version | Purpose |
|-----------|---------|---------|---------|
| **Agent Framework** | `langgraph` | latest | State machine orchestration |
| **LLM SDK** | `langchain-google-genai` | latest | Gemini 2.5 Flash integration |
| **State Persistence** | `langgraph-checkpoint-sqlite` | latest | SQLite checkpointing |
| **HTTP Client** | `httpx` | latest | Async REST API calls |
| **Webhook Server** | `fastapi` + `uvicorn` | latest | Receive webhook POSTs |
| **Excel Parser** | `openpyxl` | latest | Read .xlsx files |
| **CSV Parser** | `csv` (stdlib) | - | Read CSV files |
| **SMTP Client** | `aiosmtplib` | latest | POC reply simulator script |
| **CLI** | `typer` | latest | User interface |
| **Async** | `asyncio` | stdlib | Concurrent operations |

---

## Directory Structure

```
/workspaces/info-agent-3/
├── src/
│   ├── mock_smtp/                    # Existing mock SMTP server
│   │   └── ...
│   │
│   └── mail_agent/                   # NEW: Mail Agent package
│       ├── __init__.py
│       ├── main.py                   # CLI entrypoint (typer)
│       │
│       ├── agent/
│       │   ├── __init__.py
│       │   ├── graph.py              # LangGraph definition
│       │   ├── state.py              # TypedDict state schema
│       │   └── nodes/
│       │       ├── __init__.py
│       │       ├── parse_instruction.py
│       │       ├── compose_email.py
│       │       ├── send_email.py
│       │       ├── wait_for_reply.py
│       │       ├── fetch_email.py
│       │       ├── extract_content.py
│       │       ├── validate_response.py
│       │       └── decide_next.py
│       │
│       ├── webhook/
│       │   ├── __init__.py
│       │   └── server.py             # FastAPI webhook receiver
│       │
│       ├── tools/
│       │   ├── __init__.py
│       │   ├── smtp_client.py        # Send email via REST API
│       │   ├── inbox_client.py       # Fetch emails via REST API
│       │   └── attachment_parser.py  # Excel/CSV extraction
│       │
│       ├── llm/
│       │   ├── __init__.py
│       │   ├── client.py             # Gemini 2.5 Flash client
│       │   └── prompts.py            # Prompt templates
│       │
│       └── config.py                 # Settings (pydantic)
│
├── scripts/                          # Utility scripts
│   └── poc_reply_simulator.py        # Standalone SMTP reply script
│
├── tests/
│   ├── test_mail_agent/              # Agent tests
│   │   ├── test_parse_instruction.py
│   │   ├── test_compose_email.py
│   │   ├── test_attachment_parser.py
│   │   └── test_integration.py
│   └── ...
│
├── test_data/                        # Test fixtures
│   ├── sample_recipes.xlsx
│   ├── sample_recipes.csv
│   └── sample_invalid.xlsx
│
└── pyproject.toml                    # Updated with new dependencies
```

---

## Integration Points & API Contracts

### 1. Agent -> Mock SMTP Server: Send Email

**Endpoint:** `POST http://localhost:8025/api/send`

**Request:**
```json
{
  "from_address": "info-agent@gmail.com",
  "to_addresses": ["raj@gmail.com"],
  "subject": "Request: 10 Food Recipes in Excel Format",
  "body_text": "Dear Raj,\n\nI hope this email finds you well...",
  "body_html": null
}
```

**Response (201 Created):**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "from_address": "info-agent@gmail.com",
  "to_addresses": ["raj@gmail.com"],
  "subject": "Request: 10 Food Recipes in Excel Format",
  "received_at": "2025-12-14T10:00:00.000000"
}
```

### 2. Agent -> Mock SMTP Server: Register Webhook

**Endpoint:** `POST http://localhost:8025/api/webhooks`

**Request:**
```json
{
  "url": "http://localhost:9000/webhook/email-received",
  "inbox_filter": "info-agent@gmail.com"
}
```

**Response (201 Created):**
```json
{
  "id": "770e8400-e29b-41d4-a716-446655440002",
  "url": "http://localhost:9000/webhook/email-received",
  "inbox_filter": "info-agent@gmail.com",
  "created_at": "2025-12-14T09:00:00.000000"
}
```

### 3. Mock SMTP Server -> Agent: Webhook Notification

**Endpoint:** `POST http://localhost:9000/webhook/email-received`

**Headers:**
```
Content-Type: application/json
X-Webhook-Event: email.received
X-Email-ID: 660e8400-e29b-41d4-a716-446655440001
X-Webhook-Timestamp: 2025-12-14T11:30:00.000000
```

**Request:**
```json
{
  "event": "email.received",
  "email_id": "660e8400-e29b-41d4-a716-446655440001",
  "from": "raj@gmail.com",
  "to": ["info-agent@gmail.com"],
  "subject": "Re: Request: 10 Food Recipes in Excel Format",
  "has_attachments": true,
  "attachment_count": 1,
  "received_at": "2025-12-14T11:30:00.000000",
  "body_preview": "Hi, please find the attached Excel file..."
}
```

**Response (200 OK):**
```json
{"status": "received"}
```

### 4. Agent -> Mock SMTP Server: Fetch Full Email

**Endpoint:** `GET http://localhost:8025/api/inboxes/{email}/emails/{email_id}`

**Example:** `GET http://localhost:8025/api/inboxes/info-agent%40gmail.com/emails/660e8400-e29b-41d4-a716-446655440001`

**Response (200 OK):**
```json
{
  "id": "660e8400-e29b-41d4-a716-446655440001",
  "from_address": "raj@gmail.com",
  "to_addresses": ["info-agent@gmail.com"],
  "subject": "Re: Request: 10 Food Recipes in Excel Format",
  "body_text": "Hi,\n\nPlease find the attached Excel file with 10 food recipes.\n\nBest regards,\nRaj",
  "body_html": null,
  "attachments": [
    {
      "filename": "food_recipes.xlsx",
      "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      "size_bytes": 12456,
      "content_base64": "UEsDBBQAAAAIAA..."
    }
  ],
  "headers": {
    "In-Reply-To": "<550e8400-e29b-41d4-a716-446655440000@mock-smtp>",
    "References": "<550e8400-e29b-41d4-a716-446655440000@mock-smtp>"
  },
  "received_at": "2025-12-14T11:30:00.000000"
}
```

---

## POC Reply Simulator Script

### Purpose

A standalone Python script that simulates POC (Point of Contact) replies by sending emails with attachments via SMTP. This triggers webhooks since the mock SMTP server only fires webhooks for SMTP-received emails (not REST API sends).

### Usage

```bash
python scripts/poc_reply_simulator.py \
  --from "raj@gmail.com" \
  --to "info-agent@gmail.com" \
  --subject "Re: Request: 10 Food Recipes" \
  --body "Please find attached the recipes." \
  --attachment ./test_data/sample_recipes.xlsx
```

### Algorithm

```
ALGORITHM: POCReplySimulator

INPUT:
  - from_email: str
  - to_email: str
  - subject: str
  - body: str
  - attachment_path: str (optional, .xlsx or .csv)

1. PARSE_ARGUMENTS()
   - Validate required arguments
   - Validate attachment file exists (if provided)
   - Validate attachment extension is .xlsx or .csv

2. CREATE_MIME_MESSAGE()
   - Create MIMEMultipart("mixed") message
   - Set headers: From, To, Subject, Date, Message-ID
   - Attach body as MIMEText("plain")

3. IF attachment_path:
   a. READ_ATTACHMENT_FILE()
      - Read binary content
      - Determine content-type from extension
        - .xlsx -> application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
        - .csv -> text/csv
   b. CREATE_MIME_ATTACHMENT()
      - Create MIMEBase with content-type
      - Encode with base64
      - Set Content-Disposition header with filename
   c. ATTACH to message

4. CONNECT_SMTP()
   - Connect to localhost:1025
   - Send EHLO

5. SEND_EMAIL()
   - MAIL FROM
   - RCPT TO
   - DATA (MIME message)

6. DISCONNECT()
   - QUIT

7. LOG success message
```

### SMTP Flow

```
CONNECT localhost:1025
EHLO localhost
MAIL FROM:<raj@gmail.com>
RCPT TO:<info-agent@gmail.com>
DATA
From: raj@gmail.com
To: info-agent@gmail.com
Subject: Re: Request: 10 Food Recipes
Date: Sat, 14 Dec 2025 11:30:00 +0000
MIME-Version: 1.0
Content-Type: multipart/mixed; boundary="===============..."

--===============...
Content-Type: text/plain; charset="utf-8"

Please find attached the recipes.

--===============...
Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
Content-Disposition: attachment; filename="sample_recipes.xlsx"
Content-Transfer-Encoding: base64

UEsDBBQAAAAIAA...
--===============...--
.
QUIT
```

---

## Core Algorithms

### Algorithm 1: Main Agent Execution Flow

```
ALGORITHM: MailAgentExecution

INPUT: user_instruction (string)
OUTPUT: final_result (success/failure per POC)

1. PARSE_INSTRUCTION(user_instruction)
   a. Call LLM with instruction
   b. Extract structured data:
      - poc_emails: List[str]
      - request_description: str
      - success_criteria: str
   c. Initialize conversation state for each POC
   d. LOG: "Parsed instruction: {poc_count} POCs, request: {description}"

2. FOR EACH poc_email IN poc_emails:
   a. COMPOSE_EMAIL(poc_email, request_description)
      - Call LLM to generate professional email
      - Include clear request and expected format
      - LOG: "Composed email for {poc_email}"

   b. SEND_EMAIL(poc_email, composed_email)
      - POST to /api/send
      - Store email_id in state
      - LOG: "Sent email to {poc_email}, id={email_id}"

   c. Set conversation[poc_email].status = "waiting"
      Set conversation[poc_email].attempt_count = 1

3. REGISTER_WEBHOOK()
   - POST to /api/webhooks with agent's inbox filter
   - LOG: "Webhook registered for info-agent@gmail.com"

4. START_WEBHOOK_SERVER()
   - Launch FastAPI on port 9000
   - LOG: "Webhook server listening on :9000"

5. WAIT_FOR_WEBHOOKS()
   - Async wait for all POCs to reach terminal state
   - On webhook received:
     a. Extract email_id from payload
     b. Add to pending_webhooks queue
     c. Trigger processing

6. PROCESS_WEBHOOK(webhook_payload):
   a. FETCH_EMAIL(email_id)
      - GET /api/inboxes/{inbox}/emails/{email_id}
      - LOG: "Fetched email {email_id} from {from_address}"

   b. EXTRACT_CONTENT(email)
      - IF attachment.filename ends with .xlsx:
          - Decode base64
          - Parse with openpyxl
          - Convert to JSON: [{col1: val1, col2: val2}, ...]
      - IF attachment.filename ends with .csv:
          - Decode base64
          - Return raw text
      - LOG: "Extracted content: {row_count} rows"

   c. VALIDATE_WITH_LLM(original_request, extracted_content)
      - Build prompt with:
          - Original user instruction
          - Success criteria
          - Extracted content (JSON/text)
      - Ask LLM: "Does this response satisfy the request?"
      - Parse LLM response: {is_valid: bool, feedback: str}
      - LOG: "Validation result: {is_valid}, feedback: {feedback}"

   d. DECIDE_NEXT(validation_result, attempt_count):
      - IF is_valid:
          - Set status = "success"
          - LOG: "SUCCESS for {poc_email}"
          - RETURN
      - ELSE IF attempt_count >= 5:
          - Set status = "failed"
          - LOG: "FAILED for {poc_email} after 5 attempts"
          - RETURN
      - ELSE:
          - COMPOSE_FOLLOWUP(feedback)
          - Call LLM to generate correction request
          - Include specific feedback
          - SEND_EMAIL(poc_email, followup_email)
          - Increment attempt_count
          - Set status = "waiting"
          - LOG: "Sent follow-up #{attempt_count} to {poc_email}"

7. GENERATE_SUMMARY()
   - Compile results for all POCs
   - Report successes and failures
   - LOG and OUTPUT final summary to user
```

### Algorithm 2: Attachment Content Extraction

```
ALGORITHM: ExtractAttachmentContent

INPUT: attachment (object with filename, content_base64)
OUTPUT: extracted_content (string - JSON or raw text)

1. DECODE_BASE64(attachment.content_base64)
   - Convert base64 string to bytes

2. DETERMINE_FILE_TYPE(attachment.filename)
   - IF ends with ".xlsx": file_type = "excel"
   - IF ends with ".csv": file_type = "csv"
   - ELSE: RAISE UnsupportedAttachmentError

3. IF file_type == "excel":
   a. LOAD_WORKBOOK(bytes_io)
      - Use openpyxl.load_workbook()
   b. GET_ACTIVE_SHEET()
   c. EXTRACT_HEADERS()
      - Read first row as column names
   d. EXTRACT_ROWS()
      - For each row after header:
        - Create dict mapping header -> cell value
        - Append to rows list
   e. CONVERT_TO_JSON(rows)
      - Return JSON string representation
   f. LOG: "Extracted {row_count} rows from Excel"

4. IF file_type == "csv":
   a. DECODE_BYTES_TO_STRING(decoded_bytes)
      - Try UTF-8, fallback to latin-1
   b. RETURN raw CSV text
   c. LOG: "Extracted CSV content, {line_count} lines"

5. RETURN extracted_content
```

### Algorithm 3: LLM Validation

```
ALGORITHM: ValidateWithLLM

INPUT:
  - original_instruction: str
  - success_criteria: str
  - extracted_content: str (JSON or text)

OUTPUT:
  - is_valid: bool
  - feedback: str

1. BUILD_VALIDATION_PROMPT()
   - Include original instruction
   - Include success criteria
   - Include extracted content (truncated if too long)
   - Ask structured questions:
     - Does it contain requested information?
     - Is data complete (correct count)?
     - Is format correct?
     - Is quality acceptable?

2. CALL_LLM(prompt)
   - Send to Gemini 2.5 Flash
   - Request JSON response format

3. PARSE_RESPONSE(llm_response)
   - Extract is_valid (boolean)
   - Extract feedback (string explanation)

4. LOG: "Validation: is_valid={is_valid}"

5. RETURN {is_valid, feedback}
```

---

## LLM Prompt Templates

### Prompt 1: Parse Instruction

```
SYSTEM: You are an assistant that extracts structured information from user requests.

USER:
Extract the following from this instruction:
"{user_instruction}"

Return JSON:
{
  "poc_emails": ["email1@example.com"],
  "request_type": "data_request|information_request|action_request",
  "request_description": "brief description of what is being requested",
  "success_criteria": "specific criteria to validate the response"
}

Rules:
- Extract all email addresses mentioned
- Infer the type of request from context
- Be specific about success criteria (e.g., "10 rows of data" not just "data")
```

### Prompt 2: Compose Email

```
SYSTEM: You are a professional email composer. Write clear, polite, and concise emails.

USER:
Compose an email to request the following:
- Recipient: {poc_email}
- Request: {request_description}
- Expected format: {expected_format}

The email should:
1. Be professional and polite
2. Clearly state what is needed
3. Specify the expected format (Excel/CSV)
4. Be concise but complete

Return JSON:
{
  "subject": "email subject line",
  "body": "full email body text"
}
```

### Prompt 3: Validate Response

```
SYSTEM: You are a validation assistant. Analyze whether a response satisfies the original request.

USER:
Original request: "{request_description}"
Success criteria: "{success_criteria}"

Received response content:
{extracted_content}

Analyze the following:
1. Does the response contain the requested information?
2. Is the data complete (correct number of items as requested)?
3. Is the format correct?
4. Is the quality acceptable (meaningful data, not placeholder)?

Return JSON:
{
  "is_valid": true|false,
  "feedback": "detailed explanation of what is correct/missing/wrong"
}

Be strict: if the request asked for 10 items and only 8 are provided, mark as invalid.
```

### Prompt 4: Compose Follow-up

```
SYSTEM: You are a professional email composer. Write polite follow-up emails requesting corrections.

USER:
Original request: "{request_description}"
Previous response issue: "{validation_feedback}"
Attempt number: {attempt_count} of 5

Compose a follow-up email that:
1. Thanks them for their response
2. Politely explains what was missing or incorrect
3. Clearly states what corrections are needed
4. Remains professional and not demanding

Return JSON:
{
  "subject": "Re: {original_subject}",
  "body": "follow-up email body text"
}
```

---

## Configuration Schema

```
Settings (Pydantic BaseSettings):

  # Mock SMTP Server Connection
  MOCK_SMTP_API_URL: str = "http://localhost:8025"
  MOCK_SMTP_HOST: str = "localhost"
  MOCK_SMTP_PORT: int = 1025

  # Agent Identity
  AGENT_EMAIL: str = "info-agent@gmail.com"

  # Webhook Server
  WEBHOOK_HOST: str = "localhost"
  WEBHOOK_PORT: int = 9000
  WEBHOOK_PATH: str = "/webhook/email-received"

  # LLM Configuration
  GEMINI_API_KEY: str  # Required, from environment variable
  GEMINI_MODEL: str = "gemini-2.5-flash"

  # Agent Behavior
  MAX_ATTEMPTS: int = 5

  # State Persistence
  SQLITE_DB_PATH: str = "./mail_agent_state.db"

  # Logging
  LOG_LEVEL: str = "INFO"

Environment Variable Prefix: MAIL_AGENT_
```

---

## Error Handling Strategy

### Error Categories

| Category | Handling |
|----------|----------|
| LLM API Error | Retry with exponential backoff (3 attempts), then fail |
| Mock SMTP API Error | Retry once, then fail with clear error message |
| Webhook Server Error | Log error, agent continues waiting |
| Attachment Parse Error | Mark validation as failed, request re-send |
| Invalid User Instruction | Return error immediately, do not start agent |
| Timeout Waiting for Reply | Not implemented (POC scope) |

### Exception Hierarchy

```
MailAgentError (base)
├── InstructionParseError      # Failed to parse user instruction
├── EmailSendError             # Failed to send email via API
├── WebhookRegistrationError   # Failed to register webhook
├── EmailFetchError            # Failed to fetch email from inbox
├── AttachmentParseError       # Failed to parse attachment content
│   ├── UnsupportedFormatError # Attachment not xlsx or csv
│   └── CorruptedFileError     # File cannot be parsed
├── LLMError                   # LLM API error
│   ├── LLMConnectionError     # Cannot reach LLM API
│   └── LLMResponseParseError  # Cannot parse LLM response
└── StateError                 # State persistence error
```

---

## Testing Strategy

### Unit Tests

| Component | Test Focus |
|-----------|------------|
| `parse_instruction` | Various instruction formats, edge cases |
| `attachment_parser` | Excel parsing, CSV parsing, error handling |
| `smtp_client` | API request formatting, error handling |
| `inbox_client` | API response parsing, error handling |
| `llm/prompts` | Prompt formatting, response parsing |

### Integration Tests

| Test | Description |
|------|-------------|
| Full flow (happy path) | Send instruction -> receive valid reply -> success |
| Validation failure flow | Send instruction -> receive invalid reply -> follow-up -> success |
| Max attempts reached | Send instruction -> 5 invalid replies -> failure |
| Multi-POC handling | Send to 2 POCs -> both succeed |
| Webhook reception | Verify webhook triggers state transition |

### Test Data

```
test_data/
├── sample_recipes_valid.xlsx      # 10 rows of valid recipes
├── sample_recipes_invalid.xlsx    # 5 rows (insufficient)
├── sample_recipes.csv             # CSV version
├── sample_empty.xlsx              # Empty file
└── sample_malformed.xlsx          # Corrupted file
```

---

## Deployment Notes

### Prerequisites

1. Mock SMTP server running on `localhost:8025` (REST) and `localhost:1025` (SMTP)
2. Google Cloud API key with Gemini API access
3. Python 3.11+

### Environment Setup

```bash
# Create and activate virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -e ".[dev]"

# Set required environment variables
export MAIL_AGENT_GEMINI_API_KEY="your-api-key"
```

### Running the Agent

```bash
# Start mock SMTP server (in separate terminal)
mock-smtp

# Run the mail agent
mail-agent "send mail to raj@gmail.com asking 10 food recipes in excel file"
```

### Simulating POC Reply

```bash
# In separate terminal, simulate POC reply with attachment
python scripts/poc_reply_simulator.py \
  --from "raj@gmail.com" \
  --to "info-agent@gmail.com" \
  --subject "Re: Request: 10 Food Recipes" \
  --body "Here are the recipes you requested." \
  --attachment ./test_data/sample_recipes_valid.xlsx
```

---

## Future Considerations (Out of Scope)

The following are explicitly out of scope for this implementation but noted for future reference:

1. **Timeout handling** - No timeout for waiting for replies
2. **Email threading** - Basic subject matching only, no In-Reply-To correlation
3. **Additional attachment types** - Only Excel and CSV supported
4. **Outbound attachments** - Agent cannot send attachments
5. **Authentication** - No authentication for webhook endpoint
6. **Rate limiting** - No rate limiting on API calls
7. **Persistent message queue** - Webhook processing is in-memory only
8. **Multi-agent coordination** - Single agent instance only