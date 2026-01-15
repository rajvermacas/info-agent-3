# Multi-POC Orchestration Architecture

## Overview

This document describes the architecture for enabling the Mail Agent to communicate with **multiple Points of Contact (POCs)** simultaneously or sequentially, collect partial data from each, aggregate responses, and validate against global success criteria. This is a significant enhancement that transforms the agent from single-POC linear flow to a **DAG-based multi-POC orchestration system**.

## Requirements Summary

### Functional Requirements

| Requirement | Description |
|-------------|-------------|
| Multi-POC Communication | Send emails to multiple POCs based on user instruction |
| Dependency-Aware Execution | POCs can depend on data from other POCs |
| Dynamic POC Discovery | Agent can spawn new POCs based on response data |
| Partial Data Collection | Each POC provides subset of required data |
| Per-POC Validation | Validate each POC's contribution individually |
| Global Aggregation | Merge all POC data and validate against overall criteria |
| Conflict Resolution | Detect and resolve contradicting data from different POCs |
| Targeted Retry | Retry only failed/invalid POCs |
| Parallel Execution | Contact independent POCs simultaneously |

### Non-Functional Requirements

| Requirement | Decision |
|-------------|----------|
| Parallel Execution Limit | No limit |
| Dynamic POC Depth | No limit (recursive spawning allowed) |
| Per-POC Retry Budget | 15 attempts per POC |
| Backward Compatibility | None - unified flow (single POC = trivial case) |

---

## Consolidated Design Decisions

| Decision | Choice |
|----------|--------|
| Data Partitioning | User specifies + LLM infers from context |
| Communication Pattern | Dynamic - Parallel OR Sequential based on dependencies |
| Partial Failure Handling | Retry failed POCs only |
| Validation Strategy | Per-POC validation + Final aggregated validation |
| Retry Scope | Per-POC (15 attempts each) |
| Redirect Handling | Per-POC independent redirect |
| Conflict Resolution | LLM decides + re-requests from incorrect POC |
| Success Acknowledgment | Only to POCs with valid data |
| Progress Display | Per-POC + Aggregate + Visual DAG |
| DAG Visualization | Cytoscape.js |
| Dependency Expression | Natural language + LLM inference |

---

## System Architecture

### High-Level Multi-POC Flow

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│                           MULTI-POC ORCHESTRATION SYSTEM                              │
├──────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                       │
│   USER REQUEST                                                                        │
│   "Ask raj@gmail.com for vendor list, then ask each vendor for pricing.              │
│    Also ask priya@gmail.com for budget constraints."                                 │
│                                                                                       │
│   ════════════════════════════════════════════════════════════════════════════════   │
│                                                                                       │
│   ┌─────────────────────────────────────────────────────────────────────────────┐    │
│   │                           PHASE 1: PLANNING                                 │    │
│   │                                                                             │    │
│   │   ┌─────────────────────────────┐                                          │    │
│   │   │  parse_multi_poc_instruction │◄─── LLM extracts:                       │    │
│   │   │                              │     - POCs + emails                      │    │
│   │   │  (REPLACES parse_instruction)│     - Per-POC requests                  │    │
│   │   │                              │     - Dependencies (inferred)           │    │
│   │   └──────────────┬──────────────┘     - Dynamic spawn rules               │    │
│   │                  │                     - Success criteria (global + POC)   │    │
│   │                  ▼                                                          │    │
│   │   ┌─────────────────────────────┐                                          │    │
│   │   │  build_dependency_graph     │◄─── Constructs DAG from POCs             │    │
│   │   └──────────────┬──────────────┘                                          │    │
│   │                  │                                                          │    │
│   │                  ▼                                                          │    │
│   │   ┌───────────────────────────────────────────────────────────────────┐    │    │
│   │   │                     DEPENDENCY GRAPH (DAG)                        │    │    │
│   │   │                                                                   │    │    │
│   │   │           poc_raj ─────────────┐                                  │    │    │
│   │   │           (order 1)            │                                  │    │    │
│   │   │               │                │                                  │    │    │
│   │   │               │ spawns         │                                  │    │    │
│   │   │               ▼                │                                  │    │    │
│   │   │         [vendor_1]             │                                  │    │    │
│   │   │         [vendor_2]  ───────────┼──────► aggregate                 │    │    │
│   │   │         [vendor_N]             │        & validate                │    │    │
│   │   │           (dynamic)            │                                  │    │    │
│   │   │                                │                                  │    │    │
│   │   │          poc_priya ────────────┘                                  │    │    │
│   │   │          (order 1, parallel)                                      │    │    │
│   │   │                                                                   │    │    │
│   │   └───────────────────────────────────────────────────────────────────┘    │    │
│   │                                                                             │    │
│   └─────────────────────────────────────────────────────────────────────────────┘    │
│                                                                                       │
│   ════════════════════════════════════════════════════════════════════════════════   │
│                                                                                       │
│   ┌─────────────────────────────────────────────────────────────────────────────┐    │
│   │                         PHASE 2: EXECUTION                                  │    │
│   │                                                                             │    │
│   │   ┌─────────────────────────────┐                                          │    │
│   │   │     orchestrate_pocs        │◄─── DAG Scheduler                        │    │
│   │   │     (main loop)             │     - Finds ready POCs (deps satisfied)  │    │
│   │   │                              │     - Executes in parallel if possible   │    │
│   │   └──────────────┬──────────────┘     - Handles interrupts (wait states)   │    │
│   │                  │                                                          │    │
│   │     ┌────────────┴────────────┬────────────────────────┐                   │    │
│   │     │                         │                        │                    │    │
│   │     ▼                         ▼                        ▼                    │    │
│   │  ┌──────────┐           ┌──────────┐            ┌──────────┐               │    │
│   │  │ POC FLOW │           │ POC FLOW │            │ POC FLOW │               │    │
│   │  │ poc_raj  │           │ poc_priya│            │ vendor_N │               │    │
│   │  │          │           │          │            │ (dynamic)│               │    │
│   │  └────┬─────┘           └────┬─────┘            └────┬─────┘               │    │
│   │       │                      │                       │                      │    │
│   │       └──────────────────────┴───────────────────────┘                      │    │
│   │                              │                                               │    │
│   │                              ▼                                               │    │
│   │   ┌─────────────────────────────────────────────────────────────────────┐   │    │
│   │   │                      POC FLOW (per POC)                             │   │    │
│   │   │                                                                     │   │    │
│   │   │   inject_context ──► compose_email ──► send_email ──►              │   │    │
│   │   │   register_webhook ──► wait_for_reply (INTERRUPT) ──►              │   │    │
│   │   │   fetch_email ──► extract_content ──► validate_poc_response        │   │    │
│   │   │                                                                     │   │    │
│   │   │   Outcomes: SUCCESS | RETRY | REDIRECT | FAIL                      │   │    │
│   │   │                                                                     │   │    │
│   │   └─────────────────────────────────────────────────────────────────────┘   │    │
│   │                                                                             │    │
│   └─────────────────────────────────────────────────────────────────────────────┘    │
│                                                                                       │
│   ════════════════════════════════════════════════════════════════════════════════   │
│                                                                                       │
│   ┌─────────────────────────────────────────────────────────────────────────────┐    │
│   │                       PHASE 3: AGGREGATION                                  │    │
│   │                                                                             │    │
│   │   aggregate_poc_responses ──► detect_conflicts ──►                         │    │
│   │   resolve_conflicts (if any) ──► validate_global_criteria                  │    │
│   │                                                                             │    │
│   │   IF conflicts: LLM decides + re-request from incorrect POC                │    │
│   │   IF global validation fails: Identify missing data + targeted retry       │    │
│   │                                                                             │    │
│   └─────────────────────────────────────────────────────────────────────────────┘    │
│                                                                                       │
│   ════════════════════════════════════════════════════════════════════════════════   │
│                                                                                       │
│   ┌─────────────────────────────────────────────────────────────────────────────┐    │
│   │                       PHASE 4: COMPLETION                                   │    │
│   │                                                                             │    │
│   │   send_success_replies ──► ONLY to POCs with validated data                │    │
│   │                                                                             │    │
│   └─────────────────────────────────────────────────────────────────────────────┘    │
│                                                                                       │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

