"""Custom SMTP handler for aiosmtpd."""

import asyncio
import email
import logging
from email import policy
from email.message import EmailMessage
from typing import Any

from mock_smtp.store.inbox_store import InboxStore
from mock_smtp.store.models import Attachment, Email
from mock_smtp.webhooks.dispatcher import WebhookDispatcher
from mock_smtp.webhooks.registry import WebhookRegistry

logger = logging.getLogger(__name__)


class SMTPHandler:
    """
    Custom SMTP handler for processing incoming emails.

    Handles SMTP commands and routes emails to the inbox store,
    triggering webhooks when configured.
    """

    def __init__(
        self,
        inbox_store: InboxStore,
        webhook_registry: WebhookRegistry,
        webhook_dispatcher: WebhookDispatcher,
        max_attachment_size: int
    ):
        """
        Initialize the SMTP handler.

        Args:
            inbox_store: InboxStore instance for storing emails
            webhook_registry: WebhookRegistry for finding webhooks
            webhook_dispatcher: WebhookDispatcher for sending notifications
            max_attachment_size: Maximum attachment size in bytes
        """
        self.inbox_store = inbox_store
        self.webhook_registry = webhook_registry
        self.webhook_dispatcher = webhook_dispatcher
        self.max_attachment_size = max_attachment_size
        logger.info("SMTPHandler initialized")

    async def handle_MAIL(
        self,
        server: Any,
        session: Any,
        envelope: Any,
        address: str,
        mail_options: list
    ) -> str:
        """
        Handle MAIL FROM command.

        Args:
            server: SMTP server instance
            session: SMTP session
            envelope: Envelope being built
            address: Sender address
            mail_options: ESMTP options

        Returns:
            SMTP response string
        """
        logger.debug(f"MAIL FROM: {address}")
        envelope.mail_from = address
        envelope.mail_options.extend(mail_options)
        return "250 OK"

    async def handle_RCPT(
        self,
        server: Any,
        session: Any,
        envelope: Any,
        address: str,
        rcpt_options: list
    ) -> str:
        """
        Handle RCPT TO command.

        Args:
            server: SMTP server instance
            session: SMTP session
            envelope: Envelope being built
            address: Recipient address
            rcpt_options: ESMTP options

        Returns:
            SMTP response string
        """
        logger.debug(f"RCPT TO: {address}")
        envelope.rcpt_tos.append(address)
        envelope.rcpt_options.extend(rcpt_options)
        return "250 OK"

    async def handle_DATA(
        self,
        server: Any,
        session: Any,
        envelope: Any
    ) -> str:
        """
        Handle DATA command - called after full message received.

        Parses the email, stores it, and triggers webhooks.

        Args:
            server: SMTP server instance
            session: SMTP session
            envelope: Complete envelope with message data

        Returns:
            SMTP response string
        """
        logger.info(
            f"Received email from {envelope.mail_from} "
            f"to {envelope.rcpt_tos}"
        )

        try:
            # Parse the email message
            parsed_email = self._parse_email(envelope)

            # Store email in all recipient inboxes
            self.inbox_store.add_email(parsed_email)

            # Dispatch webhooks asynchronously (don't wait)
            asyncio.create_task(
                self._notify_webhooks(parsed_email)
            )

            logger.info(
                f"Email {parsed_email.id} processed successfully "
                f"({len(parsed_email.to_addresses)} recipients)"
            )

            return "250 Message accepted for delivery"

        except Exception as e:
            logger.error(
                f"Error processing email from {envelope.mail_from}: "
                f"{type(e).__name__}: {e}",
                exc_info=True
            )
            return f"550 Error processing message: {type(e).__name__}"

    def _parse_email(self, envelope: Any) -> Email:
        """
        Parse envelope into an Email model.

        Args:
            envelope: aiosmtpd envelope

        Returns:
            Parsed Email instance

        Raises:
            ValueError: If email cannot be parsed
        """
        # Get raw content
        if isinstance(envelope.content, bytes):
            raw_content = envelope.content.decode("utf-8", errors="replace")
        else:
            raw_content = envelope.content

        # Parse using email library
        msg: EmailMessage = email.message_from_string(
            raw_content,
            policy=policy.default
        )

        # Extract subject
        subject = str(msg.get("Subject", ""))

        # Extract body parts
        body_text = None
        body_html = None
        attachments = []

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition", ""))

                # Handle text/plain
                if content_type == "text/plain" and "attachment" not in content_disposition:
                    body_text = part.get_content()

                # Handle text/html
                elif content_type == "text/html" and "attachment" not in content_disposition:
                    body_html = part.get_content()

                # Handle attachments
                elif "attachment" in content_disposition or part.get_filename():
                    filename = part.get_filename() or "unnamed"
                    content = part.get_content()

                    # Convert content to bytes if needed
                    if isinstance(content, str):
                        content_bytes = content.encode("utf-8")
                    else:
                        content_bytes = content

                    # Check attachment size
                    if len(content_bytes) > self.max_attachment_size:
                        logger.warning(
                            f"Attachment '{filename}' exceeds max size "
                            f"({len(content_bytes)} > {self.max_attachment_size})"
                        )
                        continue

                    attachment = Attachment.from_bytes(
                        filename=filename,
                        content_type=content_type,
                        content=content_bytes
                    )
                    attachments.append(attachment)

        else:
            # Single-part message
            content_type = msg.get_content_type()
            if content_type == "text/plain":
                body_text = msg.get_content()
            elif content_type == "text/html":
                body_html = msg.get_content()

        # Extract all headers
        headers = {
            key: str(value)
            for key, value in msg.items()
        }

        # Create Email model
        parsed_email = Email(
            from_address=envelope.mail_from,
            to_addresses=envelope.rcpt_tos,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            attachments=attachments,
            headers=headers,
            raw_content=raw_content
        )

        logger.debug(
            f"Parsed email: subject='{subject}', "
            f"text={body_text is not None}, "
            f"html={body_html is not None}, "
            f"attachments={len(attachments)}"
        )

        return parsed_email

    async def _notify_webhooks(self, email: Email) -> None:
        """
        Notify registered webhooks about the new email.

        Args:
            email: Email that was received
        """
        try:
            # Get webhooks for each recipient
            webhook_tasks = []

            for recipient in email.to_addresses:
                webhooks = self.webhook_registry.get_webhooks_for_inbox(
                    recipient
                )

                for webhook in webhooks:
                    webhook_tasks.append((str(webhook.url), email))

            if not webhook_tasks:
                logger.debug("No webhooks registered for this email")
                return

            logger.info(
                f"Dispatching {len(webhook_tasks)} webhooks for "
                f"email {email.id}"
            )

            # Dispatch all webhooks concurrently
            results = await self.webhook_dispatcher.dispatch_batch(
                webhook_tasks
            )

            # Log results
            for result in results:
                if result.get("status") == "sent":
                    logger.debug(
                        f"Webhook sent: {result.get('url')} "
                        f"(status={result.get('status_code')})"
                    )
                else:
                    logger.warning(
                        f"Webhook failed: {result.get('url')} "
                        f"(error={result.get('error')})"
                    )

        except Exception as e:
            logger.error(
                f"Error notifying webhooks for email {email.id}: "
                f"{type(e).__name__}: {e}",
                exc_info=True
            )
