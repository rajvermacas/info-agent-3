"""LLM integration for Mail Agent using Gemini."""

from mail_agent.llm.client import GeminiClient
from mail_agent.llm.prompts import PromptTemplates

__all__ = ["GeminiClient", "PromptTemplates"]
