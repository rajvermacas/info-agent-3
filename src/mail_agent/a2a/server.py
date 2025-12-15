"""
A2A Server - Bootstrap and run the A2A protocol server.

Sets up the Starlette application with A2A endpoints, webhook server,
and all required components.
"""

import asyncio
import logging
import signal
from typing import Optional

import uvicorn
from starlette.applications import Starlette

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore

from mail_agent.a2a.agent_card import create_agent_card
from mail_agent.a2a.executor import MailAgentA2AExecutor
from mail_agent.agent.graph import compile_mail_agent_graph
from mail_agent.agent.nodes.wait_for_reply import set_task_router, set_webhook_server
from mail_agent.config import Settings, get_settings, configure_logging
from mail_agent.tools.smtp_client import SMTPClient
from mail_agent.webhook.router import TaskRouter
from mail_agent.webhook.server import WebhookServer


logger = logging.getLogger(__name__)


def create_a2a_application(
    settings: Optional[Settings] = None,
) -> tuple[Starlette, TaskRouter, WebhookServer]:
    """
    Create and configure the A2A server application.

    This function:
    1. Creates the AgentCard with metadata
    2. Sets up the TaskRouter for concurrent request routing
    3. Sets up the WebhookServer with TaskRouter integration
    4. Compiles the LangGraph mail agent
    5. Creates the A2A executor
    6. Builds the Starlette application

    Args:
        settings: Configuration settings. Uses get_settings() if not provided.

    Returns:
        Tuple of (Starlette app, TaskRouter, WebhookServer).
    """
    if settings is None:
        settings = get_settings()

    logger.info("Creating A2A application")

    # 1. Build Agent Card
    agent_card = create_agent_card(settings)
    logger.info(f"Agent card created: {agent_card.name} v{agent_card.version}")

    # 2. Create shared resources
    task_router = TaskRouter()
    webhook_server = WebhookServer(settings=settings, task_router=task_router)

    # 3. Set global instances for wait_for_reply node
    set_task_router(task_router)
    set_webhook_server(webhook_server)
    logger.info("TaskRouter and WebhookServer configured for A2A mode")

    # 4. Compile the mail agent graph
    graph = compile_mail_agent_graph()
    logger.info("Mail agent graph compiled")

    # 5. Create executor
    executor = MailAgentA2AExecutor(
        graph=graph,
        task_router=task_router,
        webhook_server=webhook_server,
    )
    logger.info("A2A executor created")

    # 6. Create request handler with in-memory task store
    task_store = InMemoryTaskStore()
    request_handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=task_store,
    )
    logger.info("Request handler created with InMemoryTaskStore")

    # 7. Build Starlette application
    app_builder = A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=request_handler,
    )
    app = app_builder.build()
    logger.info("Starlette A2A application built")

    return app, task_router, webhook_server


async def run_a2a_server(
    settings: Optional[Settings] = None,
    verbose: bool = False,
) -> None:
    """
    Run the A2A server with webhook server.

    This function:
    1. Creates the A2A application
    2. Starts the webhook server
    3. Registers webhook with Mock SMTP server
    4. Runs the A2A server (blocking)
    5. Cleans up on shutdown

    Args:
        settings: Configuration settings. Uses get_settings() if not provided.
        verbose: Enable verbose logging.
    """
    if settings is None:
        settings = get_settings()

    # Configure logging
    if verbose:
        settings.log_level = "DEBUG"
    configure_logging(settings)

    logger.info("=" * 60)
    logger.info("MAIL AGENT A2A SERVER")
    logger.info("=" * 60)

    # Create application
    app, task_router, webhook_server = create_a2a_application(settings)

    # SMTP client for webhook registration
    smtp_client = SMTPClient(settings)
    webhook_id: Optional[str] = None

    # Shutdown event
    shutdown_event = asyncio.Event()

    def signal_handler():
        logger.info("Shutdown signal received")
        shutdown_event.set()

    # Register signal handlers
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, signal_handler)

    try:
        # 1. Start webhook server
        logger.info("Starting webhook server...")
        await webhook_server.start()
        logger.info(f"Webhook server listening on {settings.webhook_url}")

        # 2. Check Mock SMTP server health
        logger.info("Checking mock SMTP server...")
        is_healthy = await smtp_client.health_check()
        if not is_healthy:
            logger.warning(
                f"Mock SMTP server at {settings.mock_smtp_api_url} is not responding. "
                "Email operations will fail until it's available."
            )
        else:
            logger.info("Mock SMTP server is healthy")

        # 3. Register webhook with Mock SMTP server
        logger.info("Registering webhook with mock SMTP server...")
        try:
            webhook_response = await smtp_client.register_webhook()
            webhook_id = str(webhook_response.webhook_id)
            logger.info(f"Webhook registered: {webhook_id}")
        except Exception as e:
            logger.warning(f"Failed to register webhook: {e}")
            logger.warning("Webhook registration will need to be done manually")

        # 4. Run A2A server
        logger.info(f"Starting A2A server on http://{settings.a2a_host}:{settings.a2a_port}")
        logger.info(f"Agent card available at http://{settings.a2a_host}:{settings.a2a_port}/.well-known/agent.json")
        logger.info("-" * 60)

        config = uvicorn.Config(
            app=app,
            host=settings.a2a_host,
            port=settings.a2a_port,
            log_level=settings.log_level.lower(),
        )
        server = uvicorn.Server(config)

        # Run server until shutdown
        await server.serve()

    except asyncio.CancelledError:
        logger.info("Server task cancelled")

    finally:
        # Cleanup
        logger.info("-" * 60)
        logger.info("Shutting down...")

        # Unregister webhook
        if webhook_id:
            try:
                import uuid
                await smtp_client.unregister_webhook(uuid.UUID(webhook_id))
                logger.info("Webhook unregistered")
            except Exception as e:
                logger.warning(f"Failed to unregister webhook: {e}")

        # Stop webhook server
        await webhook_server.stop()
        logger.info("Webhook server stopped")

        # Close SMTP client
        await smtp_client.close()
        logger.info("SMTP client closed")

        # Clear global instances
        set_task_router(None)
        logger.info("A2A server shutdown complete")


async def main() -> None:
    """Main entry point for running the A2A server."""
    await run_a2a_server()


if __name__ == "__main__":
    asyncio.run(main())
