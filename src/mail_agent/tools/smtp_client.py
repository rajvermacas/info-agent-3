"""
SMTP Client - HTTP client for sending emails via mock SMTP REST API.

Provides async methods for sending emails and registering webhooks.
"""

import logging
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

import httpx

from mail_agent.config import Settings, get_settings


logger = logging.getLogger(__name__)


class SMTPClientError(Exception):
    """Base exception for SMTP client errors."""

    pass


class EmailSendError(SMTPClientError):
    """Failed to send email via API."""

    pass


class WebhookRegistrationError(SMTPClientError):
    """Failed to register webhook."""

    pass


@dataclass
class SendEmailResponse:
    """Response from sending an email."""

    email_id: UUID
    from_address: str
    to_addresses: list[str]
    subject: str
    received_at: str


@dataclass
class WebhookRegistrationResponse:
    """Response from registering a webhook."""

    webhook_id: UUID
    url: str
    inbox_filter: Optional[str]
    created_at: str


class SMTPClient:
    """
    Async HTTP client for interacting with the mock SMTP server REST API.

    Provides methods for sending emails and registering webhooks.
    """

    def __init__(
        self,
        settings: Optional[Settings] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        """
        Initialize SMTP client.

        Args:
            settings: Configuration settings. Uses get_settings() if not provided.
            client: Optional httpx client for dependency injection in tests.
        """
        self._settings = settings or get_settings()
        self._client = client
        self._owns_client = client is None
        logger.debug(
            f"SMTPClient initialized with base_url={self._settings.mock_smtp_api_url}"
        )

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._settings.mock_smtp_api_url,
                timeout=self._settings.http_timeout_seconds,
            )
            logger.debug("Created new httpx.AsyncClient")
        return self._client

    async def close(self) -> None:
        """Close the HTTP client if we own it."""
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None
            logger.debug("Closed httpx.AsyncClient")

    async def send_email(
        self,
        to_addresses: list[str],
        subject: str,
        body_text: str,
        from_address: Optional[str] = None,
        body_html: Optional[str] = None,
    ) -> SendEmailResponse:
        """
        Send an email via the mock SMTP server REST API.

        Args:
            to_addresses: List of recipient email addresses.
            subject: Email subject line.
            body_text: Plain text email body.
            from_address: Sender address. Defaults to agent email.
            body_html: Optional HTML email body.

        Returns:
            SendEmailResponse with email details.

        Raises:
            EmailSendError: If the email could not be sent.
        """
        if not to_addresses:
            raise EmailSendError("to_addresses cannot be empty")
        if not body_text:
            raise EmailSendError("body_text cannot be empty")

        from_addr = from_address or self._settings.agent_email

        payload = {
            "from_address": from_addr,
            "to_addresses": to_addresses,
            "subject": subject,
            "body_text": body_text,
        }
        if body_html:
            payload["body_html"] = body_html

        logger.info(
            f"Sending email: from={from_addr}, to={to_addresses}, subject={subject}"
        )
        logger.debug(f"Email payload: {payload}")

        try:
            client = await self._get_client()
            response = await client.post("/api/send", json=payload)

            if response.status_code == 201:
                data = response.json()
                result = SendEmailResponse(
                    email_id=UUID(data["id"]),
                    from_address=data["from_address"],
                    to_addresses=data["to_addresses"],
                    subject=data["subject"],
                    received_at=data["received_at"],
                )
                logger.info(f"Email sent successfully: id={result.email_id}")
                return result

            error_msg = f"Failed to send email: status={response.status_code}"
            try:
                error_detail = response.json().get("detail", response.text)
                error_msg = f"{error_msg}, detail={error_detail}"
            except Exception:
                error_msg = f"{error_msg}, body={response.text}"

            logger.error(error_msg)
            raise EmailSendError(error_msg)

        except httpx.RequestError as e:
            error_msg = f"HTTP request failed while sending email: {e}"
            logger.error(error_msg)
            raise EmailSendError(error_msg) from e

    async def register_webhook(
        self,
        webhook_url: Optional[str] = None,
        inbox_filter: Optional[str] = None,
    ) -> WebhookRegistrationResponse:
        """
        Register a webhook with the mock SMTP server.

        Args:
            webhook_url: URL to receive webhook POSTs. Defaults to agent's webhook URL.
            inbox_filter: Optional email address to filter webhooks.
                          Defaults to agent email.

        Returns:
            WebhookRegistrationResponse with webhook details.

        Raises:
            WebhookRegistrationError: If webhook registration fails.
        """
        url = webhook_url or self._settings.webhook_url
        filter_addr = inbox_filter if inbox_filter is not None else self._settings.agent_email

        payload = {
            "url": url,
            "inbox_filter": filter_addr,
        }

        logger.info(f"Registering webhook: url={url}, inbox_filter={filter_addr}")

        try:
            client = await self._get_client()
            response = await client.post("/api/webhooks", json=payload)

            if response.status_code == 201:
                data = response.json()
                result = WebhookRegistrationResponse(
                    webhook_id=UUID(data["id"]),
                    url=data["url"],
                    inbox_filter=data.get("inbox_filter"),
                    created_at=data["created_at"],
                )
                logger.info(f"Webhook registered successfully: id={result.webhook_id}")
                return result

            error_msg = f"Failed to register webhook: status={response.status_code}"
            try:
                error_detail = response.json().get("detail", response.text)
                error_msg = f"{error_msg}, detail={error_detail}"
            except Exception:
                error_msg = f"{error_msg}, body={response.text}"

            logger.error(error_msg)
            raise WebhookRegistrationError(error_msg)

        except httpx.RequestError as e:
            error_msg = f"HTTP request failed while registering webhook: {e}"
            logger.error(error_msg)
            raise WebhookRegistrationError(error_msg) from e

    async def unregister_webhook(self, webhook_id: UUID) -> bool:
        """
        Unregister a webhook from the mock SMTP server.

        Args:
            webhook_id: ID of the webhook to unregister.

        Returns:
            True if successfully unregistered.

        Raises:
            WebhookRegistrationError: If unregistration fails.
        """
        logger.info(f"Unregistering webhook: id={webhook_id}")

        try:
            client = await self._get_client()
            response = await client.delete(f"/api/webhooks/{webhook_id}")

            if response.status_code == 204:
                logger.info(f"Webhook unregistered successfully: id={webhook_id}")
                return True

            if response.status_code == 404:
                logger.warning(f"Webhook not found for unregistration: id={webhook_id}")
                return False

            error_msg = f"Failed to unregister webhook: status={response.status_code}"
            logger.error(error_msg)
            raise WebhookRegistrationError(error_msg)

        except httpx.RequestError as e:
            error_msg = f"HTTP request failed while unregistering webhook: {e}"
            logger.error(error_msg)
            raise WebhookRegistrationError(error_msg) from e

    async def health_check(self) -> bool:
        """
        Check if the mock SMTP server is healthy.

        Returns:
            True if server is healthy.
        """
        try:
            client = await self._get_client()
            response = await client.get("/api/health")
            is_healthy = response.status_code == 200
            logger.debug(f"Health check: healthy={is_healthy}")
            return is_healthy
        except Exception as e:
            logger.warning(f"Health check failed: {e}")
            return False
