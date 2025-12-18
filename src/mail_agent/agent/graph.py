"""
LangGraph State Machine - Mail Agent graph definition.

Defines the complete state machine for the mail agent workflow.
Supports multiple POCs (Points of Contact) with:
- Sequential processing of each POC (legacy mode)
- Parallel processing of all POCs simultaneously (new parallel mode)
- Cross-POC validation for complementary data
- Targeted follow-ups for specific POCs with missing data
"""

import logging
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph

from mail_agent.agent.state import AgentState, all_conversations_complete, get_active_poc
from mail_agent.agent.nodes.parse_instruction import parse_instruction
from mail_agent.agent.nodes.compose_email import compose_email
from mail_agent.agent.nodes.send_email import send_email
from mail_agent.agent.nodes.wait_for_reply import wait_for_reply
from mail_agent.agent.nodes.fetch_email import fetch_email
from mail_agent.agent.nodes.extract_content import extract_content
from mail_agent.agent.nodes.validate_response import validate_response
from mail_agent.agent.nodes.decide_next import (
    decide_next,
    handle_success,
    handle_failure,
    prepare_followup,
)
from mail_agent.agent.nodes.handle_redirect import handle_redirect
from mail_agent.agent.nodes.compose_success_reply import compose_success_reply
from mail_agent.agent.nodes.send_success_reply import send_success_reply
from mail_agent.agent.nodes.select_next_poc import select_next_poc
from mail_agent.agent.nodes.check_more_pocs import check_more_pocs

# Parallel processing nodes
from mail_agent.agent.nodes.compose_all_emails import compose_all_emails
from mail_agent.agent.nodes.send_all_emails import send_all_emails
from mail_agent.agent.nodes.wait_for_all_replies import wait_for_all_replies
from mail_agent.agent.nodes.process_all_replies import process_all_replies
from mail_agent.agent.nodes.handle_parallel_followup import handle_parallel_followup


logger = logging.getLogger(__name__)


# ============================================================================
# Routing Functions
# ============================================================================


def route_after_parse(
    state: AgentState,
) -> Literal["select_next_poc", "end"]:
    """
    Route after parsing instruction.

    Routes to select_next_poc to pick the first POC for processing,
    or to end if there's an error or no POCs parsed.
    """
    error = state.get("error")
    if error:
        logger.debug("Routing after parse: error -> end")
        return "end"

    parsed_request = state.get("parsed_request")
    if parsed_request is None:
        logger.debug("Routing after parse: no request -> end")
        return "end"

    # Check if we have any POCs to process
    poc_emails = parsed_request.get("poc_emails", [])
    if not poc_emails:
        logger.debug("Routing after parse: no POCs -> end")
        return "end"

    logger.debug(f"Routing after parse: {len(poc_emails)} POC(s) -> select_next_poc")
    return "select_next_poc"


def route_after_select_next_poc(
    state: AgentState,
) -> Literal["compose_email", "validate_cross_poc"]:
    """
    Route after selecting next POC.

    If a POC was selected (current_poc is set), route to compose_email.
    If no POC available (all complete), route to cross-POC validation.
    """
    current_poc = state.get("current_poc")

    if current_poc:
        logger.debug(f"Routing after select_next_poc: POC {current_poc} -> compose_email")
        return "compose_email"
    else:
        logger.debug("Routing after select_next_poc: no more POCs -> validate_cross_poc")
        return "validate_cross_poc"


def route_after_validation(
    state: AgentState,
) -> Literal["handle_success", "handle_failure", "prepare_followup", "handle_redirect"]:
    """Route based on validation result using decide_next logic."""
    result = decide_next(state)

    if result == "success":
        return "handle_success"
    elif result == "failure":
        return "handle_failure"
    elif result == "redirect":
        return "handle_redirect"
    else:
        return "prepare_followup"


