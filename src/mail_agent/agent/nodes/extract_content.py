"""Extract content node - extracts and parses attachment content."""

import json
import logging

from mail_agent.agent.state import AgentState
from mail_agent.tools.attachment_parser import (
    AttachmentParser,
    AttachmentParseError,
    UnsupportedFormatError,
)

logger = logging.getLogger(__name__)


async def extract_content_node(state: AgentState) -> AgentState:
    """Extract content from email attachments.

    This node:
    1. Gets full email from state (_full_email)
    2. Checks for attachments
    3. For supported formats (Excel, CSV): parses and converts to JSON
    4. For unsupported formats: stores raw info (filename, size)
    5. Stores extracted content in state for validation node
    6. Returns updated state

    Args:
        state: Current agent state with _full_email from fetch_email node

    Returns:
        AgentState: Updated state with _extracted_content temporary data

    Raises:
        ValueError: If _full_email is missing
    """
    logger.info("extract_content_node: Starting")

    # Validate inputs
    full_email = state.get("_full_email")
    if not full_email:
        error_msg = "_full_email not found in state (fetch_email node must run first)"
        logger.error(f"extract_content_node: {error_msg}")
        raise ValueError(error_msg)

    logger.debug(f"extract_content_node: Processing email: {full_email.get('id')}")

    try:
        # Get attachments
        attachments = full_email.get("attachments", [])

        if not attachments:
            logger.info("extract_content_node: No attachments found in email")
            # Store empty content
            state["_extracted_content"] = {
                "has_attachments": False,
                "attachment_count": 0,
                "content": None,
                "error": "No attachments in email",
            }
            state["current_node"] = "extract_content"
            state["progress_messages"].append("Email has no attachments")
            return state

        logger.info(f"extract_content_node: Found {len(attachments)} attachments")

        # Process first attachment (main content)
        first_attachment = attachments[0]
        filename = first_attachment.get("filename", "")
        content_base64 = first_attachment.get("content_base64", "")
        size_bytes = first_attachment.get("size_bytes", 0)

        logger.debug(
            f"extract_content_node: Processing attachment: {filename}, "
            f"size={size_bytes} bytes"
        )

        # Check if format is supported
        if AttachmentParser.is_supported(filename):
            logger.info(f"extract_content_node: Parsing supported format: {filename}")

            try:
                # Parse attachment
                rows = AttachmentParser.parse(content_base64, filename)

                # Convert to JSON for validation
                content = json.dumps({
                    "filename": filename,
                    "row_count": len(rows),
                    "rows": rows[:100] if len(rows) > 100 else rows,  # Limit to 100 rows
                }, indent=2)

                logger.info(
                    f"extract_content_node: Successfully parsed {filename}: "
                    f"rows={len(rows)}"
                )

                state["_extracted_content"] = {
                    "has_attachments": True,
                    "attachment_count": len(attachments),
                    "content": content,
                    "filename": filename,
                    "error": None,
                }

            except AttachmentParseError as e:
                error_msg = f"Failed to parse attachment {filename}: {str(e)}"
                logger.error(f"extract_content_node: {error_msg}")

                state["_extracted_content"] = {
                    "has_attachments": True,
                    "attachment_count": len(attachments),
                    "content": None,
                    "filename": filename,
                    "error": error_msg,
                }

        else:
            # Unsupported format - store file info
            logger.warning(f"extract_content_node: Unsupported format: {filename}")

            state["_extracted_content"] = {
                "has_attachments": True,
                "attachment_count": len(attachments),
                "content": json.dumps({
                    "filename": filename,
                    "size_bytes": size_bytes,
                    "note": f"Unsupported format. Supported: .xlsx, .csv"
                }),
                "filename": filename,
                "error": f"Unsupported file format: {filename}",
            }

        state["current_node"] = "extract_content"
        state["progress_messages"].append(
            f"Extracted content from {len(attachments)} attachment(s)"
        )

        logger.info("extract_content_node: Completed successfully")

        return state

    except Exception as e:
        error_msg = f"Unexpected error extracting content: {str(e)}"
        logger.error(f"extract_content_node: {error_msg}")
        raise
