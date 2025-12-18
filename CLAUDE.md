# Info Agent - Developer Reference

**Autonomous email interaction system with LangGraph agent, A2A protocol, and real-time progress tracking.**

## System Architecture

Four-server architecture with persistent state, webhook-based resumption, and SSE streaming:

```
┌──────────────────┐         ┌───────────────────────┐
│   UI Server      │◄────────┤   Browser (User)      │
│   Port 8080      │  HTTP   │   - Submit tasks      │
│   (HTMX/Tailwind)│  SSE    │   - Monitor progress  │
└────────┬─────────┘         └───────────────────────┘
         │ JSON-RPC + SSE
         ▼
┌──────────────────────────────────────────────────────┐
│   Mail Agent A2A Server (Port 8000)                  │
│   - LangGraph execution with checkpointing           │
│   - A2A protocol (JSON-RPC 2.0)                      │
│   - Real-time progress events (SSE)                  │
│   - Task management + persistence (SQLite)           │
└────┬──────────────────────────────────┬──────────────┘
     │ REST API                         │ Webhook
     ▼                                  ▼
┌──────────────┐               ┌─────────────────────┐
│  Mock SMTP   │───────────────►  Webhook Server     │
│  1025 + 8025 │   HTTP POST   │  Port 9000          │
│  SMTP + API  │               │  - Resume tasks     │
└──────────────┘               └─────────────────────┘
```

**Tech Stack:** aiosmtpd, FastAPI, LangGraph, HTMX, Tailwind CSS, SQLite, Gemini/Azure/OpenRouter, SSE

## Quick Start

```bash
# Setup
python -m venv venv && source venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env  # Configure LLM API key

# Run servers
uv run mock-smtp           # Mock SMTP (1025, 8025)
uv run mail-agent a2a      # A2A + Webhook (8000, 9000)
uv run ui-server           # UI (8080)

# CLI
uv run mail-agent run "send mail to user@example.com asking 10 recipes in csv"

# Test
pytest --cov=src --cov-report=html
```

---

## Feature → File Quick Reference

### Core Agent Flow (LangGraph)
| Feature | Files |
|---------|-------|
| **Graph Definition** | `src/mail_agent/agent/graph.py` |
| **State Management** | `src/mail_agent/agent/state.py` |
| **Parse Instruction** | `src/mail_agent/agent/nodes/parse_instruction.py` |
| **Multi-POC Iteration** | `src/mail_agent/agent/nodes/select_next_poc.py`, `check_more_pocs.py` |
| **Compose Email** | `src/mail_agent/agent/nodes/compose_email.py` |
| **Send Email** | `src/mail_agent/agent/nodes/send_email.py` |
| **Wait for Reply** | `src/mail_agent/agent/nodes/wait_for_reply.py` (interrupt) |
| **Fetch Email** | `src/mail_agent/agent/nodes/fetch_email.py` |
| **Extract Content** | `src/mail_agent/agent/nodes/extract_content.py` (CSV/Excel) |
| **Validate Response** | `src/mail_agent/agent/nodes/validate_response.py` (LLM) |
| **Decide Next** | `src/mail_agent/agent/nodes/decide_next.py` |
| **Handle Redirect** | `src/mail_agent/agent/nodes/handle_redirect.py` |
| **Cross-POC Validation** | `src/mail_agent/agent/nodes/validate_cross_poc.py` (LLM) |
| **Targeted Follow-up** | `src/mail_agent/agent/nodes/prepare_targeted_followup.py` |
| **Success Acknowledgment** | `src/mail_agent/agent/nodes/compose_success_all.py`, `send_success_all.py` |
| **Legacy Success Reply** | `src/mail_agent/agent/nodes/compose_success_reply.py`, `send_success_reply.py` |
| **Parallel: Compose All** | `src/mail_agent/agent/nodes/compose_all_emails.py` |
| **Parallel: Send All** | `src/mail_agent/agent/nodes/send_all_emails.py` |
| **Parallel: Wait All** | `src/mail_agent/agent/nodes/wait_for_all_replies.py` (single interrupt) |
| **Parallel: Process All** | `src/mail_agent/agent/nodes/process_all_replies.py` |
| **Parallel: Followup** | `src/mail_agent/agent/nodes/handle_parallel_followup.py` |

