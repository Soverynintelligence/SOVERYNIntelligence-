"""
memory.py — ChromaDB-backed conversation memory.

NOTE: ChromaDB embeddings are DISABLED in this file due to PyTorch/Blackwell
(sm_120) incompatibility. All store/retrieve/manage functions are no-ops.
The Lattice (core/lattice/) handles all persistent memory for agents.

The soveryn_library ChromaDB collection is still used by tools/library_tool.py
for RAG search — that is the only active ChromaDB usage.
"""

import re
from datetime import datetime, timedelta

# Force UTF-8 for Windows
import sys
import io
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

_disabled_warned = False


def _warn_disabled():
    global _disabled_warned
    if not _disabled_warned:
        print(
            "[memory.py] ChromaDB conversation memory is disabled "
            "(PyTorch/Blackwell incompatibility). Use the Lattice for persistent memory.",
            flush=True
        )
        _disabled_warned = True


# ---------------------------------------------------------------------------
# Kept intact — no ChromaDB dependency
# ---------------------------------------------------------------------------

def calculate_importance(user_message: str, agent_response: str) -> float:
    """
    Calculate importance score (0.0 to 1.0) based on content.
    Higher score = more important to remember.
    """
    combined = f"{user_message} {agent_response}".lower()

    # Skip low-value exchanges
    trivial_patterns = [
        'ok', 'thanks', 'bye', 'hello', 'hi', 'hey',
        'good morning', 'good night', 'sounds good',
        'got it', 'alright', 'cool', 'nice'
    ]

    if any(pattern in combined and len(combined) < 50 for pattern in trivial_patterns):
        return 0.1  # Very low importance

    # High-value indicators
    importance = 0.5  # Base score

    # Personal information
    if any(word in combined for word in ['my name is', 'i am', 'i work', 'i live', 'my job']):
        importance += 0.3

    # Preferences and decisions
    if any(word in combined for word in ['i prefer', 'i like', 'i hate', 'i want', 'i need']):
        importance += 0.2

    # Technical/specific information
    if any(word in combined for word in ['code', 'error', 'bug', 'fix', 'issue', 'problem']):
        importance += 0.15

    # Questions (context for future)
    if '?' in combined:
        importance += 0.1

    # Longer exchanges tend to be more substantial
    if len(combined) > 200:
        importance += 0.1

    return min(importance, 1.0)  # Cap at 1.0


# ---------------------------------------------------------------------------
# Stubbed — ChromaDB removed
# ---------------------------------------------------------------------------

def get_embedding(text):
    """Stub — embeddings disabled (PyTorch/Blackwell incompatibility)."""
    _warn_disabled()
    return []


def store_memory(*args, **kwargs):
    """Stub — ChromaDB conversation memory is disabled."""
    pass


def retrieve_memory(agent_name: str, query: str, n_results: int = 10) -> str:
    """Stub — ChromaDB conversation memory is disabled. Returns empty string."""
    return ""


def get_all_memories(agent_name: str):
    """Stub — ChromaDB conversation memory is disabled. Returns empty list."""
    return []


def pin_memory(agent_name: str, memory_id: str, pinned: bool = True):
    """Stub — ChromaDB conversation memory is disabled. Returns False."""
    return False


def delete_memory_by_id(agent_name: str, memory_id: str):
    """Stub — ChromaDB conversation memory is disabled. Returns False."""
    return False


def update_memory_by_id(agent_name: str, memory_id: str, new_text: str):
    """Stub — ChromaDB conversation memory is disabled. Returns False."""
    return False


def clear_all_memories(agent_name: str):
    """Stub — ChromaDB conversation memory is disabled. Returns 0."""
    return 0


def prune_old_memories(agent_name: str, days_old: int = 30, min_importance: float = 0.5):
    """Stub — ChromaDB conversation memory is disabled. Returns 0."""
    return 0
