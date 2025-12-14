"""API routes for sending emails directly (bypassing SMTP)."""

import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from mock_smtp.store.inbox_store import InboxStore
from mock_smtp.store.models import Email

logger = logging.getLogger(__name__)


class SendEmailRequest(BaseModel):
    """Request model for sending an email."""

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


def create_send_router(inbox_store: InboxStore) -> APIRouter:
    """
    Create send router with dependency injection.

    Args:
        inbox_store: InboxStore instance

    Returns:
        Configured APIRouter
    """
    # Create fresh router each time to avoid closure issues with reused singletons
    router = APIRouter()

    @router.post(
        "/send",
        status_code=status.HTTP_201_CREATED,
        summary="Send an email",
        description="Send an email directly to inbox(es) without using SMTP"
    )
    async def send_email(request: SendEmailRequest):
        """
        Send an email directly to inbox(es).

        This bypasses the SMTP server and stores the email directly
        in the recipient inboxes. Useful for testing and manual
        email creation.

        Args:
            request: SendEmailRequest with email details

        Returns:
            Created email details

        Raises:
            400: If request validation fails
        """
        logger.info(
            f"POST /api/send from={request.from_address} "
            f"to={request.to_addresses}"
        )

        # Validate that at least one body type is provided
        if not request.body_text and not request.body_html:
            logger.warning("Send request missing both text and HTML body")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email must have at least one of body_text or body_html"
            )

        # Create email
        email = Email(
            from_address=request.from_address,
            to_addresses=request.to_addresses,
            subject=request.subject,
            body_text=request.body_text,
            body_html=request.body_html
        )

        # Store in inboxes
        try:
            inbox_store.add_email(email)
            logger.info(
                f"Email {email.id} sent to {len(email.to_addresses)} "
                f"recipient(s)"
            )
        except Exception as e:
            logger.error(
                f"Error storing sent email: {type(e).__name__}: {e}",
                exc_info=True
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to store email: {type(e).__name__}"
            )

        return {
            "message": "Email sent successfully",
            "id": str(email.id),
            "from_address": email.from_address,
            "to_addresses": email.to_addresses,
            "subject": email.subject,
            "received_at": email.received_at.isoformat()
        }

    return router
