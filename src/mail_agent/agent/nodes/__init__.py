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

# Multi-POC support nodes (sequential)
from mail_agent.agent.nodes.select_next_poc import select_next_poc
from mail_agent.agent.nodes.check_more_pocs import check_more_pocs
from mail_agent.agent.nodes.validate_cross_poc import validate_cross_poc
from mail_agent.agent.nodes.compose_success_all import compose_success_all
from mail_agent.agent.nodes.send_success_all import send_success_all
from mail_agent.agent.nodes.prepare_targeted_followup import prepare_targeted_followup

# Parallel processing nodes (multi-POC parallel)
from mail_agent.agent.nodes.compose_all_emails import compose_all_emails
from mail_agent.agent.nodes.send_all_emails import send_all_emails
from mail_agent.agent.nodes.wait_for_all_replies import wait_for_all_replies
from mail_agent.agent.nodes.process_all_replies import process_all_replies
from mail_agent.agent.nodes.handle_parallel_followup import handle_parallel_followup

__all__ = [
    # Original nodes
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
    # Multi-POC support nodes (sequential)
    "select_next_poc",
    "check_more_pocs",
    "validate_cross_poc",
    "compose_success_all",
    "send_success_all",
    "prepare_targeted_followup",
    # Parallel processing nodes (multi-POC parallel)
    "compose_all_emails",
    "send_all_emails",
    "wait_for_all_replies",
    "process_all_replies",
    "handle_parallel_followup",
]
