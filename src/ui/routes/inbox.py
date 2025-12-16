"""
Inbox API routes.

Handles inbox operations: listing, viewing, replying.
"""

import base64
import logging
from typing import Annotated

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, Response

from ui.main import get_resources
from ui.services.smtp_client import (
    EmailNotFoundError,
    InboxNotFoundError,
    SMTPClientError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/inbox", tags=["Inbox"])


@router.get("/list", response_class=HTMLResponse)
async def list_inboxes(request: Request) -> HTMLResponse:
    """
    List all inboxes.

    Returns HTML partial with inbox list.
    """
    logger.info("Listing all inboxes")
    resources = get_resources()

    try:
        inboxes = await resources.smtp_client.list_inboxes()

        return resources.templates.TemplateResponse(
            "partials/inbox_list.html",
            {
                "request": request,
                "inboxes": inboxes,
            },
        )
    except SMTPClientError as e:
        logger.error("SMTP error listing inboxes: %s", e)
        return resources.templates.TemplateResponse(
            "partials/error.html",
            {
                "request": request,
                "error": str(e),
                "title": "Failed to Load Inboxes",
            },
        )


@router.get("/{email_address}/emails", response_class=HTMLResponse)
async def list_emails(request: Request, email_address: str) -> HTMLResponse:
    """
    List emails in an inbox.

    Args:
        email_address: The inbox email address.

    Returns HTML partial with email list.
    """
    logger.info("Listing emails for inbox: %s", email_address)
    resources = get_resources()

    try:
        emails = await resources.smtp_client.get_inbox(email_address)

        return resources.templates.TemplateResponse(
            "partials/email_list.html",
            {
                "request": request,
                "emails": emails,
                "inbox_address": email_address,
            },
        )
    except InboxNotFoundError:
        logger.warning("Inbox not found: %s", email_address)
        return resources.templates.TemplateResponse(
            "partials/email_list.html",
            {
                "request": request,
                "emails": [],
                "inbox_address": email_address,
                "empty_message": f"No emails found for {email_address}",
            },
        )
    except SMTPClientError as e:
        logger.error("SMTP error listing emails: %s", e)
        return resources.templates.TemplateResponse(
            "partials/error.html",
            {
                "request": request,
                "error": str(e),
                "title": "Failed to Load Emails",
            },
        )


@router.get("/{email_address}/emails/{email_id}", response_class=HTMLResponse)
async def get_email_detail(
    request: Request,
    email_address: str,
    email_id: str,
) -> HTMLResponse:
    """
    Get email detail.

    Args:
        email_address: The inbox email address.
        email_id: The email ID.

    Returns HTML partial with email detail.
    """
    logger.info("Getting email detail: %s from %s", email_id, email_address)
    resources = get_resources()

    try:
        email = await resources.smtp_client.get_email(email_address, email_id)

        return resources.templates.TemplateResponse(
            "inbox/email_detail.html",
            {
                "request": request,
                "email": email,
                "inbox_address": email_address,
            },
        )
    except EmailNotFoundError:
        logger.warning("Email not found: %s", email_id)
        return resources.templates.TemplateResponse(
            "partials/error.html",
            {
                "request": request,
                "error": f"Email not found: {email_id}",
                "title": "Email Not Found",
            },
        )
    except SMTPClientError as e:
        logger.error("SMTP error getting email: %s", e)
        return resources.templates.TemplateResponse(
            "partials/error.html",
            {
                "request": request,
                "error": str(e),
                "title": "Failed to Load Email",
            },
        )


@router.get("/{email_address}/emails/{email_id}/attachment/{attachment_index}")
async def download_attachment(
    email_address: str,
    email_id: str,
    attachment_index: int,
) -> Response:
    """
    Download an email attachment.

    Args:
        email_address: The inbox email address.
        email_id: The email ID.
        attachment_index: The attachment index.

    Returns the attachment file.
    """
    logger.info("Downloading attachment %d from email %s", attachment_index, email_id)
    resources = get_resources()

    try:
        email = await resources.smtp_client.get_email(email_address, email_id)

        if attachment_index < 0 or attachment_index >= len(email.attachments):
            return Response(
                content="Attachment not found",
                status_code=404,
                media_type="text/plain",
            )

        attachment = email.attachments[attachment_index]
        content = base64.b64decode(attachment.content_base64)

        return Response(
            content=content,
            media_type=attachment.content_type,
            headers={
                "Content-Disposition": f'attachment; filename="{attachment.filename}"'
            },
        )
    except EmailNotFoundError:
        logger.warning("Email not found: %s", email_id)
        return Response(
            content="Email not found",
            status_code=404,
            media_type="text/plain",
        )
    except SMTPClientError as e:
        logger.error("SMTP error downloading attachment: %s", e)
        return Response(
            content=str(e),
            status_code=500,
            media_type="text/plain",
        )


@router.get("/{email_address}/emails/{email_id}/reply-form", response_class=HTMLResponse)
async def get_reply_form(
    request: Request,
    email_address: str,
    email_id: str,
) -> HTMLResponse:
    """
    Get the reply form for an email.

    Args:
        email_address: The inbox email address.
        email_id: The email ID to reply to.

    Returns HTML partial with reply form.
    """
    logger.info("Getting reply form for email: %s", email_id)
    resources = get_resources()

    try:
        email = await resources.smtp_client.get_email(email_address, email_id)

        # Prepare reply subject
        subject = email.subject
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"

        return resources.templates.TemplateResponse(
            "inbox/reply_form.html",
            {
                "request": request,
                "original_email": email,
                "inbox_address": email_address,
                "reply_subject": subject,
                "reply_to": email.from_address,
            },
        )
    except EmailNotFoundError:
        logger.warning("Email not found: %s", email_id)
        return resources.templates.TemplateResponse(
            "partials/error.html",
            {
                "request": request,
                "error": f"Email not found: {email_id}",
                "title": "Email Not Found",
            },
        )
    except SMTPClientError as e:
        logger.error("SMTP error getting email for reply: %s", e)
        return resources.templates.TemplateResponse(
            "partials/error.html",
            {
                "request": request,
                "error": str(e),
                "title": "Failed to Load Email",
            },
        )


@router.post("/send-reply", response_class=HTMLResponse)
async def send_reply(
    request: Request,
    from_address: str = Form(...),
    to_address: str = Form(...),
    subject: str = Form(...),
    body: str = Form(...),
    attachment: Annotated[UploadFile | None, File()] = None,
) -> HTMLResponse:
    """
    Send a reply email with optional attachment.

    Args:
        from_address: Sender email address.
        to_address: Recipient email address.
        subject: Email subject.
        body: Email body text.
        attachment: Optional file attachment.

    Returns HTML partial with result.
    """
    logger.info("Sending reply from %s to %s: %s", from_address, to_address, subject)
    resources = get_resources()

    try:
        # Prepare attachments
        attachments = None
        if attachment and attachment.filename:
            content = await attachment.read()
            content_type = attachment.content_type or "application/octet-stream"
            attachments = [(attachment.filename, content_type, content)]
            logger.info("Reply includes attachment: %s (%d bytes)", attachment.filename, len(content))

        # Send the email
        email_id = await resources.smtp_client.send_email(
            from_address=from_address,
            to_addresses=[to_address],
            subject=subject,
            body=body,
            attachments=attachments,
        )

        logger.info("Reply sent successfully: %s", email_id)

        return resources.templates.TemplateResponse(
            "partials/reply_sent.html",
            {
                "request": request,
                "email_id": email_id,
                "to_address": to_address,
                "success": True,
            },
        )
    except SMTPClientError as e:
        logger.error("SMTP error sending reply: %s", e)
        return resources.templates.TemplateResponse(
            "partials/reply_sent.html",
            {
                "request": request,
                "error": str(e),
                "success": False,
            },
        )
    except Exception as e:
        logger.error("Unexpected error sending reply: %s", e)
        return resources.templates.TemplateResponse(
            "partials/reply_sent.html",
            {
                "request": request,
                "error": f"Unexpected error: {e}",
                "success": False,
            },
        )
