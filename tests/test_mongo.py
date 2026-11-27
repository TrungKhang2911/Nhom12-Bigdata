import sys
import tempfile
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch


def _ensure_optional_deps():
    if "dotenv" not in sys.modules:
        try:
            import dotenv  # noqa: F401
        except ModuleNotFoundError:
            dotenv_stub = types.ModuleType("dotenv")
            dotenv_stub.load_dotenv = lambda *args, **kwargs: False
            sys.modules["dotenv"] = dotenv_stub

    if "pymongo" not in sys.modules:
        try:
            import pymongo  # noqa: F401
        except ModuleNotFoundError:
            pymongo_stub = types.ModuleType("pymongo")
            pymongo_stub.ASCENDING = 1
            pymongo_stub.DESCENDING = -1

            class _UpdateOne:
                def __init__(self, filter, update, upsert=False):
                    self._filter = filter
                    self._doc = update
                    self._upsert = upsert

            pymongo_stub.UpdateOne = _UpdateOne
            pymongo_stub.MongoClient = MagicMock
            errors_stub = types.ModuleType("pymongo.errors")

            class _OperationFailure(Exception):
                pass

            errors_stub.OperationFailure = _OperationFailure
            pymongo_stub.errors = errors_stub
            sys.modules["pymongo"] = pymongo_stub
            sys.modules["pymongo.errors"] = errors_stub


_ensure_optional_deps()

import init_mongo
from src.ingestion import import_to_mongo
from src.serving import mongo_client


class FakeCollection:
    def __init__(self):
        self.indexes = {}
        self.bulk_calls = []
        self.update_one_calls = []
        self.update_many_calls = []
        self.insert_many_calls = []
        self.dropped_indexes = []

    def index_information(self):
        return dict(self.indexes)

    def drop_index(self, name):
        self.dropped_indexes.append(name)
        self.indexes.pop(name, None)

    def create_index(self, keys, name=None, unique=False):
        self.indexes[name] = {"key": list(keys), "unique": unique}
        return name

    def bulk_write(self, ops, ordered=False):
        self.bulk_calls.append((ops, ordered))
        res = MagicMock()
        res.upserted_count = len(ops)
        res.modified_count = 0
        return res

    def update_one(self, flt, update, upsert=False):
        self.update_one_calls.append((flt, update, upsert))

    def update_many(self, flt, update):
        self.update_many_calls.append((flt, update))

    def insert_many(self, docs, ordered=False):
        self.insert_many_calls.append((docs, ordered))


class FakeDB:
    def __init__(self, existing=None):
        self.name = "sentiment"
        self._existing = list(existing or [])
        self.created_collections = []
        self.commands = []
        for col in init_mongo.COLLECTIONS:
            setattr(self, col, FakeCollection())

    def list_collection_names(self):
        return list(self._existing) + list(self.created_collections)

    def create_collection(self, name):
        self.created_collections.append(name)

    def command(self, cmd):
        self.commands.append(cmd)
        return {"ok": 1}


class TestInitMongo(unittest.TestCase):
    def test_init_database_creates_collections_validators_and_unique_daily_metrics(self):
        db = FakeDB(existing=["daily_metrics", "raw_reviews"])
        # Giả lập index cũ không unique và sai thứ tự ESR
        db.daily_metrics.indexes["daily_metrics_lookup"] = {
            "key": [("date", -1), ("source_domain", 1), ("entity_key", 1)],
            "unique": False,
        }
        db.raw_reviews.indexes["raw_processing_queue"] = {"key": [("status", 1)]}

        init_mongo.init_database(db)

        self.assertEqual(set(db.list_collection_names()), set(init_mongo.COLLECTIONS))
        self.assertIn("daily_metrics_lookup", db.daily_metrics.dropped_indexes)
        self.assertIn("raw_processing_queue", db.raw_reviews.dropped_indexes)

        dm_idx = db.daily_metrics.indexes["daily_metrics_lookup"]
        self.assertTrue(dm_idx["unique"])
        self.assertEqual(
            dm_idx["key"],
            [("source_domain", 1), ("entity_key", 1), ("date", -1)],
        )

        # Kiểm tra đã áp dụng JSON Schema validator cho tất cả 7 collection
        collmods = {cmd["collMod"] for cmd in db.commands if "collMod" in cmd}
        self.assertEqual(collmods, set(init_mongo.COLLECTIONS))

        # Kiểm tra seed sources có đầy đủ display_name, domain_type, enabled, created_at
        self.assertEqual(len(db.sources.update_one_calls), 3)
        for _, update, upsert in db.sources.update_one_calls:
            self.assertTrue(upsert)
            doc = update["$setOnInsert"]
            self.assertIn("display_name", doc)
            self.assertIn("domain_type", doc)
            self.assertIn("enabled", doc)
            self.assertIn("created_at", doc)


