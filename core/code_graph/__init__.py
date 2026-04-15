"""
CodeGraph — SOVERYN codebase structure graph.
Imported once at startup; background scan + watcher start automatically.
"""
import threading
from pathlib import Path
from . import db, indexer, watcher

# Init schema on first import
db.init_schema()

ROOT = indexer.ROOT
EXCLUDED_DIRS = indexer.EXCLUDED_DIRS


def _startup():
    indexer.full_scan(ROOT)
    watcher.start(ROOT, indexer.index_file, EXCLUDED_DIRS)


threading.Thread(target=_startup, daemon=True, name="codegraph-init").start()
