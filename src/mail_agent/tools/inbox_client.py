"""Inbox Client for fetching emails from Mock SMTP Server REST API."""

import logging
from typing import Optional

import httpx

from mail_agent.config import Settings

logger = logging.getLogger(__name__)


class InboxClientError(Exception):
    """Base exception for inbox client errors."""
    pass


class EmailFetchError(InboxClientError):
    """Exception raised when email fetching fails."""
    pass


class InboxClient:
    """HTTP client for fetching emails from Mock SMTP Server.

    Handles:
    - Fetching full email with attachments via GET /api/inboxes/{email}/emails/{email_id}
    - Listing emails in inbox via GET /api/inboxes/{email}
    """

    def __init__(self, settings: Settings, http_client: Optional[httpx.AsyncClient] = None):
        """Initialize inbox client.

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

        logger.info(f"Inbox client initialized with base URL: {self.base_url}")

    async def __aenter__(self):
        """Async context manager entry."""
        if self._owns_client:
            self._http_client = httpx.AsyncClient(timeout=30.0)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self._owns_client and self._http_client:
            await self._http_client.aclose()

    async def fetch_email(self, inbox_email: str, email_id: str) -> dict:
        """Fetch full email with attachments from Mock SMTP Server.

        Args:
            inbox_email: Inbox email address (e.g., "info-agent@gmail.com")
            email_id: Email UUID

        Returns:
            dict: Full email object with id, from_address, to_addresses, subject,
                  body_text, body_html, attachments (base64 encoded), headers, received_at

        Raises:
            EmailFetchError: If email fetching fails
            ValueError: If required parameters are missing
        """
        if not inbox_email or not inbox_email.strip():
            raise ValueError("inbox_email is required")

        if not email_id or not email_id.strip():
            raise ValueError("email_id is required")

        # URL encode inbox email to handle special characters like @
        from urllib.parse import quote

        encoded_email = quote(inbox_email.strip(), safe="")
        url = f"{self.base_url}/api/inboxes/{encoded_email}/emails/{email_id.strip()}"

        logger.debug(f"Fetching email via GET {url}")

        try:
            if not self._http_client:
                raise EmailFetchError(
                    "HTTP client not initialized. Use 'async with' context manager."
                )

            response = await self._http_client.get(url)
            response.raise_for_status()
            data = response.json()

            logger.info(
                f"Email fetched successfully: id={email_id}, "
                f"from={data.get('from_address')}, "
                f"attachments={len(data.get('attachments', []))}"
            )

            return data

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                error_msg = f"Email not found: inbox={inbox_email}, email_id={email_id}"
            else:
                error_msg = (
                    f"HTTP error fetching email: "
                    f"{e.response.status_code} - {e.response.text}"
                )
            logger.error(error_msg)
            raise EmailFetchError(error_msg) from e

        except httpx.RequestError as e:
            error_msg = f"Network error fetching email: {str(e)}"
            logger.error(error_msg)
            raise EmailFetchError(error_msg) from e

        except Exception as e:
            error_msg = f"Unexpected error fetching email: {str(e)}"
            logger.error(error_msg)
            raise EmailFetchError(error_msg) from e

    async def list_emails(self, inbox_email: str) -> list[dict]:
        """List all emails in inbox (returns EmailSummary objects).

        Args:
            inbox_email: Inbox email address

        Returns:
            list[dict]: List of email summaries with id, from_address, to_addresses,
                        subject, has_attachments, received_at

        Raises:
            EmailFetchError: If listing fails
            ValueError: If inbox_email is missing
        """
        if not inbox_email or not inbox_email.strip():
            raise ValueError("inbox_email is required")

        from urllib.parse import quote

        encoded_email = quote(inbox_email.strip(), safe="")
        url = f"{self.base_url}/api/inboxes/{encoded_email}"

        logger.debug(f"Listing emails via GET {url}")

        try:
            if not self._http_client:
                raise EmailFetchError(
                    "HTTP client not initialized. Use 'async with' context manager."
                )

            response = await self._http_client.get(url)
            response.raise_for_status()
            data = response.json()

            logger.info(f"Listed {len(data)} emails for inbox: {inbox_email}")

            return data

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                # Inbox doesn't exist yet - return empty list
                logger.debug(f"Inbox not found (empty): {inbox_email}")
                return []
            else:
                error_msg = (
                    f"HTTP error listing emails: "
                    f"{e.response.status_code} - {e.response.text}"
                )
                logger.error(error_msg)
                raise EmailFetchError(error_msg) from e

        except httpx.RequestError as e:
            error_msg = f"Network error listing emails: {str(e)}"
            logger.error(error_msg)
            raise EmailFetchError(error_msg) from e

        except Exception as e:
            error_msg = f"Unexpected error listing emails: {str(e)}"
            logger.error(error_msg)
            raise EmailFetchError(error_msg) from e
