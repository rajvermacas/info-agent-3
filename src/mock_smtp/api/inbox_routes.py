"""API routes for inbox management."""

import logging
from typing import List

from fastapi import APIRouter, HTTPException, status

from mock_smtp.store.inbox_store import InboxStore
from mock_smtp.store.models import EmailSummary, Inbox, InboxSummary

logger = logging.getLogger(__name__)

router = APIRouter()


def create_inbox_router(inbox_store: InboxStore) -> APIRouter:
    """
    Create inbox router with dependency injection.

    Args:
        inbox_store: InboxStore instance

    Returns:
        Configured APIRouter
    """

    @router.get(
        "/inboxes",
        response_model=List[InboxSummary],
        summary="List all inboxes",
        description="Get summary information for all inboxes"
    )
    async def list_inboxes():
        """List all inboxes with email counts."""
        logger.info("GET /api/inboxes")
        summaries = inbox_store.get_inbox_summaries()
        logger.debug(f"Returning {len(summaries)} inbox summaries")
        return summaries

    @router.get(
        "/inboxes/{email_address}",
        response_model=List[EmailSummary],
        summary="Get emails for an inbox",
        description="Get all emails in a specific inbox"
    )
    async def get_inbox_emails(email_address: str):
        """
        Get all emails for a specific inbox.

        Args:
            email_address: Email address of the inbox

        Returns:
            List of email summaries

        Raises:
            404: If inbox not found
        """
        logger.info(f"GET /api/inboxes/{email_address}")

        inbox = inbox_store.get_inbox(email_address)
        if not inbox:
            logger.warning(f"Inbox '{email_address}' not found")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Inbox '{email_address}' not found"
            )

        email_summaries = [
            EmailSummary.from_email(email)
            for email in inbox.emails
        ]

        logger.debug(
            f"Returning {len(email_summaries)} emails "
            f"for inbox '{email_address}'"
        )
        return email_summaries

    @router.delete(
        "/inboxes/{email_address}",
        summary="Clear an inbox",
        description="Delete all emails from a specific inbox"
    )
    async def clear_inbox(email_address: str):
        """
        Clear all emails from an inbox.

        Args:
            email_address: Email address of the inbox

        Returns:
            Success message with count

        Raises:
            404: If inbox not found
        """
        logger.info(f"DELETE /api/inboxes/{email_address}")

        if not inbox_store.inbox_exists(email_address):
            logger.warning(f"Inbox '{email_address}' not found for clearing")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Inbox '{email_address}' not found"
            )

        count = inbox_store.clear_inbox(email_address)
        logger.info(f"Cleared {count} emails from inbox '{email_address}'")

        return {
            "message": f"Cleared {count} emails from inbox '{email_address}'",
            "deleted_count": count
        }

    return router
