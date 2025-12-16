"""
UI Server Main Entry Point.

Provides a web-based interface for Mail Agent using HTMX and Tailwind CSS.
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ui.config import Settings, configure_logging, get_settings
from ui.services.a2a_client import A2AClientService
from ui.services.smtp_client import SMTPClientService
from ui.services.smtp_sender import SMTPSenderService

logger = logging.getLogger(__name__)

# Template directory path
TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"


class UIServerResources:
    """Container for UI server resources."""

    def __init__(
        self,
        settings: Settings,
        a2a_client: A2AClientService,
        smtp_client: SMTPClientService,
        smtp_sender: SMTPSenderService,
        templates: Jinja2Templates,
    ):
        self.settings = settings
        self.a2a_client = a2a_client
        self.smtp_client = smtp_client
        self.smtp_sender = smtp_sender
        self.templates = templates


# Global resources instance (set during lifespan)
_resources: UIServerResources | None = None


def get_resources() -> UIServerResources:
    """Get the global resources instance."""
    if _resources is None:
        raise RuntimeError("UI Server resources not initialized. Server not started.")
    return _resources


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Manage application lifespan.

    Initializes and cleans up resources.
    """
    global _resources

    settings = get_settings()
    configure_logging(settings)

    logger.info("Starting UI Server...")
    logger.info("  A2A Server: %s", settings.a2a_server_url)
    logger.info("  Mock SMTP API: %s", settings.mock_smtp_api_url)
    logger.info("  SMTP Server: %s:%d", settings.smtp_host, settings.smtp_port)

    # Create service clients
    a2a_client = A2AClientService(settings)
    smtp_client = SMTPClientService(settings)
    smtp_sender = SMTPSenderService(settings)

    # Create templates
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    # Store resources globally
    _resources = UIServerResources(
        settings=settings,
        a2a_client=a2a_client,
        smtp_client=smtp_client,
        smtp_sender=smtp_sender,
        templates=templates,
    )

    logger.info("UI Server resources initialized successfully")

    yield

    # Cleanup
    logger.info("Shutting down UI Server...")
    await a2a_client.close()
    await smtp_client.close()
    _resources = None
    logger.info("UI Server shutdown complete")


def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.

    Returns:
        FastAPI: Configured application instance.
    """
    app = FastAPI(
        title="Mail Agent UI",
        description="Web interface for Mail Agent - Send requests, view inboxes, and monitor tasks",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Mount static files if directory exists
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
        logger.info("Static files mounted at /static")

    # Import and include routers
    from ui.routes.pages import router as pages_router
    from ui.routes.send_request import router as send_request_router
    from ui.routes.inbox import router as inbox_router
    from ui.routes.dashboard import router as dashboard_router

    app.include_router(pages_router)
    app.include_router(send_request_router, prefix="/api")
    app.include_router(inbox_router, prefix="/api")
    app.include_router(dashboard_router, prefix="/api")

    @app.get("/health")
    async def health_check() -> dict:
        """Health check endpoint."""
        return {
            "status": "healthy",
            "service": "ui-server",
            "version": "0.1.0",
        }

    return app


def main() -> None:
    """Main entry point for the UI server."""
    settings = get_settings()
    configure_logging(settings)

    logger.info("=" * 60)
    logger.info("Mail Agent UI Server")
    logger.info("=" * 60)
    logger.info("Starting server on http://%s:%d", settings.host, settings.port)
    logger.info("=" * 60)

    app = create_app()

    try:
        uvicorn.run(
            app,
            host=settings.host,
            port=settings.port,
            log_level=settings.log_level.lower(),
        )
    except KeyboardInterrupt:
        logger.info("UI Server stopped by user")
    except Exception as e:
        logger.critical("Fatal error starting UI Server: %s", e)
        raise


if __name__ == "__main__":
    main()
