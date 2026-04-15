"""
Alpine Structures Dealer Scraper
Static Squarespace site — two-pass: collect location URLs, fetch each for contact data.
Outputs: alpine_dealers.csv
"""
import requests
from bs4 import BeautifulSoup
import csv
import time
import logging
import traceback

BASE_URL = "https://www.alpinebuildings.com"
LOCATIONS_URL = "https://www.alpinebuildings.com/locations"
OUTPUT_FILE = "alpine_dealers.csv"
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"}

log = logging.getLogger('alpine_scraper')
if not log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter('[%(name)s] %(levelname)s %(message)s'))
    log.addHandler(_h)
log.setLevel(logging.DEBUG)


def collect_location_urls():
    try:
        r = requests.get(LOCATIONS_URL, headers=HEADERS, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'html.parser')
        urls = []
        seen = set()
        for a in soup.find_all('a', href=True):
            href = a['href']
            if '/locations/' in href and href.rstrip('/') != LOCATIONS_URL.rstrip('/'):
                full = href if href.startswith('http') else BASE_URL + href
                full = full.rstrip('/')
                if full not in seen:
                    seen.add(full)
                    urls.append(full)
        log.info("Found %d location URLs", len(urls))
        return urls
    except Exception:
        log.error("Error collecting location URLs:\n%s", traceback.format_exc())
        return []


def scrape_location_page(url):
    time.sleep(0.5)
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            log.debug("HTTP %d on %s", r.status_code, url)
            return None

        soup = BeautifulSoup(r.text, 'html.parser')

        # Dealer name: h3 is the business name (h1/h2 are Alpine SEO page titles)
        name = ''
        for tag in soup.find_all('h3'):
            t = tag.get_text(strip=True)
            # Skip Alpine's own section headings
            if t and len(t) > 2 and 'alpine' not in t.lower() and 'choose' not in t.lower():
                name = t
                break
        if not name:
            # Fallback: contact person name from "Contact: ..." paragraph
            for p in soup.find_all('p'):
                t = p.get_text(strip=True)
                if t.lower().startswith('contact:'):
                    name = t[8:].strip()
                    break
        if not name:
            log.warning("No dealer name on %s", url)
            return None

        # Phone: first tel: link
        phone = ''
        phone_tag = soup.find('a', href=lambda x: x and x.startswith('tel:'))
        if phone_tag:
            phone = phone_tag.get('href', '').replace('tel:', '').strip()

        # Email: prefer dealer-specific email over Alpine corporate inquiries@ fallback
        email = ''
        for a in soup.find_all('a', href=lambda x: x and x.startswith('mailto:')):
            raw = a.get('href', '').replace('mailto:', '').split('?')[0].strip()
            if not raw:
                continue
            # Skip corporate fallback
            if 'inquiries@alpinebuildings.com' in raw:
                continue
            email = raw
            break

        # Address: first paragraph containing a zip code
        address = ''
        import re
        for p in soup.find_all('p'):
            text = p.get_text(separator=' ', strip=True)
            if re.search(r'\b\d{5}\b', text) and len(text) > 10:
                address = text[:120]
                break

        # Contact person
        contact = ''
        for p in soup.find_all('p'):
            text = p.get_text(strip=True)
            if text.lower().startswith('contact:'):
                contact = text[8:].strip()
                break

        log.info("OK: %s | %s | %s", name, phone, address[:50])
        return {'name': name, 'address': address, 'phone': phone, 'email': email, 'contact': contact, 'url': url}

    except Exception:
        log.error("Error on %s:\n%s", url, traceback.format_exc())
        return None


def run(state_filter=None):
    urls = collect_location_urls()
    if not urls:
        log.error("No location URLs found")
        return []

    dealers = []
    for url in urls:
        result = scrape_location_page(url)
        if result:
            dealers.append(result)

    if state_filter:
        import re
        state = state_filter.upper()
        dealers = [d for d in dealers if re.search(rf'\b{state}\b', ' '.join([d.get('address', ''), d.get('url', ''), d.get('name', '')]).upper())]
        log.info("After state filter (%s): %d dealers", state, len(dealers))

    with open(OUTPUT_FILE, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['name', 'address', 'phone', 'email', 'contact', 'url'])
        writer.writeheader()
        writer.writerows(dealers)

    log.info("Done. %d dealers saved to %s", len(dealers), OUTPUT_FILE)
    return dealers


if __name__ == '__main__':
    import sys
    logging.basicConfig(level=logging.DEBUG)
    state = sys.argv[1] if len(sys.argv) > 1 else None
    run(state_filter=state)
