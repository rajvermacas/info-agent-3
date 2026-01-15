"""
LangGraph State Machine - Mail Agent graph definition.

Defines the complete state machine for the mail agent workflow with
Multi-POC DAG-based orchestration support.

Graph Architecture:
===================

```
START
  ↓
parse_multi_poc_instruction
  ↓
build_dependency_graph
  ↓
orchestrate_pocs ←──────────────────────────────────────────────────────┐
  │                                                                      │
  ├─[execute]→ inject_poc_context → compose_email → send_email          │
  │             → wait_for_reply (INTERRUPT) → fetch_email              │
  │             → extract_content → validate_poc_response               │
  │             ├─[success]→ ──────────────────────────────────────────→┤
  │             ├─[retry]→ compose_email (followup) ───────────────────→┤
  │             ├─[redirect]→ handle_redirect → compose_email ─────────→┤
  │             └─[fail]→ ─────────────────────────────────────────────→┤
  │                                                                      │
  ├─[wait]→ wait_for_reply (INTERRUPT)                                  │
  │           → fetch_email → extract_content → validate_poc_response   │
  │           → (same routing as above) ───────────────────────────────→┤
  │                                                                      │
  ├─[aggregate]→ aggregate_poc_responses → detect_conflicts             │
  │               ├─[conflicts]→ resolve_conflicts                      │
  │               │               ├─[needs_retry]→ ────────────────────→┤
  │               │               └─[resolved]→ validate_global_criteria│
  │               └─[no_conflicts]→ validate_global_criteria            │
  │                                 ├─[valid]→ send_multi_success_replies│
  │                                 │           → END                    │
  │                                 └─[not_valid]→ ────────────────────→┤
  │                                                                      │
  └─[fail]→ END (with error)                                            │
```
"""

import logging
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph

from mail_agent.agent.state import AgentState
from mail_agent.agent.multi_poc_state import (
    OrchestrationAction,
    OrchestrationDecision,
    POCStatus,
)
from mail_agent.agent.multi_poc_helpers import (
    get_poc_state,
    get_poc_progress_summary,
)

# Import all nodes
from mail_agent.agent.nodes.parse_multi_poc_instruction import (
    parse_multi_poc_instruction,
)
from mail_agent.agent.nodes.build_dependency_graph import build_dependency_graph
from mail_agent.agent.nodes.orchestrate_pocs import orchestrate_pocs
from mail_agent.agent.nodes.inject_poc_context import inject_poc_context
from mail_agent.agent.nodes.compose_email import compose_email
from mail_agent.agent.nodes.send_email import send_email
from mail_agent.agent.nodes.wait_for_reply import wait_for_reply
from mail_agent.agent.nodes.fetch_email import fetch_email
from mail_agent.agent.nodes.extract_content import extract_content
from mail_agent.agent.nodes.validate_poc_response import validate_poc_response
from mail_agent.agent.nodes.handle_redirect import handle_redirect
from mail_agent.agent.nodes.aggregate_poc_responses import aggregate_poc_responses
from mail_agent.agent.nodes.detect_conflicts import detect_conflicts, has_conflicts
from mail_agent.agent.nodes.resolve_conflicts import (
    resolve_conflicts,
    needs_conflict_retry,
)
from mail_agent.agent.nodes.validate_global_criteria import (
    validate_global_criteria,
    is_global_valid,
)
from mail_agent.agent.nodes.send_multi_success_replies import send_multi_success_replies


logger = logging.getLogger(__name__)


# ============================================================================
# Routing Functions
# ============================================================================


def route_after_parse(state: AgentState) -> Literal["build_dependency_graph", "end"]:
    """
    Route after parsing multi-POC instruction.

    Returns:
        - "build_dependency_graph" if parsing succeeded
        - "end" if parsing failed or no POCs found
    """
    error = state.get("error")
    if error:
        logger.debug(f"Routing after parse: error -> end ({error})")
        return "end"

    execution_plan = state.get("execution_plan")
    if execution_plan is None:
        logger.debug("Routing after parse: no execution_plan -> end")
        return "end"

    logger.debug("Routing after parse: -> build_dependency_graph")
    return "build_dependency_graph"


