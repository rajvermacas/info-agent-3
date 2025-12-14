"""Webhook registration and management."""

import logging
import threading
from typing import Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, HttpUrl

logger = logging.getLogger(__name__)


class WebhookRegistration(BaseModel):
    """
    Webhook registration model.

    Represents a registered webhook with optional filtering by inbox.
    """

    id: UUID = Field(
        default_factory=uuid4,
        description="Unique identifier for this webhook"
    )
    url: HttpUrl = Field(
        ...,
        description="Webhook URL to POST to"
    )
    inbox_filter: Optional[str] = Field(
        default=None,
        description="If set, only notify for emails to this inbox"
    )
    created_at: str = Field(
        default_factory=lambda: __import__('datetime').datetime.utcnow().isoformat(),
        description="When this webhook was registered"
    )

    def matches_inbox(self, inbox_address: str) -> bool:
        """
        Check if this webhook should be notified for an inbox.

        Args:
            inbox_address: Email address of the inbox

        Returns:
            True if webhook should be notified, False otherwise
        """
        if self.inbox_filter is None:
            return True
        return self.inbox_filter == inbox_address


class WebhookRegistry:
    """
    Thread-safe registry for webhook subscriptions.

    Manages webhook registrations with support for filtering by inbox.

    Attributes:
        _webhooks: Dictionary mapping webhook IDs to registrations
        _lock: Threading lock for thread-safe operations
    """

    def __init__(self):
        """Initialize the webhook registry."""
        self._webhooks: Dict[UUID, WebhookRegistration] = {}
        self._lock = threading.Lock()
        logger.info("WebhookRegistry initialized")

    def register(
        self,
        url: str,
        inbox_filter: Optional[str] = None
    ) -> WebhookRegistration:
        """
        Register a new webhook.

        Args:
            url: Webhook URL to POST to
            inbox_filter: Optional inbox email address to filter notifications

        Returns:
            WebhookRegistration instance

        Raises:
            ValueError: If URL is invalid
        """
        with self._lock:
            # Validate URL by creating the registration
            registration = WebhookRegistration(
                url=url,
                inbox_filter=inbox_filter
            )

            self._webhooks[registration.id] = registration

            logger.info(
                f"Registered webhook {registration.id} for URL '{url}' "
                f"(filter: {inbox_filter or 'all inboxes'})"
            )

            return registration

    def unregister(self, webhook_id: UUID) -> bool:
        """
        Unregister a webhook by ID.

        Args:
            webhook_id: UUID of the webhook to remove

        Returns:
            True if webhook was removed, False if not found
        """
        with self._lock:
            if webhook_id in self._webhooks:
                webhook = self._webhooks[webhook_id]
                del self._webhooks[webhook_id]
                logger.info(
                    f"Unregistered webhook {webhook_id} "
                    f"(URL: {webhook.url})"
                )
                return True
            else:
                logger.debug(
                    f"Webhook {webhook_id} not found for unregistration"
                )
                return False

    def get_webhook(self, webhook_id: UUID) -> Optional[WebhookRegistration]:
        """
        Get a webhook by ID.

        Args:
            webhook_id: UUID of the webhook

        Returns:
            WebhookRegistration if found, None otherwise
        """
        with self._lock:
            webhook = self._webhooks.get(webhook_id)
            if webhook:
                logger.debug(f"Retrieved webhook {webhook_id}")
            else:
                logger.debug(f"Webhook {webhook_id} not found")
            return webhook

    def get_all_webhooks(self) -> List[WebhookRegistration]:
        """
        Get all registered webhooks.

        Returns:
            List of all WebhookRegistration instances
        """
        with self._lock:
            webhooks = list(self._webhooks.values())
            logger.debug(f"Retrieved {len(webhooks)} webhooks")
            return webhooks

    def get_webhooks_for_inbox(
        self,
        inbox_address: str
    ) -> List[WebhookRegistration]:
        """
        Get webhooks that should be notified for an inbox.

        Args:
            inbox_address: Email address of the inbox

        Returns:
            List of matching WebhookRegistration instances
        """
        with self._lock:
            matching = [
                webhook
                for webhook in self._webhooks.values()
                if webhook.matches_inbox(inbox_address)
            ]
            logger.debug(
                f"Found {len(matching)} webhooks for inbox '{inbox_address}'"
            )
            return matching

    def clear_all(self) -> int:
        """
        Clear all webhook registrations.

        Returns:
            Number of webhooks that were removed
        """
        with self._lock:
            count = len(self._webhooks)
            self._webhooks.clear()
            logger.warning(f"Cleared all {count} webhook registrations")
            return count

    @property
    def total_webhooks(self) -> int:
        """Get the total number of registered webhooks."""
        with self._lock:
            return len(self._webhooks)
