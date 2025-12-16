"""
Checkpointer Factory - Creates LangGraph AsyncSqliteSaver instances.

Provides factory functions for creating checkpointer instances that integrate
with the LangGraph state machine for checkpoint persistence.
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from mail_agent.config import Settings, get_settings


logger = logging.getLogger(__name__)


class CheckpointerError(Exception):
    """Base exception for checkpointer operations."""

    pass


@asynccontextmanager
async def create_checkpointer(
    settings: Optional[Settings] = None,
) -> AsyncIterator[AsyncSqliteSaver]:
    """
    Create a LangGraph AsyncSqliteSaver checkpointer as an async context manager.

    The checkpointer manages LangGraph state persistence, allowing the agent
    to save state at interrupt points and resume later.

    Must be used with 'async with' to ensure proper lifecycle management.
    The checkpointer connection is automatically closed when the context exits.

    Args:
        settings: Configuration settings. Uses get_settings() if not provided.

    Yields:
        Initialized AsyncSqliteSaver ready for use with LangGraph.

    Raises:
        CheckpointerError: If checkpointer creation fails.

    Example:
        async with create_checkpointer(settings) as checkpointer:
            graph = compile_mail_agent_graph(checkpointer=checkpointer)
            # Use graph...
        # Checkpointer automatically closed here
    """
    if settings is None:
        settings = get_settings()

    db_path = settings.sqlite_db_path
    logger.info(f"Creating AsyncSqliteSaver checkpointer with db_path: {db_path}")

    try:
        # AsyncSqliteSaver.from_conn_string returns an async context manager
        # that handles connection setup and teardown automatically
        async with AsyncSqliteSaver.from_conn_string(db_path) as checkpointer:
            logger.info("AsyncSqliteSaver checkpointer created and initialized")
            yield checkpointer
            logger.info("Closing AsyncSqliteSaver checkpointer")

    except Exception as e:
        logger.error(f"Failed to create checkpointer: {e}")
        raise CheckpointerError(f"Failed to create checkpointer: {e}") from e
