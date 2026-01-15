"""
Tests for DAG routes - Multi-POC dependency graph API.

Tests:
- DAG endpoint responses
- DAG data extraction from progress store
- DAG data extraction from task manager
- Response model validation
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from mail_agent.a2a.routes.dag import (
    create_dag_router,
    DAGNode,
    DAGEdge,
    DAGResponse,
    _extract_dag_from_progress,
    _extract_dag_from_task_manager,
    _infer_status_from_event,
    _make_label,
)
from mail_agent.a2a.progress_store import ProgressStore, ProgressEvent, POCProgress
from mail_agent.task_manager import TaskManager
from mail_agent.task_manager.models import TaskState, TaskStatus


class TestDAGNode:
    """Tests for DAGNode model."""

    def test_create_dag_node_minimal(self):
        """Test creating DAG node with minimal required fields."""
        node = DAGNode(
            id="poc_001",
            email="poc@test.com",
            status="pending",
            label="Poc",
        )

        assert node.id == "poc_001"
        assert node.email == "poc@test.com"
        assert node.status == "pending"
        assert node.label == "Poc"
        assert node.is_dynamic is False
        assert node.attempts == 0
        assert node.max_attempts == 15

    def test_create_dag_node_full(self):
        """Test creating DAG node with all fields."""
        node = DAGNode(
            id="poc_dynamic_001",
            email="dynamic@test.com",
            status="completed",
            label="Dynamic",
            is_dynamic=True,
            attempts=3,
            max_attempts=10,
        )

        assert node.id == "poc_dynamic_001"
        assert node.email == "dynamic@test.com"
        assert node.status == "completed"
        assert node.label == "Dynamic"
        assert node.is_dynamic is True
        assert node.attempts == 3
        assert node.max_attempts == 10


class TestDAGEdge:
    """Tests for DAGEdge model."""

    def test_create_dag_edge(self):
        """Test creating DAG edge."""
        edge = DAGEdge(
            source="poc_001",
            target="poc_002",
        )

        assert edge.source == "poc_001"
        assert edge.target == "poc_002"


class TestDAGResponse:
    """Tests for DAGResponse model."""

    def test_create_dag_response_minimal(self):
        """Test creating DAG response with minimal fields."""
        response = DAGResponse(
            task_id="task_123",
            phase="execution",
            global_status="running",
            nodes=[],
            edges=[],
            progress={},
        )

        assert response.task_id == "task_123"
        assert response.phase == "execution"
        assert response.global_status == "running"
        assert response.nodes == []
        assert response.edges == []
        assert response.progress == {}
        assert response.global_success_criteria is None

    def test_create_dag_response_full(self):
        """Test creating DAG response with all fields."""
        node1 = DAGNode(id="poc_001", email="a@test.com", status="completed", label="A")
        node2 = DAGNode(id="poc_002", email="b@test.com", status="waiting", label="B")
        edge = DAGEdge(source="poc_001", target="poc_002")

        response = DAGResponse(
            task_id="task_123",
            phase="aggregation",
            global_status="running",
            nodes=[node1, node2],
            edges=[edge],
            progress={"total": 2, "completed": 1, "waiting": 1},
            global_success_criteria="All POCs must respond with valid data",
        )

        assert len(response.nodes) == 2
        assert len(response.edges) == 1
        assert response.progress["total"] == 2
        assert response.global_success_criteria == "All POCs must respond with valid data"


class TestHelperFunctions:
    """Tests for helper functions."""

    def test_infer_status_from_event_poc_started(self):
        """Test inferring status from poc_started event."""
        event = MagicMock()
        event.event_type = "poc_started"

        assert _infer_status_from_event(event) == "in_progress"

    def test_infer_status_from_event_poc_waiting(self):
        """Test inferring status from poc_waiting event."""
        event = MagicMock()
        event.event_type = "poc_waiting"

        assert _infer_status_from_event(event) == "waiting"

    def test_infer_status_from_event_poc_completed(self):
        """Test inferring status from poc_completed event."""
        event = MagicMock()
        event.event_type = "poc_completed"

        assert _infer_status_from_event(event) == "completed"

    def test_infer_status_from_event_poc_failed(self):
        """Test inferring status from poc_failed event."""
        event = MagicMock()
        event.event_type = "poc_failed"

        assert _infer_status_from_event(event) == "failed"

    def test_infer_status_from_event_unknown(self):
        """Test inferring status from unknown event type."""
        event = MagicMock()
        event.event_type = "unknown_event"

        assert _infer_status_from_event(event) == "pending"

    def test_infer_status_from_event_no_type(self):
        """Test inferring status when event_type is None."""
        event = MagicMock()
        event.event_type = None

        assert _infer_status_from_event(event) == "pending"

    def test_make_label_simple_email(self):
        """Test making label from simple email."""
        assert _make_label("john@example.com") == "John"

    def test_make_label_complex_email(self):
        """Test making label from complex email."""
        assert _make_label("jane.doe@example.com") == "Jane.doe"

    def test_make_label_empty_email(self):
        """Test making label from empty email."""
        assert _make_label("") == "Unknown"

    def test_make_label_no_at_sign(self):
        """Test making label from email without @ sign."""
        assert _make_label("invalid") == "Invalid"


class TestExtractDAGFromProgress:
    """Tests for _extract_dag_from_progress function."""

    @pytest.mark.asyncio
    async def test_extract_dag_no_task(self):
        """Test extracting DAG when task doesn't exist."""
        progress_store = ProgressStore()

        result = await _extract_dag_from_progress("nonexistent", progress_store)

        assert result is None

    @pytest.mark.asyncio
    async def test_extract_dag_empty_events(self):
        """Test extracting DAG when task has no events."""
        progress_store = ProgressStore()

        # Create task but don't add events that would produce DAG data
        await progress_store.add_event(ProgressEvent(
            task_id="task_123",
            state=TaskState.WORKING,
            message="Starting",
        ))

        result = await _extract_dag_from_progress("task_123", progress_store)

        # No POC-level data, so returns None
        assert result is None

    @pytest.mark.asyncio
    async def test_extract_dag_with_poc_events(self):
        """Test extracting DAG with POC-level events."""
        progress_store = ProgressStore()

        # Add events with POC data
        await progress_store.add_event(ProgressEvent(
            task_id="task_123",
            state=TaskState.WORKING,
            message="Started POC 1",
            poc_id="poc_001",
            poc_email="alice@test.com",
            event_type="poc_started",
            phase="execution",
        ))

        await progress_store.add_event(ProgressEvent(
            task_id="task_123",
            state=TaskState.WORKING,
            message="POC 1 waiting",
            poc_id="poc_001",
            poc_email="alice@test.com",
            event_type="poc_waiting",
            phase="execution",
        ))

        result = await _extract_dag_from_progress("task_123", progress_store)

        assert result is not None
        assert result["task_id"] == "task_123"
        assert result["phase"] == "execution"
        assert len(result["nodes"]) == 1
        assert result["nodes"][0]["id"] == "poc_001"
        assert result["nodes"][0]["email"] == "alice@test.com"
        assert result["nodes"][0]["status"] == "waiting"

    @pytest.mark.asyncio
    async def test_extract_dag_with_poc_progress(self):
        """Test extracting DAG with POC progress data."""
        progress_store = ProgressStore()

        poc_progress = POCProgress(
            total=3,
            pending=0,
            in_progress=1,
            waiting=1,
            completed=1,
            failed=0,
        )

        await progress_store.add_event(ProgressEvent(
            task_id="task_123",
            state=TaskState.WORKING,
            message="Orchestrating",
            poc_progress=poc_progress,
            phase="execution",
        ))

        result = await _extract_dag_from_progress("task_123", progress_store)

        assert result is not None
        assert result["progress"]["total"] == 3
        assert result["progress"]["completed"] == 1
        assert result["progress"]["waiting"] == 1

    @pytest.mark.asyncio
    async def test_extract_dag_completed_status(self):
        """Test that completed state sets global_status."""
        progress_store = ProgressStore()

        await progress_store.add_event(ProgressEvent(
            task_id="task_123",
            state=TaskState.WORKING,
            message="Starting",
            poc_id="poc_001",
            poc_email="alice@test.com",
        ))

        await progress_store.add_event(ProgressEvent(
            task_id="task_123",
            state=TaskState.COMPLETED,
            message="Done",
        ))

        result = await _extract_dag_from_progress("task_123", progress_store)

        assert result is not None
        assert result["global_status"] == "completed"


