# Mail Agent A2A Integration - Architecture Document

## Overview

This document describes the architecture for exposing the existing LangGraph Mail Agent as a web service compliant with the **Google A2A (Agent-to-Agent) Protocol**. The integration enables external agents and clients to interact with the Mail Agent via standardized JSON-RPC 2.0 over HTTP.

---

## Table of Contents

1. [Objectives](#objectives)
2. [Technology Stack](#technology-stack)
3. [Port Allocation](#port-allocation)
4. [Component Architecture](#component-architecture)
5. [Directory Structure](#directory-structure)
6. [Data Flow](#data-flow)
7. [Webhook Routing Architecture](#webhook-routing-architecture)
8. [A2A Protocol Mapping](#a2a-protocol-mapping)
9. [Configuration](#configuration)
10. [API Contracts](#api-contracts)
11. [Algorithms](#algorithms)
12. [Files to Create/Modify](#files-to-createmodify)
13. [Error Handling](#error-handling)
14. [Constraints and Limitations](#constraints-and-limitations)

---

## Objectives

1. **Expose Mail Agent via A2A Protocol**: Enable external agents to send tasks to the Mail Agent using Google's A2A protocol.

2. **Support Concurrent Requests**: Multiple A2A clients can interact with the agent simultaneously without interference.

3. **Maintain Backward Compatibility**: Existing CLI interface (`mail-agent run`) continues to work unchanged.

4. **Minimal Refactoring**: Wrap existing LangGraph agent without modifying core graph logic.

---

## Technology Stack

| Layer | Technology | Version | Purpose |
|-------|------------|---------|---------|
| **Protocol** | A2A SDK | `a2a-sdk[http-server]` | Google Agent-to-Agent protocol implementation |
| **HTTP Server** | Starlette + Uvicorn | Latest | ASGI server for A2A endpoints |
| **Agent Framework** | LangGraph | `>=0.2.0` | State machine orchestration |
| **LLM Integration** | LangChain | Latest | LLM client abstraction |
| **LLM Providers** | Google Gemini / Azure OpenAI | - | Language model backends |
| **Webhook Server** | FastAPI + Uvicorn | Latest | Receives email notification callbacks |
| **HTTP Client** | httpx | Latest | Async HTTP for Mock SMTP API |
| **Task Store** | InMemoryTaskStore (A2A SDK) | - | A2A task lifecycle management |

### Dependencies to Add

```toml
# pyproject.toml
dependencies = [
    # ... existing dependencies
    "a2a-sdk[http-server]>=0.1.0",
]
```

---

## Port Allocation

```
┌─────────────────────────────────────────────────────────────────────┐
│                         PORT ALLOCATION                             │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│  MOCK SMTP SERVER (External Dependency)                             │
├─────────────────────────────────────────────────────────────────────┤
│  Port 1025  │  SMTP Protocol  │  Receives POC email replies         │
│  Port 8025  │  REST API       │  Send emails, manage inboxes        │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│  MAIL AGENT                                                         │
├─────────────────────────────────────────────────────────────────────┤
│  Port 8000  │  A2A Server     │  JSON-RPC 2.0 endpoint (NEW)        │
│  Port 9000  │  Webhook Server │  Email notification callbacks       │
└─────────────────────────────────────────────────────────────────────┘
```

| Server | Port | Protocol | Config Variable |
|--------|------|----------|-----------------|
| Mock SMTP - SMTP | `1025` | SMTP | `MOCK_SMTP_SMTP_PORT` |
| Mock SMTP - REST | `8025` | HTTP | `MOCK_SMTP_API_PORT` |
| Mail Agent - A2A | `8000` | HTTP (JSON-RPC) | `MAIL_AGENT_A2A_PORT` |
| Mail Agent - Webhook | `9000` | HTTP | `MAIL_AGENT_WEBHOOK_PORT` |

---

## Component Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         A2A CLIENT                                  │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ HTTP POST :8000/jsonrpc
                                    │ (JSON-RPC 2.0)
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    A2A SERVER (:8000)                               │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │  A2AStarletteApplication                                      │  │
│  │  ├── GET /.well-known/agent.json (AgentCard)                  │  │
│  │  ├── POST /jsonrpc (DefaultRequestHandler)                    │  │
│  │  └── InMemoryTaskStore (task lifecycle)                       │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                    │                                │
│                                    ▼                                │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │  MailAgentA2AExecutor                                         │  │
│  │  ├── Extract instruction from A2A Message                     │  │
│  │  ├── Register task with TaskRouter                            │  │
│  │  ├── Invoke run_agent(instruction, task_id, ...)              │  │
│  │  ├── Unregister task from TaskRouter                          │  │
│  │  └── Emit response via A2A Message                            │  │
│  └───────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ run_agent()
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    LANGGRAPH MAIL AGENT                             │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  StateGraph Nodes:                                          │    │
│  │  parse_instruction → compose_email → send_email             │    │
│  │       ↓                                                     │    │
│  │  [error? → END]                                             │    │
│  │       ↓                                                     │    │
│  │  wait_for_reply → fetch_email → extract_content             │    │
│  │       ↓                                                     │    │
│  │  validate_response ─┬─→ handle_success → END                │    │
│  │                     ├─→ handle_failure → END                │    │
│  │                     └─→ prepare_followup → compose_email    │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                     │
│  State: AgentState (custom TypedDict)                               │
│  ├── user_instruction: str                                          │
│  ├── parsed_request: Optional[dict]                                 │
│  ├── conversations: dict[str, dict]                                 │
│  ├── current_poc: Optional[str]                                     │
│  ├── task_id: Optional[str]  # NEW: A2A task identifier             │
│  └── final_summary: Optional[str]                                   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
         │                                          │
         │ LLM API calls                            │ REST API calls
         ▼                                          ▼
┌─────────────────────┐              ┌────────────────────────────────┐
│  LLM Provider       │              │  MOCK SMTP SERVER              │
│  ├── Google Gemini  │              │  (:8025 REST API)              │
│  └── Azure OpenAI   │              │  ├── POST /api/send            │
└─────────────────────┘              │  ├── GET /api/inboxes/...      │
                                     │  └── POST /api/webhooks        │
                                     └────────────────────────────────┘
                                                    │
                                                    │ HTTP POST callback
                                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    WEBHOOK SERVER (:9000)                           │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │  FastAPI Application                                          │  │
│  │  └── POST /webhook/email-received                             │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                    │                                │
│                                    ▼                                │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │  TaskRouter (NEW)                                             │  │
│  │  ├── _poc_to_task: Dict[str, str]  # POC email → task_id      │  │
│  │  ├── _queues: Dict[str, Queue]     # task_id → event queue    │  │
│  │  ├── register(task_id, poc_email)                             │  │
│  │  ├── unregister(task_id, poc_email)                           │  │
│  │  ├── route_event(webhook_payload)                             │  │
│  │  └── wait_for_event(task_id, timeout)                         │  │
│  └───────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Directory Structure

```
src/mail_agent/
├── a2a/                              # NEW: A2A protocol layer
│   ├── __init__.py                   # Package exports
│   ├── executor.py                   # MailAgentA2AExecutor class
│   ├── server.py                     # A2A server bootstrap + uvicorn
│   └── agent_card.py                 # AgentCard configuration
│
├── webhook/
│   ├── __init__.py                   # Package exports
│   ├── server.py                     # MODIFY: Integrate TaskRouter
│   └── router.py                     # NEW: TaskRouter for concurrent routing
│
├── agent/
│   ├── __init__.py
│   ├── graph.py                      # UNCHANGED
│   ├── state.py                      # MODIFY: Add task_id field
│   └── nodes/
│       ├── wait_for_reply.py         # MODIFY: Support TaskRouter
│       └── ...                       # Other nodes unchanged
│
├── tools/                            # UNCHANGED
├── llm/                              # UNCHANGED
├── config.py                         # MODIFY: Add A2A settings
└── main.py                           # MODIFY: Add 'a2a' CLI command

tests/
├── test_a2a_executor.py              # NEW: Executor unit tests
├── test_a2a_server.py                # NEW: Server integration tests
├── test_task_router.py               # NEW: TaskRouter unit tests
└── ...
```

---

## Data Flow

### Complete Request Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│  STEP 1: A2A Client sends task                                      │
└─────────────────────────────────────────────────────────────────────┘

A2A Client ──POST :8000/jsonrpc──▶ A2A Server
{
  "jsonrpc": "2.0",
  "method": "tasks/send",
  "params": {
    "task_id": "abc-123",
    "message": {
      "role": "user",
      "parts": [{"type": "text", "text": "Email raj@example.com asking for 10 recipes"}]
    }
  },
  "id": "req-001"
}

┌─────────────────────────────────────────────────────────────────────┐
│  STEP 2: Executor extracts instruction, runs agent                  │
└─────────────────────────────────────────────────────────────────────┘

MailAgentA2AExecutor.execute():
  instruction = "Email raj@example.com asking for 10 recipes"
  task_id = "abc-123"

  await run_agent(instruction, task_id, task_router, webhook_server)

┌─────────────────────────────────────────────────────────────────────┐
│  STEP 3: Agent composes and sends email                             │
└─────────────────────────────────────────────────────────────────────┘

parse_instruction node:
  → Extracts POC: raj@example.com
  → Sets current_poc in state

compose_email node:
  → LLM generates professional email
  → Sets _composed_subject, _composed_body

send_email node:
  → POST :8025/api/send
  → Email delivered to raj@example.com's inbox

┌─────────────────────────────────────────────────────────────────────┐
│  STEP 4: Agent waits for reply (TaskRouter registration)           │
└─────────────────────────────────────────────────────────────────────┘

wait_for_reply node:
  task_router.register(task_id="abc-123", poc_email="raj@example.com")

  TaskRouter state:
    _poc_to_task = {"raj@example.com": "abc-123"}
    _queues = {"abc-123": asyncio.Queue()}

  event = await task_router.wait_for_event("abc-123", timeout=300)
  # BLOCKS until webhook arrives

┌─────────────────────────────────────────────────────────────────────┐
│  STEP 5: POC replies (external action)                              │
└─────────────────────────────────────────────────────────────────────┘

POC (raj@example.com) sends email reply via SMTP :1025
  → Mock SMTP stores email in inbox
  → Mock SMTP triggers webhook callback

┌─────────────────────────────────────────────────────────────────────┐
│  STEP 6: Webhook routed to correct task                             │
└─────────────────────────────────────────────────────────────────────┘

Mock SMTP ──POST :9000/webhook/email-received──▶ Webhook Server
{
  "event": "email.received",
  "email_id": "uuid-xyz",
  "from": "raj@example.com",
  "to": ["info-agent@gmail.com"],
  "subject": "Re: Request for recipes"
}

TaskRouter.route_event():
  sender = "raj@example.com"
  task_id = _poc_to_task["raj@example.com"]  # → "abc-123"
  _queues["abc-123"].put_nowait(event)

wait_for_reply node unblocks:
  event = {"email_id": "uuid-xyz", ...}

┌─────────────────────────────────────────────────────────────────────┐
│  STEP 7: Agent processes reply                                      │
└─────────────────────────────────────────────────────────────────────┘

fetch_email node:
  → GET :8025/api/inboxes/info-agent@gmail.com/emails/uuid-xyz
  → Retrieves full email with attachments

extract_content node:
  → Parses Excel/CSV attachments

validate_response node:
  → LLM validates if response meets criteria
  → Routes to success/failure/followup

handle_success/handle_failure node:
  → Sets final_summary in state

┌─────────────────────────────────────────────────────────────────────┐
│  STEP 8: A2A response returned                                      │
└─────────────────────────────────────────────────────────────────────┘

MailAgentA2AExecutor:
  response_text = final_state["final_summary"]

  await event_queue.put(Message(
    role=Role.AGENT,
    parts=[TextPart(text=response_text)]
  ))

A2A Server ──HTTP Response──▶ A2A Client
{
  "jsonrpc": "2.0",
  "result": {
    "task_id": "abc-123",
    "status": "completed",
    "messages": [{
      "role": "agent",
      "parts": [{"type": "text", "text": "Successfully received 10 recipes from raj@example.com..."}]
    }]
  },
  "id": "req-001"
}
```

---

## Webhook Routing Architecture

### Problem Statement

When multiple A2A requests run concurrently, each sends emails to different POCs and waits for replies. The Mock SMTP server sends webhook callbacks when replies arrive, but **the webhook payload does not contain the A2A task_id**.

**Challenge**: How to route each webhook to the correct waiting task?

### Solution: Route by Sender Email (Option A)

Each task emails a specific POC. When a reply arrives, the sender's email address identifies which task should receive it.

```
┌─────────────────────────────────────────────────────────────────────┐
│  CONCURRENT REQUESTS WITH TASK ROUTING                              │
└─────────────────────────────────────────────────────────────────────┘

  Task abc-123                  Task xyz-456                TaskRouter
  "email raj@..."               "email bob@..."
       │                              │                          │
       │                              │                    ┌─────┴─────┐
       │                              │                    │ _poc_to_task:
       │                              │                    │ raj@→abc-123
       │                              │                    │ bob@→xyz-456
       │                              │                    │           │
       │                              │                    │ _queues:  │
       │                              │                    │ abc-123→[]│
       │                              │                    │ xyz-456→[]│
       │                              │                    └─────┬─────┘
       │                              │                          │
       │  WAITING for raj@            │  WAITING for bob@        │
       │                              │                          │
       │                              │      bob@ replies        │
       │                              │◀─────────────────────────┤
       │                              │                          │
       │                              │  route_event():          │
       │                              │  sender=bob@ → xyz-456   │
       │                              │  _queues[xyz-456].put()  │
       │                              │                          │
       │                              │  Gets event!             │
       │                              │◀─────────────────────────┤
       │                              │                          │
       │      raj@ replies            │                          │
       │◀─────────────────────────────┼──────────────────────────┤
       │                              │                          │
       │  route_event():              │                          │
       │  sender=raj@ → abc-123       │                          │
       │  _queues[abc-123].put()      │                          │
       │                              │                          │
       │  Gets event!                 │                          │
       ▼                              ▼                          │
```

### TaskRouter State Machine

```
┌─────────────────────────────────────────────────────────────────────┐
│  TaskRouter Internal State                                          │
└─────────────────────────────────────────────────────────────────────┘

Initial state:
  _poc_to_task = {}
  _queues = {}

After task abc-123 registers with POC raj@example.com:
  _poc_to_task = {"raj@example.com": "abc-123"}
  _queues = {"abc-123": Queue([])}

After task xyz-456 registers with POC bob@example.com:
  _poc_to_task = {
    "raj@example.com": "abc-123",
    "bob@example.com": "xyz-456"
  }
  _queues = {
    "abc-123": Queue([]),
    "xyz-456": Queue([])
  }

After webhook from bob@example.com arrives:
  _queues = {
    "abc-123": Queue([]),
    "xyz-456": Queue([{email_id: "...", from: "bob@..."}])
  }

After task xyz-456 unregisters:
  _poc_to_task = {"raj@example.com": "abc-123"}
  _queues = {"abc-123": Queue([])}
```

### Limitation

If the same POC is contacted by multiple concurrent tasks, routing becomes ambiguous. This is an acceptable limitation for the current use case where each task contacts a unique POC.

---

## A2A Protocol Mapping

### Conceptual Mapping

| A2A Concept | LangGraph Concept | Implementation |
|-------------|-------------------|----------------|
| `Task` | Agent execution | One `run_agent()` call |
| `task_id` | `state.task_id` | Passed through state for routing |
| `Message` (input) | `state.user_instruction` | Extracted from `parts[0].text` |
| `Message` (output) | `state.final_summary` | Wrapped in TextPart |
| Task lifecycle | Graph execution | Managed by A2A SDK's InMemoryTaskStore |

### State Mapping Strategy: Option A

The existing agent uses custom state (`user_instruction`, `parsed_request`, etc.) rather than standard `messages: List[BaseMessage]`.

**Approach**: Wrap the instruction directly, call `run_agent()`, and extract `final_summary` for response. No conversation memory across A2A requests (each request is standalone).

```
A2A Input                              AgentState
─────────────────────────────────────────────────────────────
Message.parts[0].text      →      user_instruction: str
context.task_id            →      task_id: str (NEW field)

AgentState                             A2A Output
─────────────────────────────────────────────────────────────
final_summary: str         →      Message(role=AGENT, parts=[TextPart])
error: str                 →      Message with error text
```

---

## Configuration

### New Environment Variables

```bash
# A2A Server Configuration
MAIL_AGENT_A2A_HOST=0.0.0.0           # Bind address
MAIL_AGENT_A2A_PORT=8000              # Port number

# Agent Card Metadata
MAIL_AGENT_A2A_AGENT_NAME="Mail Agent"
MAIL_AGENT_A2A_AGENT_DESCRIPTION="Intelligent email assistant powered by LangGraph"
MAIL_AGENT_A2A_AGENT_VERSION="1.0.0"
```

### Settings Class Addition

```python
# In config.py - Settings class

# A2A Server Configuration
a2a_host: str = Field(
    default="0.0.0.0",
    description="A2A server bind address",
)
a2a_port: int = Field(
    default=8000,
    ge=1,
    le=65535,
    description="A2A server port",
)

# Agent Card Metadata
a2a_agent_name: str = Field(
    default="Mail Agent",
    description="Agent name for A2A protocol",
)
a2a_agent_description: str = Field(
    default="Intelligent email assistant powered by LangGraph",
    description="Agent description for A2A protocol",
)
a2a_agent_version: str = Field(
    default="1.0.0",
    description="Agent version for A2A protocol",
)
```

---

## API Contracts

### A2A Agent Card

```
GET /.well-known/agent.json

Response:
{
  "name": "Mail Agent",
  "description": "Intelligent email assistant powered by LangGraph that handles email communication with POCs to gather information.",
  "url": "http://localhost:8000",
  "version": "1.0.0",
  "capabilities": {
    "skills": [
      {
        "name": "email_communication",
        "description": "Send emails to POCs, wait for replies, extract data from attachments, and validate responses.",
        "input_schema": {
          "type": "object",
          "properties": {
            "text": {
              "type": "string",
              "description": "Natural language instruction describing the email task"
            }
          },
          "required": ["text"]
        },
        "output_schema": {
          "type": "object",
          "properties": {
            "response": {
              "type": "string",
              "description": "Summary of the email communication outcome"
            }
          }
        }
      }
    ]
  }
}
```

### A2A Task Execution

```
POST /jsonrpc

Request:
{
  "jsonrpc": "2.0",
  "method": "tasks/send",
  "params": {
    "task_id": "uuid-string",
    "message": {
      "role": "user",
      "parts": [
        {
          "type": "text",
          "text": "Email raj@example.com asking for 10 recipes with nutritional information"
        }
      ]
    }
  },
  "id": "request-id"
}

Response (Success):
{
  "jsonrpc": "2.0",
  "result": {
    "task_id": "uuid-string",
    "status": "completed",
    "messages": [
      {
        "role": "agent",
        "parts": [
          {
            "type": "text",
            "text": "Successfully received response from raj@example.com. The attachment contained 10 recipes with complete nutritional information including calories, protein, carbs, and fat for each recipe."
          }
        ]
      }
    ]
  },
  "id": "request-id"
}

Response (Failure):
{
  "jsonrpc": "2.0",
  "result": {
    "task_id": "uuid-string",
    "status": "completed",
    "messages": [
      {
        "role": "agent",
        "parts": [
          {
            "type": "text",
            "text": "Failed to complete task: Maximum retry attempts exceeded. POC did not provide required information after 5 attempts."
          }
        ]
      }
    ]
  },
  "id": "request-id"
}
```

### Webhook Callback (Mock SMTP → Mail Agent)

```
POST /webhook/email-received

Request:
{
  "event": "email.received",
  "email_id": "uuid-xyz",
  "from": "raj@example.com",
  "to": ["info-agent@gmail.com"],
  "subject": "Re: Request for recipes",
  "has_attachments": true,
  "attachment_count": 1,
  "received_at": "2025-12-15T10:30:00.000000",
  "body_preview": "Please find the requested recipes attached..."
}

Headers:
  Content-Type: application/json
  X-Webhook-Event: email.received
  X-Email-ID: uuid-xyz
  X-Webhook-Timestamp: 2025-12-15T10:30:00.000000

Response:
  HTTP 200 OK
  {"status": "received"}
```

---

## Algorithms

### TaskRouter Class

```
CLASS TaskRouter:
    """Routes webhook events to correct A2A tasks based on sender email."""

    ATTRIBUTES:
        _poc_to_task: Dict[str, str]       # POC email → task_id
        _queues: Dict[str, asyncio.Queue]  # task_id → event queue
        _lock: asyncio.Lock                # Thread safety for concurrent access

    METHOD __init__():
        _poc_to_task = {}
        _queues = {}
        _lock = asyncio.Lock()

    ASYNC METHOD register(task_id: str, poc_email: str) -> None:
        """Register a task to receive events from a specific POC."""
        ASYNC WITH _lock:
            IF poc_email IN _poc_to_task:
                RAISE ValueError(f"POC {poc_email} already registered to task {_poc_to_task[poc_email]}")
            _poc_to_task[poc_email] = task_id
            _queues[task_id] = asyncio.Queue()
            LOG INFO f"Registered task {task_id} for POC {poc_email}"

    ASYNC METHOD unregister(task_id: str, poc_email: str) -> None:
        """Unregister a task and clean up its queue."""
        ASYNC WITH _lock:
            IF poc_email IN _poc_to_task:
                DELETE _poc_to_task[poc_email]
            IF task_id IN _queues:
                DELETE _queues[task_id]
            LOG INFO f"Unregistered task {task_id}"

    ASYNC METHOD route_event(webhook_payload: dict) -> bool:
        """Route incoming webhook to correct task queue."""
        sender = webhook_payload.get("from")
        IF NOT sender:
            LOG WARNING "Webhook missing 'from' field"
            RETURN False

        ASYNC WITH _lock:
            IF sender NOT IN _poc_to_task:
                LOG WARNING f"No task registered for sender {sender}"
                RETURN False

            task_id = _poc_to_task[sender]
            await _queues[task_id].put(webhook_payload)
            LOG INFO f"Routed event from {sender} to task {task_id}"
            RETURN True

    ASYNC METHOD wait_for_event(task_id: str, timeout: float) -> dict:
        """Wait for an event for a specific task with timeout."""
        IF task_id NOT IN _queues:
            RAISE KeyError(f"Task {task_id} not registered")

        queue = _queues[task_id]
        TRY:
            event = await asyncio.wait_for(queue.get(), timeout=timeout)
            RETURN event
        EXCEPT asyncio.TimeoutError:
            LOG WARNING f"Timeout waiting for event for task {task_id}"
            RAISE
```

### MailAgentA2AExecutor Class

```
CLASS MailAgentA2AExecutor(AgentExecutor):
    """A2A executor that bridges A2A protocol to LangGraph Mail Agent."""

    ATTRIBUTES:
        graph: CompiledStateGraph
        task_router: TaskRouter
        webhook_server: WebhookServer

    METHOD __init__(graph, task_router, webhook_server):
        self.graph = graph
        self.task_router = task_router
        self.webhook_server = webhook_server

    ASYNC METHOD execute(context: RequestContext, event_queue: EventQueue) -> None:
        """Execute an A2A task by running the mail agent."""

        # 1. EXTRACT INSTRUCTION
        message = context.request.params.message
        IF NOT message.parts OR NOT message.parts[0].text:
            RAISE ValueError("No instruction text in message")

        instruction = message.parts[0].text
        task_id = context.task_id
        LOG INFO f"Executing task {task_id}: {instruction[:100]}..."

        TRY:
            # 2. RUN MAIL AGENT
            # Pass task_id and task_router for webhook routing
            final_state = await run_agent(
                instruction=instruction,
                task_id=task_id,
                task_router=self.task_router,
                webhook_server=self.webhook_server
            )

            # 3. BUILD RESPONSE TEXT
            IF final_state.get("error"):
                response_text = f"Failed: {final_state['error']}"
            ELIF final_state.get("final_summary"):
                response_text = final_state["final_summary"]
            ELSE:
                response_text = "Task completed but no summary available"

        EXCEPT Exception as e:
            LOG ERROR f"Task {task_id} failed with exception: {e}"
            response_text = f"Error executing task: {str(e)}"

        # 4. EMIT A2A RESPONSE
        response_message = Message(
            role=Role.AGENT,
            parts=[TextPart(text=response_text)]
        )
        await event_queue.put(response_message)
        LOG INFO f"Task {task_id} completed"

    ASYNC METHOD cancel(context: RequestContext, event_queue: EventQueue) -> None:
        """Handle task cancellation (future implementation)."""
        LOG WARNING f"Cancel requested for task {context.task_id} (not implemented)"
        PASS
```

### Modified wait_for_reply Node

```
ASYNC FUNCTION wait_for_reply(state: AgentState) -> dict:
    """Wait for email reply from POC with task-aware routing."""

    task_id = state.get("task_id")
    poc_email = state.get("current_poc")
    task_router = get_task_router()  # Global or injected
    webhook_server = get_webhook_server()  # Global or injected

    LOG INFO f"Waiting for reply from {poc_email} (task: {task_id})"

    IF task_id AND task_router:
        # A2A MODE: Use task-specific routing
        await task_router.register(task_id, poc_email)
        TRY:
            event = await task_router.wait_for_event(task_id, timeout=300)
        FINALLY:
            await task_router.unregister(task_id, poc_email)
    ELSE:
        # CLI MODE: Use original single-queue behavior
        event = await webhook_server.wait_for_event(timeout=300)

    email_id = event.get("email_id")
    LOG INFO f"Received reply: email_id={email_id}"

    RETURN {
        "pending_webhooks": [email_id],
        "progress_messages": [f"Received reply from {poc_email}"]
    }
```

### A2A Server Bootstrap

```
FUNCTION create_a2a_application(settings: Settings) -> Starlette:
    """Create and configure the A2A server application."""

    # 1. BUILD AGENT CARD
    agent_card = AgentCard(
        name=settings.a2a_agent_name,
        description=settings.a2a_agent_description,
        url=f"http://{settings.a2a_host}:{settings.a2a_port}",
        version=settings.a2a_agent_version,
        capabilities=AgentCapability(
            skills=[
                AgentSkill(
                    name="email_communication",
                    description="Send emails to POCs, wait for replies, extract data from attachments",
                    input_schema={"type": "object", "properties": {"text": {"type": "string"}}},
                    output_schema={"type": "object", "properties": {"response": {"type": "string"}}}
                )
            ]
        )
    )

    # 2. CREATE SHARED RESOURCES
    task_router = TaskRouter()
    webhook_server = WebhookServer(task_router=task_router)
    graph = compile_mail_agent_graph()

    # 3. CREATE EXECUTOR
    executor = MailAgentA2AExecutor(
        graph=graph,
        task_router=task_router,
        webhook_server=webhook_server
    )

    # 4. CREATE REQUEST HANDLER
    request_handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=InMemoryTaskStore()
    )

    # 5. BUILD APPLICATION
    app_builder = A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=request_handler
    )

    RETURN app_builder.build()


ASYNC FUNCTION run_a2a_server(settings: Settings) -> None:
    """Run the A2A server with webhook server."""

    app = create_a2a_application(settings)

    # Start webhook server in background
    webhook_server = app.state.webhook_server
    await webhook_server.start()

    # Register webhook with Mock SMTP
    smtp_client = SMTPClient()
    await smtp_client.register_webhook(settings.webhook_url)

    TRY:
        # Run A2A server
        config = uvicorn.Config(
            app=app,
            host=settings.a2a_host,
            port=settings.a2a_port,
            log_level=settings.log_level.lower()
        )
        server = uvicorn.Server(config)
        await server.serve()
    FINALLY:
        # Cleanup
        await smtp_client.unregister_webhook()
        await webhook_server.stop()
```

---

## Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `src/mail_agent/a2a/__init__.py` | CREATE | Package init, exports |
| `src/mail_agent/a2a/executor.py` | CREATE | MailAgentA2AExecutor class |
| `src/mail_agent/a2a/server.py` | CREATE | A2A server bootstrap, uvicorn runner |
| `src/mail_agent/a2a/agent_card.py` | CREATE | AgentCard configuration factory |
| `src/mail_agent/webhook/router.py` | CREATE | TaskRouter class |
| `src/mail_agent/webhook/server.py` | MODIFY | Integrate TaskRouter, update handle_webhook |
| `src/mail_agent/webhook/__init__.py` | MODIFY | Export TaskRouter |
| `src/mail_agent/agent/state.py` | MODIFY | Add `task_id` field to AgentState |
| `src/mail_agent/agent/nodes/wait_for_reply.py` | MODIFY | Support TaskRouter for A2A mode |
| `src/mail_agent/config.py` | MODIFY | Add A2A configuration fields |
| `src/mail_agent/main.py` | MODIFY | Add `mail-agent a2a` CLI command |
| `tests/test_task_router.py` | CREATE | TaskRouter unit tests |
| `tests/test_a2a_executor.py` | CREATE | Executor unit tests |
| `tests/test_a2a_integration.py` | CREATE | End-to-end A2A tests |

---

## Error Handling

### Error Categories

| Category | Source | Handling |
|----------|--------|----------|
| **Input Validation** | Missing instruction text | Return A2A error message |
| **LLM Errors** | Provider API failures | Retry with backoff, then return error |
| **SMTP Errors** | Mock SMTP unavailable | Return error, don't retry |
| **Timeout** | POC doesn't reply | Return timeout error after max wait |
| **Webhook Routing** | Unknown sender | Log warning, ignore event |
| **Task Registration** | Duplicate POC | Raise error (configuration issue) |

### Error Response Format

```json
{
  "jsonrpc": "2.0",
  "result": {
    "task_id": "uuid",
    "status": "completed",
    "messages": [{
      "role": "agent",
      "parts": [{
        "type": "text",
        "text": "Error: [error description]"
      }]
    }]
  },
  "id": "request-id"
}
```

---

## Constraints and Limitations

### Current Limitations

1. **No Conversation Memory**: Each A2A request is standalone. No memory of previous tasks.

2. **Single POC per Task**: Each task can only communicate with one POC. Multiple POC support requires state refactoring.

3. **No Concurrent Same-POC Tasks**: If two tasks email the same POC simultaneously, routing is undefined.

4. **In-Memory Task Store**: Tasks are lost on server restart. Production needs persistent store.

5. **No Streaming**: Responses are sent as complete messages, not streamed tokens.

6. **No Authentication**: A2A endpoints are open. Production needs auth middleware.

### Future Enhancements

1. Add LangGraph checkpointer for conversation memory
2. Support streaming via `astream_events`
3. Add Redis/Postgres task store for persistence
4. Add API key authentication
5. Support multiple POCs per task
6. Add OpenTelemetry tracing

---

## Testing Strategy

### Unit Tests

- `test_task_router.py`: TaskRouter registration, routing, timeout
- `test_a2a_executor.py`: Executor with mocked graph
- `test_agent_card.py`: AgentCard generation

### Integration Tests

- `test_a2a_integration.py`: Full flow with mock SMTP
- Test concurrent requests
- Test timeout scenarios
- Test error handling

### Manual Testing

```bash
# Start Mock SMTP
mock-smtp

# Start A2A Server
mail-agent a2a

# Test Agent Card
curl http://localhost:8000/.well-known/agent.json

# Test Task Execution
curl -X POST http://localhost:8000/jsonrpc \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tasks/send",
    "params": {
      "task_id": "test-001",
      "message": {
        "role": "user",
        "parts": [{"type": "text", "text": "Email test@example.com asking for data"}]
      }
    },
    "id": "1"
  }'
```

---

## References

- [Google A2A Protocol Specification](https://github.com/google/a2a-protocol)
- [A2A SDK Documentation](https://pypi.org/project/a2a-sdk/)
- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [Mail Agent Architecture](./mail-agent.md)
- [Mock SMTP Server Architecture](./mock-smtp-server.md)

# Code snippets
A. The Executor (executor.py)
This class inherits from a2a.server.agent_execution.AgentExecutor. It is the bridge that translates protocols.

Key Requirements for the Code:

Accept the Graph: The __init__ method should accept the compiled LangGraph runnable.

Handle Async: Use graph.ainvoke inside the execute method.

Map ID for Persistence: Pass task_id to the graph config.

```python
# executor.py reference pattern

from typing import Any, Dict
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.types import Message, TextPart, Role

# LangChain/Graph imports
from langchain_core.messages import HumanMessage
from langgraph.graph.state import CompiledStateGraph

class LangGraphA2AExecutor(AgentExecutor):
    def __init__(self, graph: CompiledStateGraph):
        self.graph = graph

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        """
        Translates A2A request -> LangGraph input -> A2A response.
        """
        
        # 1. EXTRACT INPUT
        # A2A sends the user's prompt inside context.request.params.message
        # We assume the first part is the text prompt.
        incoming_message = context.request.params.message
        user_text = incoming_message.parts[0].text
        
        # 2. CONFIGURE PERSISTENCE
        # We map the A2A 'task_id' to the LangGraph 'thread_id'.
        # This is CRITICAL for maintaining conversation memory.
        config = {"configurable": {"thread_id": context.task_id}}
        
        # 3. PREPARE GRAPH STATE
        # Adjust 'messages' key based on your specific graph schema.
        graph_input = {"messages": [HumanMessage(content=user_text)]}
        
        # 4. EXECUTE GRAPH
        # We use ainvoke for async execution.
        try:
            final_state = await self.graph.ainvoke(graph_input, config=config)
            
            # 5. EXTRACT OUTPUT
            # Assuming the standard pattern where the last message in state is the AI response.
            ai_response_content = final_state["messages"][-1].content
            
            # 6. SEND RESPONSE
            # Wrap the text back into an A2A Message object.
            response_message = Message(
                role=Role.AGENT,
                parts=[TextPart(text=ai_response_content)]
            )
            
            # Put the message onto the event queue to send it back to the client.
            await event_queue.put(response_message)
            
        except Exception as e:
            # Handle graph errors gracefully
            error_msg = Message(role=Role.AGENT, parts=[TextPart(text=f"Error: {str(e)}")])
            await event_queue.put(error_msg)
```
------------

B. The Server (server.py)
This sets up the HTTP application and the Agent Card (metadata).

Key Requirements for the Code:

Define Identity: Create an AgentCard with a clear description.

Define Capabilities: Use AgentCapability to describe what the agent does (input/output schema).

Bootstrapping: Use A2AStarletteApplication to serve it.

```python
# server.py reference pattern

import uvicorn
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCard, AgentCapability, AgentSkill

# Import the executor we just created and your graph
from executor import LangGraphA2AExecutor
from my_agent_graph import graph  # <--- REPLACE THIS with actual import

# 1. METADATA CONFIGURATION
# This tells other agents who we are.
agent_card = AgentCard(
    name="LangGraph Interaction Agent",
    description="An intelligent agent powered by LangGraph that handles [INSERT FUNCTION].",
    url="http://localhost:8000",
    version="0.1.0",
    capabilities=AgentCapability(
        skills=[
            AgentSkill(
                name="chat",
                description="Process complex queries using a state graph",
                input_schema={
                    "type": "object", 
                    "properties": {"text": {"type": "string"}}
                },
                output_schema={
                    "type": "object", 
                    "properties": {"response": {"type": "string"}}
                }
            )
        ]
    )
)

# 2. APPLICATION WIRING
# We use InMemoryTaskStore for simplicity, but for production, 
# you might want a persistent store (Redis/Postgres) if the server restarts.
request_handler = DefaultRequestHandler(
    agent_executor=LangGraphA2AExecutor(graph),
    task_store=InMemoryTaskStore()
)

# 3. BUILD APP
# This creates the Starlette (FastAPI-compatible) app
app_builder = A2AStarletteApplication(
    agent_card=agent_card,
    http_handler=request_handler
)
app = app_builder.build()

if __name__ == "__main__":
    # Run on port 8000
    uvicorn.run(app, host="0.0.0.0", port=8000)
```