"""
A2A Executor - Bridge between A2A protocol and LangGraph Mail Agent.

Translates A2A requests to LangGraph invocations and converts the agent's
response back to A2A format.
"""

import logging
import uuid
from typing import Any, Optional

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.types import Message, Part, Role, TextPart, DataPart, FilePart
from langgraph.graph.state import CompiledStateGraph

from mail_agent.agent.state import create_initial_state
from mail_agent.webhook.router import TaskRouter
from mail_agent.webhook.server import WebhookServer


logger = logging.getLogger(__name__)


class MailAgentA2AExecutor(AgentExecutor):
    """
    A2A executor that bridges the A2A protocol to the LangGraph Mail Agent.

    This class is responsible for:
    1. Extracting the user instruction from A2A messages
    2. Running the LangGraph mail agent with the instruction
    3. Converting the agent's response to A2A format
    4. Managing task registration with TaskRouter for webhook routing

    Attributes:
        graph: The compiled LangGraph state graph for the mail agent.
        task_router: TaskRouter for routing webhook events to tasks.
        webhook_server: WebhookServer for receiving webhook callbacks.
    """

    def __init__(
        self,
        graph: CompiledStateGraph,
        task_router: TaskRouter,
        webhook_server: WebhookServer,
    ) -> None:
        """
        Initialize the Mail Agent A2A Executor.

        Args:
            graph: Compiled LangGraph state graph for the mail agent.
            task_router: TaskRouter for webhook event routing.
            webhook_server: WebhookServer for email notifications.
        """
        self.graph = graph
        self.task_router = task_router
        self.webhook_server = webhook_server

        logger.info("MailAgentA2AExecutor initialized")

    async def execute(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        """
        Execute an A2A task by running the mail agent.

        This method:
        1. Extracts the instruction text from the A2A message
        2. Creates initial agent state with task_id for routing
        3. Runs the LangGraph agent
        4. Extracts the final summary or error
        5. Sends the response via the event queue

        Args:
            context: A2A request context containing task_id and message.
            event_queue: Queue for sending response messages back to client.

        Raises:
            ValueError: If the message doesn't contain instruction text.
        """
        task_id = context.task_id
        logger.info(f"Executing A2A task: {task_id}")

        try:
            # 1. Extract instruction from A2A message
            instruction = self._extract_instruction(context)
            logger.info(
                f"Task {task_id}: Extracted instruction: {instruction[:100]}..."
            )

            # 2. Create initial state with task_id
            initial_state = create_initial_state(instruction)
            initial_state["task_id"] = task_id

            # 3. Run the LangGraph agent
            logger.info(f"Task {task_id}: Starting agent execution")
            final_state = await self._run_agent(initial_state, task_id)

            # 4. Build response text
            response_text = self._build_response_text(final_state, task_id)

        except ValueError as e:
            logger.error(f"Task {task_id}: Invalid request: {e}")
            response_text = f"Error: Invalid request - {e}"

        except Exception as e:
            logger.exception(f"Task {task_id}: Execution failed: {e}")
            response_text = f"Error: Task execution failed - {e}"

        # 5. Send A2A response
        response_message = Message(
            messageId=str(uuid.uuid4()),
            role=Role.agent,
            parts=[Part(root=TextPart(text=response_text))],
        )
        await event_queue.enqueue_event(response_message)
        logger.info(f"Task {task_id}: Response sent")

    async def cancel(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        """
        Handle task cancellation.

        Currently not implemented - logs a warning and does nothing.
        Future implementation could interrupt the running graph.

        Args:
            context: A2A request context.
            event_queue: Event queue for responses.
        """
        task_id = context.task_id
        logger.warning(
            f"Task {task_id}: Cancellation requested but not implemented"
        )
        # Future: Could set a flag to interrupt the graph execution

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
        # Parts in A2A SDK are wrapped in Part objects with a 'root' attribute
        for part in message.parts:
            # Handle both wrapped Part and direct TextPart
            actual_part = part.root if isinstance(part, Part) else part

            if isinstance(actual_part, TextPart) and actual_part.text:
                return actual_part.text.strip()

        raise ValueError("No text instruction found in message parts")

    async def _run_agent(
        self, initial_state: dict[str, Any], task_id: str
    ) -> dict[str, Any]:
        """
        Run the LangGraph agent with the given initial state.

        Args:
            initial_state: Initial agent state.
            task_id: A2A task identifier for logging.

        Returns:
            Final agent state after execution.
        """
        final_state: Optional[dict[str, Any]] = None

        # Stream through graph execution
        async for event in self.graph.astream(initial_state):
            # Event is a dict with node name as key
            for node_name, node_output in event.items():
                logger.debug(f"Task {task_id}: Node {node_name} completed")

                # Log progress messages
                progress_messages = node_output.get("progress_messages", [])
                for msg in progress_messages:
                    logger.info(f"Task {task_id}: [{node_name}] {msg}")

                # Update final state
                if final_state is None:
                    final_state = dict(initial_state)
                final_state.update(node_output)

        return final_state or {}

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
