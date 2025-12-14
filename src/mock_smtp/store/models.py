"""Data models for email storage."""

import base64
from datetime import datetime
from typing import Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, EmailStr, Field


class Attachment(BaseModel):
    """
    Email attachment model.

    Stores attachment metadata and content in base64 encoding.
    """

    filename: str = Field(
        ...,
        description="Original filename of the attachment",
        min_length=1
    )
    content_type: str = Field(
        ...,
        description="MIME content type (e.g., 'image/png')",
        min_length=1
    )
    content_base64: str = Field(
        ...,
        description="Base64-encoded attachment content",
        min_length=1
    )
    size_bytes: int = Field(
        ...,
        description="Size of the attachment in bytes",
        ge=0
    )

    @property
    def content_decoded(self) -> bytes:
        """Decode base64 content to bytes."""
        return base64.b64decode(self.content_base64)

    @classmethod
    def from_bytes(
        cls,
        filename: str,
        content_type: str,
        content: bytes
    ) -> "Attachment":
        """
        Create an Attachment from raw bytes.

        Args:
            filename: Name of the file
            content_type: MIME type
            content: Raw bytes of the attachment

        Returns:
            Attachment instance
        """
        return cls(
            filename=filename,
            content_type=content_type,
            content_base64=base64.b64encode(content).decode("utf-8"),
            size_bytes=len(content)
        )


class Email(BaseModel):
    """
    Email message model.

    Represents a complete email with headers, body, and attachments.
    """

    id: UUID = Field(
        default_factory=uuid4,
        description="Unique identifier for the email"
    )
    from_address: str = Field(
        ...,
        description="Sender email address",
        min_length=1
    )
    to_addresses: List[str] = Field(
        ...,
        description="List of recipient email addresses",
        min_length=1
    )
    subject: str = Field(
        default="",
        description="Email subject line"
    )
    body_text: Optional[str] = Field(
        default=None,
        description="Plain text body content"
    )
    body_html: Optional[str] = Field(
        default=None,
        description="HTML body content"
    )
    attachments: List[Attachment] = Field(
        default_factory=list,
        description="List of email attachments"
    )
    headers: Dict[str, str] = Field(
        default_factory=dict,
        description="Additional email headers"
    )
    received_at: datetime = Field(
        default_factory=lambda: datetime.now(__import__('datetime').timezone.utc),
        description="Timestamp when email was received"
    )
    raw_content: Optional[str] = Field(
        default=None,
        description="Raw email content (RFC 5322 format)"
    )

    @property
    def has_attachments(self) -> bool:
        """Check if email has attachments."""
        return len(self.attachments) > 0

    @property
    def total_attachment_size(self) -> int:
        """Calculate total size of all attachments in bytes."""
        return sum(att.size_bytes for att in self.attachments)

    @property
    def is_multipart(self) -> bool:
        """Check if email has both text and HTML parts."""
        return self.body_text is not None and self.body_html is not None


class Inbox(BaseModel):
    """
    Inbox model representing a collection of emails for a recipient.

    Inboxes are created implicitly when the first email arrives for
    a recipient address.
    """

    email_address: str = Field(
        ...,
        description="Email address for this inbox",
        min_length=1
    )
    emails: List[Email] = Field(
        default_factory=list,
        description="List of emails in this inbox"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(__import__('datetime').timezone.utc),
        description="Timestamp when inbox was created"
    )
    last_email_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp of the most recent email"
    )

    @property
    def email_count(self) -> int:
        """Get the number of emails in this inbox."""
        return len(self.emails)

    def add_email(self, email: Email) -> None:
        """
        Add an email to this inbox.

        Args:
            email: Email to add

        Raises:
            ValueError: If email recipient doesn't match inbox address
        """
        if self.email_address not in email.to_addresses:
            raise ValueError(
                f"Email recipient '{email.to_addresses}' does not match "
                f"inbox address '{self.email_address}'"
            )

        self.emails.append(email)
        self.last_email_at = email.received_at

    def get_email_by_id(self, email_id: UUID) -> Optional[Email]:
        """
        Find an email by its ID.

        Args:
            email_id: UUID of the email

        Returns:
            Email if found, None otherwise
        """
        for email in self.emails:
            if email.id == email_id:
                return email
        return None

    def delete_email(self, email_id: UUID) -> bool:
        """
        Delete an email by its ID.

        Args:
            email_id: UUID of the email to delete

        Returns:
            True if email was deleted, False if not found
        """
        for idx, email in enumerate(self.emails):
            if email.id == email_id:
                self.emails.pop(idx)
                return True
        return False

    def clear(self) -> int:
        """
        Clear all emails from this inbox.

        Returns:
            Number of emails that were deleted
        """
        count = len(self.emails)
        self.emails.clear()
        self.last_email_at = None
        return count


class InboxSummary(BaseModel):
    """
    Summary information about an inbox.

    Used for API responses that don't need full email content.
    """

    email_address: str = Field(
        ...,
        description="Email address for this inbox"
    )
    email_count: int = Field(
        ...,
        description="Number of emails in this inbox",
        ge=0
    )
    created_at: datetime = Field(
        ...,
        description="Timestamp when inbox was created"
    )
    last_email_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp of the most recent email"
    )


class EmailSummary(BaseModel):
    """
    Summary information about an email.

    Used for API list responses to avoid returning full email content.
    """

    id: UUID = Field(
        ...,
        description="Unique identifier for the email"
    )
    from_address: str = Field(
        ...,
        description="Sender email address"
    )
    to_addresses: List[str] = Field(
        ...,
        description="List of recipient email addresses"
    )
    subject: str = Field(
        ...,
        description="Email subject line"
    )
    has_attachments: bool = Field(
        ...,
        description="Whether email has attachments"
    )
    received_at: datetime = Field(
        ...,
        description="Timestamp when email was received"
    )

    @classmethod
    def from_email(cls, email: Email) -> "EmailSummary":
        """
        Create an EmailSummary from a full Email.

        Args:
            email: Full Email instance

        Returns:
            EmailSummary instance
        """
        return cls(
            id=email.id,
            from_address=email.from_address,
            to_addresses=email.to_addresses,
            subject=email.subject,
            has_attachments=email.has_attachments,
            received_at=email.received_at
        )
