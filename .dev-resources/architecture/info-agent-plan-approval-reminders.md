# Info Agent — Plan Approval, Clarifications, and Reminders (Finalized Architecture)

## Context
This document describes the finalized approach to add three capabilities to the existing brownfield system:
1) **Agent-proposed execution plan + end-user approval gate** (confirm/reject with feedback).
2) **POC clarification handling** (POC can reply with questions; agent answers and continues).
3) **Configurable auto-reminders** while waiting for POC replies (defaults from `.env`, user-request overrides via LLM).

This is an architecture + algorithms artifact. It intentionally avoids implementation code.

---

## Goals (Finalized Requirements)
- The agent reads a user request, compiles a deterministic, minimal plan, and shows it to the user for approval.
- The user can approve the plan to proceed or reject it with feedback; the agent iterates and proposes a new plan.
- The agent can ask/answer clarifying questions with POCs over email while executing the plan.
- The agent validates data **LLM-first** (no manual override).
- While waiting for replies, the agent auto-reminds on a configurable cadence:
  - **Default** cadence and limits come from `.env`.
  - If the user’s request includes timing instructions (e.g., “remind every 2 minutes”), the agent uses LLM-extracted values (with guardrails from `.env`).

## Non-Goals (Explicitly Out of Scope for PoC)
- Prompt-injection hardening for email content/attachments.
- Webhook deduplication/idempotency beyond existing behavior.
- Manual “accept anyway” overrides for validation edge cases.
- Plan diff UX (no diffs required when regenerating).

---

## Existing System (Brownfield Baseline)
### Services
- **UI Server** (`src/ui/`): FastAPI + Jinja2 templates + HTMX + Tailwind, runs on port 8080.
- **Mail Agent** (`src/mail_agent/`): LangGraph-based orchestration; exposes A2A JSON-RPC + REST task APIs + SSE; runs on port 8000; webhook listener on 9000.
- **Mock SMTP** (`src/mock_smtp/`): aiosmtpd + FastAPI REST API + webhook dispatcher; SMTP 1025, REST 8025.

### Key Execution Building Blocks Already Present
- **LangGraph interrupt/resume** for non-blocking “wait for reply” behavior.
- **TaskManager** that:
  - persists task checkpoints and suspended state,
  - resumes tasks when webhooks arrive (POC replies),
  - exposes `GET /api/tasks/{task_id}` and `GET /api/tasks/{task_id}/progress` (SSE).
- **Multi-contact contract** compilation (LLM structured output) and global validation.
- **Email send + webhook register** through Mock SMTP REST.

---

## Proposed Architecture (Lean Extension)
### High-Level Approach
Reuse the existing, battle-tested primitives:
- Use **LangGraph interrupts** for new wait states:
  - `awaiting_plan_approval`
  - `need_user_input` (escalation when POC asks an unanswerable question)
- Use **TaskManager** for new non-webhook resumptions:
  - resume by UI action (approve/reject/feedback),
  - schedule reminders via a background tick loop.

No new services are introduced.

---

## Execution Flows (ASCII)

### 1) Plan Proposal → Approve/Reject → Execute
```
End User (UI)                      Mail Agent (A2A + LangGraph)                 Mock SMTP
--------------                    ---------------------------                 --------
/send instruction  --------------> parse_instruction
                                   compile_contract (+plan +assumptions +reminder_policy)
                                   INTERRUPT: awaiting_plan_approval

UI renders plan:
  [Approve] [Reject + Feedback]

Approve/Reject  -----------------> TaskManager resumes graph with decision

If approved:
                                   orchestrate
                                   compose_email/send_email ------------------> POST /api/send
                                   INTERRUPT: waiting_for_any_reply  <-------- webhook POST (email received)
                                   fetch/extract/classify/validate (LLM-first)
                                   validate_global
                                   send_final_outputs -----------------------> POST /api/send
                                   COMPLETE

If rejected:
                                   compile_contract_again(original_request + feedback)
                                   INTERRUPT: awaiting_plan_approval (new plan)
```

