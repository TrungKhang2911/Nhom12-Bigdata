"""Streamlit dashboard for review collection, rating analytics, and NLP sentiment analysis."""

from __future__ import annotations

from collections import Counter
import base64
import html
import json
from pathlib import Path
import re
import sys
from urllib.parse import parse_qs, urlparse

import pandas as pd
import plotly.express as px
import streamlit as st

_CURRENT_DIR = Path(__file__).resolve().parent
_ROOT_DIR = _CURRENT_DIR.parents[1] if len(_CURRENT_DIR.parents) >= 2 else _CURRENT_DIR
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

from src.processing.nlp_pipeline import NLP_PIPELINE_VERSION, SentimentNLPPipeline
from src.processing.purchase_advisor import build_purchase_advice

PLATFORMS = ("Tiki", "Google Play", "App Store")
PLATFORM_HOSTS = {
    "Tiki": ("tiki.vn",),
    "Google Play": ("play.google.com",),
    "App Store": ("apps.apple.com", "itunes.apple.com"),
}
PLATFORM_TO_SOURCE_DOMAIN = {
    "Tiki": "tiki",
    "Google Play": "google_play",
    "App Store": "app_store",
}
SOURCE_DOMAIN_TO_PLATFORM = {
    "tiki": "Tiki",
    "google_play": "Google Play",
    "app_store": "App Store",
}
DISPLAY_COLUMNS = ("Tên người dùng", "Đánh giá (sao)", "Nội dung comment")
REVIEW_TIME_COLUMN = "Thời gian đánh giá"
RATING_COLORS = {
    "1 sao": "#e26962",
    "2 sao": "#db8a56",
    "3 sao": "#d89b35",
    "4 sao": "#5b83b4",
    "5 sao": "#0d9488",
}
SENTIMENT_COLORS = {
    "Positive": "#0d9488",
    "Neutral": "#d89b35",
    "Negative": "#e26962",
}
QUALITY_STATUS_VI_LABELS = {
    "VALID_TEXT": "Hợp lệ (VALID_TEXT)",
    "VALID_PRE_CONSUMPTION": "Chưa sử dụng (VALID_PRE_CONSUMPTION)",
    "EMOJI_ONLY": "Chỉ ký hiệu cảm xúc (EMOJI_ONLY)",
    "EMPTY_COMMENT": "Bình luận trống (EMPTY_COMMENT)",
    "FILTERED_MEANINGLESS": "Lọc: Ký tự rời rạc (FILTERED_MEANINGLESS)",
    "FILTERED_SPAM_OR_GIBBERISH": "Lọc: Spam / Vô nghĩa (FILTERED_SPAM_OR_GIBBERISH)",
    "FILTERED_OFF_TOPIC": "Lọc: Lệch danh mục (FILTERED_OFF_TOPIC)",
}
RAW_DATASET_FILES = {
    "Tiki": _ROOT_DIR / "data" / "raw" / "ecommerce_reviews" / "tiki.csv",
    "Google Play": _ROOT_DIR / "data" / "raw" / "mobile_reviews" / "google_play.csv",
    "App Store": _ROOT_DIR / "data" / "raw" / "mobile_reviews" / "app_store.csv",
}
STOPWORDS_FOR_CHART = {
    "và", "là", "của", "có", "được", "cho", "trong", "đã", "này", "đó", "với", "những",
    "các", "một", "như", "thì", "mà", "ở", "về", "khi", "ra", "lên", "xuống", "vào",
    "từ", "đến", "nên", "vì", "do", "bị", "rất", "quá", "lắm", "hơi", "cũng", "vẫn",
    "đang", "sẽ", "mới", "nữa", "thêm", "lại", "đi", "mình", "tôi", "em", "anh", "chị",
    "shop", "bạn", "người", "nó", "cái", "chiếc", "cuốn", "quyển", "bình", "app", "sách",
    "gì", "sao", "thế", "vậy", "đây", "ấy", "ai", "nào", "cứ", "chỉ", "còn", "nhưng",
    "tuy_nhiên", "lần", "ngày", "lúc", "sau", "trước", "hơn", "nhiều", "ít", "cả", "mọi",
}

TEST_PRESETS = {
    "Tự nhập nội dung": (
        "Sách đóng gói cẩn thận, không bị móp méo nhưng giao hàng hơi lâu",
        4,
    ),
    "Mẫu 1 — Phủ định khuyết điểm (Positive)": (
        "Giao đúng hẹn, sách đóng gói kĩ, không bị móp méo hay rách bìa, rất đáng tiền.",
        5,
    ),
    "Mẫu 2 — Mâu thuẫn điểm sao & nội dung (Negative)": (
        "Bình giữ nhiệt bị rỉ nước ở phần nắp, không kín, thất vọng.",
        3,
    ),
    "Mẫu 3 — Mệnh đề chuyển ý giảm nhẹ (Neutral)": (
        "Sách đẹp, giấy tốt nhưng không có bọc seal nên bìa hơi bụi.",
        5,
    ),
    "Mẫu 4 — Đánh giá trước khi sử dụng (Neutral)": (
        "Mua để tặng nên chưa đọc thử, đóng gói ổn.",
        4,
    ),
    "Mẫu 5 — Văn bản nhiễu / vô nghĩa (Filtered)": (
        "asdfghjkl qwertyuiop Good luck and the Chainsmokers là những điều",
        5,
    ),
}


def inject_custom_css():
    """Load the local dashboard design system."""
    css = (_CURRENT_DIR / "styles.css").read_text(encoding="utf-8")
    font_dir = _CURRENT_DIR / "assets" / "fonts"
    faces = []
    ranges = {
        "latin": "U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD",
        "vietnamese": "U+0102-0103,U+0110-0111,U+0128-0129,U+0168-0169,U+01A0-01A1,U+01AF-01B0,U+0300-0301,U+0303-0304,U+0308-0309,U+0323,U+0329,U+1EA0-1EF9,U+20AB",
    }
    for weight in (400, 600, 700):
        for subset, unicode_range in ranges.items():
            font = font_dir / f"be-vietnam-pro-{subset}-{weight}-normal.woff2"
            if font.exists():
                encoded = base64.b64encode(font.read_bytes()).decode("ascii")
                faces.append("@font-face {font-family:'Be Vietnam Pro';font-style:normal;font-display:swap;"
                             f"font-weight:{weight};src:url(data:font/woff2;base64,{encoded}) format('woff2');"
                             f"unicode-range:{unicode_range};" + "}")
    st.markdown("<style>" + "".join(faces) + css + "</style>", unsafe_allow_html=True)


def _style_figure(fig, height: int = 360):
    """Use a consistent, readable presentation for every analytics chart."""
    fig.update_layout(
        template="plotly_white",
        height=height,
        margin=dict(l=24, r=24, t=76, b=64),
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        font=dict(family="Be Vietnam Pro, Segoe UI, sans-serif", size=14, color="#292018"),
        title=dict(font=dict(size=16, color="#1f1913"), x=0.02, xanchor="left"),
        hoverlabel=dict(bgcolor="#2b1f14", font_size=13, font_color="#ffffff"),
        legend=dict(title_text="", orientation="h", yanchor="top", y=-0.18,
                    xanchor="center", x=0.5, font=dict(size=13, color="#292018")),
        colorway=["#0d9488", "#e5a33d", "#e26962", "#5b83b4", "#8c7ab8"],
        modebar=dict(bgcolor="rgba(255,255,255,0)", color="#94a3b8", activecolor="#a8641f"),
    )
    axis_text = dict(
        tickfont=dict(size=13, color="#292018"),
        title_font=dict(size=14, color="#1f1913"),
    )
    fig.update_xaxes(showgrid=False, zeroline=False, automargin=True,
                     title_standoff=16, **axis_text)
    fig.update_yaxes(showgrid=True, gridcolor="#f0e9df", zeroline=False,
                     automargin=True, title_standoff=16, **axis_text)
    # Explicit dark labels remain readable against the chart's medium-light fills.
    for trace_type in ("bar", "pie"):
        fig.update_traces(
            textfont=dict(size=14, color="#111111"),
            insidetextfont=dict(size=14, color="#111111"),
            outsidetextfont=dict(size=14, color="#292018"),
            selector=dict(type=trace_type),
        )
    fig.update_annotations(font=dict(size=14, color="#292018"))
    return fig


@st.cache_resource(show_spinner=False)
def get_nlp_pipeline(nlp_revision: str = NLP_PIPELINE_VERSION) -> SentimentNLPPipeline:
    """Initialize and cache the multi-domain SVM NLP pipeline."""
    return SentimentNLPPipeline()