class TestExtractDAGFromTaskManager:
    """Tests for _extract_dag_from_task_manager function."""

    @pytest.mark.asyncio
    async def test_extract_dag_task_not_found(self):
        """Test extracting DAG when task doesn't exist."""
        task_manager = MagicMock(spec=TaskManager)
        task_manager.get_waiting_pocs_for_task.return_value = set()
        task_manager.get_task_status = AsyncMock(side_effect=Exception("Not found"))

        result = await _extract_dag_from_task_manager("nonexistent", task_manager)

        assert result is None

    @pytest.mark.asyncio
    async def test_extract_dag_no_waiting_pocs(self):
        """Test extracting DAG with no waiting POCs."""
        task_manager = MagicMock(spec=TaskManager)
        task_manager.get_waiting_pocs_for_task.return_value = set()

        status = TaskStatus(
            task_id="task_123",
            state=TaskState.WORKING,
            message="Processing",
        )
        task_manager.get_task_status = AsyncMock(return_value=status)

        result = await _extract_dag_from_task_manager("task_123", task_manager)

        assert result is not None
        assert result["task_id"] == "task_123"
        assert result["global_status"] == "working"
        assert result["nodes"] == []

    @pytest.mark.asyncio
    async def test_extract_dag_with_waiting_pocs(self):
        """Test extracting DAG with waiting POCs."""
        task_manager = MagicMock(spec=TaskManager)
        task_manager.get_waiting_pocs_for_task.return_value = {"poc_001", "poc_002"}
        task_manager.get_registered_pocs.return_value = ["alice@test.com", "bob@test.com"]

        # get_task_poc_for_email is called multiple times per POC (in _find_email_for_poc loop)
        # For 2 waiting POCs, it iterates through all 2 registered emails for each POC
        # So it can be called up to 4 times total
        def get_task_poc_for_email_mock(email: str):
            mapping = {
                "alice@test.com": ("task_123", "poc_001"),
                "bob@test.com": ("task_123", "poc_002"),
            }
            return mapping.get(email)

        task_manager.get_task_poc_for_email.side_effect = get_task_poc_for_email_mock

        result = await _extract_dag_from_task_manager("task_123", task_manager)

        assert result is not None
        assert result["task_id"] == "task_123"
        assert result["global_status"] == "running"
        assert len(result["nodes"]) == 2
        assert result["progress"]["waiting"] == 2


