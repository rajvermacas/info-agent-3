import pytest
from datetime import datetime, timezone
from uuid import uuid4

from mail_agent.agent.nodes.orchestrate import orchestrate
from mail_agent.agent.state import ConversationState, ReceivedEmail


@pytest.mark.asyncio
async def test_orchestrate_blocks_pending_poc_with_unresolved_city_placeholders() -> None:
    state = {
        "conversations": {
            "raj@gmail.com": {"poc_email": "raj@gmail.com", "status": "waiting", "attempt_count": 1},
            "neha@gmail.com": {"poc_email": "neha@gmail.com", "status": "pending", "attempt_count": 0},
        },
        "poc_request_contexts": {
            "neha@gmail.com": {
                "request_description": "Share some local foods available in city 1 and city 2.",
                "success_criteria": "Include local foods for both city 1 and city 2.",
                "expected_format": "text",
            }
        },
    }

    result = await orchestrate(state)  # type: ignore[arg-type]
    assert result["orchestrator_next"] == "wait_for_any_reply"

@pytest.mark.asyncio
async def test_orchestrate_blocks_pending_poc_with_unresolved_bracket_city_placeholders() -> None:
    state = {
        "conversations": {
            "raj@gmail.com": {"poc_email": "raj@gmail.com", "status": "waiting", "attempt_count": 1},
            "neha@gmail.com": {"poc_email": "neha@gmail.com", "status": "pending", "attempt_count": 0},
        },
        "poc_request_contexts": {
            "neha@gmail.com": {
                "request_description": "Share some local foods for [City 1] and [City 2].",
                "success_criteria": "Include foods for [City 1] and [City 2].",
                "expected_format": "text",
            }
        },
    }

    result = await orchestrate(state)  # type: ignore[arg-type]
    assert result["orchestrator_next"] == "wait_for_any_reply"


@pytest.mark.asyncio
async def test_orchestrate_dispatches_pending_poc_once_city_placeholders_resolvable() -> None:
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
    state = {
        "conversations": {
            "raj@gmail.com": raj.to_dict(),
            "neha@gmail.com": {"poc_email": "neha@gmail.com", "status": "pending", "attempt_count": 0},
        },
        "poc_request_contexts": {
            "neha@gmail.com": {
                "request_description": "Share some local foods available in city 1 and city 2.",
                "success_criteria": "Include local foods for both city 1 and city 2.",
                "expected_format": "text",
            }
        },
    }

    result = await orchestrate(state)  # type: ignore[arg-type]
    assert result["orchestrator_next"] == "compose_email"
    assert result["current_poc"] == "neha@gmail.com"
