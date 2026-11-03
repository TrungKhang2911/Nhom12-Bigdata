"""Raw transport helpers; no cleaning or sentiment processing."""
import json
import logging
import math
import re
import time
from datetime import date, datetime, timezone
from urllib.error import HTTPError, URLError

import requests
from google_play_scraper.exceptions import ExtraHTTPError

logger = logging.getLogger(__name__)


def json_default(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f'Cannot encode {type(value).__name__}')


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=json_default, allow_nan=False)


def envelope(source, app_id, country, language, app, review):
    return {
        'source_domain': source,
        'item_id': str(app_id),
        'country': country,
        'language': language,
        'collected_at': datetime.now(timezone.utc).isoformat(),
        'app': app,
        'review': review,
    }


def retry(operation, attempts=3, delay=1.0):
    """Retry transport failures only, never parser/programming errors."""
    if attempts < 1 or not math.isfinite(delay) or delay < 0:
        raise ValueError('attempts must be >= 1 and delay >= 0')
    for attempt in range(attempts):
        try:
            return operation()
        except (requests.RequestException, URLError, TimeoutError, ConnectionError, ExtraHTTPError) as exc:
            status = getattr(getattr(exc, 'response', None), 'status_code', None)
            if isinstance(exc, HTTPError):
                status = exc.code
            if isinstance(exc, ExtraHTTPError):
                # Version 1.2.4 retains the HTTP status only in its message.
                match = re.search(r'Status code (\d{3}) returned', str(exc))
                if not match:
                    raise
                status = int(match.group(1))
            if status is not None and status not in (408, 429) and status < 500:
                raise
            if attempt + 1 == attempts:
                raise
            pause = delay * (2 ** attempt)
            logger.warning('Request failed (%s); retry %d/%d in %.1fs',
                           type(exc).__name__, attempt + 2, attempts, pause)
            time.sleep(pause)


def validate_options(country, limit, delay, attempts):
    if len(country) != 2 or not country.isascii() or not country.isalpha():
        raise ValueError('country must be a two-letter storefront code, e.g. vn')
    if limit < 1 or not math.isfinite(delay) or delay < 0 or attempts < 1:
        raise ValueError('limit/attempts must be positive; delay must be nonnegative')