### A2A Protocol & Task Management
| Feature | Files |
|---------|-------|
| **A2A Server** | `src/mail_agent/a2a/server.py` |
| **Executor** | `src/mail_agent/a2a/executor.py` (wraps LangGraph) |
| **Agent Card** | `src/mail_agent/a2a/agent_card.py` (RFC 8615) |
| **Task Manager** | `src/mail_agent/task_manager/manager.py` |
| **Task Routes** | `src/mail_agent/a2a/routes/tasks.py` |
| **Progress Store** | `src/mail_agent/a2a/progress_store.py` (SSE events) |
| **Progress Routes** | `src/mail_agent/a2a/routes/progress.py` (SSE endpoint) |

### Persistence Layer
| Feature | Files |
|---------|-------|
| **Database Init** | `src/mail_agent/persistence/database.py` |
| **Checkpointer** | `src/mail_agent/persistence/checkpointer.py` (LangGraph) |
| **Task Store** | `src/mail_agent/persistence/task_store.py` (CRUD) |

### Webhook System
| Feature | Files |
|---------|-------|
| **Webhook Server** | `src/mail_agent/webhook/server.py` (FastAPI) |
| **Registry** | `src/mock_smtp/webhooks/registry.py` |
| **Dispatcher** | `src/mock_smtp/webhooks/dispatcher.py` (async + retry) |

### Mock SMTP Server
| Feature | Files |
|---------|-------|
| **SMTP Handler** | `src/mock_smtp/smtp/handler.py`, `server.py` |
| **REST API** | `src/mock_smtp/api/` (send, inbox, email, webhook routes) |
| **Storage** | `src/mock_smtp/store/inbox_store.py`, `models.py` |

### UI Server
| Feature | Files |
|---------|-------|
| **Main App** | `src/ui/main.py` |
| **Routes** | `src/ui/routes/` (pages, dashboard, inbox, send_request, sse) |
| **A2A Client** | `src/ui/services/a2a_client.py` |
| **SSE Client** | `src/ui/services/sse_client.py` |
| **SMTP Clients** | `src/ui/services/smtp_client.py`, `smtp_sender.py` |
| **Templates** | `src/ui/templates/` (Jinja2 + HTMX) |

### LLM Integration
| Feature | Files |
|---------|-------|
| **Client Factory** | `src/mail_agent/llm/client.py` (Gemini/Azure/OpenRouter) |
| **Prompts** | `src/mail_agent/llm/prompts.py` |

### Tools & Utilities
| Feature | Files |
|---------|-------|
| **Attachment Parser** | `src/mail_agent/tools/attachment_parser.py` |
| **SMTP Clients** | `src/mail_agent/tools/smtp_client.py`, `inbox_client.py`, `smtp_sender.py` |
| **Config** | `src/*/config.py` (each module) |

---

## Mail Agent Module (Detailed)

### 1. LangGraph State Machine

**File:** `src/mail_agent/agent/graph.py`

**Flow (Multi-POC Support):**
```
START → parse_instruction → select_next_poc
      → compose_email → send_email → wait_for_reply
      → fetch_email → extract_content → validate_response
      → [handle_success | handle_failure | prepare_followup | handle_redirect]
      → check_more_pocs
      → [select_next_poc (if more pending) | validate_cross_poc (if all complete)]
      → [compose_success_all | prepare_targeted_followup]
      → END (or loop back for cross-POC follow-up)

Multi-POC Processing:
  1. parse_instruction: Parse ALL POCs from user instruction
  2. select_next_poc: Pick next pending POC (loop entry point)
  3. Process single POC through email flow
  4. handle_success/failure: Mark POC conversation as complete
  5. check_more_pocs: Check if more POCs need processing
  6. Loop back to select_next_poc OR proceed to cross-POC validation

Cross-POC Validation:
  After all individual POCs complete, validate_cross_poc checks:
  - Referential integrity between data from different POCs
  - Example: employee.dept_id must exist in department data from another POC

Targeted Follow-ups:
  If cross-POC validation fails, prepare_targeted_followup:
  - Identifies which specific POC(s) need to provide missing data
  - Resets those POCs for re-processing
  - Does NOT bother POCs whose data is already complete

Success Flow (All POCs):
  validate_cross_poc → compose_success_all → send_success_all → END

Retry Flow (Individual POC):
  validate_response → prepare_followup → compose_email (same POC, attempt++)

Redirect Flow:
  validate_response → handle_redirect → check_more_pocs
```

**Key Functions:**
- `create_mail_agent_graph()` - Builds graph with nodes and edges
- `compile_mail_agent_graph(checkpointer)` - Compiles with SQLite checkpointer
- `route_after_parse()` - Conditional routing after instruction parsing
- `route_after_validation()` - Conditional routing based on validation result

**Interrupt Point:** `wait_for_reply` node triggers LangGraph interrupt, suspending task until webhook arrives.

---

