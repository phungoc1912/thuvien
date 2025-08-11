# Bắt đầu từ một image Python chính thức dựa trên Debian Bullseye
FROM python:3.9-bullseye

# Thiết lập thư mục làm việc bên trong container
WORKDIR /app

# Cập nhật danh sách gói và cài đặt Calibre
# Lưu ý: Calibre là một gói lớn, quá trình này có thể mất vài phút
RUN apt-get update && \
    apt-get install -y --no-install-recommends calibre wget && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Sao chép file requirements.txt vào container
COPY requirements.txt .

# Cài đặt các thư viện Python cần thiết
RUN pip install --no-cache-dir -r requirements.txt

# Sao chép toàn bộ mã nguồn của ứng dụng vào container
COPY . .

# Mở cổng 5000 để có thể truy cập ứng dụng từ bên ngoài
EXPOSE 5000

# Lệnh để chạy ứng dụng khi container khởi động
CMD ["python", "app.py"]
