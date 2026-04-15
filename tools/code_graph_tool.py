"""
CodeGraph Tool
Gives Aetheria and Tinker structural understanding of the SOVERYN codebase.
"""
import re
from typing import Any, Dict
from core.tool_base import Tool


class CodeGraphTool(Tool):

    @property
    def name(self) -> str:
        return "query_code_graph"

    @property
    def description(self) -> str:
        return (
            "Query the SOVERYN codebase structure — classes, functions, call relationships, imports. "
            "Use this to understand architecture, trace how things connect, or inspect code before editing. "
            "Examples: 'what calls process_message', 'describe AgentLoop', "
            "'list classes in agent_loop.py', 'what does execute do in BashTool', "
            "'what imports does memory_tool.py use', 'find functions about embedding', "
            "'stats', 'rebuild'"
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language question about the codebase"
                }
            },
            "required": ["query"]
        }

    async def execute(self, query: str = '') -> str:
        from core.code_graph import db
        q = query.strip().lower()

        # rebuild / reindex
        if re.search(r'rebuild|reindex|refresh|rescan', q):
            from core.code_graph import indexer
            import threading
            threading.Thread(target=indexer.full_scan, daemon=True).start()
            return "Re-indexing started in background. Run 'stats' in ~30 seconds to check progress."

        # stats
        if re.search(r'^stats?$|graph stats|how many|coverage', q):
            s = db.get_stats()
            return (
                f"CodeGraph Status:\n"
                f"  Files indexed:   {s['files']}\n"
                f"  Total symbols:   {s['symbols']} "
                f"(classes: {s['classes']}, functions: {s['functions']}, methods: {s['methods']})\n"
                f"  Call edges:      {s['calls']}\n"
                f"  Imports tracked: {s['imports']}\n"
                f"  Last full scan:  {s['last_scan']}\n"
                f"  Watcher:         {s['watcher']}"
            )

        # who calls X
        m = re.search(r'(?:what|who|which)\s+(?:calls?|invokes?|uses?)\s+["\']?([.\w]+)["\']?', q)
        if m:
            name = m.group(1)
            rows = db.who_calls(name)
            if not rows:
                return f"No callers found for '{name}'. Try 'rebuild' if the graph is new."
            lines = [f"WHO CALLS: {name}\nFound {len(rows)} caller(s):\n"]
            for i, r in enumerate(rows[:15], 1):
                lines.append(f"  {i}. {r['path']}:{r['lineno']} — {r['caller_qual']}")
            return '\n'.join(lines)

        # what does X call (forward)
        m = re.search(r'(?:what does|what)\s+["\']?([.\w]+)["\']?\s+call', q)
        if m:
            name = m.group(1)
            sym = db.describe_symbol(name)
            if not sym:
                return f"Symbol '{name}' not found."
            rows = db.what_calls(sym['id'])
            if not rows:
                return f"'{name}' makes no tracked calls."
            lines = [f"CALLS MADE BY: {name} ({sym['path']}:{sym['lineno']})\n"]
            for r in rows[:20]:
                lines.append(f"  line {r['lineno']}: {r['callee_name']}")
            return '\n'.join(lines)

        # describe / what does X do
        m = re.search(r'(?:what does|describe|explain|tell me about|what is)\s+["\']?([.\w\s]+?)["\']?(?:\s+do|\s+class|\s+function|\s*\?)?$', q)
        if m:
            name = m.group(1).strip().rstrip(' do')
            # try exact first, then fuzzy
            sym = db.describe_symbol(name)
            if not sym:
                results = db.find_symbol(name)
                if results:
                    sym = results[0]
            if not sym:
                return f"Symbol '{name}' not found. Try 'stats' or 'list classes in <file>'."
            return _format_symbol(sym, db)

        # list classes/functions/methods in file
        m = re.search(r'(?:list|show|what)\s+(?:all\s+)?(?:(class|function|method|import)e?s?)?\s+(?:in|from)\s+["\']?([.\w/\\-]+\.py)["\']?', q)
        if m:
            kind = m.group(1)
            path = m.group(2)
            if kind == 'import':
                rows = db.get_imports(path)
                if not rows:
                    return f"No imports found for '{path}'."
                lines = [f"IMPORTS in {path}:\n"]
                for r in rows:
                    names = f" ({r['names']})" if r['names'] else ''
                    alias = f" as {r['alias']}" if r['alias'] else ''
                    lines.append(f"  line {r['lineno']}: {r['module']}{names}{alias}")
                return '\n'.join(lines)
            rows = db.list_symbols_in_file(path, kind)
            if not rows:
                return f"No {kind or 'symbols'} found in '{path}'."
            lines = [f"SYMBOLS in {path} ({kind or 'all'}):\n"]
            for r in rows:
                sig = r['signature'] or ''
                lines.append(f"  [{r['kind']}] {r['name']}{sig} — line {r['lineno']}")
            return '\n'.join(lines)

        # imports in file
        m = re.search(r'imports?\s+(?:in|of|from|for)\s+["\']?([.\w/\\-]+\.py)["\']?', q)
        if m:
            path = m.group(1)
            rows = db.get_imports(path)
            if not rows:
                return f"No imports found for '{path}'."
            lines = [f"IMPORTS in {path}:\n"]
            for r in rows:
                names = f" ({r['names']})" if r['names'] else ''
                lines.append(f"  line {r['lineno']}: {r['module']}{names}")
            return '\n'.join(lines)

        # find by docstring
        m = re.search(r'(?:find|search|look)\s+.+?(?:about|related to|involving|with)\s+["\']?(.+?)["\']?$', q)
        if m:
            text = m.group(1).strip()
            rows = db.find_in_docstrings(text)
            if not rows:
                rows = db.find_symbol(text)
            if not rows:
                return f"Nothing found matching '{text}'."
            lines = [f"SEARCH RESULTS for '{text}':\n"]
            for r in rows[:10]:
                doc = (r.get('docstring') or '')[:80]
                lines.append(f"  [{r['kind']}] {r['qualified']} ({r['path']}:{r['lineno']})")
                if doc:
                    lines.append(f"    {doc}")
            return '\n'.join(lines)

        # default: fuzzy symbol lookup
        results = db.find_symbol(query.strip())
        if not results:
            return (
                f"No matches for '{query}'.\n"
                "Try: 'what calls X', 'describe X', 'list classes in file.py', "
                "'find functions about embedding', 'stats'"
            )
        if len(results) == 1:
            return _format_symbol(results[0], db)
        lines = [f"FOUND {len(results)} match(es) for '{query}':\n"]
        for r in results[:10]:
            sig = r.get('signature') or ''
            lines.append(f"  [{r['kind']}] {r['qualified']}{sig} — {r['path']}:{r['lineno']}")
        return '\n'.join(lines)


def _format_symbol(sym: dict, db) -> str:
    lines = []
    kind = sym['kind'].upper()
    sig = sym.get('signature') or ''
    lines.append(f"{kind}: {sym['qualified']}{sig}  ({sym['path']}:{sym['lineno']})")

    if sym.get('docstring'):
        lines.append(f"\nDocstring:\n  {sym['docstring'][:300]}")

    if sym['kind'] == 'class':
        methods = db.get_methods_for_class(sym['qualified'])
        if methods:
            lines.append(f"\nMethods ({len(methods)}):")
            for m in methods[:12]:
                s = m.get('signature') or ''
                lines.append(f"  {m['name']}{s} — line {m['lineno']}")
            if len(methods) > 12:
                lines.append(f"  ... ({len(methods) - 12} more)")

    callers = db.who_calls(sym['name'])
    if callers:
        lines.append(f"\nCalled by ({len(callers)}):")
        for c in callers[:5]:
            lines.append(f"  {c['path']}:{c['lineno']} — {c['caller_qual']}")
        if len(callers) > 5:
            lines.append(f"  ... ({len(callers) - 5} more)")

    return '\n'.join(lines)
