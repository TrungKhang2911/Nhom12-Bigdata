"""Bộ tiền xử lý văn bản tiếng Việt đa lĩnh vực (Tiki, Google Play, App Store).

Thiết kế tổng quát hóa (Domain-Agnostic) cho mọi ngành hàng Thương mại điện tử
(Sách, Điện tử, Gia dụng, Thời trang, Mỹ phẩm, FMCG, Thú cưng...) và Ứng dụng di động
(Mạng xã hội, Ngân hàng số/Fintech, Game, Tiện ích, Học tập...):
1. Chuẩn hóa Unicode NFKC + NFC và quy tắc đặt dấu thanh tiếng Việt.
2. Loại bỏ các chuỗi hệ thống tự động của sàn (`(*) Đánh giá không tính điểm`, `***`).
3. Chuẩn hóa đơn vị tiền tệ (`100k` -> `100 ngàn`, `2tr` -> `2 triệu`) và số `0`
   viết tắt cho từ phủ định (`0 bị lỗi` -> `không bị lỗi`) TRƯỚC khi xóa chữ số.
4. Quy tắc ngữ pháp tổng quát hóa cho Cấu trúc Phủ định của Khuyết điểm đa ngành
   (VD: `không bị móp méo`, `không giật lag`, `không kích ứng da`, `không xù lông`,
   `không rỉ nước`, `không lỗi vặt`) -> ánh xạ về cụm từ tích cực `tốt_đẹp nguyên_vẹn`
   để mô hình Bag-of-Words / LinearSVC không bị bẫy bởi các từ chỉ lỗi đứng sau từ phủ định.
5. Tự động tương thích mọi môi trường: ưu tiên `pyvi` -> `underthesea` -> Từ điển
   từ ghép nội bộ, đồng thời có fallback an toàn nếu môi trường chạy thiếu `scikit-learn`.
"""
import re
import unicodedata

try:
    from sklearn.base import BaseEstimator, TransformerMixin
except ImportError:
    class BaseEstimator:  # type: ignore[no-redef]
        pass

    class TransformerMixin:  # type: ignore[no-redef]
        pass

try:
    from pyvi import ViTokenizer as _PyViTokenizer
except ImportError:
    _PyViTokenizer = None

try:
    from underthesea import word_tokenize as _uts_word_tokenize
except ImportError:
    _uts_word_tokenize = None


