"""UI route handlers."""

from ui.routes.pages import router as pages_router
from ui.routes.send_request import router as send_request_router
from ui.routes.inbox import router as inbox_router
from ui.routes.dashboard import router as dashboard_router

__all__ = [
    "pages_router",
    "send_request_router",
    "inbox_router",
    "dashboard_router",
]
