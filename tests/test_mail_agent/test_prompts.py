"""
Tests for the LLM prompt templates.
"""

import pytest

from mail_agent.llm.prompts import (
    ComposedEmail,
    FollowUpEmail,
    ParsedInstruction,
    PromptTemplates,
    ValidationResult,
)


class TestPydanticSchemas:
    """Tests for Pydantic output schemas."""

    def test_parsed_instruction_schema(self):
        """Test ParsedInstruction schema."""
        data = ParsedInstruction(
            poc_emails=["test@example.com"],
            request_type="data_request",
            request_description="Get 10 recipes",
            success_criteria="10 rows of recipes",
            expected_format="excel",
        )

        assert data.poc_emails == ["test@example.com"]
        assert data.request_type == "data_request"
        assert data.expected_format == "excel"

    def test_composed_email_schema(self):
        """Test ComposedEmail schema."""
        data = ComposedEmail(
            subject="Request: 10 Recipes",
            body="Dear Sir,\n\nPlease provide...",
        )

        assert data.subject == "Request: 10 Recipes"
        assert "Dear Sir" in data.body

    def test_validation_result_schema(self):
        """Test ValidationResult schema."""
        data = ValidationResult(
            is_valid=False,
            feedback="Only 8 recipes provided",
            missing_items=["Recipe 9", "Recipe 10"],
        )

        assert data.is_valid is False
        assert len(data.missing_items) == 2

    def test_followup_email_schema(self):
        """Test FollowUpEmail schema."""
        data = FollowUpEmail(
            subject="Re: Request: 10 Recipes",
            body="Thank you for your response...",
        )

        assert "Re:" in data.subject


class TestPromptTemplates:
    """Tests for prompt template methods."""

    def test_parse_instruction_prompt(self):
        """Test parse_instruction prompt generation."""
        prompt = PromptTemplates.parse_instruction(
            "send mail to test@example.com asking 10 recipes"
        )

        assert "test@example.com" in prompt
        assert "10 recipes" in prompt
        assert "email addresses" in prompt.lower()

    def test_compose_email_prompt(self):
        """Test compose_email prompt generation."""
        prompt = PromptTemplates.compose_email(
            poc_email="test@example.com",
            request_description="10 food recipes",
            expected_format="excel",
            success_criteria="10 rows of recipes with ingredients",
        )

        assert "test@example.com" in prompt
        assert "10 food recipes" in prompt
        assert "excel" in prompt.lower()
        assert "10 rows" in prompt

    def test_validate_response_prompt(self):
        """Test validate_response prompt generation."""
        prompt = PromptTemplates.validate_response(
            request_description="10 food recipes",
            success_criteria="10 rows with ingredients",
            extracted_content='[{"Recipe": "Pasta"}]',
            row_count=8,
            headers=["Recipe", "Ingredients"],
        )

        assert "10 food recipes" in prompt
        assert "10 rows with ingredients" in prompt
        assert "Row count: 8" in prompt
        assert "Recipe, Ingredients" in prompt
        assert "Pasta" in prompt

    def test_validate_response_prompt_truncation(self):
        """Test validate_response truncates long content."""
        long_content = "x" * 3000

        prompt = PromptTemplates.validate_response(
            request_description="test",
            success_criteria="test",
            extracted_content=long_content,
            row_count=1,
            headers=["A"],
        )

        assert "..." in prompt
        # Content should be truncated to 2000 chars
        assert long_content[:2000] in prompt

    def test_compose_followup_prompt(self):
        """Test compose_followup prompt generation."""
        prompt = PromptTemplates.compose_followup(
            request_description="10 food recipes",
            validation_feedback="Only 8 recipes provided",
            missing_items=["Recipe 9", "Recipe 10"],
            attempt_count=2,
            max_attempts=5,
            original_subject="Request: Recipes",
        )

        assert "10 food recipes" in prompt
        assert "8 recipes provided" in prompt
        assert "Recipe 9" in prompt
        assert "Recipe 10" in prompt
        assert "2 of 5" in prompt
        assert "Request: Recipes" in prompt

    def test_compose_followup_urgent_message(self):
        """Test compose_followup adds urgency near max attempts."""
        prompt = PromptTemplates.compose_followup(
            request_description="test",
            validation_feedback="test",
            missing_items=[],
            attempt_count=4,
            max_attempts=5,
            original_subject="Test",
        )

        # Should include urgency message
        assert "low on attempts" in prompt.lower() or "more direct" in prompt.lower()

    def test_compose_email_for_text_response(self):
        """Test compose_email_for_text_response prompt."""
        prompt = PromptTemplates.compose_email_for_text_response(
            poc_email="test@example.com",
            request_description="What is the capital of France?",
        )

        assert "test@example.com" in prompt
        assert "capital of France" in prompt
        assert "text response" in prompt.lower()


class TestSystemPrompts:
    """Tests for system prompt constants."""

    def test_parse_system_prompt(self):
        """Test PARSE_SYSTEM prompt content."""
        assert "extract" in PromptTemplates.PARSE_SYSTEM.lower()
        assert "email" in PromptTemplates.PARSE_SYSTEM.lower()
        assert "json" in PromptTemplates.PARSE_SYSTEM.lower()

    def test_compose_system_prompt(self):
        """Test COMPOSE_SYSTEM prompt content."""
        assert "professional" in PromptTemplates.COMPOSE_SYSTEM.lower()
        assert "polite" in PromptTemplates.COMPOSE_SYSTEM.lower()

    def test_validate_system_prompt(self):
        """Test VALIDATE_SYSTEM prompt content."""
        assert "strict" in PromptTemplates.VALIDATE_SYSTEM.lower()
        assert "invalid" in PromptTemplates.VALIDATE_SYSTEM.lower()

    def test_followup_system_prompt(self):
        """Test FOLLOWUP_SYSTEM prompt content."""
        assert "thank" in PromptTemplates.FOLLOWUP_SYSTEM.lower()
        assert "polite" in PromptTemplates.FOLLOWUP_SYSTEM.lower()
