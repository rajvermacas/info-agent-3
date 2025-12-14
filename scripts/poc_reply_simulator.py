"""POC Reply Simulator - sends test email with attachment via SMTP."""

import asyncio
import base64
import csv
import io
import logging
import sys
from pathlib import Path
from typing import Optional

import aiosmtplib
import typer
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

logger = logging.getLogger(__name__)

app = typer.Typer(
    help="POC Reply Simulator - sends test email with CSV/Excel attachment via SMTP"
)


def create_csv_attachment(rows: int = 5) -> bytes:
    """Create test CSV file in memory.

    Args:
        rows: Number of data rows to generate

    Returns:
        bytes: CSV file content
    """
    logger.debug(f"Generating test CSV with {rows} rows")

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["ID", "Name", "Email", "Phone"])

    # Write header
    writer.writeheader()

    # Write data rows
    for i in range(1, rows + 1):
        writer.writerow({
            "ID": i,
            "Name": f"Contact {i}",
            "Email": f"contact{i}@example.com",
            "Phone": f"+1-555-{i:04d}",
        })

    logger.debug("CSV file generated successfully")

    return output.getvalue().encode("utf-8")


async def send_reply_email(
    to_address: str,
    from_address: str = "poc@company.com",
    subject_prefix: str = "Re:",
    body_text: str = "Here is the requested data:",
    smtp_host: str = "localhost",
    smtp_port: int = 1025,
    attachment_filename: Optional[str] = None,
    attachment_rows: int = 5,
) -> None:
    """Send reply email with optional attachment via SMTP.

    Args:
        to_address: Recipient email (agent's inbox)
        from_address: Sender email (POC email)
        subject_prefix: Subject prefix (usually "Re:")
        body_text: Email body text
        smtp_host: SMTP server hostname
        smtp_port: SMTP server port
        attachment_filename: Filename for attachment (e.g., "data.csv")
        attachment_rows: Number of rows in CSV attachment

    Raises:
        aiosmtplib.SMTPException: If SMTP send fails
        ValueError: If required parameters missing
    """
    logger.info(
        f"Sending reply email: from={from_address}, to={to_address}, "
        f"attachment={attachment_filename}"
    )

    if not to_address or not to_address.strip():
        raise ValueError("to_address is required")

    if not from_address or not from_address.strip():
        raise ValueError("from_address is required")

    try:
        # Create MIME message
        message = MIMEMultipart()
        message["From"] = from_address
        message["To"] = to_address
        message["Subject"] = f"{subject_prefix} Data Request"

        # Add body
        message.attach(MIMEText(body_text, "plain"))

        # Add attachment if requested
        if attachment_filename:
            logger.debug(f"Adding attachment: {attachment_filename}")

            # Generate CSV data
            csv_data = create_csv_attachment(attachment_rows)

            # Create attachment
            part = MIMEBase("application", "octet-stream")
            part.set_payload(csv_data)
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f"attachment; filename= {attachment_filename}")

            message.attach(part)

            logger.debug(f"Attachment added: {len(csv_data)} bytes")

        # Send via SMTP
        logger.debug(f"Connecting to SMTP: {smtp_host}:{smtp_port}")

        async with aiosmtplib.SMTP(hostname=smtp_host, port=smtp_port) as smtp:
            await smtp.send_message(message)

            logger.info(f"Email sent successfully via SMTP")

    except aiosmtplib.SMTPException as e:
        error_msg = f"SMTP error: {str(e)}"
        logger.error(f"send_reply_email: {error_msg}")
        raise

    except Exception as e:
        error_msg = f"Unexpected error sending email: {str(e)}"
        logger.error(f"send_reply_email: {error_msg}")
        raise


