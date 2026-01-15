"""
Tests for the orchestrate_pocs node.

Tests the DAG scheduler logic for multi-POC orchestration.
"""

import pytest

from mail_agent.agent.multi_poc_state import (
    OrchestrationAction,
    OrchestrationDecision,
    POCExecutionPlan,
    POCRequirement,
    POCState,
    POCStatus,
)
from mail_agent.agent.nodes.orchestrate_pocs import (
    orchestrate_pocs,
    get_orchestration_decision,
    should_execute,
    should_wait,
    should_aggregate,
    should_fail,
)


class TestOrchestratePocsNode:
    """Tests for the orchestrate_pocs node."""

    @pytest.fixture
    def base_plan(self):
        """Create a base execution plan."""
        return POCExecutionPlan(
            global_success_criteria="All data collected",
            pocs=[
                POCRequirement(
                    id="poc_1",
                    email="a@test.com",
                    request="Get data A",
                    success_criteria="Data A received",
                ),
                POCRequirement(
                    id="poc_2",
                    email="b@test.com",
                    request="Get data B",
                    success_criteria="Data B received",
                ),
            ],
            dependency_graph={"poc_1": [], "poc_2": []},
        )

    @pytest.mark.asyncio
    async def test_execute_ready_pocs(self, base_plan):
        """Test that ready POCs are selected for execution."""
        state = {
            "execution_plan": base_plan.to_dict(),
            "poc_states": {
                "poc_1": POCState(poc_id="poc_1", status=POCStatus.PENDING).to_dict(),
                "poc_2": POCState(poc_id="poc_2", status=POCStatus.PENDING).to_dict(),
            },
        }

        result = await orchestrate_pocs(state)

        assert result["current_node"] == "orchestrate_pocs"
        decision = OrchestrationDecision.from_dict(result["orchestration_decision"])
        assert decision.action == OrchestrationAction.EXECUTE
        assert len(decision.poc_ids) == 1
        assert decision.poc_ids[0] in ["poc_1", "poc_2"]
        assert result.get("current_poc_id") == decision.poc_ids[0]

    @pytest.mark.asyncio
    async def test_wait_when_pocs_waiting(self, base_plan):
        """Test that WAIT is returned when POCs are waiting for replies."""
        state = {
            "execution_plan": base_plan.to_dict(),
            "poc_states": {
                "poc_1": POCState(poc_id="poc_1", status=POCStatus.WAITING).to_dict(),
                "poc_2": POCState(poc_id="poc_2", status=POCStatus.COMPLETED).to_dict(),
            },
        }

        result = await orchestrate_pocs(state)

        decision = OrchestrationDecision.from_dict(result["orchestration_decision"])
        assert decision.action == OrchestrationAction.WAIT
        assert "poc_1" in decision.poc_ids

    @pytest.mark.asyncio
    async def test_aggregate_when_all_terminal(self, base_plan):
        """Test that AGGREGATE is returned when all POCs are terminal."""
        state = {
            "execution_plan": base_plan.to_dict(),
            "poc_states": {
                "poc_1": POCState(poc_id="poc_1", status=POCStatus.COMPLETED).to_dict(),
                "poc_2": POCState(poc_id="poc_2", status=POCStatus.COMPLETED).to_dict(),
            },
        }

        result = await orchestrate_pocs(state)

        decision = OrchestrationDecision.from_dict(result["orchestration_decision"])
        assert decision.action == OrchestrationAction.AGGREGATE

    @pytest.mark.asyncio
    async def test_fail_when_all_failed(self, base_plan):
        """Test that FAIL is returned when all POCs failed."""
        state = {
            "execution_plan": base_plan.to_dict(),
            "poc_states": {
                "poc_1": POCState(poc_id="poc_1", status=POCStatus.FAILED).to_dict(),
                "poc_2": POCState(poc_id="poc_2", status=POCStatus.FAILED).to_dict(),
            },
        }

        result = await orchestrate_pocs(state)

        decision = OrchestrationDecision.from_dict(result["orchestration_decision"])
        assert decision.action == OrchestrationAction.FAIL

    @pytest.mark.asyncio
    async def test_aggregate_with_partial_failure(self, base_plan):
        """Test AGGREGATE when some completed, some failed."""
        state = {
            "execution_plan": base_plan.to_dict(),
            "poc_states": {
                "poc_1": POCState(poc_id="poc_1", status=POCStatus.COMPLETED).to_dict(),
                "poc_2": POCState(poc_id="poc_2", status=POCStatus.FAILED).to_dict(),
            },
        }

        result = await orchestrate_pocs(state)

        decision = OrchestrationDecision.from_dict(result["orchestration_decision"])
        # Should still aggregate since at least one completed
        assert decision.action == OrchestrationAction.AGGREGATE

    @pytest.mark.asyncio
    async def test_dependency_blocking(self):
        """Test that POCs wait for dependencies."""
        plan = POCExecutionPlan(
            global_success_criteria="Sequential",
            pocs=[
                POCRequirement(
                    id="poc_1",
                    email="a@test.com",
                    request="R1",
                    success_criteria="C1",
                ),
                POCRequirement(
                    id="poc_2",
                    email="b@test.com",
                    request="R2",
                    success_criteria="C2",
                    dependencies=["poc_1"],
                ),
            ],
            dependency_graph={"poc_1": [], "poc_2": ["poc_1"]},
        )

        state = {
            "execution_plan": plan.to_dict(),
            "poc_states": {
                "poc_1": POCState(poc_id="poc_1", status=POCStatus.WAITING).to_dict(),
                "poc_2": POCState(poc_id="poc_2", status=POCStatus.PENDING).to_dict(),
            },
        }

        result = await orchestrate_pocs(state)

        decision = OrchestrationDecision.from_dict(result["orchestration_decision"])
        # Should wait since poc_1 is not completed yet
        assert decision.action == OrchestrationAction.WAIT

    @pytest.mark.asyncio
    async def test_execute_after_dependency_complete(self):
        """Test that dependent POC is executed after dependency completes."""
        plan = POCExecutionPlan(
            global_success_criteria="Sequential",
            pocs=[
                POCRequirement(
                    id="poc_1",
                    email="a@test.com",
                    request="R1",
                    success_criteria="C1",
                ),
                POCRequirement(
                    id="poc_2",
                    email="b@test.com",
                    request="R2",
                    success_criteria="C2",
                    dependencies=["poc_1"],
                ),
            ],
            dependency_graph={"poc_1": [], "poc_2": ["poc_1"]},
        )

        state = {
            "execution_plan": plan.to_dict(),
            "poc_states": {
                "poc_1": POCState(poc_id="poc_1", status=POCStatus.COMPLETED).to_dict(),
                "poc_2": POCState(poc_id="poc_2", status=POCStatus.PENDING).to_dict(),
            },
        }

        result = await orchestrate_pocs(state)

        decision = OrchestrationDecision.from_dict(result["orchestration_decision"])
        assert decision.action == OrchestrationAction.EXECUTE
        assert decision.poc_ids == ["poc_2"]


