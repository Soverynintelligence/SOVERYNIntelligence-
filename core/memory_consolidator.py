"""
Memory Consolidator — synthesizes all agent logs into a structured knowledge base.

Runs in two passes:
  1. Fast pass (rule-based): extracts facts from recent logs without inference
  2. Synthesis pass (model-based): uses Tinker to review + consolidate (runs when agents idle)

Output: ~/.soveryn/workspace/knowledge.json
Injection: compact summary string injected into all agent contexts
"""
import json
import os
import re
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

WORKSPACE = Path.home() / '.soveryn' / 'workspace'
KNOWLEDGE_FILE = WORKSPACE / 'knowledge.json'
MEMORY_DIR = Path(__file__).parent.parent / 'soveryn_memory' / 'memory'

_BLANK_KNOWLEDGE = {
    "user": {
        "name": "Jon",
        "style": "direct, no filler, casual",
        "facts": []
    },
    "projects": {},
    "agent_findings": {
        "aetheria": [],
        "scout": [],
        "vett": [],
        "tinker": [],
        "ares": []
    },
    "global_facts": [],
    "last_consolidated": None,
    "consolidation_count": 0
}

# ─── I/O ──────────────────────────────────────────────────────────────────────

def load_knowledge() -> Dict:
    try:
        if KNOWLEDGE_FILE.exists():
            return json.loads(KNOWLEDGE_FILE.read_text(encoding='utf-8'))
    except Exception:
        pass
    return json.loads(json.dumps(_BLANK_KNOWLEDGE))


def save_knowledge(data: Dict):
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    KNOWLEDGE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')


# ─── LOG READING ──────────────────────────────────────────────────────────────

def _strip_think(text: str) -> str:
    text = re.sub(r'<think>[\s\S]*?</think>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<think>[\s\S]*', '', text, flags=re.IGNORECASE)
    return text.strip()


def _read_logs(days: int = 3) -> List[Dict]:
    """Return list of {date, agent, role, content} dicts from recent logs."""
    cutoff = datetime.now() - timedelta(days=days)
    entries = []

    if not MEMORY_DIR.exists():
        return entries

    for log_file in sorted(MEMORY_DIR.glob("*.md")):
        try:
            date_str = log_file.stem[:10]
            file_date = datetime.strptime(date_str, "%Y-%m-%d")
            if file_date < cutoff.replace(hour=0, minute=0, second=0):
                continue
        except ValueError:
            continue

        text = log_file.read_text(encoding='utf-8', errors='ignore')
        # Parse ## HH:MM blocks
        blocks = re.split(r'^## \d{2}:\d{2}', text, flags=re.MULTILINE)
        for block in blocks:
            block = block.strip()
            if not block:
                continue
            # Extract Jon and agent turns
            for match in re.finditer(r'\*\*(Jon|[\w]+):\*\*\s*([\s\S]*?)(?=\*\*[\w]+:\*\*|$)', block):
                speaker = match.group(1).strip()
                content = _strip_think(match.group(2).strip())
                if not content or len(content) < 10:
                    continue
                role = 'user' if speaker.lower() == 'jon' else 'agent'
                entries.append({
                    'date': date_str,
                    'speaker': speaker.lower(),
                    'role': role,
                    'content': content[:500]
                })

    return entries


# ─── FAST PASS (RULE-BASED EXTRACTION) ────────────────────────────────────────

_PREF_PATTERNS = [
    r"i (?:prefer|want|like|need|don'?t (?:want|like)|hate)\s+(.{5,80})",
    r"(?:always|never) (?:use|do|say|respond)\s+(.{5,80})",
    r"my (?:name is|project is|goal is)\s+(.{5,80})",
]

_PROJECT_PATTERNS = [
    r"(?:project|working on|building|fixing)\s+([A-Z][\w\s]{2,40})",
    r"([A-Z][\w]+)\s+is\s+(?:done|complete|broken|working|ready)",
]

def _extract_from_logs(entries: List[Dict]) -> Dict:
    """Rule-based extraction — fast, no inference needed."""
    user_facts = set()
    project_hints = set()
    agent_findings = {k: [] for k in _BLANK_KNOWLEDGE['agent_findings']}

    for entry in entries:
        text = entry['content'].lower()

        if entry['role'] == 'user':
            # Skip fast-pass user fact extraction — too noisy (catches instructions to Scout, etc.)
            # Tinker synthesis pass handles user facts with actual inference
            pass

        elif entry['role'] == 'agent':
            agent = entry['speaker']
            if agent in agent_findings:
                # Only store positive/concrete findings — skip failure messages and partial thoughts
                failure_signals = [
                    'no contact', 'no dealers', 'not found', 'no direct', 'no names',
                    'unable to', 'failed to', 'could not', 'no results', 'no email',
                    'no phone', 'we need to consider', 'let\'s proceed', 'next steps',
                    'here are some options', 'please provide', 'could you provide',
                    'mix-up', 'seems there was', 'i\'ll roll with', 'pretty wild',
                ]
                is_failure = any(sig in text for sig in failure_signals)
                is_finding = any(kw in text for kw in ['found', 'scraped', 'downloaded', 'extracted', 'confirmed', 'saved', 'dealers', 'located'])
                if is_finding and not is_failure and len(entry['content']) > 30:
                    agent_findings[agent].append(entry['content'][:200])

    return {
        'user_facts': list(user_facts),
        'project_hints': list(project_hints),
        'agent_findings': {k: v[-5:] for k, v in agent_findings.items()}  # keep last 5 per agent
    }