### 1b. Parallel Processing Mode (Multi-POC)

**Enabled by:** `MAIL_AGENT_PARALLEL_PROCESSING_ENABLED=true` (default)

**Flow (Parallel Mode):**
```
START → parse_instruction
      → compose_all_emails (concurrent LLM calls for all POCs)
      → send_all_emails (concurrent SMTP sends)
      → wait_for_all_replies (SINGLE interrupt, waits for ALL POCs)
      → process_all_replies (concurrent fetch/extract/validate)
      → [all_valid: validate_cross_poc | some_invalid: handle_parallel_followup]
      → [success: compose_success_all → send_success_all → END]
      → [followup: loop back to compose_all_emails with _followup_pocs]

Parallel vs Sequential Processing:
┌─────────────────────────────────────────────────────────────────────┐
│ Sequential Mode (legacy):                                            │
│   POC1: send → wait → process → POC2: send → wait → process → ...   │
│   Total time: O(T1 + T2 + ... + Tn)                                 │
│                                                                      │
│ Parallel Mode (new):                                                 │
│   ALL POCs: send_all → wait_all → process_all                       │
│   Total time: O(max(T1, T2, ..., Tn))                               │
└─────────────────────────────────────────────────────────────────────┘

Webhook Collection Pattern:
  1. wait_for_all_replies triggers SINGLE interrupt with all POC emails
  2. TaskManager.suspend_task_multi_poc() registers all POCs → task mapping
  3. Each webhook arrival is collected (not resuming immediately)
  4. Only when ALL POCs respond → task resumes with all webhook data
  5. process_all_replies fetches and validates all replies concurrently

Database Tables (Multi-POC):
  - suspended_tasks_multi: Task with multiple pending POCs
  - poc_task_mapping: POC email → task_id lookup
  - received_webhooks stored in suspended_tasks_multi.received_webhooks (JSON)
```

**Key Parallel Functions:**
- `create_mail_agent_graph_parallel()` - Builds parallel graph
- `compile_mail_agent_graph_parallel(checkpointer)` - Compiles parallel graph
- `route_after_process_all_replies()` - Routes based on validation results
- `route_after_parallel_followup()` - Routes to compose or cross-validation

**Parallel State Fields:**
```python
# Parallel Processing Fields in AgentState
_parallel_mode: Optional[bool]                    # True in parallel flow
_waiting_pocs: Optional[list[str]]                # POCs awaiting replies
_received_webhooks: Optional[dict[str, dict]]     # Collected webhook data
_composed_emails: Optional[list[dict]]            # Batch of composed emails
_poc_processing_results: Optional[dict[str, dict]] # Per-POC validation results
_all_individual_valid: Optional[bool]             # All POCs valid?
_followup_pocs: Optional[list[str]]               # POCs needing retry
```

**TaskManager Multi-POC Methods:**
- `suspend_task_multi_poc(task_id, poc_emails, thread_id)` - Suspend for multiple POCs
- `_handle_webhook_multi_poc(payload)` - Collect webhook, check if all received
- `_resume_task_multi_poc(task_id, thread_id, webhooks)` - Resume with all data

---

### 2. Agent State

**File:** `src/mail_agent/agent/state.py`

**State Structure:**
```python
class AgentState(TypedDict):
    # Input
    user_instruction: str                      # Original request

    # Parsed data
    parsed_request: Optional[dict]             # POC emails + requirements

    # Conversation tracking (per POC)
    conversations: dict[str, dict]             # {poc_email: ConversationState}

    # Current context
    current_node: str                          # Current graph node
    current_poc: Optional[str]                 # Active POC email
    task_id: Optional[str]                     # A2A task ID

    # Webhook & progress
    webhook_id: Optional[str]                  # Webhook registration ID
    pending_webhooks: list[str]                # Email IDs awaiting processing
    progress_messages: list[str]               # Progress log

    # Results
    final_summary: Optional[str]               # Final result text
    error: Optional[str]                       # Error message

    # Temporary data (node-to-node passing)
    _composed_subject: Optional[str]           # Composed email subject
    _composed_body: Optional[str]              # Composed email body
    _fetched_email_id: Optional[str]           # Fetched email UUID
    _fetched_attachments: Optional[list]       # Fetched attachments
    _extracted_content: Optional[str]          # Parsed CSV/Excel content
    _validation_is_valid: Optional[bool]       # Validation result
    _validation_feedback: Optional[str]        # Validation feedback
    _redirect_detected: Optional[bool]         # Redirect flag
    _redirect_email: Optional[str]             # Redirect target
```