def route_after_check_more_pocs(
    state: AgentState,
) -> Literal["select_next_poc", "validate_cross_poc"]:
    """
    Route after checking if more POCs need processing.

    If more POCs are pending, route to select_next_poc.
    If all POCs have reached terminal states, route to cross-POC validation.
    """
    all_complete = state.get("_all_pocs_individual_complete", False)

    if all_complete:
        logger.debug("Routing after check_more_pocs: all complete -> validate_cross_poc")
        return "validate_cross_poc"
    else:
        logger.debug("Routing after check_more_pocs: more pending -> select_next_poc")
        return "select_next_poc"


def route_after_cross_poc_validation(
    state: AgentState,
) -> Literal["compose_success_all", "prepare_targeted_followup"]:
    """
    Route after cross-POC validation.

    If all data is valid across POCs, route to success acknowledgment.
    If issues found, route to targeted follow-up preparation.
    """
    is_valid = state.get("_cross_poc_is_valid", True)

    if is_valid:
        logger.debug("Routing after cross-POC validation: valid -> compose_success_all")
        return "compose_success_all"
    else:
        logger.debug("Routing after cross-POC validation: issues -> prepare_targeted_followup")
        return "prepare_targeted_followup"


# ============================================================================
# Graph Builder
# ============================================================================


