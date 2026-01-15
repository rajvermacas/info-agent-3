"""
Agent nodes - Individual state machine nodes.

This module exports all LangGraph nodes for both single-POC (legacy)
and multi-POC orchestration workflows.
"""

# Single-POC (legacy) nodes
from mail_agent.agent.nodes.parse_instruction import parse_instruction
from mail_agent.agent.nodes.compose_email import compose_email
from mail_agent.agent.nodes.send_email import send_email
from mail_agent.agent.nodes.wait_for_reply import (
    wait_for_reply,
    set_webhook_server,
    get_webhook_server,
    set_a2a_mode,
    is_a2a_mode,
)
from mail_agent.agent.nodes.fetch_email import fetch_email
from mail_agent.agent.nodes.extract_content import extract_content
from mail_agent.agent.nodes.validate_response import validate_response
from mail_agent.agent.nodes.decide_next import decide_next
from mail_agent.agent.nodes.handle_redirect import handle_redirect
from mail_agent.agent.nodes.compose_success_reply import compose_success_reply
from mail_agent.agent.nodes.send_success_reply import send_success_reply

# Multi-POC orchestration nodes
from mail_agent.agent.nodes.parse_multi_poc_instruction import (
    parse_multi_poc_instruction,
)
from mail_agent.agent.nodes.build_dependency_graph import (
    build_dependency_graph,
    CircularDependencyError,
)
from mail_agent.agent.nodes.orchestrate_pocs import (
    orchestrate_pocs,
    get_orchestration_decision,
    should_execute,
    should_wait,
    should_aggregate,
    should_fail,
)
from mail_agent.agent.nodes.inject_poc_context import inject_poc_context
from mail_agent.agent.nodes.validate_poc_response import validate_poc_response
from mail_agent.agent.nodes.aggregate_poc_responses import (
    aggregate_poc_responses,
    get_aggregated_data,
)
from mail_agent.agent.nodes.detect_conflicts import (
    detect_conflicts,
    has_conflicts,
    get_conflicts,
)
from mail_agent.agent.nodes.resolve_conflicts import (
    resolve_conflicts,
    needs_conflict_retry,
)
from mail_agent.agent.nodes.validate_global_criteria import (
    validate_global_criteria,
    is_global_valid,
    get_global_validation_result,
)
from mail_agent.agent.nodes.send_multi_success_replies import (
    send_multi_success_replies,
)


__all__ = [
    # Single-POC (legacy) nodes
    "parse_instruction",
    "compose_email",
    "send_email",
    "wait_for_reply",
    "set_webhook_server",
    "get_webhook_server",
    "set_a2a_mode",
    "is_a2a_mode",
    "fetch_email",
    "extract_content",
    "validate_response",
    "decide_next",
    "handle_redirect",
    "compose_success_reply",
    "send_success_reply",
    # Multi-POC orchestration nodes
    "parse_multi_poc_instruction",
    "build_dependency_graph",
    "CircularDependencyError",
    "orchestrate_pocs",
    "get_orchestration_decision",
    "should_execute",
    "should_wait",
    "should_aggregate",
    "should_fail",
    "inject_poc_context",
    "validate_poc_response",
    "aggregate_poc_responses",
    "get_aggregated_data",
    "detect_conflicts",
    "has_conflicts",
    "get_conflicts",
    "resolve_conflicts",
    "needs_conflict_retry",
    "validate_global_criteria",
    "is_global_valid",
    "get_global_validation_result",
    "send_multi_success_replies",
]