**ConversationState (per POC):**
```python
@dataclass
class ConversationState:
    poc_email: str
    status: Literal["pending", "composing", "sending", "waiting",
                    "fetching", "extracting", "validating",
                    "success", "failed", "redirected"]
    attempt_count: int                         # Retry counter (max 5)
    sent_emails: list[SentEmail]               # Audit trail
    received_emails: list[ReceivedEmail]       # POC responses
    validation_results: list[ValidationResult] # LLM validations
    final_result: Optional[str]                # "success" | "failed_max_attempts" | "redirected"
    error_message: Optional[str]
    redirected_from: Optional[RedirectInfo]    # If created from redirect
    redirected_to: Optional[str]               # If redirected elsewhere
```

**Helper Functions:**
- `create_initial_state(instruction)` - Initialize state from user input
- `get_conversation(state, poc_email)` - Retrieve ConversationState for POC
- `update_conversation(state, poc_email, conversation)` - Immutable state update
- `get_parsed_request(state)` - Get ParsedRequest object
- `all_conversations_complete(state)` - Check if all POCs reached terminal state

---

### 3. A2A Executor

**File:** `src/mail_agent/a2a/executor.py`

**Purpose:** Bridges A2A protocol (Google Agent-to-Agent) to LangGraph execution.

**Class:** `MailAgentA2AExecutor(AgentExecutor)`

**Key Methods:**

**`execute(context, event_queue)`**
- Extracts instruction from A2A message
- Creates initial state with task_id
- Streams graph execution with SSE events
- Detects interrupts and suspends tasks
- Emits progress events to ProgressStore
- Returns final result or suspends

**`_run_agent_streaming(initial_state, task_id, event_queue)`**
- Configures thread_id (same as task_id for checkpointing)
- Emits initial SSE event with task_id
- Iterates `graph.astream()` with interrupt detection
- On interrupt: suspends task via TaskManager, emits suspended event
- On completion: emits completed/failed event
- Progress events → both event_queue (A2A) and progress_store (UI)

**`_is_interrupt_event(event)` & `_extract_interrupt_data(event)`**
- Detects LangGraph interrupt events (`__interrupt__` key)
- Parses interrupt payload (handles multiple LangGraph formats)
- Extracts POC email, task_id, and resume data

**`_emit_sse_event(event_queue, sse_event)`**
- Converts SSEEvent to A2A Message
- Emits to A2A event queue
- Emits to ProgressStore for UI streaming

**Event Flow:**
```
User submits → A2A execute → Graph streams
            → Each node emits progress event
            → On interrupt: suspend + emit "suspended"
            → On complete: emit "completed" or "failed"
```

---

### 4. Task Manager

**File:** `src/mail_agent/task_manager/manager.py`

**Purpose:** Manages task lifecycle for non-blocking A2A execution.

**Responsibilities:**
1. **Suspension:** Register POC→task mappings, persist to database
2. **Resumption:** Route webhooks to correct task, resume from checkpoint
3. **Expiration:** Clean up expired tasks (default 3600s timeout)
4. **Status:** Query task state (suspended/completed/failed)

**Key Methods:**

**`suspend_task(task_id, poc_email, thread_id, interrupt_data)`**
- Registers POC→task mapping in memory (`_poc_to_task`)
- Persists to database with expiration timestamp
- Called by executor when interrupt detected

**`handle_webhook(payload: WebhookPayload)`**
- Looks up task by sender email (`payload.from_address`)
- Checks expiration
- Removes from suspended state
- Triggers `_resume_task()` in background

**`_resume_task(task_id, thread_id, payload)`**
- Creates LangGraph `Command(resume=resume_data)`
- Streams graph execution from checkpoint
- Detects re-interrupts (retry scenario)
- Stores final result in database

**`get_task_status(task_id)`**
- Checks suspended_tasks → results tables
- Returns TaskStatus with state, progress, result/error

**`_cleanup_expired_tasks()`**
- Background loop (default 60s interval)
- Queries database for expired tasks
- Marks as failed, removes from memory

**Data Flow:**
```
Interrupt → suspend_task() → DB + memory
Email arrives → Webhook → handle_webhook() → resume_task()
                                           → Graph continues
                                           → Store result
```

**Thread Safety:** Uses `asyncio.Lock` for `_poc_to_task` access.

---

### 5. Progress Store (SSE Streaming)

**File:** `src/mail_agent/a2a/progress_store.py`

**Purpose:** Real-time progress event storage and SSE streaming to UI.

