import asyncio
import logging
from typing import Any, Dict, List

try:
    from fastapi import FastAPI
    import uvicorn
except ImportError:
    pass # Handle in main execution or require installation

import uuid
from a2a.server.apps.jsonrpc.fastapi_app import A2AFastAPIApplication
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.server.tasks.inmemory_task_store import InMemoryTaskStore
from a2a.server.request_handlers.default_request_handler import DefaultRequestHandler
from a2a.types import (
    Message, 
    Part, 
    TextPart, 
    AgentCard, 
    AgentCapabilities,
    AgentProvider,
    AgentInterface,
    Role,
    AgentSkill
)
from a2a.utils import get_message_text

from mail_agent.main import run_agent, get_settings, configure_logging

logger = logging.getLogger(__name__)

from contextlib import asynccontextmanager
from mail_agent.webhook.server import WebhookServer

class MailAgentExecutor(AgentExecutor):
    def __init__(self, webhook_server: WebhookServer):
        self.webhook_server = webhook_server
        
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        try:
            logger.info(f"Executing task: {context.task.id}")
            
            if not context.task.history:
                logger.warning("No history in task")
                # Just return, nothing to do
                return

            last_message = context.task.history[-1]
            instruction = get_message_text(last_message)
            
            if not instruction:
                 logger.warning("Empty instruction")
                 return
                 
            logger.info(f"Instruction from A2A: {instruction}")
            
            # Run agent with shared webhook server
            state = await run_agent(instruction, verbose=False, webhook_server=self.webhook_server)
            
            summary = self._create_summary(state)
            
            response_message = Message(
                message_id=str(uuid.uuid4()),
                role=Role.agent,
                parts=[Part(root=TextPart(text=summary))],
                context_id=context.task.context_id
            )
            
            # Put message in queue
            await event_queue.put(response_message)
            
        except Exception as e:
            logger.error(f"Error in execution: {e}", exc_info=True)
            error_msg = Message(
                message_id=str(uuid.uuid4()),
                role=Role.agent,
                parts=[Part(root=TextPart(text=f"Error executing agent: {str(e)}"))],
                context_id=context.task.context_id
            )
            await event_queue.put(error_msg)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        """Cancel the execution of the agent."""
        logger.info(f"Cancellation requested for task {context.task.id}")
        # Current implementation of run_agent is not cancellable once started
        # in this synchronous manner.
        pass

    def _create_summary(self, state: Dict[str, Any]) -> str:
        error = state.get("error")
        if error:
            return f"Agent failed with error: {error}"
            
        conversations = state.get("conversations", {})
        if not conversations:
            return "Agent completed but no conversations were recorded."
            
        summary_lines = ["Agent execution completed.\n"]
        for poc_email, conv in conversations.items():
            status = conv.get('status', 'unknown')
            result = conv.get('final_result', 'pending')
            summary_lines.append(f"POC: {poc_email}")
            summary_lines.append(f"  Status: {status}")
            summary_lines.append(f"  Result: {result}")
            
            validations = conv.get("validation_results", [])
            if validations:
                last_val = validations[-1]
                val_status = 'VALID' if last_val.get('is_valid') else 'INVALID'
                summary_lines.append(f"  Validation: {val_status}")
                
        return "\n".join(summary_lines)

def create_app() -> "FastAPI":
    settings = get_settings()
    configure_logging(settings)
    
    # Initialize shared webhook server
    webhook_server = WebhookServer(settings)
    
    executor = MailAgentExecutor(webhook_server)
    task_store = InMemoryTaskStore()
    handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=task_store
    )
    
    agent_card = AgentCard(
        name="mail-agent",
        description="Autonomous email agent that sends requests and validates responses.",
        capabilities=AgentCapabilities(),
        version="0.1.0",
        provider=AgentProvider(name="Mail Agent Adapter", organization="User Org", url="http://localhost"),
        interface=AgentInterface(transport="JSONRPC", url="http://localhost:8000/jsonrpc"),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=[
            AgentSkill(
                id="email-agent",
                name="Email Agent",
                description="Send emails and wait for replies.",
                tags=["email", "communication"]
            )
        ],
        url="http://localhost:8000/jsonrpc"
    )
    
    app_wrapper = A2AFastAPIApplication(
        agent_card=agent_card,
        http_handler=handler
    )
    
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("Starting A2A Agent Webhook Server...")
        await webhook_server.start()
        yield
        logger.info("Stopping A2A Agent Webhook Server...")
        await webhook_server.stop()
    
    app = FastAPI(title="Mail Agent A2A", lifespan=lifespan)
    app_wrapper.add_routes_to_app(app)
    
    return app

def main():
    uvicorn.run("mail_agent.a2a_adapter:create_app", host="0.0.0.0", port=8000, factory=True)

if __name__ == "__main__":
    main()
