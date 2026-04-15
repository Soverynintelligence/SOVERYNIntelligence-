"""
Lattice Tool — Unified memory tool for all SOVERYN agents
Replaces: persistent_memory_tool (search_memory), remember_tool, write_memory_tool
"""

from core.tool_base import Tool
from typing import Any, Dict, List, Optional
from datetime import datetime
import json

# Tag → target agent routing for cross-pollination.
# When a global node is written with a matching tag, the target agent
# is automatically notified via the message bus — no middleman needed.
# Tags are matched case-insensitively against the node's tag list.
TRIGGER_ROUTES: Dict[str, str] = {
    # Technical findings → Tinker analyzes
    'vulnerability':  'tinker',
    'bug':            'tinker',
    'codebase':       'tinker',
    'build_failure':  'tinker',
    'code':           'tinker',
    'dependency':     'tinker',
    # Security/threat events → Ares investigates
    'security':       'ares',
    'threat':         'ares',
    'intrusion':      'ares',
    'anomaly':        'ares',
    # Research gaps → Scout digs in
    'research_needed': 'scout',
    'investigate':     'scout',
    'unverified':      'scout',
}


class LatticeTool(Tool):
    """Associative memory — store nodes, recall by spreading activation, flag contradictions."""

    def __init__(self, agent_name: str):
        self.agent_name = agent_name

    @property
    def name(self) -> str:
        return "lattice"

    @property
    def description(self) -> str:
        base = """Associative memory system.

remember  — store something worth keeping (private to you by default)
           Set intensity="significant" or intensity="core" AND global=true to write
           directly to SOVERYN shared memory — visible to all agents.
           Use this when your finding is system-wide, not just yours.
recall    — retrieve related memories, including SOVERYN global knowledge
           Active contradictions and context quality are always included.
connect   — manually link two pieces of knowledge
verify    — check a claim against the Lattice. Returns supporting evidence,
           contradicting evidence, and a confidence score. Use before asserting facts.
review    — see pending contradiction flags
status    — see cognitive load + loop health across all agents"""
        if self.agent_name == 'aetheria':
            base += """
promote   — elevate any agent's private memory to SOVERYN global layer

When you promote a node, it becomes part of collective SOVERYN intelligence."""
        return base

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["remember", "recall", "connect", "verify", "review", "promote", "timeline", "status"],
                    "description": (
                        "What to do. "
                        "'verify' checks a claim — returns supporting/contradicting evidence + confidence score. "
                        "'promote' is Aetheria-only — elevates a memory to global SOVERYN layer. "
                        "'timeline' shows how a topic evolved over time (decision chain). "
                        "'status' shows current cognitive load + loop health across all agents."
                    )
                },
                "content": {
                    "type": "string",
                    "description": "For remember: what to store. For recall: what to search for. For connect: the first piece of knowledge."
                },
                "node_type": {
                    "type": "string",
                    "enum": ["entity", "event", "concept", "fact", "insight"],
                    "description": "For remember: type of memory (default: fact)"
                },
                "intensity": {
                    "type": "string",
                    "enum": ["default", "significant", "core"],
                    "description": "For remember: how important is this? core = never fades. default = normal."
                },
                "global": {
                    "type": "boolean",
                    "description": "For remember: write to SOVERYN shared memory (visible to all agents). Only valid when intensity is 'significant' or 'core'. Use for system-wide facts, not routine findings."
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "For remember: topic tags to aid retrieval"
                },
                "target": {
                    "type": "string",
                    "description": "For connect: the second piece of knowledge to link to"
                },
                "relationship": {
                    "type": "string",
                    "enum": ["associated_with", "caused_by", "supports",
                             "contradicts", "belongs_to", "precedes", "references"],
                    "description": "For connect: how the two things relate"
                }
            },
            "required": ["action"]
        }

    async def execute(
        self,
        action: str = "recall",
        content: str = "",
        node_type: str = "fact",
        intensity: str = "default",
        tags: Optional[list] = None,
        target: str = "",
        relationship: str = "associated_with",
        to_global: bool = False,
        **kwargs
    ) -> str:
        # 'global' is a reserved Python keyword so it can't be a named param —
        # it arrives in **kwargs when the model passes global=true
        if kwargs.get('global'):
            to_global = True
        try:
            if action == "remember":
                return await self._remember(content, node_type, intensity, tags or [], to_global)
            elif action == "recall":
                return await self._recall(content)
            elif action == "connect":
                return await self._connect(content, target, relationship)
            elif action == "verify":
                return await self._verify(content)
            elif action == "review":
                return await self._review()
            elif action == "promote":
                return await self._promote(content)
            elif action == "timeline":
                return await self._timeline(content)
            elif action == "status":
                return await self._status()
            else:
                return f"Unknown action: {action}. Use: remember, recall, connect, verify, review, promote, timeline, status"
        except Exception as e:
            return f"Lattice error: {e}"

    async def _remember(self, content: str, node_type: str,
                        intensity_str: str, tags: list, to_global: bool = False) -> str:
        if not content.strip():
            return "Error: content required for remember"

        from core.lattice.graph import (
            write_node, write_edge, find_nodes_by_keywords, find_nodes_by_embedding,
            INTENSITY_DEFAULT, INTENSITY_SIGNIFICANT, INTENSITY_CORE,
            LAYER_PRIVATE, LAYER_GLOBAL,
        )

        intensity_map = {
            'default':     INTENSITY_DEFAULT,
            'significant': INTENSITY_SIGNIFICANT,
            'core':        INTENSITY_CORE,
        }
        intensity = intensity_map.get(intensity_str, INTENSITY_DEFAULT)

        # Any agent can write to global layer at significant/core intensity.
        # Aetheria can write global at any intensity (she is the curator).
        if to_global and (self.agent_name == 'aetheria' or intensity >= INTENSITY_SIGNIFICANT):
            layer = LAYER_GLOBAL
        else:
            layer = LAYER_PRIVATE

        # Generate embedding for semantic search + supersedes detection
        embedding = None
        try:
            from sovereign_embeddings import sovereign_embed
            embedding = sovereign_embed(content[:1000])
        except Exception:
            pass

        node_id = write_node(
            agent=self.agent_name,
            content=content,
            node_type=node_type,
            layer=layer,
            intensity=intensity,
            tags=tags,
            embedding=embedding,
        )

        # Auto-connect: find related nodes and wire associated_with edges
        edges_made = 0
        try:
            related = find_nodes_by_keywords(self.agent_name, content, limit=5)
            for neighbor in related:
                if neighbor['id'] == node_id:
                    continue
                write_edge(node_id, neighbor['id'], 'associated_with')
                edges_made += 1
                if edges_made >= 3:
                    break
        except Exception:
            pass

        # Supersedes detection: if a semantically near-identical node already exists
        # (same agent, cosine > 0.87, older than 1 day) wire supersedes from new → old.
        # Only for evolving knowledge types — not entities.
        supersedes_made = 0
        if embedding and node_type in ('fact', 'event', 'concept', 'insight'):
            try:
                from datetime import timedelta
                cutoff = (datetime.now() - timedelta(days=1)).isoformat()
                candidates = find_nodes_by_embedding(
                    self.agent_name, embedding, limit=3, threshold=0.87
                )
                for candidate in candidates:
                    if candidate['id'] == node_id:
                        continue
                    if candidate.get('created_at', '') > cutoff:
                        continue  # too recent — not a supersede
                    write_edge(node_id, candidate['id'], 'supersedes')
                    supersedes_made += 1
                    if supersedes_made >= 1:
                        break
            except Exception:
                pass

        # Recurrence detection: find older nodes with similar patterns and wire recurs edges
        recurrences_made = 0
        try:
            from core.lattice.graph import find_recurrences
            prior_instances = find_recurrences(self.agent_name, node_id, min_age_days=7)
            for prior in prior_instances:
                if prior['id'] == node_id:
                    continue
                write_edge(node_id, prior['id'], 'recurs')
                recurrences_made += 1
        except Exception:
            pass

        # Auto-contradiction detection: find nodes on the same topic (similar but not
        # supersedes-level identical) that state the opposite.
        # Signals: positive words vs. negative words about the same subject.
        contradictions_auto = 0
        if embedding and node_type in ('fact', 'event', 'insight'):
            try:
                _POS = {'working', 'stable', 'fixed', 'success', 'running', 'healthy',
                        'resolved', 'online', 'available', 'passed', 'active', 'complete'}
                _NEG = {'failing', 'failed', 'broken', 'error', 'down', 'crashed',
                        'unstable', 'offline', 'unavailable', 'timeout', 'dead', 'critical'}

                def _polarity(text: str) -> str:
                    words = set(text.lower().split())
                    pos = len(words & _POS)
                    neg = len(words & _NEG)
                    if pos > neg:
                        return 'positive'
                    if neg > pos:
                        return 'negative'
                    return 'neutral'

                new_pol = _polarity(content)
                if new_pol != 'neutral':
                    candidates = find_nodes_by_embedding(
                        self.agent_name, embedding, limit=5, threshold=0.65
                    )
                    for candidate in candidates:
                        if candidate['id'] == node_id:
                            continue
                        if candidate.get('semantic_score', 0) > 0.87:
                            continue  # near-identical → supersedes, not contradiction
                        cand_pol = _polarity(candidate['content'])
                        if cand_pol != 'neutral' and cand_pol != new_pol:
                            write_edge(node_id, candidate['id'], 'contradicts', strength=0.6)
                            contradictions_auto += 1
            except Exception:
                pass

        # Cross-pollination: route global writes to relevant agents based on tags
        if layer == LAYER_GLOBAL:
            try:
                from core.message_bus import message_bus
                tag_list_lower = [t.lower() for t in (tags or [])]
                node_summary = (
                    f"[{node_type}]"
                    + (f"[{', '.join(tags)}]" if tags else "")
                    + f" {content[:150]}"
                    + (f" (echoes {recurrences_made} prior pattern)" if recurrences_made else "")
                )

                # Notify Aetheria of all global writes from other agents
                if self.agent_name != 'aetheria':
                    await message_bus.send_message(
                        from_agent=self.agent_name,
                        to_agent='aetheria',
                        content=f"[LATTICE] Global node written: {node_summary}",
                    )

                # Route to specialist agents based on tags — skip the writing agent and Aetheria
                # Uses agent_message_board (post_task) because InboxPoller watches that DB,
                # not message_bus. InboxPoller drives the agent loop automatically on new tasks.
                already_notified = {'aetheria', self.agent_name}
                for tag in tag_list_lower:
                    target = TRIGGER_ROUTES.get(tag)
                    if target and target not in already_notified:
                        already_notified.add(target)
                        try:
                            from agent_message_board import post_task
                            post_task(
                                from_agent=self.agent_name,
                                to_agent=target,
                                task=(
                                    f"New global finding from {self.agent_name} — "
                                    f"tagged '{tag}', flagged for your analysis:\n{node_summary}"
                                ),
                                subject=f"[TRIGGER] {tag} finding from {self.agent_name}",
                            )
                        except Exception:
                            pass
            except Exception:
                pass

        edge_note = f", linked to {edges_made} related node(s)" if edges_made else ""
        recur_note = f", echoes {recurrences_made} prior pattern(s)" if recurrences_made else ""
        super_note = f", supersedes {supersedes_made} prior node(s)" if supersedes_made else ""
        contra_note = f", ⚡ auto-flagged {contradictions_auto} contradiction(s)" if contradictions_auto else ""
        layer_note = " → SOVERYN global" if layer == LAYER_GLOBAL else ""
        return f"Stored [{node_type}] node {node_id[:8]}...{edge_note}{recur_note}{super_note}{contra_note} (intensity: {intensity_str}){layer_note}"

    async def _recall(self, query: str) -> str:
        if not query.strip():
            return "Error: content required for recall"

        from core.lattice.retrieval import query as lattice_query, format_for_context

        # Generate embedding for hybrid (semantic + keyword) retrieval
        embedding = None
        try:
            from sovereign_embeddings import sovereign_embed
            embedding = sovereign_embed(query[:1000])
        except Exception:
            pass

        nodes = lattice_query(self.agent_name, query, embedding=embedding)
        if not nodes:
            return f"No memories found for: {query}"

        formatted = format_for_context(nodes, label="Recalled Memory")

        # Inject active contradiction brief so Aetheria always sees live tensions
        try:
            from core.lattice.dream import get_contradiction_brief
            brief = get_contradiction_brief()
            if brief:
                formatted += brief
        except Exception:
            pass

        return formatted

    async def _connect(self, content_a: str, content_b: str, relationship: str) -> str:
        if not content_a.strip() or not content_b.strip():
            return "Error: both content and target required for connect"

        from core.lattice.graph import find_nodes_by_keywords, write_node, write_edge, INTENSITY_DEFAULT

        # Find or create node A
        seeds_a = find_nodes_by_keywords(self.agent_name, content_a, limit=1)
        node_a_id = seeds_a[0]['id'] if seeds_a else write_node(
            self.agent_name, content_a, 'fact', intensity=INTENSITY_DEFAULT
        )

        # Find or create node B
        seeds_b = find_nodes_by_keywords(self.agent_name, content_b, limit=1)
        node_b_id = seeds_b[0]['id'] if seeds_b else write_node(
            self.agent_name, content_b, 'fact', intensity=INTENSITY_DEFAULT
        )

        edge_id = write_edge(node_a_id, node_b_id, relationship)
        return f"Connected: '{content_a[:60]}' —[{relationship}]→ '{content_b[:60]}' (edge {edge_id[:8]}...)"

    async def _promote(self, content: str) -> str:
        if self.agent_name != 'aetheria':
            return "Error: only Aetheria can promote nodes to the global layer."
        if not content.strip():
            return "Error: content required — describe the memory to promote."

        from core.lattice.graph import find_nodes_by_keywords, promote_to_global

        candidates = find_nodes_by_keywords(self.agent_name, content, limit=3)
        if not candidates:
            return f"No matching memory found for: {content}"

        node = candidates[0]
        if node.get('layer') == 'global':
            return f"Already global: '{node['content'][:80]}'"

        success = promote_to_global(node['id'])
        if success:
            return f"Promoted to SOVERYN global: '{node['content'][:80]}' — all agents can now access this."
        return "Promotion failed — node not found."

    async def _verify(self, claim: str) -> str:
        """
        Check a claim against the Lattice.
        Returns: supporting evidence, contradicting evidence, confidence score.
        Designed so Vett can call this before asserting facts.
        """
        if not claim.strip():
            return "Error: claim required for verify"

        from core.lattice.retrieval import query as lattice_query
        from core.lattice.graph import get_edges_for_node

        embedding = None
        try:
            from sovereign_embeddings import sovereign_embed
            embedding = sovereign_embed(claim[:1000])
        except Exception:
            pass

        nodes = lattice_query(self.agent_name, claim, embedding=embedding)
        if not nodes:
            return f"UNVERIFIABLE — no memory context for: {claim[:80]}"

        # Classify nodes as supporting or contradicting via edges + polarity
        node_ids = {n['id'] for n in nodes}
        supporting = []
        contradicting = []
        uncertain = []

        for node in nodes:
            # Check for explicit contradicts edges to other retrieved nodes
            edges = get_edges_for_node(node['id'])
            has_contra_edge = any(
                e['relationship'] == 'contradicts'
                and (e['source_id'] in node_ids or e['target_id'] in node_ids)
                for e in edges
            )
            has_support_edge = any(
                e['relationship'] in ('supports', 'supersedes')
                for e in edges
            )

            # Simple keyword polarity relative to the claim
            claim_words = set(claim.lower().split())
            node_words = set(node['content'].lower().split())
            overlap = len(claim_words & node_words) / max(len(claim_words), 1)

            if has_contra_edge or node.get('intensity', 0) == 0:
                contradicting.append((node, overlap))
            elif has_support_edge or overlap > 0.3:
                supporting.append((node, overlap))
            else:
                uncertain.append((node, overlap))

        # Confidence score: weighted by supporting salience vs. contradicting salience
        sup_score = sum(n['salience'] * w for n, w in supporting) if supporting else 0
        con_score = sum(n['salience'] * w for n, w in contradicting) if contradicting else 0
        total = sup_score + con_score + 0.001
        confidence = round(sup_score / total, 3)

        if confidence >= 0.75:
            verdict = "SUPPORTED"
        elif confidence >= 0.45:
            verdict = "UNCERTAIN"
        else:
            verdict = "CONTRADICTED"

        lines = [f"VERIFY: '{claim[:80]}'",
                 f"Verdict: {verdict} (confidence: {confidence:.0%})"]

        if supporting:
            lines.append(f"\nSupporting ({len(supporting)}):")
            for node, _ in supporting[:3]:
                src = "{SOVERYN}" if node.get('layer') == 'global' else node.get('agent', '?')
                lines.append(f"  + [{src}] {node['content'][:100]}")

        if contradicting:
            lines.append(f"\nContradicting ({len(contradicting)}):")
            for node, _ in contradicting[:3]:
                src = "{SOVERYN}" if node.get('layer') == 'global' else node.get('agent', '?')
                lines.append(f"  - [{src}] {node['content'][:100]}")

        if uncertain:
            lines.append(f"\nUncertain / partial overlap ({len(uncertain)}):")
            for node, _ in uncertain[:2]:
                lines.append(f"  ? {node['content'][:80]}")

        return "\n".join(lines)

    async def _timeline(self, topic: str) -> str:
        """Show how a topic evolved over time — decision chain with supersedes."""
        if not topic.strip():
            return "Error: content required for timeline (describe the topic)"

        from core.lattice.retrieval import timeline, format_timeline

        embedding = None
        try:
            from sovereign_embeddings import sovereign_embed
            embedding = sovereign_embed(topic[:1000])
        except Exception:
            pass

        nodes = timeline(self.agent_name, topic, embedding=embedding)
        return format_timeline(nodes, topic)

    async def _status(self) -> str:
        """Show current cognitive load + loop health across all agents."""
        from core.lattice.retrieval import agent_status
        from core.lattice.graph import get_loop_health

        status_text = agent_status()

        # Append loop health for Aetheria
        try:
            health = get_loop_health(self.agent_name, last_n=5)
            if health['avg_health'] is not None:
                trend = health['trend']
                avg = health['avg_health']
                recent = health['cycles'][0] if health['cycles'] else {}
                last_summary = recent.get('summary', '')[:120]
                status_text += (
                    f"\n\n[LOOP HEALTH — last 5 cycles]"
                    f"\n  Trend: {trend} | Avg score: {avg:.0%}"
                    f"\n  Last cycle: {last_summary}"
                )
        except Exception:
            pass

        return status_text

    async def _review(self) -> str:
        from core.lattice.graph import get_pending_contradictions
        pending = get_pending_contradictions()
        if not pending:
            return "No pending contradiction flags."

        lines = [f"Pending contradictions ({len(pending)}):"]
        for flag in pending:
            lines.append(
                f"- [{flag['id'][:8]}] '{flag['content_a'][:80]}' "
                f"contradicts '{flag['content_b'][:80]}'"
            )
        lines.append("\nUse connect() with relationship='supports' or note resolution to clear.")
        return "\n".join(lines)
