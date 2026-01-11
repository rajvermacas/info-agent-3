# Mail Agent Async Architecture - Non-Blocking A2A with Checkpointing

## Overview

This document describes the architecture for making the Mail Agent **non-blocking** when communicating via A2A protocol. The current implementation blocks the A2A client while waiting for human email replies (which can take hours). This architecture introduces **LangGraph checkpointing** with SQLite persistence and **Server-Sent Events (SSE)** for real-time progress streaming.

---

## Table of Contents

1. [Problem Statement](#problem-statement)
2. [Solution Overview](#solution-overview)
3. [Technology Stack](#technology-stack)
4. [Execution Flow](#execution-flow)
5. [Component Architecture](#component-architecture)
6. [LangGraph Checkpointing](#langgraph-checkpointing)
7. [Task Manager](#task-manager)
8. [API Contracts](#api-contracts)
9. [Configuration](#configuration)
10. [Directory Structure](#directory-structure)
11. [Algorithms](#algorithms)
12. [Error Handling](#error-handling)
13. [Files to Create/Modify](#files-to-createmodify)

---

## Problem Statement

### Current Blocking Architecture

```
┌─────────────┐      ┌──────────────────┐      ┌─────────────┐
│ a2a_client  │──────│  mail_agent      │──────│  recipient  │
│             │      │  (A2A Server)    │      │  (Human)    │
└─────────────┘      └──────────────────┘      └─────────────┘
     │                       │                       │
     │  1. Send Task         │                       │
     │──────────────────────>│                       │
     │                       │  2. Send Mail         │
     │                       │──────────────────────>│
     │                       │                       │
     │        BLOCKED        │       BLOCKED         │
     │        WAITING        │       WAITING         │
     │      (HTTP conn)      │    (asyncio queue)    │
     │                       │<──────────────────────│
     │                       │  3. Reply (hours?)    │
     │<──────────────────────│                       │
     │  4. Response          │                       │
```

### Identified Blocking Points

| # | Location | Sender | Receiver | Timeout | Issue |
|---|----------|--------|----------|---------|-------|
| 1 | `a2a_client.py` | a2a_client | mail_agent | 300s | HTTP connection times out |
| 2 | `wait_for_reply.py` (A2A) | wait_for_reply node | TaskRouter queue | 300s | Agent fails if human slow |
| 3 | `wait_for_reply.py` (CLI) | wait_for_reply node | WebhookServer queue | 5s × ∞ | Infinite loop (CLI only) |

### Core Problem

The A2A client holds an HTTP connection open for the **entire agent execution**, including the `wait_for_reply` node which blocks waiting for a human to respond to an email. This can take minutes to hours, causing:

1. HTTP client timeout (300 seconds default)
2. Resource exhaustion (connections held indefinitely)
3. Poor user experience (no progress visibility)

---

## Solution Overview

### Non-Blocking Architecture with Checkpointing

```
┌─────────────┐         ┌──────────────────────────────────────────────────────┐
│             │   SSE   │                   MAIL AGENT SERVER                   │
│  a2a_client │◄───────►│  ┌─────────────┐  ┌─────────────┐  ┌──────────────┐  │
│             │ Stream  │  │  A2A Server │  │   Graph     │  │   SQLite     │  │
└─────────────┘         │  │  (FastAPI)  │  │  Executor   │  │ Checkpointer │  │
                        │  └──────┬──────┘  └──────┬──────┘  └──────┬───────┘  │
                        │         │                │                │          │
                        │         │         ┌──────▼──────┐         │          │
                        │         │         │  LangGraph  │◄────────┘          │
                        │         │         │   Agent     │  (save/restore)    │
                        │         │         └──────┬──────┘                    │
                        │         │                │                           │
                        │  ┌──────▼────────────────▼──────┐                    │
                        │  │        Task Manager          │                    │
                        │  │  (tracks suspended tasks)    │                    │
                        │  └──────────────┬───────────────┘                    │
                        │                 │                                    │
                        │  ┌──────────────▼───────────────┐                    │
                        │  │      Webhook Server          │◄──── Mock SMTP     │
                        │  │   (resumes suspended tasks)  │      (port 8025)   │
                        │  └──────────────────────────────┘                    │
                        └──────────────────────────────────────────────────────┘
```

### Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Client communication** | SSE (Server-Sent Events) | Real-time progress, standard HTTP |
| **Blocking behavior** | Checkpoint & suspend | Free client while waiting for human |
| **State persistence** | SQLite | Simple, reliable, async-compatible |
| **Result retrieval** | Polling (GET /tasks/{id}) | Simple, no SSE reconnection complexity |
| **Timeout** | 1 hour (configurable) | Humans are slow |
| **Backward compatibility** | None | Clean break, simpler implementation |

---

## Technology Stack

| Layer | Technology | Version | Purpose |
|-------|------------|---------|---------|
| **Protocol** | A2A SDK | `a2a-sdk[http-server]` | Google Agent-to-Agent protocol |
| **HTTP Server** | FastAPI + Uvicorn | Latest | A2A endpoints, SSE streaming |
| **SSE** | `sse-starlette` | Latest | Server-Sent Events |
| **Agent Framework** | LangGraph | `>=0.2.0` | State machine with checkpointing |
| **Checkpointer** | `langgraph-checkpoint-sqlite` | Latest | Async SQLite persistence |
| **Database** | `aiosqlite` | Latest | Async SQLite operations |
| **HTTP Client** | `httpx` | Latest | Async HTTP calls |
| **LLM Integration** | LangChain + Claude/Gemini | Latest | Language model backends |

### Dependencies to Add

```toml
# pyproject.toml
dependencies = [
    # ... existing dependencies
    "langgraph-checkpoint-sqlite>=1.0.0",
    "aiosqlite>=0.19.0",
    "sse-starlette>=1.6.0",
]
```

---

## Execution Flow

### Complete Non-Blocking Flow

```
═══════════════════════════════════════════════════════════════════════════════
                    NON-BLOCKING FLOW WITH CHECKPOINTING
═══════════════════════════════════════════════════════════════════════════════

┌─────────────┐        ┌──────────────────┐        ┌─────────────┐
│  a2a_client │        │   mail_agent     │        │   Human     │
└──────┬──────┘        └────────┬─────────┘        └──────┬──────┘
       │                        │                         │
       │ 1. POST message/stream │                         │
       │───────────────────────►│                         │
       │                        │                         │
       │◄·······················│                         │
       │ SSE: {state: working,  │                         │
       │       message: parsing}│                         │
       │                        │                         │
       │◄·······················│                         │
       │ SSE: {state: working,  │                         │
       │       message: compose}│                         │
       │                        │                         │
       │◄·······················│                         │
       │ SSE: {state: working,  │                         │
       │       message: sending}│                         │
       │                        │ 2. Send email           │
       │                        │────────────────────────►│
       │                        │                         │
       │◄·······················│                         │
       │ SSE: {state: suspended,│ 3. CHECKPOINT           │
       │       task_id: abc,    │    Save state to SQLite │
       │       message: waiting}│    Return to client     │
       │                        │                         │
       │  CONNECTION CLOSED     │                         │
       │  (client is free)      │                         │
       │                        │                         │
       │                        │         (Human reads    │
       │                        │          email, thinks, │
       │                        │          replies...)    │
       │                        │                         │
       │                        │◄────────────────────────│
       │                        │ 4. Webhook: email.received
       │                        │                         │
       │                        │ 5. RESTORE              │
       │                        │    Load state from SQLite
       │                        │    Resume graph execution
       │                        │                         │
       │                        │ 6. Continue processing  │
       │                        │    fetch → extract →    │
       │                        │    validate → complete  │
       │                        │                         │
       │ 7. GET /tasks/abc      │                         │
       │    (client polls)      │                         │
       │───────────────────────►│                         │
       │◄───────────────────────│                         │
       │ {status: completed,    │                         │
       │  result: {...}}        │                         │
```

### State Transitions

```
┌──────────────────────────────────────────────────────────────────┐
│                      TASK STATE MACHINE                          │
└──────────────────────────────────────────────────────────────────┘

                    ┌─────────┐
                    │ CREATED │
                    └────┬────┘
                         │
                         ▼
                    ┌─────────┐
        ┌──────────│ WORKING │──────────┐
        │          └────┬────┘          │
        │               │               │
        │ (error)       │ (interrupt)   │ (complete without wait)
        │               │               │
        ▼               ▼               ▼
   ┌────────┐    ┌───────────┐    ┌───────────┐
   │ FAILED │    │ SUSPENDED │    │ COMPLETED │
   └────────┘    └─────┬─────┘    └───────────┘
                       │
                       │ (webhook arrives)
                       │
                       ▼
                  ┌─────────┐
                  │ RESUMED │
                  └────┬────┘
                       │
          ┌────────────┼────────────┐
          │            │            │
          ▼            ▼            ▼
     ┌────────┐  ┌───────────┐  ┌───────────┐
     │ FAILED │  │ SUSPENDED │  │ COMPLETED │
     └────────┘  │ (retry)   │  └───────────┘
                 └───────────┘
```

---

## Component Architecture

### 1. LangGraph State Machine

```
┌─────────────────────────────────────────────────────────────────┐
│                    LANGGRAPH STATE MACHINE                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐         │
│  │   parse     │───►│  compose    │───►│    send     │         │
│  │ instruction │    │   email     │    │   email     │         │
│  └─────────────┘    └─────────────┘    └──────┬──────┘         │
│                                               │                 │
│                                               ▼                 │
│                                    ╔═══════════════════╗        │
│                                    ║  INTERRUPT NODE   ║        │
│                                    ║  (wait_for_reply) ║        │
│                                    ║                   ║        │
│                                    ║  • Calls interrupt()       ║
│                                    ║  • Saves checkpoint        ║
│                                    ║  • Returns to caller       ║
│                                    ╚═════════╤═════════╝        │
│                                              │                  │
│                     (webhook triggers resume)│                  │
│                                              ▼                  │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐         │
│  │  validate   │◄───│  extract    │◄───│   fetch     │         │
│  │  response   │    │  content    │    │   email     │         │
│  └──────┬──────┘    └─────────────┘    └─────────────┘         │
│         │                                                       │
│         ├───────────► handle_success ───► END                  │
│         ├───────────► handle_failure ───► END                  │
│         └───────────► prepare_followup ──► compose (retry)     │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 2. SQLite Database Schema

```
┌─────────────────────────────────────────────────────────────────┐
│                    SQLITE DATABASE                               │
│                    (mail_agent.db)                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  TABLE: checkpoints (managed by LangGraph)                       │
│  ┌────────────────┬────────────────┬───────────────────────┐    │
│  │ thread_id      │ checkpoint_id  │ checkpoint (BLOB)     │    │
│  ├────────────────┼────────────────┼───────────────────────┤    │
│  │ task-abc-123   │ cp-001         │ <serialized state>    │    │
│  │ task-def-456   │ cp-002         │ <serialized state>    │    │
│  └────────────────┴────────────────┴───────────────────────┘    │
│                                                                  │
│  TABLE: suspended_tasks (custom)                                 │
│  ┌────────────┬────────────┬────────────┬──────────────────┐    │
│  │ task_id    │ poc_email  │ created_at │ expires_at       │    │
│  ├────────────┼────────────┼────────────┼──────────────────┤    │
│  │ abc-123    │ poc@ex.com │ 2025-12-15 │ 2025-12-15+1hr   │    │
│  │ def-456    │ bob@ex.com │ 2025-12-15 │ 2025-12-15+1hr   │    │
│  └────────────┴────────────┴────────────┴──────────────────┘    │
│                                                                  │
│  TABLE: task_results (custom)                                    │
│  ┌────────────┬────────────┬────────────┬──────────────────┐    │
│  │ task_id    │ status     │ result     │ completed_at     │    │
│  ├────────────┼────────────┼────────────┼──────────────────┤    │
│  │ xyz-789    │ completed  │ {json...}  │ 2025-12-15T11:00 │    │
│  └────────────┴────────────┴────────────┴──────────────────┘    │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 3. Task Manager

```
┌─────────────────────────────────────────────────────────────────┐
│                      TASK MANAGER                                │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Responsibilities:                                               │
│  ├─ Track suspended tasks (task_id ↔ poc_email mapping)         │
│  ├─ Handle webhook routing to correct suspended task            │
│  ├─ Resume graph execution when webhook arrives                 │
│  ├─ Store task results for polling                              │
│  └─ Manage task expiration (1 hour timeout)                     │
│                                                                  │
│  In-Memory State:                                                │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ _poc_to_task: dict[str, str]                            │    │
│  │   Maps: poc_email → task_id                             │    │
│  │   Example: {"poc@example.com": "task-abc-123"}          │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
│  Methods:                                                        │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ async def suspend_task(                                 │    │
│  │     task_id: str,                                       │    │
│  │     poc_email: str,                                     │    │
│  │ ) -> None                                               │    │
│  │   • Register task_id ↔ poc_email mapping                │    │
│  │   • Store in suspended_tasks table                      │    │
│  │   • Set expiration (now + 1 hour)                       │    │
│  ├─────────────────────────────────────────────────────────┤    │
│  │ async def handle_webhook(                               │    │
│  │     payload: WebhookPayload,                            │    │
│  │ ) -> None                                               │    │
│  │   • Lookup task_id by poc_email (from address)          │    │
│  │   • Load checkpoint from SQLite                         │    │
│  │   • Resume graph with webhook data                      │    │
│  │   • Store result when complete                          │    │
│  ├─────────────────────────────────────────────────────────┤    │
│  │ async def get_task_status(                              │    │
│  │     task_id: str,                                       │    │
│  │ ) -> TaskStatus                                         │    │
│  │   • Return current state and result if available        │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## LangGraph Checkpointing

### Interrupt Pattern

The `wait_for_reply` node uses LangGraph's `interrupt()` function to:
1. Save current state to SQLite
2. Return control to the caller (SSE stream closes)
3. Wait for external trigger (webhook) to resume

```
ALGORITHM: InterruptNode (wait_for_reply)

INPUT: state (AgentState with current_poc, task_id, etc.)
OUTPUT: dict with email_id (after resume)

1. PREPARE interrupt payload:
   interrupt_data = {
       "reason": "waiting_for_reply",
       "poc_email": state["current_poc"],
       "task_id": state["task_id"],
       "sent_email_id": state["sent_email_id"],
   }

2. CALL interrupt(interrupt_data):
   - LangGraph saves checkpoint to SQLite
   - Control returns to executor
   - Executor emits "suspended" SSE event
   - SSE connection closes

3. WAIT for resume:
   - Webhook arrives at /webhook endpoint
   - TaskManager looks up task_id by poc_email
   - TaskManager calls graph.astream(Command(resume=webhook_data))
   - interrupt() returns with webhook_data

4. EXTRACT email_id from resumed data:
   reply_data = <value returned by interrupt after resume>
   email_id = reply_data["email_id"]

5. RETURN {"email_id": email_id}
```

### Graph Compilation

```
ALGORITHM: CreateGraphWithCheckpointer

1. INITIALIZE checkpointer:
   checkpointer = AsyncSqliteSaver.from_conn_string(
       "sqlite:///mail_agent.db"
   )

2. BUILD graph:
   graph = StateGraph(AgentState)
   graph.add_node("parse_instruction", parse_instruction)
   graph.add_node("compose_email", compose_email)
   graph.add_node("send_email", send_email)
   graph.add_node("wait_for_reply", wait_for_reply)  # Interrupt node
   graph.add_node("fetch_email", fetch_email)
   graph.add_node("extract_content", extract_content)
   graph.add_node("validate_response", validate_response)
   graph.add_node("handle_success", handle_success)
   graph.add_node("handle_failure", handle_failure)
   graph.add_node("prepare_followup", prepare_followup)

   # Add edges...

3. COMPILE with checkpointer:
   compiled = graph.compile(
       checkpointer=checkpointer,
       interrupt_before=["wait_for_reply"],  # Optional: interrupt before node
   )

4. RETURN compiled
```

### Resume Flow

```
ALGORITHM: ResumeFromCheckpoint

INPUT: task_id, webhook_payload
OUTPUT: Final agent result

1. CREATE config for thread:
   config = {
       "configurable": {
           "thread_id": task_id,
       }
   }

2. CREATE resume command:
   command = Command(resume=webhook_payload)

3. STREAM resumed execution:
   async for event in graph.astream(command, config=config):
       # Process each node output
       if "handle_success" in event or "handle_failure" in event:
           final_result = event
           break
       if interrupt detected again:
           # Another wait_for_reply (retry scenario)
           handle suspension again

4. STORE result:
   await task_store.save_result(task_id, final_result)

5. CLEANUP:
   await task_manager.unregister_task(task_id)
```

---

## Task Manager

### Initialization

```
ALGORITHM: TaskManagerInit

1. LOAD checkpointer:
   self.checkpointer = AsyncSqliteSaver.from_conn_string(db_path)

2. COMPILE graph with checkpointer:
   self.graph = create_graph_with_checkpointer(self.checkpointer)

3. INITIALIZE in-memory mappings:
   self._poc_to_task: dict[str, str] = {}

4. INITIALIZE database tables:
   await self._init_tables()

5. RESTORE suspended tasks from database:
   suspended = await self._load_suspended_tasks()
   for task in suspended:
       if not task.is_expired():
           self._poc_to_task[task.poc_email] = task.task_id
       else:
           await self._cleanup_expired_task(task.task_id)
```

### Suspend Task

```
ALGORITHM: SuspendTask

INPUT: task_id, poc_email, interrupt_data
OUTPUT: None

1. VALIDATE no duplicate POC:
   if poc_email in self._poc_to_task:
       existing_task = self._poc_to_task[poc_email]
       if existing_task != task_id:
           raise ConflictError(f"POC {poc_email} already has pending task")

2. REGISTER mapping:
   self._poc_to_task[poc_email] = task_id

3. CALCULATE expiration:
   expires_at = datetime.utcnow() + timedelta(seconds=settings.task_suspend_timeout)

4. PERSIST to database:
   await self._db.execute(
       "INSERT INTO suspended_tasks (task_id, poc_email, created_at, expires_at) VALUES (?, ?, ?, ?)",
       (task_id, poc_email, datetime.utcnow(), expires_at)
   )

5. LOG:
   logger.info(f"Task {task_id} suspended waiting for reply from {poc_email}")
```

### Handle Webhook

```
ALGORITHM: HandleWebhook

INPUT: webhook_payload {event, email_id, from, to, subject, ...}
OUTPUT: None (async processing)

1. EXTRACT sender:
   poc_email = webhook_payload["from"].lower()

2. LOOKUP task:
   task_id = self._poc_to_task.get(poc_email)
   if task_id is None:
       logger.warning(f"No suspended task for POC: {poc_email}")
       return  # Orphan webhook, ignore

3. VERIFY not expired:
   task_record = await self._get_suspended_task(task_id)
   if task_record.is_expired():
       logger.warning(f"Task {task_id} expired, ignoring webhook")
       await self._cleanup_expired_task(task_id)
       return

4. UNREGISTER from suspended state:
   del self._poc_to_task[poc_email]
   await self._db.execute("DELETE FROM suspended_tasks WHERE task_id = ?", (task_id,))

5. RESUME graph execution (background):
   asyncio.create_task(self._resume_task(task_id, webhook_payload))

6. LOG:
   logger.info(f"Resuming task {task_id} with webhook from {poc_email}")
```

### Resume Task (Background)

```
ALGORITHM: ResumeTaskBackground

INPUT: task_id, webhook_payload
OUTPUT: None (stores result in database)

1. CREATE config:
   config = {"configurable": {"thread_id": task_id}}

2. CREATE resume command:
   command = Command(resume=webhook_payload)

3. TRY execute resumed graph:
   final_state = None
   async for event in self.graph.astream(command, config=config):
       for node_name, node_output in event.items():
           if node_name in ("handle_success", "handle_failure"):
               final_state = node_output
           # Check for another interrupt (retry scenario)
           if is_interrupt(event):
               # Re-suspend with new POC if needed
               await self._handle_re_suspend(task_id, event)
               return

4. STORE result:
   status = "completed" if final_state.get("success") else "failed"
   await self._db.execute(
       "INSERT INTO task_results (task_id, status, result, completed_at) VALUES (?, ?, ?, ?)",
       (task_id, status, json.dumps(final_state), datetime.utcnow())
   )

5. LOG:
   logger.info(f"Task {task_id} completed with status: {status}")

CATCH Exception as e:
   logger.error(f"Task {task_id} failed during resume: {e}")
   await self._db.execute(
       "INSERT INTO task_results (task_id, status, result, completed_at) VALUES (?, ?, ?, ?)",
       (task_id, "failed", json.dumps({"error": str(e)}), datetime.utcnow())
   )
```

---

## API Contracts

### 1. Send Message (SSE Streaming)

**Endpoint:** `POST /` (JSON-RPC over HTTP with SSE response)

**Request:**
```json
{
  "jsonrpc": "2.0",
  "id": "req-123",
  "method": "message/stream",
  "params": {
    "message": {
      "role": "user",
      "parts": [
        {
          "kind": "text",
          "text": "Send email to poc@example.com asking for Q4 sales data"
        }
      ]
    }
  }
}
```

**Response:** SSE Stream

```
event: status
data: {"task_id": "abc-123", "state": "working", "message": "Parsing instruction..."}

event: status
data: {"task_id": "abc-123", "state": "working", "message": "Composing email to poc@example.com"}

event: status
data: {"task_id": "abc-123", "state": "working", "message": "Sending email..."}

event: suspended
data: {"task_id": "abc-123", "state": "suspended", "poc_email": "poc@example.com", "message": "Waiting for reply. Poll GET /tasks/abc-123 for result."}

[CONNECTION CLOSES]
```

### 2. Get Task Status (Polling)

**Endpoint:** `GET /tasks/{task_id}`

**Response (Suspended):**
```json
{
  "task_id": "abc-123",
  "status": "suspended",
  "poc_email": "poc@example.com",
  "created_at": "2025-12-15T10:00:00Z",
  "expires_at": "2025-12-15T11:00:00Z",
  "message": "Waiting for reply from poc@example.com"
}
```

**Response (Completed):**
```json
{
  "task_id": "abc-123",
  "status": "completed",
  "completed_at": "2025-12-15T10:35:00Z",
  "result": {
    "success": true,
    "data": "Q4 sales data: $1.2M revenue...",
    "poc_email": "poc@example.com",
    "attempts": 1
  }
}
```

**Response (Failed):**
```json
{
  "task_id": "abc-123",
  "status": "failed",
  "completed_at": "2025-12-15T11:00:00Z",
  "error": "Task expired: no reply received within 1 hour"
}
```

**Response (Not Found):**
```json
{
  "error": "Task not found",
  "task_id": "abc-123"
}
```

### 3. Webhook (from Mock SMTP)

**Endpoint:** `POST /webhook`

**Request:**
```json
{
  "event": "email.received",
  "email_id": "email-456",
  "from": "poc@example.com",
  "to": ["agent@mail.local"],
  "subject": "Re: Q4 Sales Data Request",
  "received_at": "2025-12-15T10:30:00Z",
  "body_preview": "Hi, here's the Q4 data you requested..."
}
```

**Response:**
```json
{
  "status": "accepted",
  "task_id": "abc-123",
  "message": "Task resumed"
}
```

**Response (No matching task):**
```json
{
  "status": "ignored",
  "message": "No suspended task for sender: poc@example.com"
}
```

---

## Configuration

```python
# config.py additions

class Settings(BaseSettings):
    # ... existing settings ...

    # Database
    database_path: str = Field(
        default="mail_agent.db",
        description="SQLite database path for checkpoints and task state"
    )

    # Task timeout
    task_suspend_timeout_seconds: int = Field(
        default=3600,  # 1 hour
        description="Maximum time a task can be suspended waiting for reply"
    )

    # Cleanup
    expired_task_cleanup_interval_seconds: int = Field(
        default=300,  # 5 minutes
        description="Interval for cleaning up expired tasks"
    )

    class Config:
        env_prefix = "MAIL_AGENT_"
```

### Environment Variables

```bash
# Task suspension timeout (1 hour default)
MAIL_AGENT_TASK_SUSPEND_TIMEOUT_SECONDS=3600

# Database path
MAIL_AGENT_DATABASE_PATH=mail_agent.db

# Cleanup interval
MAIL_AGENT_EXPIRED_TASK_CLEANUP_INTERVAL_SECONDS=300
```

---

## Directory Structure

### New/Modified Files

```
src/mail_agent/
├── main.py                      # CLI entrypoint (minor updates)
├── config.py                    # Settings (add new fields)
├── agent/
│   ├── graph.py                 # MODIFY: Add checkpointer support
│   ├── state.py                 # AgentState (unchanged)
│   └── nodes/
│       ├── wait_for_reply.py    # REWRITE: Use interrupt() pattern
│       └── ...                  # Other nodes (unchanged)
├── a2a/
│   ├── server.py                # MODIFY: Update for SSE streaming
│   ├── executor.py              # MODIFY: Handle interrupts, emit SSE
│   └── routes/                  # NEW: REST endpoints
│       ├── __init__.py
│       └── tasks.py             # GET /tasks/{id}
├── persistence/                 # NEW: Database layer
│   ├── __init__.py
│   ├── database.py              # Async SQLite connection manager
│   ├── checkpointer.py          # LangGraph AsyncSqliteSaver setup
│   └── task_store.py            # Suspended tasks & results CRUD
├── task_manager/                # NEW: Task lifecycle management
│   ├── __init__.py
│   ├── manager.py               # TaskManager class
│   └── models.py                # TaskStatus, SuspendedTask models
└── webhook/
    ├── server.py                # MODIFY: Call TaskManager.handle_webhook
    └── router.py                # DELETE: No longer needed
```

### Files to Delete

```
src/mail_agent/webhook/router.py  # TaskRouter replaced by TaskManager
```

---

## Algorithms

### A2A Executor with SSE

```
ALGORITHM: ExecuteWithSSE

INPUT: request_context, event_queue (A2A SDK)
OUTPUT: None (streams events via SSE)

1. EXTRACT instruction from A2A message:
   message = request_context.message
   instruction = extract_text(message.parts)

2. GENERATE task_id:
   task_id = str(uuid4())

3. CREATE initial state:
   initial_state = {
       "instruction": instruction,
       "task_id": task_id,
       "current_poc": None,
       "attempts": 0,
       ...
   }

4. CREATE config:
   config = {"configurable": {"thread_id": task_id}}

5. EMIT initial event:
   await event_queue.enqueue(TaskStatusUpdate(
       task_id=task_id,
       state="working",
       message="Starting task..."
   ))

6. STREAM graph execution:
   async for event in graph.astream(initial_state, config=config):
       for node_name, node_output in event.items():

           # Emit progress
           await event_queue.enqueue(TaskStatusUpdate(
               task_id=task_id,
               state="working",
               message=f"Executing {node_name}..."
           ))

           # Check for interrupt
           if is_interrupt_event(event):
               interrupt_data = extract_interrupt_data(event)

               # Register with TaskManager
               await task_manager.suspend_task(
                   task_id=task_id,
                   poc_email=interrupt_data["poc_email"]
               )

               # Emit suspended event
               await event_queue.enqueue(TaskStatusUpdate(
                   task_id=task_id,
                   state="suspended",
                   message=f"Waiting for reply from {interrupt_data['poc_email']}",
                   poc_email=interrupt_data["poc_email"]
               ))

               # Close stream (client is free)
               return

           # Check for completion
           if node_name in ("handle_success", "handle_failure"):
               await event_queue.enqueue(TaskStatusUpdate(
                   task_id=task_id,
                   state="completed",
                   result=node_output
               ))
               return

7. HANDLE unexpected completion:
   await event_queue.enqueue(TaskStatusUpdate(
       task_id=task_id,
       state="failed",
       error="Graph completed without final node"
   ))
```

### Expired Task Cleanup

```
ALGORITHM: CleanupExpiredTasks

RUN: Every 5 minutes (background task)

1. QUERY expired tasks:
   expired = await db.execute(
       "SELECT task_id, poc_email FROM suspended_tasks WHERE expires_at < ?",
       (datetime.utcnow(),)
   )

2. FOR each expired task:
   a. REMOVE from in-memory mapping:
      if task.poc_email in self._poc_to_task:
          del self._poc_to_task[task.poc_email]

   b. DELETE checkpoint:
      await checkpointer.adelete(task.task_id)

   c. STORE failure result:
      await db.execute(
          "INSERT INTO task_results (task_id, status, result, completed_at) VALUES (?, ?, ?, ?)",
          (task.task_id, "failed", '{"error": "Task expired"}', datetime.utcnow())
      )

   d. DELETE from suspended_tasks:
      await db.execute("DELETE FROM suspended_tasks WHERE task_id = ?", (task.task_id,))

   e. LOG:
      logger.info(f"Cleaned up expired task: {task.task_id}")
```

---

## Error Handling

### Error Categories

| Error | Location | Handling |
|-------|----------|----------|
| **Graph execution error** | Executor | Emit `failed` event, store error in results |
| **Checkpoint save failure** | Checkpointer | Retry once, then fail task |
| **Webhook for unknown POC** | TaskManager | Log warning, return "ignored" |
| **Task expired** | Cleanup job | Store failure result, cleanup checkpoint |
| **Database connection error** | All | Retry with backoff, fail if persistent |
| **Resume failure** | TaskManager | Store error in results |

### Error Response Format

```json
{
  "task_id": "abc-123",
  "status": "failed",
  "error": {
    "code": "TASK_EXPIRED",
    "message": "Task expired: no reply received within 1 hour",
    "details": {
      "poc_email": "poc@example.com",
      "created_at": "2025-12-15T10:00:00Z",
      "expired_at": "2025-12-15T11:00:00Z"
    }
  }
}
```

---

## Files to Create/Modify

### New Files

| File | Purpose |
|------|---------|
| `src/mail_agent/persistence/__init__.py` | Package init |
| `src/mail_agent/persistence/database.py` | Async SQLite connection manager |
| `src/mail_agent/persistence/checkpointer.py` | LangGraph checkpointer setup |
| `src/mail_agent/persistence/task_store.py` | Task state CRUD operations |
| `src/mail_agent/task_manager/__init__.py` | Package init |
| `src/mail_agent/task_manager/manager.py` | TaskManager class |
| `src/mail_agent/task_manager/models.py` | Pydantic models for task state |
| `src/mail_agent/a2a/routes/__init__.py` | Package init |
| `src/mail_agent/a2a/routes/tasks.py` | GET /tasks/{id} endpoint |

### Modified Files

| File | Changes |
|------|---------|
| `src/mail_agent/config.py` | Add database_path, task_suspend_timeout_seconds |
| `src/mail_agent/agent/graph.py` | Accept checkpointer, compile with it |
| `src/mail_agent/agent/nodes/wait_for_reply.py` | Use `interrupt()` instead of queue wait |
| `src/mail_agent/a2a/server.py` | Initialize TaskManager, mount task routes |
| `src/mail_agent/a2a/executor.py` | Handle interrupt events, emit SSE |
| `src/mail_agent/webhook/server.py` | Call TaskManager.handle_webhook |
| `pyproject.toml` | Add new dependencies |

### Deleted Files

| File | Reason |
|------|--------|
| `src/mail_agent/webhook/router.py` | Replaced by TaskManager |

---

## Summary

| Aspect | Before | After |
|--------|--------|-------|
| **Client blocking** | Blocks for entire execution (hours) | SSE stream, closes on suspend |
| **wait_for_reply** | `asyncio.Queue.get()` blocking | `interrupt()` with checkpoint |
| **State persistence** | None (in-memory only) | SQLite checkpointer |
| **Timeout** | 300 seconds (fails) | 1 hour (configurable) |
| **Client notification** | None until done | Real-time SSE events |
| **Result retrieval** | Same HTTP response | Poll `GET /tasks/{id}` |
| **Concurrency** | TaskRouter queues | Task IDs + checkpoints |

**Key Benefits:**
1. Client gets immediate feedback via SSE
2. Connection closes when waiting for human (no timeout issues)
3. Agent state survives server restarts
4. Simple polling for result retrieval
5. Clean separation of concerns