# ─── MERGE INTO KNOWLEDGE ─────────────────────────────────────────────────────

def _merge(knowledge: Dict, extracted: Dict) -> Dict:
    """Merge extracted facts into existing knowledge, avoiding duplicates."""
    existing_facts = set(knowledge['user'].get('facts', []))
    for fact in extracted['user_facts']:
        if fact not in existing_facts and len(fact) > 5:
            existing_facts.add(fact)
    knowledge['user']['facts'] = list(existing_facts)[-30:]  # cap at 30

    # Merge agent findings
    for agent, findings in extracted['agent_findings'].items():
        if agent not in knowledge['agent_findings']:
            knowledge['agent_findings'][agent] = []
        existing = set(knowledge['agent_findings'][agent])
        for f in findings:
            if f not in existing:
                knowledge['agent_findings'][agent].append(f)
        knowledge['agent_findings'][agent] = knowledge['agent_findings'][agent][-10:]

    knowledge['last_consolidated'] = datetime.now().isoformat()
    knowledge['consolidation_count'] = knowledge.get('consolidation_count', 0) + 1

    return knowledge


# ─── MODEL-BASED SYNTHESIS (TINKER PASS) ─────────────────────────────────────

_CONSOLIDATION_PROMPT = """You are performing a memory consolidation task. Read the recent conversation excerpts and extract durable facts worth remembering.

Output format — use ONLY these prefixes, one per line:
USER_FACT: [stable fact about Jon — preferences, habits, context]
PROJECT: [project_name] | [status: active/done/paused] | [one-line summary]
FINDING: [agent_name] | [what was discovered or accomplished]
DISCARD: [something that is outdated or no longer relevant]

Rules:
- Only extract HIGH-SIGNAL, DURABLE facts. Skip greetings, casual remarks, temporary states.
- Be terse. Max 15 words per fact.
- If unsure, skip it.

Recent conversations:
{conversations}

Current knowledge summary:
{current_summary}

Extract now:"""


async def run_synthesis_pass(agent_loops: Dict) -> bool:
    """Use Tinker to do a deeper synthesis pass. Returns True if successful."""
    try:
        tinker = agent_loops.get('tinker')
        if not tinker:
            return False

        entries = _read_logs(days=2)
        if not entries:
            return False

        # Format recent conversations
        conv_text = ""
        for e in entries[-40:]:  # last 40 turns
            label = "Jon" if e['role'] == 'user' else e['speaker'].title()
            conv_text += f"{label}: {e['content'][:200]}\n"

        knowledge = load_knowledge()
        current_summary = format_for_context(knowledge)

        prompt = _CONSOLIDATION_PROMPT.format(
            conversations=conv_text,
            current_summary=current_summary
        )

        response = await tinker.process_message(
            message=prompt,
            conversation_history=[],
            temperature=0.1,
            max_tokens=800,
            repeat_penalty=1.05
        )

        # Parse Tinker's output
        new_user_facts = []
        new_projects = {}
        new_findings = {}
        discards = []

        for line in response.splitlines():
            line = line.strip()
            if line.startswith('USER_FACT:'):
                fact = line[10:].strip()
                if fact:
                    new_user_facts.append(fact)
            elif line.startswith('PROJECT:'):
                parts = line[8:].strip().split('|')
                if len(parts) >= 2:
                    name = parts[0].strip().lower().replace(' ', '_')
                    status = parts[1].strip() if len(parts) > 1 else 'active'
                    summary = parts[2].strip() if len(parts) > 2 else ''
                    new_projects[name] = {'status': status, 'summary': summary}
            elif line.startswith('FINDING:'):
                parts = line[8:].strip().split('|', 1)
                if len(parts) == 2:
                    agent = parts[0].strip().lower()
                    finding = parts[1].strip()
                    if agent not in new_findings:
                        new_findings[agent] = []
                    new_findings[agent].append(finding)
            elif line.startswith('DISCARD:'):
                discards.append(line[8:].strip())

        # Apply to knowledge
        existing_facts = set(knowledge['user'].get('facts', []))
        for f in new_user_facts:
            existing_facts.add(f)
        knowledge['user']['facts'] = list(existing_facts)[-30:]

        for name, data in new_projects.items():
            knowledge['projects'][name] = data

        for agent, findings in new_findings.items():
            if agent not in knowledge['agent_findings']:
                knowledge['agent_findings'][agent] = []
            existing = set(knowledge['agent_findings'][agent])
            for f in findings:
                if f not in existing:
                    knowledge['agent_findings'][agent].append(f)
            knowledge['agent_findings'][agent] = knowledge['agent_findings'][agent][-10:]

        knowledge['last_consolidated'] = datetime.now().isoformat()
        knowledge['consolidation_count'] = knowledge.get('consolidation_count', 0) + 1
        save_knowledge(knowledge)

        print(f"[Memory] Synthesis pass complete: {len(new_user_facts)} user facts, {len(new_projects)} projects, {sum(len(v) for v in new_findings.values())} findings")
        return True

    except Exception as e:
        print(f"[Memory] Synthesis pass error: {e}")
        return False


