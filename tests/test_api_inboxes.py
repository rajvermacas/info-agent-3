"""Tests for inbox API endpoints."""

import pytest
from fastapi import status

from mock_smtp.store.models import Email


class TestInboxAPI:
    """Tests for inbox API endpoints."""

    def test_list_inboxes_empty(self, api_client):
        """Test listing inboxes when none exist."""
        response = api_client.get("/api/inboxes")

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    def test_list_inboxes_with_data(self, api_client):
        """Test listing inboxes with data."""
        # Get the inbox_store from the app state
        inbox_store = api_client.app.state.inbox_store

        # Add emails to create inboxes
        for i in range(3):
            email = Email(
                from_address="sender@example.com",
                to_addresses=[f"user{i}@example.com"]
            )
            inbox_store.add_email(email)

        response = api_client.get("/api/inboxes")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 3

        # Check structure
        assert "email_address" in data[0]
        assert "email_count" in data[0]
        assert "created_at" in data[0]

    def test_get_inbox_emails(self, api_client):
        """Test getting emails for a specific inbox."""
        # Get the inbox_store from the app state
        inbox_store = api_client.app.state.inbox_store

        email = Email(
            from_address="sender@example.com",
            to_addresses=["test@example.com"],
            subject="Test Email"
        )
        inbox_store.add_email(email)

        response = api_client.get("/api/inboxes/test@example.com")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert data[0]["subject"] == "Test Email"

    def test_get_inbox_not_found(self, api_client):
        """Test getting emails for non-existent inbox."""
        response = api_client.get("/api/inboxes/nonexistent@example.com")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_clear_inbox(self, api_client):
        """Test clearing an inbox."""
        # Get the inbox_store from the app state
        inbox_store = api_client.app.state.inbox_store

        # Add emails
        for i in range(5):
            email = Email(
                from_address="sender@example.com",
                to_addresses=["test@example.com"],
                subject=f"Email {i}"
            )
            inbox_store.add_email(email)

        assert inbox_store.total_emails == 5

        response = api_client.delete("/api/inboxes/test@example.com")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["deleted_count"] == 5
        assert inbox_store.total_emails == 0

    def test_clear_inbox_not_found(self, api_client):
        """Test clearing non-existent inbox."""
        response = api_client.delete("/api/inboxes/nonexistent@example.com")

        assert response.status_code == status.HTTP_404_NOT_FOUND
