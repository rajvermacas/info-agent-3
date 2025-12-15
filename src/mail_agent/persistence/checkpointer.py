"""
Checkpointer Factory - Creates LangGraph AsyncSqliteSaver instances.

Provides factory functions for creating checkpointer instances that integrate
with the LangGraph state machine for checkpoint persistence.
"""

import logging
from typing import Optional

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from mail_agent.config import Settings, get_settings


logger = logging.getLogger(__name__)


class CheckpointerError(Exception):
    """Base exception for checkpointer operations."""

    pass


async def create_checkpointer(
    settings: Optional[Settings] = None,
) -> AsyncSqliteSaver:
    """
    Create and initialize a LangGraph AsyncSqliteSaver checkpointer.

    The checkpointer manages LangGraph state persistence, allowing the agent
    to save state at interrupt points and resume later.

    Args:
        settings: Configuration settings. Uses get_settings() if not provided.

    Returns:
        Initialized AsyncSqliteSaver ready for use with LangGraph.

    Raises:
        CheckpointerError: If checkpointer creation fails.
    """
    if settings is None:
        settings = get_settings()

    db_path = settings.sqlite_db_path
    logger.info(f"Creating AsyncSqliteSaver checkpointer with db_path: {db_path}")

    try:
        # Create the checkpointer using the connection string format
        # AsyncSqliteSaver.from_conn_string creates and manages its own connection
        checkpointer = AsyncSqliteSaver.from_conn_string(db_path)

        # Setup the checkpointer (creates required tables)
        await checkpointer.setup()

        logger.info("AsyncSqliteSaver checkpointer created and initialized")
        return checkpointer

    except Exception as e:
        logger.error(f"Failed to create checkpointer: {e}")
        raise CheckpointerError(f"Failed to create checkpointer: {e}") from e


async def close_checkpointer(checkpointer: AsyncSqliteSaver) -> None:
    """
    Close a checkpointer and release its resources.

    Args:
        checkpointer: The checkpointer to close.

    Note:
        This is a best-effort operation. Errors are logged but not raised.
    """
    try:
        logger.info("Closing AsyncSqliteSaver checkpointer")
        # AsyncSqliteSaver manages its own connection lifecycle
        # The connection is closed when the checkpointer goes out of scope
        # But we can explicitly close if needed by accessing internal connection
        if hasattr(checkpointer, 'conn') and checkpointer.conn is not None:
            await checkpointer.conn.close()
        logger.info("Checkpointer closed")

    except Exception as e:
        logger.warning(f"Error closing checkpointer (non-fatal): {e}")
