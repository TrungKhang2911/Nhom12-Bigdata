from datetime import datetime, timezone

from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.errors import OperationFailure

from config.settings import load_settings


COLLECTIONS = [
    "sources",
    "entities",
    "raw_reviews",
    "reviews",
    "daily_metrics",
    "pipeline_runs",
    "rejected_records",
]

COLLECTION_VALIDATORS = {
    "sources": {
        "$jsonSchema": {
            "bsonType": "object",
            "required": ["_id", "display_name", "domain_type", "enabled"],
            "properties": {
                "_id": {"bsonType": "string"},
                "display_name": {"bsonType": "string"},
                "domain_type": {"bsonType": "string"},
                "enabled": {"bsonType": "bool"},
                "created_at": {"bsonType": ["date", "null"]},
                "last_seen_at": {"bsonType": ["date", "null"]},
            },
        }
    },
    "entities": {
        "$jsonSchema": {
            "bsonType": "object",
            "required": ["_id", "source_domain", "country", "item_id"],
            "not": {"required": ["raw_metadata"]},
            "properties": {
                "_id": {"bsonType": "string"},
                "source_domain": {"bsonType": "string"},
                "country": {"bsonType": "string"},
                "item_id": {"bsonType": "string"},
                "item_name": {"bsonType": ["string", "null"]},
                "category": {"bsonType": ["string", "null"]},
                "brand_or_developer": {"bsonType": ["string", "null"]},
                "metadata": {"bsonType": "object"},
                "first_seen_at": {"bsonType": ["date", "null"]},
                "last_seen_at": {"bsonType": ["date", "null"]},
            },
        }
    },
    "raw_reviews": {
        "$jsonSchema": {
            "bsonType": "object",
            "required": ["_id", "source_domain", "item_id", "entity_key", "ingest"],
            "properties": {
                "_id": {"bsonType": "string"},
                "schema_version": {"bsonType": "int"},
                "source_domain": {"bsonType": "string"},
                "item_id": {"bsonType": "string"},
                "entity_key": {"bsonType": "string"},
                "rating": {
                    "bsonType": ["double", "int", "null"],
                    "minimum": 0,
                    "maximum": 5,
                },
                "ingest": {
                    "bsonType": "object",
                    "required": ["status"],
                    "properties": {
                        "run_id": {"bsonType": ["string", "null"]},
                        "status": {
                            "enum": ["pending", "processing", "done", "failed"],
                        },
                        "received_at": {"bsonType": ["date", "null"]},
                    },
                },
            },
        }
    },
    "reviews": {
        "$jsonSchema": {
            "bsonType": "object",
            "required": ["_id", "source_domain", "entity_key"],
            "properties": {
                "_id": {"bsonType": "string"},
                "source_domain": {"bsonType": "string"},
                "entity_key": {"bsonType": "string"},
                "rating": {
                    "bsonType": ["double", "int", "null"],
                    "minimum": 0,
                    "maximum": 5,
                },
                "sentiment_label": {"bsonType": ["string", "null"]},
            },
        }
    },
    "daily_metrics": {
        "$jsonSchema": {
            "bsonType": "object",
            "required": ["date", "source_domain", "entity_key"],
            "properties": {
                "date": {"bsonType": ["string", "date"]},
                "source_domain": {"bsonType": "string"},
                "entity_key": {"bsonType": "string"},
            },
        }
    },
    "pipeline_runs": {
        "$jsonSchema": {
            "bsonType": "object",
            "required": ["_id", "stage", "status", "started_at"],
            "properties": {
                "_id": {"bsonType": "string"},
                "stage": {"bsonType": "string"},
                "status": {"enum": ["running", "succeeded", "partial", "failed"]},
                "started_at": {"bsonType": "date"},
                "finished_at": {"bsonType": ["date", "null"]},
            },
        }
    },
    "rejected_records": {
        "$jsonSchema": {
            "bsonType": "object",
            "required": ["run_id", "reason", "created_at"],
            "properties": {
                "run_id": {"bsonType": "string"},
                "source_domain": {"bsonType": ["string", "null"]},
                "reason": {"bsonType": "string"},
                "created_at": {"bsonType": "date"},
            },
        }
    },
}

