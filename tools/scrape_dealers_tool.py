"""
Scrape Dealers Tool for Scout
Runs the competitor dealer scrapers and returns a list of leads with contact info.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.tool_base import Tool
from typing import Any, Dict


class ScrapeDealersTool(Tool):
    """
    Scrape a competitor's dealer directory and return a list of dealers
    with name, address, phone, email, and URL. Use this to get bulk dealer
    data from competitors instead of fetching pages one by one.
    """

    @property
    def name(self) -> str:
        return "scrape_dealers"

    @property
    def description(self) -> str:
        return (
            "Scrape a competitor's dealer directory and return a structured list of dealers "
            "with name, address, phone, email, and source URL. "
            "Supported competitors: 'old_hickory', 'stor_mor', 'pineview', 'durabuilt', 'alpine'. "
            "Optionally filter by state abbreviation (e.g. state='NC'). "
            "Use this instead of fetching pages one by one when you need bulk dealer data."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "competitor": {
                    "type": "string",
                    "description": "Competitor name: 'old_hickory', 'stor_mor', 'pineview', 'durabuilt', 'alpine'"
                },
                "state": {
                    "type": "string",
                    "description": "Optional 2-letter state abbreviation to filter results (e.g. 'NC', 'VA')"
                },
                "max_pages": {
                    "type": "integer",
                    "description": "Maximum pages to scrape (default 120 for old_hickory)",
                    "default": 120
                }
            },
            "required": ["competitor"]
        }

    async def execute(self, competitor: str = "", state: str = "", max_pages: int = 120, **kw) -> str:
        competitor = competitor.lower().replace(' ', '_').replace('-', '_')
        state = state.upper() if state else None

        if competitor in ('old_hickory', 'old_hickory_buildings'):
            return await self._run_scraper_async('old_hickory', state, max_pages)
        elif competitor in ('stor_mor', 'stormor', 'stor-mor'):
            return await self._run_scraper_async('stor_mor', state)
        elif competitor in ('pineview', 'pine_view', 'pineview_buildings'):
            return await self._run_scraper_async('pineview', state)
        elif competitor in ('durabuilt', 'dura_built', 'dura-built'):
            return await self._run_scraper_async('durabuilt', state)
        elif competitor in ('alpine', 'alpine_structures', 'alpine_buildings'):
            return await self._run_scraper_async('alpine', state)
        else:
            return f"Unsupported competitor: {competitor}. Supported: old_hickory, stor_mor, pineview, durabuilt, alpine"

    async def _run_scraper_async(self, competitor: str, state, max_pages: int = 120) -> str:
        import asyncio
        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(None, self._run_scraper, competitor, state, max_pages)
        except asyncio.CancelledError:
            if competitor == 'old_hickory':
                try:
                    from tools.scrapers import old_hickory_scraper as _s
                    _s._stop_event.set()
                except Exception:
                    pass
            raise
        return result

    def _run_scraper(self, competitor: str, state, max_pages: int = 120) -> str:
        import csv, time

        if competitor == 'old_hickory':
            return self._run_old_hickory(state, max_pages)

        # For other competitors: load their scraper module and run it
        scraper_map = {
            'stor_mor':  ('stormor_scraper.py',  'stormor_dealers.csv'),
            'pineview':  ('pineview_scraper.py', 'pineview_dealers.csv'),
            'durabuilt': ('durabuilt_scraper.py','durabuilt_dealers.csv'),
            'alpine':    ('alpine_scraper.py',   'alpine_dealers.csv'),
        }
        scraper_file, csv_name = scraper_map[competitor]
        csv_path = os.path.join(os.path.dirname(__file__), '..', csv_name)

        # Cache check
        dealers = []
        if os.path.exists(csv_path):
            age_hours = (time.time() - os.path.getmtime(csv_path)) / 3600
            if age_hours < 24:
                try:
                    with open(csv_path, newline='', encoding='utf-8') as f:
                        dealers = list(csv.DictReader(f))
                    print(f"[scrape_dealers] Using cached {competitor} CSV ({len(dealers)} dealers, {age_hours:.1f}h old)")
                except Exception:
                    dealers = []

        if not dealers:
            import importlib.util
            scraper_path = os.path.join(os.path.dirname(__file__), 'scrapers', scraper_file)
            spec = importlib.util.spec_from_file_location(competitor + '_scraper', scraper_path)
            _mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(_mod)
            try:
                dealers = _mod.run(state_filter=None)
            except Exception as e:
                return f"Scraper error for {competitor}: {e}"

        if not dealers:
            return f"No dealers found for {competitor}."

        # State filter
        if state:
            import re
            def matches(d):
                hay = ' '.join([d.get('name',''), d.get('address',''), d.get('url','')]).upper()
                return bool(re.search(rf'\b{state}\b', hay))
            filtered = [d for d in dealers if matches(d)]
            print(f"[scrape_dealers] {competitor} state filter {state}: {len(filtered)}/{len(dealers)}")
            dealers = filtered

        return self._format_results(dealers, competitor)

    def _run_old_hickory(self, state, max_pages) -> str:
        import csv, time
        import importlib.util
        scraper_path = os.path.join(os.path.dirname(__file__), 'scrapers', 'old_hickory_scraper.py')
        spec = importlib.util.spec_from_file_location("old_hickory_scraper", scraper_path)
        _mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_mod)
        _mod._stop_event.clear()

        csv_suffix = f"_{state.lower()}" if state else ""
        csv_path = os.path.join(os.path.dirname(__file__), '..', f'old_hickory{csv_suffix}_dealers.csv')
        # Also check the unsuffixed fallback
        csv_fallback = os.path.join(os.path.dirname(__file__), '..', 'old_hickory_dealers.csv')

        dealers = []
        for check_path in [csv_path, csv_fallback]:
            if os.path.exists(check_path):
                age_hours = (time.time() - os.path.getmtime(check_path)) / 3600
                if age_hours < 24:
                    try:
                        with open(check_path, newline='', encoding='utf-8') as f:
                            dealers = list(csv.DictReader(f))
                        print(f"[scrape_dealers] Using cached CSV ({len(dealers)} dealers, {age_hours:.1f}h old)")
                        break
                    except Exception:
                        dealers = []

        if not dealers:
            try:
                dealers = _mod.run(state_filter=state, max_pages=max_pages)
            except Exception as e:
                _mod._stop_event.set()
                return f"Scraper error: {e}"

        if not dealers:
            return "No dealers found."

        if state:
            from tools.scrapers.old_hickory_scraper import _matches_state
            filtered = [d for d in dealers if _matches_state(d, state)]
            print(f"[scrape_dealers] State filter {state}: {len(filtered)}/{len(dealers)} dealers match")
            dealers = filtered

        return self._format_results(dealers, 'old_hickory')

    def _format_results(self, dealers, competitor) -> str:
        with_email = [d for d in dealers if d.get('email')]
        without_email = [d for d in dealers if not d.get('email')]

        cap = 100
        lines = [f"SCRAPED {len(dealers)} {competitor} dealers ({len(with_email)} with email, {len(without_email)} without)\n"]
        lines.append("--- DEALERS WITH EMAIL (call send_email for each EMAIL_LEAD below) ---")
        for d in with_email[:cap]:
            lines.append(f"EMAIL_LEAD: {d['name']} | {d.get('phone','')} | {d['email']} | {d.get('address','')[:80]}")

        if len(with_email) > cap:
            lines.append(f"... and {len(with_email) - cap} more saved to {competitor}_dealers.csv")

        lines.append(f"\n--- DEALERS WITHOUT EMAIL (search for emails separately) ---")
        for d in without_email[:50]:
            lines.append(f"PHONE_LEAD: {d['name']} | {d.get('phone','')} | {d.get('address','')[:80]}")

        if len(without_email) > 50:
            lines.append(f"... and {len(without_email) - 50} more in {competitor}_dealers.csv")

        lines.append(f"\nAll {len(dealers)} dealers saved to {competitor}_dealers.csv")
        return '\n'.join(lines)
