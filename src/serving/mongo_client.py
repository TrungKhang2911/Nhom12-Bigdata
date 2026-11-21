import hashlib
import json
from datetime import datetime, timezone

from pymongo import MongoClient, UpdateOne

from config.settings import load_settings


_client = None


def _now():
    return datetime.now(timezone.utc)


def _get_db():
    global _client

    settings = load_settings()
    if _client is None:
        _client = MongoClient(
            settings.mongo_uri,
            serverSelectionTimeoutMS=10000,
        )
        _client.admin.command("ping")

    return _client[settings.mongo_database]


def _stable_hash(value):
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _review_id(source, review):
    if source == "google_play":
        value = review.get("reviewId")
    elif source == "app_store":
        value = (review.get("id") or {}).get("label")
    elif source == "tiki":
        value = review.get("id")
    elif source == "shopee":
        value = review.get("cmtid")
    else:
        value = None

    return str(value) if value is not None else _stable_hash(review)


def _as_datetime(value):
    if value is None:
        return None

    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None

    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    return None


def _review_time(source, review):
    if source == "google_play":
        value = review.get("at")
    elif source == "app_store":
        value = (review.get("updated") or {}).get("label")
    elif source == "tiki":
        value = review.get("created_at")
    elif source == "shopee":
        value = review.get("ctime")
    else:
        value = None

    return _as_datetime(value)


def _review_text(source, review):
    if source == "google_play":
        value = review.get("content")
    elif source == "app_store":
        value = (review.get("content") or {}).get("label")
    elif source == "tiki":
        value = review.get("content")
    elif source == "shopee":
        value = review.get("comment")
    else:
        value = None

    return value if isinstance(value, str) else None


def _rating(source, review):
    if source == "google_play":
        value = review.get("score")
    elif source == "app_store":
        value = (review.get("im:rating") or {}).get("label")
    elif source == "tiki":
        value = review.get("rating")
    elif source == "shopee":
        value = review.get("rating_star")
    else:
        value = None

    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def ingest_raw_events(events, run_id):
    db = _get_db()
    entity_ops = []
    review_ops = []
    sources = set()
    now = _now()

    for event in events:
        source = event["source_domain"]
        country = event.get("country") or "unknown"
        item_id = str(event["item_id"])
        app_metadata = event.get("app") or {}
        raw_review = event.get("review") or {}

        entity_key = _stable_hash([source, country, item_id])
        source_review_id = _review_id(source, raw_review)
        record_id = _stable_hash(
            [source, country, item_id, source_review_id]
        )

        entity_doc = {
            "_id": entity_key,
            "source_domain": source,
            "country": country,
            "item_id": item_id,
            "item_name": (
                app_metadata.get("title")
                or app_metadata.get("trackName")
                or app_metadata.get("name")
            ),
            "raw_metadata": app_metadata,
        }
        entity_ops.append(
            UpdateOne(
                {"_id": entity_key},
                {
                    "$setOnInsert": {
                        **entity_doc,
                        "first_seen_at": now,
                    },
                    "$set": {"last_seen_at": now},
                },
                upsert=True,
            )
        )

        raw_document = {
            "_id": record_id,
            "schema_version": 1,
            "source_domain": source,
            "country": country,
            "language": event.get("language"),
            "item_id": item_id,
            "entity_key": entity_key,
            "source_review_id": source_review_id,
            "collected_at": _as_datetime(event.get("collected_at")),
            "review_time": _review_time(source, raw_review),
            "review_text": _review_text(source, raw_review),
            "rating": _rating(source, raw_review),
            "raw_review": raw_review,
            "ingest": {
                "run_id": run_id,
                "status": "pending",
                "received_at": now,
            },
        }
        review_ops.append(
            UpdateOne(
                {"_id": record_id},
                {"$setOnInsert": raw_document},
                upsert=True,
            )
        )
        sources.add(source)

    if entity_ops:
        db.entities.bulk_write(entity_ops, ordered=False)

    result = (
        db.raw_reviews.bulk_write(review_ops, ordered=False)
        if review_ops
        else None
    )

    for source in sources:
        db.sources.update_one(
            {"_id": source},
            {
                "$setOnInsert": {
                    "name": source,
                    "created_at": now,
                },
                "$set": {"last_seen_at": now},
            },
            upsert=True,
        )

    inserted = result.upserted_count if result else 0
    return {
        "received": len(events),
        "inserted": inserted,
        "already_existed": len(events) - inserted,
    }