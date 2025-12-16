"""Tests for SMTP sender service."""

import pytest
from email.mime.multipart import MIMEMultipart
from unittest.mock import AsyncMock, MagicMock, patch

from ui.config import Settings
from ui.services.smtp_sender import (
    SMTPConnectionError,
    SMTPSendError,
    SMTPSenderService,
)


@pytest.fixture
def settings() -> Settings:
    """Create test settings."""
    return Settings(
        host="localhost",
        port=8080,
        a2a_server_url="http://localhost:8000",
        mock_smtp_api_url="http://localhost:8025",
        smtp_host="localhost",
        smtp_port=1025,
    )


@pytest.fixture
def smtp_sender(settings: Settings) -> SMTPSenderService:
    """Create SMTP sender service instance."""
    return SMTPSenderService(settings)


class TestSMTPSenderServiceInit:
    """Tests for SMTPSenderService initialization."""

    def test_init_with_settings(self, settings: Settings) -> None:
        """Test initialization with settings."""
        sender = SMTPSenderService(settings)
        assert sender._smtp_host == "localhost"
        assert sender._smtp_port == 1025

    def test_init_custom_smtp_settings(self) -> None:
        """Test initialization with custom SMTP settings."""
        settings = Settings(
            smtp_host="mail.example.com",
            smtp_port=25,
        )
        sender = SMTPSenderService(settings)
        assert sender._smtp_host == "mail.example.com"
        assert sender._smtp_port == 25


class TestCreateMimeMessage:
    """Tests for MIME message creation."""

    def test_create_simple_message(self, smtp_sender: SMTPSenderService) -> None:
        """Test creating a simple message without attachment."""
        message = smtp_sender._create_mime_message(
            from_address="sender@test.com",
            to_addresses=["recipient@test.com"],
            subject="Test Subject",
            body="Test body content",
        )

        assert isinstance(message, MIMEMultipart)
        assert message["From"] == "sender@test.com"
        assert message["To"] == "recipient@test.com"
        assert message["Subject"] == "Test Subject"

        # Check that body is attached
        parts = list(message.walk())
        # First part is the multipart container, second is the text body
        assert len(parts) >= 2

    def test_create_message_multiple_recipients(
        self, smtp_sender: SMTPSenderService
    ) -> None:
        """Test creating message with multiple recipients."""
        message = smtp_sender._create_mime_message(
            from_address="sender@test.com",
            to_addresses=["recipient1@test.com", "recipient2@test.com"],
            subject="Test",
            body="Body",
        )

        assert message["To"] == "recipient1@test.com, recipient2@test.com"

    def test_create_message_with_attachment(
        self, smtp_sender: SMTPSenderService
    ) -> None:
        """Test creating message with attachment."""
        attachment_content = b"test file content"
        message = smtp_sender._create_mime_message(
            from_address="sender@test.com",
            to_addresses=["recipient@test.com"],
            subject="With Attachment",
            body="See attached file",
            attachment=("test.txt", "text/plain", attachment_content),
        )

        # Count parts: multipart container, text body, attachment
        parts = list(message.walk())
        assert len(parts) == 3  # multipart/mixed, text/plain body, text/plain attachment

    def test_create_message_with_csv_attachment(
        self, smtp_sender: SMTPSenderService
    ) -> None:
        """Test creating message with CSV attachment."""
        csv_content = b"name,email\njohn,john@test.com"
        message = smtp_sender._create_mime_message(
            from_address="sender@test.com",
            to_addresses=["recipient@test.com"],
            subject="CSV Data",
            body="Please find attached data.",
            attachment=("data.csv", "text/csv", csv_content),
        )

        # Find the attachment part
        parts = list(message.walk())
        attachment_part = None
        for part in parts:
            if part.get_filename() == "data.csv":
                attachment_part = part
                break

        assert attachment_part is not None
        assert attachment_part.get_content_type() == "text/csv"

    def test_create_message_with_excel_attachment(
        self, smtp_sender: SMTPSenderService
    ) -> None:
        """Test creating message with Excel attachment."""
        # Fake Excel content (just bytes for testing)
        xlsx_content = b"PK\x03\x04fake xlsx content"
        content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

        message = smtp_sender._create_mime_message(
            from_address="sender@test.com",
            to_addresses=["recipient@test.com"],
            subject="Excel Data",
            body="Please find attached spreadsheet.",
            attachment=("data.xlsx", content_type, xlsx_content),
        )

        # Find the attachment part
        parts = list(message.walk())
        attachment_part = None
        for part in parts:
            if part.get_filename() == "data.xlsx":
                attachment_part = part
                break

        assert attachment_part is not None
        assert attachment_part.get_content_type() == content_type

    def test_create_message_invalid_content_type(
        self, smtp_sender: SMTPSenderService
    ) -> None:
        """Test handling of invalid content type (no slash)."""
        message = smtp_sender._create_mime_message(
            from_address="sender@test.com",
            to_addresses=["recipient@test.com"],
            subject="Test",
            body="Body",
            attachment=("file.bin", "invalid", b"content"),
        )

        # Should fall back to application/octet-stream
        parts = list(message.walk())
        attachment_part = None
        for part in parts:
            if part.get_filename() == "file.bin":
                attachment_part = part
                break

        assert attachment_part is not None
        # Falls back to application/octet-stream when content type is invalid
        assert attachment_part.get_content_type() == "application/octet-stream"