def extract_item_id(platform: str, url: str) -> str:
    """Validate a platform URL and return the crawler-specific product/app ID."""
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Vui lòng nhập URL đầy đủ, bắt đầu bằng http:// hoặc https://.")

    hostname = parsed.hostname.lower()
    if not any(hostname == host or hostname.endswith(f".{host}") for host in PLATFORM_HOSTS[platform]):
        raise ValueError(f"URL không thuộc nền tảng {platform}.")

    if platform == "Tiki":
        match = re.search(r"-p(\d+)(?:\.html)?(?:$|[?#])", parsed.path, re.IGNORECASE)
        if not match:
            match = re.search(r"/product/(\d+)(?:/|$)", parsed.path, re.IGNORECASE)
        if match:
            return match.group(1)
        raise ValueError("Không tìm thấy mã sản phẩm trong URL Tiki (ví dụ: ...-p123456.html).")

    if platform == "Google Play":
        app_ids = parse_qs(parsed.query).get("id", [])
        if app_ids and re.fullmatch(r"[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+", app_ids[0]):
            return app_ids[0]
        raise ValueError("URL Google Play cần có mã ứng dụng hợp lệ trong tham số ?id=.")

    match = re.search(r"/id(\d+)(?:$|[/?])", parsed.path)
    if match:
        return match.group(1)
    raise ValueError("Không tìm thấy mã ứng dụng dạng id123456 trong URL App Store.")


def _value(value):
    """Unwrap Apple RSS label fields and return a display-safe string."""
    if isinstance(value, dict):
        return value.get("label", "")
    return value if value is not None else ""


def _review_datetime(value):
    """Convert crawler timestamps into UTC datetimes for timeline grouping."""
    value = _value(value)
    if value is None or value == "":
        return pd.NaT
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return pd.to_datetime(value, unit="s", utc=True, errors="coerce")
    return pd.to_datetime(value, utc=True, errors="coerce")


def _review_row(event: dict, platform: str) -> dict:
    review = event.get("review") or {}
    app_info = event.get("app") or {}
    if platform == "Google Play":
        username = review.get("userName") or review.get("user_name") or "Ẩn danh"
        rating = review.get("score")
        text = review.get("content")
        review_time = review.get("at") or review.get("reviewTime")
    elif platform == "App Store":
        author = review.get("author") or {}
        username = _value(author.get("name")) or "Ẩn danh"
        rating = _value(review.get("im:rating"))
        text = _value(review.get("content"))
        review_time = review.get("updated")
    else:
        author = review.get("created_by") or {}
        username = author.get("name") or review.get("customer_name") or "Ẩn danh"
        rating = review.get("rating")
        text = review.get("content")
        review_time = review.get("created_at")

    try:
        rating = int(float(rating))
    except (TypeError, ValueError):
        rating = None
    return {
        DISPLAY_COLUMNS[0]: username,
        DISPLAY_COLUMNS[1]: rating,
        DISPLAY_COLUMNS[2]: text or "",
        REVIEW_TIME_COLUMN: _review_datetime(review_time),
        "source_domain": PLATFORM_TO_SOURCE_DOMAIN.get(platform, "tiki"),
        "app_json": json.dumps(app_info, ensure_ascii=False) if isinstance(app_info, dict) and app_info else None,
    }


def _daily_rating_percentages(frame: pd.DataFrame) -> pd.DataFrame:
    """Return cumulative rating percentages through each day."""
    dated = frame.dropna(subset=[REVIEW_TIME_COLUMN]).copy()
    if dated.empty:
        return pd.DataFrame(columns=["Ngày", "Mức đánh giá", "Tỷ lệ (%)"])

    dated["Ngày"] = dated[REVIEW_TIME_COLUMN].dt.floor("D")
    daily_counts = (
        dated.groupby(["Ngày", DISPLAY_COLUMNS[1]])
        .size()
        .unstack(fill_value=0)
        .reindex(columns=range(1, 6), fill_value=0)
        .sort_index()
    )
    cumulative_counts = daily_counts.cumsum()
    cumulative_percentages = cumulative_counts.div(
        cumulative_counts.sum(axis=1), axis=0
    ).mul(100)
    return (
        cumulative_percentages.rename(
            columns={rating: f"{rating} sao" for rating in range(1, 6)}
        )
        .reset_index()
        .melt(id_vars="Ngày", var_name="Mức đánh giá", value_name="Tỷ lệ (%)")
    )


def _daily_sentiment_percentages(frame: pd.DataFrame) -> pd.DataFrame:
    """Return cumulative sentiment percentages (Positive, Neutral, Negative) through each day."""
    if "sentiment_label" not in frame.columns:
        return pd.DataFrame(columns=["Ngày", "Nhãn cảm xúc", "Tỷ lệ (%)"])

    dated = frame.dropna(subset=[REVIEW_TIME_COLUMN, "sentiment_label"]).copy()
    if dated.empty:
        return pd.DataFrame(columns=["Ngày", "Nhãn cảm xúc", "Tỷ lệ (%)"])

    dated["Ngày"] = dated[REVIEW_TIME_COLUMN].dt.floor("D")
    labels = ["Positive", "Neutral", "Negative"]
    daily_counts = (
        dated.groupby(["Ngày", "sentiment_label"])
        .size()
        .unstack(fill_value=0)
        .reindex(columns=labels, fill_value=0)
        .sort_index()
    )
    cumulative_counts = daily_counts.cumsum()
    totals = cumulative_counts.sum(axis=1).replace(0, pd.NA)
    cumulative_percentages = cumulative_counts.div(totals, axis=0).mul(100).fillna(0.0)
    return (
        cumulative_percentages.reset_index()
        .melt(id_vars="Ngày", var_name="Nhãn cảm xúc", value_name="Tỷ lệ (%)")
    )


def enrich_with_nlp(frame: pd.DataFrame, platform: str | None = None) -> pd.DataFrame:
    """Run the NLP sentiment pipeline on a review DataFrame."""
    if frame.empty:
        return frame.copy()

    df = frame.copy()
    if "source_domain" not in df.columns:
        df["source_domain"] = PLATFORM_TO_SOURCE_DOMAIN.get(platform or "", "tiki")
    if "app_json" not in df.columns:
        df["app_json"] = None

    pipeline = get_nlp_pipeline()
    processed = pipeline.process_dataframe(
        df,
        text_col=DISPLAY_COLUMNS[2],
        rating_col=DISPLAY_COLUMNS[1],
    )
    processed["Aspects hiển thị"] = processed["aspects"].apply(_format_aspects_readable)
    processed["Trạng thái hiển thị"] = processed["quality_status"].map(
        lambda s: QUALITY_STATUS_VI_LABELS.get(str(s), str(s))
    )
    return processed


def _format_aspects_readable(aspects_json: str) -> str:
    """Format JSON aspects into a clean text summary without colorful emojis."""
    if not aspects_json or not isinstance(aspects_json, str):
        return ""
    try:
        items = json.loads(aspects_json)
        if not isinstance(items, list) or not items:
            return ""
        parts = []
        for it in items:
            if isinstance(it, dict):
                asp = it.get("aspect", "")
                sent = str(it.get("sentiment", "")).upper()
                parts.append(f"{asp}: {sent}")
        return " | ".join(parts)
    except Exception:
        return aspects_json


def _extract_item_name(app_json_val) -> str:
    if not isinstance(app_json_val, str) or not app_json_val.strip():
        return "Không rõ tên"
    try:
        obj = json.loads(app_json_val)
        if isinstance(obj, dict):
            return str(obj.get("name") or obj.get("title") or obj.get("trackName") or "Không rõ tên")
    except Exception:
        pass
    return "Không rõ tên"


