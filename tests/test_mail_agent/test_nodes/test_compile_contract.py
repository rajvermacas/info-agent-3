"""
Tests for the compile_contract node.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mail_agent.agent.nodes.compile_contract import compile_contract
from mail_agent.agent.state import ConversationState, ParsedRequest
from mail_agent.llm.multi_contact import MultiContactContract, PocPlan


@pytest.mark.asyncio
async def test_compile_contract_prunes_delivery_recipients_from_conversations() -> None:
    raj = "raj@gmail.com"
    neha = "neha@gmail.com"
    sunny = "sunny@gmail.com"

    parsed = ParsedRequest(
        poc_emails=[raj, neha, sunny],
        request_type="data_request",
        request_description="Collect animal names",
        success_criteria="5 distinct animal names total",
        expected_format="csv",
    )

    state = {
        "user_instruction": "Send ...",
        "parsed_request": parsed.to_dict(),
        "conversations": {
            raj: ConversationState(poc_email=raj, status="pending").to_dict(),
            neha: ConversationState(poc_email=neha, status="pending").to_dict(),
            sunny: ConversationState(poc_email=sunny, status="pending").to_dict(),
        },
    }

    contract = MultiContactContract(
        poc_plans=[
            PocPlan(
                poc_email=raj,
                request_description="Ask for 2 animal names in CSV",
                expected_format="csv",
                success_criteria="Exactly 2 distinct animal names",
            ),
            PocPlan(
                poc_email=neha,
                request_description="Ask for 3 animal names in CSV",
                expected_format="csv",
                success_criteria="Exactly 3 distinct animal names, no overlap with Raj",
            ),
        ],
        delivery_recipients=[sunny],
        delivery_description="Send merged 5 unique animal names to Sunny",
        global_success_criteria="5 unique animal names total and disjoint between Raj/Neha",
        agent_plan_steps=["Email Raj", "Email Neha", "Validate globally", "Send to Sunny"],
        assumptions=[],
    )

    with patch("mail_agent.agent.nodes.compile_contract.LLMClient") as mock_llm_class:
        mock_llm = MagicMock()
        mock_llm.generate_structured = AsyncMock(return_value=contract)
        mock_llm_class.return_value = mock_llm

        with patch("mail_agent.agent.nodes.compile_contract.get_settings"):
            result = await compile_contract(state)  # type: ignore[arg-type]

    assert result["delivery_recipients"] == [sunny]
    assert set(result["conversations"].keys()) == {raj, neha}
    assert sunny not in result["poc_request_contexts"]
    assert result["current_poc"] == raj
    assert any("Execution plan:" in m for m in result["progress_messages"])

