"""
Agent State - TypedDict state schema for LangGraph.

Defines the complete state structure for the mail agent state machine.
"""

import operator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated, Any, Literal, Optional
from typing_extensions import TypedDict
from uuid import UUID


# ============================================================================
# Conversation State (per POC)
# ============================================================================


@dataclass
class SentEmail:
    """Record of an email sent to a POC."""

    email_id: UUID
    subject: str
    body: str
    sent_at: datetime


@dataclass
class ReceivedEmail:
    """Record of an email received from a POC."""

    email_id: UUID
    from_address: str
    subject: str
    received_at: datetime
    has_attachment: bool
    attachment_content: Optional[str] = None  # Extracted JSON/text
    attachment_filename: Optional[str] = None
    body_text: Optional[str] = None


@dataclass
class ValidationResult:
    """Result of validating a POC response."""

    attempt: int
    is_valid: bool
    feedback: str
    missing_items: list[str] = field(default_factory=list)


@dataclass
class ConversationState:
    """
    State of conversation with a single POC.

    Tracks all sent/received emails, validation results, and current status.
    """

    poc_email: str
    status: Literal[
        "pending",
        "composing",
        "sending",
        "waiting",
        "fetching",
        "extracting",
        "validating",
        "success",
        "failed",
    ] = "pending"
    attempt_count: int = 0
    sent_emails: list[SentEmail] = field(default_factory=list)
    received_emails: list[ReceivedEmail] = field(default_factory=list)
    validation_results: list[ValidationResult] = field(default_factory=list)
    final_result: Optional[Literal["success", "failed_max_attempts"]] = None
    error_message: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "poc_email": self.poc_email,
            "status": self.status,
            "attempt_count": self.attempt_count,
            "sent_emails": [
                {
                    "email_id": str(e.email_id),
                    "subject": e.subject,
                    "body": e.body,
                    "sent_at": e.sent_at.isoformat(),
                }
                for e in self.sent_emails
            ],
            "received_emails": [
                {
                    "email_id": str(e.email_id),
                    "from_address": e.from_address,
                    "subject": e.subject,
                    "received_at": e.received_at.isoformat(),
                    "has_attachment": e.has_attachment,
                    "attachment_content": e.attachment_content,
                    "attachment_filename": e.attachment_filename,
                    "body_text": e.body_text,
                }
                for e in self.received_emails
            ],
            "validation_results": [
                {
                    "attempt": v.attempt,
                    "is_valid": v.is_valid,
                    "feedback": v.feedback,
                    "missing_items": v.missing_items,
                }
                for v in self.validation_results
            ],
            "final_result": self.final_result,
            "error_message": self.error_message,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ConversationState":
        """Create from dictionary."""
        return cls(
            poc_email=data["poc_email"],
            status=data["status"],
            attempt_count=data["attempt_count"],
            sent_emails=[
                SentEmail(
                    email_id=UUID(e["email_id"]),
                    subject=e["subject"],
                    body=e["body"],
                    sent_at=datetime.fromisoformat(e["sent_at"]),
                )
                for e in data.get("sent_emails", [])
            ],
            received_emails=[
                ReceivedEmail(
                    email_id=UUID(e["email_id"]),
                    from_address=e["from_address"],
                    subject=e["subject"],
                    received_at=datetime.fromisoformat(e["received_at"]),
                    has_attachment=e["has_attachment"],
                    attachment_content=e.get("attachment_content"),
                    attachment_filename=e.get("attachment_filename"),
                    body_text=e.get("body_text"),
                )
                for e in data.get("received_emails", [])
            ],
            validation_results=[
                ValidationResult(
                    attempt=v["attempt"],
                    is_valid=v["is_valid"],
                    feedback=v["feedback"],
                    missing_items=v.get("missing_items", []),
                )
                for v in data.get("validation_results", [])
            ],
            final_result=data.get("final_result"),
            error_message=data.get("error_message"),
        )


# ============================================================================
# Parsed Request
# ============================================================================


@dataclass
class ParsedRequest:
    """Parsed user instruction."""

    poc_emails: list[str]
    request_type: str  # data_request, information_request, action_request
    request_description: str
    success_criteria: str
    expected_format: str  # excel, csv, text

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "poc_emails": self.poc_emails,
            "request_type": self.request_type,
            "request_description": self.request_description,
            "success_criteria": self.success_criteria,
            "expected_format": self.expected_format,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ParsedRequest":
        """Create from dictionary."""
        return cls(
            poc_emails=data["poc_emails"],
            request_type=data["request_type"],
            request_description=data["request_description"],
            success_criteria=data["success_criteria"],
            expected_format=data["expected_format"],
        )


