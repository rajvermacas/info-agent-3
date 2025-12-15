"""
Webhook package - FastAPI server for receiving email notifications.

Contains:
- WebhookServer: FastAPI server for receiving webhook callbacks
- TaskRouter: Routes webhook events to correct A2A tasks based on sender email
"""

from mail_agent.webhook.server import WebhookServer, WebhookEvent, WebhookPayload
from mail_agent.webhook.router import (
    TaskRouter,
    TaskRouterError,
    DuplicatePOCRegistrationError,
    TaskNotFoundError,
)

__all__ = [
    "WebhookServer",
    "WebhookEvent",
    "WebhookPayload",
    "TaskRouter",
    "TaskRouterError",
    "DuplicatePOCRegistrationError",
    "TaskNotFoundError",
]