def create_mail_agent_graph() -> StateGraph:
    """
    Create the mail agent LangGraph state machine with multi-POC support.

    Returns:
        Compiled StateGraph ready for execution.

    Graph Structure (Multi-POC Flow):
        START -> parse_instruction -> select_next_poc
              -> compose_email -> send_email -> wait_for_reply
              -> fetch_email -> extract_content -> validate_response
              -> [handle_success | handle_failure | prepare_followup | handle_redirect]
              -> check_more_pocs
              -> [select_next_poc (if more pending) | validate_cross_poc (if all complete)]
              -> [compose_success_all | prepare_targeted_followup]
              -> END

    Multi-POC Processing:
        1. parse_instruction: Parse all POCs from user instruction
        2. select_next_poc: Pick next pending POC (loop entry point)
        3. Process single POC through email flow
        4. handle_success/failure: Mark POC conversation as complete
        5. check_more_pocs: Check if more POCs need processing
        6. Loop back to select_next_poc OR proceed to cross-POC validation

    Cross-POC Validation:
        After all individual POCs complete, validate_cross_poc checks:
        - Referential integrity between data from different POCs
        - Data completeness when POCs provide complementary information
        - Example: employee.dept_id must exist in department data from another POC

    Targeted Follow-ups:
        If cross-POC validation fails, prepare_targeted_followup:
        - Identifies which specific POC(s) need to provide missing data
        - Resets those POCs for re-processing
        - Does NOT bother POCs whose data is already complete
    """
    logger.info("Creating mail agent graph with multi-POC support")

    # Create graph with state schema
    graph = StateGraph(AgentState)

    # ========================================================================
    # Add Nodes
    # ========================================================================

    # Phase 1: Parse user instruction
    graph.add_node("parse_instruction", parse_instruction)

    # Phase 2: Multi-POC iteration
    graph.add_node("select_next_poc", select_next_poc)
    graph.add_node("check_more_pocs", check_more_pocs)

    # Phase 3: Compose and send email (for current POC)
    graph.add_node("compose_email", compose_email)
    graph.add_node("send_email", send_email)

    # Phase 4: Wait for and process reply
    graph.add_node("wait_for_reply", wait_for_reply)
    graph.add_node("fetch_email", fetch_email)
    graph.add_node("extract_content", extract_content)
    graph.add_node("validate_response", validate_response)

    # Phase 5: Handle individual POC result
    graph.add_node("handle_success", handle_success)
    graph.add_node("handle_failure", handle_failure)
    graph.add_node("prepare_followup", prepare_followup)
    graph.add_node("handle_redirect", handle_redirect)

    # Phase 6: Cross-POC validation (after all individual POCs complete)
    # Placeholder - will be implemented in Phase 2
    from mail_agent.agent.nodes.validate_cross_poc import validate_cross_poc
    graph.add_node("validate_cross_poc", validate_cross_poc)

    # Phase 7: Final result handling
    # Placeholder - will be implemented in Phase 4
    from mail_agent.agent.nodes.compose_success_all import compose_success_all
    from mail_agent.agent.nodes.send_success_all import send_success_all
    from mail_agent.agent.nodes.prepare_targeted_followup import prepare_targeted_followup
    graph.add_node("compose_success_all", compose_success_all)
    graph.add_node("send_success_all", send_success_all)
    graph.add_node("prepare_targeted_followup", prepare_targeted_followup)

    # Legacy nodes for single-POC success acknowledgment
    # (kept for prepare_followup -> single POC retry flow)
    graph.add_node("compose_success_reply", compose_success_reply)
    graph.add_node("send_success_reply", send_success_reply)

    # ========================================================================
    # Add Edges
    # ========================================================================

    # Start -> Parse
    graph.add_edge(START, "parse_instruction")

    # Parse -> Select Next POC (conditional on having POCs)
    graph.add_conditional_edges(
        "parse_instruction",
        route_after_parse,
        {
            "select_next_poc": "select_next_poc",
            "end": END,
        },
    )

    # Select Next POC -> Compose Email OR Cross-POC Validation
    graph.add_conditional_edges(
        "select_next_poc",
        route_after_select_next_poc,
        {
            "compose_email": "compose_email",
            "validate_cross_poc": "validate_cross_poc",
        },
    )

    # Linear flow: Compose -> Send -> Wait -> Fetch -> Extract -> Validate
    graph.add_edge("compose_email", "send_email")
    graph.add_edge("send_email", "wait_for_reply")
    graph.add_edge("wait_for_reply", "fetch_email")
    graph.add_edge("fetch_email", "extract_content")
    graph.add_edge("extract_content", "validate_response")

    # Validate -> Decision (conditional)
    graph.add_conditional_edges(
        "validate_response",
        route_after_validation,
        {
            "handle_success": "handle_success",
            "handle_failure": "handle_failure",
            "prepare_followup": "prepare_followup",
            "handle_redirect": "handle_redirect",
        },
    )

    # After individual POC terminal state -> Check for more POCs
    # Success path: check if more POCs before final acknowledgment
    graph.add_edge("handle_success", "check_more_pocs")

    # Failure path: check if more POCs (one POC failing doesn't stop others)
    graph.add_edge("handle_failure", "check_more_pocs")

    # Redirect path: check if more POCs (redirect creates new conversation)
    graph.add_edge("handle_redirect", "check_more_pocs")

    # Followup -> Back to compose (same POC, retry)
    graph.add_edge("prepare_followup", "compose_email")

    # Check More POCs -> Select Next OR Cross-POC Validation
    graph.add_conditional_edges(
        "check_more_pocs",
        route_after_check_more_pocs,
        {
            "select_next_poc": "select_next_poc",
            "validate_cross_poc": "validate_cross_poc",
        },
    )

    # Cross-POC Validation -> Success All OR Targeted Followup
    graph.add_conditional_edges(
        "validate_cross_poc",
        route_after_cross_poc_validation,
        {
            "compose_success_all": "compose_success_all",
            "prepare_targeted_followup": "prepare_targeted_followup",
        },
    )

    # Success All -> Send Success All -> End
    graph.add_edge("compose_success_all", "send_success_all")
    graph.add_edge("send_success_all", END)

    # Targeted Followup -> Back to Select Next POC (for re-processing)
    graph.add_edge("prepare_targeted_followup", "select_next_poc")

    # Legacy single-POC success reply edges (kept for backward compatibility)
    # These are no longer directly reachable in the new flow
    # but kept in case they're referenced elsewhere
    graph.add_edge("compose_success_reply", "send_success_reply")
    graph.add_edge("send_success_reply", END)

    logger.info("Mail agent graph with multi-POC support created successfully")
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
        logger.info("Compiling graph with checkpointer")
        return graph.compile(checkpointer=checkpointer)
    else:
        logger.info("Compiling graph without checkpointer")
        return graph.compile()


# ============================================================================
# Parallel Processing Routing Functions
# ============================================================================


