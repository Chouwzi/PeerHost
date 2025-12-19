# PeerHost

PeerHost - Hệ thống Minecraft Hybrid P2P, nơi người chơi tự host thế giới, trong khi server chỉ điều phối chọn host và đồng bộ dữ liệu world. Nhanh, giảm chi phí, ổn định và dễ sử dụng.

## Mô tả

PeerHost cho phép một người chơi (client) làm `host` cho phiên chơi, trong khi một `Coordinator` (server điều phối) giữ vai trò đồng bộ, lưu trữ snapshot và đảm bảo rằng chỉ có duy nhất một client làm host cho mỗi session. Thay vì đồng bộ toàn bộ world mỗi lần, PeerHost hỗ trợ cơ chế delta-sync: khi host cập nhật world, host chỉ gửi những phần bị thiếu hoặc thay đổi (delta) lên Coordinator; Coordinator lưu giữ và/hoặc hợp nhất các delta này rồi phân phối cho các client khác khi cần.

## Mục tiêu

- Thay thế phương pháp P2P truyền thống phức tạp bằng mô hình hybrid dễ triển khai cho nhóm bạn bè nhỏ.
- Chi phí thấp hơn so với server minecraft truyền thống
- Đảm bảo chỉ 1 host mỗi session (leader lock) để tránh xung đột dữ liệu.
- Đồng bộ delta (chỉ cập nhật các vùng/thay đổi thiếu) để giảm băng thông và thời gian đồng bộ.
- Server làm nhiệm vụ điều phối, lưu snapshot và sao lưu, không giữ trạng thái chơi trực tiếp.

## Tính năng chính

- Đăng ký host (Coordinator giữ `host lock`).
- Delta-sync: host gửi chỉ các phần thay đổi; Coordinator lưu delta và phân phối cho client khác.
- Đồng bộ hai chiều giữa host <-> Coordinator.
- Hỗ trợ tunnel qua `cloudflared` để client ngoài NAT/Firewall vẫn kết nối dễ dàng.
- Lưu trữ snapshot, phục hồi và rollback.
- HTTP API để giám sát, quản lý session và trigger sync.

## Kiến trúc tổng quan

Thành phần chính:
- `Client` (Peer): Ứng dụng client chạy trên máy người chơi; có thể làm `host` hoặc `participant`.
- `Coordinator` (Server): Cung cấp API đăng ký/thu hồi host, lưu delta/snapshot, và đảm bảo lock cho host duy nhất.
- `Storage`: Lưu delta, snapshot và metadata.

Luồng hoạt động (chi tiết):
1. Người chơi A khởi tạo phiên và request `host lock` lên Coordinator.
2. Nếu Coordinator cấp lock, A trở thành host. Host có thể upload snapshot khởi tạo hoặc incremental delta.
3. Khi host thay đổi world (ví dụ khu vực mới, chunk thay đổi), host gửi chỉ các delta (vùng/chunk thiếu hoặc khác) lên Coordinator.
4. Coordinator lưu delta và hợp nhất vào view latest của world.
5. Các client B/C/... khi muốn tham gia: chạy client, kết nối qua `cloudflared` tunnel với host để truy cập world.
6. Khi host kết thúc hoặc bị ngắt, Coordinator giải phóng `host lock` và khởi động cơ chế chuyển host.

Lưu ý: mô hình hướng tới giảm yêu cầu cấu hình cho từng client - thay vì cấu hình P2P phức tạp, client chỉ cần chạy chương trình client và sử dụng tunnel (cloudflared) để kết nối tới world.

## Yêu cầu

- Python 3.11 và theo `requirements.txt`

## Cài đặt (Coordinator)

1. Tạo môi trường ảo:

```bash
python -m venv .venv
```

2. Kích hoạt môi trường (Windows):

```powershell
.venv\Scripts\Activate.ps1
```

Hoặc (cmd):

```cmd
.venv\Scripts\activate.bat
```

3. Cài đặt phụ thuộc:

```bash
pip install -r requirements.txt
```

4. Chạy server phát triển

```bash
uvicorn app.main:app --reload --host <domain> --port 8000
```

Lưu ý: nếu entrypoint khác, thay `app.main:app` bằng module tương ứng.

## Bản quyền

MIT License

## Tài liệu API

API HTTP và các endpoint chính được định nghĩa trong `app/routers`. Xem mã nguồn để biết chi tiết định dạng request/response và các routes có sẵn.
