# Hướng dẫn Crawl Dữ liệu & Nạp vào MongoDB

Tài liệu này hướng dẫn cách thu thập đánh giá từ **Tiki**, **Google Play** và **App Store**, sau đó nạp vào **MongoDB** (Atlas hoặc Docker local) và tự động chạy phân tích cảm xúc NLP.

---

## 1. Cài đặt môi trường (PowerShell — làm 1 lần đầu)

Yêu cầu **Python 3.10**.

```powershell
# 1. Tạo môi trường ảo
python -m venv .venv

# 2. Cài thư viện cần thiết (crawler + MongoDB + NLP + giao diện Streamlit)
.\.venv\Scripts\python.exe -m pip install "pymongo[srv]==4.6.3" python-dotenv==1.0.1 requests==2.31.0 google-play-scraper==1.2.4 numpy==1.26.4 pandas==2.2.1 scikit-learn==1.4.1.post1 pyvi==0.1.1 joblib==1.4.2 streamlit==1.32.2 plotly==5.20.0

# 3. Tạo file .env từ mẫu và điền chuỗi kết nối MongoDB
Copy-Item .env.example .env
```

Mở file `.env` và điền 2 dòng (nếu dùng MongoDB Atlas):
```env
MONGO_URI=mongodb+srv://<username>:<password>@<cluster>.mongodb.net/?retryWrites=true&w=majority
MONGO_DATABASE=sentiment
```

Khởi tạo cấu trúc database (collections, index, validator) — chỉ cần chạy 1 lần đầu:
```powershell
.\.venv\Scripts\python.exe init_mongo.py
```

---

## 2. Cách 1 — Crawl qua Giao diện Web Streamlit (Khuyên dùng)

Khởi chạy giao diện:
```powershell
.\.venv\Scripts\streamlit.exe run src/ui/app.py
```
Trình duyệt sẽ mở tại `http://localhost:8501`.

### Các bước crawl tại Tab 1 (`🚀 Thu thập & Nạp CSDL`)
1. **Chọn nền tảng**: `Tiki`, `Google Play` hoặc `App Store`.
2. **Dán URL sản phẩm / ứng dụng** (hoặc nhập trực tiếp ID):
   - **Tiki**: `https://tiki.vn/sach-nha-gia-kim-p52789367.html` (hoặc `52789367`)
   - **Google Play**: `https://play.google.com/store/apps/details?id=com.facebook.katana&hl=vi&gl=VN` (hoặc `com.facebook.katana`)
   - **App Store**: `https://apps.apple.com/vn/app/facebook/id284882215` (hoặc `284882215`)
3. **Chọn chế độ tải**:
   - Nhập số lượng review tối đa, **hoặc** tick **♾️ Tải toàn bộ đánh giá (nạp cuốn chiếu từng lô)** để tải không giới hạn (mặc định 200 review/lô, tự dừng nếu CSDL gần đầy ngưỡng an toàn).
   - Nên để **Độ trễ (`delay`)** từ `0.5` đến `1.0` giây để tránh bị chặn IP.
   - Bật **Tự động chạy NLP** để dữ liệu tự đi thẳng qua `raw_reviews` → `reviews` (`Positive` / `Neutral` / `Negative`) → `daily_metrics`.
4. Bấm **🚀 Bắt đầu Crawl & Nạp cuốn chiếu vào CSDL**.

### Xem thống kê dữ liệu tại Tab 2 (`🗄️ Khám phá & Thống kê CSDL`)
- Xem tổng số bản ghi, dung lượng CSDL đã dùng & còn lại, biểu đồ phân bố cảm xúc, danh sách sản phẩm (`entities`) và lịch sử đợt chạy (`pipeline_runs`).
- Bấm nút **📦 Tính số bản ghi & dung lượng theo nền tảng** để xem chi tiết số lượng và dung lượng (MB) đã crawl của từng nền tảng.

---

## 3. Cách 2 — Crawl hàng loạt bằng Dòng lệnh (CLI)

Phù hợp khi muốn cào nhiều sản phẩm theo danh sách file cấu hình, có **checkpoint SQLite** để chạy tiếp khi rớt mạng và xuất file **JSON + JSONL + CSV** cục bộ:

```powershell
# Google Play & App Store (sửa danh sách app và limit trong config/crawl_jobs.json)
Copy-Item config/crawl_jobs.example.json config/crawl_jobs.json
.\.venv\Scripts\python.exe -m src.ingestion.collect --config config/crawl_jobs.json --output-dir data/raw/mobile_reviews

# Tiki (sửa danh sách sản phẩm trong config/crawl_jobs.tiki.json)
Copy-Item config/crawl_jobs.tiki.example.json config/crawl_jobs.tiki.json
.\.venv\Scripts\python.exe -m src.ingestion.collect --config config/crawl_jobs.tiki.json --output-dir data/raw/ecommerce_reviews

# Nạp các file .jsonl đã cào vào MongoDB
.\.venv\Scripts\python.exe -m src.ingestion.import_to_mongo --input-dir data/raw/mobile_reviews --sources google_play app_store
.\.venv\Scripts\python.exe -m src.ingestion.import_to_mongo --input-dir data/raw/ecommerce_reviews --sources tiki
```

---

## 4. Lưu ý & Giới hạn từng nền tảng

- **Tiki**: Hỗ trợ tải hết đến trang cuối (20 bình luận/trang).
- **Google Play**: Không giới hạn cứng; với app lớn nên đặt mức hợp lý (`1.000 – 3.000` review/app) để cân bằng dữ liệu và không chiếm hết hạn mức 512 MB của Atlas miễn phí.
- **App Store**: Apple RSS công khai giới hạn tối đa **~500 review / ứng dụng**.
- **Shopee**: Chưa hỗ trợ do bị chặn anti-bot (HTTP 403), xem chi tiết tại [docs/crawlers.md](docs/crawlers.md).
- **Chống trùng lặp tự động**: Có thể crawl lại cùng một URL bất kỳ lúc nào — hệ thống tự bỏ qua bình luận đã có và chỉ nạp bình luận mới.

---

## 5. Chạy kiểm thử nhanh (không gọi API thật)

```powershell
.\.venv\Scripts\python.exe -m unittest tests/test_mongo.py tests/test_url_pipeline.py tests/test_tiki.py tests/test_collection.py -v
```
