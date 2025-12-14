"""Tests for data models."""

import base64
from datetime import datetime

import pytest

from mock_smtp.store.models import Attachment, Email, EmailSummary, Inbox


class TestAttachment:
    """Tests for Attachment model."""

    def test_create_from_bytes(self):
        """Test creating attachment from raw bytes."""
        content = b"Hello, World!"
        att = Attachment.from_bytes(
            filename="test.txt",
            content_type="text/plain",
            content=content
        )

        assert att.filename == "test.txt"
        assert att.content_type == "text/plain"
        assert att.size_bytes == len(content)
        assert att.content_decoded == content

    def test_content_encoded_correctly(self):
        """Test base64 encoding/decoding."""
        content = b"Test content"
        att = Attachment.from_bytes(
            filename="file.bin",
            content_type="application/octet-stream",
            content=content
        )

        # Check encoding
        expected_b64 = base64.b64encode(content).decode("utf-8")
        assert att.content_base64 == expected_b64

        # Check decoding
        assert att.content_decoded == content


class TestEmail:
    """Tests for Email model."""

    def test_create_email_minimal(self):
        """Test creating email with minimal fields."""
        email = Email(
            from_address="sender@example.com",
            to_addresses=["recipient@example.com"]
        )

        assert email.from_address == "sender@example.com"
        assert email.to_addresses == ["recipient@example.com"]
        assert email.subject == ""
        assert email.body_text is None
        assert email.body_html is None
        assert len(email.attachments) == 0

    def test_create_email_full(self, sample_attachment):
        """Test creating email with all fields."""
        email = Email(
            from_address="sender@example.com",
            to_addresses=["recipient@example.com"],
            subject="Test Subject",
            body_text="Plain text",
            body_html="<p>HTML</p>",
            attachments=[sample_attachment]
        )

        assert email.subject == "Test Subject"
        assert email.body_text == "Plain text"
        assert email.body_html == "<p>HTML</p>"
        assert len(email.attachments) == 1

    def test_has_attachments_property(self):
        """Test has_attachments property."""
        email = Email(
            from_address="sender@example.com",
            to_addresses=["recipient@example.com"]
        )
        assert email.has_attachments is False

        email.attachments = [
            Attachment.from_bytes("test.txt", "text/plain", b"content")
        ]
        assert email.has_attachments is True

    def test_is_multipart_property(self):
        """Test is_multipart property."""
        email = Email(
            from_address="sender@example.com",
            to_addresses=["recipient@example.com"],
            body_text="Plain text"
        )
        assert email.is_multipart is False

        email.body_html = "<p>HTML</p>"
        assert email.is_multipart is True


class TestInbox:
    """Tests for Inbox model."""

    def test_create_inbox(self):
        """Test creating an inbox."""
        inbox = Inbox(email_address="test@example.com")

        assert inbox.email_address == "test@example.com"
        assert inbox.email_count == 0
        assert inbox.last_email_at is None

    def test_add_email(self):
        """Test adding an email to inbox."""
        inbox = Inbox(email_address="test@example.com")
        email = Email(
            from_address="sender@example.com",
            to_addresses=["test@example.com"]
        )

        inbox.add_email(email)

        assert inbox.email_count == 1
        assert inbox.last_email_at is not None

    def test_add_email_wrong_recipient_raises_error(self):
        """Test adding email to wrong inbox raises error."""
        inbox = Inbox(email_address="test@example.com")
        email = Email(
            from_address="sender@example.com",
            to_addresses=["other@example.com"]
        )

        with pytest.raises(ValueError, match="does not match"):
            inbox.add_email(email)

    def test_get_email_by_id(self):
        """Test retrieving email by ID."""
        inbox = Inbox(email_address="test@example.com")
        email = Email(
            from_address="sender@example.com",
            to_addresses=["test@example.com"]
        )
        inbox.add_email(email)

        retrieved = inbox.get_email_by_id(email.id)
        assert retrieved is not None
        assert retrieved.id == email.id

    def test_delete_email(self):
        """Test deleting an email."""
        inbox = Inbox(email_address="test@example.com")
        email = Email(
            from_address="sender@example.com",
            to_addresses=["test@example.com"]
        )
        inbox.add_email(email)

        assert inbox.email_count == 1

        deleted = inbox.delete_email(email.id)
        assert deleted is True
        assert inbox.email_count == 0

    def test_clear_inbox(self):
        """Test clearing all emails."""
        inbox = Inbox(email_address="test@example.com")

        for i in range(5):
            email = Email(
                from_address="sender@example.com",
                to_addresses=["test@example.com"],
                subject=f"Email {i}"
            )
            inbox.add_email(email)

        assert inbox.email_count == 5

        count = inbox.clear()
        assert count == 5
        assert inbox.email_count == 0
        assert inbox.last_email_at is None


class TestEmailSummary:
    """Tests for EmailSummary model."""

    def test_from_email(self):
        """Test creating EmailSummary from Email."""
        email = Email(
            from_address="sender@example.com",
            to_addresses=["recipient@example.com"],
            subject="Test Subject",
            attachments=[
                Attachment.from_bytes("test.txt", "text/plain", b"content")
            ]
        )

        summary = EmailSummary.from_email(email)

        assert summary.id == email.id
        assert summary.from_address == email.from_address
        assert summary.to_addresses == email.to_addresses
        assert summary.subject == email.subject
        assert summary.has_attachments is True
        assert summary.received_at == email.received_at