@st.cache_data(show_spinner=False)
def load_local_raw_reviews(selected_platform: str = "Tất cả nguồn", nlp_revision: str = NLP_PIPELINE_VERSION) -> pd.DataFrame:
    """Load pre-crawled datasets from data/raw/ and enrich with NLP outputs."""
    frames = []
    targets = (
        RAW_DATASET_FILES.items()
        if selected_platform == "Tất cả nguồn"
        else [(selected_platform, RAW_DATASET_FILES[selected_platform])]
    )
    for plat_name, csv_path in targets:
        if not csv_path.exists():
            continue
        raw_df = pd.read_csv(csv_path)
        item_names = (
            raw_df["app_json"].apply(_extract_item_name)
            if "app_json" in raw_df.columns
            else pd.Series(["Không rõ tên"] * len(raw_df))
        )
        norm_df = pd.DataFrame({
            "Nền tảng": plat_name,
            "Mã SP/App": raw_df["item_id"].astype(str) if "item_id" in raw_df.columns else "",
            "Tên SP/App": item_names,
            DISPLAY_COLUMNS[0]: raw_df["username"].fillna("Ẩn danh").astype(str)
            if "username" in raw_df.columns
            else "Ẩn danh",
            DISPLAY_COLUMNS[1]: pd.to_numeric(raw_df["rating"], errors="coerce")
            if "rating" in raw_df.columns
            else None,
            DISPLAY_COLUMNS[2]: raw_df["review_text"].fillna("").astype(str)
            if "review_text" in raw_df.columns
            else "",
            REVIEW_TIME_COLUMN: raw_df["review_time"].apply(_review_datetime)
            if "review_time" in raw_df.columns
            else pd.NaT,
            "source_domain": raw_df["source_domain"].fillna(PLATFORM_TO_SOURCE_DOMAIN.get(plat_name, "tiki"))
            if "source_domain" in raw_df.columns
            else PLATFORM_TO_SOURCE_DOMAIN.get(plat_name, "tiki"),
            "app_json": raw_df["app_json"] if "app_json" in raw_df.columns else None,
        })
        frames.append(norm_df)

    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True)
    return enrich_with_nlp(combined)


def crawl_reviews(platform: str, item_id: str, limit: int) -> list[dict]:
    """Call the existing crawler module and normalize its raw review envelopes."""
    if platform == "Google Play":
        from src.ingestion.gplay_crawler import crawl

        events = crawl(item_id, country="vn", language="vi", limit=limit, delay=0.5)
        return [_review_row(event, platform) for event in events]

    if platform == "App Store":
        from src.ingestion.appstore_crawler import crawl

        events = crawl(item_id, country="vn", limit=limit, delay=0.5)
        return [_review_row(event, platform) for event in events]

    from src.ingestion.tiki_crawler import pages

    job = {
        "source": "tiki",
        "app_id": item_id,
        "country": "vn",
        "language": None,
        "limit": limit,
    }
    results = []
    stream = pages(job, {}, delay=0.5, attempts=3, timeout=45.0)
    try:
        for events, _cursor, exhausted in stream:
            for event in events:
                results.append(_review_row(event, platform))
                if len(results) >= limit:
                    break
            if len(results) >= limit or exhausted:
                break
    finally:
        stream.close()
    return results


def _build_aspect_sentiment_dataframe(frame: pd.DataFrame) -> pd.DataFrame:
    """Aggregate Positive / Neutral / Negative counts per aspect."""
    if "aspects" not in frame.columns:
        return pd.DataFrame(columns=["Khía cạnh", "Cảm xúc", "Số lượng"])

    records = []
    for asp_str in frame["aspects"].dropna():
        if not isinstance(asp_str, str) or asp_str == "[]":
            continue
        try:
            items = json.loads(asp_str)
            for item in items:
                if isinstance(item, dict) and item.get("aspect") and item.get("sentiment"):
                    records.append({
                        "Khía cạnh": str(item["aspect"]).capitalize(),
                        "Cảm xúc": str(item["sentiment"]).capitalize(),
                    })
        except Exception:
            continue

    if not records:
        return pd.DataFrame(columns=["Khía cạnh", "Cảm xúc", "Số lượng"])

    asp_df = pd.DataFrame(records)
    return asp_df.groupby(["Khía cạnh", "Cảm xúc"]).size().reset_index(name="Số lượng")


def _build_top_keywords_dataframe(frame: pd.DataFrame, sentiment_label: str, top_k: int = 12) -> pd.DataFrame:
    """Extract top tokens/compounds from cleaned_text by sentiment class."""
    if "cleaned_text" not in frame.columns or "sentiment_label" not in frame.columns:
        return pd.DataFrame(columns=["Từ khóa", "Tần suất"])

    sub = frame[
        (frame["sentiment_label"] == sentiment_label)
        & (frame["quality_status"].isin(["VALID_TEXT", "VALID_PRE_CONSUMPTION", "EMOJI_ONLY"]))
    ]
    counter: Counter = Counter()
    for txt in sub["cleaned_text"].dropna().astype(str):
        normalized_txt = txt.replace("tài khỏan", "tài_khoản").replace("tài khoản", "tài_khoản")
        for token in normalized_txt.split():
            tok = token.strip().lower()
            if len(tok) < 2 or tok in STOPWORDS_FOR_CHART:
                continue
            counter[tok] += 1

    if not counter:
        return pd.DataFrame(columns=["Từ khóa", "Tần suất"])

    return pd.DataFrame(counter.most_common(top_k), columns=["Từ khóa", "Tần suất"])


NAV_ITEMS = ("Cảm xúc khách hàng", "Điểm sao đánh giá", "Tra cứu đánh giá", "Thử một bình luận")
PAGE_DESCRIPTIONS = {
    NAV_ITEMS[0]: "Hiểu khách hàng đang khen/chê và nhận gợi ý chọn sản phẩm từ các đánh giá.",
    NAV_ITEMS[1]: "Thống kê điểm 1–5 sao do người dùng chấm, kể cả đánh giá không có nội dung.",
    NAV_ITEMS[2]: "Tìm bình luận cụ thể, đọc thông tin đầy đủ và tải danh sách đã lọc.",
    NAV_ITEMS[3]: "Phân tích riêng nội dung bạn nhập. Kết quả thử không được thêm vào bộ dữ liệu.",
}
PAGE_GUIDES = {
    NAV_ITEMS[0]: ("sentiment", "DỰA TRÊN NỘI DUNG", "Khách hàng đang khen hay chê?",
                   "Dán link để phân tích đánh giá, xem điểm khen/chê và nhận gợi ý có nên cân nhắc sản phẩm.",
                   "Gợi ý chọn sản phẩm", "Cảm xúc chung", "Khía cạnh & từ khóa", "Chất lượng nội dung"),
    NAV_ITEMS[1]: ("stars", "DỰA TRÊN ĐIỂM SAO", "Khách hàng chấm bao nhiêu sao?",
                   "Điểm sao là lựa chọn của người đánh giá. Một bình luận 5 sao vẫn có thể chứa lời phàn nàn.",
                   "Điểm trung bình", "Phân bố 1–5 sao", "Xu hướng tích lũy"),
    NAV_ITEMS[2]: ("records", "ĐỌC TỪNG BẢN GHI", "Tìm đúng đánh giá bạn cần xem",
                   "Dùng bộ lọc nhanh hoặc từ khóa, chọn một bản ghi để đọc đầy đủ, rồi xuất kết quả ra CSV.",
                   "Tìm & lọc", "Đọc chi tiết", "Xuất CSV"),
    NAV_ITEMS[3]: ("lab", "THỬ NGHIỆM ĐỘC LẬP", "Một bình luận sẽ được hiểu như thế nào?",
                   "Chọn câu mẫu hoặc nhập câu của bạn, bấm Phân tích bình luận và xem kết quả bên cạnh.",
                   "Nhập nội dung", "Bấm phân tích", "Xem kết quả riêng"),
}
SENTIMENT_VI = {"Positive": "Tích cực", "Neutral": "Trung tính", "Negative": "Tiêu cực"}
QUICK_FILTERS = ("Tất cả", "1–2 sao", "Nội dung tiêu cực", "3–5 sao nhưng nội dung chê")


def navigate_to(page, quick_filter=None):
    st.session_state["dashboard_page"] = page
    if quick_filter is not None:
        st.session_state["review_quick_filter"] = quick_filter


def show_source_controls():
    st.session_state["show_source_controls"] = not st.session_state.get("show_source_controls", False)


