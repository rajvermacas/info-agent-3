"""
Compile Contract Node - Convert free-text request into a multi-contact contract.

Uses LLM structured output to generate per-POC request contexts and a global
success criteria used for cross-POC validation.
"""

import logging
from typing import Any

from mail_agent.agent.state import AgentState, get_parsed_request
from mail_agent.config import get_settings
from mail_agent.llm.client import LLMClient
from mail_agent.llm.multi_contact import (
    MultiContactContract,
    MultiContactPrompts,
)


logger = logging.getLogger(__name__)


async def compile_contract(state: AgentState) -> dict[str, Any]:
    user_instruction = state.get("user_instruction", "")
    if not user_instruction:
        return {
            "error": "No user instruction provided",
            "current_node": "error",
            "progress_messages": ["ERROR: No user instruction provided"],
        }

    parsed = get_parsed_request(state)
    if not parsed.poc_emails:
        return {
            "error": "No POC emails available to compile contract",
            "current_node": "error",
            "progress_messages": ["ERROR: No POC emails available to compile contract"],
        }

    settings = get_settings()
    llm_client = LLMClient(settings)

    prompt = MultiContactPrompts.compile_contract(user_instruction, parsed.poc_emails)
    contract = await llm_client.generate_structured(
        prompt=prompt,
        output_schema=MultiContactContract,
        system_prompt=MultiContactPrompts.COMPILE_SYSTEM,
    )

    poc_contexts: dict[str, dict[str, str]] = {}
    for plan in contract.poc_plans:
        poc_contexts[plan.poc_email] = {
            "request_description": plan.request_description,
            "success_criteria": plan.success_criteria,
            "expected_format": plan.expected_format,
        }

    progress = (
        f"Contract compiled for {len(contract.poc_plans)} POC(s). "
        f"Assumptions: {len(contract.assumptions)}"
    )

    return {
        "contract": contract.model_dump(),
        "poc_request_contexts": poc_contexts,
        "current_node": "compile_contract",
        "progress_messages": [progress],
    }