@app.command()
async def send(
    to_address: str = typer.Argument(
        ...,
        help="Recipient email address (agent's inbox, e.g., info-agent@gmail.com)"
    ),
    from_address: str = typer.Option(
        "poc@company.com",
        "--from",
        help="Sender email address (POC email)"
    ),
    subject: str = typer.Option(
        "Re: Data Request",
        "--subject",
        help="Email subject line"
    ),
    body: str = typer.Option(
        "Here is the requested data:",
        "--body",
        help="Email body text"
    ),
    attachment: Optional[str] = typer.Option(
        "data.csv",
        "--attachment",
        help="Attachment filename (e.g., data.csv, data.xlsx)"
    ),
    rows: int = typer.Option(
        5,
        "--rows",
        help="Number of rows in CSV attachment"
    ),
    smtp_host: str = typer.Option(
        "localhost",
        "--smtp-host",
        help="Mock SMTP server hostname"
    ),
    smtp_port: int = typer.Option(
        1025,
        "--smtp-port",
        help="Mock SMTP server port"
    ),
    log_level: Optional[str] = typer.Option(
        "INFO",
        "--log-level",
        help="Logging level (DEBUG, INFO, WARNING, ERROR)"
    ),
) -> None:
    """Send test email reply with CSV attachment.

    This simulator sends an email to the agent's inbox (as if a POC is replying)
    with an attached CSV file containing test data.

    Examples:
        # Send simple reply with 5-row CSV
        poc-simulator send info-agent@gmail.com

        # Send reply with 10-row CSV from different POC
        poc-simulator send info-agent@gmail.com \\
          --from alice@company.com \\
          --rows 10

        # Send reply with custom subject and body
        poc-simulator send info-agent@gmail.com \\
          --subject "Re: Q4 Sales Data" \\
          --body "Here are the Q4 sales figures as requested"
    """
    try:
        # Configure logging
        logging.basicConfig(
            level=getattr(logging, log_level.upper()),
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )

        logger.info("POC Reply Simulator started")
        logger.debug(
            f"Parameters: to={to_address}, from={from_address}, "
            f"attachment={attachment}, rows={rows}"
        )

        # Validate inputs
        if not to_address or not to_address.strip():
            typer.echo("Error: to_address is required", err=True)
            sys.exit(1)

        if not from_address or not from_address.strip():
            typer.echo("Error: from_address is required", err=True)
            sys.exit(1)

        if rows < 1:
            typer.echo("Error: rows must be at least 1", err=True)
            sys.exit(1)

        if rows > 10000:
            typer.echo("Error: rows must not exceed 10000", err=True)
            sys.exit(1)

        # Display parameters
        typer.echo(f"Sending email via SMTP {smtp_host}:{smtp_port}")
        typer.echo(f"  From: {from_address}")
        typer.echo(f"  To: {to_address}")
        typer.echo(f"  Subject: {subject}")
        typer.echo(f"  Body: {body}")

        if attachment:
            typer.echo(f"  Attachment: {attachment} ({rows} rows)")
        else:
            typer.echo("  Attachment: None")

        typer.echo()

        # Send email
        await send_reply_email(
            to_address=to_address,
            from_address=from_address,
            subject_prefix=subject.split(":")[0] if ":" in subject else subject,
            body_text=body,
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            attachment_filename=attachment,
            attachment_rows=rows,
        )

        typer.echo("Email sent successfully!")
        logger.info("POC Reply Simulator completed successfully")

    except ValueError as e:
        typer.echo(f"Error: {str(e)}", err=True)
        logger.error(f"Validation error: {str(e)}")
        sys.exit(1)

    except aiosmtplib.SMTPException as e:
        typer.echo(f"SMTP Error: {str(e)}", err=True)
        logger.error(f"SMTP error: {str(e)}")
        sys.exit(1)

    except Exception as e:
        typer.echo(f"Error: {str(e)}", err=True)
        logger.error(f"Unexpected error: {str(e)}")
        sys.exit(1)


@app.command()
async def batch(
    to_address: str = typer.Argument(
        ...,
        help="Recipient email address (agent's inbox)"
    ),
    count: int = typer.Option(
        3,
        "--count",
        help="Number of emails to send"
    ),
    delay: float = typer.Option(
        2.0,
        "--delay",
        help="Delay between emails in seconds"
    ),
    smtp_host: str = typer.Option(
        "localhost",
        "--smtp-host",
        help="Mock SMTP server hostname"
    ),
    smtp_port: int = typer.Option(
        1025,
        "--smtp-port",
        help="Mock SMTP server port"
    ),
) -> None:
    """Send multiple test emails in sequence.

    Useful for testing agent behavior with multiple POC responses.

    Examples:
        # Send 3 emails with 2-second delay
        poc-simulator batch info-agent@gmail.com --count 3 --delay 2

        # Send 5 emails rapidly
        poc-simulator batch info-agent@gmail.com --count 5 --delay 0.5
    """
    try:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s"
        )

        logger.info(f"POC Reply Simulator batch mode: count={count}, delay={delay}s")

        poc_addresses = [
            f"poc{i}@company.com" for i in range(1, count + 1)
        ]

        typer.echo(f"Sending {count} emails to {to_address}\n")

        for i, from_addr in enumerate(poc_addresses, 1):
            typer.echo(f"[{i}/{count}] Sending from {from_addr}...")

            try:
                await send_reply_email(
                    to_address=to_address,
                    from_address=from_addr,
                    body_text=f"Here is the requested data from POC {i}",
                    smtp_host=smtp_host,
                    smtp_port=smtp_port,
                    attachment_filename=f"data_poc{i}.csv",
                    attachment_rows=5 + i,  # Varying number of rows
                )

                if i < count:
                    await asyncio.sleep(delay)

            except Exception as e:
                typer.echo(f"  Error: {str(e)}", err=True)
                logger.error(f"Error sending email {i}: {str(e)}")

        typer.echo(f"\nBatch complete: {count} emails sent")
        logger.info("Batch mode completed successfully")

    except Exception as e:
        typer.echo(f"Error: {str(e)}", err=True)
        logger.error(f"Batch error: {str(e)}")
        sys.exit(1)


def main() -> None:
    """Main entry point."""
    app()


if __name__ == "__main__":
    main()