def render_sidebar():
    legacy = dict(zip(("Tổng quan", "Thống kê rating", "Khám phá dữ liệu", "Thử phân tích"), NAV_ITEMS))
    current = st.session_state.get("dashboard_page")
    if current in legacy:
        st.session_state["dashboard_page"] = legacy[current]
    with st.sidebar:
        st.markdown(
            '<div class="brand"><div class="brand-mark"><i></i><i></i><i></i></div>'
            '<div><strong>ReviewLens</strong><span>PHÂN TÍCH ĐÁNH GIÁ</span></div></div>'
            '<div class="workspace-tag">NHÓM 12 <span>BIG DATA</span></div>'
            '<div class="nav-caption">BẠN MUỐN TÌM HIỂU ĐIỀU GÌ?</div>', unsafe_allow_html=True,
        )
        page = st.radio("Chọn chức năng", NAV_ITEMS, key="dashboard_page", label_visibility="collapsed")
        st.markdown('<div class="sidebar-divider"></div><div class="nav-caption">BỘ DỮ LIỆU DÙNG CHUNG</div>', unsafe_allow_html=True)
        result = st.session_state.get("crawl_results")
        if result:
            st.write(result["platform"])
            st.caption(f"{len(result['data']):,} đánh giá đã nạp · dùng cho 3 mục đầu")
        else:
            st.caption("Chưa nạp dữ liệu. Thu thập từ Tiki, Google Play hoặc App Store để bắt đầu.")
        if page != NAV_ITEMS[3]:
            st.button("Chọn nguồn đánh giá", on_click=show_source_controls, use_container_width=True)
        with st.expander("Chọn mục nào cho đúng?"):
            st.write("**Cảm xúc:** khách hàng viết gì và đang khen hay chê.")
            st.write("**Điểm sao:** khách hàng đã chấm bao nhiêu sao.")
            st.write("**Tra cứu:** tìm và đọc từng bình luận cụ thể.")
            st.write("**Thử một câu:** tự nhập nội dung, không cần thu thập dữ liệu.")
        st.markdown('<div class="sidebar-footer">Nguồn dữ liệu và sản phẩm đang chọn<br>'
                    '<span>được dùng chung giữa 3 mục phân tích.</span></div>', unsafe_allow_html=True)
    return page


def render_header(page):
    st.markdown(
        f'<div class="page-heading"><div><div class="eyebrow">REVIEWLENS / KHÔNG GIAN PHÂN TÍCH</div>'
        f'<h1>{html.escape(page)}</h1><p>{PAGE_DESCRIPTIONS[page]}</p></div>'
        '<span class="workspace-badge"><b>12</b><span>Nhóm 12<small>Big Data Project</small></span></span></div>',
        unsafe_allow_html=True,
    )


def render_module_guide(page):
    tone, label, question, description, *features = PAGE_GUIDES[page]
    chips = ''.join(f'<span>{feature}</span>' for feature in features)
    st.markdown(f'<div class="module-guide {tone}"><div class="module-label">{label}</div>'
                f'<h2>{question}</h2><p>{description}</p><div class="module-features">{chips}</div></div>',
                unsafe_allow_html=True)


def render_stat_cards(cards):
    markup = ''.join(
        f'<div class="kpi-card {tone}"><div class="kpi-top">{html.escape(title)}</div>'
        f'<div class="kpi-value">{html.escape(str(value))}</div><div class="kpi-sub">{html.escape(note)}</div></div>'
        for title, value, note, tone in cards
    )
    st.markdown(f'<div class="task-stats">{markup}</div>', unsafe_allow_html=True)


def remember_scope():
    st.session_state["shared_scope"] = st.session_state["_scope_widget"]


def render_dataset_context(result):
    frame = result["data"]
    left, right = st.columns([1.4, 1])
    with left:
        st.markdown(f'<div class="dataset-context"><span>BỘ DỮ LIỆU ĐANG XEM</span>'
                    f'<strong>{html.escape(str(result["platform"]))} · {len(frame):,} đánh giá</strong>'
                    '<small>Cùng nguồn và phạm vi khi chuyển giữa Cảm xúc, Điểm sao và Tra cứu.</small></div>',
                    unsafe_allow_html=True)
    with right:
        if {"Nền tảng", "Mã SP/App", "Tên SP/App"}.issubset(frame.columns):
            items = frame[["Nền tảng", "Mã SP/App", "Tên SP/App"]].drop_duplicates()
            scope_options = {f"{row['Tên SP/App']} · {row['Nền tảng']} · {row['Mã SP/App']}":
                             (str(row['Nền tảng']), str(row['Mã SP/App'])) for _, row in items.iterrows()}
            labels = ["Tất cả sản phẩm / ứng dụng", *sorted(scope_options)]
            saved = st.session_state.get("shared_scope", labels[0])
            if saved not in labels:
                saved = labels[0]
                st.session_state["shared_scope"] = saved
            st.session_state["_scope_widget"] = saved
            scope = st.selectbox("Sản phẩm / ứng dụng đang xem", labels,
                                 key="_scope_widget", on_change=remember_scope)
            selected = scope_options.get(scope)
            if selected:
                frame = frame[(frame["Nền tảng"].astype(str) == selected[0])
                              & (frame["Mã SP/App"].astype(str) == selected[1])].copy()
        else:
            st.caption(f"Đối tượng: {result['item_id']}")
    return frame


def render_kpi_bar(frame: pd.DataFrame):
    total = len(frame)
    valid = frame[frame["quality_status"].isin(["VALID_TEXT", "VALID_PRE_CONSUMPTION", "EMOJI_ONLY"])]
    empty = int(frame["quality_status"].eq("EMPTY_COMMENT").sum())
    cards = [
        ("Tổng đánh giá", total, "Bản ghi trong phạm vi đang chọn", "all", "RV"),
        ("Nội dung hợp lệ", len(valid), f"{len(valid) / max(total, 1):.1%} tổng đánh giá", "valid", "OK"),
    ]
    for label, title, tone, mark in [("Positive", "Tích cực", "positive", "+"),
                                      ("Neutral", "Trung tính", "neutral", "="),
                                      ("Negative", "Tiêu cực", "negative", "−")]:
        count = int(valid["sentiment_label"].eq(label).sum())
        subtitle = f"{count / len(valid):.1%} nội dung hợp lệ" if len(valid) else "Chưa có nội dung hợp lệ"
        cards.append((title, count, subtitle, tone, mark))
    markup = ''.join(
        f'<div class="kpi-card {tone}"><div class="kpi-top"><span>{title}</span>'
        f'<span class="kpi-icon">{mark}</span></div><div class="kpi-value">{value:,}</div>'
        f'<div class="kpi-sub">{subtitle}</div></div>'
        for title, value, subtitle, tone, mark in cards
    )
    st.markdown(f'<div class="kpi-grid">{markup}</div>', unsafe_allow_html=True)
    st.caption(f"Chất lượng dữ liệu: {empty:,} bình luận trống · {total - len(valid) - empty:,} bình luận bị lọc. "
               "Tỷ lệ cảm xúc trên thẻ được tính trong nhóm nội dung hợp lệ.")


def render_empty_state(page):
    messages = {
        NAV_ITEMS[0]: "Dán link sản phẩm bên dưới và bấm Phân tích & nhận gợi ý. Trợ lý sẽ tóm tắt liệu bạn nên cân nhắc mua hay xem xét thêm.",
        NAV_ITEMS[1]: "Nạp đánh giá có điểm 1–5 sao để xem điểm trung bình và phân bố số sao.",
        NAV_ITEMS[2]: "Nạp đánh giá để tìm kiếm, mở từng bản ghi và xuất danh sách đã lọc.",
    }
    st.info(messages[page])
    st.caption("Chỉ cần nạp một lần; bộ dữ liệu được dùng chung cho cả ba màn hình.")


