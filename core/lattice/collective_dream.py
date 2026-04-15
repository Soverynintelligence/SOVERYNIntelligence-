"""
Collective Dream — Multi-agent global Lattice review.

Runs nightly at 2 AM. Each specialist agent reviews their domain
of the global Lattice, looking for contradictions, missing connections,
and patterns. Aetheria synthesizes all findings last.

Agent domain assignments:
  tinker  — code, bug, vulnerability, codebase, build, dependency
  ares    — security, threat, anomaly, system, thermal, alert
  scout   — research, finding, external, unverified, investigate
  vett    — analysis, decision, strategy, risk

Findings are written to the global Lattice tagged with
["collective_dream", <agent_name>] at significant intensity,
so they're available to all agents and trigger the routing table.
"""

import asyncio
import time
from datetime import datetime
from typing import Dict, List, Optional


# Domain tag filters per agent
AGENT_DOMAINS: Dict[str, List[str]] = {
    'tinker': ['code', 'bug', 'vulnerability', 'codebase', 'build', 'dependency'],
    'ares':   ['security', 'threat', 'anomaly', 'system', 'thermal', 'alert'],
    'scout':  ['research', 'finding', 'external', 'unverified', 'investigate'],
    'vett':   ['analysis', 'decision', 'strategy', 'risk'],
}

# Seconds between agent passes — give VRAM time to breathe
PASS_DELAY = 30

# Max global nodes to show each agent
MAX_NODES_PER_PASS = 20


def _get_global_nodes_for_domain(domain_tags: List[str], limit: int = MAX_NODES_PER_PASS) -> List[Dict]:
    """
    Fetch global Lattice nodes whose tags overlap with domain_tags.
    Falls back to most-salient recent global nodes if no domain match.
    """
    import json as _json
    from .graph import _get_conn, LAYER_GLOBAL

    with _get_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM nodes
            WHERE layer = ?
            ORDER BY salience DESC, updated_at DESC
            LIMIT 200
        """, (LAYER_GLOBAL,)).fetchall()

    domain_set = set(t.lower() for t in domain_tags)
    matched = []
    unmatched = []

    for row in rows:
        try:
            node_tags = set(t.lower() for t in _json.loads(row['tags'] or '[]'))
        except Exception:
            node_tags = set()
        if node_tags & domain_set:
            matched.append(dict(row))
        else:
            unmatched.append(dict(row))

    # Return domain matches first, pad with recent global nodes if needed
    combined = matched[:limit]
    if len(combined) < limit // 2:
        combined += unmatched[:limit - len(combined)]

    return combined[:limit]


def _format_nodes_for_prompt(nodes: List[Dict]) -> str:
    import json as _json
    from datetime import datetime as _dt

    lines = []
    for n in nodes:
        try:
            tags = _json.loads(n.get('tags') or '[]')
            tag_str = f" [{', '.join(tags)}]" if tags else ""
        except Exception:
            tag_str = ""
        try:
            days = (_dt.now() - _dt.fromisoformat(n['created_at'])).days
            age = f"{days}d ago" if days > 0 else "today"
        except Exception:
            age = "?"
        lines.append(f"  - ({n['type']}){tag_str} [{age}] by {n['agent']}: {n['content'][:120]}")

    return "\n".join(lines) if lines else "  (no global nodes in this domain yet)"


def _build_agent_prompt(agent_name: str, nodes: List[Dict], cycle_ts: str) -> str:
    domain_tags = AGENT_DOMAINS.get(agent_name, [])
    node_block = _format_nodes_for_prompt(nodes)

    return f"""COLLECTIVE DREAM — {agent_name.upper()} pass. {cycle_ts}

You are reviewing SOVERYN's shared global Lattice during a low-activity dream cycle.
These are global memories in your domain ({', '.join(domain_tags)}):

{node_block}

Review these. Look for:
- Contradictions — two nodes that conflict with each other
- Stale or outdated information that should be flagged
- Missing connections — nodes that relate but aren't linked yet
- Patterns that concern your area of expertise

If you find something worth the collective knowing, write it to the shared Lattice:
TOOL_CALL: lattice(action="remember", content="your finding", node_type="insight", intensity="significant", global=true, tags=["collective_dream", "{agent_name}"])

If two nodes contradict, connect them:
TOOL_CALL: lattice(action="connect", content="first node content", target="second node content", relationship="contradicts")

