"""
Smart Crawl Tool for SOVERYN Scout and Vett.

Implements depth-limited BFS crawling with:
1. URL pattern filtering — skips noise URLs (/tag/, /category/, social, etc.)
2. Goal-anchored link following — only follows links relevant to the search goal
3. Breadth-first search — explores the main page fully before going deeper
4. Visited URL deduplication — no loops

Use this when you need to navigate a site to find a specific page, contact info,
or document rather than just reading a single URL.
"""
import re
import asyncio
import urllib.request
import urllib.error
import urllib.parse
from collections import deque
from core.tool_base import Tool
from typing import Any, Dict, List, Set


# URL segments that indicate low-value noise pages
_URL_BLACKLIST = [
    '/tag/', '/tags/', '/category/', '/categories/', '/author/', '/authors/',
    '/page/', '/wp-content/', '/wp-admin/', '/wp-json/',
    '/feed/', '/rss/', '/atom/',
    '/login', '/logout', '/register', '/signup', '/sign-up',
    '/terms', '/privacy', '/cookie', '/gdpr',
    '/cart', '/checkout', '/shop/page',
    'facebook.com', 'twitter.com', 'x.com', 'instagram.com',
    'linkedin.com', 'youtube.com', 'tiktok.com',
    'mailto:', 'javascript:', 'tel:',
    '.pdf', '.zip', '.exe', '.dmg', '.png', '.jpg', '.jpeg', '.gif', '.svg',
    '.css', '.js', '#',
]

_EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')
_PHONE_RE = re.compile(r'(?:\+1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)?\d{3}[-.\s]?\d{4}')


def _is_blacklisted(url: str) -> bool:
    url_lower = url.lower()
    return any(bad in url_lower for bad in _URL_BLACKLIST)


def _goal_score(url: str, anchor_text: str, goal_keywords: List[str]) -> int:
    """Score a link by how relevant it is to the goal. Higher = more relevant."""
    if not goal_keywords:
        return 1  # No goal — treat all links equally
    combined = (url + ' ' + anchor_text).lower()
    return sum(1 for kw in goal_keywords if kw.lower() in combined)


def _extract_links(html: str, base_url: str) -> List[tuple]:
    """Extract (url, anchor_text) pairs from HTML."""
    links = []
    parsed_base = urllib.parse.urlparse(base_url)
    base_domain = f"{parsed_base.scheme}://{parsed_base.netloc}"

    for match in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.DOTALL | re.IGNORECASE):
        href = match.group(1).strip()
        anchor = re.sub(r'<[^>]+>', '', match.group(2)).strip()

        if not href or href.startswith(('mailto:', 'javascript:', 'tel:', '#')):
            continue

        # Resolve relative URLs
        if href.startswith('//'):
            href = parsed_base.scheme + ':' + href
        elif href.startswith('/'):
            href = base_domain + href
        elif not href.startswith('http'):
            href = base_url.rstrip('/') + '/' + href

        # Stay on same domain
        if parsed_base.netloc not in href:
            continue

        links.append((href, anchor))
    return links


