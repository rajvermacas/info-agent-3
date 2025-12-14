"""
Inbox Client - HTTP client for fetching emails from mock SMTP REST API.

Provides async methods for retrieving emails and their attachments.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional
from uuid import UUID

import httpx

from mail_agent.config import Settings, get_settings


logger = logging.getLogger(__name__)


class InboxClientError(Exception):
    """Base exception for inbox client errors."""

    pass


class EmailFetchError(InboxClientError):
    """Failed to fetch email from inbox."""

    pass


class InboxNotFoundError(InboxClientError):
    """Inbox does not exist."""

    pass


class EmailNotFoundError(InboxClientError):
    """Email does not exist in inbox."""

    pass


@dataclass
class Attachment:
    """Email attachment data."""

    filename: str
    content_type: str
    content_base64: str
    size_bytes: int


@dataclass
class Email:
    """Full email data fetched from inbox."""

    email_id: UUID
    from_address: str
    to_addresses: list[str]
    subject: str
    body_text: Optional[str]
    body_html: Optional[str]
    attachments: list[Attachment] = field(default_factory=list)
    headers: dict[str, str] = field(default_factory=dict)
    received_at: str = ""

    @property
    def has_attachments(self) -> bool:
        """Check if email has attachments."""
        return len(self.attachments) > 0


@dataclass
class EmailSummary:
    """Lightweight email summary for listing."""

    email_id: UUID
    from_address: str
    to_addresses: list[str]
    subject: str
    has_attachments: bool
    attachment_count: int
    received_at: str


class InboxClient:
    """
    Async HTTP client for fetching emails from the mock SMTP server.

    Provides methods for listing inboxes, fetching emails, and getting attachments.
    """

    def __init__(
        self,
        settings: Optional[Settings] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        """
        Initialize inbox client.

        Args:
            settings: Configuration settings. Uses get_settings() if not provided.
            client: Optional httpx client for dependency injection in tests.
        """
        self._settings = settings or get_settings()
        self._client = client
        self._owns_client = client is None
        logger.debug(
            f"InboxClient initialized with base_url={self._settings.mock_smtp_api_url}"
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

    async def get_email(
        self,
        inbox_address: str,
        email_id: UUID,
    ) -> Email:
        """
        Fetch a full email with attachments from an inbox.

        Args:
            inbox_address: Email address of the inbox.
            email_id: UUID of the email to fetch.

        Returns:
            Email with full content and attachments.

        Raises:
            InboxNotFoundError: If inbox does not exist.
            EmailNotFoundError: If email does not exist.
            EmailFetchError: If fetch fails for other reasons.
        """
        logger.info(f"Fetching email: inbox={inbox_address}, email_id={email_id}")

        try:
            client = await self._get_client()
            # URL encode the email address
            encoded_inbox = inbox_address.replace("@", "%40")
            url = f"/api/inboxes/{encoded_inbox}/emails/{email_id}"

            response = await client.get(url)

            if response.status_code == 200:
                data = response.json()
                attachments = [
                    Attachment(
                        filename=att["filename"],
                        content_type=att["content_type"],
                        content_base64=att["content_base64"],
                        size_bytes=att["size_bytes"],
                    )
                    for att in data.get("attachments", [])
                ]
                email = Email(
                    email_id=UUID(data["id"]),
                    from_address=data["from_address"],
                    to_addresses=data["to_addresses"],
                    subject=data.get("subject", ""),
                    body_text=data.get("body_text"),
                    body_html=data.get("body_html"),
                    attachments=attachments,
                    headers=data.get("headers", {}),
                    received_at=data.get("received_at", ""),
                )
                logger.info(
                    f"Email fetched successfully: id={email_id}, "
                    f"from={email.from_address}, attachments={len(attachments)}"
                )
                return email

            if response.status_code == 404:
                error_detail = response.json().get("detail", "Not found")
                if "inbox" in error_detail.lower():
                    logger.warning(f"Inbox not found: {inbox_address}")
                    raise InboxNotFoundError(f"Inbox not found: {inbox_address}")
                else:
                    logger.warning(f"Email not found: {email_id}")
                    raise EmailNotFoundError(f"Email not found: {email_id}")

            error_msg = f"Failed to fetch email: status={response.status_code}"
            logger.error(error_msg)
            raise EmailFetchError(error_msg)

        except httpx.RequestError as e:
            error_msg = f"HTTP request failed while fetching email: {e}"
            logger.error(error_msg)
            raise EmailFetchError(error_msg) from e

    async def list_emails(
        self,
        inbox_address: str,
    ) -> list[EmailSummary]:
        """
        List all emails in an inbox.

        Args:
            inbox_address: Email address of the inbox.

        Returns:
            List of email summaries.

        Raises:
            InboxNotFoundError: If inbox does not exist.
            EmailFetchError: If listing fails.
        """
        logger.info(f"Listing emails for inbox: {inbox_address}")

        try:
            client = await self._get_client()
            encoded_inbox = inbox_address.replace("@", "%40")
            url = f"/api/inboxes/{encoded_inbox}"

            response = await client.get(url)

            if response.status_code == 200:
                data = response.json()
                emails = [
                    EmailSummary(
                        email_id=UUID(email["id"]),
                        from_address=email["from_address"],
                        to_addresses=email["to_addresses"],
                        subject=email.get("subject", ""),
                        has_attachments=email.get("has_attachments", False),
                        attachment_count=email.get("attachment_count", 0),
                        received_at=email.get("received_at", ""),
                    )
                    for email in data
                ]
                logger.info(f"Listed {len(emails)} emails for inbox: {inbox_address}")
                return emails

            if response.status_code == 404:
                logger.warning(f"Inbox not found: {inbox_address}")
                raise InboxNotFoundError(f"Inbox not found: {inbox_address}")

            error_msg = f"Failed to list emails: status={response.status_code}"
            logger.error(error_msg)
            raise EmailFetchError(error_msg)

        except httpx.RequestError as e:
            error_msg = f"HTTP request failed while listing emails: {e}"
            logger.error(error_msg)
            raise EmailFetchError(error_msg) from e

    async def clear_inbox(self, inbox_address: str) -> bool:
        """
        Clear all emails from an inbox.

        Args:
            inbox_address: Email address of the inbox to clear.

        Returns:
            True if cleared successfully.

        Raises:
            InboxClientError: If clearing fails.
        """
        logger.info(f"Clearing inbox: {inbox_address}")

        try:
            client = await self._get_client()
            encoded_inbox = inbox_address.replace("@", "%40")
            url = f"/api/inboxes/{encoded_inbox}"

            response = await client.delete(url)

            if response.status_code == 204:
                logger.info(f"Inbox cleared: {inbox_address}")
                return True

            if response.status_code == 404:
                logger.warning(f"Inbox not found for clearing: {inbox_address}")
                return False

            error_msg = f"Failed to clear inbox: status={response.status_code}"
            logger.error(error_msg)
            raise InboxClientError(error_msg)

        except httpx.RequestError as e:
            error_msg = f"HTTP request failed while clearing inbox: {e}"
            logger.error(error_msg)
            raise InboxClientError(error_msg) from e

    async def clear_all(self) -> bool:
        """
        Clear all inboxes on the server.

        Returns:
            True if cleared successfully.
        """
        logger.info("Clearing all inboxes")

        try:
            client = await self._get_client()
            response = await client.delete("/api/clear")

            if response.status_code == 204:
                logger.info("All inboxes cleared")
                return True

            error_msg = f"Failed to clear all inboxes: status={response.status_code}"
            logger.error(error_msg)
            raise InboxClientError(error_msg)

        except httpx.RequestError as e:
            error_msg = f"HTTP request failed while clearing all inboxes: {e}"
            logger.error(error_msg)
            raise InboxClientError(error_msg) from e