# Từ điển từ ghép đa lĩnh vực dùng làm fallback khi môi trường không cài pyvi
_FALLBACK_COMPOUNDS = (
    'sản phẩm', 'cửa hàng', 'đóng gói', 'giao hàng', 'chất lượng', 'tuyệt vời',
    'hài lòng', 'thất vọng', 'nhân viên', 'nhiệt tình', 'cẩn thận', 'chắc chắn',
    'bình thường', 'không gian', 'phục vụ', 'giá cả', 'hợp lý', 'hợp lí',
    'chính hãng', 'bảo hành', 'đổi trả', 'hoàn tiền', 'thời gian', 'giữ nhiệt',
    'kết nối', 'sử dụng', 'ứng dụng', 'đăng nhập', 'tài khoản', 'thanh toán',
    'chuyển khoản', 'sinh trắc', 'giao dịch', 'ngân hàng', 'quảng cáo', 'hình ảnh',
    'mô tả', 'hương vị', 'nhẹ nhàng', 'phục hồi', 'thân thiện', 'tiếp tục',
    'ủng hộ', 'cảm ơn', 'kích cỡ', 'đơn hàng', 'điện thoại', 'người ta',
    'giật lỗi', 'văng ứng dụng', 'lỗi thoát', 'tuy nhiên', 'bù lại', 'tiếc là',
    'có điều', 'nhưng mà', 'mỗi tội', 'ngoại trừ', 'nói chung', 'bình dân',
    'sạch sẽ', 'dễ thương', 'cải thiện', 'tinh thần', 'khách hàng', 'coi thường',
    'nhắn tin', 'trả lời', 'bắt máy', 'cảm thấy', 'tạm ổn', 'quá trời',
    'khiếu nại', 'giải quyết', 'bình luận', 'ngán ngẩm', 'vô trang', 'kỳ vọng',
    'hi vọng', 'học tập', 'sinh viên', 'nỗ lực', 'thế nào', 'tại sao',
    'câu chuyện', 'thực sự', 'bản thân', 'cảm nhận', 'đơn thuần', 'kĩ năng',
    'kỹ năng', 'làm ăn', 'hoàn thiện', 'rớt hạng', 'thê thảm', 'trung thành',
    'cẩu thả', 'tổng đài', 'liên hệ', 'hỗ trợ', 'kỹ thuật', 'phản hồi',
    'điều khiển', 'con lăn', 'nặng nề', 'thái độ', 'mỏi tay', 'hỏa tốc',
    'tin tưởng', 'ảnh hưởng', 'công việc', 'xuất sắc', 'thắc mắc', 'màng bọc',
    'thực phẩm', 'hành trình', 'bài học', 'cuộc sống', 'kĩ càng', 'kỹ càng',
    'tưởng tượng', 'vân tay', 'bảo vệ', 'hấp dẫn', 'ước mơ', 'trái tim',
    'hữu ích', 'sắc nét', 'nguyên vẹn', 'móp méo', 'trầy xước', 'hư hại',
    'sơ sài', 'bổ ích', 'kích ứng', 'dị ứng', 'phai màu', 'xù lông', 'đường may',
    'chống nước', 'chống ồn', 'âm thanh', 'màn hình', 'bàn phím', 'tai nghe',
    'cập nhật', 'phiên bản', 'giao diện', 'tính năng', 'đồ họa', 'nóng máy',
)


def _tokenize_vietnamese(text: str) -> str:
    """Tách từ tiếng Việt ưu tiên PyVi -> Underthesea -> Từ điển từ ghép đa ngành."""
    if _PyViTokenizer is not None:
        return _PyViTokenizer.tokenize(text)
    if _uts_word_tokenize is not None:
        try:
            return _uts_word_tokenize(text, format="text")
        except Exception:
            pass
    out = text
    for comp in sorted(_FALLBACK_COMPOUNDS, key=len, reverse=True):
        out = re.sub(r'\b' + re.escape(comp) + r'\b', comp.replace(' ', '_'), out)
    return out