class TestSendEmail:
    """Tests for send_email method."""

    @pytest.mark.asyncio
    async def test_send_email_success(self, smtp_sender: SMTPSenderService) -> None:
        """Test successful email sending."""
        with patch("ui.services.smtp_sender.aiosmtplib.send") as mock_send:
            mock_send.return_value = None

            await smtp_sender.send_email(
                from_address="sender@test.com",
                to_addresses=["recipient@test.com"],
                subject="Test",
                body="Body",
            )

            mock_send.assert_called_once()
            # Verify the message was created correctly
            call_args = mock_send.call_args
            message = call_args[0][0]
            assert message["From"] == "sender@test.com"
            assert message["To"] == "recipient@test.com"
            assert call_args[1]["hostname"] == "localhost"
            assert call_args[1]["port"] == 1025

    @pytest.mark.asyncio
    async def test_send_email_with_attachment(
        self, smtp_sender: SMTPSenderService
    ) -> None:
        """Test sending email with attachment."""
        with patch("ui.services.smtp_sender.aiosmtplib.send") as mock_send:
            mock_send.return_value = None

            await smtp_sender.send_email(
                from_address="sender@test.com",
                to_addresses=["recipient@test.com"],
                subject="With Attachment",
                body="See attached",
                attachment=("test.csv", "text/csv", b"data"),
            )

            mock_send.assert_called_once()
            # Verify attachment is in the message
            call_args = mock_send.call_args
            message = call_args[0][0]
            parts = list(message.walk())
            filenames = [p.get_filename() for p in parts if p.get_filename()]
            assert "test.csv" in filenames

    @pytest.mark.asyncio
    async def test_send_email_connection_error(
        self, smtp_sender: SMTPSenderService
    ) -> None:
        """Test handling of SMTP connection error."""
        import aiosmtplib

        with patch("ui.services.smtp_sender.aiosmtplib.send") as mock_send:
            mock_send.side_effect = aiosmtplib.SMTPConnectError("Connection refused")

            with pytest.raises(SMTPConnectionError) as exc_info:
                await smtp_sender.send_email(
                    from_address="sender@test.com",
                    to_addresses=["recipient@test.com"],
                    subject="Test",
                    body="Body",
                )

            assert "Cannot connect to SMTP server" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_send_email_smtp_error(
        self, smtp_sender: SMTPSenderService
    ) -> None:
        """Test handling of general SMTP error."""
        import aiosmtplib

        with patch("ui.services.smtp_sender.aiosmtplib.send") as mock_send:
            mock_send.side_effect = aiosmtplib.SMTPException("SMTP error")

            with pytest.raises(SMTPSendError) as exc_info:
                await smtp_sender.send_email(
                    from_address="sender@test.com",
                    to_addresses=["recipient@test.com"],
                    subject="Test",
                    body="Body",
                )

            assert "Failed to send email" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_send_email_unexpected_error(
        self, smtp_sender: SMTPSenderService
    ) -> None:
        """Test handling of unexpected error."""
        with patch("ui.services.smtp_sender.aiosmtplib.send") as mock_send:
            mock_send.side_effect = RuntimeError("Unexpected error")

            with pytest.raises(SMTPSendError) as exc_info:
                await smtp_sender.send_email(
                    from_address="sender@test.com",
                    to_addresses=["recipient@test.com"],
                    subject="Test",
                    body="Body",
                )

            assert "Unexpected error" in str(exc_info.value)


class TestHealthCheck:
    """Tests for health check method."""

    @pytest.mark.asyncio
    async def test_check_health_success(
        self, smtp_sender: SMTPSenderService
    ) -> None:
        """Test successful health check."""
        mock_smtp = AsyncMock()
        mock_smtp.__aenter__ = AsyncMock(return_value=mock_smtp)
        mock_smtp.__aexit__ = AsyncMock(return_value=None)
        mock_smtp.noop = AsyncMock(return_value=None)

        with patch("ui.services.smtp_sender.aiosmtplib.SMTP", return_value=mock_smtp):
            result = await smtp_sender.check_health()
            assert result is True

    @pytest.mark.asyncio
    async def test_check_health_failure(
        self, smtp_sender: SMTPSenderService
    ) -> None:
        """Test health check when server is unreachable."""
        with patch(
            "ui.services.smtp_sender.aiosmtplib.SMTP",
            side_effect=ConnectionRefusedError("Connection refused"),
        ):
            result = await smtp_sender.check_health()
            assert result is False
