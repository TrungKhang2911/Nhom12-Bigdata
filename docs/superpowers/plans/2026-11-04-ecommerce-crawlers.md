# E-commerce crawlers implementation plan

**Goal:** Thu thập review Tiki/Shopee đúng hợp đồng dữ liệu thô của dự án (ID, nội dung, số sao, thời gian, nền tảng) và xuất file tĩnh vào `data/`.
**Architecture:** Thêm adapter phân trang `tiki_crawler.pages` vào luồng `src.ingestion.collect` có sẵn; dùng lại envelope, checkpoint SQLite, report và export JSON/JSONL/CSV. Không đổi đầu ra Google/Apple. Không làm sạch, không NLP. Kafka để giai đoạn sau.
**Tech Stack:** Python 3.10, requests, stdlib (sqlite3, csv, unittest).
**Spec:** Phân công Tuần 1 (Thành viên 1 & 2: Kỹ sư Thu thập), docs/crawlers.md.

## Global Constraints
- Giữ nguyên payload gốc; chỉ chống trùng theo ID review để resume an toàn.
- Không vượt cơ chế anti-bot của nguồn. Nguồn bị chặn thì báo rõ, không tạo dữ liệu giả.
- Không thay đổi file đầu ra hiện có của luồng Google Play / App Store.

## Review Focus
- Tiki giới hạn 20 review/trang; lớn hơn trả HTTP 400.
- Hết trang theo `paging.last_page`, sản phẩm 0 review, sản phẩm không tồn tại (404 không retry).
- Phản hồi sai cấu trúc phải báo lỗi, không âm thầm bỏ qua.
- Export theo nhóm nguồn: chạy riêng Google vẫn ghi lại `app_store.*` như cũ; chạy riêng Tiki không sinh file mobile.

### Task 1: Tiki adapter
**Files:** src/ingestion/tiki_crawler.py, src/ingestion/source_pages.py.
**Interfaces:** pages(job, cursor, *, delay, attempts, timeout) yields (raw_events, {'page': n + 1}, exhausted).
- [x] Khảo sát API thật: `products/{id}`, `reviews` (tối đa 20/trang, `sort=id|desc`, `paging.last_page`).
- [x] Cài adapter dùng `common.retry` và `common.envelope`; đăng ký vào `source_pages.pages`.

### Task 2: Collector, export và kiểm thử
**Files:** src/ingestion/collect.py, src/ingestion/dataset.py, config/crawl_jobs.tiki.example.json, tests/test_tiki.py.
- [x] Validate job Tiki trước khi gọi mạng: ID số, chỉ `vn`, không `language`; từ chối `shopee`.
- [x] `review_key` = `review.id`; CSV hiển thị `content`, `rating`, `created_at` (ISO 8601 UTC).
- [x] Export theo nhóm nguồn (`SOURCE_GROUPS`).
- [x] 13 test mới (phân trang, resume, 0 review, 404, retry, sai cấu trúc, CSV/JSON round-trip, config, end-to-end); toàn bộ 40 test pass.

### Task 3: Shopee
**Files:** src/ingestion/shopee_crawler.py.
- [x] Khảo sát API: mọi endpoint công khai trả HTTP 403, error 90309999 (anti-bot).
- [ ] Chờ nhóm chọn phương án: bỏ Shopee / dùng dataset công khai / import thủ công (xem docs/crawlers.md).

### Task 4: Delivery and verification
**Files:** README.md, docs/crawlers.md, docs/verification.md.
- [x] Tài liệu lệnh chạy, ánh xạ trường cho nhóm processing, giới hạn nguồn.
- [x] Chạy thật cấu hình mẫu Tiki (2.300/2.300 review), chạy lại để kiểm tra resume (0 trang gọi thêm).
- [ ] Chỉ tiêu chính thức (sản phẩm, số review) chờ nhóm cung cấp.
- [ ] Nhóm quyết định có rút gọn metadata sản phẩm trong `app` không (62 MB / 2.300 review; 500 dòng vượt giới hạn ô Excel).
