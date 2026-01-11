"""
Database Manager - Async SQLite connection and table management.

Provides centralized database access for:
- LangGraph checkpointer tables (managed by langgraph-checkpoint-sqlite)
- Custom tables: suspended_tasks, task_results
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncGenerator, Optional

import aiosqlite

from mail_agent.config import Settings, get_settings


logger = logging.getLogger(__name__)


class DatabaseError(Exception):
    """Base exception for database operations."""

    pass


class DatabaseConnectionError(DatabaseError):
    """Raised when database connection fails."""

    pass


class DatabaseManager:
    """
    Async SQLite database manager for mail agent persistence.

    Manages database lifecycle, table creation, and provides connection access
    for both LangGraph checkpointer and custom task state tables.

    Attributes:
        db_path: Path to SQLite database file.
        _connection: Active database connection (when open).
    """

    # SQL statements for custom table creation
    CREATE_SUSPENDED_TASKS_TABLE = """
        CREATE TABLE IF NOT EXISTS suspended_tasks (
            task_id TEXT PRIMARY KEY,
            poc_email TEXT NOT NULL,
            thread_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            interrupt_data TEXT,
            UNIQUE(poc_email)
        )
    """

    CREATE_SUSPENDED_TASKS_INDEX = """
        CREATE INDEX IF NOT EXISTS idx_suspended_tasks_poc_email
        ON suspended_tasks(poc_email)
    """

    CREATE_SUSPENDED_TASKS_EXPIRES_INDEX = """
        CREATE INDEX IF NOT EXISTS idx_suspended_tasks_expires_at
        ON suspended_tasks(expires_at)
    """

    CREATE_TASK_RESULTS_TABLE = """
        CREATE TABLE IF NOT EXISTS task_results (
            task_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            result TEXT,
            error TEXT,
            completed_at TEXT NOT NULL
        )
    """

    CREATE_TASK_RESULTS_STATUS_INDEX = """
        CREATE INDEX IF NOT EXISTS idx_task_results_status
        ON task_results(status)
    """

    def __init__(self, settings: Optional[Settings] = None) -> None:
        """
        Initialize database manager.

        Args:
            settings: Configuration settings. Uses get_settings() if not provided.

        Raises:
            ValueError: If settings is None and get_settings() fails.
        """
        if settings is None:
            settings = get_settings()

        self._settings = settings
        self._db_path = Path(settings.sqlite_db_path)
        self._connection: Optional[aiosqlite.Connection] = None

        logger.info(f"DatabaseManager initialized with path: {self._db_path}")

    @property
    def db_path(self) -> Path:
        """Get the database file path."""
        return self._db_path

    @property
    def is_connected(self) -> bool:
        """Check if database connection is active."""
        return self._connection is not None

    async def connect(self) -> None:
        """
        Open database connection and initialize tables.

        Creates the database file and parent directories if they don't exist.
        Also creates custom tables for task state management.

        Raises:
            DatabaseConnectionError: If connection fails.
        """
        if self._connection is not None:
            logger.warning("Database already connected, skipping reconnection")
            return

        try:
            # Ensure parent directory exists
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            logger.debug(f"Ensured parent directory exists: {self._db_path.parent}")

            # Open connection
            logger.info(f"Connecting to database: {self._db_path}")
            self._connection = await aiosqlite.connect(str(self._db_path))

            # Enable WAL mode for better concurrency
            await self._connection.execute("PRAGMA journal_mode=WAL")
            await self._connection.execute("PRAGMA busy_timeout=5000")
            await self._connection.commit()

            # Create custom tables
            await self._create_tables()

            logger.info("Database connection established and tables initialized")

        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            self._connection = None
            raise DatabaseConnectionError(f"Failed to connect to database: {e}") from e

    async def _create_tables(self) -> None:
        """Create custom tables if they don't exist."""
        if self._connection is None:
            raise DatabaseConnectionError("Not connected to database")

        logger.debug("Creating custom tables if not exist")

        # Create suspended_tasks table
        await self._connection.execute(self.CREATE_SUSPENDED_TASKS_TABLE)
        await self._connection.execute(self.CREATE_SUSPENDED_TASKS_INDEX)
        await self._connection.execute(self.CREATE_SUSPENDED_TASKS_EXPIRES_INDEX)
        logger.debug("suspended_tasks table ready")

        # Create task_results table
        await self._connection.execute(self.CREATE_TASK_RESULTS_TABLE)
        await self._connection.execute(self.CREATE_TASK_RESULTS_STATUS_INDEX)
        logger.debug("task_results table ready")

        await self._connection.commit()
        logger.info("All custom tables created/verified")

    async def close(self) -> None:
        """Close database connection."""
        if self._connection is None:
            logger.warning("Database not connected, skipping close")
            return

        try:
            logger.info("Closing database connection")
            await self._connection.close()
            self._connection = None
            logger.info("Database connection closed")

        except Exception as e:
            logger.error(f"Error closing database connection: {e}")
            self._connection = None
            raise DatabaseError(f"Error closing database: {e}") from e

    @asynccontextmanager
    async def get_connection(self) -> AsyncGenerator[aiosqlite.Connection, None]:
        """
        Get database connection as async context manager.

        Usage:
            async with db_manager.get_connection() as conn:
                await conn.execute(...)

        Yields:
            Active database connection.

        Raises:
            DatabaseConnectionError: If not connected.
        """
        if self._connection is None:
            raise DatabaseConnectionError("Database not connected. Call connect() first.")

        try:
            yield self._connection
        except Exception as e:
            logger.error(f"Database operation failed: {e}")
            raise

    async def execute(
        self,
        sql: str,
        parameters: tuple[Any, ...] = (),
    ) -> aiosqlite.Cursor:
        """
        Execute a SQL statement.

        Args:
            sql: SQL statement to execute.
            parameters: Parameters to bind to the statement.

        Returns:
            Cursor from the executed statement.

        Raises:
            DatabaseConnectionError: If not connected.
            DatabaseError: If execution fails.
        """
        if self._connection is None:
            raise DatabaseConnectionError("Database not connected")

        try:
            logger.debug(f"Executing SQL: {sql[:100]}...")
            cursor = await self._connection.execute(sql, parameters)
            return cursor

        except Exception as e:
            logger.error(f"SQL execution failed: {e}")
            raise DatabaseError(f"SQL execution failed: {e}") from e

    async def execute_many(
        self,
        sql: str,
        parameters_seq: list[tuple[Any, ...]],
    ) -> None:
        """
        Execute a SQL statement with multiple parameter sets.

        Args:
            sql: SQL statement to execute.
            parameters_seq: Sequence of parameter tuples.

        Raises:
            DatabaseConnectionError: If not connected.
            DatabaseError: If execution fails.
        """
        if self._connection is None:
            raise DatabaseConnectionError("Database not connected")

        try:
            logger.debug(f"Executing SQL (many): {sql[:100]}... ({len(parameters_seq)} rows)")
            await self._connection.executemany(sql, parameters_seq)

        except Exception as e:
            logger.error(f"SQL execution (many) failed: {e}")
            raise DatabaseError(f"SQL execution failed: {e}") from e

    async def fetch_one(
        self,
        sql: str,
        parameters: tuple[Any, ...] = (),
    ) -> Optional[tuple[Any, ...]]:
        """
        Execute SQL and fetch one row.

        Args:
            sql: SQL query to execute.
            parameters: Parameters to bind.

        Returns:
            Single row tuple or None if no results.

        Raises:
            DatabaseConnectionError: If not connected.
            DatabaseError: If query fails.
        """
        cursor = await self.execute(sql, parameters)
        row = await cursor.fetchone()
        logger.debug(f"Fetched one row: {'found' if row else 'none'}")
        return row

    async def fetch_all(
        self,
        sql: str,
        parameters: tuple[Any, ...] = (),
    ) -> list[tuple[Any, ...]]:
        """
        Execute SQL and fetch all rows.

        Args:
            sql: SQL query to execute.
            parameters: Parameters to bind.

        Returns:
            List of row tuples.

        Raises:
            DatabaseConnectionError: If not connected.
            DatabaseError: If query fails.
        """
        cursor = await self.execute(sql, parameters)
        rows = await cursor.fetchall()
        logger.debug(f"Fetched {len(rows)} rows")
        return rows

    async def commit(self) -> None:
        """
        Commit current transaction.

        Raises:
            DatabaseConnectionError: If not connected.
            DatabaseError: If commit fails.
        """
        if self._connection is None:
            raise DatabaseConnectionError("Database not connected")

        try:
            await self._connection.commit()
            logger.debug("Transaction committed")

        except Exception as e:
            logger.error(f"Commit failed: {e}")
            raise DatabaseError(f"Commit failed: {e}") from e

    async def rollback(self) -> None:
        """
        Rollback current transaction.

        Raises:
            DatabaseConnectionError: If not connected.
            DatabaseError: If rollback fails.
        """
        if self._connection is None:
            raise DatabaseConnectionError("Database not connected")

        try:
            await self._connection.rollback()
            logger.debug("Transaction rolled back")

        except Exception as e:
            logger.error(f"Rollback failed: {e}")
            raise DatabaseError(f"Rollback failed: {e}") from e

    async def __aenter__(self) -> "DatabaseManager":
        """Async context manager entry - connect to database."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit - close database connection."""
        await self.close()
