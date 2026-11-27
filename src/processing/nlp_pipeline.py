"""Module Xử lý Ngôn ngữ Tự nhiên & Phân tích Cảm xúc Đa Lĩnh Vực (Bước 5 - v2.1).

Thiết kế Tổng quát hóa (Domain-Agnostic Architecture) cho toàn bộ dữ liệu crawl từ
**Tiki**, **Google Play**, và **App Store** thuộc bất kỳ thể loại/ngành hàng nào
(Sách, Điện tử, Gia dụng, Thời trang, Mỹ phẩm, Bách hóa, Thú cưng, Mạng xã hội,
Ngân hàng số/Fintech, Game, Giáo dục, Tiện ích...):

1. Tầng Lọc Nhiễu Cấu Trúc & Độ Phủ Từ Vựng 70.000 Từ (Không phụ thuộc câu mẫu cố định):
   - Tách riêng bình luận rỗng (`EMPTY_COMMENT`: `review_text = null` hoặc khoảng trắng).
   - Nhận diện bình luận chỉ chứa Emoji/Emoticon (`EMOJI_ONLY`).
   - Bắt lỗi gõ phím ngẫu nhiên (Keyboard Mash như `Idjdbbdkdb djodjsvosiwhks`, `asdfghjkl`),
     câu tiếng Anh / gợi ý bàn phím tự động (`Ukm I will let you know...`, `Good luck and the Chainsmokers...`,
     `Justin will come 7-Eleven`) dựa trên tỷ lệ độ phủ từ vựng tiếng Việt 70.000 từ (`word_vocab`)
     và cấu trúc âm tiết tiếng Việt.
   - Cổng Kiểm Soát Độ Liên Quan Ngữ Nghĩa (`Lexical Relevance Gatekeeper`): Đảm bảo bình luận
     có ít nhất 1 từ thuộc nhóm Cảm xúc/Đánh giá, HOẶC 1 từ thuộc nhóm Hành vi Mua sắm/Sử dụng
     Sản phẩm/Ứng dụng, HOẶC trùng từ khóa với metadata `app_json` của chính sản phẩm/app đó.
2. Tầng Phát Hiện Đánh Giá Nhầm Ngành Hàng Tự Động (`Cross-Domain Taxonomy Matrix`):
   - Tự động suy luận ngành hàng của sản phẩm/ứng dụng từ `source_domain` và `app_json`
     (`name`, `title`, `categories`, `genre`).
   - Đối chiếu với các nhóm từ khóa độc quyền theo ngành (Thú cưng, Thời trang, Mỹ phẩm,
     Ẩm thực...). Nếu bình luận chứa từ khóa độc quyền của ngành vật lý hoàn toàn khác
     (VD: tả cát vệ sinh mèo trong trang bán chuột máy tính hoặc sách; tả chất vải quần áo
     trong app ngân hàng) -> `FILTERED_OFF_TOPIC`.
3. Tầng Khử Thiên Lệch Danh Từ Miền & Phân Loại 3 Nhãn (`Positive`, `Neutral`, `Negative`):
   - Tự động trung hòa trọng số âm bất hợp lý trên các danh từ trung tính chỉ đối tượng
     (`sách`, `đọc`, `câu_chuyện`, `nhân_vật`, `pin`, `sạc`, `loa`, `máy`, `game`, `đăng_nhập`,
     `vải`, `son`...) trong vector trọng số của `3_Max_Single_F1_SVM.pkl`.
   - Loại trừ cấu trúc giảm nhẹ (`hơi + <tính từ chê>` như `hơi lag`, `hơi nhăn`, `hơi bụi`, `hơi khô`)
     trước khi quét lỗi nặng (`STRONG_NEG_WORDS`), giúp phân định chính xác bình luận góp ý nhẹ
     (`Neutral`) và bình luận phàn nàn lỗi nghiêm trọng (`Negative`).
4. Tầng Trích Xuất Khía Cạnh Đa Ngành (`extract_aspects`):
   - Bao phủ 8 nhóm khía cạnh chung cho cả TMĐT lẫn Mobile App: `chất lượng`, `đóng gói`,
     `giao hàng`, `giá cả`, `dịch vụ`, `hiệu năng & ổn định`, `tính năng & giao diện`,
     và `thiết kế & ngoại hình`.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import pickle
import re
import sys
import types
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
import unicodedata

import numpy as np
import pandas as pd

_CURRENT_DIR = Path(__file__).resolve().parent
_ROOT_DIR = _CURRENT_DIR.parents[1] if len(_CURRENT_DIR.parents) >= 2 else _CURRENT_DIR
for _p in (str(_CURRENT_DIR), str(_ROOT_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from src.processing.vn_text_preprocessor import VietnameseSentimentPreprocessor
except ImportError:
    from vn_text_preprocessor import VietnameseSentimentPreprocessor

if 'vn_text_preprocessor' not in sys.modules:
    _shim = types.ModuleType('vn_text_preprocessor')
    _shim.VietnameseSentimentPreprocessor = VietnameseSentimentPreprocessor
    sys.modules['vn_text_preprocessor'] = _shim
else:
    sys.modules['vn_text_preprocessor'].VietnameseSentimentPreprocessor = VietnameseSentimentPreprocessor


# ============================================================================
# 1. CÁC QUY TẮC NGỮ PHÁP & TỪ ĐIỂN ĐA LĨNH VỰC (TỔNG QUÁT HÓA 100%)
# ============================================================================

# 1.1. Mẫu cấu trúc Spam quảng cáo, tài chính đen, tuyển CTV, link rác, cày xu
SPAM_STRUCTURAL_REGEX = re.compile(
    r'(vô\s+trang|vay\s*\d+\s*%|kiếm\s+tiền\s+(0\s+vốn|online|tại\s+nhà)|'
    r'nhận\s+(free|miễn\s+phí)\s+\d+\s*[km]|ktien|vaytotnhat|tặng\s+miễn\s+phí\s+\d+\s*[km]|'
    r'tuyển\s+(ctv|cộng\s+tác\s+viên)|liên\s+hệ\s+(zalo|telegram|tele)|'
    r'\b0\d{9}\b|'
    r'hình\s+ảnh\s+(chỉ\s+)?mang\s+(tính\s+chất|tc).*?(nhận\s+xu|kiếm\s+xu|minh\s+họa|lấy\s+điểm)|'
    r'comment\s+(nhận|lấy|kiếm)\s+xu|đánh\s+giá\s+(nhận|lấy|kiếm)\s+xu)',
    re.IGNORECASE,
)

# 1.2. Mẫu bình luận khi chưa trải nghiệm sản phẩm / ứng dụng (Tổng quát cho mọi ngành)
PRE_CONSUMPTION_REGEX = re.compile(
    r'(\bchưa\s+(đọc|dùng|xài|sử\s+dụng|thử|mặc|uống|ăn|cài|tải|trải\s+nghiệm|khui|mở\s+hộp)\b|'
    r'\bgiờ\s+mới\s+(đọc|dùng|xài|thử|cài)\b|'
    r'\bđể\s+(đọc|dùng|xài|thử)\s+(thử\s+)?(coi|xem)\b|'
    r'\bmua\s+(bản\s+này\s+)?(để\s+)?(biếu|tặng)\s+nên\s+(k|ko|không|chưa)\s+(biết|rõ)\b)',
    re.IGNORECASE,
)

# 1.3. Cấu trúc Phủ định của Khuyết điểm đa ngành ("không bị móp", "không giật lag", "0 kích ứng")
NEGATED_DEFECT_REGEX = re.compile(
    r'\b(không|ko|k|khg|kg|chưa|chẳng|0)\s+(bị\s+|hề\s+|có\s+|thấy\s+|gặp\s+)?'
    r'(móp\s*méo|móp|rách|trầy\s*xước|trầy|xước|hư\s*hại|hư|hỏng|lỗi|nhăn|dơ|vỡ|bể|'
    r'rỉ\s*nước|chảy\s*nước|đổ\s*nước|tươm\s*nước|tràn|gãy|giật\s*lag|giật|lag|đơ|văng|'
    r'treo|nóng\s*máy|hao\s*pin|xù\s*lông|phai\s*màu|bai\s*nhão|kích\s*ứng|dị\s*ứng|rè|ồn)\b',
    re.IGNORECASE,
)

# 1.4. Quy tắc ngữ pháp tổng quát cho Phàn nàn nhẹ / Góp ý giảm nhẹ ("hơi + <tính từ>", "chưa quá...")
MILD_NEG_WORDS = re.compile(
    r'(\b(hơi|hơi\s+bị)\s+(bụi|cũ|nhăn|cứng|trẹt|sơ\s+sài|lâu|tiếc|chật|rộng|mỏng|khô|ồn|'
    r'nóng|chậm|đắt|lag|giật|đơ|rè|mờ|xước|móp|cong|lệch|khó|kỳ|xỉn|nhỏ|to|nặng|ít)\b|'
    r'\b(không\s+có\s+bọc|ko\s+có\s+bọc|không\s+bọc|chưa\s+cuốn|không\s+quá\s+xuất\s+sắc|'
    r'bám\s+dấu\s+vân\s+tay|đổ\s+mồ\s+hôi|kêu\s+két\s+két|tiền\s+két\s+két|mau\s+hết\s+pin|'
    r'màu\s+xỉn|móp\s+một\s+vài\s+cạnh|cong\s+nhẹ|xước\s+nhẹ|nhăn\s+nhẹ)\b)',
    re.IGNORECASE,
)

# 1.5. Từ khóa Phàn nàn / Lỗi nghiêm trọng (Quét SAU KHI đã tách riêng MILD_NEG_WORDS)
STRONG_NEG_WORDS = re.compile(
    r'\b(hư|hỏng|lỗi|tệ|kém|thất_vọng|thất\s+vọng|rách|móp|trầy|xước|cẩu_thả|cẩu\s+thả|'
    r'sơ_sài|sơ\s+sài|rỉ_nước|rỉ\s+nước|chảy_nước|chảy\s+nước|tràn|đơ|giật|lag|văng|treo|'
    r'sập|khóa\s+tài\s+khoản|bị\s+khóa|trừ\s+tiền|mất\s+tiền|không\s+nhận\s+được\s+otp|'
    r'lừa_đảo|lừa\s+đảo|hàng\s+giả|hàng\s+nhái|pha\s+ke|fake|'
    r'không_lên|không_dùng_được|không_hoạt_động|không_hài_lòng|không\s+vào\s+được|'
    r'ko\s+vào\s+đc|không\s+đăng\s+nhập\s+được|ko\s+ổn|không\s+ổn|không_ổn|'
    r'bực_mình|bực\s+mình|ức_chế|ức\s+chế|quá_tệ|quá\s+tệ|rớt_hạng|thê_thảm|'
    r'không_kín|bị_lỗ|bị\s+1\s+lỗ|in_ngược|giao_thiếu|giao\s+sai|bị\s+dính|'
    r'không\s+như\s+mô\s+tả|không\s+có\s+seal|không\s+thích\s+lắm|không\s+thich\s+lắm|'
    r'không\s+có\s+mapbook|không\s+có\s+bookmark|k\s+có\s+bookmark|ko\s+thấy\s+gói|'
    r'lằn\s+nối|nặng\s+nề|mỏi\s+tay|bị\s+gẫy\s+mép|bị\s+gấp|bị\s+cong|nịnh\s+bợ|'
    r'phai\s+màu|xù\s+lông|kích\s+ứng|dị\s+ứng|nổi\s+mẩn|mùi\s+hôi|ối\s+dồi\s+ôi|chán\s+ốm)\b',
    re.IGNORECASE,
)

# 1.6. Từ khóa Khen ngợi / Tích cực đa ngành (Loại trừ 'good luck')
STRONG_POS_WORDS = re.compile(
    r'\b(tuyệt_vời|tuyệt\s+vời|tuyet\s+voi|xuất_sắc|xuất\s+sắc|rất\s+tốt|rat\s+tot|siêu\s+tốt|'
    r'siêu\s+đẹp|rất\s+đẹp|rất\s+hay|cực\s+kỳ\s+thích|rất\s+thích|rất\s+hài_lòng|rất\s+hài\s+lòng|'
    r'hài\s+lòng|đáng\s+tiền|đáng\s+mua|đáng\s+đọc|đáng\s+để\s+đọc|nên\s+mua|nên\s+muaa|nên\s+đọc|'
    r'ưng\s+quá|ưng\s+ý|quá\s+tốt|quá\s+đẹp|quá\s+hay|quá\s+được|chu_đáo|chu\s+đáo|cẩn_thận|cẩn\s+thận|'
    r'nhiệt_tình|nhiệt\s+tình|xịn|mượt|mượt\s+mà|ngon|nhanh\s+chóng|tiện\s+lợi|dễ\s+dùng|'
    r'sắc\s+nét|rõ\s+nét|độc\s+đáo|chắc\s+chắn|bền|thơm|mát|êm|vừa\s+vặn|vừa\s+form|chuẩn\s+form|'
    r'nhẹ\s+gọn|nhỏ\s+gọn|khỏi\s+phải\s+bàn|miễn\s+bàn|rất\s+ổn|rat\s+lau|rất\s+lâu|hấp\s+dẫn|'
    r'bổ\s+ích|hữu\s+ích|ý\s+nghĩa|sâu\s+sắc|cuốn\s+hút|gối\s+đầu\s+giường|chạm\s+đến\s+trái\s+tim|'
    r'ngay\s+ngắn|mới\s+toanh|ok|oke|oki|okie|good(?!\s+luck)|go+d|nice|like|vip|tốt|tot|hay|đẹp|đep|tuyệt|thích)\b',
    re.IGNORECASE,
)

# 1.7. Biểu thức Đánh giá lưng chừng / Trung tính
NEUTRAL_HEDGE_WORDS = re.compile(
    r'^(ổn|tạm\s+ổn|tạm\s+thời\s+đang\s+ổn|bình\s+thường|cũng\s+ổn|cũng\s+được|cũng\s+ok|'
    r'chấp\s+nhận\s+được|tiền\s+nào\s+của\s+nấy|tiền\s+nào\s+của\s+đó|'
    r'chất\s+lượng\s+như\s+trong\s+hình|như\s+mô\s+tả|ổn\s+giữ\s+nhiệt.*|'
    r'mới\s+dùng.*cũng\s+được|dùng\s+tạm)[\s.!]*$',
    re.IGNORECASE,
)

CONTRAST_WORDS = re.compile(
    r'\b(nhưng|tuy\s+nhiên|tuy_nhiên|bù\s+lại|tiếc\s+là|có\s+điều|nhưng\s+mà|mỗi\s+tội|ngoại\s+trừ|mặc\s+dù|mà\s+đợt\s+này)\b',
    re.IGNORECASE,
)

POS_EMOJI_ONLY = re.compile(r'^(👍|👍🏻|❤️|❤|😍|🥰|😘|😊|😁|😄|🌟|⭐|💯|👏|🎉|💙|:v|:\)+|=\)+|<3|\s)+$')
NEG_EMOJI_ONLY = re.compile(r'^(😡|🤬|👎|😢|😭|😤|😞|😔|💔|🤮|💩|:\(+|=\(+|-_-|\s)+$')

# 1.8. Cổng Kiểm Soát Độ Liên Quan Ngữ Nghĩa (Lexical Relevance Gatekeeper cho mọi ngành)
GENERAL_REVIEW_DOMAIN_WORDS = re.compile(
    r'\b(mua|bán|đặt|giao|chuyển\s+phát|nhận|ship|shipper|shiper|shop|cửa\s+hàng|đóng\s+gói|bọc|hộp|seal|'
    r'hàng|sản\s+phẩm|sp|chất\s+lượng|giá|tiền|rẻ|đắt|sale|khuyến\s+mãi|đơn|đổi\s+trả|bảo\s+hành|'
    r'dùng|xài|sử\s+dụng|cài|tải|mở|đăng\s+nhập|cập\s+nhật|update|phiên\s+bản|app|ứng\s+dụng|'
    r'game|trò\s+chơi|tài\s+khoản|acc|ngân\s+hàng|chuyển\s+khoản|thanh\s+toán|quét\s+mã|otp|'
    r'sinh\s+trắc|quảng\s+cáo|mạng|kết\s+nối|wifi|bluetooth|pin|sạc|máy|điện\s+thoại|màn\s+hình|'
    r'loa|tai\s+nghe|chuột|bàn\s+phím|nút|bình|giữ\s+nhiệt|giu\s+nhiet|nước|nắp|sách|đọc|cuốn|'
    r'quyển|bìa|giấy|trang|in|tác\s+giả|nội\s+dung|truyện|áo|quần|váy|vải|mặc|size|kích\s+cỡ|'
    r'form|giày|son|kem|da|môi|mùi|thơm|dưỡng|tư\s+vấn|nhân\s+viên|hỗ\s+trợ|dịch\s+vụ|sao|điểm|review)\b',
    re.IGNORECASE,
)

# 1.9. Ma trận Từ khóa Độc quyền theo Ngành để bắt lỗi "Râu ông nọ cắm cằm bà kia" (Cross-Domain Off-Topic)
EXCLUSIVE_DOMAIN_SIGNATURES: Dict[str, re.Pattern] = {
    'pet_supplies': re.compile(
        r'\b(cát\s+mèo|nước\s+tiểu\s+mèo|nước\s+tiều\s+mè|vón\s+cục\s+xuống\s+thau|'
        r'thau\s+cát|chó\s+mèo|hạt\s+cho\s+mèo|pate\s+mèo)\b',
        re.IGNORECASE,
    ),
    'fashion_apparel': re.compile(
        r'\b(đường\s+kim\s+mũi\s+chỉ|vải\s+mặc\s+mát|form\s+quần|form\s+áo|'
        r'giặt\s+không\s+xù|ống\s+quần|cổ\s+áo|tay\s+áo)\b',
        re.IGNORECASE,
    ),
    'cosmetics_skincare': re.compile(
        r'\b(nâng\s+tông\s+da|thấm\s+nhanh\s+vào\s+da|lên\s+màu\s+môi|tẩy\s+trang|'
        r'kem\s+chống\s+nắng|dưỡng\s+ẩm\s+da|lỗ\s+chân\s+lông)\b',
        re.IGNORECASE,
    ),
    'food_grocery': re.compile(
        r'\b(nước\s+chấm|thịt\s+mềm|ướp\s+gia\s+vị|chiên\s+giòn|nấu\s+chín|vị\s+chua\s+cay)\b',
        re.IGNORECASE,
    ),
}

# 1.10. Từ điển 8 Khía cạnh Đa Lĩnh Vực (E-commerce + Mobile Apps + Banking + Gaming)
ASPECT_PATTERNS: Dict[str, re.Pattern] = {
    'chất lượng': re.compile(
        r'\b(chất\s*lượng|sản\s*phẩm|sp|hàng|độ\s*bền|chính\s*hãng|sách|giấy|nội\s*dung|'
        r'chuột|con\s*lăn|bình|giữ\s*nhiệt|vải|chất\s*liệu|da|kem|son|mùi\s*hương)\b',
        re.IGNORECASE,
    ),
    'đóng gói': re.compile(
        r'\b(đóng\s*gói|bao\s*bì|bọc|chống\s*sốc|seal|màng\s*co|hộp|bookcare|gói\s*hàng|bao\s*bộc)\b',
        re.IGNORECASE,
    ),
    'giao hàng': re.compile(
        r'\b(giao\s*hàng|vận\s*chuyển|chuyển\s*phát|ship|shipper|shiper|giao\s*nhanh|hỏa\s*tốc|đúng\s*hẹn|giao\s*thiếu)\b',
        re.IGNORECASE,
    ),
    'giá cả': re.compile(
        r'\b(giá|rẻ|đắt|sale|khuyến\s*mãi|đáng\s*tiền|tiền\s*nào\s*của\s*nấy|hợp\s*lý|chi\s*phí|phí)\b',
        re.IGNORECASE,
    ),
    'dịch vụ': re.compile(
        r'\b(dịch\s*vụ|shop|cửa\s*hàng|nhân\s*viên|tư\s*vấn|hỗ\s*trợ|bảo\s*hành|đổi\s*trả|tổng\s*đài|phản\s*hồi|thái\s*độ|cskh)\b',
        re.IGNORECASE,
    ),
    'hiệu năng & ổn định': re.compile(
        r'\b(mượt|lag|giật|đơ|văng|treo|sập|lỗi|bug|tốc\s*độ|nhanh|chậm|pin|sạc|nóng\s*máy|kết\s*nối|bluetooth|wifi|fps|ping)\b',
        re.IGNORECASE,
    ),
    'tính năng & giao diện': re.compile(
        r'\b(app|ứng\s*dụng|tính\s*năng|chức\s*năng|giao\s*diện|cập\s*nhật|đăng\s*nhập|tài\s*khoản|'
        r'chuyển\s*khoản|thanh\s*toán|sinh\s*trắc|otp|quảng\s*cáo|video|reel|story|game|đồ\s*họa)\b',
        re.IGNORECASE,
    ),
    'thiết kế & ngoại hình': re.compile(
        r'\b(thiết\s*kế|kiểu\s*dáng|ngoại\s*hình|màu\s*sắc|màu|bìa|in\s*ấn|form|size|kích\s*cỡ|nắp|vỏ|nhỏ\s*gọn|nhẹ\s*gọn|đẹp)\b',
        re.IGNORECASE,
    ),
}

NEUTRAL_DOMAIN_UNIGRAMS: Set[str] = {
    'sách', 'đọc', 'cuốn', 'quyển', 'trang', 'bìa', 'chương', 'tác_giả', 'nhà_xuất_bản',
    'truyện', 'câu_chuyện', 'nhân_vật', 'máy', 'pin', 'sạc', 'chuột', 'bàn_phím', 'tai_nghe',
    'loa', 'màn_hình', 'cáp', 'dây', 'nút', 'áo', 'quần', 'váy', 'vải', 'size', 'kích_cỡ',
    'form', 'màu', 'giày', 'dép', 'túi', 'da', 'kem', 'son', 'mùi', 'serum', 'dưỡng', 'môi',
    'bình', 'nắp', 'vỏ', 'inox', 'nhựa', 'nồi', 'bếp', 'quạt', 'app', 'ứng_dụng', 'game',
    'trò_chơi', 'tướng', 'map', 'server', 'acc', 'tài_khoản', 'ngân_hàng', 'chuyển_khoản',
    'đăng_nhập', 'cập_nhật', 'phiên_bản', 'giao_dịch', 'thẻ', 'mã',
}


# ============================================================================
# 2. BỘ NẠP MÔ HÌNH AN TOÀN ĐA PHIÊN BẢN & KHỬ THIÊN LỆCH MIỀN
# ============================================================================

class _DummyObj:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    def __setstate__(self, state):
        if isinstance(state, dict):
            self.__dict__.update(state)
        else:
            self._state = state


class _NumpyArrayWrapper(_DummyObj):
    def read_array(self, f):
        alignment = getattr(self, 'numpy_array_alignment_bytes', None)
        if alignment is not None:
            pad_byte = f.read(1)
            pad_len = ord(pad_byte)
            if pad_len > 0:
                f.read(pad_len)
        count = int(np.prod(self.shape))
        nbytes = count * self.dtype.itemsize
        raw = f.read(nbytes)
        arr = np.frombuffer(raw, dtype=self.dtype, count=count).copy()
        return arr.reshape(self.shape, order=self.order)


class _SafeJoblibUnpickler(pickle._Unpickler):
    dispatch = pickle._Unpickler.dispatch.copy()

    def find_class(self, module, name):
        if name == 'NumpyArrayWrapper':
            return _NumpyArrayWrapper
        if module.startswith('numpy'):
            if module.startswith('numpy._core'):
                module = module.replace('numpy._core', 'numpy.core')
            return super().find_class(module, name)
        if module in ('builtins', 'collections', 're', '_collections_abc', 'copyreg', '_codecs'):
            return super().find_class(module, name)
        return type(name, (_DummyObj,), {'__module__': module})

    def load_build(self):
        super().load_build()
        if isinstance(self.stack[-1], _NumpyArrayWrapper):
            wrapper = self.stack.pop()
            arr = wrapper.read_array(self._file_readline.__self__)
            self.stack.append(arr)

    dispatch[pickle.BUILD[0]] = load_build


class StandaloneSVMModel:
    """Thực thi suy luận từ `3_Max_Single_F1_SVM.pkl` kèm cân bằng danh từ đa miền."""

    def __init__(self, model_path: str | Path):
        self.model_path = Path(model_path)
        if not self.model_path.exists():
            raise FileNotFoundError(f"Không tìm thấy file mô hình SVM tại: {self.model_path}")

        with self.model_path.open('rb') as f:
            pipeline_obj = _SafeJoblibUnpickler(f).load()

        clf_pipe = pipeline_obj.steps[1][1]
        feat_union = clf_pipe.steps[0][1]
        svm_clf = clf_pipe.steps[1][1]
        word_vec = feat_union.transformer_list[0][1]
        char_vec = feat_union.transformer_list[1][1]

        self.word_vocab: Dict[str, int] = word_vec.vocabulary_
        self.word_idf: np.ndarray = word_vec._tfidf.idf_
        self.char_vocab: Dict[str, int] = char_vec.vocabulary_
        self.char_idf: np.ndarray = char_vec._tfidf.idf_
        self.coef: np.ndarray = svm_clf.coef_[0].copy()
        self.intercept: float = float(svm_clf.intercept_[0])
        self.word_offset: int = len(self.word_vocab)

        for noun in NEUTRAL_DOMAIN_UNIGRAMS:
            idx = self.word_vocab.get(noun)
            if idx is not None and self.coef[idx] < 0.0:
                self.coef[idx] = 0.0

        negation_words = {'không', 'chẳng', 'chưa', 'chả', 'kém', 'bất', 'vô', 'đừng', 'chớ'}
        self.compound_lookup: Set[str] = set()
        for term in self.word_vocab.keys():
            if ' ' not in term and '_' in term:
                if term.split('_')[0] not in negation_words:
                    self.compound_lookup.add(term.replace('_', ' '))

        self.preprocessor = VietnameseSentimentPreprocessor(amplify_contrast_clause=True)

    def _tokenize_with_vocab_compounds(self, text: str) -> str:
        tokens = text.split()
        n = len(tokens)
        out = []
        i = 0
        while i < n:
            matched = False
            for k in (4, 3, 2):
                if i + k <= n:
                    cand = ' '.join(tokens[i:i + k])
                    if cand in self.compound_lookup:
                        out.append(cand.replace(' ', '_'))
                        i += k
                        matched = True
                        break
            if not matched:
                out.append(tokens[i])
                i += 1
        return ' '.join(out)

    def preprocess(self, raw_text: str) -> str:
        if not isinstance(raw_text, str):
            return ""
        t = unicodedata.normalize('NFKC', raw_text)
        t = unicodedata.normalize('NFC', t).lower()
        t = re.sub(r'\(\*\)\s*đánh giá không tính điểm', ' ', t)
        t = re.sub(r'(\d+)\s*k\b', r'\1 ngàn', t)
        t = re.sub(r'(\d+)\s*tr\b', r'\1 triệu', t)
        t = re.sub(
            r'\b0\s+(bị|có|được|dc|đc|thấy|lên|vào|ăn|hiểu|ổn|tốt|hay|đẹp|rách|móp|lỗi|lag|giật)\b',
            r'không \1',
            t,
        )
        t = NEGATED_DEFECT_REGEX.sub(' tốt đẹp nguyên vẹn ', t)

        for old, new in self.preprocessor.tone_map.items():
            t = t.replace(old, new)

        t = t.replace('_', ' ').replace(':', ' ')
        t = re.sub(r'\b(positive|negative)\b', ' ', t)
        t = re.sub(self.preprocessor.pos_emojis, ' emo_pos ', t)
        t = re.sub(self.preprocessor.neg_emojis, ' emo_neg ', t)
        t = re.sub(r'http\S+|www\S+|<[^>]+>|@\S+|#\S+', ' ', t)
        t = re.sub(r'hình ảnh (chỉ )?mang (tính chất|tc).*?(nhận xu|minh họa|lấy điểm)', ' ', t)
        t = re.sub(r'[^\w\sàáảãạăắằẳẵặâấầẩẫậèéẻẽẹêếềểễệìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵđ_]', ' ', t)
        t = re.sub(r'\d+', ' ', t)
        t = re.sub(r'(.)\1{2,}', r'\1', t)

        words = t.split()
        normalized_words = [self.preprocessor.teencode_map.get(w, w) for w in words]
        t = ' '.join(normalized_words)
        t = re.sub(r'\b(\w+)(\s+\1\b)+', r'\1', t)

        t = self._tokenize_with_vocab_compounds(t)
        tokens = t.split()
        merged_tokens = []
        i = 0
        while i < len(tokens):
            if tokens[i] in self.preprocessor.negation_words and (i + 1) < len(tokens):
                merged_tokens.append(f"{tokens[i]}_{tokens[i+1]}")
                i += 2
            else:
                merged_tokens.append(tokens[i])
                i += 1
        t = ' '.join(merged_tokens)

        if self.preprocessor.amplify_contrast_clause:
            parts = re.split(self.preprocessor.contrast_conjunctions, t, maxsplit=1)
            if len(parts) == 3:
                t = f"{parts[0]} {parts[1]} {parts[2]} {parts[2]}"

        return re.sub(r'\s+', ' ', t).strip()

    def decision_margin(self, cleaned_text: str) -> float:
        tokens = re.findall(r'(?u)\b\w\w+\b', cleaned_text)
        w_counts = Counter()
        n_tok = len(tokens)
        for k in range(1, 5):
            for i in range(n_tok - k + 1):
                ng = ' '.join(tokens[i:i + k])
                idx = self.word_vocab.get(ng)
                if idx is not None:
                    w_counts[idx] += 1

        w_dot = 0.0
        if w_counts:
            w_norm_sq = 0.0
            w_vals = {}
            for idx, c in w_counts.items():
                val = (1.0 + math.log(c)) * self.word_idf[idx]
                w_vals[idx] = val
                w_norm_sq += val * val
            w_norm = math.sqrt(w_norm_sq)
            if w_norm > 0.0:
                for idx, val in w_vals.items():
                    w_dot += (val / w_norm) * self.coef[idx]

        c_counts = Counter()
        for w in cleaned_text.split():
            padded = f" {w} "
            lw = len(padded)
            for k in range(3, 7):
                for i in range(lw - k + 1):
                    ng = padded[i:i + k]
                    idx = self.char_vocab.get(ng)
                    if idx is not None:
                        c_counts[idx] += 1

        c_dot = 0.0
        if c_counts:
            c_norm_sq = 0.0
            c_vals = {}
            for idx, c in c_counts.items():
                val = (1.0 + math.log(c)) * self.char_idf[idx]
                c_vals[idx] = val
                c_norm_sq += val * val
            c_norm = math.sqrt(c_norm_sq)
            if c_norm > 0.0:
                for idx, val in c_vals.items():
                    c_dot += (val / c_norm) * self.coef[self.word_offset + idx]

        return float(w_dot + c_dot + self.intercept)


# ============================================================================
# 3. KIỂM SOÁT CHẤT LƯỢNG CẤU TRÚC, LỌC NHIỄU ĐA NGÀNH & TRÍCH XUẤT KHÍA CẠNH
# ============================================================================

_VN_VOWEL_REGEX = re.compile(
    r'[aeiouyàáảãạăắằẳẵặâấầẩẫậèéẻẽẹêếềểễệìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵ]',
    re.IGNORECASE,
)

# Các từ chức năng tiếng Anh phổ biến xuất hiện khi gõ tự động gợi ý bàn phím (Auto-suggest)
_ENGLISH_STOPWORDS_SET = {
    'the', 'and', 'will', 'you', 'know', 'have', 'time', 'for', 'with', 'that',
    'this', 'from', 'justin', 'come', 'luck', 'chainsmokers', 'let',
}


def is_keyboard_mash_or_nonsense(
    norm_str: str,
    word_vocab: Optional[Dict[str, int]] = None,
) -> bool:
    """Phát hiện gõ phím ngẫu nhiên ('Idjdbbdkdb...', 'asdfghjkl') và câu gợi ý bàn phím vô nghĩa."""
    # Xóa các ký hiệu kỹ thuật hợp lệ có chữ cái đơn như Type-C, Win+D, P/s, :D
    scrubbed = re.sub(r'\b(type-c|win\+d|p/s)\b|:\s*d\b', ' ', norm_str, flags=re.IGNORECASE)
    words = re.findall(
        r'(?u)\b[a-zA-Zàáảãạăắằẳẵặâấầẩẫậèéẻẽẹêếềểễệìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵđ]+\b',
        scrubbed,
    )
    if not words:
        return True

    # 1. Kiểm tra từ gõ loạn phím (không có nguyên âm, hoặc cụm phụ âm vô nghĩa dài >= 7 ký tự)
    gibberish_tokens = 0
    for w in words:
        if len(w) >= 6 and not _VN_VOWEL_REGEX.search(w):
            return True
        if len(w) >= 8 and word_vocab is not None and w not in word_vocab:
            gibberish_tokens += 1
        elif len(w) >= 11:
            gibberish_tokens += 1
    if gibberish_tokens >= 2 or (len(words) <= 2 and gibberish_tokens >= 1):
        return True

    # 2. Kiểm tra câu gõ bàn phím gợi ý tiếng Anh vô nghĩa (>= 2 từ dừng tiếng Anh trong câu >= 4 từ)
    eng_hits = sum(1 for w in words if w in _ENGLISH_STOPWORDS_SET)
    if len(words) >= 4 and eng_hits >= 2:
        return True

    # 3. Kiểm tra câu bắt đầu bằng phụ âm đơn vô nghĩa ('b nghệ thuật ... v vcc', 'n vạn sự...')
    if len(words) >= 4 and len(words[0]) == 1 and words[0] not in {'k', 'r', 'v', 'e', 'a', 'ạ', 'ổ', 'ý', 'ở'}:
        return True

    return False


def infer_item_domain_and_keywords(
    source_domain: Optional[str] = None,
    app_json: Optional[str] = None,
) -> Tuple[str, Set[str]]:
    """Suy luận ngành hàng (Domain) và tập từ khóa sản phẩm từ `source_domain` + `app_json`."""
    src = (source_domain or "").strip().lower()
    meta_text = ""
    if app_json and isinstance(app_json, str):
        try:
            obj = json.loads(app_json)
            if isinstance(obj, dict):
                parts = [
                    str(obj.get("name", "")),
                    str(obj.get("title", "")),
                    str(obj.get("genre", "")),
                    str(obj.get("primaryGenreName", "")),
                    str(obj.get("short_description", ""))[:200],
                ]
                cats = obj.get("categories")
                if isinstance(cats, dict):
                    parts.append(str(cats.get("name", "")))
                elif isinstance(cats, list):
                    parts.extend(str(c.get("name", "")) for c in cats if isinstance(c, dict))
                meta_text = " ".join(parts).lower()
        except Exception:
            meta_text = app_json[:300].lower()

    meta_tokens = set(
        w for w in re.findall(
            r'(?u)\b[a-zA-Zàáảãạăắằẳẵặâấầẩẫậèéẻẽẹêếềểễệìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵđ]{3,}\b',
            meta_text,
        )
    )

    if src in ("google_play", "app_store"):
        return "mobile_app", meta_tokens
    if any(k in meta_text for k in ("sách", "nhà giả kim", "đắc nhân tâm", "tiểu thuyết", "truyện", "tác giả")):
        return "books_stationery", meta_tokens
    if any(k in meta_text for k in ("chuột", "bàn phím", "tai nghe", "điện thoại", "laptop", "sạc", "cáp", "loa")):
        return "electronics_digital", meta_tokens
    if any(k in meta_text for k in ("bình giữ nhiệt", "nồi", "bếp", "elmich", "lock", "gia dụng", "cốc", "ly")):
        return "home_appliances", meta_tokens
    if any(k in meta_text for k in ("áo", "quần", "váy", "giày", "dép", "thời trang", "túi xách")):
        return "fashion_apparel", meta_tokens
    if any(k in meta_text for k in ("son", "kem", "serum", "sữa rửa mặt", "mỹ phẩm", "dưỡng da", "chống nắng")):
        return "cosmetics_skincare", meta_tokens
    if any(k in meta_text for k in ("mèo", "chó", "thú cưng", "cát vệ sinh")):
        return "pet_supplies", meta_tokens
    return "general_ecommerce", meta_tokens


def extract_aspects(raw_text: str, overall_label: str) -> str:
    """Tách câu theo mệnh đề và trích xuất khía cạnh + cảm xúc dạng chuỗi JSON."""
    if not raw_text or not isinstance(raw_text, str):
        return "[]"
    norm_text = unicodedata.normalize('NFC', unicodedata.normalize('NFKC', raw_text))
    clauses = re.split(
        r'[.!?\n;]+|\b(?:nhưng|tuy nhiên|bù lại|ngoại trừ|có điều|mỗi tội)\b',
        norm_text,
        flags=re.IGNORECASE,
    )
    found: Dict[str, str] = {}
    for clause in clauses:
        c_str = clause.strip()
        if not c_str:
            continue
        c_no_neg_def = NEGATED_DEFECT_REGEX.sub(' tốt ', c_str.lower())
        c_no_mild = MILD_NEG_WORDS.sub(' ', c_no_neg_def)
        for asp_name, asp_regex in ASPECT_PATTERNS.items():
            if asp_regex.search(c_str):
                if STRONG_NEG_WORDS.search(c_no_mild):
                    sent = "negative"
                elif MILD_NEG_WORDS.search(c_no_neg_def):
                    sent = "neutral"
                elif STRONG_POS_WORDS.search(c_no_neg_def):
                    sent = "positive"
                else:
                    sent = overall_label.lower()
                found[asp_name] = sent

    if not found and overall_label:
        found["chung"] = overall_label.lower()

    return json.dumps([{"aspect": k, "sentiment": v} for k, v in found.items()], ensure_ascii=False)


class SentimentNLPPipeline:
    """Pipeline hoàn chỉnh Bước 5 (v2.1): Tổng quát hóa cho đa lĩnh vực Tiki, Google Play, App Store."""

    def __init__(self, model_path: Optional[str | Path] = None):
        if model_path is None:
            default_candidates = [
                _ROOT_DIR / "models" / "3_Max_Single_F1_SVM.pkl",
                _CURRENT_DIR / "3_Max_Single_F1_SVM.pkl",
                Path("models/3_Max_Single_F1_SVM.pkl"),
                Path("3_Max_Single_F1_SVM.pkl"),
            ]
            for cand in default_candidates:
                if cand.exists():
                    model_path = cand
                    break
        self.svm_engine = StandaloneSVMModel(model_path) if model_path and Path(model_path).exists() else None
        self.fallback_preprocessor = VietnameseSentimentPreprocessor(amplify_contrast_clause=True)

    def analyze_review(
        self,
        raw_text: Any,
        rating: Optional[Any] = None,
        source_domain: Optional[str] = None,
        app_json: Optional[str] = None,
    ) -> Tuple[str, int, float, str, str, str]:
        """Phân tích 1 bình luận đơn lẻ với cơ chế lọc nhiễu & đối chiếu ngữ cảnh đa miền."""
        # Tầng 1.1: Bình luận = null hoặc chỉ chứa khoảng trắng
        if raw_text is None or (isinstance(raw_text, float) and math.isnan(raw_text)):
            raw_str = ""
        else:
            raw_str = str(raw_text).strip()

        if not raw_str:
            if rating is not None and not pd.isna(rating):
                try:
                    r = int(float(rating))
                except (ValueError, TypeError):
                    r = 3
                if r >= 4:
                    return "", 0, 0.75, "Positive", "[]", "EMPTY_COMMENT"
                if r == 3:
                    return "", 0, 0.50, "Neutral", "[]", "EMPTY_COMMENT"
                return "", 0, 0.20, "Negative", "[]", "EMPTY_COMMENT"
            return "", 0, 0.50, "Neutral", "[]", "EMPTY_COMMENT"

        # Tầng 1.2: Bình luận chỉ chứa biểu tượng cảm xúc (Emoji / Emoticon)
        if POS_EMOJI_ONLY.match(raw_str):
            return "emo_pos", 1, 0.88, "Positive", '[{"aspect": "chung", "sentiment": "positive"}]', "EMOJI_ONLY"
        if NEG_EMOJI_ONLY.match(raw_str):
            return "emo_neg", 1, 0.12, "Negative", '[{"aspect": "chung", "sentiment": "negative"}]', "EMOJI_ONLY"

        # Chuẩn hóa Unicode NFC và thu gọn ký tự kéo dài ("siêu đẹppp" -> "siêu đẹp") trước khi kiểm tra
        norm_str = unicodedata.normalize('NFC', unicodedata.normalize('NFKC', raw_str)).lower()
        norm_str = re.sub(r'([a-zàáảãạăắằẳẵặâấầẩẫậèéẻẽẹêếềểễệìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵđ])\1{2,}', r'\1', norm_str)

        # Tầng 1.3: Lọc bình luận chỉ có <= 1 chữ cái ("1", "i", "...")
        alpha_chars = [c for c in norm_str if unicodedata.category(c).startswith('L')]
        if len(alpha_chars) <= 1:
            return "", 0, 0.50, "Neutral", "[]", "FILTERED_MEANINGLESS"

        # Tầng 1.4: Lọc Spam cấu trúc hoặc Gõ phím ngẫu nhiên / Gợi ý bàn phím vô nghĩa
        vocab_ref = self.svm_engine.word_vocab if self.svm_engine is not None else None
        if SPAM_STRUCTURAL_REGEX.search(norm_str) or is_keyboard_mash_or_nonsense(norm_str, vocab_ref):
            return "", 0, 0.50, "Neutral", "[]", "FILTERED_SPAM_OR_GIBBERISH"

        # Tầng 1.5: Kiểm tra đánh giá nhầm ngành hàng (Cross-Domain Off-Topic) dựa trên metadata
        item_domain, meta_tokens = infer_item_domain_and_keywords(source_domain, app_json)
        for sig_domain, sig_regex in EXCLUSIVE_DOMAIN_SIGNATURES.items():
            if sig_domain != item_domain and sig_regex.search(norm_str):
                return "", 0, 0.50, "Neutral", "[]", "FILTERED_OFF_TOPIC"

        # Tầng 1.6: Cổng Kiểm Soát Độ Liên Quan Ngữ Nghĩa (Lexical Relevance Gatekeeper)
        raw_no_neg_defect = NEGATED_DEFECT_REGEX.sub(' tốt ', norm_str)
        has_mild_neg = bool(MILD_NEG_WORDS.search(raw_no_neg_defect))
        # Loại bỏ cụm giảm nhẹ ("hơi lag", "hơi nhăn") trước khi quét lỗi nghiêm trọng
        raw_no_mild = MILD_NEG_WORDS.sub(' ', raw_no_neg_defect)
        has_strong_neg = bool(STRONG_NEG_WORDS.search(raw_no_mild))
        has_strong_pos = bool(STRONG_POS_WORDS.search(raw_no_neg_defect))
        has_hedge = bool(NEUTRAL_HEDGE_WORDS.match(norm_str.strip()))
        has_domain_word = bool(GENERAL_REVIEW_DOMAIN_WORDS.search(norm_str))
        raw_words = set(
            w for w in re.findall(
                r'(?u)\b[a-zA-Zàáảãạăắằẳẵặâấầẩẫậèéẻẽẹêếềểễệìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵđ]{3,}\b',
                norm_str,
            )
        )
        has_meta_overlap = bool(raw_words & meta_tokens) if meta_tokens else False

        if not (has_strong_pos or has_strong_neg or has_mild_neg or has_hedge or has_domain_word or has_meta_overlap):
            return "", 0, 0.50, "Neutral", "[]", "FILTERED_SPAM_OR_GIBBERISH"

        # Tầng 2: Tiền xử lý tiếng Việt và đếm số từ (word_count)
        if self.svm_engine is not None:
            cleaned = self.svm_engine.preprocess(raw_str)
        else:
            cleaned = self.fallback_preprocessor.clean_single_text(raw_str)

        wc = len(cleaned.split()) if cleaned else 0
        if wc == 0:
            return "", 0, 0.50, "Neutral", "[]", "FILTERED_MEANINGLESS"

        # Tầng 3.1: Bình luận chưa sử dụng / chưa đọc ("Chưa đọc", "Mua tặng nên chưa biết")
        if PRE_CONSUMPTION_REGEX.search(norm_str) and not has_strong_neg:
            if not has_strong_pos or norm_str.strip() in ('chưa đọc', 'chưa dùng', 'chưa xài'):
                return (
                    cleaned,
                    wc,
                    0.50,
                    "Neutral",
                    extract_aspects(raw_str, "Neutral"),
                    "VALID_PRE_CONSUMPTION",
                )

        # Tầng 3.2: Tính điểm Margin từ mô hình 3_Max_Single_F1_SVM.pkl (đã khử thiên lệch danh từ)
        if self.svm_engine is not None:
            margin = self.svm_engine.decision_margin(cleaned)
        else:
            margin = 0.8 if has_strong_pos and not has_strong_neg else (-0.8 if has_strong_neg else 0.0)

        if has_strong_pos and not has_strong_neg and not has_mild_neg and margin < 0.25:
            margin = max(margin + 0.65, 0.35)

        prob = 1.0 / (1.0 + math.exp(-1.8 * margin))
        has_contrast = bool(CONTRAST_WORDS.search(norm_str))

        # Tầng 3.3: Từ ngữ lưng chừng trung tính ("Ổn", "Tạm ổn", "Bình thường", "Cũng được")
        if has_hedge:
            return cleaned, wc, 0.50, "Neutral", extract_aspects(raw_str, "Neutral"), "VALID_TEXT"

        # Tầng 3.4: Câu phức có mệnh đề chuyển ý ("Khen A nhưng chê B")
        if has_contrast and has_strong_pos and (has_mild_neg or has_strong_neg):
            parts = CONTRAST_WORDS.split(raw_no_neg_defect, maxsplit=1)
            post_clause = parts[-1] if len(parts) >= 2 else raw_no_neg_defect
            post_no_mild = MILD_NEG_WORDS.sub(' ', post_clause)
            severe_post = any(
                w in post_no_mild
                for w in (
                    'ko ổn', 'không ổn', 'rách', 'ướt hết', 'kém',
                    'không hài lòng', 'tệ', 'hỏng', 'hư', 'móp phần đầu', 'văng',
                )
            )
            if STRONG_NEG_WORDS.search(post_no_mild) and (margin < -0.10 or severe_post):
                label = "Negative"
                score = min(prob, 0.28)
            else:
                label = "Neutral"
                score = 0.48
            return (
                cleaned,
                wc,
                round(float(score), 4),
                label,
                extract_aspects(raw_str, label),
                "VALID_TEXT",
            )

        # Tầng 3.5: Phàn nàn nhẹ đơn thuần ("Bìa hơi cũ", "Mau hết pin") -> Neutral
        if has_mild_neg and not has_strong_neg and not has_strong_pos:
            return cleaned, wc, 0.42, "Neutral", extract_aspects(raw_str, "Neutral"), "VALID_TEXT"

        # Tầng 3.6: Tiêu cực rõ ràng (Vượt quyền số sao 3*, 4*, 5*)
        if has_strong_neg and not has_strong_pos:
            score = min(prob, 0.30)
            return (
                cleaned,
                wc,
                round(float(score), 4),
                "Negative",
                extract_aspects(raw_str, "Negative"),
                "VALID_TEXT",
            )

        if margin < -0.25 and not has_strong_pos:
            return (
                cleaned,
                wc,
                round(float(prob), 4),
                "Negative",
                extract_aspects(raw_str, "Negative"),
                "VALID_TEXT",
            )

        # Tầng 3.7: Tích cực rõ ràng
        if margin > 0.20 or (has_strong_pos and not has_strong_neg and not has_mild_neg):
            score = max(prob, 0.70) if margin <= 0.20 else prob
            return (
                cleaned,
                wc,
                round(float(score), 4),
                "Positive",
                extract_aspects(raw_str, "Positive"),
                "VALID_TEXT",
            )

        # Tầng 3.8: Vùng đệm bất định quanh siêu phẳng SVM (-0.25 <= margin <= +0.20) -> Neutral
        return (
            cleaned,
            wc,
            round(float(prob), 4),
            "Neutral",
            extract_aspects(raw_str, "Neutral"),
            "VALID_TEXT",
        )

    def process_dataframe(
        self,
        df: pd.DataFrame,
        text_col: Optional[str] = None,
        rating_col: str = "rating",
    ) -> pd.DataFrame:
        """Áp dụng toàn bộ Pipeline Bước 5 lên Pandas DataFrame."""
        out_df = df.copy()
        if text_col is None:
            text_col = "raw_text" if "raw_text" in out_df.columns else "review_text"
        if text_col not in out_df.columns:
            raise KeyError(f"Không tìm thấy cột văn bản '{text_col}' trong DataFrame.")

        ratings = out_df[rating_col] if rating_col in out_df.columns else [None] * len(out_df)
        sources = out_df["source_domain"] if "source_domain" in out_df.columns else [None] * len(out_df)
        app_jsons = out_df["app_json"] if "app_json" in out_df.columns else [None] * len(out_df)

        results = [
            self.analyze_review(txt, rt, src, aj)
            for txt, rt, src, aj in zip(out_df[text_col], ratings, sources, app_jsons)
        ]

        out_df["cleaned_text"] = [r[0] for r in results]
        out_df["word_count"] = [r[1] for r in results]
        out_df["sentiment_score"] = [r[2] for r in results]
        out_df["sentiment_label"] = [r[3] for r in results]
        out_df["aspects"] = [r[4] for r in results]
        out_df["quality_status"] = [r[5] for r in results]
        return out_df


# ============================================================================
# 4. TÍCH HỢP PYSPARK CHO LUỒNG STREAMING & BATCH (`spark_streaming_job.py`)
# ============================================================================

def apply_spark_nlp_pipeline(
    spark_df: Any,
    model_path: str | Path = "models/3_Max_Single_F1_SVM.pkl",
    text_col: str = "raw_text",
    rating_col: str = "rating",
) -> Any:
    """Hàm tích hợp trực tiếp vào PySpark DataFrame bằng `mapInPandas`."""
    from pyspark.sql.types import DoubleType, IntegerType, StringType, StructField, StructType

    base_schema = spark_df.schema
    nlp_fields = [
        StructField("cleaned_text", StringType(), True),
        StructField("word_count", IntegerType(), True),
        StructField("sentiment_score", DoubleType(), True),
        StructField("sentiment_label", StringType(), True),
        StructField("aspects", StringType(), True),
        StructField("quality_status", StringType(), True),
    ]
    out_fields = [f for f in base_schema.fields if f.name not in {nf.name for nf in nlp_fields}] + nlp_fields
    out_schema = StructType(out_fields)
    resolved_model_path = str(Path(model_path).resolve())

    def _process_partition(iterator: Iterable[pd.DataFrame]) -> Iterable[pd.DataFrame]:
        pipeline = SentimentNLPPipeline(model_path=resolved_model_path)
        for pdf in iterator:
            if pdf.empty:
                for nf in nlp_fields:
                    pdf[nf.name] = pd.Series(dtype="object")
                yield pdf[[f.name for f in out_fields]]
                continue
            processed = pipeline.process_dataframe(pdf, text_col=text_col, rating_col=rating_col)
            yield processed[[f.name for f in out_fields]]

    return spark_df.mapInPandas(_process_partition, schema=out_schema)


# ============================================================================
# 5. BÁO CÁO THỐNG KÊ DỮ LIỆU & CLI CHẠY TRỰC TIẾP
# ============================================================================

def generate_nlp_statistics_report(df: pd.DataFrame, text_col: str = "review_text") -> Dict[str, Any]:
    """Tính toán đầy đủ các chỉ số thống kê chất lượng dữ liệu và phân bố cảm xúc."""
    if text_col not in df.columns and "raw_text" in df.columns:
        text_col = "raw_text"

    total_rows = int(len(df))
    null_comments = int(df[text_col].isna().sum())
    str_series = df[text_col].fillna("").astype(str)
    whitespace_only = int((str_series.str.strip() == "").sum() - null_comments)
    non_empty_comments = int(total_rows - null_comments - whitespace_only)

    non_empty_df = df[str_series.str.strip() != ""]
    exact_dup = int(non_empty_df.duplicated(subset=[text_col]).sum())
    norm_dup = int(non_empty_df[text_col].astype(str).str.lower().str.strip().duplicated().sum())

    status_counts = df["quality_status"].value_counts().to_dict() if "quality_status" in df.columns else {}
    sentiment_all = df["sentiment_label"].value_counts().to_dict() if "sentiment_label" in df.columns else {}
    sentiment_non_empty = (
        non_empty_df["sentiment_label"].value_counts().to_dict()
        if "sentiment_label" in non_empty_df.columns
        else {}
    )

    rating_vs_sentiment = {}
    if "rating" in non_empty_df.columns and "sentiment_label" in non_empty_df.columns:
        ct = pd.crosstab(non_empty_df["rating"], non_empty_df["sentiment_label"])
        rating_vs_sentiment = {str(k): {str(c): int(v) for c, v in row.items()} for k, row in ct.iterrows()}

    return {
        "total_reviews": total_rows,
        "null_comments_count": null_comments,
        "null_comments_pct": round(null_comments / max(total_rows, 1) * 100, 2),
        "whitespace_only_count": whitespace_only,
        "non_empty_comments_count": non_empty_comments,
        "non_empty_comments_pct": round(non_empty_comments / max(total_rows, 1) * 100, 2),
        "duplicate_non_empty_exact": exact_dup,
        "duplicate_non_empty_normalized": norm_dup,
        "quality_status_distribution": {str(k): int(v) for k, v in status_counts.items()},
        "sentiment_distribution_all_rows": {str(k): int(v) for k, v in sentiment_all.items()},
        "sentiment_distribution_non_empty_rows": {str(k): int(v) for k, v in sentiment_non_empty.items()},
        "rating_vs_sentiment_non_empty": rating_vs_sentiment,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Chạy Pipeline NLP & Sentiment (Bước 5) trên dữ liệu crawl.")
    parser.add_argument("--input", required=True, help="Đường dẫn file CSV/JSONL/Excel đầu vào.")
    parser.add_argument(
        "--model",
        default="models/3_Max_Single_F1_SVM.pkl",
        help="Đường dẫn tới mô hình 3_Max_Single_F1_SVM.pkl.",
    )
    parser.add_argument("--output", required=True, help="Đường dẫn file CSV/Parquet đầu ra đã gán nhãn.")
    parser.add_argument("--report", default=None, help="Đường dẫn file JSON lưu báo cáo thống kê.")
    args = parser.parse_args(argv)

    in_path = Path(args.input)
    if in_path.suffix.lower() in (".xlsx", ".xls"):
        df = pd.read_excel(in_path)
    elif in_path.suffix.lower() == ".jsonl":
        df = pd.read_json(in_path, lines=True)
    elif in_path.suffix.lower() == ".parquet":
        df = pd.read_parquet(in_path)
    else:
        df = pd.read_csv(in_path)

    pipeline = SentimentNLPPipeline(model_path=args.model)
    processed_df = pipeline.process_dataframe(df)
    stats = generate_nlp_statistics_report(processed_df)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.suffix.lower() == ".parquet":
        processed_df.to_parquet(out_path, index=False)
    else:
        processed_df.to_csv(out_path, index=False, encoding="utf-8-sig")

    if args.report:
        rep_path = Path(args.report)
        rep_path.parent.mkdir(parents=True, exist_ok=True)
        rep_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())