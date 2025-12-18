"""
Process All Replies Node - Fetch, extract, and validate all POC replies.

Used in parallel processing mode to process all received webhook data
at once. Combines the functionality of fetch_email, extract_content,
and validate_response for all POCs.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from mail_agent.agent.state import (
    AgentState,
    ConversationState,
    ReceivedEmail,
    ValidationResult,
    get_conversation,
    get_parsed_request,
)
from mail_agent.config import get_settings
from mail_agent.llm.client import LLMClient
from mail_agent.llm.prompts import PromptTemplates
from mail_agent.llm.prompts import ValidationResult as ValidationResultSchema
from mail_agent.tools.attachment_parser import (
    AttachmentParser,
    AttachmentParseError,
    UnsupportedFormatError,
)
from mail_agent.tools.inbox_client import InboxClient


logger = logging.getLogger(__name__)


async def process_all_replies(state: AgentState) -> dict[str, Any]:
    """
    Process all received POC replies in parallel.

    This node combines fetch, extract, and validate operations for all POCs.
    Each POC's reply is processed concurrently.

    Args:
        state: Current agent state with _received_webhooks.

    Returns:
        State update with _poc_processing_results and updated conversations.
    """
    received_webhooks = state.get("_received_webhooks", {})

    if not received_webhooks:
        logger.error("No received webhooks for process_all_replies")
        return {
            "error": "No received webhooks",
            "current_node": "error",
            "progress_messages": ["ERROR: No webhooks to process"],
        }

    poc_count = len(received_webhooks)
    logger.info(f"Processing replies from {poc_count} POCs")

    try:
        parsed_request = get_parsed_request(state)
        settings = get_settings()

        # Process all POC replies concurrently
        async def process_poc_reply(
            poc_email: str,
            webhook_data: dict[str, Any],
        ) -> dict[str, Any]:
            """Process a single POC's reply (fetch, extract, validate)."""
            logger.info(f"Processing reply from {poc_email}")

            try:
                email_id_str = webhook_data.get("email_id")
                if not email_id_str:
                    return _build_poc_error_result(
                        poc_email, "No email_id in webhook data"
                    )

                email_id = UUID(email_id_str)

                # Step 1: Fetch email
                inbox_client = InboxClient(settings)
                try:
                    email = await inbox_client.get_email(
                        inbox_address=settings.agent_email,
                        email_id=email_id,
                    )
                finally:
                    await inbox_client.close()

                logger.info(
                    f"Fetched email from {poc_email}: subject={email.subject}, "
                    f"attachments={len(email.attachments)}"
                )

                # Step 2: Extract content
                extracted_content = ""
                headers: list[str] = []
                row_count = 0

                if email.attachments:
                    attachment = email.attachments[0]
                    parser = AttachmentParser()

                    try:
                        parsed = parser.parse(
                            filename=attachment.filename,
                            content_base64=attachment.content_base64,
                            content_type=attachment.content_type,
                        )
                        extracted_content = parsed.to_json()
                        headers = parsed.headers
                        row_count = parsed.row_count

                        logger.info(
                            f"Extracted from {poc_email}: rows={row_count}, "
                            f"headers={headers}"
                        )

                    except (UnsupportedFormatError, AttachmentParseError) as e:
                        logger.warning(
                            f"Failed to parse attachment from {poc_email}: {e}"
                        )
                        extracted_content = email.body_text or ""
                else:
                    extracted_content = email.body_text or ""
                    logger.info(f"No attachment from {poc_email}, using body text")

                # Step 3: Validate
                llm_client = LLMClient(settings)

                prompt = PromptTemplates.validate_response(
                    request_description=parsed_request.request_description,
                    success_criteria=parsed_request.success_criteria,
                    extracted_content=extracted_content,
                    row_count=row_count,
                    headers=headers,
                    max_content_chars=settings.validation_content_max_chars,
                    email_body_text=email.body_text or "",
                )

                validation = await llm_client.generate_structured(
                    prompt=prompt,
                    output_schema=ValidationResultSchema,
                    system_prompt=PromptTemplates.VALIDATE_SYSTEM,
                )

                # Check for redirect
                is_redirect = (
                    validation.redirect.is_redirect
                    if hasattr(validation, "redirect") and validation.redirect
                    else False
                )
                redirect_email = (
                    validation.redirect.redirect_email
                    if is_redirect and validation.redirect.redirect_email
                    else None
                )
                redirect_reason = (
                    validation.redirect.redirect_reason
                    if is_redirect and validation.redirect.redirect_reason
                    else None
                )

                logger.info(
                    f"Validation for {poc_email}: is_valid={validation.is_valid}, "
                    f"is_redirect={is_redirect}"
                )

                # Build received email record
                received_email = ReceivedEmail(
                    email_id=email.email_id,
                    from_address=email.from_address,
                    subject=email.subject,
                    received_at=datetime.now(timezone.utc),
                    has_attachment=email.has_attachments,
                    body_text=email.body_text,
                    attachment_content=extracted_content,
                    attachment_filename=(
                        email.attachments[0].filename if email.attachments else None
                    ),
                )

                # Build validation result record
                validation_result = ValidationResult(
                    attempt=0,  # Will be updated when merging with conversation
                    is_valid=validation.is_valid,
                    feedback=validation.feedback,
                    missing_items=validation.missing_items,
                )

                return {
                    "poc_email": poc_email,
                    "success": True,
                    "is_valid": validation.is_valid,
                    "feedback": validation.feedback,
                    "missing_items": validation.missing_items,
                    "extracted_content": extracted_content,
                    "headers": headers,
                    "row_count": row_count,
                    "received_email": received_email.to_dict(),
                    "validation_result": validation_result.to_dict(),
                    "is_redirect": is_redirect,
                    "redirect_email": redirect_email,
                    "redirect_reason": redirect_reason,
                    "error": None,
                }

            except Exception as e:
                error_msg = f"Failed to process reply from {poc_email}: {e}"
                logger.error(error_msg)
                return _build_poc_error_result(poc_email, error_msg)

        # Run all processing concurrently
        logger.info(f"Processing {poc_count} POC replies concurrently")
        process_results = await asyncio.gather(
            *[
                process_poc_reply(poc_email, webhook_data)
                for poc_email, webhook_data in received_webhooks.items()
            ]
        )

        # Consolidate results and update conversation states
        conversations = dict(state.get("conversations", {}))
        poc_processing_results: dict[str, dict[str, Any]] = {}
        all_valid = True
        failed_pocs: list[str] = []
        followup_pocs: list[str] = []

        for result in process_results:
            poc_email = result["poc_email"]

            # Find conversation key (case-insensitive)
            conv_key = _find_conversation_key(conversations, poc_email)
            if not conv_key:
                logger.warning(f"No conversation found for POC {poc_email}")
                continue

            conv = ConversationState.from_dict(conversations[conv_key])

            if result["success"]:
                # Add received email
                received_email = ReceivedEmail.from_dict(result["received_email"])
                conv.received_emails.append(received_email)

                # Add validation result with correct attempt number
                validation_result = ValidationResult.from_dict(
                    result["validation_result"]
                )
                validation_result.attempt = conv.attempt_count
                conv.validation_results.append(validation_result)

                if result["is_redirect"]:
                    conv.status = "redirected"
                    conv.final_result = "redirected"
                    conv.redirected_to = result["redirect_email"]
                elif result["is_valid"]:
                    conv.status = "success"
                    conv.final_result = "success"
                else:
                    all_valid = False
                    conv.status = "validating"  # Needs follow-up
                    followup_pocs.append(poc_email)

                # Store processing result
                poc_processing_results[poc_email] = {
                    "is_valid": result["is_valid"],
                    "feedback": result["feedback"],
                    "missing_items": result["missing_items"],
                    "extracted_content": result["extracted_content"],
                    "is_redirect": result["is_redirect"],
                    "redirect_email": result["redirect_email"],
                }

            else:
                # Processing failed
                conv.status = "failed"
                conv.error_message = result["error"]
                failed_pocs.append(poc_email)
                all_valid = False

                poc_processing_results[poc_email] = {
                    "is_valid": False,
                    "feedback": result["error"],
                    "missing_items": [],
                    "extracted_content": "",
                    "is_redirect": False,
                    "redirect_email": None,
                }

            conversations[conv_key] = conv.to_dict()

        # Build progress message
        valid_count = sum(
            1 for r in process_results if r["success"] and r["is_valid"]
        )
        redirect_count = sum(
            1 for r in process_results if r["success"] and r.get("is_redirect", False)
        )
        invalid_count = sum(
            1 for r in process_results
            if r["success"] and not r["is_valid"] and not r.get("is_redirect", False)
        )

        progress_parts = []
        if valid_count > 0:
            progress_parts.append(f"{valid_count} valid")
        if redirect_count > 0:
            progress_parts.append(f"{redirect_count} redirected")
        if invalid_count > 0:
            progress_parts.append(f"{invalid_count} invalid")
        if failed_pocs:
            progress_parts.append(f"{len(failed_pocs)} failed")

        progress_msg = f"Processed {poc_count} replies: {', '.join(progress_parts)}"
        logger.info(progress_msg)

        return {
            "conversations": conversations,
            "current_node": "process_all_replies",
            "progress_messages": [progress_msg],
            "_poc_processing_results": poc_processing_results,
            "_all_individual_valid": all_valid,
            "_followup_pocs": followup_pocs if followup_pocs else None,
            "_received_webhooks": None,  # Clear webhooks
        }

    except Exception as e:
        error_msg = f"Failed to process all replies: {e}"
        logger.exception(error_msg)
        return {
            "error": error_msg,
            "current_node": "error",
            "progress_messages": [f"ERROR: {error_msg}"],
        }


def _build_poc_error_result(poc_email: str, error_msg: str) -> dict[str, Any]:
    """Build error result for a single POC processing failure."""
    return {
        "poc_email": poc_email,
        "success": False,
        "is_valid": False,
        "feedback": error_msg,
        "missing_items": [],
        "extracted_content": "",
        "headers": [],
        "row_count": 0,
        "received_email": None,
        "validation_result": None,
        "is_redirect": False,
        "redirect_email": None,
        "redirect_reason": None,
        "error": error_msg,
    }


def _find_conversation_key(
    conversations: dict[str, dict[str, Any]],
    poc_email: str,
) -> str | None:
    """Find conversation key by POC email (case-insensitive)."""
    poc_email_lower = poc_email.lower()

    if poc_email in conversations:
        return poc_email

    for key in conversations.keys():
        if key.lower() == poc_email_lower:
            return key

    return None
