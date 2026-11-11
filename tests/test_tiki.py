import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

from src.ingestion.collect import load_config, main
from src.ingestion.dataset import Dataset, csv_row, export_sources, job_key, review_key
from src.ingestion.tiki_crawler import pages


JOB = {'source': 'tiki', 'app_id': '52789367', 'country': 'vn', 'language': None, 'limit': 2}
OPTIONS = {'delay': 0.5, 'attempts': 1, 'timeout': 5}
PRODUCT = {'id': 52789367, 'name': 'Sách Nhà Giả Kim', 'categories': {'id': 871, 'name': 'Sách'}}


def review(review_id, content='Sách hay 😊, "giao nhanh"\nđóng gói kỹ', rating=5):
    """Shape observed from https://tiki.vn/api/v2/reviews on 2026-11-04."""
    return {'id': review_id, 'title': 'Cực kì hài lòng', 'content': content, 'rating': rating,
            'created_at': 1792570197, 'thank_count': 2, 'images': [],
            'created_by': {'id': 1, 'name': 'Khách', 'purchased': True},
            'timeline': {'review_created_date': '2026-10-21 15:09:57'}}


def page(rows, last_page):
    return {'data': rows, 'paging': {'total': 99, 'per_page': 20, 'current_page': 1,
                                     'last_page': last_page}}


def event(raw):
    return {'source_domain': 'tiki', 'item_id': '52789367', 'country': 'vn', 'language': None,
            'collected_at': '2026-11-04T10:00:00+00:00', 'app': PRODUCT, 'review': raw}


@patch('src.ingestion.tiki_crawler.time.sleep')
@patch('src.ingestion.tiki_crawler.requests.Session')
class TikiPageTests(unittest.TestCase):
    def client(self, session, *payloads):
        client = session.return_value.__enter__.return_value
        client.get.side_effect = [MagicMock(json=MagicMock(return_value=p)) for p in payloads]
        return client

    def test_pagination_request_and_raw_envelope(self, session, sleep):
        first = review(2)
        client = self.client(session, PRODUCT, page([first], 2), page([review(1)], 2))
        result = list(pages(JOB, {}, **OPTIONS))
        self.assertEqual([(cursor, exhausted) for _, cursor, exhausted in result],
                         [({'page': 2}, False), ({'page': 3}, True)])
        row = result[0][0][0]
        self.assertIs(row['review'], first)
        self.assertIs(row['app'], PRODUCT)
        self.assertEqual((row['source_domain'], row['item_id'], row['country'], row['language']),
                         ('tiki', '52789367', 'vn', None))
        product_call, review_call = client.get.call_args_list[:2]
        self.assertEqual(product_call.args[0], 'https://tiki.vn/api/v2/products/52789367')
        self.assertEqual(review_call.kwargs['params'],
                         {'product_id': '52789367', 'page': 1, 'limit': 20, 'sort': 'id|desc'})
        self.assertEqual(review_call.kwargs['timeout'], 5)
        self.assertEqual(sleep.call_count, 2)

    def test_resume_starts_at_saved_page(self, session, sleep):
        client = self.client(session, PRODUCT, page([review(1)], 7))
        result = list(pages(JOB, {'page': 7}, **OPTIONS))
        self.assertEqual(client.get.call_args.kwargs['params']['page'], 7)
        self.assertEqual(result[0][1:], ({'page': 8}, True))

    def test_product_without_reviews_is_exhausted(self, session, sleep):
        self.client(session, PRODUCT, page([], 0))
        self.assertEqual(list(pages(JOB, {}, **OPTIONS)), [([], {'page': 2}, True)])

    def test_malformed_responses_fail_loudly(self, session, sleep):
        bad_pages = ({'error': {'message': 'Query limitation is: 20'}},
                     {'data': 'bad', 'paging': {'last_page': 1}},
                     {'data': [1], 'paging': {'last_page': 1}},
                     {'data': [], 'paging': {}})
        for payload in bad_pages:
            self.client(session, PRODUCT, payload)
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                list(pages(JOB, {}, **OPTIONS))
        self.client(session, ['not', 'a', 'product'])
        with self.assertRaisesRegex(ValueError, 'product'):
            list(pages(JOB, {}, **OPTIONS))

    def test_missing_product_is_not_retried(self, session, sleep):
        response = requests.Response()
        response.status_code = 404
        client = session.return_value.__enter__.return_value
        client.get.return_value.raise_for_status.side_effect = requests.HTTPError(response=response)
        with self.assertRaises(requests.HTTPError):
            list(pages(JOB, {}, **dict(OPTIONS, attempts=3)))
        self.assertEqual(client.get.call_count, 1)

    def test_transient_error_is_retried(self, session, sleep):
        client = session.return_value.__enter__.return_value
        client.get.side_effect = [MagicMock(json=MagicMock(return_value=PRODUCT)),
                                  requests.ConnectionError('reset'),
                                  MagicMock(json=MagicMock(return_value=page([review(1)], 1)))]
        with self.assertLogs('src.ingestion.common', level='WARNING'):
            result = list(pages(JOB, {}, **dict(OPTIONS, attempts=2)))
        self.assertEqual(len(result[0][0]), 1)


