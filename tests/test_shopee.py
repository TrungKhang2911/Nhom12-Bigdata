import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

from src.ingestion.collect import load_config, main
from src.ingestion.dataset import csv_row, export_sources, job_key, review_key
from src.ingestion.shopee_crawler import PAGE_SIZE, ShopeeBlockedError, pages


JOB = {'source': 'shopee', 'app_id': '3932239.1671068614', 'country': 'vn', 'language': None, 'limit': 2}
OPTIONS = {'delay': 0.5, 'attempts': 3, 'timeout': 5}
# Body observed from https://shopee.vn/api/v2/item/get_ratings on 2026-11-04.
BLOCKED = {'is_customized': False, 'is_login': False, 'action_type': 2, 'error': 90309999,
           'tracking_id': 'test', 'redirect_to_error_page': True}


def rating(cmtid, comment='Tai nghe tốt 😊, "bass" ổn\ngiao nhanh', star=5):
    """Pre-block public get_ratings format; not verifiable live."""
    return {'cmtid': cmtid, 'comment': comment, 'rating_star': star, 'ctime': 1792570197,
            'author_username': 'khach', 'like_count': 1, 'itemid': 1671068614, 'shopid': 3932239}


def response(body, status=200):
    reply = MagicMock(status_code=status)
    reply.json.return_value = body
    return reply


def ratings_page(rows):
    return {'error': 0, 'data': {'ratings': rows}}


@patch('src.ingestion.shopee_crawler.time.sleep')
@patch('src.ingestion.shopee_crawler.requests.Session')
class ShopeePageTests(unittest.TestCase):
    def client(self, session, *replies):
        client = session.return_value.__enter__.return_value
        client.get.side_effect = list(replies)
        return client

    def test_anti_bot_block_is_reported_without_retry(self, session, sleep):
        client = self.client(session, response(BLOCKED, 403))
        with self.assertRaisesRegex(ShopeeBlockedError, 'HTTP 403, error 90309999, is_login=False'):
            list(pages(JOB, {}, **OPTIONS))
        self.assertEqual(client.get.call_count, 1)
        self.assertEqual(client.get.call_args.kwargs['params']['shopid'], '3932239')
        self.assertEqual(client.get.call_args.kwargs['params']['itemid'], '1671068614')

    def test_block_inside_http_200_is_still_reported(self, session, sleep):
        self.client(session, response(BLOCKED, 200))
        with self.assertRaises(ShopeeBlockedError):
            list(pages(JOB, {}, **OPTIONS))

    def test_ratings_paginate_by_offset_and_keep_raw(self, session, sleep):
        first_page = [rating(i) for i in range(PAGE_SIZE)]
        client = self.client(session, response(ratings_page(first_page)),
                             response(ratings_page([rating(999)])))
        result = list(pages(JOB, {}, **OPTIONS))
        self.assertEqual([(cursor, exhausted) for _, cursor, exhausted in result],
                         [({'offset': PAGE_SIZE}, False), ({'offset': PAGE_SIZE + 1}, True)])
        row = result[0][0][0]
        self.assertIs(row['review'], first_page[0])
        self.assertEqual((row['source_domain'], row['item_id'], row['country'], row['language'], row['app']),
                         ('shopee', '3932239.1671068614', 'vn', None, None))
        self.assertEqual(client.get.call_args.kwargs['params']['offset'], PAGE_SIZE)

    def test_resume_starts_at_saved_offset(self, session, sleep):
        client = self.client(session, response(ratings_page([])))
        self.assertEqual(list(pages(JOB, {'offset': 150}, **OPTIONS)), [([], {'offset': 150}, True)])
        self.assertEqual(client.get.call_args.kwargs['params']['offset'], 150)

    def test_other_api_errors_and_formats_fail_loudly(self, session, sleep):
        for body in ({'error': 4, 'data': None}, {'error': 0, 'data': {'ratings': 'bad'}}, ['bad']):
            self.client(session, response(body))
            with self.subTest(body=body), self.assertRaises(ValueError):
                list(pages(JOB, {}, **OPTIONS))
        reply = response(None)
        reply.json.side_effect = ValueError('not json')
        self.client(session, reply)
        with self.assertRaisesRegex(ValueError, 'non-JSON'):
            list(pages(JOB, {}, **OPTIONS))

    def test_rate_limit_is_retried(self, session, sleep):
        limited = response({}, 429)
        limited.raise_for_status.side_effect = requests.HTTPError(response=MagicMock(status_code=429))
        self.client(session, limited, response(ratings_page([rating(1)])))
        with self.assertLogs('src.ingestion.common', level='WARNING'):
            result = list(pages(JOB, {}, **OPTIONS))
        self.assertEqual(len(result[0][0]), 1)


