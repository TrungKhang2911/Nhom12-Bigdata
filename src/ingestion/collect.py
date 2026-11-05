"""Standalone local collection: python -m src.ingestion.collect --config FILE."""
import argparse
import json
import logging
import math
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from config.logging_config import configure_logging
from src.ingestion.common import dumps, validate_options
from src.ingestion.dataset import Dataset, job_key
from src.ingestion.source_pages import pages

logger = logging.getLogger(__name__)

# Supported job sources and their app_id format. Tiki uses the numeric product
# ID after "-p" in a product URL, e.g. .../sach-nha-gia-kim-p52789367.html.
# Shopee uses "<shopid>.<itemid>" from shopee.vn/product/<shopid>/<itemid>
# or .../<name>-i.<shopid>.<itemid>.
ID_PATTERNS = {
    'google_play': r'[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+',
    'app_store': r'[0-9]+',
    'tiki': r'[0-9]+',
    'shopee': r'[0-9]+\.[0-9]+',
}
VIETNAM_ONLY = ('tiki', 'shopee')


def now():
    return datetime.now(timezone.utc).isoformat()


def load_config(path):
    config = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if not isinstance(config, dict) or set(config) - {'jobs', 'delay', 'attempts', 'timeout', 'max_batches'}:
        raise ValueError('Config must contain jobs and optional delay/attempts/timeout/max_batches')
    jobs = config.get('jobs')
    if not isinstance(jobs, list) or not jobs:
        raise ValueError('jobs must be a nonempty list')
    options = {'delay': config.get('delay', 1.0), 'attempts': config.get('attempts', 3),
               'timeout': config.get('timeout', 45.0)}
    for name in ('delay', 'timeout'):
        value = options[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f'{name} must be finite')
    if options['delay'] < 0.5 or options['timeout'] <= 0:
        raise ValueError('delay must be >= 0.5 seconds and timeout > 0')
    max_batches = config.get('max_batches', 1000)
    for name, value in (('attempts', options['attempts']), ('max_batches', max_batches)):
        if type(value) is not int or value < 1:
            raise ValueError(f'{name} must be a positive integer')
    normalized, keys = [], set()
    for raw in jobs:
        if not isinstance(raw, dict) or set(raw) - {'source', 'app_id', 'country', 'language', 'limit'}:
            raise ValueError('Unknown job keys; use source/app_id/country/language/limit')
        source, app_id = raw.get('source'), raw.get('app_id')
        country, target = raw.get('country', 'vn'), raw.get('limit')
        if not isinstance(source, str) or source not in ID_PATTERNS or not isinstance(app_id, str):
            raise ValueError(f'Each job requires a string app_id and a source in {sorted(ID_PATTERNS)}')
        if not re.fullmatch(ID_PATTERNS[source], app_id):
            raise ValueError(f'Invalid app_id: {app_id}')
        if type(target) is not int or not isinstance(country, str):
            raise ValueError('Each job requires an integer limit and string country')
        validate_options(country, target, options['delay'], options['attempts'])
        language = raw.get('language', 'vi') if source == 'google_play' else None
        if source == 'google_play' and (not isinstance(language, str) or not re.fullmatch(r'[a-zA-Z_-]{2,15}', language)):
            raise ValueError('Invalid Google language code')
        if source != 'google_play' and raw.get('language') is not None:
            raise ValueError(f'{source} does not support language filtering; omit language')
        if source in VIETNAM_ONLY and country.lower() != 'vn':
            raise ValueError(f'{source} adapter only supports Vietnam; use country "vn" or omit it')
        job = {'source': source, 'app_id': app_id, 'country': country.lower(),
               'language': language, 'limit': target}
        key = job_key(job)
        if key in keys:
            raise ValueError(f'Duplicate job: {key}')
        keys.add(key)
        normalized.append(job)
    return normalized, options, max_batches


def write_report(folder, report):
    target = Path(folder) / 'report.json'
    temp = target.with_suffix('.json.tmp')
    temp.write_text(dumps(report) + '\n', encoding='utf-8')
    temp.replace(target)


