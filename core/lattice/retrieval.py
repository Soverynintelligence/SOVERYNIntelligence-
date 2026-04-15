"""
Synapse Retrieval — Spreading activation over the Lattice
"""

import random
from typing import List, Dict, Tuple, Optional, Any
from .graph import (
    find_nodes_by_keywords, find_nodes_by_embedding,
    get_edges_for_node, get_node, touch_node,
    _get_conn, LAYER_GLOBAL,
)

# Deep dive trigger keywords
DEEP_DIVE_KEYWORDS = {
    'deep', 'why', 'root', 'underlying', 'everything about',
    'explain', 'origin', 'history', 'background', 'context',
    'how did', 'what led', 'trace'
}

STANDARD_DEPTH  = 2
DEEP_DEPTH      = 4
STANDARD_CAP    = 8
DEEP_CAP        = 15


def _is_deep_query(query: str) -> bool:
    q = query.lower()
    if '!deep' in q:
        return True
    return any(kw in q for kw in DEEP_DIVE_KEYWORDS)


def _spread(seed_ids: List[str], depth: int) -> List[Tuple[str, float]]:
    """
    Breadth-first spreading activation.
    Returns list of (node_id, path_strength) for non-seed nodes reached.
    """
    visited = set(seed_ids)
    frontier = list(seed_ids)
    results: Dict[str, float] = {}  # node_id → best path strength

    for _ in range(depth):
        next_frontier = []
        for node_id in frontier:
            node = get_node(node_id)
            if not node:
                continue
            node_salience = node['salience']

            for edge in get_edges_for_node(node_id):
                neighbor_id = (
                    edge['target_id'] if edge['source_id'] == node_id
                    else edge['source_id']
                )
                if neighbor_id in visited:
                    continue
                # Only follow reverse direction on bidirectional edges
                if edge['source_id'] != node_id and not edge['bidirectional']:
                    continue

                visited.add(neighbor_id)
                next_frontier.append(neighbor_id)
                path_strength = round(edge['strength'] * node_salience, 4)
                if neighbor_id not in results or results[neighbor_id] < path_strength:
                    results[neighbor_id] = path_strength

        frontier = next_frontier

    return sorted(results.items(), key=lambda x: x[1], reverse=True)


def query(
    agent: str,
    message: str,
    deep: bool = False,
    session_node_ids: List[str] = None,
    embedding: Optional[List[float]] = None,
) -> List[Dict]:
    """
    Main retrieval entry point.
    Returns list of node dicts ranked by relevance, with path_strength attached.
    Touches (access_count++) every node returned to feed salience.
    """
    is_deep = deep or _is_deep_query(message)
    depth = DEEP_DEPTH if is_deep else STANDARD_DEPTH
    cap = DEEP_CAP if is_deep else STANDARD_CAP

    # 1. Find seeds — hybrid: keyword + semantic if embedding provided
    seeds = find_nodes_by_keywords(agent, message, limit=10)
    if embedding:
        sem_nodes = find_nodes_by_embedding(agent, embedding, limit=10, threshold=0.68)
        seen_ids = {n['id'] for n in seeds}
        for n in sem_nodes:
            if n['id'] not in seen_ids:
                # Blend semantic score into salience for ranking
                n['salience'] = max(n.get('salience', 0.3), n['semantic_score'] * 0.9)
                seeds.append(n)
                seen_ids.add(n['id'])
    seed_ids = [n['id'] for n in seeds]

    # 2. Spread from seeds
    spread_results = _spread(seed_ids, depth)

    # 3. Combine: seeds (high weight) + spread results
    combined: Dict[str, float] = {}
    for node in seeds:
        combined[node['id']] = node['salience']
    for node_id, path_strength in spread_results:
        if node_id not in combined:
            combined[node_id] = path_strength

    # 4. Fetch, rank, cap
    ranked = sorted(combined.items(), key=lambda x: x[1], reverse=True)[:cap]

    results = []
    for node_id, score in ranked:
        node = get_node(node_id)
        if node:
            node['relevance_score'] = score
            touch_node(node_id)
            results.append(node)

    return results