class TestOrchestrationDecisionHelpers:
    """Tests for orchestration decision helper functions."""

    def test_get_orchestration_decision(self):
        """Test getting OrchestrationDecision from state."""
        decision = OrchestrationDecision(
            action=OrchestrationAction.EXECUTE,
            poc_ids=["poc_1"],
            reason="Test",
        )
        state = {"orchestration_decision": decision.to_dict()}

        result = get_orchestration_decision(state)

        assert result.action == OrchestrationAction.EXECUTE
        assert result.poc_ids == ["poc_1"]

    def test_get_orchestration_decision_missing(self):
        """Test error when decision is missing."""
        state = {}

        with pytest.raises(ValueError):
            get_orchestration_decision(state)

    def test_should_execute(self):
        """Test should_execute helper."""
        execute_decision = OrchestrationDecision(
            action=OrchestrationAction.EXECUTE, poc_ids=["poc_1"], reason="Test"
        )
        wait_decision = OrchestrationDecision(
            action=OrchestrationAction.WAIT, poc_ids=[], reason="Test"
        )

        assert should_execute({"orchestration_decision": execute_decision.to_dict()})
        assert not should_execute({"orchestration_decision": wait_decision.to_dict()})
        assert not should_execute({})

    def test_should_wait(self):
        """Test should_wait helper."""
        decision = OrchestrationDecision(
            action=OrchestrationAction.WAIT, poc_ids=["poc_1"], reason="Test"
        )

        assert should_wait({"orchestration_decision": decision.to_dict()})

    def test_should_aggregate(self):
        """Test should_aggregate helper."""
        decision = OrchestrationDecision(
            action=OrchestrationAction.AGGREGATE, poc_ids=[], reason="Test"
        )

        assert should_aggregate({"orchestration_decision": decision.to_dict()})

    def test_should_fail(self):
        """Test should_fail helper."""
        decision = OrchestrationDecision(
            action=OrchestrationAction.FAIL, poc_ids=[], reason="Test"
        )

        assert should_fail({"orchestration_decision": decision.to_dict()})