def collect_job(dataset, job, options, max_batches, restart=False):
    key, target = job_key(job), job['limit']
    initial = dataset.count(key)
    result = dict(job, existing=initial, started_at=now(), pages_fetched=0,
                  status='running', error=None)
    started = time.monotonic()
    try:
        if restart:
            dataset.reset_cursor(key)
        state = dataset.state(key)
        if initial < target and state['pending']:
            dataset.save_page(key, state['pending'], state['cursor'], state['exhausted'], target)
            state = dataset.state(key)
        if dataset.count(key) < target and not state['exhausted']:
            stream = pages(job, state['cursor'], **options)
            try:
                for rows, cursor, exhausted in stream:
                    count = dataset.save_page(key, rows, cursor, exhausted, target)
                    result['pages_fetched'] += 1
                    logger.info('%s %s: %d/%d distinct reviews', job['source'], job['app_id'], count, target)
                    if count >= target or exhausted or result['pages_fetched'] >= max_batches:
                        break
            finally:
                stream.close()
        count = dataset.count(key)
        result['status'] = 'complete' if count >= target else (
            'source_exhausted' if dataset.state(key)['exhausted'] else 'page_budget_reached')
    except KeyboardInterrupt:
        result['status'] = 'interrupted'
    except Exception as exc:
        logger.exception('Job failed; continuing other applications: %s', key)
        result['status'] = 'error'
        result['error'] = f'{type(exc).__name__}: {exc}'
    result.update(collected=dataset.count(key), finished_at=now(),
                  elapsed_seconds=round(time.monotonic() - started, 3))
    result['added'] = result['collected'] - initial
    result['shortfall'] = max(0, target - result['collected'])
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Resumable review collection (Google Play, App Store, Tiki, Shopee) to JSON, JSONL and CSV')
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, default=Path('data/raw/mobile_reviews'))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--restart-cursors', action='store_true', help='Fetch from newest page again; retain saved review IDs')
    mode.add_argument('--export-only', action='store_true', help='Regenerate files from journal without network requests')
    args = parser.parse_args(argv)
    configure_logging()
    try:
        jobs, options, max_batches = load_config(args.config)
    except (OSError, ValueError, TypeError) as exc:
        parser.error(str(exc))
    dataset = Dataset(args.output_dir)
    report = {'started_at': now(), 'config': str(args.config), 'options': options,
              'max_batches': max_batches, 'jobs': [], 'finished_at': None}
    exit_code = 0
    try:
        if not args.export_only:
            write_report(args.output_dir, report)
            for job in jobs:
                result = collect_job(dataset, job, options, max_batches, args.restart_cursors)
                report['jobs'].append(result)
                write_report(args.output_dir, report)
                if result['status'] == 'interrupted':
                    exit_code = 130
                    break
                if result['status'] == 'error':
                    exit_code = 1
                elif result['shortfall'] and exit_code == 0:
                    exit_code = 3
        outputs = dataset.export([job_key(job) for job in jobs])
        if args.export_only:
            logger.info('Exported saved reviews: %s', outputs)
        else:
            report.update(outputs=outputs, finished_at=now(), exit_code=exit_code)
            report['total_collected'] = sum(row['collected'] for row in report['jobs'])
            report['total_requested'] = sum(job['limit'] for job in jobs)
            report['all_targets_met'] = (len(report['jobs']) == len(jobs) and
                                         all(row['status'] == 'complete' for row in report['jobs']))
            write_report(args.output_dir, report)
            logger.info('Finished: %d/%d reviews; report: %s', report['total_collected'],
                        report['total_requested'], args.output_dir / 'report.json')
        return exit_code
    except KeyboardInterrupt:
        logger.warning('Interrupted during export; journal is safe. Rerun with --export-only.')
        return 130
    except Exception:
        logger.exception('Collection/export failed; journal retained. Close CSV viewers and retry --export-only.')
        return 1
    finally:
        dataset.close()


if __name__ == '__main__':
    raise SystemExit(main())
