# WSL2 + usbipd + teleimager 摄像头实时图传运行笔记

> 记录日期：2026-05-04  
> 环境：Windows 10/11 + WSL2 Ubuntu + conda `agi` 环境 + Unitree `teleimager`  
> 目标：把 Windows 端 USB 摄像头转发进 WSL2，并通过 `teleimager` 启动图传服务，再用 `teleimager-client` 弹出实时摄像头窗口。

---

## 0. 最终结论

今天已经成功完成：

- Windows 端识别到摄像头：`USB2.0 HD UVC WebCam`
- 通过 `usbipd-win` 把摄像头转发进 WSL2
- WSL2 中成功出现：
  - `/dev/video0`
  - `/dev/video1`
  - `/dev/media0`
- 修复了普通用户访问摄像头的权限问题
- 验证了 `/dev/video0` 才是真正可用的图像流
- 使用 `v4l2-ctl` 成功抓帧
- 使用 OpenCV 成功读取摄像头帧
- 修复了 OpenCV GUI 缺失导致的 `cv2.waitKey is not implemented` 错误
- 修改 `teleimager` 探测逻辑，使其在 WSL2 + usbipd 场景下强制使用 MJPG
- 修复 `cam_config_server.yaml` 中 `video_id: 0` 被 Python 当成 `False` 的问题
- 最终成功启动：
  - `teleimager.image_server`
  - `teleimager-client --host 127.0.0.1`
- 成功弹出实时摄像头窗口并看到画面

---

# 1. 每次重新运行时的标准流程

下面是以后最常用的启动顺序。

---

## 1.1 Windows PowerShell 中执行

### 第一步：查看摄像头 BUSID

在 **Windows PowerShell** 中执行：

```powershell
usbipd list
```

你今天看到的摄像头是：

```text
BUSID  VID:PID    DEVICE
1-8    322e:2122  USB2.0 HD UVC WebCam
```

> 注意：`BUSID` 可能会因为插拔 USB、重启电脑而变化。  
> 如果以后不是 `1-8`，以后所有命令里的 `1-8` 都要替换成新的 BUSID。

---

### 第二步：共享摄像头

如果状态不是 `Shared` 或 `Shared (forced)`，执行：

```powershell
usbipd bind --busid 1-8
```

如果出现类似：

```text
Unknown USB filter 'hrdevmon' may be incompatible
```

或者普通 `bind` 不稳定，可以使用：

```powershell
usbipd bind --busid 1-8 --force
```

成功后检查：

```powershell
usbipd list
```

期望状态：

```text
1-8    322e:2122  USB2.0 HD UVC WebCam    Shared
```

或者：

```text
1-8    322e:2122  USB2.0 HD UVC WebCam    Shared (forced)
```

---

### ==第三步：把摄像头挂载到 WSL2==

确保 WSL2 的 Ubuntu 窗口已经打开，然后在 PowerShell 执行：

```powershell
usbipd attach --wsl --busid 1-8
```

再次检查：

```powershell
usbipd list
```

期望状态：

```text
1-8    322e:2122  USB2.0 HD UVC WebCam    Attached
```

只要状态不是 `Attached`，WSL2 里面就不会有 `/dev/video0`。

---

### 需要停止使用摄像头时

```powershell
usbipd detach --busid 1-8
```

如果以后不想共享该设备：

```powershell
usbipd unbind --busid 1-8
```

---

## 1.2 WSL2 中执行：基础检查

进入 WSL2 Ubuntu 后执行：

```bash
lsusb
ls -l /dev/video*
v4l2-ctl --list-devices
```

期望看到：

```text
Bus 001 Device 002: ID 322e:2122 Sonix Technology Co., Ltd. USB2.0 HD UVC WebCam
```

以及：

```text
/dev/video0
/dev/video1
/dev/media0
```

`v4l2-ctl --list-devices` 期望看到：

```text
USB2.0 HD UVC WebCam: USB2.0 HD (usb-vhci_hcd.0-1):
        /dev/video0
        /dev/video1
        /dev/media0
```

---

## 1.3 WSL2 中执行：启动 teleimager server

第一个 WSL 终端：

```bash
conda activate agi
cd ~/unitree/unitree-notes/teleimager
python -m teleimager.image_server
```

注意：

```bash
python -m teleimager.image_server -c cam_config_server.yaml
```

这个命令不要用。  
你当前版本的 `teleimager.image_server` 不支持 `-c` 参数，它会默认读取当前项目里的 `cam_config_server.yaml`。

