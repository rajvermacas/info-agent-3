"""
Tests for the extract_content node.
"""

from datetime import datetime, timezone
from uuid import UUID

import pytest

from mail_agent.agent.nodes.extract_content import extract_content
from mail_agent.agent.state import ConversationState, ParsedRequest, ReceivedEmail


def _base_state(poc_email: str) -> dict:
    conv = ConversationState(
        poc_email=poc_email,
        status="extracting",
        received_emails=[
            ReceivedEmail(
                email_id=UUID("12345678-1234-1234-1234-123456789012"),
                from_address=poc_email,
                subject="Re: Request",
                received_at=datetime.now(timezone.utc),
                has_attachment=False,
                body_text=None,
            )
        ],
    )
    parsed = ParsedRequest(
        poc_emails=[poc_email],
        request_type="data_request",
        request_description="Provide 10 distinct animal names in CSV format",
        success_criteria="CSV with exactly 10 distinct animal names",
        expected_format="csv",
    )
    return {
        "current_poc": poc_email,
        "conversations": {poc_email: conv.to_dict()},
        "parsed_request": parsed.to_dict(),
    }


@pytest.mark.asyncio
async def test_extract_content_parses_csv_from_body_without_attachment() -> None:
    poc_email = "raj@gmail.com"
    state = _base_state(poc_email)
    state["_fetched_attachments"] = []
    state["_fetched_body_text"] = (
        "Dear info-agent,\n\n"
        "animal\n"
        "cat\n"
        "dog\n\n"
        "Best regards,\n"
        "Raj\n"
    )

    result = await extract_content(state)

    assert result["_extracted_row_count"] == 2
    assert result["_extracted_headers"] == ["animal"]
    assert "\"raw_text\"" in result["_extracted_content"]


@pytest.mark.asyncio
async def test_extract_content_uses_attachment_when_present() -> None:
    poc_email = "raj@gmail.com"
    state = _base_state(poc_email)
    state["_fetched_body_text"] = "Here it is in the attachment."
    state["_fetched_attachments"] = [
        {
            "filename": "animals.csv",
            "content_type": "text/csv",
            "content_base64": "Y2F0CmRvZwo=",  # base64("cat\ndog\n")
            "size_bytes": 8,
        }
    ]

    result = await extract_content(state)

    assert result["_extracted_row_count"] == 2
    assert result["_extracted_headers"] == ["Column_0"]
    assert "\"raw_text\"" in result["_extracted_content"]