class TestDAGRouter:
    """Tests for DAG router endpoint."""

    @pytest.fixture
    def app_with_dag_router(self):
        """Create FastAPI app with DAG router."""
        app = FastAPI()

        # Mock dependencies
        task_manager = MagicMock(spec=TaskManager)
        progress_store = ProgressStore()

        router = create_dag_router(task_manager, progress_store)
        app.include_router(router)

        return app, task_manager, progress_store

    def test_get_task_dag_not_found(self, app_with_dag_router):
        """Test GET /tasks/{task_id}/dag returns 404 for unknown task."""
        app, task_manager, progress_store = app_with_dag_router

        # Mock no task found
        task_manager.get_waiting_pocs_for_task.return_value = set()
        task_manager.get_task_status = AsyncMock(side_effect=Exception("Not found"))

        client = TestClient(app)
        response = client.get("/tasks/unknown/dag")

        assert response.status_code == 404
        assert "error" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_get_task_dag_from_progress_store(self, app_with_dag_router):
        """Test GET /tasks/{task_id}/dag retrieves from progress store."""
        app, task_manager, progress_store = app_with_dag_router

        # Add events to progress store
        await progress_store.add_event(ProgressEvent(
            task_id="task_123",
            state=TaskState.WORKING,
            message="Started",
            poc_id="poc_001",
            poc_email="alice@test.com",
            event_type="poc_started",
            phase="execution",
        ))

        client = TestClient(app)
        response = client.get("/tasks/task_123/dag")

        assert response.status_code == 200
        data = response.json()
        assert data["task_id"] == "task_123"
        assert data["phase"] == "execution"
        assert len(data["nodes"]) == 1

    def test_get_task_dag_from_task_manager(self, app_with_dag_router):
        """Test GET /tasks/{task_id}/dag falls back to task manager."""
        app, task_manager, progress_store = app_with_dag_router

        # No progress events, but task exists
        task_manager.get_waiting_pocs_for_task.return_value = set()
        status = TaskStatus(
            task_id="task_456",
            state=TaskState.WORKING,
            message="Processing",
        )
        task_manager.get_task_status = AsyncMock(return_value=status)

        client = TestClient(app)
        response = client.get("/tasks/task_456/dag")

        assert response.status_code == 200
        data = response.json()
        assert data["task_id"] == "task_456"
        assert data["global_status"] == "working"


class TestDAGResponseSerialization:
    """Tests for DAG response JSON serialization."""

    def test_dag_response_json_serialization(self):
        """Test DAG response serializes to valid JSON."""
        response = DAGResponse(
            task_id="task_123",
            phase="execution",
            global_status="running",
            nodes=[
                DAGNode(id="poc_001", email="a@test.com", status="completed", label="A"),
                DAGNode(id="poc_002", email="b@test.com", status="waiting", label="B", is_dynamic=True),
            ],
            edges=[
                DAGEdge(source="poc_001", target="poc_002"),
            ],
            progress={"total": 2, "completed": 1, "waiting": 1},
            global_success_criteria="All POCs respond",
        )

        json_str = response.model_dump_json()

        assert '"task_id":"task_123"' in json_str
        assert '"phase":"execution"' in json_str
        assert '"is_dynamic":true' in json_str
        assert '"global_success_criteria":"All POCs respond"' in json_str

    def test_dag_response_dict_serialization(self):
        """Test DAG response serializes to valid dict."""
        response = DAGResponse(
            task_id="task_123",
            phase="planning",
            global_status="running",
            nodes=[],
            edges=[],
            progress={},
        )

        data = response.model_dump()

        assert data["task_id"] == "task_123"
        assert data["phase"] == "planning"
        assert data["nodes"] == []
        assert data["edges"] == []
        assert data["global_success_criteria"] is None
