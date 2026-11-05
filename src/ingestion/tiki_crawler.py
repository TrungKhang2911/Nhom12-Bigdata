"""Tiki product reviews from the public JSON API behind tiki.vn product pages.

Review and product dicts are kept exactly as returned; cleaning and the unified
schema belong to the processing stage. Used by src.ingestion.collect through
source_pages.pages, which persists each page and its cursor atomically.
"""
import time

import requests

from src.ingestion.common import envelope, retry

PRODUCT_URL = 'https://tiki.vn/api/v2/products/{}'
REVIEWS_URL = 'https://tiki.vn/api/v2/reviews'
PAGE_SIZE = 20  # Tiki answers HTTP 400 "Query limitation is: 20" above this.
# Newest first: new reviews only push older ones to later pages, so a resumed
# run re-reads a few (ignored by review ID) instead of skipping any.
NEWEST_FIRST = 'id|desc'


def pages(job, cursor, *, delay, attempts, timeout):
    """Yield (raw_events, next_cursor, exhausted) per review page from cursor['page']."""
    product_id = job['app_id']
    with requests.Session() as session:
        session.headers.update({'User-Agent': 'MultiDomainSentimentResearch/1.0',
                                'Accept': 'application/json'})

        def get(url, **kwargs):
            def request():
                response = session.get(url, timeout=timeout, **kwargs)
                response.raise_for_status()
                return response
            return retry(request, attempts).json()

        product = get(PRODUCT_URL.format(product_id))
        if not isinstance(product, dict) or 'id' not in product:
            raise ValueError(f'Unexpected Tiki product response for {product_id}')
        page = cursor.get('page', 1)
        while True:
            time.sleep(delay)
            payload = get(REVIEWS_URL, params={'product_id': product_id, 'page': page,
                                               'limit': PAGE_SIZE, 'sort': NEWEST_FIRST})
            reviews, last_page = parse_page(payload, page)
            rows = [envelope('tiki', product_id, job['country'], None, product, review)
                    for review in reviews]
            exhausted = not reviews or page >= last_page
            yield rows, {'page': page + 1}, exhausted
            if exhausted:
                return
            page += 1


def parse_page(payload, page):
    """Return (reviews, last_page); fail loudly if Tiki changes the page format."""
    if isinstance(payload, dict):
        reviews, paging = payload.get('data'), payload.get('paging')
        if (isinstance(reviews, list) and all(isinstance(row, dict) for row in reviews)
                and isinstance(paging, dict) and type(paging.get('last_page')) is int):
            return reviews, paging['last_page']
    raise ValueError(f'Unexpected Tiki review page {page}')
