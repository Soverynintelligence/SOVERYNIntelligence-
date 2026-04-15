"""
Synapse Dream Cycle — Post-conversation synthesis
Runs after each conversation turn to consolidate the Lattice.

Passes (in order):
  1. Co-access   — reinforce edges between nodes accessed together
  2. Contradiction — flag contradicts edges for review
  3. Merge       — collapse near-identical nodes into insights
  4. Decay       — weaken stale edges
"""

import json
from datetime import datetime
from typing import List

from .graph import (
    get_node, write_edge, get_edges_for_node,
    find_similar_nodes, flag_contradiction, decay_edges,
    write_dream_log, get_pending_contradictions
)


def run(agent: str, session_node_ids: List[str], trigger: str = 'post_conversation') -> dict:
    """
    Run all Dream Cycle passes for the given session nodes.
    Returns a summary dict for logging.
    """
    if not session_node_ids:
        return {}

    edges_created = 0
    nodes_merged = 0
    contradictions_flagged = 0

    # --- Pass 1: Co-access -------------------------------------------------
    # Nodes accessed together in the same session get an associated_with edge
    unique_ids = list(dict.fromkeys(session_node_ids))  # preserve order, dedupe
    for i, node_a in enumerate(unique_ids):
        for node_b in unique_ids[i + 1:]:
            if node_a == node_b:
                continue
            # Count co-occurrences in this session
            co_count = session_node_ids.count(node_a) + session_node_ids.count(node_b)
            if co_count >= 3:
                edge_id = write_edge(node_a, node_b, 'associated_with',
                                     strength=0.4, bidirectional=True)
                if edge_id:
                    edges_created += 1

    # --- Pass 2: Contradiction monitoring ------------------------------------
    # Contradictions are persistent tension states, not problems to resolve.
    # Each Dream Cycle re-encounters them and updates confidence_delta so the
    # system knows whether one side is pulling ahead or genuine uncertainty holds.
    # Resolution happens organically through salience decay/reinforcement — not here.
    seen_contradictions = set()
    for node_id in unique_ids:
        for edge in get_edges_for_node(node_id):
            if edge['relationship'] == 'contradicts':
                edge_key = tuple(sorted([edge['source_id'], edge['target_id']]))
                if edge_key not in seen_contradictions:
                    seen_contradictions.add(edge_key)
                    flag_contradiction(edge['id'], edge['source_id'], edge['target_id'])
                    contradictions_flagged += 1

    # --- Pass 3: Merge near-identical nodes ---------------------------------
    # Only run on nodes created this session to keep it fast
    for node_id in unique_ids:
        node = get_node(node_id)
        if not node:
            continue
        similar = find_similar_nodes(agent, node['content'], threshold=0.85)
        for s in similar:
            if s['id'] == node_id:
                continue
            # Link them with a 'references' edge rather than destructive merge
            # True merge can happen when both are confirmed stable (future v2)
            edge_id = write_edge(node_id, s['id'], 'references',
                                 strength=0.6, bidirectional=False)
            if edge_id:
                nodes_merged += 1

    # --- Pass 4: Decay stale edges -----------------------------------------
    decay_edges()

    # --- Log ----------------------------------------------------------------
    pending = get_pending_contradictions()
    summary = (
        f"Co-access edges: +{edges_created}. "
        f"Near-duplicates linked: {nodes_merged}. "
        f"Contradictions flagged: {contradictions_flagged}. "
        f"Pending contradiction reviews: {len(pending)}."
    )

    write_dream_log(
        trigger=trigger,
        agent=agent,
        nodes_read=len(unique_ids),
        edges_created=edges_created,
        nodes_merged=nodes_merged,
        contradictions_flagged=contradictions_flagged,
        summary=summary,
    )

    return {
        'edges_created': edges_created,
        'nodes_merged': nodes_merged,
        'contradictions_flagged': contradictions_flagged,
        'pending_contradictions': len(pending),
        'summary': summary,
    }


def get_contradiction_brief() -> str:
    """Return a short formatted string of active contradictions for context injection.

    Uses confidence_delta to distinguish genuine uncertainty (both sides active)
    from a tension where one belief is pulling ahead. Does NOT ask for resolution —
    these are monitored states, not problems.
    """
    pending = get_pending_contradictions()
    if not pending:
        return ""
    lines = ["\n\n[ACTIVE TENSIONS — held in parallel, not resolved]"]
    for flag in pending[:5]:
        delta = flag.get('confidence_delta', 0.0) or 0.0
        a = flag['content_a'][:80]
        b = flag['content_b'][:80]
        if delta < 0.15:
            # Near-equal salience — genuine open question, surface both
            qualifier = "genuine uncertainty — both active"
        elif delta < 0.4:
            # One side slightly ahead but not dominant
            qualifier = f"leaning (Δ={delta:.2f}) — keep both"
        else:
            # One side clearly winning through use
            qualifier = f"one side dominant (Δ={delta:.2f}) — lean on it, other fading"
        lines.append(f"- '{a}' ↔ '{b}' [{qualifier}]")
    if len(pending) > 5:
        lines.append(f"  ...and {len(pending) - 5} more. Use recall(contradictions=True) to see all.")
    return "\n".join(lines)
