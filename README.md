**Pipeline:**

```text
[1. Scrape Raw Data]
│
▼
[2. Raw Data Storage] (Lưu file thô từng domain: tiki.csv, banking.csv,...)
│
▼
[3. Data Cleaning & Normalization] (Xóa dòng trùng, xử lý giá trị null, chuẩn hóa ngày tháng)
│
▼
[4. Schema Mapping & Merging] (Áp dụng Unified Schema chung và gộp vào một Master Dataset)
│
▼
[5. NLP & Sentiment Processing] (Tính Word Count, gán nhãn cảm xúc, phân tích khía cạnh)
│
▼
[6. Final Aggregated Database] (Bảng dữ liệu hoàn chỉnh sẵn sàng cho BI)
│
▼
[7. BI Dashboard & Insights] (Trực quan hóa, ... ).
```

**Kiến trúc dự án:**

```text

multi-domain-sentiment-bigdata/
│
├── config/                                # Cấu hình hệ thống & kết nối DB
│   ├── __init__.py
│   ├── settings.py                        # Biến môi trường, cấu hình Kafka, MongoDB
│   └── logging_config.py                  # Cấu hình ghi log cho các script cào & xử lý
│
├── data/                                  # Thư mục lưu trữ dữ liệu cục bộ (Ignore trên Git)
│   └── gold_processed/                    # [Gold Layer] Chỉ lưu dữ liệu hoàn chỉnh (đã gán nhãn NLP) nếu cần export
│       └── master_sentiment_dataset.parquet
│
├── notebooks/                             # Dùng cho Jupyter Notebooks nghiên cứu & minh chứng báo cáo
│   ├── 01_exploratory_analysis.ipynb      # Khám phá dữ liệu thô, thống kê mô tả ban đầu
│   └── 02_spark_test.ipynb                # Test các hàm PySpark (Mappers, Cleaner, NLP) trước khi đưa vào luồng thật
│
├── src/                                   # Mã nguồn chính của hệ thống (Source Code)
│   ├── __init__.py
│   │
│   ├── ingestion/                         # 1. THU THẬP: Module cào dữ liệu thuần túy (CHỈ CÀO, KHÔNG XỬ LÝ)
│   │   ├── __init__.py
│   │   ├── tiki_crawler.py                # Cào JSON nguyên bản từ Tiki API
│   │   ├── shopee_crawler.py              # Cào JSON nguyên bản từ Shopee API
│   │   └── gplay_crawler.py               # Cào JSON nguyên bản từ Google Play
│   │
│   ├── streaming/                         # 2. ĐỆM DỮ LIỆU: Module điều phối luồng thời gian thực (Kafka)
│   │   ├── __init__.py
│   │   └── kafka_producer.py              # Nhận JSON thô từ các crawler và đẩy thẳng vào Kafka Topic
│   │
│   ├── processing/                        # 3. XỬ LÝ: Module Big Data & NLP (ELT bằng PySpark)
│   │   ├── __init__.py
│   │   ├── spark_session.py               # Khởi tạo SparkSession kết nối tới Cluster, Kafka và MongoDB
│   │   │
│   │   ├── schema_mappers/                # [XỬ LÝ ĐẶC THÙ] Dùng Spark ép kiểu JSON thô của từng nguồn về chuẩn chung
│   │   │   ├── __init__.py
│   │   │   ├── unified_schema.py          # Định nghĩa StructType (Cấu trúc chung) cho toàn bộ dự án
│   │   │   ├── tiki_mapper.py             # Logic PySpark bóc tách và ánh xạ JSON của Tiki
│   │   │   ├── shopee_mapper.py           # Logic PySpark bóc tách và ánh xạ JSON của Shopee
│   │   │   └── gplay_mapper.py            # Logic PySpark bóc tách và ánh xạ JSON của Google Play
│   │   │
│   │   ├── data_cleaner.py                # [XỬ LÝ CHUNG] Xóa trùng, lọc null, chuẩn hóa chữ trên Unified DataFrame
│   │   ├── nlp_pipeline.py                # Xử lý teencode, tách từ, chạy mô hình AI gán nhãn cảm xúc
│   │   └── spark_streaming_job.py         # Nhạc trưởng: Đọc Kafka -> Gọi Mappers -> Gọi Cleaner -> NLP -> Ghi MongoDB
│   │
│   ├── serving/                           # 4. LƯU TRỮ: Module phục vụ truy vấn tốc độ cao
│   │   ├── __init__.py
│   │   └── mongo_client.py                # Thao tác đọc/ghi dữ liệu đã phân tích tại MongoDB
│   │
│   └── ui/                                # 5. HIỂN THỊ: Giao diện ứng dụng tương tác (Streamlit)
│       ├── __init__.py
│       └── app.py                         # Giao diện Web chính (Dashboard giám sát thời gian thực)
│
├── .env.example                           # Mẫu cấu hình biến môi trường (Database URLs, API keys)
├── .gitignore                             # Các file/thư mục không đưa lên Git (venv, cache, file parquet lớn)
├── docker-compose.yml                     # Cấu hình hạ tầng Big Data tối giản (Chỉ khởi tạo Kafka, Zookeeper, MongoDB)
├── requirements.txt                       # Danh sách thư viện Python cần thiết (pyspark, kafka-python, pymongo, streamlit...)
└── README.md                              # Tài liệu hướng dẫn cài đặt và mô tả đồ án cho giảng viên
```

