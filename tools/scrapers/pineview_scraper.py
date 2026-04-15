"""
Pineview Buildings Dealer Scraper
WordPress site with Ajax Search Lite plugin.
Fetches nonce from page, then posts to wp-admin/admin-ajax.php with action=asl_search.
Outputs: pineview_dealers.csv
"""
import requests
from bs4 import BeautifulSoup
import csv
import time
import logging
import traceback
import re
import json

DEALERS_URL = "https://pineviewbuildings.com/dealers/"
AJAX_URL = "https://pineviewbuildings.com/wp-admin/admin-ajax.php"
OUTPUT_FILE = "pineview_dealers.csv"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Referer": DEALERS_URL,
}

log = logging.getLogger('pineview_scraper')
if not log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter('[%(name)s] %(levelname)s %(message)s'))
    log.addHandler(_h)
log.setLevel(logging.DEBUG)


def _get_nonce():
    """Fetch the dealers page and extract the ASL nonce."""
    try:
        r = requests.get(DEALERS_URL, headers=HEADERS, timeout=15)
        r.raise_for_status()
        # Look for asl nonce in JS vars
        m = re.search(r'asl_nonce["\s:=]+["\']([a-f0-9]+)["\']', r.text, re.IGNORECASE)
        if m:
            return m.group(1)
        # Fallback: any nonce near the asl plugin
        m = re.search(r'"nonce"\s*:\s*"([a-f0-9]+)"', r.text)
        if m:
            return m.group(1)
        # Last resort: first nonce on page
        m = re.search(r'nonce["\s:=]+["\']([a-f0-9]{10})["\']', r.text)
        if m:
            return m.group(1)
    except Exception:
        log.error("Error fetching nonce:\n%s", traceback.format_exc())
    return None


def _asl_search(nonce, search='', page=1):
    """POST to admin-ajax.php for store locator results."""
    data = {
        'action': 'asl_search',
        'nonce': nonce,
        'search': search,
        'post_type': '',
        'page': page,
    }
    try:
        r = requests.post(AJAX_URL, data=data, headers=HEADERS, timeout=15)
        if r.status_code == 200:
            try:
                return r.json()
            except ValueError:
                # Sometimes returns HTML
                return {'html': r.text}
    except Exception:
        log.error("AJAX search error:\n%s", traceback.format_exc())
    return None


def _parse_dealer_html(html):
    """Parse dealer HTML from ASL response."""
    dealers = []
    soup = BeautifulSoup(html, 'html.parser')

    for item in soup.find_all(['div', 'li', 'article'], class_=re.compile(r'asl|store|dealer|result|item', re.I)):
        name_el = item.find(['h2', 'h3', 'h4', 'strong', 'span'], class_=re.compile(r'name|title', re.I))
        if not name_el:
            name_el = item.find(['h2', 'h3', 'h4'])
        if not name_el:
            continue
        name = name_el.get_text(strip=True)
        if not name:
            continue

        phone_tag = item.find('a', href=lambda x: x and x.startswith('tel:'))
        email_tag = item.find('a', href=lambda x: x and x.startswith('mailto:'))
        addr_tag = item.find(class_=re.compile(r'address|addr', re.I)) or item.find('address')

        phone = phone_tag.get('href', '').replace('tel:', '').strip() if phone_tag else ''
        email = email_tag.get('href', '').replace('mailto:', '').strip() if email_tag else ''
        address = addr_tag.get_text(separator=' ', strip=True)[:120] if addr_tag else ''

        if name:
            dealers.append({'name': name, 'address': address, 'phone': phone, 'email': email, 'url': DEALERS_URL})

    return dealers


def _scrape_static_fallback():
    """If AJAX fails, try reading dealer data directly from static page source."""
    try:
        r = requests.get(DEALERS_URL, headers=HEADERS, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'html.parser')
        dealers = []

        for el in soup.find_all(['div', 'article', 'li']):
            phone_tag = el.find('a', href=lambda x: x and x.startswith('tel:'))
            email_tag = el.find('a', href=lambda x: x and x.startswith('mailto:'))
            if not phone_tag and not email_tag:
                continue
            name_el = el.find(['h2', 'h3', 'h4', 'strong'])
            name = name_el.get_text(strip=True) if name_el else ''
            phone = phone_tag.get('href', '').replace('tel:', '').strip() if phone_tag else ''
            email = email_tag.get('href', '').replace('mailto:', '').strip() if email_tag else ''
            addr_tag = el.find('address') or el.find('p', string=re.compile(r'\d{5}'))
            address = addr_tag.get_text(separator=' ', strip=True)[:120] if addr_tag else ''
            if name or phone:
                dealers.append({'name': name, 'address': address, 'phone': phone, 'email': email, 'url': DEALERS_URL})

        return dealers
    except Exception:
        log.error("Static fallback error:\n%s", traceback.format_exc())
        return []


def run(state_filter=None):
    dealers = []

    log.info("Fetching ASL nonce from %s", DEALERS_URL)
    nonce = _get_nonce()

    if nonce:
        log.info("Got nonce: %s — running AJAX search", nonce)
        # Empty search returns all dealers
        result = _asl_search(nonce, search='')
        if result:
            if isinstance(result, dict) and 'html' in result:
                dealers = _parse_dealer_html(result['html'])
            elif isinstance(result, list):
                for item in result:
                    if isinstance(item, dict):
                        name = item.get('post_title', '') or item.get('name', '')
                        address = item.get('address', '')
                        phone = item.get('phone', '')
                        email = item.get('email', '')
                        if name:
                            dealers.append({'name': name, 'address': address, 'phone': phone, 'email': email, 'url': DEALERS_URL})
            log.info("AJAX returned %d dealers", len(dealers))

    if not dealers:
        log.info("AJAX returned nothing — trying static fallback")
        dealers = _scrape_static_fallback()

    if state_filter:
        state = state_filter.upper()
        dealers = [d for d in dealers if re.search(rf'\b{state}\b', ' '.join([d.get('address', ''), d.get('name', '')]).upper())]
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
