"""Run with python -m src.ingestion from the repository root."""
import argparse
import logging
import math
from contextlib import ExitStack
from pathlib import Path

from config.logging_config import configure_logging
from config.settings import load_settings
from src.ingestion.common import dumps

logger = logging.getLogger(__name__)


def positive_int(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError('must be positive')
    return number


def nonnegative_float(value):
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise argparse.ArgumentTypeError('must be a finite nonnegative number')
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(description='Collect raw mobile app reviews')
    parser.add_argument('source', choices=['google_play', 'app_store'])
    parser.add_argument('--app-id', required=True, nargs='+', help='One or more package names / numeric IDs')
    parser.add_argument('--country', default='vn')
    parser.add_argument('--language', default='vi', help='Google Play language (not an Apple filter)')
    parser.add_argument('--limit', type=positive_int, default=500, help='Maximum reviews per app')
    parser.add_argument('--delay', type=nonnegative_float, default=1.0, help='Seconds between requests')
    parser.add_argument('--attempts', type=positive_int, default=3)
    parser.add_argument('--max-pages', type=int, choices=range(1, 11), default=10, help='Apple RSS page cap')
    parser.add_argument('--output', type=Path, help='JSONL file (append, never overwrite)')
    parser.add_argument('--sink', choices=['jsonl', 'kafka', 'both'], default='jsonl')
    args = parser.parse_args(argv)
    settings = load_settings()
    configure_logging(settings.log_level)
    if args.output and args.sink == 'kafka':
        parser.error('--output requires --sink jsonl or both')
    output = args.output or settings.raw_data_dir / f'{args.source}.jsonl'
    total = 0
    try:
        with ExitStack() as stack:
            handle = None
            producer = None
            if args.sink in ('kafka', 'both'):
                from src.streaming.kafka_producer import RawReviewProducer
                producer = RawReviewProducer(settings.kafka_bootstrap_servers, settings.kafka_topic)
                stack.callback(producer.close)
            if args.sink in ('jsonl', 'both'):
                output.parent.mkdir(parents=True, exist_ok=True)
                handle = stack.enter_context(output.open('a', encoding='utf-8'))
            if args.source == 'google_play':
                from src.ingestion.gplay_crawler import crawl
                options = {'language': args.language}
            else:
                from src.ingestion.appstore_crawler import crawl
                options = {'max_pages': args.max_pages}
            for app_id in args.app_id:
                count = 0
                for event in crawl(app_id, country=args.country, limit=args.limit,
                                   delay=args.delay, attempts=args.attempts, **options):
                    if handle:
                        handle.write(dumps(event) + '\n')
                        handle.flush()
                    if producer:
                        producer.send(event)
                    total += 1
                    count += 1
                if count == 0:
                    logger.warning('%s returned no reviews; this does not prove there are none', app_id)
            logger.info('Finished: %d reviews delivered to %s', total, args.sink)
        return 0
    except KeyboardInterrupt:
        logger.warning('Interrupted; partial output is retained')
        return 130
    except Exception:
        logger.exception('Crawl failed after %d delivered reviews; partial output is retained', total)
        return 1
