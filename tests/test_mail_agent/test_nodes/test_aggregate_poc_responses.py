"""
Tests for the aggregate_poc_responses node.

Tests data aggregation from completed POCs.
"""

import pytest

from mail_agent.agent.multi_poc_state import (
    POCExecutionPlan,
    POCRequirement,
    POCState,
    POCStatus,
)
from mail_agent.agent.nodes.aggregate_poc_responses import (
    aggregate_poc_responses,
    get_aggregated_data,
)


class TestAggregatePocResponsesNode:
    """Tests for the aggregate_poc_responses node."""

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
    async def test_aggregate_no_completed_pocs(self, base_plan):
        """Test aggregation with no completed POCs."""
        state = {
            "execution_plan": base_plan.to_dict(),
            "poc_states": {
                "poc_1": POCState(poc_id="poc_1", status=POCStatus.PENDING).to_dict(),
                "poc_2": POCState(poc_id="poc_2", status=POCStatus.PENDING).to_dict(),
            },
        }

        result = await aggregate_poc_responses(state)

        assert result["current_node"] == "aggregate_poc_responses"
        assert result["aggregated_data"] == {}
        assert "No completed" in result["progress_messages"][0]

    @pytest.mark.asyncio
    async def test_aggregate_single_poc(self, base_plan):
        """Test aggregation with one completed POC."""
        poc_state = POCState(poc_id="poc_1", status=POCStatus.COMPLETED)
        poc_state.extracted_data = {"recipe_count": 10, "format": "csv"}

        state = {
            "execution_plan": base_plan.to_dict(),
            "poc_states": {
                "poc_1": poc_state.to_dict(),
                "poc_2": POCState(poc_id="poc_2", status=POCStatus.PENDING).to_dict(),
            },
        }

        result = await aggregate_poc_responses(state)

        assert result["current_node"] == "aggregate_poc_responses"
        aggregated = result["aggregated_data"]
        assert "recipe_count" in aggregated
        assert aggregated["recipe_count"] == 10
        assert "poc_1.recipe_count" in aggregated

    @pytest.mark.asyncio
    async def test_aggregate_multiple_pocs(self, base_plan):
        """Test aggregation with multiple completed POCs."""
        poc_state_1 = POCState(poc_id="poc_1", status=POCStatus.COMPLETED)
        poc_state_1.extracted_data = {"data_a": "value_a"}

        poc_state_2 = POCState(poc_id="poc_2", status=POCStatus.COMPLETED)
        poc_state_2.extracted_data = {"data_b": "value_b"}

        state = {
            "execution_plan": base_plan.to_dict(),
            "poc_states": {
                "poc_1": poc_state_1.to_dict(),
                "poc_2": poc_state_2.to_dict(),
            },
        }

        result = await aggregate_poc_responses(state)

        aggregated = result["aggregated_data"]
        assert aggregated["data_a"] == "value_a"
        assert aggregated["data_b"] == "value_b"
        assert aggregated["poc_1.data_a"] == "value_a"
        assert aggregated["poc_2.data_b"] == "value_b"

    @pytest.mark.asyncio
    async def test_aggregate_handles_key_collision(self, base_plan):
        """Test aggregation handles same key from multiple POCs."""
        poc_state_1 = POCState(poc_id="poc_1", status=POCStatus.COMPLETED)
        poc_state_1.extracted_data = {"count": 10}

        poc_state_2 = POCState(poc_id="poc_2", status=POCStatus.COMPLETED)
        poc_state_2.extracted_data = {"count": 20}

        state = {
            "execution_plan": base_plan.to_dict(),
            "poc_states": {
                "poc_1": poc_state_1.to_dict(),
                "poc_2": poc_state_2.to_dict(),
            },
        }

        result = await aggregate_poc_responses(state)

        aggregated = result["aggregated_data"]
        # Prefixed keys should both exist
        assert aggregated["poc_1.count"] == 10
        assert aggregated["poc_2.count"] == 20
        # Non-prefixed key will have one of the values (first wins)
        assert "count" in aggregated

    @pytest.mark.asyncio
    async def test_aggregate_skips_failed_pocs(self, base_plan):
        """Test that failed POCs are not included in aggregation."""
        poc_state_1 = POCState(poc_id="poc_1", status=POCStatus.COMPLETED)
        poc_state_1.extracted_data = {"valid_data": True}

        poc_state_2 = POCState(poc_id="poc_2", status=POCStatus.FAILED)
        poc_state_2.extracted_data = {"invalid_data": True}

        state = {
            "execution_plan": base_plan.to_dict(),
            "poc_states": {
                "poc_1": poc_state_1.to_dict(),
                "poc_2": poc_state_2.to_dict(),
            },
        }

        result = await aggregate_poc_responses(state)

        aggregated = result["aggregated_data"]
        assert "valid_data" in aggregated
        assert "invalid_data" not in aggregated

    @pytest.mark.asyncio
    async def test_aggregate_handles_empty_extracted_data(self, base_plan):
        """Test aggregation handles POCs with no extracted data."""
        poc_state = POCState(poc_id="poc_1", status=POCStatus.COMPLETED)
        poc_state.extracted_data = None

        state = {
            "execution_plan": base_plan.to_dict(),
            "poc_states": {
                "poc_1": poc_state.to_dict(),
            },
        }

        result = await aggregate_poc_responses(state)

        assert result["current_node"] == "aggregate_poc_responses"


class TestGetAggregatedData:
    """Tests for get_aggregated_data helper."""

    def test_get_aggregated_data_exists(self):
        """Test getting aggregated data when it exists."""
        state = {"aggregated_data": {"key": "value"}}

        result = get_aggregated_data(state)

        assert result == {"key": "value"}

    def test_get_aggregated_data_missing(self):
        """Test getting aggregated data when missing."""
        state = {}

        result = get_aggregated_data(state)

        assert result == {}