---

## LangGraph State Machine

### Complete Multi-POC Graph

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│                         LANGGRAPH MULTI-POC STATE MACHINE                             │
└──────────────────────────────────────────────────────────────────────────────────────┘

                                    ┌─────────┐
                                    │  START  │
                                    └────┬────┘
                                         │
                                         ▼
                    ════════════════════════════════════════════
                                   PHASE 1: PLANNING
                    ════════════════════════════════════════════
                                         │
                                         ▼
                              ┌─────────────────────────┐
                              │ parse_multi_poc_        │
                              │ instruction             │
                              │                         │
                              │ Extract:                │
                              │ - POCs + emails         │
                              │ - Dependencies          │
                              │ - Success criteria      │
                              │ - Dynamic spawn rules   │
                              └───────────┬─────────────┘
                                          │
                                          ▼
                              ┌─────────────────────────┐
                              │ build_dependency_graph  │
                              │                         │
                              │ Construct DAG:          │
                              │ - Topological sort      │
                              │ - Assign exec orders    │
                              └───────────┬─────────────┘
                                          │
                    ════════════════════════════════════════════
                                  PHASE 2: EXECUTION
                    ════════════════════════════════════════════
                                          │
                                          ▼
                    ┌─────────────────────────────────────────────┐
                    │              orchestrate_pocs               │◄────────────────┐
                    │                                             │                 │
                    │  DAG Scheduler Decision:                    │                 │
                    │  - Find POCs with satisfied dependencies    │                 │
                    │  - Execute ready POCs in parallel           │                 │
                    │  - Handle interrupts for waiting POCs       │                 │
                    └───────────────────┬─────────────────────────┘                 │
                                        │                                           │
                        ┌───────────────┼───────────────┬──────────────┐            │
                        ▼               ▼               ▼              ▼            │
                    [execute]       [wait]         [aggregate]     [fail]           │
                        │               │               │              │            │
                        │               │               │              ▼            │
                        │               │               │            END            │
                        │               │               │                           │
                        ▼               │               │                           │
              ┌─────────────────────┐   │               │                           │
              │  inject_poc_context │   │               │                           │
              │                     │   │               │                           │
              │  Inject data from   │   │               │                           │
              │  completed deps     │   │               │                           │
              └──────────┬──────────┘   │               │                           │
                         │              │               │                           │
                         ▼              │               │                           │
              ┌─────────────────────┐   │               │                           │
              │   compose_email     │◄──┼───────────────┼───────────────────────┐   │
              │   (existing)        │   │               │                       │   │
              └──────────┬──────────┘   │               │                       │   │
                         │              │               │                       │   │
                         ▼              │               │                       │   │
              ┌─────────────────────┐   │               │                       │   │
              │    send_email       │   │               │                       │   │
              │    (existing)       │   │               │                       │   │
              └──────────┬──────────┘   │               │                       │   │
                         │              │               │                       │   │
                         ▼              │               │                       │   │
              ┌─────────────────────┐   │               │                       │   │
              │ register_poc_webhook│   │               │                       │   │
              │                     │   │               │                       │   │
              │ Register webhook    │   │               │                       │   │
              │ with poc_id metadata│   │               │                       │   │
              └──────────┬──────────┘   │               │                       │   │
                         │              │               │                       │   │
                         └──────────────┼───────────────┼───────────────────────┼───┘
                                        │               │                       │
                                        ▼               │                       │
                              ┌─────────────────────┐   │                       │
                              │   wait_for_reply    │   │                       │
                              │   (existing)        │   │                       │
                              │                     │   │                       │
                              │   INTERRUPT         │   │                       │
                              │   (webhook resume)  │   │                       │
                              └──────────┬──────────┘   │                       │
                                         │              │                       │
                                         │ webhook      │                       │
                                         │ received     │                       │
                                         ▼              │                       │
                              ┌─────────────────────┐   │                       │
                              │    fetch_email      │   │                       │
                              │    (existing)       │   │                       │
                              └──────────┬──────────┘   │                       │
                                         │              │                       │
                                         ▼              │                       │
                              ┌─────────────────────┐   │                       │
                              │   extract_content   │   │                       │
                              │   (existing)        │   │                       │
                              └──────────┬──────────┘   │                       │
                                         │              │                       │
                                         ▼              │                       │
                              ┌─────────────────────┐   │                       │
                              │ validate_poc_       │   │                       │
                              │ response            │   │                       │
                              │                     │   │                       │
                              │ Per-POC validation  │   │                       │
                              │ against POC criteria│   │                       │
                              └──────────┬──────────┘   │                       │
                                         │              │                       │
                         ┌───────────────┼───────────────┬───────────┐          │
                         ▼               ▼               ▼           ▼          │
                     [success]       [retry]        [redirect]   [fail]         │
                         │               │               │           │          │
                         │               │               │           │          │
                         │               │               ▼           │          │
                         │               │    ┌─────────────────┐    │          │
                         │               │    │ handle_redirect │    │          │
                         │               │    │ (existing)      │    │          │
                         │               │    └────────┬────────┘    │          │
                         │               │             │             │          │
                         │               └─────────────┴─────────────┼──────────┘
                         │                             │             │
                         │                             └──► compose_email (retry)
                         │
                         ▼
              ┌─────────────────────┐
              │ spawn_dynamic_pocs  │
              │                     │
              │ IF spawns_dynamic:  │
              │ - Extract emails    │
              │ - Create new POCs   │
              │ - Add to DAG        │
              └──────────┬──────────┘
                         │
                         └──────────────────────────► orchestrate_pocs
                                                             │
                    ════════════════════════════════════════════
                                 PHASE 3: AGGREGATION
                    ════════════════════════════════════════════
                                             │
                                             ▼
                              ┌─────────────────────────┐
                              │ aggregate_poc_responses │
                              │                         │
                              │ Merge all POC data      │
                              └───────────┬─────────────┘
                                          │
                                          ▼
                              ┌─────────────────────────┐
                              │   detect_conflicts      │
                              │                         │
                              │ Find contradicting data │
                              └───────────┬─────────────┘
                                          │
                          ┌───────────────┴───────────────┐
                          ▼                               ▼
                    [no conflicts]                  [conflicts found]
                          │                               │
                          │                               ▼
                          │               ┌─────────────────────────┐
                          │               │   resolve_conflicts     │
                          │               │                         │
                          │               │ LLM decides correct     │
                          │               │ source + re-request     │
                          │               │ from incorrect POC      │
                          │               └───────────┬─────────────┘
                          │                           │
                          │               ┌───────────┴───────────┐
                          │               ▼                       ▼
                          │         [needs retry]           [resolved]
                          │               │                       │
                          │               │                       │
                          │               └──► orchestrate_pocs   │
                          │                                       │
                          └───────────────────┬───────────────────┘
                                              │
                                              ▼
                              ┌─────────────────────────┐
                              │ validate_global_        │
                              │ criteria                │
                              │                         │
                              │ Check against overall   │
                              │ success criteria        │
                              └───────────┬─────────────┘
                                          │
                          ┌───────────────┴───────────────┐
                          ▼                               ▼
                      [valid]                       [not valid]
                          │                               │
                          │                               ▼
                          │               ┌─────────────────────────┐
                          │               │ identify_missing_data   │
                          │               │                         │
                          │               │ Determine which POCs    │
                          │               │ need to provide more    │
                          │               └───────────┬─────────────┘
                          │                           │
                          │                           └──► orchestrate_pocs
                          │
                    ════════════════════════════════════════════
                                 PHASE 4: COMPLETION
                    ════════════════════════════════════════════
                          │
                          ▼
              ┌─────────────────────────┐
              │ send_multi_success_     │
              │ replies                 │
              │                         │
              │ Send thank-you ONLY to  │
              │ POCs with valid data    │
              └───────────┬─────────────┘
                          │
                          ▼
                       ┌─────┐
                       │ END │
                       └─────┘
