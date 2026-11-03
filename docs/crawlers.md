# Thu thập Google Play / App Store

## Chạy local, xuất JSON và CSV

Chạy tại gốc bằng Python 3.10.11. Không cần Kafka, Docker, Java hoặc Spark.
Workspace đã có `.venv`. Máy khác cần tạo venv và cài `requirements-crawler.txt`.

```powershell
# File mẫu; sửa app_id và limit theo chỉ tiêu của nhóm
Copy-Item config/crawl_jobs.example.json config/crawl_jobs.json
.\.venv\Scripts\python.exe -m src.ingestion.collect --config config/crawl_jobs.json --output-dir data/raw/mobile_reviews

# Chạy tiếp: dùng lại chính lệnh và thư mục ở trên
# Chỉ xuất lại file, không gọi mạng:
.\.venv\Scripts\python.exe -m src.ingestion.collect --config config/crawl_jobs.json --output-dir data/raw/mobile_reviews --export-only

# Token cũ hết hạn / quét lại để bù số review còn thiếu:
.\.venv\Scripts\python.exe -m src.ingestion.collect --config config/crawl_jobs.json --output-dir data/raw/mobile_reviews --restart-cursors
```

README gốc **không ghi danh sách ứng dụng, số review hay khoảng thời gian bắt
buộc**. Cấu hình mẫu dùng Facebook/Instagram tại Việt Nam: 1.000 review/ứng dụng
trên Google và 500/ứng dụng trên Apple, tổng mục tiêu mẫu 3.000. Đây không phải
chỉ tiêu của đề. Cần thay bằng yêu cầu thực khi nhóm cung cấp. Không tự thêm ứng
dụng hoặc chuyển quốc gia để bù số lượng.

## Cấu hình

```json
{
  "delay": 1.0,
  "attempts": 3,
  "timeout": 45,
  "max_batches": 1000,
  "jobs": [
    {"source": "google_play", "app_id": "com.facebook.katana", "country": "vn", "language": "vi", "limit": 1000},
    {"source": "app_store", "app_id": "284882215", "country": "vn", "limit": 500}
  ]
}
```

- `limit`: mục tiêu số review **có ID phân biệt cho từng job**, bắt buộc ghi rõ.
- Job nhận diện bằng source + app_id + country + language. Apple không hỗ trợ
  lọc language; không đặt trường này cho Apple.
- `delay`: thời gian chờ giữa trang, tối thiểu 0,5 giây; mặc định 1 giây.
- `attempts`: tổng số lần gọi khi lỗi mạng/timeout/HTTP 408, 429, 5xx. Backoff
  1, 2, 4... giây; lỗi HTTP khác không thử lại.
- `timeout`: Google chạy mỗi lời gọi trong process riêng và dừng khi quá hạn;
  Apple dùng timeout connect/read của requests.
- `max_batches`: tối đa số trang/job/lần chạy, mặc định 1.000. Nếu chạm giới hạn
  khi chưa đủ thì báo `page_budget_reached`; chạy lại để tiếp tục.

## Đầu ra

```text
data/raw/mobile_reviews/
├── checkpoint.sqlite3       # Journal và vị trí đọc; giữ lại để resume
├── google_play.json         # Mảng JSON hợp lệ
├── google_play.jsonl        # Mỗi dòng một JSON
├── google_play.csv          # UTF-8 BOM, mở được bằng Excel
├── app_store.json
├── app_store.jsonl
├── app_store.csv
└── report.json              # Số lượng, thiếu hụt, trạng thái, lỗi, thời gian
```

Chỉ chạy một collector trên cùng thư mục. Trong lúc chạy có thể xuất hiện file
SQLite `-wal`, `-shm`; không xóa chúng. Dữ liệu được Git ignore.

CSV có các cột `source_domain`, `item_id`, `country`, `language`, `collected_at`,
`review_id`, `review_text`, `rating`, `review_time`, `app_json`, `review_json`.
Hai cột JSON giữ **toàn bộ trường gốc**, kể cả nested fields, null, emoji, dấu
phẩy và xuống dòng. Đọc lại bằng `json.loads`. Cột hiển thị có ký tự đầu dạng
công thức spreadsheet được thêm dấu nháy đơn; giá trị gốc vẫn nguyên trong
`review_json` và file JSON. Đây là biểu diễn khi xuất, không phải làm sạch NLP.

Các file gộp theo nguồn, chỉ chứa job thuộc config hiện tại. Journal có thể giữ
job cũ không còn trong config. Export được tạo lại thay vì nối dòng mỗi lần chạy.

## Checkpoint và giới hạn nguồn

Review của một trang và con trỏ tiếp theo được lưu **cùng một transaction**.
Lỗi giữa lúc lưu sẽ rollback trang đó; chạy lại sẽ lấy lại trang. Trang đã
commit còn nguyên sau khi chương trình dừng. Ctrl+C cố xuất dữ liệu đã commit.

