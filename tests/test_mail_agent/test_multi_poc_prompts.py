"""
Tests for the multi-POC LLM prompt templates.

Tests MultiPOCPromptTemplates system prompts and methods,
as well as multi-POC output schemas.
"""

import pytest

from mail_agent.llm.prompts import (
    # Multi-POC schemas (re-exported from prompts.py)
    DynamicPOCSpawnConfig,
    ParsedPOCRequirement,
    ParsedMultiPOCInstruction,
    POCValidationResultSchema,
    ConflictResolutionSchema,
    GlobalValidationResultSchema,
    # Prompt templates
    MultiPOCPromptTemplates,
)


# ============================================================================
# Multi-POC Schema Tests
# ============================================================================


class TestDynamicPOCSpawnConfig:
    """Tests for DynamicPOCSpawnConfig schema."""

    def test_default_values(self):
        """Test DynamicPOCSpawnConfig default values."""
        config = DynamicPOCSpawnConfig()

        assert config.enabled is False
        assert config.email_source_field is None
        assert config.request_template is None
        assert config.success_criteria_template is None

    def test_enabled_config(self):
        """Test DynamicPOCSpawnConfig enabled configuration."""
        config = DynamicPOCSpawnConfig(
            enabled=True,
            email_source_field="vendor_emails",
            request_template="Request quote from {email}",
            success_criteria_template="Quote received with price",
        )

        assert config.enabled is True
        assert config.email_source_field == "vendor_emails"
        assert "Request quote" in config.request_template


class TestParsedPOCRequirement:
    """Tests for ParsedPOCRequirement schema."""

    def test_basic_requirement(self):
        """Test ParsedPOCRequirement basic creation."""
        req = ParsedPOCRequirement(
            id="poc_raj",
            email="raj@example.com",
            request="Get 10 recipes in CSV format",
            success_criteria="10 rows of recipes with ingredients",
        )

        assert req.id == "poc_raj"
        assert req.email == "raj@example.com"
        assert "10 recipes" in req.request
        assert req.dependencies == []
        assert req.spawns_dynamic_pocs is None

    def test_requirement_with_dependencies(self):
        """Test ParsedPOCRequirement with dependencies."""
        req = ParsedPOCRequirement(
            id="poc_2",
            email="priya@example.com",
            request="Validate data from poc_1",
            success_criteria="Validation report",
            dependencies=["poc_1"],
        )

        assert req.dependencies == ["poc_1"]

    def test_requirement_with_dynamic_spawn(self):
        """Test ParsedPOCRequirement with dynamic spawn config."""
        spawn_config = DynamicPOCSpawnConfig(
            enabled=True,
            email_source_field="vendor_list",
        )
        req = ParsedPOCRequirement(
            id="poc_admin",
            email="admin@example.com",
            request="Get vendor list",
            success_criteria="List of vendor emails",
            spawns_dynamic_pocs=spawn_config,
        )

        assert req.spawns_dynamic_pocs is not None
        assert req.spawns_dynamic_pocs.enabled is True


class TestParsedMultiPOCInstruction:
    """Tests for ParsedMultiPOCInstruction schema."""

    def test_basic_instruction(self):
        """Test ParsedMultiPOCInstruction creation."""
        instruction = ParsedMultiPOCInstruction(
            global_success_criteria="All data collected from both POCs",
            pocs=[
                ParsedPOCRequirement(
                    id="poc_1",
                    email="first@example.com",
                    request="Get first data",
                    success_criteria="First data received",
                ),
                ParsedPOCRequirement(
                    id="poc_2",
                    email="second@example.com",
                    request="Get second data",
                    success_criteria="Second data received",
                ),
            ],
        )

        assert "All data collected" in instruction.global_success_criteria
        assert len(instruction.pocs) == 2
        assert instruction.pocs[0].id == "poc_1"
        assert instruction.pocs[1].id == "poc_2"


