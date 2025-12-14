"""API routes for individual email management."""

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from mock_smtp.store.inbox_store import InboxStore
from mock_smtp.store.models import Email

logger = logging.getLogger(__name__)


def create_email_router(inbox_store: InboxStore) -> APIRouter:
    """
    Create email router with dependency injection.

    Args:
        inbox_store: InboxStore instance

    Returns:
        Configured APIRouter
    """
    # Create fresh router each time to avoid closure issues with reused singletons
    router = APIRouter()

    @router.get(
        "/inboxes/{email_address}/emails/{email_id}",
        response_model=Email,
        summary="Get a specific email",
        description="Get complete details of a specific email"
    )
    async def get_email(email_address: str, email_id: UUID):
        """
        Get a specific email from an inbox.

        Args:
            email_address: Email address of the inbox
            email_id: UUID of the email

        Returns:
            Complete Email object

        Raises:
            404: If inbox or email not found
        """
        logger.info(
            f"GET /api/inboxes/{email_address}/emails/{email_id}"
        )

        email = inbox_store.get_email(email_address, email_id)
        if not email:
            logger.warning(
                f"Email {email_id} not found in inbox '{email_address}'"
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Email not found in inbox '{email_address}'"
            )

        logger.debug(f"Returning email {email_id}")
        return email

    @router.delete(
        "/inboxes/{email_address}/emails/{email_id}",
        summary="Delete an email",
        description="Delete a specific email from an inbox"
    )
    async def delete_email(email_address: str, email_id: UUID):
        """
        Delete a specific email from an inbox.

        Args:
            email_address: Email address of the inbox
            email_id: UUID of the email

        Returns:
            Success message

        Raises:
            404: If inbox or email not found
        """
        logger.info(
            f"DELETE /api/inboxes/{email_address}/emails/{email_id}"
        )

        deleted = inbox_store.delete_email(email_address, email_id)
        if not deleted:
            logger.warning(
                f"Email {email_id} not found in inbox '{email_address}' "
                f"for deletion"
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Email not found in inbox '{email_address}'"
            )

        logger.info(
            f"Deleted email {email_id} from inbox '{email_address}'"
        )

        return {
            "message": f"Email deleted from inbox '{email_address}'",
            "email_id": str(email_id)
        }

    @router.delete(
        "/clear",
        summary="Clear all inboxes",
        description="Delete all emails from all inboxes (reset server)"
    )
    async def clear_all():
        """
        Clear all inboxes and emails.

        Returns:
            Success message with count
        """
        logger.warning("DELETE /api/clear - Clearing all inboxes")

        total_emails = inbox_store.clear_all()
        logger.warning(f"Cleared all inboxes ({total_emails} total emails)")

        return {
            "message": "Cleared all inboxes",
            "deleted_count": total_emails
        }

    return router