**Architecture:**
```
ProgressStore
 └─ {task_id: TaskProgressQueue}
     ├─ events: list[ProgressEvent]        # Event history
     ├─ subscribers: list[asyncio.Queue]   # Active SSE connections
     └─ _event_counter: int                # Sequential event ID
```

**Event Types:**
- `progress` - Node execution (state=WORKING)
- `complete` - Task succeeded (state=COMPLETED)
- `error` - Task failed (state=FAILED)
- `suspended` - Waiting for email (state=SUSPENDED)

**Key Features:**
1. **Reconnection Support:** Last-Event-Id header for SSE reconnection
2. **Historical Replay:** New subscribers get missed events
3. **Auto-cleanup:** Removes completed tasks after 300s
4. **Keepalive:** 15s timeout for SSE connection keepalive

**Methods:**

**`add_event(event: ProgressEvent)`**
- Assigns sequential event_id
- Appends to task's event history
- Notifies all subscribers
- Schedules cleanup if terminal state

**`subscribe(task_id, last_event_id=None)`**
- Replays events after last_event_id
- Returns async generator of ProgressEvent
- Yields None on timeout (for keepalive)
- Auto-removes subscriber on disconnect

**SSE Format:**
```
id: 42
event: progress
data: {"task_id":"abc","state":"working","node":"compose_email","message":"..."}

```

**Usage:**
```python
# Executor emits events
progress_store.add_event(ProgressEvent(
    task_id=task_id,
    state=TaskState.WORKING,
    node="send_email",
    message="Sending email to poc@example.com",
))

# UI streams events
async for event in progress_store.subscribe(task_id):
    yield event.to_sse_format()
```

---

### 6. Persistence Layer

**Checkpointer:** `src/mail_agent/persistence/checkpointer.py`
- LangGraph `AsyncSqliteSaver` wrapper
- Stores graph state after each node
- Enables resumption from interrupt points
- Async context manager for lifecycle

**Database Manager:** `src/mail_agent/persistence/database.py`
- Initializes SQLite tables (tasks, suspended_tasks, task_results, checkpoints)
- Connection pooling with aiosqlite
- Schema migrations

**Task Store:** `src/mail_agent/persistence/task_store.py`
- CRUD operations for tasks
- `suspend_task()` - Create suspended task record
- `get_suspended_task()` - Query by task_id
- `save_result()` - Store final result
- `get_expired_tasks()` - Cleanup query

**Tables:**
```sql
CREATE TABLE suspended_tasks (
    task_id TEXT PRIMARY KEY,
    poc_email TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    interrupt_data TEXT
);

CREATE TABLE task_results (
    task_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,  -- "completed" | "failed"
    completed_at TEXT NOT NULL,
    result TEXT,           -- JSON
    error TEXT
);
```

---

### 7. Webhook System

**Webhook Server:** `src/mail_agent/webhook/server.py`
- FastAPI app on port 9000
- `POST /webhook/email-received` endpoint
- Receives webhook from Mock SMTP
- Routes to TaskManager.handle_webhook()

**Payload:**
```python
class WebhookPayload:
    inbox: str              # Recipient inbox
    email_id: str           # Email UUID
    from_address: str       # Sender (POC email)
    subject: str
    timestamp: str
    metadata: dict          # Additional data
```

**Webhook Dispatcher:** `src/mock_smtp/webhooks/dispatcher.py`
- Async HTTP POST with exponential backoff
- Max 3 retries (configurable)
- 10s timeout per request
- Fire-and-forget (errors logged, no failure on webhook error)

**Webhook Registration:**
- Mail agent registers webhook URL on startup
- Mock SMTP stores in WebhookRegistry
- On email arrival: dispatcher fires webhook
- Mail agent receives webhook → resumes task

---

### 8. Node Implementations

**parse_instruction.py**
- Uses LLM to extract POC emails, request type, success criteria, expected format
- Creates ConversationState for each POC
- Sets `parsed_request` in state

**compose_email.py**
- Uses LLM with prompt template to generate email subject + body
- Persona: professional, friendly agent
- Stores `_composed_subject`, `_composed_body` in state

**send_email.py**
- Sends via SMTP client (REST API or SMTP protocol)
- Increments `attempt_count`
- Records SentEmail in conversation

**wait_for_reply.py**
- **Interrupt Node:** Calls `interrupt()` to suspend graph
- Registers webhook with Mock SMTP
- Stores interrupt data (poc_email, task_id, timestamp)
- Graph pauses here until webhook arrives

**fetch_email.py**
- Queries Mock SMTP API for new emails from POC
- Filters by sender address
- Stores email_id, attachments, body in state