class TestMongoClient(unittest.TestCase):
    def test_as_datetime_supports_seconds_milliseconds_microseconds_and_iso(self):
        dt_sec = mongo_client._as_datetime(1700000000)
        dt_ms = mongo_client._as_datetime(1700000000000)
        dt_us = mongo_client._as_datetime(1700000000000000)
        dt_iso = mongo_client._as_datetime("2026-11-27T07:00:00Z")

        self.assertEqual(dt_sec, dt_ms)
        self.assertEqual(dt_sec, dt_us)
        self.assertEqual(dt_iso, datetime(2026, 11, 27, 7, 0, tzinfo=timezone.utc))
        self.assertIsNone(mongo_client._as_datetime(float("nan")))

    def test_rating_rejects_out_of_range_and_bool(self):
        self.assertEqual(mongo_client._rating("tiki", {"rating": 5}), 5.0)
        self.assertIsNone(mongo_client._rating("tiki", {"rating": 6}))
        self.assertIsNone(mongo_client._rating("tiki", {"rating": -1}))
        self.assertIsNone(mongo_client._rating("tiki", {"rating": True}))

    def test_ingest_deduplicates_entities_updates_metadata_and_records_rejected(self):
        db = FakeDB()
        events = [
            {
                "source_domain": "tiki",
                "country": "vn",
                "item_id": "12345",
                "app": {},
                "review": {"id": "r1", "content": "tot", "rating": 5, "created_at": 1700000000000},
            },
            {
                "source_domain": "tiki",
                "country": "vn",
                "item_id": "12345",
                "app": {"name": "San pham A"},
                "review": {"id": "r2", "content": "tam on", "rating": 4, "created_at": 1700000001},
            },
            {
                "source_domain": "tiki",
                # thiếu item_id -> phải bị đưa vào rejected_records
                "review": {"id": "r3"},
            },
        ]

        result = mongo_client.ingest_raw_events(events, run_id="run-1", db=db)

        self.assertEqual(result["received"], 3)
        self.assertEqual(result["inserted"], 2)
        self.assertEqual(result["rejected"], 1)

        # 2 review cùng 1 entity -> chỉ gửi đúng 1 UpdateOne cho db.entities
        self.assertEqual(len(db.entities.bulk_calls), 1)
        entity_ops, _ = db.entities.bulk_calls[0]
        self.assertEqual(len(entity_ops), 1)
        update_doc = entity_ops[0]._doc
        self.assertEqual(update_doc["$set"]["item_name"], "San pham A")
        self.assertEqual(update_doc["$set"]["raw_metadata"], {"name": "San pham A"})

        # Sources dùng schema thống nhất
        self.assertEqual(len(db.sources.update_one_calls), 1)
        _, source_update, _ = db.sources.update_one_calls[0]
        self.assertEqual(source_update["$setOnInsert"]["display_name"], "Tiki")
        self.assertEqual(source_update["$setOnInsert"]["domain_type"], "e-commerce")
        self.assertTrue(source_update["$setOnInsert"]["enabled"])

        # Bản ghi lỗi được lưu vào rejected_records
        self.assertEqual(len(db.rejected_records.insert_many_calls), 1)
        rejected_docs, _ = db.rejected_records.insert_many_calls[0]
        self.assertEqual(len(rejected_docs), 1)
        self.assertEqual(rejected_docs[0]["reason"], "missing_source_or_item_id")

    def test_upsert_processed_reviews_and_daily_metrics(self):
        db = FakeDB()
        res_reviews = mongo_client.upsert_processed_reviews(
            [{"_id": "rec-1", "source_domain": "tiki", "entity_key": "e1", "sentiment_label": "Positive"}],
            run_id="nlp-1",
            db=db,
        )
        self.assertEqual(res_reviews["processed"], 1)
        self.assertEqual(len(db.reviews.bulk_calls), 1)
        self.assertEqual(len(db.raw_reviews.update_many_calls), 1)
        flt, upd = db.raw_reviews.update_many_calls[0]
        self.assertEqual(flt, {"_id": {"$in": ["rec-1"]}})
        self.assertEqual(upd["$set"]["ingest.status"], "done")

        res_metrics = mongo_client.upsert_daily_metrics(
            [{"source_domain": "tiki", "entity_key": "e1", "date": "2026-11-27", "total_reviews": 10}],
            db=db,
        )
        self.assertEqual(res_metrics["total"], 1)
        self.assertEqual(len(db.daily_metrics.bulk_calls), 1)


class TestImportToMongo(unittest.TestCase):
    def test_import_file_records_json_errors_to_rejected_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            jsonl_path = Path(tmp) / "tiki.jsonl"
            jsonl_path.write_text(
                '{"source_domain": "tiki", "item_id": "1", "review": {"id": "a"}}\n'
                '{bad json line}\n',
                encoding="utf-8",
            )

            with patch.object(
                import_to_mongo,
                "ingest_raw_events",
                return_value={"received": 1, "inserted": 1, "already_existed": 0, "rejected": 0},
            ) as mock_ingest, patch.object(
                import_to_mongo,
                "record_rejected_records",
                return_value=1,
            ) as mock_reject:
                res = import_to_mongo.import_file(jsonl_path, "tiki", "run-xyz", batch_size=10)

            self.assertEqual(res["received"], 1)
            self.assertEqual(res["inserted"], 1)
            self.assertEqual(res["rejected"], 1)
            mock_ingest.assert_called_once()
            mock_reject.assert_called_once()
            args, _ = mock_reject.call_args
            self.assertEqual(args[0], "run-xyz")
            self.assertEqual(args[1][0]["line_number"], 2)
            self.assertIn("json_decode_error", args[1][0]["reason"])


if __name__ == "__main__":
    unittest.main()
