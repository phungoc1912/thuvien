Thư Viện Sách Cá Nhân
Đây là một ứng dụng web thư viện sách cá nhân, được xây dựng bằng Flask và có thể chạy dễ dàng thông qua Docker. Ứng dụng cho phép bạn tải lên, quản lý, đọc và sắp xếp các cuốn sách điện tử của mình.

✨ Tính năng chính
Tải lên & Quản lý: Hỗ trợ nhiều định dạng sách phổ biến (EPUB, MOBI, PDF, AZW3...).

Đọc trực tuyến: Trình đọc sách EPUB tích hợp ngay trên trình duyệt.

Tổ chức thông minh: Tạo kệ sách, yêu thích, đánh dấu, đánh giá sách.

Nhập từ Calibre: Dễ dàng nhập hàng loạt sách từ file backup của Calibre.

Quản lý người dùng: Hỗ trợ nhiều tài khoản người dùng và tài khoản khách với các quyền tùy chỉnh.

Triển khai đơn giản: Đóng gói toàn bộ ứng dụng và các thành phần phụ thuộc (Calibre) bằng Docker.

🚀 Hướng dẫn Cài đặt
Cài đặt siêu tốc (Khuyên dùng cho Linux)
Mở terminal và chạy một lệnh duy nhất dưới đây. Script sẽ tự động kiểm tra và cài đặt các phần mềm cần thiết, tải mã nguồn và khởi chạy ứng dụng cho bạn.

curl -sSL https://raw.githubusercontent.com/phungoc1912/thuvien/main/install.sh | sed 's/\r$//' | sudo bash

Sau khi script chạy xong, ứng dụng của bạn sẽ sẵn sàng để sử dụng.

Cài đặt thủ công
Nếu bạn muốn cài đặt thủ công hoặc đang sử dụng Windows/macOS, hãy đảm bảo máy tính của bạn đã cài đặt Git và Docker (bao gồm Docker Compose).

1. Tải mã nguồn về máy

git clone https://github.com/phungoc1912/thuvien.git

2. Di chuyển vào thư mục dự án

cd thuvien

3. Khởi chạy ứng dụng!

docker-compose up -d

💻 Sử dụng
Truy cập ứng dụng: Mở trình duyệt và truy cập vào địa chỉ: http://localhost:5000

Tài khoản quản trị viên mặc định:

Tên đăng nhập: admin

Mật khẩu: password

Bạn nên đổi mật khẩu quản trị viên ngay sau khi đăng nhập lần đầu.

📦 Quản lý Dữ liệu
Toàn bộ dữ liệu của bạn (sách, ảnh bìa, cơ sở dữ liệu, file cấu hình) sẽ được lưu trong thư mục thuvien/kavita_library_data được tự động tạo ra. Điều này đảm bảo dữ liệu của bạn an toàn và không bị mất ngay cả khi bạn xóa hoặc xây dựng lại container.

🛑 Dừng ứng dụng
Để dừng ứng dụng, mở terminal trong thư mục thuvien và chạy lệnh:

docker-compose down
