"""
SOVERYN Self-Heal Monitor
Watches for Python errors and dispatches Tinker to fix them.
Aetheria has oversight — she reviews every proposed fix before it's applied.
If a fix is risky, Aetheria escalates to Jon via Telegram.
"""
import sys
import json
import asyncio
import threading
import traceback
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

BASE_DIR   = Path(__file__).parent.parent
ERROR_LOG  = BASE_DIR / "soveryn_memory" / "error_queue.json"
REVIEW_LOG = BASE_DIR / "soveryn_memory" / "heal_review_queue.json"
ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)

# Files Tinker is NOT allowed to propose fixes for (security boundary)
PROTECTED_FILES = {
    "app.py",           # main Flask app — too risky to auto-patch
    "sovereign_backend.py",
    "config.py",
    ".env",
}

# Aetheria auto-approves fixes that touch <= this many lines and are low severity
AUTO_APPROVE_MAX_LINES = 15


def _load_errors():
    try:
        return json.loads(ERROR_LOG.read_text()) if ERROR_LOG.exists() else []
    except Exception:
        return []


def _save_errors(q):
    ERROR_LOG.write_text(json.dumps(q, indent=2))


def log_error(error_type: str, message: str, file_path: str = "", traceback_str: str = "", source: str = "runtime"):
    """Log an error to the queue for Tinker to pick up."""
    entry = {
        "error_id":   f"err_{int(time.time())}",
        "error_type": error_type,
        "message":    message,
        "file_path":  file_path,
        "traceback":  traceback_str,
        "source":     source,
        "timestamp":  datetime.now().isoformat(),
        "status":     "pending"
    }
    q = _load_errors()
    # De-duplicate: skip if same error logged in last 5 minutes
    recent = [e for e in q if e["message"] == message and e["status"] == "pending"]
    if recent:
        return
    q.append(entry)
    _save_errors(q)
    print(f"[Self-Heal] Error logged for Tinker: {error_type}: {message[:80]}")


def _install_exception_hook():
    """Install a global exception handler that feeds the error queue."""
    original_hook = sys.excepthook

    def custom_hook(exc_type, exc_value, exc_tb):
        tb_str = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        # Extract file from traceback
        file_path = ""
        for line in tb_str.splitlines():
            if 'File "' in line and BASE_DIR.name in line:
                try:
                    raw = line.split('File "')[1].split('"')[0]
                    p = Path(raw)
                    file_path = str(p.relative_to(BASE_DIR))
                except Exception:
                    pass
        log_error(
            error_type=exc_type.__name__,
            message=str(exc_value),
            file_path=file_path,
            traceback_str=tb_str,
            source="exception_hook"
        )
        original_hook(exc_type, exc_value, exc_tb)

    sys.excepthook = custom_hook


