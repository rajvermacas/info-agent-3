"""
Send Multi Success Replies Node - Send acknowledgment emails to successful POCs.

Sends thank-you emails to all POCs that provided valid data,
summarizing what was received and confirming success.
"""

import logging
from typing import Any

from mail_agent.agent.multi_poc_helpers import (
    get_completed_pocs,
    get_execution_plan,
    get_poc_state,
)
from mail_agent.agent.multi_poc_state import POCStatus
from mail_agent.agent.state import AgentState
from mail_agent.config import get_settings
from mail_agent.llm.client import LLMClient
from mail_agent.llm.prompts import PromptTemplates, SuccessAcknowledgmentEmail
from mail_agent.tools.smtp_sender import SMTPSenderService


logger = logging.getLogger(__name__)


async def send_multi_success_replies(state: AgentState) -> dict[str, Any]:
    """
    Send success acknowledgment emails to all completed POCs.

    This node:
    1. Gets all successfully completed POCs
    2. For each POC, composes and sends a thank-you email
    3. Summarizes what data was received from each

    Args:
        state: Current agent state with poc_states.

    Returns:
        State update with progress messages about sent acknowledgments.
    """
    logger.info("Sending success replies to completed POCs")

    try:
        execution_plan = get_execution_plan(state)
        completed_poc_ids = get_completed_pocs(state)

        if not completed_poc_ids:
            logger.info("No completed POCs to acknowledge")
            return {
                "current_node": "send_multi_success_replies",
                "progress_messages": ["No POCs to acknowledge"],
            }

        settings = get_settings()
        llm_client = LLMClient(settings)
        smtp_sender = SMTPSenderService(settings)

        sent_count = 0
        failed_count = 0
        progress_messages: list[str] = []

        for poc_id in completed_poc_ids:
            try:
                poc_state = get_poc_state(state, poc_id)

                # Only send to POCs with valid completed status
                if poc_state.status != POCStatus.COMPLETED:
                    logger.debug(f"Skipping POC {poc_id} (status={poc_state.status})")
                    continue

                # Find POC requirement
                poc_req = next(
                    (p for p in execution_plan.pocs if p.id == poc_id),
                    None
                )
                if not poc_req:
                    logger.warning(f"Could not find requirement for POC {poc_id}")
                    continue

                # Get validation feedback for summary
                validation_feedback = "Response validated successfully."
                if poc_state.validation_result:
                    criteria_met = poc_state.validation_result.criteria_met
                    if criteria_met:
                        validation_feedback = (
                            f"Criteria met: {', '.join(criteria_met[:5])}"
                        )
                        if len(criteria_met) > 5:
                            validation_feedback += f" (+{len(criteria_met) - 5} more)"

                # Get original subject for reply
                original_subject = "Information Request"
                if poc_state.original_email and poc_state.original_email.get("subject"):
                    original_subject = poc_state.original_email["subject"]

                # Compose success email using LLM
                prompt = PromptTemplates.compose_success_acknowledgment(
                    poc_email=poc_req.email,
                    request_description=poc_req.request,
                    success_criteria=poc_req.success_criteria,
                    validation_feedback=validation_feedback,
                    original_subject=original_subject,
                )

                success_system_prompt = PromptTemplates.SUCCESS_ACKNOWLEDGMENT_SYSTEM.format(
                    agent_email=settings.agent_email
                )

                composed: SuccessAcknowledgmentEmail = await llm_client.generate_structured(
                    prompt=prompt,
                    output_schema=SuccessAcknowledgmentEmail,
                    system_prompt=success_system_prompt,
                )

                # Send the email
                await smtp_sender.send_email(
                    to_addresses=[poc_req.email],
                    subject=composed.subject,
                    body_text=composed.body,
                    from_address=settings.agent_email,
                )

                sent_count += 1
                logger.info(f"Sent acknowledgment to {poc_req.email}")
                progress_messages.append(
                    f"Sent acknowledgment to {poc_req.email}"
                )

            except Exception as e:
                failed_count += 1
                logger.error(f"Failed to send acknowledgment to POC {poc_id}: {e}")
                progress_messages.append(
                    f"Failed to acknowledge {poc_id}: {str(e)[:50]}"
                )

        # Final summary
        summary = f"Sent {sent_count} acknowledgment(s)"
        if failed_count > 0:
            summary += f", {failed_count} failed"

        logger.info(summary)
        progress_messages.append(summary)

        return {
            "current_node": "send_multi_success_replies",
            "progress_messages": progress_messages,
        }

    except Exception as e:
        error_msg = f"Failed to send success replies: {e}"
        logger.error(error_msg, exc_info=True)
        return {
            "error": error_msg,
            "current_node": "error",
            "progress_messages": [f"ERROR: {error_msg}"],
        }
