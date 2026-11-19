"""Regression checks for advice grounded in a single product's review evidence."""
import json
import unittest

import pandas as pd
from src.processing.purchase_advisor import build_purchase_advice


def reviews(pos=0, neutral=0, neg=0, rating=5):
    labels = ["Positive"] * pos + ["Neutral"] * neutral + ["Negative"] * neg
    return pd.DataFrame({"sentiment_label": labels, "quality_status": ["VALID_TEXT"] * len(labels),
                         "rating": [rating] * len(labels), "aspects": ["[]"] * len(labels)})


class PurchaseAdvisorTests(unittest.TestCase):
    def test_positive_evidence_and_neutral_majority(self):
        result = build_purchase_advice(reviews(16, 3, 1))
        self.assertEqual(result["tone"], "positive")
        self.assertIn("80%", result["summary"])
        self.assertEqual(result["average"], 5)
        result = build_purchase_advice(reviews(3, 15, 2))
        self.assertEqual(result["tone"], "consider")
        self.assertIn("75%", result["summary"])

    def test_negative_text_and_disagreement_with_stars(self):
        self.assertEqual(build_purchase_advice(reviews(5, 3, 12))["tone"], "negative")
        self.assertEqual(build_purchase_advice(reviews(20, rating=2))["tone"], "negative")
        self.assertEqual(build_purchase_advice(reviews(20, rating=3))["tone"], "consider")

    def test_empty_small_and_poor_quality_samples_do_not_recommend(self):
        for count in (0, 1, 9):
            self.assertEqual(build_purchase_advice(reviews(count))["tone"], "insufficient")
        frame = reviews(100)
        frame.loc[10:, "quality_status"] = "EMPTY_COMMENT"
        result = build_purchase_advice(frame)
        self.assertEqual(result["tone"], "insufficient")
        self.assertEqual(result["valid"], 10)
        for status in ("VALID_PRE_CONSUMPTION", "EMOJI_ONLY", "FILTERED_OFF_TOPIC"):
            frame["quality_status"] = status
            self.assertEqual(build_purchase_advice(frame)["valid"], 0)

    def test_mixed_product_scope_is_blocked(self):
        result = build_purchase_advice(reviews(50), single_product=False)
        self.assertEqual(result["tone"], "insufficient")
        self.assertEqual(result["counts"], {})
        self.assertIn("Chọn một", result["title"])

    def test_missing_and_invalid_stars_are_not_fabricated(self):
        frame = reviews(20)
        frame["rating"] = [None, "bad", 6, 0, 2.5] * 4
        result = build_purchase_advice(frame)
        self.assertIsNone(result["average"])
        self.assertEqual(result["rated"], 0)
        self.assertIn("chưa có điểm sao", result["summary"])

    def test_aspects_count_reviews_and_ignore_malformed_data(self):
        frame = reviews(10, neg=10)
        aspect = {"aspect": "giao hàng", "sentiment": "negative"}
        frame.loc[0, "aspects"] = json.dumps([aspect, aspect])
        frame.loc[1, "aspects"] = json.dumps([aspect])
        frame.loc[2, "aspects"] = "not-json"
        frame.loc[3, "aspects"] = "null"
        frame.loc[4, "aspects"] = json.dumps([7, {"aspect": "chung", "sentiment": "negative"}])
        frame.loc[5, "quality_status"] = "FILTERED_SPAM_OR_GIBBERISH"
        frame.loc[5, "aspects"] = json.dumps([{"aspect": "không có thật", "sentiment": "negative"}])
        result = build_purchase_advice(frame)
        self.assertEqual(result["concerns"], [("giao hàng", 2)])
        self.assertIn("giao hàng", result["summary"])
        self.assertNotIn("không có thật", result["summary"])

    def test_mobile_app_uses_experience_wording(self):
        result = build_purchase_advice(reviews(20), is_app=True)
        self.assertEqual(result["title"], "Có thể cân nhắc trải nghiệm")
        self.assertNotIn("mua", result["summary"])


if __name__ == "__main__":
    unittest.main()
