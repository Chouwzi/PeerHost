# PeerHost

<div align="center">

**Hybrid P2P • Distributed Cloud Infrastructure**  
*Empowering the future of decentralized gaming connectivity*

[English](#english) | [Tiếng Việt](#tiếng-việt)

</div>

---

# English

## Overview

PeerHost is a distributed Minecraft hosting system that allows players to share hosting responsibilities. When no one is hosting, any player can claim the host role, sync the world data, and run the server - all through a centralized coordinator.

### Architecture

```
┌─────────────────┐         ┌─────────────────┐
│   PeerHost      │ ◄─────► │  Central Server │
│   Client        │   API   │  (Coordinator)  │
│   (Host/Player) │         │                 │
└────────┬────────┘         └─────────────────┘
         │
         │ Cloudflare Tunnel (TCP)
         ▼
┌─────────────────┐
│  Minecraft      │
│  Server         │
│  (localhost)    │
└─────────────────┘
```

### How It Works

1. **Client connects** to the central server to check session status
2. **If no active host**: Client can claim host, download world data, start Minecraft server
3. **Active host** exposes Minecraft server via Cloudflare Tunnel
4. **Other players** connect through Cloudflare Access to play
5. **Continuous sync** keeps the central server updated with world changes

### Why PeerHost?

| Feature | Traditional MC Server | Pure P2P (Hamachi/LAN) | PeerHost |
|---------|----------------------|------------------------|----------|
| **Coordinator Cost** | 💸 High-spec VPS ($10-50/mo) | ✅ Free | 💰 Cheap VPS ($3-5/mo) |
| **Who runs MC Server** | VPS (always on) | Host player | Host player |
| **24/7 Availability** | ✅ Always online | ❌ Requires host online | ⚡ Anyone can become host |
| **World Persistence** | ✅ Centralized | ❌ Lost if host changes | ✅ Auto-sync to cloud |
| **No Port Forwarding** | ❌ Required | ⚠️ VPN Required | ✅ Cloudflare handles it |
| **DDoS Protection** | ❌ Extra cost | ❌ None | ✅ Cloudflare built-in |
| **Low Latency** | ⚠️ Depends on VPS location | ✅ Direct/LAN | ✅ Host is a real player |
| **Server Resources** | 💸 VPS needs 4-8GB RAM | ✅ Host's PC | ✅ Host's PC |

**Best for:**
- Friend groups who play together but can't afford high-spec 24/7 hosting
- Communities where different members can take turns hosting
- Players who want automatic world backup without manual effort

### System Requirements

#### Coordinator Server (VPS/Cloud)
| Component | Minimum | Recommended |
|-----------|---------|-------------|
| CPU | 1 vCPU | 2 vCPU |
| RAM | 512 MB | 1 GB |
| Storage | 5 GB | 10 GB |
| Network | 100 Mbps | 1 Gbps |
| OS | Windows/Linux | Linux (Ubuntu 22.04) |

> 💡 **Note**: The coordinator only stores world files and manages sessions. It does NOT run the Minecraft server, so low-spec VPS ($3-5/mo) is sufficient.

#### Client (Host Player)
| Component | Minimum | Recommended |
|-----------|---------|-------------|
| CPU | 4 cores | 6+ cores |
| RAM | 8 GB (4GB for MC) | 16 GB (8GB for MC) |
| Storage | 5 GB | 20 GB |
| Network | 10 Mbps upload | 50+ Mbps upload |
| OS | Windows 10/11 | Windows 10/11 |
| **Java** | **JDK 17+** | **JDK 21** |

> ⚠️ **Important**: Client needs Java JDK installed to run Minecraft server. Download from: https://www.oracle.com/java/technologies/downloads/

---

## Server Setup

### Prerequisites

- Python 3.11+
- Java 17+ (for Minecraft server)
- Cloudflare account with a domain

### 1. Clone & Install Dependencies

```bash
git clone https://github.com/Chouwzi/PeerHost.git
cd PeerHost
pip install -r requirements.txt
```

### 2. Configure settings.json

Edit `app/settings.json`:

```json
{
  "heartbeat_interval": 2,
  "lock_timeout": 7,
  "start_command": "java -Xms4G -Xmx4G -jar server.jar nogui",
  "mirror_sync": true,
  "secret_key": "YOUR_SECURE_SECRET_KEY",
  "algorithm": "HS256",
  "tunnel_name": "PeerHost",
  "game_hostname": "mc.yourdomain.com",
  "game_local_port": 2812
}
```

> ⚠️ **Important**: Change `secret_key` to a secure random string and `game_hostname` to your actual domain.

### 3. Setup Minecraft Server

```bash
cd app/storage/world_data
# Download your preferred server.jar (Paper, Vanilla, etc.)
java -jar server.jar nogui
# Accept EULA, configure server.properties, then stop the server
```

### 4. Setup Cloudflare Tunnels

> ⚠️ **Important**: PeerHost requires **2 separate Cloudflare Tunnels**:
> 1. **API Tunnel** (HTTP) - Exposes the PeerHost coordinator API
> 2. **Game Tunnel** (TCP) - Exposes the Minecraft server for players

#### 4.1 Download Cloudflared

Download `cloudflared.exe` from: https://github.com/cloudflare/cloudflared/releases

Place it in both locations:
- `app/storage/server_tunnel/cloudflared.exe`
- `app/storage/world_data/cloudflared-tunnel/cloudflared.exe`

#### 4.2 Login to Cloudflare (Get cert.pem)

```powershell
# Navigate to server tunnel folder
cd app/storage/server_tunnel

# Login to Cloudflare (opens browser)
.\cloudflared.exe tunnel login

# After login, cert.pem is saved to C:\Users\<username>\.cloudflared\cert.pem
# Copy it to current folder
copy "$env:USERPROFILE\.cloudflared\cert.pem" .
```

#### 4.3 Create API Tunnel (HTTP)

```powershell
# Still in app/storage/server_tunnel folder
cd app/storage/server_tunnel

# Create API tunnel
.\cloudflared.exe tunnel create peerhost-api

# Output shows: Created tunnel peerhost-api with id <API-TUNNEL-UUID>
# Credentials saved to: C:\Users\<username>\.cloudflared\<API-TUNNEL-UUID>.json

# Copy credentials to current folder
copy "$env:USERPROFILE\.cloudflared\<API-TUNNEL-UUID>.json" .

# Add DNS route (replace with your domain)
.\cloudflared.exe tunnel route dns peerhost-api peerhost.yourdomain.com
```

Create `api_config.yaml` in same folder:
```yaml
tunnel: <API-TUNNEL-UUID>
credentials-file: <API-TUNNEL-UUID>.json
ingress:
  - hostname: peerhost.yourdomain.com
    service: http://localhost:8000
  - service: http_status:404
```

**Final folder structure:**
```
app/storage/server_tunnel/
├── cloudflared.exe
├── cert.pem
├── <API-TUNNEL-UUID>.json
└── api_config.yaml
```

#### 4.4 Create Game Tunnel (TCP)

```powershell
# Navigate to game tunnel folder
cd app/storage/world_data/cloudflared-tunnel

# Copy cert.pem from server_tunnel (or from ~/.cloudflared/)
copy "..\..\server_tunnel\cert.pem" .

# Create Game tunnel
.\cloudflared.exe tunnel create peerhost-game

# Output shows: Created tunnel peerhost-game with id <GAME-TUNNEL-UUID>
# Copy credentials to current folder
copy "$env:USERPROFILE\.cloudflared\<GAME-TUNNEL-UUID>.json" .

# Add DNS route (replace with your domain)
.\cloudflared.exe tunnel route dns peerhost-game mc.yourdomain.com
```

Create `config.yaml` in same folder:
```yaml
tunnel: <GAME-TUNNEL-UUID>
credentials-file: <GAME-TUNNEL-UUID>.json
ingress:
  - hostname: mc.yourdomain.com
    service: tcp://localhost:25565
  - service: http_status:404
```

**Final folder structure:**
```
app/storage/world_data/cloudflared-tunnel/
├── cloudflared.exe
├── cert.pem
├── <GAME-TUNNEL-UUID>.json
└── config.yaml
```

> **Note**: Clients will automatically download the Game Tunnel files during sync. They use these files to run the tunnel when hosting.

### 5. Start Server

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

---

## Client Setup

### For Players (Simple)

1. Download `PeerHost.exe` from releases
2. Create a folder and place `PeerHost.exe` inside
3. Run `PeerHost.exe`
4. Enter your username when prompted
5. Wait for sync to complete
6. **Connect to Minecraft**: `127.0.0.1:2812`

> The client will automatically download all necessary files including `cloudflared.exe`.

---

## Configuration Reference

| Key | Description | Default |
|-----|-------------|---------|
| `heartbeat_interval` | Session heartbeat interval (seconds) | 2 |
| `lock_timeout` | Session lock timeout (seconds) | 7 |
| `start_command` | Minecraft server start command | - |
| `mirror_sync` | Delete local files not on server | true |
| `secret_key` | JWT signing key | - |
| `algorithm` | JWT algorithm | HS256 |
| `tunnel_name` | Cloudflare tunnel name | PeerHost |
| `game_hostname` | Game server domain | - |
| `game_local_port` | Local port for Minecraft connection | 2812 |

---

# Tiếng Việt

## Tổng quan

PeerHost là hệ thống host Minecraft phân tán cho phép người chơi chia sẻ trách nhiệm hosting. Khi không có ai host, bất kỳ người chơi nào cũng có thể nhận vai trò host, đồng bộ dữ liệu world, và chạy server - tất cả thông qua server điều phối trung tâm.

### Cách hoạt động

1. **Client kết nối** đến server trung tâm để kiểm tra trạng thái session
2. **Nếu không có host**: Client có thể nhận host, tải world data, khởi động Minecraft server
3. **Host đang hoạt động** mở Minecraft server qua Cloudflare Tunnel
4. **Người chơi khác** kết nối qua Cloudflare Access để chơi
5. **Đồng bộ liên tục** cập nhật world changes lên server trung tâm

### Tại sao chọn PeerHost?

| Tính năng | MC Server Truyền thống | P2P Thuần (Hamachi/LAN) | PeerHost |
|-----------|------------------------|-------------------------|----------|
| **Chi phí Điều phối** | 💸 VPS cao cấp ($10-50/tháng) | ✅ Miễn phí | 💰 VPS giá rẻ ($3-5/tháng) |
| **Ai chạy MC Server** | VPS (luôn bật) | Máy host | Máy host |
| **Hoạt động 24/7** | ✅ Luôn online | ❌ Cần host online | ⚡ Ai cũng có thể làm host |
| **Lưu trữ World** | ✅ Tập trung | ❌ Mất khi đổi host | ✅ Tự động sync lên cloud |
| **Không cần Port Forward** | ❌ Bắt buộc | ⚠️ Cần VPN | ✅ Cloudflare xử lý |
| **Chống DDoS** | ❌ Tốn thêm phí | ❌ Không có | ✅ Cloudflare tích hợp sẵn |
| **Độ trễ thấp** | ⚠️ Phụ thuộc vị trí VPS | ✅ Trực tiếp/LAN | ✅ Host là người chơi thật |
| **Tài nguyên Server** | 💸 VPS cần 4-8GB RAM | ✅ Máy host | ✅ Máy host |

**Phù hợp với:**
- Nhóm bạn bè chơi cùng nhau nhưng không đủ chi phí VPS cao cấp 24/7
- Cộng đồng có nhiều người có thể thay phiên làm host
- Người chơi muốn tự động backup world mà không cần thao tác thủ công

### Yêu cầu Hệ thống

#### Server Điều phối (VPS/Cloud)
| Thành phần | Tối thiểu | Khuyến nghị |
|------------|-----------|-------------|
| CPU | 1 vCPU | 2 vCPU |
| RAM | 512 MB | 1 GB |
| Ổ cứng | 5 GB | 10 GB |
| Mạng | 100 Mbps | 1 Gbps |
| OS | Windows 10/11 | Windows 10/11 |

> 💡 **Lưu ý**: Server điều phối chỉ lưu trữ file world và quản lý session. Nó KHÔNG chạy Minecraft server, nên VPS giá rẻ ($3-5/tháng) là đủ.

#### Client (Máy Host)
| Thành phần | Tối thiểu | Khuyến nghị |
|------------|-----------|-------------|
| CPU | 4 nhân | 6+ nhân |
| RAM | 8 GB (4GB cho MC) | 16 GB (8GB cho MC) |
| Ổ cứng | 5 GB | 20 GB |
| Mạng | 10 Mbps upload | 50+ Mbps upload |
| OS | Windows 10/11 | Windows 10/11 |
| **Java** | **JDK 17+** | **JDK 21** |

> ⚠️ **Quan trọng**: Client cần cài đặt Java JDK để chạy Minecraft server. Tải từ: https://www.oracle.com/java/technologies/downloads/

---

## Cài đặt Server

### Yêu cầu

- Python 3.11+
- Java 17+ (cho Minecraft server)
- Tài khoản Cloudflare với domain

### 1. Clone & Cài đặt Dependencies

```bash
git clone https://github.com/Chouwzi/PeerHost.git
cd PeerHost
pip install -r requirements.txt
```

### 2. Cấu hình settings.json

Chỉnh sửa `app/settings.json`:

```json
{
  "heartbeat_interval": 2,
  "lock_timeout": 7,
  "start_command": "java -Xms4G -Xmx4G -jar server.jar nogui",
  "mirror_sync": true,
  "secret_key": "THAY_BANG_KEY_BAO_MAT",
  "algorithm": "HS256",
  "tunnel_name": "PeerHost",
  "game_hostname": "mc.yourdomain.com",
  "game_local_port": 2812
}
```

> ⚠️ **Quan trọng**: Thay `secret_key` bằng chuỗi ngẫu nhiên bảo mật và `game_hostname` bằng domain thực của bạn.

### 3. Cài đặt Minecraft Server

```bash
cd app/storage/world_data
# Tải server.jar mong muốn (Paper, Vanilla, v.v.)
java -jar server.jar nogui
# Chấp nhận EULA, cấu hình server.properties, sau đó tắt server
```


### 4. Cài đặt Cloudflare Tunnels

> ⚠️ **Quan trọng**: PeerHost cần **2 Cloudflare Tunnels riêng biệt**:
> 1. **API Tunnel** (HTTP) - Mở API điều phối PeerHost
> 2. **Game Tunnel** (TCP) - Mở Minecraft server cho người chơi

#### 4.1 Tải Cloudflared

Tải `cloudflared.exe` từ: https://github.com/cloudflare/cloudflared/releases

Đặt vào cả 2 vị trí:
- `app/storage/server_tunnel/cloudflared.exe`
- `app/storage/world_data/cloudflared-tunnel/cloudflared.exe`

#### 4.2 Đăng nhập Cloudflare (Lấy cert.pem)

```powershell
# Di chuyển đến thư mục server tunnel
cd app/storage/server_tunnel

# Đăng nhập Cloudflare (mở trình duyệt)
.\cloudflared.exe tunnel login

# Sau khi đăng nhập, cert.pem được lưu tại C:\Users\<username>\.cloudflared\cert.pem
# Copy vào thư mục hiện tại
copy "$env:USERPROFILE\.cloudflared\cert.pem" .
```

#### 4.3 Tạo API Tunnel (HTTP)

```powershell
# Vẫn ở trong thư mục app/storage/server_tunnel
cd app/storage/server_tunnel

# Tạo API tunnel
.\cloudflared.exe tunnel create peerhost-api

# Output hiển thị: Created tunnel peerhost-api with id <API-TUNNEL-UUID>
# Credentials được lưu tại: C:\Users\<username>\.cloudflared\<API-TUNNEL-UUID>.json

# Copy credentials vào thư mục hiện tại
copy "$env:USERPROFILE\.cloudflared\<API-TUNNEL-UUID>.json" .

# Thêm DNS route (thay bằng domain của bạn)
.\cloudflared.exe tunnel route dns peerhost-api peerhost.yourdomain.com
```

Tạo `api_config.yaml` trong cùng thư mục:
```yaml
tunnel: <API-TUNNEL-UUID>
credentials-file: <API-TUNNEL-UUID>.json
ingress:
  - hostname: peerhost.yourdomain.com
    service: http://localhost:8000
  - service: http_status:404
```

**Cấu trúc thư mục cuối cùng:**
```
app/storage/server_tunnel/
├── cloudflared.exe
├── cert.pem
├── <API-TUNNEL-UUID>.json
└── api_config.yaml
```

#### 4.4 Tạo Game Tunnel (TCP)

```powershell
# Di chuyển đến thư mục game tunnel
cd app/storage/world_data/cloudflared-tunnel

# Copy cert.pem từ server_tunnel (hoặc từ ~/.cloudflared/)
copy "..\..\server_tunnel\cert.pem" .

# Tạo Game tunnel
.\cloudflared.exe tunnel create peerhost-game

# Output hiển thị: Created tunnel peerhost-game with id <GAME-TUNNEL-UUID>
# Copy credentials vào thư mục hiện tại
copy "$env:USERPROFILE\.cloudflared\<GAME-TUNNEL-UUID>.json" .

# Thêm DNS route (thay bằng domain của bạn)
.\cloudflared.exe tunnel route dns peerhost-game mc.yourdomain.com
```

Tạo `config.yaml` trong cùng thư mục:
```yaml
tunnel: <GAME-TUNNEL-UUID>
credentials-file: <GAME-TUNNEL-UUID>.json
ingress:
  - hostname: mc.yourdomain.com
    service: tcp://localhost:25565
  - service: http_status:404
```

**Cấu trúc thư mục cuối cùng:**
```
app/storage/world_data/cloudflared-tunnel/
├── cloudflared.exe
├── cert.pem
├── <GAME-TUNNEL-UUID>.json
└── config.yaml
```

> **Lưu ý**: Client sẽ tự động tải các file Game Tunnel khi đồng bộ. Họ dùng các file này để chạy tunnel khi hosting.

### 5. Khởi động Server

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

---

## Cài đặt Client

### Cho Người chơi

1. Tải `PeerHost.exe` từ releases
2. Tạo thư mục và đặt `PeerHost.exe` vào
3. Chạy `PeerHost.exe`
4. Nhập tên người dùng khi được yêu cầu
5. Đợi đồng bộ hoàn tất
6. **Kết nối Minecraft**: `127.0.0.1:2812`

> Client sẽ tự động tải tất cả file cần thiết bao gồm `cloudflared.exe`.

---

## Bảng tham khảo cấu hình

| Key | Mô tả | Mặc định |
|-----|-------|----------|
| `heartbeat_interval` | Khoảng thời gian heartbeat session (giây) | 2 |
| `lock_timeout` | Thời gian timeout khóa session (giây) | 7 |
| `start_command` | Lệnh khởi động Minecraft server | - |
| `mirror_sync` | Xóa file local không có trên server | true |
| `secret_key` | Khóa ký JWT | - |
| `algorithm` | Thuật toán JWT | HS256 |
| `tunnel_name` | Tên Cloudflare tunnel | PeerHost |
| `game_hostname` | Domain game server | - |
| `game_local_port` | Port local để kết nối Minecraft | 2812 |

---

## License

MIT License - Made with ❤️ by Chouwzi
