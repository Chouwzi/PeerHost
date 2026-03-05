# Recovery Flow Explanation (After BUG #13 Fix)

## Problem
Trước khi fix, khi heartbeat recovery xảy ra, hai control flow đang xung đột:
1. **Heartbeat recovery task** (nền) - Cố tình dừng CF tunnel, game server, upload dữ liệu
2. **State machine `_handle_hosting`** (vòng chính) - Kiểm tra sức khỏe CF/game, tự động chuyển sang DISCOVERY khi thấy băng bẻ

→ Tạo vòng lặp vô tận: `HOSTING → (recovery dừng CF) → state machine thấy CF chết → DISCOVERY → CLAIM → HOSTING → (CF crash lại) → DISCOVERY → ...`

---

## Solution (BUG #13 Fix)

State machine `_handle_hosting` giờ:
1. **Kiểm tra recovery flag** tại entry: Nếu recovery đang xử lý → sleep và trở lại HOSTING (không can thiệp)
2. **Kiểm tra heartbeat** TRƯỚC `start_hosting_services()`: Nếu heartbeat chết (recovery vừa dọn dẹp xong) → ngay lập tức return DISCOVERY **mà không khởi động lại services**
3. **Re-check recovery** sau sleep: Catch trường hợp recovery bắt đầu giữa lúc monitoring

---

## Detailed Flow Timeline (with logs)

### Phase 1: Normal Hosting
```
[10:00:59] State: HOSTING (heartbeat task chạy bình thường)
[10:00:59] INFO [Heartbeat] Gửi heartbeat → Server
[10:00:59] ✓ Server trả 200 OK
```

### Phase 2: Heartbeat Failure Detection
```
[10:00:59] WARNING [Heartbeat] Không thể duy trì phiên (Status: 502). Lần 1/3
[10:01:01] WARNING [Heartbeat] Không thể duy trì phiên (Status: 502). Lần 2/3
[10:01:03] WARNING [Heartbeat] Không thể duy trì phiên (Status: 502). Lần 3/3
                           ↓
         3 heartbeat failures → Trigger _network_failure_recovery()
```

### Phase 3: Network Failure Recovery (Heartbeat Background Task)
```
[10:01:03] _recovery_in_progress = True  ← Signal to state machine
[10:01:03] WARNING [Cloudflare] Đang dừng Host-Mode (PID: 31788)...
[10:01:03] WARNING [GameServer] Đang dừng Server...
[10:01:04] INFO [GameServer] Dữ liệu Minecraft đã được lưu...
[10:01:19] WARNING [GameServer] Graceful shutdown timeout. Forcing kill...
[10:01:19] WARNING [GameServer] Đã Force Kill Server (Sync).
[10:01:20] WARNING [Connection] Đang đợi kết nối từ Server (tối đa 300s)...

           ← Waiting for network reconnection (polling check_connection)

[10:01:32] ✓ Reconnected!
[10:01:32] INFO [Session] Đăng ký Session thành công
[10:01:32] INFO [FinalSync] Đang đồng bộ dữ liệu cuối cùng trước khi tắt...
[10:01:47] INFO [FinalSync] Hoàn tất! Đã upload 26 file
[10:01:47] INFO [Recovery] Đã upload dữ liệu thành công.
[10:01:48] INFO [Session] Dừng Session thành công
[10:01:48] self._heartbeat_task.cancel() ← Kết thúc heartbeat task
[10:01:48] self.sync_service = None
[10:01:48] _recovery_in_progress = False  ← Signal recovery complete
```

### Phase 4: State Machine Detection (State Machine Main Loop)
```
[10:01:48] _handle_hosting() được gọi (vào lần tiếp theo)
           ↓
           if self.context._recovery_in_progress:
               → FALSE (recovery vừa kết thúc)
           ↓
           # ✅ NEW: Kiểm tra heartbeat TRƯỚC start_hosting
           if not self.context._heartbeat_task:
               → TRUE (recovery đã kill nó)
           ↓
           logger.warning("[Hosting] Heartbeat Task đã dừng! Chuyển sang Discovery.")
           return ClientState.DISCOVERY

[10:01:48] WARNING [Hosting] Heartbeat Task đã dừng! Chuyển sang Discovery.

           ✅ KEY FIX: Không call start_hosting_services() → Không khởi động lại services vô ích
```

