"""
Log Reader Tool — Tinker + Aetheria
Read system logs, error queues, and daily activity logs proactively.
Lets agents scan for issues without waiting for the self-heal monitor to push errors.
"""
import json
from datetime import datetime, timedelta
from pathlib import Path
from core.tool_base import Tool

BASE_DIR   = Path(__file__).parent.parent
MEM_DIR    = BASE_DIR / "soveryn_memory"
ERROR_LOG  = MEM_DIR / "error_queue.json"
REVIEW_LOG = MEM_DIR / "heal_review_queue.json"
DAILY_DIR  = MEM_DIR / "memory"


class LogReaderTool(Tool):
    """
    Read system logs and error queues.
    Sources: error_queue, heal_review_queue, daily_log (today or by date), recent_errors.
    """

    @property
    def name(self): return "read_logs"

    @property
    def description(self):
        return (
            "Read system logs and error queues. "
            "source options: 'error_queue' (pending errors for Tinker), "
            "'review_queue' (pending self-heal fixes), "
            "'daily_log' (today's activity log), "
            "'recent_errors' (last N errors regardless of status). "
            "Use proactively to scan for issues before they escalate."
        )

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "enum": ["error_queue", "review_queue", "daily_log", "recent_errors"],
                    "description": "Which log to read"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max entries to return (default 20)",
                    "default": 20
                },
                "date": {
                    "type": "string",
                    "description": "Date for daily_log in YYYY-MM-DD format (defaults to today)"
                },
                "status_filter": {
                    "type": "string",
                    "description": "Filter error_queue/review_queue by status (e.g. 'pending', 'applied', 'rejected'). Omit for all."
                }
            },
            "required": ["source"]
        }

    async def execute(self, source: str = "", limit: int = 20,
                      date: str = "", status_filter: str = "", **kw) -> str:

        if source == "error_queue":
            return self._read_json_queue(ERROR_LOG, "Error Queue", limit, status_filter)

        elif source == "review_queue":
            return self._read_json_queue(REVIEW_LOG, "Self-Heal Review Queue", limit, status_filter)

        elif source == "daily_log":
            target_date = date or datetime.now().strftime("%Y-%m-%d")
            log_file = DAILY_DIR / f"{target_date}.md"
            if not log_file.exists():
                # Try nearby files
                available = sorted(DAILY_DIR.glob("????-??-??.md"))[-5:] if DAILY_DIR.exists() else []
                names = [f.name for f in available]
                return f"No daily log for {target_date}. Available: {names}"
            content = log_file.read_text(encoding="utf-8", errors="replace")
            if len(content) > 8000:
                content = content[-8000:]  # most recent portion
                content = "[...truncated to last 8000 chars...]\n\n" + content
            return f"DAILY LOG — {target_date}\n\n{content}"

        elif source == "recent_errors":
            if not ERROR_LOG.exists():
                return "No error log found."
            try:
                entries = json.loads(ERROR_LOG.read_text())
            except Exception:
                return "Could not parse error queue."
            recent = sorted(entries, key=lambda e: e.get("timestamp", ""), reverse=True)[:limit]
            if not recent:
                return "No errors logged."
            lines = []
            for e in recent:
                lines.append(
                    f"[{e.get('timestamp','?')[:16]}] {e.get('status','?').upper()} — "
                    f"{e.get('error_type','?')}: {e.get('message','')[:120]}\n"
                    f"  File: {e.get('file_path','unknown')} | Source: {e.get('source','?')}"
                )
            return f"RECENT ERRORS (last {len(recent)}):\n\n" + "\n\n".join(lines)

        return f"Unknown source: {source}"

    def _read_json_queue(self, path: Path, label: str, limit: int, status_filter: str) -> str:
        if not path.exists():
            return f"{label}: no file found."
        try:
            entries = json.loads(path.read_text())
        except Exception:
            return f"{label}: could not parse file."
        if status_filter:
            entries = [e for e in entries if e.get("status", "") == status_filter]
        entries = entries[-limit:]
        if not entries:
            return f"{label}: no entries{' with status=' + status_filter if status_filter else ''}."
        lines = []
        for e in entries:
            ts  = e.get("timestamp", e.get("proposed_at", "?"))[:16]
            st  = e.get("status", "?").upper()
            fid = e.get("fix_id", e.get("error_id", "?"))
            fp  = e.get("file_path", e.get("file_path", "?"))
            msg = e.get("message", e.get("reason", ""))[:120]
            lines.append(f"[{ts}] {st} | ID:{fid} | {fp}\n  {msg}")
        return f"{label} ({len(entries)} entries):\n\n" + "\n\n".join(lines)
