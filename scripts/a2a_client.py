#!/usr/bin/env python3
"""
A2A Client for Mail Agent.

A command-line client to interact with the Mail Agent A2A server.
Supports sending email tasks and multi-turn conversations.

Usage:
    python scripts/a2a_client.py info                     # Show agent info
    python scripts/a2a_client.py send --message "..."     # Send a task
    python scripts/a2a_client.py interactive              # Interactive mode
"""

import asyncio
import json
import logging
import sys
from typing import Any
from uuid import uuid4

import click
import httpx

from a2a.client import A2ACardResolver, Client, ClientConfig, ClientFactory
from a2a.types import (
    AgentCard,
    Message,
    Part,
    Role,
    Task,
    TaskArtifactUpdateEvent,
    TaskStatusUpdateEvent,
    TextPart,
)


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class A2AClientError(Exception):
    """Exception raised for A2A client errors."""

    pass


class A2AMailClient:
    """
    Client for interacting with Mail Agent A2A server.

    Provides methods to connect, send email tasks, and handle
    multi-turn conversations with the mail agent.
    """

    def __init__(self, server_url: str):
        """
        Initialize the A2A Mail Client.

        Args:
            server_url: Base URL of the A2A server (e.g., http://localhost:8000)
        """
        if not server_url:
            raise A2AClientError("server_url is required")

        self.server_url = server_url.rstrip("/")
        self.httpx_client: httpx.AsyncClient | None = None
        self.client: Client | None = None
        self.agent_card: AgentCard | None = None
        self._connected = False

        logger.info(f"A2AMailClient initialized with server_url={self.server_url}")

    async def connect(self) -> AgentCard:
        """
        Connect to the A2A server and resolve the agent card.

        Returns:
            AgentCard with agent metadata and capabilities.

        Raises:
            A2AClientError: If connection or agent card resolution fails.
        """
        logger.info(f"Connecting to A2A server at {self.server_url}")

        try:
            self.httpx_client = httpx.AsyncClient(timeout=30.0)

            resolver = A2ACardResolver(
                httpx_client=self.httpx_client,
                base_url=self.server_url,
            )

            logger.debug("Fetching agent card from /.well-known/agent.json")
            self.agent_card = await resolver.get_agent_card()

            logger.info(
                f"Agent card resolved: name={self.agent_card.name}, "
                f"version={self.agent_card.version}"
            )

            # Use ClientFactory.connect() for modern client creation
            # Use a longer timeout (300s) for agent operations which can take significant time
            client_config = ClientConfig(
                httpx_client=httpx.AsyncClient(timeout=300.0),
            )
            self.client = await ClientFactory.connect(
                agent=self.agent_card,
                client_config=client_config,
            )

            self._connected = True
            logger.info("Successfully connected to A2A server")

            return self.agent_card

        except httpx.ConnectError as e:
            error_msg = f"Failed to connect to A2A server at {self.server_url}: {e}"
            logger.error(error_msg)
            raise A2AClientError(error_msg) from e

        except Exception as e:
            error_msg = f"Failed to resolve agent card: {e}"
            logger.error(error_msg)
            raise A2AClientError(error_msg) from e

    def _ensure_connected(self) -> None:
        """Ensure the client is connected before making requests."""
        if not self._connected or self.client is None:
            raise A2AClientError(
                "Client not connected. Call connect() first."
            )

    async def send_message(
        self,
        message_text: str,
        task_id: str | None = None,
        context_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Send a message to the mail agent.

        Args:
            message_text: The message text to send.
            task_id: Optional task ID for multi-turn conversations.
            context_id: Optional context ID for multi-turn conversations.

        Returns:
            Response from the agent as a dictionary.

        Raises:
            A2AClientError: If the request fails.
        """
        self._ensure_connected()

        logger.info(f"Sending message: {message_text[:100]}...")
        logger.debug(f"task_id={task_id}, context_id={context_id}")

        # Create Message object for the new client API
        msg = Message(
            messageId=uuid4().hex,
            role=Role.user,
            parts=[Part(root=TextPart(text=message_text))],
            taskId=task_id,
            contextId=context_id,
        )

        try:
            # The new client returns an async iterator
            # Collect all responses and return the final result
            result: dict[str, Any] = {}

            async for response in self.client.send_message(msg):
                if isinstance(response, Message):
                    # Direct message response
                    result = {"message": response.model_dump(mode="json", exclude_none=True)}
                elif isinstance(response, tuple):
                    # (Task, Event) tuple
                    task, event = response
                    result = {
                        "task": task.model_dump(mode="json", exclude_none=True) if task else None,
                        "event": event.model_dump(mode="json", exclude_none=True) if event else None,
                    }

            logger.info("Message sent successfully")
            logger.debug(f"Response: {json.dumps(result, indent=2)}")

            return result

        except Exception as e:
            error_msg = f"Failed to send message: {e}"
            logger.error(error_msg)
            raise A2AClientError(error_msg) from e

    async def send_message_streaming(
        self,
        message_text: str,
        task_id: str | None = None,
        context_id: str | None = None,
    ):
        """
        Send a message and stream the response.

        The new client API always returns an async iterator, so this method
        is essentially the same as send_message but yields each chunk.

        Args:
            message_text: The message text to send.
            task_id: Optional task ID for multi-turn conversations.
            context_id: Optional context ID for multi-turn conversations.

        Yields:
            Response chunks from the agent.

        Raises:
            A2AClientError: If the request fails.
        """
        self._ensure_connected()

        logger.info(f"Sending streaming message: {message_text[:100]}...")

        msg = Message(
            messageId=uuid4().hex,
            role=Role.user,
            parts=[Part(root=TextPart(text=message_text))],
            taskId=task_id,
            contextId=context_id,
        )

        try:
            async for response in self.client.send_message(msg):
                if isinstance(response, Message):
                    yield {"message": response.model_dump(mode="json", exclude_none=True)}
                elif isinstance(response, tuple):
                    task, event = response
                    yield {
                        "task": task.model_dump(mode="json", exclude_none=True) if task else None,
                        "event": event.model_dump(mode="json", exclude_none=True) if event else None,
                    }

        except Exception as e:
            error_msg = f"Failed to send streaming message: {e}"
            logger.error(error_msg)
            raise A2AClientError(error_msg) from e

    async def send_email_task(
        self,
        to_email: str,
        subject: str,
        body: str,
        success_criteria: str | None = None,
    ) -> dict[str, Any]:
        """
        Send an email task to the mail agent.

        Constructs a natural language message for the mail agent
        specifying the email to send.

        Args:
            to_email: Recipient email address.
            subject: Email subject.
            body: Email body/request content.
            success_criteria: Optional criteria for successful response.

        Returns:
            Response from the agent as a dictionary.
        """
        # Construct natural language message for the mail agent
        message_parts = [
            f"Send an email to {to_email}.",
            f"Subject: {subject}",
            f"Message: {body}",
        ]

        if success_criteria:
            message_parts.append(f"Success criteria: {success_criteria}")

        message = "\n".join(message_parts)

        logger.info(f"Sending email task to {to_email}")
        return await self.send_message(message)

    async def close(self) -> None:
        """Close the client and release resources."""
        logger.info("Closing A2A client")

        if self.httpx_client:
            await self.httpx_client.aclose()
            self.httpx_client = None

        self.client = None
        self.agent_card = None
        self._connected = False

        logger.info("A2A client closed")

    async def __aenter__(self) -> "A2AMailClient":
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.close()


def print_json(data: dict[str, Any]) -> None:
    """Print formatted JSON to stdout."""
    print(json.dumps(data, indent=2))


def extract_task_info(response: dict[str, Any]) -> tuple[str | None, str | None]:
    """
    Extract task_id and context_id from response for multi-turn conversations.

    Args:
        response: Response dictionary from send_message.

    Returns:
        Tuple of (task_id, context_id).
    """
    # Try new format (task in response)
    task = response.get("task", {})
    if task:
        return task.get("id"), task.get("contextId")

    # Try message format
    message = response.get("message", {})
    if message:
        return message.get("taskId"), message.get("contextId")

    return None, None


def extract_task_status(response: dict[str, Any]) -> str | None:
    """
    Extract task status from response.

    Args:
        response: Response dictionary from send_message.

    Returns:
        Task status string or None.
    """
    task = response.get("task", {})
    if task:
        status = task.get("status", {})
        return status.get("state")

    return None


def extract_agent_message(response: dict[str, Any]) -> str | None:
    """
    Extract the agent's text message from response.

    Args:
        response: Response dictionary from send_message.

    Returns:
        Agent's message text or None.
    """
    # Try task status message
    task = response.get("task", {})
    if task:
        status = task.get("status", {})
        message = status.get("message", {})
        parts = message.get("parts", [])
        for part in parts:
            if part.get("kind") == "text":
                return part.get("text")

    # Try direct message response
    message = response.get("message", {})
    if message:
        parts = message.get("parts", [])
        for part in parts:
            if part.get("kind") == "text":
                return part.get("text")

    return None


# =============================================================================
# CLI Commands
# =============================================================================


@click.group()
@click.option(
    "--server-url",
    default="http://localhost:8000",
    envvar="A2A_SERVER_URL",
    help="A2A server URL",
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    help="Enable verbose logging",
)
@click.pass_context
def cli(ctx: click.Context, server_url: str, verbose: bool) -> None:
    """A2A Client for Mail Agent."""
    ctx.ensure_object(dict)
    ctx.obj["server_url"] = server_url

    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.setLevel(logging.DEBUG)


@cli.command()
@click.pass_context
def info(ctx: click.Context) -> None:
    """Show agent card information."""

    async def _info():
        server_url = ctx.obj["server_url"]
        client = A2AMailClient(server_url)

        try:
            agent_card = await client.connect()

            click.echo("\n" + "=" * 60)
            click.echo("AGENT CARD INFORMATION")
            click.echo("=" * 60)
            click.echo(f"Name: {agent_card.name}")
            click.echo(f"Version: {agent_card.version}")
            click.echo(f"Description: {agent_card.description}")
            click.echo(f"URL: {agent_card.url}")

            click.echo("\nCapabilities:")
            if agent_card.capabilities:
                click.echo(f"  - Streaming: {agent_card.capabilities.streaming}")
                click.echo(
                    f"  - Push Notifications: {agent_card.capabilities.push_notifications}"
                )

            click.echo("\nSupported Input Modes:")
            for mode in agent_card.default_input_modes:
                click.echo(f"  - {mode}")

            click.echo("\nSupported Output Modes:")
            for mode in agent_card.default_output_modes:
                click.echo(f"  - {mode}")

            click.echo("\nSkills:")
            for skill in agent_card.skills:
                click.echo(f"  - {skill.name} ({skill.id})")
                click.echo(f"    Description: {skill.description}")
                if skill.tags:
                    click.echo(f"    Tags: {', '.join(skill.tags)}")
                if skill.examples:
                    click.echo("    Examples:")
                    for example in skill.examples:
                        click.echo(f"      - {example}")

            click.echo("=" * 60 + "\n")

        except A2AClientError as e:
            click.echo(f"Error: {e}", err=True)
            sys.exit(1)

        finally:
            await client.close()

    asyncio.run(_info())


@cli.command()
@click.option("--message", "-m", required=True, help="Message to send to the agent")
@click.option("--json-output", "-j", is_flag=True, help="Output raw JSON response")
@click.pass_context
def send(ctx: click.Context, message: str, json_output: bool) -> None:
    """Send a message to the mail agent."""

    async def _send():
        server_url = ctx.obj["server_url"]

        async with A2AMailClient(server_url) as client:
            try:
                response = await client.send_message(message)

                if json_output:
                    print_json(response)
                else:
                    task_id, context_id = extract_task_info(response)
                    status = extract_task_status(response)
                    agent_message = extract_agent_message(response)

                    click.echo("\n" + "-" * 60)
                    click.echo("RESPONSE")
                    click.echo("-" * 60)

                    if task_id:
                        click.echo(f"Task ID: {task_id}")
                    if context_id:
                        click.echo(f"Context ID: {context_id}")
                    if status:
                        click.echo(f"Status: {status}")

                    if agent_message:
                        click.echo(f"\nAgent Message:\n{agent_message}")

                    click.echo("-" * 60 + "\n")

            except A2AClientError as e:
                click.echo(f"Error: {e}", err=True)
                sys.exit(1)

    asyncio.run(_send())


@cli.command()
@click.option(
    "--to", "to_email",
    required=True,
    help="Recipient email address",
)
@click.option(
    "--subject", "-s",
    required=True,
    help="Email subject",
)
@click.option(
    "--body", "-b",
    required=True,
    help="Email body/request",
)
@click.option(
    "--success-criteria", "-c",
    default=None,
    help="Success criteria for the response",
)
@click.option("--json-output", "-j", is_flag=True, help="Output raw JSON response")
@click.pass_context
def email(
    ctx: click.Context,
    to_email: str,
    subject: str,
    body: str,
    success_criteria: str | None,
    json_output: bool,
) -> None:
    """Send an email task to the mail agent."""

    async def _email():
        server_url = ctx.obj["server_url"]

        async with A2AMailClient(server_url) as client:
            try:
                response = await client.send_email_task(
                    to_email=to_email,
                    subject=subject,
                    body=body,
                    success_criteria=success_criteria,
                )

                if json_output:
                    print_json(response)
                else:
                    task_id, context_id = extract_task_info(response)
                    status = extract_task_status(response)
                    agent_message = extract_agent_message(response)

                    click.echo("\n" + "-" * 60)
                    click.echo(f"EMAIL TASK SENT TO: {to_email}")
                    click.echo("-" * 60)

                    if task_id:
                        click.echo(f"Task ID: {task_id}")
                    if context_id:
                        click.echo(f"Context ID: {context_id}")
                    if status:
                        click.echo(f"Status: {status}")

                    if agent_message:
                        click.echo(f"\nAgent Message:\n{agent_message}")

                    click.echo("-" * 60 + "\n")

            except A2AClientError as e:
                click.echo(f"Error: {e}", err=True)
                sys.exit(1)

    asyncio.run(_email())


@cli.command()
@click.pass_context
def interactive(ctx: click.Context) -> None:
    """Start an interactive session with the mail agent."""

    async def _interactive():
        server_url = ctx.obj["server_url"]
        task_id: str | None = None
        context_id: str | None = None

        click.echo("\n" + "=" * 60)
        click.echo("INTERACTIVE MODE - Mail Agent A2A Client")
        click.echo("=" * 60)
        click.echo("Commands:")
        click.echo("  /quit, /exit  - Exit interactive mode")
        click.echo("  /new          - Start a new conversation")
        click.echo("  /status       - Show current task/context IDs")
        click.echo("  /info         - Show agent information")
        click.echo("=" * 60 + "\n")

        async with A2AMailClient(server_url) as client:
            click.echo(f"Connected to: {client.agent_card.name} v{client.agent_card.version}")
            click.echo()

            while True:
                try:
                    user_input = click.prompt("You", type=str)

                    # Handle commands
                    if user_input.lower() in ("/quit", "/exit"):
                        click.echo("Goodbye!")
                        break

                    if user_input.lower() == "/new":
                        task_id = None
                        context_id = None
                        click.echo("Started new conversation.\n")
                        continue

                    if user_input.lower() == "/status":
                        click.echo(f"Task ID: {task_id or 'None'}")
                        click.echo(f"Context ID: {context_id or 'None'}\n")
                        continue

                    if user_input.lower() == "/info":
                        click.echo(f"Agent: {client.agent_card.name}")
                        click.echo(f"Version: {client.agent_card.version}")
                        click.echo(f"Description: {client.agent_card.description}\n")
                        continue

                    # Send message
                    response = await client.send_message(
                        message_text=user_input,
                        task_id=task_id,
                        context_id=context_id,
                    )

                    # Update conversation context
                    new_task_id, new_context_id = extract_task_info(response)
                    if new_task_id:
                        task_id = new_task_id
                    if new_context_id:
                        context_id = new_context_id

                    # Display response
                    status = extract_task_status(response)
                    agent_message = extract_agent_message(response)

                    click.echo()
                    if status:
                        click.echo(f"[Status: {status}]")
                    if agent_message:
                        click.echo(f"Agent: {agent_message}")
                    else:
                        click.echo("Agent: (No text response)")
                    click.echo()

                except click.exceptions.Abort:
                    click.echo("\nGoodbye!")
                    break

                except A2AClientError as e:
                    click.echo(f"Error: {e}\n", err=True)

                except Exception as e:
                    click.echo(f"Unexpected error: {e}\n", err=True)
                    logger.exception("Unexpected error in interactive mode")

    asyncio.run(_interactive())


if __name__ == "__main__":
    cli()
