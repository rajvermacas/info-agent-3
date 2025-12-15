import sys
import os
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from mail_agent.a2a_adapter import MailAgentExecutor
from a2a.types import Task, Message, Part, TextPart, TaskStatus, TaskState, Role

async def test_adapter():
    print("Testing MailAgentExecutor...")
    
    # Mock WebhookServer
    mock_webhook_server = MagicMock()
    
    executor = MailAgentExecutor(mock_webhook_server)
    
    # Mock run_agent
    with patch("mail_agent.a2a_adapter.run_agent", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = {
            "conversations": {
                "test@example.com": {
                    "status": "completed",
                    "final_result": "Success",
                    "validation_results": [{"is_valid": True}]
                }
            }
        }
        
        # Mock Context/Queue
        mock_queue = MagicMock()
        mock_queue.put = AsyncMock()
        
        # Create a task with history
        # Note: Depending on SDK version, required fields might vary.
        # Ensure minimal valid object.
        message = Message(
            message_id="msg-123",
            role=Role.user,
            parts=[Part(root=TextPart(text="send mail to test@example.com"))],
            context_id="ctx-123"
        )
        task = Task(
            id="task-123",
            context_id="ctx-123",
            status=TaskStatus(state=TaskState.submitted),
            history=[message]
        )
        
        mock_context = MagicMock()
        mock_context.task = task
        
        print("Executing adapter...")
        await executor.execute(mock_context, mock_queue)
        
        # Verify run_agent called
        mock_run.assert_called_once()
        # Verify call arguments
        call_args = mock_run.call_args
        assert call_args[0][0] == "send mail to test@example.com"
        assert call_args[1].get('webhook_server') == mock_webhook_server
        print("run_agent called successfully with webhook_server.")
        
        # Verify queue put
        mock_queue.put.assert_called_once()
        args = mock_queue.put.call_args[0]
        response_msg = args[0]
        
        # Check response
        assert isinstance(response_msg, Message)
        # Accessing text might need drilling down content
        text_part = response_msg.parts[0].root
        text = text_part.text
        
        print(f"Response text: {text}")
        assert "Success" in text
        assert "VALID" in text
        print("Verification passed!")

if __name__ == "__main__":
    asyncio.run(test_adapter())