```

---

## State Model

### AgentState Schema

```
AgentState = {
    # ═══════════════════════════════════════════════════════════════
    # ORIGINAL REQUEST
    # ═══════════════════════════════════════════════════════════════

    "instruction": str,                    # Raw user instruction

    # ═══════════════════════════════════════════════════════════════
    # PLANNING PHASE OUTPUT
    # ═══════════════════════════════════════════════════════════════

    "execution_plan": POCExecutionPlan,    # Parsed multi-POC plan

    # ═══════════════════════════════════════════════════════════════
    # PER-POC EXECUTION STATE
    # ═══════════════════════════════════════════════════════════════

    "poc_states": Dict[str, POCState],     # poc_id → POCState

    # ═══════════════════════════════════════════════════════════════
    # CURRENT PROCESSING CONTEXT
    # ═══════════════════════════════════════════════════════════════

    "current_poc_id": Optional[str],       # Currently active POC ID

    # ═══════════════════════════════════════════════════════════════
    # AGGREGATION PHASE
    # ═══════════════════════════════════════════════════════════════

    "aggregated_data": Dict[str, Any],     # Merged results from all POCs
    "conflicts": List[DataConflict],       # Detected conflicts
    "global_validation_result": Optional[GlobalValidationResult],

    # ═══════════════════════════════════════════════════════════════
    # PROGRESS & ERROR
    # ═══════════════════════════════════════════════════════════════

    "progress_messages": List[str],        # Real-time status updates
    "error": Optional[str],                # Error message if failed
    "task_id": Optional[str],              # Task identifier
}
```

### POCExecutionPlan Schema

```
POCExecutionPlan = {
    "global_success_criteria": str,        # Overall success condition

    "pocs": List[POCRequirement],          # All POC definitions

    "dependency_graph": Dict[str, List[str]],  # poc_id → [dependency_poc_ids]
}
```

### POCRequirement Schema

```
POCRequirement = {
    "id": str,                             # Unique identifier (e.g., "poc_raj")
    "email": str,                          # POC email address
    "request": str,                        # What to request from this POC
    "success_criteria": str,               # Per-POC validation criteria
    "dependencies": List[str],             # POC IDs this depends on
    "execution_order": int,                # For parallel grouping (1, 2, 3...)

    "spawns_dynamic_pocs": Optional[{
        "enabled": bool,
        "email_source_field": str,         # Field in response containing emails
        "request_template": str,           # Template for new POC request
        "success_criteria_template": str,  # Template for success criteria
    }],

    "context_from_deps": Dict[str, Any],   # Injected data from dependencies
}
```

### POCState Schema

```
POCState = {
    "poc_id": str,
    "status": POCStatus,                   # pending|in_progress|waiting|completed|failed
    "attempts": int,                       # Current attempt count
    "max_attempts": int,                   # 15

    "conversation": ConversationState,     # Existing conversation model

    "extracted_data": Dict[str, Any],      # Validated data from POC
    "validation_result": Optional[POCValidationResult],

    "original_email": str,                 # Initial POC email
    "redirect_chain": List[str],           # Email redirect history

    "webhook_id": Optional[str],           # For wait resumption
}
```

### POCStatus Enum

```
POCStatus = {
    PENDING = "pending"           # Not yet started
    IN_PROGRESS = "in_progress"   # Currently executing
    WAITING = "waiting"           # Waiting for email reply
    COMPLETED = "completed"       # Successfully completed
    FAILED = "failed"             # Failed after max retries
}
```

### POCValidationResult Schema

```
POCValidationResult = {
    "valid": bool,
    "criteria_met": List[str],             # Satisfied criteria
    "criteria_missing": List[str],         # Unsatisfied criteria
    "should_retry": bool,
    "should_redirect": bool,
    "redirect_email": Optional[str],
    "reasoning": str,
}
```

### DataConflict Schema

```
DataConflict = {
    "field": str,                          # Conflicting field name
    "poc_values": Dict[str, Any],          # poc_id → value
    "resolution_reasoning": str,           # LLM's analysis
    "correct_poc_id": Optional[str],       # POC with correct value
    "incorrect_poc_ids": List[str],        # POCs to re-request
}
```

### GlobalValidationResult Schema

```
GlobalValidationResult = {
    "valid": bool,
    "all_criteria_met": bool,
    "missing_data": List[str],             # What's still needed
    "poc_ids_needing_retry": List[str],    # Which POCs should provide more
    "reasoning": str,
}
```

---

## Node Specifications

### Phase 1: Planning Nodes

#### parse_multi_poc_instruction

| Attribute | Value |
|-----------|-------|
| Purpose | Extract POCs, dependencies, criteria from natural language instruction |
| Location | `src/mail_agent/agent/nodes/parse_multi_poc_instruction.py` |
| Replaces | `parse_instruction.py` |
| Input | `instruction: str` |
| Output | `execution_plan: POCExecutionPlan` |

**Algorithm:**

```
ALGORITHM: Parse Multi-POC Instruction