def render_source_controls():
    advising = st.session_state.get("dashboard_page") == NAV_ITEMS[0]
    title = "Dán link sản phẩm để phân tích & nhận gợi ý" if advising else "Chuẩn bị dữ liệu · Thu thập hoặc nạp đánh giá"
    with st.expander(title, expanded=True):
        live_tab, local_tab = st.tabs(["Thu thập từ đường dẫn", "Dữ liệu đã thu thập"])
        with live_tab:
            st.caption("Chọn nền tảng, dán đường dẫn và đặt số đánh giá tối đa để bắt đầu.")
            with st.form("crawl_form"):
                platform_col, url_col, limit_col = st.columns([1.25, 3, 1])
                with platform_col:
                    platform = st.selectbox("Nền tảng", PLATFORMS)
                with url_col:
                    url = st.text_input("Đường dẫn sản phẩm / ứng dụng", placeholder="https://tiki.vn/... hoặc đường dẫn ứng dụng")
                with limit_col:
                    limit = st.number_input("Số đánh giá tối đa", min_value=1, max_value=2000, value=100, step=50)
                submitted = st.form_submit_button("Phân tích & nhận gợi ý" if advising else "Thu thập & phân tích", type="primary")
            if submitted:
                if not url.strip():
                    st.error("Hãy nhập đường dẫn sản phẩm hoặc ứng dụng để tiếp tục.")
                else:
                    try:
                        item_id = extract_item_id(platform, url)
                        with st.spinner("Đang thu thập đánh giá và phân tích cảm xúc…"):
                            reviews = crawl_reviews(platform, item_id, int(limit))
                            if reviews:
                                frame = enrich_with_nlp(pd.DataFrame(reviews), platform=platform)
                                st.session_state["crawl_results"] = {
                                    "mode": "live_crawl", "platform": platform, "item_id": item_id, "data": frame,
                                    "url": url.strip(), "nlp_revision": NLP_PIPELINE_VERSION,
                                }
                        if reviews:
                            st.session_state["show_source_controls"] = False
                            st.session_state.pop("shared_scope", None)
                            st.rerun()
                        else:
                            st.warning("Nguồn chưa trả về đánh giá cho đường dẫn này. Hãy kiểm tra hoặc thử một đối tượng khác.")
                    except (ValueError, KeyError) as exc:
                        st.error(f"Không thể xử lý yêu cầu: {exc}")
                    except Exception as exc:
                        st.error(f"Chưa thể hoàn tất thu thập: {exc}")
        with local_tab:
            available = [name for name, path in RAW_DATASET_FILES.items() if path.exists()]
            if not available:
                st.info("Chưa có bộ dữ liệu đã thu thập trên máy. Bạn có thể bắt đầu bằng đường dẫn ở tab bên cạnh.")
                st.caption("Dữ liệu được đọc từ các bộ CSV do collector tạo trong thư mục data/raw.")
            else:
                source = st.selectbox("Nguồn dữ liệu", ["Tất cả nguồn", *available])
                st.caption(f"Có sẵn: {', '.join(available)}. Số bản ghi sẽ được cập nhật sau khi nạp.")
                if st.button("Nạp & phân tích dữ liệu", type="primary"):
                    try:
                        # Refresh on an explicit load so newly collected CSV files are reflected.
                        load_local_raw_reviews.clear()
                        with st.spinner("Đang nạp dữ liệu và phân tích cảm xúc…"):
                            frame = load_local_raw_reviews(source)
                        if frame.empty:
                            st.warning("Bộ dữ liệu được chọn chưa có đánh giá.")
                        else:
                            st.session_state["crawl_results"] = {
                                "mode": "local_dataset", "platform": source,
                                "item_id": f"{len(frame):,} bản ghi", "data": frame,
                            }
                            st.session_state["show_source_controls"] = False
                            st.session_state.pop("shared_scope", None)
                            st.rerun()
                    except Exception as exc:
                        st.error(f"Chưa thể nạp bộ dữ liệu: {exc}")


def render_purchase_advisor(frame: pd.DataFrame, result):
    """Keep the advice tied to exactly the product used by the surrounding charts."""
    single_product = result.get("mode") == "live_crawl" and bool(result.get("item_id"))
    platform = result.get("platform", "")
    identity = {"Nền tảng", "Mã SP/App"}
    product = str(result.get("item_id", ""))
    if "app_json" in frame.columns and not frame.empty:
        name = _extract_item_name(frame["app_json"].iloc[0])
        if name != "Không rõ tên":
            product = name
    if identity.issubset(frame.columns):
        items = frame[["Nền tảng", "Mã SP/App"]].drop_duplicates()
        single_product = len(items) == 1 and items.notna().all().all() and all(str(v).strip() for v in items.iloc[0])
        if single_product:
            platform = str(items.iloc[0]["Nền tảng"])
            product = str(items.iloc[0]["Mã SP/App"])
            if "Tên SP/App" in frame.columns:
                names = frame["Tên SP/App"].dropna()
                if not names.empty:
                    product = str(names.iloc[0])
    is_app = platform in ("Google Play", "App Store")
    advice = build_purchase_advice(frame, DISPLAY_COLUMNS[1], single_product=single_product, is_app=is_app)
    st.markdown("### Trợ lý chọn sản phẩm" if not is_app else "### Trợ lý chọn ứng dụng")
    with st.chat_message("assistant"):
        if single_product:
            st.caption(f"Đang tư vấn: {product} · {platform}")
        st.markdown(f'<div class="purchase-advice {advice["tone"]}"><span>GỢI Ý TỪ ĐÁNH GIÁ</span>'
                    f'<h3>{html.escape(advice["title"])}</h3><p>{html.escape(advice["summary"])}</p></div>',
                    unsafe_allow_html=True)
        if advice["reasons"]:
            with st.expander("Vì sao có gợi ý này? · Số liệu và điểm cần chú ý"):
                for reason in advice["reasons"]:
                    st.write("• " + reason)
                for label, key in [("Điểm được khen", "positives"), ("Điểm bị phàn nàn", "concerns")]:
                    if advice[key]:
                        st.markdown(f"**{label}**")
                        for aspect, count in advice[key]:
                            st.write(f"• {aspect.capitalize()}: được nhắc trong {count:,} bình luận hợp lệ.")
                st.caption("Gợi ý cần ít nhất 10 bình luận hợp lệ đã trải nghiệm và chiếm ít nhất 30% dữ liệu. "
                           "Hướng tích cực cần ≥70% tích cực, ≤15% tiêu cực và điểm sao phù hợp nếu có. "
                           "Hướng thận trọng khi ≥40% tiêu cực, hoặc ít nhất 10 đánh giá có sao với điểm trung bình <3/5 hay ≥40% chấm 1–2 sao. "
                           "Các trường hợp còn lại cần xem xét thêm.")
        st.caption("Tóm tắt tự động từ các đánh giá đã thu thập của sản phẩm đang chọn; chưa xét giá bán, thông số hay nhu cầu riêng của bạn.")
        source_url = result.get("url")
        if single_product and source_url and result.get("mode") == "live_crawl":
            st.link_button("Mở sản phẩm / ứng dụng gốc", source_url)
    left, right = st.columns(2)
    with left:
        if single_product and advice["valid"]:
            st.button("Đọc các phản hồi tiêu cực", on_click=navigate_to, args=(NAV_ITEMS[2], QUICK_FILTERS[2]))
    with right:
        st.button("Dán link sản phẩm khác", on_click=show_source_controls)


