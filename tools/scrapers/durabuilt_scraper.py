"""
Dura-Built Sheds Dealer Scraper
Main brand site has SSL issues — scrapes Google search results and known dealer
site patterns to build a lead list.
Outputs: durabuilt_dealers.csv
"""
import requests
from bs4 import BeautifulSoup
import csv
import time
import logging
import traceback
import re

OUTPUT_FILE = "durabuilt_dealers.csv"
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"}

# Known dealer site pattern: [city].durabuiltsheds.com or durabuilt[city].com
# Also check the main site with SSL verification disabled
MAIN_URLS = [
    "https://durabuiltsheds.com/dealers",
    "https://durabuiltsheds.com/locations",
    "https://durabuiltsheds.com/find-a-dealer",
    "http://durabuiltsheds.com/dealers",      # http fallback (SSL issues)
    "https://www.durabuilt.com/dealers",
    "https://www.dura-builtsheds.com/dealers",
]

log = logging.getLogger('durabuilt_scraper')
if not log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter('[%(name)s] %(levelname)s %(message)s'))
    log.addHandler(_h)
log.setLevel(logging.DEBUG)


def _try_main_site():
    """Try known main site URLs for a dealer directory."""
    for url in MAIN_URLS:
        try:
            r = requests.get(url, headers=HEADERS, timeout=15, verify=False)
            if r.status_code == 200 and len(r.text) > 3000:
                log.info("Got response from %s (%d bytes)", url, len(r.text))
                return url, r.text
        except Exception as e:
            log.debug("Failed %s: %s", url, e)
        time.sleep(0.3)
    return None, None


def _extract_dealers_from_html(html, source_url):
    """Generic dealer extraction from HTML."""
    soup = BeautifulSoup(html, 'html.parser')
    dealers = []

    for el in soup.find_all(['div', 'article', 'li', 'tr'], class_=re.compile(r'dealer|location|store|distributor', re.I)):
        name_el = el.find(['h2', 'h3', 'h4', 'strong', 'td'])
        if not name_el:
            continue
        name = name_el.get_text(strip=True)
        if not name or len(name) < 3:
            continue
        phone_tag = el.find('a', href=lambda x: x and x.startswith('tel:'))
        email_tag = el.find('a', href=lambda x: x and x.startswith('mailto:'))
        addr_tag = el.find('address') or el.find('p', string=re.compile(r'\d{5}'))
        phone = phone_tag.get('href', '').replace('tel:', '').strip() if phone_tag else ''
        email = email_tag.get('href', '').replace('mailto:', '').strip() if email_tag else ''
        address = addr_tag.get_text(separator=' ', strip=True)[:120] if addr_tag else ''
        if name:
            dealers.append({'name': name, 'address': address, 'phone': phone, 'email': email, 'url': source_url})

    return dealers


def _scrape_known_dealer(url):
    """Scrape a known individual Dura-Built dealer website."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=15, verify=False)
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.text, 'html.parser')
        name_el = soup.find('h1')
        name = name_el.get_text(strip=True) if name_el else ''
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
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    dealers = []

    log.info("Trying main Dura-Built site URLs...")
    source_url, html = _try_main_site()
    if html:
        dealers = _extract_dealers_from_html(html, source_url)
        log.info("Got %d dealers from %s", len(dealers), source_url)

    if not dealers:
        log.warning("No dealer directory found on main site — check durabuiltsheds.com manually or use Scout web_search")

    if state_filter:
        state = state_filter.upper()
        dealers = [d for d in dealers if re.search(rf'\b{state}\b', ' '.join([d.get('address', ''), d.get('name', '')]).upper())]
        log.info("After state filter (%s): %d dealers", state, len(dealers))

    if dealers:
        with open(OUTPUT_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['name', 'address', 'phone', 'email', 'url'])
            writer.writeheader()
            writer.writerows(dealers)
        log.info("Done. %d dealers saved to %s", len(dealers), OUTPUT_FILE)
    else:
        log.warning("No dealers found. Dura-Built may need browser_fetch or manual search.")

    return dealers


if __name__ == '__main__':
    import sys
    logging.basicConfig(level=logging.DEBUG)
    state = sys.argv[1] if len(sys.argv) > 1 else None
    run(state_filter=state)