INPUT: instruction (str)
OUTPUT: POCExecutionPlan

1. CALL LLM with MULTI_POC_PARSE_PROMPT:
   - Extract all mentioned POC emails
   - For each POC, identify:
     - What data to request
     - Success criteria (inferred)
     - Dependencies on other POCs
     - Whether response might spawn new POCs

2. BUILD dependency_graph:
   - For each POC:
     - IF dependencies mentioned ("after X", "using data from Y"):
       - Add edges in graph
     - ELSE:
       - No dependencies (can run in parallel)

3. ASSIGN execution_order:
   - POCs with no deps → order 1
   - POCs depending on order 1 → order 2
   - Continue (topological sort)

4. INFER global_success_criteria:
   - Combine all POC criteria
   - Or extract from overall request goal

5. RETURN POCExecutionPlan
```

#### build_dependency_graph

| Attribute | Value |
|-----------|-------|
| Purpose | Construct DAG and validate no circular dependencies |
| Location | `src/mail_agent/agent/nodes/build_dependency_graph.py` |
| Input | `execution_plan: POCExecutionPlan` |
| Output | Updated `execution_plan.dependency_graph` |

**Algorithm:**

```
ALGORITHM: Build Dependency Graph

INPUT: execution_plan
OUTPUT: validated dependency_graph

1. INITIALIZE adjacency_list = {}

2. FOR EACH poc in execution_plan.pocs:
   - adjacency_list[poc.id] = poc.dependencies

3. DETECT circular dependencies:
   - Run topological sort
   - IF cycle detected:
     - RAISE CircularDependencyError

4. ASSIGN execution_order via topological sort levels

5. RETURN updated execution_plan
```

---

### Phase 2: Execution Nodes

#### orchestrate_pocs

| Attribute | Value |
|-----------|-------|
| Purpose | DAG scheduler - determine which POC(s) to execute next |
| Location | `src/mail_agent/agent/nodes/orchestrate_pocs.py` |
| Input | `execution_plan`, `poc_states` |
| Output | `OrchestrationDecision` (action + poc_ids) |

**Algorithm:**

```
ALGORITHM: Orchestrate POCs (DAG Scheduler)

INPUT: execution_plan, poc_states
OUTPUT: OrchestrationDecision {
  action: "execute" | "wait" | "aggregate" | "fail",
  poc_ids: list[str],
  reason: str
}

1. CLASSIFY all POCs by status:
   - pending_pocs: status = PENDING
   - waiting_pocs: status = WAITING
   - completed_pocs: status = COMPLETED
   - failed_pocs: status = FAILED
   - in_progress_pocs: status = IN_PROGRESS

2. CHECK terminal condition:
   - IF all_pocs are (COMPLETED or FAILED):
     - RETURN action="aggregate"

3. FIND ready_pocs:
   - FOR each poc in pending_pocs:
     - deps = execution_plan.dependency_graph[poc.id]
     - IF all deps are COMPLETED:
       - ADD to ready_pocs
     - ELIF any dep is FAILED with no fallback:
       - MARK poc as FAILED (cascade)

4. IF ready_pocs NOT EMPTY:
   - RETURN action="execute", poc_ids=ready_pocs

5. IF waiting_pocs NOT EMPTY:
   - RETURN action="wait" (INTERRUPT)

6. IF in_progress_pocs NOT EMPTY:
   - RETURN action="wait" (still processing)

7. DETECT deadlock:
   - IF pending_pocs exist but none are ready:
     - Circular dependency detected
     - RETURN action="fail", reason="Circular dependency"

8. DEFAULT:
   - RETURN action="fail", reason="Unknown state"
```

#### inject_poc_context

| Attribute | Value |
|-----------|-------|
| Purpose | Inject data from completed dependencies into current POC |
| Location | `src/mail_agent/agent/nodes/inject_poc_context.py` |
| Input | `current_poc`, `poc_states` |
| Output | Updated `current_poc.context_from_deps` |

**Algorithm:**

```
ALGORITHM: Inject POC Context

INPUT: current_poc (POCRequirement), poc_states
OUTPUT: updated POCRequirement

1. FOR EACH dep_id in current_poc.dependencies:
   - dep_state = poc_states[dep_id]
   - IF dep_state.status == COMPLETED:
     - MERGE dep_state.extracted_data into current_poc.context_from_deps

2. RETURN updated current_poc
```

#### register_poc_webhook

| Attribute | Value |
|-----------|-------|
| Purpose | Register webhook with POC-specific metadata |
| Location | `src/mail_agent/agent/nodes/register_poc_webhook.py` |
| Input | `current_poc_id`, `task_id` |
| Output | `webhook_id` stored in POCState |

#### validate_poc_response

| Attribute | Value |
|-----------|-------|
| Purpose | Per-POC validation against POC-specific success criteria |
| Location | `src/mail_agent/agent/nodes/validate_poc_response.py` |
| Input | `poc_state`, `poc_requirement` |
| Output | `POCValidationResult` |

**Algorithm:**

```
ALGORITHM: Validate POC Response

INPUT: poc_state, poc_requirement
OUTPUT: POCValidationResult

1. EXTRACT response data from poc_state.conversation

2. CALL LLM with POC_VALIDATION_PROMPT:
   - Provide: extracted_data, success_criteria
   - Ask: Does the data satisfy the criteria?

3. PARSE LLM response:
   - valid: bool
   - criteria_met: list
   - criteria_missing: list
   - should_retry: bool
   - should_redirect: bool
   - redirect_email: str (if redirect)

4. IF redirect detected:
   - UPDATE poc_state.redirect_chain
   - SET should_redirect = True

5. RETURN POCValidationResult
```

#### spawn_dynamic_pocs

| Attribute | Value |
|-----------|-------|
| Purpose | Create new POC entries from response data |
| Location | `src/mail_agent/agent/nodes/spawn_dynamic_pocs.py` |
| Input | `poc_state`, `poc_requirement`, `execution_plan` |
| Output | Updated `execution_plan` with new POCs |

**Algorithm:**

```
ALGORITHM: Spawn Dynamic POCs

