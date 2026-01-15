"""
Multi-POC Prompt Templates - LLM prompts for multi-POC orchestration.

Contains prompt templates and schemas for:
- Multi-POC instruction parsing
- Per-POC response validation
- Conflict resolution
- Global validation
- Context-aware email composition
"""

from dataclasses import dataclass

from pydantic import BaseModel, Field


# ============================================================================
# Multi-POC Output Schemas
# ============================================================================


class DynamicPOCSpawnConfig(BaseModel):
    """Schema for dynamic POC spawning configuration."""

    enabled: bool = Field(
        default=False,
        description="Whether this POC's response may contain new POC emails"
    )
    email_source_field: str | None = Field(
        default=None,
        description="Field name in response that contains POC emails (e.g., 'vendor_emails')"
    )
    request_template: str | None = Field(
        default=None,
        description="Template for requests to spawned POCs"
    )
    success_criteria_template: str | None = Field(
        default=None,
        description="Template for success criteria of spawned POCs"
    )


class ParsedPOCRequirement(BaseModel):
    """Schema for a single POC requirement in multi-POC parsing."""

    id: str = Field(description="Unique identifier (e.g., 'poc_1', 'poc_raj')")
    email: str = Field(description="Email address of this POC")
    request: str = Field(description="What specifically to ask this person")
    success_criteria: str = Field(description="What constitutes success from this POC")
    dependencies: list[str] = Field(
        default_factory=list,
        description="List of POC IDs this depends on (empty if independent)"
    )
    spawns_dynamic_pocs: DynamicPOCSpawnConfig | None = Field(
        default=None,
        description="Configuration if response might spawn new POCs"
    )


class ParsedMultiPOCInstruction(BaseModel):
    """Schema for parsed multi-POC instruction."""

    global_success_criteria: str = Field(
        description="Overall success condition for the entire request"
    )
    pocs: list[ParsedPOCRequirement] = Field(
        description="List of POC requirements with dependencies"
    )


class POCValidationResultSchema(BaseModel):
    """Schema for per-POC validation result."""

    valid: bool = Field(description="Whether POC's response satisfies their criteria")
    criteria_met: list[str] = Field(
        default_factory=list,
        description="List of criteria that were satisfied"
    )
    criteria_missing: list[str] = Field(
        default_factory=list,
        description="List of criteria not satisfied"
    )
    should_retry: bool = Field(
        default=False,
        description="Whether to send follow-up email"
    )
    should_redirect: bool = Field(
        default=False,
        description="Whether POC suggested a redirect"
    )
    redirect_email: str | None = Field(
        default=None,
        description="Email to redirect to (if redirect detected)"
    )
    reasoning: str = Field(description="Detailed explanation of the validation")


class ConflictResolutionSchema(BaseModel):
    """Schema for conflict resolution between POC responses."""

    correct_poc_id: str = Field(description="POC ID with the correct value")
    incorrect_poc_ids: list[str] = Field(
        description="POC IDs with incorrect values that need re-request"
    )
    reasoning: str = Field(description="Explanation of why this POC is correct")
    clarification_request: str = Field(
        description="What to ask the incorrect POC(s) for clarification"
    )


class GlobalValidationResultSchema(BaseModel):
    """Schema for global validation of aggregated data."""

    valid: bool = Field(
        description="Whether combined data satisfies overall request"
    )
    all_criteria_met: bool = Field(
        default=False,
        description="Whether all success criteria were met"
    )
    missing_data: list[str] = Field(
        default_factory=list,
        description="List of data still needed"
    )
    poc_ids_needing_retry: list[str] = Field(
        default_factory=list,
        description="POC IDs that should provide more information"
    )
    reasoning: str = Field(description="Detailed explanation")


# ============================================================================
# Multi-POC Prompt Templates
# ============================================================================


