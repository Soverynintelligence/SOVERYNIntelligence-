"""
Old Hickory Buildings Dealer Scraper — Two-Pass
Pass 1: paginate listing pages to collect dealer URLs
Pass 2: fetch each dealer page for real contact data
Outputs: CSV to old_hickory_dealers.csv
"""
import requests
from bs4 import BeautifulSoup
import csv
import time
import re
import logging
import traceback
import tracemalloc
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE_URL   = "https://oldhickorybuildings.com/locations/page/{}/"
PAGE_1_URL = "https://oldhickorybuildings.com/locations/"
OUTPUT_FILE = "old_hickory_dealers.csv"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}

_STATE_RE = re.compile(
    r'\b(AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|'
    r'MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY)\b'
)


# ─── LOGGING ──────────────────────────────────────────────────────────────────

log = logging.getLogger('old_hickory_scraper')
if not log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter('[%(name)s] %(levelname)s %(message)s'))
    log.addHandler(_h)
log.setLevel(logging.DEBUG)

# Stop flag — set this to abort an in-progress scrape cleanly
import threading
_stop_event = threading.Event()


# ─── PASS 1: collect dealer URLs from listing pages ───────────────────────────

def _get_listing_page(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code == 404:
            return None  # end of pages
        # 406 = "Not Acceptable" but site still returns valid HTML — proceed
        if r.status_code not in (200, 406):
            log.warning("Listing page %s returned HTTP %d", url, r.status_code)
            return []

        soup = BeautifulSoup(r.text, 'html.parser')

        # Explicit check: listing pages must have at least one article or location link
        articles = soup.find_all('article')
        location_links = [
            a['href'] for a in soup.find_all('a', href=True)
            if '/locations/' in a['href']
            and 'page/' not in a['href']
            and a['href'].rstrip('/') != PAGE_1_URL.rstrip('/')
        ]

        if not articles and not location_links:
            log.warning("Page %s: no articles or location links found — unexpected structure", url)
            log.debug("Page HTML sample: %s", r.text[:500])

        return list(dict.fromkeys(h.rstrip('/') for h in location_links))

    except requests.exceptions.Timeout:
        log.error("Timeout fetching listing page %s", url)
        return []
    except Exception:
        log.error("Unexpected error fetching listing page %s:\n%s", url, traceback.format_exc())
        return []


def collect_dealer_urls(max_pages=120):
    all_urls = []
    seen = set()

    result = _get_listing_page(PAGE_1_URL)
    if result is None:
        raise RuntimeError("Page 1 of dealer listings returned 404 — URL may have changed")
    if not result:
        log.warning("Page 1 returned no dealer links — site structure may have changed")
    for u in result:
        if u not in seen:
            seen.add(u)
            all_urls.append(u)
    log.info("Page 1: %d links", len(result))

    for page in range(2, max_pages + 1):
        if _stop_event.is_set():
            log.info("Stop requested — halting at page %d", page)
            break
        result = _get_listing_page(BASE_URL.format(page))
        if result is None:
            log.info("Page %d: end of pages", page)
            break
        new = [u for u in result if u not in seen]
        for u in new:
            seen.add(u)
            all_urls.append(u)
        log.info("Page %d: %d links (%d total unique)", page, len(result), len(all_urls))
        time.sleep(0.5)

    return all_urls


# ─── PASS 2: fetch each dealer page for real contact data ────────────────────

def _diagnose(has_tel, has_mailto, has_digits, has_zip, page_len):
    """Return a plain-English reason why contact extraction failed."""
    if page_len < 5000:
        return "page suspiciously small — likely a redirect, error page, or bot block"
    if not has_tel and not has_digits and not has_zip:
        return "no phone data anywhere in page — dealer may have no listing or page is JS-rendered shell"
    if has_digits and not has_tel:
        return "phone digits present in text but no tel: href — number is plain text, not a link; parser needs regex extraction"
    if has_tel and not has_mailto:
        return "tel: link exists but wasn't captured — selector mismatch or link is inside an iframe/shadow DOM"
    if has_zip and not has_tel:
        return "address-like content present but no phone found — partial listing, dealer may be inactive"
    return "contact data may be JS-rendered and not present in static HTML"


def scrape_dealer_page(url):
    time.sleep(1.5)  # stagger concurrent requests — site rate-limits fast bursts
    for attempt in range(3):
        try:
            r = requests.get(url, headers=HEADERS, timeout=40)
            break
        except requests.exceptions.Timeout:
            wait = 10 * (attempt + 1)
            log.warning("Timeout on %s (attempt %d/3) — retrying in %ds", url, attempt + 1, wait)
            time.sleep(wait)
    else:
        log.error("Timeout fetching dealer page %s — giving up after 3 attempts", url)
        return None
    try:
        if r.status_code not in (200, 406):
            log.debug("Dealer page %s returned HTTP %d — skipping", url, r.status_code)
            return None

        soup = BeautifulSoup(r.text, 'html.parser')

        # Name
        name = ''
        h1 = soup.find('h1')
        if h1:
            name = h1.get_text(strip=True)
        if not name:
            title = soup.find('title')
            if title:
                name = title.get_text(strip=True).split('|')[0].strip()
        if not name:
            log.warning("No name found on %s — skipping", url)
            return None

        # ── Preferred path: structured location-column elements ──
        location_columns = soup.find_all(class_='location-column')
        if location_columns:
            addr_tag  = soup.find('p', class_='location-address')
            phone_tag = soup.find('a', class_='location-phone')
            email_tag = soup.find('a', href=lambda x: x and x.startswith('mailto:'))
            address = addr_tag.get_text(separator=' ', strip=True) if addr_tag else ''
            phone   = ''
            if phone_tag:
                phone = phone_tag.get_text(strip=True) or phone_tag.get('href', '').replace('tel:', '').strip()
            email = email_tag['href'].replace('mailto:', '').strip() if email_tag else ''
            source = 'structured'
        else:
            # ── Fallback: scan full page for any tel/mailto/address elements ──
            log.warning("MISSING location-column on %s — falling back to full-page scan", url)
            phone_tag = soup.find('a', href=lambda x: x and x.startswith('tel:'))
            email_tag = soup.find('a', href=lambda x: x and x.startswith('mailto:'))
            addr_tag  = soup.find('address') or soup.find('p', string=re.compile(r'\d{5}'))
            address = addr_tag.get_text(separator=' ', strip=True)[:200] if addr_tag else ''
            phone   = phone_tag.get('href', '').replace('tel:', '').strip() if phone_tag else ''
            email   = email_tag['href'].replace('mailto:', '').strip() if email_tag else ''
            source  = 'fallback'
            log.debug("Fallback result for %s — address=%r phone=%r email=%r", url, address, phone, email)

        # Must have at least something useful beyond just a name
        if not address and not phone and not email:
            # Diagnose WHY — what was actually on the page
            all_links   = [a.get('href','') for a in soup.find_all('a', href=True)]
            all_text    = soup.get_text(separator=' ', strip=True)
            has_tel     = any('tel:' in h for h in all_links)
            has_mailto  = any('mailto:' in h for h in all_links)
            has_digits  = bool(re.search(r'\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b', all_text))
            has_zip     = bool(re.search(r'\b\d{5}\b', all_text))
            page_len    = len(r.text)
            log.warning(
                "[%s] %s — name='%s' zero contact data. "
                "Diagnosis: page_bytes=%d tel_links=%s mailto_links=%s "
                "phone_pattern_in_text=%s zip_in_text=%s. "
                "Likely cause: %s",
                source, url, name, page_len,
                has_tel, has_mailto, has_digits, has_zip,
                _diagnose(has_tel, has_mailto, has_digits, has_zip, page_len)
            )
            return None

        return {'name': name, 'address': address, 'phone': phone, 'email': email, 'url': url}

    except requests.exceptions.Timeout:
        log.error("Timeout fetching dealer page %s", url)
        return None
    except Exception:
        log.error("Unexpected error on dealer page %s:\n%s", url, traceback.format_exc())
        return None


# ─── STATE FILTER ─────────────────────────────────────────────────────────────

def _matches_state(dealer, state):
    state = state.upper()
    haystack = ' '.join([
        dealer.get('name', ''),
        dealer.get('address', ''),
        dealer.get('url', ''),
    ]).upper()
    return bool(re.search(rf'\b{state}\b', haystack))


# ─── MAIN ────────────────────────────────────────────────────────────────────

def run(state_filter=None, max_pages=120):
    tracemalloc.start()
    t0 = time.time()

    log.info("Pass 1: collecting dealer URLs from listing pages...")
    try:
        urls = collect_dealer_urls(max_pages=max_pages)
    except RuntimeError as e:
        log.error("Pass 1 failed: %s", e)
        return []

    log.info("Found %d unique dealer URLs. Starting Pass 2...", len(urls))

    dealers = []
    done = 0

    MEMORY_WARN_MB = 500  # log top allocators if peak exceeds this

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {pool.submit(scrape_dealer_page, u): u for u in urls}
        for future in as_completed(futures):
            done += 1
            result = future.result()
            if result:
                dealers.append(result)
            if done % 50 == 0:
                current, peak = tracemalloc.get_traced_memory()
                log.info(
                    "Progress: %d/%d pages | %d dealers | mem current=%.1fMB peak=%.1fMB",
                    done, len(urls), len(dealers),
                    current / 1_048_576, peak / 1_048_576
                )

    # Session-wide peak — covers the entire scrape from tracemalloc.start()
    current_final, peak_final = tracemalloc.get_traced_memory()
    elapsed = time.time() - t0

    log.info(
        "Pass 2 complete: %d/%d pages yielded dealer data (%.0fs elapsed) | "
        "mem final=%.1fMB session_peak=%.1fMB",
        len(dealers), len(urls), elapsed,
        current_final / 1_048_576, peak_final / 1_048_576
    )

    if peak_final / 1_048_576 > MEMORY_WARN_MB:
        log.warning("Peak memory %.1fMB exceeds threshold — top allocators:", peak_final / 1_048_576)
        snapshot = tracemalloc.take_snapshot()
        for stat in snapshot.statistics('lineno')[:10]:
            log.warning("  %s", stat)

    tracemalloc.stop()

    if state_filter:
        dealers = [d for d in dealers if _matches_state(d, state_filter)]
        log.info("After state filter (%s): %d dealers", state_filter, len(dealers))

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