### 2) POC Clarification Question Loop
```
POC replies with a question -> webhook -> resume task
  fetch_email -> extract_content -> classify_reply
    if clarification_question:
      if answerable from contract:
        compose_answer_email -> send_email -> set POC back to waiting
      else:
        INTERRUPT: need_user_input (question + suggested defaults)
```

### 3) Auto-Reminder Loop While Waiting
```
Task is suspended (waiting_for_any_reply)
TaskManager background tick (every T seconds):
  for each waiting POC:
    if now - last_outbound_email >= interval and reminders_sent < max:
      send reminder email
    if reminders_sent == max:
      INTERRUPT UI: need_user_input (POC non-responsive)
```

---

## Agent State Machine (Conceptual)
### Core Nodes (Existing + New)
- Existing:
  - `parse_instruction`
  - `compile_contract`
  - `orchestrate`
  - `compose_email` → `send_email`
  - `wait_for_any_reply` → `fetch_email` → `extract_content`
  - `validate_response` (LLM-based)
  - `validate_global` (LLM-based)
  - `send_final_outputs`
  - follow-up/receipt/success reply nodes
- New (conceptual):
  - `wait_for_plan_approval` (interrupt)
  - `compile_contract_again` (same capability as compile with feedback input)
  - `classify_reply` (LLM structured output)
  - `handle_clarification` (answer or escalate to user)

### State Transition Sketch
```
START
  -> parse_instruction
  -> compile_contract
  -> wait_for_plan_approval (interrupt)
       approved -> orchestrate
       rejected -> compile_contract_again -> wait_for_plan_approval (interrupt)

orchestrate
  -> dispatch pending emails OR wait_for_any_reply (interrupt) OR validate_global OR send_final_outputs

on reply resume:
  -> fetch_email -> extract_content -> classify_reply
       clarification -> handle_clarification -> orchestrate (waiting)
       redirect       -> handle_redirect -> orchestrate
       data           -> validate_response -> follow-up/success -> orchestrate
```

---

## Data Contracts (Conceptual)

### 1) Plan Artifact (Agent → UI)
The plan must be a structured artifact derived from the compiled contract:
- `agent_plan_steps[]`: ordered, human-readable checklist for UI
- `assumptions[]`: explicit assumptions inferred by LLM
- `poc_plans[]`: who will be contacted for what
- `delivery_recipients[]` + `delivery_description`
- `global_success_criteria`
- `reminder_policy` (effective policy computed from `.env` defaults and/or LLM parsing)

### 2) Reply Classification Output (LLM structured)
Purpose: treat “question vs data vs redirect” as first-class.
- `kind`: `data | clarification_question | redirect`
- `question_text` (when clarification_question)
- `redirect_email` + `redirect_reason` (when redirect)
- `notes` (optional)

### 3) Reminder Policy Output (LLM structured)
Derived from user request text when present; otherwise `.env` defaults apply.
- `enabled`: boolean
- `interval_seconds`: integer
- `max_reminders_per_poc`: integer
- `first_reminder_delay_seconds`: optional (if user asks “wait X then start reminders”)

### 4) Task Decision Payloads (UI → Agent resume)
- `plan_decision`:
  - `decision`: `approve | reject`
  - `feedback`: string (required on reject)

---

## API Contracts and Integration Points

### A) UI → Mail Agent (A2A JSON-RPC)
- **Endpoint**: `POST /` (JSON-RPC 2.0)
- **Method**: `message/send`
- **Input**: user instruction (text)
- **Output**: initial response; UI uses task APIs + SSE for progress thereafter

### B) UI → Mail Agent (Existing Task APIs)
- `GET /api/tasks`
- `GET /api/tasks/{task_id}`
- `GET /api/tasks/{task_id}/progress` (SSE)

### C) UI → Mail Agent (New Plan Approval APIs)
1) **Get current plan**
- `GET /api/tasks/{task_id}/plan`
- Returns: plan artifact + `plan_status` (`pending_approval | approved | rejected | regenerating`)

2) **Approve or reject**
- `POST /api/tasks/{task_id}/plan/decision`
- Request body:
  - `decision`: `approve | reject`
  - `feedback`: string (required for reject)
- Behavior:
  - `approve`: resumes graph from `awaiting_plan_approval`
  - `reject`: resumes graph with feedback; agent regenerates plan and re-suspends

