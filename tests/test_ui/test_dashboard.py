"""
Tests for Dashboard routes.

Tests the dashboard task list, detail, and activity endpoints.
These tests verify that the URL path fix is correctly implemented:
- Dashboard routes should be at /dashboard/... (not /api/dashboard/...)
"""

import pytest
from fastapi.testclient import TestClient


class TestDashboardTaskList:
    """Tests for GET /dashboard/tasks endpoint."""

    def test_list_tasks_success(self, test_client: TestClient) -> None:
        """Test listing tasks returns HTML with task data."""
        response = test_client.get("/dashboard/tasks")
        assert response.status_code == 200
        assert "test-task-123" in response.text
        assert "test-task-456" in response.text

    def test_list_tasks_shows_status(self, test_client: TestClient) -> None:
        """Test task list shows status badges."""
        response = test_client.get("/dashboard/tasks")
        assert response.status_code == 200
        assert "working" in response.text
        assert "completed" in response.text


class TestDashboardTaskDetail:
    """Tests for GET /dashboard/task/{task_id} endpoint."""

    def test_get_task_detail_success(self, test_client: TestClient) -> None:
        """Test getting task detail returns HTML with task info."""
        response = test_client.get("/dashboard/task/test-task-123")
        assert response.status_code == 200
        assert "test-task-123" in response.text

    def test_get_task_detail_shows_status(self, test_client: TestClient) -> None:
        """Test task detail shows status badge."""
        response = test_client.get("/dashboard/task/test-task-123")
        assert response.status_code == 200
        assert "working" in response.text


class TestDashboardTaskActivity:
    """Tests for GET /dashboard/task/{task_id}/activity endpoint."""

    def test_get_task_activity_returns_timeline(
        self, test_client: TestClient
    ) -> None:
        """Test getting task activity returns timeline HTML."""
        response = test_client.get("/dashboard/task/test-task-123/activity")
        assert response.status_code == 200
        # Activity template should render
        assert "Activity History" in response.text

    def test_get_task_activity_shows_events(self, test_client: TestClient) -> None:
        """Test activity shows individual events from mock."""
        response = test_client.get("/dashboard/task/test-task-123/activity")
        assert response.status_code == 200
        # Mock returns "Starting task execution" event
        assert "Starting task execution" in response.text


class TestDashboardRoutePrefix:
    """Tests to verify dashboard routes are at correct paths.

    This is the key fix - dashboard routes should be at /dashboard/...,
    NOT /api/dashboard/... (which was the bug causing activities not to show).
    """

    def test_dashboard_tasks_route_exists(self, test_client: TestClient) -> None:
        """Test /dashboard/tasks endpoint exists (not /api/dashboard/tasks)."""
        response = test_client.get("/dashboard/tasks")
        assert response.status_code == 200

    def test_dashboard_task_detail_route_exists(self, test_client: TestClient) -> None:
        """Test /dashboard/task/{id} endpoint exists."""
        response = test_client.get("/dashboard/task/test-123")
        assert response.status_code == 200

    def test_dashboard_activity_route_exists(self, test_client: TestClient) -> None:
        """Test /dashboard/task/{id}/activity endpoint exists."""
        response = test_client.get("/dashboard/task/test-123/activity")
        assert response.status_code == 200

    def test_api_dashboard_route_not_found(self, test_client: TestClient) -> None:
        """Test /api/dashboard/tasks returns 404 (route moved).

        This test verifies the fix - before the fix, dashboard was mounted
        at /api/dashboard but templates requested /dashboard, causing 404.
        Now /api/dashboard should return 404 since it's not there.
        """
        response = test_client.get("/api/dashboard/tasks")
        assert response.status_code == 404
