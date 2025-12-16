"""
A2A Client Service for UI.

Handles communication with the A2A server (Mail Agent).
"""

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, AsyncGenerator
from uuid import uuid4

import httpx

from ui.config import Settings

logger = logging.getLogger(__name__)


class A2AClientError(Exception):
    """Base exception for A2A client errors."""

    pass


class A2AConnectionError(A2AClientError):
    """Raised when connection to A2A server fails."""

    pass


class A2ATaskError(A2AClientError):
    """Raised when task execution fails."""

    pass


@dataclass
class TaskInfo:
    """Information about an A2A task."""

    task_id: str
    state: str
    message: str | None = None
    poc_email: str | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None
    result: dict | None = None
    error: str | None = None


@dataclass
class AgentInfo:
    """Information about the A2A agent."""

    name: str
    version: str
    description: str
    url: str
    capabilities: list[str] | None = None


class A2AClientService:
    """
    Client service for A2A server communication.

    Handles:
    - Agent card fetching
    - Task submission via JSON-RPC
    - Task status polling
    - SSE streaming for real-time updates
    """

    def __init__(self, settings: Settings):
        """
        Initialize the A2A client service.

        Args:
            settings: UI settings containing A2A server URL.
        """
        self._settings = settings
        self._client: httpx.AsyncClient | None = None
        self._base_url = settings.a2a_server_url.rstrip("/")
        logger.info("A2AClientService initialized with base URL: %s", self._base_url)

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._settings.http_timeout_seconds,
            )
            logger.debug("Created new httpx client for A2A server")
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            logger.debug("A2A client closed")

    async def get_agent_info(self) -> AgentInfo:
        """
        Fetch the agent card from the A2A server.

        Returns:
            AgentInfo: Information about the agent.

        Raises:
            A2AConnectionError: If connection fails.
        """
        logger.info("Fetching agent info from A2A server")
        client = await self._get_client()

        try:
            response = await client.get("/.well-known/agent.json")
            response.raise_for_status()
            data = response.json()

            logger.info("Agent info fetched: %s v%s", data.get("name"), data.get("version"))

            return AgentInfo(
                name=data.get("name", "Unknown"),
                version=data.get("version", "Unknown"),
                description=data.get("description", ""),
                url=data.get("url", self._base_url),
                capabilities=[s.get("id") for s in data.get("skills", [])],
            )
        except httpx.ConnectError as e:
            logger.error("Failed to connect to A2A server: %s", e)
            raise A2AConnectionError(f"Cannot connect to A2A server at {self._base_url}") from e
        except httpx.HTTPStatusError as e:
            logger.error("HTTP error fetching agent info: %s", e)
            raise A2AConnectionError(f"HTTP error: {e.response.status_code}") from e
        except Exception as e:
            logger.error("Unexpected error fetching agent info: %s", e)
            raise A2AConnectionError(f"Unexpected error: {e}") from e

    async def send_task(self, instruction: str) -> TaskInfo:
        """
        Send a task to the A2A server.

        Uses JSON-RPC 2.0 protocol to submit the task.

        Args:
            instruction: The user instruction (e.g., "Send mail to x@y.com asking for 10 recipes")

        Returns:
            TaskInfo: Initial task information.

        Raises:
            A2ATaskError: If task submission fails.
        """
        logger.info("Sending task to A2A server: %s", instruction[:50])

        # Create long-polling client for task submission
        client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._settings.http_long_poll_timeout_seconds,
        )

        try:
            # JSON-RPC 2.0 request format
            rpc_request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "message/send",
                "params": {
                    "message": {
                        "messageId": uuid4().hex,
                        "role": "user",
                        "parts": [{"type": "text", "text": instruction}],
                    }
                },
            }

            logger.debug("Sending JSON-RPC request: %s", rpc_request)

            response = await client.post(
                "/",
                json=rpc_request,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            data = response.json()

            logger.debug("JSON-RPC response: %s", data)

            # Check for JSON-RPC error
            if "error" in data:
                error = data["error"]
                logger.error("JSON-RPC error: %s", error)
                raise A2ATaskError(f"RPC Error: {error.get('message', 'Unknown error')}")

            # Extract task info from result
            result = data.get("result", {})

            # Handle different response formats
            task_id = None
            state = "submitted"
            message = None

            if isinstance(result, dict):
                # Check if this is a Message response (suspended task)
                if result.get("kind") == "message":
                    # Extract task_id from message text content
                    # Message format: "[suspended] Waiting for reply from {poc}. Poll GET /tasks/{task_id} for result."
                    parts = result.get("parts", [])
                    for part in parts:
                        if isinstance(part, dict):
                            text = part.get("text", "")
                            # Handle nested Part structure
                            if "root" in part:
                                root = part.get("root", {})
                                if isinstance(root, dict):
                                    text = root.get("text", "")
                        else:
                            text = ""

                        # Look for task_id in "Poll GET /tasks/{task_id}" pattern
                        match = re.search(r'/tasks/([a-f0-9-]+)', text)
                        if match:
                            task_id = match.group(1)
                            logger.debug("Extracted task_id from message text: %s", task_id)
                            break

                    # Extract state from message text prefix
                    parts_str = str(parts)
                    if "[suspended]" in parts_str:
                        state = "suspended"
                    elif "[completed]" in parts_str:
                        state = "completed"
                    elif "[failed]" in parts_str:
                        state = "failed"
                    elif "[working]" in parts_str:
                        state = "working"

                    logger.debug("Message response - task_id: %s, state: %s", task_id, state)
                else:
                    # Task response - extract normally
                    task_id = result.get("id") or result.get("task_id")
                    state = result.get("state") or result.get("status", "submitted")
                    message = result.get("message")

            # Validate task_id before returning
            if task_id is None:
                logger.warning("Could not extract task_id from response: %s", result)

            logger.info("Task submitted successfully: %s (state: %s)", task_id, state)

            return TaskInfo(
                task_id=task_id if task_id is not None else "",
                state=state,
                message=message,
            )
        except httpx.ConnectError as e:
            logger.error("Failed to connect to A2A server: %s", e)
            raise A2ATaskError(f"Cannot connect to A2A server: {e}") from e
        except httpx.HTTPStatusError as e:
            logger.error("HTTP error sending task: %s", e)
            raise A2ATaskError(f"HTTP error: {e.response.status_code}") from e
        except A2ATaskError:
            raise
        except Exception as e:
            logger.error("Unexpected error sending task: %s", e)
            raise A2ATaskError(f"Unexpected error: {e}") from e
        finally:
            await client.aclose()

    async def get_task_status(self, task_id: str) -> TaskInfo:
        """
        Get the status of a task.

        Args:
            task_id: The task ID to check.

        Returns:
            TaskInfo: Current task information.

        Raises:
            A2ATaskError: If status check fails.
        """
        logger.info("Getting status for task: %s", task_id)
        client = await self._get_client()

        try:
            response = await client.get(f"/api/tasks/{task_id}")
            response.raise_for_status()
            data = response.json()

            logger.debug("Task status response: %s", data)

            return TaskInfo(
                task_id=data.get("task_id", task_id),
                state=data.get("state", "unknown"),
                message=data.get("message"),
                poc_email=data.get("poc_email"),
                created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None,
                completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
                result=data.get("result"),
                error=data.get("error"),
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.warning("Task not found: %s", task_id)
                raise A2ATaskError(f"Task not found: {task_id}") from e
            logger.error("HTTP error getting task status: %s", e)
            raise A2ATaskError(f"HTTP error: {e.response.status_code}") from e
        except Exception as e:
            logger.error("Unexpected error getting task status: %s", e)
            raise A2ATaskError(f"Unexpected error: {e}") from e

    async def list_tasks(self) -> list[TaskInfo]:
        """
        List all tasks.

        Returns:
            List of TaskInfo objects.

        Raises:
            A2ATaskError: If listing fails.
        """
        logger.info("Listing all tasks")
        client = await self._get_client()

        try:
            response = await client.get("/api/tasks")
            response.raise_for_status()
            data = response.json()

            tasks = []
            for task_data in data.get("tasks", []):
                tasks.append(
                    TaskInfo(
                        task_id=task_data.get("task_id", ""),
                        state=task_data.get("state", "unknown"),
                        message=task_data.get("message"),
                        poc_email=task_data.get("poc_email"),
                        created_at=datetime.fromisoformat(task_data["created_at"]) if task_data.get("created_at") else None,
                        completed_at=datetime.fromisoformat(task_data["completed_at"]) if task_data.get("completed_at") else None,
                        result=task_data.get("result"),
                        error=task_data.get("error"),
                    )
                )

            logger.info("Found %d tasks", len(tasks))
            return tasks
        except httpx.HTTPStatusError as e:
            logger.error("HTTP error listing tasks: %s", e)
            raise A2ATaskError(f"HTTP error: {e.response.status_code}") from e
        except Exception as e:
            logger.error("Unexpected error listing tasks: %s", e)
            raise A2ATaskError(f"Unexpected error: {e}") from e

    async def check_health(self) -> bool:
        """
        Check if A2A server is healthy.

        Returns:
            True if healthy, False otherwise.
        """
        try:
            client = await self._get_client()
            response = await client.get("/.well-known/agent.json")
            return response.status_code == 200
        except Exception as e:
            logger.warning("A2A health check failed: %s", e)
            return False
