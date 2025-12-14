"""SMTP Client for sending emails via Mock SMTP Server REST API."""

import logging
from typing import Optional

import httpx

from mail_agent.config import Settings

logger = logging.getLogger(__name__)


class SMTPClientError(Exception):
    """Base exception for SMTP client errors."""
    pass


class EmailSendError(SMTPClientError):
    """Exception raised when email sending fails."""
    pass


class WebhookRegistrationError(SMTPClientError):
    """Exception raised when webhook registration fails."""
    pass


class SMTPClient:
    """HTTP client for Mock SMTP Server REST API.

    Handles:
    - Sending emails via POST /api/send
    - Registering webhooks via POST /api/webhooks
    """

    def __init__(self, settings: Settings, http_client: Optional[httpx.AsyncClient] = None):
        """Initialize SMTP client.

        Args:
            settings: Mail agent settings
            http_client: Optional httpx client (for testing/reuse)

        Raises:
            ValueError: If settings are invalid
        """
        if not settings.mock_smtp_api_url:
            raise ValueError("mock_smtp_api_url is required in settings")

        self.settings = settings
        self.base_url = settings.mock_smtp_api_url.rstrip("/")
        self._http_client = http_client
        self._owns_client = http_client is None

        logger.info(f"SMTP client initialized with base URL: {self.base_url}")

    async def __aenter__(self):
        """Async context manager entry."""
        if self._owns_client:
            self._http_client = httpx.AsyncClient(timeout=30.0)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self._owns_client and self._http_client:
            await self._http_client.aclose()

    async def send_email(
        self,
        from_address: str,
        to_addresses: list[str],
        subject: str,
        body_text: str,
        body_html: Optional[str] = None,
    ) -> dict:
        """Send email via Mock SMTP Server REST API.

        Args:
            from_address: Sender email address
            to_addresses: List of recipient email addresses (at least 1 required)
            subject: Email subject
            body_text: Plain text body
            body_html: Optional HTML body

        Returns:
            dict: Email response with id, from_address, to_addresses, subject, received_at

        Raises:
            EmailSendError: If email sending fails
            ValueError: If required parameters are missing or invalid
        """
        if not from_address or not from_address.strip():
            raise ValueError("from_address is required")

        if not to_addresses or len(to_addresses) == 0:
            raise ValueError("at least one recipient in to_addresses is required")

        if not subject:
            raise ValueError("subject is required")

        if not body_text:
            raise ValueError("body_text is required")

        payload = {
            "from_address": from_address.strip(),
            "to_addresses": [addr.strip() for addr in to_addresses],
            "subject": subject,
            "body_text": body_text,
            "body_html": body_html,
        }

        url = f"{self.base_url}/api/send"

        logger.debug(f"Sending email via POST {url}: from={from_address}, to={to_addresses}, subject={subject}")

        try:
            if not self._http_client:
                raise EmailSendError("HTTP client not initialized. Use 'async with' context manager.")

            response = await self._http_client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()

            logger.info(
                f"Email sent successfully: id={data.get('id')}, "
                f"from={from_address}, to={to_addresses}"
            )

            return data

        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP error sending email: {e.response.status_code} - {e.response.text}"
            logger.error(error_msg)
            raise EmailSendError(error_msg) from e

        except httpx.RequestError as e:
            error_msg = f"Network error sending email: {str(e)}"
            logger.error(error_msg)
            raise EmailSendError(error_msg) from e

        except Exception as e:
            error_msg = f"Unexpected error sending email: {str(e)}"
            logger.error(error_msg)
            raise EmailSendError(error_msg) from e

    async def register_webhook(self, url: str, inbox_filter: Optional[str] = None) -> dict:
        """Register webhook with Mock SMTP Server.

        Args:
            url: Webhook URL to receive notifications
            inbox_filter: Optional inbox email filter (only notify for this inbox)

        Returns:
            dict: Webhook registration response with id, url, inbox_filter, created_at

        Raises:
            WebhookRegistrationError: If webhook registration fails
            ValueError: If url is invalid
        """
        if not url or not url.strip():
            raise ValueError("webhook url is required")

        if not url.startswith("http://") and not url.startswith("https://"):
            raise ValueError(f"webhook url must start with http:// or https://, got: {url}")

        payload = {
            "url": url.strip(),
            "inbox_filter": inbox_filter.strip() if inbox_filter else None,
        }

        api_url = f"{self.base_url}/api/webhooks"

        logger.debug(
            f"Registering webhook via POST {api_url}: "
            f"url={url}, inbox_filter={inbox_filter}"
        )

        try:
            if not self._http_client:
                raise WebhookRegistrationError(
                    "HTTP client not initialized. Use 'async with' context manager."
                )

            response = await self._http_client.post(api_url, json=payload)
            response.raise_for_status()
            data = response.json()

            logger.info(
                f"Webhook registered successfully: id={data.get('id')}, "
                f"url={url}, inbox_filter={inbox_filter}"
            )

            return data

        except httpx.HTTPStatusError as e:
            error_msg = (
                f"HTTP error registering webhook: "
                f"{e.response.status_code} - {e.response.text}"
            )
            logger.error(error_msg)
            raise WebhookRegistrationError(error_msg) from e

        except httpx.RequestError as e:
            error_msg = f"Network error registering webhook: {str(e)}"
            logger.error(error_msg)
            raise WebhookRegistrationError(error_msg) from e

        except Exception as e:
            error_msg = f"Unexpected error registering webhook: {str(e)}"
            logger.error(error_msg)
            raise WebhookRegistrationError(error_msg) from e
