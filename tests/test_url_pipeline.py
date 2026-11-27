import unittest
from unittest.mock import MagicMock, patch

from src.ingestion.url_pipeline import (
    get_db_storage_info,
    get_platform_data_stats,
    parse_target_url,
    run_url_to_mongo_pipeline,
)
from tests.test_mongo import FakeDB


class TestParseTargetUrl(unittest.TestCase):
    def test_tiki_urls_and_id(self):
        self.assertEqual(
            parse_target_url("tiki", "https://tiki.vn/sach-nha-gia-kim-p52789367.html?spid=52789368")[0],
            "52789367",
        )
        self.assertEqual(parse_target_url("tiki", "52789367")[0], "52789367")
        with self.assertRaises(ValueError):
            parse_target_url("tiki", "https://tiki.vn/khong-co-ma")

    def test_google_play_urls_and_id(self):
        item_id, extra = parse_target_url(
            "google_play",
            "https://play.google.com/store/apps/details?id=com.facebook.katana&hl=vi&gl=VN",
        )
        self.assertEqual(item_id, "com.facebook.katana")
        self.assertEqual(extra, {"country": "vn", "language": "vi"})
        self.assertEqual(parse_target_url("google_play", "com.instagram.android")[0], "com.instagram.android")
        with self.assertRaises(ValueError):
            parse_target_url("google_play", "https://play.google.com/store/apps")

    def test_app_store_urls_and_id(self):
        item_id, extra = parse_target_url(
            "app_store",
            "https://apps.apple.com/vn/app/facebook/id284882215",
        )
        self.assertEqual(item_id, "284882215")
        self.assertEqual(extra, {"country": "vn"})
        self.assertEqual(parse_target_url("app_store", "284882215")[0], "284882215")
        with self.assertRaises(ValueError):
            parse_target_url("app_store", "https://apps.apple.com/vn/app/facebook")


