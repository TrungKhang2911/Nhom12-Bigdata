"""Resumable page adapters for local collection; raw review fields are preserved."""
import time

import requests
from google_play_scraper import Sort
from google_play_scraper.features.reviews import _ContinuationToken

from src.ingestion.common import envelope, retry
from src.ingestion.google_transport import call


def google_pages(job, cursor, *, delay, attempts, timeout):
    app_id, country, language = job['app_id'], job['country'], job['language']
    metadata = retry(lambda: call('app', app_id, {'country': country, 'lang': language}, timeout), attempts)
    marker = cursor.get('token')
    seen = {marker} if marker else set()
    while True:
        time.sleep(delay)
        # This private cursor is pinned to google-play-scraper==1.2.4.
        token = _ContinuationToken(marker, language, country, Sort.NEWEST, 199, None) if marker else None
        kwargs = {'country': country, 'lang': language, 'sort': Sort.NEWEST,
                  'count': 199, 'continuation_token': token}
        batch, token = retry(lambda: call('reviews', app_id, kwargs, timeout), attempts)
        if not isinstance(batch, list) or any(not isinstance(row, dict) for row in batch):
            raise ValueError('Unexpected Google review page')
        next_marker = getattr(token, 'token', None)
        if next_marker and next_marker in seen:
            raise RuntimeError('Google repeated a continuation token; rerun with --restart-cursors')
        rows = [envelope('google_play', app_id, country, language, metadata, row) for row in batch]
        exhausted = not batch or not next_marker
        yield rows, {'token': next_marker}, exhausted
        if exhausted:
            return
        seen.add(next_marker)
        marker = next_marker


def apple_pages(job, cursor, *, delay, attempts, timeout):
    app_id, country = job['app_id'], job['country']
    with requests.Session() as session:
        session.headers.update({'User-Agent': 'MultiDomainSentimentResearch/1.0',
                                'Accept': 'application/json'})

        def get(url, **kwargs):
            def request():
                response = session.get(url, timeout=timeout, **kwargs)
                response.raise_for_status()
                return response
            return retry(request, attempts).json()

        lookup = get('https://itunes.apple.com/lookup',
                     params={'id': app_id, 'country': country, 'entity': 'software'})
        if not isinstance(lookup, dict) or not isinstance(lookup.get('results'), list):
            raise ValueError('Unexpected Apple lookup response')
        if not lookup['results']:
            raise ValueError(f'App {app_id} not found in {country}')
        metadata = lookup['results'][0]
        for page in range(cursor.get('page', 1), 11):
            time.sleep(delay)
            payload = get(f'https://itunes.apple.com/{country}/rss/customerreviews/'
                          f'page={page}/id={app_id}/sortby=mostrecent/json')
            if not isinstance(payload, dict) or not isinstance(payload.get('feed'), dict):
                raise ValueError(f'Unexpected Apple feed on page {page}')
            entries = payload['feed'].get('entry', [])
            if isinstance(entries, dict):
                entries = [entries]
            if not isinstance(entries, list) or any(not isinstance(row, dict) for row in entries):
                raise ValueError(f'Unexpected Apple entries on page {page}')
            rows = [envelope('app_store', app_id, country, None, metadata, row)
                    for row in entries if 'im:rating' in row]
            # Empty pages do not prove exhaustion: continue up to the configured source cap.
            yield rows, {'page': page + 1}, page == 10


def pages(job, cursor, **options):
    adapter = google_pages if job['source'] == 'google_play' else apple_pages
    return adapter(job, cursor, **options)