def route_after_parse_parallel(
    state: AgentState,
) -> Literal["compose_all_emails", "end"]:
    """
    Route after parsing instruction in parallel mode.

    Routes to compose_all_emails to compose for all POCs at once,
    or to end if there's an error or no POCs parsed.
    """
    error = state.get("error")
    if error:
        logger.debug("Routing after parse (parallel): error -> end")
        return "end"

    parsed_request = state.get("parsed_request")
    if parsed_request is None:
        logger.debug("Routing after parse (parallel): no request -> end")
        return "end"

    poc_emails = parsed_request.get("poc_emails", [])
    if not poc_emails:
        logger.debug("Routing after parse (parallel): no POCs -> end")
        return "end"

    logger.debug(
        f"Routing after parse (parallel): {len(poc_emails)} POC(s) -> compose_all_emails"
    )
    return "compose_all_emails"


def route_after_process_all_replies(
    state: AgentState,
) -> Literal["validate_cross_poc", "handle_parallel_followup"]:
    """
    Route after processing all POC replies.

    Routes to cross-POC validation if all individual validations passed,
    or to parallel follow-up handling if some need re-processing.
    """
    all_valid = state.get("_all_individual_valid", False)
    followup_pocs = state.get("_followup_pocs")

    if all_valid:
        logger.debug("Routing after process_all: all valid -> validate_cross_poc")
        return "validate_cross_poc"
    elif followup_pocs:
        logger.debug(
            f"Routing after process_all: {len(followup_pocs)} need follow-up "
            "-> handle_parallel_followup"
        )
        return "handle_parallel_followup"
    else:
        # All invalid but no followups needed (max attempts reached)
        logger.debug("Routing after process_all: no follow-ups -> validate_cross_poc")
        return "validate_cross_poc"


def route_after_parallel_followup(
    state: AgentState,
) -> Literal["compose_all_emails", "validate_cross_poc"]:
    """
    Route after handling parallel follow-up.

    Routes back to compose_all_emails if there are POCs needing follow-up,
    or to cross-POC validation if all POCs have reached terminal state.
    """
    followup_pocs = state.get("_followup_pocs")

    if followup_pocs:
        logger.debug(
            f"Routing after parallel followup: {len(followup_pocs)} POCs "
            "-> compose_all_emails"
        )
        return "compose_all_emails"
    else:
        logger.debug(
            "Routing after parallel followup: no more follow-ups -> validate_cross_poc"
        )
        return "validate_cross_poc"


def route_after_cross_poc_validation_parallel(
    state: AgentState,
) -> Literal["compose_success_all", "handle_parallel_followup"]:
    """
    Route after cross-POC validation in parallel mode.

    Same as sequential mode but routes to parallel followup handler.
    """
    is_valid = state.get("_cross_poc_is_valid", True)

    if is_valid:
        logger.debug(
            "Routing after cross-POC validation (parallel): valid -> compose_success_all"
        )
        return "compose_success_all"
    else:
        logger.debug(
            "Routing after cross-POC validation (parallel): issues "
            "-> handle_parallel_followup"
        )
        return "handle_parallel_followup"


# ============================================================================
# Parallel Graph Builder
# ============================================================================


