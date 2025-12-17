"""
Prompt Templates - LLM prompts for the mail agent.

Contains all prompt templates for parsing, composing, validating, and following up.
"""

from dataclasses import dataclass
from typing import Optional

from pydantic import BaseModel, Field


# ============================================================================
# Pydantic Output Schemas
# ============================================================================


class ParsedInstruction(BaseModel):
    """Schema for parsed user instruction."""

    poc_emails: list[str] = Field(
        description="List of email addresses to contact (POCs)"
    )
    request_type: str = Field(
        description="Type of request: data_request, information_request, or action_request"
    )
    request_description: str = Field(
        description="Brief description of what is being requested"
    )
    success_criteria: str = Field(
        description="Specific criteria to validate the response (e.g., '10 rows of recipes')"
    )
    expected_format: str = Field(
        description="Expected response format: excel, csv, or text"
    )


class ComposedEmail(BaseModel):
    """Schema for composed email."""

    subject: str = Field(description="Email subject line")
    body: str = Field(description="Full email body text")


class RedirectInfo(BaseModel):
    """Schema for redirect information when POC suggests another contact."""

    is_redirect: bool = Field(
        default=False,
        description="Whether the response indicates redirection to another person"
    )
    redirect_email: str | None = Field(
        default=None,
        description="Email address of the new contact to redirect to"
    )
    redirect_reason: str | None = Field(
        default=None,
        description="Reason given for the redirect (e.g., 'not the right department')"
    )


class ValidationResult(BaseModel):
    """Schema for response validation result."""

    is_valid: bool = Field(description="Whether the response satisfies the request")
    feedback: str = Field(
        description="Detailed explanation of what is correct, missing, or wrong"
    )
    missing_items: list[str] = Field(
        default_factory=list,
        description="List of specific items that are missing or incorrect",
    )
    redirect: RedirectInfo = Field(
        default_factory=RedirectInfo,
        description="Redirect information if POC suggests another contact"
    )


class FollowUpEmail(BaseModel):
    """Schema for follow-up email."""

    subject: str = Field(description="Follow-up email subject (usually Re: original)")
    body: str = Field(description="Follow-up email body text")


# ============================================================================
# Prompt Templates
# ============================================================================


@dataclass
class PromptTemplates:
    """
    Collection of prompt templates for the mail agent.

    Each template is a method that returns a formatted prompt string.
    """

    # System prompts
    PARSE_SYSTEM = """You are an assistant that extracts structured information from user requests.
You must extract email addresses, understand what is being requested, and define clear success criteria.
Be specific about success criteria (e.g., "10 rows of data" not just "data").
Always respond with the requested JSON structure."""

    COMPOSE_SYSTEM = """You are an Information Gathering Agent sending emails on behalf of your organization.
Your email address is: {agent_email}

When composing emails:
1. Be professional and polite
2. Clearly state what information/data is needed
3. Specify the expected format (Excel/CSV) if applicable
4. Be concise but complete
5. Include a friendly greeting and professional closing

IMPORTANT EMAIL SIGNATURE RULES:
- End emails with exactly: "Best regards,\\ninfo-agent"
- NEVER use placeholder text like [Your Name], [Your Position], [Your Contact Information], [Your Company]
- The agent's identity is simply "info-agent" - no title, position, or contact details needed
- Do NOT include any bracketed placeholders in your email"""

    VALIDATE_SYSTEM = """You are a validation assistant. Analyze whether a response satisfies the original request.
Be strict: if the request asked for 10 items and only 8 are provided, mark as invalid.

IMPORTANT: Also check if the response is a REDIRECT. A redirect occurs when:
- The responder says they are NOT the correct point of contact
- The responder suggests contacting someone else (e.g., "please contact xyz@abc.com instead")
- The responder forwards the request or says "I've forwarded this to..." with an email address

If a redirect is detected:
- Set is_redirect=true
- Extract the redirect_email (the new contact's email address)
- Provide the redirect_reason (why they are redirecting)

Check for:
1. Is this a REDIRECT to another person? (highest priority check)
2. Correct number of items
3. Correct format/structure
4. Meaningful data (not placeholders)
5. Completeness of information"""

    FOLLOWUP_SYSTEM = """You are an Information Gathering Agent sending follow-up emails.
Your email address is: {agent_email}

When composing follow-up emails:
1. Thank them for their response
2. Politely explain what was missing or incorrect
3. Clearly state what corrections are needed
4. Remain professional and not demanding
5. Be encouraging and helpful

IMPORTANT EMAIL SIGNATURE RULES:
- End emails with exactly: "Best regards,\\ninfo-agent"
- NEVER use placeholder text like [Your Name], [Your Position], [Your Contact Information], [Your Company]
- The agent's identity is simply "info-agent" - no title, position, or contact details needed
- Do NOT include any bracketed placeholders in your email"""

    @staticmethod
    def parse_instruction(user_instruction: str) -> str:
        """
        Create prompt for parsing user instruction.

        Args:
            user_instruction: Raw user input string.

        Returns:
            Formatted prompt string.
        """
        return f"""Extract the following from this instruction:
"{user_instruction}"

Rules:
- Extract all email addresses mentioned
- Infer the type of request from context (data_request, information_request, action_request)
- Be specific about success criteria (e.g., "10 rows of recipes" not just "recipes")
- Determine expected format from context (excel, csv, or text)

Return the structured information as specified."""

    @staticmethod
    def compose_email(
        poc_email: str,
        request_description: str,
        expected_format: str,
        success_criteria: str,
    ) -> str:
        """
        Create prompt for composing initial email.

        Args:
            poc_email: Recipient email address.
            request_description: What is being requested.
            expected_format: Expected response format (excel, csv, text).
            success_criteria: Specific criteria for success.

        Returns:
            Formatted prompt string.
        """
        return f"""Compose an email to request the following:

Recipient: {poc_email}
Request: {request_description}
Expected format: {expected_format}
Success criteria: {success_criteria}

The email should:
1. Be professional and polite
2. Clearly state what is needed
3. Specify the expected format ({expected_format})
4. Mention the specific criteria ({success_criteria})
5. Be concise but complete

Write the email subject and body."""

    @staticmethod
    def validate_response(
        request_description: str,
        success_criteria: str,
        extracted_content: str,
        row_count: int,
        headers: list[str],
        max_content_chars: int = 8000,
        email_body_text: str | None = None,
    ) -> str:
        """
        Create prompt for validating POC response.

        Args:
            request_description: Original request description.
            success_criteria: Original success criteria.
            extracted_content: JSON/text extracted from attachment.
            row_count: Number of rows in the attachment.
            headers: Column headers from the attachment.
            max_content_chars: Maximum characters of content to include in prompt.
            email_body_text: The email body text (for redirect detection).

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

        return f"""Original request: "{request_description}"
