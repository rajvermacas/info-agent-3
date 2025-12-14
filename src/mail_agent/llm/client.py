"""Gemini LLM client for Mail Agent."""

import logging
from typing import Optional

from langchain_google_genai import ChatGoogleGenerativeAI

from mail_agent.config import Settings

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """Base exception for LLM errors."""
    pass


class LLMConnectionError(LLMError):
    """Exception raised when LLM API connection fails."""
    pass


class LLMResponseError(LLMError):
    """Exception raised when LLM response is invalid."""
    pass


class GeminiClient:
    """Client for Google Gemini LLM via LangChain.

    Wraps ChatGoogleGenerativeAI with error handling and logging.
    """

    def __init__(self, settings: Settings):
        """Initialize Gemini client.

        Args:
            settings: Mail agent settings with Gemini configuration

        Raises:
            ValueError: If settings are invalid or API key is missing
        """
        if not settings.gemini_api_key:
            raise ValueError(
                "GEMINI_API_KEY is required. "
                "Set MAIL_AGENT_GEMINI_API_KEY environment variable."
            )

        self.settings = settings

        # Initialize LangChain Gemini client
        self.llm = ChatGoogleGenerativeAI(
            model=settings.gemini_model,
            google_api_key=settings.gemini_api_key,
            temperature=settings.gemini_temperature,
            max_tokens=settings.gemini_max_tokens,
            timeout=settings.gemini_timeout,
        )

        logger.info(
            f"Gemini client initialized: model={settings.gemini_model}, "
            f"temp={settings.gemini_temperature}, max_tokens={settings.gemini_max_tokens}"
        )

    async def ainvoke(self, prompt: str, system_message: Optional[str] = None) -> str:
        """Invoke LLM asynchronously with prompt.

        Args:
            prompt: User prompt
            system_message: Optional system message (defaults to generic assistant)

        Returns:
            str: LLM response text

        Raises:
            LLMConnectionError: If API connection fails
            LLMResponseError: If response is invalid or empty
        """
        if not prompt or not prompt.strip():
            raise ValueError("prompt is required")

        # Build messages
        messages = []

        if system_message:
            messages.append({"role": "system", "content": system_message})

        messages.append({"role": "user", "content": prompt})

        logger.debug(f"Invoking Gemini with prompt (length={len(prompt)} chars)")

        try:
            response = await self.llm.ainvoke(messages)

            # Extract text content
            if hasattr(response, "content"):
                response_text = response.content
            else:
                response_text = str(response)

            if not response_text or not response_text.strip():
                raise LLMResponseError("LLM returned empty response")

            logger.debug(f"Gemini response received (length={len(response_text)} chars)")

            return response_text.strip()

        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e)

            logger.error(f"Gemini API error: {error_type}: {error_msg}")

            # Categorize error
            if "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
                raise LLMConnectionError(f"LLM API timeout: {error_msg}") from e
            elif "connection" in error_msg.lower() or "network" in error_msg.lower():
                raise LLMConnectionError(f"LLM API connection error: {error_msg}") from e
            elif "api key" in error_msg.lower() or "authentication" in error_msg.lower():
                raise LLMConnectionError(f"LLM API authentication error: {error_msg}") from e
            else:
                raise LLMResponseError(f"LLM API error: {error_msg}") from e

    def invoke(self, prompt: str, system_message: Optional[str] = None) -> str:
        """Invoke LLM synchronously with prompt.

        Args:
            prompt: User prompt
            system_message: Optional system message

        Returns:
            str: LLM response text

        Raises:
            LLMConnectionError: If API connection fails
            LLMResponseError: If response is invalid or empty
        """
        if not prompt or not prompt.strip():
            raise ValueError("prompt is required")

        # Build messages
        messages = []

        if system_message:
            messages.append({"role": "system", "content": system_message})

        messages.append({"role": "user", "content": prompt})

        logger.debug(f"Invoking Gemini (sync) with prompt (length={len(prompt)} chars)")

        try:
            response = self.llm.invoke(messages)

            # Extract text content
            if hasattr(response, "content"):
                response_text = response.content
            else:
                response_text = str(response)

            if not response_text or not response_text.strip():
                raise LLMResponseError("LLM returned empty response")

            logger.debug(f"Gemini response received (length={len(response_text)} chars)")

            return response_text.strip()

        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e)

            logger.error(f"Gemini API error: {error_type}: {error_msg}")

            # Categorize error
            if "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
                raise LLMConnectionError(f"LLM API timeout: {error_msg}") from e
            elif "connection" in error_msg.lower() or "network" in error_msg.lower():
                raise LLMConnectionError(f"LLM API connection error: {error_msg}") from e
            elif "api key" in error_msg.lower() or "authentication" in error_msg.lower():
                raise LLMConnectionError(f"LLM API authentication error: {error_msg}") from e
            else:
                raise LLMResponseError(f"LLM API error: {error_msg}") from e
