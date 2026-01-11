"""
Mail Agent CLI - Typer-based command line interface.

Provides the main entrypoint for running the mail agent.
"""

import asyncio
import logging
import signal
import sys
from typing import Optional

import typer

from mail_agent.config import LLMProvider, configure_logging, get_settings
from mail_agent.agent.state import create_initial_state
from mail_agent.agent.graph import compile_mail_agent_graph
from mail_agent.agent.nodes.wait_for_reply import set_webhook_server
from mail_agent.tools.smtp_client import SMTPClient
from mail_agent.webhook.server import WebhookServer


logger = logging.getLogger(__name__)

app = typer.Typer(
    name="mail-agent",
    help="Autonomous email agent that sends requests and validates responses.",
    add_completion=False,
)

# A2A subcommand app
a2a_app = typer.Typer(
    name="a2a",
    help="A2A protocol server commands.",
    add_completion=False,
)


# ============================================================================
# Helper Functions
# ============================================================================


async def run_agent(instruction: str, verbose: bool = False) -> dict:
    """
    Run the mail agent with the given instruction.

    Args:
        instruction: User instruction (e.g., "send mail to x@y.com asking...")
        verbose: Enable verbose output.

    Returns:
        Final agent state.
    """
    settings = get_settings()

    # Configure logging
    if verbose:
        settings.log_level = "DEBUG"
    configure_logging(settings)

    logger.info(f"Starting mail agent with instruction: {instruction}")
    print(f"\n{'='*60}")
    print("MAIL AGENT")
    print(f"{'='*60}\n")
    print(f"Instruction: {instruction}\n")

    # Initialize components
    webhook_server = WebhookServer(settings)
    smtp_client = SMTPClient(settings)

    # Set webhook server for wait_for_reply node
    set_webhook_server(webhook_server)

    try:
        # Start webhook server
        print("Starting webhook server...")
        await webhook_server.start()
        print(f"Webhook server listening on {settings.webhook_url}")

        # Check mock SMTP server health
        print("Checking mock SMTP server...")
        is_healthy = await smtp_client.health_check()
        if not is_healthy:
            print(
                f"WARNING: Mock SMTP server at {settings.mock_smtp_api_url} "
                "is not responding. Make sure it's running."
            )
            # Continue anyway - might start later

        # Register webhook with mock SMTP server
        print("Registering webhook with mock SMTP server...")
        try:
            webhook_response = await smtp_client.register_webhook()
            webhook_id = str(webhook_response.webhook_id)
            print(f"Webhook registered: {webhook_id}")
        except Exception as e:
            print(f"WARNING: Failed to register webhook: {e}")
            print("Continuing without webhook registration...")
            webhook_id = None

        # Create initial state
        initial_state = create_initial_state(instruction)
        if webhook_id:
            initial_state["webhook_id"] = webhook_id

        # Compile and run graph
        print("\nStarting agent workflow...\n")
        print("-" * 60)

        graph = compile_mail_agent_graph()

        # Run graph with streaming to show progress
        final_state = None
        async for event in graph.astream(initial_state):
            # Event is a dict with node name as key
            for node_name, node_output in event.items():
                logger.debug(f"Node {node_name} output: {node_output}")

                # Print progress messages
                progress_messages = node_output.get("progress_messages", [])
                for msg in progress_messages:
                    print(f"[{node_name}] {msg}")

                # Update final state
                if final_state is None:
                    final_state = dict(initial_state)
                final_state.update(node_output)

        print("-" * 60)
        print("\nAgent workflow completed.\n")

        # Print summary
        if final_state:
            print_summary(final_state)

        return final_state or {}

    except asyncio.CancelledError:
        print("\nAgent interrupted by user.")
        return {}

    finally:
        # Cleanup
        print("\nCleaning up...")

        # Unregister webhook
        if webhook_id:
            try:
                await smtp_client.unregister_webhook(
                    __import__("uuid").UUID(webhook_id)
                )
                print("Webhook unregistered.")
            except Exception as e:
                logger.warning(f"Failed to unregister webhook: {e}")

        # Stop webhook server
        await webhook_server.stop()
        print("Webhook server stopped.")

        # Close SMTP client
        await smtp_client.close()


