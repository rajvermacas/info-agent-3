"""
Unit tests for MailAgentA2AExecutor class.

Tests cover:
- Instruction extraction from A2A messages
- Response building from agent state
- Error handling for invalid requests
- Integration with mocked graph execution
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from a2a.server.events import EventQueue
from a2a.types import Message, Part, Role, TextPart

from mail_agent.a2a.executor import MailAgentA2AExecutor


from mail_agent.webhook.router import TaskRouter
from mail_agent.webhook.server import WebhookServer


def get_part_text(part) -> str:
    """Extract text from a Part or TextPart object."""
    actual_part = part.root if isinstance(part, Part) else part
    return actual_part.text if hasattr(actual_part, 'text') else str(actual_part)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_graph() -> MagicMock:
    """Create a mock LangGraph compiled state graph."""
    graph = MagicMock()

    async def mock_astream(initial_state):
        """Mock async stream that yields node outputs."""
        # Simulate a successful agent execution
        yield {
            "parse_instruction": {
                "progress_messages": ["Parsed instruction"],
                "parsed_request": {"poc_emails": ["test@example.com"]},
                "conversations": {"test@example.com": {"status": "pending"}},
            }
        }
        yield {
            "handle_success": {
                "progress_messages": ["Task completed successfully"],
                "final_summary": "Successfully received 10 recipes from test@example.com",
            }
        }

    graph.astream = mock_astream
    return graph


@pytest.fixture
def mock_task_router() -> TaskRouter:
    """Create a TaskRouter instance for testing."""
    return TaskRouter()


@pytest.fixture
def mock_webhook_server() -> MagicMock:
    """Create a mock WebhookServer."""
    return MagicMock(spec=WebhookServer)


@pytest.fixture
def executor(
    mock_graph: MagicMock,
    mock_task_router: TaskRouter,
    mock_webhook_server: MagicMock,
) -> MailAgentA2AExecutor:
    """Create a MailAgentA2AExecutor instance for testing."""
    return MailAgentA2AExecutor(
        graph=mock_graph,
        task_router=mock_task_router,
        webhook_server=mock_webhook_server,
    )


@pytest.fixture
def mock_request_context() -> MagicMock:
    """Create a mock RequestContext with valid message."""
    context = MagicMock()
    context.task_id = "test-task-123"
    context.message = Message(
        messageId="msg-123",
        role=Role.user,
        parts=[TextPart(text="Email test@example.com asking for 10 recipes")],
    )
    return context


@pytest.fixture
def mock_event_queue() -> AsyncMock:
    """Create a mock EventQueue."""
    queue = AsyncMock(spec=EventQueue)
    queue.put = AsyncMock()
    return queue


# ============================================================================
# Instruction Extraction Tests
# ============================================================================


class TestInstructionExtraction:
    """Test instruction extraction from A2A messages."""

    def test_extract_instruction_from_text_part(
        self, executor: MailAgentA2AExecutor
    ) -> None:
        """Test extracting instruction from TextPart."""
        context = MagicMock()
        context.message = Message(
            messageId="test-msg-1",
            role=Role.user,
            parts=[TextPart(text="  Test instruction  ")],
        )

        instruction = executor._extract_instruction(context)

        assert instruction == "Test instruction"

    def test_extract_instruction_no_message_raises_error(
        self, executor: MailAgentA2AExecutor
    ) -> None:
        """Test that missing message raises ValueError."""
        context = MagicMock()
        context.message = None

        with pytest.raises(ValueError) as exc_info:
            executor._extract_instruction(context)

        assert "No message" in str(exc_info.value)

    def test_extract_instruction_no_parts_raises_error(
        self, executor: MailAgentA2AExecutor
    ) -> None:
        """Test that message without parts raises ValueError."""
        context = MagicMock()
        context.message = Message(messageId="test-msg-2", role=Role.user, parts=[])

        with pytest.raises(ValueError) as exc_info:
            executor._extract_instruction(context)

        assert "no parts" in str(exc_info.value)

    def test_extract_instruction_no_text_part_raises_error(
        self, executor: MailAgentA2AExecutor
    ) -> None:
        """Test that message without TextPart raises ValueError."""
        context = MagicMock()
        # Create a message with a non-text part
        context.message = Message(messageId="test-msg-3", role=Role.user, parts=[])

        with pytest.raises(ValueError) as exc_info:
            executor._extract_instruction(context)

        assert "no parts" in str(exc_info.value)


# ============================================================================
# Response Building Tests
# ============================================================================


class TestResponseBuilding:
    """Test response building from agent state."""

    def test_build_response_with_error(
        self, executor: MailAgentA2AExecutor
    ) -> None:
        """Test building response when state has error."""
        final_state = {"error": "Something went wrong"}

        response = executor._build_response_text(final_state, "task-123")

        assert "Failed:" in response
        assert "Something went wrong" in response

    def test_build_response_with_final_summary(
        self, executor: MailAgentA2AExecutor
    ) -> None:
        """Test building response when state has final_summary."""
        final_state = {
            "final_summary": "Successfully received 10 recipes from test@example.com"
        }

        response = executor._build_response_text(final_state, "task-123")

        assert "Successfully received 10 recipes" in response

    def test_build_response_from_conversations(
        self, executor: MailAgentA2AExecutor
    ) -> None:
        """Test building response from conversation states."""
        final_state = {
            "conversations": {
                "poc1@example.com": {"status": "success", "final_result": "success"},
                "poc2@example.com": {"status": "failed", "final_result": "failed_max_attempts"},
            }
        }

        response = executor._build_response_text(final_state, "task-123")

        assert "Task completed" in response
        assert "poc1@example.com" in response
        assert "poc2@example.com" in response
        assert "success" in response
        assert "failed" in response

    def test_build_response_fallback(
        self, executor: MailAgentA2AExecutor
    ) -> None:
        """Test fallback response when no summary available."""
        final_state = {}

        response = executor._build_response_text(final_state, "task-123")

        assert "no summary available" in response


# ============================================================================
# Execute Tests
# ============================================================================


class TestExecute:
    """Test the execute method."""

    @pytest.mark.asyncio
    async def test_execute_successful(
        self,
        executor: MailAgentA2AExecutor,
        mock_request_context: MagicMock,
        mock_event_queue: AsyncMock,
    ) -> None:
        """Test successful execution."""
        await executor.execute(mock_request_context, mock_event_queue)

        # Verify response was sent
        mock_event_queue.put.assert_called_once()

        # Verify response content
        call_args = mock_event_queue.put.call_args
        response_message = call_args[0][0]

        assert isinstance(response_message, Message)
        assert response_message.role == Role.agent
        assert len(response_message.parts) == 1
        part_text = get_part_text(response_message.parts[0])
        assert "Successfully received 10 recipes" in part_text

    @pytest.mark.asyncio
    async def test_execute_with_invalid_message(
        self,
        executor: MailAgentA2AExecutor,
        mock_event_queue: AsyncMock,
    ) -> None:
        """Test execution with invalid message."""
        context = MagicMock()
        context.task_id = "test-task-456"
        context.message = None

        await executor.execute(context, mock_event_queue)

        # Verify error response was sent
        mock_event_queue.put.assert_called_once()

        call_args = mock_event_queue.put.call_args
        response_message = call_args[0][0]

        part_text = get_part_text(response_message.parts[0])
        assert "Error" in part_text

    @pytest.mark.asyncio
    async def test_execute_with_graph_error(
        self,
        mock_task_router: TaskRouter,
        mock_webhook_server: MagicMock,
        mock_request_context: MagicMock,
        mock_event_queue: AsyncMock,
    ) -> None:
        """Test execution when graph raises an exception."""
        # Create a graph that raises an error
        graph = MagicMock()

        async def mock_astream_error(initial_state):
            raise RuntimeError("Graph execution failed")
            yield  # Make it a generator

        graph.astream = mock_astream_error

        executor = MailAgentA2AExecutor(
            graph=graph,
            task_router=mock_task_router,
            webhook_server=mock_webhook_server,
        )

        await executor.execute(mock_request_context, mock_event_queue)

        # Verify error response was sent
        mock_event_queue.put.assert_called_once()

        call_args = mock_event_queue.put.call_args
        response_message = call_args[0][0]

        part_text = get_part_text(response_message.parts[0])
        assert "Error" in part_text
        assert "Graph execution failed" in part_text

    @pytest.mark.asyncio
    async def test_execute_sets_task_id_in_state(
        self,
        mock_task_router: TaskRouter,
        mock_webhook_server: MagicMock,
        mock_request_context: MagicMock,
        mock_event_queue: AsyncMock,
    ) -> None:
        """Test that execute sets task_id in the initial state."""
        captured_state = None

        async def mock_astream_capture(initial_state):
            nonlocal captured_state
            captured_state = dict(initial_state)
            yield {"test_node": {"progress_messages": []}}

        graph = MagicMock()
        graph.astream = mock_astream_capture

        executor = MailAgentA2AExecutor(
            graph=graph,
            task_router=mock_task_router,
            webhook_server=mock_webhook_server,
        )

        await executor.execute(mock_request_context, mock_event_queue)

        assert captured_state is not None
        assert captured_state.get("task_id") == "test-task-123"


# ============================================================================
# Cancel Tests
# ============================================================================


class TestCancel:
    """Test the cancel method."""

    @pytest.mark.asyncio
    async def test_cancel_logs_warning(
        self,
        executor: MailAgentA2AExecutor,
        mock_request_context: MagicMock,
        mock_event_queue: AsyncMock,
    ) -> None:
        """Test that cancel logs a warning (not implemented)."""
        # Cancel should not raise an exception
        await executor.cancel(mock_request_context, mock_event_queue)

        # Currently does nothing - just verify it doesn't crash


# ============================================================================
# Integration Tests
# ============================================================================


class TestExecutorIntegration:
    """Integration tests for MailAgentA2AExecutor."""

    @pytest.mark.asyncio
    async def test_executor_with_error_state(
        self,
        mock_task_router: TaskRouter,
        mock_webhook_server: MagicMock,
        mock_request_context: MagicMock,
        mock_event_queue: AsyncMock,
    ) -> None:
        """Test executor handling of graph that returns error state."""

        async def mock_astream_with_error(initial_state):
            yield {
                "parse_instruction": {
                    "error": "Failed to parse instruction",
                    "progress_messages": ["ERROR: Invalid instruction format"],
                }
            }

        graph = MagicMock()
        graph.astream = mock_astream_with_error

        executor = MailAgentA2AExecutor(
            graph=graph,
            task_router=mock_task_router,
            webhook_server=mock_webhook_server,
        )

        await executor.execute(mock_request_context, mock_event_queue)

        # Verify error response
        call_args = mock_event_queue.put.call_args
        response_message = call_args[0][0]

        part_text = get_part_text(response_message.parts[0])
        assert "Failed:" in part_text
        assert "Failed to parse instruction" in part_text

    @pytest.mark.asyncio
    async def test_executor_with_multiple_node_outputs(
        self,
        mock_task_router: TaskRouter,
        mock_webhook_server: MagicMock,
        mock_request_context: MagicMock,
        mock_event_queue: AsyncMock,
    ) -> None:
        """Test executor correctly accumulates state from multiple nodes."""

        async def mock_astream_multi_node(initial_state):
            yield {"node1": {"key1": "value1", "progress_messages": ["Step 1"]}}
            yield {"node2": {"key2": "value2", "progress_messages": ["Step 2"]}}
            yield {
                "node3": {
                    "final_summary": "All steps completed",
                    "progress_messages": ["Done"],
                }
            }

        graph = MagicMock()
        graph.astream = mock_astream_multi_node

        executor = MailAgentA2AExecutor(
            graph=graph,
            task_router=mock_task_router,
            webhook_server=mock_webhook_server,
        )

        await executor.execute(mock_request_context, mock_event_queue)

        # Verify final response
        call_args = mock_event_queue.put.call_args
        response_message = call_args[0][0]

        part_text = get_part_text(response_message.parts[0])
        assert "All steps completed" in part_text
