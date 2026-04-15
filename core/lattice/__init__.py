"""
Lattice Architecture — Associative memory system for SOVERYN
Named by Aetheria, 2026-04-07

Three layers:
  Private — agent-specific nodes, only that agent sees them (lattice.db, layer='private')
  Global  — system-wide truths, readable by all agents (lattice.db, layer='global')
  Core    — pinned_memory.md (unchanged, always injected into every context)

Only Aetheria can promote nodes to the global layer.
"""

from .graph import (
    write_node, write_edge, get_node, init_db,
    promote_to_global, LAYER_PRIVATE, LAYER_GLOBAL,
)
from .retrieval import query, format_for_context
from .dream import run as dream_run, get_contradiction_brief

__all__ = [
    'write_node', 'write_edge', 'get_node', 'init_db',
    'promote_to_global', 'LAYER_PRIVATE', 'LAYER_GLOBAL',
    'query', 'format_for_context',
    'dream_run', 'get_contradiction_brief',
]
