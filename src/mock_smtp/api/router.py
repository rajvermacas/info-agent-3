"""Main API router aggregating all route modules."""

import logging

from fastapi import APIRouter

from mock_smtp.api.email_routes import create_email_router
from mock_smtp.api.inbox_routes import create_inbox_router
from mock_smtp.api.send_routes import create_send_router
from mock_smtp.api.webhook_routes import create_webhook_router
from mock_smtp.store.inbox_store import InboxStore
from mock_smtp.webhooks.dispatcher import WebhookDispatcher
from mock_smtp.webhooks.registry import WebhookRegistry

logger = logging.getLogger(__name__)


def create_api_router(
    inbox_store: InboxStore,
    webhook_registry: WebhookRegistry,
    webhook_dispatcher: WebhookDispatcher
) -> APIRouter:
    """
    Create the main API router with all subrouters.

    Args:
        inbox_store: InboxStore instance
        webhook_registry: WebhookRegistry instance
        webhook_dispatcher: WebhookDispatcher instance for sending notifications

    Returns:
        Configured APIRouter with all endpoints
    """
    api_router = APIRouter(prefix="/api")

    # Create and include all subrouters
    inbox_router = create_inbox_router(inbox_store)
    email_router = create_email_router(inbox_store)
    send_router = create_send_router(
        inbox_store=inbox_store,
        webhook_registry=webhook_registry,
        webhook_dispatcher=webhook_dispatcher
    )
    webhook_router = create_webhook_router(webhook_registry)

    # Include routers
    api_router.include_router(inbox_router, tags=["Inboxes"])
    api_router.include_router(email_router, tags=["Emails"])
    api_router.include_router(send_router, tags=["Send"])
    api_router.include_router(webhook_router, tags=["Webhooks"])

    # Health check endpoint
    @api_router.get(
        "/health",
        tags=["Health"],
        summary="Health check",
        description="Check if the server is running"
    )
    async def health_check():
        """
        Health check endpoint.

        Returns:
            Server status information
        """
        return {
            "status": "healthy",
            "service": "Mock SMTP Server",
            "inboxes": inbox_store.total_inboxes,
            "total_emails": inbox_store.total_emails,
            "webhooks": webhook_registry.total_webhooks
        }

    logger.info("API router created with all endpoints")
    return api_router
