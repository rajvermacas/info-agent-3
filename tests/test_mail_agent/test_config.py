"""
Tests for the configuration module.
"""

import os
import pytest
from unittest.mock import patch

from mail_agent.config import Settings, get_settings, configure_logging


class TestSettings:
    """Tests for Settings class."""

    def test_default_values(self):
        """Test default configuration values."""
        # Create settings without environment variables
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings()

        assert settings.mock_smtp_api_url == "http://localhost:8025"
        assert settings.mock_smtp_host == "localhost"
        assert settings.mock_smtp_port == 1025
        assert settings.agent_email == "info-agent@gmail.com"
        assert settings.webhook_host == "localhost"
        assert settings.webhook_port == 9000
        assert settings.webhook_path == "/webhook/email-received"
        assert settings.gemini_model == "gemini-2.5-flash"
        assert settings.llm_temperature == 0.0
        assert settings.max_attempts == 5
        assert settings.log_level == "INFO"

    def test_environment_variable_override(self):
        """Test that environment variables override defaults."""
        env_vars = {
            "MAIL_AGENT_MOCK_SMTP_API_URL": "http://custom:9999",
            "MAIL_AGENT_AGENT_EMAIL": "custom@test.com",
            "MAIL_AGENT_WEBHOOK_PORT": "8888",
            "MAIL_AGENT_MAX_ATTEMPTS": "3",
            "MAIL_AGENT_LOG_LEVEL": "DEBUG",
        }

        with patch.dict(os.environ, env_vars, clear=False):
            settings = Settings()

        assert settings.mock_smtp_api_url == "http://custom:9999"
        assert settings.agent_email == "custom@test.com"
        assert settings.webhook_port == 8888
        assert settings.max_attempts == 3
        assert settings.log_level == "DEBUG"

    def test_webhook_url_property(self):
        """Test webhook_url property construction."""
        settings = Settings(
            webhook_host="myhost",
            webhook_port=7777,
            webhook_path="/custom/path",
        )

        assert settings.webhook_url == "http://myhost:7777/custom/path"

    def test_log_level_validation_valid(self):
        """Test log level validation with valid values."""
        for level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            settings = Settings(log_level=level)
            assert settings.log_level == level

    def test_log_level_validation_case_insensitive(self):
        """Test log level validation is case insensitive."""
        settings = Settings(log_level="debug")
        assert settings.log_level == "DEBUG"

    def test_log_level_validation_invalid(self):
        """Test log level validation with invalid value."""
        with pytest.raises(ValueError) as exc_info:
            Settings(log_level="INVALID")

        assert "Invalid log level" in str(exc_info.value)

    def test_port_validation_valid(self):
        """Test port validation with valid values."""
        settings = Settings(
            mock_smtp_port=1025,
            webhook_port=9000,
        )
        assert settings.mock_smtp_port == 1025
        assert settings.webhook_port == 9000

    def test_port_validation_boundaries(self):
        """Test port validation at boundaries."""
        # Min port
        settings = Settings(webhook_port=1)
        assert settings.webhook_port == 1

        # Max port
        settings = Settings(webhook_port=65535)
        assert settings.webhook_port == 65535

    def test_port_validation_invalid(self):
        """Test port validation with invalid values."""
        with pytest.raises(ValueError):
            Settings(webhook_port=0)

        with pytest.raises(ValueError):
            Settings(webhook_port=65536)

    def test_max_attempts_validation(self):
        """Test max_attempts validation."""
        # Valid range
        for attempts in [1, 5, 10]:
            settings = Settings(max_attempts=attempts)
            assert settings.max_attempts == attempts

        # Invalid - too low
        with pytest.raises(ValueError):
            Settings(max_attempts=0)

        # Invalid - too high
        with pytest.raises(ValueError):
            Settings(max_attempts=11)

    def test_validation_content_max_chars_default(self):
        """Test validation_content_max_chars default value."""
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings()
        assert settings.validation_content_max_chars == 8000

    def test_validation_content_max_chars_validation(self):
        """Test validation_content_max_chars validation."""
        # Valid range
        for chars in [1000, 8000, 50000]:
            settings = Settings(validation_content_max_chars=chars)
            assert settings.validation_content_max_chars == chars

        # Invalid - too low
        with pytest.raises(ValueError):
            Settings(validation_content_max_chars=999)

        # Invalid - too high
        with pytest.raises(ValueError):
            Settings(validation_content_max_chars=50001)

    def test_validation_content_max_chars_env_override(self):
        """Test validation_content_max_chars can be set via environment."""
        env_vars = {
            "MAIL_AGENT_VALIDATION_CONTENT_MAX_CHARS": "15000",
        }
        with patch.dict(os.environ, env_vars, clear=False):
            settings = Settings()
        assert settings.validation_content_max_chars == 15000

    def test_llm_temperature_validation(self):
        """Test LLM temperature validation."""
        # Valid range
        for temp in [0.0, 0.5, 1.0, 2.0]:
            settings = Settings(llm_temperature=temp)
            assert settings.llm_temperature == temp

        # Invalid - negative
        with pytest.raises(ValueError):
            Settings(llm_temperature=-0.1)

        # Invalid - too high
        with pytest.raises(ValueError):
            Settings(llm_temperature=2.1)

    def test_get_log_level_int(self):
        """Test get_log_level_int method."""
        import logging

        settings = Settings(log_level="DEBUG")
        assert settings.get_log_level_int() == logging.DEBUG

        settings = Settings(log_level="INFO")
        assert settings.get_log_level_int() == logging.INFO

        settings = Settings(log_level="ERROR")
        assert settings.get_log_level_int() == logging.ERROR


class TestGetSettings:
    """Tests for get_settings function."""

    def test_returns_settings_instance(self):
        """Test that get_settings returns a Settings instance."""
        # Clear cache
        get_settings.cache_clear()

        settings = get_settings()
        assert isinstance(settings, Settings)

    def test_cached_result(self):
        """Test that get_settings returns cached instance."""
        # Clear cache
        get_settings.cache_clear()

        settings1 = get_settings()
        settings2 = get_settings()

        assert settings1 is settings2


class TestConfigureLogging:
    """Tests for configure_logging function."""

    def test_configure_logging_default(self):
        """Test configure_logging with default settings."""
        # Should not raise
        configure_logging()

    def test_configure_logging_with_settings(self, mock_settings):
        """Test configure_logging with explicit settings."""
        configure_logging(mock_settings)
        # Should not raise
