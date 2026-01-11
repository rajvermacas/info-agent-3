"""
Tests for UI page routes.

Note: Full integration tests with TestClient are disabled due to
environment isolation issues with pytest running in a separate venv.
These tests verify module imports and basic functionality.
"""

import pytest


class TestUIModuleImports:
    """Tests that UI modules can be imported correctly."""

    def test_routes_pages_imports(self) -> None:
        """Test that pages route module imports."""
        from ui.routes import pages
        assert hasattr(pages, 'router')
        assert hasattr(pages, 'home_page')
        assert hasattr(pages, 'send_request_page')
        assert hasattr(pages, 'inbox_page')
        assert hasattr(pages, 'dashboard_page')

    def test_routes_send_request_imports(self) -> None:
        """Test that send request route module imports."""
        from ui.routes import send_request
        assert hasattr(send_request, 'router')
        assert hasattr(send_request, 'submit_request')

    def test_routes_inbox_imports(self) -> None:
        """Test that inbox route module imports."""
        from ui.routes import inbox
        assert hasattr(inbox, 'router')
        assert hasattr(inbox, 'list_inboxes')
        assert hasattr(inbox, 'list_emails')
        assert hasattr(inbox, 'get_email_detail')
        assert hasattr(inbox, 'send_reply')

    def test_routes_dashboard_imports(self) -> None:
        """Test that dashboard route module imports."""
        from ui.routes import dashboard
        assert hasattr(dashboard, 'router')
        assert hasattr(dashboard, 'list_tasks')
        assert hasattr(dashboard, 'get_task_detail')

    def test_main_imports(self) -> None:
        """Test that main module imports."""
        from ui import main
        assert hasattr(main, 'create_app')
        assert hasattr(main, 'main')
        assert hasattr(main, 'UIServerResources')
        assert hasattr(main, 'get_resources')

    def test_config_imports(self) -> None:
        """Test that config module imports."""
        from ui import config
        assert hasattr(config, 'Settings')
        assert hasattr(config, 'get_settings')
        assert hasattr(config, 'configure_logging')


class TestUIRouterConfiguration:
    """Tests for route configuration."""

    def test_pages_router_has_routes(self) -> None:
        """Test that pages router has expected routes."""
        from ui.routes.pages import router

        route_paths = [r.path for r in router.routes]
        assert "/" in route_paths
        assert "/send" in route_paths
        assert "/inbox" in route_paths
        assert "/inbox/{email_address}" in route_paths
        assert "/dashboard" in route_paths

    def test_send_request_router_has_routes(self) -> None:
        """Test that send request router has expected routes."""
        from ui.routes.send_request import router

        route_paths = [r.path for r in router.routes]
        # Routes include prefix /send
        assert any("/submit" in p for p in route_paths)

    def test_inbox_router_has_routes(self) -> None:
        """Test that inbox router has expected routes."""
        from ui.routes.inbox import router

        route_paths = [r.path for r in router.routes]
        # Routes include prefix /inbox
        assert any("/list" in p for p in route_paths)
        assert any("/emails" in p for p in route_paths)
        assert any("/send-reply" in p for p in route_paths)

    def test_dashboard_router_has_routes(self) -> None:
        """Test that dashboard router has expected routes."""
        from ui.routes.dashboard import router

        route_paths = [r.path for r in router.routes]
        # Routes include prefix /dashboard
        assert any("/tasks" in p for p in route_paths)
        assert any("/task/" in p for p in route_paths)