# ─── FAST CONSOLIDATION (no inference) ────────────────────────────────────────

def consolidate_fast():
    """Run the fast rule-based pass. Safe to call any time."""
    try:
        entries = _read_logs(days=3)
        if not entries:
            print("[Memory] No log entries found for consolidation")
            return

        extracted = _extract_from_logs(entries)
        knowledge = load_knowledge()
        knowledge = _merge(knowledge, extracted)
        save_knowledge(knowledge)
        print(f"[Memory] Fast consolidation: {len(extracted['user_facts'])} user facts extracted, "
              f"knowledge.json updated (pass #{knowledge['consolidation_count']})")
    except Exception as e:
        print(f"[Memory] Fast consolidation error: {e}")


# ─── CONTEXT FORMATTER ────────────────────────────────────────────────────────

def format_for_context(knowledge: Optional[Dict] = None, agent_name: str = "") -> str:
    """Compact string for injection into agent system prompts. ~100-150 tokens."""
    if knowledge is None:
        knowledge = load_knowledge()

    lines = []

    # User facts
    user = knowledge.get('user', {})
    user_facts = user.get('facts', [])
    if user_facts:
        lines.append("USER FACTS: " + " | ".join(user_facts[-8:]))

    # Active projects — skip dealer recruitment details for Aetheria
    projects = knowledge.get('projects', {})
    if projects:
        proj_parts = []
        for name, data in list(projects.items())[-5:]:
            # Aetheria doesn't need granular dealer ops context
            if agent_name == 'aetheria' and 'dealer' in name:
                continue
            status = data.get('status', '')
            summary = data.get('summary', '')
            proj_parts.append(f"{name}({status}): {summary}" if summary else f"{name}({status})")
        if proj_parts:
            lines.append("PROJECTS: " + " | ".join(proj_parts))

    # Agent findings — each agent only sees its own last finding.
    # Aetheria gets full team intel via the separate shared_intel block in agent_loop.py.
    findings_parts = []
    for agent, findings in knowledge.get('agent_findings', {}).items():
        if not findings:
            continue
        if agent != agent_name:
            continue
        findings_parts.append(f"{agent.upper()}: {findings[-1][:80]}")
    if findings_parts:
        lines.append("RECENT FINDINGS: " + " | ".join(findings_parts))

    if not lines:
        return ""

    last = knowledge.get('last_consolidated', '')
    ts = last[:10] if last else 'never'
    return f"[KNOWLEDGE BASE — {ts}]\n" + "\n".join(lines)


# ─── BACKGROUND SCHEDULER ─────────────────────────────────────────────────────

_last_fast_pass = 0.0
_last_synthesis_pass = 0.0
_synthesis_lock = threading.Lock()

FAST_INTERVAL = 3600       # 1 hour
SYNTHESIS_INTERVAL = 21600  # 6 hours


def tick(agent_loops: Dict = None):
    """Call this from the heartbeat. Runs passes when due."""
    global _last_fast_pass, _last_synthesis_pass
    now = time.time()

    if now - _last_fast_pass >= FAST_INTERVAL:
        _last_fast_pass = now
        threading.Thread(target=consolidate_fast, daemon=True).start()

    if agent_loops and now - _last_synthesis_pass >= SYNTHESIS_INTERVAL:
        if _synthesis_lock.acquire(blocking=False):
            _last_synthesis_pass = now
            import asyncio

            def _run():
                try:
                    loop = asyncio.new_event_loop()
                    loop.run_until_complete(run_synthesis_pass(agent_loops))
                finally:
                    _synthesis_lock.release()

            threading.Thread(target=_run, daemon=True).start()
