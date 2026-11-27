import hashlib
import json
import math
from datetime import datetime, timezone

from pymongo import MongoClient, UpdateOne

from config.settings import load_settings


_client = None
_client_uri = None

KNOWN_SOURCES = {
    "tiki": ("Tiki", "e-commerce"),
    "shopee": ("Shopee", "e-commerce"),
    "google_play": ("Google Play", "mobile_app"),
    "app_store": ("App Store", "mobile_app"),
}


def _now():
    return datetime.now(timezone.utc)


def _get_db():
    global _client, _client_uri

    settings = load_settings()
    if _client is None or _client_uri != settings.mongo_uri:
        close_client()
        _client = MongoClient(
            settings.mongo_uri,
            serverSelectionTimeoutMS=10000,
        )
        _client.admin.command("ping")
        _client_uri = settings.mongo_uri

    return _client[settings.mongo_database]


def close_client():
    global _client, _client_uri

    if _client is not None:
        _client.close()
        _client = None
        _client_uri = None


def _stable_hash(value):
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _source_defaults(source):
    display_name, domain_type = KNOWN_SOURCES.get(
        source,
        (source.replace("_", " ").title(), "unknown"),
    )
    return {
        "display_name": display_name,
        "domain_type": domain_type,
        "enabled": True,
    }


def compact_entity_metadata(source, app_metadata):
    """Lọc gọn metadata sản phẩm/ứng dụng: loại bỏ mô tả HTML, mảng ảnh và bảng thông số nặng."""
    if not isinstance(app_metadata, dict) or not app_metadata:
        return {
            "item_name": None,
            "category": None,
            "brand_or_developer": None,
            "metadata": {},
        }

    item_name = (
        app_metadata.get("title")
        or app_metadata.get("trackName")
        or app_metadata.get("name")
    )

    category = None
    brand_or_developer = None
    metadata = {}

    if source == "tiki":
        cat_obj = app_metadata.get("categories")
        if isinstance(cat_obj, dict):
            category = cat_obj.get("name")
        elif isinstance(cat_obj, str):
            category = cat_obj
        brand_obj = app_metadata.get("brand")
        seller_obj = app_metadata.get("current_seller")
        if isinstance(brand_obj, dict):
            brand_or_developer = brand_obj.get("name")
        if not brand_or_developer and isinstance(seller_obj, dict):
            brand_or_developer = seller_obj.get("name")

        for dst, src in (
            ("price", "price"),
            ("rating_average", "rating_average"),
            ("review_count", "review_count"),
            ("thumbnail_url", "thumbnail_url"),
            ("short_url", "short_url"),
        ):
            if app_metadata.get(src) is not None:
                metadata[dst] = app_metadata[src]
    elif source == "google_play":
        category = app_metadata.get("genre")
        brand_or_developer = app_metadata.get("developer")
        for dst, src in (
            ("price", "price"),
            ("rating_average", "score"),
            ("review_count", "reviews"),
            ("installs", "installs"),
            ("thumbnail_url", "icon"),
            ("url", "url"),
        ):
            if app_metadata.get(src) is not None:
                metadata[dst] = app_metadata[src]
    elif source == "app_store":
        category = app_metadata.get("primaryGenreName")
        if not category and isinstance(app_metadata.get("genres"), list) and app_metadata["genres"]:
            category = str(app_metadata["genres"][0])
        brand_or_developer = app_metadata.get("sellerName") or app_metadata.get("artistName")
        for dst, src in (
            ("price", "price"),
            ("rating_average", "averageUserRating"),
            ("review_count", "userRatingCount"),
            ("thumbnail_url", "artworkUrl100"),
            ("url", "trackViewUrl"),
        ):
            if app_metadata.get(src) is not None:
                metadata[dst] = app_metadata[src]
    else:
        category = app_metadata.get("category") or app_metadata.get("genre")
        brand_or_developer = app_metadata.get("brand") or app_metadata.get("developer")

    return {
        "item_name": str(item_name) if item_name else None,
        "category": str(category) if category else None,
        "brand_or_developer": str(brand_or_developer) if brand_or_developer else None,
        "metadata": metadata,
    }


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
        if not math.isfinite(value):
            return None
        seconds = float(value)
        # Tự động chuẩn hóa timestamp dạng micro-giây (16 chữ số) hoặc mili-giây (13 chữ số).
        if abs(seconds) >= 1e14:
            seconds /= 1_000_000.0
        elif abs(seconds) >= 1e11:
            seconds /= 1_000.0
        try:
            return datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None

    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
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

    if value is None or isinstance(value, bool):
        return None

    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None

    if not math.isfinite(numeric) or numeric < 0.0 or numeric > 5.0:
        return None

    return numeric


