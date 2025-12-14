"""Webhook server for Mail Agent - receives email notifications from Mock SMTP."""

import asyncio
import logging
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class EmailWebhookPayload(BaseModel):
    """Webhook payload structure for email received event."""

    event: str = Field(description="Event type (always 'email.received')")
    email_id: str = Field(description="Email UUID")
    from_address: str = Field(description="Sender email address")
    to_addresses: list[str] = Field(description="Recipient email addresses")
    subject: str = Field(description="Email subject")
    has_attachments: bool = Field(description="Whether email has attachments")
    attachment_count: Optional[int] = Field(description="Number of attachments")
    received_at: str = Field(description="ISO timestamp when email was received")
    body_preview: Optional[str] = Field(description="First 100 chars of body text")


class WebhookServer:
    """FastAPI server for receiving email webhooks from Mock SMTP.

    This server:
    1. Listens on configured host:port
    2. Receives POST requests to /webhook/email-received
    3. Validates payload structure
    4. Stores in shared state (pending_webhooks list)
    5. Returns 200 OK immediately (fire-and-forget pattern)
    """

    def __init__(self, host: str, port: int, webhook_path: str = "/webhook/email-received"):
        """Initialize webhook server.

        Args:
            host: Host to bind to
            port: Port to bind to
            webhook_path: HTTP path for webhook endpoint
        """
        self.host = host
        self.port = port
        self.webhook_path = webhook_path
        self.app = FastAPI(title="Mail Agent Webhook Server")
        self._setup_routes()

        logger.info(f"Webhook server initialized: {host}:{port}{webhook_path}")

    def _setup_routes(self) -> None:
        """Set up FastAPI routes."""

        @self.app.post(self.webhook_path)
        async def receive_email_webhook(payload: EmailWebhookPayload) -> dict:
            """Receive email notification from Mock SMTP webhook.

            Args:
                payload: Email event payload

            Returns:
                dict: Acknowledgment response

            Raises:
                HTTPException: If payload validation fails
            """
            logger.info(
                f"Webhook received: event={payload.event}, from={payload.from_address}, "
                f"subject={payload.subject}"
            )

            # Validate event type
            if payload.event != "email.received":
                error_msg = f"Unexpected event type: {payload.event}"
                logger.error(f"receive_email_webhook: {error_msg}")
                raise HTTPException(status_code=400, detail=error_msg)

            try:
                # Store webhook in shared state (agent will poll this)
                # We access the shared state via app.state
                if not hasattr(self.app.state, "pending_webhooks"):
                    self.app.state.pending_webhooks = []

                webhook_dict = payload.model_dump()
                self.app.state.pending_webhooks.append(webhook_dict)

                logger.debug(
                    f"receive_email_webhook: Stored webhook, "
                    f"total pending={len(self.app.state.pending_webhooks)}"
                )

                return {
                    "status": "received",
                    "email_id": payload.email_id,
                    "message": "Webhook received and queued"
                }

            except Exception as e:
                error_msg = f"Error processing webhook: {str(e)}"
                logger.error(f"receive_email_webhook: {error_msg}")
                raise HTTPException(status_code=500, detail=error_msg)

        @self.app.get("/health")
        async def health_check() -> dict:
            """Health check endpoint.

            Returns:
                dict: Health status
            """
            return {
                "status": "healthy",
                "service": "mail-agent-webhook",
                "pending_webhooks": len(getattr(self.app.state, "pending_webhooks", []))
            }

    async def start(self) -> None:
        """Start webhook server in background.

        This is called by the agent graph to start the server.
        """
        logger.info(f"Starting webhook server on {self.host}:{self.port}")

        # Configure uvicorn
        import uvicorn

        config = uvicorn.Config(
            self.app,
            host=self.host,
            port=self.port,
            log_level="info",
            access_log=False,
        )

        self.server = uvicorn.Server(config)

        logger.info("Webhook server started")

        # Run server (blocking)
        await self.server.serve()

    async def stop(self) -> None:
        """Stop webhook server gracefully."""
        logger.info("Stopping webhook server")

        if hasattr(self, "server"):
            self.server.should_exit = True

        logger.info("Webhook server stopped")

    def get_pending_webhooks(self) -> list[dict]:
        """Get list of pending webhooks (for agent to poll).

        Returns:
            list[dict]: List of webhook payloads
        """
        return getattr(self.app.state, "pending_webhooks", [])

    def clear_pending_webhooks(self) -> None:
        """Clear pending webhooks list (after agent processes them)."""
        self.app.state.pending_webhooks = []
        logger.debug("Cleared pending webhooks")