class TestPOCValidationResultSchema:
    """Tests for POCValidationResultSchema."""

    def test_valid_result(self):
        """Test valid POCValidationResultSchema."""
        result = POCValidationResultSchema(
            valid=True,
            criteria_met=["10 rows provided", "CSV format correct"],
            reasoning="All criteria satisfied",
        )

        assert result.valid is True
        assert len(result.criteria_met) == 2
        assert result.should_retry is False
        assert result.should_redirect is False

    def test_invalid_needs_retry(self):
        """Test invalid result needing retry."""
        result = POCValidationResultSchema(
            valid=False,
            criteria_met=["CSV format correct"],
            criteria_missing=["Only 8 rows instead of 10"],
            should_retry=True,
            reasoning="Missing 2 rows of data",
        )

        assert result.valid is False
        assert result.should_retry is True
        assert len(result.criteria_missing) == 1

    def test_redirect_result(self):
        """Test redirect validation result."""
        result = POCValidationResultSchema(
            valid=False,
            should_redirect=True,
            redirect_email="other@example.com",
            reasoning="POC suggested contacting another person",
        )

        assert result.should_redirect is True
        assert result.redirect_email == "other@example.com"


class TestConflictResolutionSchema:
    """Tests for ConflictResolutionSchema."""

    def test_conflict_resolution(self):
        """Test ConflictResolutionSchema creation."""
        resolution = ConflictResolutionSchema(
            correct_poc_id="poc_1",
            incorrect_poc_ids=["poc_2", "poc_3"],
            reasoning="POC 1 is the authoritative source for pricing",
            clarification_request="Please verify the price with your records",
        )

        assert resolution.correct_poc_id == "poc_1"
        assert len(resolution.incorrect_poc_ids) == 2
        assert "authoritative" in resolution.reasoning


class TestGlobalValidationResultSchema:
    """Tests for GlobalValidationResultSchema."""

    def test_valid_global_result(self):
        """Test valid global validation result."""
        result = GlobalValidationResultSchema(
            valid=True,
            all_criteria_met=True,
            reasoning="All data collected successfully",
        )

        assert result.valid is True
        assert result.all_criteria_met is True
        assert result.missing_data == []
        assert result.poc_ids_needing_retry == []

    def test_invalid_global_result(self):
        """Test invalid global validation result."""
        result = GlobalValidationResultSchema(
            valid=False,
            all_criteria_met=False,
            missing_data=["vendor pricing", "delivery dates"],
            poc_ids_needing_retry=["poc_2", "poc_3"],
            reasoning="Missing critical data from some POCs",
        )

        assert result.valid is False
        assert len(result.missing_data) == 2
        assert len(result.poc_ids_needing_retry) == 2


# ============================================================================
# Multi-POC System Prompt Tests
# ============================================================================


class TestMultiPOCSystemPrompts:
    """Tests for multi-POC system prompt constants."""

    def test_multi_poc_parse_system(self):
        """Test MULTI_POC_PARSE_SYSTEM prompt content."""
        system = MultiPOCPromptTemplates.MULTI_POC_PARSE_SYSTEM

        assert "email addresses" in system.lower()
        assert "dependencies" in system.lower()
        assert "success criteria" in system.lower()
        assert "json" in system.lower()

    def test_poc_validation_system(self):
        """Test POC_VALIDATION_SYSTEM prompt content."""
        system = MultiPOCPromptTemplates.POC_VALIDATION_SYSTEM

        assert "strict" in system.lower()
        assert "redirect" in system.lower()
        assert "should_redirect" in system.lower()
        assert "criteria" in system.lower()

    def test_conflict_resolution_system(self):
        """Test CONFLICT_RESOLUTION_SYSTEM prompt content."""
        system = MultiPOCPromptTemplates.CONFLICT_RESOLUTION_SYSTEM

        assert "conflict" in system.lower()
        assert "correct" in system.lower()
        assert "trustworthy" in system.lower()
        assert "clarification" in system.lower()

    def test_global_validation_system(self):
        """Test GLOBAL_VALIDATION_SYSTEM prompt content."""
        system = MultiPOCPromptTemplates.GLOBAL_VALIDATION_SYSTEM

        assert "aggregated" in system.lower()
        assert "global success criteria" in system.lower()
        assert "missing" in system.lower()


