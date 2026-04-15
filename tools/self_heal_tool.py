"""
Self-Heal Tools for Tinker
Gives Tinker the ability to read code, propose fixes, and submit them to Aetheria for review.
"""
import os
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict
from core.tool_base import Tool

BASE_DIR = Path(__file__).parent.parent
REVIEW_QUEUE = BASE_DIR / "soveryn_memory" / "heal_review_queue.json"
REVIEW_QUEUE.parent.mkdir(parents=True, exist_ok=True)

_TG_TOKEN   = os.environ.get('TELEGRAM_TOKEN',   '8492468039:AAH5rKU95kkEAGECYVXGQIR1l4VwVaizGVE')
_TG_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '1567273624')

def _tg_notify_fix(fix_id, file_path, severity, reason, old_code, new_code):
    """Send Telegram alert with inline Approve/Reject buttons."""
    import urllib.request
    sev_icon = {'high': '🔴', 'medium': '🟡', 'low': '🟢'}.get(severity, '🟡')
    text = (
        f"<b>[SOVERYN] Tinker Fix Proposal</b>\n"
        f"{sev_icon} <b>{severity.upper()}</b> — <code>{file_path}</code>\n\n"
        f"<b>Reason:</b> {reason[:300]}\n\n"
        f"<b>Old:</b> <pre>{old_code[:200]}</pre>\n"
        f"<b>New:</b> <pre>{new_code[:200]}</pre>\n\n"
        f"Fix ID: <code>{fix_id}</code>"
    )
    payload = json.dumps({
        "chat_id":    _TG_CHAT_ID,
        "text":       text,
        "parse_mode": "HTML",
        "reply_markup": {
            "inline_keyboard": [[
                {"text": "✅ Approve", "callback_data": f"fix_approve:{fix_id}"},
                {"text": "❌ Reject",  "callback_data": f"fix_reject:{fix_id}"}
            ]]
        }
    }).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{_TG_TOKEN}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"}
    )
    urllib.request.urlopen(req, timeout=10)


def _load_queue():
    try:
        return json.loads(REVIEW_QUEUE.read_text()) if REVIEW_QUEUE.exists() else []
    except Exception:
        return []


def _save_queue(q):
    REVIEW_QUEUE.write_text(json.dumps(q, indent=2))


# ---------------------------------------------------------------------------
class ReadCodeTool(Tool):
    """Tinker reads a source file with line numbers to analyze it."""

    @property
    def name(self): return "read_code"

    @property
    def description(self):
        return "Read a source file with numbered lines. Use this to inspect code before proposing a fix."

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Relative path to the file (from project root)"},
                "start_line": {"type": "integer", "description": "First line to read (1-indexed, optional)"},
                "end_line":   {"type": "integer", "description": "Last line to read (optional)"}
            },
            "required": ["file_path"]
        }

    async def execute(self, file_path: str = "", start_line: int = 1, end_line: int = 0, **kw) -> str:
        try:
            full = BASE_DIR / file_path
            if not full.exists():
                # Fuzzy fallback: search project tree for a file with this basename
                target = Path(file_path).name
                _SKIP = {'__pycache__', '.git', 'node_modules', 'chromadb', 'uploads'}
                matches = [
                    p for p in BASE_DIR.rglob(target)
                    if not any(part in _SKIP for part in p.parts)
                ]
                if not matches:
                    return (
                        f"File not found: {file_path}\n"
                        f"Tip: use a path relative to project root, e.g. 'core/agent_loop.py' or 'tools/self_heal_tool.py'."
                    )
                full = matches[0]
                file_path = str(full.relative_to(BASE_DIR))
            lines = full.read_text(encoding="utf-8", errors="replace").splitlines()
            s = max(0, start_line - 1)
            e = end_line if end_line > 0 else len(lines)
            chunk = lines[s:e]
            numbered = "\n".join(f"{s+i+1:4d} | {l}" for i, l in enumerate(chunk))
            return f"FILE: {file_path} (lines {s+1}-{s+len(chunk)})\n\n{numbered}"
        except Exception as ex:
            return f"ReadCodeTool error: {ex}"