class TestRollingBatchAndStorage(unittest.TestCase):
    def _make_fake_db(self, storage_bytes=10 * 1024 * 1024, index_bytes=2 * 1024 * 1024):
        db = FakeDB()
        db.command = MagicMock(
            return_value={
                "dataSize": storage_bytes * 2,
                "storageSize": storage_bytes,
                "indexSize": index_bytes,
            }
        )
        db.reviews.aggregate = MagicMock(
            return_value=[
                {
                    "_id": {"source_domain": "tiki", "entity_key": "ek1", "date": "2026-11-27"},
                    "item_id": "52789367",
                    "item_name": "Sách Nhà Giả Kim",
                    "total_reviews": 5,
                    "positive_count": 5,
                    "neutral_count": 0,
                    "negative_count": 0,
                    "avg_rating": 5.0,
                    "avg_sentiment_score": 0.95,
                }
            ]
        )
        return db

    def _make_events(self, count):
        return [
            {
                "source_domain": "tiki",
                "item_id": "52789367",
                "country": "vn",
                "language": None,
                "collected_at": "2026-11-27T08:00:00+00:00",
                "app": {"id": 52789367, "name": "Sách Nhà Giả Kim"},
                "review": {
                    "id": 1000 + i,
                    "content": f"Sách đẹp, giao nhanh #{i}",
                    "rating": 5,
                    "created_at": 1764230400 + i,
                },
            }
            for i in range(count)
        ]

    def test_get_db_storage_info(self):
        db = self._make_fake_db(storage_bytes=100 * 1024 * 1024, index_bytes=12 * 1024 * 1024)
        info = get_db_storage_info(quota_mb=512.0, db=db)
        self.assertEqual(info["used_mb"], 112.0)
        self.assertEqual(info["remaining_mb"], 400.0)
        self.assertEqual(info["quota_mb"], 512.0)

    def test_get_platform_data_stats(self):
        db = self._make_fake_db()
        mb = 1024 * 1024
        db.raw_reviews.aggregate = MagicMock(
            return_value=[
                {"_id": "tiki", "count": 500, "bytes": int(0.5 * mb)},
                {"_id": "google_play", "count": 300, "bytes": int(0.3 * mb)},
            ]
        )
        db.reviews.aggregate = MagicMock(
            return_value=[{"_id": "tiki", "count": 500, "bytes": int(0.4 * mb)}]
        )
        db.entities.aggregate = MagicMock(
            return_value=[{"_id": "tiki", "count": 2, "bytes": int(0.01 * mb)}]
        )
        db.daily_metrics.aggregate = MagicMock(return_value=[])

        rows = get_platform_data_stats(db=db)
        by_src = {r["source_domain"]: r for r in rows}
        self.assertEqual(by_src["tiki"]["raw_count"], 500)
        self.assertEqual(by_src["tiki"]["nlp_count"], 500)
        self.assertEqual(by_src["tiki"]["entity_count"], 2)
        self.assertAlmostEqual(by_src["tiki"]["total_mb"], 0.91, places=2)
        self.assertEqual(by_src["app_store"]["raw_count"], 0)

    def test_rolling_batch_unlimited_flushes_incrementally(self):
        db = self._make_fake_db()
        fake_events = self._make_events(5)
        fake_nlp = MagicMock()
        fake_nlp.analyze_review.return_value = (
            "sách đẹp giao nhanh",
            4,
            0.95,
            "Positive",
            [{"aspect": "giao hàng", "sentiment": "positive"}],
            "VALID_TEXT",
        )
        batch_updates = []

        with patch("src.ingestion.url_pipeline.iter_crawl_events", return_value=iter(fake_events)), patch(
            "src.ingestion.url_pipeline.get_nlp_pipeline", return_value=fake_nlp
        ):
            res = run_url_to_mongo_pipeline(
                "tiki",
                "https://tiki.vn/sach-nha-gia-kim-p52789367.html",
                limit=None,
                batch_size=2,
                run_nlp=True,
                quota_mb=512.0,
                batch_callback=batch_updates.append,
                db=db,
            )

        # 5 events với batch_size=2 -> 3 lô (2 + 2 + 1)
        self.assertEqual(res["stats"]["batches"], 3)
        self.assertEqual(res["stats"]["crawled"], 5)
        self.assertEqual(res["stats"]["raw_inserted"], 5)
        self.assertEqual(res["stats"]["nlp_processed"], 5)
        self.assertGreater(res["stats"]["downloaded_bytes"], 0)
        self.assertEqual(len(batch_updates), 3)
        self.assertEqual(len(db.raw_reviews.bulk_calls), 3)
        self.assertFalse(res["stats"]["stopped_due_to_quota"])

    def test_stops_early_when_remaining_storage_hits_threshold(self):
        # Đã dùng 505 MB / 512 MB -> còn 7 MB <= ngưỡng an toàn 10 MB
        db = self._make_fake_db(storage_bytes=495 * 1024 * 1024, index_bytes=10 * 1024 * 1024)
        fake_events = self._make_events(6)
        fake_nlp = MagicMock()
        fake_nlp.analyze_review.return_value = ("tot", 1, 0.9, "Positive", [], "VALID_TEXT")

        with patch("src.ingestion.url_pipeline.iter_crawl_events", return_value=iter(fake_events)), patch(
            "src.ingestion.url_pipeline.get_nlp_pipeline", return_value=fake_nlp
        ):
            res = run_url_to_mongo_pipeline(
                "tiki",
                "52789367",
                limit=None,
                batch_size=2,
                run_nlp=True,
                quota_mb=512.0,
                stop_when_remaining_mb=10.0,
                db=db,
            )

        self.assertTrue(res["stats"]["stopped_due_to_quota"])
        # Dừng ngay sau lô đầu tiên (2 review) thay vì chạy hết 6 review
        self.assertEqual(res["stats"]["batches"], 1)
        self.assertEqual(res["stats"]["crawled"], 2)


if __name__ == "__main__":
    unittest.main()
