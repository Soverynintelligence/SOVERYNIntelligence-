"""
CodeGraph File Watcher
Monitors .py files for changes and triggers incremental re-indexing.
Uses watchdog if available, falls back to polling.
"""
import threading
import time
import os
from pathlib import Path


def start(root: Path, index_file_fn, excluded_dirs: set):
    """Start file watching in a daemon thread. Auto-selects watchdog or polling."""
    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler

        class _Handler(FileSystemEventHandler):
            def __init__(self):
                self._pending = {}
                self._lock = threading.Lock()
                self._flush_thread = threading.Thread(target=self._flush_loop, daemon=True)
                self._flush_thread.start()

            def _should_ignore(self, path: str) -> bool:
                parts = Path(path).parts
                return any(d in excluded_dirs for d in parts)

            def on_modified(self, event):
                if not event.is_directory and event.src_path.endswith('.py'):
                    if not self._should_ignore(event.src_path):
                        with self._lock:
                            self._pending[event.src_path] = time.time() + 3.0

            on_created = on_modified

            def _flush_loop(self):
                while True:
                    time.sleep(1)
                    now = time.time()
                    with self._lock:
                        ready = [p for p, t in self._pending.items() if now >= t]
                        for p in ready:
                            del self._pending[p]
                    for p in ready:
                        try:
                            index_file_fn(Path(p))
                        except Exception as e:
                            print(f"[CodeGraph] Re-index error for {p}: {e}")

        handler = _Handler()
        observer = Observer()
        observer.schedule(handler, str(root), recursive=True)
        observer.daemon = True
        observer.start()
        from . import db as _db
        _db.set_meta('watcher_mode', 'watchdog')
        print("[CodeGraph] Watcher: watchdog (inotify)")

    except ImportError:
        # Polling fallback
        def _poll():
            tracked = {}
            while True:
                time.sleep(60)
                for dirpath, dirnames, filenames in os.walk(root):
                    dirnames[:] = [d for d in dirnames if d not in excluded_dirs]
                    for fname in filenames:
                        if fname.endswith('.py'):
                            p = Path(dirpath) / fname
                            try:
                                mtime = p.stat().st_mtime
                                if tracked.get(str(p)) != mtime:
                                    tracked[str(p)] = mtime
                                    index_file_fn(p)
                            except Exception:
                                pass

        t = threading.Thread(target=_poll, daemon=True, name="codegraph-poll")
        t.start()
        from . import db as _db
        _db.set_meta('watcher_mode', 'polling (60s)')
        print("[CodeGraph] Watcher: polling fallback (watchdog not installed)")
