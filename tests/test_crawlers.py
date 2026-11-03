import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import requests
from google_play_scraper.exceptions import ExtraHTTPError

from src.ingestion import appstore_crawler as apple
from src.ingestion import gplay_crawler as google
from src.ingestion.cli import main
from src.ingestion.common import dumps, retry
from src.streaming.kafka_producer import RawReviewProducer


class GoogleTests(unittest.TestCase):
    @patch.object(google, 'app', return_value={'title': 'Test'})
    @patch.object(google, 'reviews')
    def test_pagination_and_raw_preservation(self, reviews, app):
        raw = {'reviewId': '1', 'content': 'Tốt 😊', 'at': datetime(2026, 1, 1)}
        token = SimpleNamespace(token='next')
        reviews.side_effect = [([raw], token), ([{'reviewId': '2'}, {'reviewId': '3'}], None)]
        rows = list(google.crawl('com.test.app', limit=2, delay=0))
        self.assertEqual(len(rows), 2)
        self.assertIs(rows[0]['review'], raw)
        self.assertEqual(reviews.call_args.kwargs['continuation_token'], token)
        self.assertEqual(reviews.call_args.kwargs['count'], 1)
        self.assertEqual(json.loads(dumps(rows[0]))['review']['content'], 'Tốt 😊')
        self.assertEqual(json.loads(dumps(rows[0]))['review']['at'], '2026-01-01T00:00:00')

    @patch.object(google, 'app', return_value={})
    @patch.object(google, 'reviews', return_value=([], None))
    def test_empty(self, reviews, app):
        self.assertEqual(list(google.crawl('com.test.app', delay=0)), [])

    @patch.object(google, 'app', return_value={})
    @patch.object(google, 'reviews', return_value=([{'reviewId': '1'}], SimpleNamespace(token='same')))
    def test_repeated_token(self, reviews, app):
        with self.assertRaisesRegex(RuntimeError, 'repeated'):
            list(google.crawl('com.test.app', delay=0))
        self.assertEqual(reviews.call_count, 2)

    def test_invalid_options(self):
        for kwargs in ({'limit': 0}, {'country': '../'}, {'batch_size': 201}, {'delay': -1}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                list(google.crawl('com.test.app', **kwargs))


class AppleTests(unittest.TestCase):
    def run_feed(self, pages, **kwargs):
        with patch.object(apple.requests, 'Session') as session:
            client = session.return_value.__enter__.return_value
            responses = [{'results': [{'trackName': 'App'}]}] + pages
            client.get.side_effect = [MagicMock(json=MagicMock(return_value=p)) for p in responses]
            rows = list(apple.crawl('123', delay=0, **kwargs))
            return rows, client

    def test_singleton_empty_page_and_raw_content(self):
        raw = {'im:rating': {'label': '5'}, 'content': {'label': 'Hay 😊'}}
        rows, client = self.run_feed([
            {'feed': {}}, {'feed': {'entry': raw}},
            {'feed': {'entry': [{'im:name': {}}, raw]}},
        ], max_pages=3)
        self.assertEqual(len(rows), 2)
        self.assertIs(rows[0]['review'], raw)
        self.assertIsNone(rows[0]['language'])
        self.assertEqual(client.get.call_count, 4)

    def test_limit(self):
        raw = {'im:rating': {'label': '4'}}
        rows, client = self.run_feed([{'feed': {'entry': [raw, raw]}}], limit=1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(client.get.call_count, 2)
        self.assertEqual(client.get.call_args.kwargs['timeout'], 30.0)

    def test_malformed_feed(self):
        for feed in ({'error': 'oops'}, {'feed': {'entry': 'bad'}}):
            with self.subTest(feed=feed), self.assertRaises(ValueError):
                self.run_feed([feed], max_pages=1)

    def test_missing_app(self):
        with patch.object(apple.requests, 'Session') as session:
            session.return_value.__enter__.return_value.get.return_value.json.return_value = {'results': []}
            with self.assertRaisesRegex(ValueError, 'not found'):
                list(apple.crawl('123', delay=0))


class TransportTests(unittest.TestCase):
    @patch('src.ingestion.common.time.sleep')
    def test_google_wrapped_http_error(self, sleep):
        for status, calls in ((403, 1), (429, 3), (503, 3)):
            operation = MagicMock(side_effect=ExtraHTTPError(
                f'App not found. Status code {status} returned.'))
            with self.assertRaises(ExtraHTTPError):
                retry(operation)
            self.assertEqual(operation.call_count, calls)

    @patch('src.ingestion.common.time.sleep')
    def test_retry_and_exhaustion(self, sleep):
        operation = MagicMock(side_effect=[requests.Timeout(), 'ok'])
        self.assertEqual(retry(operation), 'ok')
        sleep.assert_called_once_with(1.0)
        operation = MagicMock(side_effect=requests.Timeout())
        with self.assertRaises(requests.Timeout):
            retry(operation, attempts=2)
        self.assertEqual(operation.call_count, 2)

    @patch('src.ingestion.common.time.sleep')
    def test_http_status_policy(self, sleep):
        for status, calls in ((404, 1), (429, 3), (503, 3)):
            response = requests.Response()
            response.status_code = status
            operation = MagicMock(side_effect=requests.HTTPError(response=response))
            with self.assertRaises(requests.HTTPError):
                retry(operation)
            self.assertEqual(operation.call_count, calls)

    @patch('src.streaming.kafka_producer.KafkaProducer')
    def test_kafka_ack_and_failure(self, producer):
        sink = RawReviewProducer('localhost:9092', 'raw_reviews')
        event = {'source_domain': 'google_play', 'item_id': 'com.test.app'}
        sink.send(event)
        producer.return_value.send.return_value.get.assert_called_once_with(timeout=60)
        producer.return_value.send.return_value.get.side_effect = RuntimeError('broker failed')
        with self.assertRaises(RuntimeError):
            sink.send(event)
        sink.close()
        producer.return_value.close.assert_called_once()


class CLITests(unittest.TestCase):
    @patch.object(google, 'crawl')
    def test_jsonl_append_multiple_apps(self, crawl):
        crawl.side_effect = lambda app_id, **kwargs: iter([{'item_id': app_id, 'review': 'Tốt'}])
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'reviews.jsonl'
            output.write_text('{"previous": true}\n', encoding='utf-8')
            code = main(['google_play', '--app-id', 'com.a', 'com.b', '--output', str(output)])
            self.assertEqual(code, 0)
            rows = [json.loads(line) for line in output.read_text(encoding='utf-8').splitlines()]
            self.assertEqual(len(rows), 3)
            self.assertTrue(rows[0]['previous'])
            self.assertEqual(rows[2]['item_id'], 'com.b')

    @patch.object(google, 'crawl')
    def test_partial_failure_is_nonzero(self, crawl):
        def failing(*args, **kwargs):
            yield {'review': 'retained'}
            raise requests.Timeout('network failed')
        crawl.side_effect = failing
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'partial.jsonl'
            with self.assertLogs(level='ERROR'):
                code = main(['google_play', '--app-id', 'com.a', '--output', str(output)])
            self.assertEqual(code, 1)
            self.assertEqual(len(output.read_text().splitlines()), 1)


if __name__ == '__main__':
    unittest.main()
