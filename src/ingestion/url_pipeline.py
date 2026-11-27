"""Pipeline tự động: bóc tách URL -> Crawl cuốn chiếu từng lô -> MongoDB -> NLP -> daily_metrics."""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from src.serving import mongo_client

MODEL_DEFAULT_PATH = Path(__file__).resolve().parents[2] / "models" / "3_Max_Single_F1_SVM.pkl"
DEFAULT_ATLAS_QUOTA_MB = 512.0
UNLIMITED_SENTINEL = 10_000_000

PLATFORM_LABELS = {
    "tiki": "Tiki",
    "google_play": "Google Play",
    "app_store": "App Store",
}

PLATFORM_EXAMPLES = {
    "tiki": "https://tiki.vn/sach-nha-gia-kim-p52789367.html",
    "google_play": "https://play.google.com/store/apps/details?id=com.facebook.katana&hl=vi&gl=VN",
    "app_store": "https://apps.apple.com/vn/app/facebook/id284882215",
}

_DOMAIN_TYPES = {
    "tiki": "e-commerce",
    "shopee": "e-commerce",
    "google_play": "mobile_app",
    "app_store": "mobile_app",
}

_nlp_pipeline_cache = None


def get_db_storage_info(quota_mb: float = DEFAULT_ATLAS_QUOTA_MB, db=None) -> Dict[str, float]:
    """Đọc dung lượng hiện tại và dung lượng còn lại của database MongoDB (đơn vị MB)."""
    db = db if db is not None else mongo_client._get_db()
    stats = db.command("dbStats")
    data_mb = (stats.get("dataSize") or 0) / (1024 * 1024)
    storage_mb = (stats.get("storageSize") or 0) / (1024 * 1024)
    index_mb = (stats.get("indexSize") or 0) / (1024 * 1024)
    used_mb = storage_mb + index_mb
    quota = max(float(quota_mb), 1.0)
    remaining_mb = max(0.0, quota - used_mb)
    used_pct = min(100.0, (used_mb / quota) * 100.0)
    return {
        "data_mb": round(data_mb, 3),
        "storage_mb": round(storage_mb, 3),
        "index_mb": round(index_mb, 3),
        "used_mb": round(used_mb, 3),
        "quota_mb": round(quota, 2),
        "remaining_mb": round(remaining_mb, 3),
        "used_pct": round(used_pct, 2),
    }


def get_platform_data_stats(db=None) -> List[Dict[str, Any]]:
    """Thống kê số bản ghi và dung lượng BSON (MB) theo từng nền tảng trên các collection chính."""
    db = db if db is not None else mongo_client._get_db()

    def _agg_by_source(collection):
        pipeline = [
            {
                "$group": {
                    "_id": "$source_domain",
                    "count": {"$sum": 1},
                    "bytes": {"$sum": {"$bsonSize": "$$ROOT"}},
                }
            }
        ]
        result = {}
        for row in collection.aggregate(pipeline):
            key = row.get("_id") or "unknown"
            result[key] = {
                "count": int(row.get("count") or 0),
                "bytes": int(row.get("bytes") or 0),
            }
        return result

    raw_stats = _agg_by_source(db.raw_reviews)
    nlp_stats = _agg_by_source(db.reviews)
    ent_stats = _agg_by_source(db.entities)
    dm_stats = _agg_by_source(db.daily_metrics)

    all_sources = sorted(
        set(PLATFORM_LABELS.keys())
        | set(raw_stats.keys())
        | set(nlp_stats.keys())
        | set(ent_stats.keys())
        | set(dm_stats.keys())
    )

    mb = 1024 * 1024
    rows = []
    for src in all_sources:
        r = raw_stats.get(src, {"count": 0, "bytes": 0})
        n = nlp_stats.get(src, {"count": 0, "bytes": 0})
        e = ent_stats.get(src, {"count": 0, "bytes": 0})
        d = dm_stats.get(src, {"count": 0, "bytes": 0})
        total_bytes = r["bytes"] + n["bytes"] + e["bytes"] + d["bytes"]
        rows.append(
            {
                "source_domain": src,
                "platform_name": PLATFORM_LABELS.get(src, src),
                "entity_count": e["count"],
                "raw_count": r["count"],
                "raw_mb": round(r["bytes"] / mb, 3),
                "nlp_count": n["count"],
                "nlp_mb": round(n["bytes"] / mb, 3),
                "total_mb": round(total_bytes / mb, 3),
            }
        )

    rows.sort(key=lambda item: (item["raw_count"], item["total_mb"]), reverse=True)
    return rows


