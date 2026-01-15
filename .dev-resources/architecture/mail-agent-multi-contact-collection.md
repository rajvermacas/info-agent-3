# Mail Agent - Multi-Contact Collection, Merge, and Validation (Contract-Driven)

## Overview

This document defines the finalized architecture for enabling the Mail Agent to:

- Split a single user request into **multiple contact-specific sub-requests** (field/data partitions).
- Collect partial data from each point-of-contact (POC) **in parallel**.
- **Merge** the partial results into a single dataset using deterministic rules.
- **Validate** the merged dataset against the user’s intent.
- **Emit no artifact** (e.g., CSV) unless the dataset is **fully valid**.
- Run fully autonomously with an enforced ceiling of **10 chase rounds per POC**.
- Provide **replayability** (rerun the same contract) and **audit exports** (complete provenance).

The core design pattern is a **Prompt → Contract compiler** (LLM) followed by a **deterministic workflow** (LangGraph) that executes and enforces the contract.

---

## Requirements (Final)

### Functional

1. **Free-text user requests** drive behavior (example: “send mail to raj@gmail.com asking 10 animal names in a csv file with the animal name and cost”).
2. The system can request **different subsets** of required data from **multiple POCs**, then validate the combined dataset.
3. If contacts provide overlapping/conflicting data, the agent **emails the involved POCs** and iterates until resolved or max rounds reached.
4. **No human-in-the-loop** after request submission.
5. **No artifact output** unless the final dataset passes validation.
6. **Chase policy**: max **10 rounds per POC**; after that, **fail** with no artifact.
7. CSV acceptance must be **strict enough** to ensure correctness, but **flexible** on representational details (header variants, ordering, quoting, currency symbols, delimiters).
8. Support **replayability** (rerun with the same contract) and **audit exports**.

### Non-Functional

- Lean architecture: reuse existing Mail Agent services (A2A, webhook, LangGraph checkpointing).
- Deterministic validation: enforcement is machine-checkable, not prose-based.
- Strong traceability: every extracted value includes provenance (message id, POC, timestamp).

---

## Consolidated Design Decisions

| Decision | Choice |
|---|---|
| Orchestration | LangGraph state machine with parallel POC branches |
| Planning | LLM compiles free-text prompt into a machine-checkable contract |
| Autonomy | Fully autonomous (no user confirmations mid-flight) |
| Output gating | Emit artifact only if validation passes |
| Chase limit | Max 10 rounds per POC |
| Conflict handling | Email all involved POCs with competing candidates; re-validate after each reply |
| CSV strictness | Strict semantic rubric; flexible parsing/normalization |
| Persisted state | Contract + runs + message/event log in DB for replay and audit |
| UX/telemetry | SSE progress updates + machine-readable deficits and assumptions |

---

## Technology Stack (Frameworks, Libraries, SDKs)

| Layer | Technology | Purpose |
|---|---|---|
| Workflow | LangGraph | State machine, branching, retries, checkpoint/resume |
| Checkpointing | langgraph-checkpoint-sqlite (or equivalent) | Persist/restore graph execution |
| API server | FastAPI + Uvicorn | A2A JSON-RPC, SSE status, inbound webhook |
| A2A Protocol | a2a-sdk (http-server) | Standardized JSON-RPC 2.0 agent interface |
| HTTP client | httpx | Mock SMTP REST API, any internal HTTP calls |
| Contracts | Pydantic + JSON Schema | Typed contract, schema validation, structured outputs |
| CSV parsing | Python `csv` module | Flexible dialect parsing and normalization |
| Email parsing | Python `email` stdlib / mailparser | Parse inbound messages + attachments |
| Persistence | SQLite/Postgres | Contracts, runs, events, messages, artifacts metadata |
| Streaming | SSE (e.g., sse-starlette) | Real-time progress updates |
| LLM SDK | Provider SDK via existing LangChain integration | Structured outputs: contract + extractions |

Notes:
- Exact provider selection is a deployment choice; this architecture assumes structured outputs are available.

---

## Port Allocation (Current System)

This feature reuses the existing port layout described in the Mail Agent architecture docs:

| Component | Port | Purpose |
|---|---:|---|
| Mock SMTP (SMTP) | 1025 | Receives inbound email (POC replies) |
| Mock SMTP (REST API) | 8025 | Send emails / fetch inboxes / webhook registration |
| Mail Agent (A2A JSON-RPC) | 8000 | External task API (start/status/rerun/export) |
| Mail Agent (Inbound Webhook) | 9000 | Receives inbound email notifications |

---

