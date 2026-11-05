# Kết quả kiểm tra

## 2026-11-04: Crawler Tiki (mới nhất)

- Python 3.10.11, `.venv` cài từ `requirements-crawler.txt`; **40 tests passed**
  (27 cũ + 13 mới trong `tests/test_tiki.py`): phân trang, resume theo trang,
  sản phẩm 0 review, 404 không retry, retry lỗi mạng, phản hồi sai cấu trúc,
  round-trip JSON/JSONL/CSV, validate config, chạy end-to-end lệnh collect.
- `compileall`, `git diff --check`, `src.ingestion.collect --help`: thành công.
- Cấu hình mẫu: `config/crawl_jobs.tiki.example.json`; output:
  `data/raw/ecommerce_reviews_sample/` (Git ignore).

| Sản phẩm (ID) | Ngành hàng | Mục tiêu mẫu | Thu được | Có nội dung | Trang | Thời gian |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Sách Nhà Giả Kim (52789367) | Sách | 1.000 | 1.000 | 245 (24%) | 50 | 85 s |
| Sách Đắc Nhân Tâm (111285062) | Sách | 500 | 500 | 131 (26%) | 25 | 40 s |
| Chuột không dây HXSJ M103 (56859344) | Thiết bị số | 500 | 500 | 200 (40%) | 25 | 41 s |
| Bình giữ nhiệt Elmich EL-8013OL (120552065) | Gia dụng | 300 | 300 | 95 (32%) | 15 | 23 s |
| **Tổng** | | **2.300** | **2.300** | **671 (29%)** | 115 | ~3 phút |

Đọc lại output bằng script kiểm tra: JSON, JSONL, CSV mỗi file 2.300 dòng; JSON
khớp JSONL; `review_json`/`app_json` trong CSV parse ngược khớp payload;
`review_id` = `review.id`. 2.300 ID phân biệt, đúng thứ tự mới nhất trước trên cả
4 sản phẩm, không thiếu `rating`/`created_at`; review trải từ 2022-01 đến
2026-11. Thư mục chỉ có job Tiki không sinh file `google_play.*`/`app_store.*`.

Chạy lại cùng cấu hình/thư mục: **0 review thêm mới, 0 trang được gọi**, tổng
vẫn 2.300. `report.json` hiện ghi lần chạy lại này; `all_targets_met=true`.

Phát hiện nhóm cần lưu ý:

- **Chỉ 29% review Tiki có nội dung chữ**; còn lại chỉ chấm sao.
- **Lệch nhãn mạnh**: 5 sao chiếm 87,5% (2.013), 4 sao 10% (231), 3 sao 24 review,
  1–2 sao chỉ 32 review (1,4%). Nhóm NLP cần tính đến khi huấn luyện và đánh giá.
- **Dung lượng**: mỗi file JSON/JSONL/CSV khoảng 62 MB cho 2.300 review, vì metadata
  sản phẩm (trung bình 22.788 ký tự) lặp lại trong từng review, gấp khoảng 16 lần
  chính review (trung bình 1.434 ký tự). 500 dòng của sản phẩm 111285062 có
  `app_json` dài 35.189 ký tự, vượt giới hạn 32.767 ký tự/ô của Excel.
- **Shopee**: mọi endpoint công khai trả HTTP 403, error 90309999; chưa thu thập
  được. Xem mục Shopee trong `docs/crawlers.md`.

**Chỉ tiêu mẫu không phải chỉ tiêu đề bài.** Không chạy Kafka/Docker ở đợt này.

## 2026-11-03: Đợt hoàn thiện collector local

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
