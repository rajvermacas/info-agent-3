"""
SSE Routes - Server-Sent Events proxy for task progress streaming.

Proxies SSE connections from the browser to the A2A server,
providing real-time task progress updates to the UI.
"""

import asyncio
import json
import logging
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from ui.services.sse_client import (
    SSEClientService,
    SSEConnectionError,
    ProgressEvent,
    ProgressState,
)
from ui.config import Settings

logger = logging.getLogger(__name__)


def create_sse_router(settings: Settings, sse_client: SSEClientService) -> APIRouter:
    """
    Create the SSE router with dependency injection.

    Args:
        settings: UI settings.
        sse_client: SSE client service for A2A communication.

    Returns:
        Configured APIRouter with SSE endpoints.
    """
    router = APIRouter(prefix="/api/sse", tags=["sse"])

    async def _generate_sse_proxy_stream(
        task_id: str,
        last_event_id: Optional[int],
        request: Request,
    ) -> AsyncGenerator[str, None]:
        """
        Generate SSE stream that proxies events from A2A server.

        Args:
            task_id: Task identifier.
            last_event_id: Last received event ID for reconnection.
            request: FastAPI request for disconnect detection.

        Yields:
            SSE formatted strings.
        """
        logger.info(
            f"Starting SSE proxy stream: task_id={task_id}, "
            f"last_event_id={last_event_id}"
        )

        try:
            # Stream events from A2A server with reconnection
            async for event in sse_client.stream_with_reconnection(
                task_id=task_id,
                max_retries=5,
                initial_delay=1.0,
                max_delay=30.0,
            ):
                # Check for client disconnect
                if await request.is_disconnected():
                    logger.info(f"Client disconnected: task_id={task_id}")
                    break

                # Format as SSE
                sse_data = _format_progress_event_sse(event)
                yield sse_data

                # Stop on terminal state
                if event.is_terminal:
                    logger.info(
                        f"Terminal state reached: task_id={task_id}, "
                        f"state={event.state.value}"
                    )
                    break

        except SSEConnectionError as e:
            logger.error(f"SSE proxy connection error: task_id={task_id}, error={e}")
            # Send error event to client
            error_event = {
                "task_id": task_id,
                "state": "failed",
                "message": f"Connection error: {e}",
                "error": str(e),
            }
            yield f"event: error\ndata: {json.dumps(error_event)}\n\n"

        except asyncio.CancelledError:
            logger.info(f"SSE proxy stream cancelled: task_id={task_id}")
            raise

        except Exception as e:
            logger.error(
                f"SSE proxy stream error: task_id={task_id}, error={e}",
                exc_info=True,
            )
            error_event = {
                "task_id": task_id,
                "state": "failed",
                "message": "Internal server error",
                "error": str(e),
            }
            yield f"event: error\ndata: {json.dumps(error_event)}\n\n"

        finally:
            logger.info(f"SSE proxy stream ended: task_id={task_id}")

    def _format_progress_event_sse(event: ProgressEvent) -> str:
        """
        Format a ProgressEvent as SSE string.

        Args:
            event: Progress event to format.

        Returns:
            SSE formatted string.
        """
        # Determine event type
        if event.state == ProgressState.COMPLETED:
            event_type = "complete"
        elif event.state == ProgressState.FAILED:
            event_type = "error"
        elif event.state == ProgressState.SUSPENDED:
            event_type = "suspended"
        else:
            event_type = "progress"

        # Build data payload
        data = {
            "task_id": event.task_id,
            "state": event.state.value,
            "message": event.message,
        }

        if event.node:
            data["node"] = event.node
        if event.timestamp:
            data["timestamp"] = event.timestamp.isoformat()
        if event.poc_email:
            data["poc_email"] = event.poc_email
        if event.result:
            data["result"] = event.result
        if event.error:
            data["error"] = event.error

        # Format SSE
        lines = []
        if event.event_id is not None:
            lines.append(f"id: {event.event_id}")
        lines.append(f"event: {event_type}")
        lines.append(f"data: {json.dumps(data)}")
        lines.append("")
        lines.append("")

        return "\n".join(lines)

    @router.get(
        "/task/{task_id}/progress",
        summary="Stream task progress",
        description=(
            "Proxy SSE endpoint for real-time task progress. "
            "Streams events from the A2A server with automatic reconnection."
        ),
    )
    async def stream_task_progress(
        task_id: str,
        request: Request,
    ) -> StreamingResponse:
        """
        Stream task progress via Server-Sent Events.

        Proxies SSE events from the A2A server to the browser.
        Supports reconnection via Last-Event-Id header.

        Args:
            task_id: The unique task identifier.
            request: FastAPI request object.

        Returns:
            StreamingResponse with text/event-stream content type.
        """
        logger.info(f"SSE proxy request: task_id={task_id}")

        # Parse Last-Event-Id header for reconnection
        last_event_id: Optional[int] = None
        last_event_id_header = request.headers.get("Last-Event-Id")
        if last_event_id_header:
            try:
                last_event_id = int(last_event_id_header)
                logger.info(
                    f"SSE reconnection: task_id={task_id}, "
                    f"last_event_id={last_event_id}"
                )
            except ValueError:
                logger.warning(
                    f"Invalid Last-Event-Id header: {last_event_id_header}"
                )

        return StreamingResponse(
            _generate_sse_proxy_stream(task_id, last_event_id, request),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # Disable nginx buffering
            },
        )

    @router.get(
        "/task/{task_id}/events",
        summary="Get progress event history",
        description="Get all progress events for a task (non-streaming).",
    )
    async def get_progress_events(
        task_id: str,
        since_event_id: Optional[int] = None,
    ) -> dict:
        """
        Get progress event history for a task.

        Fetches events from the A2A server REST endpoint.

        Args:
            task_id: The unique task identifier.
            since_event_id: Return events after this ID.

        Returns:
            Dictionary with events list and metadata.
        """
        logger.info(
            f"Fetching progress events: task_id={task_id}, "
            f"since_event_id={since_event_id}"
        )

        try:
            events = await sse_client.get_progress_events(task_id, since_event_id)

            events_list = [
                {
                    "event_id": e.event_id,
                    "task_id": e.task_id,
                    "state": e.state.value,
                    "node": e.node,
                    "message": e.message,
                    "timestamp": e.timestamp.isoformat() if e.timestamp else None,
                    "poc_email": e.poc_email,
                    "result": e.result,
                    "error": e.error,
                }
                for e in events
            ]

            # Determine if task is terminal
            is_terminal = any(e.is_terminal for e in events)

            return {
                "task_id": task_id,
                "events": events_list,
                "is_terminal": is_terminal,
                "event_count": len(events_list),
            }

        except SSEConnectionError as e:
            logger.error(f"Failed to fetch events: task_id={task_id}, error={e}")
            return {
                "task_id": task_id,
                "events": [],
                "is_terminal": False,
                "event_count": 0,
                "error": str(e),
            }

    return router
