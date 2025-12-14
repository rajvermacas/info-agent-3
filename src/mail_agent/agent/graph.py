"""LangGraph state machine for Mail Agent."""

import logging
from datetime import datetime

from langgraph.graph import START, StateGraph
from langgraph.checkpoint.sqlite import SqliteSaver

from mail_agent.agent.nodes import (
    parse_instruction_node,
    compose_email_node,
    compose_followup_node,
    send_email_node,
    wait_for_reply_node,
    fetch_email_node,
    extract_content_node,
    validate_response_node,
    decide_next_node,
)
from mail_agent.agent.state import AgentState
from mail_agent.config import get_settings

logger = logging.getLogger(__name__)


def create_agent_graph():
    """Create and compile LangGraph state machine for agent.

    Graph structure:
    START -> parse_instruction -> decide_next (routing)

    Routing from decide_next:
    - "compose_email" -> compose_email -> send_email -> wait_for_reply -> decide_next
    - "compose_followup" -> compose_followup -> send_email -> wait_for_reply -> decide_next
    - "end" -> end node (generate summary)

    State persistence:
    - Uses SQLite checkpointer from config
    - Maintains conversation state across graph executions
    - Enables resuming interrupted executions

    Returns:
        Compiled StateGraph with SQLite checkpointer
    """
    logger.info("Creating agent graph")

    # Create graph
    graph = StateGraph(AgentState)

    # Add nodes
    logger.debug("Adding nodes to graph")

    graph.add_node("parse_instruction", parse_instruction_node)
    graph.add_node("compose_email", compose_email_node)
    graph.add_node("compose_followup", compose_followup_node)
    graph.add_node("send_email", send_email_node)
    graph.add_node("wait_for_reply", wait_for_reply_node)
    graph.add_node("fetch_email", fetch_email_node)
    graph.add_node("extract_content", extract_content_node)
    graph.add_node("validate_response", validate_response_node)
    graph.add_node("decide_next", decide_next_node)

    # Add end node function
    async def end_node(state: AgentState) -> AgentState:
        """End node - generate final summary."""
        logger.info("end_node: Starting")

        conversations = state.get("conversations", {})
        progress_messages = state.get("progress_messages", [])

        # Count results
        success_count = 0
        failed_count = 0

        for conv in conversations.values():
            final_result = conv.get("final_result")
            if final_result == "success":
                success_count += 1
            elif final_result and final_result.startswith("failed"):
                failed_count += 1

        # Generate summary
        total_pocs = len(conversations)
        summary = (
            f"Mail Agent Execution Complete\n"
            f"Total POCs: {total_pocs}\n"
            f"Successful: {success_count}\n"
            f"Failed: {failed_count}\n"
            f"\nProgress Summary:\n" +
            "\n".join(progress_messages[-20:])  # Last 20 messages
        )

        state["final_summary"] = summary
        state["current_node"] = "end"
        state["completed_at"] = datetime.utcnow().isoformat()

        logger.info("end_node: Completed")

        return state

    graph.add_node("end", end_node)

    # Add edges
    logger.debug("Adding edges to graph")

    # START -> parse_instruction
    graph.add_edge(START, "parse_instruction")

    # parse_instruction -> decide_next
    graph.add_edge("parse_instruction", "decide_next")

    # decide_next -> routing (conditional)
    def route_from_decide(output):
        """Route based on decide_next output."""
        # decide_next returns {"next_node": ..., "state": ...}
        if isinstance(output, dict) and "next_node" in output:
            return output["next_node"]
        logger.warning(f"route_from_decide: Unexpected output: {output}")
        return "end"

    graph.add_conditional_edges("decide_next", route_from_decide)

    # compose_email -> send_email
    graph.add_edge("compose_email", "send_email")

    # compose_followup -> send_email
    graph.add_edge("compose_followup", "send_email")

    # send_email -> wait_for_reply
    graph.add_edge("send_email", "wait_for_reply")

    # wait_for_reply -> fetch_email
    graph.add_edge("wait_for_reply", "fetch_email")

    # fetch_email -> extract_content
    graph.add_edge("fetch_email", "extract_content")

    # extract_content -> validate_response
    graph.add_edge("extract_content", "validate_response")

    # validate_response -> decide_next
    graph.add_edge("validate_response", "decide_next")

    # end node has no outgoing edges (terminal)

    logger.info("Agent graph created successfully")

    # Create SQLite checkpointer
    settings = get_settings()
    db_path = settings.sqlite_db_path

    logger.info(f"Creating SQLite checkpointer: {db_path}")

    checkpointer = SqliteSaver(db_path)

    # Compile graph with checkpointer
    compiled_graph = graph.compile(checkpointer=checkpointer)

    logger.info("Agent graph compiled with checkpointer")

    return compiled_graph


def initialize_agent_state(user_instruction: str) -> AgentState:
    """Initialize fresh agent state for new execution.

    Args:
        user_instruction: User's email request instruction

    Returns:
        AgentState: Fresh state ready for graph execution
    """
    logger.info(f"Initializing agent state: instruction_len={len(user_instruction)}")

    return AgentState(
        user_instruction=user_instruction,
        parsed_request=None,
        conversations={},
        current_node="start",
        pending_webhooks=[],
        progress_messages=[],
        final_summary=None,
        started_at=datetime.utcnow().isoformat(),
        completed_at=None,
    )
