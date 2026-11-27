"""Script độc lập: Thống kê chất lượng dữ liệu thô trên 3 nguồn crawl TRƯỚC khi làm sạch.

Vị trí khuyến nghị trong project: `src/processing/raw_data_quality_stats.py`
Chức năng:
- Tự động quét hoặc nhận đường dẫn 3 nguồn dữ liệu thô (`tiki`, `google_play`, `app_store`
  dưới định dạng `.csv`, `.jsonl`, `.json` hoặc `.xlsx`).
- Thực hiện kiểm toán chất lượng dữ liệu thô (Pre-Cleaning Raw Data Profiling) TRƯỚC khi
  đưa vào `data_cleaner.py` và `nlp_pipeline.py`:
  1. Tổng số bản ghi, số lượng & tỷ lệ `review_text = null` (NaN), rỗng khoảng trắng,
     và số lượng bình luận thực sự có nội dung chữ (`non_empty`).
  2. Số lượng `language = null`, trùng lặp `review_id`, trùng lặp nội dung chính xác
     và trùng lặp sau khi chuẩn hóa chữ thường.
  3. Phân bố chi tiết theo từng mức sao (1 -> 5 sao) tách rõ: Tổng | Có chữ | Null/Rỗng.
  4. Thống kê phân phối độ dài bình luận (số từ: Min, 25%, Median, Mean, 75%, Max).
  5. Thống kê 8 nhóm vấn đề nhiễu tiềm ẩn trong văn bản thô trước khi làm sạch:
     - Chỉ chứa Emoji / Số / Ký tự đặc biệt (không có chữ cái Latin/Tiếng Việt).
     - Bình luận 1 ký tự chữ cái rời rạc (`"i"`, `"a"`).
     - Bình luận cụt lủn 1 từ (`"Ok"`, `"Tốt"`, `"Hay"`).
     - Bình luận ngắn 2 từ (`"Sách hay"`, `"Chưa đọc"`).
     - Dính tiền tố hệ thống sàn TMĐT (`"(*) Đánh giá không tính điểm"`).
     - Chứa từ bị hệ thống che tự động (`"***"`).
     - Nghi ngờ Spam quảng cáo / Gõ phím ngẫu nhiên / Gợi ý bàn phím tiếng Anh.
     - Nghi ngờ mâu thuẫn giữa Số sao và Nội dung chữ (VD: 3-5 sao nhưng phàn nàn lỗi).
  6. Bảng thống kê chi tiết theo từng Sản phẩm / Ứng dụng (`item_id` + Tên từ `app_json`).
- In bảng báo cáo trực quan ra màn hình Terminal và xuất file tổng hợp `.csv` + `.json`.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple
import unicodedata

import numpy as np
import pandas as pd


# Các mẫu Regex phục vụ kiểm toán dữ liệu thô (Pre-cleaning profiling)
_ALPHA_REGEX = re.compile(
    r'[a-zA-Zàáảãạăắằẳẵặâấầẩẫậèéẻẽẹêếềểễệìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵđ]'
)
_VN_VOWEL_REGEX = re.compile(
    r'[aeiouyàáảãạăắằẳẵặâấầẩẫậèéẻẽẹêếềểễệìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵ]',
    re.IGNORECASE,
)
_SYS_PREFIX_REGEX = re.compile(r'\(\*\)\s*đánh giá không tính điểm', re.IGNORECASE)
_CENSORED_REGEX = re.compile(r'\*{2,}')
_SPAM_RAW_REGEX = re.compile(
    r'(vô\s+trang|vay\s*\d+\s*%|kiếm\s+tiền\s+0\s+vốn|nhận\s+free\s+\d+k|ktien|vaytotnhat|'
    r'tặng\s+miễn\s+phí\s+\d+k|hình\s+ảnh\s+(chỉ\s+)?mang\s+(tính\s+chất|tc).*?(nhận\s+xu|minh\s+họa)|'
    r'\b0\d{9}\b)',
    re.IGNORECASE,
)
_RAW_COMPLAINT_CLUES = re.compile(
    r'\b(hư|hỏng|lỗi|tệ|kém|thất\s+vọng|rách|móp|trầy|xước|cẩu\s+thả|sơ\s+sài|'
    r'rỉ\s+nước|chảy\s+nước|tràn|đơ|giật|lag|văng|lừa\s+đảo|không\s+lên|không\s+dùng\s+được|'
    r'ko\s+dùng\s+đc|không\s+hoạt\s+động|không\s+hài\s+lòng|ko\s+ổn|không\s+ổn|bực\s+mình|ức\s+chế)\b',
    re.IGNORECASE,
)
_RAW_NEGATED_DEFECT = re.compile(
    r'\b(không|ko|k|khg|kg|chưa|chẳng|0)\s+(bị\s+|hề\s+|có\s+|thấy\s+)?'
    r'(móp|rách|trầy|xước|hư|hỏng|lỗi|nhăn|dơ|vỡ|bể|rỉ\s+nước|chảy\s+nước|tràn|lag|giật|đơ)\b',
    re.IGNORECASE,
)
_ENGLISH_STOPWORDS = {
    'the', 'and', 'will', 'you', 'know', 'have', 'time', 'for', 'with', 'that',
    'this', 'from', 'justin', 'come', 'luck', 'chainsmokers', 'let',
}


def _extract_item_name(app_json_val: Any) -> str:
    """Trích xuất tên sản phẩm hoặc ứng dụng từ cột `app_json`."""
    if not isinstance(app_json_val, str) or not app_json_val.strip():
        return "Unknown"
    try:
        obj = json.loads(app_json_val)
        if isinstance(obj, dict):
            return str(obj.get("name") or obj.get("title") or obj.get("trackName") or "Unknown")
    except Exception:
        pass
    return "Unknown"


def _is_raw_gibberish_or_spam(text: str) -> bool:
    """Kiểm tra nhanh một bình luận thô có dấu hiệu spam hoặc gõ phím loạn/vô nghĩa không."""
    if _SPAM_RAW_REGEX.search(text):
        return True
    norm = unicodedata.normalize('NFC', unicodedata.normalize('NFKC', text)).lower()
    norm = re.sub(r'([a-zà-ỹ])\1{2,}', r'\1', norm)
    scrubbed = re.sub(r'\b(type-c|win\+d|p/s)\b|:\s*d\b', ' ', norm, flags=re.IGNORECASE)
    words = re.findall(
        r'(?u)\b[a-zA-Zàáảãạăắằẳẵặâấầẩẫậèéẻẽẹêếềểễệìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵđ]+\b',
        scrubbed,
    )
    if not words:
        return False
    for w in words:
        if len(w) >= 6 and not _VN_VOWEL_REGEX.search(w):
            return True
        if len(w) >= 12:
            return True
    eng_hits = sum(1 for w in words if w in _ENGLISH_STOPWORDS)
    if len(words) >= 4 and eng_hits >= 2:
        return True
    if len(words) >= 4 and len(words[0]) == 1 and words[0] not in {'k', 'r', 'v', 'e', 'a', 'ạ', 'ổ', 'ý', 'ở'}:
        return True
    return False


def load_raw_dataset(path: str | Path) -> pd.DataFrame:
    """Đọc file dữ liệu thô hỗ trợ CSV, Excel, JSONL, JSON."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Không tìm thấy file dữ liệu tại: {p}")
    suffix = p.suffix.lower()
    if suffix in (".xlsx", ".xls"):
        return pd.read_excel(p)
    if suffix == ".jsonl":
        return pd.read_json(p, lines=True)
    if suffix == ".json":
        return pd.read_json(p)
    return pd.read_csv(p)