## High-Level Component Architecture

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                               MAIL AGENT SERVER                               │
│                                                                              │
│  ┌───────────────────────┐     ┌──────────────────────────────────────────┐  │
│  │ A2A JSON-RPC API       │     │ Workflow Orchestrator (LangGraph)        │  │
│  │ - start_from_prompt    │────▶│ - compile_contract node                  │  │
│  │ - rerun                │     │ - dispatch node (parallel POCs)          │  │
│  │ - export_audit         │     │ - wait/ingest/extract/validate nodes     │  │
│  │ - status/SSE           │     │ - chase loop + conflict loop             │  │
│  └───────────────────────┘     └──────────────────────────────────────────┘  │
│                 ▲                                   │                         │
│                 │ SSE                               │ checkpoint/resume       │
│                 │                                   ▼                         │
│        ┌──────────────────┐              ┌───────────────────────┐           │
│        │ Status Stream     │              │ Persistence Store      │           │
│        │ (SSE)             │              │ - contract snapshots   │           │
│        └──────────────────┘              │ - runs + events log    │           │
│                                          │ - messages + artifacts │           │
│                                          └───────────────────────┘           │
│                                                                              │
│  ┌───────────────────────────────┐         ┌──────────────────────────────┐  │
│  │ Inbound Email Webhook (:9000)  │◀────────│ Mock SMTP / Email Provider   │  │
│  │ - correlate workflow/run       │         │ (outbound + inbound)         │  │
│  │ - store message + payload      │         └──────────────────────────────┘  │
│  └───────────────────────────────┘                                            │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## Execution Flows

### Flow A: Happy Path (Single POC, Valid CSV on First Try)

```
User Prompt
  |
  v
[Compile Contract]
  |
  v
[Send Email round=1] ---> POC replies with CSV
  |
  v
[Ingest + Extract + Normalize]
  |
  v
[Validate vs Contract] ---> PASS
  |
  v
Emit CSV + Done
```

### Flow B: Multi-POC Partition, Merge, and Validate

```
User Prompt
  |
  v
[Compile Contract]
  - infer schema + constraints + join keys
  - route field_groups to POCs
  |
  v
[Parallel Dispatch]
  |------------------> POC A provides subset
  |------------------> POC B provides subset
  |
  v
[Ingest + Extract both]
  |
  v
[Merge (join strategy)]
  |
  v
[Validate vs Contract] ---> PASS
  |
  v
Emit CSV + Done
```

### Flow C: Conflict Loop (No Human-in-the-loop, Email POCs Until Resolved)

```
[Validate] -> conflict detected on field(s)
  |
  v
[Conflict Email to Involved POCs]
  - include competing candidates + strict reply format
  |
  v
Inbound replies (round increments)
  |
  v
[Re-extract + Re-validate]
  |
  +--> PASS -> Emit + Done
  |
  +--> conflict persists AND any POC rounds <= 10 -> repeat loop
  |
  +--> any POC rounds > 10 -> Fail (no CSV)
```

### Flow D: Format Failure → Stricter Template After Round 2

```
Round 1: POC replies with malformed/incorrect CSV
  |
  v
Validator produces deficits (e.g., header mismatch, row_count mismatch)
  |
  v
Round 2: targeted follow-up
  |
  v
Round 3+: switch to strict template + example CSV snippet
  |
  v
Continue until PASS or rounds > 10
```

### Flow E: Replayability and Audit Export

```
contract_id created (immutable snapshot)
  |
  +--> run_id=run_001 executes workflow
  |
  +--> rerun(contract_id) -> run_id=run_002 executes same contract again
  |
  +--> export_audit(workflow_id) -> contract + event log + messages + validations
```

---

## Contract-Driven Design

### Why a Contract is Required

To support arbitrary user requirements with deterministic enforcement, the system needs a structured intermediate representation (Contract) that:

- Makes implicit assumptions explicit.
- Defines machine-checkable validation rules (rubric).
- Defines routing (field_groups → POCs).
- Defines tolerances for flexible parsing (CSV acceptance).
- Defines chase and termination policies.

### Contract Contents (Conceptual)

1. **Deliverable spec**: artifact type (CSV), gating policy (emit only if valid).
2. **Schema**: canonical columns/fields, types, requiredness.
3. **Rubric**: deterministic checks (row counts, uniqueness, allowed values, ranges, cross-field constraints).
4. **Tolerances**: header synonyms, delimiter set, currency normalization.
5. **Routing**: field_groups mapped to POCs, including join strategy for merges.
6. **Policies**: max rounds per POC, strict-template trigger, SLA if applicable.
7. **Assumptions**: inferred constraints with confidence scores (auditable).