---

## 1.4 WSL2 中执行：启动 teleimager client

新开第二个 WSL 终端：

```bash
conda activate agi
cd ~/unitree/unitree-notes/teleimager
teleimager-client --host 127.0.0.1
```

或者：

```bash
python -m teleimager.image_client --host 127.0.0.1
```

如果成功，会弹出实时摄像头窗口。

---

# 2. 今天具体做了哪些事情

---

## 2.1 最初的问题

最开始运行：

```bash
python -m teleimager.image_server --cf
```

输出：

```text
Found video devices: []
Found RGB video devices: []
```

原因不是 `teleimager` 坏了，而是 WSL2 里当时没有任何 `/dev/video*` 设备。

---

## 2.2 Windows 端发现摄像头

在 PowerShell 中执行：

```powershell
usbipd list
```

发现 Windows 端可以看到摄像头：

```text
1-8    322e:2122  USB2.0 HD UVC WebCam    Not shared
```

这说明摄像头硬件和 Windows 驱动本身是正常的，只是还没有转发给 WSL2。

---

## 2.3 使用 usbipd-win 转发摄像头到 WSL2

执行：

```powershell
usbipd bind --busid 1-8
usbipd bind --busid 1-8 --force
usbipd attach --wsl --busid 1-8
```

最后 `usbipd list` 显示：

```text
1-8    322e:2122  USB2.0 HD UVC WebCam    Attached
```

这一步说明 USB 摄像头已经成功挂载进 WSL2。

---

## 2.4 WSL2 成功识别 USB 和 video 设备

WSL2 中执行：

```bash
lsusb
ls -l /dev/video*
```

成功看到：

```text
Bus 001 Device 002: ID 322e:2122 Sonix Technology Co., Ltd. USB2.0 HD UVC WebCam
```

以及：

```text
/dev/video0
/dev/video1
```

这说明：

- USB 转发成功
- WSL2 UVC/V4L2 驱动可用
- 摄像头节点已经生成

---

## 2.5 修复普通用户没有 video 设备权限的问题

一开始普通用户运行：

```bash
v4l2-ctl --list-devices
```

报：

```text
Failed to open /dev/video0: Permission denied
```

原因是 `/dev/video0` 属于：

```text
root video
```

所以执行：

```bash
sudo usermod -aG video $USER
newgrp video
```

再检查：

```bash
groups
```

看到包含：

```text
video
```

之后普通用户就可以访问 `/dev/video0` 了。

如果以后重新打开 WSL 后权限没有立刻生效，可以执行：

```powershell
wsl --shutdown
```

然后重新打开 WSL，再重新：

```powershell
usbipd attach --wsl --busid 1-8
```

---

## 2.6 确认 `/dev/video0` 才是真正的图像流

执行：

```bash
v4l2-ctl -d /dev/video0 --list-formats-ext
v4l2-ctl -d /dev/video1 --list-formats-ext
```

结论：

- `/dev/video0` 支持：
  - `MJPG`
  - `YUYV`
  - `1280x720`
  - `640x480`
  - `30 FPS`
- `/dev/video1` 没有实际可用的图像格式

所以以后配置里只用：

```yaml
video_id: "0"
```

不要用 `/dev/video1`。

---

## 2.7 用 v4l2-ctl 验证摄像头可以真实吐帧

执行：

```bash
v4l2-ctl -d /dev/video0 \
  --set-fmt-video=width=640,height=480,pixelformat=MJPG \
  --stream-mmap=3 \
  --stream-count=30 \
  --stream-to=/tmp/cam_mjpg.raw
```

输出类似：

```text
<<<<<<<<<<<<<<<<<<< 18.50 fps, dropped buffers: 1
```

这不是报错。  
`<` 表示帧正在被抓取。

检查文件：

```bash
ls -lh /tmp/cam_mjpg.raw
```

看到：

```text
626K /tmp/cam_mjpg.raw
```

说明摄像头视频流真实可用。

---

## 2.8 用 OpenCV 验证摄像头可以读帧

执行：

