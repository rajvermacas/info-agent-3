"""
Tests for UI SSE routes - SSE proxy endpoints.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ui.routes.sse import create_sse_router
from ui.services.sse_client import (
    SSEClientService,
    SSEConnectionError,
    ProgressEvent,
    ProgressState,
)
from ui.config import Settings


@pytest.fixture
def mock_settings():
    """Create mock settings."""
    settings = Settings()
    settings.a2a_server_url = "http://localhost:8000"
    return settings


@pytest.fixture
def mock_sse_client():
    """Create mock SSE client service."""
    return MagicMock(spec=SSEClientService)


@pytest.fixture
def test_app(mock_settings, mock_sse_client):
    """Create test FastAPI app with SSE router."""
    app = FastAPI()
    router = create_sse_router(mock_settings, mock_sse_client)
    app.include_router(router)
    return app


@pytest.fixture
def client(test_app):
    """Create test client."""
    return TestClient(test_app)


class TestGetProgressEventsEndpoint:
    """Tests for GET /api/sse/task/{task_id}/events endpoint."""

    def test_get_events_success(self, client, mock_sse_client):
        """Test getting progress events successfully."""
        # Setup mock
        mock_events = [
            ProgressEvent(
                task_id="task-123",
                state=ProgressState.WORKING,
                message="Processing...",
                node="compose_email",
                timestamp=datetime.now(timezone.utc),
                event_id=1,
            ),
            ProgressEvent(
                task_id="task-123",
                state=ProgressState.WORKING,
                message="Sending...",
                node="send_email",
                timestamp=datetime.now(timezone.utc),
                event_id=2,
            ),
        ]

        async def mock_get_events(*args, **kwargs):
            return mock_events

        mock_sse_client.get_progress_events = AsyncMock(side_effect=mock_get_events)

        # Make request
        response = client.get("/api/sse/task/task-123/events")

        assert response.status_code == 200
        data = response.json()
        assert data["task_id"] == "task-123"
        assert len(data["events"]) == 2
        assert data["event_count"] == 2
        assert data["is_terminal"] is False

    def test_get_events_with_since_event_id(self, client, mock_sse_client):
        """Test getting events with since_event_id parameter."""
        mock_sse_client.get_progress_events = AsyncMock(return_value=[])

        response = client.get("/api/sse/task/task-123/events?since_event_id=5")

        assert response.status_code == 200
        mock_sse_client.get_progress_events.assert_called_once_with("task-123", 5)

    def test_get_events_terminal_state(self, client, mock_sse_client):
        """Test that is_terminal is True when events contain terminal state."""
        mock_events = [
            ProgressEvent(
                task_id="task-123",
                state=ProgressState.COMPLETED,
                message="Done",
                timestamp=datetime.now(timezone.utc),
                event_id=1,
            ),
        ]

        mock_sse_client.get_progress_events = AsyncMock(return_value=mock_events)

        response = client.get("/api/sse/task/task-123/events")

        assert response.status_code == 200
        data = response.json()
        assert data["is_terminal"] is True

    def test_get_events_connection_error(self, client, mock_sse_client):
        """Test handling connection error."""
        mock_sse_client.get_progress_events = AsyncMock(
            side_effect=SSEConnectionError("Connection failed")
        )

        response = client.get("/api/sse/task/task-123/events")

        assert response.status_code == 200
        data = response.json()
        assert "error" in data
        assert data["events"] == []


class TestProgressEventModel:
    """Tests for ProgressEvent model."""

    def test_from_dict_valid(self):
        """Test creating ProgressEvent from valid dict."""
        data = {
            "task_id": "task-123",
            "state": "working",
            "message": "Processing...",
            "node": "compose_email",
            "timestamp": "2025-01-01T12:00:00Z",
            "poc_email": "test@example.com",
        }

        event = ProgressEvent.from_dict(data)

        assert event.task_id == "task-123"
        assert event.state == ProgressState.WORKING
        assert event.message == "Processing..."
        assert event.node == "compose_email"
        assert event.poc_email == "test@example.com"

    def test_from_dict_missing_task_id(self):
        """Test that missing task_id raises ValueError."""
        data = {
            "state": "working",
            "message": "Processing...",
        }

        with pytest.raises(ValueError, match="task_id"):
            ProgressEvent.from_dict(data)

    def test_from_dict_missing_state(self):
        """Test that missing state raises ValueError."""
        data = {
            "task_id": "task-123",
            "message": "Processing...",
        }

        with pytest.raises(ValueError, match="state"):
            ProgressEvent.from_dict(data)

    def test_from_dict_missing_message(self):
        """Test that missing message raises ValueError."""
        data = {
            "task_id": "task-123",
            "state": "working",
        }

        with pytest.raises(ValueError, match="message"):
            ProgressEvent.from_dict(data)

    def test_from_dict_unknown_state(self):
        """Test handling unknown state value."""
        data = {
            "task_id": "task-123",
            "state": "unknown_state",
            "message": "Processing...",
        }

        event = ProgressEvent.from_dict(data)

        # Should default to WORKING
        assert event.state == ProgressState.WORKING

    def test_is_terminal_completed(self):
        """Test is_terminal returns True for completed state."""
        event = ProgressEvent(
            task_id="task-123",
            state=ProgressState.COMPLETED,
            message="Done",
        )

        assert event.is_terminal is True

    def test_is_terminal_failed(self):
        """Test is_terminal returns True for failed state."""
        event = ProgressEvent(
            task_id="task-123",
            state=ProgressState.FAILED,
            message="Error",
        )

        assert event.is_terminal is True

    def test_is_terminal_working(self):
        """Test is_terminal returns False for working state."""
        event = ProgressEvent(
            task_id="task-123",
            state=ProgressState.WORKING,
            message="Processing...",
        )

        assert event.is_terminal is False

    def test_is_terminal_suspended(self):
        """Test is_terminal returns False for suspended state."""
        event = ProgressEvent(
            task_id="task-123",
            state=ProgressState.SUSPENDED,
            message="Waiting...",
        )

        assert event.is_terminal is False


class TestSSEClientService:
    """Tests for SSEClientService."""

    def test_init(self, mock_settings):
        """Test SSE client initialization."""
        client = SSEClientService(mock_settings)

        assert client._base_url == "http://localhost:8000"

    def test_init_strips_trailing_slash(self):
        """Test that trailing slash is stripped from URL."""
        settings = Settings()
        settings.a2a_server_url = "http://localhost:8000/"

        client = SSEClientService(settings)

        assert client._base_url == "http://localhost:8000"
