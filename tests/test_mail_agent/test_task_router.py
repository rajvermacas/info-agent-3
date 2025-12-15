"""
Unit tests for TaskRouter class.

Tests cover:
- Registration and unregistration of task-POC mappings
- Event routing based on sender email
- Concurrent access safety
- Timeout handling
- Edge cases and error conditions
"""

import asyncio
import pytest
from unittest.mock import MagicMock

from mail_agent.webhook.router import (
    TaskRouter,
    TaskRouterError,
    DuplicatePOCRegistrationError,
    TaskNotFoundError,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def task_router() -> TaskRouter:
    """Create a fresh TaskRouter instance for each test."""
    return TaskRouter()


@pytest.fixture
def sample_webhook_payload() -> dict:
    """Create a sample webhook payload."""
    return {
        "event": "email.received",
        "email_id": "test-email-id-123",
        "from": "poc@example.com",
        "to": ["agent@example.com"],
        "subject": "Re: Test Request",
        "has_attachments": True,
        "attachment_count": 1,
        "received_at": "2025-12-15T10:00:00.000000",
        "body_preview": "Here is the data you requested...",
    }


# ============================================================================
# Registration Tests
# ============================================================================


class TestTaskRouterRegistration:
    """Test registration functionality."""

    @pytest.mark.asyncio
    async def test_register_single_task(self, task_router: TaskRouter) -> None:
        """Test registering a single task-POC mapping."""
        await task_router.register("task-001", "poc@example.com")

        assert task_router.registration_count == 1
        assert task_router.is_registered("task-001")
        assert task_router.get_task_for_poc("poc@example.com") == "task-001"

    @pytest.mark.asyncio
    async def test_register_multiple_tasks(self, task_router: TaskRouter) -> None:
        """Test registering multiple task-POC mappings."""
        await task_router.register("task-001", "poc1@example.com")
        await task_router.register("task-002", "poc2@example.com")
        await task_router.register("task-003", "poc3@example.com")

        assert task_router.registration_count == 3
        assert task_router.is_registered("task-001")
        assert task_router.is_registered("task-002")
        assert task_router.is_registered("task-003")

    @pytest.mark.asyncio
    async def test_register_case_insensitive_email(
        self, task_router: TaskRouter
    ) -> None:
        """Test that POC email registration is case-insensitive."""
        await task_router.register("task-001", "POC@Example.COM")

        assert task_router.get_task_for_poc("poc@example.com") == "task-001"
        assert task_router.get_task_for_poc("POC@EXAMPLE.COM") == "task-001"
        assert task_router.get_task_for_poc("Poc@Example.Com") == "task-001"

    @pytest.mark.asyncio
    async def test_register_duplicate_poc_raises_error(
        self, task_router: TaskRouter
    ) -> None:
        """Test that registering a duplicate POC raises DuplicatePOCRegistrationError."""
        await task_router.register("task-001", "poc@example.com")

        with pytest.raises(DuplicatePOCRegistrationError) as exc_info:
            await task_router.register("task-002", "poc@example.com")

        assert "already registered to task task-001" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_register_duplicate_poc_case_insensitive(
        self, task_router: TaskRouter
    ) -> None:
        """Test that duplicate POC detection is case-insensitive."""
        await task_router.register("task-001", "poc@example.com")

        with pytest.raises(DuplicatePOCRegistrationError):
            await task_router.register("task-002", "POC@EXAMPLE.COM")

    @pytest.mark.asyncio
    async def test_register_empty_task_id_raises_error(
        self, task_router: TaskRouter
    ) -> None:
        """Test that empty task_id raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            await task_router.register("", "poc@example.com")

        assert "task_id cannot be empty" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_register_empty_poc_email_raises_error(
        self, task_router: TaskRouter
    ) -> None:
        """Test that empty poc_email raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            await task_router.register("task-001", "")

        assert "poc_email cannot be empty" in str(exc_info.value)


# ============================================================================
# Unregistration Tests
# ============================================================================


class TestTaskRouterUnregistration:
    """Test unregistration functionality."""

    @pytest.mark.asyncio
    async def test_unregister_existing_task(self, task_router: TaskRouter) -> None:
        """Test unregistering an existing task."""
        await task_router.register("task-001", "poc@example.com")
        assert task_router.registration_count == 1

        await task_router.unregister("task-001", "poc@example.com")

        assert task_router.registration_count == 0
        assert not task_router.is_registered("task-001")
        assert task_router.get_task_for_poc("poc@example.com") is None

    @pytest.mark.asyncio
    async def test_unregister_nonexistent_task_no_error(
        self, task_router: TaskRouter
    ) -> None:
        """Test that unregistering a nonexistent task does not raise an error."""
        # Should not raise any exception
        await task_router.unregister("nonexistent-task", "nobody@example.com")
        assert task_router.registration_count == 0

    @pytest.mark.asyncio
    async def test_unregister_preserves_other_registrations(
        self, task_router: TaskRouter
    ) -> None:
        """Test that unregistering one task preserves other registrations."""
        await task_router.register("task-001", "poc1@example.com")
        await task_router.register("task-002", "poc2@example.com")
        await task_router.register("task-003", "poc3@example.com")

        await task_router.unregister("task-002", "poc2@example.com")

        assert task_router.registration_count == 2
        assert task_router.is_registered("task-001")
        assert not task_router.is_registered("task-002")
        assert task_router.is_registered("task-003")


# ============================================================================
# Event Routing Tests
# ============================================================================


class TestTaskRouterEventRouting:
    """Test event routing functionality."""

    @pytest.mark.asyncio
    async def test_route_event_to_registered_task(
        self, task_router: TaskRouter, sample_webhook_payload: dict
    ) -> None:
        """Test routing an event to a registered task."""
        await task_router.register("task-001", "poc@example.com")

        result = await task_router.route_event(sample_webhook_payload)

        assert result is True

    @pytest.mark.asyncio
    async def test_route_event_unknown_sender_returns_false(
        self, task_router: TaskRouter, sample_webhook_payload: dict
    ) -> None:
        """Test that routing from an unknown sender returns False."""
        await task_router.register("task-001", "different@example.com")

        result = await task_router.route_event(sample_webhook_payload)

        assert result is False

    @pytest.mark.asyncio
    async def test_route_event_no_registrations_returns_false(
        self, task_router: TaskRouter, sample_webhook_payload: dict
    ) -> None:
        """Test that routing with no registrations returns False."""
        result = await task_router.route_event(sample_webhook_payload)

        assert result is False

    @pytest.mark.asyncio
    async def test_route_event_missing_from_field_returns_false(
        self, task_router: TaskRouter
    ) -> None:
        """Test that routing a payload without 'from' field returns False."""
        await task_router.register("task-001", "poc@example.com")

        payload_no_from = {"event": "email.received", "email_id": "test-123"}
        result = await task_router.route_event(payload_no_from)

        assert result is False

    @pytest.mark.asyncio
    async def test_route_event_uses_from_address_field(
        self, task_router: TaskRouter
    ) -> None:
        """Test that routing works with 'from_address' field as fallback."""
        await task_router.register("task-001", "poc@example.com")

        payload_with_from_address = {
            "event": "email.received",
            "email_id": "test-123",
            "from_address": "poc@example.com",
        }
        result = await task_router.route_event(payload_with_from_address)

        assert result is True

    @pytest.mark.asyncio
    async def test_route_event_case_insensitive(
        self, task_router: TaskRouter
    ) -> None:
        """Test that event routing is case-insensitive for sender email."""
        await task_router.register("task-001", "poc@example.com")

        payload_uppercase = {
            "event": "email.received",
            "email_id": "test-123",
            "from": "POC@EXAMPLE.COM",
        }
        result = await task_router.route_event(payload_uppercase)

        assert result is True


# ============================================================================
# Wait For Event Tests
# ============================================================================


class TestTaskRouterWaitForEvent:
    """Test wait_for_event functionality."""

    @pytest.mark.asyncio
    async def test_wait_for_event_receives_routed_event(
        self, task_router: TaskRouter, sample_webhook_payload: dict
    ) -> None:
        """Test that wait_for_event receives an event after routing."""
        await task_router.register("task-001", "poc@example.com")

        # Route the event
        await task_router.route_event(sample_webhook_payload)

        # Wait for the event
        event = await task_router.wait_for_event("task-001", timeout=1.0)

        assert event == sample_webhook_payload
        assert event["email_id"] == "test-email-id-123"

    @pytest.mark.asyncio
    async def test_wait_for_event_timeout(self, task_router: TaskRouter) -> None:
        """Test that wait_for_event raises TimeoutError on timeout."""
        await task_router.register("task-001", "poc@example.com")

        with pytest.raises(asyncio.TimeoutError):
            await task_router.wait_for_event("task-001", timeout=0.1)

    @pytest.mark.asyncio
    async def test_wait_for_event_unregistered_task_raises_error(
        self, task_router: TaskRouter
    ) -> None:
        """Test that wait_for_event raises TaskNotFoundError for unregistered task."""
        with pytest.raises(TaskNotFoundError) as exc_info:
            await task_router.wait_for_event("nonexistent-task", timeout=1.0)

        assert "not registered" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_wait_for_event_concurrent_routing(
        self, task_router: TaskRouter
    ) -> None:
        """Test concurrent routing and waiting."""
        await task_router.register("task-001", "poc@example.com")

        payload = {
            "event": "email.received",
            "email_id": "concurrent-test-id",
            "from": "poc@example.com",
        }

        async def route_after_delay():
            await asyncio.sleep(0.1)
            await task_router.route_event(payload)

        # Start routing in background
        route_task = asyncio.create_task(route_after_delay())

        # Wait for event
        event = await task_router.wait_for_event("task-001", timeout=1.0)

        await route_task

        assert event["email_id"] == "concurrent-test-id"


# ============================================================================
# Concurrent Access Tests
# ============================================================================


class TestTaskRouterConcurrentAccess:
    """Test concurrent access safety."""

    @pytest.mark.asyncio
    async def test_concurrent_registrations(self, task_router: TaskRouter) -> None:
        """Test that concurrent registrations are handled safely."""

        async def register_task(task_num: int):
            await task_router.register(
                f"task-{task_num:03d}", f"poc{task_num}@example.com"
            )

        # Register 10 tasks concurrently
        await asyncio.gather(*[register_task(i) for i in range(10)])

        assert task_router.registration_count == 10

    @pytest.mark.asyncio
    async def test_concurrent_routing_to_different_tasks(
        self, task_router: TaskRouter
    ) -> None:
        """Test concurrent routing to different tasks."""
        # Register multiple tasks
        await task_router.register("task-001", "poc1@example.com")
        await task_router.register("task-002", "poc2@example.com")
        await task_router.register("task-003", "poc3@example.com")

        # Create payloads for each task
        payloads = [
            {"event": "email.received", "email_id": f"email-{i}", "from": f"poc{i}@example.com"}
            for i in range(1, 4)
        ]

        # Route all concurrently
        results = await asyncio.gather(*[task_router.route_event(p) for p in payloads])

        assert all(results)

        # Verify each task received its event
        for i in range(1, 4):
            event = await task_router.wait_for_event(f"task-00{i}", timeout=1.0)
            assert event["email_id"] == f"email-{i}"


# ============================================================================
# Helper Method Tests
# ============================================================================


class TestTaskRouterHelperMethods:
    """Test helper methods."""

    @pytest.mark.asyncio
    async def test_get_registered_pocs(self, task_router: TaskRouter) -> None:
        """Test getting list of registered POCs."""
        await task_router.register("task-001", "poc1@example.com")
        await task_router.register("task-002", "poc2@example.com")

        pocs = task_router.get_registered_pocs()

        assert len(pocs) == 2
        assert "poc1@example.com" in pocs
        assert "poc2@example.com" in pocs

    @pytest.mark.asyncio
    async def test_get_task_for_poc_not_found(self, task_router: TaskRouter) -> None:
        """Test get_task_for_poc returns None for unknown POC."""
        result = task_router.get_task_for_poc("unknown@example.com")
        assert result is None

    def test_registration_count_empty(self, task_router: TaskRouter) -> None:
        """Test registration_count is 0 for new router."""
        assert task_router.registration_count == 0

    def test_is_registered_unregistered_task(self, task_router: TaskRouter) -> None:
        """Test is_registered returns False for unregistered task."""
        assert not task_router.is_registered("nonexistent-task")


# ============================================================================
# Edge Case Tests
# ============================================================================


class TestTaskRouterEdgeCases:
    """Test edge cases."""

    @pytest.mark.asyncio
    async def test_reregister_after_unregister(self, task_router: TaskRouter) -> None:
        """Test re-registering a POC after unregistering."""
        await task_router.register("task-001", "poc@example.com")
        await task_router.unregister("task-001", "poc@example.com")

        # Should be able to register again
        await task_router.register("task-002", "poc@example.com")

        assert task_router.get_task_for_poc("poc@example.com") == "task-002"

    @pytest.mark.asyncio
    async def test_multiple_events_queued(self, task_router: TaskRouter) -> None:
        """Test multiple events can be queued for a task."""
        await task_router.register("task-001", "poc@example.com")

        # Route multiple events
        for i in range(3):
            payload = {
                "event": "email.received",
                "email_id": f"email-{i}",
                "from": "poc@example.com",
            }
            await task_router.route_event(payload)

        # Receive all events in order
        for i in range(3):
            event = await task_router.wait_for_event("task-001", timeout=1.0)
            assert event["email_id"] == f"email-{i}"

    @pytest.mark.asyncio
    async def test_route_event_after_unregister_returns_false(
        self, task_router: TaskRouter
    ) -> None:
        """Test routing returns False after task unregistration."""
        await task_router.register("task-001", "poc@example.com")
        await task_router.unregister("task-001", "poc@example.com")

        payload = {
            "event": "email.received",
            "email_id": "test-123",
            "from": "poc@example.com",
        }
        result = await task_router.route_event(payload)

        assert result is False
