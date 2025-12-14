#!/usr/bin/env python3
"""
POC Reply Simulator - Send test replies with attachments via SMTP.

This script simulates a POC (Point of Contact) replying to the mail agent
by sending an email with an optional attachment via SMTP protocol.

Usage:
    python scripts/poc_reply_simulator.py \\
        --from "raj@gmail.com" \\
        --to "info-agent@gmail.com" \\
        --subject "Re: Request: 10 Food Recipes" \\
        --body "Please find the attached recipes." \\
        --attachment ./test_data/sample_recipes.xlsx
"""

import argparse
import asyncio
import logging
import mimetypes
import sys
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email import encoders
from pathlib import Path
from typing import Optional

import aiosmtplib


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# ============================================================================
# Constants
# ============================================================================

DEFAULT_SMTP_HOST = "localhost"
DEFAULT_SMTP_PORT = 1025

SUPPORTED_EXTENSIONS = {".xlsx", ".csv"}

CONTENT_TYPES = {
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".csv": "text/csv",
}


# ============================================================================
# Functions
# ============================================================================


def create_mime_message(
    from_address: str,
    to_address: str,
    subject: str,
    body: str,
    attachment_path: Optional[Path] = None,
) -> MIMEMultipart:
    """
    Create a MIME message with optional attachment.

    Args:
        from_address: Sender email address.
        to_address: Recipient email address.
        subject: Email subject.
        body: Email body text.
        attachment_path: Optional path to attachment file.

    Returns:
        MIMEMultipart message ready to send.

    Raises:
        ValueError: If attachment file doesn't exist or has unsupported format.
    """
    logger.info(f"Creating MIME message: from={from_address}, to={to_address}")

    # Create message
    message = MIMEMultipart("mixed")
    message["From"] = from_address
    message["To"] = to_address
    message["Subject"] = subject

    # Add body
    body_part = MIMEText(body, "plain", "utf-8")
    message.attach(body_part)
    logger.debug(f"Added body: {len(body)} chars")

    # Add attachment if provided
    if attachment_path:
        attachment_path = Path(attachment_path)

        # Validate file exists
        if not attachment_path.exists():
            raise ValueError(f"Attachment file not found: {attachment_path}")

        # Validate extension
        extension = attachment_path.suffix.lower()
        if extension not in SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"Unsupported attachment format: {extension}. "
                f"Supported: {SUPPORTED_EXTENSIONS}"
            )

        # Get content type
        content_type = CONTENT_TYPES.get(extension)
        if not content_type:
            content_type, _ = mimetypes.guess_type(str(attachment_path))
            if not content_type:
                content_type = "application/octet-stream"

        logger.info(f"Adding attachment: {attachment_path.name} ({content_type})")

        # Read file
        with open(attachment_path, "rb") as f:
            file_content = f.read()

        # Create attachment part
        maintype, subtype = content_type.split("/", 1)
        attachment_part = MIMEBase(maintype, subtype)
        attachment_part.set_payload(file_content)

        # Encode as base64
        encoders.encode_base64(attachment_part)

        # Set headers
        attachment_part.add_header(
            "Content-Disposition",
            "attachment",
            filename=attachment_path.name,
        )

        message.attach(attachment_part)
        logger.debug(f"Attached file: {len(file_content)} bytes")

    return message


async def send_email(
    message: MIMEMultipart,
    smtp_host: str = DEFAULT_SMTP_HOST,
    smtp_port: int = DEFAULT_SMTP_PORT,
) -> None:
    """
    Send email via SMTP.

    Args:
        message: MIME message to send.
        smtp_host: SMTP server hostname.
        smtp_port: SMTP server port.

    Raises:
        aiosmtplib.SMTPException: If sending fails.
    """
    logger.info(f"Connecting to SMTP server: {smtp_host}:{smtp_port}")

    try:
        await aiosmtplib.send(
            message,
            hostname=smtp_host,
            port=smtp_port,
            start_tls=False,
            use_tls=False,
        )
        logger.info("Email sent successfully!")

    except aiosmtplib.SMTPException as e:
        logger.error(f"SMTP error: {e}")
        raise


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Simulate POC reply by sending email via SMTP",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Send simple reply
    python scripts/poc_reply_simulator.py \\
        --from "raj@gmail.com" \\
        --to "info-agent@gmail.com" \\
        --subject "Re: Request: 10 Food Recipes" \\
        --body "Here are the recipes you requested."

    # Send reply with Excel attachment
    python scripts/poc_reply_simulator.py \\
        --from "raj@gmail.com" \\
        --to "info-agent@gmail.com" \\
        --subject "Re: Request: 10 Food Recipes" \\
        --body "Please find attached." \\
        --attachment ./test_data/sample_recipes.xlsx

    # Use custom SMTP server
    python scripts/poc_reply_simulator.py \\
        --from "raj@gmail.com" \\
        --to "info-agent@gmail.com" \\
        --subject "Test" \\
        --body "Test message" \\
        --smtp-host localhost \\
        --smtp-port 1025
        """,
    )

    parser.add_argument(
        "--from",
        dest="from_address",
        required=True,
        help="Sender email address (e.g., raj@gmail.com)",
    )
    parser.add_argument(
        "--to",
        dest="to_address",
        required=True,
        help="Recipient email address (e.g., info-agent@gmail.com)",
    )
    parser.add_argument(
        "--subject",
        required=True,
        help="Email subject line",
    )
    parser.add_argument(
        "--body",
        required=True,
        help="Email body text",
    )
    parser.add_argument(
        "--attachment",
        type=Path,
        help="Path to attachment file (.xlsx or .csv)",
    )
    parser.add_argument(
        "--smtp-host",
        default=DEFAULT_SMTP_HOST,
        help=f"SMTP server hostname (default: {DEFAULT_SMTP_HOST})",
    )
    parser.add_argument(
        "--smtp-port",
        type=int,
        default=DEFAULT_SMTP_PORT,
        help=f"SMTP server port (default: {DEFAULT_SMTP_PORT})",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    return parser.parse_args()


async def main() -> int:
    """Main function."""
    args = parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        # Create message
        message = create_mime_message(
            from_address=args.from_address,
            to_address=args.to_address,
            subject=args.subject,
            body=args.body,
            attachment_path=args.attachment,
        )

        # Send email
        await send_email(
            message=message,
            smtp_host=args.smtp_host,
            smtp_port=args.smtp_port,
        )

        print("\n" + "=" * 50)
        print("EMAIL SENT SUCCESSFULLY")
        print("=" * 50)
        print(f"From: {args.from_address}")
        print(f"To: {args.to_address}")
        print(f"Subject: {args.subject}")
        if args.attachment:
            print(f"Attachment: {args.attachment}")
        print("=" * 50 + "\n")

        return 0

    except ValueError as e:
        logger.error(f"Validation error: {e}")
        return 1

    except aiosmtplib.SMTPException as e:
        logger.error(f"SMTP error: {e}")
        print(
            f"\nMake sure the mock SMTP server is running on "
            f"{args.smtp_host}:{args.smtp_port}"
        )
        return 1

    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
