"""SMTP server using aiosmtpd."""

import asyncio
import logging

from aiosmtpd.controller import Controller

from mock_smtp.smtp.handler import SMTPHandler
from mock_smtp.store.inbox_store import InboxStore
from mock_smtp.webhooks.dispatcher import WebhookDispatcher
from mock_smtp.webhooks.registry import WebhookRegistry

logger = logging.getLogger(__name__)


class SMTPServer:
    """
    SMTP server wrapper using aiosmtpd Controller.

    Manages the lifecycle of the SMTP server.
    """

    def __init__(
        self,
        host: str,
        port: int,
        inbox_store: InboxStore,
        webhook_registry: WebhookRegistry,
        webhook_dispatcher: WebhookDispatcher,
        max_attachment_size: int
    ):
        """
        Initialize the SMTP server.

        Args:
            host: Bind address
            port: Port to listen on
            inbox_store: InboxStore instance
            webhook_registry: WebhookRegistry instance
            webhook_dispatcher: WebhookDispatcher instance
            max_attachment_size: Maximum attachment size in bytes
        """
        self.host = host
        self.port = port
        self.inbox_store = inbox_store
        self.webhook_registry = webhook_registry
        self.webhook_dispatcher = webhook_dispatcher
        self.max_attachment_size = max_attachment_size

        # Create handler
        self.handler = SMTPHandler(
            inbox_store=inbox_store,
            webhook_registry=webhook_registry,
            webhook_dispatcher=webhook_dispatcher,
            max_attachment_size=max_attachment_size
        )

        # Create controller (will be started later)
        self.controller = Controller(
            handler=self.handler,
            hostname=host,
            port=port,
            ready_timeout=5.0
        )

        logger.info(
            f"SMTPServer initialized on {host}:{port} "
            f"(max_attachment_size={max_attachment_size} bytes)"
        )

    async def start(self):
        """Start the SMTP server."""
        try:
            logger.info(f"Starting SMTP server on {self.host}:{self.port}...")
            self.controller.start()
            logger.info(
                f"SMTP server started successfully on "
                f"{self.host}:{self.port}"
            )
        except Exception as e:
            logger.error(
                f"Failed to start SMTP server: {type(e).__name__}: {e}",
                exc_info=True
            )
            raise

    async def stop(self):
        """Stop the SMTP server."""
        try:
            logger.info("Stopping SMTP server...")
            self.controller.stop()
            logger.info("SMTP server stopped successfully")
        except Exception as e:
            logger.error(
                f"Error stopping SMTP server: {type(e).__name__}: {e}",
                exc_info=True
            )
            raise

    async def run_forever(self):
        """
        Run the SMTP server indefinitely.

        This method blocks until the server is stopped.
        """
        await self.start()

        try:
            # Keep running
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            logger.info("SMTP server task cancelled")
            await self.stop()
        except KeyboardInterrupt:
            logger.info("SMTP server interrupted")
            await self.stop()
