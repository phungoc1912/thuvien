#!/bin/bash

# ===================================================================================
# Script Cài Đặt Tự Động cho Ứng Dụng Thư Viện Sách
#
# Chức năng:
# 1. Kiểm tra và cài đặt Git, Docker, và Docker Compose nếu chưa có.
# 2. Tải mã nguồn mới nhất từ kho lưu trữ GitHub.
# 3. Xây dựng (build) và khởi chạy ứng dụng bằng Docker Compose.
#
# Yêu cầu: Chạy với quyền sudo.
# Cách dùng: curl -sSL <URL-raw-cua-file-nay> | sudo bash
# ===================================================================================

# --- Biến và Cấu hình ---
REPO_URL="https://github.com/phungoc1912/thuvien.git"
REPO_DIR="thuvien"
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# --- Hàm chức năng ---

# In thông báo với màu sắc
log_info() {
    echo -e "${GREEN}[INFO] $1${NC}"
}

log_warn() {
    echo -e "${YELLOW}[WARN] $1${NC}"
}

# Kiểm tra quyền root
check_root() {
    if [ "$EUID" -ne 0 ]; then
        log_warn "Vui lòng chạy script này với quyền sudo."
        exit 1
    fi
}

# Cài đặt các gói cần thiết
install_dependencies() {
    log_info "Kiểm tra và cài đặt các gói cần thiết (git, curl)..."
    if ! command -v git &> /dev/null || ! command -v curl &> /dev/null; then
        apt-get update
        apt-get install -y git curl
    else
        log_info "Git và Curl đã được cài đặt."
    fi
}

# Kiểm tra và cài đặt Docker
install_docker() {
    # Kiểm tra xem plugin compose có hoạt động không
    if docker compose version &> /dev/null; then
        log_info "Docker và Docker Compose đã được cài đặt."
    else
        log_info "Docker hoặc Docker Compose chưa được cài đặt đúng. Bắt đầu quá trình cài đặt..."
        # Sử dụng script chính thức từ Docker để cài đặt
        curl -fsSL https://get.docker.com -o get-docker.sh
        sh get-docker.sh
        rm get-docker.sh
        
        # Thêm người dùng hiện tại vào nhóm docker để không cần sudo khi chạy lệnh docker
        SUDO_USER=$(logname)
        if [ -n "$SUDO_USER" ]; then
            usermod -aG docker "$SUDO_USER"
            log_info "Đã thêm người dùng '$SUDO_USER' vào nhóm docker."
            log_warn "Bạn có thể cần đăng xuất và đăng nhập lại để thay đổi có hiệu lực."
        fi
        
        log_info "Đảm bảo Docker Compose plugin đã được cài đặt..."
        apt-get install -y docker-compose-plugin || apt-get install -y docker-compose
    fi
}

# Tải hoặc cập nhật mã nguồn
clone_or_update_repo() {
    if [ -d "$REPO_DIR" ]; then
        log_warn "Thư mục '$REPO_DIR' đã tồn tại. Đang xóa để tải phiên bản mới nhất..."
        rm -rf "$REPO_DIR"
    fi
    log_info "Đang tải mã nguồn từ GitHub..."
    git clone "$REPO_URL"
    if [ $? -ne 0 ]; then
        echo "Lỗi: Không thể tải mã nguồn từ GitHub."
        exit 1
    fi
}

# Xây dựng và chạy container
build_and_run() {
    cd "$REPO_DIR" || exit
    log_info "Đang ở trong thư mục: $(pwd)"
    log_info "Bắt đầu xây dựng và khởi chạy container..."
    
    if [ ! -f "docker-compose.yml" ]; then
        echo "Lỗi: Không tìm thấy file docker-compose.yml."
        exit 1
    fi

    # SỬA LỖI: Dùng 'docker compose' thay vì 'docker-compose'
    docker compose up -d --build
    if [ $? -ne 0 ]; then
        echo "Lỗi: Docker Compose thất bại."
        exit 1
    fi
}

# --- Luồng chính ---
main() {
    check_root
    install_dependencies
    install_docker
    clone_or_update_repo
    build_and_run

    log_info "============================================================"
    log_info "🎉 CÀI ĐẶT HOÀN TẤT! 🎉"
    log_info "Ứng dụng Thư Viện Sách đang chạy."
    log_info "Truy cập vào: http://localhost:5000"
    log_info "Tài khoản mặc định: admin / password"
    log_info "Dữ liệu của bạn được lưu tại thư mục '$REPO_DIR/kavita_library_data'"
    log_info "Để dừng ứng dụng, chạy lệnh: cd $REPO_DIR && docker compose down"
    log_info "============================================================"
}

# Chạy hàm main
main
