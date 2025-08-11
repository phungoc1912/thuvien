Thư Viện Sách Cá Nhân
Đây là một ứng dụng web thư viện sách cá nhân, được xây dựng bằng Flask và có thể chạy dễ dàng thông qua Docker. Ứng dụng cho phép bạn tải lên, quản lý, đọc và sắp xếp các cuốn sách điện tử của mình.

✨ Tính năng chính
Tải lên & Quản lý: Hỗ trợ nhiều định dạng sách phổ biến (EPUB, MOBI, PDF, AZW3...).

Đọc trực tuyến: Trình đọc sách EPUB tích hợp ngay trên trình duyệt.

Tổ chức thông minh: Tạo kệ sách, yêu thích, đánh dấu, đánh giá sách.

Nhập từ Calibre: Dễ dàng nhập hàng loạt sách từ file backup của Calibre.

Quản lý người dùng: Hỗ trợ nhiều tài khoản người dùng và tài khoản khách với các quyền tùy chỉnh.

Triển khai đơn giản: Đóng gói toàn bộ ứng dụng và các thành phần phụ thuộc (Calibre) bằng Docker.

🚀 Hướng dẫn Cài đặt (Một Bước)
Chỉ cần máy tính của bạn đã cài đặt Git và Docker (bao gồm Docker Compose), bạn có thể khởi chạy toàn bộ ứng dụng chỉ với 3 lệnh.

1. Tải mã nguồn về máy
Mở terminal hoặc PowerShell và chạy lệnh sau (thay <URL-REPO-CUA-BAN> bằng URL kho lưu trữ GitHub của bạn):

git clone <URL-REPO-CUA-BAN>

2. Di chuyển vào thư mục dự án
cd <TEN-REPO-CUA-BAN>

3. Khởi chạy ứng dụng!
Đây là lệnh duy nhất bạn cần để xây dựng và chạy toàn bộ hệ thống:

docker-compose up -d

Lệnh này sẽ tự động:

Xây dựng image cho ứng dụng từ Dockerfile.

Cài đặt Calibre và các thư viện Python cần thiết.

Khởi tạo container và chạy ứng dụng của bạn ở chế độ nền.

Quá trình này có thể mất vài phút ở lần chạy đầu tiên. Sau khi hoàn tất, ứng dụng của bạn đã sẵn sàng!

💻 Sử dụng
Truy cập ứng dụng: Mở trình duyệt và truy cập vào địa chỉ: http://localhost:5000

Tài khoản quản trị viên mặc định:

Tên đăng nhập: admin

Mật khẩu: password

Bạn nên đổi mật khẩu quản trị viên ngay sau khi đăng nhập lần đầu.

📦 Quản lý Dữ liệu
Toàn bộ dữ liệu của bạn (sách, ảnh bìa, cơ sở dữ liệu, file cấu hình) sẽ được lưu trong thư mục kavita_library_data được tự động tạo ra cùng cấp với các file dự án. Điều này đảm bảo dữ liệu của bạn an toàn và không bị mất ngay cả khi bạn xóa hoặc xây dựng lại container.

🛑 Dừng ứng dụng
Để dừng ứng dụng, mở terminal trong thư mục dự án và chạy lệnh:

docker-compose down
