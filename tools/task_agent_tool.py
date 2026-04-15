"""
Task Agent Tool
Allows Aetheria to directly invoke another agent with a task — not just post to the board.
The target agent runs immediately and returns a result.
"""
import asyncio
from core.tool_base import Tool
from typing import Any, Dict


class TaskAgentTool(Tool):

    def __init__(self, agent_loops: dict):
        self.agent_loops = agent_loops

    @property
    def name(self) -> str:
        return "task_agent"

    @property
    def description(self) -> str:
        return (
            "Directly assign a task to another SOVERYN agent and get their response. "
            "Use this when you need another agent to actually DO something — NOT by writing to them, but by calling this tool. "
            "Agents: tinker (code/fixes), scout (research/leads), ares (security), vett (analysis). "
            "Usage: TOOL_CALL: task_agent(agent=\"tinker\", task=\"run query_code_graph on agent_loop.py\") "
            "or: TOOL_CALL: task_agent(agent=\"scout\", task=\"find NC dealer contacts for used car leads\") "
            "IMPORTANT: You MUST use TOOL_CALL format. Do NOT write the task as plain text or address agents by name in your response."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "agent": {
                    "type": "string",
                    "enum": ["tinker", "scout", "ares", "vett"],
                    "description": "Which agent to task"
                },
                "task": {
                    "type": "string",
                    "description": "Clear description of what you need the agent to do"
                }
            },
            "required": ["agent", "task"]
        }

    async def execute(self, agent: str = '', task: str = '') -> str:
        if not agent or not task:
            return "Error: must specify agent and task"

        loop = self.agent_loops.get(agent.lower())
        if not loop:
            return f"Error: agent '{agent}' not found"

        print(f"[TASK] Aetheria → {agent}: {task[:80]}...")
        try:
            response = await loop.process_message(
                f"[TASK FROM AETHERIA]: {task}",
                conversation_history=[],
                max_tokens=800
            )
            result = (response or '').strip()[:600]
            print(f"[TASK] {agent} responded: {result[:100]}...")
            return f"{agent.upper()} RESPONSE:\n{result}"
        except Exception as e:
            return f"Error running {agent}: {e}"
