# Kết quả kiểm tra ngày 2026-11-03

## Đợt hoàn thiện collector local (mới nhất)

- Python 3.10.11; **27 tests passed**, gồm rollback transaction, checkpoint,
  resume, tăng quota giữa trang, không đếm lại ID khi giao nhận, timeout Google,
  tiếp tục sau lỗi ứng dụng, báo thiếu dữ liệu và round-trip JSON/CSV.
- `compileall`, `git diff --check`, `src.ingestion.collect --help`: thành công.
- Cấu hình mẫu: `config/crawl_jobs.example.json`; output:
  `data/raw/mobile_reviews_sample/`.

| Nguồn | Ứng dụng | Mục tiêu mẫu | Thu được |
| --- | --- | ---: | ---: |
| Google Play | com.facebook.katana | 1.000 | 1.000 |
| Google Play | com.instagram.android | 1.000 | 1.000 |
| App Store | 284882215 (Facebook) | 500 | 500 |
| App Store | 389801252 (Instagram) | 500 | 500 |
| Tổng | Storefront VN | 3.000 | 3.000 |

Kiểm tra từng file JSON, JSONL và CSV: đủ 2.000 dòng Google, 1.000 dòng Apple;
`app_json`/`review_json` đọc ngược bằng JSON parser khớp với payload JSON gốc.
ID review phân biệt theo từng app/storefront/language. Bộ mẫu không thiếu trường
nội dung, rating, review_time trên cả hai nguồn.

Chạy lại cùng cấu hình/thư mục: **0 review thêm mới, 0 trang được gọi**, tổng
vẫn 3.000. `report.json` hiện ghi lần chạy lại này; `all_targets_met=true`.
Các file dữ liệu và SQLite đều nằm trong thư mục bị Git ignore.

**Chỉ tiêu mẫu không phải chỉ tiêu đề bài.** README và các file yêu cầu hiện có
không nêu quota/danh sách app bắt buộc; đang chờ người dùng cung cấp để đối chiếu
hoặc thu thập chính thức. Không chạy Kafka/Docker ở đợt này.

## Kiểm tra giai đoạn đầu

Môi trường: Windows, Python **3.10.11**, `.venv`, dependencies từ
`requirements-crawler.txt`. Python dùng để tạo venv nằm trong `.runtime/`;
cả hai thư mục đều bị Git ignore.

- `python -m unittest discover -s tests -v`: **14 tests passed**.
- `python -m compileall -q config src tests`: thành công.
- `python -m src.ingestion --help`: thành công.
- Hai notebook đọc được bằng JSON parser.
- `git diff --check`: thành công.
- `docker compose config --quiet`: exit 0; có cảnh báo không đọc được
  cấu hình Docker cá nhân do quyền truy cập. Chưa khởi động container.
- Thu thập thật Google Play: `com.facebook.katana`, `vn`, `vi`, limit 201:
  **201 reviews**, qua nhiều trang.
- Thu thập thật App Store: `284882215`, `vn`, limit 51, max-pages 2:
  **51 reviews**, qua nhiều trang.

Dữ liệu thử nằm ở `data/raw/google_play_pagination.jsonl` và
`data/raw/app_store_pagination.jsonl`, không đưa lên Git. Mỗi file đã được
parse JSONL và kiểm tra số dòng, nguồn, payload review và ID review phân biệt.

Kafka chỉ được kiểm thử mock (acknowledgment, lỗi gửi, đóng producer), chưa
xác minh với broker thật. Các module Spark/NLP/UI và các crawler khác là khung,
không có kết quả kiểm thử chạy nghiệp vụ. Đọc `docs/crawlers.md` để biết giới hạn
nguồn dữ liệu và hành vi khi lỗi.