def _estimate_event_bytes(event: Dict[str, Any], include_app: bool = False) -> int:
    """Ước tính dung lượng thực nạp vào MongoDB (đã lọc bỏ mô tả HTML/ảnh/thông số nặng)."""
    payload = {k: v for k, v in event.items() if k != "app"}
    if include_app and "app" in event:
        source = str(event.get("source_domain") or "")
        payload["entity"] = mongo_client.compact_entity_metadata(source, event.get("app"))
    try:
        return len(json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"))
    except Exception:
        return 0


def parse_target_url(source: str, url_or_id: str) -> Tuple[str, Dict[str, str]]:
    """Trích xuất `item_id` (và `country`/`language` nếu có) từ URL hoặc ID trực tiếp."""
    raw = (url_or_id or "").strip()
    if not raw:
        raise ValueError("Vui lòng nhập URL hoặc mã sản phẩm/ứng dụng.")

    extra: Dict[str, str] = {}

    if source == "tiki":
        if re.fullmatch(r"\d+", raw):
            return raw, extra
        match = re.search(r"-p(\d+)\.html", raw)
        if not match:
            match = re.search(r"(?:^|[/-])p(\d+)(?:\.html|[/?#]|$)", raw)
        if not match:
            parsed = urlparse(raw)
            qs = parse_qs(parsed.query)
            if "product_id" in qs and qs["product_id"][0].isdigit():
                return qs["product_id"][0], extra
            raise ValueError(
                "Không tìm thấy mã sản phẩm Tiki trong URL. "
                "Ví dụ hợp lệ: https://tiki.vn/ten-san-pham-p52789367.html hoặc 52789367"
            )
        return match.group(1), extra

    if source == "google_play":
        if re.fullmatch(r"[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+", raw):
            return raw, extra
        parsed = urlparse(raw)
        qs = parse_qs(parsed.query)
        app_id = (qs.get("id") or [""])[0].strip()
        if not re.fullmatch(r"[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+", app_id):
            raise ValueError(
                "Không tìm thấy package name Google Play (tham số ?id=...) trong URL. "
                "Ví dụ hợp lệ: https://play.google.com/store/apps/details?id=com.facebook.katana"
            )
        gl = (qs.get("gl") or [""])[0].strip().lower()
        hl = (qs.get("hl") or [""])[0].strip().lower()
        if len(gl) == 2 and gl.isalpha():
            extra["country"] = gl
        if hl:
            extra["language"] = hl.split("-")[0]
        return app_id, extra

    if source == "app_store":
        if re.fullmatch(r"\d+", raw):
            return raw, extra
        match = re.search(r"/id(\d+)", raw)
        if not match:
            match = re.search(r"\bid=(\d+)", raw)
        if not match:
            raise ValueError(
                "Không tìm thấy App ID (dạng /id123456789) trong URL App Store. "
                "Ví dụ hợp lệ: https://apps.apple.com/vn/app/facebook/id284882215"
            )
        country_match = re.search(r"apps\.apple\.com/([a-zA-Z]{2})/", raw)
        if country_match:
            extra["country"] = country_match.group(1).lower()
        return match.group(1), extra

    raise ValueError(f"Nền tảng không được hỗ trợ: {source}")


def iter_crawl_events(
    source: str,
    item_id: str,
    *,
    country: str = "vn",
    language: str = "vi",
    limit: Optional[int] = None,
    delay: float = 0.5,
    attempts: int = 3,
    timeout: float = 30.0,
) -> Iterator[Dict[str, Any]]:
    """Generator trả về từng raw event (hỗ trợ `limit=None` để tải toàn bộ không giữ trong RAM)."""
    emitted = 0

    if source == "tiki":
        from src.ingestion import tiki_crawler

        seen_keys = set()
        job = {"source": "tiki", "app_id": str(item_id), "country": country.lower()}
        cursor: Dict[str, Any] = {}
        for page_rows, _, exhausted in tiki_crawler.pages(
            job, cursor, delay=delay, attempts=attempts, timeout=timeout
        ):
            for ev in page_rows:
                rid = mongo_client._review_id("tiki", ev.get("review") or {})
                if rid in seen_keys:
                    continue
                seen_keys.add(rid)
                yield ev
                emitted += 1
                if limit is not None and emitted >= limit:
                    return
            if exhausted:
                return
        return

    if source == "google_play":
        from src.ingestion import gplay_crawler

        effective_limit = limit if limit is not None else UNLIMITED_SENTINEL
        for ev in gplay_crawler.crawl(
            item_id,
            country=country.lower(),
            language=language,
            limit=effective_limit,
            delay=delay,
            attempts=attempts,
        ):
            yield ev
        return

    if source == "app_store":
        from src.ingestion import appstore_crawler

        # Apple RSS công khai tối đa 10 trang (~500 review).
        effective_limit = limit if limit is not None else 500
        for ev in appstore_crawler.crawl(
            item_id,
            country=country.lower(),
            limit=effective_limit,
            delay=delay,
            attempts=attempts,
            timeout=timeout,
        ):
            yield ev
        return

    raise ValueError(f"Nền tảng không được hỗ trợ: {source}")


def crawl_events(
    source: str,
    item_id: str,
    *,
    country: str = "vn",
    language: str = "vi",
    limit: Optional[int] = 100,
    delay: float = 0.5,
    attempts: int = 3,
    timeout: float = 30.0,
    progress_callback: Optional[Callable[[int, Optional[int]], None]] = None,
) -> List[Dict[str, Any]]:
    """Thu thập danh sách raw events (giữ tương thích ngược)."""
    events: List[Dict[str, Any]] = []
    for ev in iter_crawl_events(
        source,
        item_id,
        country=country,
        language=language,
        limit=limit,
        delay=delay,
        attempts=attempts,
        timeout=timeout,
    ):
        events.append(ev)
        if progress_callback:
            progress_callback(len(events), limit)
    return events


def get_nlp_pipeline(model_path: str | Path = MODEL_DEFAULT_PATH):
    """Khởi tạo và cache mô hình SentimentNLPPipeline để dùng lại nhanh trên UI."""
    global _nlp_pipeline_cache
    if _nlp_pipeline_cache is None:
        from src.processing.nlp_pipeline import SentimentNLPPipeline

        _nlp_pipeline_cache = SentimentNLPPipeline(model_path=model_path)
    return _nlp_pipeline_cache


def _build_processed_review_doc(event: Dict[str, Any], nlp_pipeline: Any) -> Dict[str, Any]:
    source = str(event["source_domain"])
    country = str(event.get("country") or "unknown")
    item_id = str(event["item_id"])
    app_meta = event.get("app") if isinstance(event.get("app"), dict) else {}
    raw_review = event.get("review") if isinstance(event.get("review"), dict) else {}

    entity_key = mongo_client._stable_hash([source, country, item_id])
    source_review_id = mongo_client._review_id(source, raw_review)
    record_id = mongo_client._stable_hash([source, country, item_id, source_review_id])

    raw_text = mongo_client._review_text(source, raw_review)
    rating = mongo_client._rating(source, raw_review)
    review_time = mongo_client._review_time(source, raw_review)
    collected_at = mongo_client._as_datetime(event.get("collected_at"))

    item_name = (
        app_meta.get("title")
        or app_meta.get("trackName")
        or app_meta.get("name")
    )

    cleaned_text, word_count, sentiment_score, sentiment_label, aspects, quality_status = (
        nlp_pipeline.analyze_review(
            raw_text,
            rating,
            source,
            app_meta,
        )
    )

    return {
        "_id": record_id,
        "source_domain": source,
        "domain_type": _DOMAIN_TYPES.get(source, "unknown"),
        "country": country,
        "language": event.get("language"),
        "item_id": item_id,
        "item_name": item_name,
        "entity_key": entity_key,
        "source_review_id": source_review_id,
        "rating": rating,
        "review_time": review_time,
        "collected_at": collected_at,
        "raw_text": raw_text,
        "cleaned_text": cleaned_text,
        "word_count": int(word_count),
        "sentiment_score": float(sentiment_score) if sentiment_score is not None else None,
        "sentiment_label": sentiment_label,
        "aspects": aspects,
        "quality_status": quality_status,
    }


def refresh_daily_metrics_for_entities(entity_keys: List[str], db=None) -> Dict[str, int]:
    """Tổng hợp lại `daily_metrics` từ collection `reviews` cho các `entity_key` vừa cập nhật."""
    if not entity_keys:
        return {"total": 0, "upserted": 0, "modified": 0}

    db = db if db is not None else mongo_client._get_db()
    pipeline = [
        {"$match": {"entity_key": {"$in": list(set(entity_keys))}}},
        {
            "$addFields": {
                "_metric_dt": {"$ifNull": ["$review_time", "$collected_at"]},
            }
        },
        {"$match": {"_metric_dt": {"$ne": None}}},
        {
            "$group": {
                "_id": {
                    "source_domain": "$source_domain",
                    "entity_key": "$entity_key",
                    "date": {
                        "$dateToString": {"format": "%Y-%m-%d", "date": "$_metric_dt"}
                    },
                },
                "item_id": {"$first": "$item_id"},
                "item_name": {"$first": "$item_name"},
                "total_reviews": {"$sum": 1},
                "positive_count": {
                    "$sum": {"$cond": [{"$eq": ["$sentiment_label", "Positive"]}, 1, 0]}
                },
                "neutral_count": {
                    "$sum": {"$cond": [{"$eq": ["$sentiment_label", "Neutral"]}, 1, 0]}
                },
                "negative_count": {
                    "$sum": {"$cond": [{"$eq": ["$sentiment_label", "Negative"]}, 1, 0]}
                },
                "avg_rating": {"$avg": "$rating"},
                "avg_sentiment_score": {"$avg": "$sentiment_score"},
            }
        },
    ]

    aggregated = list(db.reviews.aggregate(pipeline))
    metrics = []
    for row in aggregated:
        key = row["_id"]
        metrics.append(
            {
                "source_domain": key["source_domain"],
                "entity_key": key["entity_key"],
                "date": key["date"],
                "item_id": row.get("item_id"),
                "item_name": row.get("item_name"),
                "total_reviews": int(row["total_reviews"]),
                "positive_count": int(row["positive_count"]),
                "neutral_count": int(row["neutral_count"]),
                "negative_count": int(row["negative_count"]),
                "avg_rating": round(float(row["avg_rating"]), 4)
                if row.get("avg_rating") is not None
                else None,
                "avg_sentiment_score": round(float(row["avg_sentiment_score"]), 4)
                if row.get("avg_sentiment_score") is not None
                else None,
            }
        )

    return mongo_client.upsert_daily_metrics(metrics, db=db)


def run_url_to_mongo_pipeline(
    source: str,
    url_or_id: str,
    *,
    limit: Optional[int] = 100,
    batch_size: int = 200,
    country: str = "vn",
    language: str = "vi",
    delay: float = 0.5,
    run_nlp: bool = True,
    quota_mb: float = DEFAULT_ATLAS_QUOTA_MB,
    stop_when_remaining_mb: float = 10.0,
    status_callback: Optional[Callable[[str, float], None]] = None,
    batch_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    db=None,
) -> Dict[str, Any]:
    """Chạy nạp cuốn chiếu từng lô (rolling batch): Crawl -> raw_reviews -> NLP -> reviews -> daily_metrics.

    Đặt `limit=None` để tải toàn bộ đánh giá (không giới hạn số lượng).
    """
    if batch_size < 1:
        raise ValueError("batch_size phải lớn hơn 0.")

    def _notify(msg: str, progress: float):
        if status_callback:
            status_callback(msg, progress)

    _notify("Đang bóc tách mã sản phẩm/ứng dụng từ URL...", 0.02)
    item_id, detected = parse_target_url(source, url_or_id)
    effective_country = detected.get("country", country).lower()
    effective_language = detected.get("language", language).lower()

    run_id = str(uuid.uuid4())
    mongo_client.start_pipeline_run(
        run_id=run_id,
        stage="ui_crawl_rolling_pipeline",
        metadata={
            "source_domain": source,
            "input": url_or_id,
            "item_id": item_id,
            "country": effective_country,
            "language": effective_language,
            "limit": limit,
            "batch_size": batch_size,
            "run_nlp": run_nlp,
            "quota_mb": quota_mb,
        },
        db=db,
    )

    total_crawled = 0
    total_raw_inserted = 0
    total_raw_existing = 0
    total_raw_rejected = 0
    total_nlp_processed = 0
    total_batches = 0
    downloaded_bytes = 0
    stopped_due_to_quota = False
    item_name: Optional[str] = None
    entity_keys = set()
    sentiment_summary: Dict[str, int] = {}
    sample_reviews: List[Dict[str, Any]] = []
    nlp_pipeline = get_nlp_pipeline() if run_nlp else None
    storage_info = get_db_storage_info(quota_mb=quota_mb, db=db)

    def _flush_batch(batch: List[Dict[str, Any]]):
        nonlocal total_raw_inserted, total_raw_existing, total_raw_rejected
        nonlocal total_nlp_processed, total_batches, storage_info, stopped_due_to_quota

        if not batch:
            return

        total_batches += 1
        raw_res = mongo_client.ingest_raw_events(batch, run_id=run_id, db=db)
        total_raw_inserted += raw_res["inserted"]
        total_raw_existing += raw_res["already_existed"]
        total_raw_rejected += raw_res.get("rejected", 0)

        if run_nlp and nlp_pipeline is not None:
            processed_docs = []
            for ev in batch:
                doc = _build_processed_review_doc(ev, nlp_pipeline)
                processed_docs.append(doc)
                entity_keys.add(doc["entity_key"])
                label = doc.get("sentiment_label") or "Unknown"
                sentiment_summary[label] = sentiment_summary.get(label, 0) + 1
                if len(sample_reviews) < 30:
                    sample_reviews.append(doc)

            nlp_res = mongo_client.upsert_processed_reviews(
                processed_docs, run_id=run_id, db=db
            )
            total_nlp_processed += nlp_res["processed"]

        storage_info = get_db_storage_info(quota_mb=quota_mb, db=db)
        if stop_when_remaining_mb > 0 and storage_info["remaining_mb"] <= stop_when_remaining_mb:
            stopped_due_to_quota = True

        if batch_callback:
            batch_callback(
                {
                    "batches": total_batches,
                    "crawled": total_crawled,
                    "raw_inserted": total_raw_inserted,
                    "raw_already_existed": total_raw_existing,
                    "nlp_processed": total_nlp_processed,
                    "downloaded_mb": round(downloaded_bytes / (1024 * 1024), 3),
                    "storage": storage_info,
                    "stopped_due_to_quota": stopped_due_to_quota,
                }
            )

    try:
        target_label = f"tối đa {limit:,}" if limit is not None else "TOÀN BỘ (không giới hạn)"
        _notify(
            f"Đang crawl {target_label} đánh giá từ {PLATFORM_LABELS.get(source, source)} "
            f"(nạp cuốn chiếu {batch_size} dòng/lô)...",
            0.08,
        )

        batch: List[Dict[str, Any]] = []
        for ev in iter_crawl_events(
            source,
            item_id,
            country=effective_country,
            language=effective_language,
            limit=limit,
            delay=delay,
        ):
            if item_name is None:
                app_meta = ev.get("app") if isinstance(ev.get("app"), dict) else {}
                item_name = (
                    app_meta.get("title")
                    or app_meta.get("trackName")
                    or app_meta.get("name")
                )

            include_app = total_crawled == 0
            batch.append(ev)
            total_crawled += 1
            downloaded_bytes += _estimate_event_bytes(ev, include_app=include_app)

            if len(batch) >= batch_size:
                _flush_batch(batch)
                batch.clear()
                frac = (
                    min(0.90, 0.10 + 0.80 * (total_crawled / limit))
                    if limit is not None and limit > 0
                    else min(0.90, 0.10 + 0.05 * total_batches)
                )
                _notify(
                    f"Lô #{total_batches}: đã nạp cuốn chiếu {total_crawled:,} đánh giá "
                    f"({downloaded_bytes / (1024 * 1024):.2f} MB) | "
                    f"CSDL còn lại: {storage_info['remaining_mb']:.2f} MB",
                    frac,
                )
                if stopped_due_to_quota:
                    break

        if batch and not stopped_due_to_quota:
            _flush_batch(batch)
            batch.clear()

        metrics_res = {"total": 0, "upserted": 0, "modified": 0}
        if run_nlp and entity_keys:
            _notify("Đang tổng hợp lại báo cáo theo ngày vào daily_metrics...", 0.95)
            metrics_res = refresh_daily_metrics_for_entities(list(entity_keys), db=db)
            storage_info = get_db_storage_info(quota_mb=quota_mb, db=db)

        stats = {
            "item_id": item_id,
            "item_name": item_name,
            "batches": total_batches,
            "crawled": total_crawled,
            "raw_inserted": total_raw_inserted,
            "raw_already_existed": total_raw_existing,
            "raw_rejected": total_raw_rejected,
            "nlp_processed": total_nlp_processed,
            "daily_metrics_updated": metrics_res["total"],
            "downloaded_bytes": downloaded_bytes,
            "downloaded_mb": round(downloaded_bytes / (1024 * 1024), 3),
            "stopped_due_to_quota": stopped_due_to_quota,
            "db_storage": storage_info,
            "sentiment_summary": sentiment_summary,
        }
        status = (
            "partial"
            if (total_raw_rejected > 0 or stopped_due_to_quota)
            else "succeeded"
        )
        mongo_client.finish_pipeline_run(run_id, status=status, stats=stats, db=db)

        if stopped_due_to_quota:
            _notify(
                f"Đã tự động dừng sớm vì dung lượng CSDL còn lại ({storage_info['remaining_mb']:.2f} MB) "
                f"chạm ngưỡng an toàn ({stop_when_remaining_mb:.1f} MB). Các lô trước đã lưu an toàn!",
                1.0,
            )
        else:
            _notify("Hoàn tất toàn bộ luồng nạp cuốn chiếu & xử lý NLP!", 1.0)

        return {
            "run_id": run_id,
            "source_domain": source,
            "item_id": item_id,
            "item_name": item_name,
            "stats": stats,
            "sentiment_summary": sentiment_summary,
            "sample_reviews": sample_reviews,
            "storage": storage_info,
        }
    except Exception as exc:
        mongo_client.finish_pipeline_run(
            run_id,
            status="failed",
            stats={
                "item_id": item_id,
                "batches": total_batches,
                "crawled": total_crawled,
                "raw_inserted": total_raw_inserted,
                "nlp_processed": total_nlp_processed,
                "downloaded_mb": round(downloaded_bytes / (1024 * 1024), 3),
            },
            error=exc,
            db=db,
        )
        raise
