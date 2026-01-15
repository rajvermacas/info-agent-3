"""
Parse Multi-POC Instruction Node - Extract structured data for multi-POC orchestration.

Uses LLM to parse natural language instruction into multiple POC requirements,
dependencies between POCs, and global success criteria.
"""

import logging
from typing import Any

from mail_agent.agent.multi_poc_state import (
    DynamicPOCConfig,
    POCExecutionPlan,
    POCRequirement,
    POCState,
    POCStatus,
)
from mail_agent.agent.state import AgentState
from mail_agent.config import get_settings
from mail_agent.llm.client import LLMClient
from mail_agent.llm.multi_poc_prompts import (
    MultiPOCPromptTemplates,
    ParsedMultiPOCInstruction,
)


logger = logging.getLogger(__name__)


async def parse_multi_poc_instruction(state: AgentState) -> dict[str, Any]:
    """
    Parse user instruction to extract multi-POC structured request data.

    This node:
    1. Sends the user instruction to LLM for multi-POC parsing
    2. Extracts POC emails, per-POC requests, dependencies, dynamic spawn rules
    3. Infers global success criteria
    4. Initializes POC states for each POC requirement

    Args:
        state: Current agent state with user_instruction.

    Returns:
        State update with execution_plan and initialized poc_states.

    Raises:
        ValueError: If user instruction is missing or no POCs found.
    """
    logger.info("Parsing multi-POC instruction")

    user_instruction = state.get("user_instruction")
    if not user_instruction:
        error_msg = "No user instruction provided"
        logger.error(error_msg)
        return {
            "error": error_msg,
            "current_node": "error",
            "progress_messages": [f"ERROR: {error_msg}"],
        }

    logger.debug(f"User instruction: {user_instruction}")

    try:
        settings = get_settings()
        llm_client = LLMClient(settings)

        # Generate prompt and call LLM
        prompt = MultiPOCPromptTemplates.parse_multi_poc_instruction(user_instruction)
        parsed: ParsedMultiPOCInstruction = await llm_client.generate_structured(
            prompt=prompt,
            output_schema=ParsedMultiPOCInstruction,
            system_prompt=MultiPOCPromptTemplates.MULTI_POC_PARSE_SYSTEM,
        )

        logger.info(
            f"Parsed multi-POC instruction: {len(parsed.pocs)} POC(s) found, "
            f"global_criteria={parsed.global_success_criteria[:50]}..."
        )

        # Validate we have at least one POC
        if not parsed.pocs:
            error_msg = "No POC requirements found in instruction"
            logger.error(error_msg)
            return {
                "error": error_msg,
                "current_node": "error",
                "progress_messages": [
                    f"ERROR: {error_msg}. Could not find any email addresses."
                ],
            }

        # Convert parsed POCs to POCRequirement objects
        poc_requirements: list[POCRequirement] = []
        for idx, parsed_poc in enumerate(parsed.pocs):
            # Convert dynamic spawn config if present
            dynamic_config = None
            if parsed_poc.spawns_dynamic_pocs:
                dynamic_config = DynamicPOCConfig(
                    enabled=parsed_poc.spawns_dynamic_pocs.enabled,
                    email_source_field=parsed_poc.spawns_dynamic_pocs.email_source_field,
                    request_template=parsed_poc.spawns_dynamic_pocs.request_template,
                    success_criteria_template=parsed_poc.spawns_dynamic_pocs.success_criteria_template,
                )

            requirement = POCRequirement(
                id=parsed_poc.id,
                email=parsed_poc.email,
                request=parsed_poc.request,
                success_criteria=parsed_poc.success_criteria,
                dependencies=list(parsed_poc.dependencies),
                execution_order=idx,  # Will be updated by build_dependency_graph
                spawns_dynamic_pocs=dynamic_config,
            )
            poc_requirements.append(requirement)
            logger.debug(
                f"Created POCRequirement: id={requirement.id}, "
                f"email={requirement.email}, deps={requirement.dependencies}"
            )

        # Create execution plan
        execution_plan = POCExecutionPlan(
            global_success_criteria=parsed.global_success_criteria,
            pocs=poc_requirements,
            dependency_graph={},  # Will be built by build_dependency_graph node
        )

        # Initialize POC states
        poc_states: dict[str, dict[str, Any]] = {}
        for requirement in poc_requirements:
            poc_state = POCState(
                poc_id=requirement.id,
                status=POCStatus.PENDING,
            )
            poc_states[requirement.id] = poc_state.to_dict()
            logger.debug(f"Initialized POCState for: {requirement.id}")

        # Create progress message
        poc_summary = ", ".join(
            f"{req.id}({req.email})" for req in poc_requirements
        )
        progress_msg = (
            f"Parsed instruction: {len(poc_requirements)} POC(s) identified. "
            f"POCs: {poc_summary}"
        )

        logger.info(
            f"Multi-POC parsing complete: "
            f"{len(poc_requirements)} POCs, "
            f"global_criteria='{parsed.global_success_criteria[:100]}...'"
        )

        return {
            "execution_plan": execution_plan.to_dict(),
            "poc_states": poc_states,
            "current_node": "parse_multi_poc_instruction",
            "progress_messages": [progress_msg],
        }

    except Exception as e:
        error_msg = f"Failed to parse multi-POC instruction: {e}"
        logger.error(error_msg, exc_info=True)
        return {
            "error": error_msg,
            "current_node": "error",
            "progress_messages": [f"ERROR: {error_msg}"],
        }
