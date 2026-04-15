"""
Stor-Mor Portable Buildings Dealer Scraper
Uses the storelocatorwidgets.com API (site alias 334cf723) to get dealer data.
Falls back to fetching individual state pages via browser if API unavailable.
Outputs: stormor_dealers.csv
"""
import requests
import csv
import time
import logging
import traceback
import re
import json

OUTPUT_FILE = "stormor_dealers.csv"
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"}

# storelocatorwidgets.com API — site alias extracted from stormor.com page source
WIDGET_SITE = "334cf723"
WIDGET_API_BASE = "https://www.storelocatorwidgets.com"

log = logging.getLogger('stormor_scraper')
if not log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter('[%(name)s] %(levelname)s %(message)s'))
    log.addHandler(_h)
log.setLevel(logging.DEBUG)


def _try_widget_api():
    """Attempt to pull all dealers from the storelocatorwidgets.com API."""
    # Common endpoint patterns for this widget service
    endpoints = [
        f"{WIDGET_API_BASE}/api/getlocations?site={WIDGET_SITE}",
        f"{WIDGET_API_BASE}/ajax/getlocations?site={WIDGET_SITE}",
        f"{WIDGET_API_BASE}/locations?site={WIDGET_SITE}&format=json",
        f"https://api.storelocatorwidgets.com/locations?site={WIDGET_SITE}",
    ]
    for url in endpoints:
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            if r.status_code == 200:
                try:
                    data = r.json()
                    if data:
                        log.info("Widget API hit on %s — %d records", url, len(data) if isinstance(data, list) else 1)
                        return data
                except ValueError:
                    pass
        except Exception:
            pass
    return None


def _parse_widget_response(data):
    """Parse storelocatorwidgets API response into dealer dicts."""
    dealers = []
    items = data if isinstance(data, list) else data.get('locations', data.get('results', []))
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get('name') or item.get('title') or item.get('store_name', '')
        address_parts = [
            item.get('address', ''),
            item.get('address2', ''),
            item.get('city', ''),
            item.get('state', ''),
            item.get('zip', ''),
        ]
        address = ' '.join(p for p in address_parts if p).strip()
        phone = item.get('phone', '') or item.get('telephone', '')
        email = item.get('email', '')
        if name:
            dealers.append({'name': name, 'address': address, 'phone': phone, 'email': email, 'url': ''})
    return dealers


# State pages found in sitemap — 28 states
_STATE_SLUGS = [
    'alabama', 'arkansas', 'florida', 'georgia', 'illinois', 'indiana',
    'iowa', 'kansas', 'kentucky', 'louisiana', 'maryland', 'michigan',
    'minnesota', 'mississippi', 'missouri', 'nebraska', 'new-york',
    'north-carolina', 'ohio', 'oklahoma', 'pennsylvania', 'south-carolina',
    'tennessee', 'texas', 'virginia', 'west-virginia', 'wisconsin', 'wyoming',
]

def _scrape_state_page(state_slug):
    """Fetch a Stor-Mor state page and extract any static dealer data."""
    url = f"https://www.stormor.com/stor-mor-locations/{state_slug}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return []
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.text, 'html.parser')

        dealers = []
        # Look for dealer cards, list items, or structured dealer blocks
        for el in soup.find_all(['article', 'div', 'li'], class_=re.compile(r'dealer|location|store|card', re.I)):
            name_el = el.find(['h2', 'h3', 'h4', 'strong'])
            if not name_el:
                continue
            name = name_el.get_text(strip=True)
            if not name or len(name) < 3:
                continue
            phone_tag = el.find('a', href=lambda x: x and x.startswith('tel:'))
            email_tag = el.find('a', href=lambda x: x and x.startswith('mailto:'))
            addr_tag = el.find('address') or el.find('p')
            phone = phone_tag.get('href', '').replace('tel:', '').strip() if phone_tag else ''
            email = email_tag.get('href', '').replace('mailto:', '').strip() if email_tag else ''
            address = addr_tag.get_text(separator=' ', strip=True)[:120] if addr_tag else ''
            dealers.append({'name': name, 'address': address, 'phone': phone, 'email': email, 'url': url})

        # Also try shedsuite individual pages linked from here
        for a in soup.find_all('a', href=re.compile(r'shedsuite\.com|stormor\.shedsuite')):
            href = a['href']
            dealer_data = _scrape_shedsuite_page(href)
            if dealer_data:
                dealers.append(dealer_data)

        return dealers
    except Exception:
        log.error("Error on state page %s:\n%s", url, traceback.format_exc())
        return []


def _scrape_shedsuite_page(url):
    """Individual Stor-Mor dealer pages on shedsuite.com often have contact emails."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return None
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.text, 'html.parser')
        name_el = soup.find('h1') or soup.find('h2')
        name = name_el.get_text(strip=True) if name_el else ''
        if not name:
            return None
        phone_tag = soup.find('a', href=lambda x: x and x.startswith('tel:'))
        email_tag = soup.find('a', href=lambda x: x and x.startswith('mailto:'))
        addr_tag = soup.find('address') or soup.find('p', string=re.compile(r'\d{5}'))
        phone = phone_tag.get('href', '').replace('tel:', '').strip() if phone_tag else ''
        email = email_tag.get('href', '').replace('mailto:', '').strip() if email_tag else ''
        address = addr_tag.get_text(separator=' ', strip=True)[:120] if addr_tag else ''
        if name and (phone or email or address):
            return {'name': name, 'address': address, 'phone': phone, 'email': email, 'url': url}
    except Exception:
        pass
    return None


def run(state_filter=None):
    dealers = []

    # Try widget API first
    log.info("Attempting storelocatorwidgets.com API...")
    api_data = _try_widget_api()
    if api_data:
        dealers = _parse_widget_response(api_data)
        log.info("Widget API returned %d dealers", len(dealers))
    else:
        # Fall back to state pages
        log.info("Widget API unavailable — scraping %d state pages", len(_STATE_SLUGS))
        for slug in _STATE_SLUGS:
            results = _scrape_state_page(slug)
            dealers.extend(results)
            log.info("State %s: %d dealers (total: %d)", slug, len(results), len(dealers))
            time.sleep(0.5)

    if not dealers:
        log.warning("No dealers found via any method")
        return []

    if state_filter:
        state = state_filter.upper()
        dealers = [d for d in dealers if re.search(rf'\b{state}\b', ' '.join([d.get('address', ''), d.get('url', ''), d.get('name', '')]).upper())]
        log.info("After state filter (%s): %d dealers", state, len(dealers))

    with open(OUTPUT_FILE, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['name', 'address', 'phone', 'email', 'url'])
        writer.writeheader()
        writer.writerows(dealers)

    log.info("Done. %d dealers saved to %s", len(dealers), OUTPUT_FILE)
    return dealers


if __name__ == '__main__':
    import sys
    logging.basicConfig(level=logging.DEBUG)
    state = sys.argv[1] if len(sys.argv) > 1 else None
    run(state_filter=state)
