"""
Tests for UI DAG routes - DAG visualization endpoints.

Tests:
- DAG page rendering
- DAG data fetching from A2A server
- Error handling for missing/failed requests
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from fastapi.testclient import TestClient


def create_mock_response(status_code: int, json_data: dict) -> MagicMock:
    """Create a mock httpx.Response with proper structure."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = json_data

    # Make raise_for_status work properly
    if status_code >= 400:
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "HTTP Error",
            request=MagicMock(),
            response=mock_resp,
        )
    else:
        mock_resp.raise_for_status.return_value = None

    return mock_resp


class TestDAGRoute:
    """Tests for DAG visualization routes."""

    def test_get_task_dag_renders_visualization(self, test_client: TestClient):
        """Test GET /api/dashboard/task/{task_id}/dag renders DAG visualization."""
        dag_data = {
            "task_id": "test-task-123",
            "phase": "execution",
            "global_status": "running",
            "nodes": [
                {
                    "id": "poc_001",
                    "email": "alice@test.com",
                    "status": "completed",
                    "label": "Alice",
                    "is_dynamic": False,
                    "attempts": 2,
                    "max_attempts": 15,
                },
                {
                    "id": "poc_002",
                    "email": "bob@test.com",
                    "status": "waiting",
                    "label": "Bob",
                    "is_dynamic": False,
                    "attempts": 1,
                    "max_attempts": 15,
                },
            ],
            "edges": [
                {"source": "poc_001", "target": "poc_002"},
            ],
            "progress": {
                "total": 2,
                "completed": 1,
                "waiting": 1,
                "pending": 0,
                "in_progress": 0,
                "failed": 0,
            },
        }
        mock_response = create_mock_response(200, dag_data)

        with patch("ui.routes.dag._fetch_dag_data", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = dag_data

            response = test_client.get("/api/dashboard/task/test-task-123/dag")

            assert response.status_code == 200
            content = response.text

            # Check DAG container is present
            assert "dag-container-test-task-123" in content
            assert "dag-canvas-test-task-123" in content

            # Check phase badge
            assert "Execution" in content

            # Check progress summary
            assert "2 Total" in content
            assert "1 Completed" in content
            assert "1 Waiting" in content

    def test_get_task_dag_empty_nodes(self, test_client: TestClient):
        """Test GET /api/dashboard/task/{task_id}/dag with no nodes."""
        dag_data = {
            "task_id": "test-task-456",
            "phase": "unknown",
            "global_status": "unknown",
            "nodes": [],
            "edges": [],
            "progress": {},
        }

        with patch("ui.routes.dag._fetch_dag_data", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = dag_data

            response = test_client.get("/api/dashboard/task/test-task-456/dag")

            assert response.status_code == 200
            content = response.text

            # Check empty state message
            assert "No POC data available" in content

    def test_get_task_dag_not_found(self, test_client: TestClient):
        """Test GET /api/dashboard/task/{task_id}/dag returns gracefully for 404."""
        # When task not found, _fetch_dag_data returns empty structure
        empty_dag = {
            "task_id": "nonexistent",
            "phase": "unknown",
            "global_status": "unknown",
            "nodes": [],
            "edges": [],
            "progress": {},
        }

        with patch("ui.routes.dag._fetch_dag_data", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = empty_dag

            response = test_client.get("/api/dashboard/task/nonexistent/dag")

            # Should still return 200 with empty DAG structure
            assert response.status_code == 200
            content = response.text
            assert "dag-container-nonexistent" in content

    def test_get_task_dag_connection_error(self, test_client: TestClient):
        """Test GET /api/dashboard/task/{task_id}/dag handles connection errors."""
        from ui.services.a2a_client import A2AClientError

        with patch("ui.routes.dag._fetch_dag_data", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.side_effect = A2AClientError("Connection refused")

            response = test_client.get("/api/dashboard/task/test-task/dag")

            assert response.status_code == 200
            content = response.text

            # Should show error message
            assert "Failed to Load DAG" in content or "error" in content.lower()


class TestDAGDataRoute:
    """Tests for DAG data JSON endpoint."""

    def test_get_task_dag_data_success(self, test_client: TestClient):
        """Test GET /api/dashboard/task/{task_id}/dag/data returns JSON."""
        dag_data = {
            "task_id": "test-task-123",
            "phase": "aggregation",
            "global_status": "running",
            "nodes": [
                {
                    "id": "poc_001",
                    "email": "alice@test.com",
                    "status": "completed",
                    "label": "Alice",
                    "is_dynamic": False,
                },
            ],
            "edges": [],
            "progress": {"total": 1, "completed": 1},
        }

        with patch("ui.routes.dag._fetch_dag_data", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = dag_data

            response = test_client.get("/api/dashboard/task/test-task-123/dag/data")

            assert response.status_code == 200
            data = response.json()

            assert data["task_id"] == "test-task-123"
            assert data["phase"] == "aggregation"
            assert len(data["nodes"]) == 1
            assert data["nodes"][0]["id"] == "poc_001"

    def test_get_task_dag_data_not_found(self, test_client: TestClient):
        """Test GET /api/dashboard/task/{task_id}/dag/data handles 404."""
        # When task not found, _fetch_dag_data returns empty structure
        empty_dag = {
            "task_id": "nonexistent",
            "phase": "unknown",
            "global_status": "unknown",
            "nodes": [],
            "edges": [],
            "progress": {},
        }

        with patch("ui.routes.dag._fetch_dag_data", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = empty_dag

            response = test_client.get("/api/dashboard/task/nonexistent/dag/data")

            assert response.status_code == 200
            data = response.json()

            # Should return empty DAG structure
            assert data["task_id"] == "nonexistent"
            assert data["nodes"] == []
            assert data["edges"] == []

    def test_get_task_dag_data_error(self, test_client: TestClient):
        """Test GET /api/dashboard/task/{task_id}/dag/data handles errors."""
        with patch("ui.routes.dag._fetch_dag_data", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.side_effect = Exception("Network error")

            response = test_client.get("/api/dashboard/task/test-task/dag/data")

            assert response.status_code == 200
            data = response.json()

            # Should return error response
            assert "error" in data
            assert data["nodes"] == []


class TestDAGIntegration:
    """Integration tests for DAG in task detail."""

    def test_task_detail_includes_dag_section(self, test_client: TestClient):
        """Test that task detail page includes DAG section."""
        response = test_client.get("/api/dashboard/task/test-task-123")

        assert response.status_code == 200
        content = response.text

        # Check DAG section is included
        assert "POC Orchestration" in content
        assert "dag-section-test-task-123" in content
        assert "dag-content-test-task-123" in content

        # Check HTMX attributes for dynamic loading
        assert "hx-get" in content
        assert "/api/dashboard/task/test-task-123/dag" in content

    def test_task_detail_dag_refresh_button(self, test_client: TestClient):
        """Test that task detail has DAG refresh button."""
        response = test_client.get("/api/dashboard/task/test-task-123")

        assert response.status_code == 200
        content = response.text

        # Check refresh button exists
        assert "Refresh DAG" in content


class TestDAGVisualizationTemplate:
    """Tests for DAG visualization template rendering."""

    def test_dag_visualization_with_nodes(self, test_client: TestClient):
        """Test DAG visualization renders nodes correctly."""
        dag_data = {
            "task_id": "task-multi-poc",
            "phase": "execution",
            "global_status": "running",
            "nodes": [
                {
                    "id": "poc_raj",
                    "email": "raj@test.com",
                    "status": "completed",
                    "label": "Raj",
                    "is_dynamic": False,
                    "attempts": 1,
                    "max_attempts": 15,
                },
                {
                    "id": "poc_priya",
                    "email": "priya@test.com",
                    "status": "waiting",
                    "label": "Priya",
                    "is_dynamic": False,
                    "attempts": 0,
                    "max_attempts": 15,
                },
                {
                    "id": "poc_dynamic_1",
                    "email": "dynamic@test.com",
                    "status": "pending",
                    "label": "Dynamic",
                    "is_dynamic": True,
                    "attempts": 0,
                    "max_attempts": 15,
                },
            ],
            "edges": [
                {"source": "poc_raj", "target": "poc_priya"},
                {"source": "poc_raj", "target": "poc_dynamic_1"},
            ],
            "progress": {
                "total": 3,
                "completed": 1,
                "waiting": 1,
                "pending": 1,
            },
        }

        with patch("ui.routes.dag._fetch_dag_data", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = dag_data

            response = test_client.get("/api/dashboard/task/task-multi-poc/dag")

            assert response.status_code == 200
            content = response.text

            # Check Cytoscape.js initialization
            assert "cytoscape" in content
            assert "dagre" in content

            # Check legend
            assert "Legend" in content
            assert "Pending" in content
            assert "In Progress" in content
            assert "Waiting" in content
            assert "Completed" in content
            assert "Failed" in content
            assert "Dynamic" in content

    def test_dag_visualization_global_status_completed(self, test_client: TestClient):
        """Test DAG visualization shows completed status."""
        dag_data = {
            "task_id": "completed-task",
            "phase": "completion",
            "global_status": "completed",
            "nodes": [],
            "edges": [],
            "progress": {},
        }

        with patch("ui.routes.dag._fetch_dag_data", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = dag_data

            response = test_client.get("/api/dashboard/task/completed-task/dag")

            assert response.status_code == 200
            content = response.text

            # Check completed status badge
            assert "Completed" in content
            assert "bg-green-100" in content

    def test_dag_visualization_global_status_failed(self, test_client: TestClient):
        """Test DAG visualization shows failed status."""
        dag_data = {
            "task_id": "failed-task",
            "phase": "execution",
            "global_status": "failed",
            "nodes": [],
            "edges": [],
            "progress": {},
        }

        with patch("ui.routes.dag._fetch_dag_data", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = dag_data

            response = test_client.get("/api/dashboard/task/failed-task/dag")

            assert response.status_code == 200
            content = response.text

            # Check failed status badge
            assert "Failed" in content
            assert "bg-red-100" in content
