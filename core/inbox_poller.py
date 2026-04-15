"""
SOVERYN Inbox Poller
Background thread per agent — polls the typed inbox in agent_message_board.db
and drives the agent loop when messages arrive.

Poll intervals (seconds):
  Aetheria — 30s  (decision layer, needs fast response)
  Tinker   — 60s  (acts on tasks, inference is slow)
  Vett     — 60s
  Scout    — 90s
  Ares     — 120s (mostly event-driven; polls as fallback)
"""

import asyncio
import threading
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

POLL_INTERVALS = {
    'aetheria': 30,
    'tinker':   60,
    'vett':     60,
    'scout':    90,
    'ares':    120,
}

# Startup delay — give models time to load before first poll
STARTUP_DELAY = 90


class InboxPoller:
    """
    Background daemon thread that polls an agent's inbox and triggers
    the agent loop when new messages arrive.
    """

    def __init__(self, agent_name: str, agent_loop):
        self.agent_name = agent_name
        self.agent_loop = agent_loop
        self._running = False
        self._thread: threading.Thread = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(
            target=self._run,
            name=f"inbox-{self.agent_name}",
            daemon=True,
        )
        self._thread.start()
        print(f"[Inbox] Poller started for {self.agent_name}", flush=True)

    def stop(self):
        self._running = False

    # ──────────────────────────────────────────────
    # Internal
    # ──────────────────────────────────────────────

    def _run(self):
        time.sleep(STARTUP_DELAY)
        interval = POLL_INTERVALS.get(self.agent_name, 60)
        while self._running:
            try:
                self._check_and_process()
            except Exception as e:
                print(f"[Inbox] {self.agent_name} poll error: {e}", flush=True)
            time.sleep(interval)

    def _check_and_process(self):
        from agent_message_board import get_inbox, update_status
        all_messages = get_inbox(self.agent_name, unread_only=True, limit=10)
        if not all_messages:
            return

        # Skip response-type messages — agents reply via tools if they choose to,
        # not via automatic poller replies. Processing responses automatically creates
        # infinite Aetheria ↔ Tinker loops.
        messages = [m for m in all_messages if m.get('message_type') != 'response']

        # Mark everything read (including skipped responses) so they don't accumulate
        for msg in all_messages:
            update_status(msg['id'], 'read')

        if not messages:
            return

        # Build prompt
        prompt = self._format_prompt(messages)
        print(f"[Inbox] {self.agent_name} processing {len(messages)} message(s)", flush=True)

        # Run through agent loop (synchronous call from thread)
        try:
            response = asyncio.run(self.agent_loop.process_message(prompt))
        except Exception as e:
            print(f"[Inbox] {self.agent_name} inference error: {e}", flush=True)
            return

        if not response:
            return

        # No automatic replies — agents use send_message tool if they need to respond.
        # Auto-replies caused runaway Aetheria ↔ Tinker inbox loops.

        # Store decision in Lattice memory
        self._store_lattice(messages, response)

        # Mirror to agent's board file so the UI board tab reflects inbox activity
        self._mirror_to_board(messages)

    def _format_prompt(self, messages: list) -> str:
        parts = []
        for msg in messages:
            subject = msg.get('subject') or ''
            body    = msg.get('message', '')
            sender  = msg.get('from_agent', 'unknown')
            mtype   = msg.get('message_type', 'message')
            priority = msg.get('priority', 'normal')
            priority_tag = f" [PRIORITY: {priority.upper()}]" if priority in ('high', 'alert', 'urgent') else ''
            subj_line = f"Subject: {subject}\n" if subject else ''
            parts.append(
                f"[INBOX — {mtype.upper()} from {sender.upper()}{priority_tag}]\n"
                f"{subj_line}{body}"
            )
        return "[INBOX — respond to each message below]\n\n" + "\n\n".join(parts)

    def _store_lattice(self, messages: list, response: str):
        try:
            from tools.lattice_tool import LatticeTool
            lattice_tool = LatticeTool(self.agent_name)
            summary = (
                f"Inbox ({len(messages)} msg): "
                f"{messages[0].get('subject') or messages[0]['message'][:80]} "
                f"→ {response[:120]}"
            )
            asyncio.run(lattice_tool.execute(
                action='remember',
                content=summary,
                node_type='inbox_decision',
                intensity='default',
                tags=['inbox', messages[0].get('message_type', 'message')],
            ))
        except Exception as e:
            print(f"[Inbox] Lattice store error: {e}", flush=True)

    def _mirror_to_board(self, messages: list):
        """Write a brief summary line to the agent's .md board so the UI shows it."""
        try:
            from pathlib import Path
            from datetime import datetime
            boards_dir = Path(__file__).parent.parent / 'soveryn_memory' / 'boards'
            boards_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y-%m-%d %H:%M")
            for msg in messages:
                sender = msg.get('from_agent', '?')
                mtype  = msg.get('message_type', 'msg')
                subj   = msg.get('subject') or msg['message'][:60]
                line   = f"\n- **{self.agent_name.upper()} [{ts}]:** [inbox/{mtype} from {sender}] {subj}\n"
                bp = boards_dir / f"{self.agent_name}.md"
                with open(bp, 'a', encoding='utf-8') as f:
                    f.write(line)
        except Exception:
            pass