Đạt limit giữa trang thì phần chưa dùng được giữ trong checkpoint. Tăng limit
sẽ dùng tiếp phần đó rồi đọc thêm trang. Job đã đủ limit không gọi mạng. Giảm
limit không xóa review đã lưu; muốn bộ dữ liệu nhỏ hơn hoặc một đợt độc lập,
dùng thư mục output mới.

Tránh ghi lại cùng ID phục vụ resume/giao nhận; không xóa trùng theo nội dung,
không sửa review. Nếu thiếu ID, dùng hash raw review cho bookkeeping. Giữ bản
review đầu tiên đã lưu, không tự cập nhật các bản sửa đổi về sau.

`--restart-cursors` giữ review đã lưu, quét lại từ đầu cho job còn thiếu và bỏ
qua ID đã có. Token Google có thể hết hạn; trang Apple có thể dịch khi có review
mới. Resume không bảo đảm snapshot đầy đủ lịch sử.

Google đọc NEWEST, tối đa 199 review/batch. Apple đọc tối đa 10 trang RSS, kể cả
sau trang rỗng. Nếu không đủ thì ghi thiếu hụt, không nhân bản review để bù.
Thư viện Google 1.2.4 có thể chuyển một số lỗi parse thành kết quả rỗng.
`source_exhausted` chỉ có nghĩa adapter dừng do phản hồi nguồn/giới hạn RSS,
không khẳng định không còn review khác. Không cam kết toàn bộ lịch sử. Storefront
VN hay language vi không bảo đảm mọi nội dung đều là tiếng Việt.

## Báo cáo

Mỗi job có `existing`, `added`, `collected`, `limit`, `shortfall`, `pages_fetched`,
thời điểm bắt đầu/kết thúc, thời gian chạy, `status`, `error`.
`all_targets_met=true` chỉ khi tất cả job đạt mục tiêu và không lỗi.

| Exit code | Ý nghĩa |
| --- | --- |
| 0 | Đạt tất cả mục tiêu hoặc export-only thành công |
| 1 | Có lỗi; các ứng dụng khác vẫn được thử |
| 2 | Config/tham số sai |
| 3 | Thiếu dữ liệu hoặc chạm giới hạn số trang |
| 130 | Người dùng ngắt |

Report cập nhật sau từng job. Tắt cưỡng bức có thể khiến report chậm hơn journal;
chạy lại để cập nhật. Nếu ngắt trong lúc export, các file có thể khác thế hệ;
`--export-only` sẽ tạo lại từ journal. Đóng CSV trong Excel trước khi xuất lại
nếu Windows báo file đang bị khóa.

## Hợp đồng dữ liệu với nhóm processing

Envelope gồm `source_domain`, `item_id`, `country`, `language`, `collected_at`,
`app`, `review`. `collected_at` là thời điểm thu thập UTC, không phải ngày review.
Apple có language null. `app`/`review` giữ dict trả về từ nguồn/thư viện; datetime
Google encode ISO 8601, không tự thêm timezone. Google raw ở giao diện thư viện,
không phải toàn bộ phản hồi HTTP nguyên bản.

| Trường | Google | Apple |
| --- | --- | --- |
| ID review | `review.reviewId` | `review.id.label` |
| Tên ứng dụng | `app.title` | `app.trackName` |
| Nhà phát triển | `app.developer` | `app.artistName` |
| Thể loại | `app.genre` | `app.primaryGenreName` |
| Người đánh giá | `review.userName` | `review.author.name.label` |
| Điểm sao | `review.score` | `review.im:rating.label` |
| Nội dung | `review.content` | `review.content.label` |
| Ngày review | `review.at` | `review.updated.label` nếu có |
| Lượt hữu ích | `review.thumbsUpCount` | `review.im:voteSum.label` nếu có |

Unified Schema, làm sạch, xóa trùng nội dung, NLP thuộc processing. Trường nguồn
không trả phải để thiếu/null, không điền dữ liệu giả. Kafka để giai đoạn sau.

## CLI cũ và kiểm thử

`python -m src.ingestion ...` vẫn giữ hành vi cũ: nối JSONL, không resume và có
tùy chọn Kafka. Muốn JSON + CSV + checkpoint, dùng **`src.ingestion.collect`**.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q config src tests
.\.venv\Scripts\python.exe -m src.ingestion.collect --help
```

Nguồn: [google-play-scraper](https://github.com/JoMingyu/google-play-scraper),
[Apple Lookup](https://developer.apple.com/library/archive/documentation/AudioVideo/Conceptual/iTuneSearchAPI/LookupExamples.html),
[Apple RSS](https://itunes.apple.com/vn/rss/customerreviews/page=1/id=284882215/sortby=mostrecent/json).
