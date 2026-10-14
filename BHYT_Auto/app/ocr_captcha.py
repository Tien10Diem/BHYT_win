"""Module OCR đọc mã CAPTCHA từ ảnh chụp element trên trang BHXH."""
import ddddocr
from PIL import Image, ImageFilter, ImageOps
from io import BytesIO
import re

# Khởi tạo một lần, tái sử dụng cho các lần gọi sau
_ocr = None

def _get_ocr():
    global _ocr
    if _ocr is None:
        _ocr = ddddocr.DdddOcr(show_ad=False)
    return _ocr

def preprocess_captcha(image_bytes: bytes) -> bytes:
    """Tiền xử lý ảnh CAPTCHA: chuyển xám, tăng tương phản, loại nhiễu."""
    img = Image.open(BytesIO(image_bytes)).convert('L')  # Grayscale
    # Tăng tương phản bằng cách stretch histogram
    img = ImageOps.autocontrast(img, cutoff=5)
    # Nhị phân hóa (threshold) để tách chữ ra khỏi nền + nhiễu
    threshold = 160
    img = img.point(lambda p: 255 if p > threshold else 0)
    # Loại bỏ nhiễu nhỏ (các vạch mảnh)
    img = img.filter(ImageFilter.MedianFilter(size=3))
    # Xuất lại bytes PNG
    buf = BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()

def ocr_captcha(image_bytes: bytes, preprocess: bool = True) -> str:
    """Đọc text từ ảnh CAPTCHA. Trả về chuỗi ký tự viết hoa."""
    ocr = _get_ocr()
    if preprocess:
        processed = preprocess_captcha(image_bytes)
    else:
        processed = image_bytes
    result = ocr.classification(processed)
    # Chuẩn hóa: chỉ giữ chữ cái và số, viết hoa
    result = re.sub(r'[^A-Za-z0-9]', '', result).upper()
    return result

def ocr_captcha_from_element(driver, captcha_img_element) -> str:
    """Chụp screenshot của element CAPTCHA trên trang web và OCR."""
    screenshot_bytes = captcha_img_element.screenshot_as_png
    return ocr_captcha(screenshot_bytes)
