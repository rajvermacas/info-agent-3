"""
Tests for the LLM client module.

Tests OpenRouter provider initialization and configuration.
"""

import pytest
from unittest.mock import MagicMock, patch

from mail_agent.config import LLMProvider, Settings
from mail_agent.llm.client import (
    LLMClient,
    LLMConfigurationError,
)


class TestLLMClientOpenRouterInitialization:
    """Tests for LLMClient OpenRouter initialization."""

    def test_init_openrouter_success(self):
        """Test successful OpenRouter initialization."""
        settings = Settings(
            llm_provider=LLMProvider.OPENROUTER,
            openrouter_api_key="test-openrouter-key",
            openrouter_model="anthropic/claude-3.5-sonnet",
        )

        with patch("mail_agent.llm.client.ChatOpenAI") as mock_chat_openai:
            mock_model = MagicMock()
            mock_chat_openai.return_value = mock_model

            client = LLMClient(settings)

            assert client.provider == LLMProvider.OPENROUTER
            assert client.model_name == "anthropic/claude-3.5-sonnet"

            # Verify ChatOpenAI was called with correct parameters
            mock_chat_openai.assert_called_once()
            call_kwargs = mock_chat_openai.call_args[1]
            assert call_kwargs["model"] == "anthropic/claude-3.5-sonnet"
            assert call_kwargs["openai_api_key"] == "test-openrouter-key"
            assert call_kwargs["openai_api_base"] == "https://openrouter.ai/api/v1"

    def test_init_openrouter_missing_key(self):
        """Test OpenRouter initialization fails without API key."""
        settings = Settings(
            llm_provider=LLMProvider.OPENROUTER,
            openrouter_api_key=None,
        )

        with pytest.raises(LLMConfigurationError) as exc_info:
            LLMClient(settings)

        assert "MAIL_AGENT_OPENROUTER_API_KEY" in str(exc_info.value)
        assert "https://openrouter.ai/keys" in str(exc_info.value)

    def test_init_openrouter_with_optional_headers(self):
        """Test OpenRouter initialization with optional ranking headers."""
        settings = Settings(
            llm_provider=LLMProvider.OPENROUTER,
            openrouter_api_key="test-key",
            openrouter_site_url="https://example.com",
            openrouter_app_name="Test App",
        )

        with patch("mail_agent.llm.client.ChatOpenAI") as mock_chat_openai:
            mock_model = MagicMock()
            mock_chat_openai.return_value = mock_model

            LLMClient(settings)

            call_kwargs = mock_chat_openai.call_args[1]
            assert call_kwargs["default_headers"]["HTTP-Referer"] == "https://example.com"
            assert call_kwargs["default_headers"]["X-Title"] == "Test App"

    def test_init_openrouter_without_optional_headers(self):
        """Test OpenRouter initialization without optional headers."""
        settings = Settings(
            llm_provider=LLMProvider.OPENROUTER,
            openrouter_api_key="test-key",
            openrouter_site_url=None,
            openrouter_app_name=None,
        )

        with patch("mail_agent.llm.client.ChatOpenAI") as mock_chat_openai:
            mock_model = MagicMock()
            mock_chat_openai.return_value = mock_model

            LLMClient(settings)

            call_kwargs = mock_chat_openai.call_args[1]
            # default_headers should be None when no optional headers provided
            assert call_kwargs["default_headers"] is None

    def test_init_openrouter_default_model(self):
        """Test OpenRouter uses default model when not specified."""
        settings = Settings(
            llm_provider=LLMProvider.OPENROUTER,
            openrouter_api_key="test-key",
        )

        with patch("mail_agent.llm.client.ChatOpenAI") as mock_chat_openai:
            mock_model = MagicMock()
            mock_chat_openai.return_value = mock_model

            client = LLMClient(settings)

            assert client.model_name == "anthropic/claude-3.5-sonnet"

    def test_init_openrouter_temperature_and_max_tokens(self):
        """Test OpenRouter respects temperature and max_tokens settings."""
        settings = Settings(
            llm_provider=LLMProvider.OPENROUTER,
            openrouter_api_key="test-key",
            llm_temperature=0.7,
            llm_max_tokens=2048,
        )

        with patch("mail_agent.llm.client.ChatOpenAI") as mock_chat_openai:
            mock_model = MagicMock()
            mock_chat_openai.return_value = mock_model

            LLMClient(settings)

            call_kwargs = mock_chat_openai.call_args[1]
            assert call_kwargs["temperature"] == 0.7
            assert call_kwargs["max_tokens"] == 2048


class TestOpenRouterModelFormats:
    """Tests for different OpenRouter model name formats."""

    @pytest.mark.parametrize(
        "model_name",
        [
            "anthropic/claude-3.5-sonnet",
            "google/gemini-2.5-flash",
            "openai/gpt-4-turbo",
            "meta-llama/llama-3.1-70b-instruct",
            "mistralai/mistral-large",
        ],
    )
    def test_openrouter_model_formats(self, model_name):
        """Test OpenRouter accepts various model name formats."""
        settings = Settings(
            llm_provider=LLMProvider.OPENROUTER,
            openrouter_api_key="test-key",
            openrouter_model=model_name,
        )

        with patch("mail_agent.llm.client.ChatOpenAI") as mock_chat_openai:
            mock_model = MagicMock()
            mock_chat_openai.return_value = mock_model

            client = LLMClient(settings)

            call_kwargs = mock_chat_openai.call_args[1]
            assert call_kwargs["model"] == model_name
            assert client.model_name == model_name


class TestOpenRouterWithPartialHeaders:
    """Tests for OpenRouter with partial optional headers."""

    def test_openrouter_with_only_site_url(self):
        """Test OpenRouter with only site_url set."""
        settings = Settings(
            llm_provider=LLMProvider.OPENROUTER,
            openrouter_api_key="test-key",
            openrouter_site_url="https://example.com",
            openrouter_app_name=None,
        )

        with patch("mail_agent.llm.client.ChatOpenAI") as mock_chat_openai:
            mock_model = MagicMock()
            mock_chat_openai.return_value = mock_model

            LLMClient(settings)

            call_kwargs = mock_chat_openai.call_args[1]
            assert call_kwargs["default_headers"]["HTTP-Referer"] == "https://example.com"
            assert "X-Title" not in call_kwargs["default_headers"]

    def test_openrouter_with_only_app_name(self):
        """Test OpenRouter with only app_name set."""
        settings = Settings(
            llm_provider=LLMProvider.OPENROUTER,
            openrouter_api_key="test-key",
            openrouter_site_url=None,
            openrouter_app_name="Test App",
        )

        with patch("mail_agent.llm.client.ChatOpenAI") as mock_chat_openai:
            mock_model = MagicMock()
            mock_chat_openai.return_value = mock_model

            LLMClient(settings)

            call_kwargs = mock_chat_openai.call_args[1]
            assert "HTTP-Referer" not in call_kwargs["default_headers"]
            assert call_kwargs["default_headers"]["X-Title"] == "Test App"
