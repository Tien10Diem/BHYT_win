# Hướng dẫn sử dụng Tra cứu BHYT trên Windows

Ứng dụng hỗ trợ tự động điền danh sách từ Excel vào trang tra cứu BHXH Việt Nam, theo dõi kết quả và tự động lưu vào file Excel kết quả.

## 1. Yêu cầu hệ thống
- Hệ điều hành: Windows 10 hoặc Windows 11 (64-bit).
- Đã cài đặt **Google Chrome**.
- Đã cài đặt **Python** (phiên bản 3.10 trở lên).

## 2. Cách khởi động
- **Cách 1 (Nhanh nhất):** Nhấp đúp chuột vào file `launch.bat`.
- **Cách 2 (Qua dòng lệnh CMD / PowerShell):**
  ```cmd
  cd BHYT_Windows
  python launcher.py
  ```

## 3. Cách sử dụng
1. Khi ứng dụng khởi động, trình duyệt sẽ tự động mở giao diện Streamlit tại `http://127.0.0.1:851x`.
2. Tải lên file Excel danh sách cần tra cứu (mẫu chuẩn có 3 cột: `Mã thẻ`, `Họ tên`, `Ngày sinh` định dạng Text) rồi nhấn **Nạp danh sách**. (Có file mẫu `mau_nhap.xlsx` trong thư mục `app/`).
3. Nhấn **Mở / điền bản ghi trong Chrome**:
   - Trình duyệt Chrome sẽ tự động bật lên và điền sẵn Họ tên, Mã thẻ, Ngày sinh.
   - Bạn chỉ cần nhìn mã CAPTCHA trên màn hình Chrome và gõ mã vào ô CAPTCHA rồi nhấn **Tra cứu**.
4. Chế độ **"Tự đọc kết quả và chuyển tiếp"** được bật mặc định: sau khi tra cứu thành công, ứng dụng sẽ tự động nhận diện kết quả, lưu vào file Excel và tự động chuyển sang dòng tiếp theo trong danh sách.
5. Kết quả tra cứu được lưu tự động tại thư mục `data/results/`.
6. Khi hoàn tất: Bấm nút **Đóng Chrome** trên giao diện Web, sau đó quay lại cửa sổ dòng lệnh nhấn `Ctrl + C` để tắt.

## 4. Lưu ý về CAPTCHA
- Mã xác nhận (CAPTCHA) trên cổng Dịch vụ công BHXH là biện pháp bảo vệ chống bot tự động hóa và bảo mật dữ liệu công dân. Hệ thống được thiết kế để người dùng nhập tay CAPTCHA nhằm đảm bảo ổn định, tránh bị chặn IP hoặc từ chối dịch vụ.