# ============================================================================
# Multi-POC Prompt Method Tests
# ============================================================================


class TestMultiPOCPromptMethods:
    """Tests for multi-POC prompt generation methods."""

    def test_parse_multi_poc_instruction(self):
        """Test parse_multi_poc_instruction prompt generation."""
        instruction = (
            "Contact raj@test.com for 10 recipes and priya@test.com "
            "for ingredient prices"
        )

        prompt = MultiPOCPromptTemplates.parse_multi_poc_instruction(instruction)

        assert "raj@test.com" in prompt
        assert "priya@test.com" in prompt
        assert "recipes" in prompt
        assert "DEPENDENCIES" in prompt
        assert "SUCCESS CRITERIA" in prompt
        assert "GLOBAL success criteria" in prompt

    def test_validate_poc_response_basic(self):
        """Test validate_poc_response prompt generation."""
        prompt = MultiPOCPromptTemplates.validate_poc_response(
            poc_id="poc_raj",
            poc_email="raj@test.com",
            request="Get 10 recipes in CSV format",
            success_criteria="10 rows of recipes with ingredients",
            extracted_content='[{"recipe": "pasta", "ingredients": "noodles"}]',
            row_count=8,
            headers=["recipe", "ingredients"],
        )

        assert "poc_raj" in prompt
        assert "raj@test.com" in prompt
        assert "10 recipes" in prompt
        assert "10 rows" in prompt
        assert "Row count: 8" in prompt
        assert "recipe, ingredients" in prompt
        assert "REDIRECT" in prompt

    def test_validate_poc_response_with_email_body(self):
        """Test validate_poc_response with email body for redirect detection."""
        email_body = "I'm not the right person. Please contact john@test.com."

        prompt = MultiPOCPromptTemplates.validate_poc_response(
            poc_id="poc_1",
            poc_email="test@test.com",
            request="Get data",
            success_criteria="Data received",
            extracted_content="[]",
            row_count=0,
            headers=[],
            email_body_text=email_body,
        )

        assert "not the right person" in prompt
        assert "john@test.com" in prompt
        assert "Email body text" in prompt

    def test_validate_poc_response_truncation(self):
        """Test validate_poc_response truncates long content."""
        long_content = "x" * 10000

        prompt = MultiPOCPromptTemplates.validate_poc_response(
            poc_id="poc_1",
            poc_email="test@test.com",
            request="Test",
            success_criteria="Test",
            extracted_content=long_content,
            row_count=1,
            headers=["a"],
        )

        # Should be truncated to 8000 chars
        assert long_content[:8000] in prompt
        assert "..." in prompt

    def test_validate_poc_response_custom_max_chars(self):
        """Test validate_poc_response respects custom max_content_chars."""
        long_content = "x" * 5000

        prompt = MultiPOCPromptTemplates.validate_poc_response(
            poc_id="poc_1",
            poc_email="test@test.com",
            request="Test",
            success_criteria="Test",
            extracted_content=long_content,
            row_count=1,
            headers=["a"],
            max_content_chars=2000,
        )

        assert long_content[:2000] in prompt
        assert long_content[:2001] not in prompt

    def test_resolve_conflict(self):
        """Test resolve_conflict prompt generation."""
        prompt = MultiPOCPromptTemplates.resolve_conflict(
            field_name="unit_price",
            poc_values={"poc_raj": "100", "poc_priya": "150"},
            context="Raj is from the sales team, Priya is from accounting",
        )

        assert "unit_price" in prompt
        assert "poc_raj" in prompt
        assert "100" in prompt
        assert "poc_priya" in prompt
        assert "150" in prompt
        assert "sales team" in prompt
        assert "accounting" in prompt

    def test_validate_global_criteria(self):
        """Test validate_global_criteria prompt generation."""
        poc_summaries = [
            {
                "poc_id": "poc_1",
                "email": "first@test.com",
                "status": "completed",
                "data_summary": "10 recipes received",
            },
            {
                "poc_id": "poc_2",
                "email": "second@test.com",
                "status": "completed",
                "data_summary": "Prices for 10 items",
            },
        ]

        prompt = MultiPOCPromptTemplates.validate_global_criteria(
            global_success_criteria="Complete recipe list with prices",
            aggregated_data_summary="10 recipes with pricing information",
            poc_summaries=poc_summaries,
        )

        assert "Complete recipe list" in prompt
        assert "10 recipes with pricing" in prompt
        assert "poc_1" in prompt
        assert "poc_2" in prompt
        assert "first@test.com" in prompt
        assert "completed" in prompt

    def test_compose_email_with_context(self):
        """Test compose_email_with_context prompt generation."""
        context_from_deps = {
            "vendor_list": "Vendor A, Vendor B, Vendor C",
            "budget": "$10,000",
        }

        prompt = MultiPOCPromptTemplates.compose_email_with_context(
            poc_email="vendor_a@test.com",
            request="Request quote for office supplies",
            success_criteria="Quote with itemized pricing",
            context_from_deps=context_from_deps,
            expected_format="excel",
        )

        assert "vendor_a@test.com" in prompt
        assert "office supplies" in prompt
        assert "Quote with itemized" in prompt
        assert "vendor_list" in prompt
        assert "Vendor A, Vendor B" in prompt
        assert "budget" in prompt
        assert "$10,000" in prompt
        assert "excel" in prompt.lower()

    def test_compose_email_with_context_default_format(self):
        """Test compose_email_with_context uses default format."""
        prompt = MultiPOCPromptTemplates.compose_email_with_context(
            poc_email="test@test.com",
            request="Get info",
            success_criteria="Info received",
            context_from_deps={"key": "value"},
        )

        # Default format is "text"
        assert "text" in prompt.lower()