def route_after_orchestration(
    state: AgentState,
) -> Literal["execute_poc", "wait_for_poc", "aggregate", "fail_end"]:
    """
    Route based on orchestration decision from orchestrate_pocs node.

    Returns:
        - "execute_poc" to start processing a ready POC
        - "wait_for_poc" when POCs are waiting for replies
        - "aggregate" when all POCs are complete
        - "fail_end" on failure or deadlock
    """
    decision_dict = state.get("orchestration_decision")
    if not decision_dict:
        logger.warning("No orchestration_decision in state, routing to fail_end")
        return "fail_end"

    decision = OrchestrationDecision.from_dict(decision_dict)
    logger.debug(f"Routing after orchestration: action={decision.action.value}")

    if decision.action == OrchestrationAction.EXECUTE:
        return "execute_poc"
    elif decision.action == OrchestrationAction.WAIT:
        return "wait_for_poc"
    elif decision.action == OrchestrationAction.AGGREGATE:
        return "aggregate"
    else:  # FAIL
        return "fail_end"


def route_after_poc_validation(
    state: AgentState,
) -> Literal["poc_success", "poc_retry", "poc_redirect", "poc_fail"]:
    """
    Route based on POC validation result.

    Returns:
        - "poc_success" if POC response is valid
        - "poc_retry" if POC needs to retry (send followup)
        - "poc_redirect" if POC suggests redirect
        - "poc_fail" if POC validation failed permanently
    """
    # Check temporary validation flags set by validate_poc_response
    is_valid = state.get("_poc_validation_valid", False)
    should_retry = state.get("_poc_validation_should_retry", False)
    should_redirect = state.get("_poc_validation_should_redirect", False)

    if is_valid:
        logger.debug("Routing after POC validation: valid -> poc_success")
        return "poc_success"
    elif should_redirect:
        logger.debug("Routing after POC validation: redirect -> poc_redirect")
        return "poc_redirect"
    elif should_retry:
        # Check if max attempts reached
        current_poc_id = state.get("current_poc_id")
        if current_poc_id:
            try:
                poc_state = get_poc_state(state, current_poc_id)
                if poc_state.status == POCStatus.FAILED:
                    logger.debug(
                        f"Routing after POC validation: max attempts reached -> poc_fail"
                    )
                    return "poc_fail"
            except (KeyError, ValueError):
                pass
        logger.debug("Routing after POC validation: retry -> poc_retry")
        return "poc_retry"
    else:
        logger.debug("Routing after POC validation: fail -> poc_fail")
        return "poc_fail"


def route_after_conflict_detection(
    state: AgentState,
) -> Literal["has_conflicts", "no_conflicts"]:
    """
    Route based on whether conflicts were detected.

    Returns:
        - "has_conflicts" if there are data conflicts to resolve
        - "no_conflicts" if no conflicts detected
    """
    if has_conflicts(state):
        logger.debug("Routing after conflict detection: has_conflicts")
        return "has_conflicts"
    else:
        logger.debug("Routing after conflict detection: no_conflicts")
        return "no_conflicts"


def route_after_conflict_resolution(
    state: AgentState,
) -> Literal["needs_retry", "resolved"]:
    """
    Route based on conflict resolution result.

    Returns:
        - "needs_retry" if POCs need to re-provide data
        - "resolved" if conflicts are fully resolved
    """
    if needs_conflict_retry(state):
        logger.debug("Routing after conflict resolution: needs_retry")
        return "needs_retry"
    else:
        logger.debug("Routing after conflict resolution: resolved")
        return "resolved"


def route_after_global_validation(
    state: AgentState,
) -> Literal["valid", "not_valid"]:
    """
    Route based on global validation result.

    Returns:
        - "valid" if all global criteria are met
        - "not_valid" if criteria not satisfied (need more data)
    """
    if is_global_valid(state):
        logger.debug("Routing after global validation: valid")
        return "valid"
    else:
        logger.debug("Routing after global validation: not_valid")
        return "not_valid"


# ============================================================================
# Passthrough Nodes (for routing purposes)
# ============================================================================


async def mark_poc_success(state: AgentState) -> dict[str, Any]:
    """
    Mark current POC as successful and return to orchestrator.

    This is a passthrough node for routing - the actual status update
    is done in validate_poc_response.
    """
    current_poc_id = state.get("current_poc_id")
    logger.info(f"POC {current_poc_id} completed successfully")
    return {
        "current_node": "mark_poc_success",
        "progress_messages": [f"POC {current_poc_id}: Completed successfully"],
    }


async def mark_poc_failed(state: AgentState) -> dict[str, Any]:
    """
    Mark current POC as failed and return to orchestrator.

    This is a passthrough node for routing - the actual status update
    is done in validate_poc_response.
    """
    current_poc_id = state.get("current_poc_id")
    logger.warning(f"POC {current_poc_id} failed")
    return {
        "current_node": "mark_poc_failed",
        "progress_messages": [f"POC {current_poc_id}: Failed"],
    }


