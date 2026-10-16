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

    def reset_tab(self):
        """Mở tab mới sạch sẽ, xóa session cookies bị nghẽn và đóng tab cũ."""
        try:
            self.driver.delete_all_cookies()
        except Exception:
            pass
        try:
            old_tab = self.driver.current_window_handle
            self.driver.switch_to.new_window('tab')
            new_tab = self.driver.current_window_handle
            try:
                self.driver.switch_to.window(old_tab)
                self.driver.close()
            except Exception:
                pass
            self.driver.switch_to.window(new_tab)
        except Exception:
            try:
                self.driver.get(URL)
            except Exception:
                pass

    def _find_captcha_image(self):
        """Tìm element ảnh CAPTCHA (id=imgCaptcha)."""
        try:
            el = self.driver.find_element(By.ID, 'imgCaptcha')
            if el.is_displayed():
                return el
        except Exception:
            pass
        return None

    def _check_image_state(self, img=None):
        """
        Kiểm tra trạng thái ảnh CAPTCHA tức thì:
        - 'ready': Đã nạp thành công, kích thước chuẩn (> 30px).
        - 'broken': Đã nạp xong nhưng bị lỗi/vỡ icon/0 bytes (complete == true, naturalWidth <= 30).
        - 'loading': Đang tải từ máy chủ về (!complete).
        - 'not_found': Chưa tìm thấy element.
        """
        try:
            if img is None:
                img = self._find_captcha_image()
            if not img:
                return 'not_found'
            return self.driver.execute_script("""
                var img = arguments[0];
                if (!img) return 'not_found';
                if (!img.complete) return 'loading';
                if (img.naturalWidth > 30 && img.naturalHeight > 10) return 'ready';
                return 'broken';
            """, img)
        except Exception:
            return 'not_found'

    def _is_image_ready(self, img=None):
        """Kiểm tra ảnh CAPTCHA có thực sự hiển thị đầy đủ."""
        return self._check_image_state(img) == 'ready'

    def _force_reload_captcha(self):
        """Kích hoạt đổi ảnh CAPTCHA trực tiếp bằng timestamp mới nhất để tải ảnh mới ngay lập tức."""
        try:
            self.driver.execute_script("""
                var img = document.getElementById('imgCaptcha');
                if (img) {
                    img.src = '/UserControls/CaptchaImageHandler.ashx?t=' + new Date().getTime();
                }
            """)
        except Exception:
            try:
                self.driver.find_element(By.ID, 'imgCaptcha').click()
            except Exception:
                pass

    def _get_captcha_src(self):
        """Lấy URL hiện tại của ảnh CAPTCHA để theo dõi khi nào ảnh đổi."""
        try:
            return self.driver.execute_script(
                "var img = document.getElementById('imgCaptcha'); return img ? img.src : '';")
        except Exception:
            return ''

    def _wait_captcha_loaded(self, timeout=2.5):
        """
        Đợi cho đến khi ảnh CAPTCHA nạp xong chuẩn (> 30px).
        Nếu phát hiện ảnh vỡ ('broken'), ép nạp lại ngay lập tức.
        Nếu bị lỗi 2 lần liên tiếp, xóa cookies session bị nghẽn để tạo phiên mới ngay!
        """
        deadline = monotonic() + timeout
        broken_count = 0
        while monotonic() < deadline:
            img = self._find_captcha_image()
            if img:
                state = self._check_image_state(img)
                if state == 'ready':
                    return img
                elif state == 'broken':
                    broken_count += 1
                    if broken_count >= 2:
                        try:
                            self.driver.delete_all_cookies()
                            self.driver.get(URL)
                        except Exception:
                            pass
                        broken_count = 0
                    else:
                        self._force_reload_captcha()
                    sleep(0.12)
                    continue
            sleep(0.08)
        return self._find_captcha_image()

    def _wait_new_captcha(self, old_src=None, timeout=1.5):
        """
        Đợi ảnh CAPTCHA mới nạp xong sau khi tra cứu.
        Nếu sau 0.5s mà ảnh chưa đổi hoặc bị vỡ, ép đổi ảnh ngay lập tức.
        """
        deadline = monotonic() + timeout
        forced = False
        while monotonic() < deadline:
            img = self._find_captcha_image()
            if img:
                state = self._check_image_state(img)
                if state == 'ready':
                    curr_src = self._get_captcha_src()
                    if old_src is None or (curr_src and curr_src != old_src):
                        return img
                elif state == 'broken':
                    self._force_reload_captcha()
                    forced = True
                    sleep(0.12)
                    continue
            if not forced and (deadline - monotonic() < timeout - 0.5):
                self._force_reload_captcha()
                forced = True
            sleep(0.08)
        return self._find_captcha_image()

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

    def solve_and_submit_full(self, max_retries=4, row=None):
        """
        Tự động giải CAPTCHA và thử lại khi sai:
        - Đồng bộ cả 4 trường dữ liệu (mã thẻ, họ tên, ngày sinh, captcha) trước khi gửi
        - Đảm bảo 100% lệnh Tra cứu được phát đi (có fallback $.post nếu click bị nuốt)
        - Tốc độ polling siêu nhanh (0.08s) để nhận kết quả trong tích tắc
        """
        if row is None:
            row = getattr(self, 'current_row', {})

        ma_the = str(row.get('Mã thẻ', '')).strip() if row else ''
        ho_ten = str(row.get('Họ tên', '')).strip() if row else ''
        ngay_sinh = str(row.get('Ngày sinh', '')).strip() if row else ''

        for attempt in range(1, max_retries + 1):
            # 1. Đợi ảnh CAPTCHA sẵn sàng
            img = self._wait_captcha_loaded(timeout=2.0)
            if not img or self._check_image_state(img) != 'ready':
                self._force_reload_captcha()
                sleep(0.2)
                img = self._wait_captcha_loaded(timeout=2.0)
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
                self._force_reload_captcha()
                sleep(0.15)
                continue

            self.last_ocr_text = text
            self.last_ocr_status = f'Lần {attempt}: OCR "{text}" ➔ Tra cứu...'

            current_captcha_src = self._get_captcha_src()

            # 3. Điền thông tin + mã CAPTCHA + Kích hoạt Tra cứu (bảo đảm 100% không bị nuốt lệnh)
            try:
                self.driver.execute_script("""
                    var text = arguments[0];
                    var maThe = arguments[1];
                    var hoTen = arguments[2];
                    var ngaySinh = arguments[3];

                    // Luôn bảo đảm cả 3 trường dữ liệu không bị trống
                    if (maThe) { $('#txtMaThe').val(maThe); var e1 = document.getElementById('txtMaThe'); if (e1) e1.value = maThe; }
                    if (hoTen) { $('#txtHoTen').val(hoTen); var e2 = document.getElementById('txtHoTen'); if (e2) e2.value = hoTen; }
                    if (ngaySinh) { $('#txtNgaySinh').val(ngaySinh); var e3 = document.getElementById('txtNgaySinh'); if (e3) e3.value = ngaySinh; }

                    // Điền mã CAPTCHA
                    var inp = document.getElementById('tokenRecaptch');
                    if (inp) {
                        inp.value = text;
                        try { inp.dispatchEvent(new Event('input', {bubbles:true})); } catch(e) {}
                        try { inp.dispatchEvent(new Event('change', {bubbles:true})); } catch(e) {}
                    }
                    try { $('#tokenRecaptch').val(text); } catch(e) {}
                    $('#tcContainer').html('');
                    $('#messeger').html('');

                    // Kích hoạt Tra cứu qua sự kiện jQuery và click
                    var btn = document.getElementById('btnTraCuu');
                    if (btn) {
                        try { $(btn).trigger('click'); } catch(e) {}
                        try { btn.click(); } catch(e) {}
                    } else {
                        try { $('#btnTraCuu').trigger('click'); } catch(e) {}
                    }

                    // Nếu sự kiện click bị nuốt (jQuery.active vẫn = 0), gọi trực tiếp $.post của web để chống đứng hình
                    if (window.jQuery && jQuery.active === 0) {
                        $.post("/UserControls/BHXH/BaoHiemYTe/TheBHYT/pListTheBHYTThe.aspx", {
                            "txtMaThe": $('#txtMaThe').val(),
                            "tokenRecaptch": $('#tokenRecaptch').val(),
                            "txtHoTen": $('#txtHoTen').val(),
                            "txtNgaySinh": $('#txtNgaySinh').val()
                        }, function (data) {
                            try {
                                $('#imgCaptcha').trigger('click');
                                if (data.Error) {
                                    $("#messeger").html(data.Title);
                                } else {
                                    $("#tcContainer").html(data);
                                }
                            } catch (err) {
                                $("#tcContainer").html(data);
                            }
                        });
                    }
                """, text, ma_the, ho_ten, ngay_sinh)
            except Exception:
                pass

            # 4. Polling phản hồi từ máy chủ - chu kỳ 0.08s siêu nhạy (hạn chót 2.5s)
            state = 'WAITING'
            deadline = monotonic() + 2.5
            ajax_started = False

            while monotonic() < deadline:
                sleep(0.08)
                try:
                    res = self.driver.execute_script("""
                        var tc = ($('#tcContainer').text() || '').trim();
                        var msg = ($('#messeger').text() || '').trim();
                        var dialog = ($('#dialog-message').text() || '').trim();
                        var redEl = document.querySelector('#tcContainer span[style*="red"], #messeger span[style*="red"]');
                        var redMsg = redEl ? redEl.innerText.trim() : '';
                        var aj = (window.jQuery && jQuery.active > 0) ? true : false;
                        return {tc:tc, msg:msg, dialog:dialog, redMsg:redMsg, aj:aj};
                    """)
                except Exception:
                    res = {}

                is_ajax = res.get('aj', False)
                if is_ajax:
                    ajax_started = True

                tc = res.get('tc', '')
                msg = res.get('msg', '')
                dialog = res.get('dialog', '')
                redMsg = res.get('redMsg', '')

                norm_tc = norm(tc)
                norm_msg = norm(msg)
                norm_dialog = norm(dialog)
                combined = f"{norm_tc} {norm_msg} {norm_dialog}"

                if not ajax_started and not tc and not msg and not dialog and not redMsg:
                    continue

                # THÀNH CÔNG hoặc có kết quả rõ ràng (Không có thông tin, Bộ Quốc Phòng, Còn hạn, Hết hạn...)
                if any(p in combined for p in [
                    'thẻ bhyt còn giá trị sử dụng',
                    'thẻ bhyt hết hạn',
                    'chưa có thông tin',
                    'không có thông tin',
                    'không tìm thấy thông tin',
                    'chưa có dữ liệu',
                    'không tìm thấy dữ liệu',
                    'bộ quốc phòng',
                    'quốc phòng'
                ]):
                    self.last_ocr_status = f'OCR thành công: "{text}"!'
                    return ('SUCCESS', tc or dialog or msg)

                # LỖI DỮ LIỆU (chữ đỏ)
                if redMsg and not any(k in norm(redMsg) for k in ['mã xác nhận', 'mã xác thực', 'sai mã']):
                    clean_err = redMsg.split('.')[0].strip() or redMsg
                    self.data_error = clean_err
                    self.last_ocr_status = f'Lỗi thông tin: {clean_err}'
                    return ('DATA_ERROR', clean_err)

                # LỖI DỮ LIỆU từ dialog hoặc messeger
                for err_text in [dialog, msg]:
                    if err_text and not any(k in norm(err_text) for k in ['mã xác nhận', 'mã xác thực', 'sai mã']):
                        clean_err = err_text.split('.')[0].strip() or err_text
                        self.data_error = clean_err
                        self.last_ocr_status = f'Lỗi thông tin: {clean_err}'
                        return ('DATA_ERROR', clean_err)

                # LỖI DỮ LIỆU trong text tcContainer
                for err_phrase in ['ngày sinh không đúng', 'ngày sinh không hợp lệ', 'họ tên không đúng',
                                   'họ tên không hợp lệ', 'mã số bhxh không đúng', 'mã thẻ không đúng',
                                   'không tìm thấy thông tin']:
                    if err_phrase in norm_tc:
                        clean_err = tc.split('.')[0].strip() or err_phrase
                        self.data_error = clean_err
                        self.last_ocr_status = f'Lỗi: {clean_err}'
                        return ('DATA_ERROR', clean_err)

                # CAPTCHA SAI → server báo lỗi mã xác nhận
                if any(k in combined or k in norm(redMsg) for k in ['mã xác nhận', 'mã xác thực', 'sai mã']):
                    state = 'CAPTCHA_WRONG'
                    break

            # Xử lý CAPTCHA sai: Đợi ảnh mới nạp xong
            if state == 'CAPTCHA_WRONG':
                self.last_ocr_status = f'Lần {attempt}: Mã "{text}" sai ➔ Nạp ảnh mới...'
                img = self._wait_new_captcha(old_src=current_captcha_src, timeout=1.5)
                continue

            # Timeout không có phản hồi (> 2.5s): Yêu cầu bị kẹt trên máy chủ -> Hủy kết nối treo và thử lại ngay lập tức
            if attempt < max_retries:
                self.last_ocr_status = f'Lần {attempt}: Máy chủ phản hồi chậm (>2.5s) ➔ Đổi mã & gửi lại ngay...'
                try:
                    self.driver.execute_script("try { window.stop(); } catch(e) {}")
                except Exception:
                    pass
                self._force_reload_captcha()
                sleep(0.15)
                continue

        reason = f'Chưa vượt được CAPTCHA sau {max_retries} lần thử'
        self.last_ocr_status = reason
        return ('CAPTCHA_RETRY', reason)

    def solve_and_submit(self, max_retries=4):
        status, payload = self.solve_and_submit_full(max_retries=max_retries)
        return (self.last_ocr_text, status in ('SUCCESS', 'DATA_ERROR'))

    def process_record(self, row, max_attempts=3, max_retries=None):
        """
        Thực hiện tra cứu tự động cho 1 bản ghi:
        - Mở trang, kiểm tra ảnh CAPTCHA nạp thành công rồi mới điền form.
        - Tự động giải CAPTCHA (tối đa 4 lần thử nhanh trong cùng 1 tab).
        - Nếu vẫn chưa qua thì mới làm mới phiên.
        """
        if max_retries is not None:
            max_attempts = max_retries

        for attempt in range(1, max_attempts + 1):
            try:
                force_tab = (attempt > 1)
                if attempt == 1:
                    self.prepare(row, auto_ocr=False)
                else:
                    self.prepare(row, auto_ocr=False, force_new_tab=True)

                status, payload = self.solve_and_submit_full(max_retries=4, row=row)
                if status in ('SUCCESS', 'DATA_ERROR'):
                    return (status, payload)
            except Exception as e:
                self.last_ocr_status = f"Làm mới trang ({e})"
                sleep(0.3)
                try:
                    self.reset_tab()
                except Exception:
                    pass

        return ('CAPTCHA_RETRY', 'Chưa qua CAPTCHA sau các lần thử, tiếp tục làm lại')

    def prepare(self, row, auto_ocr=True, force_new_tab=False):
        """Mở trang sạch hoặc tái sử dụng trang hiện tại, đợi ảnh CAPTCHA sẵn sàng, điền thông tin và chuẩn bị giải."""
        self.ready = False
        self.data_error = ''
        self.current_row = row

        can_reuse = False
        if not force_new_tab:
            try:
                curr = self.driver.current_url or ''
                if 'baohiemxahoi.gov.vn' in curr:
                    el = self.driver.find_element(By.ID, 'txtMaThe')
                    if el.is_displayed():
                        can_reuse = True
            except Exception:
                can_reuse = False

        if not can_reuse:
            if force_new_tab:
                self.reset_tab()
            self.driver.get(URL)
            img = self._wait_captcha_loaded(timeout=2.5)
            if not img or self._check_image_state(img) != 'ready':
                try:
                    self.driver.delete_all_cookies()
                    self.driver.get(URL)
                    img = self._wait_captcha_loaded(timeout=2.5)
                except Exception:
                    pass
            if not img or self._check_image_state(img) != 'ready':
                raise RuntimeError('Ảnh CAPTCHA chưa tải được từ máy chủ BHXH. Đang thử lại...')
        else:
            # Tái sử dụng trang đã tải sẵn: dọn dẹp các khung kết quả cũ và ô captcha
            try:
                self.driver.execute_script("""
                    $('#tcContainer').html('');
                    $('#messeger').html('');
                    var inp = document.getElementById('tokenRecaptch');
                    if (inp) inp.value = '';
                    try { $('#tokenRecaptch').val(''); } catch(e) {}
                """)
            except Exception:
                pass

            # Đợi ảnh CAPTCHA mới sẵn sàng (thường đã được web tự tải ngầm sau khi submit)
            img = self._wait_captcha_loaded(timeout=1.2)
            if not img or self._check_image_state(img) != 'ready':
                try:
                    self.driver.execute_script("$('#imgCaptcha').trigger('click');")
                    img = self._wait_captcha_loaded(timeout=1.5)
                except Exception:
                    pass

            if not img or self._check_image_state(img) != 'ready':
                # Nếu không thể tải captcha trên trang cũ thì mới tải lại trang
                self.driver.get(URL)
                img = self._wait_captcha_loaded(timeout=2.5)
                if not img or self._check_image_state(img) != 'ready':
                    raise RuntimeError('Ảnh CAPTCHA chưa tải được từ máy chủ BHXH. Đang thử lại...')

        # 2. Sau khi ảnh đã sẵn sàng 100%, điền thông tin trực tiếp bằng ID và JavaScript
        ma_the = str(row.get('Mã thẻ', '')).strip()
        ho_ten = str(row.get('Họ tên', '')).strip()
        ngay_sinh = str(row.get('Ngày sinh', '')).strip()

        wait = WebDriverWait(self.driver, 5)
        wait.until(lambda d: d.find_element(By.ID, 'txtMaThe').is_displayed() and d.find_element(By.ID, 'txtHoTen').is_displayed() and d.find_element(By.ID, 'txtNgaySinh').is_displayed())

        self.driver.execute_script("""
            var maThe = arguments[0];
            var hoTen = arguments[1];
            var ngaySinh = arguments[2];

            function setVal(id, val) {
                var el = document.getElementById(id);
                if (el) {
                    el.value = val;
                    try { $(el).val(val).trigger('input').trigger('change'); } catch(e) {}
                }
            }

            setVal('txtMaThe', maThe);
            setVal('txtHoTen', hoTen);
            setVal('txtNgaySinh', ngaySinh);
            $('#tcContainer').html('');
            $('#messeger').html('');
        """, ma_the, ho_ten, ngay_sinh)

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
