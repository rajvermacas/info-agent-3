"""Tests for InboxStore."""

import pytest
from uuid import uuid4

from mock_smtp.store.inbox_store import InboxStore
from mock_smtp.store.models import Email


class TestInboxStore:
    """Tests for InboxStore class."""

    def test_init(self):
        """Test InboxStore initialization."""
        store = InboxStore(max_emails_per_inbox=50)
        assert store.total_inboxes == 0
        assert store.total_emails == 0

    def test_add_email_creates_inbox(self, inbox_store, sample_email):
        """Test adding email creates inbox implicitly."""
        assert inbox_store.total_inboxes == 0

        inbox_store.add_email(sample_email)

        assert inbox_store.total_inboxes == 1
        assert inbox_store.total_emails == 1

    def test_add_email_no_recipients_raises_error(self, inbox_store):
        """Test adding email without recipients raises error."""
        # Creating Email with empty list will fail pydantic validation
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="at least 1 item"):
            email = Email(
                from_address="sender@example.com",
                to_addresses=[]
            )

    def test_add_email_multiple_recipients(self, inbox_store):
        """Test adding email to multiple inboxes."""
        email = Email(
            from_address="sender@example.com",
            to_addresses=["user1@example.com", "user2@example.com"]
        )

        inbox_store.add_email(email)

        assert inbox_store.total_inboxes == 2
        assert inbox_store.total_emails == 2

        inbox1 = inbox_store.get_inbox("user1@example.com")
        inbox2 = inbox_store.get_inbox("user2@example.com")

        assert inbox1.email_count == 1
        assert inbox2.email_count == 1

    def test_get_inbox(self, inbox_store, sample_email):
        """Test retrieving an inbox."""
        inbox_store.add_email(sample_email)

        inbox = inbox_store.get_inbox("recipient@example.com")
        assert inbox is not None
        assert inbox.email_address == "recipient@example.com"

    def test_get_inbox_not_found(self, inbox_store):
        """Test retrieving non-existent inbox."""
        inbox = inbox_store.get_inbox("nonexistent@example.com")
        assert inbox is None

    def test_get_all_inboxes(self, inbox_store):
        """Test getting all inboxes."""
        for i in range(3):
            email = Email(
                from_address="sender@example.com",
                to_addresses=[f"user{i}@example.com"]
            )
            inbox_store.add_email(email)

        inboxes = inbox_store.get_all_inboxes()
        assert len(inboxes) == 3

    def test_get_email(self, inbox_store, sample_email):
        """Test retrieving a specific email."""
        inbox_store.add_email(sample_email)

        email = inbox_store.get_email(
            "recipient@example.com",
            sample_email.id
        )
        assert email is not None
        assert email.id == sample_email.id

    def test_delete_email(self, inbox_store, sample_email):
        """Test deleting an email."""
        inbox_store.add_email(sample_email)
        assert inbox_store.total_emails == 1

        deleted = inbox_store.delete_email(
            "recipient@example.com",
            sample_email.id
        )
        assert deleted is True
        assert inbox_store.total_emails == 0

    def test_clear_inbox(self, inbox_store):
        """Test clearing all emails from an inbox."""
        for i in range(5):
            email = Email(
                from_address="sender@example.com",
                to_addresses=["test@example.com"],
                subject=f"Email {i}"
            )
            inbox_store.add_email(email)

        assert inbox_store.total_emails == 5

        count = inbox_store.clear_inbox("test@example.com")
        assert count == 5
        assert inbox_store.total_emails == 0

    def test_clear_all(self, inbox_store):
        """Test clearing all inboxes."""
        for i in range(3):
            email = Email(
                from_address="sender@example.com",
                to_addresses=[f"user{i}@example.com"]
            )
            inbox_store.add_email(email)

        assert inbox_store.total_inboxes == 3
        assert inbox_store.total_emails == 3

        total = inbox_store.clear_all()
        assert total == 3
        assert inbox_store.total_inboxes == 0
        assert inbox_store.total_emails == 0

    def test_max_emails_per_inbox_enforcement(self):
        """Test that old emails are removed when max is reached."""
        store = InboxStore(max_emails_per_inbox=5)

        # Add 10 emails
        for i in range(10):
            email = Email(
                from_address="sender@example.com",
                to_addresses=["test@example.com"],
                subject=f"Email {i}"
            )
            store.add_email(email)

        inbox = store.get_inbox("test@example.com")

        # Should only have 5 emails (most recent)
        assert inbox.email_count == 5

        # Check that it's the last 5 emails
        subjects = [e.subject for e in inbox.emails]
        assert "Email 9" in subjects
        assert "Email 0" not in subjects

    def test_inbox_exists(self, inbox_store, sample_email):
        """Test checking if inbox exists."""
        assert inbox_store.inbox_exists("test@example.com") is False

        inbox_store.add_email(sample_email)

        assert inbox_store.inbox_exists("recipient@example.com") is True
