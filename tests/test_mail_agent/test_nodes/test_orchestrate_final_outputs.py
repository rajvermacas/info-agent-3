"""
Tests for orchestrate final output dispatch behavior.
"""

import pytest

from mail_agent.agent.nodes.orchestrate import orchestrate


@pytest.mark.asyncio
async def test_orchestrate_routes_to_send_final_outputs_after_global_validation() -> None:
    state = {"global_valid": True, "_final_outputs_sent": False, "conversations": {}}  # type: ignore[typeddict-item]
    result = await orchestrate(state)  # type: ignore[arg-type]
    assert result["orchestrator_next"] == "send_final_outputs"