**extract_content.py**
- Parses CSV/Excel attachments using openpyxl/csv
- Extracts headers, row count, content
- Stores `_extracted_content` (JSON string)

**validate_response.py**
- Uses LLM to validate extracted content against success criteria
- Returns is_valid, feedback, missing_items
- Stores validation result in conversation
- Detects redirects ("email xyz@example.com instead")

**decide_next.py**
- Checks validation result
- If valid → "success"
- If max attempts (5) → "failure"
- If redirect detected → "redirect"
- Else → "followup" (retry)

**handle_redirect.py**
- Creates new ConversationState for redirected POC
- Marks original POC as "redirected"
- Stores redirect info

**compose_success_reply.py**
- Generates thank-you email summarizing received data
- Uses LLM with success acknowledgment prompt

**send_success_reply.py**
- Sends acknowledgment via SMTP
- Does NOT increment attempt_count

---

## Integration Points

### UI Server ↔ A2A Server

**Protocol:** JSON-RPC 2.0 + SSE
**Client:** `src/ui/services/a2a_client.py`

**Endpoints:**
- `POST /jsonrpc` - Execute task (`tasks.execute` method)
- `GET /api/tasks` - List all tasks
- `GET /api/tasks/{task_id}` - Get task status
- `GET /api/tasks/{task_id}/progress` - SSE stream

**Flow:**
```
User submits form → UI calls A2A execute → A2A returns task_id
                 → UI subscribes to SSE stream
                 → Displays real-time progress
```

---

### UI Server ↔ Mock SMTP

**Protocol:** REST API + Direct SMTP
**Clients:** `src/ui/services/smtp_client.py`, `smtp_sender.py`

**Endpoints:**
- `GET /api/inboxes` - List inboxes
- `GET /api/inboxes/{inbox}/emails` - List emails
- `GET /api/emails/{email_id}` - Email detail
- `POST /api/send` - Send email (REST)
- SMTP port 1025 - Send email (protocol)

**Flow:**
```
UI Inbox page → Fetch emails via API → Display list
             → Click email → Fetch detail → Show content + attachments
             → Reply → Send via SMTP protocol
```

---

### Mail Agent ↔ Mock SMTP

**Protocol:** REST API
**Clients:** `src/mail_agent/tools/smtp_client.py`, `inbox_client.py`, `smtp_sender.py`

**Operations:**
1. **Send Email:** `POST /api/send` or SMTP protocol
2. **Register Webhook:** `POST /api/webhooks`
3. **Fetch Emails:** `GET /api/inboxes/{inbox}/emails`
4. **Unregister Webhook:** `DELETE /api/webhooks/{webhook_id}`

**Flow:**
```
send_email node → POST /api/send → Email stored
wait_for_reply → POST /api/webhooks → Register callback
fetch_email → GET /api/inboxes/.../emails → Retrieve response
```

---

### Mock SMTP → Webhook Server

**Protocol:** HTTP POST (async)
**Dispatcher:** `src/mock_smtp/webhooks/dispatcher.py`
**Receiver:** `src/mail_agent/webhook/server.py`

**Payload:**
```json
{
  "inbox": "info-agent@gmail.com",
  "email_id": "uuid",
  "from_address": "poc@example.com",
  "subject": "Re: Request",
  "timestamp": "2025-12-17T10:00:00Z",
  "metadata": {}
}
```

**Flow:**
```
Email arrives at Mock SMTP → Dispatcher fires webhook (async, retry)
                          → Webhook server receives
                          → TaskManager.handle_webhook()
                          → Resume suspended task
```

---

## Environment Configuration

### Mail Agent (MAIL_AGENT_*)
```bash
# Mock SMTP Connection
MAIL_AGENT_MOCK_SMTP_API_URL=http://localhost:8025
MAIL_AGENT_MOCK_SMTP_HOST=localhost
MAIL_AGENT_MOCK_SMTP_PORT=1025
MAIL_AGENT_AGENT_EMAIL=info-agent@gmail.com

# Webhook Server
MAIL_AGENT_WEBHOOK_HOST=localhost
MAIL_AGENT_WEBHOOK_PORT=9000

# LLM
MAIL_AGENT_LLM_PROVIDER=gemini  # or azure-openai, openrouter
MAIL_AGENT_GEMINI_API_KEY=your-key
MAIL_AGENT_GEMINI_MODEL=gemini-2.5-flash
MAIL_AGENT_LLM_TEMPERATURE=0.0
MAIL_AGENT_LLM_MAX_TOKENS=4096

# Agent Behavior
MAIL_AGENT_MAX_ATTEMPTS=5
MAIL_AGENT_SQLITE_DB_PATH=./mail_agent_state.db
MAIL_AGENT_PARALLEL_PROCESSING_ENABLED=true  # Enable parallel POC processing (default: true)

# A2A Server
MAIL_AGENT_A2A_HOST=0.0.0.0
MAIL_AGENT_A2A_PORT=8000
MAIL_AGENT_A2A_AGENT_NAME=Mail Agent
MAIL_AGENT_A2A_AGENT_VERSION=1.0.0

# Logging
MAIL_AGENT_LOG_LEVEL=INFO
```

