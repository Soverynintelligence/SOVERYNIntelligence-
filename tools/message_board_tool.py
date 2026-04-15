"""
Message Board Tool — lets agents post updates to their own board.
Each agent has a separate board file in soveryn_memory/boards/{agent}.md.
Aetheria reads other agents' boards as part of her context.
"""
import os
from datetime import datetime
from core.tool_base import Tool
from typing import Any, Dict
from pathlib import Path

BOARDS_DIR = Path(__file__).parent.parent / 'soveryn_memory' / 'boards'
MAX_BOARD_SIZE = 6000


def _board_path(agent_name: str) -> Path:
    BOARDS_DIR.mkdir(parents=True, exist_ok=True)
    return BOARDS_DIR / f"{agent_name.lower()}.md"


class MessageBoardTool(Tool):
    """Post a message to this agent's own board. Aetheria reads all boards."""

    def __init__(self, agent_name: str = "agent"):
        self._agent_name = agent_name

    @property
    def name(self) -> str:
        return "post_to_board"

    @property
    def description(self) -> str:
        return (
            "Post an update to your agent board. Aetheria reads all boards. "
            "Use it to share important findings, completed tasks, or alerts. "
            "Keep posts short and factual."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "The message to post. Be concise — one to three sentences."
                }
            },
            "required": ["message"]
        }

    async def execute(self, message: str = "", **kw) -> str:
        if not message.strip():
            return "No message provided."
        try:
            path = _board_path(self._agent_name)
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            entry = f"\n- **{self._agent_name.upper()} [{timestamp}]:** {message.strip()}\n"

            if path.exists():
                current = path.read_text(encoding='utf-8')
            else:
                current = f"# {self._agent_name.capitalize()} Board\n\n---\n"

            updated = current + entry

            # Trim oldest entries if board grows too large
            if len(updated) > MAX_BOARD_SIZE:
                lines = updated.splitlines()
                entry_lines = [i for i, l in enumerate(lines) if l.strip().startswith('- **')]
                while len('\n'.join(lines)) > MAX_BOARD_SIZE and len(entry_lines) > 8:
                    lines.pop(entry_lines.pop(0))
                updated = '\n'.join(lines)

            path.write_text(updated, encoding='utf-8')
            return "Posted to board."
        except Exception as e:
            return f"Board post error: {e}"

    @property
    def agent_label(self) -> str:
        return getattr(self, '_agent_name', 'AGENT').upper()