### D) Mail Agent → Mock SMTP (Existing)
- Send email: `POST {mock_smtp_api_url}/api/send`
- Register webhook: `POST {mock_smtp_api_url}/api/webhooks`

### E) Mock SMTP → Mail Agent (Webhook callback)
- `POST {webhook_url}{webhook_path}` with payload describing the received email

---

## UI/UX Changes (High-Level)
### /send Page
- Replace “Expected Agent Plan (optional)” input with:
  1) user instruction input
  2) submit button
  3) plan display panel once computed
  4) actions:
     - **Approve** (continue execution)
     - **Reject** + feedback textbox (agent regenerates plan)

### Dashboard / Task Detail
- Show:
  - current plan status,
  - reminder policy (effective),
  - per-POC status (pending/waiting/validating/success/follow-up attempts),
  - current “waiting for” POCs,
  - progress log via SSE.

---

## Configuration (.env Driven Defaults + Guardrails)
All defaults are set via `.env` and documented in `.env.example`.

### Reminder Defaults
- `REMINDER_DEFAULT_ENABLED=true`
- `REMINDER_DEFAULT_INTERVAL_SECONDS=7200` (2 hours)
- `REMINDER_MAX_PER_POC=3`
- `REMINDER_SCHEDULER_TICK_SECONDS=60`

### Reminder Guardrails for LLM-Parsed Intervals
- `REMINDER_MIN_INTERVAL_SECONDS=60`
- `REMINDER_MAX_INTERVAL_SECONDS=86400`

### Task Suspension TTL (Optional but recommended)
- `TASK_SUSPEND_TTL_SECONDS=86400` (example)

### Precedence Rules (Effective Policy)
1) If user request includes explicit reminder cadence → use LLM-extracted values (clamped by min/max).
2) Else → use `.env` defaults.
3) Persist effective policy in task state; display it in the plan before approval.

---

## LLM-First Validation Strategy
### Per-POC Validation
- The LLM evaluates extracted payload vs per-POC success criteria.
- Output is strict pass/fail + missing_items and feedback.
- No “accept anyway”.

### Global Validation
- When all required POC contributions exist, LLM validates combined payload vs global criteria.
- If fail: LLM returns targeted corrections per POC; agent sends targeted follow-ups.

---

## Operational Considerations (PoC-Appropriate)
### Observability
- SSE remains the primary UI feedback loop.
- Add explicit progress events for:
  - `plan_ready`
  - `plan_approved` / `plan_rejected`
  - `reminder_sent` (with count)
  - `clarification_answered` / `needs_user_input`

### Failure Handling
- If a POC is non-responsive after `REMINDER_MAX_PER_POC` reminders:
  - interrupt UI (`need_user_input`) with options (wait longer / change approach / abort).
- If email parsing fails:
  - still run LLM validation on body text (fallback behavior is acceptable for PoC).

---

## Technology Stack / Frameworks / SDKs (Final)
- **Python 3.12+**
- **FastAPI** (UI server, task APIs, webhook receiver)
- **Starlette** (A2A app runtime)
- **Uvicorn** (ASGI server)
- **LangGraph** + **langgraph-checkpoint-sqlite** (graph orchestration + persistence)
- **LangChain** providers (**langchain-openai**, **langchain-google-genai**) (LLM structured output)
- **Pydantic v2** (contracts + schemas)
- **httpx** (service-to-service HTTP)
- **A2A SDK** (`a2a-sdk[http-server]`) (JSON-RPC + protocol server)
- **SSE** (progress streaming)
- **HTMX + Jinja2 + Tailwind** (UI interactions)
- **Mock SMTP**: **aiosmtpd** + FastAPI REST + webhook dispatcher

---

## Implementation Footprint (Where Changes Land)
This is not code, but the intended modification points are:
- **UI**: `/send` page workflow + new plan approval actions.
- **Mail Agent graph**: insert `wait_for_plan_approval`; add reply classification and clarification handling.
- **TaskManager**: add UI-driven resume endpoint support and reminder scheduler loop driven by `.env` + LLM overrides.
- **Config**: add `.env` settings and `.env.example` documentation for reminder defaults/guardrails.

