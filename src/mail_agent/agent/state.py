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
class RedirectInfo:
    """Information about a redirect from one POC to another."""

    original_poc: str
    redirect_email: str
    redirect_reason: Optional[str] = None
    redirected_at: Optional[datetime] = None


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
        "redirected",
    ] = "pending"
    attempt_count: int = 0
    sent_emails: list[SentEmail] = field(default_factory=list)
    received_emails: list[ReceivedEmail] = field(default_factory=list)
    validation_results: list[ValidationResult] = field(default_factory=list)
    final_result: Optional[Literal["success", "failed_max_attempts", "redirected"]] = None
    error_message: Optional[str] = None
    # Redirect tracking
    redirected_from: Optional[RedirectInfo] = None  # If this conversation was created from a redirect
    redirected_to: Optional[str] = None  # Email of POC we redirected to (if any)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = {
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
            "redirected_to": self.redirected_to,
        }
        # Add redirect info if present
        if self.redirected_from:
            result["redirected_from"] = {
                "original_poc": self.redirected_from.original_poc,
                "redirect_email": self.redirected_from.redirect_email,
                "redirect_reason": self.redirected_from.redirect_reason,
                "redirected_at": (
                    self.redirected_from.redirected_at.isoformat()
                    if self.redirected_from.redirected_at
                    else None
                ),
            }
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ConversationState":
        """Create from dictionary."""
        # Parse redirect info if present
        redirected_from = None
        if data.get("redirected_from"):
            rf = data["redirected_from"]
            redirected_from = RedirectInfo(
                original_poc=rf["original_poc"],
                redirect_email=rf["redirect_email"],
                redirect_reason=rf.get("redirect_reason"),
                redirected_at=(
                    datetime.fromisoformat(rf["redirected_at"])
                    if rf.get("redirected_at")
                    else None
                ),
            )

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
            redirected_from=redirected_from,
            redirected_to=data.get("redirected_to"),
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

    # A2A task identifier (set when running in A2A mode)
    task_id: Optional[str]

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

    # Temporary: fetch_email -> extract_content
    _fetched_email_id: Optional[str]
    _fetched_attachments: Optional[list[dict[str, Any]]]
    _fetched_body_text: Optional[str]

    # Temporary: extract_content -> validate_response
    _extracted_content: Optional[str]
    _extracted_headers: Optional[list[str]]
    _extracted_row_count: Optional[int]

    # Temporary: validate_response -> decide_next
    _validation_is_valid: Optional[bool]
    _validation_feedback: Optional[str]
    _validation_missing_items: Optional[list[str]]

    # Temporary: redirect detection from validate_response
    _redirect_detected: Optional[bool]
    _redirect_email: Optional[str]
    _redirect_reason: Optional[str]


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
        True if all conversations are in success, failed, or redirected state.
    """
    conversations = state.get("conversations", {})
    if not conversations:
        return False

    for conv_dict in conversations.values():
        status = conv_dict.get("status")
        # redirected is terminal for the original POC, but a new conversation is created
        if status not in ("success", "failed", "redirected"):
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
        if status not in ("success", "failed", "redirected"):
            return poc_email

    return None


def get_related_conversations(
    state: AgentState,
    poc_email: str
) -> list[ConversationState]:
    """
    Get all conversations related to a POC through redirects.

    This traces back through redirect chains to find all conversations
    that contributed to the current request (e.g., if A redirected to B,
    and B redirected to C, get all three conversations when processing C).

    Args:
        state: Current agent state.
        poc_email: The POC email to find related conversations for.

    Returns:
        List of ConversationState objects in chronological order (oldest first).
    """
    conversations = state.get("conversations", {})
    related = []
    visited = set()

    # First, trace back to find the original conversation (follow redirected_from chain)
    current_email = poc_email
    chain = []

    while current_email and current_email not in visited:
        visited.add(current_email)
        conv_dict = conversations.get(current_email)
        if not conv_dict:
            break

        conv = ConversationState.from_dict(conv_dict)
        chain.append(conv)

        # Check if this conversation was created from a redirect
        if conv.redirected_from:
            current_email = conv.redirected_from.original_poc
        else:
            break

    # Reverse to get chronological order (original first)
    related = list(reversed(chain))

    return related


def build_conversation_thread_context(
    state: AgentState,
    poc_email: str,
    include_current: bool = True,
) -> str:
    """
    Build a formatted context string summarizing all related conversations.

    This creates a text summary of all emails sent and received in the
    conversation chain, including any partial results received from
    previous contacts who redirected.

    Args:
        state: Current agent state.
        poc_email: The current POC email.
        include_current: Whether to include the current POC's conversation.

    Returns:
        Formatted string with conversation history.
    """
    related = get_related_conversations(state, poc_email)

    if not related:
        return ""

    # If not including current, remove the last one (which is the current POC)
    if not include_current and related:
        # Find and remove the current POC's conversation
        related = [c for c in related if c.poc_email != poc_email]

    if not related:
        return ""

    context_parts = []
    context_parts.append("=== CONVERSATION HISTORY ===")

    for conv in related:
        context_parts.append(f"\n--- Conversation with {conv.poc_email} ---")
        context_parts.append(f"Status: {conv.status}")

        # Include sent emails
        for i, sent in enumerate(conv.sent_emails, 1):
            context_parts.append(f"\n[SENT EMAIL #{i} to {conv.poc_email}]")
            context_parts.append(f"Subject: {sent.subject}")
            context_parts.append(f"Body:\n{sent.body[:1000]}{'...' if len(sent.body) > 1000 else ''}")

        # Include received emails with their content
        for i, received in enumerate(conv.received_emails, 1):
            context_parts.append(f"\n[RECEIVED EMAIL #{i} from {conv.poc_email}]")
            context_parts.append(f"Subject: {received.subject}")
            if received.body_text:
                body_preview = received.body_text[:1000]
                context_parts.append(f"Body:\n{body_preview}{'...' if len(received.body_text) > 1000 else ''}")
            if received.attachment_content:
                # Include attachment content (this is where partial data would be)
                content_preview = received.attachment_content[:3000]
                context_parts.append(f"Attachment content:\n{content_preview}{'...' if len(received.attachment_content) > 3000 else ''}")

        # Include validation results
        for i, validation in enumerate(conv.validation_results, 1):
            context_parts.append(f"\n[VALIDATION #{i}]")
            context_parts.append(f"Valid: {validation.is_valid}")
            context_parts.append(f"Feedback: {validation.feedback}")
            if validation.missing_items:
                context_parts.append(f"Missing items: {', '.join(validation.missing_items)}")

        # Note if this conversation redirected
        if conv.redirected_to:
            context_parts.append(f"\n[REDIRECTED to {conv.redirected_to}]")

    context_parts.append("\n=== END CONVERSATION HISTORY ===")

    return "\n".join(context_parts)


def get_received_items_summary(state: AgentState, poc_email: str) -> dict:
    """
    Calculate what has already been received from related conversations.

    This is used to adjust the request when contacting a redirected POC,
    so we ask only for the remaining items needed.

    Args:
        state: Current agent state.
        poc_email: The current POC email (typically a redirect target).

    Returns:
        Dictionary with:
        - total_items_received: Number of items already received
        - items_summary: Text summary of what was received
        - sources: List of POCs who provided items
    """
    related = get_related_conversations(state, poc_email)

    # Exclude the current POC (we want items from others)
    previous_convs = [c for c in related if c.poc_email != poc_email]

    result = {
        "total_items_received": 0,
        "items_summary": "",
        "sources": [],
    }

    summaries = []

    for conv in previous_convs:
        # Check validation results for item counts
        for validation in conv.validation_results:
            if validation.feedback:
                summaries.append(f"From {conv.poc_email}: {validation.feedback}")
                if conv.poc_email not in result["sources"]:
                    result["sources"].append(conv.poc_email)

        # Check received emails for content
        for received in conv.received_emails:
            if received.attachment_content:
                # Track this source
                if conv.poc_email not in result["sources"]:
                    result["sources"].append(conv.poc_email)

                # Try to count items in the attachment
                content = received.attachment_content
                # Simple heuristic: count data rows (lines that look like data)
                try:
                    import json
                    data = json.loads(content)
                    if isinstance(data, list):
                        result["total_items_received"] += len(data)
                        summaries.append(
                            f"From {conv.poc_email}: {len(data)} items in attachment"
                        )
                except (json.JSONDecodeError, TypeError):
                    # If not JSON, try counting lines (excluding empty/header lines)
                    lines = [l for l in content.strip().split('\n') if l.strip()]
                    if lines:
                        # Rough estimate: assume first line is header
                        item_count = max(0, len(lines) - 1)
                        result["total_items_received"] += item_count
                        if item_count > 0:
                            summaries.append(
                                f"From {conv.poc_email}: {item_count} items in attachment"
                            )

    result["items_summary"] = "; ".join(summaries) if summaries else ""

    return result