### UI Server (UI_*)
```bash
UI_HOST=0.0.0.0
UI_PORT=8080
UI_A2A_SERVER_URL=http://localhost:8000
UI_MOCK_SMTP_API_URL=http://localhost:8025
UI_DEFAULT_INBOX_EMAIL=info-agent@gmail.com
UI_SMTP_HOST=localhost
UI_SMTP_PORT=1025
UI_LOG_LEVEL=INFO
```

### Mock SMTP (MOCK_SMTP_*)
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

---

## Common Development Tasks

### Add a LangGraph Node
1. Create `src/mail_agent/agent/nodes/my_node.py`
2. Implement `async def my_node(state: AgentState) -> dict[str, Any]`
3. Import in `src/mail_agent/agent/nodes/__init__.py`
4. Add to graph in `src/mail_agent/agent/graph.py`:
   ```python
   graph.add_node("my_node", my_node)
   graph.add_edge("previous_node", "my_node")
   ```
5. Test: `tests/test_mail_agent/test_nodes/test_my_node.py`

### Modify Agent State
1. Update `AgentState` TypedDict in `src/mail_agent/agent/state.py`
2. Add field with appropriate type annotation
3. If persistent, update ConversationState dataclass
4. Update `to_dict()` and `from_dict()` serialization methods
5. Test state serialization

### Add SSE Event Type
1. Update `ProgressEvent` model in `src/mail_agent/a2a/progress_store.py`
2. Emit event in `src/mail_agent/a2a/executor.py`
3. Handle in `src/ui/services/sse_client.py`
4. Display in `src/ui/templates/partials/progress_log.html`

### Debug Agent Flow
```bash
# Enable debug logging
MAIL_AGENT_LOG_LEVEL=DEBUG

# Check database
sqlite3 mail_agent_state.db
> SELECT * FROM suspended_tasks;
> SELECT * FROM task_results;

# Inspect checkpoints
> SELECT * FROM checkpoints WHERE thread_id = 'task-id';
```

### Troubleshooting

**Mock SMTP not responding:**
```bash
curl http://localhost:8025/api/health
lsof -i :1025  # Check if port in use
```

**Webhook not firing:**
```bash
curl http://localhost:8025/api/webhooks  # Verify registration
curl http://localhost:9000/health        # Check webhook server
```

**SSE not streaming:**
```bash
curl -N http://localhost:8000/api/tasks/{task_id}/progress
# Check browser console for SSE errors
```

**Task stuck in suspended:**
```bash
# Check expiration
sqlite3 mail_agent_state.db "SELECT * FROM suspended_tasks;"
# Manually resume (simulate webhook)
curl -X POST http://localhost:9000/webhook/email-received \
  -H "Content-Type: application/json" \
  -d '{"inbox":"info-agent@gmail.com","email_id":"...","from_address":"poc@example.com"}'
```

---

## Directory Structure

