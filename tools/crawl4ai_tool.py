"""
Crawl4AI Tool — LLM-optimized web crawler.
Returns clean markdown from any URL, including JavaScript-rendered pages
that web_fetch can't handle. Use this when web_fetch returns empty or skeleton content.
"""
from core.tool_base import Tool
from typing import Any, Dict


class Crawl4AITool(Tool):

    @property
    def name(self) -> str:
        return "crawl_page"

    @property
    def description(self) -> str:
        return (
            "Fetch and extract clean markdown from any URL, including JavaScript-rendered pages. "
            "Use this instead of web_fetch when a page returns empty content or just a skeleton. "
            "Returns structured markdown optimized for LLM reading."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Full URL to crawl (must start with http:// or https://)"
                },
                "max_chars": {
                    "type": "integer",
                    "description": "Maximum characters to return (default 8000)",
                    "default": 8000
                }
            },
            "required": ["url"]
        }

    async def execute(self, url: str = "", max_chars: int = 8000, **kwargs) -> str:
        if not url.startswith(("http://", "https://")):
            return "crawl_page: URL must start with http:// or https://"
        try:
            from crawl4ai import AsyncWebCrawler
            async with AsyncWebCrawler(verbose=False) as crawler:
                result = await crawler.arun(url=url)
                if not result.success:
                    return f"crawl_page: Failed to crawl {url}"
                content = result.markdown or result.cleaned_html or ""
                if len(content) > max_chars:
                    content = content[:max_chars] + f"\n\n[... truncated at {max_chars} chars]"
                return f"CRAWLED: {url}\n\n{content}"
        except Exception as e:
            return f"crawl_page error: {e}"
