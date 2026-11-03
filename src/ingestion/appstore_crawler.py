"""Public Apple RSS reviews by storefront; this is not a full historical API."""
import logging
import re
import time

import requests

from src.ingestion.common import envelope, retry, validate_options

logger = logging.getLogger(__name__)


def crawl(app_id: str, *, country='vn', limit=500, max_pages=10,
          delay=1.0, attempts=3, timeout=30.0):
    validate_options(country, limit, delay, attempts)
    if not re.fullmatch(r'[0-9]+', str(app_id)):
        raise ValueError('App Store app_id must contain digits only')
    if not 1 <= max_pages <= 10 or timeout <= 0:
        raise ValueError('max_pages must be 1..10; timeout must be positive')
    country = country.lower()
    emitted = 0
    with requests.Session() as session:
        session.headers.update({'User-Agent': 'MultiDomainSentimentResearch/1.0',
                                'Accept': 'application/json'})

        def get_json(url, **kwargs):
            def request():
                response = session.get(url, timeout=timeout, **kwargs)
                response.raise_for_status()
                return response
            return retry(request, attempts).json()

        lookup = get_json('https://itunes.apple.com/lookup',
                          params={'id': app_id, 'country': country, 'entity': 'software'})
        if not isinstance(lookup, dict) or not isinstance(lookup.get('results'), list):
            raise ValueError('Unexpected Apple lookup response')
        if not lookup['results']:
            raise ValueError(f'App {app_id} was not found in storefront {country}')
        metadata = lookup['results'][0]
        for page in range(1, max_pages + 1):
            if emitted >= limit:
                break
            time.sleep(delay)
            url = (f'https://itunes.apple.com/{country}/rss/customerreviews/'
                   f'page={page}/id={app_id}/sortby=mostrecent/json')
            payload = get_json(url)
            if not isinstance(payload, dict) or not isinstance(payload.get('feed'), dict):
                raise ValueError(f'Unexpected Apple review feed on page {page}')
            entries = payload['feed'].get('entry', [])
            if isinstance(entries, dict):
                entries = [entries]
            if not isinstance(entries, list) or any(not isinstance(e, dict) for e in entries):
                raise ValueError(f'Unexpected Apple review entries on page {page}')
            # Some feeds include the application entry alongside reviews.
            page_reviews = [entry for entry in entries if 'im:rating' in entry]
            if not page_reviews:
                logger.warning('Apple %s page %d has no reviews; checking remaining pages',
                               app_id, page)
            for review in page_reviews[:limit - emitted]:
                yield envelope('app_store', app_id, country, None, metadata, review)
                emitted += 1
    logger.info('App Store %s: collected %d reviews (requested up to %d)',
                app_id, emitted, limit)
