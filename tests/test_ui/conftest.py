"""
Test fixtures for UI module tests.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from fastapi.testclient import TestClient

from ui.config import Settings
from ui.services.a2a_client import A2AClientService, TaskInfo, AgentInfo
from ui.services.smtp_client import (
    SMTPClientService,
    InboxSummary,
    EmailSummary,
    Email,
    Attachment,
)
from ui.services.smtp_sender import SMTPSenderService
from ui.services.sse_client import SSEClientService


@pytest.fixture
def settings() -> Settings:
    """Create test settings."""
    return Settings(
        host="127.0.0.1",
        port=8080,
        a2a_server_url="http://localhost:8000",
        mock_smtp_api_url="http://localhost:8025",
        default_inbox_email="test@example.com",
        log_level="DEBUG",
    )


@pytest.fixture
def mock_a2a_client() -> AsyncMock:
    """Create a mock A2A client service."""
    client = AsyncMock(spec=A2AClientService)
    client.close = AsyncMock()
    client.check_health = AsyncMock(return_value=True)
    client.get_agent_info = AsyncMock(
        return_value=AgentInfo(
            name="Mail Agent",
            version="1.0.0",
            description="Test agent",
            url="http://localhost:8000",
            capabilities=["email_communication"],
        )
    )
    client.send_task = AsyncMock(
        return_value=TaskInfo(
            task_id="test-task-123",
            state="submitted",
            message="Task submitted successfully",
        )
    )
    client.get_task_status = AsyncMock(
        return_value=TaskInfo(
            task_id="test-task-123",
            state="working",
            message="Processing...",
            created_at=datetime.now(),
        )
    )
    client.list_tasks = AsyncMock(
        return_value=[
            TaskInfo(
                task_id="test-task-123",
                state="working",
                message="Processing...",
                created_at=datetime.now(),
            ),
            TaskInfo(
                task_id="test-task-456",
                state="completed",
                message="Done",
                created_at=datetime.now(),
                completed_at=datetime.now(),
            ),
        ]
    )
    return client


@pytest.fixture
def mock_smtp_client() -> AsyncMock:
    """Create a mock SMTP client service."""
    client = AsyncMock(spec=SMTPClientService)
    client.close = AsyncMock()
    client.check_health = AsyncMock(return_value=True)
    client.list_inboxes = AsyncMock(
        return_value=[
            InboxSummary(
                email_address="test@example.com",
                email_count=5,
                last_email_at=datetime.now(),
            ),
            InboxSummary(
                email_address="info-agent@gmail.com",
                email_count=3,
                last_email_at=datetime.now(),
            ),
        ]
    )
    client.get_inbox = AsyncMock(
        return_value=[
            EmailSummary(
                id="email-1",
                from_address="sender@example.com",
                subject="Test Subject 1",
                received_at=datetime.now(),
                has_attachments=False,
            ),
            EmailSummary(
                id="email-2",
                from_address="sender2@example.com",
                subject="Test Subject 2 with Attachment",
                received_at=datetime.now(),
                has_attachments=True,
            ),
        ]
    )
    client.get_email = AsyncMock(
        return_value=Email(
            id="email-1",
            from_address="sender@example.com",
            to_addresses=["test@example.com"],
            subject="Test Subject",
            body_text="This is a test email body.",
            received_at=datetime.now(),
            attachments=[
                Attachment(
                    filename="test.csv",
                    content_type="text/csv",
                    content_base64="dGVzdCxkYXRhCjEsMgo=",
                    size_bytes=16,
                )
            ],
            has_attachments=True,
        )
    )
    client.send_email = AsyncMock(return_value="new-email-id-123")
    return client


@pytest.fixture
def test_client(
    settings: Settings,
    mock_a2a_client: AsyncMock,
    mock_smtp_client: AsyncMock,
) -> TestClient:
    """Create a test client with mocked dependencies."""
    import jinja2
    from starlette.templating import Jinja2Templates
    from pathlib import Path
    from ui.main import UIServerResources

    # Create templates
    templates_dir = Path(__file__).parent.parent.parent / "src" / "ui" / "templates"

    # Create jinja2 env explicitly to avoid the import timing issue
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(templates_dir)),
        autoescape=jinja2.select_autoescape(["html", "xml"]),
    )
    templates = Jinja2Templates(env=env)

    # Create resources
    smtp_sender = AsyncMock(spec=SMTPSenderService)
    sse_client = AsyncMock(spec=SSEClientService)
    resources = UIServerResources(
        settings=settings,
        a2a_client=mock_a2a_client,
        smtp_client=mock_smtp_client,
        smtp_sender=smtp_sender,
        sse_client=sse_client,
        templates=templates,
    )

    # Patch the global resources and create app
    with patch("ui.main._resources", resources):
        with patch("ui.main.get_resources", return_value=resources):
            with patch("ui.routes.pages.get_resources", return_value=resources):
                with patch("ui.routes.send_request.get_resources", return_value=resources):
                    with patch("ui.routes.inbox.get_resources", return_value=resources):
                        with patch("ui.routes.dashboard.get_resources", return_value=resources):
                            from ui.main import create_app
                            app = create_app()
                            client = TestClient(app)
                            yield client
