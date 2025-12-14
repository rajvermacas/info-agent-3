"""Thread-safe in-memory storage for email inboxes."""

import logging
import threading
from typing import Dict, List, Optional
from uuid import UUID

from mock_smtp.store.models import Email, Inbox, InboxSummary

logger = logging.getLogger(__name__)


class InboxStore:
    """
    Thread-safe in-memory storage for email inboxes.

    This class provides CRUD operations for managing multiple inboxes and
    their emails. All operations are thread-safe using a lock.

    Attributes:
        _inboxes: Dictionary mapping email addresses to Inbox instances
        _lock: Threading lock for thread-safe operations
    """

    def __init__(self, max_emails_per_inbox: int = 1000):
        """
        Initialize the inbox store.

        Args:
            max_emails_per_inbox: Maximum emails per inbox before cleanup
        """
        self._inboxes: Dict[str, Inbox] = {}
        self._lock = threading.Lock()
        self._max_emails_per_inbox = max_emails_per_inbox
        logger.info(
            f"InboxStore initialized with max {max_emails_per_inbox} "
            f"emails per inbox"
        )

    def add_email(self, email: Email) -> None:
        """
        Add an email to the appropriate inbox(es).

        Creates inboxes implicitly if they don't exist. If an inbox reaches
        the maximum size, oldest emails are removed (FIFO).

        Args:
            email: Email to add

        Raises:
            ValueError: If email has no recipients
        """
        if not email.to_addresses:
            raise ValueError("Email must have at least one recipient")

        with self._lock:
            for recipient in email.to_addresses:
                # Create inbox if it doesn't exist
                if recipient not in self._inboxes:
                    self._inboxes[recipient] = Inbox(email_address=recipient)
                    logger.info(f"Created new inbox for '{recipient}'")

                inbox = self._inboxes[recipient]

                # Add email to inbox
                inbox.add_email(email)
                logger.debug(
                    f"Added email {email.id} to inbox '{recipient}' "
                    f"(total: {inbox.email_count})"
                )

                # Enforce max size by removing oldest emails
                if inbox.email_count > self._max_emails_per_inbox:
                    removed_count = (
                        inbox.email_count - self._max_emails_per_inbox
                    )
                    inbox.emails = inbox.emails[-self._max_emails_per_inbox:]
                    logger.warning(
                        f"Inbox '{recipient}' exceeded max size. "
                        f"Removed {removed_count} oldest emails"
                    )

    def get_inbox(self, email_address: str) -> Optional[Inbox]:
        """
        Get an inbox by email address.

        Args:
            email_address: Email address to lookup

        Returns:
            Inbox if found, None otherwise
        """
        with self._lock:
            inbox = self._inboxes.get(email_address)
            if inbox:
                logger.debug(
                    f"Retrieved inbox '{email_address}' "
                    f"({inbox.email_count} emails)"
                )
            else:
                logger.debug(f"Inbox '{email_address}' not found")
            return inbox

    def get_all_inboxes(self) -> List[Inbox]:
        """
        Get all inboxes.

        Returns:
            List of all Inbox instances
        """
        with self._lock:
            inboxes = list(self._inboxes.values())
            logger.debug(f"Retrieved {len(inboxes)} inboxes")
            return inboxes

    def get_inbox_summaries(self) -> List[InboxSummary]:
        """
        Get summary information for all inboxes.

        Returns:
            List of InboxSummary instances
        """
        with self._lock:
            summaries = [
                InboxSummary(
                    email_address=inbox.email_address,
                    email_count=inbox.email_count,
                    created_at=inbox.created_at,
                    last_email_at=inbox.last_email_at
                )
                for inbox in self._inboxes.values()
            ]
            logger.debug(f"Generated {len(summaries)} inbox summaries")
            return summaries

    def get_email(
        self,
        email_address: str,
        email_id: UUID
    ) -> Optional[Email]:
        """
        Get a specific email from an inbox.

        Args:
            email_address: Email address of the inbox
            email_id: UUID of the email

        Returns:
            Email if found, None otherwise
        """
        with self._lock:
            inbox = self._inboxes.get(email_address)
            if not inbox:
                logger.debug(
                    f"Inbox '{email_address}' not found when "
                    f"getting email {email_id}"
                )
                return None

            email = inbox.get_email_by_id(email_id)
            if email:
                logger.debug(
                    f"Retrieved email {email_id} from inbox '{email_address}'"
                )
            else:
                logger.debug(
                    f"Email {email_id} not found in inbox '{email_address}'"
                )
            return email

    def delete_email(
        self,
        email_address: str,
        email_id: UUID
    ) -> bool:
        """
        Delete a specific email from an inbox.

        Args:
            email_address: Email address of the inbox
            email_id: UUID of the email

        Returns:
            True if email was deleted, False otherwise
        """
        with self._lock:
            inbox = self._inboxes.get(email_address)
            if not inbox:
                logger.debug(
                    f"Inbox '{email_address}' not found when "
                    f"deleting email {email_id}"
                )
                return False

            deleted = inbox.delete_email(email_id)
            if deleted:
                logger.info(
                    f"Deleted email {email_id} from inbox '{email_address}'"
                )
            else:
                logger.debug(
                    f"Email {email_id} not found in inbox "
                    f"'{email_address}' for deletion"
                )
            return deleted

    def clear_inbox(self, email_address: str) -> int:
        """
        Clear all emails from an inbox.

        Args:
            email_address: Email address of the inbox

        Returns:
            Number of emails that were deleted
        """
        with self._lock:
            inbox = self._inboxes.get(email_address)
            if not inbox:
                logger.debug(
                    f"Inbox '{email_address}' not found when clearing"
                )
                return 0

            count = inbox.clear()
            logger.info(f"Cleared {count} emails from inbox '{email_address}'")
            return count

    def delete_inbox(self, email_address: str) -> bool:
        """
        Delete an entire inbox and all its emails.

        Args:
            email_address: Email address of the inbox

        Returns:
            True if inbox was deleted, False if not found
        """
        with self._lock:
            if email_address in self._inboxes:
                email_count = self._inboxes[email_address].email_count
                del self._inboxes[email_address]
                logger.info(
                    f"Deleted inbox '{email_address}' "
                    f"with {email_count} emails"
                )
                return True
            else:
                logger.debug(
                    f"Inbox '{email_address}' not found for deletion"
                )
                return False

    def clear_all(self) -> int:
        """
        Clear all inboxes and emails.

        Returns:
            Total number of emails that were deleted
        """
        with self._lock:
            total_emails = sum(
                inbox.email_count for inbox in self._inboxes.values()
            )
            inbox_count = len(self._inboxes)
            self._inboxes.clear()
            logger.warning(
                f"Cleared all {inbox_count} inboxes "
                f"({total_emails} total emails)"
            )
            return total_emails

    def inbox_exists(self, email_address: str) -> bool:
        """
        Check if an inbox exists.

        Args:
            email_address: Email address to check

        Returns:
            True if inbox exists, False otherwise
        """
        with self._lock:
            exists = email_address in self._inboxes
            logger.debug(f"Inbox '{email_address}' exists: {exists}")
            return exists

    @property
    def total_inboxes(self) -> int:
        """Get the total number of inboxes."""
        with self._lock:
            return len(self._inboxes)

    @property
    def total_emails(self) -> int:
        """Get the total number of emails across all inboxes."""
        with self._lock:
            return sum(inbox.email_count for inbox in self._inboxes.values())