def profile_single_source(df: pd.DataFrame, source_label: str) -> Dict[str, Any]:
    """Tính toán toàn bộ chỉ số thống kê chất lượng bình luận thô cho 1 nguồn."""
    text_col = "review_text" if "review_text" in df.columns else ("raw_text" if "raw_text" in df.columns else "content")
    total_rows = int(len(df))
    null_count = int(df[text_col].isna().sum())
    s_text = df[text_col].fillna("").astype(str)
    empty_ws_count = int((s_text.str.strip() == "").sum() - null_count)
    non_empty_mask = s_text.str.strip() != ""
    non_empty_count = int(non_empty_mask.sum())

    lang_null_count = int(df["language"].isna().sum()) if "language" in df.columns else total_rows
    dup_id_count = int(df.duplicated(subset=["review_id"]).sum()) if "review_id" in df.columns else 0

    non_empty_df = df[non_empty_mask].copy()
    texts = non_empty_df[text_col].astype(str)

    dup_exact = int(non_empty_df.duplicated(subset=[text_col]).sum())
    dup_norm = int(texts.str.lower().str.strip().duplicated().sum())

    # Thống kê độ dài từ trên các dòng có chữ
    word_lengths = texts.str.strip().str.split().str.len()
    if len(word_lengths) > 0:
        w_min = int(word_lengths.min())
        w_p25 = float(np.percentile(word_lengths, 25))
        w_med = float(np.median(word_lengths))
        w_mean = round(float(word_lengths.mean()), 2)
        w_p75 = float(np.percentile(word_lengths, 75))
        w_max = int(word_lengths.max())
    else:
        w_min = w_p25 = w_med = w_mean = w_p75 = w_max = 0

    # 8 nhóm vấn đề chất lượng văn bản thô
    no_alpha_count = int((~texts.str.contains(_ALPHA_REGEX)).sum())
    single_alpha_count = int(
        texts.apply(lambda x: len(_ALPHA_REGEX.findall(x)) == 1).sum()
    )
    one_word_count = int((word_lengths == 1).sum())
    two_word_count = int((word_lengths == 2).sum())
    sys_prefix_count = int(texts.str.contains(_SYS_PREFIX_REGEX).sum())
    censored_count = int(texts.str.contains(_CENSORED_REGEX).sum())
    spam_gibberish_count = int(texts.apply(_is_raw_gibberish_or_spam).sum())

    # Đếm số dòng 3-5 sao nhưng có từ khóa phàn nàn lỗi (sau khi loại trừ phủ định của lỗi như "không bị móp")
    def _has_unnegated_complaint(txt: str) -> bool:
        scrub = _RAW_NEGATED_DEFECT.sub(" ", txt.lower())
        return bool(_RAW_COMPLAINT_CLUES.search(scrub))

    if "rating" in non_empty_df.columns:
        high_star_complaint_count = int(
            non_empty_df[non_empty_df["rating"] >= 3][text_col]
            .astype(str)
            .apply(_has_unnegated_complaint)
            .sum()
        )
        star_3_complaint_count = int(
            non_empty_df[non_empty_df["rating"] == 3][text_col]
            .astype(str)
            .apply(_has_unnegated_complaint)
            .sum()
        )
    else:
        high_star_complaint_count = 0
        star_3_complaint_count = 0

    # Phân bố theo số sao (1 -> 5)
    rating_breakdown: Dict[int, Dict[str, Any]] = {}
    if "rating" in df.columns:
        for r in (1, 2, 3, 4, 5):
            sub = df[df["rating"] == r]
            sub_total = int(len(sub))
            sub_has_text = int((sub[text_col].fillna("").astype(str).str.strip() != "").sum())
            sub_null = sub_total - sub_has_text
            rating_breakdown[r] = {
                "total": sub_total,
                "pct_of_source": round(sub_total / max(total_rows, 1) * 100, 2),
                "non_empty": sub_has_text,
                "null_or_empty": sub_null,
            }

    # Phân bố theo từng sản phẩm / ứng dụng (item_id)
    item_breakdown: List[Dict[str, Any]] = []
    if "item_id" in df.columns:
        for item_id, grp in df.groupby("item_id", sort=False):
            g_total = int(len(grp))
            g_non_empty = int((grp[text_col].fillna("").astype(str).str.strip() != "").sum())
            g_null = g_total - g_non_empty
            item_name = _extract_item_name(grp["app_json"].iloc[0]) if "app_json" in grp.columns else str(item_id)
            item_breakdown.append({
                "item_id": str(item_id),
                "item_name": item_name,
                "total_rows": g_total,
                "non_empty_rows": g_non_empty,
                "non_empty_pct": round(g_non_empty / max(g_total, 1) * 100, 2),
                "null_or_empty_rows": g_null,
                "null_or_empty_pct": round(g_null / max(g_total, 1) * 100, 2),
            })

    return {
        "source_label": source_label,
        "total_rows": total_rows,
        "null_comments_count": null_count,
        "null_comments_pct": round(null_count / max(total_rows, 1) * 100, 2),
        "whitespace_only_count": empty_ws_count,
        "non_empty_comments_count": non_empty_count,
        "non_empty_comments_pct": round(non_empty_count / max(total_rows, 1) * 100, 2),
        "language_null_count": lang_null_count,
        "language_null_pct": round(lang_null_count / max(total_rows, 1) * 100, 2),
        "duplicate_review_id_count": dup_id_count,
        "duplicate_content_exact_count": dup_exact,
        "duplicate_content_norm_count": dup_norm,
        "duplicate_content_norm_pct": round(dup_norm / max(non_empty_count, 1) * 100, 2),
        "word_count_stats": {
            "min": w_min,
            "p25": w_p25,
            "median": w_med,
            "mean": w_mean,
            "p75": w_p75,
            "max": w_max,
        },
        "anomalies": {
            "no_alpha_emoji_or_symbol_only": no_alpha_count,
            "single_alpha_char_only": single_alpha_count,
            "one_word_comments": one_word_count,
            "two_word_comments": two_word_count,
            "tiki_system_prefix_no_score": sys_prefix_count,
            "censored_asterisks": censored_count,
            "suspected_spam_or_gibberish": spam_gibberish_count,
            "star_3_with_complaint_text": star_3_complaint_count,
            "star_3_to_5_with_complaint_text": high_star_complaint_count,
        },
        "rating_breakdown": rating_breakdown,
        "item_breakdown": item_breakdown,
    }