class SelfHealMonitor:
    """
    Background thread that:
    1. Polls the error queue every 60 seconds
    2. Dispatches Tinker to analyze and propose fixes
    3. Routes proposed fixes to Aetheria for review
    4. Aetheria auto-approves safe fixes or escalates to Jon via Telegram
    """

    def __init__(self, agent_loops_dict: dict, telegram_token: str = "", telegram_chat_id: str = ""):
        self.agent_loops   = agent_loops_dict
        self.tg_token      = telegram_token
        self.tg_chat_id    = telegram_chat_id
        self._stop         = threading.Event()
        self._thread       = threading.Thread(target=self._run, daemon=True, name="SelfHealMonitor")

    def start(self):
        _install_exception_hook()
        self._thread.start()
        print("[Self-Heal] Monitor started — Tinker is watching for errors")

    def stop(self):
        self._stop.set()

    # ------------------------------------------------------------------
    def _run(self):
        while not self._stop.is_set():
            try:
                self._cycle()
            except Exception as ex:
                print(f"[Self-Heal] Monitor cycle error: {ex}")
            self._stop.wait(60)

    def _cycle(self):
        # Always drain the review queue first — fixes may be waiting from previous cycles
        self._aetheria_oversight()

        errors = _load_errors()
        pending = [e for e in errors if e["status"] == "pending"]
        if not pending:
            return

        tinker = self.agent_loops.get("tinker")
        if not tinker:
            return

        for error in pending[:3]:   # Process up to 3 errors per cycle
            self._dispatch_tinker(tinker, error)
            error["status"] = "dispatched"

        _save_errors(errors)

    def _dispatch_tinker(self, tinker, error: dict):
        """Send Tinker the error context and ask it to propose a fix."""
        file_context = ""
        if error.get("file_path"):
            fp = BASE_DIR / error["file_path"]
            if fp.exists() and fp.name not in PROTECTED_FILES:
                try:
                    lines = fp.read_text(encoding="utf-8", errors="replace").splitlines()
                    # Include up to 80 lines around the error area
                    numbered = "\n".join(f"{i+1:4d} | {l}" for i, l in enumerate(lines[:120]))
                    file_context = f"\n\nFILE CONTENT ({error['file_path']}):\n{numbered}"
                except Exception:
                    pass

        prompt = (
            f"[SELF-HEAL TASK]\n"
            f"An error was detected in the SOVERYN system. Your job is to diagnose it and propose a fix.\n\n"
            f"ERROR TYPE: {error['error_type']}\n"
            f"MESSAGE: {error['message']}\n"
            f"FILE: {error.get('file_path', 'unknown')}\n"
            f"SOURCE: {error.get('source', 'runtime')}\n\n"
            f"TRACEBACK:\n{error.get('traceback', '')[:1000]}"
            f"{file_context}\n\n"
            f"INSTRUCTIONS:\n"
            f"1. Use read_code to inspect the relevant file if you need more context\n"
            f"2. Identify the exact cause of the error\n"
            f"3. Use propose_fix to submit your fix — provide the exact old_code and new_code\n"
            f"4. Set severity: low for 1-3 line changes, medium for logic changes, high for anything structural\n"
            f"If the file is protected or you cannot safely fix it, explain why and stop."
        )

        try:
            loop = asyncio.new_event_loop()
            response = loop.run_until_complete(
                tinker.process_message(prompt, conversation_history=[], temperature=0.3, max_tokens=1500)
            )
            loop.close()
            print(f"[Self-Heal] Tinker responded to error {error['error_id']}: {response[:120]}")

            # Now route to Aetheria for oversight
            self._aetheria_oversight()

        except Exception as ex:
            print(f"[Self-Heal] Tinker dispatch error: {ex}")

    def _aetheria_oversight(self):
        """
        Review pipeline: Ares (security) → Aetheria (logic/oversight) → apply or escalate to Jon.
        - Ares vets every fix for security implications first
        - Aetheria reviews logic correctness and approves/rejects
        - High severity or large changes always ping Jon via Telegram
        """
        try:
            fixes = json.loads(REVIEW_LOG.read_text()) if REVIEW_LOG.exists() else []
        except Exception:
            return

        pending = [f for f in fixes if f["status"] == "pending_review"]
        if not pending:
            return

        ares     = self.agent_loops.get("ares")
        aetheria = self.agent_loops.get("aetheria")

        for fix in pending:
            old_lines = fix["old_code"].count("\n") + 1
            new_lines = fix["new_code"].count("\n") + 1
            change_size = max(old_lines, new_lines)
            is_protected = Path(fix["file_path"]).name in PROTECTED_FILES

            if is_protected:
                fix["status"] = "rejected"
                fix["reviewed_by"] = "aetheria"
                self._telegram(
                    f"[SOVERYN] Tinker attempted to fix a PROTECTED file:\n"
                    f"File: {fix['file_path']}\nReason: {fix['reason']}\n"
                    f"Fix rejected automatically — requires your direct review."
                )
                continue

            # Step 1 — Ares security review
            ares_cleared = True
            if ares:
                ares_prompt = (
                    f"[SECURITY REVIEW] Tinker proposed a code fix. Your job is to identify any security risk.\n\n"
                    f"Fix ID: {fix['fix_id']}\n"
                    f"File: {fix['file_path']}\n"
                    f"Severity: {fix['severity']}\n"
                    f"Reason: {fix['reason']}\n\n"
                    f"OLD CODE:\n{fix['old_code']}\n\n"
                    f"NEW CODE:\n{fix['new_code']}\n\n"
                    f"Assess: does this fix introduce any injection vulnerability, path traversal, "
                    f"privilege escalation, data exfiltration risk, or unintended code execution path?\n"
                    f"Respond with CLEARED if it is safe, or BLOCKED: <reason> if you identify a risk.\n"
                    f"Be concise — one word verdict, then brief reasoning."
                )
                try:
                    ev_loop = asyncio.new_event_loop()
                    ares_response = ev_loop.run_until_complete(
                        ares.process_message(ares_prompt, conversation_history=[], temperature=0.1, max_tokens=300)
                    )
                    ev_loop.close()
                    print(f"[Self-Heal] Ares security verdict for {fix['fix_id']}: {ares_response[:120]}")
                    if ares_response and ares_response.strip().upper().startswith("BLOCKED"):
                        ares_cleared = False
                        fix["status"] = "rejected"
                        fix["reviewed_by"] = "ares"
                        fix["ares_verdict"] = ares_response[:400]
                        self._telegram(
                            f"[SOVERYN SECURITY] Ares BLOCKED a proposed fix.\n"
                            f"Fix ID: {fix['fix_id']}\n"
                            f"File: {fix['file_path']}\n"
                            f"Ares verdict: {ares_response[:300]}\n"
                            f"Fix has been rejected. Your review may still be warranted."
                        )
                except Exception as ex:
                    print(f"[Self-Heal] Ares security review error: {ex}")

            if not ares_cleared:
                continue

            # Step 2 — Aetheria logic and oversight review
            if aetheria:
                review_prompt = (
                    f"[OVERSIGHT REVIEW] Tinker proposed a code fix. Ares cleared it for security. "
                    f"Your job is logic correctness and system integrity.\n\n"
                    f"Fix ID: {fix['fix_id']}\n"
                    f"File: {fix['file_path']}\n"
                    f"Severity: {fix['severity']}\n"
                    f"Reason: {fix['reason']}\n\n"
                    f"OLD CODE:\n{fix['old_code']}\n\n"
                    f"NEW CODE:\n{fix['new_code']}\n\n"
                    f"If this fix is correct and safe, use apply_fix(fix_id='{fix['fix_id']}', approver='aetheria').\n"
                    f"If you are unsure or it touches critical logic, flag it — do not apply.\n"
                    f"Do not apply if you detect any logic regression or unintended side effects."
                )
                try:
                    ev_loop = asyncio.new_event_loop()
                    ev_loop.run_until_complete(
                        aetheria.process_message(review_prompt, conversation_history=[], temperature=0.2, max_tokens=800)
                    )
                    ev_loop.close()
                except Exception as ex:
                    print(f"[Self-Heal] Aetheria review error: {ex}")

            # Always ping Jon for high severity or large changes
            if fix["severity"] == "high" or change_size > AUTO_APPROVE_MAX_LINES:
                self._telegram(
                    f"[SOVERYN SELF-HEAL] Tinker proposed a {fix['severity']} fix.\n"
                    f"Fix ID: {fix['fix_id']}\n"
                    f"File: {fix['file_path']}\n"
                    f"Reason: {fix['reason']}\n\n"
                    f"Ares: CLEARED | Aetheria reviewing. You may need to approve at /approve_{fix['fix_id']}"
                )

        REVIEW_LOG.write_text(json.dumps(fixes, indent=2))

    def _telegram(self, text: str):
        """Send a Telegram notification to Jon."""
        if not self.tg_token or not self.tg_chat_id:
            return
        try:
            import urllib.request
            url = f"https://api.telegram.org/bot{self.tg_token}/sendMessage"
            data = json.dumps({"chat_id": self.tg_chat_id, "text": text, "parse_mode": "HTML"}).encode()
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=10)
        except Exception as ex:
            print(f"[Self-Heal] Telegram error: {ex}")
