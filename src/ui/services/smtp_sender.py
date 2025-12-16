"""
SMTP Sender Service for UI.

Sends emails via SMTP protocol with support for attachments.
Uses aiosmtplib for async SMTP communication.
"""

import logging
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib

from ui.config import Settings

logger = logging.getLogger(__name__)


class SMTPSendError(Exception):
    """Raised when sending email via SMTP fails."""

    pass


class SMTPConnectionError(SMTPSendError):
    """Raised when connection to SMTP server fails."""

    pass


class SMTPSenderService:
    """
    Service for sending emails via SMTP protocol.

    This service creates properly formatted MIME messages and sends them
    via SMTP, supporting attachments. It mirrors the functionality of
    the poc_reply_simulator.py script.
    """

    def __init__(self, settings: Settings):
        """
        Initialize the SMTP sender service.

        Args:
            settings: UI settings containing SMTP server configuration.
        """
        self._smtp_host = settings.smtp_host
        self._smtp_port = settings.smtp_port
        logger.info(
            "SMTPSenderService initialized with SMTP server: %s:%d",
            self._smtp_host,
            self._smtp_port,
        )

    async def send_email(
        self,
        from_address: str,
        to_addresses: list[str],
        subject: str,
        body: str,
        attachment: tuple[str, str, bytes] | None = None,
    ) -> None:
        """
        Send an email via SMTP with optional attachment.

        Args:
            from_address: Sender email address.
            to_addresses: List of recipient email addresses.
            subject: Email subject.
            body: Email body text.
            attachment: Optional tuple of (filename, content_type, content_bytes).

        Raises:
            SMTPConnectionError: If connection to SMTP server fails.
            SMTPSendError: If sending the email fails.
        """
        logger.info(
            "Sending email via SMTP from %s to %s: %s",
            from_address,
            to_addresses,
            subject,
        )

        # Create MIME message
        message = self._create_mime_message(
            from_address=from_address,
            to_addresses=to_addresses,
            subject=subject,
            body=body,
            attachment=attachment,
        )

        # Send via SMTP
        try:
            logger.debug(
                "Connecting to SMTP server: %s:%d",
                self._smtp_host,
                self._smtp_port,
            )
            await aiosmtplib.send(
                message,
                hostname=self._smtp_host,
                port=self._smtp_port,
                start_tls=False,
                use_tls=False,
            )
            logger.info("Email sent successfully via SMTP")
        except aiosmtplib.SMTPConnectError as e:
            logger.error(
                "Failed to connect to SMTP server %s:%d: %s",
                self._smtp_host,
                self._smtp_port,
                e,
            )
            raise SMTPConnectionError(
                f"Cannot connect to SMTP server at {self._smtp_host}:{self._smtp_port}"
            ) from e
        except aiosmtplib.SMTPException as e:
            logger.error("SMTP error sending email: %s", e)
            raise SMTPSendError(f"Failed to send email: {e}") from e
        except Exception as e:
            logger.error("Unexpected error sending email via SMTP: %s", e)
            raise SMTPSendError(f"Unexpected error: {e}") from e

    def _create_mime_message(
        self,
        from_address: str,
        to_addresses: list[str],
        subject: str,
        body: str,
        attachment: tuple[str, str, bytes] | None = None,
    ) -> MIMEMultipart:
        """
        Create a MIME multipart message with optional attachment.

        Args:
            from_address: Sender email address.
            to_addresses: List of recipient email addresses.
            subject: Email subject.
            body: Email body text.
            attachment: Optional tuple of (filename, content_type, content_bytes).

        Returns:
            MIMEMultipart message ready to send.
        """
        logger.debug(
            "Creating MIME message: from=%s, to=%s, subject=%s",
            from_address,
            to_addresses,
            subject,
        )

        # Create multipart message
        message = MIMEMultipart("mixed")
        message["From"] = from_address
        message["To"] = ", ".join(to_addresses)
        message["Subject"] = subject

        # Add body as plain text
        body_part = MIMEText(body, "plain", "utf-8")
        message.attach(body_part)
        logger.debug("Added body: %d chars", len(body))

        # Add attachment if provided
        if attachment:
            filename, content_type, content_bytes = attachment
            logger.info(
                "Adding attachment: %s (%s, %d bytes)",
                filename,
                content_type,
                len(content_bytes),
            )

            # Parse content type
            if "/" in content_type:
                maintype, subtype = content_type.split("/", 1)
            else:
                maintype = "application"
                subtype = "octet-stream"
                logger.warning(
                    "Invalid content type '%s', using application/octet-stream",
                    content_type,
                )

            # Create attachment part
            attachment_part = MIMEBase(maintype, subtype)
            attachment_part.set_payload(content_bytes)

            # Encode as base64
            encoders.encode_base64(attachment_part)

            # Set headers
            attachment_part.add_header(
                "Content-Disposition",
                "attachment",
                filename=filename,
            )

            message.attach(attachment_part)
            logger.debug("Attached file: %s", filename)

        return message

    async def check_health(self) -> bool:
        """
        Check if SMTP server is reachable.

        Returns:
            True if SMTP server is reachable, False otherwise.
        """
        try:
            async with aiosmtplib.SMTP(
                hostname=self._smtp_host,
                port=self._smtp_port,
                start_tls=False,
                use_tls=False,
                timeout=5,
            ) as smtp:
                await smtp.noop()
            logger.debug("SMTP health check passed")
            return True
        except Exception as e:
            logger.warning("SMTP health check failed: %s", e)
            return False