def print_summary(state: dict) -> None:
    """Print a summary of the agent execution."""
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)

    # Check for errors
    error = state.get("error")
    if error:
        print(f"\nERROR: {error}")
        return

    # Print conversation results
    conversations = state.get("conversations", {})
    if not conversations:
        print("\nNo conversations recorded.")
        return

    for poc_email, conv in conversations.items():
        print(f"\nPOC: {poc_email}")
        print(f"  Status: {conv.get('status', 'unknown')}")
        print(f"  Attempts: {conv.get('attempt_count', 0)}")
        print(f"  Final Result: {conv.get('final_result', 'pending')}")

        # Print validation results
        validations = conv.get("validation_results", [])
        if validations:
            last_validation = validations[-1]
            print(f"  Last Validation: {'VALID' if last_validation.get('is_valid') else 'INVALID'}")
            print(f"  Feedback: {last_validation.get('feedback', '')[:100]}...")

    print()


# ============================================================================
# CLI Commands
# ============================================================================


@app.command()
def run(
    instruction: str = typer.Argument(
        ...,
        help="Instruction for the mail agent (e.g., 'send mail to x@y.com asking 10 recipes')",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose output",
    ),
) -> None:
    """
    Run the mail agent with the given instruction.

    Example:
        mail-agent run "send mail to raj@gmail.com asking 10 food recipes in excel file"
    """
    try:
        asyncio.run(run_agent(instruction, verbose))
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        sys.exit(1)


@app.command()
def health() -> None:
    """
    Check the health of the mock SMTP server.
    """
    async def check_health():
        settings = get_settings()
        smtp_client = SMTPClient(settings)
        try:
            is_healthy = await smtp_client.health_check()
            if is_healthy:
                print(f"Mock SMTP server at {settings.mock_smtp_api_url} is healthy.")
            else:
                print(f"Mock SMTP server at {settings.mock_smtp_api_url} is not responding.")
                sys.exit(1)
        finally:
            await smtp_client.close()

    asyncio.run(check_health())


@app.command()
def config() -> None:
    """
    Show current configuration.
    """
    settings = get_settings()
    print("Mail Agent Configuration")
    print("=" * 40)
    print(f"Mock SMTP API URL: {settings.mock_smtp_api_url}")
    print(f"Mock SMTP Host: {settings.mock_smtp_host}")
    print(f"Mock SMTP Port: {settings.mock_smtp_port}")
    print(f"Agent Email: {settings.agent_email}")
    print(f"Webhook URL: {settings.webhook_url}")
    print(f"Max Attempts: {settings.max_attempts}")
    print(f"Log Level: {settings.log_level}")
    print()
    print("LLM Configuration")
    print("-" * 40)
    print(f"Provider: {settings.llm_provider.value}")
    if settings.llm_provider == LLMProvider.GEMINI:
        print(f"Model: {settings.gemini_model}")
        print(f"API Key Set: {'Yes' if settings.gemini_api_key else 'No'}")
    elif settings.llm_provider == LLMProvider.AZURE_OPENAI:
        print(f"Deployment: {settings.azure_openai_deployment_name or 'Not set'}")
        print(f"Endpoint: {settings.azure_openai_endpoint or 'Not set'}")
        print(f"API Version: {settings.azure_openai_api_version}")
        print(f"API Key Set: {'Yes' if settings.azure_openai_api_key else 'No'}")
    print(f"Temperature: {settings.llm_temperature}")
    print(f"Max Tokens: {settings.llm_max_tokens}")
    print()
    print("A2A Server Configuration")
    print("-" * 40)
    print(f"A2A Host: {settings.a2a_host}")
    print(f"A2A Port: {settings.a2a_port}")
    print(f"Agent Name: {settings.a2a_agent_name}")
    print(f"Agent Version: {settings.a2a_agent_version}")


@app.command()
def a2a(
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose output",
    ),
) -> None:
    """
    Start the A2A protocol server.

    The A2A server exposes the Mail Agent via the Google Agent-to-Agent
    protocol, allowing external agents to interact with it via JSON-RPC 2.0
    over HTTP.

    Endpoints:
    - GET /.well-known/agent.json - Agent discovery card
    - POST /jsonrpc - JSON-RPC 2.0 endpoint for task execution

    Example:
        mail-agent a2a
        mail-agent a2a --verbose
    """
    from mail_agent.a2a.server import run_a2a_server

    try:
        asyncio.run(run_a2a_server(verbose=verbose))
    except KeyboardInterrupt:
        print("\nA2A server stopped by user.")
        sys.exit(0)


def main() -> None:
    """Main entrypoint for the CLI."""
    app()


if __name__ == "__main__":
    main()