def print_pretty_report(reports: List[Dict[str, Any]]) -> pd.DataFrame:
    """In báo cáo thống kê chất lượng dữ liệu thô ra màn hình Terminal và trả về bảng tổng hợp."""
    print("=" * 95)
    print("BÁO CÁO THỐNG KÊ CHẤT LƯỢNG BÌNH LUẬN THÔ TRÊN 3 NGUỒN CRAWL (TRƯỚC KHI LÀM SẠCH)")
    print("=" * 95)

    summary_rows = []
    for rep in reports:
        anom = rep["anomalies"]
        wc = rep["word_count_stats"]
        summary_rows.append({
            "Nguồn dữ liệu": rep["source_label"],
            "Tổng số dòng": rep["total_rows"],
            "Comment = Null": f"{rep['null_comments_count']} ({rep['null_comments_pct']}%)",
            "Có nội dung chữ": f"{rep['non_empty_comments_count']} ({rep['non_empty_comments_pct']}%)",
            "Language = Null": f"{rep['language_null_count']} ({rep['language_null_pct']}%)",
            "Trùng nội dung": f"{rep['duplicate_content_norm_count']} ({rep['duplicate_content_norm_pct']}%)",
            "Chỉ Emoji/Số/Ký tự": anom["no_alpha_emoji_or_symbol_only"],
            "Cụt lủn 1 từ": anom["one_word_comments"],
            "Ngắn 2 từ": anom["two_word_comments"],
            "Spam/Loạn phím": anom["suspected_spam_or_gibberish"],
            "3-5* nhưng chê": anom["star_3_to_5_with_complaint_text"],
            "Số từ TB (Median)": f"{wc['mean']} ({wc['median']})",
        })

    # Thêm dòng Tổng cộng 3 nguồn
    tot_all = sum(r["total_rows"] for r in reports)
    null_all = sum(r["null_comments_count"] for r in reports)
    non_empty_all = sum(r["non_empty_comments_count"] for r in reports)
    lang_null_all = sum(r["language_null_count"] for r in reports)
    dup_all = sum(r["duplicate_content_norm_count"] for r in reports)
    summary_rows.append({
        "Nguồn dữ liệu": "TỔNG CỘNG (3 NGUỒN)",
        "Tổng số dòng": tot_all,
        "Comment = Null": f"{null_all} ({round(null_all / max(tot_all, 1) * 100, 2)}%)",
        "Có nội dung chữ": f"{non_empty_all} ({round(non_empty_all / max(tot_all, 1) * 100, 2)}%)",
        "Language = Null": f"{lang_null_all} ({round(lang_null_all / max(tot_all, 1) * 100, 2)}%)",
        "Trùng nội dung": f"{dup_all} ({round(dup_all / max(non_empty_all, 1) * 100, 2)}%)",
        "Chỉ Emoji/Số/Ký tự": sum(r["anomalies"]["no_alpha_emoji_or_symbol_only"] for r in reports),
        "Cụt lủn 1 từ": sum(r["anomalies"]["one_word_comments"] for r in reports),
        "Ngắn 2 từ": sum(r["anomalies"]["two_word_comments"] for r in reports),
        "Spam/Loạn phím": sum(r["anomalies"]["suspected_spam_or_gibberish"] for r in reports),
        "3-5* nhưng chê": sum(r["anomalies"]["star_3_to_5_with_complaint_text"] for r in reports),
        "Số từ TB (Median)": "-",
    })

    df_summary = pd.DataFrame(summary_rows)
    print("\n1. BẢNG TỔNG HỢP CHẤT LƯỢNG DỮ LIỆU THÔ TOÀN HỆ THỐNG:")
    print(df_summary.to_string(index=False))

    print("\n2. CHI TIẾT PHÂN BỐ THEO SỐ SAO & TỪNG SẢN PHẨM / ỨNG DỤNG:")
    for rep in reports:
        print("-" * 95)
        print(f"[*] Nguồn: {rep['source_label']} (Tổng: {rep['total_rows']} dòng)")
        print("  + Phân bố theo điểm đánh giá (Rating 1 -> 5 sao):")
        for star, s_info in rep["rating_breakdown"].items():
            print(
                f"    - {star} sao: {s_info['total']:4d} dòng ({s_info['pct_of_source']:5.2f}%) "
                f"| Có chữ: {s_info['non_empty']:4d} | Null/Rỗng: {s_info['null_or_empty']:4d}"
            )
        print("  + Phân bố theo từng sản phẩm / ứng dụng (item_id):")
        for it in rep["item_breakdown"]:
            print(
                f"    - ID {it['item_id']:<22s} ({it['item_name'][:38]:<38s}): "
                f"Tổng={it['total_rows']:4d} | Có chữ={it['non_empty_rows']:4d} ({it['non_empty_pct']:5.1f}%) "
                f"| Null={it['null_or_empty_rows']:4d} ({it['null_or_empty_pct']:5.1f}%)"
            )
        anom = rep["anomalies"]
        print(
            f"  + Các bất thường văn bản thô cần xử lý: "
            f"Tiền tố '(*) Đánh giá không tính điểm'={anom['tiki_system_prefix_no_score']}, "
            f"Từ bị che '***'={anom['censored_asterisks']}, "
            f"Chỉ có 1 chữ cái={anom['single_alpha_char_only']}, "
            f"3 sao nhưng chê={anom['star_3_with_complaint_text']}"
        )
    print("=" * 95)
    return df_summary


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Thống kê chất lượng bình luận thô trên 3 nguồn crawl trước khi làm sạch."
    )
    parser.add_argument(
        "--tiki",
        default="data/raw/ecommerce_reviews/tiki.csv",
        help="Đường dẫn file dữ liệu Tiki (.csv, .jsonl, .xlsx).",
    )
    parser.add_argument(
        "--gplay",
        default="data/raw/mobile_reviews/google_play.csv",
        help="Đường dẫn file dữ liệu Google Play (.csv, .jsonl, .xlsx).",
    )
    parser.add_argument(
        "--appstore",
        default="data/raw/mobile_reviews/app_store.csv",
        help="Đường dẫn file dữ liệu App Store (.csv, .jsonl, .xlsx).",
    )
    parser.add_argument(
        "--output-csv",
        default="data/gold_processed/raw_quality_summary.csv",
        help="Đường dẫn xuất bảng thống kê tổng hợp ra CSV.",
    )
    parser.add_argument(
        "--output-json",
        default="data/gold_processed/raw_quality_detailed_report.json",
        help="Đường dẫn xuất báo cáo thống kê chi tiết ra JSON.",
    )
    args = parser.parse_args(argv)

    source_configs: List[Tuple[str, str]] = [
        ("Tiki", args.tiki),
        ("Google Play", args.gplay),
        ("App Store", args.appstore),
    ]

    reports: List[Dict[str, Any]] = []
    for label, path_str in source_configs:
        p = Path(path_str)
        if p.exists():
            df = load_raw_dataset(p)
            reports.append(profile_single_source(df, label))
        else:
            print(f"[!] Cảnh báo: Bỏ qua nguồn '{label}' vì chưa tìm thấy file tại '{p}'")

    if not reports:
        raise FileNotFoundError("Không tìm thấy bất kỳ file dữ liệu đầu vào nào để thống kê.")

    df_summary = print_pretty_report(reports)

    if args.output_csv:
        out_csv = Path(args.output_csv)
        out_csv.parent.mkdir(parents=True, exist_ok=True)
        df_summary.to_csv(out_csv, index=False, encoding="utf-8-sig")
        print(f"[+] Đã lưu bảng tổng hợp CSV tại: {out_csv}")

    if args.output_json:
        out_json = Path(args.output_json)
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[+] Đã lưu báo cáo chi tiết JSON tại: {out_json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())