### Phase 5: State Machine Returns to DISCOVERY (Normal Re-sync)
```
[10:01:48] State: HOSTING → DISCOVERY (heartbeat chết, dừng recovery)
[10:01:50] _handle_discovery()
[10:01:50] INFO [Session] Đăng ký Session thành công (re-claim)
[10:02:10] _handle_pre_host_sync() → sync dữ liệu với server
[10:02:10] INFO [Sync] Đã khởi động (services started again)
[10:02:10] INFO [Cloudflare] Đang khởi động Host-Mode...
[10:02:10] INFO [GameServer] Server started...
           ↓
[10:03:04] State: PRE_HOST_SYNC → CLAIM_HOST
[10:03:04] Server Minecraft đã sẵn sàng kết nối!
           ↓
           State: CLAIM_HOST → HOSTING (heartbeat started lại)
```

---

## Key Differences (Before vs After)

### ❌ BEFORE FIX (Infinite Loop Problem)
```
[10:01:48] Recovery complete, heartbeat killed
[10:01:48] _handle_hosting() re-enter
[10:01:48] Recovery check: FALSE
[10:01:48] await start_hosting_services()  ← Restart CF, game, sync
[10:01:50] Check CF tunnel → NOT running yet (just started)
[10:01:50] → "Cloudflare Tunnel đã bị tắt bất thường!"
[10:01:50] return ClientState.DISCOVERY
           ↓ Quay lại vòng lặp DISCOVERY → CLAIM → HOSTING
[10:02:00] _handle_hosting() lại
[10:02:00] await start_hosting_services() ← Khởi động lại (thứ 2)
[10:02:00] Check CF → Possibly still initializing
[10:02:00] → DISCOVERY lại
           ↓ Vòng lặp tiếp tục...
```

### ✅ AFTER FIX (Proper Sequential Flow)
```
[10:01:48] Recovery complete, heartbeat killed
[10:01:48] _handle_hosting() re-enter
[10:01:48] Recovery check: FALSE
[10:01:48] Heartbeat check: NOT running → return DISCOVERY ngay
[10:01:48] Không call start_hosting_services() ← Không khởi động vô ích
[10:01:50] State: HOSTING → DISCOVERY
[10:01:50] _handle_discovery() → CLAIM_HOST → PRE_HOST_SYNC
[10:02:10] Services khởi động (1 lần duy nhất, bình thường)
[10:03:04] State: CLAIM_HOST → HOSTING (bình thường)
           ↓ Hosting ổn định
```

---

## Summary of Changes

| Aspect | Before | After |
|--------|--------|-------|
| **Heartbeat check position** | Sau `start_hosting_services()` | Trước `start_hosting_services()` |
| **Recovery guard** | Không có | Kiểm tra `_recovery_in_progress` |
| **Wasteful restarts** | Có (khởi động CF/game 2-3 lần) | Không (1 lần duy nhất) |
| **Loop behavior** | Vòng lặp vô tận HOSTING−DISCOVERY | Một lần transition HOSTING→DISCOVERY rồi bình thường |
| **Upload reliability** | Dữ liệu có thể bị mất | **BUG #2 fix** - dữ liệu luôn được upload |
| **Heartbeat recovery** | Không hoạt động do state machine can thiệp | **Hoạt động bình thường** |

---

## Code Changes

### `client/state_machine.py` - `_handle_hosting()`

```python
async def _handle_hosting(self) -> ClientState:
    # 0. Recovery Guard ← NEW
    if self.context._recovery_in_progress:
        logger.debug("[Hosting] Recovery đang xử lý, chờ hoàn tất...")
        await asyncio.sleep(2)
        return ClientState.HOSTING

    # 1. Check Heartbeat BEFORE start_hosting ← MOVED UP (was after)
    if not self.context._heartbeat_task or self.context._heartbeat_task.done():
         logger.warning("[Hosting] Heartbeat Task đã dừng!")
         return ClientState.DISCOVERY

    # 2. Only if heartbeat is alive, start services
    await self.context.start_hosting_services(known_server_files=self.cached_manifest)

    # ... rest of monitoring
```

### `client/client.py` - Recovery Methods

```python
def __init__(self):
    # ...
    self._recovery_in_progress = False  # ← NEW flag

async def _network_failure_recovery(self, max_wait: int):
    self._recovery_in_progress = True  # ← Set at start
    try:
        # Dừng tunnel, game, chờ reconnect, upload
        # ...
    finally:
        self._recovery_in_progress = False  # ← Clear at end

async def _emergency_save_and_shutdown(self):
    self._recovery_in_progress = True  # ← Same pattern
    try:
        # ...
    finally:
        self._recovery_in_progress = False
```

---

## Testing

4 unit tests added to validate recovery guard behavior:
- ✅ Recovery flag prevents discovery transition
- ✅ Recovery done allows discovery
- ✅ Heartbeat dead skips restarting services
- ✅ Done heartbeat task triggers discovery

**Result: 33/33 tests pass**, 0 regressions
