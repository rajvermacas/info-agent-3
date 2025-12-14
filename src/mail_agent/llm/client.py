"""
LLM Client - Gemini 2.5 Flash integration via LangChain.

Provides async methods for LLM operations with structured output support.
"""

import logging
from dataclasses import dataclass
from typing import Any, Optional, Type, TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel

from mail_agent.config import Settings, get_settings


logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class LLMClientError(Exception):
    """Base exception for LLM client errors."""

    pass


class LLMConnectionError(LLMClientError):
    """Failed to connect to LLM API."""

    pass


class LLMResponseParseError(LLMClientError):
    """Failed to parse LLM response."""

    pass


class LLMConfigurationError(LLMClientError):
    """LLM client is not properly configured."""

    pass


@dataclass
class LLMResponse:
    """Generic LLM response wrapper."""

    content: str
    model: str
    usage: Optional[dict[str, int]] = None


class LLMClient:
    """
    Async client for Gemini 2.5 Flash via LangChain.

    Supports both free-form text and structured (Pydantic) outputs.
    """

    def __init__(
        self,
        settings: Optional[Settings] = None,
    ) -> None:
        """
        Initialize LLM client.

        Args:
            settings: Configuration settings. Uses get_settings() if not provided.

        Raises:
            LLMConfigurationError: If API key is not configured.
        """
        self._settings = settings or get_settings()

        if not self._settings.gemini_api_key:
            raise LLMConfigurationError(
                "MAIL_AGENT_GEMINI_API_KEY environment variable is required. "
                "Please set it to your Google Gemini API key."
            )

        self._model_name = self._settings.gemini_model
        self._temperature = self._settings.llm_temperature
        self._max_tokens = self._settings.llm_max_tokens

        # Create the LangChain model
        self._model = ChatGoogleGenerativeAI(
            model=self._model_name,
            google_api_key=self._settings.gemini_api_key,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
        )

        logger.info(
            f"LLMClient initialized: model={self._model_name}, "
            f"temperature={self._temperature}, max_tokens={self._max_tokens}"
        )

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
    ) -> LLMResponse:
        """
        Generate a free-form text response.

        Args:
            prompt: User prompt/question.
            system_prompt: Optional system prompt for context.

        Returns:
            LLMResponse with generated text.

        Raises:
            LLMConnectionError: If API call fails.
        """
        logger.debug(f"Generating response for prompt: {prompt[:100]}...")

        messages = []
        if system_prompt:
            messages.append(SystemMessage(content=system_prompt))
        messages.append(HumanMessage(content=prompt))

        try:
            response = await self._model.ainvoke(messages)

            result = LLMResponse(
                content=response.content,
                model=self._model_name,
                usage=response.usage_metadata if hasattr(response, "usage_metadata") else None,
            )

            logger.debug(f"Generated response: {result.content[:100]}...")
            return result

        except Exception as e:
            error_msg = f"LLM generation failed: {e}"
            logger.error(error_msg)
            raise LLMConnectionError(error_msg) from e

    async def generate_structured(
        self,
        prompt: str,
        output_schema: Type[T],
        system_prompt: Optional[str] = None,
    ) -> T:
        """
        Generate a structured response matching a Pydantic schema.

        Args:
            prompt: User prompt/question.
            output_schema: Pydantic model class for the expected output.
            system_prompt: Optional system prompt for context.

        Returns:
            Instance of output_schema with generated data.

        Raises:
            LLMConnectionError: If API call fails.
            LLMResponseParseError: If response cannot be parsed to schema.
        """
        logger.debug(
            f"Generating structured response for schema: {output_schema.__name__}"
        )

        messages = []
        if system_prompt:
            messages.append(SystemMessage(content=system_prompt))
        messages.append(HumanMessage(content=prompt))

        try:
            # Create structured output model
            structured_model = self._model.with_structured_output(output_schema)
            response = await structured_model.ainvoke(messages)

            if not isinstance(response, output_schema):
                raise LLMResponseParseError(
                    f"Response is not an instance of {output_schema.__name__}"
                )

            logger.debug(f"Generated structured response: {response}")
            return response

        except LLMResponseParseError:
            raise
        except Exception as e:
            error_msg = f"Structured LLM generation failed: {e}"
            logger.error(error_msg)
            raise LLMConnectionError(error_msg) from e

    async def generate_json(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Generate a JSON response.

        Instructs the model to output valid JSON and attempts to parse it.

        Args:
            prompt: User prompt/question.
            system_prompt: Optional system prompt for context.

        Returns:
            Parsed JSON as a dictionary.

        Raises:
            LLMConnectionError: If API call fails.
            LLMResponseParseError: If response is not valid JSON.
        """
        import json

        # Add JSON instruction to system prompt
        json_instruction = "You must respond with valid JSON only. No markdown, no explanations."
        if system_prompt:
            full_system = f"{system_prompt}\n\n{json_instruction}"
        else:
            full_system = json_instruction

        response = await self.generate(prompt, system_prompt=full_system)

        try:
            # Try to extract JSON from response
            content = response.content.strip()

            # Handle markdown code blocks
            if content.startswith("```json"):
                content = content[7:]
            if content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]

            content = content.strip()
            return json.loads(content)

        except json.JSONDecodeError as e:
            error_msg = f"Failed to parse LLM response as JSON: {e}"
            logger.error(f"{error_msg}. Response was: {response.content}")
            raise LLMResponseParseError(error_msg) from e

    @property
    def model_name(self) -> str:
        """Get the model name."""
        return self._model_name
