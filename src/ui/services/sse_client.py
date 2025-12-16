"""
SSE Client Service for UI.

Handles Server-Sent Events streaming from the A2A server for real-time
task progress updates.
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, AsyncGenerator, Optional

import httpx

from ui.config import Settings

logger = logging.getLogger(__name__)


class SSEConnectionError(Exception):
    """Raised when SSE connection fails."""

    pass


class SSEParseError(Exception):
    """Raised when SSE event parsing fails."""

    pass


class ProgressState(str, Enum):
    """Task progress state enumeration."""

    CREATED = "created"
    WORKING = "working"
    SUSPENDED = "suspended"
    RESUMED = "resumed"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ProgressEvent:
    """Progress event from SSE stream."""

    task_id: str
    state: ProgressState
    message: str
    node: Optional[str] = None
    timestamp: Optional[datetime] = None
    poc_email: Optional[str] = None
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    event_id: Optional[int] = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProgressEvent":
        """
        Create ProgressEvent from dictionary.

        Args:
            data: Dictionary with event data.

        Returns:
            ProgressEvent instance.

        Raises:
            ValueError: If required fields are missing.
        """
        if "task_id" not in data:
            raise ValueError("ProgressEvent requires task_id")
        if "state" not in data:
            raise ValueError("ProgressEvent requires state")
        if "message" not in data:
            raise ValueError("ProgressEvent requires message")

        timestamp = None
        if "timestamp" in data and data["timestamp"]:
            try:
                timestamp = datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00"))
            except (ValueError, AttributeError) as e:
                logger.warning(f"Failed to parse timestamp: {data['timestamp']}, error: {e}")

        try:
            state = ProgressState(data["state"])
        except ValueError:
            logger.warning(f"Unknown progress state: {data['state']}, defaulting to WORKING")
            state = ProgressState.WORKING

        return cls(
            task_id=data["task_id"],
            state=state,
            message=data["message"],
            node=data.get("node"),
            timestamp=timestamp,
            poc_email=data.get("poc_email"),
            result=data.get("result"),
            error=data.get("error"),
            event_id=data.get("event_id"),
        )

    @property
    def is_terminal(self) -> bool:
        """Check if this is a terminal state."""
        return self.state in (ProgressState.COMPLETED, ProgressState.FAILED)


class SSEClientService:
    """
    SSE client service for streaming task progress from A2A server.

    Handles:
    - SSE connection establishment
    - Event parsing and validation
    - Automatic reconnection with exponential backoff
    - Connection error handling
    """

    def __init__(self, settings: Settings) -> None:
        """
        Initialize the SSE client service.

        Args:
            settings: UI settings containing A2A server URL.
        """
        self._settings = settings
        self._base_url = settings.a2a_server_url.rstrip("/")
        logger.info(f"SSEClientService initialized with base URL: {self._base_url}")

    async def stream_task_progress(
        self,
        task_id: str,
        last_event_id: Optional[int] = None,
    ) -> AsyncGenerator[ProgressEvent, None]:
        """
        Stream progress events for a task.

        Opens an SSE connection to the A2A server and yields progress events
        as they arrive. The stream closes when a terminal state is reached
        or the connection is lost.

        Args:
            task_id: Task identifier to stream progress for.
            last_event_id: Last received event ID for reconnection.

        Yields:
            ProgressEvent instances as they arrive.

        Raises:
            SSEConnectionError: If connection fails.
        """
        url = f"{self._base_url}/api/tasks/{task_id}/progress"
        headers = {
            "Accept": "text/event-stream",
            "Cache-Control": "no-cache",
        }
        if last_event_id is not None:
            headers["Last-Event-Id"] = str(last_event_id)

        logger.info(
            f"Opening SSE connection: task_id={task_id}, "
            f"last_event_id={last_event_id}, url={url}"
        )

        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream("GET", url, headers=headers) as response:
                    if response.status_code != 200:
                        error_body = await response.aread()
                        logger.error(
                            f"SSE connection failed: status={response.status_code}, "
                            f"body={error_body.decode()}"
                        )
                        raise SSEConnectionError(
                            f"SSE connection failed with status {response.status_code}"
                        )

                    logger.info(f"SSE connection established: task_id={task_id}")

                    # Parse SSE stream
                    async for event in self._parse_sse_stream(response):
                        yield event

                        # Stop on terminal state
                        if event.is_terminal:
                            logger.info(
                                f"Terminal state reached: task_id={task_id}, "
                                f"state={event.state.value}"
                            )
                            return

        except httpx.ConnectError as e:
            logger.error(f"SSE connection error: task_id={task_id}, error={e}")
            raise SSEConnectionError(f"Failed to connect to A2A server: {e}") from e

        except httpx.ReadTimeout as e:
            logger.warning(f"SSE read timeout: task_id={task_id}, error={e}")
            raise SSEConnectionError(f"SSE connection timed out: {e}") from e

        except Exception as e:
            logger.error(f"SSE stream error: task_id={task_id}, error={e}", exc_info=True)
            raise SSEConnectionError(f"SSE stream error: {e}") from e

        finally:
            logger.info(f"SSE connection closed: task_id={task_id}")

    async def _parse_sse_stream(
        self, response: httpx.Response
    ) -> AsyncGenerator[ProgressEvent, None]:
        """
        Parse SSE events from HTTP response stream.

        SSE format:
        ```
        id: 1
        event: progress
        data: {"task_id": "...", ...}

        ```

        Args:
            response: HTTP response with SSE stream.

        Yields:
            Parsed ProgressEvent instances.
        """
        current_event: dict[str, str] = {}

        async for line in response.aiter_lines():
            line = line.strip()

            # Empty line marks end of event
            if not line:
                if current_event:
                    event = self._process_sse_event(current_event)
                    if event:
                        yield event
                    current_event = {}
                continue

            # Skip comments (keepalive pings)
            if line.startswith(":"):
                logger.debug(f"SSE keepalive received: {line}")
                continue

            # Parse field: value
            if ":" in line:
                field, _, value = line.partition(":")
                value = value.lstrip()  # Remove leading space
                current_event[field] = value
            else:
                # Field with no value
                current_event[line] = ""

    def _process_sse_event(self, event_data: dict[str, str]) -> Optional[ProgressEvent]:
        """
        Process parsed SSE event fields into ProgressEvent.

        Args:
            event_data: Dictionary with SSE fields (id, event, data).

        Returns:
            ProgressEvent or None if parsing fails.
        """
        data_str = event_data.get("data", "")
        if not data_str:
            logger.debug(f"SSE event without data: {event_data}")
            return None

        event_type = event_data.get("event", "message")
        event_id_str = event_data.get("id")

        # Skip error events (handled separately)
        if event_type == "error":
            logger.warning(f"SSE error event: {data_str}")
            # Try to parse as error
            try:
                error_data = json.loads(data_str)
                return ProgressEvent(
                    task_id="unknown",
                    state=ProgressState.FAILED,
                    message=error_data.get("error", "Unknown error"),
                    error=error_data.get("error"),
                )
            except json.JSONDecodeError:
                return ProgressEvent(
                    task_id="unknown",
                    state=ProgressState.FAILED,
                    message=data_str,
                    error=data_str,
                )

        try:
            data = json.loads(data_str)

            # Add event_id if present
            if event_id_str:
                try:
                    data["event_id"] = int(event_id_str)
                except ValueError:
                    pass

            event = ProgressEvent.from_dict(data)
            logger.debug(
                f"Parsed SSE event: task_id={event.task_id}, "
                f"state={event.state.value}, node={event.node}"
            )
            return event

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse SSE data as JSON: {data_str}, error={e}")
            return None

        except ValueError as e:
            logger.warning(f"Failed to create ProgressEvent: {data_str}, error={e}")
            return None

    async def stream_with_reconnection(
        self,
        task_id: str,
        max_retries: int = 5,
        initial_delay: float = 1.0,
        max_delay: float = 30.0,
    ) -> AsyncGenerator[ProgressEvent, None]:
        """
        Stream progress events with automatic reconnection.

        On connection failure, retries with exponential backoff.
        Resumes from last received event ID.

        Args:
            task_id: Task identifier to stream progress for.
            max_retries: Maximum number of reconnection attempts.
            initial_delay: Initial delay between retries (seconds).
            max_delay: Maximum delay between retries (seconds).

        Yields:
            ProgressEvent instances as they arrive.

        Raises:
            SSEConnectionError: If all retries are exhausted.
        """
        last_event_id: Optional[int] = None
        retry_count = 0
        delay = initial_delay

        while True:
            try:
                async for event in self.stream_task_progress(task_id, last_event_id):
                    # Update last event ID for reconnection
                    if event.event_id is not None:
                        last_event_id = event.event_id

                    # Reset retry count on successful event
                    retry_count = 0
                    delay = initial_delay

                    yield event

                    # Stop on terminal state
                    if event.is_terminal:
                        return

                # Stream ended normally (shouldn't happen before terminal state)
                logger.warning(f"SSE stream ended without terminal state: task_id={task_id}")
                return

            except SSEConnectionError as e:
                retry_count += 1
                if retry_count > max_retries:
                    logger.error(
                        f"SSE max retries exceeded: task_id={task_id}, "
                        f"retries={retry_count}"
                    )
                    raise

                logger.warning(
                    f"SSE connection lost, reconnecting: task_id={task_id}, "
                    f"retry={retry_count}/{max_retries}, delay={delay}s, error={e}"
                )

                await asyncio.sleep(delay)

                # Exponential backoff
                delay = min(delay * 2, max_delay)

    async def get_progress_events(
        self, task_id: str, since_event_id: Optional[int] = None
    ) -> list[ProgressEvent]:
        """
        Get progress events for a task (non-streaming).

        Fetches all events from the REST endpoint instead of SSE.

        Args:
            task_id: Task identifier.
            since_event_id: Return events after this ID.

        Returns:
            List of ProgressEvent instances.

        Raises:
            SSEConnectionError: If request fails.
        """
        url = f"{self._base_url}/api/tasks/{task_id}/progress/events"
        params = {}
        if since_event_id is not None:
            params["since_event_id"] = since_event_id

        logger.info(f"Fetching progress events: task_id={task_id}, since={since_event_id}")

        try:
            async with httpx.AsyncClient(
                timeout=self._settings.http_timeout_seconds
            ) as client:
                response = await client.get(url, params=params)

                if response.status_code == 404:
                    logger.warning(f"Task not found: task_id={task_id}")
                    return []

                if response.status_code != 200:
                    logger.error(
                        f"Failed to fetch progress events: "
                        f"status={response.status_code}, body={response.text}"
                    )
                    raise SSEConnectionError(
                        f"Failed to fetch progress events: {response.status_code}"
                    )

                data = response.json()
                events_data = data.get("events", [])

                events = []
                for event_data in events_data:
                    try:
                        events.append(ProgressEvent.from_dict(event_data))
                    except ValueError as e:
                        logger.warning(f"Failed to parse event: {event_data}, error={e}")

                logger.info(
                    f"Fetched {len(events)} progress events: task_id={task_id}"
                )
                return events

        except httpx.RequestError as e:
            logger.error(f"Failed to fetch progress events: {e}")
            raise SSEConnectionError(f"Failed to fetch progress events: {e}") from e
