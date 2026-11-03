"""Google Play reviews, retaining all fields returned by google-play-scraper."""
import logging
import re
import time

from google_play_scraper import Sort, app, reviews

from src.ingestion.common import envelope, retry, validate_options

logger = logging.getLogger(__name__)


def crawl(app_id: str, *, country='vn', language='vi', limit=1000,
          batch_size=199, delay=1.0, attempts=3):
    validate_options(country, limit, delay, attempts)
    if not re.fullmatch(r'[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+', app_id):
        raise ValueError('Google Play app_id must be a package name')
    if not 1 <= batch_size <= 199:
        raise ValueError('batch_size must be between 1 and 199')
    country = country.lower()
    metadata = retry(lambda: app(app_id, lang=language, country=country), attempts)
    token = None
    emitted = 0
    seen_tokens = set()
    while emitted < limit:
        time.sleep(delay)
        batch, next_token = retry(
            lambda: reviews(app_id, lang=language, country=country,
                            sort=Sort.NEWEST, count=min(batch_size, limit - emitted),
                            continuation_token=token), attempts,
        )
        if not isinstance(batch, list):
            raise ValueError('Unexpected Google Play review response')
        if not batch:
            break
        for review in batch[:limit - emitted]:
            yield envelope('google_play', app_id, country, language, metadata, review)
            emitted += 1
        marker = getattr(next_token, 'token', None)
        if not marker:
            break
        if marker in seen_tokens:
            raise RuntimeError('Google Play returned a repeated continuation token')
        seen_tokens.add(marker)
        token = next_token
    logger.info('Google Play %s: collected %d reviews', app_id, emitted)
