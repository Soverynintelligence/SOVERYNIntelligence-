"""
Browser Tool for SOVERYN
Uses Playwright to interact with dynamic JavaScript-driven pages.
Handles store locators, map-based dealer finders, and any site
that requires user interaction before data populates.
"""
import asyncio
import re
from core.tool_base import Tool


def _strip_html(html: str) -> str:
    html = re.sub(r'<(script|style|noscript|head)[^>]*>.*?</\1>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<!--.*?-->', ' ', html, flags=re.DOTALL)
    html = re.sub(r'<(br|p|div|li|h[1-6]|tr|blockquote)[^>]*>', '\n', html, flags=re.IGNORECASE)
    html = re.sub(r'<[^>]+>', ' ', html)
    entities = {'&amp;': '&', '&lt;': '<', '&gt;': '>', '&quot;': '"',
                '&apos;': "'", '&nbsp;': ' ', '&#39;': "'"}
    for ent, ch in entities.items():
        html = html.replace(ent, ch)
    html = re.sub(r'[ \t]+', ' ', html)
    html = re.sub(r'\n{3,}', '\n\n', html)
    return html.strip()


class BrowserFetchTool(Tool):
    """
    Fetch content from a dynamic JavaScript-rendered page using a real browser.
    Use this when web_fetch returns empty or skeleton content because the page
    requires JavaScript to load (store locators, map-based dealer finders, etc).
    """

    @property
    def name(self): return "browser_fetch"

    @property
    def description(self):
        return (
            "Fetch content from a JavaScript-rendered page using a real browser. "
            "Use when web_fetch fails or returns empty results because the page uses "
            "dynamic loading (store locators, dealer maps, search forms). "
            "Can optionally type text into a search field and click a button before extracting content."
        )

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Full URL to open in the browser"
                },
                "search_text": {
                    "type": "string",
                    "description": "Optional: text to type into a search/input field before extracting content (e.g. a zip code)"
                },
                "search_selector": {
                    "type": "string",
                    "description": "Optional: CSS selector for the input field to type into (default: input[type='text'], input[type='search'])"
                },
                "click_selector": {
                    "type": "string",
                    "description": "Optional: CSS selector for a button to click after typing (e.g. 'button[type=submit]')"
                },
                "wait_seconds": {
                    "type": "number",
                    "description": "Seconds to wait after page load or button click for content to render (default: 3)"
                },
                "max_chars": {
                    "type": "integer",
                    "description": "Maximum characters to return (default: 8000)",
                    "default": 8000
                },
                "intercept_api": {
                    "type": "boolean",
                    "description": "If true, capture XHR/fetch API responses made by the page — useful for finding hidden dealer data endpoints. Returns captured JSON responses.",
                    "default": False
                }
            },
            "required": ["url"]
        }

    async def execute(self, url: str = "", search_text: str = "", search_selector: str = "",
                      click_selector: str = "", wait_seconds: float = 3.0,
                      max_chars: int = 8000, intercept_api: bool = False, **kw) -> str:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return "BrowserFetchTool: playwright not installed. Run: pip install playwright && playwright install chromium"

        captured_responses = []

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
                )
                page = await context.new_page()

                if intercept_api:
                    async def handle_response(response):
                        content_type = response.headers.get("content-type", "")
                        if "json" in content_type and response.status == 200:
                            try:
                                body = await response.text()
                                if len(body) > 100:
                                    captured_responses.append({
                                        "url": response.url,
                                        "body": body[:3000]
                                    })
                            except Exception:
                                pass
                    page.on("response", handle_response)

                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(wait_seconds)

                if search_text:
                    selector = search_selector or "input[type='text'], input[type='search'], input:not([type])"
                    try:
                        await page.fill(selector, search_text)
                        await asyncio.sleep(0.5)
                    except Exception as e:
                        print(f"[BrowserFetch] Could not fill input: {e}")

                if click_selector:
                    try:
                        await page.click(click_selector)
                        await asyncio.sleep(wait_seconds)
                    except Exception as e:
                        print(f"[BrowserFetch] Could not click: {e}")
                elif search_text:
                    try:
                        await page.keyboard.press("Enter")
                        await asyncio.sleep(wait_seconds)
                    except Exception:
                        pass

                html = await page.content()
                await browser.close()

            text = _strip_html(html)
            if len(text) > max_chars:
                text = text[:max_chars] + f"\n\n[... truncated at {max_chars} chars]"

            result = f"BROWSER_FETCH: {url}\n\n{text}"

            if intercept_api and captured_responses:
                result += "\n\n--- CAPTURED API RESPONSES ---\n"
                for r in captured_responses[:5]:
                    result += f"\nAPI URL: {r['url']}\n{r['body'][:1500]}\n"

            return result

        except Exception as ex:
            return f"BrowserFetchTool error: {ex}"