def render_nlp_analysis_tab(frame: pd.DataFrame):
    """Content sentiment, aspects and quality; independent of star summaries."""
    render_kpi_bar(frame)
    sub_overview, sub_aspects, sub_quality = st.tabs([
        "Cảm xúc chung",
        "Khía cạnh & từ khóa",
        "Chất lượng & đối chiếu",
    ])

    valid_statuses = {"VALID_TEXT", "VALID_PRE_CONSUMPTION", "EMOJI_ONLY"}

    # --- SUB-TAB 1: TỔNG QUAN CẢM XÚC ---
    with sub_overview:
        st.caption("Nhãn cảm xúc được suy ra từ nội dung. Các thẻ phía trên luôn thống kê nhóm nội dung hợp lệ.")
        only_valid_text = st.toggle(
            "Chỉ tính trên văn bản hợp lệ (loại bỏ bình luận trống & nhiễu)",
            value=True,
            key="toggle_valid_sentiment",
        )
        nlp_target_df = (
            frame[frame["quality_status"].isin(valid_statuses)].copy()
            if only_valid_text and "quality_status" in frame.columns
            else frame.copy()
        )

        if not only_valid_text:
            st.warning("Biểu đồ bên dưới đang tính cả bình luận trống và bị lọc. Nhãn của bình luận trống có thể được suy ra từ số sao.")

        sent_counts = (
            nlp_target_df["sentiment_label"]
            .value_counts()
            .reindex(["Positive", "Neutral", "Negative"], fill_value=0)
            .rename_axis("Nhãn cảm xúc")
            .reset_index(name="Số bình luận")
        )

        c1, c2 = st.columns(2)
        with c1:
            fig_sbar = px.bar(
                sent_counts,
                x="Nhãn cảm xúc",
                y="Số bình luận",
                color="Nhãn cảm xúc",
                color_discrete_map=SENTIMENT_COLORS,
                text_auto=True,
                title="Phân bố số lượng theo nhãn cảm xúc",
            )
            fig_sbar.update_traces(marker_line_width=0, opacity=0.92)
            st.plotly_chart(_style_figure(fig_sbar), use_container_width=True, theme=None)

        with c2:
            sent_pie = sent_counts[sent_counts["Số bình luận"] > 0]
            if not sent_pie.empty:
                fig_spie = px.pie(
                    sent_pie,
                    names="Nhãn cảm xúc",
                    values="Số bình luận",
                    color="Nhãn cảm xúc",
                    color_discrete_map=SENTIMENT_COLORS,
                    hole=0.44,
                    title="Tỷ lệ cảm xúc (%)",
                )
                fig_spie.update_traces(textposition="inside", textinfo="percent+label")
                st.plotly_chart(_style_figure(fig_spie), use_container_width=True, theme=None)
            else:
                st.info("Không có dữ liệu hợp lệ.")

        with st.expander("Phân tích nâng cao · Điểm cảm xúc và độ dài bình luận"):
            c3, c4 = st.columns(2)
            with c3:
                if not nlp_target_df.empty and "sentiment_score" in nlp_target_df.columns:
                    fig_hist = px.histogram(
                        nlp_target_df,
                        x="sentiment_score",
                        color="sentiment_label",
                        color_discrete_map=SENTIMENT_COLORS,
                        nbins=25,
                        barmode="overlay",
                        opacity=0.82,
                        title="Phân phối điểm cảm xúc",
                        labels={"sentiment_score": "Sentiment Score"},
                    )
                    st.plotly_chart(_style_figure(fig_hist), use_container_width=True, theme=None)

            with c4:
                if not nlp_target_df.empty and "word_count" in nlp_target_df.columns:
                    fig_box = px.box(
                        nlp_target_df,
                        x="sentiment_label",
                        y="word_count",
                        color="sentiment_label",
                        color_discrete_map=SENTIMENT_COLORS,
                        category_orders={"sentiment_label": ["Positive", "Neutral", "Negative"]},
                        title="Phân bố độ dài bình luận (Số từ) theo nhãn",
                        labels={"word_count": "Số từ", "sentiment_label": "Nhãn cảm xúc"},
                    )
                    st.plotly_chart(_style_figure(fig_box), use_container_width=True, theme=None)

        sent_trend = _daily_sentiment_percentages(nlp_target_df)
        if not sent_trend.empty:
            fig_strend = px.line(
                sent_trend,
                x="Ngày",
                y="Tỷ lệ (%)",
                color="Nhãn cảm xúc",
                color_discrete_map=SENTIMENT_COLORS,
                markers=True,
                title="Xu hướng tỷ lệ cảm xúc tích lũy theo thời gian",
            )
            st.plotly_chart(_style_figure(fig_strend, height=360), use_container_width=True, theme=None)

    # --- SUB-TAB 2: KHÍA CẠNH & TỪ KHÓA ---
    with sub_aspects:
        nlp_valid_df = frame[frame["quality_status"].isin(valid_statuses)].copy()
        aspect_df = _build_aspect_sentiment_dataframe(nlp_valid_df)
        if not aspect_df.empty:
            col_asp_chart, col_asp_table = st.columns([1.45, 1])
            with col_asp_chart:
                fig_asp = px.bar(
                    aspect_df,
                    x="Số lượng",
                    y="Khía cạnh",
                    color="Cảm xúc",
                    orientation="h",
                    barmode="stack",
                    color_discrete_map=SENTIMENT_COLORS,
                    text_auto=True,
                    title="Phân bố cảm xúc theo khía cạnh (ABSA)",
                )
                st.plotly_chart(_style_figure(fig_asp, height=380), use_container_width=True, theme=None)

            with col_asp_table:
                pivot_asp = (
                    aspect_df.pivot(index="Khía cạnh", columns="Cảm xúc", values="Số lượng")
                    .fillna(0)
                    .astype(int)
                )
                for col in ("Positive", "Neutral", "Negative"):
                    if col not in pivot_asp.columns:
                        pivot_asp[col] = 0
                pivot_asp = pivot_asp[["Positive", "Neutral", "Negative"]]
                pivot_asp["Tổng"] = pivot_asp.sum(axis=1)
                pivot_asp["% Positive"] = (
                    pivot_asp["Positive"] / pivot_asp["Tổng"].replace(0, 1) * 100
                ).round(1).astype(str) + "%"
                pivot_asp = pivot_asp.sort_values("Tổng", ascending=False).reset_index()
                st.dataframe(pivot_asp, use_container_width=True, hide_index=True, height=350)
        else:
            st.info("Không có dữ liệu khía cạnh.")

        top_k = st.slider("Số lượng từ khóa hiển thị", min_value=5, max_value=25, value=12, step=1)
        col_kw_pos, col_kw_neg = st.columns(2)
        with col_kw_pos:
            top_pos = _build_top_keywords_dataframe(frame, "Positive", top_k=top_k)
            if not top_pos.empty:
                fig_kw_pos = px.bar(
                    top_pos.sort_values("Tần suất", ascending=True),
                    x="Tần suất",
                    y="Từ khóa",
                    orientation="h",
                    text_auto=True,
                    color_discrete_sequence=["#0d9488"],
                    title=f"Top {len(top_pos)} từ khóa — Positive",
                )
                st.plotly_chart(_style_figure(fig_kw_pos, height=370), use_container_width=True, theme=None)
            else:
                st.info("Không có dữ liệu từ khóa Positive.")

        with col_kw_neg:
            top_neg = _build_top_keywords_dataframe(frame, "Negative", top_k=top_k)
            if not top_neg.empty:
                fig_kw_neg = px.bar(
                    top_neg.sort_values("Tần suất", ascending=True),
                    x="Tần suất",
                    y="Từ khóa",
                    orientation="h",
                    text_auto=True,
                    color_discrete_sequence=["#e26962"],
                    title=f"Top {len(top_neg)} từ khóa — Negative",
                )
                st.plotly_chart(_style_figure(fig_kw_neg, height=370), use_container_width=True, theme=None)
            else:
                st.info("Không có dữ liệu từ khóa Negative.")

    # --- SUB-TAB 3: CHẤT LƯỢNG & ĐỐI CHIẾU ---
    with sub_quality:
        col_qual, col_cross = st.columns(2)
        with col_qual:
            qual_counts = (
                frame["quality_status"]
                .value_counts()
                .rename_axis("Mã trạng thái")
                .reset_index(name="Số lượng")
            )
            qual_counts["Trạng thái"] = qual_counts["Mã trạng thái"].map(
                lambda k: QUALITY_STATUS_VI_LABELS.get(str(k), str(k)).split(" (")[0]
            )
            fig_qual = px.bar(
                qual_counts,
                x="Số lượng",
                y="Trạng thái",
                orientation="h",
                color="Mã trạng thái",
                text_auto=True,
                title="Phân bố trạng thái kiểm soát chất lượng văn bản",
            )
            fig_qual.update_layout(showlegend=False)
            st.plotly_chart(_style_figure(fig_qual, height=370), use_container_width=True, theme=None)

        with col_cross:
            st.caption("Đối chiếu hai tín hiệu: số sao người dùng chấm và cảm xúc từ nội dung.")
            rated_nlp = frame[frame["quality_status"].isin(valid_statuses)].dropna(
                subset=[DISPLAY_COLUMNS[1], "sentiment_label"]
            ).copy()
            rated_nlp = rated_nlp[rated_nlp[DISPLAY_COLUMNS[1]].between(1, 5)]
            if not rated_nlp.empty:
                rated_nlp["Mức sao"] = rated_nlp[DISPLAY_COLUMNS[1]].astype(int).astype(str) + " sao"
                cross_df = (
                    rated_nlp.groupby(["Mức sao", "sentiment_label"])
                    .size()
                    .reset_index(name="Số bình luận")
                )
                fig_cross = px.bar(
                    cross_df,
                    x="Mức sao",
                    y="Số bình luận",
                    color="sentiment_label",
                    color_discrete_map=SENTIMENT_COLORS,
                    barmode="group",
                    text_auto=True,
                    category_orders={
                        "Mức sao": ["1 sao", "2 sao", "3 sao", "4 sao", "5 sao"],
                        "sentiment_label": ["Positive", "Neutral", "Negative"],
                    },
                    title="Đối chiếu Rating (1–5 sao) và Nhãn cảm xúc NLP",
                )
                st.plotly_chart(_style_figure(fig_cross, height=370), use_container_width=True, theme=None)
            else:
                st.info("Không đủ dữ liệu đối chiếu.")

        mismatch_df = frame[
            (frame[DISPLAY_COLUMNS[1]].fillna(0) >= 3)
            & (frame["sentiment_label"] == "Negative")
            & (frame["quality_status"] == "VALID_TEXT")
        ]
        st.markdown(f"**Bất đồng Rating & Nội dung ({len(mismatch_df):,} bản ghi có Rating 3–5 sao nhưng nhãn NLP là Negative)**")
        if mismatch_df.empty:
            st.caption("Không ghi nhận trường hợp bất đồng giữa điểm sao và nội dung.")
        else:
            cols_to_show = [
                DISPLAY_COLUMNS[0],
                DISPLAY_COLUMNS[1],
                DISPLAY_COLUMNS[2],
                "cleaned_text",
                "sentiment_label",
                "sentiment_score",
                "Aspects hiển thị",
            ]
            if "Tên SP/App" in mismatch_df.columns:
                cols_to_show = ["Nền tảng", "Tên SP/App", *cols_to_show]
            st.dataframe(
                mismatch_df[cols_to_show],
                use_container_width=True,
                hide_index=True,
                height=300,
            )


