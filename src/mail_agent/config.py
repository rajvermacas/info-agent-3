"""Configuration for Mail Agent using Pydantic Settings.

Environment variables with MAIL_AGENT_ prefix override default values.
Example: MAIL_AGENT_GEMINI_API_KEY=your-key
"""

import logging
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Mail Agent configuration settings.

    All settings can be overridden via environment variables with MAIL_AGENT_ prefix.
    Case-insensitive environment variable names are supported.
    """

    model_config = SettingsConfigDict(
        env_prefix="MAIL_AGENT_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Mock SMTP Server Connection
    mock_smtp_api_url: str = Field(
        default="http://localhost:8025",
        description="Base URL for Mock SMTP Server REST API"
    )
    mock_smtp_host: str = Field(
        default="localhost",
        description="Mock SMTP server hostname for sending emails"
    )
    mock_smtp_port: int = Field(
        default=1025,
        ge=1,
        le=65535,
        description="Mock SMTP server port for sending emails"
    )

    # Agent Identity
    agent_email: str = Field(
        default="info-agent@gmail.com",
        description="Email address of the agent (receives POC replies)"
    )

    # Webhook Server
    webhook_host: str = Field(
        default="localhost",
        description="Host for agent's webhook server"
    )
    webhook_port: int = Field(
        default=9000,
        ge=1,
        le=65535,
        description="Port for agent's webhook server"
    )
    webhook_path: str = Field(
        default="/webhook/email-received",
        description="Path for webhook endpoint"
    )

    # LLM Configuration
    gemini_api_key: str = Field(
        default="",
        description="Google Gemini API key (required)"
    )
    gemini_model: str = Field(
        default="gemini-2.0-flash-exp",
        description="Gemini model to use"
    )
    gemini_temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=2.0,
        description="LLM temperature for generation"
    )
    gemini_max_tokens: int = Field(
        default=2048,
        ge=1,
        description="Maximum tokens for LLM generation"
    )
    gemini_timeout: float = Field(
        default=60.0,
        gt=0,
        description="Timeout for LLM API calls in seconds"
    )

    # Agent Behavior
    max_attempts: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Maximum conversation attempts before giving up"
    )
    webhook_wait_timeout: Optional[float] = Field(
        default=None,
        gt=0,
        description="Timeout for waiting for webhook reply (None = wait indefinitely)"
    )

    # State Persistence
    sqlite_db_path: str = Field(
        default="./mail_agent_state.db",
        description="Path to SQLite database for state persistence"
    )

    # Logging
    log_level: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)"
    )

    @field_validator("gemini_api_key")
    @classmethod
    def validate_gemini_api_key(cls, v: str) -> str:
        """Validate that Gemini API key is provided.

        Raises:
            ValueError: If API key is empty or whitespace
        """
        if not v or not v.strip():
            raise ValueError(
                "GEMINI_API_KEY is required. Set MAIL_AGENT_GEMINI_API_KEY environment variable."
            )
        return v.strip()

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level is valid.

        Raises:
            ValueError: If log level is not valid
        """
        v = v.upper()
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v not in valid_levels:
            raise ValueError(
                f"Invalid log level: {v}. Must be one of {valid_levels}"
            )
        return v

    @field_validator("sqlite_db_path")
    @classmethod
    def validate_sqlite_path(cls, v: str) -> str:
        """Validate and prepare SQLite database path.

        Creates parent directory if it doesn't exist.
        """
        db_path = Path(v)
        if db_path.parent and not db_path.parent.exists():
            db_path.parent.mkdir(parents=True, exist_ok=True)
        return v

    @property
    def webhook_url(self) -> str:
        """Get full webhook URL for registration with Mock SMTP."""
        return f"http://{self.webhook_host}:{self.webhook_port}{self.webhook_path}"

    def configure_logging(self) -> None:
        """Configure logging based on settings."""
        logging.basicConfig(
            level=getattr(logging, self.log_level),
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance.

    Returns:
        Settings: Singleton settings instance

    Raises:
        ValueError: If required settings are invalid or missing
    """
    return Settings()
