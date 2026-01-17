"""
Clarification schemas and prompts.

Used when a POC replies with a question instead of providing the requested data.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class ClarificationDetection(BaseModel):
    """Detect whether a POC reply is a clarification question."""

    is_clarification_question: bool = Field(
        description="True if the email is asking questions/clarifications about the request (not providing the data)"
    )
    question: Optional[str] = Field(
        default=None,
        description="The clarification question asked by the POC, extracted as a short summary",
    )


class ClarificationReply(BaseModel):
    """Body for an email reply answering the POC clarification question."""

    body: str = Field(description="Email body text answering the question and restating what to provide")


class ClarificationPrompts:
    DETECT_SYSTEM = """You are a strict email reply classifier.
Determine whether the sender is asking a clarification question about the request.

Rules:
- If the sender asks what to send, format, columns, counts, constraints, or timing, mark is_clarification_question=true.
- If the sender provides the requested data, mark false.
- If the sender redirects to another email, mark false (redirect handling is separate).
- Return ONLY valid JSON for the requested schema."""

    REPLY_SYSTEM = """You are an Information Gathering Agent replying to a point-of-contact who asked a clarification question.
Answer clearly and concisely using the user's original request context.

IMPORTANT EMAIL SIGNATURE RULES:
- End emails with exactly: "Best regards,\\ninfo-agent"
- Do NOT include placeholders or extra contact details.

Return ONLY valid JSON for the requested schema."""

    @staticmethod
    def detect(email_body_text: str) -> str:
        return f"""POC reply email body:
\"\"\"{email_body_text}\"\"\"

Task: Decide if this is a clarification question. If yes, extract the question succinctly."""

    @staticmethod
    def reply(
        user_instruction: str,
        request_description: str,
        expected_format: str,
        success_criteria: str,
        question: str,
    ) -> str:
        return f"""User request:
\"\"\"{user_instruction}\"\"\"

What we asked this POC for:
- Request: {request_description}
- Expected format: {expected_format}
- Success criteria: {success_criteria}

POC question:
\"\"\"{question}\"\"\"

Write an email body that answers the question and tells them exactly what to send next."""

