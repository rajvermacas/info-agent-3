"""
A2A Server - Non-blocking A2A protocol server with checkpointing.

Sets up the Starlette application with:
- A2A protocol endpoints
- Task status polling endpoint (GET /tasks/{id})
- Webhook server for email notifications
- TaskManager for non-blocking task lifecycle
- LangGraph checkpointer for state persistence
"""

import asyncio
import logging
import signal
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

import uvicorn
from starlette.applications import Starlette
from starlette.routing import Mount

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore

from mail_agent.a2a.agent_card import create_agent_card
from mail_agent.a2a.executor import MailAgentA2AExecutor
from mail_agent.a2a.routes import create_tasks_router
from mail_agent.agent.graph import compile_mail_agent_graph
from mail_agent.agent.nodes.wait_for_reply import set_a2a_mode, set_webhook_server
from mail_agent.config import Settings, get_settings, configure_logging
from mail_agent.persistence import DatabaseManager, TaskStore, create_checkpointer
from mail_agent.task_manager import TaskManager
from mail_agent.tools.smtp_client import SMTPClient
from mail_agent.webhook.server import WebhookServer


logger = logging.getLogger(__name__)


class A2AServerResources:
    """
    Container for shared A2A server resources.

    Holds references to all components that need lifecycle management.
    """

    def __init__(
        self,
        app: Starlette,
        task_manager: TaskManager,
        webhook_server: WebhookServer,
        db_manager: DatabaseManager,
    ) -> None:
        """
        Initialize resource container.

        Args:
            app: Starlette application.
            task_manager: TaskManager for task lifecycle.
            webhook_server: WebhookServer for email notifications.
            db_manager: DatabaseManager for persistence.
        """
        self.app = app
        self.task_manager = task_manager
        self.webhook_server = webhook_server
        self.db_manager = db_manager


async def create_a2a_application(
    settings: Settings,
    db_manager: DatabaseManager,
    checkpointer,
) -> A2AServerResources:
    """
    Create and configure the A2A server application with all resources.

    This function:
    1. Creates TaskStore and TaskManager
    2. Sets up the WebhookServer
    3. Compiles the LangGraph with checkpointer
    4. Creates the A2A executor
    5. Builds the Starlette application with task routes

    Args:
        settings: Configuration settings.
        db_manager: Initialized DatabaseManager.
        checkpointer: Initialized LangGraph checkpointer (must be kept alive externally).

    Returns:
        A2AServerResources containing all initialized components.
    """
    logger.info("Creating A2A application (non-blocking mode)")

    # 1. Create TaskStore
    task_store = TaskStore(db_manager)
    logger.info("TaskStore created")

    # 2. Compile graph with checkpointer
    logger.info("Compiling mail agent graph with checkpointer")
    graph = compile_mail_agent_graph(checkpointer=checkpointer)
    logger.info("Graph compiled with checkpointer")

    # 3. Create WebhookServer (without TaskRouter - we'll use TaskManager)
    webhook_server = WebhookServer(settings=settings)
    logger.info("WebhookServer created")

    # 4. Create TaskManager
    task_manager = TaskManager(
        db_manager=db_manager,
        task_store=task_store,
        checkpointer=checkpointer,
        graph=graph,
        settings=settings,
    )
    logger.info("TaskManager created")

    # 5. Connect WebhookServer to TaskManager for webhook routing
    webhook_server.set_task_manager(task_manager)
    logger.info("WebhookServer connected to TaskManager")

    # 6. Set global instances for wait_for_reply node
    set_a2a_mode(True)
    set_webhook_server(webhook_server)
    logger.info("A2A mode enabled, webhook server configured")

    # 7. Build Agent Card
    agent_card = create_agent_card(settings)
    logger.info(f"Agent card created: {agent_card.name} v{agent_card.version}")

    # 8. Create executor with TaskManager
    executor = MailAgentA2AExecutor(
        graph=graph,
        task_manager=task_manager,
    )
    logger.info("A2A executor created (non-blocking)")

    # 9. Create request handler with in-memory task store
    a2a_task_store = InMemoryTaskStore()
    request_handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=a2a_task_store,
    )
    logger.info("Request handler created")

    # 10. Build A2A Starlette application
    app_builder = A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=request_handler,
    )
    app = app_builder.build()
    logger.info("A2A Starlette application built")

    # 11. Mount task routes as FastAPI sub-application
    # FastAPI routes need FastAPI's dependency injection and routing,
    # so we mount a FastAPI app instead of converting routes manually.
    tasks_router = create_tasks_router(task_manager)
    from fastapi import FastAPI as TaskFastAPI
    from starlette.routing import Mount
    task_app = TaskFastAPI()
    task_app.include_router(tasks_router)
    # Mount at /api so routes become /api/tasks and /api/tasks/{task_id}
    app.routes.append(Mount("/api", app=task_app))
    logger.info("Task routes mounted at /api/tasks")

    return A2AServerResources(
        app=app,
        task_manager=task_manager,
        webhook_server=webhook_server,
        db_manager=db_manager,
    )


