"""
LangGraph State Machine - Mail Agent graph definition.

Defines the state machine for:
- Multi-contact dispatch (send to multiple POCs without waiting after each send)
- Interrupt-based waiting for replies (non-blocking A2A)
- Per-POC validation + follow-ups (max attempts)
- Global validation across POCs before final completion
"""

import logging
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph

from mail_agent.agent.state import AgentState
from mail_agent.agent.nodes.parse_instruction import parse_instruction
from mail_agent.agent.nodes.compile_contract import compile_contract
from mail_agent.agent.nodes.orchestrate import orchestrate
from mail_agent.agent.nodes.compose_email import compose_email
from mail_agent.agent.nodes.send_email import send_email
from mail_agent.agent.nodes.wait_for_any_reply import wait_for_any_reply
from mail_agent.agent.nodes.fetch_email import fetch_email
from mail_agent.agent.nodes.extract_content import extract_content
from mail_agent.agent.nodes.validate_response import validate_response
from mail_agent.agent.nodes.validate_global import validate_global
from mail_agent.agent.nodes.decide_next import (
    decide_next,
    handle_success,
    handle_failure,
    prepare_followup,
)
from mail_agent.agent.nodes.handle_redirect import handle_redirect
from mail_agent.agent.nodes.compose_success_reply import compose_success_reply
from mail_agent.agent.nodes.send_success_reply import send_success_reply


logger = logging.getLogger(__name__)


def route_after_parse(state: AgentState) -> Literal["compile_contract", "end"]:
    error = state.get("error")
    if error or state.get("parsed_request") is None:
        return "end"
    return "compile_contract"


def route_after_orchestrate(
    state: AgentState,
) -> Literal["compose_email", "wait_for_any_reply", "validate_global", "end"]:
    next_step = state.get("orchestrator_next")
    if next_step in ("compose_email", "wait_for_any_reply", "validate_global"):
        return next_step  # type: ignore[return-value]
    return "end"


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


def route_after_validation(
    state: AgentState,
) -> Literal["handle_success", "handle_failure", "prepare_followup", "handle_redirect"]:
    result = decide_next(state)
    if result == "success":
        return "handle_success"
    if result == "failure":
        return "handle_failure"
    if result == "redirect":
        return "handle_redirect"
    return "prepare_followup"


# ============================================================================
# Graph Builder
# ============================================================================


def create_mail_agent_graph() -> StateGraph:
    """
    Create the mail agent LangGraph state machine.

    Returns:
        Compiled StateGraph ready for execution.

    Graph Structure:
        START -> parse_instruction -> compile_contract -> orchestrate
        orchestrate -> [compose_email -> send_email -> orchestrate]*
        orchestrate -> wait_for_any_reply -> fetch_email -> extract_content -> validate_response
                    -> [handle_success | handle_failure | prepare_followup | handle_redirect]
                    -> [compose_success_reply -> send_success_reply]?
                    -> orchestrate
        orchestrate -> validate_global -> orchestrate -> END
    """
    logger.info("Creating mail agent graph")

    # Create graph with state schema
    graph = StateGraph(AgentState)

    # ========================================================================
    # Add Nodes
    # ========================================================================

    # Phase 1: Parse user instruction
    graph.add_node("parse_instruction", parse_instruction)
    graph.add_node("compile_contract", compile_contract)
    graph.add_node("orchestrate", orchestrate)

    # Phase 2: Compose and send email
    graph.add_node("compose_email", compose_email)
    graph.add_node("send_email", send_email)

    # Phase 3: Wait for and process reply
    graph.add_node("wait_for_any_reply", wait_for_any_reply)
    graph.add_node("fetch_email", fetch_email)
    graph.add_node("extract_content", extract_content)
    graph.add_node("validate_response", validate_response)
    graph.add_node("validate_global", validate_global)

    # Phase 4: Handle result
    graph.add_node("handle_success", handle_success)
    graph.add_node("handle_failure", handle_failure)
    graph.add_node("prepare_followup", prepare_followup)
    graph.add_node("handle_redirect", handle_redirect)

    # Phase 5: Success acknowledgment
    graph.add_node("compose_success_reply", compose_success_reply)
    graph.add_node("send_success_reply", send_success_reply)

    # ========================================================================
    # Add Edges
    # ========================================================================

    # Start -> Parse
    graph.add_edge(START, "parse_instruction")

    # Parse -> Compile contract (conditional)
    graph.add_conditional_edges(
        "parse_instruction",
        route_after_parse,
        {
            "compile_contract": "compile_contract",
            "end": END,
        },
    )

    graph.add_edge("compile_contract", "orchestrate")

    graph.add_conditional_edges(
        "orchestrate",
        route_after_orchestrate,
        {
            "compose_email": "compose_email",
            "wait_for_any_reply": "wait_for_any_reply",
            "validate_global": "validate_global",
            "end": END,
        },
    )

    # Compose -> Send -> back to orchestrate (dispatch without waiting)
    graph.add_edge("compose_email", "send_email")
    graph.add_edge("send_email", "orchestrate")

    # Wait -> Fetch -> Extract -> Validate
    graph.add_edge("wait_for_any_reply", "fetch_email")
    graph.add_edge("fetch_email", "extract_content")
    graph.add_edge("extract_content", "validate_response")

    # Validate -> Decision (conditional, per POC)
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

    # Success path -> Compose and send acknowledgment -> back to orchestrate
    graph.add_edge("handle_success", "compose_success_reply")
    graph.add_edge("compose_success_reply", "send_success_reply")
    graph.add_edge("send_success_reply", "orchestrate")

    graph.add_edge("handle_failure", "orchestrate")
    graph.add_edge("prepare_followup", "orchestrate")
    graph.add_edge("handle_redirect", "orchestrate")

    # Global validate always returns to orchestrate (which will end on success or chase on fail)
    graph.add_edge("validate_global", "orchestrate")

    logger.info("Mail agent graph created successfully")
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
