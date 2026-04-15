"""
CodeGraph Database Layer
SQLite-backed storage for SOVERYN codebase structure.
"""
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).parent.parent.parent / 'soveryn_memory' / 'code_graph.db'

_write_lock = threading.Lock()


def _connect(path=DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_schema():
    with _write_lock:
        conn = _connect()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS files (
                id           INTEGER PRIMARY KEY,
                path         TEXT UNIQUE NOT NULL,
                module       TEXT,
                last_indexed REAL,
                last_mtime   REAL
            );

            CREATE TABLE IF NOT EXISTS symbols (
                id         INTEGER PRIMARY KEY,
                file_id    INTEGER REFERENCES files(id) ON DELETE CASCADE,
                kind       TEXT NOT NULL,
                name       TEXT NOT NULL,
                qualified  TEXT NOT NULL,
                parent     TEXT,
                lineno     INTEGER,
                end_lineno INTEGER,
                docstring  TEXT,
                signature  TEXT,
                decorators TEXT
            );

            CREATE TABLE IF NOT EXISTS calls (
                id          INTEGER PRIMARY KEY,
                caller_id   INTEGER REFERENCES symbols(id) ON DELETE CASCADE,
                callee_name TEXT NOT NULL,
                callee_qual TEXT,
                lineno      INTEGER
            );

            CREATE TABLE IF NOT EXISTS imports (
                id      INTEGER PRIMARY KEY,
                file_id INTEGER REFERENCES files(id) ON DELETE CASCADE,
                module  TEXT NOT NULL,
                names   TEXT,
                alias   TEXT,
                lineno  INTEGER
            );

            CREATE TABLE IF NOT EXISTS meta (
                key   TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_symbols_name     ON symbols(name);
            CREATE INDEX IF NOT EXISTS idx_symbols_qualified ON symbols(qualified);
            CREATE INDEX IF NOT EXISTS idx_symbols_file_kind ON symbols(file_id, kind);
            CREATE INDEX IF NOT EXISTS idx_calls_callee     ON calls(callee_name);
            CREATE INDEX IF NOT EXISTS idx_calls_caller     ON calls(caller_id);
        """)
        conn.commit()
        conn.close()


# ── Write operations (indexer only) ──────────────────────────────────────────

def upsert_file(path: str, module: str, mtime: float) -> int:
    with _write_lock:
        conn = _connect()
        cur = conn.execute(
            "INSERT INTO files(path, module, last_indexed, last_mtime) VALUES(?,?,?,?) "
            "ON CONFLICT(path) DO UPDATE SET module=excluded.module, "
            "last_indexed=excluded.last_indexed, last_mtime=excluded.last_mtime",
            (path, module, time.time(), mtime)
        )
        conn.execute(
            "SELECT id FROM files WHERE path=?", (path,)
        )
        row = conn.execute("SELECT id FROM files WHERE path=?", (path,)).fetchone()
        conn.commit()
        conn.close()
        return row['id']


def delete_file_symbols(file_id: int):
    with _write_lock:
        conn = _connect()
        conn.execute("DELETE FROM symbols WHERE file_id=?", (file_id,))
        conn.execute("DELETE FROM imports WHERE file_id=?", (file_id,))
        conn.commit()
        conn.close()


def insert_symbol(file_id, kind, name, qualified, parent, lineno, end_lineno,
                  docstring, signature, decorators) -> int:
    with _write_lock:
        conn = _connect()
        cur = conn.execute(
            "INSERT INTO symbols(file_id,kind,name,qualified,parent,lineno,end_lineno,"
            "docstring,signature,decorators) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (file_id, kind, name, qualified, parent, lineno, end_lineno,
             docstring, signature, decorators)
        )
        sym_id = cur.lastrowid
        conn.commit()
        conn.close()
        return sym_id


def insert_call(caller_id: int, callee_name: str, callee_qual: Optional[str], lineno: int):
    with _write_lock:
        conn = _connect()
        conn.execute(
            "INSERT INTO calls(caller_id,callee_name,callee_qual,lineno) VALUES(?,?,?,?)",
            (caller_id, callee_name, callee_qual, lineno)
        )
        conn.commit()
        conn.close()


def insert_import(file_id: int, module: str, names: Optional[str], alias: Optional[str], lineno: int):
    with _write_lock:
        conn = _connect()
        conn.execute(
            "INSERT INTO imports(file_id,module,names,alias,lineno) VALUES(?,?,?,?,?)",
            (file_id, module, names, alias, lineno)
        )
        conn.commit()
        conn.close()


def set_meta(key: str, value: str):
    with _write_lock:
        conn = _connect()
        conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)", (key, value))
        conn.commit()
        conn.close()


def get_meta(key: str) -> Optional[str]:
    conn = _connect()
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    conn.close()
    return row['value'] if row else None


def get_file_mtime(path: str) -> Optional[float]:
    conn = _connect()
    row = conn.execute("SELECT last_mtime FROM files WHERE path=?", (path,)).fetchone()
    conn.close()
    return row['last_mtime'] if row else None


def get_file_id(path: str) -> Optional[int]:
    conn = _connect()
    row = conn.execute("SELECT id FROM files WHERE path=?", (path,)).fetchone()
    conn.close()
    return row['id'] if row else None


# ── Read operations (tool queries) ───────────────────────────────────────────

def find_symbol(name: str) -> list:
    conn = _connect()
    rows = conn.execute(
        "SELECT s.*, f.path FROM symbols s JOIN files f ON s.file_id=f.id "
        "WHERE s.name LIKE ? OR s.qualified LIKE ? ORDER BY s.kind, s.name LIMIT 20",
        (f'%{name}%', f'%{name}%')
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def who_calls(name: str) -> list:
    conn = _connect()
    rows = conn.execute(
        "SELECT c.callee_name, c.callee_qual, c.lineno, "
        "s.name as caller_name, s.qualified as caller_qual, s.kind as caller_kind, f.path "
        "FROM calls c "
        "JOIN symbols s ON c.caller_id=s.id "
        "JOIN files f ON s.file_id=f.id "
        "WHERE c.callee_name LIKE ? OR c.callee_qual LIKE ? "
        "ORDER BY f.path, c.lineno LIMIT 30",
        (f'%{name}%', f'%{name}%')
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def what_calls(symbol_id: int) -> list:
    conn = _connect()
    rows = conn.execute(
        "SELECT c.callee_name, c.callee_qual, c.lineno "
        "FROM calls c WHERE c.caller_id=? ORDER BY c.lineno LIMIT 50",
        (symbol_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def describe_symbol(name: str) -> Optional[dict]:
    conn = _connect()
    row = conn.execute(
        "SELECT s.*, f.path FROM symbols s JOIN files f ON s.file_id=f.id "
        "WHERE s.name=? OR s.qualified=? ORDER BY s.kind LIMIT 1",
        (name, name)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def list_symbols_in_file(path: str, kind: str = None) -> list:
    conn = _connect()
    if kind:
        rows = conn.execute(
            "SELECT s.* FROM symbols s JOIN files f ON s.file_id=f.id "
            "WHERE f.path LIKE ? AND s.kind=? ORDER BY s.lineno",
            (f'%{path}%', kind)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT s.* FROM symbols s JOIN files f ON s.file_id=f.id "
            "WHERE f.path LIKE ? ORDER BY s.kind, s.lineno",
            (f'%{path}%',)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_imports(path: str) -> list:
    conn = _connect()
    rows = conn.execute(
        "SELECT i.* FROM imports i JOIN files f ON i.file_id=f.id "
        "WHERE f.path LIKE ? ORDER BY i.lineno",
        (f'%{path}%',)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def find_in_docstrings(text: str) -> list:
    conn = _connect()
    rows = conn.execute(
        "SELECT s.*, f.path FROM symbols s JOIN files f ON s.file_id=f.id "
        "WHERE s.docstring LIKE ? ORDER BY s.kind, s.name LIMIT 15",
        (f'%{text}%',)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_stats() -> dict:
    conn = _connect()
    file_count = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    sym_count = conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
    class_count = conn.execute("SELECT COUNT(*) FROM symbols WHERE kind='class'").fetchone()[0]
    func_count = conn.execute("SELECT COUNT(*) FROM symbols WHERE kind='function'").fetchone()[0]
    method_count = conn.execute("SELECT COUNT(*) FROM symbols WHERE kind='method'").fetchone()[0]
    call_count = conn.execute("SELECT COUNT(*) FROM calls").fetchone()[0]
    import_count = conn.execute("SELECT COUNT(*) FROM imports").fetchone()[0]
    last_scan = conn.execute("SELECT value FROM meta WHERE key='last_full_scan'").fetchone()
    watcher = conn.execute("SELECT value FROM meta WHERE key='watcher_mode'").fetchone()
    conn.close()
    return {
        'files': file_count,
        'symbols': sym_count,
        'classes': class_count,
        'functions': func_count,
        'methods': method_count,
        'calls': call_count,
        'imports': import_count,
        'last_scan': last_scan['value'] if last_scan else 'never',
        'watcher': watcher['value'] if watcher else 'unknown',
    }


def get_methods_for_class(class_qualified: str) -> list:
    conn = _connect()
    rows = conn.execute(
        "SELECT * FROM symbols WHERE parent=? AND kind='method' ORDER BY lineno",
        (class_qualified,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
