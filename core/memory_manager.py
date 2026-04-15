"""
core/memory_manager.py
SOVERYN Memory Manager - Unified short/long term memory interface
Wraps memory.py with tiered memory architecture.

NOTE: memory.py ChromaDB functions are now stubs (PyTorch/Blackwell
incompatibility). store() is permanently a no-op here; the Lattice
(core/lattice/) handles all real persistent memory for agents.
"""

import sys
import os
from datetime import datetime, timedelta
from typing import Optional

# memory.py stubs are permanently active — no ChromaDB writes happen here.
_chroma_broken: bool = True   # Always true: memory.py is now fully stubbed
_chroma_warned: bool = False

# Allow imports from parent directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory import (
    store_memory,
    retrieve_memory,
    get_all_memories,
    delete_memory_by_id,
    pin_memory,
    prune_old_memories,
    calculate_importance
)

# Thresholds
SHORT_TERM_IMPORTANCE_THRESHOLD = 0.3   # Minimum to store at all
LONG_TERM_IMPORTANCE_THRESHOLD = 0.7    # Promoted to long term
SHORT_TERM_MAX_AGE_HOURS = 24           # Short term expires after 24 hours
LONG_TERM_MIN_IMPORTANCE = 0.7          # Long term = high importance or pinned


class MemoryManager:
    """
    Tiered memory system for SOVERYN agents.

    Short Term: Recent exchanges, lower importance, expires after 24 hours
    Long Term:  High importance or pinned memories, never auto-pruned

    Uses ChromaDB via memory.py as the backing store.
    Importance metadata field determines tier:
      < 0.7  = short term
      >= 0.7 = long term
      pinned = always long term
    """

    def __init__(self, agent_name: str):
        self.agent_name = agent_name.lower()

    # ------------------------------------------------------------------
    # STORE
    # ------------------------------------------------------------------

    def store(self, user_message: str, agent_response: str, force_importance: float = None):
        """
        Store a memory. Automatically tiered by importance score.
        High importance (>= 0.7) goes to long term.
        Lower importance goes to short term (pruned after 24h).
        """
        global _chroma_broken, _chroma_warned

        # If ChromaDB/embeddings are known broken, skip immediately with a
        # one-time warning to avoid log spam every agent cycle.
        if _chroma_broken:
            if not _chroma_warned:
                print("[MemoryManager] ChromaDB embeddings are unavailable (PyTorch/GPU "
                      "incompatibility). store() is a no-op until fixed. "
                      "The Lattice remains active for real memory.", flush=True)
                _chroma_warned = True
            return

        importance = force_importance if force_importance is not None else \
            calculate_importance(user_message, agent_response)

        if importance < SHORT_TERM_IMPORTANCE_THRESHOLD:
            print(f"[MemoryManager] Skipping low-importance memory ({importance:.2f})", flush=True)
            return

        tier = "long_term" if importance >= LONG_TERM_IMPORTANCE_THRESHOLD else "short_term"
        print(f"[MemoryManager] Storing {tier} memory (importance: {importance:.2f})", flush=True)

        try:
            store_memory(self.agent_name, user_message, agent_response, force_importance=importance)
        except Exception as e:
            _chroma_broken = True
            print(f"[MemoryManager] ChromaDB store failed — marking as broken to suppress "
                  f"future attempts. Error: {e}", flush=True)

    def store_long_term(self, user_message: str, agent_response: str):
        """Force store as long term memory (importance 0.9)"""
        self.store(user_message, agent_response, force_importance=0.9)

    def store_short_term(self, user_message: str, agent_response: str):
        """Force store as short term memory (importance 0.4)"""
        self.store(user_message, agent_response, force_importance=0.4)

    # ------------------------------------------------------------------
    # RETRIEVE
    # ------------------------------------------------------------------

    def retrieve(self, query: str, n_results: int = 5) -> str:
        """Retrieve relevant memories (both tiers, pinned/important first)"""
        return retrieve_memory(self.agent_name, query, n_results)

    def retrieve_long_term(self, query: str, n_results: int = 5) -> str:
        """Retrieve only long term (high importance + pinned) memories"""
        all_memories = get_all_memories(self.agent_name)
        long_term = [
            m for m in all_memories
            if m.get('pinned') or m.get('importance', 0) >= LONG_TERM_MIN_IMPORTANCE
        ]

        if not long_term:
            return ""

        # Return most recent long term memories up to n_results
        texts = [m['text'] for m in long_term[:n_results]]
        return "Long term memories:\n" + "\n\n".join(texts)

    def retrieve_short_term(self, query: str, n_results: int = 5) -> str:
        """Retrieve only recent short term memories (last 24 hours)"""
        all_memories = get_all_memories(self.agent_name)
        cutoff = datetime.now() - timedelta(hours=SHORT_TERM_MAX_AGE_HOURS)

        short_term = []
        for m in all_memories:
            if m.get('pinned'):
                continue
            if m.get('importance', 0) >= LONG_TERM_MIN_IMPORTANCE:
                continue
            ts = m.get('timestamp', '')
            if ts:
                try:
                    if datetime.fromisoformat(ts) >= cutoff:
                        short_term.append(m)
                except:
                    pass

        if not short_term:
            return ""

        texts = [m['text'] for m in short_term[:n_results]]
        return "Recent context:\n" + "\n\n".join(texts)

    # ------------------------------------------------------------------
    # MANAGE
    # ------------------------------------------------------------------

    def promote_to_long_term(self, memory_id: str):
        """Pin a memory to promote it to long term"""
        return pin_memory(self.agent_name, memory_id, pinned=True)

    def delete(self, memory_id: str):
        """Delete a specific memory"""
        return delete_memory_by_id(self.agent_name, memory_id)

    def prune_short_term(self, hours_old: int = 24):
        """Prune expired short term memories"""
        pruned = prune_old_memories(
            self.agent_name,
            days_old=hours_old // 24 or 1,
            min_importance=LONG_TERM_MIN_IMPORTANCE
        )
        print(f"[MemoryManager] Pruned {pruned} expired short term memories", flush=True)
        return pruned

    def get_stats(self) -> dict:
        """Get memory stats for this agent"""
        all_memories = get_all_memories(self.agent_name)
        cutoff = datetime.now() - timedelta(hours=SHORT_TERM_MAX_AGE_HOURS)

        long_term_count = 0
        short_term_count = 0
        pinned_count = 0

        for m in all_memories:
            if m.get('pinned'):
                pinned_count += 1
                long_term_count += 1
            elif m.get('importance', 0) >= LONG_TERM_MIN_IMPORTANCE:
                long_term_count += 1
            else:
                short_term_count += 1

        return {
            "agent": self.agent_name,
            "total": len(all_memories),
            "long_term": long_term_count,
            "short_term": short_term_count,
            "pinned": pinned_count
        }

    # ------------------------------------------------------------------
    # CONFERENCE SUPPORT
    # ------------------------------------------------------------------

    def store_conference_summary(self, topic: str, summary: str, participants: list):
        """Store a conference/discussion summary as long term memory"""
        participant_str = ", ".join(participants)
        user_msg = f"Conference on: {topic} (participants: {participant_str})"
        self.store_long_term(user_msg, summary)
        print(f"[MemoryManager] Conference summary stored for {self.agent_name}", flush=True)
