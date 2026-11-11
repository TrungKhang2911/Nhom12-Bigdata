import csv
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.ingestion.collect import collect_job, load_config, main
from src.ingestion.dataset import Dataset, job_key
from src.ingestion.google_transport import call
from src.ingestion.source_pages import apple_pages, google_pages


JOB = {'source': 'google_play', 'app_id': 'com.example.app', 'country': 'vn', 'language': 'vi', 'limit': 2}
OPTIONS = {'delay': 0.5, 'attempts': 1, 'timeout': 5}


def event(index, text='Tốt 😊, "hay"\nxuống dòng'):
    return {'source_domain': 'google_play', 'item_id': 'com.example.app', 'country': 'vn',
            'language': 'vi', 'collected_at': '2026-11-03T10:00:00+00:00',
            'app': {'title': 'App', 'nested': {'key': [1, 2]}},
            'review': {'reviewId': str(index), 'content': text, 'score': 5, 'extra': None}}


class DatasetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dataset = Dataset(self.temp.name)
        self.key = job_key(JOB)

    def tearDown(self):
        self.dataset.close()
        self.temp.cleanup()

    def test_transaction_rolls_back_rows_and_cursor(self):
        self.dataset.save_page(self.key, [event(1)], {'token': 'first'}, False, 10)
        with self.assertRaises(KeyError):
            self.dataset.save_page(self.key, [event(2), {'bad': 'entry'}], {'token': 'lost'}, False, 10)
        self.assertEqual(self.dataset.count(self.key), 1)
        self.assertEqual(self.dataset.state(self.key)['cursor'], {'token': 'first'})

    def test_pending_survives_reopen_and_quota_increase(self):
        self.dataset.save_page(self.key, [event(1), event(2), event(3)], {}, True, 2)
        self.dataset.close()
        self.dataset = Dataset(self.temp.name)
        with patch('src.ingestion.collect.pages') as fetch:
            result = collect_job(self.dataset, dict(JOB, limit=3), OPTIONS, 10)
        fetch.assert_not_called()
        self.assertEqual(result['collected'], 3)
        self.assertEqual(result['status'], 'complete')

    def test_duplicate_delivery_not_counted_toward_target(self):
        self.dataset.save_page(self.key, [event(1), event(1), event(2)], {}, True, 2)
        self.assertEqual(self.dataset.count(self.key), 2)

    def test_json_csv_and_jsonl_preserve_raw_payload(self):
        rows = [event(1), event(2, '=HYPERLINK("example")')]
        self.dataset.save_page(self.key, rows, {}, True, 2)
        self.dataset.export([self.key])
        folder = Path(self.temp.name)
        self.assertEqual(json.loads((folder / 'google_play.json').read_text(encoding='utf-8')), rows)
        lines = [json.loads(line) for line in (folder / 'google_play.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual(lines, rows)
        with (folder / 'google_play.csv').open(encoding='utf-8-sig', newline='') as handle:
            csv_rows = list(csv.DictReader(handle))
        self.assertEqual([json.loads(row['review_json']) for row in csv_rows], [row['review'] for row in rows])
        self.assertEqual(json.loads(csv_rows[0]['app_json']), rows[0]['app'])
        self.assertTrue(csv_rows[1]['review_text'].startswith("'="))
        self.assertEqual(json.loads((folder / 'app_store.json').read_text()), [])

    @patch('src.ingestion.collect.pages')
    def test_resume_passes_saved_cursor_and_completed_job_skips_network(self, pages):
        self.dataset.save_page(self.key, [event(1)], {'token': 'saved'}, False, 2)
        def source(*args, **kwargs):
            yield [event(2)], {'token': 'next'}, False
        pages.side_effect = source
        result = collect_job(self.dataset, JOB, OPTIONS, 10)
        self.assertEqual(pages.call_args.args[1], {'token': 'saved'})
        self.assertEqual(result['added'], 1)
        pages.reset_mock()
        result = collect_job(self.dataset, JOB, OPTIONS, 10)
        pages.assert_not_called()
        self.assertEqual(result['added'], 0)

    @patch('src.ingestion.collect.pages')
    def test_source_exhaustion_reports_shortfall(self, pages):
        def source(*args, **kwargs):
            yield [event(1)], {}, True
        pages.side_effect = source
        result = collect_job(self.dataset, JOB, OPTIONS, 10)
        self.assertEqual((result['status'], result['shortfall']), ('source_exhausted', 1))

    @patch('src.ingestion.collect.pages')
    def test_page_budget_is_resumable(self, pages):
        def source(*args, **kwargs):
            for i in range(3):
                yield [event(i)], {'token': str(i)}, False
        pages.side_effect = source
        result = collect_job(self.dataset, dict(JOB, limit=10), OPTIONS, 1)
        self.assertEqual(result['status'], 'page_budget_reached')
        self.assertEqual(self.dataset.count(self.key), 1)
        self.assertEqual(self.dataset.state(self.key)['cursor'], {'token': '0'})


class CollectionTests(unittest.TestCase):
    def test_invalid_config_before_network(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'jobs.json'
            for config in ({'jobs': []}, {'jobs': [JOB], 'delay': 0},
                           {'jobs': [dict(JOB, limit=True)]}, {'jobs': [JOB, JOB]},
                           {'jobs': [JOB], 'typo': 1}):
                path.write_text(json.dumps(config))
                with self.subTest(config=config), self.assertRaises(ValueError):
                    load_config(path)

    @patch('src.ingestion.collect.pages')
    def test_failed_app_continues_and_export_only_does_not_fetch(self, pages):
        def source(job, *args, **kwargs):
            if job['app_id'] == 'com.failed.app':
                raise TimeoutError('test deadline')
            yield [event(1), event(2)], {}, True
        pages.side_effect = source
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / 'config.json'
            config.write_text(json.dumps({'jobs': [dict(JOB, app_id='com.failed.app'), JOB]}))
            output = Path(folder) / 'data'
            with self.assertLogs(level='ERROR'):
                self.assertEqual(main(['--config', str(config), '--output-dir', str(output)]), 1)
            report = json.loads((output / 'report.json').read_text())
            self.assertEqual([row['status'] for row in report['jobs']], ['error', 'complete'])
            self.assertFalse(report['all_targets_met'])
            pages.reset_mock()
            self.assertEqual(main(['--config', str(config), '--output-dir', str(output), '--export-only']), 0)
            pages.assert_not_called()


class PageTests(unittest.TestCase):
    @patch('src.ingestion.source_pages.time.sleep')
    @patch('src.ingestion.source_pages.call')
    def test_google_resume_token(self, request, sleep):
        request.side_effect = [{'title': 'App'}, ([{'reviewId': '1'}], SimpleNamespace(token=None))]
        result = list(google_pages(JOB, {'token': 'saved'}, **OPTIONS))
        self.assertEqual(request.call_args.args[2]['continuation_token'].token, 'saved')
        self.assertEqual(len(result), 1)
        self.assertTrue(result[0][2])

    @patch('src.ingestion.source_pages.time.sleep')
    @patch('src.ingestion.source_pages.call')
    def test_google_repeated_token_fails(self, request, sleep):
        request.side_effect = [{}, ([{'reviewId': '1'}], SimpleNamespace(token='saved'))]
        with self.assertRaises(RuntimeError):
            list(google_pages(JOB, {'token': 'saved'}, **OPTIONS))

    @patch('src.ingestion.source_pages.time.sleep')
    @patch('src.ingestion.source_pages.requests.Session')
    def test_apple_resume_empty_page_and_last_page(self, session, sleep):
        client = session.return_value.__enter__.return_value
        client.get.side_effect = [MagicMock(json=MagicMock(return_value=data)) for data in
                                  ({'results': [{}]}, {'feed': {}},
                                   {'feed': {'entry': {'im:rating': {'label': '5'}}}})]
        result = list(apple_pages(dict(JOB, source='app_store', app_id='123'), {'page': 9}, **OPTIONS))
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0][0], [])
        self.assertEqual(result[-1][1], {'page': 11})
        self.assertTrue(result[-1][2])
        self.assertIn('page=9', client.get.call_args_list[1].args[0])

    @patch('src.ingestion.google_transport.multiprocessing.get_context')
    def test_deadline_terminates_worker(self, context):
        parent, child = MagicMock(), MagicMock()
        context.return_value.Pipe.return_value = parent, child
        parent.poll.return_value = False
        process = context.return_value.Process.return_value
        process.pid = 123
        process.is_alive.return_value = True
        with self.assertRaises(TimeoutError):
            call('app', 'com.example.app', {}, timeout=0.01)
        process.terminate.assert_called_once()
        parent.close.assert_called_once()
        process.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
