"""Giao diện Streamlit: Crawl cuốn chiếu không giới hạn từ URL -> MongoDB -> NLP -> Thống kê dung lượng CSDL."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pandas as pd
import plotly.express as px
import streamlit as st

from src.ingestion.url_pipeline import (
    DEFAULT_ATLAS_QUOTA_MB,
    PLATFORM_EXAMPLES,
    PLATFORM_LABELS,
    get_db_storage_info,
    get_platform_data_stats,
    parse_target_url,
    run_url_to_mongo_pipeline,
)
from src.serving import mongo_client

st.set_page_config(
    page_title="Nhóm 12 — Thu thập & Phân tích Cảm xúc",
    page_icon="📊",
    layout="wide",
)

# ============================================================================
# SIDEBAR: CẤU HÌNH HẠN MỨC DUNG LƯỢNG & LÔ NẠP CUỐN CHIẾU
# ============================================================================
with st.sidebar:
    st.header("⚙️ Cấu hình nạp & Dung lượng")
    quota_mb = st.number_input(
        "Hạn mức CSDL (MB)",
        min_value=10.0,
        max_value=100000.0,
        value=DEFAULT_ATLAS_QUOTA_MB,
        step=64.0,
        help="Mặc định 512 MB cho gói MongoDB Atlas M0 miễn phí.",
    )
    batch_size = st.number_input(
        "Kích thước mỗi lô nạp cuốn chiếu",
        min_value=20,
        max_value=1000,
        value=200,
        step=50,
        help="Cứ cào đủ số review này sẽ ghi ngay vào MongoDB và chạy NLP để tiết kiệm RAM.",
    )
    stop_when_remaining_mb = st.number_input(
        "Tự dừng khi CSDL còn dưới (MB)",
        min_value=0.0,
        max_value=200.0,
        value=10.0,
        step=5.0,
        help="Ngưỡng an toàn tránh tràn quota Atlas. Đặt 0 để tắt.",
    )

st.title("📊 Hệ thống Thu thập, Nạp CSDL & Phân tích Cảm xúc")
st.caption(
    "Hỗ trợ Tiki, Google Play, App Store → Nạp cuốn chiếu từng lô vào MongoDB Atlas → NLP 3 nhãn (Positive / Neutral / Negative)"
)

# Thanh trạng thái dung lượng CSDL tổng quan ở đầu trang
top_storage_container = st.container()


def _render_storage_banner(container, storage: dict):
    with container:
        s1, s2, s3, s4 = st.columns(4)
        s1.metric("Dung lượng CSDL đã dùng", f"{storage['used_mb']:.2f} MB", help="storageSize + indexSize trên đĩa")
        s2.metric("Dung lượng CSDL còn lại", f"{storage['remaining_mb']:.2f} MB", help=f"Trên tổng hạn mức {storage['quota_mb']:.0f} MB")
        s3.metric("Dữ liệu logic (dataSize)", f"{storage['data_mb']:.2f} MB", help="Dung lượng chưa nén của toàn bộ document")
        s4.metric("Mức sử dụng CSDL", f"{storage['used_pct']:.1f}%")
        st.progress(min(max(storage["used_pct"] / 100.0, 0.0), 1.0))


try:
    initial_storage = get_db_storage_info(quota_mb=quota_mb)
    _render_storage_banner(top_storage_container, initial_storage)
except Exception as exc:
    top_storage_container.warning(f"Chưa đọc được dung lượng CSDL MongoDB: {exc}")

tab_crawl, tab_explore = st.tabs(["🚀 Thu thập & Nạp CSDL", "🗄️ Khám phá & Thống kê CSDL"])


# ============================================================================
# TAB 1: CRAWL TỪ URL & NẠP CUỐN CHIẾU VÀO MONGODB + NLP
# ============================================================================
with tab_crawl:
    col_form, col_guide = st.columns([2, 1])

    with col_form:
        platform = st.selectbox(
            "1. Chọn nền tảng",
            options=["tiki", "google_play", "app_store"],
            format_func=lambda k: PLATFORM_LABELS[k],
        )

        url_input = st.text_input(
            "2. Nhập URL sản phẩm / ứng dụng (hoặc nhập trực tiếp ID)",
            placeholder=PLATFORM_EXAMPLES[platform],
        )

        if url_input.strip():
            try:
                parsed_id, detected = parse_target_url(platform, url_input)
                extra_txt = f" | Tự nhận diện: {detected}" if detected else ""
                st.success(f"Nhận diện hợp lệ — Mã đối tượng (`item_id`): `{parsed_id}`{extra_txt}")
            except ValueError as err:
                st.warning(str(err))

        unlimited = st.checkbox(
            "♾️ Tải toàn bộ đánh giá của sản phẩm (không giới hạn — nạp cuốn chiếu từng lô)",
            value=False,
        )
        if unlimited:
            if platform == "app_store":
                st.caption("ℹ️ Lưu ý: Apple RSS công khai giới hạn tối đa ~500 đánh giá mỗi ứng dụng.")
            elif platform == "google_play":
                st.caption(
                    "ℹ️ Lưu ý: Ứng dụng lớn trên Google Play có thể có rất nhiều đánh giá; "
                    f"hệ thống sẽ nạp cuốn chiếu {int(batch_size)} dòng/lô và tự dừng nếu CSDL còn dưới {stop_when_remaining_mb:.0f} MB."
                )

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            limit_val = st.number_input(
                "Số lượng tối đa",
                min_value=1,
                max_value=100000,
                value=200,
                step=100,
                disabled=unlimited,
            )
        with c2:
            country = st.text_input("Quốc gia (2 ký tự)", value="vn", max_chars=2)
        with c3:
            language = st.text_input("Ngôn ngữ", value="vi", max_chars=5)
        with c4:
            delay = st.number_input("Độ trễ (giây)", min_value=0.0, max_value=10.0, value=0.5, step=0.1)

        run_nlp = st.checkbox(
            "Tự động chạy NLP phân tích cảm xúc (Positive / Neutral / Negative) & tổng hợp báo cáo ngày",
            value=True,
        )

        start_btn = st.button("🚀 Bắt đầu Crawl & Nạp cuốn chiếu vào CSDL", type="primary", use_container_width=True)

    with col_guide:
        st.info(
            "**Cơ chế nạp cuốn chiếu từng lô:**\n"
            f"- Cứ cào đủ **{int(batch_size)} bình luận** sẽ đẩy ngay vào `raw_reviews` → chạy NLP → lưu vào `reviews` rồi giải phóng RAM.\n"
            "- Sau mỗi lô, giao diện cập nhật trực tiếp **dung lượng đã tải** và **dung lượng CSDL còn lại**.\n"
            f"- Tự động dừng an toàn nếu CSDL còn dưới **{stop_when_remaining_mb:.0f} MB**."
        )
        st.markdown("**Ví dụ URL hợp lệ:**")
        st.code(
            f"Tiki:        {PLATFORM_EXAMPLES['tiki']}\n"
            f"Google Play: {PLATFORM_EXAMPLES['google_play']}\n"
            f"App Store:   {PLATFORM_EXAMPLES['app_store']}",
            language="text",
        )

    if start_btn:
        if not url_input.strip():
            st.error("Vui lòng nhập URL sản phẩm hoặc ứng dụng trước khi chạy.")
        else:
            progress_bar = st.progress(0.0)
            status_box = st.empty()
            live_metrics_box = st.empty()

            def _update_ui(message: str, frac: float):
                status_box.info(message)
                progress_bar.progress(min(max(frac, 0.0), 1.0))

            def _on_batch_done(info: dict):
                st_info = info["storage"]
                with live_metrics_box.container():
                    lm1, lm2, lm3, lm4, lm5 = st.columns(5)
                    lm1.metric("Số lô đã nạp", info["batches"])
                    lm2.metric("Đã tải (review)", f"{info['crawled']:,}")
                    lm3.metric("Dung lượng đã tải", f"{info['downloaded_mb']:.2f} MB")
                    lm4.metric("CSDL đã dùng", f"{st_info['used_mb']:.2f} MB")
                    lm5.metric("CSDL còn lại", f"{st_info['remaining_mb']:.2f} MB")

            try:
                result = run_url_to_mongo_pipeline(
                    source=platform,
                    url_or_id=url_input,
                    limit=None if unlimited else int(limit_val),
                    batch_size=int(batch_size),
                    country=country.strip() or "vn",
                    language=language.strip() or "vi",
                    delay=float(delay),
                    run_nlp=run_nlp,
                    quota_mb=float(quota_mb),
                    stop_when_remaining_mb=float(stop_when_remaining_mb),
                    status_callback=_update_ui,
                    batch_callback=_on_batch_done,
                )
                stats = result["stats"]
                final_storage = result["storage"]

                if stats.get("stopped_due_to_quota"):
                    status_box.warning(
                        f"Đã dừng sớm vì CSDL chạm ngưỡng an toàn! "
                        f"Các lô trước ({stats['crawled']:,} review) đã lưu an toàn cho **{result['item_name'] or result['item_id']}**."
                    )
                else:
                    status_box.success(
                        f"Hoàn tất đợt nạp `{result['run_id']}` cho **{result['item_name'] or result['item_id']}**!"
                    )

                m1, m2, m3, m4, m5, m6 = st.columns(6)
                m1.metric("Đã crawl", f"{stats['crawled']:,}")
                m2.metric("Thêm mới (raw)", f"{stats['raw_inserted']:,}")
                m3.metric("Đã chạy NLP", f"{stats['nlp_processed']:,}")
                m4.metric("Dung lượng đã tải", f"{stats['downloaded_mb']:.2f} MB")
                m5.metric("CSDL đã dùng", f"{final_storage['used_mb']:.2f} MB")
                m6.metric("CSDL còn lại", f"{final_storage['remaining_mb']:.2f} MB")

                if result["sentiment_summary"]:
                    st.subheader("Phân bố cảm xúc của đợt crawl vừa rồi")
                    sent_df = pd.DataFrame(
                        [{"Cảm xúc": k, "Số lượng": v} for k, v in result["sentiment_summary"].items()]
                    )
                    fig = px.bar(
                        sent_df,
                        x="Cảm xúc",
                        y="Số lượng",
                        color="Cảm xúc",
                        color_discrete_map={
                            "Positive": "#2ecc71",
                            "Neutral": "#95a5a6",
                            "Negative": "#e74c3c",
                        },
                    )
                    st.plotly_chart(fig, use_container_width=True)

                if result["sample_reviews"]:
                    st.subheader("Xem trước bình luận vừa xử lý (tối đa 30 dòng)")
                    preview_df = pd.DataFrame(
                        [
                            {
                                "Thời gian": r.get("review_time"),
                                "Sao": r.get("rating"),
                                "Cảm xúc": r.get("sentiment_label"),
                                "Điểm NLP": r.get("sentiment_score"),
                                "Chất lượng": r.get("quality_status"),
                                "Bình luận gốc": r.get("raw_text"),
                                "Khía cạnh": str(r.get("aspects")),
                            }
                            for r in result["sample_reviews"]
                        ]
                    )
                    st.dataframe(preview_df, use_container_width=True)
            except Exception as exc:
                progress_bar.empty()
                status_box.error(f"Lỗi trong quá trình thực thi: {exc}")


# ============================================================================
# TAB 2: KHÁM PHÁ & THỐNG KÊ DỮ LIỆU HIỆN CÓ TRONG MONGODB
# ============================================================================
with tab_explore:
    if st.button("🔄 Làm mới dữ liệu từ MongoDB"):
        st.rerun()

    try:
        db = mongo_client._get_db()
        storage = get_db_storage_info(quota_mb=quota_mb, db=db)

        counts = {
            name: db[name].count_documents({})
            for name in (
                "raw_reviews",
                "reviews",
                "entities",
                "daily_metrics",
                "pipeline_runs",
                "rejected_records",
                "sources",
            )
        }

        k1, k2, k3, k4, k5, k6 = st.columns(6)
        k1.metric("Raw Reviews", f"{counts['raw_reviews']:,}")
        k2.metric("Reviews (đã NLP)", f"{counts['reviews']:,}")
        k3.metric("Sản phẩm / App", f"{counts['entities']:,}")
        k4.metric("Daily Metrics", f"{counts['daily_metrics']:,}")
        k5.metric("CSDL đã dùng", f"{storage['used_mb']:.2f} MB")
        k6.metric("CSDL còn lại", f"{storage['remaining_mb']:.2f} MB")

        st.divider()
        st.subheader("📦 Lượng data đã crawl theo từng nền tảng (Số bản ghi & Dung lượng)")
        st.caption("Chỉ tính toán khi bạn bấm nút bên dưới để không làm chậm quá trình crawl.")
        if st.button("📦 Tính số bản ghi & dung lượng theo nền tảng", key="btn_platform_stats"):
            with st.spinner("Đang thống kê số bản ghi và dung lượng BSON theo từng nền tảng..."):
                st.session_state["platform_data_stats"] = get_platform_data_stats(db=db)

        platform_stats = st.session_state.get("platform_data_stats")
        if platform_stats:
            df_plat = pd.DataFrame(
                [
                    {
                        "Nền tảng": r["platform_name"],
                        "Sản phẩm / App": r["entity_count"],
                        "Bản ghi thô (raw_reviews)": r["raw_count"],
                        "Dung lượng thô (MB)": r["raw_mb"],
                        "Bản ghi đã NLP (reviews)": r["nlp_count"],
                        "Dung lượng NLP (MB)": r["nlp_mb"],
                        "Tổng dung lượng (MB)": r["total_mb"],
                    }
                    for r in platform_stats
                ]
            )
            st.dataframe(df_plat, use_container_width=True, hide_index=True)

            p_col1, p_col2 = st.columns(2)
            with p_col1:
                fig_p_cnt = px.bar(
                    df_plat,
                    x="Nền tảng",
                    y="Bản ghi thô (raw_reviews)",
                    color="Nền tảng",
                    title="Số bản ghi đã crawl theo nền tảng",
                )
                st.plotly_chart(fig_p_cnt, use_container_width=True)
            with p_col2:
                fig_p_mb = px.bar(
                    df_plat,
                    x="Nền tảng",
                    y="Tổng dung lượng (MB)",
                    color="Nền tảng",
                    title="Tổng dung lượng BSON (MB) theo nền tảng",
                )
                st.plotly_chart(fig_p_mb, use_container_width=True)

        st.divider()

        col_left, col_right = st.columns(2)

        with col_left:
            st.subheader("Phân bố cảm xúc (Collection `reviews`)")
            sent_rows = list(
                db.reviews.aggregate(
                    [
                        {"$group": {"_id": "$sentiment_label", "count": {"$sum": 1}}},
                        {"$sort": {"count": -1}},
                    ]
                )
            )
            if sent_rows:
                df_sent = pd.DataFrame(
                    [{"Cảm xúc": r["_id"] or "Unknown", "Số lượng": r["count"]} for r in sent_rows]
                )
                fig_sent = px.pie(
                    df_sent,
                    names="Cảm xúc",
                    values="Số lượng",
                    color="Cảm xúc",
                    color_discrete_map={
                        "Positive": "#2ecc71",
                        "Neutral": "#95a5a6",
                        "Negative": "#e74c3c",
                    },
                )
                st.plotly_chart(fig_sent, use_container_width=True)
            else:
                st.info("Chưa có dữ liệu trong collection `reviews`. Hãy crawl ở Tab 1 để nạp dữ liệu.")

        with col_right:
            st.subheader("Số lượng bình luận theo nền tảng")
            src_rows = list(
                db.raw_reviews.aggregate(
                    [
                        {"$group": {"_id": "$source_domain", "count": {"$sum": 1}}},
                        {"$sort": {"count": -1}},
                    ]
                )
            )
            if src_rows:
                df_src = pd.DataFrame(
                    [
                        {"Nền tảng": PLATFORM_LABELS.get(r["_id"], r["_id"]), "Số lượng": r["count"]}
                        for r in src_rows
                    ]
                )
                fig_src = px.bar(df_src, x="Nền tảng", y="Số lượng", color="Nền tảng")
                st.plotly_chart(fig_src, use_container_width=True)
            else:
                st.info("Chưa có dữ liệu trong collection `raw_reviews`.")

        st.subheader("Danh sách sản phẩm / ứng dụng (`entities`)")
        entities_docs = list(db.entities.find({}, {"raw_metadata": 0}).sort("last_seen_at", -1).limit(50))
        if entities_docs:
            st.dataframe(pd.DataFrame(entities_docs), use_container_width=True)
        else:
            st.info("Chưa có entity nào.")

        st.subheader("Xem nhanh bình luận đã phân tích (`reviews`)")
        f1, f2 = st.columns(2)
        with f1:
            filter_source = st.selectbox("Lọc theo nguồn", ["Tất cả", "tiki", "google_play", "app_store"])
        with f2:
            filter_sentiment = st.selectbox("Lọc theo cảm xúc", ["Tất cả", "Positive", "Neutral", "Negative"])

        query = {}
        if filter_source != "Tất cả":
            query["source_domain"] = filter_source
        if filter_sentiment != "Tất cả":
            query["sentiment_label"] = filter_sentiment

        review_docs = list(
            db.reviews.find(
                query,
                {
                    "_id": 0,
                    "source_domain": 1,
                    "item_name": 1,
                    "rating": 1,
                    "sentiment_label": 1,
                    "sentiment_score": 1,
                    "quality_status": 1,
                    "review_time": 1,
                    "raw_text": 1,
                },
            )
            .sort("review_time", -1)
            .limit(100)
        )
        if review_docs:
            st.dataframe(pd.DataFrame(review_docs), use_container_width=True)
        else:
            st.info("Không có bình luận nào khớp bộ lọc.")

        st.subheader("Lịch sử các đợt nạp gần nhất (`pipeline_runs`)")
        runs = list(db.pipeline_runs.find({}).sort("started_at", -1).limit(10))
        if runs:
            runs_df = pd.DataFrame(
                [
                    {
                        "run_id": r.get("_id"),
                        "stage": r.get("stage"),
                        "status": r.get("status"),
                        "started_at": r.get("started_at"),
                        "finished_at": r.get("finished_at"),
                        "stats": str(r.get("stats")),
                        "error": r.get("error"),
                    }
                    for r in runs
                ]
            )
            st.dataframe(runs_df, use_container_width=True)
        else:
            st.info("Chưa có lịch sử đợt chạy nào.")

    except Exception as exc:
        st.error(f"Không thể kết nối MongoDB: {exc}")
