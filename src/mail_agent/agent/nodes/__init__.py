"""Agent nodes for LangGraph state machine."""

from mail_agent.agent.nodes.compose_email import compose_email_node
from mail_agent.agent.nodes.decide_next import compose_followup_node, decide_next_node
from mail_agent.agent.nodes.extract_content import extract_content_node
from mail_agent.agent.nodes.fetch_email import fetch_email_node
from mail_agent.agent.nodes.parse_instruction import parse_instruction_node
from mail_agent.agent.nodes.send_email import send_email_node
from mail_agent.agent.nodes.validate_response import validate_response_node
from mail_agent.agent.nodes.wait_for_reply import wait_for_reply_node

__all__ = [
    "parse_instruction_node",
    "compose_email_node",
    "compose_followup_node",
    "send_email_node",
    "wait_for_reply_node",
    "fetch_email_node",
    "extract_content_node",
    "validate_response_node",
    "decide_next_node",
]
