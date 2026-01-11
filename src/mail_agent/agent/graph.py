"""
LangGraph State Machine - Mail Agent graph definition.

Defines the complete state machine for the mail agent workflow.
Includes support for email redirects when POC suggests another contact.
"""

import logging
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph

from mail_agent.agent.state import AgentState, all_conversations_complete
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


logger = logging.getLogger(__name__)


# ============================================================================
# Routing Functions
# ============================================================================


def route_after_parse(state: AgentState) -> Literal["compose_email", "end"]:
    """Route after parsing instruction."""
    error = state.get("error")
    if error:
        logger.debug("Routing after parse: error -> end")
        return "end"

    parsed_request = state.get("parsed_request")
    if parsed_request is None:
        logger.debug("Routing after parse: no request -> end")
        return "end"

    logger.debug("Routing after parse: -> compose_email")
    return "compose_email"


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


def route_after_terminal(state: AgentState) -> Literal["end"]:
    """
    Route after terminal state (success/failure).

    For now, we only support single POC, so always go to end.
    For multi-POC support, this would check if other POCs need processing.
    """
    # Check if all conversations are complete
    if all_conversations_complete(state):
        logger.debug("All conversations complete -> end")
        return "end"

    # For multi-POC support (future):
    # Would return to compose_email for next POC
    logger.debug("Routing to end (single POC mode)")
    return "end"


# ============================================================================
# Graph Builder
# ============================================================================


def create_mail_agent_graph() -> StateGraph:
    """
    Create the mail agent LangGraph state machine.

    Returns:
        Compiled StateGraph ready for execution.

    Graph Structure:
        START -> parse_instruction -> compose_email -> send_email -> wait_for_reply
              -> fetch_email -> extract_content -> validate_response
              -> [handle_success | handle_failure | prepare_followup | handle_redirect]
              -> END (or loop back to compose_email for followup/redirect)

    Redirect Flow:
        When a POC responds with "I'm not the right contact, email xyz@abc.com":
        validate_response -> handle_redirect -> compose_email (for new POC)
    """
    logger.info("Creating mail agent graph")

    # Create graph with state schema
    graph = StateGraph(AgentState)

    # ========================================================================
    # Add Nodes
    # ========================================================================

    # Phase 1: Parse user instruction
    graph.add_node("parse_instruction", parse_instruction)

    # Phase 2: Compose and send email
    graph.add_node("compose_email", compose_email)
    graph.add_node("send_email", send_email)

    # Phase 3: Wait for and process reply
    graph.add_node("wait_for_reply", wait_for_reply)
    graph.add_node("fetch_email", fetch_email)
    graph.add_node("extract_content", extract_content)
    graph.add_node("validate_response", validate_response)

    # Phase 4: Handle result
    graph.add_node("handle_success", handle_success)
    graph.add_node("handle_failure", handle_failure)
    graph.add_node("prepare_followup", prepare_followup)
    graph.add_node("handle_redirect", handle_redirect)

    # ========================================================================
    # Add Edges
    # ========================================================================

    # Start -> Parse
    graph.add_edge(START, "parse_instruction")

    # Parse -> Compose (conditional)
    graph.add_conditional_edges(
        "parse_instruction",
        route_after_parse,
        {
            "compose_email": "compose_email",
            "end": END,
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

    # Terminal states -> End
    graph.add_edge("handle_success", END)
    graph.add_edge("handle_failure", END)

    # Followup -> Back to compose
    graph.add_edge("prepare_followup", "compose_email")

    # Redirect -> Back to compose (for new POC)
    graph.add_edge("handle_redirect", "compose_email")

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
