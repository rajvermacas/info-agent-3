"""
Webhook package - FastAPI server for receiving email notifications.

Contains:
- WebhookServer: FastAPI server for receiving webhook callbacks
- WebhookEvent/WebhookPayload: Data models for webhook events

Note: TaskRouter has been replaced by TaskManager in mail_agent.task_manager
for non-blocking A2A mode.
"""

from mail_agent.webhook.server import WebhookServer, WebhookEvent, WebhookPayload

__all__ = [
    "WebhookServer",
    "WebhookEvent",
    "WebhookPayload",
]
