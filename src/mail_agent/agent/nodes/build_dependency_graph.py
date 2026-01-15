"""
Build Dependency Graph Node - Construct DAG from POC dependencies.

Analyzes POC dependencies to build a directed acyclic graph (DAG),
detects circular dependencies, and assigns execution order via topological sort.
"""

import logging
from collections import deque
from typing import Any

from mail_agent.agent.multi_poc_helpers import get_execution_plan
from mail_agent.agent.multi_poc_state import POCExecutionPlan, POCRequirement
from mail_agent.agent.state import AgentState


logger = logging.getLogger(__name__)


class CircularDependencyError(Exception):
    """Raised when circular dependencies are detected in POC graph."""

    def __init__(self, cycle: list[str]):
        self.cycle = cycle
        cycle_str = " -> ".join(cycle)
        super().__init__(f"Circular dependency detected: {cycle_str}")


def _build_adjacency_list(
    pocs: list[POCRequirement],
) -> tuple[dict[str, list[str]], dict[str, int]]:
    """
    Build adjacency list and in-degree map from POC requirements.

    Args:
        pocs: List of POC requirements with dependencies.

    Returns:
        Tuple of (adjacency_list, in_degree_map).
        adjacency_list: Maps poc_id -> list of POCs that depend on it.
        in_degree_map: Maps poc_id -> number of dependencies it has.
    """
    adjacency: dict[str, list[str]] = {poc.id: [] for poc in pocs}
    in_degree: dict[str, int] = {poc.id: 0 for poc in pocs}

    for poc in pocs:
        for dep_id in poc.dependencies:
            if dep_id in adjacency:
                # dep_id -> poc.id means poc.id depends on dep_id
                adjacency[dep_id].append(poc.id)
                in_degree[poc.id] += 1
            else:
                logger.warning(
                    f"POC {poc.id} has dependency on unknown POC: {dep_id}. "
                    "Ignoring invalid dependency."
                )

    return adjacency, in_degree


def _topological_sort(
    adjacency: dict[str, list[str]],
    in_degree: dict[str, int],
) -> list[str]:
    """
    Perform topological sort using Kahn's algorithm.

    Args:
        adjacency: Maps poc_id -> list of POCs that depend on it.
        in_degree: Maps poc_id -> number of dependencies it has.

    Returns:
        List of POC IDs in topological order.

    Raises:
        CircularDependencyError: If circular dependency is detected.
    """
    # Copy in_degree to avoid mutation
    in_degree = dict(in_degree)

    # Start with POCs that have no dependencies
    queue = deque([poc_id for poc_id, deg in in_degree.items() if deg == 0])
    sorted_order: list[str] = []

    while queue:
        current = queue.popleft()
        sorted_order.append(current)

        # Reduce in-degree for dependent POCs
        for dependent in adjacency.get(current, []):
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    # Check for cycle
    if len(sorted_order) != len(in_degree):
        # Find cycle for error message
        remaining = [poc_id for poc_id in in_degree if poc_id not in sorted_order]
        raise CircularDependencyError(remaining)

    return sorted_order


def _detect_cycle(
    adjacency: dict[str, list[str]],
    start: str,
) -> list[str] | None:
    """
    Detect cycle starting from a given node using DFS.

    Args:
        adjacency: Maps poc_id -> list of POCs that depend on it.
        start: Starting node for cycle detection.

    Returns:
        List of POC IDs forming the cycle, or None if no cycle.
    """
    visited: set[str] = set()
    rec_stack: set[str] = set()
    path: list[str] = []

    def dfs(node: str) -> bool:
        visited.add(node)
        rec_stack.add(node)
        path.append(node)

        for neighbor in adjacency.get(node, []):
            if neighbor not in visited:
                if dfs(neighbor):
                    return True
            elif neighbor in rec_stack:
                # Found cycle
                path.append(neighbor)
                return True

        path.pop()
        rec_stack.remove(node)
        return False

    if dfs(start):
        # Extract just the cycle portion
        cycle_start = path[-1]
        cycle_idx = path.index(cycle_start)
        return path[cycle_idx:]

    return None