DEFAULT_SOURCES = [
    {
        "_id": "tiki",
        "display_name": "Tiki",
        "domain_type": "e-commerce",
        "enabled": True,
    },
    {
        "_id": "google_play",
        "display_name": "Google Play",
        "domain_type": "mobile_app",
        "enabled": True,
    },
    {
        "_id": "app_store",
        "display_name": "App Store",
        "domain_type": "mobile_app",
        "enabled": True,
    },
]


def _apply_validators(db):
    for name, validator in COLLECTION_VALIDATORS.items():
        try:
            db.command(
                {
                    "collMod": name,
                    "validator": validator,
                    "validationLevel": "moderate",
                    "validationAction": "error",
                }
            )
        except OperationFailure as exc:
            print(f"Canh bao: khong the ap dung validator cho {name}: {exc}")


def _ensure_daily_metrics_index(db):
    desired_key = [
        ("source_domain", ASCENDING),
        ("entity_key", ASCENDING),
        ("date", DESCENDING),
    ]
    existing_indexes = db.daily_metrics.index_information()
    if "daily_metrics_lookup" in existing_indexes:
        info = existing_indexes["daily_metrics_lookup"]
        if info.get("key") != desired_key or not info.get("unique", False):
            db.daily_metrics.drop_index("daily_metrics_lookup")

    db.daily_metrics.create_index(
        desired_key,
        unique=True,
        name="daily_metrics_lookup",
    )


def init_database(db):
    now = datetime.now(timezone.utc)
    existing = set(db.list_collection_names())
    for name in COLLECTIONS:
        if name not in existing:
            db.create_collection(name)

    _apply_validators(db)

    # Một đối tượng được nhận diện theo nguồn, thị trường và ID nguồn.
    db.entities.create_index(
        [
            ("source_domain", ASCENDING),
            ("country", ASCENDING),
            ("item_id", ASCENDING),
        ],
        unique=True,
        name="entity_identity",
    )

    # Xóa index cũ trỏ sai trường, nếu đã được tạo trước đó.
    if "raw_processing_queue" in db.raw_reviews.index_information():
        db.raw_reviews.drop_index("raw_processing_queue")

    db.raw_reviews.create_index(
        [
            ("source_domain", ASCENDING),
            ("ingest.status", ASCENDING),
            ("collected_at", DESCENDING),
        ],
        name="raw_ingest_queue",
    )
    db.raw_reviews.create_index(
        [("entity_key", ASCENDING), ("review_time", DESCENDING)],
        name="raw_reviews_by_entity_time",
    )

    # Tìm review đã xử lý theo đối tượng, nguồn, thời gian và cảm xúc.
    db.reviews.create_index(
        [("entity_key", ASCENDING), ("review_time", DESCENDING)],
        name="reviews_by_entity_time",
    )
    db.reviews.create_index(
        [
            ("source_domain", ASCENDING),
            ("sentiment_label", ASCENDING),
            ("review_time", DESCENDING),
        ],
        name="reviews_by_source_sentiment_time",
    )

    # Tối ưu theo ESR (Equality -> Sort) và chống trùng bản ghi tổng hợp theo ngày.
    _ensure_daily_metrics_index(db)

    db.pipeline_runs.create_index(
        [("started_at", DESCENDING)],
        name="pipeline_runs_by_start",
    )
    db.rejected_records.create_index(
        [("run_id", ASCENDING), ("created_at", DESCENDING)],
        name="rejected_records_by_run",
    )

    # Đăng ký nguồn; đồng bộ schema với mongo_client.py.
    for source in DEFAULT_SOURCES:
        db.sources.update_one(
            {"_id": source["_id"]},
            {
                "$setOnInsert": {
                    **source,
                    "created_at": now,
                }
            },
            upsert=True,
        )


def main():
    settings = load_settings()
    client = MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=10000)
    try:
        client.admin.command("ping")
        db = client[settings.mongo_database]
        init_database(db)
        print(f"Khởi tạo thành công database: {db.name}")
        print("Collections:", ", ".join(sorted(db.list_collection_names())))
    finally:
        client.close()


if __name__ == "__main__":
    main()
