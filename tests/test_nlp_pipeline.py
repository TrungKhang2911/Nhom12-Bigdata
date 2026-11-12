"""Kiểm thử tự động cho Bước 5: Xử lý ngôn ngữ & Cảm xúc Đa Lĩnh Vực (`src/processing/nlp_pipeline.py`)."""
import json
from pathlib import Path
import unittest
import pandas as pd

from src.processing.nlp_pipeline import SentimentNLPPipeline, generate_nlp_statistics_report


MODEL_CANDIDATES = [
    Path("models/3_Max_Single_F1_SVM.pkl"),
    Path("/working_dir/c_220e4eeac867edd4/downloads/3_Max_Single_F1_SVM.pkl"),
]
MODEL_PATH = next((p for p in MODEL_CANDIDATES if p.exists()), None)


class TestNLPPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pipeline = SentimentNLPPipeline(model_path=MODEL_PATH)

    def test_null_and_empty_comment_fallback(self):
        cleaned, wc, score, label, aspects, status = self.pipeline.analyze_review(None, rating=5)
        self.assertEqual(cleaned, "")
        self.assertEqual(wc, 0)
        self.assertEqual(label, "Positive")
        self.assertEqual(status, "EMPTY_COMMENT")
        self.assertEqual(aspects, "[]")

        _, _, _, label_3, _, status_3 = self.pipeline.analyze_review("   ", rating=3)
        self.assertEqual(label_3, "Neutral")
        self.assertEqual(status_3, "EMPTY_COMMENT")

    def test_three_star_complaint_classified_as_negative(self):
        text = "bìa sách bị trầy xước! quyển này mình mua để tặng, tiếc quá."
        _, wc, score, label, _, status = self.pipeline.analyze_review(text, rating=3)
        self.assertGreater(wc, 0)
        self.assertEqual(label, "Negative")
        self.assertLess(score, 0.40)
        self.assertEqual(status, "VALID_TEXT")

    def test_off_topic_cross_domain_filtering(self):
        # 1. Đánh giá cát vệ sinh mèo trong trang bán chuột máy tính Tiki
        cat_litter_text = (
            "Bụi nhiều, vón cục xuống thau, cứng, mỗi lần vệ sinh phải cạo, "
            "để bệ phần vón cụng thì nghe mùi khải của nước tiều mè"
        )
        mouse_app_json = json.dumps({"name": "Chuột không dây HXSJ M103", "categories": {"name": "Thiết bị số"}})
        cleaned, wc, _, label, _, status = self.pipeline.analyze_review(
            cat_litter_text, rating=3, source_domain="tiki", app_json=mouse_app_json
        )
        self.assertEqual(cleaned, "")
        self.assertEqual(wc, 0)
        self.assertEqual(label, "Neutral")
        self.assertEqual(status, "FILTERED_OFF_TOPIC")

        # 2. Đánh giá quần áo thời trang dán nhầm vào ứng dụng Ngân hàng trên Google Play
        fashion_in_bank_text = "Áo vải mặc mát lắm, đường kim mũi chỉ may đều, form áo chuẩn"
        bank_app_json = json.dumps({"title": "VCB Digibank", "genre": "Tài chính"})
        _, wc_f, _, _, _, status_f = self.pipeline.analyze_review(
            fashion_in_bank_text, rating=5, source_domain="google_play", app_json=bank_app_json
        )
        self.assertEqual(wc_f, 0)
        self.assertEqual(status_f, "FILTERED_OFF_TOPIC")

    def test_general_gibberish_and_irrelevant_filtering(self):
        # Không cần viết cứng câu vào Regex, bộ lọc độ phủ từ vựng & cấu trúc vẫn bắt được:
        irrelevant_samples = [
            "Good luck and the Chainsmokers là những điều",
            "Justin will come 7-Eleven 6",
            "Vào giường nằm nek em",
            "asdfghjkl qwertyuiop",
            "b nghệ thuật và công nghệ v VCC nó bị hư hỏng nặng vì ưu",
        ]
        for sample in irrelevant_samples:
            _, wc, _, label, _, status = self.pipeline.analyze_review(sample, rating=3)
            self.assertEqual(wc, 0, msg=f"Failed on sample: {sample}")
            self.assertEqual(label, "Neutral")
            self.assertEqual(status, "FILTERED_SPAM_OR_GIBBERISH")

    def test_meaningless_single_char_filtered(self):
        for raw in ("i", "1", "..."):
            cleaned, wc, _, label, _, status = self.pipeline.analyze_review(raw, rating=5)
            self.assertEqual(cleaned, "")
            self.assertEqual(wc, 0)
            self.assertEqual(label, "Neutral")
            self.assertEqual(status, "FILTERED_MEANINGLESS")

    def test_emoji_only_classification(self):
        cleaned, wc, score, label, _, status = self.pipeline.analyze_review("👍👍👍👍", rating=5)
        self.assertEqual(cleaned, "emo_pos")
        self.assertEqual(wc, 1)
        self.assertEqual(label, "Positive")
        self.assertGreater(score, 0.80)
        self.assertEqual(status, "EMOJI_ONLY")

    def test_pre_consumption_classified_as_neutral(self):
        _, wc, score, label, _, status = self.pipeline.analyze_review("Chưa đọc", rating=4)
        self.assertGreater(wc, 0)
        self.assertEqual(label, "Neutral")
        self.assertEqual(score, 0.50)
        self.assertEqual(status, "VALID_PRE_CONSUMPTION")

    def test_negated_defect_and_zero_shorthand_classified_as_positive(self):
        text = "Giao đúng hẹn, sách đóng gói kĩ, không bị móp méo hay rách bìa"
        _, _, score, label, _, status = self.pipeline.analyze_review(text, rating=5)
        self.assertEqual(label, "Positive")
        self.assertGreater(score, 0.65)
        self.assertEqual(status, "VALID_TEXT")

    def test_multi_domain_generalization_banking_gaming_fashion_cosmetics(self):
        # Kiểm tra độ tổng quát trên các ngành hàng mới chưa có trong sample Tiki
        cases = [
            ("App ngân hàng chuyển khoản nhanh, giao diện mượt và dễ dùng", 5, "Positive"),
            ("Cập nhật xong không đăng nhập bằng sinh trắc học được, không nhận được OTP", 1, "Negative"),
            ("Game đồ họa đẹp nhưng ping cao quá, vào giao tranh hơi lag", 3, "Neutral"),
            ("Áo vải mát, mặc vừa form, giao hàng nhanh", 5, "Positive"),
            ("Son lên màu đẹp nhưng hơi khô môi một chút", 4, "Neutral"),
            ("Kem bôi lên bị kích ứng da và nổi mẩn đỏ, quá tệ", 1, "Negative"),
            ("Sách hay. Có thể nhìn thấy mình trong câu chuyện của nhân vật chính.", 5, "Positive"),
        ]
        for text, stars, expected in cases:
            _, wc, _, label, _, status = self.pipeline.analyze_review(text, rating=stars)
            self.assertGreater(wc, 0, msg=f"Zero wc for: {text}")
            self.assertEqual(status, "VALID_TEXT", msg=f"Wrong status for: {text}")
            self.assertEqual(label, expected, msg=f"Expected {expected} but got {label} for: {text}")

    def test_mixed_contrast_clause_classified_as_neutral(self):
        text = "sách rất đẹp nhưng mà không có bọc nên hơi bụi"
        _, _, _, label, aspects_json, _ = self.pipeline.analyze_review(text, rating=5)
        self.assertEqual(label, "Neutral")
        aspects = json.loads(aspects_json)
        aspect_map = {item["aspect"]: item["sentiment"] for item in aspects}
        self.assertEqual(aspect_map.get("chất lượng"), "positive")
        self.assertEqual(aspect_map.get("đóng gói"), "neutral")

    def test_dataframe_batch_and_statistics_report(self):
        df = pd.DataFrame({
            "review_id": [1, 2, 3, 4],
            "review_text": [
                None,
                "Sách hay, đóng gói cẩn thận, giao hàng siêu nhanh",
                "Bình bị rỉ nước, không kín, thất vọng quá trời",
                "Chưa đọc",
            ],
            "rating": [5, 5, 3, 4],
        })
        out = self.pipeline.process_dataframe(df)
        self.assertEqual(list(out["sentiment_label"]), ["Positive", "Positive", "Negative", "Neutral"])
        stats = generate_nlp_statistics_report(out)
        self.assertEqual(stats["total_reviews"], 4)
        self.assertEqual(stats["null_comments_count"], 1)
        self.assertEqual(stats["non_empty_comments_count"], 3)


if __name__ == "__main__":
    unittest.main()