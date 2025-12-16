"""
UI Server Configuration.

All settings use the UI_ prefix for environment variables.
"""

import logging
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """UI Server configuration settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="UI_",
        case_sensitive=False,
        validate_default=True,
        extra="ignore",
    )

    # Server settings
    host: str = Field(
        default="0.0.0.0",
        description="Host to bind the UI server to",
    )
    port: int = Field(
        default=8080,
        description="Port to bind the UI server to",
        ge=1,
        le=65535,
    )

    # External service URLs
    a2a_server_url: str = Field(
        default="http://localhost:8000",
        description="URL of the A2A server (Mail Agent)",
    )
    mock_smtp_api_url: str = Field(
        default="http://localhost:8025",
        description="URL of the Mock SMTP server API",
    )

    # Default inbox to display
    default_inbox_email: str = Field(
        default="info-agent@gmail.com",
        description="Default inbox email address to display",
    )

    # SMTP server settings (for sending emails via SMTP protocol)
    smtp_host: str = Field(
        default="localhost",
        description="SMTP server hostname for sending emails",
    )
    smtp_port: int = Field(
        default=1025,
        description="SMTP server port for sending emails",
        ge=1,
        le=65535,
    )

    # HTTP client settings
    http_timeout_seconds: float = Field(
        default=30.0,
        description="HTTP client timeout in seconds",
        gt=0,
    )
    http_long_poll_timeout_seconds: float = Field(
        default=300.0,
        description="HTTP client timeout for long-polling operations (like A2A tasks)",
        gt=0,
    )

    # SSE settings
    sse_reconnect_max_retries: int = Field(
        default=5,
        description="Maximum SSE reconnection attempts",
        ge=1,
    )
    sse_reconnect_initial_delay: float = Field(
        default=1.0,
        description="Initial delay between SSE reconnection attempts (seconds)",
        gt=0,
    )
    sse_keepalive_interval: float = Field(
        default=15.0,
        description="Interval for SSE keepalive ping (seconds)",
        gt=0,
    )

    # Logging
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        description="Logging level",
    )

    @field_validator("log_level", mode="before")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level is one of the allowed values."""
        if not isinstance(v, str):
            raise ValueError(f"log_level must be a string, got {type(v)}")
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper_v = v.upper()
        if upper_v not in allowed:
            raise ValueError(f"log_level must be one of {allowed}, got {v}")
        return upper_v

    def get_log_level_int(self) -> int:
        """Convert log level string to logging constant."""
        return getattr(logging, self.log_level)


def configure_logging(settings: Settings) -> None:
    """Configure logging based on settings."""
    logging.basicConfig(
        level=settings.get_log_level_int(),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logger = logging.getLogger(__name__)
    logger.info("Logging configured with level: %s", settings.log_level)


@lru_cache
def get_settings() -> Settings:
    """
    Get cached settings instance.

    Returns:
        Settings: Cached settings instance.
    """
    settings = Settings()
    logger = logging.getLogger(__name__)
    logger.info("UI Server settings loaded:")
    logger.info("  Host: %s", settings.host)
    logger.info("  Port: %d", settings.port)
    logger.info("  A2A Server URL: %s", settings.a2a_server_url)
    logger.info("  Mock SMTP API URL: %s", settings.mock_smtp_api_url)
    logger.info("  SMTP Server: %s:%d", settings.smtp_host, settings.smtp_port)
    logger.info("  Default Inbox: %s", settings.default_inbox_email)
    logger.info("  Log Level: %s", settings.log_level)
    return settings