## Cấu Trúc Dữ Liệu (Unified Schema)

**1. Nhóm thông tin định danh & Nguồn (Metadata & Source)**
- **`record_id`**: Mã định danh duy nhất cho mỗi dòng dữ liệu (UUID) để dễ dàng quản lý và tránh trùng lặp.
- **`source_domain`**: Nguồn thu thập dữ liệu (VD: tiki, shopee, google_play, app_store). Phục vụ cho bộ lọc trên BI Dashboard.
- **`domain_type`**: Phân loại ngành hàng tổng quát (VD: e-commerce, mobile_app, banking).

**2. Nhóm thông tin Đối tượng đánh giá (Item Details)**
- **`item_id`**: Mã sản phẩm (SKU) hoặc ID ứng dụng (Package Name/App ID).
- **`item_name`**: Tên sản phẩm hoặc tên ứng dụng.
- **`category`**: Ngành hàng hoặc Thể loại ứng dụng (VD: Điện thoại, Finance, Game).
- **`brand_or_developer`**: Tên thương hiệu sản phẩm hoặc nhà phát triển ứng dụng.

**3. Nhóm thông tin Đánh giá gốc (Raw Review Data - Qua bước 3)**
- **`user_name`**: Tên người dùng hoặc ID người dùng (đã ẩn danh hóa nếu cần).
- **`rating`**: Điểm số sao đánh giá (từ 1 đến 5).
- **`review_time`**: Thời gian đánh giá đã được chuẩn hóa định dạng chung (VD: YYYY-MM-DD HH:MM:SS).
- **`helpful_votes`**: Số lượt hữu ích/like mà bình luận nhận được (để BI ưu tiên hiển thị các bình luận có độ tin cậy cao).
- **`raw_text`**: Nội dung bình luận nguyên gốc (dùng để đối chiếu khi cần).

**4. Nhóm dữ liệu Xử lý ngôn ngữ & Cảm xúc (NLP & Sentiment - Qua bước 5)**
- **`cleaned_text`**: Văn bản đã qua làm sạch (chuẩn hóa Unicode, xóa emoji, dịch teencode, loại bỏ ký tự nhiễu).
- **`word_count`**: Số lượng từ trong `cleaned_text`. (Dùng để lọc các bình luận quá ngắn/spam trên BI).
- **`sentiment_score`**: Điểm số cảm xúc do mô hình AI dự đoán (từ 0.0 đến 1.0, hoặc -1.0 đến 1.0).
- **`sentiment_label`**: Nhãn phân loại cảm xúc (VD: Positive, Negative, Neutral).
- **`aspects`**: Dữ liệu dạng JSON/Array trích xuất các khía cạnh và cảm xúc tương ứng. (VD: `[{"aspect": "giao hàng", "sentiment": "negative"}, {"aspect": "chất lượng", "sentiment": "positive"}]`).