```
src/
├── mail_agent/
│   ├── agent/
│   │   ├── graph.py                    # LangGraph definition
│   │   ├── state.py                    # State schema
│   │   └── nodes/                      # All graph nodes
│   │       ├── parse_instruction.py
│   │       ├── compose_email.py
│   │       ├── send_email.py
│   │       ├── wait_for_reply.py       # Interrupt point
│   │       ├── fetch_email.py
│   │       ├── extract_content.py
│   │       ├── validate_response.py
│   │       ├── decide_next.py
│   │       ├── handle_redirect.py
│   │       ├── compose_success_reply.py
│   │       ├── send_success_reply.py
│   │       ├── compose_all_emails.py    # Parallel mode
│   │       ├── send_all_emails.py       # Parallel mode
│   │       ├── wait_for_all_replies.py  # Parallel mode
│   │       ├── process_all_replies.py   # Parallel mode
│   │       └── handle_parallel_followup.py
│   ├── a2a/
│   │   ├── server.py                   # A2A server setup
│   │   ├── executor.py                 # LangGraph wrapper
│   │   ├── agent_card.py               # Agent discovery
│   │   ├── progress_store.py           # SSE event storage
│   │   └── routes/
│   │       ├── tasks.py                # Task list/status API
│   │       └── progress.py             # SSE streaming endpoint
│   ├── persistence/
│   │   ├── database.py                 # DB initialization
│   │   ├── checkpointer.py             # LangGraph checkpointer
│   │   └── task_store.py               # Task CRUD
│   ├── task_manager/
│   │   ├── manager.py                  # Task lifecycle
│   │   └── models.py                   # Task models
│   ├── webhook/
│   │   └── server.py                   # Webhook receiver
│   ├── llm/
│   │   ├── client.py                   # LLM client factory
│   │   └── prompts.py                  # Prompt templates
│   ├── tools/
│   │   ├── smtp_client.py              # SMTP API client
│   │   ├── inbox_client.py             # Inbox API client
│   │   ├── smtp_sender.py              # SMTP protocol sender
│   │   └── attachment_parser.py        # CSV/Excel parser
│   ├── config.py                       # Settings
│   └── main.py                         # CLI entry
├── mock_smtp/
│   ├── smtp/
│   │   ├── server.py                   # SMTP protocol server
│   │   └── handler.py                  # Email handler
│   ├── api/
│   │   ├── router.py                   # Main API router
│   │   ├── send_routes.py              # Send email
│   │   ├── inbox_routes.py             # List inboxes
│   │   ├── email_routes.py             # Get email details
│   │   └── webhook_routes.py           # Webhook CRUD
│   ├── store/
│   │   ├── inbox_store.py              # Thread-safe email storage
│   │   └── models.py                   # Email/Attachment models
│   ├── webhooks/
│   │   ├── registry.py                 # Webhook registration
│   │   └── dispatcher.py               # HTTP POST with retry
│   ├── config.py                       # Settings
│   └── main.py                         # CLI entry
└── ui/
    ├── routes/
    │   ├── pages.py                    # Main pages
    │   ├── send_request.py             # Task submission form
    │   ├── inbox.py                    # Inbox viewer
    │   ├── dashboard.py                # Task dashboard
    │   └── sse.py                      # SSE proxy
    ├── services/
    │   ├── a2a_client.py               # A2A client
    │   ├── sse_client.py               # SSE client
    │   ├── smtp_client.py              # SMTP API client
    │   └── smtp_sender.py              # SMTP protocol sender
    ├── templates/                      # Jinja2 + HTMX
    ├── static/                         # CSS, JS
    ├── config.py                       # Settings
    └── main.py                         # FastAPI app

tests/
├── test_mail_agent/
│   ├── test_a2a/                       # A2A protocol tests
│   ├── test_nodes/                     # Node unit tests
│   ├── test_persistence/               # Database tests
│   └── test_task_manager/              # Task manager tests
├── test_ui/                            # UI server tests
└── test_*.py                           # Mock SMTP tests

scripts/
├── a2a_client.py                       # A2A test client
├── poc_reply_simulator.py              # Simulate POC replies
└── generate_test_data.py               # Generate test CSVs
```

---

## Key Design Decisions

**Why LangGraph?**
- State machine modeling with checkpointing
- Built-in interrupt support for wait_for_reply
- State persistence for resumable workflows

**Why A2A Protocol?**
- Standardized agent communication
- JSON-RPC 2.0 for interoperability
- Non-blocking task execution model

**Why SSE for Progress?**
- Real-time updates without WebSocket complexity
- Browser-native EventSource API
- Automatic reconnection with Last-Event-Id

**Why Webhook Fire-and-Forget?**
- Async dispatch, no blocking
- Retry logic for transient failures
- Email arrival shouldn't block SMTP handler

**Why In-Memory Mock SMTP?**
- Testing tool, not production server
- Fast, simple, clean state on restart
- No database overhead

---

## Testing Checklist

Before committing:
- [ ] `pytest` passes
- [ ] `pytest --cov=src --cov-report=html` shows coverage
- [ ] No files exceed 800 lines
- [ ] Logging added for new operations
- [ ] `.env.example` updated
- [ ] README.md updated (if user-facing change)

---

## Fail-Fast Philosophy

**Mail Agent:**
- No LLM API key → Exception on startup
- Invalid config → ValueError on startup
- Max attempts reached → Mark task as failed
- Task expired → Mark as failed, clean up
- Webhook registration fails → Log warning, continue

**Mock SMTP:**
- Invalid config → ValueError on startup
- Attachment too large → SMTP 552 error
- Inbox full → FIFO eviction (oldest removed)

**UI Server:**
- A2A server unreachable → Display connection error
- SSE connection drops → Auto-reconnect
