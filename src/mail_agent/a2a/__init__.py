"""
A2A Package - Google Agent-to-Agent protocol integration for Mail Agent.

This package provides the A2A protocol layer for exposing the Mail Agent
as a web service. External agents can interact with the Mail Agent via
standardized JSON-RPC 2.0 over HTTP.

Components:
- MailAgentA2AExecutor: Bridge between A2A protocol and LangGraph agent
- create_agent_card: Factory function for AgentCard metadata
- create_a2a_application: Factory function for Starlette application
- run_a2a_server: Main function to start the A2A server
"""

from mail_agent.a2a.agent_card import create_agent_card
from mail_agent.a2a.executor import MailAgentA2AExecutor
from mail_agent.a2a.progress_store import POCProgress, ProgressEvent, ProgressStore
from mail_agent.a2a.server import create_a2a_application, run_a2a_server

__all__ = [
    "MailAgentA2AExecutor",
    "POCProgress",
    "ProgressEvent",
    "ProgressStore",
    "create_agent_card",
    "create_a2a_application",
    "run_a2a_server",
]
