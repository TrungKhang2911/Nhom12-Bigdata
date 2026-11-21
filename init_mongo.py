from pymongo import ASCENDING, DESCENDING, MongoClient

from config.settings import load_settings


settings = load_settings()
client = MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=10000)
client.admin.command("ping")

db = client[settings.mongo_database]

collections = [
    "sources",
    "entities",
    "raw_reviews",
    "reviews",
    "daily_metrics",
    "pipeline_runs",
    "rejected_records",
]

existing = set(db.list_collection_names())
for name in collections:
    if name not in existing:
        db.create_collection(name)

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

db.daily_metrics.create_index(
    [
        ("date", DESCENDING),
        ("source_domain", ASCENDING),
        ("entity_key", ASCENDING),
    ],
    name="daily_metrics_lookup",
)
db.pipeline_runs.create_index(
    [("started_at", DESCENDING)],
    name="pipeline_runs_by_start",
)
db.rejected_records.create_index(
    [("run_id", ASCENDING), ("created_at", DESCENDING)],
    name="rejected_records_by_run",
)

# Đăng ký nguồn; có thể bổ sung nguồn khác sau này.
sources = [
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

for source in sources:
    db.sources.update_one(
        {"_id": source["_id"]},
        {"$setOnInsert": source},
        upsert=True,
    )

print(f"Khởi tạo thành công database: {db.name}")
print("Collections:", ", ".join(sorted(db.list_collection_names())))

client.close()