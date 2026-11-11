"""Streamlit demo for collecting and exploring product/app reviews."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

import pandas as pd
import plotly.express as px
import streamlit as st

PLATFORMS = ("Tiki", "Google Play", "App Store")
PLATFORM_HOSTS = {
    "Tiki": ("tiki.vn",),
    "Google Play": ("play.google.com",),
    "App Store": ("apps.apple.com", "itunes.apple.com"),
}
DISPLAY_COLUMNS = ("Tên người dùng", "Đánh giá (sao)", "Nội dung comment")
REVIEW_TIME_COLUMN = "Thời gian đánh giá"
RATING_COLORS = {
    "1 sao": "#d62728",
    "2 sao": "#ff7f0e",
    "3 sao": "#bcbd22",
    "4 sao": "#1f77b4",
    "5 sao": "#2ca02c",
}


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


def main():
    st.set_page_config(page_title="Review Crawl & Analysis", page_icon="📊", layout="wide")
    st.title("Thu thập & phân tích đánh giá")
    st.write("Crawl bình luận và điểm đánh giá từ Tiki, Google Play hoặc App Store.")

    with st.form("crawl_form"):
        platform = st.selectbox("Nền tảng", ("— Chọn nền tảng —", *PLATFORMS))
        url = st.text_input("Link sản phẩm / ứng dụng", placeholder="Dán URL tại đây")
        limit = st.number_input("Số bình luận tối đa", min_value=1, max_value=2000, value=100, step=50)
        submitted = st.form_submit_button("Bắt đầu Crawl & Phân tích", type="primary")

    if submitted:
        st.session_state.pop("crawl_results", None)
        if platform not in PLATFORMS:
            st.error("Vui lòng chọn một nền tảng trước khi bắt đầu.")
        elif not url.strip():
            st.error("Vui lòng nhập link sản phẩm hoặc ứng dụng.")
        else:
            try:
                item_id = extract_item_id(platform, url)
                with st.spinner("Đang thu thập dữ liệu..."):
                    reviews = crawl_reviews(platform, item_id, int(limit))
                if not reviews:
                    st.warning("Crawler không trả về bình luận nào cho link này.")
                else:
                    st.session_state["crawl_results"] = {
                        "platform": platform,
                        "item_id": item_id,
                        "data": pd.DataFrame(reviews, columns=(*DISPLAY_COLUMNS, REVIEW_TIME_COLUMN)),
                    }
            except (ValueError, KeyError) as exc:
                st.error(f"Không thể xử lý yêu cầu: {exc}")
            except Exception as exc:
                st.error(f"Crawl thất bại ({type(exc).__name__}): {exc}")

    result = st.session_state.get("crawl_results")
    if not result:
        return

    frame = result["data"]
    st.subheader(f"Kết quả: {result['platform']} · {result['item_id']}")
    st.caption(f"Đã thu thập {len(frame):,} bình luận.")
    st.dataframe(frame[list(DISPLAY_COLUMNS)], use_container_width=True, hide_index=True)

    rated = frame.dropna(subset=[DISPLAY_COLUMNS[1]]).copy()
    rated = rated[rated[DISPLAY_COLUMNS[1]].between(1, 5)]
    if rated.empty:
        st.info("Không có dữ liệu rating hợp lệ (1–5 sao) để vẽ biểu đồ.")
        return

    counts = (
        rated[DISPLAY_COLUMNS[1]]
        .value_counts()
        .reindex(range(1, 6), fill_value=0)
        .rename_axis("Số sao")
        .reset_index(name="Số bình luận")
    )
    left, right = st.columns(2)
    with left:
        st.plotly_chart(
            px.bar(counts, x="Số sao", y="Số bình luận", title="Số lượng bình luận theo rating"),
            use_container_width=True,
        )
    with right:
        pie_data = counts[counts["Số bình luận"] > 0]
        st.plotly_chart(
            px.pie(pie_data, names="Số sao", values="Số bình luận",
                   title="Tỷ lệ các mức đánh giá", hole=0.35),
            use_container_width=True,
        )

    trend = _daily_rating_percentages(rated)
    if trend.empty:
        st.info("Không có ngày đánh giá hợp lệ để vẽ biểu đồ xu hướng theo thời gian.")
        return

    st.plotly_chart(
        px.line(
            trend,
            x="Ngày",
            y="Tỷ lệ (%)",
            color="Mức đánh giá",
            color_discrete_map=RATING_COLORS,
            markers=True,
            title="Tỷ lệ rating tích lũy theo thời gian",
        ),
        use_container_width=True,
    )


if __name__ == "__main__":
    main()