# ============================================================================
# Re-export Tests
# ============================================================================


class TestMultiPOCReexports:
    """Tests to verify multi-POC schemas are properly re-exported from prompts.py."""

    def test_import_from_prompts_module(self):
        """Test that multi-POC schemas can be imported from prompts module."""
        from mail_agent.llm.prompts import (
            DynamicPOCSpawnConfig,
            ParsedPOCRequirement,
            ParsedMultiPOCInstruction,
            POCValidationResultSchema,
            ConflictResolutionSchema,
            GlobalValidationResultSchema,
            MultiPOCPromptTemplates,
        )

        # Verify they are the correct types
        assert DynamicPOCSpawnConfig is not None
        assert ParsedPOCRequirement is not None
        assert ParsedMultiPOCInstruction is not None
        assert POCValidationResultSchema is not None
        assert ConflictResolutionSchema is not None
        assert GlobalValidationResultSchema is not None
        assert MultiPOCPromptTemplates is not None

    def test_import_from_multi_poc_prompts_module(self):
        """Test that schemas can be imported directly from multi_poc_prompts."""
        from mail_agent.llm.multi_poc_prompts import (
            DynamicPOCSpawnConfig,
            ParsedPOCRequirement,
            ParsedMultiPOCInstruction,
            POCValidationResultSchema,
            ConflictResolutionSchema,
            GlobalValidationResultSchema,
            MultiPOCPromptTemplates,
        )

        # Verify they are the correct types
        assert DynamicPOCSpawnConfig is not None
        assert ParsedPOCRequirement is not None
        assert ParsedMultiPOCInstruction is not None
        assert POCValidationResultSchema is not None
        assert ConflictResolutionSchema is not None
        assert GlobalValidationResultSchema is not None
        assert MultiPOCPromptTemplates is not None
