"""
Mock SMTP Client Service for UI.

Handles communication with the Mock SMTP server API.
"""

import base64
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import BinaryIO

import httpx

from ui.config import Settings

logger = logging.getLogger(__name__)


class SMTPClientError(Exception):
    """Base exception for SMTP client errors."""

    pass


class SMTPConnectionError(SMTPClientError):
    """Raised when connection to SMTP server fails."""

    pass


class InboxNotFoundError(SMTPClientError):
    """Raised when inbox is not found."""

    pass


class EmailNotFoundError(SMTPClientError):
    """Raised when email is not found."""

    pass


class EmailSendError(SMTPClientError):
    """Raised when sending email fails."""

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
    """Email data."""

    id: str
    from_address: str
    to_addresses: list[str]
    subject: str
    body_text: str | None = None
    body_html: str | None = None
    attachments: list[Attachment] = field(default_factory=list)
    received_at: datetime | None = None
    has_attachments: bool = False


@dataclass
class EmailSummary:
    """Lightweight email summary for list views."""

    id: str
    from_address: str
    subject: str
    received_at: datetime | None = None
    has_attachments: bool = False


@dataclass
class InboxSummary:
    """Inbox summary data."""

    email_address: str
    email_count: int
    last_email_at: datetime | None = None


class SMTPClientService:
    """
    Client service for Mock SMTP server communication.

    Handles:
    - Inbox listing
    - Email retrieval
    - Email sending with attachments
    """

    def __init__(self, settings: Settings):
        """
        Initialize the SMTP client service.

        Args:
            settings: UI settings containing SMTP server URL.
        """
        self._settings = settings
        self._client: httpx.AsyncClient | None = None
        self._base_url = settings.mock_smtp_api_url.rstrip("/")
        logger.info("SMTPClientService initialized with base URL: %s", self._base_url)

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._settings.http_timeout_seconds,
            )
            logger.debug("Created new httpx client for SMTP server")
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            logger.debug("SMTP client closed")

    async def list_inboxes(self) -> list[InboxSummary]:
        """
        List all inboxes.

        Returns:
            List of InboxSummary objects.

        Raises:
            SMTPConnectionError: If connection fails.
        """
        logger.info("Listing all inboxes")
        client = await self._get_client()

        try:
            response = await client.get("/api/inboxes")
            response.raise_for_status()
            data = response.json()

            inboxes = []
            for inbox_data in data:  # API returns List[InboxSummary] directly
                inboxes.append(
                    InboxSummary(
                        email_address=inbox_data.get("email_address", ""),
                        email_count=inbox_data.get("email_count", 0),
                        last_email_at=datetime.fromisoformat(inbox_data["last_email_at"]) if inbox_data.get("last_email_at") else None,
                    )
                )

            logger.info("Found %d inboxes", len(inboxes))
            return inboxes
        except httpx.ConnectError as e:
            logger.error("Failed to connect to SMTP server: %s", e)
            raise SMTPConnectionError(f"Cannot connect to SMTP server at {self._base_url}") from e
        except httpx.HTTPStatusError as e:
            logger.error("HTTP error listing inboxes: %s", e)
            raise SMTPConnectionError(f"HTTP error: {e.response.status_code}") from e
        except Exception as e:
            logger.error("Unexpected error listing inboxes: %s", e)
            raise SMTPConnectionError(f"Unexpected error: {e}") from e

    async def get_inbox(self, email_address: str) -> list[EmailSummary]:
        """
        Get emails in an inbox.

        Args:
            email_address: The inbox email address.

        Returns:
            List of EmailSummary objects.

        Raises:
            InboxNotFoundError: If inbox doesn't exist.
            SMTPConnectionError: If connection fails.
        """
        logger.info("Getting inbox for: %s", email_address)
        client = await self._get_client()

        try:
            response = await client.get(f"/api/inboxes/{email_address}")
            response.raise_for_status()
            data = response.json()

            emails = []
            for email_data in data:  # API returns List[EmailSummary] directly
                emails.append(
                    EmailSummary(
                        id=email_data.get("id", ""),
                        from_address=email_data.get("from_address", ""),
                        subject=email_data.get("subject", "(No Subject)"),
                        received_at=datetime.fromisoformat(email_data["received_at"]) if email_data.get("received_at") else None,
                        has_attachments=email_data.get("has_attachments", False),
                    )
                )

            logger.info("Found %d emails in inbox %s", len(emails), email_address)
            return emails
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.warning("Inbox not found: %s", email_address)
                raise InboxNotFoundError(f"Inbox not found: {email_address}") from e
            logger.error("HTTP error getting inbox: %s", e)
            raise SMTPConnectionError(f"HTTP error: {e.response.status_code}") from e
        except Exception as e:
            logger.error("Unexpected error getting inbox: %s", e)
            raise SMTPConnectionError(f"Unexpected error: {e}") from e

    async def get_email(self, email_address: str, email_id: str) -> Email:
        """
        Get a specific email.

        Args:
            email_address: The inbox email address.
            email_id: The email ID.

        Returns:
            Email object with full details.

        Raises:
            EmailNotFoundError: If email doesn't exist.
            SMTPConnectionError: If connection fails.
        """
        logger.info("Getting email %s from inbox %s", email_id, email_address)
        client = await self._get_client()

        try:
            response = await client.get(f"/api/inboxes/{email_address}/emails/{email_id}")
            response.raise_for_status()
            data = response.json()

            # Parse attachments from API response
            raw_attachments = data.get("attachments", [])
            logger.debug(
                "API response contains %d attachments in data",
                len(raw_attachments),
            )

            attachments = []
            for att_data in raw_attachments:
                att = Attachment(
                    filename=att_data.get("filename", ""),
                    content_type=att_data.get("content_type", "application/octet-stream"),
                    content_base64=att_data.get("content_base64", ""),
                    size_bytes=att_data.get("size_bytes", 0),
                )
                attachments.append(att)
                logger.debug(
                    "Parsed attachment: %s (%s, %d bytes)",
                    att.filename,
                    att.content_type,
                    att.size_bytes,
                )

            email = Email(
                id=data.get("id", email_id),
                from_address=data.get("from_address", ""),
                to_addresses=data.get("to_addresses", []),
                subject=data.get("subject", "(No Subject)"),
                body_text=data.get("body_text"),
                body_html=data.get("body_html"),
                attachments=attachments,
                received_at=datetime.fromisoformat(data["received_at"]) if data.get("received_at") else None,
                has_attachments=len(attachments) > 0,
            )

            logger.info(
                "Retrieved email: %s (has_attachments=%s, attachment_count=%d)",
                email.subject,
                email.has_attachments,
                len(email.attachments),
            )
            return email
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.warning("Email not found: %s in inbox %s", email_id, email_address)
                raise EmailNotFoundError(f"Email not found: {email_id}") from e
            logger.error("HTTP error getting email: %s", e)
            raise SMTPConnectionError(f"HTTP error: {e.response.status_code}") from e
        except Exception as e:
            logger.error("Unexpected error getting email: %s", e)
            raise SMTPConnectionError(f"Unexpected error: {e}") from e

    async def send_email(
        self,
        from_address: str,
        to_addresses: list[str],
        subject: str,
        body: str,
        attachments: list[tuple[str, str, bytes]] | None = None,
    ) -> str:
        """
        Send an email via the Mock SMTP API.

        Args:
            from_address: Sender email address.
            to_addresses: List of recipient email addresses.
            subject: Email subject.
            body: Email body text.
            attachments: Optional list of (filename, content_type, content_bytes) tuples.

        Returns:
            The ID of the sent email.

        Raises:
            EmailSendError: If sending fails.
        """
        logger.info("Sending email from %s to %s: %s", from_address, to_addresses, subject)
        client = await self._get_client()

        try:
            # Build request payload
            payload = {
                "from_address": from_address,
                "to_addresses": to_addresses,
                "subject": subject,
                "body_text": body,
            }

            # Add attachments if provided
            if attachments:
                payload["attachments"] = []
                for filename, content_type, content_bytes in attachments:
                    payload["attachments"].append({
                        "filename": filename,
                        "content_type": content_type,
                        "content_base64": base64.b64encode(content_bytes).decode("utf-8"),
                    })
                logger.debug("Added %d attachments to email", len(attachments))

            response = await client.post("/api/send", json=payload)
            response.raise_for_status()
            data = response.json()

            email_id = data.get("email_id", "")
            logger.info("Email sent successfully: %s", email_id)
            return email_id
        except httpx.HTTPStatusError as e:
            logger.error("HTTP error sending email: %s", e)
            try:
                error_detail = e.response.json().get("detail", str(e))
            except Exception:
                error_detail = str(e)
            raise EmailSendError(f"Failed to send email: {error_detail}") from e
        except Exception as e:
            logger.error("Unexpected error sending email: %s", e)
            raise EmailSendError(f"Unexpected error: {e}") from e

    async def delete_email(self, email_address: str, email_id: str) -> bool:
        """
        Delete an email.

        Args:
            email_address: The inbox email address.
            email_id: The email ID to delete.

        Returns:
            True if deleted successfully.

        Raises:
            EmailNotFoundError: If email doesn't exist.
            SMTPConnectionError: If connection fails.
        """
        logger.info("Deleting email %s from inbox %s", email_id, email_address)
        client = await self._get_client()

        try:
            response = await client.delete(f"/api/inboxes/{email_address}/emails/{email_id}")
            response.raise_for_status()
            logger.info("Email deleted: %s", email_id)
            return True
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.warning("Email not found for deletion: %s", email_id)
                raise EmailNotFoundError(f"Email not found: {email_id}") from e
            logger.error("HTTP error deleting email: %s", e)
            raise SMTPConnectionError(f"HTTP error: {e.response.status_code}") from e
        except Exception as e:
            logger.error("Unexpected error deleting email: %s", e)
            raise SMTPConnectionError(f"Unexpected error: {e}") from e

    async def check_health(self) -> bool:
        """
        Check if SMTP server is healthy.

        Returns:
            True if healthy, False otherwise.
        """
        try:
            client = await self._get_client()
            response = await client.get("/api/health")
            return response.status_code == 200
        except Exception as e:
            logger.warning("SMTP health check failed: %s", e)
            return False
