"""
Progress Route - SSE streaming endpoint for real-time task progress.

Provides GET /tasks/{task_id}/progress endpoint for clients to stream
progress events during task execution.
"""

import asyncio
import logging
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from mail_agent.a2a.progress_store import ProgressStore, ProgressEvent


logger = logging.getLogger(__name__)

# SSE keepalive interval in seconds
SSE_KEEPALIVE_INTERVAL = 15.0


def create_progress_router(progress_store: ProgressStore) -> APIRouter:
    """
    Create the progress router with dependency injection.

    Args:
        progress_store: ProgressStore instance for streaming progress events.

    Returns:
        Configured APIRouter with progress SSE endpoint.
    """
    router = APIRouter(prefix="/tasks", tags=["progress"])

    async def _generate_sse_stream(
        task_id: str,
        last_event_id: Optional[int],
        request: Request,
    ) -> AsyncGenerator[str, None]:
        """
        Generate SSE stream for task progress.

        Args:
            task_id: Task identifier.
            last_event_id: Last received event ID for reconnection.
            request: FastAPI request for disconnect detection.

        Yields:
            SSE formatted strings.
        """
        logger.info(
            f"SSE stream started for task_id={task_id}, "
            f"last_event_id={last_event_id}"
        )

        try:
            # Check if client is still connected
            async def check_disconnect() -> bool:
                return await request.is_disconnected()

            # Stream events from progress store
            event_generator = progress_store.subscribe(task_id, last_event_id)

            keepalive_counter = 0
            async for event in event_generator:
                # Check for client disconnect
                if await check_disconnect():
                    logger.info(f"Client disconnected for task_id={task_id}")
                    break

                # Yield event in SSE format
                sse_data = event.to_sse_format()
                logger.debug(
                    f"Sending SSE event: task_id={task_id}, "
                    f"event_id={event.event_id}, state={event.state.value}"
                )
                yield sse_data

                # Reset keepalive counter on each event
                keepalive_counter = 0

        except KeyError as e:
            # Task not found - send error event
            logger.warning(f"Task not found for SSE stream: task_id={task_id}")
            error_msg = f"Task {task_id} not found"
            yield f"event: error\ndata: {{\"error\": \"{error_msg}\"}}\n\n"

        except asyncio.CancelledError:
            logger.info(f"SSE stream cancelled for task_id={task_id}")
            raise

        except Exception as e:
            logger.error(
                f"Error in SSE stream for task_id={task_id}: {e}",
                exc_info=True,
            )
            yield f"event: error\ndata: {{\"error\": \"Internal server error\"}}\n\n"

        finally:
            logger.info(f"SSE stream ended for task_id={task_id}")

    async def _sse_stream_with_keepalive(
        task_id: str,
        last_event_id: Optional[int],
        request: Request,
    ) -> AsyncGenerator[str, None]:
        """
        Wrap SSE stream with keepalive pings.

        Args:
            task_id: Task identifier.
            last_event_id: Last received event ID for reconnection.
            request: FastAPI request for disconnect detection.

        Yields:
            SSE formatted strings including keepalive pings.
        """
        event_generator = _generate_sse_stream(task_id, last_event_id, request)
        keepalive_interval = SSE_KEEPALIVE_INTERVAL

        try:
            while True:
                # Check for client disconnect
                if await request.is_disconnected():
                    logger.info(f"Client disconnected for task_id={task_id}")
                    break

                try:
                    # Try to get next event with timeout
                    event_task = asyncio.create_task(
                        event_generator.__anext__()
                    )

                    try:
                        sse_data = await asyncio.wait_for(
                            event_task, timeout=keepalive_interval
                        )
                        yield sse_data
                    except asyncio.TimeoutError:
                        # Send keepalive ping
                        logger.debug(f"Sending keepalive for task_id={task_id}")
                        yield ": keepalive\n\n"

                except StopAsyncIteration:
                    # Generator exhausted
                    logger.debug(f"Event generator exhausted for task_id={task_id}")
                    break

        except asyncio.CancelledError:
            logger.info(f"SSE stream with keepalive cancelled for task_id={task_id}")
            raise

        finally:
            await event_generator.aclose()

    @router.get(
        "/{task_id}/progress",
        summary="Stream task progress",
        description=(
            "Server-Sent Events endpoint for real-time task progress. "
            "Streams progress events as the agent executes, including node "
            "transitions and status updates. Supports reconnection via "
            "Last-Event-Id header."
        ),
        responses={
            200: {
                "description": "SSE stream of progress events",
                "content": {
                    "text/event-stream": {
                        "example": (
                            "id: 1\n"
                            "event: progress\n"
                            "data: {\"task_id\":\"abc\",\"state\":\"working\","
                            "\"node\":\"compose_email\",\"message\":\"Composing...\"}\n\n"
                        )
                    }
                },
            },
            404: {"description": "Task not found"},
        },
    )
    async def stream_task_progress(
        task_id: str,
        request: Request,
    ) -> StreamingResponse:
        """
        Stream task progress via Server-Sent Events.

        Connect to this endpoint to receive real-time progress updates
        as the agent executes. Events include:
        - progress: Node execution updates
        - suspended: Task waiting for POC reply
        - complete: Task finished successfully
        - error: Task failed

        Supports reconnection:
        - Include Last-Event-Id header with the last received event ID
        - Server will replay missed events before streaming live events

        Args:
            task_id: The unique task identifier.
            request: FastAPI request object.

        Returns:
            StreamingResponse with text/event-stream content type.
        """
        logger.info(f"SSE connection requested for task_id={task_id}")

        # Check if task exists
        if not progress_store.has_task(task_id):
            logger.warning(
                f"SSE requested for non-existent task_id={task_id}, "
                "creating placeholder"
            )
            # Don't error - task may not have started yet
            # Client will receive events when they arrive

        # Parse Last-Event-Id header for reconnection
        last_event_id: Optional[int] = None
        last_event_id_header = request.headers.get("Last-Event-Id")
        if last_event_id_header:
            try:
                last_event_id = int(last_event_id_header)
                logger.info(
                    f"SSE reconnection for task_id={task_id}, "
                    f"last_event_id={last_event_id}"
                )
            except ValueError:
                logger.warning(
                    f"Invalid Last-Event-Id header: {last_event_id_header}"
                )

        return StreamingResponse(
            _sse_stream_with_keepalive(task_id, last_event_id, request),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # Disable nginx buffering
            },
        )

    @router.get(
        "/{task_id}/progress/events",
        summary="Get progress event history",
        description="Get all progress events for a task (non-streaming).",
        responses={
            200: {"description": "List of progress events"},
            404: {"description": "Task not found"},
        },
    )
    async def get_progress_events(
        task_id: str,
        since_event_id: Optional[int] = None,
    ) -> dict:
        """
        Get progress event history for a task.

        Use this endpoint for initial load or when SSE is not available.
        Events are returned in chronological order.

        Args:
            task_id: The unique task identifier.
            since_event_id: Return events after this ID (for pagination).

        Returns:
            Dictionary with events list and metadata.

        Raises:
            HTTPException 404: If task not found.
        """
        logger.info(
            f"GET progress events for task_id={task_id}, "
            f"since_event_id={since_event_id}"
        )

        if not progress_store.has_task(task_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "Task not found", "task_id": task_id},
            )

        try:
            events = progress_store.get_events(task_id, since_event_id)

            events_list = [
                {
                    "event_id": event.event_id,
                    "task_id": event.task_id,
                    "state": event.state.value,
                    "node": event.node,
                    "message": event.message,
                    "timestamp": event.timestamp.isoformat(),
                    "poc_email": event.poc_email,
                    "result": event.result,
                    "error": event.error,
                }
                for event in events
            ]

            is_terminal = progress_store.is_terminal(task_id)

            logger.info(
                f"Returning {len(events_list)} events for task_id={task_id}, "
                f"is_terminal={is_terminal}"
            )

            return {
                "task_id": task_id,
                "events": events_list,
                "is_terminal": is_terminal,
                "event_count": len(events_list),
            }

        except KeyError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "Task not found", "task_id": task_id},
            )

    return router
