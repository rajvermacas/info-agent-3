"""
A2A Executor - Non-blocking bridge between A2A protocol and LangGraph Mail Agent.

Handles:
- Translating A2A requests to LangGraph invocations
- Streaming SSE progress events during execution
- Detecting interrupts and triggering task suspension
- Converting agent responses back to A2A format
"""

import logging
import uuid
from typing import Any, Optional

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.types import Message, Part, Role, TextPart
from langgraph.graph.state import CompiledStateGraph

from mail_agent.agent.state import create_initial_state
from mail_agent.task_manager import TaskManager, TaskState
from mail_agent.task_manager.models import SSEEvent


logger = logging.getLogger(__name__)


class MailAgentA2AExecutor(AgentExecutor):
    """
    A2A executor that bridges the A2A protocol to the LangGraph Mail Agent.

    This non-blocking executor:
    1. Extracts the user instruction from A2A messages
    2. Runs the LangGraph mail agent with streaming events
    3. Detects interrupt points and suspends tasks
    4. Emits SSE events for progress, suspension, and completion
    5. Converts the agent's response to A2A format

    Attributes:
        graph: The compiled LangGraph state graph for the mail agent.
        task_manager: TaskManager for handling suspension and resumption.
    """

    def __init__(
        self,
        graph: CompiledStateGraph,
        task_manager: TaskManager,
    ) -> None:
        """
        Initialize the Mail Agent A2A Executor.

        Args:
            graph: Compiled LangGraph state graph for the mail agent.
            task_manager: TaskManager for task lifecycle management.
        """
        if graph is None:
            raise ValueError("graph cannot be None")
        if task_manager is None:
            raise ValueError("task_manager cannot be None")

        self.graph = graph
        self.task_manager = task_manager

        logger.info("MailAgentA2AExecutor initialized (non-blocking mode)")

    async def execute(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        """
        Execute an A2A task by running the mail agent with SSE streaming.

        This method:
        1. Extracts the instruction text from the A2A message
        2. Creates initial agent state with task_id
        3. Streams the LangGraph execution with SSE events
        4. Detects interrupts and suspends the task
        5. Sends final response or suspension notification

        The execution is non-blocking - when an interrupt occurs (wait_for_reply),
        the task is suspended and control returns immediately. The client
        receives a 'suspended' SSE event and can poll GET /tasks/{id} for results.

        Args:
            context: A2A request context containing task_id and message.
            event_queue: Queue for sending response messages back to client.

        Raises:
            ValueError: If the message doesn't contain instruction text.
        """
        task_id = context.task_id
        logger.info(f"Executing A2A task (non-blocking): {task_id}")

        try:
            # 1. Extract instruction from A2A message
            instruction = self._extract_instruction(context)
            logger.info(
                f"Task {task_id}: Extracted instruction: {instruction[:100]}..."
            )

            # 2. Create initial state with task_id
            initial_state = create_initial_state(instruction)
            initial_state["task_id"] = task_id

            # 3. Run agent with streaming and interrupt detection
            result = await self._run_agent_streaming(
                initial_state, task_id, event_queue
            )

            # 4. If we got a result (not suspended), send response
            if result is not None:
                response_text = self._build_response_text(result, task_id)
                response_message = Message(
                    messageId=str(uuid.uuid4()),
                    role=Role.agent,
                    parts=[Part(root=TextPart(text=response_text))],
                )
                await event_queue.enqueue_event(response_message)
                logger.info(f"Task {task_id}: Response sent")

        except ValueError as e:
            logger.error(f"Task {task_id}: Invalid request: {e}")
            await self._send_error_response(
                event_queue, f"Error: Invalid request - {e}"
            )

        except Exception as e:
            logger.exception(f"Task {task_id}: Execution failed: {e}")
            await self._send_error_response(
                event_queue, f"Error: Task execution failed - {e}"
            )

    async def cancel(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        """
        Handle task cancellation.

        Currently logs a warning. Future implementation could interrupt
        the running graph or mark suspended tasks as cancelled.

        Args:
            context: A2A request context.
            event_queue: Event queue for responses.
        """
        task_id = context.task_id
        logger.warning(
            f"Task {task_id}: Cancellation requested but not fully implemented"
        )

    def _extract_instruction(self, context: RequestContext) -> str:
        """
        Extract instruction text from A2A request context.

        Args:
            context: A2A request context.

        Returns:
            The instruction text.

        Raises:
            ValueError: If no instruction text is found.
        """
        message = context.message
        if not message:
            raise ValueError("No message in request")

        if not message.parts:
            raise ValueError("Message has no parts")

        # Look for the first TextPart
        for part in message.parts:
            actual_part = part.root if isinstance(part, Part) else part

            if isinstance(actual_part, TextPart) and actual_part.text:
                return actual_part.text.strip()

        raise ValueError("No text instruction found in message parts")

    async def _run_agent_streaming(
        self,
        initial_state: dict[str, Any],
        task_id: str,
        event_queue: EventQueue,
    ) -> Optional[dict[str, Any]]:
        """
        Run the LangGraph agent with streaming events and interrupt detection.

        Streams through graph execution, emitting SSE events for each node.
        When an interrupt is detected (from wait_for_reply), suspends the
        task and returns None.

        Args:
            initial_state: Initial agent state.
            task_id: A2A task identifier.
            event_queue: Queue for sending SSE events.

        Returns:
            Final agent state if completed, None if suspended.
        """
        config = {"configurable": {"thread_id": task_id}}
        final_state: Optional[dict[str, Any]] = None

        # Emit initial working event
        await self._emit_sse_event(
            event_queue,
            SSEEvent(
                task_id=task_id,
                state=TaskState.WORKING,
                message="Starting task execution...",
                node="start",
            ),
        )

        # Stream through graph execution
        async for event in self.graph.astream(initial_state, config=config):
            # Check for interrupt
            if self._is_interrupt_event(event):
                interrupt_data = self._extract_interrupt_data(event)
                logger.info(
                    f"Task {task_id}: Interrupt detected - suspending task"
                )

                # Suspend the task
                poc_email = interrupt_data.get("poc_email")
                if poc_email:
                    await self.task_manager.suspend_task(
                        task_id=task_id,
                        poc_email=poc_email,
                        thread_id=task_id,  # Use task_id as thread_id
                        interrupt_data=interrupt_data,
                    )

                    # Emit suspended event
                    await self._emit_sse_event(
                        event_queue,
                        SSEEvent(
                            task_id=task_id,
                            state=TaskState.SUSPENDED,
                            message=f"Waiting for reply from {poc_email}. Poll GET /tasks/{task_id} for result.",
                            poc_email=poc_email,
                        ),
                    )

                    logger.info(
                        f"Task {task_id}: Suspended waiting for {poc_email}"
                    )
                    return None  # Suspended, not completed

                else:
                    logger.error(
                        f"Task {task_id}: Interrupt without POC email"
                    )
                    await self._emit_sse_event(
                        event_queue,
                        SSEEvent(
                            task_id=task_id,
                            state=TaskState.FAILED,
                            message="Interrupt without POC email",
                            error="Interrupt data missing poc_email",
                        ),
                    )
                    return {"error": "Interrupt without POC email"}

            # Process regular node outputs
            for node_name, node_output in event.items():
                if node_name.startswith("__"):
                    continue  # Skip internal events

                logger.debug(f"Task {task_id}: Node {node_name} completed")

                # Get progress messages if available
                progress_messages = node_output.get("progress_messages", [])
                message = progress_messages[-1] if progress_messages else f"Executing {node_name}..."

                # Emit progress event
                await self._emit_sse_event(
                    event_queue,
                    SSEEvent(
                        task_id=task_id,
                        state=TaskState.WORKING,
                        message=message,
                        node=node_name,
                    ),
                )

                # Update final state
                if final_state is None:
                    final_state = dict(initial_state)
                final_state.update(node_output)

                # Check for terminal nodes
                if node_name in ("handle_success", "handle_failure"):
                    # Task completed
                    is_success = node_name == "handle_success"
                    state = TaskState.COMPLETED if is_success else TaskState.FAILED

                    await self._emit_sse_event(
                        event_queue,
                        SSEEvent(
                            task_id=task_id,
                            state=state,
                            message="Task completed successfully" if is_success else "Task failed",
                            node=node_name,
                            result=final_state if is_success else None,
                            error=final_state.get("error") if not is_success else None,
                        ),
                    )

        return final_state or {}

    def _is_interrupt_event(self, event: dict[str, Any]) -> bool:
        """
        Check if an event indicates a LangGraph interrupt.

        Args:
            event: Graph stream event.

        Returns:
            True if this is an interrupt event.
        """
        # LangGraph interrupt events have "__interrupt__" key
        if "__interrupt__" in event:
            return True

        # Check for interrupt in node outputs
        for value in event.values():
            if isinstance(value, dict) and "__interrupt__" in value:
                return True

        return False

    def _extract_interrupt_data(self, event: dict[str, Any]) -> dict[str, Any]:
        """
        Extract interrupt data from an interrupt event.

        Args:
            event: Graph stream event containing interrupt.

        Returns:
            Interrupt payload data.
        """
        # Direct __interrupt__ key
        if "__interrupt__" in event:
            interrupt_info = event["__interrupt__"]
            if isinstance(interrupt_info, list) and len(interrupt_info) > 0:
                # Interrupt info is a list of Interrupt objects
                first_interrupt = interrupt_info[0]
                if hasattr(first_interrupt, 'value'):
                    return first_interrupt.value
            return interrupt_info if isinstance(interrupt_info, dict) else {}

        # Check in node outputs
        for value in event.values():
            if isinstance(value, dict) and "__interrupt__" in value:
                return value["__interrupt__"]

        return {}

    async def _emit_sse_event(
        self,
        event_queue: EventQueue,
        sse_event: SSEEvent,
    ) -> None:
        """
        Emit an SSE event to the client.

        Converts SSEEvent to A2A Message format for the event queue.

        Args:
            event_queue: A2A event queue.
            sse_event: SSE event to emit.
        """
        # Create a status message for the A2A protocol
        # The A2A SDK handles converting to SSE format
        message = Message(
            messageId=str(uuid.uuid4()),
            role=Role.agent,
            parts=[
                Part(
                    root=TextPart(
                        text=f"[{sse_event.state.value}] {sse_event.message}"
                    )
                )
            ],
        )

        # Add metadata for SSE parsing
        # Note: The A2A SDK may not directly support SSE metadata,
        # so we encode key info in the message text
        logger.debug(
            f"SSE: task_id={sse_event.task_id}, state={sse_event.state.value}, "
            f"message={sse_event.message}"
        )

        await event_queue.enqueue_event(message)

    def _build_response_text(
        self, final_state: dict[str, Any], task_id: str
    ) -> str:
        """
        Build response text from final agent state.

        Args:
            final_state: Final agent state after execution.
            task_id: A2A task identifier for logging.

        Returns:
            Response text to send to the A2A client.
        """
        # Check for errors
        error = final_state.get("error")
        if error:
            logger.warning(f"Task {task_id}: Agent returned error: {error}")
            return f"Failed: {error}"

        # Get final summary
        final_summary = final_state.get("final_summary")
        if final_summary:
            logger.info(f"Task {task_id}: Agent completed with summary")
            return final_summary

        # Build summary from conversation states
        conversations = final_state.get("conversations", {})
        if conversations:
            summary_parts = []
            for poc_email, conv_dict in conversations.items():
                status = conv_dict.get("status", "unknown")
                final_result = conv_dict.get("final_result", "pending")
                summary_parts.append(
                    f"- {poc_email}: status={status}, result={final_result}"
                )

            if summary_parts:
                return "Task completed.\n\n" + "\n".join(summary_parts)

        # Fallback
        logger.warning(f"Task {task_id}: No summary available")
        return "Task completed but no summary available."

    async def _send_error_response(
        self, event_queue: EventQueue, error_message: str
    ) -> None:
        """Send an error response message."""
        response_message = Message(
            messageId=str(uuid.uuid4()),
            role=Role.agent,
            parts=[Part(root=TextPart(text=error_message))],
        )
        await event_queue.enqueue_event(response_message)