---

## Algorithms (No Code)

### 1) Prompt → Contract Compilation (LLM Structured Output)

Input: free-text prompt.

Algorithm:
1. Extract contacts (emails), deliverable type (CSV/text), and data request intent.
2. Infer schema candidates:
   - columns/fields, types, requiredness
   - examples of valid values (for extraction hints)
3. Infer constraints from prompt and common sense:
   - “10 animal names” → `row_count = 10` and likely uniqueness (record as assumption if not explicit)
4. If multi-POC is implied:
   - infer a partition plan (field_groups) and a merge/join strategy
5. Emit deterministic rubric rules + tolerance policy:
   - strict semantic checks, flexible parsing allowances
6. Output contract with:
   - assumptions[] and confidence for each inference
   - “strict_template_after_round = 2”

### 2) Routing and Dispatch (Parallel POCs)

Algorithm:
1. For each field_group in contract.routing:
   - generate an email prompt specific to that POC and field_group
   - include correlation metadata (workflow_id, run_id, poc_id, round)
2. Send all POC emails concurrently.

### 3) Ingest + Correlate Inbound Email

Algorithm:
1. Receive inbound webhook payload.
2. Resolve to workflow/run using correlation metadata (headers/subject token fallback).
3. Store raw message + attachments metadata.
4. Trigger workflow resume from checkpoint.

### 4) Extraction + Normalization (CSV-Focused)

Algorithm:
1. Select candidate CSV attachment deterministically:
   - prefer attachment with best header match to canonical schema
2. Decode with charset fallbacks.
3. Dialect sniff:
   - delimiter in {`,`, `;`, `\\t`, `|`}
4. Canonicalize headers:
   - lowercase, trim, replace separators with `_`
   - apply header_synonyms mapping from contract.tolerances
5. Parse rows and normalize cells:
   - trim whitespace, normalize numbers
   - optional currency normalization (strip symbols, parse numeric)
6. Produce structured table:
   - `rows[]`, per-field parse errors, provenance references

### 5) Merge / Join Across POCs

Algorithm:
1. For each partial dataset from a POC:
   - map to canonical schema keys
2. Apply merge strategy from contract:
   - join by a stable key if available
   - if join is ambiguous, record deficit `join_failure`
3. Maintain provenance per field value:
   - `{value, source_poc, message_id, received_at}`

### 6) Validation (Hard Gate)

Algorithm:
1. Run rubric rules in deterministic order:
   - required columns present
   - type checks after normalization
   - row count constraints
   - uniqueness constraints (if present or inferred)
   - cross-field constraints (if present)
2. Produce `ValidationReport`:
   - `status: PASS|FAIL`
   - deficits: missing, invalid_format, conflicts, join_failures
3. If PASS:
   - emit canonical CSV artifact
4. If FAIL:
   - compute targeted next actions for chase loop

### 7) Chase Loop (Max 10 Rounds per POC)

Algorithm:
1. For each deficit, assign the “best” POC(s) to address it:
   - missing fields → routed POC
   - conflicts → all involved POCs
   - format issues → POC that produced invalid artifact
2. Increment `rounds[poc]` when sending follow-up.
3. After round 2 for a POC:
   - switch to stricter template + include example CSV snippet
4. Stop conditions:
   - PASS → emit CSV
   - any `rounds[poc] > 10` → FAIL with no CSV

---

## API Contracts (Integration Points)

The system uses the existing A2A/JSON-RPC and webhook pattern and adds methods oriented around contract/run lifecycle.

### 1) Start a Workflow From a Free-Text Prompt (A2A JSON-RPC)

**Method**: `workflow.start_from_prompt`

**Params**
- `prompt`: string
- `max_rounds_per_poc`: integer (defaulted by server, but treated as policy)
- `output_policy`: `"emit_only_if_valid"`

**Result**
- `workflow_id`, `contract_id`, `run_id`, `status`

**Example request**
```json
{
  "jsonrpc": "2.0",
  "id": "req_1",
  "method": "workflow.start_from_prompt",
  "params": {
    "prompt": "send mail to raj@gmail.com asking 10 animal names in a csv file with the animal name and cost",
    "max_rounds_per_poc": 10,
    "output_policy": "emit_only_if_valid"
  }
}
```

**Example response**
```json
{
  "jsonrpc": "2.0",
  "id": "req_1",
  "result": {
    "workflow_id": "wf_123",
    "contract_id": "ct_456",
    "run_id": "run_001",
    "status": "planning"
  }
}
```

### 2) Status and Progress (SSE)

**Event**: `workflow.updated`

