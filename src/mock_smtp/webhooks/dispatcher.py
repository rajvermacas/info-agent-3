"""Webhook dispatching with async HTTP POST requests."""

import asyncio
import logging
from datetime import datetime
from enum import Enum
from typing import Optional

import httpx

from mock_smtp.store.models import Email

logger = logging.getLogger(__name__)


class WebhookStatus(str, Enum):
    """Webhook dispatch status."""

    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    TIMEOUT = "timeout"


class WebhookDispatcher:
    """
    Async webhook dispatcher using httpx.

    Dispatches webhook notifications with retry logic, timeout handling,
    and comprehensive error logging.
    """

    def __init__(
        self,
        timeout_seconds: float = 10.0,
        max_retries: int = 3,
        max_concurrent: int = 10
    ):
        """
        Initialize the webhook dispatcher.

        Args:
            timeout_seconds: HTTP request timeout
            max_retries: Maximum retry attempts on failure
            max_concurrent: Maximum concurrent webhook dispatches
        """
        self.timeout = httpx.Timeout(
            connect=30.0,
            read=timeout_seconds,
            write=10.0,
            pool=10.0
        )
        self.max_retries = max_retries
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.client: Optional[httpx.AsyncClient] = None

        logger.info(
            f"WebhookDispatcher initialized "
            f"(timeout={timeout_seconds}s, retries={max_retries})"
        )

    async def start(self):
        """Initialize the HTTP client."""
        if self.client is None:
            limits = httpx.Limits(
                max_connections=100,
                max_keepalive_connections=20
            )
            self.client = httpx.AsyncClient(
                timeout=self.timeout,
                limits=limits
            )
            logger.info("WebhookDispatcher HTTP client started")

    async def stop(self):
        """Close the HTTP client and cleanup resources."""
        if self.client:
            await self.client.aclose()
            self.client = None
            logger.info("WebhookDispatcher HTTP client stopped")

    async def dispatch(
        self,
        url: str,
        email: Email
    ) -> dict:
        """
        Dispatch a webhook notification for an email.

        Args:
            url: Webhook URL to POST to
            email: Email that triggered the webhook

        Returns:
            Dictionary with dispatch status and details
        """
        if self.client is None:
            raise RuntimeError(
                "WebhookDispatcher not started. Call start() first."
            )

        async with self.semaphore:
            return await self._dispatch_with_retry(url, email)

    async def _dispatch_with_retry(
        self,
        url: str,
        email: Email
    ) -> dict:
        """
        Internal method with retry logic.

        Args:
            url: Webhook URL
            email: Email data

        Returns:
            Dispatch result dictionary
        """
        payload = self._build_payload(email)

        for attempt in range(self.max_retries):
            try:
                logger.debug(
                    f"Dispatching webhook to {url} for email {email.id} "
                    f"(attempt {attempt + 1}/{self.max_retries})"
                )

                response = await self.client.post(
                    url,
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "X-Webhook-Event": "email.received",
                        "X-Email-ID": str(email.id),
                        "X-Webhook-Timestamp": datetime.utcnow().isoformat()
                    }
                )

                response.raise_for_status()

                logger.info(
                    f"Webhook sent successfully to {url} "
                    f"(email={email.id}, status={response.status_code})"
                )

                return {
                    "url": url,
                    "email_id": str(email.id),
                    "status": WebhookStatus.SENT.value,
                    "status_code": response.status_code,
                    "attempt": attempt + 1,
                    "error": None
                }

            except httpx.TimeoutException as e:
                logger.warning(
                    f"Timeout dispatching webhook to {url} "
                    f"(email={email.id}, attempt={attempt + 1}): "
                    f"{type(e).__name__}"
                )

                if attempt == self.max_retries - 1:
                    logger.error(
                        f"Webhook to {url} failed after {self.max_retries} "
                        f"timeout attempts (email={email.id})"
                    )
                    return {
                        "url": url,
                        "email_id": str(email.id),
                        "status": WebhookStatus.TIMEOUT.value,
                        "status_code": None,
                        "attempt": attempt + 1,
                        "error": f"Timeout after {self.max_retries} attempts"
                    }

                # Exponential backoff
                await asyncio.sleep(2 ** attempt)

            except httpx.HTTPStatusError as e:
                logger.error(
                    f"HTTP error {e.response.status_code} from {url} "
                    f"(email={email.id}): {e.response.text[:200]}"
                )

                return {
                    "url": url,
                    "email_id": str(email.id),
                    "status": WebhookStatus.FAILED.value,
                    "status_code": e.response.status_code,
                    "attempt": attempt + 1,
                    "error": f"HTTP {e.response.status_code}"
                }

            except Exception as e:
                logger.error(
                    f"Unexpected error dispatching webhook to {url} "
                    f"(email={email.id}): {type(e).__name__}: {e}"
                )

                if attempt < self.max_retries - 1:
                    # Retry on unexpected errors
                    await asyncio.sleep(2 ** attempt)
                else:
                    return {
                        "url": url,
                        "email_id": str(email.id),
                        "status": WebhookStatus.FAILED.value,
                        "status_code": None,
                        "attempt": attempt + 1,
                        "error": f"{type(e).__name__}: {str(e)}"
                    }

        # Should not reach here, but return failure if we do
        return {
            "url": url,
            "email_id": str(email.id),
            "status": WebhookStatus.FAILED.value,
            "status_code": None,
            "attempt": self.max_retries,
            "error": "All retry attempts exhausted"
        }

    def _build_payload(self, email: Email) -> dict:
        """
        Build webhook payload from email.

        Args:
            email: Email instance

        Returns:
            Payload dictionary for JSON serialization
        """
        return {
            "event": "email.received",
            "email_id": str(email.id),
            "from": email.from_address,
            "to": email.to_addresses,
            "subject": email.subject,
            "has_attachments": email.has_attachments,
            "attachment_count": len(email.attachments),
            "received_at": email.received_at.isoformat(),
            "body_preview": (
                email.body_text[:100] + "..."
                if email.body_text and len(email.body_text) > 100
                else email.body_text or ""
            )
        }

    async def dispatch_batch(
        self,
        webhooks: list[tuple[str, Email]]
    ) -> list[dict]:
        """
        Dispatch webhooks to multiple URLs concurrently.

        Args:
            webhooks: List of (url, email) tuples

        Returns:
            List of dispatch result dictionaries
        """
        if not webhooks:
            return []

        tasks = [
            self.dispatch(url, email)
            for url, email in webhooks
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        successful = sum(
            1 for r in results
            if not isinstance(r, Exception) and
            r.get("status") == WebhookStatus.SENT.value
        )
        failed = len(results) - successful

        logger.info(
            f"Batch dispatch complete: {len(webhooks)} webhooks "
            f"({successful} sent, {failed} failed)"
        )

        return [
            r if not isinstance(r, Exception)
            else {
                "status": WebhookStatus.FAILED.value,
                "error": str(r)
            }
            for r in results
        ]