class TikiDatasetTests(unittest.TestCase):
    def test_review_key_and_csv_display_columns(self):
        raw = review(20266557, content='=SUM(A1) vẫn giữ trong review_json', rating=4)
        row = csv_row(event(raw))
        self.assertEqual(review_key(event(raw)), '20266557')
        self.assertEqual((row['review_id'], row['rating'], row['source_domain']), ('20266557', 4, 'tiki'))
        self.assertEqual(row['review_time'], '2026-10-21T08:09:57+00:00')
        self.assertEqual(row['review_text'], "'=SUM(A1) vẫn giữ trong review_json")
        self.assertEqual(json.loads(row['review_json']), raw)
        self.assertEqual(json.loads(row['app_json']), PRODUCT)

    def test_missing_id_uses_stable_hash(self):
        raw = review(None)
        self.assertTrue(review_key(event(raw)).startswith('sha256:'))
        self.assertEqual(review_key(event(raw)), review_key(event(dict(raw))))

    def test_export_groups(self):
        google = job_key({'source': 'google_play', 'app_id': 'a.b', 'country': 'vn', 'language': 'vi'})
        self.assertEqual(export_sources([job_key(JOB)]), ['tiki'])
        self.assertEqual(export_sources([google]), ['google_play', 'app_store'])
        self.assertEqual(export_sources([google, job_key(JOB)]), ['google_play', 'app_store', 'tiki'])

    def test_export_round_trip_writes_only_tiki_files(self):
        with tempfile.TemporaryDirectory() as folder:
            dataset = Dataset(folder)
            try:
                rows = [event(review(1)), event(review(2, content=''))]
                key = job_key(JOB)
                dataset.save_page(key, rows, {'page': 2}, True, 2)
                outputs = dataset.export([key])
            finally:
                dataset.close()
            path = Path(folder)
            self.assertEqual(list(outputs), ['tiki'])
            self.assertEqual(json.loads((path / 'tiki.json').read_text(encoding='utf-8')), rows)
            lines = (path / 'tiki.jsonl').read_text(encoding='utf-8').splitlines()
            self.assertEqual([json.loads(line) for line in lines], rows)
            with (path / 'tiki.csv').open(encoding='utf-8-sig', newline='') as handle:
                table = list(csv.DictReader(handle))
            self.assertEqual([row['review_text'] for row in table], [rows[0]['review']['content'], ''])
            self.assertFalse((path / 'google_play.json').exists())


class TikiConfigTests(unittest.TestCase):
    def load(self, *jobs):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'jobs.json'
            path.write_text(json.dumps({'jobs': list(jobs)}), encoding='utf-8')
            return load_config(path)

    def test_valid_job_defaults_to_vietnam_without_language(self):
        jobs, _, _ = self.load({'source': 'tiki', 'app_id': '52789367', 'limit': 10})
        self.assertEqual(jobs, [dict(JOB, limit=10)])

    def test_invalid_jobs_rejected_before_network(self):
        base = {'source': 'tiki', 'app_id': '52789367', 'limit': 10}
        for job in (dict(base, language='vi'), dict(base, app_id='p52789367'),
                    dict(base, country='us'), dict(base, source='lazada')):
            with self.subTest(job=job), self.assertRaises(ValueError):
                self.load(job)


class TikiCollectTests(unittest.TestCase):
    @patch('src.ingestion.tiki_crawler.time.sleep')
    @patch('src.ingestion.tiki_crawler.requests.Session')
    def test_collect_command_end_to_end(self, session, sleep):
        client = session.return_value.__enter__.return_value
        client.get.side_effect = [MagicMock(json=MagicMock(return_value=p)) for p in
                                  (PRODUCT, page([review(3), review(2), review(1)], 5))]
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / 'tiki.json'
            config.write_text(json.dumps({'jobs': [{'source': 'tiki', 'app_id': '52789367', 'limit': 2}]}))
            output = Path(folder) / 'data'
            self.assertEqual(main(['--config', str(config), '--output-dir', str(output)]), 0)
            report = json.loads((output / 'report.json').read_text(encoding='utf-8'))
            self.assertTrue(report['all_targets_met'])
            self.assertEqual((report['jobs'][0]['collected'], report['jobs'][0]['status']), (2, 'complete'))
            with (output / 'tiki.csv').open(encoding='utf-8-sig', newline='') as handle:
                self.assertEqual([row['review_id'] for row in csv.DictReader(handle)], ['3', '2'])
            dataset = Dataset(output)
            try:
                self.assertEqual(len(dataset.state(job_key(JOB))['pending']), 1)
            finally:
                dataset.close()


if __name__ == '__main__':
    unittest.main()
