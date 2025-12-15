"""
Task Manager - Non-blocking task lifecycle management for A2A mode.

This package provides:
- TaskManager: Orchestrates task suspension, resumption, and webhook routing
- Models: Pydantic models for task state representation
"""

from mail_agent.task_manager.models import (
    TaskState,
    TaskStatus,
    SuspendedTaskInfo,
    TaskResult,
    WebhookPayload,
)
from mail_agent.task_manager.manager import TaskManager

__all__ = [
    "TaskManager",
    "TaskState",
    "TaskStatus",
    "SuspendedTaskInfo",
    "TaskResult",
    "WebhookPayload",
]