def create_mail_agent_graph_parallel() -> StateGraph:
    """
    Create the mail agent LangGraph state machine with PARALLEL POC processing.

    This graph sends emails to ALL POCs simultaneously and processes
    all replies in parallel, significantly reducing total wait time.

    Returns:
        Compiled StateGraph ready for execution.

    Graph Structure (Parallel Flow):
        START -> parse_instruction -> compose_all_emails
              -> send_all_emails -> wait_for_all_replies
              -> process_all_replies
              -> [validate_cross_poc | handle_parallel_followup]
              -> [compose_success_all | loop back for follow-ups]
              -> END

    Parallel Processing Flow:
        1. parse_instruction: Parse all POCs from user instruction
        2. compose_all_emails: Compose emails for ALL POCs (concurrent LLM calls)
        3. send_all_emails: Send to ALL POCs simultaneously
        4. wait_for_all_replies: Single interrupt, TaskManager collects webhooks
        5. process_all_replies: Fetch, extract, validate ALL replies concurrently
        6. Route to follow-up or cross-POC validation
        7. Cross-POC validation (same as sequential)
        8. Success or targeted follow-up

    Time Complexity:
        Sequential: O(T_poc1 + T_poc2 + ... + T_pocN)
        Parallel:   O(max(T_poc1, T_poc2, ..., T_pocN))
    """
    logger.info("Creating mail agent graph with PARALLEL POC processing")

    graph = StateGraph(AgentState)

    # ========================================================================
    # Add Nodes
    # ========================================================================

    # Phase 1: Parse user instruction
    graph.add_node("parse_instruction", parse_instruction)

    # Phase 2: Parallel Compose and Send
    graph.add_node("compose_all_emails", compose_all_emails)
    graph.add_node("send_all_emails", send_all_emails)

    # Phase 3: Parallel Wait
    graph.add_node("wait_for_all_replies", wait_for_all_replies)

    # Phase 4: Parallel Process
    graph.add_node("process_all_replies", process_all_replies)

    # Phase 5: Parallel Follow-up Handler
    graph.add_node("handle_parallel_followup", handle_parallel_followup)

    # Phase 6: Cross-POC validation
    from mail_agent.agent.nodes.validate_cross_poc import validate_cross_poc
    graph.add_node("validate_cross_poc", validate_cross_poc)

    # Phase 7: Final result handling
    from mail_agent.agent.nodes.compose_success_all import compose_success_all
    from mail_agent.agent.nodes.send_success_all import send_success_all
    graph.add_node("compose_success_all", compose_success_all)
    graph.add_node("send_success_all", send_success_all)

    # ========================================================================
    # Add Edges
    # ========================================================================

    # Start -> Parse
    graph.add_edge(START, "parse_instruction")

    # Parse -> Compose All (conditional on having POCs)
    graph.add_conditional_edges(
        "parse_instruction",
        route_after_parse_parallel,
        {
            "compose_all_emails": "compose_all_emails",
            "end": END,
        },
    )

    # Linear flow: Compose All -> Send All -> Wait All -> Process All
    graph.add_edge("compose_all_emails", "send_all_emails")
    graph.add_edge("send_all_emails", "wait_for_all_replies")
    graph.add_edge("wait_for_all_replies", "process_all_replies")

    # Process All -> Cross-POC Validation or Parallel Followup
    graph.add_conditional_edges(
        "process_all_replies",
        route_after_process_all_replies,
        {
            "validate_cross_poc": "validate_cross_poc",
            "handle_parallel_followup": "handle_parallel_followup",
        },
    )

    # Parallel Followup -> Compose All (retry) or Cross-POC Validation
    graph.add_conditional_edges(
        "handle_parallel_followup",
        route_after_parallel_followup,
        {
            "compose_all_emails": "compose_all_emails",
            "validate_cross_poc": "validate_cross_poc",
        },
    )

    # Cross-POC Validation -> Success All or Parallel Followup
    graph.add_conditional_edges(
        "validate_cross_poc",
        route_after_cross_poc_validation_parallel,
        {
            "compose_success_all": "compose_success_all",
            "handle_parallel_followup": "handle_parallel_followup",
        },
    )

    # Success All -> Send Success All -> End
    graph.add_edge("compose_success_all", "send_success_all")
    graph.add_edge("send_success_all", END)

    logger.info("Mail agent PARALLEL graph created successfully")
    return graph


def compile_mail_agent_graph_parallel(checkpointer: Any = None) -> Any:
    """
    Compile the PARALLEL mail agent graph with optional checkpointer.

    Args:
        checkpointer: Optional SQLite checkpointer for state persistence.

    Returns:
        Compiled graph ready for invocation.
    """
    graph = create_mail_agent_graph_parallel()

    if checkpointer:
        logger.info("Compiling PARALLEL graph with checkpointer")
        return graph.compile(checkpointer=checkpointer)
    else:
        logger.info("Compiling PARALLEL graph without checkpointer")
        return graph.compile()
