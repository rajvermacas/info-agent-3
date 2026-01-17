"""
Tests for send_final_outputs node.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from mail_agent.agent.nodes.send_final_outputs import send_final_outputs
from mail_agent.agent.state import ConversationState, ReceivedEmail


@pytest.mark.asyncio
async def test_send_final_outputs_sends_to_pocs_and_delivery_recipients() -> None:
    raj = "raj@gmail.com"
    neha = "neha@gmail.com"
    sunny = "sunny@gmail.com"

    def conv(email: str, payload: str) -> dict:
        c = ConversationState(poc_email=email, status="success")
        c.sent_emails = []
        c.received_emails = [
            ReceivedEmail(
                email_id=UUID("12345678-1234-1234-1234-123456789012"),
                from_address=email,
                subject="Re: Request",
                received_at=datetime.now(timezone.utc),
                has_attachment=False,
                attachment_content=payload,
                body_text=None,
            )
        ]
        return c.to_dict()

    raj_payload = "{\"data\": [{\"animal_name\": \"lion\"}], \"raw_text\": \"animal_name\\nlion\\n\"}"
    neha_payload = "{\"data\": [{\"animal_name\": \"tiger\"}], \"raw_text\": \"animal_name\\ntiger\\n\"}"

    state = {
        "conversations": {raj: conv(raj, raj_payload), neha: conv(neha, neha_payload)},
        "delivery_recipients": [sunny],
        "global_validation": {"feedback": "All constraints satisfied."},
    }

    with patch("mail_agent.agent.nodes.send_final_outputs.SMTPSenderService") as mock_sender_cls:
        mock_sender = MagicMock()
        mock_sender.send_email = AsyncMock()
        mock_sender_cls.return_value = mock_sender

        with patch("mail_agent.agent.nodes.send_final_outputs.get_settings"):
            result = await send_final_outputs(state)  # type: ignore[arg-type]

    assert result["_final_outputs_sent"] is True
    assert mock_sender.send_email.await_count == 3  # 2 POCs + 1 delivery

