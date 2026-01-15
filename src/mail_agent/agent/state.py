"""
Agent State - TypedDict state schema for LangGraph.

Defines the complete state structure for the mail agent state machine,
including support for Multi-POC orchestration with DAG-based execution.
"""

import operator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated, Any, Literal, Optional
from typing_extensions import TypedDict
from uuid import UUID

# Re-export multi-POC models for backward compatibility
from mail_agent.agent.multi_poc_state import (  # noqa: F401
    DataConflict,
    DynamicPOCConfig,
    GlobalValidationResult,
    OrchestrationAction,
    OrchestrationDecision,
    POCExecutionPlan,
    POCRequirement,
    POCState,
    POCStatus,
    POCValidationResult,
)

# Re-export multi-POC helper functions
from mail_agent.agent.multi_poc_helpers import (  # noqa: F401
    add_poc_to_plan,
    all_pocs_terminal,
    create_initial_multi_poc_state,
    get_all_poc_states,
    get_execution_plan,
    get_poc_progress_summary,
    get_poc_requirement,
    get_poc_state,
    get_ready_pocs,
    get_waiting_pocs,
    update_poc_state,
)

# Expose all models through __all__
__all__ = [
    # Legacy single-POC models
    "SentEmail",
    "ReceivedEmail",
    "ValidationResult",
    "RedirectInfo",
    "ConversationState",
    "ParsedRequest",
    "AgentState",
    # Legacy helpers
    "create_initial_state",
    "get_conversation",
    "update_conversation",
    "get_parsed_request",
    "all_conversations_complete",
    "get_active_poc",
    # Multi-POC models (re-exported)
    "POCStatus",
    "OrchestrationAction",
    "DynamicPOCConfig",
    "POCRequirement",
    "POCValidationResult",
    "POCState",
    "POCExecutionPlan",
    "DataConflict",
    "GlobalValidationResult",
    "OrchestrationDecision",
    # Multi-POC helpers
    "create_initial_multi_poc_state",
    "get_execution_plan",
    "get_poc_state",
    "update_poc_state",
    "get_poc_requirement",
    "get_all_poc_states",
    "all_pocs_terminal",
    "get_ready_pocs",
    "get_waiting_pocs",
    "get_poc_progress_summary",
    "add_poc_to_plan",
]


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

    This state supports both single-POC (legacy) and multi-POC orchestration:
    - Single POC: Uses conversations, current_poc, parsed_request
    - Multi-POC: Uses execution_plan, poc_states, current_poc_id, aggregated_data
    """

    # =========================================================================
    # Original Request
    # =========================================================================
    user_instruction: str

    # =========================================================================
    # Single-POC Mode Fields (Legacy - for backward compatibility)
    # =========================================================================

    # Parsed request (set by parse_instruction node - legacy single-POC)
    parsed_request: Optional[dict[str, Any]]

    # Per-POC conversation state (legacy)
    # Key: POC email address, Value: ConversationState as dict
    conversations: dict[str, dict[str, Any]]

    # Current POC being processed (legacy single-POC mode)
    current_poc: Optional[str]

    # =========================================================================
    # Multi-POC Orchestration Fields (New)
    # =========================================================================

    # Execution plan with all POC requirements and dependency graph
    execution_plan: Optional[dict[str, Any]]  # POCExecutionPlan as dict

    # Per-POC execution state
    # Key: poc_id, Value: POCState as dict
    poc_states: dict[str, dict[str, Any]]

    # Current POC ID being processed in multi-POC mode
    current_poc_id: Optional[str]

    # Aggregated data from all POCs (Phase 3: Aggregation)
    aggregated_data: dict[str, Any]

    # Detected conflicts between POC responses
    conflicts: list[dict[str, Any]]  # List of DataConflict as dict

    # Global validation result
    global_validation_result: Optional[dict[str, Any]]  # GlobalValidationResult as dict

    # Current orchestration phase
    orchestration_phase: Optional[str]  # planning, execution, aggregation, completion

    # Orchestration decision for routing (set by orchestrate_pocs node)
    orchestration_decision: Optional[dict[str, Any]]  # OrchestrationDecision as dict

    # =========================================================================
    # Common Fields (Both Modes)
    # =========================================================================

    # Current node in graph execution
    current_node: str

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

    # =========================================================================
    # Temporary Fields (Passed between nodes, prefixed with _)
    # =========================================================================

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
    Get the first POC that needs processing (legacy single-POC mode).

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