```bash
conda activate agi

python - <<'PY'
import cv2
import time

cap = cv2.VideoCapture(0, cv2.CAP_V4L2)

cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
cap.set(cv2.CAP_PROP_FPS, 30)
cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

print("opened:", cap.isOpened())
print("width:", cap.get(cv2.CAP_PROP_FRAME_WIDTH))
print("height:", cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
print("fps:", cap.get(cv2.CAP_PROP_FPS))

fourcc = int(cap.get(cv2.CAP_PROP_FOURCC))
print("fourcc:", "".join([chr((fourcc >> 8 * i) & 0xFF) for i in range(4)]))

for i in range(20):
    ok, frame = cap.read()
    print("read", i, ok, None if frame is None else frame.shape)
    if ok and frame is not None:
        cv2.imwrite("/tmp/opencv_video0_test.jpg", frame)
        print("saved: /tmp/opencv_video0_test.jpg")
        break
    time.sleep(0.1)

cap.release()
PY
```

成功输出：

```text
opened: True
width: 640.0
height: 480.0
fps: 30.0
fourcc: MJPG
read 0 True (480, 640, 3)
saved: /tmp/opencv_video0_test.jpg
```

这说明 OpenCV 读取摄像头没有问题。

---

## 2.9 用 FFmpeg 验证摄像头也可读

执行：

```bash
ffmpeg -y -f v4l2 \
  -input_format mjpeg \
  -video_size 640x480 \
  -framerate 30 \
  -i /dev/video0 \
  -frames:v 1 \
  -update 1 \
  /tmp/cam_test.jpg
```

成功抓取一帧图片。

---

# 3. 修复 OpenCV GUI 问题

---

## 3.1 原始错误

运行：

```bash
teleimager-client --host 127.0.0.1
```

一开始报：

```text
cv2.error: The function is not implemented
...
in function 'cvWaitKey'
```

原因是 conda 环境里同时存在：

```text
opencv-python
opencv-python-headless
```

并且实际加载的是：

```text
GUI: NONE
```

所以 `cv2.imshow()` / `cv2.waitKey()` 不能用。

---

## 3.2 修复方法

在 `agi` 环境中执行：

```bash
conda activate agi

pip uninstall -y opencv-python-headless opencv-contrib-python-headless opencv-python opencv-contrib-python
pip install --no-cache-dir opencv-python==4.11.0.86
```

安装 GUI 相关依赖：

```bash
sudo apt update
sudo apt install -y libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 libgtk2.0-dev pkg-config
```

检查 OpenCV GUI：

```bash
python - <<'PY'
import cv2

print("cv2 version:", cv2.__version__)
print("cv2 file:", cv2.__file__)

info = cv2.getBuildInformation()
for line in info.splitlines():
    if "GUI:" in line or "GTK" in line or "QT" in line:
        print(line)
PY
```

成功结果：

```text
GUI: QT5
QT: YES
```

这说明 OpenCV 可以弹出 GUI 窗口。

---

## 3.3 测试 OpenCV 弹窗

```bash
python - <<'PY'
import cv2
import numpy as np

img = np.zeros((240, 320, 3), dtype=np.uint8)
cv2.putText(img, "OpenCV GUI OK", (30, 120),
            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)

cv2.imshow("test", img)
print("A window should appear. Press any key in that window.")
cv2.waitKey(0)
cv2.destroyAllWindows()
PY
```

如果看到窗口并能按键关闭，说明 `teleimager-client` 的 GUI 依赖已经修好。

---

# 4. 修复 teleimager 的 camera finder 探测问题

---

## 4.1 问题表现

虽然手动 OpenCV 可以读取 `/dev/video0`，但一开始：

```bash
python -m teleimager.image_server --cf
```

仍然显示：

```text
Found RGB video devices: []
```

原因是 `teleimager` 自己的自动探测逻辑里没有强制 MJPG，导致在 WSL2 + usbipd 摄像头场景下容易 timeout。

---

## 4.2 patch 探测逻辑

先备份：

```bash
cd ~/unitree/unitree-notes/teleimager
cp src/teleimager/image_server.py src/teleimager/image_server.py.bak
```

执行 patch：

```bash
python - <<'PY'
from pathlib import Path

p = Path("src/teleimager/image_server.py")
s = p.read_text()

old = "cap = cv2.VideoCapture(video_path)"
new = """cap = cv2.VideoCapture(video_path, cv2.CAP_V4L2)
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        cap.set(cv2.CAP_PROP_FPS, 30)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)"""

if old not in s:
    raise SystemExit("没有找到 cap = cv2.VideoCapture(video_path)，请用 grep 查看实际代码。")

s = s.replace(old, new, 1)
p.write_text(s)

print("patched CameraFinder OpenCV MJPG probing")
PY
```

之后重新执行：

