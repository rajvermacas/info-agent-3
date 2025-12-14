"""
Configuration management for Mail Agent.

Uses Pydantic Settings for environment variable support.
All settings can be overridden with MAIL_AGENT_ prefix.
"""

import logging
from functools import lru_cache
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """
    Mail Agent configuration settings.

    All settings can be overridden via environment variables with MAIL_AGENT_ prefix.
    Example: MAIL_AGENT_GEMINI_API_KEY=your-key
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
        description="Base URL of the mock SMTP server REST API",
    )
    mock_smtp_host: str = Field(
        default="localhost",
        description="SMTP server hostname for POC reply simulator",
    )
    mock_smtp_port: int = Field(
        default=1025,
        ge=1,
        le=65535,
        description="SMTP server port for POC reply simulator",
    )

    # Agent Identity
    agent_email: str = Field(
        default="info-agent@gmail.com",
        description="Email address used by the agent to send/receive emails",
    )

    # Webhook Server
    webhook_host: str = Field(
        default="localhost",
        description="Host for the webhook receiver server",
    )
    webhook_port: int = Field(
        default=9000,
        ge=1,
        le=65535,
        description="Port for the webhook receiver server",
    )
    webhook_path: str = Field(
        default="/webhook/email-received",
        description="Path for the webhook endpoint",
    )

    # LLM Configuration
    gemini_api_key: Optional[str] = Field(
        default=None,
        description="Google Gemini API key (required)",
    )
    gemini_model: str = Field(
        default="gemini-2.5-flash",
        description="Gemini model to use",
    )
    llm_temperature: float = Field(
        default=0.0,
        ge=0.0,
        le=2.0,
        description="LLM temperature for responses",
    )
    llm_max_tokens: int = Field(
        default=4096,
        ge=1,
        description="Maximum tokens for LLM responses",
    )

    # Agent Behavior
    max_attempts: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Maximum conversation attempts before giving up",
    )

    # State Persistence
    sqlite_db_path: str = Field(
        default="./mail_agent_state.db",
        description="Path to SQLite database for state persistence",
    )

    # HTTP Client Settings
    http_timeout_seconds: float = Field(
        default=30.0,
        gt=0,
        description="HTTP request timeout in seconds",
    )

    # Logging
    log_level: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
    )

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level is a valid Python logging level."""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        upper_v = v.upper()
        if upper_v not in valid_levels:
            raise ValueError(
                f"Invalid log level: {v}. Must be one of: {valid_levels}"
            )
        return upper_v

    @field_validator("gemini_api_key")
    @classmethod
    def validate_gemini_api_key(cls, v: Optional[str]) -> Optional[str]:
        """Warn if API key is not set."""
        if v is None:
            logger.warning(
                "MAIL_AGENT_GEMINI_API_KEY not set. "
                "LLM operations will fail until configured."
            )
        return v

    @property
    def webhook_url(self) -> str:
        """Full URL for the webhook endpoint."""
        return f"http://{self.webhook_host}:{self.webhook_port}{self.webhook_path}"

    def get_log_level_int(self) -> int:
        """Get the logging level as an integer."""
        return getattr(logging, self.log_level)


@lru_cache
def get_settings() -> Settings:
    """
    Get cached settings instance.

    Returns:
        Settings: The application settings singleton.

    Raises:
        ValidationError: If settings validation fails.
    """
    logger.debug("Loading Mail Agent settings")
    settings = Settings()
    logger.info(
        f"Settings loaded: api_url={settings.mock_smtp_api_url}, "
        f"agent_email={settings.agent_email}, "
        f"webhook_url={settings.webhook_url}"
    )
    return settings


def configure_logging(settings: Optional[Settings] = None) -> None:
    """
    Configure logging for the application.

    Args:
        settings: Optional settings instance. Uses get_settings() if not provided.
    """
    if settings is None:
        settings = get_settings()

    logging.basicConfig(
        level=settings.get_log_level_int(),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logger.info(f"Logging configured at level: {settings.log_level}")
