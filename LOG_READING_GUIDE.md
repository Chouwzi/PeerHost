# Hướng Dẫn Đọc Logs - PeerHost Recovery Flow

## Overview
Logs được cập nhật để rõ ràng, dễ đọc, và dễ dàng theo dõi tiến trình.

---

## Log Structure

Mỗi log message có format:
```
[HH:MM:SS] LEVEL [Category] Message
```

### Ví dụ:
```
[10:00:59] INFO [Heartbeat] Server trả 200 OK
[10:01:03] WARNING [Heartbeat] Phiên làm việc đã bị hủy hoặc hết hạn (401). Khởi động khôi phục khẩn cấp.
[10:01:03] WARNING [Recovery] Bắt đầu khôi phục khẩn cấp (401: Phiên hết hạn)
```

---

## Log Levels Explained

| Level | When Used | Color | Example |
|-------|-----------|-------|---------|
| **DEBUG** | Chi tiết nội bộ | Xám | `Khởi tạo Sync Service...` |
| **INFO** | Sự kiện quan trọng | Xanh | `Kết nối lại thành công sau 29s!` |
| **WARNING** | Chú ý | Vàng | `Không thể duy trì kết nối sau 3 lần thử...` |
| **ERROR** | Lỗi | Đỏ | `Timeout sau 300s` |

---

## Scenario 1: Normal Hosting (No Issues)

```
[10:00:00] INFO [Session] Đăng ký session thành công
[10:00:05] INFO [Hosting] Bắt đầu khởi động hosting services
[10:00:05] DEBUG [Hosting] Khởi tạo Sync Service (Fetch config & Scan)...
[10:00:06] INFO [Sync] Đã khởi động | Watch Dir: C:\...\world
[10:00:06] INFO [GameServer] Khởi động Server: java ...
[10:00:06] INFO [Cloudflare] Khởi động Cloudflare Tunnel (Host Mode)...
[10:00:07] INFO [Hosting] Tất cả hosting services đã khởi động thành công

[10:00:10] DEBUG [Hosting] Tất cả services đang hoạt động bình thường
[10:00:12] DEBUG [Hosting] Tất cả services đang hoạt động bình thường
[10:00:14] DEBUG [Hosting] Tất cả services đang hoạt động bình thường
```

---

## Scenario 2: 401 Error (Session Expired) → Emergency Recovery

### Phase 1: Heartbeat Đang Chạy Normal

```
[10:00:59] INFO [Heartbeat] Server trả 200 OK (Status: 200)
[10:01:00] INFO [Heartbeat] Server trả 200 OK (Status: 200)
```

### Phase 2: Heartbeat Fail với 401

```
[10:01:59] ERROR [Heartbeat] Phiên làm việc đã bị hủy hoặc hết hạn (401).
                   Khởi động khôi phục khẩn cấp.
```

### Phase 3: Recovery In Progress

```
[10:01:59] WARNING [Recovery] Bắt đầu khôi phục khẩn cấp (401: Phiên hết hạn)
[10:01:59] DEBUG [Recovery] Dừng Cloudflare Tunnel...
[10:01:59] DEBUG [Recovery] Dừng file monitoring...
[10:02:00] DEBUG [Recovery] Dừng Game Server...
[10:02:10] DEBUG [GameServer] Dữ liệu Minecraft đã được lưu...
[10:02:15] INFO [Recovery] Đăng ký lại session para có token mới...
[10:02:15] INFO [Session] Đăng ký session thành công

[10:02:15] INFO [Recovery] Đã đăng ký lại session thành công. Bắt đầu upload dữ liệu...
[10:02:16] INFO [FinalSync] Đang đồng bộ dữ liệu cuối cùng trước khi tắt...
[10:02:30] INFO [FinalSync] Hoàn tất! Đã upload 26 file
[10:02:30] INFO [Recovery] Đã upload dữ liệu thành công sau khôi phục session.
[10:02:31] INFO [Session] Dừng session thành công
[10:02:31] DEBUG [Recovery] Dọn dẹp resources...
[10:02:31] WARNING [Recovery] Kết thúc khôi phục khẩn cấp
```

### Phase 4: State Machine Returns to DISCOVERY

```
[10:02:32] WARNING [Hosting] Heartbeat task đã dừng. Quay lại discovery để re-sync.

[10:02:33] INFO [Discovery] Kết nối server OK
[10:02:33] INFO [Session] Đăng ký session thành công (re-claim)

[10:02:50] INFO [PreHostSync] Đã đồng bộ dữ liệu hoàn toàn với server
[10:03:00] INFO [Hosting] Bắt đầu khởi động hosting services (lần 2)
[10:03:01] INFO [Hosting] Tất cả hosting services đã khởi động thành công (lần 2)
```

**Ý Nghĩa:** Sau khi recovery hoàn tất upload, state machine phát hiện heartbeat task đã dừng, nên quay lại DISCOVERY. Sẽ có một lần khởi động lại services bình thường.

---

## Scenario 3: Network Failure (3x 502) → Network Recovery

### Phase 1: 3 Heartbeat Failures

```
[10:00:59] WARNING [Heartbeat] Lỗi heartbeat (HTTP 502). Lần 1/3
[10:01:01] WARNING [Heartbeat] Lỗi heartbeat (HTTP 502). Lần 2/3
[10:01:03] WARNING [Heartbeat] Lỗi heartbeat (HTTP 502). Lần 3/3
[10:01:03] WARNING [Heartbeat] Không thể duy trì kết nối sau 3 lần thử.
                   Khởi động khôi phục mạng.
```

