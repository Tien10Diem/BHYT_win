from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from urllib.parse import urlparse
from core import input_error
from monitor import StableResult
from ocr_captcha import ocr_captcha
from time import monotonic, sleep
from uuid import uuid4
import unicodedata
import os
import sys
import shutil
from pathlib import Path
from selenium.webdriver.chrome.service import Service

URL = 'https://baohiemxahoi.gov.vn/tracuu/pages/tra-cuu-thoi-han-su-dung-the-bhyt.aspx'

def norm(s):
    return ' '.join(unicodedata.normalize('NFC', str(s)).split()).casefold()

class Browser:
    def __init__(self):
        options = webdriver.ChromeOptions()
        options.add_argument('--incognito')
        options.page_load_strategy = 'eager'
        if sys.platform.startswith('linux'):
            chrome = os.environ.get('BHYT_CHROME_PATH') or shutil.which('google-chrome') or shutil.which('google-chrome-stable')
            if not chrome:
                raise ValueError('Không tìm thấy Google Chrome.')
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
        self.driver.set_page_load_timeout(35)
        self.ready = False
        self.baseline = ''
        self.last_ocr_text = ''
        self.last_ocr_status = ''
        self.data_error = ''

    def _find_captcha_image(self):
        """Tìm element ảnh CAPTCHA (id=imgCaptcha)."""
        try:
            el = self.driver.find_element(By.ID, 'imgCaptcha')
            if el.is_displayed():
                return el
        except Exception:
            pass
        return None

    def _wait_captcha_loaded(self, timeout=10):
        """Đợi cho đến khi ảnh CAPTCHA thực sự xuất hiện và nạp xong (naturalWidth > 30)."""
        deadline = monotonic() + timeout
        while monotonic() < deadline:
            img = self._find_captcha_image()
            if img:
                try:
                    loaded = self.driver.execute_script(
                        "var img = arguments[0]; "
                        "return img && img.complete && img.naturalWidth > 30 && img.naturalHeight > 10;",
                        img
                    )
                    if loaded:
                        return img
                except Exception:
                    pass
            sleep(0.3)

        # Nếu sau timeout vẫn chưa hiện, bấm đổi mã và đợi tiếp
        try:
            self.driver.execute_script("$('#imgCaptcha').trigger('click');")
        except Exception:
            pass

        deadline2 = monotonic() + 4
        while monotonic() < deadline2:
            img = self._find_captcha_image()
            if img:
                try:
                    if self.driver.execute_script("return arguments[0].complete && arguments[0].naturalWidth > 30;", img):
                        return img
                except Exception:
                    pass
            sleep(0.3)
        return None

    def _find_captcha_input(self):
        """Tìm ô nhập mã CAPTCHA (id=tokenRecaptch)."""
        try:
            el = self.driver.find_element(By.ID, 'tokenRecaptch')
            if el.is_displayed() and el.is_enabled():
                return el
        except Exception:
            pass
        return None

    def _find_submit_button(self):
        """Tìm nút Tra cứu (id=btnTraCuu)."""
        try:
            el = self.driver.find_element(By.ID, 'btnTraCuu')
            if el.is_displayed():
                return el
        except Exception:
            pass
        return None

    def solve_and_submit_full(self, max_retries=6):
        """
        Tự động giải CAPTCHA và TỰ ĐỘNG THỬ LẠI KHI SAI:
        - Đợi ảnh CAPTCHA nạp xong 100%
        - OCR -> Điền -> Kích hoạt Tra cứu
        - Nếu CAPTCHA sai: ĐỢI ẢNH MỚI NẠP XONG HOÀN TOÀN -> OCR lại -> Thử lại tối đa max_retries lần
        - Trả về tuple (status, payload):
            * ('SUCCESS', tcContainer_html_or_text)
            * ('DATA_ERROR', error_message_from_server)
            * ('CAPTCHA_FAILED', reason)
        """
        for attempt in range(1, max_retries + 1):
            # 1. Đợi ảnh CAPTCHA xuất hiện rõ ràng
            img = self._wait_captcha_loaded(timeout=8)
            if not img:
                self.last_ocr_status = f'Lần {attempt}: Đang chờ ảnh CAPTCHA hiển thị...'
                try:
                    self.driver.execute_script("$('#imgCaptcha').trigger('click');")
                except Exception:
                    pass
                sleep(1.5)
                img = self._wait_captcha_loaded(timeout=6)

            if not img:
                continue

            # 2. OCR ảnh CAPTCHA
            try:
                screenshot_bytes = img.screenshot_as_png
                text = ocr_captcha(screenshot_bytes)
                if not text or len(text) < 3:
                    text = ocr_captcha(screenshot_bytes, preprocess=False)
            except Exception:
                text = ''

            if not text or len(text) < 4:
                # Ảnh chưa rõ chữ -> đổi mã khác và đợi ảnh mới
                try:
                    self.driver.execute_script("$('#imgCaptcha').trigger('click');")
                except Exception:
                    pass
                sleep(1.5)
                continue

            self.last_ocr_text = text
            self.last_ocr_status = f'Lần {attempt}: OCR "{text}" ➔ Đang kích hoạt Tra cứu...'

            # 3. Điền mã CAPTCHA vào ô (cả JS lẫn send_keys)
            token_inp = self._find_captcha_input()
            if token_inp:
                try:
                    token_inp.clear()
                    token_inp.send_keys(text)
                except Exception:
                    pass
            try:
                self.driver.execute_script("$('#tokenRecaptch').val(arguments[0]);", text)
            except Exception:
                pass

            # 4. Kích hoạt nút Tra cứu duy nhất 1 lần bằng jQuery
            try:
                self.driver.execute_script("""
                    window.__bhytWatch = {seq: (window.__bhytWatch ? window.__bhytWatch.seq + 1 : 1)};
                    $('#tcContainer').html('');
                    $('#messeger').html('');
                    $('#btnTraCuu').click();
                """)
            except Exception:
                pass

            # 5. Chờ phản hồi từ máy chủ (tối đa 6.0 giây, kiểm tra mỗi 0.25s)
            state = 'WAITING'
            for _ in range(24):
                sleep(0.25)
                try:
                    res = self.driver.execute_script("""
                        var tc = ($('#tcContainer').text() || '').trim();
                        var msg = ($('#messeger').text() || '').trim();
                        var dialog = ($('#dialog-message').text() || '').trim();
                        var redEl = document.querySelector('#tcContainer span[style*="red"], #tcContainer .hoten, #tcContainer fieldset span');
                        var redMsg = redEl ? redEl.innerText.trim() : '';
                        return {
                            tc: tc,
                            msg: msg,
                            dialog: dialog,
                            redMsg: redMsg
                        };
                    """)
                except Exception:
                    res = {}

                tc = res.get('tc', '')
                msg = res.get('msg', '')
                dialog = res.get('dialog', '')
                redMsg = res.get('redMsg', '')

                # 1. THÀNH CÔNG: Có kết quả tra cứu trong tcContainer
                if any(p in norm(tc) for p in ['thẻ bhyt còn giá trị sử dụng!', 'thẻ bhyt hết hạn!', 'chưa có thông tin thẻ bhyt']):
                    self.last_ocr_status = f'OCR thành công: "{text}"!'
                    return ('SUCCESS', tc)

                # 2. LỖI DỮ LIỆU ĐỎ TRONG TCCONTAINER (Sai ngày sinh, họ tên, mã thẻ...)
                if redMsg and not any(k in norm(redMsg) for k in ['mã xác nhận', 'mã xác thực', 'sai mã']):
                    clean_err = redMsg.split('.')[0].strip() or redMsg
                    self.data_error = clean_err
                    self.last_ocr_status = f'Lỗi thông tin: {clean_err}'
                    return ('DATA_ERROR', clean_err)

                # 3. LỖI DỮ LIỆU TỪ HỘP THOẠI DIALOG HOẶC #MESSEGER
                for err_text in [dialog, msg]:
                    if err_text and not any(k in norm(err_text) for k in ['mã xác nhận', 'mã xác thực', 'sai mã']):
                        clean_err = err_text.split('.')[0].strip() or err_text
                        self.data_error = clean_err
                        self.last_ocr_status = f'Lỗi thông tin: {clean_err}'
                        return ('DATA_ERROR', clean_err)

                # 4. LỖI DỮ LIỆU TRONG TEXT CỦA TCCONTAINER (Dạng văn bản thông báo)
                norm_tc = norm(tc)
                for err_phrase in ['ngày sinh không đúng', 'ngày sinh không hợp lệ', 'họ tên không đúng',
                                   'họ tên không hợp lệ', 'mã số bhxh không đúng', 'mã thẻ không đúng',
                                   'không tìm thấy thông tin']:
                    if err_phrase in norm_tc:
                        clean_err = tc.split('.')[0].strip() or err_phrase
                        self.data_error = clean_err
                        self.last_ocr_status = f'Lỗi thông tin: {clean_err}'
                        return ('DATA_ERROR', clean_err)

                # 5. CAPTCHA SAI ➔ Bắt được lỗi mã xác nhận từ máy chủ
                if any(k in norm(msg) or k in norm(dialog) or k in norm(redMsg) for k in ['mã xác nhận', 'mã xác thực', 'sai mã']):
                    state = 'CAPTCHA_WRONG'
                    break

            # NẾU CAPTCHA SAI: ĐỢI ĐỦ THỜI GIAN ĐỂ ẢNH MỚI NẠP VỀ HOÀN TOÀN RỒI MỚI THỬ TIẾP!
            if state == 'CAPTCHA_WRONG':
                self.last_ocr_status = f'Lần {attempt}: Mã "{text}" chưa đúng ➔ Chờ ảnh mới tải xong rồi thử lại...'
                sleep(2.0)  # Đợi 2 giây để server BHXH sinh và load ảnh mới hoàn toàn
                continue

            # Nếu sau 6s mà web vẫn im lìm (lag mạng) ➔ Đổi ảnh mới, đợi 1.8s rồi thử lại
            if attempt < max_retries:
                try:
                    self.driver.execute_script("$('#imgCaptcha').trigger('click');")
                except Exception:
                    pass
                sleep(1.8)
                continue

        reason = f'Không vượt được CAPTCHA sau {max_retries} lần thử'
        self.last_ocr_status = reason
        return ('CAPTCHA_FAILED', reason)

    def solve_and_submit(self, max_retries=6):
        status, payload = self.solve_and_submit_full(max_retries=max_retries)
        return (self.last_ocr_text, status in ('SUCCESS', 'DATA_ERROR'))

    def process_record(self, row, max_retries=6):
        """Mở trang, điền thông tin và thực hiện giải CAPTCHA + tra cứu tự động."""
        self.prepare(row, auto_ocr=False)
        return self.solve_and_submit_full(max_retries=max_retries)

    def prepare(self, row, auto_ocr=True):
        """Mở trang sạch, đợi ảnh CAPTCHA sẵn sàng, điền thông tin và tự động giải CAPTCHA."""
        self.ready = False
        self.data_error = ''
        self.driver.get(URL)

        # 1. ĐỢI CHO ĐẾN KHI ẢNH CAPTCHA HIỆN RÕ RÀNG TRƯỚC
        img = self._wait_captcha_loaded(timeout=10)
        if not img:
            self.driver.execute_script("$('#imgCaptcha').trigger('click');")
            sleep(1.5)
            self._wait_captcha_loaded(timeout=6)

        # 2. Sau khi ảnh đã sẵn sàng, điền thông tin
        wait = WebDriverWait(self.driver, 15)
        for field, hint, elem_id in [
            ('Mã thẻ', 'mã số BHXH/thẻ BHYT', 'txtMaThe'),
            ('Họ tên', 'họ tên', 'txtHoTen'),
            ('Ngày sinh', '1950', 'txtNgaySinh')
        ]:
            xpath = f"//input[contains(@placeholder, '{hint}')]"
            elements = wait.until(lambda d: [e for e in d.find_elements(By.XPATH, xpath) if e.is_displayed() and e.is_enabled()] or False)
            if len(elements) != 1:
                raise ValueError('Không xác định duy nhất ô ' + field)
            elements[0].clear()
            elements[0].send_keys(row[field])

        self.baseline = self.driver.find_element(By.TAG_NAME, 'body').text
        self.row_token = uuid4().hex
        self.monitor = StableResult()
        self.ready = True

        # 3. Tự động giải CAPTCHA (sẽ tự thử lại liên tục nếu sai)
        if auto_ocr:
            self.solve_and_submit()

    def auto_read(self):
        """Tự động kiểm tra và đọc kết quả khi xuất hiện trên trang mà không bị đứng hình."""
        if not self.ready:
            return None
        try:
            text = self.read()
            if text:
                return self.monitor.consider(text, self.row_token, 1, monotonic())
        except ValueError:
            return None
        return None

    def read(self):
        if not self.ready:
            raise ValueError('Hãy mở bản ghi trong Chrome trước.')
        parsed = urlparse(self.driver.current_url)
        if parsed.scheme != 'https' or parsed.hostname != 'baohiemxahoi.gov.vn' or parsed.path != urlparse(URL).path:
            raise ValueError('Chrome không ở đúng trang tra cứu BHXH.')

        # 1. Kiểm tra nếu có lỗi dữ liệu từ server (#messeger hoặc chữ đỏ trong tcContainer hoặc self.data_error)
        try:
            red_msg = self.driver.execute_script("""
                var el = document.querySelector('#tcContainer span[style*="red"], #tcContainer .hoten, #tcContainer fieldset span');
                return el ? el.innerText.trim() : '';
            """)
            if red_msg and not any(k in norm(red_msg) for k in ['mã xác nhận', 'mã xác thực', 'sai mã']):
                clean_err = red_msg.split('.')[0].strip() or red_msg
                return f"Lỗi: {clean_err}"
        except Exception:
            pass

        try:
            msg = self.driver.execute_script("return ($('#messeger').text() || '').trim();")
            if msg and not any(k in norm(msg) for k in ['mã xác nhận', 'mã xác thực', 'sai mã']):
                return f"Lỗi: {msg}"
        except Exception:
            pass

        if self.data_error:
            return f"Lỗi: {self.data_error}"

        text = self.driver.find_element(By.TAG_NAME, 'body').text
        if text == self.baseline:
            raise ValueError('Chưa phát hiện nội dung mới.')

        # NẾU LÀ LỖI CAPTCHA, KHÔNG ĐỌC THÀNH KẾT QUẢ ĐỂ HỆ THỐNG TỰ THỬ LẠI!
        if any(k in norm(text) for k in ['mã xác nhận không', 'mã xác thực không', 'sai mã']):
            raise ValueError('Đang xử lý CAPTCHA sai...')

        if input_error(text):
            return f"Lỗi: {input_error(text)}"  # Lỗi dữ liệu nhập thực sự (họ tên, ngày sinh, cccd)

        starts = [text.find(p) for p in ('Thẻ BHYT còn giá trị sử dụng!', 'Thẻ BHYT hết hạn!', 'Chưa có thông tin thẻ BHYT') if p in text]
        if len(starts) != 1:
            raise ValueError('Chưa có thông báo rõ ràng duy nhất.')
        return text[starts[0]:]

    def close(self):
        try:
            self.driver.quit()
        except Exception:
            pass
