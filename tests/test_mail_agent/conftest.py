"""
Pytest fixtures for mail_agent tests.
"""

import base64
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

from mail_agent.config import Settings
from mail_agent.tools.inbox_client import Attachment, Email


# ============================================================================
# Paths
# ============================================================================

TEST_DATA_DIR = Path(__file__).parent.parent.parent / "test_data"


# ============================================================================
# Settings Fixtures
# ============================================================================


@pytest.fixture
def mock_settings() -> Settings:
    """Create mock settings for testing."""
    return Settings(
        mock_smtp_api_url="http://localhost:8025",
        mock_smtp_host="localhost",
        mock_smtp_port=1025,
        agent_email="test-agent@gmail.com",
        webhook_host="localhost",
        webhook_port=9000,
        webhook_path="/webhook/email-received",
        gemini_api_key="test-api-key",
        gemini_model="gemini-2.5-flash",
        llm_temperature=0.0,
        llm_max_tokens=4096,
        max_attempts=5,
        sqlite_db_path=":memory:",
        http_timeout_seconds=30.0,
        log_level="DEBUG",
    )


# ============================================================================
# Test Data Fixtures
# ============================================================================


@pytest.fixture
def sample_excel_path() -> Path:
    """Path to sample Excel file."""
    return TEST_DATA_DIR / "sample_recipes.xlsx"


@pytest.fixture
def sample_csv_path() -> Path:
    """Path to sample CSV file."""
    return TEST_DATA_DIR / "sample_recipes.csv"


@pytest.fixture
def sample_invalid_path() -> Path:
    """Path to invalid Excel file (5 rows)."""
    return TEST_DATA_DIR / "sample_invalid.xlsx"


@pytest.fixture
def sample_excel_base64(sample_excel_path: Path) -> str:
    """Base64 encoded sample Excel file."""
    with open(sample_excel_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


@pytest.fixture
def sample_csv_base64(sample_csv_path: Path) -> str:
    """Base64 encoded sample CSV file."""
    with open(sample_csv_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


# ============================================================================
# Mock Email Fixtures
# ============================================================================


@pytest.fixture
def sample_attachment(sample_excel_base64: str) -> Attachment:
    """Sample email attachment."""
    return Attachment(
        filename="food_recipes.xlsx",
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        content_base64=sample_excel_base64,
        size_bytes=len(base64.b64decode(sample_excel_base64)),
    )


@pytest.fixture
def sample_email(sample_attachment: Attachment) -> Email:
    """Sample email with attachment."""
    return Email(
        email_id=UUID("12345678-1234-1234-1234-123456789012"),
        from_address="raj@gmail.com",
        to_addresses=["test-agent@gmail.com"],
        subject="Re: Request: 10 Food Recipes",
        body_text="Please find attached the recipes you requested.",
        body_html=None,
        attachments=[sample_attachment],
        headers={"In-Reply-To": "<original-message-id>"},
        received_at="2025-12-14T12:00:00.000000",
    )


@pytest.fixture
def sample_email_no_attachment() -> Email:
    """Sample email without attachment."""
    return Email(
        email_id=UUID("12345678-1234-1234-1234-123456789013"),
        from_address="raj@gmail.com",
        to_addresses=["test-agent@gmail.com"],
        subject="Re: Request",
        body_text="Sorry, I don't have that information.",
        body_html=None,
        attachments=[],
        headers={},
        received_at="2025-12-14T12:00:00.000000",
    )


# ============================================================================
# Mock Client Fixtures
# ============================================================================


@pytest.fixture
def mock_httpx_client() -> AsyncMock:
    """Mock httpx.AsyncClient."""
    client = AsyncMock()
    client.aclose = AsyncMock()
    return client