Payload includes:
- `phase`: planning|collecting|chasing|validating|done|failed_incomplete
- `rounds_by_poc`
- `deficits` (missing, conflicts, invalid_format, join_failures)
- `assumptions` (inferred rules + confidence)

**Example SSE event payload**
```json
{
  "workflow_id": "wf_123",
  "run_id": "run_001",
  "phase": "chasing",
  "rounds_by_poc": {"raj@gmail.com": 3},
  "deficits": {
    "missing": ["cost"],
    "conflicts": [],
    "invalid_format": [],
    "join_failures": []
  },
  "assumptions": [
    {"text": "Interpreted '10 animal names' as unique names", "confidence": 0.7}
  ]
}
```

### 3) Rerun (Replayability)

**Method**: `workflow.rerun`

**Params**
- `contract_id`
- optional overrides (e.g., contact emails)

**Result**
- new `run_id`, status

**Example request**
```json
{
  "jsonrpc": "2.0",
  "id": "req_2",
  "method": "workflow.rerun",
  "params": {
    "contract_id": "ct_456",
    "overrides": {
      "contacts": [{"email": "raj@gmail.com"}]
    }
  }
}
```

**Example response**
```json
{
  "jsonrpc": "2.0",
  "id": "req_2",
  "result": {
    "workflow_id": "wf_123",
    "contract_id": "ct_456",
    "run_id": "run_002",
    "status": "collecting"
  }
}
```

### 4) Audit Export

**Method**: `workflow.export_audit`

**Params**
- `workflow_id`
- `format`: json|zip

**Result**
- contract snapshot + run events + messages + validation reports + emitted artifacts metadata

**Example request**
```json
{
  "jsonrpc": "2.0",
  "id": "req_3",
  "method": "workflow.export_audit",
  "params": {
    "workflow_id": "wf_123",
    "format": "zip"
  }
}
```

### 5) Inbound Email Webhook

**Endpoint**: `POST /webhook/email/inbound`

Required fields:
- `message_id` (idempotency)
- `from`
- `text`
- `attachments[]` (including CSV attachment payload or reference)
- correlation metadata (preferred in headers; subject token fallback)

**Correlation headers (recommended)**
- `X-Workflow-Id`: workflow identifier
- `X-Run-Id`: run identifier
- `X-Poc-Id`: POC identifier (or email)
- `X-Round`: integer round counter

**Example webhook payload**
```json
{
  "message_id": "m_789",
  "from": "raj@gmail.com",
  "subject": "Re: wf_123 run_001 r3",
  "text": "Attached is the CSV.",
  "attachments": [
    {"filename": "animals.csv", "content_base64": "..."}
  ],
  "headers": {
    "X-Workflow-Id": "wf_123",
    "X-Run-Id": "run_001",
    "X-Poc-Id": "raj@gmail.com",
    "X-Round": "3"
  }
}
```

---

## Persistence Model (Replay + Audit)

Minimum persisted entities:

- **Contract**: immutable JSON snapshot (schema, rubric, tolerances, routing, assumptions, policies).
- **Run**: mutable execution instance referencing a contract (run_id, phase, start/end, per-POC rounds).
- **Message**: inbound and outbound email records (raw payload, parsed metadata, correlation ids).
- **Event Log**: append-only workflow transitions and decisions (audit-grade).
- **Validation Report**: per validation attempt (PASS/FAIL, deficits, candidates, reasons).
- **Artifact Record**: emitted CSV metadata (only created on PASS).

Replay rule:
- A rerun creates a new `run_id` referencing the same immutable `contract_id`.

---

## Error Handling and Edge Cases (Deterministic)

1. **Duplicate inbound webhook deliveries**: ignore using `message_id` idempotency.
2. **Multiple attachments**: pick best header-match; if ambiguous, deficit requiring resend with a single attachment.
3. **Non-CSV attachments**: deficit `invalid_format` with explicit guidance.
4. **Ambiguous merge/join**: deficit `join_failure` and chase with a targeted question for a stable join key.
5. **Conflicting values**: conflict emails to all involved POCs; enforce strict response format.
6. **Round exhaustion**: if any POC exceeds 10 rounds, stop with `failed_incomplete` and no artifact.

---

## Constraints and Limitations

- Autonomy with inferred constraints can lead to incorrect assumptions; mitigations are:
  - assumptions recorded with confidence and surfaced in audit/status
  - chase loop can explicitly ask POCs to confirm constraints when conflicts arise
- “Email anyone, no limits” increases blast radius risk; recommended (optional) mitigations:
  - mandatory correlation headers/tokens
  - auditing and administrative monitoring
