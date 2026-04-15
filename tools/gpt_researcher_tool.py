"""
GPT-Researcher Tool — deep multi-source research reports.
Aggregates 10-20+ web sources into a structured report on any topic.
Use for grant research, competitive analysis, technical deep-dives, or
any task where a single web_search isn't enough.
"""
import asyncio
from core.tool_base import Tool
from typing import Any, Dict


class GPTResearcherTool(Tool):

    @property
    def name(self) -> str:
        return "deep_research"

    @property
    def description(self) -> str:
        return (
            "Run a deep multi-source research report on any topic. "
            "Searches 10-20+ sources and returns a structured, cited report. "
            "Use for grant research, market analysis, technology deep-dives, or any task "
            "that needs more than a single web search. Takes 60-120 seconds."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Research question or topic to investigate in depth"
                },
                "report_type": {
                    "type": "string",
                    "description": "Type of report: 'research_report' (default), 'outline_report', or 'resource_report'",
                    "default": "research_report"
                }
            },
            "required": ["query"]
        }

    async def execute(self, query: str = "", report_type: str = "research_report", **kwargs) -> str:
        if not query.strip():
            return "deep_research: query cannot be empty"
        try:
            import os
            os.environ.setdefault("RETRIEVER", "duckduckgo")
            from gpt_researcher import GPTResearcher
            researcher = GPTResearcher(
                query=query,
                report_type=report_type,
                verbose=False
            )
            await researcher.conduct_research()
            report = await researcher.write_report()
            if not report:
                return f"deep_research: No report generated for '{query}'"
            # Cap output to avoid flooding context
            if len(report) > 12000:
                report = report[:12000] + "\n\n[... report truncated at 12000 chars]"
            return f"RESEARCH REPORT: {query}\n\n{report}"
        except Exception as e:
            return f"deep_research error: {e}"
