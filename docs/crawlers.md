# Thu thập Google Play / App Store / Tiki

Phần đầu mô tả Google Play và App Store; cấu hình, đầu ra, checkpoint và exit code
dùng chung cho Tiki. Riêng Tiki và Shopee xem [mục Tiki](#tiki) và [mục Shopee](#shopee).

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

## Tiki

```powershell
Copy-Item config/crawl_jobs.tiki.example.json config/crawl_jobs.tiki.json
.\.venv\Scripts\python.exe -m src.ingestion.collect --config config/crawl_jobs.tiki.json --output-dir data/raw/ecommerce_reviews
```

Cùng lệnh `src.ingestion.collect`, nên `delay`, `attempts`, `timeout`,
`max_batches`, `--restart-cursors`, `--export-only`, `report.json` và exit code
giống hệt các mục trên.

```json
{"source": "tiki", "app_id": "52789367", "country": "vn", "limit": 1000}
```

- `app_id`: **ID sản phẩm dạng số**, phần sau `-p` trong URL. Ví dụ
  `https://tiki.vn/sach-nha-gia-kim-p52789367.html?spid=52789368` → `"52789367"`
  (không dùng `spid`).
- `country` chỉ nhận `"vn"` (mặc định khi bỏ trống). Không đặt `language`.
- Job Tiki có thể nằm chung file với Google/Apple, nhưng nên dùng thư mục riêng
  `data/raw/ecommerce_reviews`. Thư mục chỉ có job Tiki sinh `tiki.json`,
  `tiki.jsonl`, `tiki.csv`, không sinh file `google_play`/`app_store`.

### Nguồn và giới hạn

- API công khai mà trang sản phẩm tiki.vn tự gọi, không cần đăng nhập:
  `GET https://tiki.vn/api/v2/products/{id}` (metadata sản phẩm) và
  `GET https://tiki.vn/api/v2/reviews?product_id={id}&page={n}&limit=20&sort=id|desc`.
- Tối đa **20 review/trang**; lớn hơn Tiki trả HTTP 400. Đọc từ mới nhất, con trỏ
  resume là số trang, dừng ở `paging.last_page`. Review mới chỉ đẩy review cũ
  xuống trang sau, nên chạy tiếp chỉ đọc lại vài review (bỏ qua theo ID), không
  bỏ sót. Job đã `source_exhausted` sẽ không tự lấy review mới; dùng
  `--restart-cursors`.
- **Đa số review Tiki chỉ chấm sao, không có nội dung**: `content` rỗng còn
  `title` là câu mẫu theo số sao ("Cực kì hài lòng"). `limit` đếm cả review rỗng
  vì ingestion không lọc; nhóm processing lọc theo `word_count`. Bộ mẫu 2.300
  review chỉ có 29% kèm nội dung (24–40% tùy sản phẩm, xem
  [verification.md](verification.md)). Cần N review có chữ thì đặt `limit`
  khoảng 3–4 lần N.
- `paging.total` của API review có thể lớn hơn `review_count` hiển thị trên sản
  phẩm (Nhà Giả Kim: 7.205 so với 6.092), vì có thể gồm review của nhà bán khác.
- Metadata sản phẩm (15–35 nghìn ký tự: mô tả HTML, ảnh, nhà bán khác, biến
  thể...) lặp lại trong mỗi review, giống cách Google/Apple lưu `app`, nên file
  lớn: bộ mẫu 2.300 review khoảng 62 MB mỗi định dạng. Sản phẩm có metadata trên
  32.767 ký tự vượt giới hạn một ô Excel, nên cột `app_json` sẽ bị cắt hoặc làm
  lệch dòng khi mở CSV bằng Excel. Dữ liệu trong file vẫn đầy đủ; đọc bằng
  Python/pandas hoặc dùng file JSON/JSONL.

### Ánh xạ trường cho nhóm processing

Envelope giống Google/Apple. Khóa `app` chứa metadata **sản phẩm**, `language`
là null, `item_id` là ID sản phẩm.

| Trường | Tiki |
| --- | --- |
| ID review | `review.id` |
| Tên sản phẩm | `app.name` |
| Thương hiệu | `app.brand.name` (sách thường null; xem `app.authors`) |
| Nhà bán | `review.seller.name` |
| Ngành hàng | `app.categories.name` |
| Người đánh giá | `review.created_by.name` |
| Điểm sao | `review.rating` |
| Nội dung | `review.content` (có thể rỗng) |
| Ngày review | `review.created_at` (Unix giây, UTC) |
| Lượt hữu ích | `review.thank_count` |

Cột `review_time` trong CSV hiển thị `created_at` dạng ISO 8601 UTC, ví dụ
`2026-10-21T08:09:57+00:00` (15:09:57 giờ Việt Nam). Giá trị số gốc vẫn nằm
trong `review_json` và file JSON.

## Shopee

**Chưa thu thập được (kiểm tra ngày 2026-11-04).** Mọi endpoint công khai đã thử
(`/api/v2/item/get_ratings`, `/api/v4/item/get_ratings`, `/api/v4/search/search_items`,
`/api/v4/pdp/get_pc`) đều trả HTTP 403 với `{"error": 90309999, "is_login": false}`.
Shopee yêu cầu phiên đăng nhập kèm chữ ký request do JavaScript của họ sinh ra
(cơ chế anti-bot). Dự án không giả lập chữ ký hay né phát hiện bot: việc này vi
phạm điều khoản của Shopee và hỏng ngay khi họ đổi thuật toán.

Các phương án đang chờ nhóm chọn:

1. **Bỏ Shopee**, dùng Tiki cho mảng thương mại điện tử. Một sản phẩm phổ biến
   trên Tiki đã có hàng nghìn review.
2. **Dùng bộ dữ liệu review Shopee công khai** (Kaggle, Hugging Face...) có giấy
   phép cho nghiên cứu, viết bộ import về cùng envelope với
   `source_domain = "shopee"`.
3. **Thu thập thủ công lượng nhỏ**: mở trang sản phẩm bằng trình duyệt, lưu phản
   hồi `get_ratings` từ DevTools → Network thành file JSON, rồi viết bộ import
   offline. Tốn công, chỉ hợp với vài trăm review.

`collect.py` hiện từ chối job `"source": "shopee"` ngay khi đọc cấu hình.

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
