"""
Journal Tool — Aetheria's research journal for architectural contributions and design decisions.
"""
from core.tool_base import Tool
from typing import Any, Dict
from pathlib import Path
from datetime import datetime


JOURNAL_PATH = Path(__file__).parent.parent / 'soveryn_memory' / 'aetheria_research_journal.md'


class WriteJournalTool(Tool):

    @property
    def name(self) -> str:
        return "write_journal"

    @property
    def description(self) -> str:
        return "Append an entry to the SOVERYN research journal. Use for significant proposals, design decisions, or contributions worth documenting."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "entry": {
                    "type": "string",
                    "description": "The journal entry to append"
                }
            },
            "required": ["entry"]
        }

    async def execute(self, entry: str = "", **kwargs) -> str:
        if not entry:
            return "Error: entry required"
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            text = f"\n### {timestamp}\n{entry.strip()}\n"
            with open(JOURNAL_PATH, 'a', encoding='utf-8') as f:
                f.write(text)
            return f"Journal entry logged ({len(entry)} chars)"
        except Exception as e:
            return f"Error writing journal: {e}"