INPUT: poc_state (completed), poc_requirement, execution_plan
OUTPUT: updated execution_plan

1. IF NOT poc_requirement.spawns_dynamic_pocs.enabled:
   - RETURN execution_plan (unchanged)

2. EXTRACT emails from poc_state.extracted_data:
   - field = spawns_dynamic_pocs.email_source_field
   - new_emails = extracted_data[field]

3. FOR EACH email in new_emails:
   - CREATE new POCRequirement:
     - id: f"dynamic_{parent_id}_{index}"
     - email: email
     - request: spawns_dynamic_pocs.request_template.format(...)
     - success_criteria: spawns_dynamic_pocs.success_criteria_template
     - dependencies: [poc_requirement.id]

   - ADD to execution_plan.pocs
   - UPDATE execution_plan.dependency_graph
   - INITIALIZE POCState

4. RETURN updated execution_plan
```

---

### Phase 3: Aggregation Nodes

#### aggregate_poc_responses

| Attribute | Value |
|-----------|-------|
| Purpose | Merge all POC data into unified structure |
| Location | `src/mail_agent/agent/nodes/aggregate_poc_responses.py` |
| Input | `poc_states` |
| Output | `aggregated_data` |

#### detect_conflicts

| Attribute | Value |
|-----------|-------|
| Purpose | Find contradicting data across POCs |
| Location | `src/mail_agent/agent/nodes/detect_conflicts.py` |
| Input | `aggregated_data` |
| Output | `List[DataConflict]` |

**Algorithm:**

```
ALGORITHM: Detect Conflicts

INPUT: aggregated_data
OUTPUT: list[DataConflict]

1. BUILD field_map:
   - FOR EACH poc_id, data in aggregated_data:
     - FOR EACH field, value in data:
       - field_map[field].append((poc_id, value))

2. FIND conflicts:
   - FOR EACH field, poc_values in field_map:
     - IF len(poc_values) > 1:
       - unique_values = set(values)
       - IF len(unique_values) > 1:
         - CREATE DataConflict

3. RETURN conflicts
```

#### resolve_conflicts

| Attribute | Value |
|-----------|-------|
| Purpose | LLM decides correct source, triggers re-request |
| Location | `src/mail_agent/agent/nodes/resolve_conflicts.py` |
| Input | `conflicts`, `aggregated_data` |
| Output | Resolution decisions, POCs to retry |

**Algorithm:**

```
ALGORITHM: Resolve Conflicts

INPUT: conflicts, aggregated_data, execution_plan
OUTPUT: resolution decisions, POCs to retry

1. FOR EACH conflict in conflicts:

   2. CALL LLM with CONFLICT_RESOLUTION_PROMPT:
      - Provide: field name, all values, POC context
      - Ask: Which POC is correct? Why?

   3. PARSE LLM response:
      - correct_poc_id
      - incorrect_poc_ids
      - reasoning

   4. UPDATE conflict with resolution

   5. FOR EACH incorrect_poc_id:
      - MARK for retry
      - COMPOSE clarification email

6. IF any POCs marked for retry:
   - RETURN to orchestrate_pocs (Phase 2)

7. ELSE:
   - CONTINUE to global validation
```

#### validate_global_criteria

| Attribute | Value |
|-----------|-------|
| Purpose | Final validation against overall success criteria |
| Location | `src/mail_agent/agent/nodes/validate_global_criteria.py` |
| Input | `aggregated_data`, `global_success_criteria` |
| Output | `GlobalValidationResult` |

---

### Phase 4: Completion Nodes

#### send_multi_success_replies

| Attribute | Value |
|-----------|-------|
| Purpose | Send thank-you only to POCs with valid data |
| Location | `src/mail_agent/agent/nodes/send_multi_success_replies.py` |
| Input | `poc_states`, `global_validation_result` |
| Output | Success emails sent |

---

## Modified Existing Nodes

| Node | Modification |
|------|--------------|
| `compose_email` | Accept `context_from_deps` for template injection |
| `send_email` | Use `current_poc_id` to track which POC |
| `wait_for_reply` | Per-POC interrupt handling |
| `fetch_email` | Fetch for specific POC based on webhook metadata |
| `handle_redirect` | Update POCState instead of global state |
| `extract_content` | No changes needed |

---

## Technology Stack

### Core Framework

| Component | Package | Version | Purpose |
|-----------|---------|---------|---------|
| Agent Framework | `langgraph` | latest | State machine orchestration with DAG support |
| State Persistence | `langgraph-checkpoint-sqlite` | latest | SQLite checkpointing |
| Async Runtime | `asyncio` | stdlib | Parallel POC execution |

### LLM Integration

| Component | Package | Purpose |
|-----------|---------|---------|
| Primary | `langchain-google-genai` | Gemini 2.5 Flash |
| Fallback | `langchain-openai` | Azure OpenAI |
| Alternative | `openai` | OpenRouter |

### Web Framework

| Component | Package | Purpose |
|-----------|---------|---------|
| API Server | `fastapi` | A2A server, webhook receiver |
| ASGI Server | `uvicorn` | HTTP server |
| HTTP Client | `httpx` | Async REST API calls |

### UI & Visualization

| Component | Package/CDN | Purpose |
|-----------|-------------|---------|
| Frontend | `htmx` | Dynamic UI without heavy JS |
| Styling | `tailwindcss` | CSS framework |
| DAG Visualization | `cytoscape.js` | Interactive graph rendering |
| DAG Layout | `cytoscape-dagre` | Hierarchical DAG layout |
| Real-time Updates | SSE (native) | Progress streaming |

### Data Processing

| Component | Package | Purpose |
|-----------|---------|---------|
| Excel Parser | `openpyxl` | Read .xlsx files |
| CSV Parser | `csv` (stdlib) | Read CSV files |
| JSON | `json` (stdlib) | Data serialization |

### Testing

| Component | Package | Purpose |
|-----------|---------|---------|
| Test Framework | `pytest` | Unit and integration tests |
| Async Testing | `pytest-asyncio` | Async test support |
| Coverage | `pytest-cov` | Code coverage |
| Mocking | `unittest.mock` | Test doubles |

---

## Integration Points & API Contracts

### 1. Enhanced Webhook Registration

**Endpoint:** `POST http://localhost:8025/api/webhooks`

**Request (Enhanced):**
```json
{
  "url": "http://localhost:9000/webhook/email-received",
  "inbox_filter": "info-agent@gmail.com",
  "metadata": {
    "task_id": "task_123",
    "poc_id": "poc_raj"
  }
}
```