Yêu cầu hệ thống:
Python: 3.10.11 (Bắt buộc dùng nhánh 3.10. Tuyệt đối không dùng 3.11 hay 3.12 vì cấu trúc tuần tự hóa dữ liệu sẽ gây lỗi crash cho PySpark).
Java Development Kit (JDK): 11 (OpenJDK 11 hoặc Oracle JDK 11). Dù JDK 17 đã ra mắt, JDK 11 vẫn là phiên bản có độ ổn định cao nhất khi chạy nền cho PySpark 3.5.
Hadoop (winutils): 3.3.6.
Docker Desktop: Phiên bản mới nhất.   

## Trạng thái triển khai

Đã dựng cấu trúc trên ngay tại thư mục gốc repository. Crawler Google Play và
App Store được triển khai tại `src/ingestion/gplay_crawler.py` và
`src/ingestion/appstore_crawler.py`, có CLI đơn giản lưu JSONL và tùy chọn Kafka.
Luồng thu thập local hoàn thiện chạy qua `src/ingestion/collect.py`, sử dụng
adapter phân trang `source_pages.py`: xuất **JSON + JSONL + CSV**, checkpoint
SQLite, timeout, tiếp tục job khác khi lỗi và báo cáo số lượng thiếu.
Kafka được để lại cho giai đoạn tích hợp sau.
Thêm `data/raw/` để lưu dữ liệu thu thập cục bộ, `tests/` để kiểm thử và
`src/processing/schema_mappers/appstore_mapper.py` làm khung tích hợp Apple.

Crawler **Tiki** (`src/ingestion/tiki_crawler.py`) dùng chung luồng `collect.py`
ở trên (checkpoint, resume, report, xuất `tiki.json`/`tiki.jsonl`/`tiki.csv`).
Crawler **Shopee** chưa làm được: Shopee chặn mọi API công khai bằng anti-bot
(HTTP 403, error 90309999); phương án thay thế đang chờ nhóm quyết định, xem
mục Shopee trong [docs/crawlers.md](docs/crawlers.md).

Các module Shopee, Spark, schema mapper, NLP, MongoDB client và UI hiện
**chỉ là khung cho các thành viên khác**, chưa có xử lý nghiệp vụ. Hai notebook
là notebook khởi tạo. File Parquet chỉ được tạo khi pipeline xử lý thực sự có
dữ liệu; repository không chứa file Parquet giả.

## Chạy crawler nhanh (PowerShell)

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-crawler.txt
Copy-Item .env.example .env

# Sửa danh sách app và limit trong file cấu hình theo chỉ tiêu của nhóm
Copy-Item config/crawl_jobs.example.json config/crawl_jobs.json

# Thu thập cả hai nguồn, xuất JSON + JSONL + CSV; chạy lại cùng lệnh để resume
.\.venv\Scripts\python.exe -m src.ingestion.collect --config config/crawl_jobs.json --output-dir data/raw/mobile_reviews

# Tiki: cùng lệnh, file cấu hình và thư mục riêng
Copy-Item config/crawl_jobs.tiki.example.json config/crawl_jobs.tiki.json
.\.venv\Scripts\python.exe -m src.ingestion.collect --config config/crawl_jobs.tiki.json --output-dir data/raw/ecommerce_reviews

# Kiểm thử không gọi API thật
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Nếu `.venv` đã được chuẩn bị trong workspace thì dùng trực tiếp Python trong
đó, không cần tạo lại. Crawler chạy độc lập, không cần Java, Spark hay Docker.
Cài toàn bộ dependencies cho các phần khác bằng `pip install -r requirements.txt`
(file này tham chiếu danh sách gốc `requirement.txt`).

README hiện không có chỉ tiêu số review hay danh sách ứng dụng bắt buộc. Cấu hình
mẫu là Facebook/Instagram tại VN, mục tiêu mẫu tổng 3.000 review; đây không phải
chỉ tiêu của đề. Nếu nguồn không đủ, `report.json` ghi rõ số thiếu.

Xem [hướng dẫn crawler](docs/crawlers.md) để cấu hình ứng dụng, xuất dữ liệu,
chạy tiếp khi gián đoạn và hiểu giới hạn từng nguồn.
