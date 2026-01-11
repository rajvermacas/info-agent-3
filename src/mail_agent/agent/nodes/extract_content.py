"""
Extract Content Node - Parse attachment content from fetched email.

Extracts data from Excel/CSV attachments for LLM validation.
"""

import logging
from typing import Any

from mail_agent.agent.state import (
    AgentState,
    get_conversation,
    update_conversation,
)
from mail_agent.tools.attachment_parser import (
    AttachmentParser,
    AttachmentParseError,
    UnsupportedFormatError,
)


logger = logging.getLogger(__name__)


async def extract_content(state: AgentState) -> dict[str, Any]:
    """
    Extract content from email attachment.

    This node:
    1. Gets the fetched attachment data from state
    2. Parses Excel/CSV content
    3. Stores extracted content for validation

    Args:
        state: Current agent state with _fetched_attachments.

    Returns:
        State update with extracted content.
    """
    current_poc = state.get("current_poc")
    if not current_poc:
        logger.error("No current POC set for extract_content")
        return {
            "error": "No current POC set",
            "current_node": "error",
            "progress_messages": ["ERROR: No current POC set for content extraction"],
        }

    logger.info(f"Extracting content from email for POC: {current_poc}")

    try:
        # Get conversation state
        conversation = get_conversation(state, current_poc)
        conversation.status = "extracting"

        # Get fetched attachment data
        attachments = state.get("_fetched_attachments", [])
        body_text = state.get("_fetched_body_text")

        # Check if we have attachments
        if not attachments:
            # No attachment - use body text as content
            logger.info("No attachments found, using email body text")

            if not body_text:
                logger.warning("No attachment and no body text in email")
                # Still proceed to validation - might be an empty response
                extracted_content = ""
                headers = []
                row_count = 0
            else:
                extracted_content = body_text
                headers = []
                row_count = 0

            # Update last received email with content
            if conversation.received_emails:
                conversation.received_emails[-1].attachment_content = extracted_content

            conversation.status = "validating"

            progress_msg = "No attachment found - using email body for validation"

            return {
                "conversations": update_conversation(state, current_poc, conversation),
                "current_node": "extract_content",
                "progress_messages": [progress_msg],
                "_extracted_content": extracted_content,
                "_extracted_headers": headers,
                "_extracted_row_count": row_count,
            }

        # Parse first attachment
        attachment = attachments[0]
        parser = AttachmentParser()

        try:
            parsed = parser.parse(
                filename=attachment["filename"],
                content_base64=attachment["content_base64"],
                content_type=attachment["content_type"],
            )

            extracted_content = parsed.to_json()
            headers = parsed.headers
            row_count = parsed.row_count

            logger.info(
                f"Content extracted: type={parsed.content_type}, "
                f"rows={row_count}, headers={headers}, "
                f"json_size={len(extracted_content)} chars"
            )

            # Update last received email with content
            if conversation.received_emails:
                conversation.received_emails[-1].attachment_content = extracted_content
                conversation.received_emails[-1].attachment_filename = attachment["filename"]

            conversation.status = "validating"

            progress_msg = (
                f"Extracted {row_count} rows from '{attachment['filename']}' "
                f"(columns: {', '.join(headers[:3])}{'...' if len(headers) > 3 else ''})"
            )

            return {
                "conversations": update_conversation(state, current_poc, conversation),
                "current_node": "extract_content",
                "progress_messages": [progress_msg],
                "_extracted_content": extracted_content,
                "_extracted_headers": headers,
                "_extracted_row_count": row_count,
            }

        except UnsupportedFormatError as e:
            error_msg = f"Unsupported attachment format: {e}"
            logger.warning(error_msg)

            # Use body text as fallback
            extracted_content = body_text or ""
            headers = []
            row_count = 0

            if conversation.received_emails:
                conversation.received_emails[-1].attachment_content = f"[Unsupported format: {attachment['filename']}]\n\n{extracted_content}"

            conversation.status = "validating"

            return {
                "conversations": update_conversation(state, current_poc, conversation),
                "current_node": "extract_content",
                "progress_messages": [f"WARNING: {error_msg}, using email body"],
                "_extracted_content": extracted_content,
                "_extracted_headers": headers,
                "_extracted_row_count": row_count,
            }

        except AttachmentParseError as e:
            error_msg = f"Failed to parse attachment: {e}"
            logger.error(error_msg)

            # Update conversation with error but continue to validation
            # Validation will fail and request re-send
            if conversation.received_emails:
                conversation.received_emails[-1].attachment_content = f"[Parse error: {e}]"

            conversation.status = "validating"

            return {
                "conversations": update_conversation(state, current_poc, conversation),
                "current_node": "extract_content",
                "progress_messages": [f"WARNING: {error_msg}"],
                "_extracted_content": "",
                "_extracted_headers": [],
                "_extracted_row_count": 0,
            }

    except Exception as e:
        error_msg = f"Failed to extract content: {e}"
        logger.error(error_msg)

        try:
            conversation = get_conversation(state, current_poc)
            conversation.status = "failed"
            conversation.error_message = error_msg
            return {
                "conversations": update_conversation(state, current_poc, conversation),
                "current_node": "error",
                "progress_messages": [f"ERROR: {error_msg}"],
            }
        except Exception:
            return {
                "error": error_msg,
                "current_node": "error",
                "progress_messages": [f"ERROR: {error_msg}"],
            }
