"""
Tools package - HTTP clients and utilities.
"""

from mail_agent.tools.smtp_client import SMTPClient
from mail_agent.tools.inbox_client import InboxClient
from mail_agent.tools.attachment_parser import AttachmentParser
from mail_agent.tools.smtp_sender import (
    SMTPSenderService,
    SMTPSendError,
    SMTPConnectionError,
)

__all__ = [
    "SMTPClient",
    "InboxClient",
    "AttachmentParser",
    "SMTPSenderService",
    "SMTPSendError",
    "SMTPConnectionError",
]
