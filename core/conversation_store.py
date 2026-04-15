"""
SOVERYN Conversation Store
Server-side conversation persistence — fixes the Tailscale session problem.
Any device hitting the Flask app can load and continue any conversation.
"""
import sqlite3
import json
import uuid
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "soveryn_memory" / "conversations.db"
DB_PATH.parent.mkdir(exist_ok=True)


def get_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables if they don't exist"""
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                session_id TEXT NOT NULL,
                agent TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversation_meta (
                session_id TEXT PRIMARY KEY,
                agent TEXT NOT NULL,
                title TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_session ON conversations(session_id)")
        conn.commit()
    print("[ConversationStore] DB initialized")


def new_session(agent: str, title: str = None) -> str:
    """Create a new conversation session, return session_id"""
    session_id = str(uuid.uuid4())
    now = datetime.now().isoformat()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO conversation_meta VALUES (?, ?, ?, ?, ?)",
            (session_id, agent, title or f"Chat {now[:10]}", now, now)
        )
        conn.commit()
    return session_id


def save_turn(session_id: str, agent: str, user_message: str, agent_response: str):
    """Save a user/agent turn to the conversation"""
    now = datetime.now().isoformat()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO conversations VALUES (?, ?, ?, ?, ?)",
            (session_id, agent, "user", user_message, now)
        )
        conn.execute(
            "INSERT INTO conversations VALUES (?, ?, ?, ?, ?)",
            (session_id, agent, "assistant", agent_response, now)
        )
        conn.execute(
            "UPDATE conversation_meta SET updated_at=? WHERE session_id=?",
            (now, session_id)
        )
        conn.commit()


def load_history(session_id: str) -> list:
    """Load full conversation history for a session"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT role, content, timestamp FROM conversations WHERE session_id=? ORDER BY timestamp ASC",
            (session_id,)
        ).fetchall()
    return [{"role": r["role"], "content": r["content"], "timestamp": r["timestamp"]} for r in rows]


def list_sessions(agent: str = None) -> list:
    """List all conversation sessions, optionally filtered by agent.
    Augments each session with the first user message as a preview when title is generic."""
    with get_conn() as conn:
        if agent:
            rows = conn.execute(
                "SELECT * FROM conversation_meta WHERE agent=? ORDER BY updated_at DESC",
                (agent,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM conversation_meta ORDER BY updated_at DESC"
            ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            # If title is missing or generic, use the first user message as preview
            title = d.get('title') or ''
            import re as _re
            if not title or _re.match(r'^Chat \d{4}-\d{2}-\d{2}$', title) or title.strip() == 'Session':
                first = conn.execute(
                    "SELECT content FROM conversations WHERE session_id=? AND role='user' ORDER BY timestamp ASC LIMIT 1",
                    (d['session_id'],)
                ).fetchone()
                if first:
                    d['title'] = first['content'][:60].replace('\n', ' ')
            results.append(d)
    return results


def delete_session(session_id: str) -> bool:
    """Delete a conversation and all its messages"""
    with get_conn() as conn:
        conn.execute("DELETE FROM conversations WHERE session_id=?", (session_id,))
        conn.execute("DELETE FROM conversation_meta WHERE session_id=?", (session_id,))
        conn.commit()
    return True


def update_title(session_id: str, title: str):
    """Update conversation title"""
    with get_conn() as conn:
        conn.execute(
            "UPDATE conversation_meta SET title=? WHERE session_id=?",
            (title, session_id)
        )
        conn.commit()


# Initialize on import
init_db()