async def handle_global_retry(state: AgentState) -> dict[str, Any]:
    """
    Handle case where global validation failed and POCs need retry.

    This resets the orchestration to process POCs that need more data.
    """
    global_result = state.get("global_validation_result", {})
    poc_ids_needing_retry = global_result.get("poc_ids_needing_retry", [])

    logger.info(f"Global validation incomplete. POCs needing retry: {poc_ids_needing_retry}")

    # Note: The actual retry logic is handled by orchestrate_pocs
    # which will pick up POCs that need more data
    return {
        "current_node": "handle_global_retry",
        "progress_messages": [
            f"Global criteria not met. Need more data from: {', '.join(poc_ids_needing_retry)}"
        ],
    }


async def finalize_success(state: AgentState) -> dict[str, Any]:
    """
    Finalize successful completion of multi-POC orchestration.
    """
    progress = get_poc_progress_summary(state)
    logger.info(
        f"Multi-POC orchestration complete: "
        f"{progress['completed']} completed, {progress['failed']} failed"
    )

    return {
        "current_node": "finalize_success",
        "final_summary": (
            f"Successfully completed multi-POC orchestration. "
            f"{progress['completed']} POC(s) completed, {progress['failed']} failed."
        ),
        "progress_messages": ["Multi-POC orchestration completed successfully"],
    }


async def finalize_failure(state: AgentState) -> dict[str, Any]:
    """
    Finalize failed multi-POC orchestration.
    """
    error = state.get("error", "Unknown error")
    progress = get_poc_progress_summary(state)

    logger.error(f"Multi-POC orchestration failed: {error}")

    return {
        "current_node": "finalize_failure",
        "final_summary": f"Multi-POC orchestration failed: {error}",
        "progress_messages": [f"Orchestration failed: {error}"],
    }


# ============================================================================
# Graph Builder
# ============================================================================


