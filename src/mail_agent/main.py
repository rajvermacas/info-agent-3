"""Mail Agent CLI - autonomous email agent for data collection."""

import asyncio
import logging
import sys
from typing import Optional

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from mail_agent.agent.graph import create_agent_graph, initialize_agent_state
from mail_agent.config import Settings, get_settings
from mail_agent.webhook.server import WebhookServer

logger = logging.getLogger(__name__)
console = Console()

app = typer.Typer(help="Mail Agent - Autonomous email agent for data collection")


async def run_webhook_server(
    webhook_server: WebhookServer,
    timeout_seconds: float = 300.0
) -> None:
    """Run webhook server in background for specified timeout.

    Args:
        webhook_server: WebhookServer instance
        timeout_seconds: Time to run server (allows graceful shutdown)
    """
    logger.info("Starting webhook server in background")

    try:
        # Start server with timeout
        await asyncio.wait_for(webhook_server.start(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        logger.info("Webhook server timeout reached, shutting down")
        await webhook_server.stop()
    except Exception as e:
        logger.error(f"Webhook server error: {str(e)}")
        raise


async def run_agent(
    user_instruction: str,
    webhook_server: WebhookServer,
) -> None:
    """Run agent graph to process instruction.

    Args:
        user_instruction: User's email request
        webhook_server: WebhookServer instance for receiving replies
    """
    logger.info("Running agent graph")

    try:
        # Create graph
        graph = create_agent_graph()

        # Initialize state
        state = initialize_agent_state(user_instruction)

        # Get settings for max attempts
        settings = get_settings()

        console.print("\n[bold cyan]Starting Mail Agent[/bold cyan]")
        console.print(f"Instruction: {user_instruction[:100]}...")
        console.print(f"Max attempts per POC: {settings.max_attempts}")
        console.print(f"Webhook URL: {settings.webhook_url}\n")

        # Run graph with progress tracking
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("[cyan]Processing...", total=None)

            # Run graph synchronously
            config = {"configurable": {"thread_id": "default"}}

            # Input for graph
            input_state = {
                "user_instruction": user_instruction,
                "parsed_request": None,
                "conversations": {},
                "current_node": "start",
                "pending_webhooks": [],
                "progress_messages": [],
                "final_summary": None,
                "started_at": state["started_at"],
                "completed_at": None,
            }

            # Execute graph
            output = await asyncio.to_thread(
                lambda: graph.invoke(input_state, config)
            )

            progress.stop()

            # Display results
            final_summary = output.get("final_summary", "No summary available")
            console.print("\n[bold green]Mail Agent Execution Complete[/bold green]\n")
            console.print(final_summary)

            # Display conversation details
            conversations = output.get("conversations", {})
            if conversations:
                console.print("\n[bold]Conversation Details:[/bold]")
                for poc_email, conv in conversations.items():
                    status = conv.get("final_result", conv.get("status", "unknown"))
                    attempts = conv.get("attempt_count", 0)
                    console.print(f"  {poc_email}: {status} ({attempts} attempts)")

    except Exception as e:
        error_msg = f"Agent error: {str(e)}"
        logger.error(error_msg)
        console.print(f"[bold red]Error:[/bold red] {error_msg}")
        raise


async def _send_async(
    instruction: str,
    skip_webhook: bool,
    webhook_timeout: int,
    settings: Settings,
    webhook_server: WebhookServer,
) -> None:
    """Async implementation of send command.

    Args:
        instruction: User's email request instruction
        skip_webhook: Whether to skip webhook server
        webhook_timeout: Webhook server timeout in seconds
        settings: Application settings
        webhook_server: WebhookServer instance
    """
    logger.info("Starting async send implementation")

    # Register webhook with Mock SMTP
    if not skip_webhook:
        console.print(f"[cyan]Registering webhook at {settings.webhook_url}...[/cyan]")

        try:
            from mail_agent.tools.smtp_client import SMTPClient
            import httpx

            async with httpx.AsyncClient(timeout=30.0) as http_client:
                smtp_client = SMTPClient(settings, http_client)
                async with smtp_client:
                    await smtp_client.register_webhook(
                        url=settings.webhook_url,
                        inbox_filter=settings.agent_email
                    )
            console.print("[green]Webhook registered successfully[/green]")

        except Exception as e:
            logger.warning(f"Failed to register webhook: {str(e)}")
            console.print(f"[yellow]Warning: Webhook registration failed: {str(e)}[/yellow]")

    # Run agent with webhook server
    webhook_task = None

    try:
        # Start webhook server in background
        if not skip_webhook:
            webhook_task = asyncio.create_task(
                run_webhook_server(webhook_server, webhook_timeout)
            )

        # Run agent (concurrent with webhook server if not skipped)
        agent_task = asyncio.create_task(
            run_agent(instruction, webhook_server)
        )

        # Wait for agent to complete
        await agent_task

        # Cancel webhook task if still running
        if webhook_task and not webhook_task.done():
            webhook_task.cancel()
            try:
                await webhook_task
            except asyncio.CancelledError:
                pass

        console.print("[green]Mail Agent finished successfully[/green]")

    except KeyboardInterrupt:
        logger.info("Mail Agent interrupted by user")
        console.print("\n[yellow]Interrupted by user[/yellow]")

        # Clean up webhook
        if webhook_task and not webhook_task.done():
            webhook_task.cancel()
            try:
                await webhook_task
            except asyncio.CancelledError:
                pass

        raise

    except Exception as e:
        logger.error(f"Mail Agent error: {str(e)}")
        console.print(f"[red]Error: {str(e)}[/red]")

        # Clean up webhook
        if webhook_task and not webhook_task.done():
            webhook_task.cancel()
            try:
                await webhook_task
            except asyncio.CancelledError:
                pass

        raise


@app.command()
def send(
    instruction: str = typer.Argument(
        ...,
        help="Email request instruction (e.g., 'Send email to alice@company.com requesting sales data')"
    ),
    skip_webhook: bool = typer.Option(
        False,
        "--skip-webhook",
        help="Skip webhook server (for testing without replies)"
    ),
    webhook_timeout: int = typer.Option(
        300,
        "--webhook-timeout",
        help="Webhook server timeout in seconds"
    ),
    log_level: Optional[str] = typer.Option(
        None,
        "--log-level",
        help="Logging level (DEBUG, INFO, WARNING, ERROR)"
    ),
) -> None:
    """Send email request via Mail Agent.

    Examples:
        # Request data from single POC
        mail-agent send "Send email to alice@company.com asking for Q4 sales data in Excel"

        # Request from multiple POCs
        mail-agent send "Send email to alice@company.com and bob@company.com requesting product list in CSV"
    """
    try:
        # Configure logging
        if log_level:
            logging.basicConfig(
                level=getattr(logging, log_level.upper()),
                format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            )
        else:
            settings = get_settings()
            settings.configure_logging()

        logger.info(f"Mail Agent started: instruction={instruction[:100]}")
        logger.debug(f"Options: skip_webhook={skip_webhook}, webhook_timeout={webhook_timeout}")

        # Get settings
        settings = get_settings()

        # Validate instruction
        if not instruction or not instruction.strip():
            console.print("[red]Error: Instruction cannot be empty[/red]")
            sys.exit(1)

        if len(instruction) < 10:
            console.print("[red]Error: Instruction too short (minimum 10 characters)[/red]")
            sys.exit(1)

        # Create webhook server
        webhook_server = WebhookServer(
            host=settings.webhook_host,
            port=settings.webhook_port,
            webhook_path=settings.webhook_path
        )

        # Run async operations
        asyncio.run(_send_async(
            instruction=instruction,
            skip_webhook=skip_webhook,
            webhook_timeout=webhook_timeout,
            settings=settings,
            webhook_server=webhook_server,
        ))

    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/yellow]")
        sys.exit(0)

    except ValueError as e:
        logger.error(f"Configuration error: {str(e)}")
        console.print(f"[red]Configuration Error:[/red] {str(e)}")
        sys.exit(1)

    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        console.print(f"[red]Unexpected Error:[/red] {str(e)}")
        sys.exit(1)


@app.command()
def health() -> None:
    """Check Mail Agent health and configuration."""
    try:
        settings = get_settings()

        console.print("[bold cyan]Mail Agent Health Check[/bold cyan]\n")

        # Configuration
        console.print("[bold]Configuration:[/bold]")
        console.print(f"  Mock SMTP API: {settings.mock_smtp_api_url}")
        console.print(f"  Webhook URL: {settings.webhook_url}")
        console.print(f"  Agent Email: {settings.agent_email}")
        console.print(f"  Max Attempts: {settings.max_attempts}")
        console.print(f"  LLM: {settings.gemini_model}")
        console.print(f"  Database: {settings.sqlite_db_path}\n")

        # API Health
        console.print("[bold]Testing Mock SMTP API...[/bold]")

        async def check_api_health():
            import httpx

            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    response = await client.get(f"{settings.mock_smtp_api_url}/api/health")
                    response.raise_for_status()
                    console.print("  [green]✓ Mock SMTP API is healthy[/green]")
                    return True
            except Exception as e:
                console.print(f"  [red]✗ Mock SMTP API error: {str(e)}[/red]")
                return False

        api_ok = asyncio.run(check_api_health())

        # LLM Health
        console.print("[bold]Testing Gemini LLM...[/bold]")

        try:
            from mail_agent.llm.client import GeminiClient

            llm = GeminiClient(settings)
            console.print("  [green]✓ Gemini LLM client initialized[/green]")
        except Exception as e:
            console.print(f"  [red]✗ Gemini LLM error: {str(e)}[/red]")

        console.print()

        if api_ok:
            console.print("[green]Health check passed - ready to run Mail Agent[/green]")
        else:
            console.print("[yellow]Some services unavailable - check configuration[/yellow]")

    except Exception as e:
        console.print(f"[red]Error:[/red] {str(e)}")
        sys.exit(1)


def main() -> None:
    """Main entry point."""
    app()


if __name__ == "__main__":
    main()
