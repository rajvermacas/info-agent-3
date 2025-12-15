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
    set_task_router,
    get_task_router,
)
from mail_agent.agent.nodes.fetch_email import fetch_email
from mail_agent.agent.nodes.extract_content import extract_content
from mail_agent.agent.nodes.validate_response import validate_response
from mail_agent.agent.nodes.decide_next import decide_next

__all__ = [
    "parse_instruction",
    "compose_email",
    "send_email",
    "wait_for_reply",
    "set_webhook_server",
    "get_webhook_server",
    "set_task_router",
    "get_task_router",
    "fetch_email",
    "extract_content",
    "validate_response",
    "decide_next",
]