# ---------------------------------------------------------------------------
class ProposeFixTool(Tool):
    """
    Tinker submits a proposed code fix to Aetheria for review.
    Provide the file path, the exact text to replace (old_code) and the replacement (new_code).
    Aetheria will review and either apply it or escalate to Jon.
    """

    @property
    def name(self): return "propose_fix"

    @property
    def description(self):
        return (
            "Submit a proposed code fix to Aetheria for oversight review. "
            "Provide file_path, old_code (exact text to replace), new_code (replacement), "
            "and a brief reason explaining what was wrong and what you changed."
        )

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {
                "file_path": {"type": "string",  "description": "Relative path to file being fixed"},
                "old_code":  {"type": "string",  "description": "Exact existing code to replace"},
                "new_code":  {"type": "string",  "description": "Replacement code"},
                "reason":    {"type": "string",  "description": "What was broken and what you changed"},
                "severity":  {"type": "string",  "description": "low | medium | high", "enum": ["low","medium","high"]}
            },
            "required": ["file_path", "old_code", "new_code", "reason"]
        }

    async def execute(self, file_path: str = "", old_code: str = "", new_code: str = "",
                      reason: str = "", severity: str = "medium", **kw) -> str:
        try:
            if not old_code.strip():
                return (
                    "Cannot propose fix: old_code is empty. "
                    "Use read_code to get the exact text you want to replace, then resubmit."
                )
            if not new_code.strip():
                return (
                    "Cannot propose fix: new_code is empty. "
                    "Provide the replacement code, then resubmit."
                )
            if not reason.strip():
                return "Cannot propose fix: reason is required."
            full = BASE_DIR / file_path
            if not full.exists():
                # Fuzzy fallback: search by basename
                target = Path(file_path).name
                _SKIP = {'__pycache__', '.git', 'node_modules', 'chromadb', 'uploads'}
                matches = [
                    p for p in BASE_DIR.rglob(target)
                    if not any(part in _SKIP for part in p.parts)
                ]
                if not matches:
                    return f"Cannot propose fix: file not found: {file_path}"
                full = matches[0]
                file_path = str(full.relative_to(BASE_DIR))
            content = full.read_text(encoding="utf-8", errors="replace")
            if old_code not in content:
                return (
                    "Cannot propose fix: old_code not found verbatim in file. "
                    "Use read_code to get the exact text, then resubmit."
                )
            fix_id = str(uuid.uuid4())[:8]
            entry = {
                "fix_id":    fix_id,
                "file_path": file_path,
                "old_code":  old_code,
                "new_code":  new_code,
                "reason":    reason,
                "severity":  severity,
                "status":    "pending_review",
                "proposed_by": "tinker",
                "proposed_at": datetime.now().isoformat(),
                "reviewed_by": None,
                "applied_at":  None
            }
            q = _load_queue()
            q.append(entry)
            _save_queue(q)

            # Notify Aetheria via message bus
            try:
                from core.message_bus import message_bus
                import asyncio
                msg = (
                    f"[SELF-HEAL REVIEW REQUIRED]\n"
                    f"Fix ID: {fix_id}\n"
                    f"File: {file_path}\n"
                    f"Severity: {severity}\n"
                    f"Reason: {reason}\n\n"
                    f"OLD:\n{old_code[:400]}\n\nNEW:\n{new_code[:400]}\n\n"
                    f"Reply: approve_fix({fix_id}) or reject_fix({fix_id}, reason)"
                )
                asyncio.create_task(
                    message_bus.send_message("tinker", "aetheria", msg)
                )
            except Exception:
                pass

            # Telegram notification with inline approve/reject buttons
            try:
                _tg_notify_fix(fix_id, file_path, severity, reason, old_code, new_code)
            except Exception:
                pass

            return (
                f"Fix {fix_id} submitted for Aetheria review.\n"
                f"File: {file_path} | Severity: {severity}\n"
                f"Reason: {reason}\n"
                f"Status: pending_review"
            )
        except Exception as ex:
            return f"ProposeFixTool error: {ex}"


# ---------------------------------------------------------------------------
class ApplyFixTool(Tool):
    """
    Aetheria uses this to apply a Tinker-proposed fix after review.
    Only call this after you have evaluated the fix and determined it is safe.
    """

    @property
    def name(self): return "apply_fix"

    @property
    def description(self):
        return (
            "Apply a Tinker-proposed fix that has been reviewed and approved. "
            "Provide the fix_id from the review queue. "
            "Only call this after you have read and verified the change is correct and safe."
        )

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {
                "fix_id":    {"type": "string", "description": "The fix ID from the review queue"},
                "approver":  {"type": "string", "description": "Who approved: 'aetheria' or 'jon'"}
            },
            "required": ["fix_id"]
        }

    async def execute(self, fix_id: str = "", approver: str = "aetheria", **kw) -> str:
        try:
            q = _load_queue()
            entry = next((e for e in q if e["fix_id"] == fix_id), None)
            if not entry:
                return f"Fix {fix_id} not found in review queue."
            if entry["status"] == "applied":
                return f"Fix {fix_id} already applied."

            full = BASE_DIR / entry["file_path"]
            if not full.exists():
                return f"File not found: {entry['file_path']}"

            content = full.read_text(encoding="utf-8", errors="replace")
            if entry["old_code"] not in content:
                entry["status"] = "stale"
                _save_queue(q)
                return f"Fix {fix_id} is stale — the old_code no longer exists in the file (may have already been fixed)."

            new_content = content.replace(entry["old_code"], entry["new_code"], 1)
            full.write_text(new_content, encoding="utf-8")

            entry["status"]      = "applied"
            entry["reviewed_by"] = approver
            entry["applied_at"]  = datetime.now().isoformat()
            _save_queue(q)

            print(f"[Self-Heal] Fix {fix_id} applied to {entry['file_path']} by {approver}")
            return (
                f"Fix {fix_id} applied successfully.\n"
                f"File: {entry['file_path']}\n"
                f"Approved by: {approver}\n"
                f"Reason: {entry['reason']}"
            )
        except Exception as ex:
            return f"ApplyFixTool error: {ex}"


# ---------------------------------------------------------------------------
class ReviewQueueTool(Tool):
    """Read the current self-heal review queue."""

    @property
    def name(self): return "review_queue"

    @property
    def description(self):
        return "List all pending self-heal fixes waiting for Aetheria review."

    @property
    def parameters(self):
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, **kw) -> str:
        q = _load_queue()
        pending = [e for e in q if e["status"] == "pending_review"]
        if not pending:
            return "No fixes pending review."
        lines = []
        for e in pending:
            lines.append(
                f"[{e['fix_id']}] {e['file_path']} | {e['severity']} | {e['proposed_at'][:16]}\n"
                f"  Reason: {e['reason']}\n"
                f"  OLD: {e['old_code'][:80]}...\n"
                f"  NEW: {e['new_code'][:80]}..."
            )
        return "PENDING FIXES:\n\n" + "\n\n".join(lines)
