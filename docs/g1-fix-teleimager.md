# 修复 teleimager 启动失败（WSL2 USB 摄像头丢失）

## 现象

上一次 teleimager 关不掉，强关窗口后再启动报错：

```
modprobe: FATAL: Module uvcvideo is in use.
ERROR    Failed to reload driver: Command 'sudo modprobe -r uvcvideo' returned
         non-zero exit status 1.
[ WARN:0@198.870] global cap.cpp:215 open VIDEOIO(V4L2): backend is generally
         available but can't be used to capture by name
```

最后卡在 `cv2.VideoCapture(video_path, cv2.CAP_V4L2)`，要 Ctrl-C 才能退出。

## 根因诊断

**当前 WSL2 状态（不是 teleimager 本身的 bug）：**

1. `/sys/class/video4linux/` 目录不存在 → 系统里**完全没有 V4L2 视频设备**
2. `/sys/bus/usb/devices/` 只有根 hub，**没有任何用户 USB 设备**
3. `/sys/devices/platform/vhci_hcd.0/status` 所有端口都是 `004 000`（VDEV_ST_NULL）→ **usbipd 附加状态全部丢失**

也就是说：摄像头（UVC + RealSense）**已经从 WSL2 完全断开了**。这通常是因为上一次 teleimager 异常退出时，子进程把 USB 设备弄进了 bad state，usbipd-win 那边自动 detach（或挂掉了）。

**两个错误信息的真相：**

- `modprobe: FATAL: Module uvcvideo is in use.` → WSL2 内核怪癖，`lsmod` 显示 uvcvideo 引用计数为 0 但仍报 in use。teleimager 的 `reload_uvc_driver()` 用 try/except 吞掉了这个异常，**不是真正的阻塞原因**。
- 真正卡住的 `cv2.VideoCapture(...CAP_V4L2)` → 因为枚举到了一个**马上要消失的**僵尸 video 节点，open 系统调用 hang 住直到被 Ctrl-C。

至于"teleimager 关不掉" → teleimager 是多进程架构（启动日志 `[Performance] CPU Affinity locked to: [0, 1, 2]` 已暗示），主进程被强关时子进程没被回收，它们继续抓着 USB 句柄不放，最终把 usbipd 那一侧也搞炸了。

## 解决方法

### Step 1 — 在 Windows 端重新附加摄像头

这一步是必须的，因为 WSL2 内部已经看不到任何 USB 设备了。打开**管理员 PowerShell**：

```powershell
usbipd list
# 找到你的 RealSense / UVC 摄像头的 BUSID（比如 2-3）
usbipd detach --busid 2-3      # 如果显示 "Attached" 先 detach
usbipd attach --wsl --busid 2-3
```

每个摄像头都要 attach 一次。如果 `usbipd list` 报错或者状态卡住，最干脆的办法是 `wsl --shutdown` 后重新打开终端。

### Step 2 — 在 WSL 里验证

```bash
ls /sys/class/video4linux/   # 应该看到 video0, video1...
ls /dev/video*               # 应该看到对应的设备节点
```

### Step 3 — 重启 teleimager

```bash
conda activate agi
cd ~/unitree/unitree-notes/teleimager
python -m teleimager.image_server
```

## 下次怎么避免

- 关 teleimager 时**先在那个终端按 Ctrl-C** 让主进程优雅退出（它会清理子进程并释放 USB），再关窗口。
- 如果发现关不掉，用 `pkill -f teleimager.image_server` 一次性把整个进程组打掉，别只关窗口（终端窗口被关时进程组未必收得到 SIGHUP，子进程会变孤儿，继续占着 USB）。
