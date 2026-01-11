"""
Task Manager Models - Pydantic models for task state representation.

Provides strongly-typed models for:
- Task status enumeration
- Suspended task information
- Task results
- Webhook payloads
"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class TaskState(str, Enum):
    """
    Task state enumeration for non-blocking A2A mode.

    States:
        CREATED: Task created, not yet started
        WORKING: Task actively executing
        SUSPENDED: Task paused, waiting for external input (POC reply)
        RESUMED: Task resuming from suspension
        COMPLETED: Task finished successfully
        FAILED: Task failed with error
    """

    CREATED = "created"
    WORKING = "working"
    SUSPENDED = "suspended"
    RESUMED = "resumed"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskStatus(BaseModel):
    """
    Current status of a task for API responses.

    Used by GET /tasks/{task_id} endpoint to report task state.
    """

    task_id: str = Field(description="Unique task identifier")
    state: TaskState = Field(description="Current task state")
    message: str = Field(description="Human-readable status message")
    poc_email: Optional[str] = Field(
        default=None,
        description="POC email if task is suspended waiting for reply",
    )
    created_at: Optional[datetime] = Field(
        default=None,
        description="Task creation timestamp",
    )
    expires_at: Optional[datetime] = Field(
        default=None,
        description="Expiration timestamp for suspended tasks",
    )
    completed_at: Optional[datetime] = Field(
        default=None,
        description="Completion timestamp for finished tasks",
    )
    result: Optional[dict[str, Any]] = Field(
        default=None,
        description="Task result data (for completed tasks)",
    )
    error: Optional[str] = Field(
        default=None,
        description="Error message (for failed tasks)",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "task_id": "task-abc-123",
                "state": "suspended",
                "message": "Waiting for reply from poc@example.com",
                "poc_email": "poc@example.com",
                "created_at": "2025-12-15T10:00:00Z",
                "expires_at": "2025-12-15T11:00:00Z",
            }
        }
    )


class SuspendedTaskInfo(BaseModel):
    """
    Information about a suspended task.

    Used internally to track suspended tasks and their checkpoint references.
    """

    task_id: str = Field(description="Unique task identifier")
    poc_email: str = Field(description="POC email the task is waiting for")
    thread_id: str = Field(description="LangGraph thread ID for checkpoint")
    created_at: datetime = Field(description="When task was suspended")
    expires_at: datetime = Field(description="When task will expire")
    interrupt_data: Optional[dict[str, Any]] = Field(
        default=None,
        description="Data from the interrupt point",
    )

    def is_expired(self) -> bool:
        """Check if the task has expired."""
        return datetime.now(self.created_at.tzinfo) > self.expires_at


class TaskResult(BaseModel):
    """
    Result of a completed or failed task.

    Stored in database and returned to clients polling for results.
    """

    task_id: str = Field(description="Unique task identifier")
    status: str = Field(description="Final status: 'completed' or 'failed'")
    result: Optional[dict[str, Any]] = Field(
        default=None,
        description="Result data for successful tasks",
    )
    error: Optional[str] = Field(
        default=None,
        description="Error message for failed tasks",
    )
    completed_at: datetime = Field(description="When task finished")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "task_id": "task-abc-123",
                "status": "completed",
                "result": {
                    "success": True,
                    "data": "Q4 sales data: $1.2M revenue...",
                    "poc_email": "poc@example.com",
                },
                "completed_at": "2025-12-15T10:35:00Z",
            }
        }
    )


class WebhookPayload(BaseModel):
    """
    Webhook payload from mock SMTP server.

    Contains email notification data that triggers task resumption.
    """

    model_config = {"populate_by_name": True}

    event: str = Field(description="Event type, e.g., 'email.received'")
    email_id: str = Field(description="Unique email identifier")
    from_address: str = Field(alias="from", description="Sender email address")
    to: list[str] = Field(description="Recipient email addresses")
    subject: str = Field(description="Email subject line")
    has_attachments: bool = Field(
        default=False,
        description="Whether email has attachments",
    )
    attachment_count: int = Field(
        default=0,
        description="Number of attachments",
    )
    received_at: str = Field(description="ISO timestamp when email was received")
    body_preview: str = Field(
        default="",
        description="Preview of email body (first 100 chars)",
    )

    def to_resume_data(self) -> dict[str, Any]:
        """
        Convert to data dict for resuming the graph.

        Returns:
            Dict with email_id and metadata for interrupt resume.
        """
        return {
            "email_id": self.email_id,
            "from_address": self.from_address,
            "subject": self.subject,
            "has_attachments": self.has_attachments,
            "received_at": self.received_at,
        }


class SSEEvent(BaseModel):
    """
    Server-Sent Event data for streaming progress updates.

    Sent to clients during graph execution to provide real-time feedback.
    """

    task_id: str = Field(description="Task identifier")
    state: TaskState = Field(description="Current task state")
    message: str = Field(description="Progress message")
    node: Optional[str] = Field(
        default=None,
        description="Current graph node being executed",
    )
    poc_email: Optional[str] = Field(
        default=None,
        description="POC email (for suspended state)",
    )
    result: Optional[dict[str, Any]] = Field(
        default=None,
        description="Result data (for completed state)",
    )
    error: Optional[str] = Field(
        default=None,
        description="Error message (for failed state)",
    )

    def to_sse_data(self) -> str:
        """
        Convert to SSE data format (JSON string).

        Returns:
            JSON string for SSE data field.
        """
        return self.model_dump_json(exclude_none=True)
