# PeerHost

**PeerHost** là hệ thống Minecraft Server theo mô hình Hybrid P2P, được thiết kế để kết hợp sự linh hoạt của việc tự host với sự ổn định của máy chủ trung tâm. Hệ thống cho phép người chơi tận dụng tài nguyên cá nhân để vận hành thế giới game, trong khi Server trung tâm (`Coordinator`) đóng vai trò điều phối, đồng bộ dữ liệu và quản lý phiên làm việc.

Giải pháp này giúp giảm thiểu chi phí vận hành server truyền thống, đồng thời đảm bảo tính toàn vẹn và đồng nhất của dữ liệu thế giới cho nhóm người chơi.

## Tính Năng Chính

### 1. Kiến Trúc Hybrid P2P Thông Minh
*   **Coordinator (Server)**: Giữ vai trò trọng tài, lưu trữ dữ liệu gốc và điều phối quyền Host. Không chạy logic game nặng nề, giúp tiết kiệm tài nguyên.
*   **Client (Host)**: Người chơi đóng vai trò Host sẽ chạy game server thực tế. Dữ liệu được đồng bộ hai chiều với Coordinator.

### 2. Hệ Thống Đồng Bộ (Sync System)
*   **Pre-Sync**: Tự động kiểm tra và tải xuống các dữ liệu mới nhất từ Coordinator trước khi khởi chạy server, đảm bảo mọi người chơi đều bắt đầu từ trạng thái mới nhất.
*   **Real-time Sync**: (Đang phát triển) Đồng bộ các thay đổi quan trọng trong thời gian thực.
*   **Data Integrity**: Sử dụng thuật toán băm SHA-256 để kiểm tra toàn vẹn file, đảm bảo không có sự sai lệch dữ liệu giữa các máy.
*   **Security & Rollback**: Hệ thống tự động phát hiện và khôi phục các file bị chỉnh sửa trái phép hoặc bị lỗi.

### 3. Quản Lý Session (Session Management)
*   **Atomic Claim**: Cơ chế khóa (Locking) đảm bảo tại một thời điểm chỉ có duy nhất một Client được quyền làm Host, ngăn chặn xung đột dữ liệu (Split-brain).
*   **Heartbeat**: Giám sát liên tục trạng thái của Host. Nếu Host mất kết nối hoặc gặp sự cố, session sẽ tự động được thu hồi để bảo vệ dữ liệu.
*   **Smart Storage**: Dữ liệu thế giới được tổ chức khoa học trong `world_data`, tách biệt với metadata hệ thống.

## Cài Đặt và Sử Dụng

### Yêu Cầu Hệ Thống
*   **Python**: Phiên bản 3.11 trở lên.
*   **Mạng**: Kết nối Internet ổn định.
*   **OS**: Windows (Khuyến nghị), Linux, macOS.

### 1. Coordinator (Server)

Server đóng vai trò là kho lưu trữ trung tâm và API quản lý.

**Bước 1: Thiết lập môi trường**
```bash
python -m venv .venv
.venv\Scripts\Activate.ps1  # Windows
pip install -r requirements.txt
```

**Bước 2: Khởi chạy**
Server sẽ chạy mặc định tại cổng 8000.
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 2. Client (Host)

Ứng dụng Client dùng để đồng bộ dữ liệu và khởi chạy Minecraft Server.

**Bước 1: Cấu hình**
Chỉnh sửa file `client/settings.json`:
*   `server_url`: Địa chỉ IP/Domain của Coordinator (VD: `http://localhost:8000`).
*   `host_id`: Định danh duy nhất cho máy khách này.
*   `watch_dir`: Thư mục chứa dữ liệu world (VD: `./world`).

**Bước 2: Khởi chạy**
```bash
python client/client.py
```

## Cấu Trúc Dữ Liệu

Hệ thống tổ chức dữ liệu tại Coordinator như sau:

*   **storage/**: Thư mục gốc lưu trữ.
    *   **world_data/**: Chứa toàn bộ file của Minecraft Server (level.dat, region files, ...).
    *   **meta/**: Chứa dữ liệu phiên (session.json) và cơ sở dữ liệu chỉ mục.
    *   **snapshots/**: (Tùy chọn) Chứa các bản sao lưu dự phòng.

## Đóng Góp

Dự án được phát triển với mục tiêu mã nguồn mở. Mọi đóng góp về mã nguồn, báo lỗi hoặc đề xuất tính năng đều được hoan nghênh.

## Bản Quyền

Dự án được phân phối dưới giấy phép [MIT License](LICENSE).
