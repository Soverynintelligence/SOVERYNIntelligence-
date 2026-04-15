"""
Crawl Tool for SOVERYN Scout
Uses Crawl4AI to extract clean Markdown from any page — strips ads, nav bars,
script noise. Automatically extracts emails, phones from the content.
"""
import re
import asyncio
from core.tool_base import Tool


_EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')
_PHONE_RE = re.compile(r'(?:\+1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)?\d{3}[-.\s]?\d{4}')


def _extract_contacts(text: str) -> str:
    """Pull emails and phone numbers out of text and append a summary."""
    emails = list(dict.fromkeys(_EMAIL_RE.findall(text)))
    phones = list(dict.fromkeys(
        p.strip() for p in _PHONE_RE.findall(text)
        if len(re.sub(r'\D', '', p)) >= 10
    ))
    if not emails and not phones:
        return ""
    lines = ["\n--- EXTRACTED CONTACTS ---"]
    if emails:
        lines.append("Emails: " + ", ".join(emails[:10]))
    if phones:
        lines.append("Phones: " + ", ".join(phones[:10]))
    return "\n".join(lines)


class CrawlTool(Tool):
    """
    Crawl a web page and return clean Markdown content, stripping ads,
    navigation, and script noise. Better than web_fetch for extracting
    structured contact info from dealer pages, directories, and About/Contact sections.
    Automatically highlights any emails and phone numbers found.
    """

    @property
    def name(self): return "crawl_page"

    @property
    def description(self):
        return (
            "Crawl a web page and return clean Markdown text — removes ads, nav bars, "
            "and script noise. Use instead of web_fetch when you need clean structured "
            "content from dealer pages, contact pages, or business directories. "
            "Automatically extracts emails and phone numbers found on the page."
        )

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Full URL to crawl (must start with http:// or https://)"
                },
                "max_chars": {
                    "type": "integer",
                    "description": "Maximum characters of content to return (default 8000)",
                    "default": 8000
                }
            },
            "required": ["url"]
        }

    async def execute(self, url: str = "", max_chars: int = 8000, **kw) -> str:
        if not url.startswith(("http://", "https://")):
            return "CrawlTool: URL must start with http:// or https://"
        try:
            from crawl4ai import AsyncWebCrawler
            async with AsyncWebCrawler(verbose=False) as crawler:
                result = await crawler.arun(url=url)
                if not result.success:
                    return f"CrawlTool: failed to crawl {url} — {result.error_message}"
                content = result.markdown or result.cleaned_html or ""
                if len(content) > max_chars:
                    content = content[:max_chars] + f"\n\n[... truncated at {max_chars} chars]"
                contacts = _extract_contacts(content)
                return f"CRAWLED: {url}\n\n{content}{contacts}"
        except ImportError:
            return "CrawlTool: crawl4ai not installed. Run: pip install crawl4ai"
        except Exception as ex:
            return f"CrawlTool error: {ex}"
