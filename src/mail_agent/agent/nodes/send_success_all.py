"""
Send Success All Node - Sends success acknowledgment emails to all POCs.

This node dispatches the composed success acknowledgment emails to all
successful POCs and generates the final summary.
"""

import logging
from datetime import datetime
from typing import Any
from uuid import uuid4

from mail_agent.agent.state import (
    AgentState,
    ConversationState,
    SentEmail,
    update_conversation,
    get_conversation,
)
from mail_agent.tools.smtp_sender import SMTPSenderService
from mail_agent.config import get_settings


logger = logging.getLogger(__name__)


async def send_success_all(state: AgentState) -> dict[str, Any]:
    """
    Send success acknowledgment emails to all successful POCs.

    This node sends the emails composed by compose_success_all and
    generates the final summary of the entire multi-POC operation.

    Args:
        state: Current agent state with _success_emails from compose_success_all.

    Returns:
        State update with:
        - final_summary: Complete summary of the operation
        - conversations: Updated with sent acknowledgment emails
        - current_node: "send_success_all"
        - progress_messages: Send status
    """
    logger.info("Sending success acknowledgment emails to all POCs")

    settings = get_settings()
    agent_email = settings.agent_email

    # Get composed emails
    success_emails = state.get("_success_emails", [])

    if not success_emails:
        logger.warning("No success emails to send")
        return {
            "final_summary": _generate_final_summary(state, []),
            "current_node": "send_success_all",
            "progress_messages": ["No success emails to send."],
        }

    # Send each email
    sent_results = []
    conversations = dict(state.get("conversations", {}))
    smtp_sender = SMTPSenderService(settings)

    for email_info in success_emails:
        poc_email = email_info["poc_email"]
        subject = email_info["subject"]
        body = email_info["body"]

        try:
            # Send via SMTP
            await smtp_sender.send_email(
                to_addresses=[poc_email],
                subject=subject,
                body_text=body,
                from_address=agent_email,
            )
            email_id = uuid4()

            logger.info(f"Sent success acknowledgment to {poc_email}, email_id={email_id}")

            # Record in conversation
            if poc_email in conversations:
                conv = ConversationState.from_dict(conversations[poc_email])
                conv.sent_emails.append(SentEmail(
                    email_id=email_id,
                    subject=subject,
                    body=body,
                    sent_at=datetime.now(),
                ))
                conversations[poc_email] = conv.to_dict()

            sent_results.append({
                "poc_email": poc_email,
                "success": True,
                "email_id": str(email_id),
            })

        except Exception as e:
            logger.exception(f"Failed to send success email to {poc_email}: {e}")
            sent_results.append({
                "poc_email": poc_email,
                "success": False,
                "error": str(e),
            })

    # Count successes/failures
    successful_sends = sum(1 for r in sent_results if r["success"])
    failed_sends = len(sent_results) - successful_sends

    logger.info(
        f"Success email send results: {successful_sends} sent, {failed_sends} failed"
    )

    # Generate final summary
    final_summary = _generate_final_summary(state, sent_results)

    progress_msg = (
        f"Sent {successful_sends} success acknowledgment email(s)"
    )
    if failed_sends > 0:
        progress_msg += f" ({failed_sends} failed)"

    return {
        "final_summary": final_summary,
        "conversations": conversations,
        "current_node": "send_success_all",
        "progress_messages": [progress_msg, "Task completed successfully."],
    }


def _generate_final_summary(
    state: AgentState,
    sent_results: list[dict[str, Any]],
) -> str:
    """
    Generate comprehensive final summary of the multi-POC operation.

    Args:
        state: Current agent state.
        sent_results: Results of sending acknowledgment emails.

    Returns:
        Human-readable summary string.
    """
    conversations = state.get("conversations", {})
    user_instruction = state.get("user_instruction", "N/A")

    # Count by status
    status_counts = {
        "success": 0,
        "failed": 0,
        "redirected": 0,
    }

    poc_details = []
    for poc_email, conv_dict in conversations.items():
        status = conv_dict.get("status", "unknown")
        attempt_count = conv_dict.get("attempt_count", 0)

        if status in status_counts:
            status_counts[status] += 1

        poc_details.append(f"  - {poc_email}: {status} (attempts: {attempt_count})")

    # Build summary
    lines = [
        "=" * 60,
        "MULTI-POC EMAIL TASK COMPLETED",
        "=" * 60,
        "",
        f"Original Request: {user_instruction[:100]}{'...' if len(user_instruction) > 100 else ''}",
        "",
        f"POC Summary:",
        f"  Total POCs: {len(conversations)}",
        f"  Successful: {status_counts['success']}",
        f"  Failed: {status_counts['failed']}",
        f"  Redirected: {status_counts['redirected']}",
        "",
        "POC Details:",
        *poc_details,
        "",
    ]

    # Add acknowledgment send results
    if sent_results:
        ack_success = sum(1 for r in sent_results if r["success"])
        lines.extend([
            f"Acknowledgment Emails Sent: {ack_success}/{len(sent_results)}",
            "",
        ])

    # Cross-POC validation status
    cross_valid = state.get("_cross_poc_is_valid")
    if cross_valid is not None:
        lines.append(f"Cross-POC Validation: {'PASSED' if cross_valid else 'ISSUES FOUND'}")

        issues = state.get("_cross_poc_issues", [])
        if issues:
            lines.append(f"  Issues Found: {len(issues)}")
            for issue in issues[:3]:
                lines.append(
                    f"    - {issue.get('source_poc')} -> {issue.get('target_poc')}: "
                    f"{issue.get('issue_type')}"
                )
            if len(issues) > 3:
                lines.append(f"    ... and {len(issues) - 3} more")

    lines.extend([
        "",
        "=" * 60,
    ])

    return "\n".join(lines)