def start_pipeline_run(run_id, stage, metadata=None, db=None):
    db = db if db is not None else _get_db()
    now = _now()
    doc = {
        "_id": run_id,
        "stage": stage,
        "status": "running",
        "started_at": now,
        "finished_at": None,
        "metadata": metadata or {},
        "stats": {},
    }
    db.pipeline_runs.update_one(
        {"_id": run_id},
        {"$setOnInsert": doc},
        upsert=True,
    )
    return doc


def finish_pipeline_run(run_id, status, stats=None, error=None, db=None):
    db = db if db is not None else _get_db()
    update = {
        "status": status,
        "finished_at": _now(),
        "stats": stats or {},
    }
    if error is not None:
        update["error"] = str(error)

    db.pipeline_runs.update_one(
        {"_id": run_id},
        {"$set": update},
    )


def record_rejected_records(run_id, records, db=None):
    if not records:
        return 0

    db = db if db is not None else _get_db()
    now = _now()
    docs = []
    for item in records:
        docs.append(
            {
                "run_id": run_id,
                "source_domain": item.get("source_domain"),
                "reason": item.get("reason") or "invalid_record",
                "raw_payload": item.get("raw_payload"),
                "file_path": item.get("file_path"),
                "line_number": item.get("line_number"),
                "created_at": now,
            }
        )

    db.rejected_records.insert_many(docs, ordered=False)
    return len(docs)


