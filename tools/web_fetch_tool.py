"""
Web Fetch Tool for VETT
Fetches and extracts readable text from a URL — forums, papers, docs, GitHub issues.
"""
import re
import urllib.request
import urllib.error
from core.tool_base import Tool

_EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')
_PHONE_RE = re.compile(r'(?:\+1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)?\d{3}[-.\s]?\d{4}')

def _extract_contacts(text: str) -> str:
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


def _strip_html(html: str) -> str:
    """Basic HTML → plain text conversion using stdlib only."""
    # Remove script and style blocks entirely
    html = re.sub(r'<(script|style|noscript|head)[^>]*>.*?</\1>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
    # Remove HTML comments
    html = re.sub(r'<!--.*?-->', ' ', html, flags=re.DOTALL)
    # Replace block-level tags with newlines
    html = re.sub(r'<(br|p|div|li|h[1-6]|tr|blockquote)[^>]*>', '\n', html, flags=re.IGNORECASE)
    # Strip remaining tags
    html = re.sub(r'<[^>]+>', ' ', html)
    # Decode common HTML entities
    entities = {'&amp;': '&', '&lt;': '<', '&gt;': '>', '&quot;': '"',
                 '&apos;': "'", '&nbsp;': ' ', '&#39;': "'"}
    for ent, ch in entities.items():
        html = html.replace(ent, ch)
    # Collapse whitespace
    html = re.sub(r'[ \t]+', ' ', html)
    html = re.sub(r'\n{3,}', '\n\n', html)
    return html.strip()


class WebFetchTool(Tool):
    """
    Fetch the full text content of a web page.
    Use this after web_search to read a forum thread, documentation page,
    GitHub issue, arXiv abstract, or any URL in depth.
    """

    @property
    def name(self): return "web_fetch"

    @property
    def description(self):
        return (
            "Fetch and read the text content of a URL. "
            "Use after web_search to read forum posts, documentation, papers, or GitHub issues in full. "
            "Returns cleaned plain text — no HTML."
        )

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Full URL to fetch (must start with http:// or https://)"
                },
                "max_chars": {
                    "type": "integer",
                    "description": "Maximum characters to return (default 6000). Increase to 12000 or more for dealer directories, long pages, or when contact info may be deeper in the page.",
                    "default": 6000
                }
            },
            "required": ["url"]
        }

    async def execute(self, url: str = "", max_chars: int = 6000, **kw) -> str:
        if not url.startswith(("http://", "https://")):
            return "WebFetchTool: URL must start with http:// or https://"
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
                    ),
                    "Accept": "text/html,application/xhtml+xml,*/*",
                    "Accept-Language": "en-US,en;q=0.9",
                }
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                content_type = resp.headers.get("Content-Type", "")
                raw = resp.read(512_000)   # cap at 512 KB download
                charset = "utf-8"
                m = re.search(r'charset=([^\s;]+)', content_type, re.IGNORECASE)
                if m:
                    charset = m.group(1).strip('"\'')
                try:
                    html = raw.decode(charset, errors="replace")
                except LookupError:
                    html = raw.decode("utf-8", errors="replace")

            text = _strip_html(html)
            if len(text) > max_chars:
                text = text[:max_chars] + f"\n\n[... truncated at {max_chars} chars — use max_chars to increase]"
            contacts = _extract_contacts(text)
            return f"FETCHED: {url}\n\n{text}{contacts}"

        except urllib.error.HTTPError as e:
            return f"WebFetchTool HTTP {e.code}: {e.reason} — {url}"
        except urllib.error.URLError as e:
            return f"WebFetchTool network error: {e.reason} — {url}"
        except Exception as ex:
            return f"WebFetchTool error: {ex}"
