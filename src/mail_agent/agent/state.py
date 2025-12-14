"""Agent state schema for LangGraph."""

from datetime import datetime
from typing import Any, Optional, TypedDict


class ParsedRequest(TypedDict, total=False):
    """Parsed user request structure."""

    poc_emails: list[str]  # POC email addresses
    request_type: str  # "data_request", "information_request", "action_request"
    request_description: str  # Brief description
    success_criteria: str  # Specific validation criteria


class SentEmail(TypedDict, total=False):
    """Sent email metadata."""

    email_id: str  # Email UUID
    subject: str  # Email subject
    body: str  # Email body
    sent_at: str  # ISO timestamp


class ReceivedEmail(TypedDict, total=False):
    """Received email metadata."""

    email_id: str  # Email UUID
    from_address: str  # Sender
    subject: str  # Email subject
    received_at: str  # ISO timestamp
    has_attachment: bool  # Has attachments?
    attachment_content: Optional[str]  # Extracted content (JSON/text)


class ValidationResult(TypedDict, total=False):
    """LLM validation result."""

    attempt: int  # Attempt number
    is_valid: bool  # Validation passed?
    feedback: str  # LLM explanation


class ConversationState(TypedDict, total=False):
    """Per-POC conversation state."""

    status: str  # "pending", "waiting", "validating", "success", "failed"
    attempt_count: int  # Current attempt (0-5)
    sent_emails: list[SentEmail]  # All sent emails
    received_emails: list[ReceivedEmail]  # All received emails
    validation_results: list[ValidationResult]  # All validation results
    final_result: Optional[str]  # "success" or "failed_max_attempts"
    error: Optional[str]  # Error message if failed


class AgentState(TypedDict, total=False):
    """Main agent state for LangGraph.

    This state is maintained across all nodes and persisted via checkpointer.
    """

    # Original request
    user_instruction: str  # Raw user input

    # Parsed request
    parsed_request: Optional[ParsedRequest]  # Extracted structure

    # Per-POC conversation state (keyed by POC email)
    conversations: dict[str, ConversationState]

    # Current processing
    current_node: str  # Current node name (for debugging)
    pending_webhooks: list[dict[str, Any]]  # Webhook payloads to process

    # Output
    progress_messages: list[str]  # Real-time status updates
    final_summary: Optional[str]  # End result summary

    # Metadata
    started_at: str  # ISO timestamp
    completed_at: Optional[str]  # ISO timestamp