def ingest_raw_events(events, run_id, db=None):
    db = db if db is not None else _get_db()
    entities_by_key = {}
    review_ops = []
    rejected = []
    sources = set()
    now = _now()

    for event in events:
        if not isinstance(event, dict):
            rejected.append(
                {
                    "source_domain": None,
                    "reason": "event_not_object",
                    "raw_payload": event,
                }
            )
            continue

        source = event.get("source_domain")
        raw_item_id = event.get("item_id")
        if not source or raw_item_id is None or str(raw_item_id).strip() == "":
            rejected.append(
                {
                    "source_domain": source if isinstance(source, str) else None,
                    "reason": "missing_source_or_item_id",
                    "raw_payload": event,
                }
            )
            continue

        source = str(source)
        country = str(event.get("country") or "unknown")
        item_id = str(raw_item_id)
        app_metadata = event.get("app") if isinstance(event.get("app"), dict) else {}
        raw_review = event.get("review") if isinstance(event.get("review"), dict) else {}

        entity_key = _stable_hash([source, country, item_id])
        source_review_id = _review_id(source, raw_review)
        record_id = _stable_hash(
            [source, country, item_id, source_review_id]
        )

        compact_meta = compact_entity_metadata(source, app_metadata)

        # Gom trùng entity trong cùng một batch để giảm số thao tác ghi lên MongoDB.
        existing_entity = entities_by_key.get(entity_key)
        if existing_entity is None:
            entities_by_key[entity_key] = {
                "source_domain": source,
                "country": country,
                "item_id": item_id,
                "item_name": compact_meta["item_name"],
                "category": compact_meta["category"],
                "brand_or_developer": compact_meta["brand_or_developer"],
                "metadata": compact_meta["metadata"],
            }
        else:
            if compact_meta["item_name"]:
                existing_entity["item_name"] = compact_meta["item_name"]
            if compact_meta["category"]:
                existing_entity["category"] = compact_meta["category"]
            if compact_meta["brand_or_developer"]:
                existing_entity["brand_or_developer"] = compact_meta["brand_or_developer"]
            if compact_meta["metadata"]:
                existing_entity["metadata"] = compact_meta["metadata"]

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

    entity_ops = []
    for entity_key, info in entities_by_key.items():
        set_fields = {"last_seen_at": now}
        set_on_insert = {
            "_id": entity_key,
            "source_domain": info["source_domain"],
            "country": info["country"],
            "item_id": info["item_id"],
            "first_seen_at": now,
        }
        # Cho phép cập nhật tên, ngành hàng, thương hiệu & metadata gọn khi có dữ liệu.
        for field in ("item_name", "category", "brand_or_developer"):
            if info[field]:
                set_fields[field] = info[field]
            else:
                set_on_insert[field] = None

        if info["metadata"]:
            set_fields["metadata"] = info["metadata"]
        else:
            set_on_insert["metadata"] = {}

        entity_ops.append(
            UpdateOne(
                {"_id": entity_key},
                {
                    "$setOnInsert": set_on_insert,
                    "$set": set_fields,
                    "$unset": {"raw_metadata": ""},
                },
                upsert=True,
            )
        )

    if entity_ops:
        db.entities.bulk_write(entity_ops, ordered=False)

    result = (
        db.raw_reviews.bulk_write(review_ops, ordered=False)
        if review_ops
        else None
    )

    if rejected:
        record_rejected_records(run_id, rejected, db=db)

    for source in sources:
        defaults = _source_defaults(source)
        db.sources.update_one(
            {"_id": source},
            {
                "$setOnInsert": {
                    **defaults,
                    "created_at": now,
                },
                "$set": {"last_seen_at": now},
            },
            upsert=True,
        )

    valid_count = len(review_ops)
    inserted = result.upserted_count if result else 0
    return {
        "received": len(events),
        "inserted": inserted,
        "already_existed": valid_count - inserted,
        "rejected": len(rejected),
    }


def upsert_processed_reviews(reviews, run_id=None, db=None):
    """Ghi hàng loạt review đã xử lý NLP vào collection `reviews` và đánh dấu `done` ở `raw_reviews`."""
    if not reviews:
        return {"processed": 0, "upserted": 0, "modified": 0}

    db = db if db is not None else _get_db()
    now = _now()
    review_ops = []
    processed_ids = []

    for doc in reviews:
        record_id = doc["_id"]
        processed_ids.append(record_id)
        payload = {
            **doc,
            "processed_at": doc.get("processed_at") or now,
        }
        if run_id is not None:
            payload["processing_run_id"] = run_id

        review_ops.append(
            UpdateOne(
                {"_id": record_id},
                {"$set": payload},
                upsert=True,
            )
        )

    result = db.reviews.bulk_write(review_ops, ordered=False)
    db.raw_reviews.update_many(
        {"_id": {"$in": processed_ids}},
        {
            "$set": {
                "ingest.status": "done",
                "ingest.processed_at": now,
            }
        },
    )
    return {
        "processed": len(processed_ids),
        "upserted": result.upserted_count,
        "modified": result.modified_count,
    }


def upsert_daily_metrics(metrics, db=None):
    """Ghi hàng loạt số liệu tổng hợp theo ngày vào `daily_metrics` (idempotent theo khóa duy nhất)."""
    if not metrics:
        return {"total": 0, "upserted": 0, "modified": 0}

    db = db if db is not None else _get_db()
    now = _now()
    ops = []
    for metric in metrics:
        key = {
            "source_domain": metric["source_domain"],
            "entity_key": metric["entity_key"],
            "date": metric["date"],
        }
        payload = {
            **metric,
            "updated_at": now,
        }
        ops.append(
            UpdateOne(
                key,
                {"$set": payload},
                upsert=True,
            )
        )

    result = db.daily_metrics.bulk_write(ops, ordered=False)
    return {
        "total": len(ops),
        "upserted": result.upserted_count,
        "modified": result.modified_count,
    }
