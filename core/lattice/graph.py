"""
Lattice Graph — Node/edge SQLite layer
"""

import os
import json
import sqlite3
import uuid
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

DB_PATH = os.path.join(
    os.path.dirname(__file__), '..', '..', 'soveryn_memory', 'lattice.db'
)

# Intensity tiers
INTENSITY_DEFAULT     = 0.3
INTENSITY_SIGNIFICANT = 0.7
INTENSITY_CORE        = 1.0

# Layer constants
LAYER_PRIVATE = 'private'   # agent-specific — only that agent sees it
LAYER_GLOBAL  = 'global'    # system-wide — all agents can read and connect to it
# 'lattice' and 'core' are legacy values treated as private

# Edge decay
EDGE_DECAY_DAYS       = 14    # edges not reinforced lose strength after this
EDGE_DECAY_AMOUNT     = 0.05
EDGE_ARCHIVE_THRESHOLD = 0.1  # archived (not deleted) below this

# Valid node types and relationship types
NODE_TYPES = {'entity', 'event', 'concept', 'fact', 'insight'}
RELATIONSHIP_TYPES = {
    'associated_with', 'caused_by', 'supports',
    'contradicts', 'belongs_to', 'precedes', 'references', 'recurs', 'supersedes'
}


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create tables if they don't exist."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with _get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS nodes (
                id           TEXT PRIMARY KEY,
                type         TEXT NOT NULL,
                layer        TEXT NOT NULL DEFAULT 'lattice',
                agent        TEXT NOT NULL,
                content      TEXT NOT NULL,
                intensity    REAL NOT NULL DEFAULT 0.3,
                salience     REAL NOT NULL DEFAULT 0.5,
                access_count INTEGER NOT NULL DEFAULT 0,
                tags         TEXT,
                created_at   TEXT NOT NULL,
                updated_at   TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_nodes_agent    ON nodes(agent);
            CREATE INDEX IF NOT EXISTS idx_nodes_layer    ON nodes(layer);
            CREATE INDEX IF NOT EXISTS idx_nodes_type     ON nodes(type);
            CREATE INDEX IF NOT EXISTS idx_nodes_salience ON nodes(salience DESC);

            CREATE TABLE IF NOT EXISTS edges (
                id                  TEXT PRIMARY KEY,
                source_id           TEXT NOT NULL,
                target_id           TEXT NOT NULL,
                relationship        TEXT NOT NULL,
                strength            REAL NOT NULL DEFAULT 0.5,
                bidirectional       INTEGER NOT NULL DEFAULT 1,
                archived            INTEGER NOT NULL DEFAULT 0,
                reinforcement_count INTEGER NOT NULL DEFAULT 1,
                reinforced_at       TEXT NOT NULL,
                created_at          TEXT NOT NULL,
                FOREIGN KEY (source_id) REFERENCES nodes(id),
                FOREIGN KEY (target_id) REFERENCES nodes(id)
            );

            CREATE INDEX IF NOT EXISTS idx_edges_source   ON edges(source_id);
            CREATE INDEX IF NOT EXISTS idx_edges_target   ON edges(target_id);
            CREATE INDEX IF NOT EXISTS idx_edges_rel      ON edges(relationship);
            CREATE INDEX IF NOT EXISTS idx_edges_archived ON edges(archived);

            CREATE TABLE IF NOT EXISTS contradiction_flags (
                id               TEXT PRIMARY KEY,
                edge_id          TEXT NOT NULL,
                node_a_id        TEXT NOT NULL,
                node_b_id        TEXT NOT NULL,
                flagged_at       TEXT NOT NULL,
                reviewed         INTEGER NOT NULL DEFAULT 0,
                resolution       TEXT,
                confidence_delta REAL DEFAULT 0.0,
                last_monitored   TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_nodes_created ON nodes(created_at DESC);

            CREATE TABLE IF NOT EXISTS dream_log (
                id            TEXT PRIMARY KEY,
                trigger       TEXT NOT NULL,
                agent         TEXT NOT NULL,
                nodes_read    INTEGER DEFAULT 0,
                edges_created INTEGER DEFAULT 0,
                nodes_merged  INTEGER DEFAULT 0,
                contradictions_flagged INTEGER DEFAULT 0,
                summary       TEXT,
                ran_at        TEXT NOT NULL
            );
        """)


# ---------------------------------------------------------------------------
# Salience
# ---------------------------------------------------------------------------

def compute_salience(intensity: float, access_count: int, updated_at: str) -> float:
    """Salience = 0.2*recency + 0.3*frequency + 0.5*intensity. Core nodes never decay."""
    if intensity >= INTENSITY_CORE:
        return 1.0

    try:
        last = datetime.fromisoformat(updated_at)
    except ValueError:
        last = datetime.now()

    days_since = max((datetime.now() - last).days, 0)
    recency = 0.5 ** (days_since / 7)          # half-life 7 days
    frequency = min(access_count / 50.0, 1.0)   # caps at 50 accesses

    return round(0.2 * recency + 0.3 * frequency + 0.5 * intensity, 4)


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

def write_node(
    agent: str,
    content: str,
    node_type: str = 'fact',
    layer: str = LAYER_PRIVATE,
    intensity: float = INTENSITY_DEFAULT,
    tags: Optional[List[str]] = None,
    embedding: Optional[List[float]] = None,
) -> str:
    """Write a new node. Returns node id."""
    if node_type not in NODE_TYPES:
        node_type = 'fact'
    if layer not in (LAYER_PRIVATE, LAYER_GLOBAL, 'lattice', 'core'):
        layer = LAYER_PRIVATE

    node_id = str(uuid.uuid4())
    now = datetime.now().isoformat()
    tags_json = json.dumps(tags or [])
    salience = compute_salience(intensity, 0, now)
    embedding_json = json.dumps(embedding) if embedding else None

    with _get_conn() as conn:
        conn.execute("""
            INSERT INTO nodes (id, type, layer, agent, content, intensity, salience,
                               access_count, tags, embedding, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
        """, (node_id, node_type, layer, agent, content, intensity, salience,
              tags_json, embedding_json, now, now))

    return node_id


def get_node(node_id: str) -> Optional[Dict]:
    with _get_conn() as conn:
        row = conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
    return dict(row) if row else None


def touch_node(node_id: str):
    """Increment access_count and recompute salience."""
    node = get_node(node_id)
    if not node:
        return
    new_count = node['access_count'] + 1
    now = datetime.now().isoformat()
    new_salience = compute_salience(node['intensity'], new_count, now)
    with _get_conn() as conn:
        conn.execute("""
            UPDATE nodes SET access_count = ?, salience = ?, updated_at = ?
            WHERE id = ?
        """, (new_count, new_salience, now, node_id))


def find_nodes_by_keywords(agent: str, query: str, limit: int = 20) -> List[Dict]:
    """Keyword search across agent's private nodes AND all global nodes."""
    words = [w.strip().lower() for w in query.split() if len(w.strip()) > 2]
    if not words:
        return []

    with _get_conn() as conn:
        results = []
        seen = set()
        for word in words[:6]:
            rows = conn.execute("""
                SELECT * FROM nodes
                WHERE (agent = ? AND layer != ?)
                   OR layer = ?
                  AND (LOWER(content) LIKE ? OR tags LIKE ?)
                ORDER BY salience DESC
                LIMIT ?
            """, (agent, LAYER_GLOBAL, LAYER_GLOBAL,
                  f'%{word}%', f'%{word}%', limit)).fetchall()
            for row in rows:
                if row['id'] not in seen:
                    seen.add(row['id'])
                    results.append(dict(row))

    return sorted(results, key=lambda n: n['salience'], reverse=True)[:limit]


def find_nodes_by_embedding(
    agent: str,
    embedding: List[float],
    limit: int = 10,
    threshold: float = 0.70,
) -> List[Dict]:
    """Semantic similarity search using cosine distance over stored embeddings."""
    import numpy as np

    with _get_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM nodes
            WHERE embedding IS NOT NULL
              AND ((agent = ? AND layer != ?) OR layer = ?)
            ORDER BY salience DESC
            LIMIT 2000
        """, (agent, LAYER_GLOBAL, LAYER_GLOBAL)).fetchall()

    if not rows:
        return []

    query_vec = np.array(embedding, dtype=np.float32)
    query_norm = float(np.linalg.norm(query_vec)) + 1e-9

    results = []
    for row in rows:
        try:
            stored_vec = np.array(json.loads(row['embedding']), dtype=np.float32)
            sim = float(np.dot(query_vec, stored_vec) / (query_norm * np.linalg.norm(stored_vec) + 1e-9))
            if sim >= threshold:
                r = dict(row)
                r['semantic_score'] = round(sim, 4)
                results.append(r)
        except Exception:
            continue

    return sorted(results, key=lambda n: n['semantic_score'], reverse=True)[:limit]


def get_agent_activity(agents: Optional[List[str]] = None, limit: int = 5) -> Dict[str, Any]:
    """
    Delegation transparency: recent Lattice activity per agent.
    Returns last `limit` node writes per agent with metadata.
    """
    all_agents = agents or ['aetheria', 'vett', 'tinker', 'ares', 'scout', 'vision']
    result = {}
    with _get_conn() as conn:
        for ag in all_agents:
            rows = conn.execute("""
                SELECT id, type, content, tags, layer, intensity, created_at
                FROM nodes WHERE agent = ?
                ORDER BY created_at DESC LIMIT ?
            """, (ag, limit)).fetchall()
            result[ag] = [dict(r) for r in rows]
    return result


def find_similar_nodes(agent: str, content: str, threshold: float = 0.85) -> List[Dict]:
    """Find nodes with highly similar content (for merge detection)."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM nodes WHERE agent = ?", (agent,)
        ).fetchall()

    content_lower = content.lower()
    similar = []
    for row in rows:
        existing = row['content'].lower()
        # Simple overlap ratio
        shared = sum(1 for w in content_lower.split() if w in existing)
        total = max(len(content_lower.split()), len(existing.split()), 1)
        ratio = shared / total
        if ratio >= threshold:
            similar.append(dict(row))
    return similar


def find_recurrences(
    agent: str,
    node_id: str,
    min_age_days: int = 7,
    similarity_threshold: float = 0.45,
) -> List[Dict]:
    """
    Find older nodes that share a meaningful pattern with the given node.
    'Older' means written at least min_age_days before node_id's created_at.
    Similarity is word-overlap ratio — lower threshold than find_similar_nodes
    so we catch pattern echoes, not just near-duplicates.
    Returns up to 5 matches, sorted by similarity descending.
    """
    node = get_node(node_id)
    if not node:
        return []

    try:
        node_created = datetime.fromisoformat(node['created_at'])
    except ValueError:
        node_created = datetime.now()

    cutoff = (node_created - timedelta(days=min_age_days)).isoformat()

    with _get_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM nodes
            WHERE (agent = ? OR layer = ?)
              AND id != ?
              AND created_at < ?
            ORDER BY created_at DESC
            LIMIT 300
        """, (agent, LAYER_GLOBAL, node_id, cutoff)).fetchall()

    content_words = set(w.lower() for w in node['content'].split() if len(w) > 3)
    if not content_words:
        return []

    matches = []
    for row in rows:
        other_words = set(w.lower() for w in row['content'].split() if len(w) > 3)
        if not other_words:
            continue
        shared = len(content_words & other_words)
        ratio = shared / max(len(content_words), len(other_words))
        if ratio >= similarity_threshold:
            r = dict(row)
            r['recurrence_similarity'] = round(ratio, 3)
            matches.append(r)

    return sorted(matches, key=lambda x: x['recurrence_similarity'], reverse=True)[:5]


def promote_to_global(node_id: str) -> bool:
    """Promote a node to the global layer. Only Aetheria should call this."""
    now = datetime.now().isoformat()
    with _get_conn() as conn:
        result = conn.execute(
            "UPDATE nodes SET layer = ?, updated_at = ? WHERE id = ?",
            (LAYER_GLOBAL, now, node_id)
        )
        return result.rowcount > 0


# ---------------------------------------------------------------------------
# Edges
# ---------------------------------------------------------------------------

def write_edge(
    source_id: str,
    target_id: str,
    relationship: str,
    strength: float = 0.5,
    bidirectional: bool = True,
) -> str:
    """Write or reinforce an edge. Returns edge id."""
    if relationship not in RELATIONSHIP_TYPES:
        relationship = 'associated_with'

    now = datetime.now().isoformat()

    with _get_conn() as conn:
        # Check for existing edge between these two nodes
        existing = conn.execute("""
            SELECT id, strength, reinforcement_count FROM edges
            WHERE ((source_id = ? AND target_id = ?) OR (source_id = ? AND target_id = ?))
              AND relationship = ? AND archived = 0
        """, (source_id, target_id, target_id, source_id, relationship)).fetchone()

        if existing:
            # Reinforce: strengthen slightly, update timestamp
            new_strength = min(existing['strength'] + 0.05, 1.0)
            conn.execute("""
                UPDATE edges
                SET strength = ?, reinforcement_count = ?, reinforced_at = ?
                WHERE id = ?
            """, (new_strength, existing['reinforcement_count'] + 1, now, existing['id']))
            return existing['id']
        else:
            edge_id = str(uuid.uuid4())
            conn.execute("""
                INSERT INTO edges (id, source_id, target_id, relationship, strength,
                                   bidirectional, archived, reinforcement_count,
                                   reinforced_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 0, 1, ?, ?)
            """, (edge_id, source_id, target_id, relationship,
                  strength, int(bidirectional), now, now))
            return edge_id


def get_edges_for_node(node_id: str, include_archived: bool = False) -> List[Dict]:
    """Get all non-archived edges connected to a node."""
    archived_filter = "" if include_archived else "AND archived = 0"
    with _get_conn() as conn:
        rows = conn.execute(f"""
            SELECT * FROM edges
            WHERE (source_id = ? OR target_id = ?) {archived_filter}
        """, (node_id, node_id)).fetchall()
    return [dict(r) for r in rows]


def decay_edges():
    """Weaken edges not reinforced in EDGE_DECAY_DAYS. Archive those below threshold."""
    cutoff = (datetime.now() - timedelta(days=EDGE_DECAY_DAYS)).isoformat()
    with _get_conn() as conn:
        stale = conn.execute("""
            SELECT id, strength FROM edges
            WHERE reinforced_at < ? AND archived = 0
        """, (cutoff,)).fetchall()

        for edge in stale:
            new_strength = edge['strength'] - EDGE_DECAY_AMOUNT
            if new_strength < EDGE_ARCHIVE_THRESHOLD:
                conn.execute("UPDATE edges SET archived = 1 WHERE id = ?", (edge['id'],))
            else:
                conn.execute("UPDATE edges SET strength = ? WHERE id = ?",
                             (round(new_strength, 4), edge['id']))


# ---------------------------------------------------------------------------
# Contradiction flags
# ---------------------------------------------------------------------------

def flag_contradiction(edge_id: str, node_a_id: str, node_b_id: str) -> str:
    """Flag a contradiction and compute initial confidence_delta from node salience scores."""
    flag_id = str(uuid.uuid4())
    now = datetime.now().isoformat()
    with _get_conn() as conn:
        # Don't double-flag the same edge — but DO update delta if it exists
        existing = conn.execute(
            "SELECT id FROM contradiction_flags WHERE edge_id = ? AND reviewed = 0",
            (edge_id,)
        ).fetchone()
        # Compute confidence_delta: |salience_a - salience_b|
        row_a = conn.execute("SELECT salience FROM nodes WHERE id = ?", (node_a_id,)).fetchone()
        row_b = conn.execute("SELECT salience FROM nodes WHERE id = ?", (node_b_id,)).fetchone()
        sal_a = row_a['salience'] if row_a else 0.5
        sal_b = row_b['salience'] if row_b else 0.5
        delta = round(abs(sal_a - sal_b), 4)
        if existing:
            # Update delta on re-encounter
            conn.execute(
                "UPDATE contradiction_flags SET confidence_delta = ?, last_monitored = ? WHERE id = ?",
                (delta, now, existing['id'])
            )
            return existing['id']
        conn.execute("""
            INSERT INTO contradiction_flags
                (id, edge_id, node_a_id, node_b_id, flagged_at, reviewed, confidence_delta, last_monitored)
            VALUES (?, ?, ?, ?, ?, 0, ?, ?)
        """, (flag_id, edge_id, node_a_id, node_b_id, now, delta, now))
    return flag_id


def get_pending_contradictions() -> List[Dict]:
    with _get_conn() as conn:
        rows = conn.execute("""
            SELECT cf.*,
                   na.content AS content_a, nb.content AS content_b
            FROM contradiction_flags cf
            JOIN nodes na ON cf.node_a_id = na.id
            JOIN nodes nb ON cf.node_b_id = nb.id
            WHERE cf.reviewed = 0
            ORDER BY cf.flagged_at DESC
        """).fetchall()
    return [dict(r) for r in rows]


def resolve_contradiction(flag_id: str, resolution: str):
    with _get_conn() as conn:
        conn.execute("""
            UPDATE contradiction_flags SET reviewed = 2, resolution = ? WHERE id = ?
        """, (resolution, flag_id))


# ---------------------------------------------------------------------------
# Dream log
# ---------------------------------------------------------------------------

def write_dream_log(trigger: str, agent: str, nodes_read: int = 0,
                    edges_created: int = 0, nodes_merged: int = 0,
                    contradictions_flagged: int = 0, summary: str = "") -> str:
    log_id = str(uuid.uuid4())
    with _get_conn() as conn:
        conn.execute("""
            INSERT INTO dream_log
                (id, trigger, agent, nodes_read, edges_created, nodes_merged,
                 contradictions_flagged, summary, ran_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (log_id, trigger, agent, nodes_read, edges_created,
              nodes_merged, contradictions_flagged, summary,
              datetime.now().isoformat()))
    return log_id


# ---------------------------------------------------------------------------
# Schema migrations (safe — idempotent)
# ---------------------------------------------------------------------------

def _migrate_db():
    """Apply schema migrations that may not exist in older databases."""
    with _get_conn() as conn:
        # Add embedding column if missing
        try:
            conn.execute("ALTER TABLE nodes ADD COLUMN embedding TEXT DEFAULT NULL")
        except Exception:
            pass  # already exists
        # Add created_at index if missing
        try:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_nodes_created ON nodes(created_at DESC)")
        except Exception:
            pass


# Initialize on import
init_db()
_migrate_db()
