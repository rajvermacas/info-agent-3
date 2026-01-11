"""API routes for webhook management."""

import logging
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, HttpUrl

from mock_smtp.webhooks.registry import WebhookRegistry, WebhookRegistration

logger = logging.getLogger(__name__)


class WebhookCreateRequest(BaseModel):
    """Request model for creating a webhook."""

    url: HttpUrl = Field(
        ...,
        description="Webhook URL to POST to"
    )
    inbox_filter: Optional[str] = Field(
        default=None,
        description="Optional inbox email address to filter notifications"
    )


def create_webhook_router(webhook_registry: WebhookRegistry) -> APIRouter:
    """
    Create webhook router with dependency injection.

    Args:
        webhook_registry: WebhookRegistry instance

    Returns:
        Configured APIRouter
    """
    # Create fresh router each time to avoid closure issues with reused singletons
    router = APIRouter()

    @router.post(
        "/webhooks",
        status_code=status.HTTP_201_CREATED,
        response_model=WebhookRegistration,
        summary="Register a webhook",
        description="Register a new webhook to receive email notifications"
    )
    async def register_webhook(request: WebhookCreateRequest):
        """
        Register a new webhook.

        Args:
            request: WebhookCreateRequest with URL and optional filter

        Returns:
            Created WebhookRegistration

        Raises:
            400: If URL is invalid
        """
        logger.info(
            f"POST /api/webhooks url={request.url} "
            f"filter={request.inbox_filter or 'all'}"
        )

        try:
            registration = webhook_registry.register(
                url=str(request.url),
                inbox_filter=request.inbox_filter
            )

            logger.info(f"Registered webhook {registration.id}")
            return registration

        except Exception as e:
            logger.error(
                f"Error registering webhook: {type(e).__name__}: {e}",
                exc_info=True
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to register webhook: {type(e).__name__}"
            )

    @router.get(
        "/webhooks",
        response_model=List[WebhookRegistration],
        summary="List webhooks",
        description="Get all registered webhooks"
    )
    async def list_webhooks():
        """
        List all registered webhooks.

        Returns:
            List of WebhookRegistration objects
        """
        logger.info("GET /api/webhooks")

        webhooks = webhook_registry.get_all_webhooks()
        logger.debug(f"Returning {len(webhooks)} webhooks")

        return webhooks

    @router.get(
        "/webhooks/{webhook_id}",
        response_model=WebhookRegistration,
        summary="Get a webhook",
        description="Get details of a specific webhook"
    )
    async def get_webhook(webhook_id: UUID):
        """
        Get a specific webhook by ID.

        Args:
            webhook_id: UUID of the webhook

        Returns:
            WebhookRegistration object

        Raises:
            404: If webhook not found
        """
        logger.info(f"GET /api/webhooks/{webhook_id}")

        webhook = webhook_registry.get_webhook(webhook_id)
        if not webhook:
            logger.warning(f"Webhook {webhook_id} not found")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Webhook {webhook_id} not found"
            )

        logger.debug(f"Returning webhook {webhook_id}")
        return webhook

    @router.delete(
        "/webhooks/{webhook_id}",
        summary="Unregister a webhook",
        description="Remove a registered webhook"
    )
    async def unregister_webhook(webhook_id: UUID):
        """
        Unregister a webhook.

        Args:
            webhook_id: UUID of the webhook to remove

        Returns:
            Success message

        Raises:
            404: If webhook not found
        """
        logger.info(f"DELETE /api/webhooks/{webhook_id}")

        deleted = webhook_registry.unregister(webhook_id)
        if not deleted:
            logger.warning(f"Webhook {webhook_id} not found for deletion")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Webhook {webhook_id} not found"
            )

        logger.info(f"Unregistered webhook {webhook_id}")

        return {
            "message": f"Webhook {webhook_id} unregistered",
            "webhook_id": str(webhook_id)
        }

    return router
