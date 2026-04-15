"""
SOVERYN Invoke Council Tool
Allows Aetheria to invoke her internal council of voices for deep thinking
"""
import asyncio
from typing import Any, Dict
from core.tool_base import Tool

class InvokeCouncilTool(Tool):
    """Tool that lets Aetheria invoke her internal council of five voices"""
    
    def __init__(self, agent_loop):
        self.agent_loop = agent_loop
    
    @property
    def name(self) -> str:
        return "invoke_council"
    
    @property
    def description(self) -> str:
        return "Invoke your internal council of five voices (Skeptic, Empath, Creative, Technical, Intuitive) for deep reflection on complex problems, ethical questions, or important decisions. Use this when you need to think deeply before responding."
    
    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The question, problem, or topic to reflect on deeply"
                }
            },
            "required": ["question"]
        }
    
    async def execute(self, **kwargs) -> str:
        question = kwargs.get("question") or kwargs.get("query") or kwargs.get("topic") or ""
        try:
            print(f"[COUNCIL] Aetheria invoking internal council...")
            print(f"[COUNCIL] Question: {question[:100]}")
            
            import importlib
            re_mod = importlib.import_module('core.reflection_engine')
            result = await re_mod.deep_reflect(question, self.agent_loop)
            
            print(f"[COUNCIL] Synthesis complete ({len(result)} chars)")
            return f"[COUNCIL REFLECTION]\n{result}"
            
        except Exception as e:
            print(f"[COUNCIL] Error: {e}")
            return f"[COUNCIL ERROR] {e}"