def create_mail_agent_graph() -> StateGraph:
    """
    Create the mail agent LangGraph state machine with Multi-POC orchestration.

    Returns:
        StateGraph ready for compilation.

    The graph implements a DAG-based orchestration flow:
    1. Planning Phase: Parse instruction, build dependency graph
    2. Execution Phase: Execute POCs respecting dependencies
    3. Aggregation Phase: Merge data, detect/resolve conflicts
    4. Completion Phase: Validate global criteria, send acknowledgments
    """
    logger.info("Creating multi-POC mail agent graph")

    graph = StateGraph(AgentState)

    # ========================================================================
    # Phase 1: Planning Nodes
    # ========================================================================

    graph.add_node("parse_multi_poc_instruction", parse_multi_poc_instruction)
    graph.add_node("build_dependency_graph", build_dependency_graph)

    # ========================================================================
    # Phase 2: Orchestration Nodes
    # ========================================================================

    graph.add_node("orchestrate_pocs", orchestrate_pocs)
    graph.add_node("inject_poc_context", inject_poc_context)

    # ========================================================================
    # Phase 2: POC Execution Nodes (per-POC flow)
    # ========================================================================

    graph.add_node("compose_email", compose_email)
    graph.add_node("send_email", send_email)
    graph.add_node("wait_for_reply", wait_for_reply)
    graph.add_node("fetch_email", fetch_email)
    graph.add_node("extract_content", extract_content)
    graph.add_node("validate_poc_response", validate_poc_response)

    # POC result handling
    graph.add_node("handle_redirect", handle_redirect)
    graph.add_node("mark_poc_success", mark_poc_success)
    graph.add_node("mark_poc_failed", mark_poc_failed)

    # ========================================================================
    # Phase 3: Aggregation Nodes
    # ========================================================================

    graph.add_node("aggregate_poc_responses", aggregate_poc_responses)
    graph.add_node("detect_conflicts", detect_conflicts)
    graph.add_node("resolve_conflicts", resolve_conflicts)

    # ========================================================================
    # Phase 4: Completion Nodes
    # ========================================================================

    graph.add_node("validate_global_criteria", validate_global_criteria)
    graph.add_node("handle_global_retry", handle_global_retry)
    graph.add_node("send_multi_success_replies", send_multi_success_replies)
    graph.add_node("finalize_success", finalize_success)
    graph.add_node("finalize_failure", finalize_failure)

    # ========================================================================
    # Edges: Phase 1 - Planning
    # ========================================================================

    # START -> parse_multi_poc_instruction
    graph.add_edge(START, "parse_multi_poc_instruction")

    # parse_multi_poc_instruction -> build_dependency_graph or END
    graph.add_conditional_edges(
        "parse_multi_poc_instruction",
        route_after_parse,
        {
            "build_dependency_graph": "build_dependency_graph",
            "end": END,
        },
    )

    # build_dependency_graph -> orchestrate_pocs
    graph.add_edge("build_dependency_graph", "orchestrate_pocs")

    # ========================================================================
    # Edges: Phase 2 - Orchestration Loop
    # ========================================================================

    # orchestrate_pocs -> execute/wait/aggregate/fail
    graph.add_conditional_edges(
        "orchestrate_pocs",
        route_after_orchestration,
        {
            "execute_poc": "inject_poc_context",
            "wait_for_poc": "wait_for_reply",
            "aggregate": "aggregate_poc_responses",
            "fail_end": "finalize_failure",
        },
    )

    # ========================================================================
    # Edges: POC Execution Flow
    # ========================================================================

    # inject_poc_context -> compose_email -> send_email -> wait_for_reply
    graph.add_edge("inject_poc_context", "compose_email")
    graph.add_edge("compose_email", "send_email")
    graph.add_edge("send_email", "wait_for_reply")

    # wait_for_reply -> fetch_email -> extract_content -> validate_poc_response
    graph.add_edge("wait_for_reply", "fetch_email")
    graph.add_edge("fetch_email", "extract_content")
    graph.add_edge("extract_content", "validate_poc_response")

    # validate_poc_response -> routing based on validation result
    graph.add_conditional_edges(
        "validate_poc_response",
        route_after_poc_validation,
        {
            "poc_success": "mark_poc_success",
            "poc_retry": "compose_email",  # Loop back for followup
            "poc_redirect": "handle_redirect",
            "poc_fail": "mark_poc_failed",
        },
    )

    # handle_redirect -> compose_email (for new POC)
    graph.add_edge("handle_redirect", "compose_email")

    # POC terminal states return to orchestrator
    graph.add_edge("mark_poc_success", "orchestrate_pocs")
    graph.add_edge("mark_poc_failed", "orchestrate_pocs")

    # ========================================================================
    # Edges: Phase 3 - Aggregation
    # ========================================================================

    # aggregate_poc_responses -> detect_conflicts
    graph.add_edge("aggregate_poc_responses", "detect_conflicts")

    # detect_conflicts -> has_conflicts or no_conflicts
    graph.add_conditional_edges(
        "detect_conflicts",
        route_after_conflict_detection,
        {
            "has_conflicts": "resolve_conflicts",
            "no_conflicts": "validate_global_criteria",
        },
    )

    # resolve_conflicts -> needs_retry or resolved
    graph.add_conditional_edges(
        "resolve_conflicts",
        route_after_conflict_resolution,
        {
            "needs_retry": "orchestrate_pocs",  # Back to orchestrator for retry
            "resolved": "validate_global_criteria",
        },
    )

    # ========================================================================
    # Edges: Phase 4 - Completion
    # ========================================================================

    # validate_global_criteria -> valid or not_valid
    graph.add_conditional_edges(
        "validate_global_criteria",
        route_after_global_validation,
        {
            "valid": "send_multi_success_replies",
            "not_valid": "handle_global_retry",
        },
    )

    # handle_global_retry -> orchestrate_pocs (for retry)
    graph.add_edge("handle_global_retry", "orchestrate_pocs")

    # send_multi_success_replies -> finalize_success -> END
    graph.add_edge("send_multi_success_replies", "finalize_success")
    graph.add_edge("finalize_success", END)

    # finalize_failure -> END
    graph.add_edge("finalize_failure", END)

    logger.info("Multi-POC mail agent graph created successfully")
    return graph


def compile_mail_agent_graph(checkpointer: Any = None) -> Any:
    """
    Compile the mail agent graph with optional checkpointer.

    Args:
        checkpointer: Optional SQLite checkpointer for state persistence.

    Returns:
        Compiled graph ready for invocation.
    """
    graph = create_mail_agent_graph()

    if checkpointer:
        logger.info("Compiling multi-POC graph with checkpointer")
        return graph.compile(checkpointer=checkpointer)
    else:
        logger.info("Compiling multi-POC graph without checkpointer")
        return graph.compile()
