"""
Tests for DatabaseManager - async SQLite connection management.
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mail_agent.persistence.database import (
    DatabaseManager,
    DatabaseError,
    DatabaseConnectionError,
)


@pytest.fixture
def temp_db_path():
    """Create a temporary database path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir) / "test.db"


@pytest.fixture
def mock_settings(temp_db_path):
    """Create mock settings with temporary database path."""
    settings = MagicMock()
    settings.sqlite_db_path = str(temp_db_path)
    return settings


class TestDatabaseManagerInit:
    """Tests for DatabaseManager initialization."""

    def test_init_with_settings(self, mock_settings):
        """Test initialization with explicit settings."""
        db = DatabaseManager(settings=mock_settings)
        assert db.db_path == Path(mock_settings.sqlite_db_path)
        assert not db.is_connected

    def test_init_creates_correct_path(self, mock_settings):
        """Test that database path is set correctly."""
        db = DatabaseManager(settings=mock_settings)
        assert str(db.db_path) == mock_settings.sqlite_db_path


class TestDatabaseManagerConnect:
    """Tests for database connection."""

    @pytest.mark.asyncio
    async def test_connect_creates_database(self, mock_settings, temp_db_path):
        """Test that connect creates the database file."""
        db = DatabaseManager(settings=mock_settings)
        await db.connect()

        try:
            assert temp_db_path.exists()
            assert db.is_connected
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_connect_creates_parent_directory(self, mock_settings):
        """Test that connect creates parent directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            nested_path = Path(tmpdir) / "nested" / "dir" / "test.db"
            mock_settings.sqlite_db_path = str(nested_path)
            db = DatabaseManager(settings=mock_settings)

            await db.connect()
            try:
                assert nested_path.parent.exists()
            finally:
                await db.close()

    @pytest.mark.asyncio
    async def test_connect_creates_tables(self, mock_settings):
        """Test that connect creates required tables."""
        db = DatabaseManager(settings=mock_settings)
        await db.connect()

        try:
            # Check suspended_tasks table exists
            result = await db.fetch_one(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='suspended_tasks'"
            )
            assert result is not None
            assert result[0] == "suspended_tasks"

            # Check task_results table exists
            result = await db.fetch_one(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='task_results'"
            )
            assert result is not None
            assert result[0] == "task_results"
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_double_connect_warns(self, mock_settings, caplog):
        """Test that connecting twice logs a warning."""
        import logging

        caplog.set_level(logging.WARNING)
        db = DatabaseManager(settings=mock_settings)
        await db.connect()

        try:
            await db.connect()  # Second connect should warn
            assert "already connected" in caplog.text.lower()
        finally:
            await db.close()


class TestDatabaseManagerClose:
    """Tests for database disconnection."""

    @pytest.mark.asyncio
    async def test_close_disconnects(self, mock_settings):
        """Test that close disconnects the database."""
        db = DatabaseManager(settings=mock_settings)
        await db.connect()
        assert db.is_connected

        await db.close()
        assert not db.is_connected

    @pytest.mark.asyncio
    async def test_close_without_connect_warns(self, mock_settings, caplog):
        """Test that closing without connecting logs a warning."""
        import logging

        caplog.set_level(logging.WARNING)
        db = DatabaseManager(settings=mock_settings)

        await db.close()
        assert "not connected" in caplog.text.lower()


class TestDatabaseManagerOperations:
    """Tests for database operations."""

    @pytest.mark.asyncio
    async def test_execute_inserts_data(self, mock_settings):
        """Test execute can insert data."""
        db = DatabaseManager(settings=mock_settings)
        await db.connect()

        try:
            await db.execute(
                """
                INSERT INTO task_results (task_id, status, completed_at)
                VALUES (?, ?, ?)
                """,
                ("test-task-1", "completed", "2025-12-15T10:00:00"),
            )
            await db.commit()

            result = await db.fetch_one(
                "SELECT task_id, status FROM task_results WHERE task_id = ?",
                ("test-task-1",),
            )
            assert result is not None
            assert result[0] == "test-task-1"
            assert result[1] == "completed"
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_fetch_all_returns_multiple_rows(self, mock_settings):
        """Test fetch_all returns all matching rows."""
        db = DatabaseManager(settings=mock_settings)
        await db.connect()

        try:
            # Insert multiple rows
            for i in range(3):
                await db.execute(
                    """
                    INSERT INTO task_results (task_id, status, completed_at)
                    VALUES (?, ?, ?)
                    """,
                    (f"test-task-{i}", "completed", "2025-12-15T10:00:00"),
                )
            await db.commit()

            results = await db.fetch_all(
                "SELECT task_id FROM task_results WHERE status = ?",
                ("completed",),
            )
            assert len(results) == 3
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_fetch_one_returns_none_for_no_match(self, mock_settings):
        """Test fetch_one returns None when no rows match."""
        db = DatabaseManager(settings=mock_settings)
        await db.connect()

        try:
            result = await db.fetch_one(
                "SELECT task_id FROM task_results WHERE task_id = ?",
                ("nonexistent",),
            )
            assert result is None
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_operations_fail_when_not_connected(self, mock_settings):
        """Test that operations fail when not connected."""
        db = DatabaseManager(settings=mock_settings)

        with pytest.raises(DatabaseConnectionError):
            await db.execute("SELECT 1")

        with pytest.raises(DatabaseConnectionError):
            await db.fetch_one("SELECT 1")

        with pytest.raises(DatabaseConnectionError):
            await db.commit()


class TestDatabaseManagerContextManager:
    """Tests for context manager usage."""

    @pytest.mark.asyncio
    async def test_context_manager_connects_and_closes(self, mock_settings):
        """Test that context manager connects on enter and closes on exit."""
        async with DatabaseManager(settings=mock_settings) as db:
            assert db.is_connected
            # Can perform operations
            result = await db.fetch_one("SELECT 1")
            assert result == (1,)

        # After exit, should be disconnected
        assert not db.is_connected

    @pytest.mark.asyncio
    async def test_context_manager_closes_on_exception(self, mock_settings):
        """Test that context manager closes even on exception."""
        db_ref = None
        try:
            async with DatabaseManager(settings=mock_settings) as db:
                db_ref = db
                raise ValueError("Test error")
        except ValueError:
            pass

        assert db_ref is not None
        assert not db_ref.is_connected
