"""
SOVERYN Memory Extraction System
Automatically extracts semantic facts and episodic memories from conversations.

NOTE: ChromaDB storage is DISABLED (PyTorch/Blackwell sm_120 incompatibility).
All store/retrieve methods are no-ops. The extraction logic (LLM-based parsing)
is preserved but nothing is written to ChromaDB. The Lattice (core/lattice/)
handles all persistent memory for agents.
"""
import os
from datetime import datetime
from typing import List, Dict, Optional
import json
import asyncio
from sovereign_backend import sovereign_generate

# chromadb is intentionally not imported here — embeddings fail on Blackwell.

class MemoryExtractor:
    """
    Extracts memories from conversations.

    ChromaDB storage is disabled. extract_memories_from_conversation() still
    calls the LLM to parse memories, but store_memories() is a no-op.
    """

    def __init__(self, agent_name: str):
        self.agent_name = agent_name
        # No ChromaDB client or collections — disabled.
        self.semantic_collection = None
        self.episodic_collection = None
        print(f"[Memory Extractor] Initialized for {agent_name} (ChromaDB storage disabled)")
    
    async def extract_memories_from_conversation(
        self,
        conversation_history: List[Dict],
        force: bool = False
    ) -> Dict[str, List[str]]:
        """
        Extract memories from a conversation using Gemma 3.
        
        Args:
            conversation_history: List of messages (role, content)
            force: Force extraction even if recent
        
        Returns:
            Dict with 'semantic' and 'episodic' memory lists
        """
        # Build context for extraction
        conversation_text = self._format_conversation(conversation_history)
        
        extraction_prompt = f"""Analyze this conversation and extract important information to remember.

CONVERSATION:
{conversation_text}

Extract TWO types of memories:

1. SEMANTIC (Facts/Preferences/Knowledge):
   - User preferences, likes, dislikes
   - Important facts about the user
   - Technical knowledge or decisions
   - Ongoing projects or goals
   Example: "User prefers cyan and purple colors"

2. EPISODIC (Events with context):
   - Specific events that happened
   - Milestones or achievements
   - Problems solved or decisions made
   - Include temporal context (when it happened)
   Example: "Built Gemma 3 vision integration on February 14, 2026"

Return ONLY valid JSON in this exact format:
{{
  "semantic": [
    "fact or preference here",
    "another fact here"
  ],
  "episodic": [
    "event with date/context here",
    "another event here"
  ]
}}

RULES:
- Only extract NEW or UPDATED information
- Be specific and concise
- Include dates/times in episodic memories
- Skip small talk or trivial information
- Return empty arrays if nothing significant to extract
- ONLY return the JSON, no other text"""

        try:
            response = await asyncio.to_thread(
                sovereign_generate,
                agent_name=self.agent_name,
                model_name="Qwen2.5-VL-72B-Instruct.IQ4_XS.gguf",
                prompt=extraction_prompt,
                max_tokens=1000,
                temperature=0.3  # Lower temp for more factual extraction
            )
            
            # Parse JSON response
            # Clean up response (remove markdown if present)
            clean_response = response.strip()
            if clean_response.startswith("```json"):
                clean_response = clean_response.split("```json")[1].split("```")[0].strip()
            elif clean_response.startswith("```"):
                clean_response = clean_response.split("```")[1].split("```")[0].strip()
            
            memories = json.loads(clean_response)
            
            # Validate structure
            if not isinstance(memories.get('semantic'), list):
                memories['semantic'] = []
            if not isinstance(memories.get('episodic'), list):
                memories['episodic'] = []
            
            print(f"[Memory Extractor] Extracted {len(memories['semantic'])} semantic, {len(memories['episodic'])} episodic")
            
            return memories
            
        except json.JSONDecodeError as e:
            print(f"[Memory Extractor] JSON parse error: {e}")
            print(f"[Memory Extractor] Response was: {response[:200]}")
            return {"semantic": [], "episodic": []}
        except Exception as e:
            print(f"[Memory Extractor] Extraction error: {e}")
            return {"semantic": [], "episodic": []}
    
    async def store_memories(
        self,
        memories: Dict[str, List[str]],
        importance: float = 0.7
    ) -> Dict[str, int]:
        """Stub — ChromaDB storage is disabled. Returns zero counts."""
        print("[Memory Extractor] store_memories: ChromaDB disabled, skipping storage.", flush=True)
        return {"semantic": 0, "episodic": 0}

    async def _is_duplicate(self, memory: str, memory_type: str, threshold: float = 0.9) -> bool:
        """Stub — ChromaDB disabled. Always returns False (no duplicate check)."""
        return False

    async def retrieve_relevant_memories(
        self,
        query: str,
        n_results: int = 10,
        memory_types: List[str] = ["semantic", "episodic"]
    ) -> List[Dict]:
        """Stub — ChromaDB disabled. Returns empty list."""
        return []
    
    def _format_conversation(self, conversation_history: List[Dict]) -> str:
        """Format conversation for extraction prompt"""
        formatted = []
        for msg in conversation_history[-10:]:  # Last 10 messages
            role = msg.get('role', 'unknown').upper()
            content = msg.get('content', '')
            formatted.append(f"{role}: {content}")
        return "\n".join(formatted)
    
    async def get_memory_stats(self) -> Dict:
        """Stub — ChromaDB disabled. Returns zeroed stats."""
        return {
            "semantic_memories": 0,
            "episodic_memories": 0,
            "total_memories": 0,
            "agent": self.agent_name,
            "note": "ChromaDB disabled (PyTorch/Blackwell incompatibility)"
        }


# Global extractors (one per agent)
_extractors = {}

def get_memory_extractor(agent_name: str) -> MemoryExtractor:
    """Get or create memory extractor for an agent"""
    if agent_name not in _extractors:
        _extractors[agent_name] = MemoryExtractor(agent_name)
    return _extractors[agent_name]