def _fetch_page(url: str, timeout: int = 10) -> str:
    """Synchronous page fetch — returns raw HTML or empty string on error."""
    try:
        req = urllib.request.Request(
            url,
            headers={
                'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36',
                'Accept': 'text/html,*/*',
                'Accept-Language': 'en-US,en;q=0.9',
            }
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(256_000)
            content_type = resp.headers.get('Content-Type', '')
            charset = 'utf-8'
            m = re.search(r'charset=([^\s;]+)', content_type, re.IGNORECASE)
            if m:
                charset = m.group(1).strip('"\'')
            try:
                return raw.decode(charset, errors='replace')
            except LookupError:
                return raw.decode('utf-8', errors='replace')
    except Exception:
        return ''


def _html_to_text(html: str) -> str:
    """Strip HTML to readable plain text."""
    html = re.sub(r'<(script|style|noscript|head)[^>]*>.*?</\1>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<!--.*?-->', ' ', html, flags=re.DOTALL)
    html = re.sub(r'<(br|p|div|li|h[1-6]|tr)[^>]*>', '\n', html, flags=re.IGNORECASE)
    html = re.sub(r'<[^>]+>', ' ', html)
    for ent, ch in [('&amp;', '&'), ('&lt;', '<'), ('&gt;', '>'), ('&quot;', '"'), ('&nbsp;', ' '), ('&#39;', "'")]:
        html = html.replace(ent, ch)
    html = re.sub(r'[ \t]+', ' ', html)
    html = re.sub(r'\n{3,}', '\n\n', html)
    return html.strip()


def _extract_contacts(text: str) -> str:
    emails = list(dict.fromkeys(_EMAIL_RE.findall(text)))
    phones = list(dict.fromkeys(
        p.strip() for p in _PHONE_RE.findall(text)
        if len(re.sub(r'\D', '', p)) >= 10
    ))
    if not emails and not phones:
        return ''
    lines = ['\n--- CONTACTS FOUND ---']
    if emails:
        lines.append('Emails: ' + ', '.join(emails[:10]))
    if phones:
        lines.append('Phones: ' + ', '.join(phones[:10]))
    return '\n'.join(lines)


def _bfs_crawl(start_url: str, goal_keywords: List[str], max_depth: int, max_pages: int) -> str:
    """BFS crawl with goal-anchored link filtering. Returns aggregated text."""
    visited: Set[str] = set()
    # Queue items: (url, depth)
    queue = deque([(start_url, 0)])
    results = []
    all_contacts = ''

    while queue and len(visited) < max_pages:
        url, depth = queue.popleft()

        if url in visited or _is_blacklisted(url):
            continue
        visited.add(url)

        html = _fetch_page(url)
        if not html:
            continue

        text = _html_to_text(html)
        contacts = _extract_contacts(text)
        if contacts:
            all_contacts += f'\n[{url}]{contacts}'

        # Truncate individual page content
        page_snippet = text[:2000] if len(text) > 2000 else text
        results.append(f'--- PAGE: {url} ---\n{page_snippet}')

        # Don't enqueue more links beyond max_depth
        if depth >= max_depth:
            continue

        # Extract and score links
        links = _extract_links(html, url)
        scored = []
        for link_url, anchor in links:
            if link_url not in visited and not _is_blacklisted(link_url):
                score = _goal_score(link_url, anchor, goal_keywords)
                scored.append((score, link_url))

        # Sort by relevance score descending, then enqueue
        scored.sort(key=lambda x: x[0], reverse=True)
        for score, link_url in scored[:15]:  # max 15 links per page
            if score > 0 or not goal_keywords:
                queue.append((link_url, depth + 1))

    output = '\n\n'.join(results)
    if all_contacts:
        output += f'\n\n=== ALL CONTACTS FOUND ===\n{all_contacts}'
    return output


class SmartCrawlTool(Tool):
    """
    BFS site crawler with URL filtering and goal-anchored navigation.
    Use this when you need to explore a site to find a specific page,
    contact info, or document. Better than fetching one URL at a time.
    """

    @property
    def name(self) -> str:
        return "smart_crawl"

    @property
    def description(self) -> str:
        return (
            "Crawl a website using breadth-first search to find specific content. "
            "Filters out noise URLs (tags, categories, social links) and prioritizes "
            "pages relevant to your goal. Use when you need to navigate a site to find "
            "a contact page, grant application page, careers page, or specific document. "
            "Provide goal keywords to guide which links to follow."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Starting URL to crawl from (must start with http:// or https://)"
                },
                "goal": {
                    "type": "string",
                    "description": "What you are looking for — e.g. 'contact email', 'grant application', 'careers'. Used to prioritize relevant links.",
                    "default": ""
                },
                "max_depth": {
                    "type": "integer",
                    "description": "How many levels deep to crawl (default 2, max 3)",
                    "default": 2
                },
                "max_pages": {
                    "type": "integer",
                    "description": "Maximum number of pages to visit (default 10, max 20)",
                    "default": 10
                },
                "max_chars": {
                    "type": "integer",
                    "description": "Maximum total characters to return (default 10000)",
                    "default": 10000
                }
            },
            "required": ["url"]
        }

    async def execute(self, url: str = "", goal: str = "", max_depth: int = 2,
                      max_pages: int = 10, max_chars: int = 10000, **kwargs) -> str:
        if not url.startswith(("http://", "https://")):
            return "smart_crawl: URL must start with http:// or https://"

        max_depth = min(max_depth, 3)
        max_pages = min(max_pages, 20)

        goal_keywords = [kw.strip() for kw in goal.split() if kw.strip()] if goal else []

        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: _bfs_crawl(url, goal_keywords, max_depth, max_pages)
            )
            if not result.strip():
                return f"smart_crawl: No content retrieved from {url}"
            if len(result) > max_chars:
                result = result[:max_chars] + f'\n\n[... truncated at {max_chars} chars]'
            return f"SMART CRAWL: {url} (goal: '{goal}', depth: {max_depth}, pages: {max_pages})\n\n{result}"
        except Exception as e:
            return f"smart_crawl error: {e}"
