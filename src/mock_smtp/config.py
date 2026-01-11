"""Configuration settings for Mock SMTP Server."""

import logging
from functools import lru_cache
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """
    Application configuration settings.

    All settings can be overridden via environment variables with the
    MOCK_SMTP_ prefix (e.g., MOCK_SMTP_SMTP_PORT=2525).
    """

    # SMTP Server Settings
    smtp_host: str = Field(
        default="localhost",
        description="SMTP server bind address"
    )
    smtp_port: int = Field(
        default=1025,
        ge=1,
        le=65535,
        description="SMTP server port"
    )

    # REST API Settings
    api_host: str = Field(
        default="0.0.0.0",
        description="REST API bind address"
    )
    api_port: int = Field(
        default=8025,
        ge=1,
        le=65535,
        description="REST API port"
    )

    # Storage Settings
    max_emails_per_inbox: int = Field(
        default=1000,
        ge=1,
        description="Maximum number of emails per inbox before auto-cleanup"
    )
    max_attachment_size_mb: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum attachment size in MB"
    )

    # Webhook Settings
    webhook_timeout_seconds: float = Field(
        default=10.0,
        ge=1.0,
        le=60.0,
        description="HTTP timeout for webhook requests"
    )
    webhook_max_retries: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Maximum retry attempts for failed webhooks"
    )

    # Logging Settings
    log_level: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)"
    )

    # Application Settings
    app_name: str = Field(
        default="Mock SMTP Server",
        description="Application name"
    )
    app_version: str = Field(
        default="0.1.0",
        description="Application version"
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="MOCK_SMTP_",
        case_sensitive=False,
        validate_default=True,
        extra="ignore",
    )

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level is a valid logging level."""
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        v_upper = v.upper()
        if v_upper not in valid_levels:
            raise ValueError(
                f"Invalid log level: {v}. Must be one of {valid_levels}"
            )
        return v_upper

    @property
    def max_attachment_size_bytes(self) -> int:
        """Convert max attachment size from MB to bytes."""
        return self.max_attachment_size_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    """
    Get cached settings instance.

    Uses lru_cache to ensure settings are only loaded once from
    environment/file during application lifetime.

    Returns:
        Settings instance
    """
    settings = Settings()
    logger.info(
        f"Settings loaded: SMTP={settings.smtp_host}:{settings.smtp_port}, "
        f"API={settings.api_host}:{settings.api_port}"
    )
    return settings