async def build_dependency_graph(state: AgentState) -> dict[str, Any]:
    """
    Build dependency graph and assign execution order to POCs.

    This node:
    1. Constructs DAG from POC dependencies
    2. Detects circular dependencies (raises error if found)
    3. Assigns execution_order via topological sort
    4. Updates execution_plan with dependency_graph

    Args:
        state: Current agent state with execution_plan.

    Returns:
        State update with updated execution_plan containing dependency_graph
        and execution_order for each POC.

    Raises:
        CircularDependencyError: If circular dependencies are detected.
    """
    logger.info("Building dependency graph for POCs")

    try:
        execution_plan = get_execution_plan(state)
        pocs = execution_plan.pocs

        if not pocs:
            logger.warning("No POCs in execution plan")
            return {
                "current_node": "build_dependency_graph",
                "progress_messages": ["No POCs to process"],
            }

        logger.debug(f"Building graph for {len(pocs)} POCs")

        # Build adjacency list and in-degree map
        adjacency, in_degree = _build_adjacency_list(pocs)

        # Log dependency structure
        for poc in pocs:
            if poc.dependencies:
                logger.debug(f"POC {poc.id} depends on: {poc.dependencies}")
            else:
                logger.debug(f"POC {poc.id} has no dependencies (root node)")

        # Perform topological sort
        try:
            sorted_order = _topological_sort(adjacency, in_degree)
            logger.info(f"Topological order: {sorted_order}")
        except CircularDependencyError as e:
            logger.error(f"Circular dependency detected: {e.cycle}")
            return {
                "error": str(e),
                "current_node": "error",
                "progress_messages": [f"ERROR: {e}"],
            }

        # Update execution order for each POC
        updated_pocs: list[POCRequirement] = []
        order_map = {poc_id: idx for idx, poc_id in enumerate(sorted_order)}

        for poc in pocs:
            updated_poc = POCRequirement(
                id=poc.id,
                email=poc.email,
                request=poc.request,
                success_criteria=poc.success_criteria,
                dependencies=poc.dependencies,
                execution_order=order_map.get(poc.id, 0),
                spawns_dynamic_pocs=poc.spawns_dynamic_pocs,
                context_from_deps=poc.context_from_deps,
            )
            updated_pocs.append(updated_poc)
            logger.debug(
                f"POC {poc.id}: execution_order={updated_poc.execution_order}"
            )

        # Build dependency graph representation
        # Maps poc_id -> list of POC IDs it depends on
        dependency_graph: dict[str, list[str]] = {}
        for poc in pocs:
            dependency_graph[poc.id] = list(poc.dependencies)

        # Create updated execution plan
        updated_plan = POCExecutionPlan(
            global_success_criteria=execution_plan.global_success_criteria,
            pocs=updated_pocs,
            dependency_graph=dependency_graph,
        )

        # Create progress message
        root_pocs = [poc.id for poc in pocs if not poc.dependencies]
        leaf_pocs = [
            poc.id for poc in pocs
            if not any(poc.id in other.dependencies for other in pocs)
        ]

        progress_msg = (
            f"Dependency graph built: {len(pocs)} POCs, "
            f"{len(root_pocs)} root(s), {len(leaf_pocs)} leaf(s). "
            f"Execution order: {' -> '.join(sorted_order)}"
        )

        logger.info(
            f"Dependency graph complete: roots={root_pocs}, "
            f"leaves={leaf_pocs}, order={sorted_order}"
        )

        return {
            "execution_plan": updated_plan.to_dict(),
            "current_node": "build_dependency_graph",
            "progress_messages": [progress_msg],
        }

    except CircularDependencyError:
        raise
    except Exception as e:
        error_msg = f"Failed to build dependency graph: {e}"
        logger.error(error_msg, exc_info=True)
        return {
            "error": error_msg,
            "current_node": "error",
            "progress_messages": [f"ERROR: {error_msg}"],
        }