class VietnameseSentimentPreprocessor(BaseEstimator, TransformerMixin):
    """Pipeline tiền xử lý đa lĩnh vực cho Tiki, Shopee, Google Play, App Store."""

    def __init__(self, amplify_contrast_clause=True):
        self.amplify_contrast_clause = amplify_contrast_clause

        self.tone_map = {
            'oà': 'òa', 'oá': 'óa', 'oả': 'ỏa', 'oã': 'õa', 'oạ': 'ọa',
            'oè': 'òe', 'oé': 'óe', 'oẻ': 'ỏe', 'oẽ': 'õe', 'oẹ': 'ọe',
            'uỳ': 'ùy', 'uý': 'úy', 'uỷ': 'ủy', 'uỹ': 'ũy', 'uỵ': 'ụy',
        }

        self.teencode_map = {
            'sp': 'sản phẩm', 'spham': 'sản phẩm', 'shop': 'cửa hàng', 'shoppe': 'shopee',
            'ko': 'không', 'k': 'không', 'kh': 'không', 'khg': 'không', 'kg': 'không',
            'hok': 'không', 'hong': 'không', 'hg': 'không', 'kp': 'không phải',
            'dc': 'được', 'đc': 'được', 'dk': 'được', 'đk': 'được',
            'tks': 'cảm ơn', 'thanks': 'cảm ơn', 'thaks': 'cảm ơn', 'thank': 'cảm ơn',
            'thjk': 'thích', 'thik': 'thích', 'thich': 'thích', 'tot': 'tốt', 'thom': 'thơm',
            'okie': 'ok', 'okey': 'ok', 'oke': 'ok', 'oki': 'ok', 'okla': 'ok',
            'gud': 'tốt', 'good': 'tốt', 'gút': 'tốt', 'nice': 'tốt',
            'nv': 'nhân viên', 'nvien': 'nhân viên', 'ship': 'giao hàng',
            'shipper': 'người giao hàng', 'shiper': 'người giao hàng',
            'đh': 'đơn hàng', 'dt': 'điện thoại', 'đt': 'điện thoại',
            'j': 'gì', 'z': 'vậy', 'v': 'vậy', 'bth': 'bình thường', 'bt': 'bình thường',
            'bthuong': 'bình thường', 'cx': 'cũng', 'nma': 'nhưng mà',
            'sz': 'kích cỡ', 'size': 'kích cỡ', 'mik': 'mình', 'mk': 'mình', 'm': 'mình',
            'r': 'rồi', 'wa': 'quá', 'qá': 'quá', 'wá': 'quá', 'lun': 'luôn',
            'clg': 'chất lượng', 'sd': 'sử dụng', 'vs': 'với', 'ngta': 'người ta', 'tui': 'tôi',
            'lag': 'giật lỗi', 'bug': 'lỗi', 'crash': 'văng ứng dụng', 'văng': 'lỗi thoát',
            'cmt': 'bình luận', 'acc': 'tài khoản', 'fb': 'facebook', 'ig': 'instagram',
            'vp': 'văn phòng', 'mn': 'mọi người', 'đep': 'đẹp', 'dsongs': 'đóng',
            'ck': 'chuyển khoản', 'tk': 'tài khoản', 'qc': 'quảng cáo', 'update': 'cập nhật',
        }

        self.pos_emojis = r'(❤️|❤|👍|👍🏻|😍|🥰|😘|😊|😁|😄|🌟|⭐|💯|👏|🎉|💙|:v|:\)+|=\)+|<3)'
        self.neg_emojis = r'(😡|🤬|👎|😢|😭|😤|😞|😔|💔|🤮|💩|:\(+|=\(+|-_-)'

        self.negation_words = {'không', 'chẳng', 'chưa', 'chả', 'kém', 'bất', 'vô', 'đừng', 'chớ'}
        self.contrast_conjunctions = r'\b(nhưng|tuy_nhiên|bù_lại|tiếc_là|có_điều|nhưng_mà|mỗi_tội|ngoại_trừ)\b'

        # Quy tắc ngữ pháp tổng quát: Phủ định + Từ chỉ khuyết điểm đa ngành (TMĐT + Mobile App)
        self.negated_defect_pattern = re.compile(
            r'\b(không|ko|k|khg|kg|chưa|chẳng|0)\s+(bị\s+|hề\s+|có\s+|thấy\s+|gặp\s+)?'
            r'(móp\s*méo|móp|rách|trầy\s*xước|trầy|xước|hư\s*hại|hư|hỏng|lỗi|nhăn|dơ|vỡ|bể|'
            r'rỉ\s*nước|chảy\s*nước|đổ\s*nước|tươm\s*nước|tràn|gãy|giật\s*lag|giật|lag|đơ|văng|'
            r'treo|nóng\s*máy|hao\s*pin|xù\s*lông|phai\s*màu|bai\s*nhão|kích\s*ứng|dị\s*ứng|rè|ồn)\b',
            re.IGNORECASE,
        )

    def normalize_tone(self, text: str) -> str:
        tone_map = getattr(self, 'tone_map', {})
        for old, new in tone_map.items():
            text = text.replace(old, new)
        return text

    def clean_single_text(self, text: str) -> str:
        if not isinstance(text, str):
            return ""

        # Bước 1: Chuẩn hóa Unicode NFKC -> NFC và chữ thường
        text = unicodedata.normalize('NFKC', text)
        text = unicodedata.normalize('NFC', text).lower()
        text = self.normalize_tone(text)

        # Bước 1b: Xóa chuỗi hệ thống tự động của sàn
        text = re.sub(r'\(\*\)\s*đánh giá không tính điểm', ' ', text)

        # Bước 1c: Chuẩn hóa đơn vị tiền ("100k" -> "100 ngàn", "2tr" -> "2 triệu") và số '0' = "không"
        text = re.sub(r'(\d+)\s*k\b', r'\1 ngàn', text)
        text = re.sub(r'(\d+)\s*tr\b', r'\1 triệu', text)
        text = re.sub(
            r'\b0\s+(bị|có|được|dc|đc|thấy|lên|vào|ăn|hiểu|ổn|tốt|hay|đẹp|rách|móp|lỗi|lag|giật)\b',
            r'không \1',
            text,
        )

        # Bước 1d: Chuyển cấu trúc phủ định của khuyết điểm đa ngành -> cụm từ tích cực
        neg_def_pat = getattr(self, 'negated_defect_pattern', None)
        if neg_def_pat is not None:
            text = neg_def_pat.sub(' tốt đẹp nguyên vẹn ', text)

        # Bước 2: Xóa dấu '_' có sẵn và nhãn 'positive'/'negative' chèn sẵn
        text = text.replace('_', ' ').replace(':', ' ')
        text = re.sub(r'\b(positive|negative)\b', ' ', text)

        # Bước 3: Ánh xạ Emoji/Emoticon sang token cảm xúc
        text = re.sub(self.pos_emojis, ' emo_pos ', text)
        text = re.sub(self.neg_emojis, ' emo_neg ', text)

        # Bước 4: Xóa URL, HTML, câu spam nhận xu
        text = re.sub(r'http\S+|www\S+|<[^>]+>|@\S+|#\S+', ' ', text)
        text = re.sub(r'hình ảnh (chỉ )?mang (tính chất|tc).*?(nhận xu|minh họa|lấy điểm)', ' ', text)

        # Bước 5: Giữ lại chữ cái tiếng Việt và khoảng trắng, xóa chữ số
        text = re.sub(r'[^\w\sàáảãạăắằẳẵặâấầẩẫậèéẻẽẹêếềểễệìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵđ_]', ' ', text)
        text = re.sub(r'\d+', ' ', text)

        # Bước 6: Thu gọn ký tự kéo dài liên tiếp ("đẹppp" -> "đẹp")
        text = re.sub(r'(.)\1{2,}', r'\1', text)

        # Bước 7: Chuẩn hóa Teencode
        words = text.split()
        normalized_words = [self.teencode_map.get(w, w) for w in words]
        text = ' '.join(normalized_words)
        text = re.sub(r'\b(\w+)(\s+\1\b)+', r'\1', text)

        # Bước 8: Tách từ tiếng Việt đồng nhất và ghép từ phủ định
        text = _tokenize_vietnamese(text)
        tokens = text.split()
        merged_tokens = []
        i = 0
        while i < len(tokens):
            if tokens[i] in self.negation_words and (i + 1) < len(tokens):
                merged_tokens.append(f"{tokens[i]}_{tokens[i+1]}")
                i += 2
            else:
                merged_tokens.append(tokens[i])
                i += 1
        text = ' '.join(merged_tokens)

        # Bước 9: Nhấn mạnh mệnh đề quyết định sau liên từ chuyển ý ("nhưng", "tuy_nhiên")
        if getattr(self, 'amplify_contrast_clause', True):
            parts = re.split(self.contrast_conjunctions, text, maxsplit=1)
            if len(parts) == 3:
                text = f"{parts[0]} {parts[1]} {parts[2]} {parts[2]}"

        return re.sub(r'\s+', ' ', text).strip()

    def fit(self, X, y=None):
        return self

    def transform(self, X):
        return [self.clean_single_text(doc) for doc in X]