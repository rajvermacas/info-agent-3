"""Prompt templates for Mail Agent LLM interactions."""

import json
from typing import Any


class PromptTemplates:
    """Collection of prompt templates for agent nodes."""

    @staticmethod
    def parse_instruction(user_instruction: str) -> str:
        """Generate prompt for parsing user instruction.

        Args:
            user_instruction: Raw user input

        Returns:
            str: Formatted prompt for LLM
        """
        return f"""You are an assistant that extracts structured information from user requests for sending emails.

Extract the following from this instruction:
"{user_instruction}"

Return ONLY a valid JSON object with this exact structure (no markdown, no code blocks):
{{
  "poc_emails": ["email1@example.com", "email2@example.com"],
  "request_type": "data_request|information_request|action_request",
  "request_description": "brief description of what is being requested",
  "success_criteria": "specific criteria to validate the response"
}}

Rules:
- Extract ALL email addresses mentioned in the instruction
- Infer the type of request from context
- Be specific about success criteria (e.g., "10 rows of recipe data in Excel format" not just "recipes")
- If expecting a file, specify the format in success_criteria
- If expecting a specific count, include the number in success_criteria

Return ONLY the JSON object, nothing else."""

    @staticmethod
    def compose_email(poc_email: str, request_description: str, expected_format: str = "Excel or CSV") -> str:
        """Generate prompt for composing email.

        Args:
            poc_email: Recipient email address
            request_description: What is being requested
            expected_format: Expected file format

        Returns:
            str: Formatted prompt for LLM
        """
        return f"""You are a professional email composer. Write a clear, polite, and concise email.

Compose an email to request the following:
- Recipient: {poc_email}
- Request: {request_description}
- Expected format: {expected_format}

The email should:
1. Be professional and polite
2. Clearly state what is needed
3. Specify the expected format ({expected_format})
4. Be concise but complete
5. Use a friendly but professional tone

Return ONLY a valid JSON object with this exact structure (no markdown, no code blocks):
{{
  "subject": "email subject line",
  "body": "full email body text"
}}

Return ONLY the JSON object, nothing else."""

    @staticmethod
    def validate_response(
        request_description: str,
        success_criteria: str,
        extracted_content: str
    ) -> str:
        """Generate prompt for validating response.

        Args:
            request_description: Original request description
            success_criteria: Success criteria to check against
            extracted_content: Extracted content from attachment (JSON or text)

        Returns:
            str: Formatted prompt for LLM
        """
        # Truncate extracted content if too long (keep first 5000 chars)
        truncated_content = extracted_content[:5000]
        if len(extracted_content) > 5000:
            truncated_content += "\n... (content truncated for analysis)"

        return f"""You are a validation assistant. Analyze whether a response satisfies the original request.

Original request: "{request_description}"
Success criteria: "{success_criteria}"

Received response content:
{truncated_content}

Analyze the following:
1. Does the response contain the requested information?
2. Is the data complete (correct number of items as requested)?
3. Is the format correct?
4. Is the quality acceptable (meaningful data, not placeholders or dummy data)?

Return ONLY a valid JSON object with this exact structure (no markdown, no code blocks):
{{
  "is_valid": true or false,
  "feedback": "detailed explanation of what is correct/missing/wrong"
}}

Be strict: if the request asked for 10 items and only 8 are provided, mark as invalid.
If data is placeholder or dummy data, mark as invalid.

Return ONLY the JSON object, nothing else."""

    @staticmethod
    def compose_followup(
        request_description: str,
        validation_feedback: str,
        attempt_count: int,
        max_attempts: int
    ) -> str:
        """Generate prompt for composing follow-up email.

        Args:
            request_description: Original request description
            validation_feedback: Feedback from validation
            attempt_count: Current attempt number
            max_attempts: Maximum attempts allowed

        Returns:
            str: Formatted prompt for LLM
        """
        return f"""You are a professional email composer. Write a polite follow-up email requesting corrections.

Original request: "{request_description}"
Previous response issue: "{validation_feedback}"
Attempt number: {attempt_count} of {max_attempts}

Compose a follow-up email that:
1. Thanks them for their response
2. Politely explains what was missing or incorrect
3. Clearly states what corrections are needed
4. Remains professional and not demanding
5. Is encouraging and appreciative

Return ONLY a valid JSON object with this exact structure (no markdown, no code blocks):
{{
  "subject": "Re: [previous subject]",
  "body": "follow-up email body text"
}}

Return ONLY the JSON object, nothing else."""

    @staticmethod
    def parse_llm_json_response(response_text: str) -> dict[str, Any]:
        """Parse JSON response from LLM, handling markdown code blocks.

        Args:
            response_text: Raw LLM response text

        Returns:
            dict: Parsed JSON object

        Raises:
            json.JSONDecodeError: If response is not valid JSON
            ValueError: If response is empty or invalid format
        """
        if not response_text or not response_text.strip():
            raise ValueError("LLM response is empty")

        text = response_text.strip()

        # Remove markdown code blocks if present
        if text.startswith("```json"):
            text = text[7:]  # Remove ```json
        elif text.startswith("```"):
            text = text[3:]  # Remove ```

        if text.endswith("```"):
            text = text[:-3]  # Remove trailing ```

        text = text.strip()

        # Parse JSON
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise json.JSONDecodeError(
                f"Failed to parse LLM response as JSON: {str(e)}\nResponse: {text}",
                e.doc,
                e.pos
            )
