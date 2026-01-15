"""
Tests for the build_dependency_graph node.

Tests DAG construction, circular dependency detection, and topological sorting.
"""

import pytest
from unittest.mock import patch

from mail_agent.agent.multi_poc_state import (
    POCExecutionPlan,
    POCRequirement,
    POCState,
    POCStatus,
)
from mail_agent.agent.nodes.build_dependency_graph import (
    build_dependency_graph,
    CircularDependencyError,
    _build_adjacency_list,
    _topological_sort,
)


class TestBuildAdjacencyList:
    """Tests for _build_adjacency_list helper."""

    def test_no_dependencies(self):
        """Test with POCs that have no dependencies."""
        pocs = [
            POCRequirement(
                id="poc_1", email="a@test.com", request="R1", success_criteria="C1"
            ),
            POCRequirement(
                id="poc_2", email="b@test.com", request="R2", success_criteria="C2"
            ),
        ]

        adjacency, in_degree = _build_adjacency_list(pocs)

        assert adjacency == {"poc_1": [], "poc_2": []}
        assert in_degree == {"poc_1": 0, "poc_2": 0}

    def test_simple_dependency(self):
        """Test with simple A -> B dependency."""
        pocs = [
            POCRequirement(
                id="poc_1", email="a@test.com", request="R1", success_criteria="C1"
            ),
            POCRequirement(
                id="poc_2",
                email="b@test.com",
                request="R2",
                success_criteria="C2",
                dependencies=["poc_1"],
            ),
        ]

        adjacency, in_degree = _build_adjacency_list(pocs)

        # poc_1 has poc_2 as dependent (poc_2 depends on poc_1)
        assert adjacency == {"poc_1": ["poc_2"], "poc_2": []}
        assert in_degree == {"poc_1": 0, "poc_2": 1}

    def test_complex_dependencies(self):
        """Test with complex dependency graph.

        poc_1 -> poc_2 -> poc_4
              \\-> poc_3 /
        """
        pocs = [
            POCRequirement(
                id="poc_1", email="a@test.com", request="R1", success_criteria="C1"
            ),
            POCRequirement(
                id="poc_2",
                email="b@test.com",
                request="R2",
                success_criteria="C2",
                dependencies=["poc_1"],
            ),
            POCRequirement(
                id="poc_3",
                email="c@test.com",
                request="R3",
                success_criteria="C3",
                dependencies=["poc_1"],
            ),
            POCRequirement(
                id="poc_4",
                email="d@test.com",
                request="R4",
                success_criteria="C4",
                dependencies=["poc_2", "poc_3"],
            ),
        ]

        adjacency, in_degree = _build_adjacency_list(pocs)

        assert "poc_2" in adjacency["poc_1"]
        assert "poc_3" in adjacency["poc_1"]
        assert "poc_4" in adjacency["poc_2"]
        assert "poc_4" in adjacency["poc_3"]
        assert in_degree["poc_1"] == 0
        assert in_degree["poc_2"] == 1
        assert in_degree["poc_3"] == 1
        assert in_degree["poc_4"] == 2


class TestTopologicalSort:
    """Tests for _topological_sort helper."""

    def test_no_dependencies(self):
        """Test topological sort with no dependencies."""
        adjacency = {"poc_1": [], "poc_2": [], "poc_3": []}
        in_degree = {"poc_1": 0, "poc_2": 0, "poc_3": 0}

        result = _topological_sort(adjacency, in_degree)

        assert len(result) == 3
        assert set(result) == {"poc_1", "poc_2", "poc_3"}

    def test_linear_dependency(self):
        """Test topological sort with linear chain."""
        # poc_1 -> poc_2 -> poc_3
        adjacency = {"poc_1": ["poc_2"], "poc_2": ["poc_3"], "poc_3": []}
        in_degree = {"poc_1": 0, "poc_2": 1, "poc_3": 1}

        result = _topological_sort(adjacency, in_degree)

        assert result == ["poc_1", "poc_2", "poc_3"]

    def test_diamond_dependency(self):
        """Test topological sort with diamond pattern."""
        # poc_1 -> poc_2 -> poc_4
        # poc_1 -> poc_3 -> poc_4
        adjacency = {
            "poc_1": ["poc_2", "poc_3"],
            "poc_2": ["poc_4"],
            "poc_3": ["poc_4"],
            "poc_4": [],
        }
        in_degree = {"poc_1": 0, "poc_2": 1, "poc_3": 1, "poc_4": 2}

        result = _topological_sort(adjacency, in_degree)

        assert result[0] == "poc_1"  # Root must be first
        assert result[-1] == "poc_4"  # Leaf must be last
        # poc_2 and poc_3 can be in any order, but before poc_4
        assert result.index("poc_2") < result.index("poc_4")
        assert result.index("poc_3") < result.index("poc_4")

    def test_circular_dependency_detection(self):
        """Test that circular dependency raises error."""
        # poc_1 -> poc_2 -> poc_3 -> poc_1 (cycle)
        adjacency = {
            "poc_1": ["poc_2"],
            "poc_2": ["poc_3"],
            "poc_3": ["poc_1"],
        }
        in_degree = {"poc_1": 1, "poc_2": 1, "poc_3": 1}

        with pytest.raises(CircularDependencyError):
            _topological_sort(adjacency, in_degree)


