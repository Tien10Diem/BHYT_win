# BHYT Auto — Phiên Bản Tự Động Toàn Bộ (Auto-Retry & Resilient Watcher)

Phiên bản nâng cấp tối ưu hóa cho Windows với 2 tính năng chính:
1. **Tự động bắt lỗi khi CAPTCHA sai (Auto-Retry)**: Nếu OCR đọc sai mã và web báo "Mã xác nhận không hợp lệ", hệ thống lập tức chụp mã CAPTCHA mới, OCR lại và bấm Tra cứu lại cho đến khi thành công (thử tối đa 6 lần).
2. **Theo dõi kết quả bền vững (Resilient Watcher)**: Không phụ thuộc vào JavaScript click listener, trực tiếp kiểm tra trạng thái kết quả trên màn hình nên không bao giờ bị đứng hình.
3. **Chống nghẽn & chống mất ảnh CAPTCHA**: Dùng nút "Nhập lại" thay vì reload trang và có độ trễ nghỉ 1.5s giữa các bản ghi để server BHXH luôn cấp ảnh CAPTCHA mượt mà.

## Cách sử dụng
1. Nhấp đúp chuột vào file `launch.bat`.
2. Trình duyệt tự mở giao diện Web tại `http://127.0.0.1:851x`.
3. Tải file danh sách Excel lên rồi bấm **Nạp danh sách vào hệ thống**.
4. Bấm nút **▶️ BẮT ĐẦU CHẠY TỰ ĐỘNG TOÀN BỘ**.
5. Hệ thống sẽ tự động điền, tự giải CAPTCHA, nếu sai tự thử lại, tự lưu vào file Excel kết quả tại `data/results/` và tự chuyển người tiếp theo cho đến khi hết danh sách.
6. Khi hoàn tất, bấm **Tải file Excel kết quả về máy**.