Success criteria: "{success_criteria}"
{email_body_section}
Received response content:
- Row count: {row_count}
- Headers/Columns: {', '.join(headers)}
- Data preview:
{extracted_content[:max_content_chars]}{"..." if len(extracted_content) > max_content_chars else ""}

FIRST, check if this is a REDIRECT:
- Does the email body say they are not the correct contact?
- Does it suggest contacting someone else with an email address?
- If YES: Set redirect.is_redirect=true, extract redirect.redirect_email, and provide redirect.redirect_reason

If NOT a redirect, analyze the following:
1. Does the response contain the requested information?
2. Is the data complete (correct number of items as requested)?
3. Is the format correct?
4. Is the quality acceptable (meaningful data, not placeholders)?

Be strict: if the request asked for 10 items and only 8 are provided, mark as INVALID.
Provide detailed feedback on what is correct, missing, or wrong."""

    @staticmethod
    def compose_followup(
        request_description: str,
        validation_feedback: str,
        missing_items: list[str],
        attempt_count: int,
        max_attempts: int,
        original_subject: str,
    ) -> str:
        """
        Create prompt for composing follow-up email.

        Args:
            request_description: Original request description.
            validation_feedback: Feedback from validation.
            missing_items: List of missing or incorrect items.
            attempt_count: Current attempt number.
            max_attempts: Maximum allowed attempts.
            original_subject: Original email subject for Re: prefix.

        Returns:
            Formatted prompt string.
        """
        missing_str = "\n".join(f"- {item}" for item in missing_items) if missing_items else "See feedback above"

        return f"""Original request: "{request_description}"
Previous response issue: "{validation_feedback}"

Missing or incorrect items:
{missing_str}

Attempt number: {attempt_count} of {max_attempts}
Original subject: "{original_subject}"

Compose a follow-up email that:
1. Thanks them for their response
2. Politely explains what was missing or incorrect
3. Clearly states what corrections are needed
4. Remains professional and not demanding

Note: This is attempt {attempt_count} of {max_attempts}.
{"Be slightly more direct as we're running low on attempts." if attempt_count >= max_attempts - 1 else ""}

Write the email subject (should be "Re: {original_subject}") and body."""

    @staticmethod
    def compose_email_for_text_response(
        poc_email: str,
        request_description: str,
    ) -> str:
        """
        Create prompt for composing email requesting text response.

        Args:
            poc_email: Recipient email address.
            request_description: What is being requested.

        Returns:
            Formatted prompt string.
        """
        return f"""Compose an email to request the following:

Recipient: {poc_email}
Request: {request_description}

The email should:
1. Be professional and polite
2. Clearly state what information is needed
3. Request a text response in the email body
4. Be concise but complete

Write the email subject and body."""

    @staticmethod
    def compose_email_for_redirect(
        poc_email: str,
        request_description: str,
        expected_format: str,
        success_criteria: str,
        referrer_email: str,
        redirect_reason: Optional[str] = None,
    ) -> str:
        """
        Create prompt for composing email to a redirected contact.

        This is used when the original POC (referrer_email) has redirected us
        to a new contact (poc_email). The email should mention the referral.

        Args:
            poc_email: Recipient email address (the redirect target).
            request_description: What is being requested.
            expected_format: Expected response format (excel, csv, text).
            success_criteria: Specific criteria for success.
            referrer_email: Email of the person who redirected us.
            redirect_reason: Optional reason given for the redirect.

        Returns:
            Formatted prompt string.
        """
        reason_context = ""
        if redirect_reason:
            reason_context = f" They mentioned: \"{redirect_reason}\"."

        return f"""Compose an email to request the following:

Recipient: {poc_email}
Request: {request_description}
Expected format: {expected_format}
Success criteria: {success_criteria}

IMPORTANT CONTEXT - This is a REDIRECT:
- {referrer_email} has redirected me to you for this request.{reason_context}
- You MUST mention in the opening that {referrer_email} referred you to contact {poc_email}.
- Example opening: "I was referred to you by {referrer_email} regarding the following request..."
- Do NOT ask {poc_email} to forward anything back to {referrer_email}.

The email should:
1. Start by mentioning the referral from {referrer_email}
2. Clearly state what information/data is needed
3. Specify the expected format ({expected_format})
4. Mention the specific criteria ({success_criteria})
5. Be concise but complete

Write the email subject and body."""
