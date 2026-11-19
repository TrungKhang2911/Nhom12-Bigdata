"""Short, evidence-based buying guidance from one product's analyzed reviews."""
from collections import Counter
import json

import pandas as pd


def build_purchase_advice(frame, rating_col="rating", *, single_product=True, is_app=False):
    """Summarize observed reviews; never infer features, price or unobserved facts."""
    result = {"tone": "consider", "title": "Nên xem xét kỹ hơn", "summary": "",
              "reasons": [], "concerns": [], "positives": [], "total": len(frame),
              "valid": 0, "counts": {}, "average": None, "rated": 0}
    if not single_product:
        result.update(tone="insufficient", title="Chọn một sản phẩm để nhận gợi ý",
                      summary="Bạn đang xem nhiều sản phẩm hoặc chưa xác định được sản phẩm. Hãy chọn một sản phẩm / ứng dụng ở phía trên hoặc dán đường dẫn cụ thể.")
        return result

    # Exclude empty, filtered, emoji-only and pre-consumption reviews from buying evidence.
    valid = frame[frame["quality_status"].eq("VALID_TEXT")
                  & frame["sentiment_label"].isin(["Positive", "Neutral", "Negative"])]
    count = len(valid)
    counts = valid["sentiment_label"].value_counts().reindex(["Positive", "Neutral", "Negative"], fill_value=0)
    ratings = pd.to_numeric(frame[rating_col], errors="coerce")
    ratings = ratings[ratings.isin([1, 2, 3, 4, 5])]
    average = float(ratings.mean()) if len(ratings) else None
    result.update(valid=count, counts={k: int(v) for k, v in counts.items()},
                  average=average, rated=len(ratings))
    if count:
        pos, neutral, neg = (float(counts[k] / count) for k in ["Positive", "Neutral", "Negative"])
        result["reasons"].append(f"Trong {count:,} bình luận hợp lệ: {pos:.0%} tích cực, {neutral:.0%} trung tính và {neg:.0%} tiêu cực.")
    if average is not None:
        result["reasons"].append(f"Điểm trung bình {average:.2f}/5 từ {len(ratings):,} đánh giá có sao, gồm cả đánh giá không có nội dung.")
    else:
        result["reasons"].append("Chưa có điểm sao hợp lệ để đối chiếu.")
    excluded = len(frame) - count
    result["reasons"].append(f"Không dùng {excluded:,} bình luận trống, bị lọc, chỉ có biểu tượng hoặc chưa trải nghiệm để kết luận mua hàng.")

    aspect_counts = {"negative": Counter(), "positive": Counter()}
    for raw in valid.get("aspects", pd.Series(dtype=object)):
        try:
            aspects = json.loads(raw) if isinstance(raw, str) else []
        except (ValueError, TypeError):
            continue
        if not isinstance(aspects, list):
            continue
        seen = set()
        for item in aspects:
            if not isinstance(item, dict):
                continue
            name = str(item.get("aspect", "")).strip().lower()
            sentiment = str(item.get("sentiment", "")).lower()
            if name and name != "chung" and sentiment in aspect_counts and (name, sentiment) not in seen:
                aspect_counts[sentiment][name] += 1
                seen.add((name, sentiment))
    result["concerns"] = aspect_counts["negative"].most_common(2)
    result["positives"] = aspect_counts["positive"].most_common(2)

    if count < 10 or count / max(len(frame), 1) < .30:
        result.update(tone="insufficient", title="Chưa đủ cơ sở để khuyên mua" if not is_app else "Chưa đủ cơ sở để gợi ý sử dụng",
                      summary=f"Hiện chỉ có {count:,}/{len(frame):,} bình luận hợp lệ đã có trải nghiệm. Bạn nên thu thập thêm đánh giá trước khi quyết định.")
        return result

    low_star = float(ratings.le(2).mean()) if len(ratings) else 0.0
    star_warning = len(ratings) >= 10 and (average < 3.0 or low_star >= .40)
    star_support = not len(ratings) or (average >= 4.0 and low_star <= .20)
    if neg >= .40 or star_warning:
        result.update(tone="negative", title="Chưa nên ưu tiên sản phẩm này" if not is_app else "Chưa nên ưu tiên ứng dụng này")
        reason = f"{neg:.0%} bình luận hợp lệ mang cảm xúc tiêu cực" if neg >= .40 else f"điểm trung bình chỉ {average:.2f}/5 và tỷ lệ 1–2 sao là {low_star:.0%}"
        result["summary"] = f"Bạn nên cân nhắc lựa chọn khác hoặc đọc kỹ phản hồi trước khi quyết định, vì {reason}."
    elif pos >= .70 and neg <= .15 and star_support:
        result.update(tone="positive", title="Có thể cân nhắc mua" if not is_app else "Có thể cân nhắc trải nghiệm",
                      summary=f"Đánh giá đang nghiêng về tích cực ({pos:.0%} trong {count:,} bình luận hợp lệ). Bạn có thể cân nhắc nếu phù hợp nhu cầu" + (f", với điểm trung bình {average:.2f}/5." if average is not None else "; hiện chưa có điểm sao để đối chiếu."))
    else:
        reason = f"{neutral:.0%} bình luận hợp lệ là trung tính" if neutral >= .40 else "ý kiến còn trái chiều hoặc điểm sao chưa đồng thuận với nội dung"
        result["summary"] = f"Bạn nên xem xét kỹ hơn vì {reason}. Hãy đọc các điểm khen/chê và đối chiếu nhu cầu trước khi quyết định."
    if result["concerns"]:
        names = ", ".join(name for name, _ in result["concerns"])
        result["summary"] += f" Điểm cần xem kỹ: {names}."
    return result