**Response:**
```json
{
  "id": "webhook_456",
  "url": "http://localhost:9000/webhook/email-received",
  "inbox_filter": "info-agent@gmail.com",
  "metadata": {
    "task_id": "task_123",
    "poc_id": "poc_raj"
  },
  "created_at": "2025-12-14T10:00:00.000000"
}
```

### 2. Enhanced Webhook Callback

**Endpoint:** `POST http://localhost:9000/webhook/email-received`

**Request (Enhanced):**
```json
{
  "event": "email.received",
  "email_id": "email_789",
  "from": "raj@gmail.com",
  "to": ["info-agent@gmail.com"],
  "subject": "Re: Request",
  "has_attachments": true,
  "received_at": "2025-12-14T11:00:00.000000",
  "metadata": {
    "task_id": "task_123",
    "poc_id": "poc_raj"
  }
}
```

### 3. DAG API Endpoint (New)

**Endpoint:** `GET http://localhost:8000/api/tasks/{task_id}/dag`

**Response:**
```json
{
  "nodes": [
    {
      "id": "poc_raj",
      "email": "raj@gmail.com",
      "status": "completed",
      "attempts": 2,
      "max_attempts": 15,
      "is_dynamic": false,
      "request_summary": "provide vendor list..."
    },
    {
      "id": "dynamic_poc_raj_1",
      "email": "vendor1@co.com",
      "status": "waiting",
      "attempts": 1,
      "max_attempts": 15,
      "is_dynamic": true,
      "request_summary": "provide pricing..."
    }
  ],
  "edges": [
    {"from": "poc_raj", "to": "dynamic_poc_raj_1"},
    {"from": "poc_raj", "to": "dynamic_poc_raj_2"}
  ],
  "phase": "execution",
  "global_status": {
    "total": 5,
    "completed": 2,
    "waiting": 2,
    "failed": 0,
    "pending": 1
  }
}
```

### 4. Enhanced SSE Progress Events

**New Event Types:**

```
# Phase transitions
event: phase_planning
event: phase_execution
event: phase_aggregation
event: phase_completion

# POC-level events
event: poc_started
event: poc_email_sent
event: poc_waiting
event: poc_reply_received
event: poc_validated
event: poc_retry
event: poc_redirect
event: poc_completed
event: poc_failed

# Dynamic POC events
event: dynamic_pocs_spawned

# Aggregation events
event: aggregation_started
event: conflict_detected
event: conflict_resolved
event: global_validation_started
event: global_validation_result

# DAG update (for UI refresh)
event: dag_updated
```

**Example POC Event:**
```json
{
  "event_type": "poc_status_changed",
  "timestamp": "2025-12-14T11:00:00.000000",
  "poc_id": "poc_raj",
  "poc_email": "raj@gmail.com",
  "message": "Waiting for reply from raj@gmail.com",
  "aggregate_progress": {
    "total": 5,
    "completed": 2,
    "waiting": 2,
    "failed": 0
  }
}
```

---

## UI DAG Visualization

### Cytoscape.js Configuration

```javascript
// Technology: Cytoscape.js with dagre layout plugin

const dagConfig = {
    layout: {
        name: 'dagre',
        rankDir: 'TB',           // Top to bottom
        nodeSep: 50,             // Horizontal spacing
        rankSep: 80,             // Vertical spacing
        animate: true
    },

    style: [
        // Node base style
        {
            selector: 'node',
            style: {
                'label': 'data(label)',
                'text-valign': 'center',
                'text-halign': 'center',
                'width': 120,
                'height': 60,
                'shape': 'roundrectangle',
                'border-width': 2
            }
        },

        // Edge style
        {
            selector: 'edge',
            style: {
                'width': 2,
                'line-color': '#999',
                'target-arrow-color': '#999',
                'target-arrow-shape': 'triangle',
                'curve-style': 'bezier'
            }
        },

        // Status-based colors
        {
            selector: 'node[status="pending"]',
            style: { 'background-color': '#9CA3AF' }    // Gray
        },
        {
            selector: 'node[status="in_progress"]',
            style: { 'background-color': '#3B82F6' }    // Blue
        },
        {
            selector: 'node[status="waiting"]',
            style: { 'background-color': '#F59E0B' }    // Amber
        },
        {
            selector: 'node[status="completed"]',
            style: { 'background-color': '#10B981' }    // Green
        },
        {
            selector: 'node[status="failed"]',
            style: { 'background-color': '#EF4444' }    // Red
        },

        // Dynamic POC indicator
        {
            selector: 'node[is_dynamic="true"]',
            style: { 'border-style': 'dashed' }
        }
    ]
};
```

### Visual Representation

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         TASK PROGRESS - DAG VIEW                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   Phase: EXECUTION                    Progress: 2/5 POCs complete           │
│                                                                             │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                                                                     │   │
│   │        ┌───────────────┐                                           │   │
│   │        │  poc_raj      │                                           │   │
│   │        │  raj@gmail    │                                           │   │
│   │        │  ✓ COMPLETED  │                                           │   │
│   │        │  (2 attempts) │                                           │   │
│   │        └───────┬───────┘                                           │   │
│   │                │                                                    │   │
│   │       ┌────────┼────────┐                                          │   │
│   │       │        │        │                                          │   │
│   │       ▼        ▼        ▼                                          │   │
│   │   ┌╌╌╌╌╌╌╌╌┐ ┌╌╌╌╌╌╌╌╌┐ ┌╌╌╌╌╌╌╌╌┐                                │   │
│   │   ┊vendor_1┊ ┊vendor_2┊ ┊vendor_3┊    ┌────────────────┐          │   │
│   │   ┊v1@co   ┊ ┊v2@co   ┊ ┊v3@co   ┊    │   poc_priya    │          │   │
│   │   ┊⏳ WAIT ┊ ┊✓ DONE  ┊ ┊⏳ WAIT ┊    │   priya@gmail  │          │   │
│   │   ┊(1/15)  ┊ ┊(1/15)  ┊ ┊(1/15)  ┊    │   ✓ COMPLETED  │          │   │
│   │   └╌╌╌╌┬╌╌╌┘ └╌╌╌┬╌╌╌╌┘ └╌╌╌┬╌╌╌╌┘    │   (1 attempt)  │          │   │
│   │        │         │          │         └───────┬────────┘          │   │
│   │        └─────────┼──────────┘                 │                    │   │
│   │                  │                            │                    │   │
│   │                  └────────────┬───────────────┘                    │   │
│   │                               │                                    │   │
│   │                               ▼                                    │   │
│   │                      ┌────────────────┐                           │   │
│   │                      │   AGGREGATE    │                           │   │
│   │                      │   & VALIDATE   │                           │   │
│   │                      │   (pending)    │                           │   │
│   │                      └────────────────┘                           │   │
│   │                                                                     │   │
│   │   ╌╌╌ = Dynamic POC (spawned from response)                        │   │
│   │                                                                     │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│   Legend: ✓ Completed  ⏳ Waiting  ▶ In Progress  ✗ Failed  ○ Pending      │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## LLM Prompt Templates