class TestBuildDependencyGraphNode:
    """Tests for the build_dependency_graph node."""

    @pytest.fixture
    def simple_plan(self):
        """Create a simple execution plan with no dependencies."""
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
            dependency_graph={},
        )

    @pytest.fixture
    def sequential_plan(self):
        """Create a plan with sequential dependencies."""
        return POCExecutionPlan(
            global_success_criteria="Chain complete",
            pocs=[
                POCRequirement(
                    id="poc_1",
                    email="a@test.com",
                    request="Get list",
                    success_criteria="List received",
                ),
                POCRequirement(
                    id="poc_2",
                    email="b@test.com",
                    request="Process list",
                    success_criteria="List processed",
                    dependencies=["poc_1"],
                ),
                POCRequirement(
                    id="poc_3",
                    email="c@test.com",
                    request="Validate",
                    success_criteria="Validated",
                    dependencies=["poc_2"],
                ),
            ],
            dependency_graph={},
        )

    @pytest.mark.asyncio
    async def test_build_graph_no_dependencies(self, simple_plan):
        """Test building graph with no dependencies."""
        state = {
            "execution_plan": simple_plan.to_dict(),
            "poc_states": {},
        }

        result = await build_dependency_graph(state)

        assert result["current_node"] == "build_dependency_graph"
        assert "execution_plan" in result
        assert "progress_messages" in result

        updated_plan = POCExecutionPlan.from_dict(result["execution_plan"])
        assert len(updated_plan.pocs) == 2

    @pytest.mark.asyncio
    async def test_build_graph_sequential(self, sequential_plan):
        """Test building graph with sequential dependencies."""
        state = {
            "execution_plan": sequential_plan.to_dict(),
            "poc_states": {},
        }

        result = await build_dependency_graph(state)

        assert result["current_node"] == "build_dependency_graph"

        updated_plan = POCExecutionPlan.from_dict(result["execution_plan"])

        # Verify execution order
        orders = {poc.id: poc.execution_order for poc in updated_plan.pocs}
        assert orders["poc_1"] < orders["poc_2"] < orders["poc_3"]

    @pytest.mark.asyncio
    async def test_build_graph_no_pocs(self):
        """Test building graph with empty POC list."""
        plan = POCExecutionPlan(
            global_success_criteria="Empty",
            pocs=[],
            dependency_graph={},
        )
        state = {"execution_plan": plan.to_dict(), "poc_states": {}}

        result = await build_dependency_graph(state)

        assert result["current_node"] == "build_dependency_graph"
        assert "No POCs" in result["progress_messages"][0]

    @pytest.mark.asyncio
    async def test_build_graph_circular_dependency(self):
        """Test that circular dependency is detected."""
        plan = POCExecutionPlan(
            global_success_criteria="Cycle",
            pocs=[
                POCRequirement(
                    id="poc_1",
                    email="a@test.com",
                    request="R1",
                    success_criteria="C1",
                    dependencies=["poc_2"],
                ),
                POCRequirement(
                    id="poc_2",
                    email="b@test.com",
                    request="R2",
                    success_criteria="C2",
                    dependencies=["poc_1"],
                ),
            ],
            dependency_graph={},
        )
        state = {"execution_plan": plan.to_dict(), "poc_states": {}}

        result = await build_dependency_graph(state)

        assert result["current_node"] == "error"
        assert "Circular" in result.get("error", "")

    @pytest.mark.asyncio
    async def test_build_graph_missing_execution_plan(self):
        """Test handling of missing execution plan."""
        state = {"poc_states": {}}

        result = await build_dependency_graph(state)

        assert result["current_node"] == "error"
        assert "error" in result
