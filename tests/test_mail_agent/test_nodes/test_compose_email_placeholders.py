import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from mail_agent.agent.nodes.compose_email import compose_email
from mail_agent.agent.state import ConversationState, ParsedRequest, ReceivedEmail
from mail_agent.llm.prompts import ComposedEmail


@pytest.mark.asyncio
async def test_compose_email_resolves_city_placeholders_from_prior_success() -> None:
    neha = ConversationState(poc_email="neha@gmail.com", status="pending", attempt_count=0)
    raj = ConversationState(
        poc_email="raj@gmail.com",
        status="success",
        attempt_count=1,
        received_emails=[
            ReceivedEmail(
                email_id=uuid4(),
                from_address="raj@gmail.com",
                subject="Cities",
                received_at=datetime.now(timezone.utc),
                has_attachment=False,
                body_text="mumbai and delhi",
            )
        ],
    )
    parsed = ParsedRequest(
        poc_emails=["raj@gmail.com", "neha@gmail.com"],
        request_type="information_request",
        request_description="Ask Raj for 2 city names, then ask Neha about local foods in those cities.",
        success_criteria="Get local foods for the two cities.",
        expected_format="text",
    )

    state = {
        "conversations": {"neha@gmail.com": neha.to_dict(), "raj@gmail.com": raj.to_dict()},
        "current_poc": "neha@gmail.com",
        "parsed_request": parsed.to_dict(),
        "poc_request_contexts": {
            "neha@gmail.com": {
                "request_description": "Share some local foods available in city 1 and city 2.",
                "success_criteria": "Include foods for city 1 and city 2.",
                "expected_format": "text",
            }
        },
    }

    mock_composed = ComposedEmail(
        subject="Local foods request",
        body="Please share foods.\n\nBest regards,\ninfo-agent",
    )

    with patch("mail_agent.agent.nodes.compose_email.LLMClient") as mock_llm_class:
        mock_llm = MagicMock()
        mock_llm.generate_structured = AsyncMock(return_value=mock_composed)
        mock_llm_class.return_value = mock_llm

        with patch("mail_agent.agent.nodes.compose_email.get_settings") as mock_settings:
            mock_settings.return_value.agent_email = "info-agent@gmail.com"
            mock_settings.return_value.max_attempts = 5

            result = await compose_email(state)  # type: ignore[arg-type]

    call_args = mock_llm.generate_structured.call_args
    prompt = call_args.kwargs.get("prompt", call_args.args[0] if call_args.args else "")

    assert "Mumbai" in prompt
    assert "Delhi" in prompt
    assert "city 1" not in prompt.lower()

    updated_contexts = result.get("poc_request_contexts") or {}
    assert "Mumbai" in updated_contexts["neha@gmail.com"]["request_description"]
    assert "Delhi" in updated_contexts["neha@gmail.com"]["request_description"]


@pytest.mark.asyncio
async def test_compose_email_resolves_bracket_city_placeholders_from_prior_success() -> None:
    neha = ConversationState(poc_email="neha@gmail.com", status="pending", attempt_count=0)
    raj = ConversationState(
        poc_email="raj@gmail.com",
        status="success",
        attempt_count=1,
        received_emails=[
            ReceivedEmail(
                email_id=uuid4(),
                from_address="raj@gmail.com",
                subject="Cities",
                received_at=datetime.now(timezone.utc),
                has_attachment=False,
                body_text="mumbai and delhi",
            )
        ],
    )
    parsed = ParsedRequest(
        poc_emails=["raj@gmail.com", "neha@gmail.com"],
        request_type="information_request",
        request_description="Ask Raj for 2 city names, then ask Neha about local foods in those cities.",
        success_criteria="Get local foods for the two cities.",
        expected_format="text",
    )

    state = {
        "conversations": {"neha@gmail.com": neha.to_dict(), "raj@gmail.com": raj.to_dict()},
        "current_poc": "neha@gmail.com",
        "parsed_request": parsed.to_dict(),
        "poc_request_contexts": {
            "neha@gmail.com": {
                "request_description": "Share some local foods available in [City 1] and [City 2].",
                "success_criteria": "Include foods for [City 1] and [City 2].",
                "expected_format": "text",
            }
        },
    }

    mock_composed = ComposedEmail(
        subject="Local foods request",
        body="Please share foods.\n\nBest regards,\ninfo-agent",
    )

    with patch("mail_agent.agent.nodes.compose_email.LLMClient") as mock_llm_class:
        mock_llm = MagicMock()
        mock_llm.generate_structured = AsyncMock(return_value=mock_composed)
        mock_llm_class.return_value = mock_llm

        with patch("mail_agent.agent.nodes.compose_email.get_settings") as mock_settings:
            mock_settings.return_value.agent_email = "info-agent@gmail.com"
            mock_settings.return_value.max_attempts = 5

            result = await compose_email(state)  # type: ignore[arg-type]

    call_args = mock_llm.generate_structured.call_args
    prompt = call_args.kwargs.get("prompt", call_args.args[0] if call_args.args else "")

    assert "Mumbai" in prompt
    assert "Delhi" in prompt
    assert "[city 1]" not in prompt.lower()

    updated_contexts = result.get("poc_request_contexts") or {}
    assert "Mumbai" in updated_contexts["neha@gmail.com"]["request_description"]
    assert "Delhi" in updated_contexts["neha@gmail.com"]["request_description"]