@dataclass
class MultiPOCPromptTemplates:
    """
    Collection of prompt templates for multi-POC orchestration.

    Each template is a method that returns a formatted prompt string.
    """

    # =========================================================================
    # System Prompts
    # =========================================================================

    MULTI_POC_PARSE_SYSTEM = """You are an assistant that extracts structured information from complex multi-person requests.
You must:
1. Identify ALL email addresses (POCs) mentioned in the instruction
2. Determine what specific information is needed from EACH POC
3. Identify dependencies between POCs (e.g., "ask X for Y, then use Y to ask Z")
4. Define per-POC success criteria
5. Define global success criteria for the entire request
6. Identify if any POC's response might contain emails for dynamic POC spawning

Be specific about success criteria (e.g., "10 rows of recipes" not just "recipes").
Assign unique IDs to each POC (e.g., "poc_1", "poc_raj", "poc_vendor_list").
Always respond with the requested JSON structure."""

    POC_VALIDATION_SYSTEM = """You are a validation assistant for multi-POC orchestration.
Your task is to validate a SINGLE POC's response against their SPECIFIC success criteria.

Be strict: if the criteria asked for 10 items and only 8 are provided, mark as invalid.

IMPORTANT: Also check for REDIRECTS. A redirect occurs when:
- The responder says they are NOT the correct point of contact
- The responder suggests contacting someone else (with an email address)
- The responder forwards the request to another person

If redirect detected:
- Set should_redirect=true
- Extract redirect_email
- Set valid=false (original POC did not provide the data)

Check for:
1. Is this a REDIRECT? (highest priority)
2. Does the response meet the POC's specific success criteria?
3. Is the data complete and in the expected format?
4. Is the quality acceptable (meaningful data, not placeholders)?

Provide detailed reasoning for your validation decision."""

    CONFLICT_RESOLUTION_SYSTEM = """You are a conflict resolution assistant for multi-POC data aggregation.
When multiple POCs provide conflicting values for the same data field, you must determine:

1. Which POC has the CORRECT value (based on context, authority, data quality)
2. Why that POC is more trustworthy for this data
3. What clarification to request from the incorrect POC(s)

Consider:
- POC's role/position (who would know this information best?)
- Data quality and specificity
- Consistency with other data points
- Recency of information

Always provide clear reasoning for your decision."""

    GLOBAL_VALIDATION_SYSTEM = """You are a validation assistant for multi-POC data aggregation.
Your task is to validate the AGGREGATED data from all POCs against the GLOBAL success criteria.

The global success criteria represents what the user originally requested.
Even if individual POCs provided valid responses, the combined data might:
- Still be missing key information
- Have gaps that need additional POC requests
- Be incomplete for the user's actual needs

Evaluate:
1. Does the combined data fully satisfy the original user request?
2. Are all required pieces of information present?
3. Is the data coherent and usable?

If not fully satisfied, identify:
- What specific data is still missing
- Which POC(s) should provide the missing data
- Whether new POCs need to be contacted"""

    # =========================================================================
    # Prompt Methods
    # =========================================================================

    @staticmethod
    def parse_multi_poc_instruction(user_instruction: str) -> str:
        """
        Create prompt for parsing multi-POC user instruction.

        Args:
            user_instruction: Raw user input string with multiple POCs.

        Returns:
            Formatted prompt string.
        """
        return f"""Analyze this instruction and extract information about ALL points of contact (POCs):
"{user_instruction}"

For EACH POC identified:
1. Assign a unique ID (e.g., "poc_1", "poc_raj", "poc_vendor")
2. Extract their email address
3. Determine what SPECIFIC information to request from them
4. Define SUCCESS CRITERIA for their response
5. Identify DEPENDENCIES (which POC's data is needed before contacting this POC?)
6. Check if their response might SPAWN new POCs (e.g., "get vendor list, then contact each vendor")

Rules:
- Extract ALL email addresses mentioned
- If a POC depends on another's response, list that dependency
- If a POC's response may contain emails for new contacts, mark spawns_dynamic_pocs
- Be specific about per-POC success criteria (e.g., "10 rows of recipes" not just "recipes")
- Define the GLOBAL success criteria (what makes the entire request successful?)

Return the structured information as specified."""

    @staticmethod
    def validate_poc_response(
        poc_id: str,
        poc_email: str,
        request: str,
        success_criteria: str,
        extracted_content: str,
        row_count: int,
        headers: list[str],
        email_body_text: str | None = None,
        max_content_chars: int = 8000,
    ) -> str:
        """
        Create prompt for validating a single POC's response.

        Args:
            poc_id: Unique identifier for this POC.
            poc_email: POC's email address.
            request: What was requested from this POC.
            success_criteria: Per-POC success criteria.
            extracted_content: JSON/text extracted from attachment.
            row_count: Number of rows in the attachment.
            headers: Column headers from the attachment.
            email_body_text: The email body text (for redirect detection).
            max_content_chars: Maximum characters of content to include.

        Returns:
            Formatted prompt string.
        """
        email_body_section = ""
        if email_body_text:
            email_body_section = f"""
Email body text:
\"\"\"
{email_body_text[:2000]}{"..." if len(email_body_text) > 2000 else ""}
\"\"\"
"""

        return f"""Validate response from POC: {poc_id} ({poc_email})

Original request to this POC: "{request}"
Success criteria for this POC: "{success_criteria}"
{email_body_section}
Received response content:
- Row count: {row_count}
- Headers/Columns: {', '.join(headers) if headers else 'N/A'}
- Data preview:
{extracted_content[:max_content_chars]}{"..." if len(extracted_content) > max_content_chars else ""}

FIRST, check if this is a REDIRECT:
- Does the email body say they are not the correct contact?
- Does it suggest contacting someone else with an email address?
- If YES: Set should_redirect=true, extract redirect_email

If NOT a redirect, validate against the SUCCESS CRITERIA:
1. Does the response contain what was specifically requested?
2. Is the data complete per the criteria?
3. Is the format correct?
4. Is the quality acceptable?

Be strict: if criteria asked for 10 items and only 8 provided, mark as INVALID.
List which criteria were met and which are still missing."""

    @staticmethod
    def resolve_conflict(
        field_name: str,
        poc_values: dict[str, str],
        context: str,
    ) -> str:
        """
        Create prompt for resolving data conflicts between POCs.

        Args:
            field_name: Name of the conflicting field.
            poc_values: Dictionary of poc_id → value for the conflict.
            context: Additional context about the request/POCs.

        Returns:
            Formatted prompt string.
        """
        values_str = "\n".join(
            f"- {poc_id}: \"{value}\"" for poc_id, value in poc_values.items()
        )

        return f"""Data conflict detected for field: "{field_name}"

Conflicting values from different POCs:
{values_str}

Context: {context}

Determine:
1. Which POC has the CORRECT value? (Consider authority, data quality, context)
2. Why is that POC's value more trustworthy?
3. What should we ask the incorrect POC(s) to clarify?

Provide your reasoning and decision."""

    @staticmethod
    def validate_global_criteria(
        global_success_criteria: str,
        aggregated_data_summary: str,
        poc_summaries: list[dict[str, str]],
    ) -> str:
        """
        Create prompt for validating aggregated data against global criteria.

        Args:
            global_success_criteria: Overall success condition.
            aggregated_data_summary: Summary of all aggregated data.
            poc_summaries: List of dicts with poc_id, email, status, data_summary.

        Returns:
            Formatted prompt string.
        """
        poc_info = "\n".join(
            f"- {p['poc_id']} ({p['email']}): Status={p['status']}, Data={p['data_summary']}"
            for p in poc_summaries
        )

        return f"""Validate aggregated data against GLOBAL success criteria.

Global success criteria: "{global_success_criteria}"

Aggregated data summary:
{aggregated_data_summary}

POC contribution breakdown:
{poc_info}

Evaluate:
1. Does the combined data FULLY satisfy the global criteria?
2. Is all required information present and complete?
3. Are there any gaps that need additional data?

If NOT fully satisfied:
- List what specific data is still missing
- Identify which POC(s) should provide the missing data
- Explain why the current data is insufficient

Provide detailed reasoning for your validation decision."""

    @staticmethod
    def compose_email_with_context(
        poc_email: str,
        request: str,
        success_criteria: str,
        context_from_deps: dict[str, str],
        expected_format: str = "text",
    ) -> str:
        """
        Create prompt for composing email with injected context from dependencies.

        This is used when a POC depends on data from other POCs.

        Args:
            poc_email: Recipient email address.
            request: What is being requested.
            success_criteria: Per-POC success criteria.
            context_from_deps: Data injected from completed dependencies.
            expected_format: Expected response format.

        Returns:
            Formatted prompt string.
        """
        context_str = "\n".join(
            f"- {key}: {value}" for key, value in context_from_deps.items()
        )

        return f"""Compose an email to request the following:

Recipient: {poc_email}
Request: {request}
Expected format: {expected_format}
Success criteria: {success_criteria}

IMPORTANT - Use this context from previous POC responses:
{context_str}

The email should:
1. Be professional and polite
2. Clearly state what is needed, incorporating the context above
3. Specify the expected format ({expected_format}) if applicable
4. Mention the specific criteria ({success_criteria})
5. Be concise but complete

Write the email subject and body."""
