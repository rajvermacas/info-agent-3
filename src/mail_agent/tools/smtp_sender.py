"""
SMTP Sender Service - Send emails via SMTP protocol.

Sends emails directly via SMTP protocol using aiosmtplib.
This replaces the REST API approach for email sending.
"""

import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import aiosmtplib

from mail_agent.config import Settings, get_settings


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
    directly via SMTP protocol to the mock SMTP server.

    Attributes:
        _smtp_host: SMTP server hostname.
        _smtp_port: SMTP server port.
        _default_from_address: Default sender email address.
    """

    def __init__(
        self,
        settings: Optional[Settings] = None,
    ) -> None:
        """
        Initialize the SMTP sender service.

        Args:
            settings: Mail agent settings. Uses get_settings() if not provided.

        Raises:
            ValueError: If settings are invalid.
        """
        self._settings = settings or get_settings()
        self._smtp_host = self._settings.mock_smtp_host
        self._smtp_port = self._settings.mock_smtp_port
        self._default_from_address = self._settings.agent_email

        logger.info(
            "SMTPSenderService initialized with SMTP server: %s:%d, "
            "default from: %s",
            self._smtp_host,
            self._smtp_port,
            self._default_from_address,
        )

    async def send_email(
        self,
        to_addresses: list[str],
        subject: str,
        body_text: str,
        from_address: Optional[str] = None,
    ) -> None:
        """
        Send an email via SMTP protocol.

        Args:
            to_addresses: List of recipient email addresses.
            subject: Email subject line.
            body_text: Plain text email body.
            from_address: Sender address. Defaults to agent email.

        Raises:
            SMTPConnectionError: If connection to SMTP server fails.
            SMTPSendError: If sending the email fails.
            ValueError: If to_addresses is empty or body_text is empty.
        """
        if not to_addresses:
            error_msg = "to_addresses cannot be empty"
            logger.error(error_msg)
            raise ValueError(error_msg)

        if not body_text:
            error_msg = "body_text cannot be empty"
            logger.error(error_msg)
            raise ValueError(error_msg)

        sender = from_address or self._default_from_address

        logger.info(
            "Sending email via SMTP from %s to %s: %s",
            sender,
            to_addresses,
            subject,
        )

        # Create MIME message
        message = self._create_mime_message(
            from_address=sender,
            to_addresses=to_addresses,
            subject=subject,
            body=body_text,
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
            logger.info("Email sent successfully via SMTP to %s", to_addresses)

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
    ) -> MIMEMultipart:
        """
        Create a MIME multipart message.

        Args:
            from_address: Sender email address.
            to_addresses: List of recipient email addresses.
            subject: Email subject.
            body: Email body text.

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