async def run_a2a_server(
    settings: Optional[Settings] = None,
    verbose: bool = False,
) -> None:
    """
    Run the non-blocking A2A server with all components.

    This function:
    1. Initializes database and checkpointer (as context manager)
    2. Creates the A2A application with all resources
    3. Starts the TaskManager (restores suspended tasks)
    4. Starts the webhook server
    5. Registers webhook with Mock SMTP server
    6. Runs the A2A server (blocking)
    7. Cleans up on shutdown

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
    logger.info("MAIL AGENT A2A SERVER (NON-BLOCKING)")
    logger.info("=" * 60)

    # 1. Initialize database
    logger.info(f"Initializing database: {settings.sqlite_db_path}")
    db_manager = DatabaseManager(settings)
    await db_manager.connect()
    logger.info("Database connected")

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
        # 2. Create checkpointer as context manager (stays open for server lifetime)
        logger.info("Creating LangGraph checkpointer")
        async with create_checkpointer(settings) as checkpointer:
            logger.info("Checkpointer created")

            # 3. Create application and resources
            resources = await create_a2a_application(settings, db_manager, checkpointer)

            try:
                # 4. Start TaskManager (restore suspended tasks)
                logger.info("Starting TaskManager...")
                await resources.task_manager.start()
                logger.info(
                    f"TaskManager started with {resources.task_manager.suspended_task_count} "
                    "restored suspended tasks"
                )

                # 5. Start webhook server
                logger.info("Starting webhook server...")
                await resources.webhook_server.start()
                logger.info(f"Webhook server listening on {settings.webhook_url}")

                # 6. Check Mock SMTP server health
                logger.info("Checking mock SMTP server...")
                is_healthy = await smtp_client.health_check()
                if not is_healthy:
                    logger.warning(
                        f"Mock SMTP server at {settings.mock_smtp_api_url} is not responding. "
                        "Email operations will fail until it's available."
                    )
                else:
                    logger.info("Mock SMTP server is healthy")

                # 7. Register webhook with Mock SMTP server
                logger.info("Registering webhook with mock SMTP server...")
                try:
                    webhook_response = await smtp_client.register_webhook()
                    webhook_id = str(webhook_response.webhook_id)
                    logger.info(f"Webhook registered: {webhook_id}")
                except Exception as e:
                    logger.warning(f"Failed to register webhook: {e}")
                    logger.warning("Webhook registration will need to be done manually")

                # 8. Run A2A server
                logger.info(f"Starting A2A server on http://{settings.a2a_host}:{settings.a2a_port}")
                logger.info(f"Agent card: http://{settings.a2a_host}:{settings.a2a_port}/.well-known/agent.json")
                logger.info(f"Task status: http://{settings.a2a_host}:{settings.a2a_port}/tasks/{{task_id}}")
                logger.info("-" * 60)

                config = uvicorn.Config(
                    app=resources.app,
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
                # Cleanup within checkpointer context
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

                # Stop TaskManager
                await resources.task_manager.stop()
                logger.info("TaskManager stopped")

                # Stop webhook server
                await resources.webhook_server.stop()
                logger.info("Webhook server stopped")

                # Clear global instances
                set_a2a_mode(False)

        # Checkpointer context exits here - automatically closed
        logger.info("Checkpointer closed")

    finally:
        # Close SMTP client
        await smtp_client.close()
        logger.info("SMTP client closed")

        # Close database
        await db_manager.close()
        logger.info("Database closed")

        logger.info("A2A server shutdown complete")


async def main() -> None:
    """Main entry point for running the A2A server."""
    await run_a2a_server()


if __name__ == "__main__":
    asyncio.run(main())
