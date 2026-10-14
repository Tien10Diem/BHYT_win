from datetime import datetime
from io import BytesIO
from pathlib import Path
from uuid import uuid4
import re
import os
from time import sleep
import pandas as pd
import streamlit as st
from openpyxl import load_workbook
from browser import Browser
from core import parse_result, save_atomic, excel_bytes, input_result

RESULTS_DIR = Path(os.environ.get('BHYT_DATA_DIR', str(Path(__file__).parent))) / 'results'

st.set_page_config(page_title='Tra cứu BHYT • Tự Động 100%', layout='wide')
st.title('Tra cứu BHYT • Tự Động 100% & Bảng Theo Dõi Trực Tiếp')
st.caption('Tự động điền dữ liệu, giải CAPTCHA (tự thử lại khi sai), ghi nhận chi tiết lỗi thông tin và cập nhật bảng trực tiếp từng case.')

ss = st.session_state
defaults = {
    'rows': [],
    'results': [],
    'index': 0,
    'browser': None,
    'notice': '',
    'auto_running': False,
    'delay_sec': 0.5,
    'max_retries': 6
}
for key, value in defaults.items():
    if key not in ss:
        ss[key] = value

if 'output' not in ss:
    ss.output = RESULTS_DIR / ('bhyt_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid4().hex[:8] + '.xlsx')

def read_input(data):
    wb = load_workbook(BytesIO(data), read_only=True, data_only=False)
    try:
        ws = wb.active
        if ws.max_row > 10001 or ws.max_column > 100:
            raise ValueError('Giới hạn 10.000 dòng và 100 cột.')
        it = ws.iter_rows()
        headers = [str(c.value or '').strip() for c in next(it)]
        required = ['Mã thẻ', 'Họ tên', 'Ngày sinh']
        if any(headers.count(h) != 1 for h in required):
            raise ValueError('Cần ba cột duy nhất: Mã thẻ, Họ tên, Ngày sinh.')
        positions = [headers.index(h) for h in required]
        rows = []
        for number, cells in enumerate(it, 2):
            if all(c.value is None for c in cells):
                continue
            selected = [cells[i] for i in positions]
            if any(c.data_type == 'f' or not isinstance(c.value, str) for c in selected):
                raise ValueError(f'Dòng {number}: ba trường phải là Text, không phải công thức/số/ngày Excel.')
            row = dict(zip(required, [c.value.strip() for c in selected]))
            if not re.fullmatch(r'[A-Za-z0-9]{10,15}', row['Mã thẻ']) or not row['Họ tên']:
                raise ValueError(f'Dòng {number}: mã thẻ/họ tên không hợp lệ.')
            if not re.fullmatch(r'(?:\d{4}|\d{2}/\d{2}/\d{4})', row['Ngày sinh']):
                raise ValueError(f'Dòng {number}: ngày sinh dùng dd/mm/yyyy hoặc yyyy.')
            row['STT nguồn'] = str(number)
            rows.append(row)
        if not rows:
            raise ValueError('Excel không có bản ghi.')
        return rows
    finally:
        wb.close()

def commit_result(row, result):
    result.update({
        'STT nguồn': row['STT nguồn'],
        'Đọc lúc': datetime.now().astimezone().isoformat(timespec='seconds')
    })
    new_results = ss.results + [result]
    ss.results = new_results
    try:
        save_atomic(ss.output, new_results)
    except PermissionError:
        ss.notice = '⚠️ Không thể ghi file kết quả do file đang được mở trong Excel. Vui lòng đóng file để lưu tiếp.'
    except Exception as e:
        ss.notice = f'Lỗi lưu kết quả: {str(e)}'
    ss.index += 1

# Bố cục 2 cột: Trái (Điều khiển & Tiến độ), Phải (Bảng kết quả trực tiếp)
left, right = st.columns([1, 1.35])

with left:
    # 1. Nạp file Excel nếu chưa có dữ liệu
    if not ss.rows:
        upload = st.file_uploader('Chọn file danh sách Excel (.xlsx)', type=['xlsx'])
        if upload and st.button('📥 Nạp danh sách và chuẩn bị', type='primary'):
            try:
                ss.rows = read_input(upload.getvalue())
                ss.index = 0
                ss.results = []
                ss.notice = f'Đã nạp thành công {len(ss.rows)} bản ghi. Hãy bấm "Bắt đầu chạy tự động".'
                st.rerun()
            except Exception as exc:
                st.error(str(exc) if isinstance(exc, ValueError) else 'Lỗi đọc file Excel. Kiểm tra định dạng.')
        st.caption('Cột bắt buộc trong file: Mã thẻ, Họ tên, Ngày sinh (định dạng Text, ngày sinh dd/mm/yyyy hoặc yyyy).')
    else:
        # 2. Điều khiển Tự Động Toàn Bộ
        st.subheader('⚙️ Điều Khiển Tự Động')

        ctrl_col1, ctrl_col2 = st.columns([1.3, 1])
        with ctrl_col1:
            if not ss.auto_running:
                if ss.index < len(ss.rows):
                    btn_text = '▶️ TIẾP TỤC CHẠY TỰ ĐỘNG' if ss.index > 0 else '▶️ BẮT ĐẦU CHẠY TỰ ĐỘNG TOÀN BỘ'
                    if st.button(btn_text, type='primary', use_container_width=True):
                        ss.auto_running = True
                        ss.notice = 'Đang bắt đầu chạy tự động...'
                        st.rerun()
                else:
                    st.success('🎉 Đã hoàn thành tra cứu toàn bộ danh sách!')
            else:
                if st.button('⏸️ TẠM DỪNG TỰ ĐỘNG', type='secondary', use_container_width=True):
                    ss.auto_running = False
                    ss.notice = 'Đã tạm dừng tự động.'
                    st.rerun()

        with ctrl_col2:
            ss.delay_sec = st.slider('Nghỉ giữa mỗi case (giây)', min_value=0.0, max_value=3.0, value=float(ss.delay_sec), step=0.5)

        # Thanh tiến độ
        progress_val = min(1.0, ss.index / max(1, len(ss.rows)))
        st.progress(progress_val, text=f'Tiến độ: {ss.index} / {len(ss.rows)} bản ghi ({int(progress_val * 100)}%)')

        if ss.index < len(ss.rows):
            current_row = ss.rows[ss.index]
            with st.container(border=True):
                st.markdown(f"**Đang xử lý:** `{current_row['Họ tên']}` | Ngày sinh: `{current_row['Ngày sinh']}` | Mã: `{current_row['Mã thẻ']}` (Dòng {ss.index + 1}/{len(ss.rows)})")
                if ss.browser and ss.browser.last_ocr_status:
                    st.caption(f"🔍 Trạng thái OCR: {ss.browser.last_ocr_status}")

            # Thao tác thủ công bổ trợ (khi cần)
            with st.expander('🛠️ Thao tác thủ công bổ trợ (tùy chọn)'):
                m_col1, m_col2 = st.columns(2)
                with m_col1:
                    if st.button('⏭️ Bỏ qua dòng này', use_container_width=True, help='Bỏ qua người này và chuyển sang dòng tiếp theo.'):
                        commit_result(current_row, input_result(current_row, 'Bỏ qua', 'Người dùng bỏ qua, chưa tra cứu'))
                        st.rerun()
                with m_col2:
                    if st.button('🔄 Tra cứu lại từ đầu', use_container_width=True, help='Đặt lại từ dòng 1 và tạo file kết quả mới.'):
                        ss.results = []
                        ss.index = 0
                        ss.auto_running = False
                        ss.output = RESULTS_DIR / ('bhyt_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid4().hex[:8] + '.xlsx')
                        ss.notice = 'Đã đặt lại danh sách về dòng đầu.'
                        st.rerun()

        if ss.notice:
            st.info(ss.notice)

with right:
    st.subheader('📋 Bảng Theo Dõi Trực Tiếp Từng Case')

    if ss.results:
        df = pd.DataFrame(ss.results)

        # Thống kê nhanh kết quả
        counts = df['Trạng thái'].value_counts().to_dict() if 'Trạng thái' in df.columns else {}
        stat_parts = [f"**Tổng**: {len(df)}/{len(ss.rows)}"]
        if 'Còn giá trị sử dụng' in counts:
            stat_parts.append(f"🟢 **Còn hạn**: {counts['Còn giá trị sử dụng']}")
        if 'Hết hạn' in counts:
            stat_parts.append(f"🔴 **Hết hạn**: {counts['Hết hạn']}")
        if 'Lỗi' in counts:
            stat_parts.append(f"🟠 **Lỗi**: {counts['Lỗi']}")
        if 'Không có' in counts:
            stat_parts.append(f"🟡 **Không có**: {counts['Không có']}")
        if 'Bỏ qua' in counts:
            stat_parts.append(f"⚪ **Bỏ qua**: {counts['Bỏ qua']}")
        st.markdown(" | ".join(stat_parts))

        # Nút tải file Excel
        st.download_button(
            '📥 Tải file Excel kết quả hiện tại',
            data=excel_bytes(ss.results),
            file_name=ss.output.name,
            mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            type='primary',
            use_container_width=True
        )

        # Hiển thị bảng kết quả với case mới nhất nằm trên cùng
        cols = [c for c in ['STT nguồn', 'Họ tên', 'Ngày sinh', 'Mã thẻ', 'Trạng thái', 'Hạn thẻ', 'Ghi chú'] if c in df.columns]
        st.dataframe(df[cols].iloc[::-1], hide_index=True, use_container_width=True, height=520)
        st.caption(f'📁 Tự động lưu trực tiếp trên ổ đĩa tại: `{ss.output}`')
    else:
        st.info('👉 Kết quả từng case sẽ tự động cập nhật lên bảng này ngay khi tra cứu xong từng người (case mới nhất nằm trên cùng).')

    st.divider()
    if st.button('🚫 Đóng trình duyệt Chrome'):
        if ss.browser:
            try:
                ss.browser.close()
            except Exception:
                pass
        ss.browser = None
        ss.auto_running = False
        ss.notice = 'Đã đóng Chrome.'
        st.rerun()

# --- VÒNG LẶP CHẠY TỰ ĐỘNG TOÀN BỘ (ĐẶT Ở CUỐI SCRIPT ĐỂ UI LUÔN HIỂN THỊ TRƯỚC) ---
if ss.auto_running and ss.index < len(ss.rows):
    current_row = ss.rows[ss.index]
    result = None

    try:
        if ss.browser is None:
            ss.browser = Browser()

        # Thực hiện toàn bộ quy trình: Mở trang -> Điền -> OCR -> Tra cứu (tự retry 6 lần nếu sai CAPTCHA)
        status, payload = ss.browser.process_record(current_row, max_retries=ss.max_retries)

        if status == 'SUCCESS':
            result = parse_result(payload, current_row)
        elif status == 'DATA_ERROR':
            result = input_result(current_row, 'Lỗi', payload)
        elif status == 'CAPTCHA_FAILED':
            result = input_result(current_row, 'Lỗi', payload)
        else:
            result = input_result(current_row, 'Lỗi', f'Phản hồi không rõ ràng: {payload}')

    except Exception as exc:
        # Nếu Chrome bị crash hoặc lỗi kết nối, đóng để mở lại ở case tiếp theo
        try:
            if ss.browser:
                ss.browser.close()
        except Exception:
            pass
        ss.browser = None
        result = input_result(current_row, 'Lỗi', f'Lỗi hệ thống: {str(exc)}')

    if result:
        commit_result(current_row, result)

    # Nghỉ giữa mỗi case theo thiết lập
    if ss.delay_sec > 0:
        sleep(ss.delay_sec)

    # Nếu đã chạy hết danh sách
    if ss.index >= len(ss.rows):
        ss.auto_running = False
        ss.notice = '🎉 Đã hoàn thành tra cứu toàn bộ danh sách!'

    # Tự động chuyển và nạp case tiếp theo
    st.rerun()