def format_for_context(nodes: List[Dict], label: str = "Relevant Memory") -> str:
    """Format retrieved nodes as a context block for prompt injection."""
    if not nodes:
        return ""
    import json as _json
    lines = [f"\n\n[{label}]"]
    for node in nodes:
        tags = ""
        try:
            tag_list = _json.loads(node.get('tags') or '[]')
            if tag_list:
                tags = f" [{', '.join(tag_list)}]"
        except Exception:
            pass
        source = " {SOVERYN}" if node.get('layer') == 'global' else f" [{node.get('agent', '?')}]"
        lines.append(f"- ({node['type']}){tags}{source} {node['content']}")
    return "\n".join(lines)


def wander(agent: str, top_n: int = 50) -> Dict:
    """
    Curiosity-driven traversal with no destination query.
    Picks a random high-salience node as a seed and spreads from it,
    returning whatever the graph happens to connect to.

    This is the WANDER primitive: no keyword, no intent, just follow edges.
    """
    with _get_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM nodes
            WHERE (agent = ? OR layer = ?)
              AND salience > 0.2
            ORDER BY salience DESC
            LIMIT ?
        """, (agent, LAYER_GLOBAL, top_n)).fetchall()

    if not rows:
        return {"seed": None, "neighbors": []}

    # Weight the random choice by salience — higher salience = more likely to be picked
    # but not deterministic, so the path is always genuinely surprising
    population = [dict(r) for r in rows]
    weights = [r['salience'] for r in population]
    seed = random.choices(population, weights=weights, k=1)[0]
    touch_node(seed['id'])

    spread_results = _spread([seed['id']], depth=3)

    # Build edge index for seed node so we can annotate how each neighbor connects
    seed_edges = get_edges_for_node(seed['id'])
    direct_connections: Dict[str, str] = {}  # neighbor_id → relationship
    for edge in seed_edges:
        neighbor_id = edge['target_id'] if edge['source_id'] == seed['id'] else edge['source_id']
        # Prefer 'recurs' over other relationships if multiple edges exist
        existing = direct_connections.get(neighbor_id)
        if existing != 'recurs':
            direct_connections[neighbor_id] = edge['relationship']

    neighbors = []
    for node_id, path_strength in spread_results[:12]:
        node = get_node(node_id)
        if node:
            node['path_strength'] = path_strength
            node['edge_relationship'] = direct_connections.get(node_id, 'spread')
            touch_node(node_id)
            neighbors.append(node)

    # Collect the recurrence chain for the seed — prior appearances of this pattern
    recurrence_chain = get_recurrence_chain(seed['id'])

    return {"seed": seed, "neighbors": neighbors, "recurrence_chain": recurrence_chain}


def get_recurrence_chain(node_id: str, max_depth: int = 6) -> List[Dict]:
    """
    Follow 'recurs' edges from a node to build the chronological chain
    of prior appearances of this pattern. Returns nodes oldest-first.
    """
    chain = []
    visited = {node_id}
    frontier = [node_id]

    for _ in range(max_depth):
        next_frontier = []
        for nid in frontier:
            for edge in get_edges_for_node(nid):
                if edge['relationship'] != 'recurs':
                    continue
                neighbor_id = (
                    edge['target_id'] if edge['source_id'] == nid
                    else edge['source_id']
                )
                if neighbor_id in visited:
                    continue
                neighbor = get_node(neighbor_id)
                if neighbor:
                    visited.add(neighbor_id)
                    next_frontier.append(neighbor_id)
                    chain.append(neighbor)
        if not next_frontier:
            break
        frontier = next_frontier

    chain.sort(key=lambda n: n.get('created_at', ''))
    return chain


def format_wander_for_prompt(result: Dict) -> str:
    """Format a wander() result as a prompt block for Aetheria."""
    import json as _json
    from datetime import datetime as _dt

    seed = result.get("seed")
    neighbors = result.get("neighbors", [])
    recurrence_chain = result.get("recurrence_chain", [])

    if not seed:
        return ""

    def _fmt_node(n: Dict, score: Optional[float] = None, rel: Optional[str] = None) -> str:
        tags_raw = n.get('tags') or '[]'
        try:
            tag_list = _json.loads(tags_raw)
            tag_str = f" [{', '.join(tag_list)}]" if tag_list else ""
        except Exception:
            tag_str = ""
        score_str = f" (strength: {score:.2f})" if score is not None else ""
        source = " {SOVERYN}" if n.get('layer') == 'global' else ""
        rel_str = f" ←[{rel}]" if rel and rel != 'spread' else ""
        return f"  - ({n['type']}){tag_str}{source}{rel_str}{score_str}: {n['content']}"

    def _age(node: Dict) -> str:
        try:
            created = _dt.fromisoformat(node['created_at'])
            days = (_dt.now() - created).days
            if days == 0:
                return "today"
            elif days == 1:
                return "yesterday"
            elif days < 30:
                return f"{days}d ago"
            elif days < 365:
                return f"{days // 30}mo ago"
            else:
                return f"{days // 365}y ago"
        except Exception:
            return "?"

    lines = ["[WANDER — no query, just following edges]"]
    lines.append(f"Seed node (salience {seed['salience']:.2f}, written {_age(seed)}):")
    lines.append(f"  ({seed['type']}): {seed['content']}")

    # Recurrence chain — the echo of this pattern through time
    if recurrence_chain:
        lines.append(f"\nECHO — this pattern has appeared before ({len(recurrence_chain)} prior instance(s)):")
        for prior in recurrence_chain:
            lines.append(f"  - [{_age(prior)}] ({prior['type']}): {prior['content']}")
        lines.append("  ↑ The same pattern, recurring across time.")

    if neighbors:
        # Separate direct recurrences from other connections
        recur_neighbors = [n for n in neighbors if n.get('edge_relationship') == 'recurs']
        other_neighbors = [n for n in neighbors if n.get('edge_relationship') != 'recurs']

        if recur_neighbors:
            lines.append(f"\nDirect recurrence links ({len(recur_neighbors)}):")
            for n in recur_neighbors:
                lines.append(_fmt_node(n, score=n.get('path_strength'), rel='recurs'))

        if other_neighbors:
            lines.append(f"\nOther connected nodes ({len(other_neighbors)}, via spreading activation):")
            for n in other_neighbors:
                lines.append(_fmt_node(n, score=n.get('path_strength'), rel=n.get('edge_relationship')))
    else:
        lines.append("\nNo connected nodes found from this seed.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Timeline — temporal decision chain for a topic
# ---------------------------------------------------------------------------

def timeline(
    agent: str,
    topic: str,
    embedding: Optional[List[float]] = None,
    limit: int = 30,
) -> List[Dict]:
    """
    Return all nodes related to a topic sorted chronologically (oldest first),
    annotated with supersedes/superseded_by relationships.
    Combines keyword + semantic search for maximum coverage.
    """
    keyword_nodes = find_nodes_by_keywords(agent, topic, limit=limit)

    semantic_nodes: List[Dict] = []
    if embedding:
        semantic_nodes = find_nodes_by_embedding(agent, embedding, limit=20, threshold=0.65)

    seen: set = set()
    all_nodes: List[Dict] = []
    for n in keyword_nodes + semantic_nodes:
        if n['id'] not in seen:
            seen.add(n['id'])
            all_nodes.append(n)

    if not all_nodes:
        return []

    # Sort chronologically
    all_nodes.sort(key=lambda n: n.get('created_at', ''))

    # Annotate supersedes chains within the result set
    node_id_set = {n['id'] for n in all_nodes}
    for node in all_nodes:
        edges = get_edges_for_node(node['id'])
        node['supersedes_ids'] = [
            e['target_id'] for e in edges
            if e['relationship'] == 'supersedes'
            and e['source_id'] == node['id']
            and e['target_id'] in node_id_set
        ]
        node['superseded_by_ids'] = [
            e['source_id'] for e in edges
            if e['relationship'] == 'supersedes'
            and e['target_id'] == node['id']
            and e['source_id'] in node_id_set
        ]
        touch_node(node['id'])

    return all_nodes


def format_timeline(nodes: List[Dict], topic: str) -> str:
    """Format a timeline as a readable decision chain for Aetheria."""
    import json as _json
    from datetime import datetime as _dt

    if not nodes:
        return f"No timeline found for: {topic}"

    def _date(node: Dict) -> str:
        try:
            return _dt.fromisoformat(node['created_at']).strftime('%b %d')
        except Exception:
            return '?'

    lines = [f"[TIMELINE — {topic}] {len(nodes)} nodes, oldest → newest\n"]
    for node in nodes:
        source = "{SOVERYN}" if node.get('layer') == 'global' else f"[{node.get('agent', '?')}]"
        try:
            tag_list = _json.loads(node.get('tags') or '[]')
            tag_str = f" [{', '.join(tag_list)}]" if tag_list else ""
        except Exception:
            tag_str = ""
        chain_note = ""
        if node.get('supersedes_ids'):
            chain_note = " ↑ supersedes prior"
        elif node.get('superseded_by_ids'):
            chain_note = " ← superseded"
        lines.append(
            f"  {_date(node)} {source} ({node['type']}){tag_str}{chain_note}: {node['content'][:140]}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Agent status — delegation transparency
# ---------------------------------------------------------------------------

def agent_status() -> str:
    """
    Aggregate cognitive load across all agents:
    - Recent Lattice writes per agent
    - Pending message board tasks
    Returns a formatted block for Aetheria.
    """
    from datetime import datetime as _dt
    import json as _json
    from .graph import get_agent_activity

    # Lattice activity
    activity = get_agent_activity(limit=3)

    # Message board pending tasks
    board_data: Dict[str, Any] = {}
    try:
        import sqlite3 as _sqlite3
        from pathlib import Path as _Path
        board_db = _Path(__file__).parent.parent.parent / 'soveryn_memory' / 'message_board.db'
        if board_db.exists():
            conn = _sqlite3.connect(str(board_db))
            conn.row_factory = _sqlite3.Row
            agents = ['aetheria', 'vett', 'tinker', 'ares', 'scout', 'vision']
            for ag in agents:
                rows = conn.execute("""
                    SELECT from_agent, subject, message, timestamp, status, message_type
                    FROM messages
                    WHERE to_agent = ? AND status = 'unread'
                    ORDER BY timestamp DESC LIMIT 3
                """, (ag,)).fetchall()
                board_data[ag] = [dict(r) for r in rows]
            conn.close()
    except Exception:
        pass

    def _age(ts: str) -> str:
        try:
            t = _dt.fromisoformat(ts)
            mins = int((_dt.now() - t).total_seconds() / 60)
            if mins < 60:
                return f"{mins}m ago"
            elif mins < 1440:
                return f"{mins // 60}h ago"
            else:
                return f"{mins // 1440}d ago"
        except Exception:
            return '?'

    lines = ["[AGENT STATUS — delegation view]\n"]
    agent_order = ['aetheria', 'vett', 'tinker', 'ares', 'scout', 'vision']
    for ag in agent_order:
        nodes = activity.get(ag, [])
        tasks = board_data.get(ag, [])
        if not nodes and not tasks:
            lines.append(f"  {ag.upper()}: idle — no recent activity")
            continue
        lines.append(f"  {ag.upper()}:")
        for n in nodes:
            try:
                tag_list = _json.loads(n.get('tags') or '[]')
                tag_str = f" [{', '.join(tag_list)}]" if tag_list else ""
            except Exception:
                tag_str = ""
            lines.append(f"    Lattice {_age(n['created_at'])} ({n['type']}){tag_str}: {n['content'][:80]}")
        for t in tasks:
            subj = t.get('subject') or t.get('message', '')[:60]
            lines.append(f"    Inbox unread from {t['from_agent']} {_age(t['timestamp'])}: {subj[:80]}")
    return "\n".join(lines)