class ShopeeDatasetTests(unittest.TestCase):
    def test_review_key_csv_columns_and_export_group(self):
        raw = rating(123456, comment='+84 vẫn giữ nguyên trong review_json', star=4)
        event = {'source_domain': 'shopee', 'item_id': JOB['app_id'], 'country': 'vn', 'language': None,
                 'collected_at': '2026-11-04T10:00:00+00:00', 'app': None, 'review': raw}
        row = csv_row(event)
        self.assertEqual(review_key(event), '123456')
        self.assertEqual((row['review_id'], row['rating'], row['review_time']),
                         ('123456', 4, '2026-10-21T08:09:57+00:00'))
        self.assertEqual(row['review_text'], "'+84 vẫn giữ nguyên trong review_json")
        self.assertEqual((json.loads(row['review_json']), row['app_json']), (raw, 'null'))
        self.assertEqual(export_sources([job_key(JOB)]), ['shopee'])


class ShopeeConfigTests(unittest.TestCase):
    def load(self, *jobs):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'jobs.json'
            path.write_text(json.dumps({'jobs': list(jobs)}), encoding='utf-8')
            return load_config(path)

    def test_valid_job(self):
        jobs, _, _ = self.load({'source': 'shopee', 'app_id': '3932239.1671068614', 'limit': 2})
        self.assertEqual(jobs, [JOB])

    def test_invalid_jobs_rejected_before_network(self):
        base = {'source': 'shopee', 'app_id': '3932239.1671068614', 'limit': 2}
        for job in (dict(base, app_id='1671068614'), dict(base, app_id='3932239/1671068614'),
                    dict(base, language='vi'), dict(base, country='th')):
            with self.subTest(job=job), self.assertRaises(ValueError):
                self.load(job)


class ShopeeCollectTests(unittest.TestCase):
    @patch('src.ingestion.shopee_crawler.time.sleep')
    @patch('src.ingestion.shopee_crawler.requests.Session')
    def test_blocked_check_is_recorded_in_report(self, session, sleep):
        session.return_value.__enter__.return_value.get.return_value = response(BLOCKED, 403)
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / 'shopee.json'
            config.write_text(json.dumps({'jobs': [{'source': 'shopee', 'app_id': JOB['app_id'], 'limit': 2}]}))
            output = Path(folder) / 'data'
            with self.assertLogs(level='ERROR'):
                self.assertEqual(main(['--config', str(config), '--output-dir', str(output)]), 1)
            report = json.loads((output / 'report.json').read_text(encoding='utf-8'))
            job = report['jobs'][0]
            self.assertEqual((job['status'], job['collected'], job['shortfall']), ('error', 0, 2))
            self.assertIn('ShopeeBlockedError', job['error'])
            self.assertFalse(report['all_targets_met'])
            self.assertEqual(json.loads((output / 'shopee.json').read_text(encoding='utf-8')), [])
            with (output / 'shopee.csv').open(encoding='utf-8-sig', newline='') as handle:
                self.assertEqual(list(csv.DictReader(handle)), [])


if __name__ == '__main__':
    unittest.main()