### MULTI_POC_PARSE_PROMPT

```
SYSTEM: You are an assistant that extracts structured multi-POC information from user requests.

USER:
Analyze this instruction and extract all points of contact (POCs) with their requirements:

"{instruction}"

Return JSON:
{{
  "global_success_criteria": "Overall success condition for the entire request",
  "pocs": [
    {{
      "id": "unique_identifier (e.g., poc_1, poc_raj)",
      "email": "email@address.com",
      "request": "What specifically to ask this person",
      "success_criteria": "What constitutes a successful response from this POC",
      "dependencies": ["list of POC ids this depends on, empty if independent"],
      "spawns_dynamic_pocs": {{
        "enabled": true|false,
        "email_source_field": "field name in response containing new POC emails",
        "request_template": "template for requests to spawned POCs",
        "success_criteria_template": "template for success criteria"
      }}
    }}
  ]
}}

Rules:
- Extract ALL email addresses mentioned as separate POCs
- If POC order is explicitly mentioned ("first ask X, then Y"), create dependency
- If data from one POC is needed for another ("using the list from X, ask Y"), create dependency
- If POCs can be contacted simultaneously with no data dependency, leave dependencies empty
- Infer success criteria from context if not explicit
- Detect if response might contain new POC emails (vendor lists, team members, referrals)
- For dynamic POC spawning, identify which field will contain the emails
```

### POC_VALIDATION_PROMPT

```
SYSTEM: You validate whether a POC's response satisfies their specific requirements.

USER:
POC: {poc_email}
Request made: "{request}"
Success criteria: "{success_criteria}"

Response received:
{extracted_content}

Analyze:
1. Does the response contain the requested information?
2. Is the data complete as per the success criteria?
3. Is the format correct?
4. Does the POC suggest contacting someone else instead? (redirect)

Return JSON:
{{
  "valid": true|false,
  "criteria_met": ["list of criteria that were satisfied"],
  "criteria_missing": ["list of criteria not satisfied"],
  "should_retry": true|false,
  "should_redirect": true|false,
  "redirect_email": "email@address.com or null",
  "reasoning": "detailed explanation"
}}
```

### CONFLICT_RESOLUTION_PROMPT

```
SYSTEM: You resolve data conflicts between multiple POC responses.

USER:
Field in conflict: "{field}"

POC responses for this field:
{poc_values_json}

Context about each POC:
{poc_context_json}

Analyze:
1. Which POC's value is most likely correct?
2. Why might the other POC(s) have provided incorrect data?
3. What clarification should be requested?

Return JSON:
{{
  "correct_poc_id": "poc_id with correct value",
  "incorrect_poc_ids": ["poc_ids with incorrect values"],
  "reasoning": "explanation of decision",
  "clarification_request": "what to ask the incorrect POC(s)"
}}
```

### GLOBAL_VALIDATION_PROMPT

```
SYSTEM: You validate aggregated data from multiple POCs against global success criteria.

USER:
Original request: "{instruction}"
Global success criteria: "{global_success_criteria}"

Aggregated data from all POCs:
{aggregated_data_json}

Analyze:
1. Does the combined data satisfy the overall request?
2. Is any critical data missing?
3. Which POC(s) should provide additional information if needed?

Return JSON:
{{
  "valid": true|false,
  "all_criteria_met": true|false,
  "missing_data": ["list of what's still needed"],
  "poc_ids_needing_retry": ["poc_ids that should provide more"],
  "reasoning": "detailed explanation"
}}
```

---

## Directory Structure Changes

```
src/mail_agent/
├── agent/
│   ├── state.py                          # MODIFY: Add all new models
│   ├── graph.py                          # REWRITE: New multi-POC graph
│   │
│   └── nodes/
│       ├── __init__.py                   # MODIFY: Export new nodes
│       │
│       │ # DELETED
│       ├── parse_instruction.py          # DELETE: Replaced
│       │
│       │ # NEW NODES
│       ├── parse_multi_poc_instruction.py   # NEW
│       ├── build_dependency_graph.py        # NEW
│       ├── orchestrate_pocs.py              # NEW
│       ├── inject_poc_context.py            # NEW
│       ├── register_poc_webhook.py          # NEW
│       ├── validate_poc_response.py         # NEW
│       ├── spawn_dynamic_pocs.py            # NEW
│       ├── aggregate_poc_responses.py       # NEW
│       ├── detect_conflicts.py              # NEW
│       ├── resolve_conflicts.py             # NEW
│       ├── validate_global_criteria.py      # NEW
│       ├── send_multi_success_replies.py    # NEW
│       │
│       │ # MODIFIED NODES
│       ├── compose_email.py              # MODIFY: Context injection
│       ├── send_email.py                 # MODIFY: Use current_poc_id
│       ├── wait_for_reply.py             # MODIFY: Per-POC interrupt
│       ├── fetch_email.py                # MODIFY: POC-specific fetch
│       ├── extract_content.py            # NO CHANGE
│       ├── validate_response.py          # MODIFY: Extract per-POC logic
│       ├── decide_next.py                # NO CHANGE (used per-POC)
│       ├── handle_redirect.py            # MODIFY: Per-POC redirect
│       ├── compose_success_reply.py      # DEPRECATE: Replaced by multi
│       └── send_success_reply.py         # DEPRECATE: Replaced by multi
│
├── llm/
│   └── prompts.py                        # MODIFY: Add new prompts
│
├── a2a/
│   ├── progress_store.py                 # MODIFY: New event types
│   └── routes/
│       ├── __init__.py                   # MODIFY: Include dag routes
│       └── dag.py                        # NEW: DAG API endpoint
│
├── webhook/
│   └── server.py                         # MODIFY: Route to specific POC
│
├── task_manager/
│   └── manager.py                        # MODIFY: resume_poc method
│
└── ...

src/mock_smtp/
├── webhooks/
│   └── registry.py                       # MODIFY: POC metadata support
└── ...

src/ui/
├── routes/
│   └── dag.py                            # NEW: DAG visualization route
├── templates/
│   ├── dashboard/
│   │   └── task_detail.html              # MODIFY: Include DAG view
│   └── partials/
│       └── dag_visualization.html        # NEW: DAG UI component
└── static/
    └── js/
        └── dag.js                        # NEW: Cytoscape.js integration

tests/
├── test_mail_agent/
│   ├── test_nodes/
│   │   ├── test_parse_multi_poc_instruction.py   # NEW
│   │   ├── test_orchestrate_pocs.py              # NEW
│   │   ├── test_spawn_dynamic_pocs.py            # NEW
│   │   ├── test_aggregate_responses.py           # NEW
│   │   ├── test_detect_conflicts.py              # NEW
│   │   ├── test_resolve_conflicts.py             # NEW
│   │   ├── test_validate_global_criteria.py      # NEW
│   │   └── ...
│   │
│   └── test_integration/
│       ├── test_multi_poc_parallel.py            # NEW
│       ├── test_multi_poc_sequential.py          # NEW
│       ├── test_dynamic_poc_spawning.py          # NEW
│       ├── test_conflict_resolution.py           # NEW
│       └── ...
└── ...
```

