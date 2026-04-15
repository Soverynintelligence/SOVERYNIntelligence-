"""
inbox_tool.py
Scout's personal email management tool — reads Jon's Gmail inbox via IMAP,
creates labels, archives messages, and flags priority items.
"""
import imaplib
import email
import os
import re
from email.header import decode_header
from typing import Any, Dict, List, Optional
from core.tool_base import Tool

# Patterns that identify trash/junk automatically
_TRASH_SENDERS = [
    'noreply', 'no-reply', 'donotreply', 'do-not-reply', 'mailer-daemon',
    'notifications@', 'newsletter@', 'news@', 'updates@', 'promo@',
    'promotions@', 'marketing@', 'offers@', 'deals@', 'info@',
    'support@', 'hello@', 'team@', 'automated@', 'alert@',
]
_TRASH_SUBJECT_KEYWORDS = [
    'unsubscribe', 'newsletter', 'weekly digest', 'monthly digest',
    'special offer', '% off', 'flash sale', 'limited time', 'act now',
    'you have been selected', 'congratulations', 'winner', 'prize',
    'verify your email', 'confirm your subscription', 'opt out',
    'order confirmation', 'your receipt', 'invoice #', 'payment received',
    'shipping update', 'your order', 'has shipped', 'out for delivery',
    'tracking number', 'delivery confirmation',
    'new login', 'sign-in attempt', 'security alert from google',
]

def _is_trash(sender: str, subject: str) -> bool:
    """Heuristic: return True if email looks like automated noise."""
    s = sender.lower()
    sub = subject.lower()
    if any(p in s for p in _TRASH_SENDERS):
        return True
    if any(k in sub for k in _TRASH_SUBJECT_KEYWORDS):
        return True
    return False


def _load_credentials():
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))
    except ImportError:
        pass
    return os.environ.get('JON_EMAIL', ''), os.environ.get('JON_EMAIL_PASSWORD', '')


def _decode_header_str(value: str) -> str:
    if not value:
        return ''
    parts = decode_header(value)
    decoded = []
    for part, enc in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(enc or 'utf-8', errors='replace'))
        else:
            decoded.append(str(part))
    return ' '.join(decoded)


def _get_body(msg) -> str:
    """Extract plain text body from email message."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == 'text/plain':
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode('utf-8', errors='replace')[:500]
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            return payload.decode('utf-8', errors='replace')[:500]
    return ''


def _connect() -> imaplib.IMAP4_SSL:
    email_addr, password = _load_credentials()
    if not email_addr or not password:
        raise ValueError("JON_EMAIL or JON_EMAIL_PASSWORD not configured in .env")
    conn = imaplib.IMAP4_SSL('imap.gmail.com', 993)
    conn.login(email_addr, password)
    return conn


class InboxTool(Tool):
    """
    Manage Jon's personal Gmail inbox.
    Read emails, create labels, archive, flag priority items.
    """

    @property
    def name(self) -> str:
        return "inbox"

    @property
    def description(self) -> str:
        return """Manage Jon's personal Gmail inbox. Actions:

read        — read recent emails from inbox (returns sender, subject, date, snippet)
fetch       — fetch full email by UID
label       — create a Gmail label (folder)
move        — move email to a label/folder
archive     — archive an email (remove from inbox)
flag        — mark email as important/priority
search      — search inbox by query string
list_labels — list all existing Gmail labels
batch_triage — bulk process a batch of emails: auto-move obvious trash to JUNK folder,
               return summary of what remains for manual review. Use offset to page
               through the full inbox in chunks.