def render_rating_tab(frame: pd.DataFrame):
    """Render rating distribution and cumulative timeline charts."""
    rated = frame.dropna(subset=[DISPLAY_COLUMNS[1]]).copy()
    rated = rated[rated[DISPLAY_COLUMNS[1]].between(1, 5)]
    if rated.empty:
        st.info("Không có dữ liệu rating hợp lệ (1–5 sao).")
        return

    stars = rated[DISPLAY_COLUMNS[1]]
    high = int(stars.ge(4).sum())
    low = int(stars.le(2).sum())
    render_stat_cards([
        ("Điểm trung bình", f"{stars.mean():.2f} / 5", "Từ điểm sao người dùng chấm", "all"),
        ("Đánh giá có điểm sao", f"{len(rated):,}", f"{len(frame) - len(rated):,} bản ghi thiếu hoặc sai điểm sao", "valid"),
        ("Tỷ lệ 4–5 sao", f"{high / len(rated):.1%}", f"{high:,} / {len(rated):,} đánh giá có sao", "positive"),
        ("Tỷ lệ 1–2 sao", f"{low / len(rated):.1%}", f"{low:,} / {len(rated):,} đánh giá có sao", "negative"),
    ])
    st.caption(f"Thống kê gồm cả đánh giá chỉ chấm sao, không có chữ. Có {int(stars.eq(3).sum()):,} đánh giá 3 sao.")
    st.button("Đọc các đánh giá 1–2 sao", on_click=navigate_to,
              args=(NAV_ITEMS[2], QUICK_FILTERS[1]))
    st.markdown("### Phân bố điểm sao")
    counts = (
        rated[DISPLAY_COLUMNS[1]]
        .value_counts()
        .reindex(range(1, 6), fill_value=0)
        .rename_axis("Số sao")
        .reset_index(name="Số bình luận")
    )
    counts["Nhãn sao"] = counts["Số sao"].astype(int).astype(str) + " sao"

    left, right = st.columns(2)
    with left:
        fig_bar = px.bar(
            counts,
            x="Nhãn sao",
            y="Số bình luận",
            color="Nhãn sao",
            color_discrete_map=RATING_COLORS,
            text_auto=True,
            title="Số lượng bình luận theo mức sao",
        )
        fig_bar.update_traces(marker_line_width=0, opacity=0.92)
        st.plotly_chart(_style_figure(fig_bar), use_container_width=True, theme=None)

    with right:
        pie_data = counts[counts["Số bình luận"] > 0].copy()
        fig_pie = px.pie(
            pie_data,
            names="Nhãn sao",
            values="Số bình luận",
            color="Nhãn sao",
            color_discrete_map=RATING_COLORS,
            title="Tỷ lệ các mức đánh giá (%)",
            hole=0.42,
        )
        fig_pie.update_traces(textposition="inside", textinfo="percent+label")
        st.plotly_chart(_style_figure(fig_pie), use_container_width=True, theme=None)

    trend = _daily_rating_percentages(rated)
    if trend.empty:
        st.info("Không có dữ liệu thời gian hợp lệ.")
        return

    st.markdown("### Điểm sao thay đổi theo thời gian ra sao?")
    st.caption("Mỗi mốc là tỷ lệ tích lũy từ đầu bộ dữ liệu đến ngày đó, không phải tỷ lệ riêng trong ngày. Bản ghi thiếu ngày được bỏ qua.")
    fig_trend = px.line(
        trend,
        x="Ngày",
        y="Tỷ lệ (%)",
        color="Mức đánh giá",
        color_discrete_map=RATING_COLORS,
        markers=True,
        title="Tỷ lệ rating tích lũy theo thời gian",
    )
    st.plotly_chart(_style_figure(fig_trend, height=370), use_container_width=True, theme=None)


def render_data_explorer_tab(frame: pd.DataFrame):
    """A workbench for filtering, reading individual records and exporting them."""
    st.markdown("### Tìm đánh giá")
    preset = st.session_state.get("review_quick_filter", QUICK_FILTERS[0])
    if preset not in QUICK_FILTERS:
        st.session_state["review_quick_filter"] = QUICK_FILTERS[0]
    quick = st.radio("Lọc nhanh", QUICK_FILTERS, horizontal=True, key="review_quick_filter")
    keyword = st.text_input("Từ khóa trong bình luận", placeholder="Ví dụ: giao hàng, đăng nhập, đóng gói…")
    with st.expander("Bộ lọc chi tiết · Cảm xúc, chất lượng và số sao"):
        c1, c2, c3 = st.columns(3)
        with c1:
            sentiment_options = {value: key for key, value in SENTIMENT_VI.items()}
            labels = st.multiselect("Cảm xúc từ nội dung", list(sentiment_options), default=list(sentiment_options))
            sentiments = [sentiment_options[value] for value in labels]
        with c2:
            status_options = {QUALITY_STATUS_VI_LABELS.get(str(value), str(value)).split(" (")[0]: value
                              for value in sorted(frame["quality_status"].dropna().unique())}
            statuses = st.multiselect("Chất lượng nội dung", list(status_options), default=list(status_options))
        with c3:
            star_options = ["5 sao", "4 sao", "3 sao", "2 sao", "1 sao", "Thiếu / sai điểm sao"]
            selected_stars = st.multiselect("Điểm sao người dùng chấm", star_options, default=star_options)
    ratings = pd.to_numeric(frame[DISPLAY_COLUMNS[1]], errors="coerce")
    star_numbers = [int(value[0]) for value in selected_stars if value.endswith("sao") and value[0].isdigit()]
    star_mask = ratings.isin(star_numbers)
    if "Thiếu / sai điểm sao" in selected_stars:
        star_mask |= ~ratings.isin([1, 2, 3, 4, 5])
    mask = (frame["sentiment_label"].isin(sentiments)
            & frame["quality_status"].isin([status_options[value] for value in statuses]) & star_mask)
    if quick == QUICK_FILTERS[1]:
        mask &= ratings.isin([1, 2])
    elif quick == QUICK_FILTERS[2]:
        mask &= frame["sentiment_label"].eq("Negative") & frame["quality_status"].isin(["VALID_TEXT", "VALID_PRE_CONSUMPTION", "EMOJI_ONLY"])
    elif quick == QUICK_FILTERS[3]:
        mask &= ratings.isin([3, 4, 5]) & frame["sentiment_label"].eq("Negative") & frame["quality_status"].eq("VALID_TEXT")
        st.caption("Nhóm đối chiếu: 3–5 sao nhưng nội dung hợp lệ được phân loại tiêu cực.")
    if keyword.strip():
        query = keyword.strip().lower()
        mask &= (frame[DISPLAY_COLUMNS[2]].fillna("").astype(str).str.lower().str.contains(query, regex=False)
                 | frame["cleaned_text"].fillna("").astype(str).str.lower().str.contains(query, regex=False))
    filtered = frame[mask].copy().reset_index(drop=True)
    left, right = st.columns([3, 1])
    with left:
        st.markdown(f"### Kết quả · {len(filtered):,} đánh giá")
        st.caption(f"Trong {len(frame):,} bản ghi thuộc phạm vi đang chọn. CSV chứa toàn bộ cột của các dòng khớp bộ lọc.")
    with right:
        st.download_button("Tải kết quả CSV", filtered.to_csv(index=False).encode("utf-8-sig"),
                           file_name="reviews_filtered.csv", mime="text/csv", disabled=filtered.empty,
                           use_container_width=True)
    if filtered.empty:
        st.info("Không có đánh giá khớp. Chọn Lọc nhanh: Tất cả, xóa từ khóa hoặc mở rộng bộ lọc chi tiết.")
        return
    extended = st.toggle("Hiện thêm điểm cảm xúc, văn bản xử lý và khía cạnh", value=False)
    columns = [column for column in ["Nền tảng", "Tên SP/App", *DISPLAY_COLUMNS, REVIEW_TIME_COLUMN,
                                    "sentiment_label", "quality_status"] if column in filtered.columns]
    if extended:
        columns += ["sentiment_score", "cleaned_text", "Aspects hiển thị", "word_count"]
    display = filtered[columns].copy()
    display["sentiment_label"] = display["sentiment_label"].map(SENTIMENT_VI).fillna(display["sentiment_label"])
    display["quality_status"] = display["quality_status"].map(lambda value: QUALITY_STATUS_VI_LABELS.get(str(value), str(value)).split(" (")[0])
    display = display.rename(columns={"sentiment_label":"Cảm xúc nội dung", "quality_status":"Chất lượng",
                                      "sentiment_score":"Điểm cảm xúc", "cleaned_text":"Văn bản xử lý",
                                      "Aspects hiển thị":"Khía cạnh", "word_count":"Số từ"})
    st.dataframe(display, use_container_width=True, hide_index=True, height=360)
    st.markdown("### Đọc đầy đủ một đánh giá")
    review_options = [f"{i + 1}. {row[DISPLAY_COLUMNS[0]]} · {str(row[DISPLAY_COLUMNS[2]])[:65] or '(Không có nội dung)'}"
                      for i, row in filtered.iterrows()]
    chosen = st.selectbox("Chọn bản ghi từ kết quả phía trên", review_options)
    row = filtered.iloc[review_options.index(chosen)]
    with st.container(border=True):
        st.markdown("**Nội dung gốc**")
        st.text(str(row[DISPLAY_COLUMNS[2]]) or "(Đánh giá chỉ có điểm sao, không có nội dung)")
        c1, c2, c3 = st.columns(3)
        c1.metric("Số sao đã chấm", "—" if pd.isna(row[DISPLAY_COLUMNS[1]]) else str(row[DISPLAY_COLUMNS[1]]))
        c2.metric("Cảm xúc nội dung", SENTIMENT_VI.get(row["sentiment_label"], row["sentiment_label"]))
        c3.metric("Điểm cảm xúc", f"{row['sentiment_score']:.4f}")
        st.caption("Chất lượng: " + QUALITY_STATUS_VI_LABELS.get(str(row["quality_status"]), str(row["quality_status"])).split(" (")[0])
        if row["quality_status"] == "EMPTY_COMMENT":
            st.info("Bản ghi không có nội dung; nhãn cảm xúc được suy ra từ điểm sao, không phải từ văn bản.")
        st.write("**Khía cạnh:** " + (str(row.get("Aspects hiển thị", "")) or "Không có khía cạnh"))
        with st.expander("Văn bản xử lý và toàn bộ trường dữ liệu"):
            st.text(str(row["cleaned_text"]) or "(Rỗng)")
            st.json(json.loads(filtered.iloc[[review_options.index(chosen)]].to_json(orient="records", date_format="iso"))[0])


