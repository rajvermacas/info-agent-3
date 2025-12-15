"""
Persistence Layer - SQLite-based storage for checkpoints and task state.

This package provides:
- Database connection management via async SQLite
- LangGraph checkpointer integration
- Task state CRUD operations (suspended tasks, results)
"""

from mail_agent.persistence.database import DatabaseManager
from mail_agent.persistence.checkpointer import create_checkpointer
from mail_agent.persistence.task_store import TaskStore

__all__ = [
    "DatabaseManager",
    "create_checkpointer",
    "TaskStore",
]