---

## Implementation Phases

### Phase 1: State Models & Core Types
- POCStatus, POCRequirement, POCState
- POCExecutionPlan, DataConflict
- POCValidationResult, GlobalValidationResult
- Enhanced AgentState

### Phase 2: LLM Prompts
- MULTI_POC_PARSE_PROMPT
- POC_VALIDATION_PROMPT
- CONFLICT_RESOLUTION_PROMPT
- GLOBAL_VALIDATION_PROMPT

### Phase 3: Planning Nodes
- parse_multi_poc_instruction
- build_dependency_graph

### Phase 4: Orchestration Nodes
- orchestrate_pocs (DAG scheduler)
- inject_poc_context
- register_poc_webhook

### Phase 5: Modify Existing Nodes
- compose_email (context injection support)
- send_email (current_poc_id support)
- wait_for_reply (per-POC interrupt)
- fetch_email (POC-specific fetch)
- handle_redirect (per-POC redirect)

### Phase 6: Validation Nodes
- validate_poc_response (per-POC)
- spawn_dynamic_pocs

### Phase 7: Aggregation Nodes
- aggregate_poc_responses
- detect_conflicts
- resolve_conflicts
- validate_global_criteria

### Phase 8: Completion Nodes
- send_multi_success_replies

### Phase 9: Graph Definition
- Rewrite graph.py with new flow

### Phase 10: Webhook Enhancement
- Registry (POC metadata)
- Webhook server (POC routing)
- Task manager (resume_poc)

### Phase 11: SSE & Progress Events
- New event types
- DAG update events

### Phase 12: UI - DAG Visualization
- DAG API endpoint
- Cytoscape.js integration
- Dashboard updates

### Phase 13: Tests
- Unit tests for all new nodes
- Integration tests for multi-POC flow
- E2E tests

---

## Test Cases

### Unit Tests

| Test | Description |
|------|-------------|
| `test_parse_multi_poc_single` | Single POC instruction → trivial case |
| `test_parse_multi_poc_parallel` | Multiple independent POCs |
| `test_parse_multi_poc_sequential` | POCs with dependencies |
| `test_parse_multi_poc_dynamic` | POC that spawns new POCs |
| `test_build_dependency_graph_valid` | Valid DAG construction |
| `test_build_dependency_graph_circular` | Circular dependency detection |
| `test_orchestrate_parallel_execution` | Multiple POCs run in parallel |
| `test_orchestrate_dependency_ordering` | Deps respected in execution |
| `test_orchestrate_wait_handling` | Correct interrupt on waiting |
| `test_inject_context_from_deps` | Data from completed deps injected |
| `test_spawn_dynamic_pocs` | New POCs created from response |
| `test_aggregate_responses` | Data merged correctly |
| `test_detect_conflicts_none` | No conflicts detected |
| `test_detect_conflicts_found` | Conflicts properly identified |
| `test_resolve_conflicts` | LLM resolution + retry |
| `test_validate_global_success` | Global criteria met |
| `test_validate_global_failure` | Global criteria not met → retry |
| `test_targeted_retry` | Only failed POC retried |
| `test_redirect_per_poc` | Redirect handled independently |
| `test_success_replies_valid_only` | Thank-you to valid POCs only |

### Integration Tests

| Test | Description |
|------|-------------|
| `test_full_flow_single_poc` | Single POC (trivial case) |
| `test_full_flow_parallel_pocs` | Two independent POCs |
| `test_full_flow_sequential_pocs` | POC2 depends on POC1 data |
| `test_full_flow_dynamic_spawn` | POC1 response spawns new POCs |
| `test_full_flow_conflict_resolution` | Two POCs conflict → resolved |
| `test_webhook_poc_routing` | Webhook routes to correct POC |
| `test_dag_api_response` | DAG endpoint returns correct structure |
| `test_sse_poc_events` | SSE streams per-POC events |

---

## Error Handling

### New Error Types

```
MultiPOCError (base)
├── CircularDependencyError      # Circular dependency in DAG
├── POCExecutionError            # POC flow failed
│   ├── POCMaxRetriesError       # Exceeded 15 attempts
│   └── POCTimeoutError          # (Future: timeout)
├── AggregationError             # Aggregation phase failed
│   ├── ConflictResolutionError  # Cannot resolve conflict
│   └── GlobalValidationError    # Global criteria not met
└── DynamicPOCError              # Dynamic POC spawning failed
    └── InvalidEmailSourceError  # Cannot extract emails from response
```

### Error Recovery

| Error | Recovery |
|-------|----------|
| Single POC fails | Continue with other POCs, mark as failed |
| Circular dependency | Fail immediately with clear error |
| Conflict unresolved | Ask user to resolve manually |
| Global validation fails | Targeted retry of specific POCs |
| Dynamic spawn fails | Log error, continue without spawned POCs |

---

## Configuration Changes

### New Configuration Options

```
# Agent Behavior (Enhanced)
MAIL_AGENT_MAX_ATTEMPTS=15              # Per-POC retry limit (was 5)
MAIL_AGENT_PARALLEL_EXECUTION=true      # Enable parallel POC execution
MAIL_AGENT_DYNAMIC_POC_ENABLED=true     # Enable dynamic POC spawning
# MAIL_AGENT_DYNAMIC_POC_MAX_DEPTH=unlimited  # No limit on spawn depth
# MAIL_AGENT_PARALLEL_POC_LIMIT=unlimited     # No limit on parallel POCs
```

---

## Future Considerations

The following are explicitly out of scope but noted for future reference:

1. **Timeout per POC** - Currently no timeout for waiting POCs
2. **POC Priority** - All POCs treated equally
3. **Partial Success Mode** - Currently all-or-nothing per global criteria
4. **POC Groups** - Cannot group POCs for batch operations
5. **Conditional POCs** - Cannot skip POCs based on other POC results
6. **POC Templates** - Cannot save/reuse POC configurations
7. **Manual Conflict Resolution UI** - Currently LLM-only resolution

---

## References

- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [Cytoscape.js Documentation](https://js.cytoscape.org/)
- [Cytoscape-dagre Layout](https://github.com/cytoscape/cytoscape.js-dagre)
- Existing Architecture: `mail-agent.md`, `mail-agent-a2a.md`, `mail-agent-async.md`
