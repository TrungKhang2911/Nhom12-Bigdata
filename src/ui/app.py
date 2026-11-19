"""Streamlit dashboard for review collection, rating analytics, and NLP sentiment analysis."""

from __future__ import annotations

from collections import Counter
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

from src.processing.nlp_pipeline import SentimentNLPPipeline

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
    "1 sao": "#ef4444",
    "2 sao": "#f97316",
    "3 sao": "#eab308",
    "4 sao": "#3b82f6",
    "5 sao": "#10b981",
}
SENTIMENT_COLORS = {
    "Positive": "#10b981",
    "Neutral": "#f59e0b",
    "Negative": "#ef4444",
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
    "Mặc định (Tự nhập)": (
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
    """Minimalist enterprise CSS with smooth transitions and animations."""
    st.markdown(
        """
        <style>
        @keyframes fadeInUp {
            0% { opacity: 0; transform: translateY(12px); }
            100% { opacity: 1; transform: translateY(0); }
        }
        @keyframes progressFill {
            0% { width: 0%; }
        }

        /* Header Bar */
        .app-header {
            background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
            border-radius: 12px;
            padding: 20px 26px;
            color: #f8fafc;
            margin-bottom: 16px;
            border: 1px solid rgba(255, 255, 255, 0.08);
            animation: fadeInUp 0.45s cubic-bezier(0.16, 1, 0.3, 1);
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 12px;
        }
        .app-header-title {
            font-size: 1.45rem;
            font-weight: 700;
            margin: 0;
            letter-spacing: -0.02em;
            color: #ffffff;
        }
        .app-header-sub {
            font-size: 0.86rem;
            color: #94a3b8;
            margin: 4px 0 0 0;
        }
        .meta-pills {
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
        }
        .meta-pill {
            background: rgba(255, 255, 255, 0.07);
            border: 1px solid rgba(255, 255, 255, 0.14);
            color: #e2e8f0;
            padding: 4px 11px;
            border-radius: 6px;
            font-size: 0.76rem;
            font-weight: 600;
            letter-spacing: 0.02em;
        }

        /* KPI Cards */
        .kpi-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(185px, 1fr));
            gap: 12px;
            margin: 10px 0 18px 0;
        }
        .kpi-card {
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid rgba(148, 163, 184, 0.2);
            border-radius: 10px;
            padding: 14px 16px;
            animation: fadeInUp 0.45s cubic-bezier(0.16, 1, 0.3, 1) both;
            transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;
        }
        .kpi-card:nth-child(1) { animation-delay: 0.04s; border-top: 3px solid #3b82f6; }
        .kpi-card:nth-child(2) { animation-delay: 0.08s; border-top: 3px solid #6366f1; }
        .kpi-card:nth-child(3) { animation-delay: 0.12s; border-top: 3px solid #10b981; }
        .kpi-card:nth-child(4) { animation-delay: 0.16s; border-top: 3px solid #f59e0b; }
        .kpi-card:nth-child(5) { animation-delay: 0.20s; border-top: 3px solid #ef4444; }
        .kpi-card:hover {
            transform: translateY(-3px);
            box-shadow: 0 8px 18px -6px rgba(15, 23, 42, 0.14);
            border-color: rgba(59, 130, 246, 0.4);
        }
        .kpi-label {
            font-size: 0.74rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            opacity: 0.72;
            margin-bottom: 4px;
        }
        .kpi-value {
            font-size: 1.55rem;
            font-weight: 700;
            line-height: 1.15;
            margin-bottom: 4px;
        }
        .kpi-sub {
            font-size: 0.76rem;
            opacity: 0.7;
            margin-bottom: 8px;
        }
        .kpi-bar-bg {
            width: 100%;
            height: 4px;
            background: rgba(148, 163, 184, 0.18);
            border-radius: 999px;
            overflow: hidden;
        }
        .kpi-bar-fill {
            height: 100%;
            border-radius: 999px;
            animation: progressFill 0.85s cubic-bezier(0.16, 1, 0.3, 1);
        }

        /* Tabs */
        div[data-testid="stTabs"] button[data-baseweb="tab"] {
            border-radius: 6px 6px 0 0 !important;
            padding: 8px 16px !important;
            font-weight: 600 !important;
            font-size: 0.85rem !important;
            letter-spacing: 0.02em !important;
            transition: all 0.2s ease !important;
        }
        div[data-testid="stTabs"] button[data-baseweb="tab"]:hover {
            background-color: rgba(59, 130, 246, 0.06) !important;
        }
        div[data-testid="stTabs"] div[data-baseweb="tab-panel"] {
            animation: fadeInUp 0.35s cubic-bezier(0.16, 1, 0.3, 1);
            padding-top: 10px !important;
        }

        /* Chart Containers */
        div[data-testid="stPlotlyChart"] {
            border: 1px solid rgba(148, 163, 184, 0.16);
            border-radius: 10px;
            padding: 6px;
            background: rgba(255, 255, 255, 0.015);
            transition: box-shadow 0.2s ease;
            animation: fadeInUp 0.4s ease both;
        }
        div[data-testid="stPlotlyChart"]:hover {
            box-shadow: 0 6px 16px -6px rgba(15, 23, 42, 0.1);
        }

        /* Aspect Tags */
        .aspect-chip {
            display: inline-block;
            padding: 4px 11px;
            border-radius: 6px;
            font-size: 0.8rem;
            font-weight: 600;
            margin: 3px 6px 3px 0;
        }
        .aspect-pos { background: rgba(16, 185, 129, 0.12); color: #059669; border: 1px solid rgba(16, 185, 129, 0.3); }
        .aspect-neu { background: rgba(245, 158, 11, 0.12); color: #d97706; border: 1px solid rgba(245, 158, 11, 0.3); }
        .aspect-neg { background: rgba(239, 68, 68, 0.12); color: #dc2626; border: 1px solid rgba(239, 68, 68, 0.3); }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _style_figure(fig, height: int = 360):
    """Apply clean, minimalist styling and smooth transitions to Plotly charts."""
    fig.update_layout(
        height=height,
        margin=dict(l=16, r=16, t=42, b=20),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Segoe UI, Inter, system-ui, sans-serif", size=12),
        title_font=dict(size=14, family="Segoe UI, Inter, system-ui, sans-serif"),
        hoverlabel=dict(bgcolor="#0f172a", font_size=12, font_family="Segoe UI, sans-serif"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        transition={"duration": 400, "easing": "cubic-in-out"},
    )
    fig.update_xaxes(showgrid=True, gridcolor="rgba(148, 163, 184, 0.12)", zeroline=False)
    fig.update_yaxes(showgrid=True, gridcolor="rgba(148, 163, 184, 0.12)", zeroline=False)
    return fig


@st.cache_resource(show_spinner=False)
def get_nlp_pipeline() -> SentimentNLPPipeline:
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
def load_local_raw_reviews(selected_platform: str = "Tất cả nguồn") -> pd.DataFrame:
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


def render_header():
    """Render minimalist executive header."""
    st.markdown(
        """
        <div class="app-header">
            <div>
                <div class="app-header-title">HỆ THỐNG THU THẬP & PHÂN TÍCH ĐÁNH GIÁ</div>
                <div class="app-header-sub">Thu thập dữ liệu đa nguồn (Tiki, Google Play, App Store) & Phân tích cảm xúc NLP (Linear SVM)</div>
            </div>
            <div class="meta-pills">
                <span class="meta-pill">MODEL: 3_Max_Single_F1_SVM</span>
                <span class="meta-pill">VOCAB: 70K VN</span>
                <span class="meta-pill">ABSA: 8 KHÍA CẠNH</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_kpi_bar(frame: pd.DataFrame):
    """Render 5 minimalist animated KPI cards."""
    total_reviews = len(frame)
    valid_mask = frame["quality_status"].isin(["VALID_TEXT", "VALID_PRE_CONSUMPTION", "EMOJI_ONLY"])
    valid_count = int(valid_mask.sum())
    empty_count = int((frame["quality_status"] == "EMPTY_COMMENT").sum())
    filtered_noise_count = total_reviews - valid_count - empty_count

    valid_df = frame[valid_mask]
    pos_count = int((valid_df["sentiment_label"] == "Positive").sum())
    neu_count = int((valid_df["sentiment_label"] == "Neutral").sum())
    neg_count = int((valid_df["sentiment_label"] == "Negative").sum())
    denom = max(valid_count, 1)

    valid_pct = valid_count / max(total_reviews, 1) * 100
    pos_pct = pos_count / denom * 100
    neu_pct = neu_count / denom * 100
    neg_pct = neg_count / denom * 100
    avg_score = float(valid_df["sentiment_score"].mean()) if not valid_df.empty else 0.50

    st.markdown(
        f"""
        <div class="kpi-grid">
            <div class="kpi-card">
                <div class="kpi-label">Tổng bản ghi</div>
                <div class="kpi-value">{total_reviews:,}</div>
                <div class="kpi-sub">Trống: {empty_count:,} · Lọc nhiễu: {filtered_noise_count:,}</div>
                <div class="kpi-bar-bg"><div class="kpi-bar-fill" style="width: 100%; background: #3b82f6;"></div></div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">Văn bản hợp lệ</div>
                <div class="kpi-value">{valid_count:,}</div>
                <div class="kpi-sub">{valid_pct:.1f}% tổng dữ liệu</div>
                <div class="kpi-bar-bg"><div class="kpi-bar-fill" style="width: {min(valid_pct, 100):.1f}%; background: #6366f1;"></div></div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">Positive (Tích cực)</div>
                <div class="kpi-value" style="color: #10b981;">{pos_count:,}</div>
                <div class="kpi-sub">{pos_pct:.1f}% văn bản hợp lệ</div>
                <div class="kpi-bar-bg"><div class="kpi-bar-fill" style="width: {min(pos_pct, 100):.1f}%; background: #10b981;"></div></div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">Neutral (Trung tính)</div>
                <div class="kpi-value" style="color: #f59e0b;">{neu_count:,}</div>
                <div class="kpi-sub">{neu_pct:.1f}% văn bản hợp lệ</div>
                <div class="kpi-bar-bg"><div class="kpi-bar-fill" style="width: {min(neu_pct, 100):.1f}%; background: #f59e0b;"></div></div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">Negative (Tiêu cực)</div>
                <div class="kpi-value" style="color: #ef4444;">{neg_count:,}</div>
                <div class="kpi-sub">{neg_pct:.1f}% · Điểm SVM TB: {avg_score:.2f}</div>
                <div class="kpi-bar-bg"><div class="kpi-bar-fill" style="width: {min(neg_pct, 100):.1f}%; background: #ef4444;"></div></div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_nlp_analysis_tab(frame: pd.DataFrame):
    """Unified NLP section containing 3 switchable sub-tabs."""
    sub_overview, sub_aspects, sub_quality = st.tabs([
        "01. TỔNG QUAN CẢM XÚC",
        "02. KHÍA CẠNH & TỪ KHÓA",
        "03. CHẤT LƯỢNG & ĐỐI CHIẾU",
    ])

    valid_statuses = {"VALID_TEXT", "VALID_PRE_CONSUMPTION", "EMOJI_ONLY"}

    # --- SUB-TAB 1: TỔNG QUAN CẢM XÚC ---
    with sub_overview:
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
            st.plotly_chart(_style_figure(fig_sbar), use_container_width=True)

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
                st.plotly_chart(_style_figure(fig_spie), use_container_width=True)
            else:
                st.info("Không có dữ liệu hợp lệ.")

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
                    title="Phân phối điểm SVM (Sentiment Score 0.0 – 1.0)",
                    labels={"sentiment_score": "Sentiment Score"},
                )
                st.plotly_chart(_style_figure(fig_hist), use_container_width=True)

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
                st.plotly_chart(_style_figure(fig_box), use_container_width=True)

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
            st.plotly_chart(_style_figure(fig_strend, height=360), use_container_width=True)

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
                st.plotly_chart(_style_figure(fig_asp, height=380), use_container_width=True)

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
                    color_discrete_sequence=["#10b981"],
                    title=f"Top {len(top_pos)} từ khóa — Positive",
                )
                st.plotly_chart(_style_figure(fig_kw_pos, height=370), use_container_width=True)
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
                    color_discrete_sequence=["#ef4444"],
                    title=f"Top {len(top_neg)} từ khóa — Negative",
                )
                st.plotly_chart(_style_figure(fig_kw_neg, height=370), use_container_width=True)
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
                lambda k: QUALITY_STATUS_VI_LABELS.get(str(k), str(k))
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
            st.plotly_chart(_style_figure(fig_qual, height=370), use_container_width=True)

        with col_cross:
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
                st.plotly_chart(_style_figure(fig_cross, height=370), use_container_width=True)
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
        st.plotly_chart(_style_figure(fig_bar), use_container_width=True)

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
        st.plotly_chart(_style_figure(fig_pie), use_container_width=True)

    trend = _daily_rating_percentages(rated)
    if trend.empty:
        st.info("Không có dữ liệu thời gian hợp lệ.")
        return

    fig_trend = px.line(
        trend,
        x="Ngày",
        y="Tỷ lệ (%)",
        color="Mức đánh giá",
        color_discrete_map=RATING_COLORS,
        markers=True,
        title="Tỷ lệ rating tích lũy theo thời gian",
    )
    st.plotly_chart(_style_figure(fig_trend, height=370), use_container_width=True)


def render_data_explorer_tab(frame: pd.DataFrame):
    """Render filterable review table and CSV export."""
    f_col1, f_col2, f_col3, f_col4 = st.columns([1.1, 1.4, 1.1, 1.4])
    with f_col1:
        selected_sentiments = st.multiselect(
            "Nhãn cảm xúc",
            options=["Positive", "Neutral", "Negative"],
            default=["Positive", "Neutral", "Negative"],
        )
    with f_col2:
        all_statuses = sorted(frame["quality_status"].dropna().unique().tolist())
        selected_statuses = st.multiselect(
            "Trạng thái chất lượng",
            options=all_statuses,
            default=all_statuses,
        )
    with f_col3:
        selected_stars = st.multiselect(
            "Mức sao",
            options=[5, 4, 3, 2, 1],
            default=[5, 4, 3, 2, 1],
        )
    with f_col4:
        keyword_query = st.text_input(
            "Tìm từ khóa",
            placeholder="Nhập từ khóa...",
        )

    star_series = frame[DISPLAY_COLUMNS[1]]
    star_mask = star_series.isin(selected_stars) | star_series.isna()
    filtered_table = frame[
        frame["sentiment_label"].isin(selected_sentiments)
        & frame["quality_status"].isin(selected_statuses)
        & star_mask
    ].copy()

    if keyword_query.strip():
        kw = keyword_query.strip().lower()
        filtered_table = filtered_table[
            filtered_table[DISPLAY_COLUMNS[2]].fillna("").astype(str).str.lower().str.contains(kw, regex=False)
            | filtered_table["cleaned_text"].fillna("").astype(str).str.lower().str.contains(kw, regex=False)
        ]

    top_bar_left, top_bar_right = st.columns([3.2, 1])
    with top_bar_left:
        st.caption(f"Hiển thị **{len(filtered_table):,}** / **{len(frame):,}** bản ghi.")
    with top_bar_right:
        csv_bytes = filtered_table.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
        st.download_button(
            "Xuất CSV",
            data=csv_bytes,
            file_name="nlp_processed_reviews.csv",
            mime="text/csv",
            use_container_width=True,
        )

    display_cols = [
        *DISPLAY_COLUMNS,
        "sentiment_label",
        "sentiment_score",
        "cleaned_text",
        "Aspects hiển thị",
        "word_count",
        "quality_status",
    ]
    if "Tên SP/App" in filtered_table.columns:
        display_cols = ["Nền tảng", "Tên SP/App", *display_cols]

    renamed_table = filtered_table[display_cols].rename(
        columns={
            "sentiment_label": "Nhãn cảm xúc",
            "sentiment_score": "Điểm SVM",
            "cleaned_text": "Văn bản chuẩn hóa",
            "Aspects hiển thị": "Khía cạnh",
            "word_count": "Số từ",
            "quality_status": "Trạng thái",
        }
    )
    st.dataframe(renamed_table, use_container_width=True, hide_index=True, height=440)


def render_test_tab():
    """Render single-text NLP testing view."""
    preset_choice = st.selectbox(
        "Mẫu kiểm thử",
        list(TEST_PRESETS.keys()),
    )
    default_text, default_star = TEST_PRESETS[preset_choice]

    c1, c2 = st.columns([3.4, 1])
    with c1:
        sample_text = st.text_area(
            "Văn bản đầu vào",
            value=default_text,
            height=85,
        )
    with c2:
        sample_rating = st.selectbox(
            "Rating giả định",
            [5, 4, 3, 2, 1],
            index=[5, 4, 3, 2, 1].index(default_star),
        )

    if sample_text is not None:
        pipeline = get_nlp_pipeline()
        cleaned, wc, score, label, aspects_json, status = pipeline.analyze_review(
            sample_text, rating=sample_rating
        )

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Nhãn cảm xúc", label)
        m2.metric("Điểm SVM", f"{score:.4f}")
        m3.metric("Số từ", wc)
        m4.metric("Trạng thái", status)

        try:
            aspect_items = json.loads(aspects_json) if aspects_json else []
        except Exception:
            aspect_items = []

        chips_html = ""
        for item in aspect_items:
            if isinstance(item, dict):
                asp = html.escape(str(item.get("aspect", "")))
                sent = str(item.get("sentiment", "neutral")).lower()
                css_cls = "aspect-pos" if sent == "positive" else ("aspect-neg" if sent == "negative" else "aspect-neu")
                chips_html += f'<span class="aspect-chip {css_cls}">{asp.capitalize()}: {sent.upper()}</span>'

        if not chips_html:
            chips_html = '<span class="aspect-chip aspect-neu">Không trích xuất khía cạnh</span>'

        escaped_cleaned = html.escape(cleaned if cleaned else "(rỗng)")
        escaped_status_vi = html.escape(QUALITY_STATUS_VI_LABELS.get(status, status))
        st.markdown(
            f"""
            <div class="kpi-card" style="margin-top: 10px; border-top: 3px solid {SENTIMENT_COLORS.get(label, '#3b82f6')};">
                <div style="margin-bottom: 8px;">
                    <b>Văn bản chuẩn hóa (<code>cleaned_text</code>):</b>
                    <code style="font-size: 0.9rem; padding: 3px 8px; margin-left: 6px; border-radius: 4px;">{escaped_cleaned}</code>
                </div>
                <div style="margin-bottom: 8px;">
                    <b>Trạng thái kiểm soát (<code>quality_status</code>):</b>
                    <span style="margin-left: 6px;">{escaped_status_vi}</span>
                </div>
                <div>
                    <b>Khía cạnh (<code>aspects</code>):</b>
                    <div style="margin-top: 6px;">{chips_html}</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def main():
    st.set_page_config(page_title="Review Crawl & NLP Analytics", page_icon="▪", layout="wide")
    inject_custom_css()
    render_header()

    src_tab_crawl, src_tab_dataset = st.tabs([
        "CRAWL TRỰC TIẾP (URL)",
        "DỮ LIỆU CÓ SẴN (4.550 BẢN GHI)",
    ])

    with src_tab_crawl:
        with st.form("crawl_form"):
            f1, f2, f3, f4 = st.columns([1.2, 2.8, 1.0, 1.1])
            with f1:
                platform = st.selectbox("Nền tảng", ("— Chọn nền tảng —", *PLATFORMS))
            with f2:
                url = st.text_input("URL sản phẩm / ứng dụng", placeholder="https://...")
            with f3:
                limit = st.number_input("Giới hạn bản ghi", min_value=1, max_value=2000, value=100, step=50)
            with f4:
                st.write("")
                submitted = st.form_submit_button("Thu thập & Phân tích", type="primary", use_container_width=True)

        if submitted:
            st.session_state.pop("crawl_results", None)
            if platform not in PLATFORMS:
                st.error("Vui lòng chọn một nền tảng trước khi bắt đầu.")
            elif not url.strip():
                st.error("Vui lòng nhập link sản phẩm hoặc ứng dụng.")
            else:
                try:
                    item_id = extract_item_id(platform, url)
                    with st.spinner("Đang thu thập và xử lý NLP..."):
                        reviews = crawl_reviews(platform, item_id, int(limit))
                    if not reviews:
                        st.warning("Crawler không trả về bình luận nào cho link này.")
                    else:
                        raw_df = pd.DataFrame(reviews)
                        nlp_df = enrich_with_nlp(raw_df, platform=platform)
                        st.session_state["crawl_results"] = {
                            "mode": "live_crawl",
                            "platform": platform,
                            "item_id": item_id,
                            "data": nlp_df,
                        }
                except (ValueError, KeyError) as exc:
                    st.error(f"Không thể xử lý yêu cầu: {exc}")
                except Exception as exc:
                    st.error(f"Crawl thất bại ({type(exc).__name__}): {exc}")

    with src_tab_dataset:
        d_col1, d_col2 = st.columns([3.0, 1.1])
        with d_col1:
            dataset_source = st.selectbox(
                "Nguồn dữ liệu (data/raw)",
                ("Tất cả nguồn (Tiki, Google Play, App Store — 4.550 bản ghi)", *PLATFORMS),
            )
        with d_col2:
            st.write("")
            load_local_btn = st.button(
                "Nạp dữ liệu",
                type="primary",
                use_container_width=True,
            )

        if load_local_btn:
            src_key = "Tất cả nguồn" if dataset_source.startswith("Tất cả") else dataset_source
            with st.spinner("Đang nạp dữ liệu và chạy mô hình NLP..."):
                local_df = load_local_raw_reviews(src_key)
            if local_df.empty:
                st.warning("Không tìm thấy dữ liệu trong data/raw/.")
            else:
                st.session_state["crawl_results"] = {
                    "mode": "local_dataset",
                    "platform": src_key,
                    "item_id": f"{len(local_df):,} bản ghi",
                    "data": local_df,
                }

    result = st.session_state.get("crawl_results")
    if not result:
        st.markdown("---")
        tab_test_only, = st.tabs(["TEST"])
        with tab_test_only:
            render_test_tab()
        return

    frame = result["data"]
    if "sentiment_label" not in frame.columns:
        frame = enrich_with_nlp(frame, platform=result.get("platform"))
        result["data"] = frame

    st.markdown("---")
    header_left, header_right = st.columns([2.2, 1.8])
    with header_left:
        st.markdown(f"#### Nguồn dữ liệu: {result['platform']} — {result['item_id']}")
    with header_right:
        if "Tên SP/App" in frame.columns and frame["Tên SP/App"].nunique() > 1:
            item_options = ["Tất cả sản phẩm / ứng dụng"] + sorted(
                f"{row['Mã SP/App']} — {row['Tên SP/App']}"
                for _, row in frame[["Mã SP/App", "Tên SP/App"]].drop_duplicates().iterrows()
            )
            chosen_item = st.selectbox("Lọc theo đối tượng", item_options, label_visibility="collapsed")
            if chosen_item != "Tất cả sản phẩm / ứng dụng":
                chosen_id = chosen_item.split(" — ", 1)[0]
                frame = frame[frame["Mã SP/App"] == chosen_id].copy()

    render_kpi_bar(frame)

    tab_nlp, tab_rating, tab_data, tab_test = st.tabs([
        "PHÂN TÍCH NLP",
        "THỐNG KÊ RATING",
        "DỮ LIỆU",
        "TEST",
    ])

    with tab_nlp:
        render_nlp_analysis_tab(frame)

    with tab_rating:
        render_rating_tab(frame)

    with tab_data:
        render_data_explorer_tab(frame)

    with tab_test:
        render_test_tab()


if __name__ == "__main__":
    main()