```bash
python -m teleimager.image_server --cf
```

成功看到：

```text
Found video devices: ['/dev/video0', '/dev/video1']
Found RGB video devices: ['/dev/video0']
```

---

# 5. 修复 `video_id: 0` 被当作 False 的问题

---

## 5.1 问题表现

启动 server 时出现：

```text
Cannot find OpenCVCamera for head_camera with video_id 0
```

虽然 `--cf` 已经能识别：

```text
Found RGB video devices: ['/dev/video0']
```

原因是配置文件中如果写：

```yaml
video_id: 0
```

YAML 会把它解析为整数 `0`。  
Python 里：

```python
bool(0) == False
```

于是源码里类似：

```python
video_path = f"/dev/video{video_id}" if video_id else None
```

会把 `video_path` 变成 `None`，导致匹配失败。

---

## 5.2 最简单修复：把 `video_id` 写成字符串

在：

```bash
cd ~/unitree/unitree-notes/teleimager
nano cam_config_server.yaml
```

中把：

```yaml
video_id: 0
```

改成：

```yaml
video_id: "0"
```

这是关键。

---

# 6. 最终 `cam_config_server.yaml` 推荐配置

当前只有一个普通 USB 摄像头，所以只启用 `head_camera`，关闭两个 wrist camera。

```yaml
head_camera:
  enable_zmq: true
  zmq_port: 55555
  enable_webrtc: false
  webrtc_port: 60001
  webrtc_codec: h264
  type: opencv
  image_shape: [480, 640]
  binocular: false
  fps: 30
  video_id: "0"
  serial_number: null
  physical_path: null

left_wrist_camera:
  enable_zmq: false
  zmq_port: 55556
  enable_webrtc: false
  webrtc_port: 60002
  webrtc_codec: h264
  type: opencv
  image_shape: [480, 640]
  binocular: false
  fps: 30
  video_id: "2"
  serial_number: null
  physical_path: null

right_wrist_camera:
  enable_zmq: false
  zmq_port: 55557
  enable_webrtc: false
  webrtc_port: 60003
  webrtc_codec: h264
  type: opencv
  image_shape: [480, 640]
  binocular: false
  fps: 30
  video_id: "4"
  serial_number: null
  physical_path: null
```

关键配置解释：

| 字段 | 当前值 | 原因 |
|---|---:|---|
| `type` | `opencv` | WSL2 + usbipd 下 OpenCV + MJPG 更稳定 |
| `video_id` | `"0"` | 必须是字符串，避免整数 `0` 被当成 `False` |
| `image_shape` | `[480, 640]` | teleimager 按 `[height, width]` 写 |
| `fps` | `30` | `/dev/video0` 支持 640x480 30 FPS |
| `binocular` | `false` | 当前摄像头是单目 |
| `enable_zmq` | `true` | 先验证 ZMQ 图传 |
| `enable_webrtc` | `false` | 先避免 WebRTC 额外复杂度 |
| wrist cameras | disabled | 当前只有一个摄像头 |

---

# 7. 最终运行命令汇总

---

## 7.1 PowerShell：每次开机/重启 WSL 后

```powershell
usbipd list
usbipd attach --wsl --busid 1-8
usbipd list
```

如果还没有 shared：

```powershell
usbipd bind --busid 1-8 --force
usbipd attach --wsl --busid 1-8
```

期望：

```text
USB2.0 HD UVC WebCam    Attached
```

---

## 7.2 WSL：确认摄像头存在

```bash
lsusb
ls -l /dev/video*
v4l2-ctl --list-devices
```

可选：确认 `/dev/video0` 能吐帧：

```bash
v4l2-ctl -d /dev/video0 \
  --set-fmt-video=width=640,height=480,pixelformat=MJPG \
  --stream-mmap=3 \
  --stream-count=30 \
  --stream-to=/tmp/cam_mjpg.raw
```

---

## 7.3 WSL 终端 1：启动服务端

```bash
conda activate agi
cd ~/unitree/unitree-notes/teleimager
python -m teleimager.image_server
```

不要加 `-c`。

---

## 7.4 WSL 终端 2：启动客户端

```bash
conda activate agi
cd ~/unitree/unitree-notes/teleimager
teleimager-client --host 127.0.0.1
```

或者：

```bash
python -m teleimager.image_client --host 127.0.0.1
```

---

# 8. 常见问题速查

---

## 8.1 `Found video devices: []`

说明 WSL 里没有摄像头节点。

检查：