If nothing needs attention: DREAM_OK"""


def _build_synthesis_prompt(findings: Dict[str, str], cycle_ts: str) -> str:
    parts = []
    for agent_name, response in findings.items():
        if response and response.strip() != 'DREAM_OK':
            parts.append(f"--- {agent_name.upper()} ---\n{response[:400]}")

    if not parts:
        return ""

    findings_block = "\n\n".join(parts)

    return f"""COLLECTIVE DREAM — SYNTHESIS. {cycle_ts}

The following findings were submitted by your agents during tonight's collective review:

{findings_block}

Review these findings. Promote the most critical insights if warranted:
TOOL_CALL: lattice(action="remember", content="synthesis: ...", node_type="insight", intensity="core", global=true, tags=["collective_dream", "synthesis"])

Write a brief summary of what the collective dream found. If nothing critical surfaced, say so.
Keep it under 3 sentences."""


async def run(agent_loops: Dict, quiet_hours_check=None) -> Dict:
    """
    Run a full collective dream cycle.

    Args:
        agent_loops: dict of agent_name → AgentLoop
        quiet_hours_check: optional callable() → bool — skips if returns True

    Returns:
        summary dict
    """
    cycle_ts = datetime.now().strftime('%Y-%m-%d %H:%M')
    print(f"\n[COLLECTIVE DREAM] Starting — {cycle_ts}")

    results = {
        'started_at': cycle_ts,
        'passes': {},
        'synthesis': None,
        'skipped': [],
    }

    findings: Dict[str, str] = {}

    # Run each specialist agent pass
    for agent_name, domain_tags in AGENT_DOMAINS.items():
        agent_loop = agent_loops.get(agent_name)
        if not agent_loop:
            print(f"[COLLECTIVE DREAM] {agent_name} not available, skipping")
            results['skipped'].append(agent_name)
            continue

        # Yield if user is active
        if quiet_hours_check and quiet_hours_check():
            print(f"[COLLECTIVE DREAM] Quiet hours detected mid-cycle — aborting remaining passes")
            break

        try:
            from sovereign_backend import _inference_lock
            if _inference_lock.locked():
                print(f"[COLLECTIVE DREAM] Inference locked — skipping {agent_name} pass")
                results['skipped'].append(agent_name)
                continue
        except Exception:
            pass

        nodes = _get_global_nodes_for_domain(domain_tags)
        prompt = _build_agent_prompt(agent_name, nodes, cycle_ts)

        print(f"[COLLECTIVE DREAM] Running {agent_name.upper()} pass ({len(nodes)} nodes)...")
        try:
            response = await agent_loop.process_message(
                prompt,
                conversation_history=[],
                max_tokens=400,
                temperature=0.7,
            )
            response = (response or '').strip()
            findings[agent_name] = response
            results['passes'][agent_name] = response[:200]
            print(f"[COLLECTIVE DREAM] {agent_name}: {response[:100]}...")
        except Exception as e:
            print(f"[COLLECTIVE DREAM] {agent_name} pass failed: {e}")
            results['passes'][agent_name] = f"error: {e}"

        # Stagger passes to avoid VRAM contention
        await asyncio.sleep(PASS_DELAY)

    # Aetheria synthesis — only if at least one agent found something
    aetheria = agent_loops.get('aetheria')
    real_findings = {k: v for k, v in findings.items() if v and v.strip() != 'DREAM_OK'}

    if real_findings and aetheria:
        synthesis_prompt = _build_synthesis_prompt(real_findings, cycle_ts)
        if synthesis_prompt:
            print(f"[COLLECTIVE DREAM] Running Aetheria synthesis ({len(real_findings)} finding(s))...")
            try:
                synthesis = await aetheria.process_message(
                    synthesis_prompt,
                    conversation_history=[],
                    max_tokens=300,
                    temperature=0.7,
                )
                results['synthesis'] = (synthesis or '').strip()
                print(f"[COLLECTIVE DREAM] Synthesis: {results['synthesis'][:120]}...")
            except Exception as e:
                print(f"[COLLECTIVE DREAM] Synthesis failed: {e}")
                results['synthesis'] = f"error: {e}"
    else:
        print(f"[COLLECTIVE DREAM] All agents returned DREAM_OK — nothing to synthesize")
        results['synthesis'] = 'DREAM_OK'

    print(f"[COLLECTIVE DREAM] Complete — {len(results['passes'])} passes, {len(results['skipped'])} skipped")
    return results
