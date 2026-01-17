"""
Extract Content Node - Parse attachment content from fetched email.

Extracts data from Excel/CSV attachments for LLM validation.
"""

import logging
from typing import Any

from mail_agent.agent.state import (
    AgentState,
    get_conversation,
    get_request_context,
    update_conversation,
)
from mail_agent.tools.attachment_parser import (
    AttachmentParser,
    AttachmentParseError,
    UnsupportedFormatError,
)


logger = logging.getLogger(__name__)


def _normalize_body_for_csv(body_text: str) -> str:
    lines: list[str] = []
    for raw in body_text.splitlines():
        line = raw.strip()
        if not line:
            lines.append("")
            continue
        if line.startswith(">"):
            continue
        lowered = line.lower()
        if lowered.startswith(("hi ", "hello", "dear ")):
            continue
        if "original message" in lowered or "wrote:" in lowered:
            break
        if lowered.startswith(("best regards", "regards", "thanks", "thank you")):
            break
        lines.append(line)
    return "\n".join(lines).strip()


def _pick_best_csv_block(parser: AttachmentParser, body_text: str) -> tuple[str, list[str], int] | None:
    normalized = _normalize_body_for_csv(body_text)
    blocks = [b.strip() for b in normalized.split("\n\n") if b.strip()]
    best: tuple[int, int, str, list[str], int] | None = None
    for block in blocks:
        if block.count("\n") < 1:
            continue
        parsed = parser.parse_csv_text(filename="email_body.csv", text_content=block)
        score = (parsed.row_count, len(parsed.headers))
        if best is None or score > (best[0], best[1]):
            best = (score[0], score[1], parsed.to_json(), parsed.headers, parsed.row_count)
    if best is None or best[0] <= 0:
        return None
    return best[2], best[3], best[4]


def _update_last_received_email(
    conversation: Any, extracted_content: str, attachment_filename: str | None
) -> None:
    if not conversation.received_emails:
        return
    conversation.received_emails[-1].attachment_content = extracted_content
    if attachment_filename:
        conversation.received_emails[-1].attachment_filename = attachment_filename


def _get_body_csv(
    parser: AttachmentParser, body_text: str | None, expected_format: str
) -> tuple[str, list[str], int] | None:
    if not body_text:
        return None
    if expected_format.lower() != "csv":
        return None
    return _pick_best_csv_block(parser, body_text)


def _finish_extraction(
    state: AgentState,
    current_poc: str,
    conversation: Any,
    extracted_content: str,
    headers: list[str],
    row_count: int,
    progress_msg: str,
    attachment_filename: str | None = None,
) -> dict[str, Any]:
    _update_last_received_email(conversation, extracted_content, attachment_filename)
    conversation.status = "validating"
    return {
        "conversations": update_conversation(state, current_poc, conversation),
        "current_node": "extract_content",
        "progress_messages": [progress_msg],
        "_extracted_content": extracted_content,
        "_extracted_headers": headers,
        "_extracted_row_count": row_count,
    }


def _resolve_body_only(
    body_text: str | None, body_csv: tuple[str, list[str], int] | None
) -> tuple[str, list[str], int, str]:
    if body_csv:
        extracted_content, headers, row_count = body_csv
        return extracted_content, headers, row_count, "No attachment found - using parsed CSV from email body"
    return body_text or "", [], 0, "No attachment found - using email body for validation"


def _resolve_attachment_success(
    parsed: Any,
    attachment_filename: str,
    body_csv: tuple[str, list[str], int] | None,
) -> tuple[str, list[str], int, str | None]:
    extracted_content = parsed.to_json()
    headers = parsed.headers
    row_count = parsed.row_count
    used_filename: str | None = attachment_filename

    if body_csv and row_count == 0 and body_csv[2] > 0:
        extracted_content, headers, row_count = body_csv
        used_filename = None
    return extracted_content, headers, row_count, used_filename


def _resolve_unsupported_attachment(
    attachment_filename: str,
    body_text: str | None,
    body_csv: tuple[str, list[str], int] | None,
    error_msg: str,
) -> tuple[str, list[str], int, str]:
    extracted_content, headers, row_count = body_csv if body_csv else (body_text or "", [], 0)
    if not body_csv:
        extracted_content = f"[Unsupported format: {attachment_filename}]\n\n{extracted_content}"
    progress_msg = (
        f"WARNING: {error_msg}, using {'parsed CSV from body' if body_csv else 'email body'}"
    )
    return extracted_content, headers, row_count, progress_msg


def _extract_content_for_poc(state: AgentState, current_poc: str) -> dict[str, Any]:
    conversation = get_conversation(state, current_poc)
    conversation.status = "extracting"

    attachments = state.get("_fetched_attachments", [])
    body_text = state.get("_fetched_body_text")
    _request_description, _success_criteria, expected_format = get_request_context(
        state, current_poc
    )

    parser = AttachmentParser()
    body_csv = _get_body_csv(parser, body_text, expected_format)

    if not attachments:
        extracted_content, headers, row_count, progress_msg = _resolve_body_only(
            body_text, body_csv
        )
        return _finish_extraction(
            state, current_poc, conversation, extracted_content, headers, row_count, progress_msg
        )

    attachment = attachments[0]
    try:
        parsed = parser.parse(
            filename=attachment["filename"],
            content_base64=attachment["content_base64"],
            content_type=attachment["content_type"],
        )

        extracted_content, headers, row_count, used_filename = _resolve_attachment_success(
            parsed, attachment["filename"], body_csv
        )

        logger.info(
            f"Content extracted: type={parsed.content_type}, rows={row_count}, "
            f"headers={headers}, json_size={len(extracted_content)} chars"
        )

        progress_msg = (
            f"Extracted {row_count} rows from '{used_filename or 'email body'}' "
            f"(columns: {', '.join(headers[:3])}{'...' if len(headers) > 3 else ''})"
        )
        return _finish_extraction(
            state,
            current_poc,
            conversation,
            extracted_content,
            headers,
            row_count,
            progress_msg,
            attachment_filename=used_filename,
        )
    except UnsupportedFormatError as e:
        error_msg = f"Unsupported attachment format: {e}"
        logger.warning(error_msg)
        extracted_content, headers, row_count, progress_msg = _resolve_unsupported_attachment(
            attachment["filename"], body_text, body_csv, error_msg
        )
        return _finish_extraction(
            state, current_poc, conversation, extracted_content, headers, row_count, progress_msg
        )
    except AttachmentParseError as e:
        error_msg = f"Failed to parse attachment: {e}"
        logger.error(error_msg)
        extracted_content = f"[Parse error: {e}]"
        _update_last_received_email(conversation, extracted_content, None)
        conversation.status = "validating"
        return {
            "conversations": update_conversation(state, current_poc, conversation),
            "current_node": "extract_content",
            "progress_messages": [f"WARNING: {error_msg}"],
            "_extracted_content": "",
            "_extracted_headers": [],
            "_extracted_row_count": 0,
        }


async def extract_content(state: AgentState) -> dict[str, Any]:
    """Extract content from attachment or body for validation."""
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
        return _extract_content_for_poc(state, current_poc)

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
