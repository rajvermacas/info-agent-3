"""
A2A Routes - REST API endpoints for the A2A server.

Provides:
- Task status polling endpoint (GET /tasks/{task_id})
"""

from mail_agent.a2a.routes.tasks import create_tasks_router

__all__ = [
    "create_tasks_router",
]
