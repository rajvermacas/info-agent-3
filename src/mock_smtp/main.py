"""Main entrypoint for Mock SMTP Server."""

import asyncio
import logging
import signal
import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from mock_smtp.api.router import create_api_router
from mock_smtp.config import get_settings
from mock_smtp.smtp.server import SMTPServer
from mock_smtp.store.inbox_store import InboxStore
from mock_smtp.webhooks.dispatcher import WebhookDispatcher
from mock_smtp.webhooks.registry import WebhookRegistry

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

# Global instances (shared between SMTP and API)
inbox_store: InboxStore = None
webhook_registry: WebhookRegistry = None
webhook_dispatcher: WebhookDispatcher = None
smtp_server: SMTPServer = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan context manager.

    Manages startup and shutdown of all services.
    """
    global inbox_store, webhook_registry, webhook_dispatcher, smtp_server

    settings = get_settings()

    # Update logging level from settings
    logging.getLogger().setLevel(settings.log_level)
    logger.info(
        f"Starting {settings.app_name} v{settings.app_version}"
    )

    # Initialize shared resources
    logger.info("Initializing shared resources...")
    inbox_store = InboxStore(
        max_emails_per_inbox=settings.max_emails_per_inbox
    )
    webhook_registry = WebhookRegistry()
    webhook_dispatcher = WebhookDispatcher(
        timeout_seconds=settings.webhook_timeout_seconds,
        max_retries=settings.webhook_max_retries
    )

    # Start webhook dispatcher
    await webhook_dispatcher.start()

    # Start SMTP server
    smtp_server = SMTPServer(
        host=settings.smtp_host,
        port=settings.smtp_port,
        inbox_store=inbox_store,
        webhook_registry=webhook_registry,
        webhook_dispatcher=webhook_dispatcher,
        max_attachment_size=settings.max_attachment_size_bytes
    )
    await smtp_server.start()

    # Create and include API router AFTER resources are initialized
    # This ensures the router captures the real instances, not fallbacks
    api_router = create_api_router(
        inbox_store=inbox_store,
        webhook_registry=webhook_registry,
        webhook_dispatcher=webhook_dispatcher
    )
    app.include_router(api_router)
    logger.info("API router created and included with shared resources")

    logger.info(
        f"Mock SMTP Server started successfully\n"
        f"  SMTP: {settings.smtp_host}:{settings.smtp_port}\n"
        f"  API: {settings.api_host}:{settings.api_port}\n"
        f"  Swagger UI: http://{settings.api_host}:{settings.api_port}/docs"
    )

    yield

    # Shutdown
    logger.info("Shutting down Mock SMTP Server...")

    # Stop SMTP server
    if smtp_server:
        await smtp_server.stop()

    # Stop webhook dispatcher
    if webhook_dispatcher:
        await webhook_dispatcher.stop()

    logger.info("Mock SMTP Server shut down successfully")


def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.

    Returns:
        Configured FastAPI app
    """
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "A mock SMTP server for testing with REST API and webhook support. "
            "Accepts emails via SMTP and provides a REST API for inspection."
        ),
        lifespan=lifespan
    )

    # NOTE: API router is created in lifespan() after shared resources are initialized
    # This ensures the router uses the real InboxStore/WebhookRegistry instances

    # Root endpoint
    @app.get("/", tags=["Root"])
    async def root():
        """Root endpoint with service information."""
        return {
            "service": settings.app_name,
            "version": settings.app_version,
            "smtp_port": settings.smtp_port,
            "api_port": settings.api_port,
            "docs": f"/docs",
            "health": "/api/health"
        }

    return app


def main():
    """
    Main entry point for running the server.

    Starts both SMTP and FastAPI servers.
    """
    settings = get_settings()

    # Create FastAPI app
    app = create_app()

    # Run with uvicorn
    try:
        uvicorn.run(
            app,
            host=settings.api_host,
            port=settings.api_port,
            log_level=settings.log_level.lower(),
            access_log=True
        )
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down...")
    except Exception as e:
        logger.error(
            f"Fatal error: {type(e).__name__}: {e}",
            exc_info=True
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
