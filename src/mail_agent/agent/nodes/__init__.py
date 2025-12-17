"""
Agent nodes - Individual state machine nodes.
"""

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

__all__ = [
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
]
