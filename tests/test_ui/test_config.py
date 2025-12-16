"""
Tests for UI configuration.
"""

import pytest
from unittest.mock import patch

from ui.config import Settings, get_settings, configure_logging


class TestSettings:
    """Tests for Settings class."""

    def test_default_settings(self) -> None:
        """Test default settings values."""
        settings = Settings()

        assert settings.host == "0.0.0.0"
        assert settings.port == 8080
        assert settings.a2a_server_url == "http://localhost:8000"
        assert settings.mock_smtp_api_url == "http://localhost:8025"
        assert settings.default_inbox_email == "info-agent@gmail.com"
        assert settings.http_timeout_seconds == 30.0
        assert settings.http_long_poll_timeout_seconds == 300.0
        assert settings.log_level == "INFO"

    def test_custom_settings(self) -> None:
        """Test custom settings values."""
        settings = Settings(
            host="127.0.0.1",
            port=9000,
            a2a_server_url="http://a2a.example.com:8000",
            mock_smtp_api_url="http://smtp.example.com:8025",
            default_inbox_email="custom@example.com",
            log_level="DEBUG",
        )

        assert settings.host == "127.0.0.1"
        assert settings.port == 9000
        assert settings.a2a_server_url == "http://a2a.example.com:8000"
        assert settings.mock_smtp_api_url == "http://smtp.example.com:8025"
        assert settings.default_inbox_email == "custom@example.com"
        assert settings.log_level == "DEBUG"

    def test_log_level_validation(self) -> None:
        """Test log level validation."""
        # Valid log levels
        for level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            settings = Settings(log_level=level)
            assert settings.log_level == level

        # Case insensitive
        settings = Settings(log_level="debug")
        assert settings.log_level == "DEBUG"

    def test_log_level_invalid(self) -> None:
        """Test invalid log level raises error."""
        with pytest.raises(ValueError):
            Settings(log_level="INVALID")

    def test_port_validation(self) -> None:
        """Test port validation."""
        # Valid ports
        settings = Settings(port=1)
        assert settings.port == 1

        settings = Settings(port=65535)
        assert settings.port == 65535

        # Invalid ports
        with pytest.raises(ValueError):
            Settings(port=0)

        with pytest.raises(ValueError):
            Settings(port=65536)

    def test_get_log_level_int(self) -> None:
        """Test get_log_level_int method."""
        import logging

        settings = Settings(log_level="DEBUG")
        assert settings.get_log_level_int() == logging.DEBUG

        settings = Settings(log_level="INFO")
        assert settings.get_log_level_int() == logging.INFO

        settings = Settings(log_level="ERROR")
        assert settings.get_log_level_int() == logging.ERROR


class TestConfigureFunctions:
    """Tests for configuration functions."""

    def test_configure_logging(self) -> None:
        """Test logging configuration."""
        settings = Settings(log_level="DEBUG")
        # Should not raise
        configure_logging(settings)

    def test_get_settings_cached(self) -> None:
        """Test that get_settings returns cached instance."""
        # Clear cache first
        get_settings.cache_clear()

        settings1 = get_settings()
        settings2 = get_settings()

        assert settings1 is settings2