### Phase 2: Network Recovery In Progress

```
[10:01:03] WARNING [Recovery] Bắt đầu khôi phục mạng (Mất kết nối)
[10:01:03] DEBUG [Recovery] Dừng Cloudflare Tunnel...
[10:01:03] DEBUG [Recovery] Dừng file monitoring...
[10:01:04] DEBUG [Recovery] Dừng Game Server...

[10:01:05] WARNING [Connection] Chờ kết nối lại từ Server (tối đa 300s)...
[10:01:07] DEBUG [Connection] Đang kiểm tra... (2s/300s)
[10:01:09] DEBUG [Connection] Đang kiểm tra... (4s/300s)
[10:01:11] DEBUG [Connection] Đang kiểm tra... (6s/300s)
...chờ ~20-30 giây...
[10:01:32] INFO [Connection] Kết nối lại thành công sau 29s!
```

### Phase 3: After Reconnect → Upload

```
[10:01:32] INFO [Recovery] Đăng ký lại session sau reconnect...
[10:01:32] INFO [Session] Đăng ký session thành công
[10:01:32] INFO [Recovery] Đã đăng ký lại session. Bắt đầu upload dữ liệu...
[10:01:33] INFO [FinalSync] Đang đồng bộ dữ liệu cuối cùng trước khi tắt...
[10:01:47] INFO [FinalSync] Hoàn tất! Đã upload 26 file
[10:01:47] INFO [Recovery] Đã upload dữ liệu thành công sau reconnect.
[10:01:48] DEBUG [Recovery] Dọn dẹp resources...
[10:01:48] WARNING [Recovery] Kết thúc khôi phục mạng
```

### Phase 4: Back to Normal

```
[10:01:48] WARNING [Hosting] Heartbeat task đã dừng. Quay lại discovery để re-sync.
[10:01:50] INFO [Session] Đăng ký session thành công
[10:02:10] INFO [Hosting] Bắt đầu khởi động hosting services
[10:02:10] INFO [Hosting] Tất cả hosting services đã khởi động thành công
```

---

## Scenario 4: Timeout Network Failure (Server Completely Down)

```
[10:01:03] WARNING [Recovery] Bắt đầu khôi phục mạng
[10:01:05] WARNING [Connection] Chờ kết nối lại từ Server (tối đa 300s)...
...chờ 300 giây...
[10:06:05] ERROR [Connection] Timeout sau 300s. Dữ liệu giữ lại ở local.
[10:06:05] DEBUG [Recovery] Dọn dẹp resources...
[10:06:05] WARNING [Recovery] Kết thúc khôi phục mạng
```

**Ý Nghĩa:** Server hoàn toàn down. Dữ liệu được lưu ở local, sẽ upload khi server sống lại.

---

## Scenario 5: Recovery While State Machine Monitoring

```
[10:01:00] DEBUG [Hosting] Tất cả services đang hoạt động bình thường
[10:01:02] [Heartbeat detects 502...]
[10:01:03] WARNING [Recovery] Bắt đầu khôi phục mạng
         (State Machine cũng đang monitoring...)

[10:01:04] DEBUG [Hosting] Recovery đang xử lý, chờ hoàn tất...
         (State machine nhấn dừng, không can thiệp)
[10:01:04] (sleep 2s)
[10:01:06] DEBUG [Hosting] Recovery đang xử lý, chờ hoàn tất...
         (State machine vẫn chờ)
...
[10:01:47] WARNING [Recovery] Kết thúc khôi phục mạng
[10:01:48] WARNING [Hosting] Heartbeat task đã dừng. Quay lại discovery để re-sync.
         (State machine detect heartbeat chết, chuyển DISCOVERY)
```

**Key Point:** State machine **KHÔNG** đi DISCOVERY khi recovery đang chạy. Nó chờ recovery hoàn tất rồi mới react.

---

## Quick Checklist - Xem Logs, Phán Đoán Vấn Đề

### ✅ Mọi thứ đang tốt:
- Heartbeat liên tục: `Server trả 200 OK`
- Hosting services: `Tất cả services đang hoạt động bình thường`

### ⚠️ Đang khôi phục (chính thường):
- Thấy `Bắt đầu khôi phục khẩn cấp` hoặc `Bắt đầu khôi phục mạng`
- Thấy `Chờ kết nối lại từ Server`
- _Dữ liệu sẽ được upload tự động_

### ❌ Vấn đề nghiêm trọng:
- `Timeout sau 300s` → Server hoàn toàn down → Dữ liệu local, chờ server recovery
- `Không thể đăng ký lại session` → Token expired? Server lỗi? Check debug logs

### 🔄 Khôi động lại Game Server:
- Thấy `Đang thử khôi động lại game server...`
- Nếu `Game server khôi động lại thành công` → OK
- Nếu `Lỗi khi khôi động lại` → Game Server có vấn đề

---

## Pro Tips

1. **Filter logs cho recovery:**
   ```
   grep "Recovery" logfile.txt
   ```

2. **Watch realtime logs:**
   ```
   tail -f logfile.txt | grep -E "Recovery|Heartbeat|Hosting"
   ```

3. **Count heartbeat failures:**
   ```
   grep "Lỗi heartbeat" logfile.txt | wc -l
   ```

4. **Find all recovery sessions:**
   ```
   grep "Bắt đầu khôi phục" logfile.txt
   ```

5. **See recovery completion:**
   ```
   grep "Kết thúc khôi phục" logfile.txt
   ```
