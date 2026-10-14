from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from urllib.parse import urlparse
from core import input_error
from monitor import StableResult
from ocr_captcha import ocr_captcha
from time import monotonic, sleep
from uuid import uuid4
import os
import sys
import shutil
from pathlib import Path
from selenium.webdriver.chrome.service import Service

URL = 'https://baohiemxahoi.gov.vn/tracuu/pages/tra-cuu-thoi-han-su-dung-the-bhyt.aspx'

class Browser:
    def __init__(self):
        options = webdriver.ChromeOptions()
        options.add_argument('--incognito')
        if sys.platform.startswith('linux'):
            chrome = os.environ.get('BHYT_CHROME_PATH') or shutil.which('google-chrome') or shutil.which('google-chrome-stable')
            if not chrome:
                raise ValueError('Không tìm thấy Google Chrome. Bản portable dùng Chrome có sẵn, không cài trình duyệt.')
            options.binary_location = chrome
            os.environ.setdefault('SE_AVOID_BROWSER_DOWNLOAD', 'true')
        elif sys.platform.startswith('win'):
            chrome_candidates = [
                os.environ.get('BHYT_CHROME_PATH'),
                r'C:\Program Files\Google\Chrome\Application\chrome.exe',
                r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
                os.path.expandvars(r'%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe'),
                shutil.which('chrome'),
                shutil.which('chrome.exe'),
            ]
            chrome = next((c for c in chrome_candidates if c and Path(c).is_file()), None)
            if chrome:
                options.binary_location = chrome
        driver = os.environ.get('BHYT_DRIVER_PATH')
        if driver and not Path(driver).is_file():
            raise ValueError('Đường dẫn ChromeDriver cấu hình không tồn tại.')
        self.driver = webdriver.Chrome(service=Service(executable_path=driver), options=options) if driver else webdriver.Chrome(options=options)
        self.driver.set_page_load_timeout(40)
        self.ready = False
        self.baseline = ''
        self.last_ocr_text = ''
        self.last_ocr_status = ''

    def _find_captcha_image(self):
        """Tìm element ảnh CAPTCHA trên trang BHXH."""
        # Selector chính xác từ trang baohiemxahoi.gov.vn
        try:
            el = self.driver.find_element(By.ID, 'imgCaptcha')
            if el.is_displayed():
                return el
        except Exception:
            pass
        # Fallback: tìm theo src chứa CaptchaImageHandler
        selectors = [
            "//img[contains(@src, 'CaptchaImageHandler')]",
            "//img[contains(@src, 'captcha') or contains(@src, 'Captcha')]",
            "//img[@alt='captcha']",
        ]
        for xpath in selectors:
            elements = self.driver.find_elements(By.XPATH, xpath)
            visible = [e for e in elements if e.is_displayed()]
            if visible:
                return visible[0]
        return None

    def _wait_captcha_loaded(self, timeout=15):
        """Chờ ảnh CAPTCHA tải xong. Trả về element nếu OK, None nếu hết thời gian."""
        deadline = monotonic() + timeout
        while monotonic() < deadline:
            img = self._find_captcha_image()
            if img:
                try:
                    # Kiểm tra ảnh đã tải xong chưa bằng JS
                    loaded = self.driver.execute_script(
                        "var img = arguments[0]; "
                        "return img.complete && img.naturalWidth > 0 && img.naturalHeight > 0;",
                        img
                    )
                    if loaded:
                        return img
                except Exception:
                    pass
            sleep(0.5)
        # Thử click vào ảnh để tải lại (trang BHXH hỗ trợ click để đổi mã)
        img = self._find_captcha_image()
        if img:
            try:
                img.click()
                sleep(2)
                loaded = self.driver.execute_script(
                    "var img = arguments[0]; "
                    "return img.complete && img.naturalWidth > 0 && img.naturalHeight > 0;",
                    img
                )
                if loaded:
                    return img
            except Exception:
                pass
        return None

    def _find_captcha_input(self):
        """Tìm ô nhập mã CAPTCHA."""
        # Selector chính xác từ trang baohiemxahoi.gov.vn: id="tokenRecaptch"
        try:
            el = self.driver.find_element(By.ID, 'tokenRecaptch')
            if el.is_displayed() and el.is_enabled():
                return el
        except Exception:
            pass
        # Fallback
        selectors = [
            "//input[@name='tokenRecaptch']",
            "//input[contains(@id, 'token') and contains(@id, 'ecaptch')]",
            "//input[contains(@id, 'captcha') or contains(@id, 'Captcha')]",
        ]
        for xpath in selectors:
            elements = self.driver.find_elements(By.XPATH, xpath)
            visible = [e for e in elements if e.is_displayed() and e.is_enabled()]
            if visible:
                return visible[0]
        return None

    def _find_submit_button(self):
        """Tìm nút Tra cứu."""
        # Selector chính xác từ trang baohiemxahoi.gov.vn: id="btnTraCuu"
        try:
            el = self.driver.find_element(By.ID, 'btnTraCuu')
            if el.is_displayed():
                return el
        except Exception:
            pass
        # Fallback
        selectors = [
            "//button[contains(@id, 'btnTraCuu')]",
            "//button[contains(@class, 'btn-red') and contains(text(), 'Tra')]",
        ]
        for xpath in selectors:
            elements = self.driver.find_elements(By.XPATH, xpath)
            visible = [e for e in elements if e.is_displayed()]
            if visible:
                return visible[0]
        return None

    def solve_captcha(self, max_retries=3):
        """OCR ảnh CAPTCHA, điền vào ô nhập. Trả về text đã nhận dạng hoặc rỗng."""
        # Chờ ảnh CAPTCHA tải xong (xử lý lag/limit kết nối)
        captcha_img = self._wait_captcha_loaded(timeout=15)
        if not captcha_img:
            self.last_ocr_status = 'Ảnh CAPTCHA chưa tải được (lag/mất kết nối). Chờ rồi thử lại.'
            self.last_ocr_text = ''
            return ''

        captcha_input = self._find_captcha_input()
        if not captcha_input:
            self.last_ocr_status = 'Không tìm thấy ô nhập mã xác nhận.'
            self.last_ocr_text = ''
            return ''

        for attempt in range(max_retries):
            try:
                screenshot_bytes = captcha_img.screenshot_as_png
                if len(screenshot_bytes) < 500:
                    # Ảnh quá nhỏ = chưa tải xong, chờ thêm
                    sleep(2)
                    captcha_img = self._wait_captcha_loaded(timeout=10)
                    if not captcha_img:
                        continue
                    screenshot_bytes = captcha_img.screenshot_as_png
                text = ocr_captcha(screenshot_bytes)
                if not text or len(text) < 3:
                    text = ocr_captcha(screenshot_bytes, preprocess=False)
                if text and len(text) >= 4:
                    captcha_input.clear()
                    captcha_input.send_keys(text)
                    self.last_ocr_text = text
                    self.last_ocr_status = f'OCR thành công: "{text}" (lần {attempt + 1})'
                    return text
            except Exception as e:
                self.last_ocr_status = f'Lỗi OCR lần {attempt + 1}: {str(e)}'
            sleep(1)
            # Thử click ảnh để tải lại CAPTCHA mới
            if attempt < max_retries - 1:
                try:
                    captcha_img.click()
                    sleep(2)
                    captcha_img = self._wait_captcha_loaded(timeout=10)
                    if not captcha_img:
                        continue
                except Exception:
                    pass

        self.last_ocr_status = f'OCR không đọc được sau {max_retries} lần thử.'
        self.last_ocr_text = ''
        return ''

    def solve_and_submit(self, max_retries=3):
        """OCR CAPTCHA, điền mã, và bấm nút Tra cứu. Trả về (ocr_text, submitted)."""
        text = self.solve_captcha(max_retries=max_retries)
        if not text:
            return ('', False)
        submit_btn = self._find_submit_button()
        if submit_btn:
            try:
                submit_btn.click()
                self.last_ocr_status += ' → Đã bấm Tra cứu.'
                return (text, True)
            except Exception as e:
                self.last_ocr_status += f' → Không bấm được Tra cứu: {str(e)}'
                return (text, False)
        else:
            self.last_ocr_status += ' → Không tìm thấy nút Tra cứu.'
            return (text, False)

    def _fill_form_and_setup(self, row):
        """Điền form và thiết lập watcher. Tách riêng để có thể gọi lại khi reload."""
        wait = WebDriverWait(self.driver, 20)
        for field, hint in [('Mã thẻ', 'mã số BHXH/thẻ BHYT'), ('Họ tên', 'họ tên'), ('Ngày sinh', '1950')]:
            xpath = f"//input[contains(@placeholder, '{hint}')]"
            elements = wait.until(lambda d: [e for e in d.find_elements(By.XPATH, xpath) if e.is_displayed() and e.is_enabled()] or False)
            if len(elements) != 1:
                raise ValueError('Không xác định duy nhất ô ' + field + '. Dừng điền để tránh nhầm.')
            elements[0].clear()
            elements[0].send_keys(row[field])
        self.baseline = self.driver.find_element(By.TAG_NAME, 'body').text
        self.row_token = uuid4().hex
        self.monitor = StableResult()
        self.driver.execute_script('''
            window.__bhytWatch = {seq: 0};
            document.addEventListener('click', function(e) {
                const el = e.target.closest('button,a,input,[role="button"]');
                if (!el) return;
                const label = (el.innerText || el.value || '').trim().toLocaleLowerCase('vi');
                if (/tra\\s+cứu/.test(label)) window.__bhytWatch.seq++;
            }, true);
            document.addEventListener('submit', function(e) {
                window.__bhytWatch.seq++;
            }, true);
        ''')
        self.ready = True

    def prepare(self, row, auto_ocr=True):
        self.ready = False
        max_page_retries = 3
        for page_attempt in range(max_page_retries):
            self.driver.get(URL)
            try:
                self._fill_form_and_setup(row)
            except Exception:
                if page_attempt < max_page_retries - 1:
                    sleep(2)
                    continue
                raise

            if not auto_ocr:
                return

            # OCR + bấm Tra cứu, nếu ảnh CAPTCHA bị mất thì reload trang
            ocr_text, submitted = self.solve_and_submit()
            if ocr_text:
                return  # Thành công
            # Ảnh CAPTCHA bị mất — reload trang, điền lại, thử lại
            if page_attempt < max_page_retries - 1:
                self.last_ocr_status = f'Ảnh CAPTCHA bị mất, đang tải lại trang... (lần {page_attempt + 2}/{max_page_retries})'
                self.ready = False
                sleep(3)  # Chờ tránh bị limit kết nối
        # Hết retry vẫn không OCR được — giữ trang đã điền, người dùng tự nhập
        self.last_ocr_status = 'Không tải được ảnh CAPTCHA sau nhiều lần thử. Vui lòng nhập tay.'

    def auto_read(self):
        if not self.ready:
            return None
        watch = self.driver.execute_script('return window.__bhytWatch || null;')
        if not watch or not watch.get('seq'):
            return None
        try:
            text = self.read()
        except ValueError:
            self.monitor.consider('', self.row_token, watch['seq'], monotonic())
            return None
        return self.monitor.consider(text, self.row_token, watch['seq'], monotonic())

    def read(self):
        if not self.ready:
            raise ValueError('Hãy mở bản ghi trong Chrome trước.')
        parsed = urlparse(self.driver.current_url)
        if parsed.scheme != 'https' or parsed.hostname != 'baohiemxahoi.gov.vn' or parsed.path != urlparse(URL).path:
            raise ValueError('Chrome không ở đúng trang tra cứu BHXH.')
        text = self.driver.find_element(By.TAG_NAME, 'body').text
        if text == self.baseline:
            raise ValueError('Chưa phát hiện nội dung mới. Nhập CAPTCHA và bấm Tra cứu trong Chrome.')
        if input_error(text):
            return text  # Lỗi CAPTCHA có thể nằm phía trên vùng Thông báo.
        # Chỉ trả vùng bắt đầu bằng thông báo, không phân tích dữ liệu ẩn hay CAPTCHA.
        starts = [text.find(p) for p in ('Thẻ BHYT còn giá trị sử dụng!', 'Thẻ BHYT hết hạn!', 'Chưa có thông tin thẻ BHYT') if p in text]
        if len(starts) != 1:
            raise ValueError('Chưa có thông báo rõ ràng duy nhất; không lưu hoặc chuyển dòng.')
        return text[starts[0]:]

    def close(self):
        self.driver.quit()