# ============================================================================
# Main Agent State (TypedDict for LangGraph)
# ============================================================================


class AgentState(TypedDict, total=False):
    """
    Complete state for the mail agent LangGraph.

    Uses TypedDict for LangGraph compatibility. Some fields use Annotated
    with operator.add for list reduction (appending instead of replacing).
    """

    # Original request
    user_instruction: str

    # Parsed request (set by parse_instruction node)
    parsed_request: Optional[dict[str, Any]]

    # Per-POC conversation state
    # Key: POC email address, Value: ConversationState as dict
    conversations: dict[str, dict[str, Any]]

    # Current processing context
    current_node: str
    current_poc: Optional[str]  # POC being processed

    # Pending webhook events (email IDs)
    pending_webhooks: Annotated[list[str], operator.add]

    # Progress messages for CLI output
    progress_messages: Annotated[list[str], operator.add]

    # Final summary
    final_summary: Optional[str]

    # Error tracking
    error: Optional[str]

    # Webhook registration
    webhook_id: Optional[str]

    # Temporary composed email data (passed between compose_email and send_email)
    _composed_subject: Optional[str]
    _composed_body: Optional[str]


# ============================================================================
# State Helper Functions
# ============================================================================


def create_initial_state(user_instruction: str) -> AgentState:
    """
    Create initial agent state from user instruction.

    Args:
        user_instruction: Raw user input string.

    Returns:
        Initial AgentState dictionary.
    """
    return AgentState(
        user_instruction=user_instruction,
        parsed_request=None,
        conversations={},
        current_node="start",
        current_poc=None,
        pending_webhooks=[],
        progress_messages=[f"Starting mail agent with instruction: {user_instruction}"],
        final_summary=None,
        error=None,
        webhook_id=None,
        _composed_subject=None,
        _composed_body=None,
    )


def get_conversation(state: AgentState, poc_email: str) -> ConversationState:
    """
    Get ConversationState for a POC from state.

    Args:
        state: Current agent state.
        poc_email: POC email address.

    Returns:
        ConversationState object.

    Raises:
        KeyError: If POC not found in state.
    """
    conv_dict = state["conversations"].get(poc_email)
    if conv_dict is None:
        raise KeyError(f"No conversation found for POC: {poc_email}")
    return ConversationState.from_dict(conv_dict)


def update_conversation(
    state: AgentState,
    poc_email: str,
    conversation: ConversationState,
) -> dict[str, dict[str, Any]]:
    """
    Create updated conversations dict with modified conversation.

    Args:
        state: Current agent state.
        poc_email: POC email address.
        conversation: Updated ConversationState.

    Returns:
        New conversations dictionary (for state update).
    """
    conversations = dict(state.get("conversations", {}))
    conversations[poc_email] = conversation.to_dict()
    return conversations


def get_parsed_request(state: AgentState) -> ParsedRequest:
    """
    Get ParsedRequest from state.

    Args:
        state: Current agent state.

    Returns:
        ParsedRequest object.

    Raises:
        ValueError: If parsed_request is not set.
    """
    parsed_dict = state.get("parsed_request")
    if parsed_dict is None:
        raise ValueError("parsed_request is not set in state")
    return ParsedRequest.from_dict(parsed_dict)


def all_conversations_complete(state: AgentState) -> bool:
    """
    Check if all POC conversations have reached terminal state.

    Args:
        state: Current agent state.

    Returns:
        True if all conversations are in success or failed state.
    """
    conversations = state.get("conversations", {})
    if not conversations:
        return False

    for conv_dict in conversations.values():
        status = conv_dict.get("status")
        if status not in ("success", "failed"):
            return False

    return True


def get_active_poc(state: AgentState) -> Optional[str]:
    """
    Get the first POC that needs processing.

    Args:
        state: Current agent state.

    Returns:
        POC email address or None if all complete.
    """
    conversations = state.get("conversations", {})

    for poc_email, conv_dict in conversations.items():
        status = conv_dict.get("status")
        if status not in ("success", "failed"):
            return poc_email

    return None
