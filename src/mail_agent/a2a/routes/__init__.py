"""
A2A Routes - REST API endpoints for the A2A server.

Provides:
- Task status polling endpoint (GET /tasks/{task_id})
- Task progress SSE streaming endpoint (GET /tasks/{task_id}/progress)
- Task DAG endpoint (GET /tasks/{task_id}/dag)
"""

from mail_agent.a2a.routes.dag import create_dag_router
from mail_agent.a2a.routes.progress import create_progress_router
from mail_agent.a2a.routes.tasks import create_tasks_router

__all__ = [
    "create_dag_router",
    "create_progress_router",
    "create_tasks_router",
]
