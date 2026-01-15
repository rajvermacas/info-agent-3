"""
Multi-POC Orchestration State Models.

Defines state structures for DAG-based multi-POC orchestration,
enabling parallel/sequential POC execution with dependency management.

This module provides:
- POCStatus: Execution status enum for POCs
- POCRequirement: What is required from each POC
- POCState: Runtime state for each POC
- POCExecutionPlan: Complete execution plan with dependency graph
- POCValidationResult: Per-POC validation result
- DataConflict: Conflict detection between POC responses
- GlobalValidationResult: Final aggregated validation
- OrchestrationDecision: DAG scheduler decisions
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


# ============================================================================
# Multi-POC Status Enums
# ============================================================================


class POCStatus(str, Enum):
    """
    Status enum for POC execution in multi-POC orchestration.

    Tracks the lifecycle of each POC from pending through completion or failure.
    """
    PENDING = "pending"           # Not yet started
    IN_PROGRESS = "in_progress"   # Currently executing (composing/sending)
    WAITING = "waiting"           # Waiting for email reply
    COMPLETED = "completed"       # Successfully completed
    FAILED = "failed"             # Failed after max retries


class OrchestrationAction(str, Enum):
    """
    Actions that the DAG scheduler (orchestrate_pocs) can return.

    Determines the next step in multi-POC execution.
    """
    EXECUTE = "execute"           # Execute ready POCs
    WAIT = "wait"                 # Wait for POC replies (INTERRUPT)
    AGGREGATE = "aggregate"       # All POCs done, aggregate responses
    FAIL = "fail"                 # Fatal error, cannot continue


# ============================================================================
# Dynamic POC Spawning Configuration
# ============================================================================


@dataclass
class DynamicPOCConfig:
    """
    Configuration for dynamic POC spawning from response data.

    When enabled, the agent can extract email addresses from a POC's response
    and automatically spawn new POC flows for each discovered email.

    Example: A POC returns a vendor list, and we spawn POCs for each vendor.
    """
    enabled: bool = False
    email_source_field: Optional[str] = None  # Field in response containing emails
    request_template: Optional[str] = None    # Template for new POC request
    success_criteria_template: Optional[str] = None  # Template for success criteria

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "enabled": self.enabled,
            "email_source_field": self.email_source_field,
            "request_template": self.request_template,
            "success_criteria_template": self.success_criteria_template,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DynamicPOCConfig":
        """Create from dictionary."""
        return cls(
            enabled=data.get("enabled", False),
            email_source_field=data.get("email_source_field"),
            request_template=data.get("request_template"),
            success_criteria_template=data.get("success_criteria_template"),
        )


# ============================================================================
# POC Requirement Definition
# ============================================================================


@dataclass
class POCRequirement:
    """
    Defines what is required from a single POC in multi-POC orchestration.

    Each POC has:
    - Unique ID and email address
    - Specific request and success criteria
    - Dependencies on other POCs (for sequential execution)
    - Optional configuration to spawn new POCs from response
    - Context data injected from completed dependencies
    """
    id: str                                    # Unique identifier (e.g., "poc_raj")
    email: str                                 # POC email address
    request: str                               # What to request from this POC
    success_criteria: str                      # Per-POC validation criteria
    dependencies: list[str] = field(default_factory=list)  # POC IDs this depends on
    execution_order: int = 1                   # For parallel grouping (1, 2, 3...)
    spawns_dynamic_pocs: Optional[DynamicPOCConfig] = None
    context_from_deps: dict[str, Any] = field(default_factory=dict)  # Injected data

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "email": self.email,
            "request": self.request,
            "success_criteria": self.success_criteria,
            "dependencies": self.dependencies,
            "execution_order": self.execution_order,
            "spawns_dynamic_pocs": (
                self.spawns_dynamic_pocs.to_dict()
                if self.spawns_dynamic_pocs
                else None
            ),
            "context_from_deps": self.context_from_deps,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "POCRequirement":
        """Create from dictionary."""
        spawns_config = None
        if data.get("spawns_dynamic_pocs"):
            spawns_config = DynamicPOCConfig.from_dict(data["spawns_dynamic_pocs"])

        return cls(
            id=data["id"],
            email=data["email"],
            request=data["request"],
            success_criteria=data["success_criteria"],
            dependencies=data.get("dependencies", []),
            execution_order=data.get("execution_order", 1),
            spawns_dynamic_pocs=spawns_config,
            context_from_deps=data.get("context_from_deps", {}),
        )


# ============================================================================
# Per-POC Validation Result
# ============================================================================


@dataclass
class POCValidationResult:
    """
    Result of validating a single POC's response against its success criteria.

    Used by validate_poc_response node to determine next action:
    - valid=True → proceed to spawn dynamic POCs or mark complete
    - should_retry=True → compose follow-up email
    - should_redirect=True → create new POC for redirect target
    """
    valid: bool
    criteria_met: list[str] = field(default_factory=list)      # Satisfied criteria
    criteria_missing: list[str] = field(default_factory=list)  # Unsatisfied criteria
    should_retry: bool = False
    should_redirect: bool = False
    redirect_email: Optional[str] = None
    reasoning: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "valid": self.valid,
            "criteria_met": self.criteria_met,
            "criteria_missing": self.criteria_missing,
            "should_retry": self.should_retry,
            "should_redirect": self.should_redirect,
            "redirect_email": self.redirect_email,
            "reasoning": self.reasoning,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "POCValidationResult":
        """Create from dictionary."""
        return cls(
            valid=data["valid"],
            criteria_met=data.get("criteria_met", []),
            criteria_missing=data.get("criteria_missing", []),
            should_retry=data.get("should_retry", False),
            should_redirect=data.get("should_redirect", False),
            redirect_email=data.get("redirect_email"),
            reasoning=data.get("reasoning", ""),
        )


# ============================================================================
# POC Runtime State
# ============================================================================


@dataclass
class POCState:
    """
    Complete state for a single POC in multi-POC orchestration.

    Tracks:
    - Execution status and attempt count
    - Conversation history (reuses existing ConversationState)
    - Extracted data from responses
    - Validation results
    - Redirect chain history
    - Webhook registration for reply notification
    """
    poc_id: str
    status: POCStatus = POCStatus.PENDING
    attempts: int = 0
    max_attempts: int = 15  # Per-POC retry limit

    # Conversation data (embedded ConversationState as dict)
    conversation: Optional[dict[str, Any]] = None

    # Data extracted from POC's response
    extracted_data: dict[str, Any] = field(default_factory=dict)

    # Per-POC validation result
    validation_result: Optional[POCValidationResult] = None

    # Email tracking
    original_email: str = ""
    redirect_chain: list[str] = field(default_factory=list)  # Redirect history

    # Webhook for reply notification
    webhook_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "poc_id": self.poc_id,
            "status": self.status.value if isinstance(self.status, POCStatus) else self.status,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "conversation": self.conversation,
            "extracted_data": self.extracted_data,
            "validation_result": (
                self.validation_result.to_dict()
                if self.validation_result
                else None
            ),
            "original_email": self.original_email,
            "redirect_chain": self.redirect_chain,
            "webhook_id": self.webhook_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "POCState":
        """Create from dictionary."""
        # Parse status - handle both string and enum
        status_val = data.get("status", "pending")
        if isinstance(status_val, str):
            status = POCStatus(status_val)
        else:
            status = status_val

        # Parse validation result if present
        validation = None
        if data.get("validation_result"):
            validation = POCValidationResult.from_dict(data["validation_result"])

        return cls(
            poc_id=data["poc_id"],
            status=status,
            attempts=data.get("attempts", 0),
            max_attempts=data.get("max_attempts", 15),
            conversation=data.get("conversation"),
            extracted_data=data.get("extracted_data", {}),
            validation_result=validation,
            original_email=data.get("original_email", ""),
            redirect_chain=data.get("redirect_chain", []),
            webhook_id=data.get("webhook_id"),
        )


# ============================================================================
# Execution Plan
# ============================================================================


@dataclass
class POCExecutionPlan:
    """
    Complete execution plan for multi-POC orchestration.

    Generated by parse_multi_poc_instruction node from user input.
    Contains:
    - Global success criteria for the entire request
    - List of all POC requirements
    - Dependency graph for execution ordering
    """
    global_success_criteria: str               # Overall success condition
    pocs: list[POCRequirement] = field(default_factory=list)
    dependency_graph: dict[str, list[str]] = field(default_factory=dict)  # poc_id → [dep_ids]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "global_success_criteria": self.global_success_criteria,
            "pocs": [p.to_dict() for p in self.pocs],
            "dependency_graph": self.dependency_graph,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "POCExecutionPlan":
        """Create from dictionary."""
        return cls(
            global_success_criteria=data["global_success_criteria"],
            pocs=[POCRequirement.from_dict(p) for p in data.get("pocs", [])],
            dependency_graph=data.get("dependency_graph", {}),
        )


# ============================================================================
# Conflict Detection & Resolution
# ============================================================================


@dataclass
class DataConflict:
    """
    Represents a data conflict between multiple POC responses.

    When multiple POCs provide different values for the same field,
    the LLM-based conflict resolution determines which source is correct.
    """
    field_name: str                             # Conflicting field name
    poc_values: dict[str, Any] = field(default_factory=dict)  # poc_id → value
    resolution_reasoning: str = ""              # LLM's analysis
    correct_poc_id: Optional[str] = None        # POC with correct value
    incorrect_poc_ids: list[str] = field(default_factory=list)  # POCs to re-request

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "field_name": self.field_name,
            "poc_values": self.poc_values,
            "resolution_reasoning": self.resolution_reasoning,
            "correct_poc_id": self.correct_poc_id,
            "incorrect_poc_ids": self.incorrect_poc_ids,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DataConflict":
        """Create from dictionary."""
        return cls(
            field_name=data["field_name"],
            poc_values=data.get("poc_values", {}),
            resolution_reasoning=data.get("resolution_reasoning", ""),
            correct_poc_id=data.get("correct_poc_id"),
            incorrect_poc_ids=data.get("incorrect_poc_ids", []),
        )


# ============================================================================
# Global Validation
# ============================================================================


@dataclass
class GlobalValidationResult:
    """
    Result of validating aggregated data against global success criteria.

    After all POCs complete and conflicts are resolved, this validates
    whether the combined data satisfies the user's original request.
    """
    valid: bool
    all_criteria_met: bool = False
    missing_data: list[str] = field(default_factory=list)  # What's still needed
    poc_ids_needing_retry: list[str] = field(default_factory=list)  # Which POCs should provide more
    reasoning: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "valid": self.valid,
            "all_criteria_met": self.all_criteria_met,
            "missing_data": self.missing_data,
            "poc_ids_needing_retry": self.poc_ids_needing_retry,
            "reasoning": self.reasoning,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GlobalValidationResult":
        """Create from dictionary."""
        return cls(
            valid=data["valid"],
            all_criteria_met=data.get("all_criteria_met", False),
            missing_data=data.get("missing_data", []),
            poc_ids_needing_retry=data.get("poc_ids_needing_retry", []),
            reasoning=data.get("reasoning", ""),
        )


# ============================================================================
# Orchestration Decision
# ============================================================================


@dataclass
class OrchestrationDecision:
    """
    Decision returned by the DAG scheduler (orchestrate_pocs node).

    Determines what action to take next in multi-POC execution:
    - EXECUTE: Start execution for specified ready POCs
    - WAIT: Suspend execution waiting for POC replies
    - AGGREGATE: All POCs done, proceed to aggregation phase
    - FAIL: Fatal error, terminate execution
    """
    action: OrchestrationAction
    poc_ids: list[str] = field(default_factory=list)  # POCs to execute
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "action": self.action.value if isinstance(self.action, OrchestrationAction) else self.action,
            "poc_ids": self.poc_ids,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OrchestrationDecision":
        """Create from dictionary."""
        action_val = data["action"]
        if isinstance(action_val, str):
            action = OrchestrationAction(action_val)
        else:
            action = action_val

        return cls(
            action=action,
            poc_ids=data.get("poc_ids", []),
            reason=data.get("reason", ""),
        )
