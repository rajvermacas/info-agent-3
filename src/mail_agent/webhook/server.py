"""
Webhook Server - FastAPI server for receiving email notifications.

Runs embedded within the agent process and notifies via asyncio.Queue.
Supports TaskRouter integration for A2A concurrent request routing.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID

import uvicorn
from fastapi import FastAPI, Request, Response
from pydantic import BaseModel, Field

from mail_agent.config import Settings, get_settings

if TYPE_CHECKING:
    from mail_agent.webhook.router import TaskRouter


logger = logging.getLogger(__name__)


# ============================================================================
# Data Models
# ============================================================================


class WebhookPayload(BaseModel):
    """
    Webhook payload received from mock SMTP server.

    Matches the payload format sent by the mock SMTP server's webhook dispatcher.
    """

    model_config = {"populate_by_name": True}

    event: str = Field(description="Event type (e.g., 'email.received')")
    email_id: str = Field(description="UUID of the received email")
    from_address: str = Field(alias="from", description="Sender email address")
    to: list[str] = Field(description="List of recipient email addresses")
    subject: str = Field(description="Email subject")
    has_attachments: bool = Field(description="Whether email has attachments")
    attachment_count: int = Field(description="Number of attachments")
    received_at: str = Field(description="ISO timestamp of when email was received")
    body_preview: str = Field(default="", description="Preview of email body")


@dataclass
class WebhookEvent:
    """
    Internal representation of a webhook event for the agent.
    """

    email_id: UUID
    from_address: str
    to_addresses: list[str]
    subject: str
    has_attachments: bool
    attachment_count: int
    received_at: datetime
    body_preview: str

    @classmethod
    def from_payload(cls, payload: WebhookPayload) -> "WebhookEvent":
        """Create WebhookEvent from webhook payload."""
        return cls(
            email_id=UUID(payload.email_id),
            from_address=payload.from_address,
            to_addresses=payload.to,
            subject=payload.subject,
            has_attachments=payload.has_attachments,
            attachment_count=payload.attachment_count,
            received_at=datetime.fromisoformat(payload.received_at.replace("Z", "+00:00")),
            body_preview=payload.body_preview,
        )


# ============================================================================
# Webhook Server
# ============================================================================


class WebhookServer:
    """
    Embedded FastAPI server for receiving webhook notifications.

    The server runs in the background and puts received events on an asyncio.Queue
    for the agent to process. Optionally integrates with TaskRouter for A2A mode
    to route events to specific task queues.
    """

    def __init__(
        self,
        settings: Optional[Settings] = None,
        event_queue: Optional[asyncio.Queue] = None,
        task_router: Optional["TaskRouter"] = None,
    ) -> None:
        """
        Initialize webhook server.

        Args:
            settings: Configuration settings. Uses get_settings() if not provided.
            event_queue: Queue for received events. Creates new queue if not provided.
            task_router: Optional TaskRouter for A2A mode event routing.
        """
        self._settings = settings or get_settings()
        self._event_queue: asyncio.Queue[WebhookEvent] = event_queue or asyncio.Queue()
        self._task_router: Optional["TaskRouter"] = task_router
        self._server: Optional[uvicorn.Server] = None
        self._server_task: Optional[asyncio.Task] = None
        self._app: Optional[FastAPI] = None

        logger.info(
            f"WebhookServer initialized: host={self._settings.webhook_host}, "
            f"port={self._settings.webhook_port}, path={self._settings.webhook_path}, "
            f"task_router={'enabled' if task_router else 'disabled'}"
        )

    @property
    def event_queue(self) -> asyncio.Queue[WebhookEvent]:
        """Get the event queue for receiving webhook events."""
        return self._event_queue

    @property
    def task_router(self) -> Optional["TaskRouter"]:
        """Get the TaskRouter instance if configured."""
        return self._task_router

    def set_task_router(self, task_router: "TaskRouter") -> None:
        """
        Set or update the TaskRouter instance.

        Args:
            task_router: TaskRouter instance for A2A event routing.
        """
        self._task_router = task_router
        logger.info("TaskRouter set for WebhookServer")

    def _create_app(self) -> FastAPI:
        """Create FastAPI application with webhook endpoint."""

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            logger.info("Webhook server starting up")
            yield
            logger.info("Webhook server shutting down")

        app = FastAPI(
            title="Mail Agent Webhook Receiver",
            description="Receives webhook notifications from mock SMTP server",
            version="0.1.0",
            lifespan=lifespan,
        )

        @app.post(self._settings.webhook_path)
        async def receive_webhook(request: Request) -> dict[str, str]:
            """
            Receive webhook notification from mock SMTP server.

            Expected headers:
            - X-Webhook-Event: email.received
            - X-Email-ID: <uuid>
            - X-Webhook-Timestamp: <iso_timestamp>

            When TaskRouter is configured (A2A mode), routes events to task-specific
            queues based on sender email. Otherwise, uses the default event queue.
            """
            try:
                # Log incoming request
                event_type = request.headers.get("X-Webhook-Event", "unknown")
                email_id = request.headers.get("X-Email-ID", "unknown")
                logger.info(
                    f"Webhook received: event={event_type}, email_id={email_id}"
                )

                # Parse payload
                body = await request.json()
                logger.debug(f"Webhook payload: {body}")

                payload = WebhookPayload(**body)
                event = WebhookEvent.from_payload(payload)

                # Route through TaskRouter if available (A2A mode)
                if self._task_router is not None:
                    # Build payload dict for TaskRouter
                    router_payload = {
                        "event": payload.event,
                        "email_id": payload.email_id,
                        "from": payload.from_address,
                        "to": payload.to,
                        "subject": payload.subject,
                        "has_attachments": payload.has_attachments,
                        "attachment_count": payload.attachment_count,
                        "received_at": payload.received_at,
                        "body_preview": payload.body_preview,
                    }
                    routed = await self._task_router.route_event(router_payload)
                    if routed:
                        logger.info(
                            f"Webhook event routed via TaskRouter: email_id={event.email_id}, "
                            f"from={event.from_address}"
                        )
                    else:
                        # No task registered for this sender, fall back to default queue
                        logger.info(
                            f"No task registered for sender {event.from_address}, "
                            "falling back to default queue"
                        )
                        await self._event_queue.put(event)
                else:
                    # CLI mode: use default queue
                    await self._event_queue.put(event)
                    logger.info(
                        f"Webhook event queued: email_id={event.email_id}, "
                        f"from={event.from_address}, subject={event.subject}"
                    )

                return {"status": "received"}

            except Exception as e:
                logger.error(f"Failed to process webhook: {e}")
                # Still return 200 to prevent retries
                return {"status": "error", "message": str(e)}

        @app.get("/health")
        async def health_check() -> dict[str, Any]:
            """Health check endpoint."""
            return {
                "status": "healthy",
                "queue_size": self._event_queue.qsize(),
            }

        return app

    async def start(self) -> None:
        """
        Start the webhook server in the background.

        The server runs in an asyncio task and can be stopped with stop().
        """
        if self._server_task is not None:
            logger.warning("Webhook server is already running")
            return

        self._app = self._create_app()

        config = uvicorn.Config(
            app=self._app,
            host=self._settings.webhook_host,
            port=self._settings.webhook_port,
            log_level="warning",  # Reduce uvicorn logging noise
        )
        self._server = uvicorn.Server(config)

        async def run_server():
            try:
                await self._server.serve()
            except asyncio.CancelledError:
                logger.info("Webhook server task cancelled")
            except Exception as e:
                logger.error(f"Webhook server error: {e}")

        self._server_task = asyncio.create_task(run_server())
        logger.info(
            f"Webhook server started on "
            f"http://{self._settings.webhook_host}:{self._settings.webhook_port}"
        )

        # Give the server a moment to start
        await asyncio.sleep(0.5)

    async def stop(self) -> None:
        """Stop the webhook server gracefully."""
        if self._server is None:
            logger.warning("Webhook server is not running")
            return

        logger.info("Stopping webhook server")
        self._server.should_exit = True

        if self._server_task is not None:
            try:
                await asyncio.wait_for(self._server_task, timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("Webhook server shutdown timeout, cancelling task")
                self._server_task.cancel()
                try:
                    await self._server_task
                except asyncio.CancelledError:
                    pass

        self._server = None
        self._server_task = None
        logger.info("Webhook server stopped")

    async def wait_for_event(
        self,
        timeout: Optional[float] = None,
    ) -> Optional[WebhookEvent]:
        """
        Wait for a webhook event.

        Args:
            timeout: Maximum time to wait in seconds. None for indefinite.

        Returns:
            WebhookEvent if received, None if timeout.
        """
        try:
            if timeout is not None:
                event = await asyncio.wait_for(
                    self._event_queue.get(),
                    timeout=timeout,
                )
            else:
                event = await self._event_queue.get()

            self._event_queue.task_done()
            return event

        except asyncio.TimeoutError:
            logger.debug(f"Webhook wait timed out after {timeout}s")
            return None

    def has_pending_events(self) -> bool:
        """Check if there are pending events in the queue."""
        return not self._event_queue.empty()

    @property
    def is_running(self) -> bool:
        """Check if the server is running."""
        return self._server_task is not None and not self._server_task.done()
