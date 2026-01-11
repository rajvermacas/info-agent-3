"""
Agent package - LangGraph state machine and nodes.
"""

from mail_agent.agent.state import AgentState
from mail_agent.agent.graph import create_mail_agent_graph

__all__ = ["AgentState", "create_mail_agent_graph"]
