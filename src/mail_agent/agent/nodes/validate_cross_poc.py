"""
Validate Cross-POC Node - Validates data consistency across multiple POCs.

This node performs holistic validation after all individual POC conversations
have completed. It checks for:
- Referential integrity between data from different POCs
- Data completeness when POCs provide complementary information
- Missing references (e.g., employee.dept_id not found in department data)
"""

import json
import logging
from typing import Any

from mail_agent.agent.state import (
    AgentState,
    ConversationState,
    get_parsed_request,
)
from mail_agent.config import get_settings
from mail_agent.llm.client import LLMClient
from mail_agent.llm.prompts import PromptTemplates


logger = logging.getLogger(__name__)


async def validate_cross_poc(state: AgentState) -> dict[str, Any]:
    """
    Validate data consistency across all POC responses.

    This node is called after all individual POC conversations have reached
    terminal states (success, failed, redirected). It performs holistic
    validation to check referential integrity and data completeness.

    Example scenarios detected:
    - Employee data references dept_id=5, but department data has no dept 5
    - Order data references customer_id=123, but customer data missing that ID
    - Inventory data references product_id not found in product catalog

    Args:
        state: Current agent state with all POC conversations complete.

    Returns:
        State update with:
        - _cross_poc_validation_complete: True
        - _cross_poc_is_valid: Whether all cross-POC checks pass
        - _cross_poc_issues: List of issues found (if any)
        - _cross_poc_missing_data: Map of POC -> missing items for follow-up
        - progress_messages: Validation results
    """
    logger.info("Starting cross-POC validation")

    # Get all conversations
    conversations = state.get("conversations", {})

    # Collect successful POC data for validation
    poc_data: dict[str, dict[str, Any]] = {}
    successful_pocs = []
    failed_pocs = []

    for poc_email, conv_dict in conversations.items():
        status = conv_dict.get("status", "unknown")

        if status == "success":
            successful_pocs.append(poc_email)
            # Extract the content from the last received email
            received_emails = conv_dict.get("received_emails", [])
            if received_emails:
                last_email = received_emails[-1]
                poc_data[poc_email] = {
                    "content": last_email.get("attachment_content") or last_email.get("body_text", ""),
                    "filename": last_email.get("attachment_filename"),
                    "has_attachment": last_email.get("has_attachment", False),
                }
        elif status == "failed":
            failed_pocs.append(poc_email)
        # redirected POCs are handled via their target conversation

    logger.info(
        f"Cross-POC validation: {len(successful_pocs)} successful, "
        f"{len(failed_pocs)} failed POCs"
    )

    # If only 0 or 1 successful POC, no cross-validation needed
    if len(successful_pocs) <= 1:
        logger.info("Single or no successful POC - skipping cross-POC validation")
        return {
            "_cross_poc_validation_complete": True,
            "_cross_poc_is_valid": True,
            "_cross_poc_issues": [],
            "_cross_poc_missing_data": {},
            "current_node": "validate_cross_poc",
            "progress_messages": [
                f"Cross-POC validation: {len(successful_pocs)} successful POC(s). "
                "No cross-reference validation needed."
            ],
        }

    # Get parsed request for context
    try:
        parsed_request = get_parsed_request(state)
        request_description = parsed_request.request_description
        success_criteria = parsed_request.success_criteria
    except ValueError:
        logger.warning("No parsed request found - using default context")
        request_description = state.get("user_instruction", "")
        success_criteria = ""

    # Use LLM to perform cross-POC validation
    try:
        settings = get_settings()
        llm_client = LLMClient(settings)

        # Build prompt for cross-POC validation
        prompt = PromptTemplates.validate_cross_poc(
            request_description=request_description,
            success_criteria=success_criteria,
            poc_data=poc_data,
        )

        logger.debug(f"Cross-POC validation prompt length: {len(prompt)} chars")

        # Call LLM for validation
        # Use higher max_tokens (16384) because cross-POC validation with multiple POCs
        # and detailed issues can produce long responses that exceed the default 4096 limit
        response = await llm_client.generate_structured(
            prompt=prompt,
            output_schema=CrossPOCValidationResponse,
            max_tokens=16384,
        )

        is_valid = response.is_valid
        issues = [issue.model_dump() for issue in response.issues]
        missing_data = response.missing_data_by_poc

        logger.info(
            f"Cross-POC validation result: is_valid={is_valid}, "
            f"issues={len(issues)}, missing_data_pocs={len(missing_data)}"
        )

        # Build progress message
        if is_valid:
            progress_msg = (
                f"Cross-POC validation passed. All data from {len(successful_pocs)} "
                "POCs is consistent and complete."
            )
        else:
            issue_summary = "; ".join(
                f"{i['source_poc']} -> {i['target_poc']}: {i['issue_type']}"
                for i in issues[:3]  # Show first 3 issues
            )
            if len(issues) > 3:
                issue_summary += f" (+{len(issues) - 3} more)"
            progress_msg = (
                f"Cross-POC validation found {len(issues)} issue(s): {issue_summary}"
            )

        return {
            "_cross_poc_validation_complete": True,
            "_cross_poc_is_valid": is_valid,
            "_cross_poc_issues": issues,
            "_cross_poc_missing_data": missing_data,
            "current_node": "validate_cross_poc",
            "progress_messages": [progress_msg],
        }

    except Exception as e:
        logger.exception(f"Cross-POC validation failed with error: {e}")
        # On error, assume valid to avoid blocking (fail-open for UX)
        return {
            "_cross_poc_validation_complete": True,
            "_cross_poc_is_valid": True,
            "_cross_poc_issues": [],
            "_cross_poc_missing_data": {},
            "current_node": "validate_cross_poc",
            "error": f"Cross-POC validation error: {str(e)}",
            "progress_messages": [
                f"Cross-POC validation encountered error: {str(e)}. "
                "Proceeding with success acknowledgment."
            ],
        }


# ============================================================================
# Response Schema for LLM
# ============================================================================

from pydantic import BaseModel, Field


class CrossPOCIssue(BaseModel):
    """Single cross-POC validation issue."""

    source_poc: str = Field(
        description="POC email that has the referencing/incomplete data"
    )
    target_poc: str = Field(
        description="POC email that should have the referenced data"
    )
    issue_type: str = Field(
        description="Type of issue: missing_reference, invalid_reference, incomplete_data, inconsistent_data"
    )
    details: str = Field(
        description="Human-readable description of the issue"
    )
    missing_items: list[str] = Field(
        default_factory=list,
        description="List of specific missing items (e.g., IDs, fields)"
    )


class CrossPOCValidationResponse(BaseModel):
    """Response schema for cross-POC validation."""

    is_valid: bool = Field(
        description="True if all cross-POC data is consistent and complete"
    )
    issues: list[CrossPOCIssue] = Field(
        default_factory=list,
        description="List of cross-POC issues found"
    )
    missing_data_by_poc: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Map of POC email to list of missing items they need to provide"
    )
    summary: str = Field(
        description="Brief summary of the validation result"
    )
