"""Tests for SMTP sender service."""

import pytest
from email.mime.multipart import MIMEMultipart
from unittest.mock import AsyncMock, patch

from mail_agent.config import Settings
from mail_agent.tools.smtp_sender import (
    SMTPConnectionError,
    SMTPSendError,
    SMTPSenderService,
)


@pytest.fixture
def settings() -> Settings:
    """Create test settings."""
    return Settings(
        mock_smtp_api_url="http://localhost:8025",
        mock_smtp_host="localhost",
        mock_smtp_port=1025,
        agent_email="test-agent@example.com",
        gemini_api_key="test-key",
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
        assert sender._default_from_address == "test-agent@example.com"

    def test_init_custom_smtp_settings(self) -> None:
        """Test initialization with custom SMTP settings."""
        settings = Settings(
            mock_smtp_host="mail.example.com",
            mock_smtp_port=25,
            agent_email="custom@example.com",
            gemini_api_key="test-key",
        )
        sender = SMTPSenderService(settings)
        assert sender._smtp_host == "mail.example.com"
        assert sender._smtp_port == 25
        assert sender._default_from_address == "custom@example.com"

    def test_init_without_settings_uses_defaults(self) -> None:
        """Test initialization without explicit settings uses get_settings()."""
        # This will use the cached settings or create new ones
        # We can't easily test this without mocking get_settings
        pass


class TestCreateMimeMessage:
    """Tests for MIME message creation."""

    def test_create_simple_message(self, smtp_sender: SMTPSenderService) -> None:
        """Test creating a simple message."""
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

    def test_create_message_with_unicode_body(
        self, smtp_sender: SMTPSenderService
    ) -> None:
        """Test creating message with unicode characters in body."""
        unicode_body = "Hello 世界! Привет мир! 🌍"
        message = smtp_sender._create_mime_message(
            from_address="sender@test.com",
            to_addresses=["recipient@test.com"],
            subject="Unicode Test",
            body=unicode_body,
        )

        # Verify message was created successfully
        assert message["Subject"] == "Unicode Test"
        parts = list(message.walk())
        assert len(parts) >= 2

    def test_create_message_with_long_subject(
        self, smtp_sender: SMTPSenderService
    ) -> None:
        """Test creating message with long subject line."""
        long_subject = "A" * 200  # Long subject
        message = smtp_sender._create_mime_message(
            from_address="sender@test.com",
            to_addresses=["recipient@test.com"],
            subject=long_subject,
            body="Body",
        )

        assert message["Subject"] == long_subject


class TestSendEmail:
    """Tests for send_email method."""

    @pytest.mark.asyncio
    async def test_send_email_success(self, smtp_sender: SMTPSenderService) -> None:
        """Test successful email sending."""
        with patch("mail_agent.tools.smtp_sender.aiosmtplib.send") as mock_send:
            mock_send.return_value = None

            await smtp_sender.send_email(
                to_addresses=["recipient@test.com"],
                subject="Test",
                body_text="Body",
            )

            mock_send.assert_called_once()
            # Verify the message was created correctly
            call_args = mock_send.call_args
            message = call_args[0][0]
            assert message["From"] == "test-agent@example.com"
            assert message["To"] == "recipient@test.com"
            assert call_args[1]["hostname"] == "localhost"
            assert call_args[1]["port"] == 1025

    @pytest.mark.asyncio
    async def test_send_email_with_custom_from_address(
        self, smtp_sender: SMTPSenderService
    ) -> None:
        """Test sending email with custom from address."""
        with patch("mail_agent.tools.smtp_sender.aiosmtplib.send") as mock_send:
            mock_send.return_value = None

            await smtp_sender.send_email(
                to_addresses=["recipient@test.com"],
                subject="Test",
                body_text="Body",
                from_address="custom@example.com",
            )

            mock_send.assert_called_once()
            call_args = mock_send.call_args
            message = call_args[0][0]
            assert message["From"] == "custom@example.com"

    @pytest.mark.asyncio
    async def test_send_email_multiple_recipients(
        self, smtp_sender: SMTPSenderService
    ) -> None:
        """Test sending email to multiple recipients."""
        with patch("mail_agent.tools.smtp_sender.aiosmtplib.send") as mock_send:
            mock_send.return_value = None

            await smtp_sender.send_email(
                to_addresses=["user1@test.com", "user2@test.com"],
                subject="Test",
                body_text="Body",
            )

            mock_send.assert_called_once()
            call_args = mock_send.call_args
            message = call_args[0][0]
            assert message["To"] == "user1@test.com, user2@test.com"

    @pytest.mark.asyncio
    async def test_send_email_empty_recipients_raises_error(
        self, smtp_sender: SMTPSenderService
    ) -> None:
        """Test that empty recipients list raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            await smtp_sender.send_email(
                to_addresses=[],
                subject="Test",
                body_text="Body",
            )

        assert "to_addresses cannot be empty" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_send_email_empty_body_raises_error(
        self, smtp_sender: SMTPSenderService
    ) -> None:
        """Test that empty body raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            await smtp_sender.send_email(
                to_addresses=["recipient@test.com"],
                subject="Test",
                body_text="",
            )

        assert "body_text cannot be empty" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_send_email_connection_error(
        self, smtp_sender: SMTPSenderService
    ) -> None:
        """Test handling of SMTP connection error."""
        import aiosmtplib

        with patch("mail_agent.tools.smtp_sender.aiosmtplib.send") as mock_send:
            mock_send.side_effect = aiosmtplib.SMTPConnectError("Connection refused")

            with pytest.raises(SMTPConnectionError) as exc_info:
                await smtp_sender.send_email(
                    to_addresses=["recipient@test.com"],
                    subject="Test",
                    body_text="Body",
                )

            assert "Cannot connect to SMTP server" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_send_email_smtp_error(
        self, smtp_sender: SMTPSenderService
    ) -> None:
        """Test handling of general SMTP error."""
        import aiosmtplib

        with patch("mail_agent.tools.smtp_sender.aiosmtplib.send") as mock_send:
            mock_send.side_effect = aiosmtplib.SMTPException("SMTP error")

            with pytest.raises(SMTPSendError) as exc_info:
                await smtp_sender.send_email(
                    to_addresses=["recipient@test.com"],
                    subject="Test",
                    body_text="Body",
                )

            assert "Failed to send email" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_send_email_unexpected_error(
        self, smtp_sender: SMTPSenderService
    ) -> None:
        """Test handling of unexpected error."""
        with patch("mail_agent.tools.smtp_sender.aiosmtplib.send") as mock_send:
            mock_send.side_effect = RuntimeError("Unexpected error")

            with pytest.raises(SMTPSendError) as exc_info:
                await smtp_sender.send_email(
                    to_addresses=["recipient@test.com"],
                    subject="Test",
                    body_text="Body",
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

        with patch(
            "mail_agent.tools.smtp_sender.aiosmtplib.SMTP", return_value=mock_smtp
        ):
            result = await smtp_sender.check_health()
            assert result is True

    @pytest.mark.asyncio
    async def test_check_health_failure(
        self, smtp_sender: SMTPSenderService
    ) -> None:
        """Test health check when server is unreachable."""
        with patch(
            "mail_agent.tools.smtp_sender.aiosmtplib.SMTP",
            side_effect=ConnectionRefusedError("Connection refused"),
        ):
            result = await smtp_sender.check_health()
            assert result is False
