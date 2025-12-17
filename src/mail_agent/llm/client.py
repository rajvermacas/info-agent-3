"""
LLM Client - Multi-provider LLM integration via LangChain.

Supports Google Gemini, Azure OpenAI, and OpenRouter providers.
Provides async methods for LLM operations with structured output support.
"""

import logging
from dataclasses import dataclass
from typing import Any, Optional, Type, TypeVar

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import AzureChatOpenAI, ChatOpenAI
from pydantic import BaseModel

from mail_agent.config import LLMProvider, Settings, get_settings


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
    Async client for LLM operations via LangChain.

    Supports multiple providers (Gemini, Azure OpenAI) with
    both free-form text and structured (Pydantic) outputs.
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
            LLMConfigurationError: If required credentials are not configured.
        """
        self._settings = settings or get_settings()
        self._temperature = self._settings.llm_temperature
        self._max_tokens = self._settings.llm_max_tokens
        self._provider = self._settings.llm_provider

        # Initialize the appropriate provider
        self._model: BaseChatModel
        if self._provider == LLMProvider.GEMINI:
            self._model, self._model_name = self._init_gemini()
        elif self._provider == LLMProvider.AZURE_OPENAI:
            self._model, self._model_name = self._init_azure_openai()
        elif self._provider == LLMProvider.OPENROUTER:
            self._model, self._model_name = self._init_openrouter()
        else:
            raise LLMConfigurationError(
                f"Unknown LLM provider: {self._provider}. "
                f"Supported providers: {[p.value for p in LLMProvider]}"
            )

        logger.info(
            f"LLMClient initialized: provider={self._provider.value}, "
            f"model={self._model_name}, temperature={self._temperature}, "
            f"max_tokens={self._max_tokens}"
        )

    def _init_gemini(self) -> tuple[BaseChatModel, str]:
        """Initialize Google Gemini model."""
        if not self._settings.gemini_api_key:
            raise LLMConfigurationError(
                "MAIL_AGENT_GEMINI_API_KEY environment variable is required "
                "when using Gemini provider. Please set it to your Google Gemini API key."
            )

        model_name = self._settings.gemini_model
        model = ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=self._settings.gemini_api_key,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
        )
        return model, model_name

    def _init_azure_openai(self) -> tuple[BaseChatModel, str]:
        """Initialize Azure OpenAI model."""
        if not self._settings.azure_openai_api_key:
            raise LLMConfigurationError(
                "MAIL_AGENT_AZURE_OPENAI_API_KEY environment variable is required "
                "when using Azure OpenAI provider."
            )
        if not self._settings.azure_openai_endpoint:
            raise LLMConfigurationError(
                "MAIL_AGENT_AZURE_OPENAI_ENDPOINT environment variable is required "
                "when using Azure OpenAI provider."
            )
        if not self._settings.azure_openai_deployment_name:
            raise LLMConfigurationError(
                "MAIL_AGENT_AZURE_OPENAI_DEPLOYMENT_NAME environment variable is required "
                "when using Azure OpenAI provider."
            )

        model_name = self._settings.azure_openai_deployment_name
        model = AzureChatOpenAI(
            azure_deployment=model_name,
            azure_endpoint=self._settings.azure_openai_endpoint,
            api_key=self._settings.azure_openai_api_key,
            api_version=self._settings.azure_openai_api_version,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
        )
        return model, model_name

    def _init_openrouter(self) -> tuple[BaseChatModel, str]:
        """
        Initialize OpenRouter model using OpenAI-compatible API.

        OpenRouter provides access to 200+ models via https://openrouter.ai/api/v1

        Returns:
            Tuple of (model instance, model name string)

        Raises:
            LLMConfigurationError: If API key is missing
        """
        if not self._settings.openrouter_api_key:
            raise LLMConfigurationError(
                "MAIL_AGENT_OPENROUTER_API_KEY environment variable is required "
                "when using OpenRouter provider. Get your key from: https://openrouter.ai/keys"
            )

        model_name = self._settings.openrouter_model

        logger.debug(f"Initializing OpenRouter with model: {model_name}")

        # Build optional headers for OpenRouter rankings
        default_headers = {}
        if self._settings.openrouter_site_url:
            default_headers["HTTP-Referer"] = self._settings.openrouter_site_url
        if self._settings.openrouter_app_name:
            default_headers["X-Title"] = self._settings.openrouter_app_name

        model = ChatOpenAI(
            model=model_name,
            openai_api_key=self._settings.openrouter_api_key,
            openai_api_base="https://openrouter.ai/api/v1",
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            default_headers=default_headers if default_headers else None,
        )

        logger.info(f"OpenRouter model initialized: {model_name}")
        return model, model_name

    def _create_model_with_max_tokens(self, max_tokens: int) -> BaseChatModel:
        """
        Create a new model instance with a custom max_tokens setting.

        Used when a specific operation needs more tokens than the default.
        For example, cross-POC validation may need 16384 tokens instead of 4096.

        Args:
            max_tokens: Maximum tokens for the response.

        Returns:
            BaseChatModel instance with the custom max_tokens setting.

        Raises:
            LLMConfigurationError: If provider is unknown.
        """
        logger.debug(
            f"Creating model with custom max_tokens={max_tokens} "
            f"(default was {self._max_tokens})"
        )

        if self._provider == LLMProvider.GEMINI:
            return ChatGoogleGenerativeAI(
                model=self._settings.gemini_model,
                google_api_key=self._settings.gemini_api_key,
                temperature=self._temperature,
                max_tokens=max_tokens,
            )
        elif self._provider == LLMProvider.AZURE_OPENAI:
            return AzureChatOpenAI(
                azure_deployment=self._settings.azure_openai_deployment_name,
                azure_endpoint=self._settings.azure_openai_endpoint,
                api_key=self._settings.azure_openai_api_key,
                api_version=self._settings.azure_openai_api_version,
                temperature=self._temperature,
                max_tokens=max_tokens,
            )
        elif self._provider == LLMProvider.OPENROUTER:
            default_headers = {}
            if self._settings.openrouter_site_url:
                default_headers["HTTP-Referer"] = self._settings.openrouter_site_url
            if self._settings.openrouter_app_name:
                default_headers["X-Title"] = self._settings.openrouter_app_name

            return ChatOpenAI(
                model=self._settings.openrouter_model,
                openai_api_key=self._settings.openrouter_api_key,
                openai_api_base="https://openrouter.ai/api/v1",
                temperature=self._temperature,
                max_tokens=max_tokens,
                default_headers=default_headers if default_headers else None,
            )
        else:
            raise LLMConfigurationError(
                f"Unknown LLM provider: {self._provider}. "
                f"Cannot create model with custom max_tokens."
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
        max_tokens: Optional[int] = None,
    ) -> T:
        """
        Generate a structured response matching a Pydantic schema.

        Args:
            prompt: User prompt/question.
            output_schema: Pydantic model class for the expected output.
            system_prompt: Optional system prompt for context.
            max_tokens: Optional override for max tokens. Use for operations that
                need more tokens than the default (e.g., cross-POC validation).

        Returns:
            Instance of output_schema with generated data.

        Raises:
            LLMConnectionError: If API call fails.
            LLMResponseParseError: If response cannot be parsed to schema.
        """
        logger.debug(
            f"Generating structured response for schema: {output_schema.__name__}"
            f"{f', max_tokens={max_tokens}' if max_tokens else ''}"
        )

        messages = []
        if system_prompt:
            messages.append(SystemMessage(content=system_prompt))
        messages.append(HumanMessage(content=prompt))

        try:
            # Use custom max_tokens model if specified, otherwise use default model
            if max_tokens is not None:
                model = self._create_model_with_max_tokens(max_tokens)
            else:
                model = self._model

            # Create structured output model
            structured_model = model.with_structured_output(output_schema)
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

    @property
    def provider(self) -> LLMProvider:
        """Get the LLM provider."""
        return self._provider
