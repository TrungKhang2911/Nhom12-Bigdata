Pipeline:

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
[7. BI Dashboard & Insights] (Trực quan hóa, ... )



Kiến trúc dự án
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

Python: 3.10.11 (Bắt buộc dùng nhánh 3.10. Tuyệt đối không dùng 3.11 hay 3.12 vì cấu trúc tuần tự hóa dữ liệu sẽ gây lỗi crash cho PySpark).

Java Development Kit (JDK): 11 (OpenJDK 11 hoặc Oracle JDK 11). Dù JDK 17 đã ra mắt, JDK 11 vẫn là phiên bản có độ ổn định cao nhất khi chạy nền cho PySpark 3.5.

Hadoop (winutils): 3.3.6.

Docker Desktop: Phiên bản mới nhất.