```bash
lsusb
ls -l /dev/video*
```

如果没有 `/dev/video0`，回到 PowerShell：

```powershell
usbipd list
usbipd attach --wsl --busid 1-8
```

---

## 8.2 `Permission denied`

如果：

```bash
v4l2-ctl --list-devices
```

报：

```text
Permission denied
```

执行：

```bash
sudo usermod -aG video $USER
newgrp video
groups
```

确认 `groups` 里有：

```text
video
```

---

## 8.3 OpenCV `select() timeout`

如果 OpenCV 默认读取 timeout，要强制 MJPG：

```python
cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
cap.set(cv2.CAP_PROP_FPS, 30)
```

---

## 8.4 `cv2.waitKey is not implemented`

说明 OpenCV 是 headless 或 GUI 不可用。

检查：

```bash
python - <<'PY'
import cv2
print(cv2.getBuildInformation())
PY
```

如果看到：

```text
GUI: NONE
```

修复：

```bash
pip uninstall -y opencv-python-headless opencv-contrib-python-headless opencv-python opencv-contrib-python
pip install --no-cache-dir opencv-python==4.11.0.86
```

再确认：

```bash
python - <<'PY'
import cv2
info = cv2.getBuildInformation()
for line in info.splitlines():
    if "GUI:" in line or "QT" in line or "GTK" in line:
        print(line)
PY
```

期望：

```text
GUI: QT5
```

---

## 8.5 `unrecognized arguments: -c cam_config_server.yaml`

说明当前版本 `image_server.py` 不支持 `-c`。

正确启动：

```bash
python -m teleimager.image_server
```

错误启动：

```bash
python -m teleimager.image_server -c cam_config_server.yaml
```

---

## 8.6 `Cannot find OpenCVCamera for head_camera with video_id 0`

优先检查：

```bash
grep -nA20 "head_camera" cam_config_server.yaml
```

确认：

```yaml
type: opencv
video_id: "0"
```

注意 `video_id` 必须是字符串 `"0"`，不是整数 `0`。

---

## 8.7 server 启动后 client 收到 config 但没有窗口

先确认 OpenCV GUI：

```bash
python - <<'PY'
import cv2
import numpy as np

img = np.zeros((240, 320, 3), dtype=np.uint8)
cv2.putText(img, "OpenCV GUI OK", (30, 120),
            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)

cv2.imshow("test", img)
cv2.waitKey(0)
cv2.destroyAllWindows()
PY
```

如果这个窗口可以弹出，client 才能弹出图传窗口。

---

# 9. 当前可用状态快照

| 项目 | 当前状态 |
|---|---|
| PowerShell `usbipd list` | 摄像头可见 |
| `usbipd attach` | 成功 |
| WSL `lsusb` | 能看到 Sonix UVC WebCam |
| `/dev/video0` | 存在，可读 |
| `/dev/video1` | 存在，但不用 |
| `v4l2-ctl` 抓帧 | 成功 |
| OpenCV 读帧 | 成功 |
| OpenCV GUI | `QT5`，成功 |
| `teleimager --cf` | 成功识别 `/dev/video0` |
| `cam_config_server.yaml` | 使用 `type: opencv` 和 `video_id: "0"` |
| `image_server` | 成功启动 |
| `teleimager-client` | 成功弹出实时窗口 |

---

# 10. 最短启动版

以后如果环境没有变，最短流程如下。

## PowerShell

```powershell
usbipd attach --wsl --busid 1-8
```

## WSL 终端 1

```bash
conda activate agi
cd ~/unitree/unitree-notes/teleimager
python -m teleimager.image_server
```

## WSL 终端 2

```bash
conda activate agi
cd ~/unitree/unitree-notes/teleimager
teleimager-client --host 127.0.0.1
```

如果 PowerShell 提示设备没有 shared，再补：

```powershell
usbipd bind --busid 1-8 --force
usbipd attach --wsl --busid 1-8
```

---

# 11. 重要提醒

1. `BUSID` 可能变化，变了就重新 `usbipd list`。
2. WSL 重启后需要重新 `usbipd attach`。
3. `/dev/video0` 是当前真正画面流。
4. `video_id` 必须写 `"0"`，不要写 `0`。
5. `image_server` 不支持 `-c` 参数。
6. 先用 ZMQ，WebRTC 后面再单独调。
7. 如果未来 `git pull` 覆盖源码，之前对 `image_server.py` 的 MJPG patch 可能需要重新打。