"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["read", "fetch", "label", "move", "archive", "flag", "search", "list_labels"],
                    "description": "What to do"
                },
                "count": {
                    "type": "integer",
                    "description": "For read: number of emails to fetch (default 20)"
                },
                "uid": {
                    "type": "string",
                    "description": "For fetch/move/archive/flag: email UID"
                },
                "label_name": {
                    "type": "string",
                    "description": "For label/move: label name to create or move to"
                },
                "query": {
                    "type": "string",
                    "description": "For search: Gmail search query (e.g. 'from:amazon.com', 'subject:invoice')"
                },
                "folder": {
                    "type": "string",
                    "description": "For read/search: mailbox folder to operate on (default: INBOX)"
                },
                "batch_size": {
                    "type": "integer",
                    "description": "For batch_triage: number of emails to process per run (default 100)"
                },
                "offset": {
                    "type": "integer",
                    "description": "For batch_triage: skip this many emails from the oldest end (default 0, use to page through inbox)"
                }
            },
            "required": ["action"]
        }

    async def execute(self, action: str = "read", count: int = 20, uid: str = "",
                      label_name: str = "", query: str = "", folder: str = "INBOX",
                      batch_size: int = 50, offset: int = 0,
                      **kwargs) -> str:
        # Strip accidental brackets the model may copy from display output (e.g. "[5]" → "5")
        uid = uid.strip('[]') if uid else uid
        try:
            if action == "read":
                return self._read(count, folder)
            elif action == "fetch":
                return self._fetch(uid, folder)
            elif action == "label":
                return self._create_label(label_name)
            elif action == "move":
                return self._move(uid, label_name, folder)
            elif action == "archive":
                return self._archive(uid, folder)
            elif action == "flag":
                return self._flag(uid, folder)
            elif action == "search":
                return self._search(query, folder)
            elif action == "list_labels":
                return self._list_labels()
            elif action == "batch_triage":
                return self._batch_triage(batch_size, offset)
            else:
                return f"Unknown action: {action}"
        except Exception as e:
            return f"Inbox error: {e}"

    def _read(self, count: int, folder: str) -> str:
        conn = _connect()
        try:
            conn.select(folder, readonly=True)
            _, data = conn.search(None, 'ALL')
            uids = data[0].split()
            recent = uids[-count:] if len(uids) > count else uids
            recent = list(reversed(recent))  # newest first

            results = []
            for uid in recent:
                _, msg_data = conn.fetch(uid, '(RFC822.SIZE BODY[HEADER.FIELDS (FROM SUBJECT DATE)])')
                if not msg_data or not msg_data[0]:
                    continue
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)
                sender  = _decode_header_str(msg.get('From', ''))[:60]
                subject = _decode_header_str(msg.get('Subject', '(no subject)'))[:80]
                date    = msg.get('Date', '')[:30]
                results.append(f"uid={uid.decode()} | {date}\n  From: {sender}\n  Subject: {subject}")

            return f"Inbox ({len(results)} of {len(uids)} total):\n\n" + "\n\n".join(results)
        finally:
            conn.logout()

    def _fetch(self, uid: str, folder: str) -> str:
        if not uid:
            return "Error: uid required for fetch"
        conn = _connect()
        try:
            conn.select(folder, readonly=True)
            _, msg_data = conn.fetch(uid.encode(), '(RFC822)')
            if not msg_data or not msg_data[0]:
                return f"Email {uid} not found"
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)
            sender  = _decode_header_str(msg.get('From', ''))
            subject = _decode_header_str(msg.get('Subject', '(no subject)'))
            date    = msg.get('Date', '')
            body    = _get_body(msg)
            return f"From: {sender}\nDate: {date}\nSubject: {subject}\n\n{body}"
        finally:
            conn.logout()

    def _create_label(self, label_name: str) -> str:
        if not label_name:
            return "Error: label_name required"
        conn = _connect()
        try:
            result, _ = conn.create(f'"{label_name}"')
            if result == 'OK':
                return f"Label '{label_name}' created."
            return f"Label may already exist or creation failed (result: {result})"
        finally:
            conn.logout()

    def _move(self, uid: str, label_name: str, folder: str) -> str:
        if not uid or not label_name:
            return "Error: uid and label_name required for move"
        conn = _connect()
        try:
            conn.select(folder)
            conn.copy(uid.encode(), f'"{label_name}"')
            conn.store(uid.encode(), '+FLAGS', '\\Deleted')
            conn.expunge()
            return f"Email {uid} moved to '{label_name}'."
        finally:
            conn.logout()

    def _archive(self, uid: str, folder: str) -> str:
        if not uid:
            return "Error: uid required for archive"
        conn = _connect()
        try:
            conn.select(folder)
            # Gmail archive = move to [Gmail]/All Mail, remove Inbox label
            conn.copy(uid.encode(), '"[Gmail]/All Mail"')
            conn.store(uid.encode(), '+FLAGS', '\\Deleted')
            conn.expunge()
            return f"Email {uid} archived."
        finally:
            conn.logout()

    def _flag(self, uid: str, folder: str) -> str:
        if not uid:
            return "Error: uid required for flag"
        conn = _connect()
        try:
            conn.select(folder)
            conn.store(uid.encode(), '+FLAGS', '\\Flagged')
            return f"Email {uid} flagged as priority."
        finally:
            conn.logout()

    def _search(self, query: str, folder: str) -> str:
        if not query:
            return "Error: query required for search"
        conn = _connect()
        try:
            conn.select(folder, readonly=True)
            # Convert simple query to IMAP search criteria
            search_criteria = f'SUBJECT "{query}"' if not query.startswith('from:') else f'FROM "{query[5:]}"'
            _, data = conn.search(None, search_criteria)
            uids = data[0].split()
            if not uids:
                return f"No emails found matching: {query}"

            results = []
            for uid in list(reversed(uids))[:20]:
                _, msg_data = conn.fetch(uid, '(BODY[HEADER.FIELDS (FROM SUBJECT DATE)])')
                if not msg_data or not msg_data[0]:
                    continue
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)
                sender  = _decode_header_str(msg.get('From', ''))[:60]
                subject = _decode_header_str(msg.get('Subject', '(no subject)'))[:80]
                date    = msg.get('Date', '')[:30]
                results.append(f"uid={uid.decode()} | {date}\n  From: {sender}\n  Subject: {subject}")

            return f"Found {len(uids)} email(s) matching '{query}':\n\n" + "\n\n".join(results)
        finally:
            conn.logout()

    def _list_labels(self) -> str:
        conn = _connect()
        try:
            _, labels = conn.list()
            result = []
            for label in labels:
                if label:
                    decoded = label.decode() if isinstance(label, bytes) else str(label)
                    parts = decoded.split('"/"')
                    name = parts[-1].strip().strip('"') if parts else decoded
                    result.append(name)
            return "Gmail labels:\n" + "\n".join(sorted(result))
        finally:
            conn.logout()

    def _batch_triage(self, batch_size: int, offset: int) -> str:
        """
        Process a batch of emails: auto-move obvious trash to JUNK label,
        return a summary of what remains for manual review.
        """
        conn = _connect()
        try:
            # Ensure JUNK label exists
            conn.create('"JUNK"')
        except Exception:
            pass

        try:
            conn.select('INBOX')
            _, data = conn.search(None, 'ALL')
            all_uids = data[0].split()
            total = len(all_uids)

            # Page through oldest-first using offset
            start = offset
            end   = min(offset + batch_size, total)
            batch = all_uids[start:end]

            if not batch:
                return f"No emails in range (offset={offset}, total={total}). Inbox fully processed."

            junked    = 0
            kept      = []

            for uid in batch:
                try:
                    _, msg_data = conn.fetch(uid, '(BODY[HEADER.FIELDS (FROM SUBJECT)])')
                    if not msg_data or not msg_data[0]:
                        continue
                    raw = msg_data[0][1]
                    msg = email.message_from_bytes(raw)
                    sender  = _decode_header_str(msg.get('From', ''))
                    subject = _decode_header_str(msg.get('Subject', ''))

                    if _is_trash(sender, subject):
                        # Move to JUNK
                        conn.copy(uid, '"JUNK"')
                        conn.store(uid, '+FLAGS', '\\Deleted')
                        junked += 1
                    else:
                        kept.append(f"  uid={uid.decode()} | {sender[:50]} — {subject[:60]}")
                except Exception:
                    continue

            conn.expunge()

            next_offset = end
            remaining   = total - next_offset
            done = remaining == 0

            summary = (
                f"Batch {start}–{end} of {total} total.\n"
                f"Junked: {junked} | Kept for review: {len(kept)}\n"
            )
            if kept:
                summary += "Emails kept (need review):\n" + "\n".join(kept[:15])
                if len(kept) > 15:
                    summary += f"\n  ...and {len(kept)-15} more in this batch."
                summary += "\n"
            if done:
                summary += "\nINBOX FULLY PROCESSED. No more batches."
            else:
                summary += f"\nREMAINING: {remaining} emails. MUST call: batch_triage(offset={next_offset})"
            return summary
        finally:
            conn.logout()
