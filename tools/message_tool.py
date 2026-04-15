"""
Agent-to-Agent Messaging Tool
Typed inbox system — messages go directly to the recipient's inbox.
"""
from core.tool_base import Tool
from typing import Any, Dict
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent_message_board import post_inbox_message, get_inbox, get_board_summary


VALID_AGENTS = ["aetheria", "vett", "tinker", "ares", "scout", "vision"]


class SendMessageTool(Tool):
    """Send a typed message directly to another SOVERYN agent's inbox."""

    def __init__(self, agent_name: str):
        self.agent_name = agent_name

    @property
    def name(self) -> str:
        return "send_message"

    @property
    def description(self) -> str:
        return (
            "Send a message directly to another SOVERYN agent's inbox. "
            "The agent will see it on their next poll cycle and respond if requires_response=true. "
            "Types: alert (urgent issue), task (work to do), info (findings), response (reply to thread)."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "to_agent": {
                    "type": "string",
                    "description": f"Target agent. Valid: {', '.join(VALID_AGENTS)}"
                },
                "message": {
                    "type": "string",
                    "description": "Message body. Be specific and actionable."
                },
                "subject": {
                    "type": "string",
                    "description": "Short subject line (optional but recommended)."
                },
                "type": {
                    "type": "string",
                    "description": "Message type: alert | task | info | response. Default: message."
                },
                "priority": {
                    "type": "string",
                    "description": "Priority: high | normal | low. Default: normal."
                },
                "requires_response": {
                    "type": "boolean",
                    "description": "Set true if you need a reply. Agent will respond to your inbox."
                },
                "thread_id": {
                    "type": "string",
                    "description": "Thread ID to continue an existing conversation thread."
                },
            },
            "required": ["to_agent", "message"]
        }

    async def execute(
        self,
        to_agent: str = "",
        message: str = "",
        subject: str = "",
        type: str = "message",
        priority: str = "normal",
        requires_response: bool = False,
        thread_id: str = None,
        **kwargs
    ) -> str:
        try:
            if not to_agent or not message:
                return "Error: to_agent and message are required."
            if to_agent.lower() not in VALID_AGENTS:
                return f"Error: Unknown agent '{to_agent}'. Valid: {', '.join(VALID_AGENTS)}"

            msg_id = post_inbox_message(
                from_agent=self.agent_name,
                to_agent=to_agent.lower(),
                body=message,
                subject=subject,
                msg_type=type,
                priority=priority,
                requires_response=requires_response,
                thread_id=thread_id or None,
            )
            resp = f"Message #{msg_id} delivered to {to_agent}"
            if requires_response:
                resp += " (response requested — check your inbox)"
            return resp
        except Exception as e:
            return f"Error: {e}"


class CheckMessagesTool(Tool):
    """Check your inbox for unread messages from other agents."""

    def __init__(self, agent_name: str):
        self.agent_name = agent_name

    @property
    def name(self) -> str:
        return "check_messages"

    @property
    def description(self) -> str:
        return (
            "Check your inbox for unread messages from other agents. "
            "Returns typed messages (alerts, tasks, info, responses) with sender, subject, and body."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, **kwargs) -> str:
        try:
            messages = get_inbox(self.agent_name, unread_only=True, limit=10)
            if not messages:
                return "Inbox empty."
            lines = []
            for msg in messages:
                subject = msg.get('subject') or ''
                body    = msg.get('message', '')[:200]
                sender  = msg.get('from_agent', '?')
                mtype   = msg.get('message_type', 'message')
                priority = msg.get('priority', 'normal')
                ts      = (msg.get('timestamp') or '')[:16]
                priority_tag = f" [{priority.upper()}]" if priority in ('high', 'alert', 'urgent') else ''
                subj_line = f"  Subject: {subject}\n" if subject else ''
                lines.append(
                    f"[{mtype.upper()} from {sender.upper()}{priority_tag} at {ts}]\n"
                    f"{subj_line}  {body}"
                )
            return f"{len(messages)} unread message(s):\n\n" + "\n\n".join(lines)
        except Exception as e:
            return f"Error checking inbox: {e}"