def render_test_tab():
    """Explicit single-review experiment, isolated from the shared dataset."""
    input_col, output_col = st.columns([1, 1.1], gap="large")
    with input_col:
        st.markdown("### Nhập bình luận")
        preset = st.selectbox("Bắt đầu từ một ví dụ", list(TEST_PRESETS))
        default_text, default_star = TEST_PRESETS[preset]
        with st.form("single_review_form"):
            sample = st.text_area("Nội dung muốn phân tích", default_text, height=180, key=f"lab_text_{preset}")
            rating = st.selectbox("Điểm sao tham khảo", [5, 4, 3, 2, 1],
                                  index=[5, 4, 3, 2, 1].index(default_star), key=f"lab_rating_{preset}")
            st.caption("Điểm sao được dùng để suy ra nhãn khi bình luận trống. Với nội dung có chữ, kết quả có thể khác số sao.")
            submitted = st.form_submit_button("Phân tích bình luận", type="primary", use_container_width=True)
        if submitted:
            try:
                with st.spinner("Đang phân tích bình luận…"):
                    result = get_nlp_pipeline().analyze_review(sample, rating=rating)
                st.session_state["single_review_result"] = {"text":sample, "rating":rating, "result":result, "nlp_revision":NLP_PIPELINE_VERSION}
            except Exception as exc:
                st.error(f"Chưa thể phân tích bình luận: {exc}")
    with output_col:
        st.markdown("### Kết quả của lần phân tích gần nhất")
        record = st.session_state.get("single_review_result")
        if record and record.get("nlp_revision") != NLP_PIPELINE_VERSION:
            record = None
            st.session_state.pop("single_review_result", None)
        if record is None:
            st.markdown('<div class="lab-placeholder"><span>Aa</span><h3>Chờ bình luận của bạn</h3>'
                        '<p>Nhập hoặc chọn một câu mẫu, sau đó bấm <b>Phân tích bình luận</b>.</p>'
                        '<small>Kết quả sẽ gồm cảm xúc, khía cạnh và thông tin xử lý.</small></div>', unsafe_allow_html=True)
        else:
            cleaned, words, score, label, aspects_json, status = record["result"]
            tone = {"Positive":"positive", "Neutral":"neutral", "Negative":"negative"}.get(label, "neutral")
            st.markdown(f'<div class="lab-result {tone}"><span>CẢM XÚC DỰ ĐOÁN</span>'
                        f'<strong>{SENTIMENT_VI.get(label, html.escape(label))}</strong>'
                        f'<p>{html.escape(QUALITY_STATUS_VI_LABELS.get(status, status).split(" (")[0])}</p></div>', unsafe_allow_html=True)
            st.caption(f"Đầu vào đã phân tích · điểm sao tham khảo: {record['rating']}/5")
            st.text(record["text"] or "(Bình luận trống)")
            if status == "EMPTY_COMMENT":
                st.info("Kết quả này được suy ra từ điểm sao vì nội dung trống.")
            st.markdown("**Các khía cạnh được nhắc đến**")
            try:
                aspects = json.loads(aspects_json) if aspects_json else []
            except (ValueError, TypeError):
                aspects = []
            chips = []
            for item in aspects:
                if isinstance(item, dict):
                    sent = str(item.get("sentiment", "neutral")).lower()
                    cls = {"positive":"aspect-pos", "negative":"aspect-neg"}.get(sent,"aspect-neu")
                    text = html.escape(str(item.get("aspect", "")).capitalize())
                    sent_vi = SENTIMENT_VI.get(sent.capitalize(), "Trung tính")
                    chips.append(f'<span class="aspect-chip {cls}">{text}: {sent_vi}</span>')
            st.markdown(''.join(chips) or '<span class="aspect-chip aspect-neu">Không trích xuất được khía cạnh</span>', unsafe_allow_html=True)
            with st.expander("Chi tiết xử lý · Điểm cảm xúc, số từ và văn bản"):
                a, b = st.columns(2)
                a.metric("Điểm cảm xúc", f"{score:.4f}")
                b.metric("Số từ sau xử lý", words)
                st.caption("Điểm 0–1 kết hợp mô hình và quy tắc; không phải xác suất tin cậy.")
                st.text(cleaned or "(Rỗng)")
    st.caption("Khu vực thử nghiệm độc lập. Kết quả ở đây không làm thay đổi biểu đồ, số lượng đánh giá hay file CSV của bộ dữ liệu.")


def main():
    st.set_page_config(page_title="ReviewLens · Nhóm 12", page_icon="◈", layout="wide",
                       initial_sidebar_state="expanded")
    inject_custom_css()
    page = render_sidebar()
    render_header(page)
    render_module_guide(page)
    if page == NAV_ITEMS[3]:
        render_test_tab()
        return

    result = st.session_state.get("crawl_results")
    if not result:
        render_empty_state(page)
    if not result or st.session_state.get("show_source_controls", False):
        render_source_controls()
    result = st.session_state.get("crawl_results")
    if not result:
        st.button("Thử trước với một bình luận", on_click=navigate_to, args=(NAV_ITEMS[3],))
        return

    if "sentiment_label" not in result["data"].columns or result.get("nlp_revision") != NLP_PIPELINE_VERSION:
        result["data"] = enrich_with_nlp(result["data"], platform=result.get("platform"))
        result["nlp_revision"] = NLP_PIPELINE_VERSION
    frame = render_dataset_context(result)
    if page == NAV_ITEMS[0]:
        render_purchase_advisor(frame, result)
        render_nlp_analysis_tab(frame)
    elif page == NAV_ITEMS[1]:
        render_rating_tab(frame)
    else:
        render_data_explorer_tab(frame)
    st.markdown('<div class="page-footer">ReviewLens <span>Nhóm 12 · Phân tích đánh giá đa nguồn</span></div>', unsafe_allow_html=True)


if __name__ == "__main__":
    main()
