# Teleimager 仓库深度学习笔记

> **仓库定位**：Unitree Robotics 出品的"多相机图像服务"，把机器人本体上的若干 USB / RealSense / 仿真相机的画面，通过 **ZeroMQ PUB-SUB**（高画质 LAN 流）和 **WebRTC**（低延时浏览器 / VR 流）两种通道发布出去，并通过 **ZeroMQ REQ-REP** 回应客户端的相机配置查询。它是 [`xr_teleoperate`](https://github.com/unitreerobotics/xr_teleoperate) 的视觉数据源。
>
> **代码体量**：1 个 1567 行的 `image_server.py` + 1 个 772 行的 `image_client.py` + 一份 yaml + 两个 shell 脚本 + 打包文件。所有"用户可调用 API" 在源码里都用 `# public api` 注释标记。
>
> **本文目标**：让读者读完一遍即可在脑里复现整个系统：知道每个文件的作用、每个类的职责边界、每个方法在干什么、线程是怎么跑的、配置是怎么解析的、自启动是怎么注册的。

---

## 目录

1. [仓库全量路径说明表](#1-仓库全量路径说明表)
2. [整体架构与数据流](#2-整体架构与数据流)
3. [配置文件：`cam_config_server.yaml`](#3-配置文件cam_config_serveryaml)
4. [`image_server.py` 深度拆解](#4-image_serverpy-深度拆解)
5. [`image_client.py` 深度拆解](#5-image_clientpy-深度拆解)
6. [启动脚本](#6-启动脚本)
7. [打包与命令行入口（`pyproject.toml`）](#7-打包与命令行入口pyprojecttoml)
8. [关键设计点回顾](#8-关键设计点回顾)
9. [与 `xr_teleoperate` 的协作关系](#9-与-xr_teleoperate-的协作关系)
10. [典型使用流程速查](#10-典型使用流程速查)

---

## 1. 仓库全量路径说明表

| 路径 | 类型 | 大小 | 主要作用 |
| --- | --- | --- | --- |
| `LICENSE` | 文本 | ~700 B | Apache 2.0 许可声明，注明引用了 [beavr-bot](https://github.com/ARCLab-MIT/beavr-bot) 的部分代码。 |
| `README.md` | Markdown | ~16 KB | 英文版使用文档：功能列表、环境安装、相机发现、启动指引、设计原则、FAQ。 |
| `README_zh-CN.md` | Markdown | ~18 KB | 同上的中文版本。 |
| `.gitignore` | 文本 | <1 KB | 忽略 `.vscode/`、`build/`、`__pycache__`、`*.pem`/`*.key`/`*.cnf`（证书相关）、`*_client.yaml`（客户端缓存的 cam_config）等。 |
| `pyproject.toml` | TOML | ~1 KB | 包元数据 `teleimager==1.5.0`，Python 3.8–3.11，定义运行依赖和 `server` 可选依赖，注册两个命令行入口 `teleimager-server` / `teleimager-client`。 |
| `cam_config_server.yaml` | YAML | ~3 KB | **核心配置**：定义 `head_camera` / `left_wrist_camera` / `right_wrist_camera` 三个相机的 ZMQ/WebRTC 端口、编解码、分辨率、FPS、识别符（video_id / serial_number / physical_path）。 |
| `setup_uvc.sh` | Bash | ~1.5 KB | 一次性环境配置：写 udev 规则，把当前用户加入 `video` 组，给 `modprobe -r/+ uvcvideo` 配置免密 sudo，并立即重载 UVC 驱动。 |
| `setup_autostart.sh` | Bash | ~5.5 KB | 安装 systemd 服务 `teleimager.service`：自动检测 conda 路径与环境，让 `teleimager-server` 在开机时启动，CPUAffinity 锁到 0/1/2。 |
| `src/teleimager/__init__.py` | Python | 空 | 仅作为包标记。 |
| `src/teleimager/image_server.py` | Python | 1567 行 | **服务端实现**：相机发现 + 三类相机驱动封装（UVC/OpenCV/RealSense/IsaacSim）+ Triple Ring Buffer 推流缓存 + WebRTC 推流（aiortc + aiohttp + libx264 自定义编码） + 调度采集线程 + 信号处理。 |
| `src/teleimager/image_client.py` | Python | 772 行 | **客户端实现**（同时也是 server 的工具库）：`TripleRingBuffer` / `SimpleFPSMonitor` 工具类、ZMQ PUB/SUB/REP/REQ 全套封装、`TeleImage` 数据类、`ImageClient` 顶层 API。 |
| `src/teleimager/__pycache__/` | 自动生成 | – | Python 字节码缓存（被 `.gitignore`）。 |

> **注**：仓库根目录运行时还可能出现 `cert.pem` / `key.pem`（WebRTC 用 TLS 证书，由 [televuer](https://github.com/unitreerobotics/televuer) 生成）和 `cam_config_client.yaml`（客户端从服务器拉到 cam_config 后的本地缓存），这两类文件都在 `.gitignore` 里，不会出现在仓库提交记录中。

---

## 2. 整体架构与数据流

### 2.1 进程视角

`teleimager` 默认是**单进程多线程**架构。一台机器人主控（通常是 NVIDIA Jetson Orin NX）上跑一个 `teleimager-server` 进程，它会启动如下线程组：

```
teleimager-server (主进程)
│
├── ZMQ_Responser             [线程]   ── REP @ 60000，向客户端回送 cam_config
│
├── 每路相机:
│   ├── _update_frames        [线程]   ── 从相机驱动读帧 → 写入 Triple Ring Buffer
│   ├── _zmq_pub              [线程]   ── 从 buffer 拿 jpeg → 调用 ZMQ_PublisherManager
│   └── _webrtc_pub           [线程]   ── 从 buffer 拿 BGR ndarray → 调用 WebRTC_PublisherManager
│
├── ZMQ_PublisherManager (单例)
│   └── 每个 zmq_port 一个 ZMQ_PublisherThread   [线程]
│       └── PUB socket bind tcp://0.0.0.0:<zmq_port>
│
└── WebRTC_PublisherManager (单例)
    └── 每个 webrtc_port 一个 WebRTC_PublisherThread [线程]
        └── 内含独立 asyncio EventLoop
        └── aiohttp HTTPS 服务 :<webrtc_port>     (PEM 证书)
        └── aiortc PeerConnection 池 + MediaRelay
```

客户端进程对应：

```
teleimager-client (主进程)
│
├── ZMQ_Requester                       ── REQ → 60000，把 cam_config 拉到本地
│
└── ZMQ_SubscriberManager (单例)
    └── 每个 (host, zmq_port) 一个 ZMQ_SubscriberThread   [线程]
        ├── SUB socket connect tcp://<host>:<zmq_port>
        ├── jpg bytes 写入 TripleRingBuffer
        └── (可选) request_bgr=True 时启动 _decoder_loop [线程]
            └── 把 jpg bytes 解成 BGR ndarray，再写入 BGR TripleRingBuffer
```

### 2.2 一帧画面的旅程

```
[USB 摄像头]
      │ MJPEG bytes (UVC) 或 BGR ndarray (OpenCV/RealSense/IsaacSim)
      ▼
[BaseCamera._update_frame]                     ── _update_frames 线程内调用
      │                                         按 cam_type 分支
      ▼
   ┌─────────────────────┬────────────────────┐
   │ UVC: 直接拿 jpeg    │ OpenCV/RS/Isaac:  │
   │       和 frame.bgr  │ cv2.imencode .jpg │
   └─────────┬───────────┴─────────┬──────────┘
             │ jpeg bytes          │ BGR ndarray
             ▼                     ▼
   _zmq_buffer: TripleRingBuffer    _webrtc_buffer: TripleRingBuffer
             │                     │
   _zmq_pub 线程 (sleep 1/fps)     _webrtc_pub 线程 (sleep 1/fps)
             │                     │
             ▼                     ▼
   ZMQ_PublisherManager.publish    WebRTC_PublisherManager.publish
             │                     │
   ZMQ_PublisherThread.send         WebRTC_PublisherThread.send
             │                     │
   queue.Queue(maxsize=10)          queue.Queue(maxsize=1)
             │                     │
   PUB.send(jpeg, NOBLOCK)          asyncio Track.recv ← BGRArrayVideoStreamTrack
             │                     │
             │                     ├── av.VideoFrame.from_ndarray(format=bgr24)
             │                     ├── PTS 按 90 kHz 时基计算
             │                     └── (Jetson) libx264 ultrafast/zerolatency 软编码
             ▼                     ▼
   ┌────── tcp://*:<zmq_port> ──┐  ┌─── DTLS/SRTP webrtc :<webrtc_port> ───┐
   │                            │  │                                       │
   ▼                            ▼  ▼                                       ▼
 ZMQ 客户端 (image_client.py)    浏览器/VR  (HTML+JS @ /, /client.js)
   │                                                                       │
   ▼                                                                       ▼
 ZMQ_SubscriberThread.run                                            <video> 渲染
   ├── jpg bytes → TripleRingBuffer (jpg)
   └── (request_bgr) → cv2.imdecode → TripleRingBuffer (bgr)
   ▼
 ImageClient.get_*_frame() → TeleImage(fps, jpg, bgr)
```

### 2.3 三个 ZMQ 端口角色

| 端口角色 | 协议 | 默认端口 | 谁 bind | 谁 connect |
| --- | --- | --- | --- | --- |
| 配置查询 | REQ-REP | 60000 | `ZMQ_Responser`（server 侧） | `ZMQ_Requester`（client 侧） |
| 图像分发 | PUB-SUB | 55555/55556/55557（每路相机一个） | `ZMQ_PublisherThread`（server 侧） | `ZMQ_SubscriberThread`（client 侧） |
| WebRTC 信令+媒体 | HTTPS + DTLS/SRTP | 60001/60002/60003 | `WebRTC_PublisherThread.aiohttp + aiortc` | 浏览器 / aiortc-client |

---

## 3. 配置文件：`cam_config_server.yaml`

`cam_config_server.yaml` 是 server 启动时加载的唯一相机配置源；同时也通过 REP-socket 完整地原样发给客户端，所以两端语义一致。

仓库附带的样例定义了三个相机：`head_camera`、`left_wrist_camera`、`right_wrist_camera`。三者结构相同，逐字段说明如下。

### 3.1 字段表

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `enable_zmq` | bool | 是否启用 ZeroMQ PUB-SUB 推流。**与 `enable_webrtc` 都为 false 时该相机被跳过初始化。** |
| `zmq_port` | int | PUB socket bind 的 TCP 端口。每个相机必须互不冲突。 |
| `enable_webrtc` | bool | 是否启动 WebRTC 推流。 |
| `webrtc_port` | int | aiohttp HTTPS 服务监听端口（同时也是 WebRTC 信令入口，浏览器访问 `https://host:port`）。 |
| `webrtc_codec` | `"h264"` / `"vp8"` / null | 编解码偏好。`h264`（默认）走 libx264 ultrafast；`vp8` 用 libvpx；空值或不识别时回落到 H264，再不行再交给 aiortc 自动协商。 |
| `type` | `"uvc"` / `"opencv"` / `"realsense"` / `"isaacsim"` | 决定调用哪个相机封装类。`isaacsim` 仅在以 `isaacsim_enable=True` 启动 server 时使用，从共享内存读图。 |
| `image_shape` | `[height, width]` | 期望的图像分辨率。注意是 **HxW** 顺序（OpenCV 也常见这种排列）。例如 `[480, 1280]` 表示 480 高 1280 宽（双目拼接）。 |
| `binocular` | bool | 仅在 `head_camera` 中含义重要。值为 true 表示这是一对左右拼接的双目摄像头。`IsaacSimCamera` 会在 `binocular=True` 时把仿真侧 `left+right` 两张图 `cv2.hconcat` 拼起来。 |
| `fps` | int | 期望帧率。`UVCCamera._choose_mode` 严格匹配，找不到精确等同的 MJPG 模式会抛错。 |
| `video_id` | int / null | `/dev/videoX` 的 X 值，最低优先级标识符。 |
| `serial_number` | str / null | 厂商序列号，中等优先级。 |
| `physical_path` | str / null | sysfs 物理 USB 路径（最稳定，跨重启不变），最高优先级。 |

### 3.2 优先级解析

`ImageServer.__init__` 里实现的解析顺序为：**`physical_path > serial_number > video_id`**。注意一个**陷阱**：

> 一旦显式设置了 `physical_path` 或 `serial_number`（任一非空），系统就会停在该层级——即便没找到匹配的相机也不会回落到 `video_id`。这是为了保证多相机配置不会因为插拔顺序变化而错乱地回落到错误的设备。

`type=realsense` 时**只支持 `serial_number`**（其它两个字段会被忽略）。RealSense 自身硬件序列号稳定唯一，所以这是合理选择。

### 3.3 yaml ↔ 客户端键的隐含约定

`ImageClient.__init__` 直接用字面键 `head_camera` / `left_wrist_camera` / `right_wrist_camera` 访问 cam_config。**改键名会破坏客户端**。如果想加第四个相机，需要同步修改 `ImageClient` 顶层逻辑（目前它把这三路硬编码做了订阅）。

---

## 4. `image_server.py` 深度拆解

文件按"自上而下"的依赖顺序组织，下面也按这个顺序分节。

### 4.1 模块级常量与初始化（L1–L70）

```python
import logging_mp
logging_mp.basicConfig(level=logging_mp.INFO)
logger_mp = logging_mp.getLogger(__name__)
```

- **`logging_mp`**：是 Unitree 的多进程友好 logger（带文件名:行号、毫秒级时间戳）。客户端文件也用同一个库。
- **`from .image_client import TripleRingBuffer, ZMQ_PublisherManager, ZMQ_Responser`**：服务端复用了客户端文件里的工具类——这就是为什么 `image_client.py` 里既有 PUB 也有 SUB；它实际上是"通信工具库"，server 侧只用 PUB 与 REP 部分。

**`CONFIG_PATH`**（L50–L54）：

```python
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "cam_config_server.yaml")
```

`__file__` 是 `<repo>/src/teleimager/image_server.py`，往上两层就是仓库根目录。**所以 yaml 必须放在 git 仓库根**，不能跟 setup.py 的"安装后位置"混用——开发模式 `pip install -e .` 是必须的。

**证书路径解析**（L57–L70）：

```python
module_dir = Path(__file__).resolve().parent.parent.parent  # 仓库根
default_cert = module_dir / "cert.pem"
default_key  = module_dir / "key.pem"
env_cert = os.getenv("XR_TELEOP_CERT")
env_key  = os.getenv("XR_TELEOP_KEY")
user_config_dir = Path.home() / ".config" / "xr_teleoperate"
user_cert = user_config_dir / "cert.pem"
user_key  = user_config_dir / "key.pem"
CERT_PEM_PATH = Path(env_cert or (user_cert if user_cert.exists() else default_cert))
KEY_PEM_PATH  = Path(env_key  or (user_key  if user_key.exists()  else default_key))
```

优先级：**环境变量 > `~/.config/xr_teleoperate/` > 仓库根**。这与 `setup_autostart.sh` 写入 systemd 的 `Environment=` 行（强制指向 `/home/unitree/.config/...`）相一致。

### 4.2 H.264 Encoder Patch（L73–L115）

为了在 Jetson 上稳定地软编 H.264，作者**直接 monkey-patch 了 `aiortc.codecs.h264.H264Encoder._encode_frame`**：

```python
def jetson_software_encode_frame(self, frame, force_keyframe):
    if self.codec is None:
        self.codec = av.CodecContext.create("libx264", "w")
        self.codec.width  = frame.width
        self.codec.height = frame.height
        self.codec.bit_rate = self.target_bitrate
        self.codec.pix_fmt = "yuv420p"
        self.codec.framerate = fractions.Fraction(30, 1)
        self.codec.time_base = fractions.Fraction(1, 30)
        self.codec.options = {
            "preset": "ultrafast",
            "tune":   "zerolatency",
            "threads": "1",
            "g":      "60",          # 每 60 帧强制一个 IDR
        }
        force_keyframe = True
    if not force_keyframe and self.frame_count % 60 == 0:
        force_keyframe = True
    frame.pict_type = av.video.frame.PictureType.I if force_keyframe else av.video.frame.PictureType.NONE
    for packet in self.codec.encode(frame):
        yield from self._split_bitstream(bytes(packet))

h264.H264Encoder._encode_frame = jetson_software_encode_frame
```

**要点**：

1. `aiortc` 默认会试图调用硬件 H.264 编码器（在 Jetson 上路径不稳定甚至错误）。这里强制走 `libx264` 软编。
2. `preset=ultrafast / tune=zerolatency / threads=1` 三连，是经典低延时配置。`threads=1` 也避免与 `set_performance_mode` 钉的 0/1/2 三核冲突。
3. 每 60 帧（默认 fps=30 → 2 秒）一个关键帧，保证新订阅者能在 ≤2 秒内对齐画面。
4. 当输入分辨率发生变化时（`frame.width != self.codec.width`），重置 codec。

### 4.3 内嵌 HTML/JS（L120–L245）

WebRTC 客户端页面与 JS 都嵌成 Python 字符串。

**`INDEX_HTML`** 是简单的播放器页面：标题 + Logo + Start/Stop 按钮 + `<video>` + `<audio>`。

**`CLIENT_JS`** 是 WebRTC 协商的浏览器侧实现：

```js
function negotiate() {
    pc.addTransceiver('video', { direction: 'recvonly' });
    return pc.createOffer()
        .then(offer => pc.setLocalDescription(offer))
        .then(() => /* 等 ICE gathering 完成 */ )
        .then(() => fetch('/offer', {                       // POST 给 aiohttp
            body: JSON.stringify({sdp: pc.localDescription.sdp, type: 'offer'}),
            method: 'POST'
        }))
        .then(r => r.json())
        .then(answer => pc.setRemoteDescription(answer));
}
```

注意**没有 STUN 服务器**——典型 LAN 内 / VR-头显与 robot 同子网的部署场景。

### 4.4 `BGRArrayVideoStreamTrack`（L250–L304）

**定位**：把 numpy BGR ndarray 包装成 aiortc `MediaStreamTrack`，是 server 侧"图像数据 → WebRTC"的桥梁。

```python
class BGRArrayVideoStreamTrack(MediaStreamTrack):
    kind = "video"
    def __init__(self):
        super().__init__()
        self._queue = asyncio.Queue(maxsize=1)   # 只保留最新一帧
        self._start_time = None
        self._pts = 0

    async def recv(self):
        return await self._queue.get()           # aiortc 调用，会一直挂起

    def push_frame(self, bgr_numpy, loop=None):
        video_frame = av.VideoFrame.from_ndarray(bgr_numpy, format="bgr24")
        if self._start_time is None:
            self._start_time, self._pts = time.time(), 0
        else:
            self._pts = int((time.time() - self._start_time) * 90000)  # 90 kHz RTP 时基
        video_frame.pts = self._pts
        video_frame.time_base = fractions.Fraction(1, 90000)
        # 跨线程入队（drop-old 策略）
        target_loop = loop or asyncio.get_event_loop()
        def _put():
            if self._queue.full(): self._queue.get_nowait()
            self._queue.put_nowait(video_frame)
        target_loop.call_soon_threadsafe(_put)
```

**关键设计**：

- `_queue.maxsize=1` + drop-old：典型实时流策略，永远只保留**最新**一帧。
- PTS 用真实墙钟差 × 90000 计算，符合 RTP 视频时基习惯，确保播放器节奏正确（这是注释里强调的 "MediaRelay 需要一致 PTS"）。
- 用 `call_soon_threadsafe` 把帧从工作线程递交给 asyncio loop——`push_frame` 在另一个线程里被调用。

### 4.5 `WebRTC_PublisherThread`（L307–L477）

**定位**：单一 WebRTC 端口的全部生命周期。每个 `webrtc_port` 一个实例。

#### 构造（L312–L335）

```python
def __init__(self, port, host="0.0.0.0", codec_pref=None):
    super().__init__(daemon=True)
    self._app = web.Application()
    self._pcs = set()                # 所有活跃 RTCPeerConnection
    self._frame_queue = queue.Queue(maxsize=1)
    self._bgr_track = None           # 在 run() 里创建（必须在新 loop 内）
    self._relay = None
    self._loop = None
    # 注册路由：/  /client.js  /offer  + OPTIONS（CORS 预检）
```

#### `run`（L424–L462）

```python
def run(self):
    self._loop = asyncio.new_event_loop()
    asyncio.set_event_loop(self._loop)

    async def _main():
        runner = web.AppRunner(self._app); await runner.setup()
        self._bgr_track = BGRArrayVideoStreamTrack()
        self._relay = MediaRelay()
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_context.load_cert_chain(CERT_PEM_PATH, KEY_PEM_PATH)
        site = web.TCPSite(runner, self._host, self._port, ssl_context=ssl_context)
        await site.start()
        self._start_event.set()         # 通知主线程"我已就绪"

        while not self._stop_event.is_set():
            if not self._frame_queue.empty():
                frame = self._frame_queue.get_nowait()
                self._bgr_track.push_frame(frame, loop=self._loop)
            await asyncio.sleep(0.005)  # 让 aiortc 处理 RTP 包
    self._loop.run_until_complete(_main())
```

**两个 `Event`**：

- `_start_event`：让 `WebRTC_PublisherManager._create_publisher` 阻塞等到 socket 真的 bind 成功（最多 10 s），否则后续 `publish` 会丢帧。
- `_stop_event`：优雅退出标记，由 `stop()` 设置。

**MediaRelay** 是 aiortc 的"广播复用器"——不管同一端口连了多少个浏览器/VR 客户端，**编码只发生一次**，再分发给所有 PeerConnection；这是高效率的关键。

#### `_offer`（L353–L413）：信令处理

```python
async def _offer(self, request):
    params = await request.json()
    offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])
    pc = RTCPeerConnection()
    self._pcs.add(pc)

    relayed_track = self._relay.subscribe(self._bgr_track)
    transceiver = pc.addTransceiver(relayed_track, direction="sendonly")
    capabilities = RTCRtpSender.getCapabilities("video")
    pref = (self._codec_pref or "h264").lower()

    if pref == "h264":
        h264_codecs = [c for c in capabilities.codecs if c.mimeType == "video/H264"]
        if h264_codecs:
            transceiver.setCodecPreferences(h264_codecs)
    elif pref == "vp8":
        vp8_codecs = [c for c in capabilities.codecs if c.mimeType == "video/VP8"]
        if vp8_codecs:
            transceiver.setCodecPreferences(vp8_codecs)
    # 其它情况：尝试 H264，再不行交给自动协商

    @pc.on("connectionstatechange")
    async def _():
        if pc.connectionState in ("failed", "closed"):
            await self._cleanup_pc(pc)

    await pc.setRemoteDescription(offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)
    return web.Response(content_type="application/json", text=json.dumps(...))
```

**亮点**：

- `setCodecPreferences` 强制把首选 codec 排在最前，aiortc 协商时通常会选第一个匹配项。
- CORS 三件套（Allow-Origin/Methods/Headers）配齐，浏览器跨域不会被拦。

#### `send` / `stop` / `wait_for_start`

- `send(data)`：drop-old 把 BGR ndarray 塞进 `_frame_queue`。
- `stop()`：置位 `_stop_event` 并 `join(1s)`。
- `wait_for_start(timeout)`：阻塞等待第一次 `await site.start()` 完成。

### 4.6 `WebRTC_PublisherManager`（L483–L531）

**单例 + 端口路由**（与 `ZMQ_PublisherManager` 同构）：

| 方法 | 作用 |
| --- | --- |
| `get_instance()` | 双重检查锁式单例。 |
| `_create_publisher(port, host, codec_pref)` | 起一个 `WebRTC_PublisherThread` 并等其就绪（10 s 超时）。 |
| `_get_publisher(...)` | 用 `(host, port)` 作 key，懒创建。 |
| `publish(data, port, host="0.0.0.0", codec_pref=None)` | 公开 API。把 ndarray 塞给对应 publisher。 |
| `close()` | 把 `_running` 置 false，停所有 publisher，清空 dict。 |

`_publisher_threads: Dict[(host, port), WebRTC_PublisherThread]` 让"先在 yaml 里写 webrtc_port=60001 → 后续 publish 时会自动起线程"成为可能；server 不用预先知道有几路相机。

### 4.7 `reload_uvc_driver`（L536–L544）

```python
def reload_uvc_driver():
    subprocess.run("sudo modprobe -r uvcvideo", shell=True, check=True)
    time.sleep(1)
    subprocess.run("sudo modprobe uvcvideo debug=0", shell=True, check=True)
    time.sleep(1)
```

**为什么需要**：在 Jetson 上 USB 摄像头有时会因驱动状态遗留导致 `pupil-labs-uvc` 无法初始化（特别是热插拔后）。强制 `modprobe -r/+ uvcvideo` 解决了 90% 的场景。`debug=0` 把内核冗余日志关掉。

`setup_uvc.sh` 已为 `modprobe` 配置免密 sudo，所以这个调用在生产环境不会卡。

`CameraFinder.__init__` 第一步就调用它（L561）。

### 4.8 `CameraFinder`（L549–L824）

**职责**：枚举本机所有 USB / RealSense 相机，建立 `vpath ↔ video_id ↔ physical_path ↔ uid ↔ serial_number` 之间的映射，用于配置文件解析。

#### 4.8.1 关键术语

| 术语 | 含义 | 例子 |
| --- | --- | --- |
| `vpath` | `/dev/videoX` 设备节点 | `/dev/video0` |
| `video_id` | X 数字部分 | `0` |
| `ppath` (physical_path) | `/sys/class/video4linux/videoX/device` 软链解析后的物理路径 | `/sys/devices/pci0000:00/0000:00:14.0/usb1/1-11/1-11.2/1-11.2:1.0` |
| `uid` | pyuvc 风格的 `bus:dev` ID | `"1:9"` |
| `dev_info` | pyuvc `device_list()` 返回的字典（含 idVendor、idProduct、serialNumber 等） | `{...}` |
| `sn` | 序列号字符串 | `"200901010001"` |

#### 4.8.2 构造（L558–L601）

```python
def __init__(self, realsense_enable=False, verbose=False):
    reload_uvc_driver()
    import uvc                                     # pupil-labs-uvc
    self.uvc_devices = uvc.device_list()
    self.uid_map = {dev["uid"]: dev for dev in self.uvc_devices}
    self.video_paths = self._list_video_paths()    # /dev/video0..N

    if realsense_enable:
        self.rs_serial_numbers = self._list_realsense_serial_numbers()
        self.rs_video_paths    = self._list_realsense_video_paths()
        self.rs_rgb_video_paths = [p for p in self.rs_video_paths if self._is_like_rgb(p)]
    else:
        self.rs_serial_numbers = []
        self.rs_video_paths = []
        self.rs_rgb_video_paths = []

    # 对所有 RGB 类 UVC 视频设备建立完整索引
    self.uvc_rgb_video_paths    = self._list_uvc_rgb_video_paths()
    self.uvc_rgb_video_ids      = [int(v[len("/dev/video"):]) for v in self.uvc_rgb_video_paths]
    self.uvc_rgb_physical_paths = [self._get_ppath_from_vpath(v) for v in self.uvc_rgb_video_paths]
    self.uvc_rgb_uids           = [self._get_uid_from_ppath(p) for p in self.uvc_rgb_physical_paths]
    self.uvc_rgb_dev_info       = [self.uid_map.get(uid) for uid in self.uvc_rgb_uids]
    self.uvc_rgb_serial_numbers = [info.get("serialNumber") if info else None for info in self.uvc_rgb_dev_info]

    self.uvc_rgb_cameras = {}
    for vpath, vid, ppath, uid, info, sn in zip(...):
        self.uvc_rgb_cameras[vpath] = {
            "video_id": vid, "physical_path": ppath,
            "uid": uid, "dev_info": info, "serial_number": sn
        }
    if verbose: self.info()
```

#### 4.8.3 私有辅助方法

- **`_list_video_paths()`**：列出 `/sys/class/video4linux/` 下所有以 `video` 开头的项，前缀 `/dev/`。
- **`_list_uvc_rgb_video_paths()`**：在 `video_paths` 里挑出"打开能读出 BGR 三通道"且不在 `rs_video_paths` 里的设备。
- **`_list_realsense_video_paths()`**：扫描 `/dev/video*`，沿着 `device` 软链一路向上找 USB 父节点，匹配 `idVendor in {"8086", "32902"}`（Intel）且 `name` 含 `realsense`。
- **`get_realsense_module()`**：懒加载 `pyrealsense2`，未安装时根据 arm64 / x86 给出不同安装提示（arm64 给从源码编译的完整命令）。
- **`_list_realsense_serial_numbers()`**：用 `rs.context().query_devices()` 拿全部设备序列号。
- **`_get_ppath_from_vpath(vp)`**：`os.path.realpath('/sys/class/video4linux/<basename>/device')`，把符号链接还原成真实物理路径。
- **`_get_uid_from_ppath(pp)`**：读取 sysfs 节点的 `busnum` / `devnum` 文件（如果当前层没有，回退到上一级目录），拼成 `"<bus>:<dev>"`。
- **`_is_like_rgb(vpath)`**：用 `cv2.VideoCapture` 打开一次试读一帧，判断是否得到 H×W×3 的 BGR 帧——这是过滤"红外深度流之类的非 RGB 设备节点"的实用手段。

#### 4.8.4 公有 API

| 方法 | 作用 |
| --- | --- |
| `is_rs_serial_exist(sn)` | RealSense 序列号是否存在。 |
| `is_vpath_exist(vp)` / `is_ppath_exist(pp)` | 路径是否存在。 |
| `get_uid_by_sn(sn)` / `get_uid_by_ppath(pp)` / `get_uid_by_vpath(vp)` | 把任一标识符 → uvc uid（用于 `uvc.Capture(uid)`）。 |
| `get_vpath_by_sn(sn)` / `get_vpath_by_ppath(pp)` | 把 sn / ppath → `/dev/videoX`（用于 OpenCVCamera）。 |
| `info()` | 漂亮打印所有发现到的相机及其支持的格式列表（`teleimager-server --cf` 的输出）。 |

**多匹配处理**：当存在多个 sn 或 ppath 命中同一标识符时，主动 `raise ValueError`，避免静默选错。

### 4.9 `BaseCamera`（L826–L899）

抽象基类，定义所有相机驱动封装的统一接口。

#### 状态

```python
self._ready          = threading.Event()
self._cam_topic      = cam_topic                # "head_camera" 等
self._img_shape      = img_shape                # (H, W)
self._fps            = fps
self._enable_zmq     = enable_zmq
self._zmq_port       = zmq_port
self._zmq_buffer     = TripleRingBuffer() if enable_zmq else None
self._enable_webrtc  = enable_webrtc
self._webrtc_port    = webrtc_port
self._webrtc_codec   = webrtc_codec
self._webrtc_buffer  = TripleRingBuffer() if enable_webrtc else None
```

每个相机自带**两个独立的** Triple Ring Buffer——一个存 jpeg bytes 给 ZMQ，一个存 BGR ndarray 给 WebRTC。这避免了 ZMQ 拿数据时与 WebRTC 互相阻塞。

#### 抽象/具体方法

| 方法 | 是否抽象 | 说明 |
| --- | --- | --- |
| `__str__` | 抽象 | 子类必须返回描述字符串。 |
| `_update_frame()` | 抽象 | 抓一帧并写入 buffer，第一次成功后 `self._ready.set()`。 |
| `wait_until_ready(timeout)` | 具体 | 阻塞等到第一帧。`ImageServer.start` 用它做 ready barrier。 |
| `enable_webrtc()` / `enable_zmq()` | 具体 | 标志查询。 |
| `get_jpeg_bytes()` / `get_bgr_frame()` | 具体 | 从对应 buffer 读最新帧。 |
| `get_depth_frame()` | 具体（默认 None） | 仅 RealSenseCamera 实现真实返回。 |
| `get_zmq_port()` / `get_webrtc_port()` / `get_webrtc_codec()` / `get_fps()` | 具体 | 普通 getter。 |
| `release()` | 抽象 | 子类必须实现资源释放。 |

### 4.10 `RealSenseCamera`（L901–L998）

**初始化**：

```python
import pyrealsense2 as rs
self.align = rs.align(rs.stream.color)
self.pipeline = rs.pipeline()
config = rs.config()
config.enable_device(self._serial_number)
config.enable_stream(rs.stream.color, W, H, rs.format.bgr8, fps)
if enable_depth:
    config.enable_stream(rs.stream.depth, W, H, rs.format.z16, fps)
profile = self.pipeline.start(config)
self._device     = profile.get_device()
self.intrinsics  = profile.get_stream(rs.stream.color).as_video_stream_profile().get_intrinsics()
if enable_depth:
    self.g_depth_scale = self._device.first_depth_sensor().get_depth_scale()
```

构造失败时**会先 `pipeline.stop()` 再 raise**，避免泄漏 RealSense 状态。

**`_update_frame()`**：

```python
frames = self.pipeline.wait_for_frames()
aligned_frames = self.align.process(frames)
color_frame = aligned_frames.get_color_frame()
if not color_frame: return None

if self._enable_depth:
    depth_frame = aligned_frames.get_depth_frame()
    self._latest_depth = np.asanyarray(depth_frame.get_data()) if depth_frame else None

bgr_numpy = np.asanyarray(color_frame.get_data())
if self._enable_webrtc: self._webrtc_buffer.write(bgr_numpy)
if self._enable_zmq:
    ok, buf = cv2.imencode(".jpg", bgr_numpy)
    if ok: self._zmq_buffer.write(buf.tobytes())
self._ready.set()
```

**`get_depth_frame()`**：返回 `self._latest_depth.tobytes()`（注意是字节流，不是 ndarray）。当前 `enable_depth=True` 在仓库内**没有从 yaml 读取**（参数硬编码为 False）——`get_depth_frame` 是为未来扩展留的接口。

**`release()`**：尝试 `pipeline.stop()`，捕获所有异常，最终把 `self.pipeline = None`。

### 4.11 `UVCCamera`（L1000–L1062）

基于 [`pupil-labs-uvc`](https://github.com/pupil-labs/pyuvc) 的最高效路径。

```python
import uvc
self.cap = uvc.Capture(self.uid)
self.cap.frame_mode = self._choose_mode(self.cap, width=W, height=H, fps=fps)
```

**`_choose_mode`**：必须找到精确匹配 `width × height @ fps` 且 `format_name=="MJPG"` 的模式，否则 `raise ValueError`——意味着不会自动降到 YUYV 或近似 fps。这是为了保证延时和带宽符合预期。

**`_update_frame()`**：

```python
frame = self.cap.get_frame_robust()
if self._enable_zmq and frame.jpeg_buffer is not None:
    self._zmq_buffer.write(bytes(frame.jpeg_buffer))    # 直接拿到 MJPEG 字节，零编码
if self._enable_webrtc and frame.bgr is not None:
    self._webrtc_buffer.write(frame.bgr)                # pyuvc 内部已解码
self._ready.set()
```

**这是 ZMQ 路径最高效的相机类**：MJPG 帧从 USB 拿到后直接进 ZMQ buffer，零解码、零再编码。

**`release()`**：注释里写明了一个深坑——

> usbhub 拔出时，调用 `stop_streaming` / `close` 可能会**永远阻塞**。

所以这里干脆什么都不做，仅打 log。资源回收依赖进程退出。`main()` 末尾的 `os.killpg(os.getpgrp(), 9)` 也是为这个保底。

### 4.12 `OpenCVCamera`（L1064–L1115）

通用 V4L2 路径，不依赖 pyuvc。

```python
self.cap = cv2.VideoCapture(self._video_path, cv2.CAP_V4L2)
self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, H)
self.cap.set(cv2.CAP_PROP_FRAME_WIDTH,  W)
self.cap.set(cv2.CAP_PROP_FPS, fps)

if not self._can_read_frame():
    self.release(); raise RuntimeError(...)
```

**`_update_frame`**：`ret, bgr = cap.read()` → 写 webrtc buffer；ZMQ 这边需要 `cv2.imencode(".jpg", bgr)` 重新编一次 jpeg。

**与 UVCCamera 的取舍**：OpenCVCamera 普适性更好（不需要 pyuvc 二进制依赖），但 ZMQ 路径会多一次 encode/decode 循环，CPU 开销略高。

**`release()`**：直接 `cap.release()` 然后置空——OpenCV 不会因为拔 USB 而卡死，所以这里能干净地清理。

### 4.13 `IsaacSimCamera`（L1117–L1198）

仿真专用，从 `unitree_sim_isaaclab` 项目通过共享内存读图。

```python
from tools.shared_memory_utils import MultiImageReader
self.multi_image_reader = MultiImageReader()
self._image_source = image_source     # "head" / "left" / "right"
self._binocular = binocular
self._ready.set()                      # 立刻 ready，不等首帧
```

**`_update_frame()`**：

```python
if self._binocular:
    left  = self.multi_image_reader.read_single_image('left')
    right = self.multi_image_reader.read_single_image('right')
    if left is not None and right is not None:
        frame_data = cv2.hconcat([left, right])
else:
    frame_data = self.multi_image_reader.read_single_image(self._image_source)

if frame_data is not None:
    if self._enable_zmq:
        ok, buf = cv2.imencode(".jpg", frame_data)
        if ok: self._zmq_buffer.write(buf.tobytes())
    if self._enable_webrtc:
        self._webrtc_buffer.write(frame_data)
```

`ImageServer.__init__` 会根据 cam_topic 关键词推断 source：含 `"left"` → `"left"`，含 `"right"` → `"right"`，否则 `"head"`；当 `binocular=True` 时 source 被强制为 `"head"`（在 IsaacSimCamera 内部表示双目模式）。

`release()` 关闭 `multi_image_reader`。

### 4.14 `ImageServer`（L1202–L1471）

#### 4.14.1 构造（L1203–L1330）

```python
def __init__(self, cam_config, realsense_enable=False, camera_finder_verbose=False, isaacsim_enable=False):
    self._cam_config = cam_config
    self._realsense_enable = realsense_enable
    self._isaacsim_enable  = isaacsim_enable
    self._stop_event = threading.Event()
    self._cameras: dict[str, BaseCamera] = {}
    if not isaacsim_enable:
        self._cam_finder = CameraFinder(realsense_enable, camera_finder_verbose)

    self._responser              = ZMQ_Responser(cam_config)
    self._zmq_publisher_manager  = ZMQ_PublisherManager.get_instance()
    self._webrtc_publisher_manager = WebRTC_PublisherManager.get_instance()
    self._publisher_threads      = []          # 工作线程引用，便于 join

    for cam_topic, cam_cfg in cam_config.items():
        # 至少有一种发布方式打开才走下去
        if not cam_cfg.get("enable_zmq") and not cam_cfg.get("enable_webrtc"):
            continue
        # 提取所有字段
        ...
        # 按 type 分发：
        if cam_type == "opencv":   ...
        elif cam_type == "realsense": ...
        elif cam_type == "uvc":    ...
        elif cam_type == "isaacsim": ...
```

**解析逻辑细读**（以 `uvc` 为例，opencv 同构）：

1. **`physical_path` 优先**：调用 `cam_finder.get_uid_by_ppath`，找不到则把该 cam 设为 None 并报 error，但 **continue 跳过后续兜底**。
2. **`serial_number` 次之**：同上，`continue` 阻断回落。
3. **`video_id` 兜底**：用 `is_vpath_exist` 检查后构造。

`realsense` 仅按 sn 解析，且需要 `--rs` 启动；否则报错并把 cam 置 None。

`isaacsim` 路径根据 cam_topic 推断 source / binocular。

如果 `isaacsim_enable=True` 但配置里 type 不是 isaacsim，会**强制覆盖为 `isaacsim`**（L1228–L1229）——这让同一份 yaml 在物理 / 仿真两种模式下复用。

构造抛错时调用 `self._clean_up()` 然后再次 raise。

#### 4.14.2 三个工作线程函数（L1332–L1400）

**`_update_frames(cam_topic, camera)`**：

```python
interval = 1.0 / camera.get_fps()
next_frame_time = time.monotonic()
while not self._stop_event.is_set():
    try: camera._update_frame()
    except Exception:
        self._stop_event.set(); break
    next_frame_time += interval
    sleep_time = next_frame_time - time.monotonic()
    if sleep_time > 0: time.sleep(sleep_time)
    else: next_frame_time = time.monotonic()
```

经典"目标时间累加 + 跌出窗口就重置"——保证长期稳态接近期望 fps，又不会被一次延迟拖累成无限补偿。

**`_zmq_pub(cam_topic, camera)`** / **`_webrtc_pub(cam_topic, camera)`**：节奏一致，从对应 buffer 取最新帧 → 调 manager.publish。**任何一帧返回 None 都会触发整个 server stop**（保守策略，宁停勿坏）。

#### 4.14.3 `_clean_up`（L1402–L1424）

```python
self._responser.stop()                                # REP 线程停
for t in self._publisher_threads:                     # 所有 worker 线程
    if t.is_alive(): t.join(timeout=1.0)
self._publisher_threads.clear()
self._zmq_publisher_manager.close()
self._webrtc_publisher_manager.close()
for cam in self._cameras.values():
    if cam: cam.release()
```

#### 4.14.4 公开 API（L1429–L1471）

| 方法 | 作用 |
| --- | --- |
| `start()` | **核心入口**：先起所有 `_update_frames` 线程；如果 isaacsim 模式额外 `time.sleep(2)` 等共享内存就绪；逐个 `wait_until_ready`（普通 5s / IsaacSim 15s 超时）；最后才起 `_zmq_pub` / `_webrtc_pub` 推流线程。 |
| `wait()` | 阻塞当前线程，等到 `_stop_event` 被 set 后调用 `_clean_up`。 |
| `stop()` | 置位 `_stop_event`。 |

**为什么先采集再发布**：让所有相机都有第一帧后才开始推流，避免某些客户端订阅到 `None` 而触发整链 stop。

### 4.15 入口与工具（L1476–L1567）

**`signal_handler(server, signum, frame)`**：用 `functools.partial` 把 server 实例绑进信号回调，调用 `server.stop()`。在 `main` 里注册到 SIGINT/SIGTERM。

**`set_performance_mode(cores=[0,1,2])`**：用 `psutil` 把当前进程及其全部线程的 CPU 亲和性钉到 0/1/2 三核。这与 systemd unit 的 `CPUAffinity=0 1 2` 互相印证；目的是把图像 IO 与 RL 控制器隔离开（典型 Jetson 上把 4-7 核留给控制循环）。

**`run_isaacsim_server()`**：仿真模式入口，没有命令行参数解析，直接读 yaml → 构造 `ImageServer(cam_config, realsense_enable=False, isaacsim_enable=True)` → `server.start()` → return。被 `unitree_sim_isaaclab` 这种外部项目作为库 import。

**`main()`**：

```python
parser = argparse.ArgumentParser()
parser.add_argument('--cf', action='store_true', help='camera find mode')
parser.add_argument('--rs', action='store_true', help='enable RealSense')
parser.add_argument('--no-affinity', action='store_false', dest='affinity')
args = parser.parse_args()

if args.affinity: set_performance_mode(cores=[0,1,2])
if args.cf:
    CameraFinder(realsense_enable=args.rs, verbose=True); exit(0)

with open(CONFIG_PATH) as f: cam_config = yaml.safe_load(f)
server = ImageServer(cam_config, realsense_enable=args.rs)
server.start()
signal.signal(signal.SIGINT,  functools.partial(signal_handler, server))
signal.signal(signal.SIGTERM, functools.partial(signal_handler, server))
server.wait()

time.sleep(0.5)
os.killpg(os.getpgrp(), 9)        # 兜底：USB 拔出导致线程卡死时强杀整个进程组
```

`os.killpg(os.getpgrp(), 9)` 是**最后一记保险**——前面 `_clean_up` 里 UVCCamera.release 故意不调用 stop_streaming（会卡），所以总会有些底层线程在等 USB 应答。SIGKILL 整个进程组是最干净的退出方式。

---

## 5. `image_client.py` 深度拆解

> 注意：尽管文件名叫 client，里面有大量类被 server 复用：`TripleRingBuffer` / `ZMQ_PublisherManager` / `ZMQ_PublisherThread` / `ZMQ_Responser`。

### 5.1 `TripleRingBuffer`（L39–L60）

**全仓库的核心数据结构**，在 server / client 两侧都被复用了多份。

```python
class TripleRingBuffer:
    def __init__(self):
        self.buffer = [None, None, None]
        self.write_index  = 0
        self.latest_index = -1
        self.read_index   = -1
        self.lock = threading.Lock()

    def write(self, data):
        with self.lock:
            self.buffer[self.write_index] = data
            self.latest_index = self.write_index
            self.write_index  = (self.write_index + 1) % 3
            if self.write_index == self.read_index:
                self.write_index = (self.write_index + 1) % 3   # 避开 reader

    def read(self):
        with self.lock:
            if self.latest_index == -1:
                return None
            self.read_index = self.latest_index
        return self.buffer[self.read_index]
```

**不变量**：

- `write_index` 永远不会落到 `read_index` 上 → reader 不会读到正在写的 slot。
- `latest_index` 始终指向最近一次 write 完成的 slot。
- read 操作只持锁 O(1) 时间（仅更新索引），返回 buffer 引用本身——读者拿到的是不可变的 jpeg bytes / ndarray view，写者后续就算覆盖另两个 slot 也不会损坏当前 read。
- 如果还没写过任何数据，`read()` 返回 `None`。

**与队列的对比**（README 4.3 节强调的）：

- 不会阻塞 writer（永远有 slot 可写）。
- reader 不会读到旧帧（永远拿最新）。
- 不会 partial read。

### 5.2 `SimpleFPSMonitor`（L62–L94）

滚动窗口 FPS 计算器：

```python
def __init__(self, window_size: int):
    self._times = deque(maxlen=window_size)
    self._last_tick = None
    self._fps = 0.0

def tick(self):
    now = time.perf_counter_ns()
    if self._last_tick is not None:
        interval_ns = now - self._last_tick
        if interval_ns < 100_000:    # < 0.1 ms 的连续 tick 视为抖动，跳过
            return
        self._times.append(interval_ns)
        if len(self._times) == self._times.maxlen:    # 窗口满了才出数
            rolling_sum = sum(self._times)
            if rolling_sum > 0:
                self._fps = (len(self._times) * 1_000_000_000.0) / rolling_sum
        else:
            self._fps = 0.0
    self._last_tick = now
```

**特点**：

- 用 `perf_counter_ns()` 而非 `time.time()`：单调时钟，不受 NTP 调时干扰。
- 窗口未满时 `fps=0.0`：避免开始几帧产生不可信的尖锐数字。
- 100 µs 抖动过滤：防止某些帧密集回调把 fps 算成爆炸大。

`reset()` 在 SUB 线程一段时间未收到包时被调用——这样客户端能感知到"流断了"。

### 5.3 `ZMQ_PublisherThread`（L98–L192）

**职责**：拥有一个 PUB socket，用 queue 解耦"上层 send 调用"与"socket 实际写入"。

```python
def __init__(self, port, host="0.0.0.0", context=None):
    super().__init__(daemon=True)
    self._context = context
    self._queue = queue.Queue(maxsize=10)
    self._started = threading.Event()

def send(self, data):
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError(...)
    try: self._queue.put_nowait(data)
    except queue.Full:
        logger_mp.warning("queue full, dropping message")
```

**`run`**：

```python
self._socket = self._context.socket(zmq.PUB)
self._socket.setsockopt(zmq.SNDHWM, 1)     # 高水位 1，超过即丢
self._socket.setsockopt(zmq.LINGER, 0)     # close 时不等
self._socket.bind(f"tcp://{self._host}:{self._port}")
self._started.set()
while self._running:
    try:
        data = self._queue.get(timeout=0.1)
        if data is None: break          # sentinel
        self._socket.send(data, zmq.NOBLOCK)
    except queue.Empty:
        continue
    except zmq.Again:
        logger_mp.warning("HWM reached, dropping")
```

**`stop`**：把 `_running` 置 false 并放入 sentinel `None` 来即时唤醒 get。

**特点**：

- `SNDHWM=1` + `NOBLOCK` 双保险——绝不阻塞写者。
- queue.maxsize=10：图像帧偶发 burst 时（比如客户端短暂断流 ZMQ 内部缓冲满）有一点缓冲。
- 上层 send 只接受 bytes 类型，主动拒绝 dict / numpy 输入避免无声错误。

### 5.4 `ZMQ_PublisherManager`（L194–L281）

单例 + 端口路由 + 共享 zmq.Context（同一进程内多 PUB socket 复用一个 context 是 zmq 推荐做法）。

| 方法 | 作用 |
| --- | --- |
| `get_instance()` | 双重检查锁单例。 |
| `_create_publisher_thread(port, host)` | 起线程，等待 `wait_for_start(5s)`，超时即报 `ConnectionError`。 |
| `_get_publisher_thread(port, host)` | 用 `(host, port)` 缓存。 |
| `_close_publisher(key)` | 显式停某个 publisher（实际 close 时不直接调用，由 close 统一）。 |
| `publish(data, port, host)` | 公开 API。 |
| `close()` | 停所有 publisher，清字典。**不 term context**——这与 ZMQ_Responser/Requester 在自己 close 里 term 不同；因为 manager 是单例，进程退出时会自然回收。 |

### 5.5 `TeleImage`（L286–L323）

客户端"一帧"的统一返回类型。**用 `__slots__` 省内存**（视频流场景每秒几十次实例化）。

```python
class TeleImage:
    _NOT_SET = object()              # 哨兵对象，区分 "未启用" vs "失败"
    __slots__ = ['jpg', '_bgr', 'fps']

    def __init__(self, fps, jpg, bgr=_NOT_SET):
        self.fps = fps
        self.jpg = jpg
        self._bgr = bgr

    @property
    def bgr(self):
        if self._bgr is TeleImage._NOT_SET:
            logger_mp.warning("Accessing .bgr but decoding was DISABLED.")
            return None
        if self._bgr is None:
            return None       # 启用了 decode 但本帧失败/没数据
        return self._bgr

    def __bool__(self):
        return bool(self.jpg)

    def __iter__(self):
        yield self.fps
        yield self.jpg
        yield (None if self._bgr is TeleImage._NOT_SET else self._bgr)
```

**三态语义**用了一个非常清爽的设计：

| `self._bgr` | 含义 | 访问 `.bgr` 行为 |
| --- | --- | --- |
| `_NOT_SET`（哨兵单例） | 客户端 `request_bgr=False`，没启用解码 | 返回 None 并 `warning` |
| `None` | 启用解码但本帧无数据 | 返回 None，仅 `debug` |
| `np.ndarray` | 正常 | 返回数组 |

`__bool__` 让 `if image: ...` 可以判断是否有 jpg 数据。`__iter__` 支持解构 `fps, jpg, bgr = image`。

### 5.6 `ZMQ_SubscriberThread`（L326–L469）

#### 状态

```python
self._jpg_3ring_buffer = TripleRingBuffer()
self._fps_monitor = SimpleFPSMonitor(window_size=10)
if request_bgr:
    self._bgr_3ring_buffer = TripleRingBuffer()
    self._bgr_decode_queue = queue.Queue(maxsize=1)
    self._decoder_thread = threading.Thread(target=self._decoder_loop, daemon=True)
    self._decoder_thread.start()
```

**关键架构**：SUB 接到 jpeg bytes 后**总是**写入 jpg buffer；当 `request_bgr=True` 时，再额外起一个 **decoder 线程**异步把 bytes 解成 ndarray 写入 BGR buffer。这样 SUB 接收线程不会被 cv2.imdecode 阻塞，丢帧概率小。

#### `_decoder_loop`（L370–L380）

```python
while self._running:
    try:
        jpg_bytes = self._bgr_decode_queue.get(timeout=0.1)
        if jpg_bytes is None: continue          # 流断时塞的占位 None
        img = self._decode_image(jpg_bytes)
        self._bgr_3ring_buffer.write(img)
    except queue.Empty: continue
```

`_bgr_decode_queue.maxsize=1` + drop-old：永远只解码最新一张图。这是延时优先而非完整性优先。

#### `run`（L410–L469）

```python
self._socket = self._context.socket(zmq.SUB)
self._socket.setsockopt(zmq.RCVHWM, 1)
self._socket.setsockopt(zmq.LINGER, 0)
self._socket.connect(f"tcp://{self._host}:{self._port}")
self._socket.setsockopt_string(zmq.SUBSCRIBE, "")     # 订阅所有 topic
poller = zmq.Poller()
poller.register(self._socket, zmq.POLLIN)
self._started.set()
while self._running:
    events = dict(poller.poll(timeout=100))
    if self._socket in events:
        img_bytes = self._socket.recv()
        self._jpg_3ring_buffer.write(img_bytes)
        if self._request_bgr:
            try:
                if self._bgr_decode_queue.full(): self._bgr_decode_queue.get_nowait()
                self._bgr_decode_queue.put_nowait(img_bytes)
            except queue.Full: pass
        self._fps_monitor.tick()
    else:                                              # 100ms 内没收到任何包
        self._jpg_3ring_buffer.write(None)             # 标记"流断"
        if self._request_bgr:
            ... self._bgr_decode_queue.put_nowait(None)
        self._fps_monitor.reset()                       # FPS 立刻归零
```

**断流处理**很妙——主动写入 None 让 reader（`recv` → `TeleImage`）能及时知晓画面停了，并把 fps 重置。

#### 公开 API

- `recv()`：返回 `TeleImage(fps, jpg, bgr)`。无锁——TripleRingBuffer 自带锁。
- `stop()`：把 `_running=False` 然后 `join(1s)`。

### 5.7 `ZMQ_SubscriberManager`（L471–L539）

与 publisher manager 同构，也是单例 + `(host, port)` 缓存。`subscribe()` 是公开 API：

```python
def subscribe(self, host, port, request_bgr=False) -> TeleImage:
    sub = self._get_subscriber_thread(host, port, request_bgr)
    return sub.recv()
```

`request_bgr` 在第一次 `subscribe(host, port, ...)` 调用时被记入新创建的 `ZMQ_SubscriberThread`；**后续同一 (host, port) 的 subscribe 调用复用旧 thread，request_bgr 参数实际被忽略**。这意味着如果客户端代码先以 `request_bgr=False` 订阅了某端口，再用 `request_bgr=True` 订阅，第二次拿不到 BGR。`ImageClient` 由于在构造时统一传同一个 `request_bgr`，不会踩这个坑。

### 5.8 `ZMQ_Responser`（L544–L597）

**角色**：server 端的 cam_config 应答服务。bind 在固定 60000 端口。

```python
def __init__(self, cam_config, host="0.0.0.0", port=60000):
    self._cam_config = cam_config
    self._socket = self._context.socket(zmq.REP)
    self._socket.bind(f"tcp://{host}:{port}")
    self._thread = threading.Thread(target=self._run, daemon=True)
    self._thread.start()
```

**`_run`** 是个死循环 poll 200ms：

```python
while self._running:
    socks = dict(poller.poll(timeout=200))
    if self._socket in socks:
        _ = self._socket.recv()              # 不关心请求内容
        self._socket.send_json(self._cam_config)
```

任何请求都得到完整的 cam_config（dict 结构）作为响应，自动序列化为 JSON。

`stop()` 关 socket、term context。

### 5.9 `ZMQ_Requester`（L602–L671）

**客户端 cam_config 拉取器**，**带本地兜底文件**。

```python
def __init__(self, host, port):
    self._socket = self._context.socket(zmq.REQ)
    self._socket.setsockopt(zmq.LINGER, 0)
    self._socket.connect(f"tcp://{host}:{port}")
    self._poller = zmq.Poller()
    self._poller.register(self._socket, zmq.POLLIN)
    self._config_client_path = ".../cam_config_client.yaml"   # 本地缓存
    self._config_server_path = ".../cam_config_server.yaml"   # 仓库自带
```

**`request()`**：

```python
self._socket.send(b"GET_DATA")
socks = dict(self._poller.poll(timeout=1000))
if self._socket in socks:
    cam_config = self._socket.recv_json()
    with open(self._config_client_path, "w") as f:
        yaml.safe_dump(cam_config, f, sort_keys=False, allow_unicode=True)
else:
    # 1s 超时，回落本地：
    if os.path.exists(self._config_client_path):
        cam_config = yaml.safe_load(...)
    elif os.path.exists(self._config_server_path):
        cam_config = yaml.safe_load(...)
    else:
        logger_mp.error("No camera configuration file found locally.")
return cam_config
```

**三层回退**：服务器响应 → `cam_config_client.yaml`（上次成功后写的本地缓存）→ `cam_config_server.yaml`（仓库自带样例）→ None。让客户端在网络抖动时也能用一个旧配置撑住。

### 5.10 `ImageClient`（L677–L726）

**顶层用户 API**：

```python
def __init__(self, host="192.168.123.164", request_port=60000, request_bgr=False):
    self._subscriber_manager = ZMQ_SubscriberManager.get_instance()
    self._requester = ZMQ_Requester(host, request_port)
    self._cam_config = self._requester.request()
    if self._cam_config is None:
        raise RuntimeError("Failed to get camera configuration.")

    if self._cam_config['head_camera']['enable_zmq']:
        self._subscriber_manager.subscribe(host, self._cam_config['head_camera']['zmq_port'], request_bgr)
    if self._cam_config['left_wrist_camera']['enable_zmq']:
        self._subscriber_manager.subscribe(host, ...)
    if self._cam_config['right_wrist_camera']['enable_zmq']:
        self._subscriber_manager.subscribe(host, ...)
```

构造时**预先订阅**三个端口——这样后续 `get_*_frame` 不会触发首次连接的延时。

**公开方法**：

| 方法 | 作用 |
| --- | --- |
| `get_cam_config()` | 返回 dict。 |
| `get_head_frame()` / `get_left_wrist_frame()` / `get_right_wrist_frame()` | 调 `subscriber_manager.subscribe(host, zmq_port, request_bgr)`，返回 `TeleImage`。本质是从 `(host, port)` 对应的 `ZMQ_SubscriberThread.recv()` 读最新一帧。 |
| `close()` | 关闭整个 manager。 |

### 5.11 `main()`（L728–L770）

`teleimager-client` 命令行入口：

```python
parser.add_argument('--host', type=str, default='192.168.123.164')
client = ImageClient(host=args.host, request_bgr=True)
cam_config = client.get_cam_config()
while True:
    if cam_config['head_camera']['enable_zmq']:
        head_img = client.get_head_frame()
        if head_img.bgr is not None:
            cv2.imshow("Head Camera", head_img.bgr)
    if cam_config['left_wrist_camera']['enable_zmq']:
        left = client.get_left_wrist_frame()
        if left.bgr is not None: cv2.imshow("Left Wrist Camera", left.bgr)
    if cam_config['right_wrist_camera']['enable_zmq']:
        right = client.get_right_wrist_frame()
        if right.bgr is not None: cv2.imshow("Right Wrist Camera", right.bgr)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        client.close(); cv2.destroyAllWindows(); break
    time.sleep(0.002)
```

`request_bgr=True` 是必须的——`cv2.imshow` 必须传 ndarray。`time.sleep(0.002)` 防 CPU 100%，同时还能保持 ~500 fps 的 GUI 刷新上限。

---

## 6. 启动脚本

### 6.1 `setup_uvc.sh`

四步搞定 UVC 权限：

```bash
# 1. udev 规则：USB device 自动归属 video 组
echo 'SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_device", GROUP="video", MODE="0664"' \
  | sudo tee /etc/udev/rules.d/10-libuvc.rules > /dev/null
sudo udevadm trigger

# 2. 当前用户加入 video 组（重新登录后生效）
sudo usermod -a -G video $USER

# 3. 给 modprobe -r/+ uvcvideo 配置免密 sudo
echo "ALL ALL=(ALL) NOPASSWD: $(which modprobe) -r uvcvideo, $(which modprobe) uvcvideo debug=*" \
  | sudo tee /etc/sudoers.d/uvc_modprobe > /dev/null
sudo chmod 0440 /etc/sudoers.d/uvc_modprobe

# 4. 立即重载驱动
sudo modprobe -r uvcvideo
sudo modprobe uvcvideo debug=0
```

第 3 步是 `image_server.py` 启动时调用 `reload_uvc_driver()` 不被 sudo 密码挡住的关键——精确白名单了两条 modprobe 命令，安全性比 NOPASSWD ALL 好得多。

### 6.2 `setup_autostart.sh`

7 步把 server 注册成 systemd 服务：

| 步 | 做什么 |
| --- | --- |
| 0 | 探测脚本所在目录 `SCRIPT_DIR`，确保 `$SCRIPT_DIR/src` 存在。 |
| 1 | 自动检测 conda 安装路径：先 `which conda`，如果路径含 `/envs/` 则去掉后半，否则向上两层。检测不到则交互询问。 |
| 2 | 决定要用的 conda 环境。优先复用当前激活的 `$CONDA_DEFAULT_ENV`（询问确认），否则交互询问。然后 `conda env list` 验证存在。 |
| 3 | `conda activate` 该环境，确认 `teleimager-server` 命令可用。 |
| 4 | 询问是否使用 RealSense（`y/Y` 即追加 `--rs`）。 |
| 5 | 写 `/etc/systemd/system/teleimager.service`：见下文 unit 内容。 |
| 6 | `systemctl daemon-reload && enable && restart`，最后打印 status 与运维命令。 |

写出的 unit 文件内容：

```ini
[Unit]
Description=Teleimager Image Server
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$SCRIPT_DIR
CPUAffinity=0 1 2
ExecStart=/bin/bash -lc "source $CONDA_PATH/etc/profile.d/conda.sh && conda activate $CONDA_ENV && teleimager-server $USE_RS"
Restart=always
RestartSec=5
Environment="PATH=$CONDA_PATH/bin:/usr/local/sbin:..."
Environment="PYTHONPATH=$SCRIPT_DIR/src"
Environment="XR_TELEOP_CERT=/home/unitree/.config/xr_teleoperate/cert.pem"
Environment="XR_TELEOP_KEY=/home/unitree/.config/xr_teleoperate/key.pem"
StandardOutput=journal+console
StandardError=journal+console

[Install]
WantedBy=multi-user.target
```

**关键点**：

- `User=root`：因为需要重载 uvcvideo 内核模块。
- `CPUAffinity=0 1 2`：与 `set_performance_mode` 冗余但更早生效（系统层面）。
- `Restart=always` + `RestartSec=5`：相机插拔 / 网络抖动导致 crash 时自动恢复。
- 强制写入 `XR_TELEOP_CERT/KEY` 指向 `/home/unitree/.config/xr_teleoperate/`——这要求该用户存在且证书已 `cp` 进去。换用户名时这两行需要改。

---

## 7. 打包与命令行入口（`pyproject.toml`）

```toml
[project]
name = "teleimager"
version = "1.5.0"
requires-python = ">=3.8,<3.12"
dependencies = ["logging_mp", "opencv-python", "numpy>=1.21,<2", "pyyaml", "pyzmq"]

[project.optional-dependencies]
server = ["aiohttp", "aiortc", "pupil-labs-uvc"]

[tool.setuptools]
package-dir = {"" = "src"}
[tool.setuptools.packages.find]
where = ["src"]

[project.scripts]
teleimager-server = "teleimager.image_server:main"
teleimager-client = "teleimager.image_client:main"
```

**重点**：

- **`[server]` 可选 extra**：客户端机器（开发者笔记本）只需 `pip install -e .`；机器人主控才需要 `pip install -e ".[server]"` 拉 `aiohttp` / `aiortc` / `pupil-labs-uvc` 这些重依赖。
- **`numpy>=1.21,<2`**：明确避开 numpy 2.0+ 的 ABI 破坏。
- 生成两个 console_scripts：`teleimager-server` 与 `teleimager-client`，分别对应 `image_server.py:main()` 与 `image_client.py:main()`。

---

## 8. 关键设计点回顾

### 8.1 Triple Ring Buffer（双向解耦）

每路相机维护**两个独立**的 TripleRingBuffer：jpg buffer 给 ZMQ，BGR buffer 给 WebRTC。同时客户端 SUB 内部也用了两个 buffer：jpg 来自网络、BGR 来自异步解码线程。

整个链路里出现 buffer 的位置：

| 位置 | 内容 | 写者 | 读者 |
| --- | --- | --- | --- |
| `BaseCamera._zmq_buffer` | jpeg bytes | `_update_frames` 线程 | `_zmq_pub` 线程 |
| `BaseCamera._webrtc_buffer` | BGR ndarray | `_update_frames` 线程 | `_webrtc_pub` 线程 |
| `ZMQ_SubscriberThread._jpg_3ring_buffer` | jpeg bytes | SUB 线程 | `recv()` 调用方 |
| `ZMQ_SubscriberThread._bgr_3ring_buffer` | BGR ndarray | `_decoder_loop` 线程 | `recv()` 调用方 |

**收益**：

- 任何一个消费者卡顿都不阻塞生产；生产者永远拿最新槽。
- 加锁开销小：只在更新索引时持锁，纳秒级。

### 8.2 三种相机标识符

`physical_path > serial_number > video_id` 的优先级 + "一旦设了高优先级就不回落"是有意为之的——避免低优先级误命中导致左右手相机串号。给低成本摄像头（厂家共用一个 sn）部署时，**只能用 physical_path**。

### 8.3 三种传输方式

| 方式 | 用途 | 延时 | 编码 |
| --- | --- | --- | --- |
| ZMQ PUB-SUB | LAN 内高画质图像（数据采集、模型训练） | 几十 ms | 直接送 jpeg bytes，不重编 |
| WebRTC | VR 头显 / 浏览器低延时观感 | < 100 ms | H.264 (libx264 软编 ultrafast/zerolatency) |
| 共享内存 | 同机零拷贝 | μs 级 | TODO（README 1.0 标注） |

### 8.4 单例 + 端口路由 Manager

`ZMQ_PublisherManager` / `ZMQ_SubscriberManager` / `WebRTC_PublisherManager` 三者都是同一套模式：

- 进程级单例（避免重复 zmq.Context）。
- 用 `(host, port)` 做 key 缓存底层 thread。
- 公开 `publish` / `subscribe` 接口直接拿 host+port 即可，不暴露 thread 创建细节。

这套抽象使得 `BaseCamera` 不需要持有自己的 publisher 实例；只把 `(zmq_port, webrtc_port)` 信息暴露出来，由 server 顶层的 manager 按需路由。

### 8.5 协作式优雅退出

| 触发源 | 流程 |
| --- | --- |
| `Ctrl+C` (SIGINT) | `signal_handler` → `server.stop()` → `_stop_event.set()` → 工作线程退 → `server.wait()` 返回 → `_clean_up()` |
| 任何 worker 异常 | 线程内 `_stop_event.set()` → 同上 |
| systemd `stop` (SIGTERM) | 同 SIGINT |
| USB 拔出导致线程卡死 | `time.sleep(0.5)` + `os.killpg(SIGKILL)` 兜底 |

---

## 9. 与 `xr_teleoperate` 的协作关系

虽然 teleimager 是独立 pip 包，但它的设计目标就是为 [`xr_teleoperate`](https://github.com/unitreerobotics/xr_teleoperate) 提供视频流：

```
┌──────────────────── 机器人主控 (Jetson Orin NX) ─────────────────┐
│  teleimager-server (systemd auto-start)                        │
│   ├── REP :60000  ── cam_config                                │
│   ├── PUB :55555  ── head_camera   jpeg                        │
│   ├── PUB :55556  ── left_wrist    jpeg                        │
│   ├── PUB :55557  ── right_wrist   jpeg                        │
│   ├── HTTPS :60001 ── head WebRTC (h264)                       │
│   ├── HTTPS :60002 ── left WebRTC                              │
│   └── HTTPS :60003 ── right WebRTC                             │
└─────────────────────────────────────────────────────────────────┘
                            │
            ┌───────────────┼────────────────┐
            ▼               ▼                ▼
   xr_teleoperate     teleimager-client     VR 头显 / 浏览器
   (操作员主机)       (调试可视化)          https://<ip>:60001
   ImageClient(host=...) → cv2.imshow
```

- `xr_teleoperate` 用 `ImageClient` 拉 jpeg + 解码后的 BGR，喂给手势识别 / 数据录制管线。
- 调试时直接 `teleimager-client --host <ip>` 起三个 OpenCV 窗口。
- VR 头显走 WebRTC 路径，硬件解码 H.264，延时最低。

证书目录 `~/.config/xr_teleoperate/` 暗示了两者约定共用 PEM。

---

## 10. 典型使用流程速查

### 10.1 在新机器人主控上首次部署

```bash
# 1. 装 conda 并创建 env
conda create -n teleimager python=3.10 -y && conda activate teleimager

# 2. 装系统依赖
sudo apt install -y libusb-1.0-0-dev libturbojpeg-dev

# 3. 拉仓库 + 装 server 模式
git clone https://github.com/unitreerobotics/teleimager.git
cd teleimager
pip install -e ".[server]"

# 4. 配权限
bash setup_uvc.sh        # 加组、udev、免密 modprobe
# logout / login 让 video 组生效

# 5. 放证书
mkdir -p ~/.config/xr_teleoperate/
cp <televuer 生成的> cert.pem key.pem ~/.config/xr_teleoperate/

# 6. 发现相机
teleimager-server --cf
# 抄写输出里的 video_id / serial_number / physical_path 到 cam_config_server.yaml

# 7. 试跑
teleimager-server         # 普通启动
teleimager-server --rs    # 含 RealSense

# 8. 注册自启动
bash setup_autostart.sh   # 走交互
```

### 10.2 在客户端机器开发

```bash
conda activate teleimager
pip install -e .                  # 不需要 server extra
teleimager-client --host 192.168.123.164
# 或浏览器打开 https://192.168.123.164:60001
```

### 10.3 程序化使用 client API

```python
from teleimager.image_client import ImageClient
client = ImageClient(host="192.168.123.164", request_bgr=True)
cfg = client.get_cam_config()

while True:
    head = client.get_head_frame()
    if head.bgr is not None:
        process(head.bgr, fps=head.fps)        # numpy ndarray，HxWx3
    # head.jpg 是 jpeg bytes，可以直接落盘 .jpg 做数据采集
client.close()
```

### 10.4 程序化使用 server API（仿真模式）

```python
from teleimager.image_server import run_isaacsim_server, ImageServer
import yaml
with open("cam_config_server.yaml") as f: cfg = yaml.safe_load(f)
server = ImageServer(cfg, realsense_enable=False, isaacsim_enable=True)
server.start()
try: server.wait()
except KeyboardInterrupt: server.stop()
```

### 10.5 故障排查速查

| 现象 | 可能原因 | 处置 |
| --- | --- | --- |
| `--cf` 输出里 sn / extra_info 大量 unknown | 当前用户没访问 USB metadata 的权限 | `sudo $(which teleimager-server) --cf` |
| `teleimager-server` 启动后某相机 ready timeout | yaml 里写的 `(physical_path/serial_number/video_id)` 实际不存在 | 重新跑 `--cf`，改 yaml |
| WebRTC 网页 `Start` 后视频不动 | aiortc 的 H264 decode 在浏览器侧失败 | yaml 里把 `webrtc_codec` 改 `vp8` 试试 |
| `Cannot find UVCCamera ... with serial number` | 相机厂商共用 sn 或 sn 里有空白 | 用 `physical_path` 取代 |
| systemd 服务起不来但手工跑可以 | unit 里写死的 `XR_TELEOP_CERT/KEY=/home/unitree/...` 用户名不对 | 编辑 `/etc/systemd/system/teleimager.service` |
| 退出后 `python` 进程还在 | UVCCamera 卡 release，等 `os.killpg` 收 | 不影响下次启动 |

---

## 附：完整模块/类/方法索引

为了方便日后翻查，最后列一份"哪个东西在哪一行"的速查表。

### `image_server.py`

| 名称 | 行 | 角色 |
| --- | --- | --- |
| `CONFIG_PATH` / cert paths | 47–70 | 模块常量 |
| `jetson_software_encode_frame` | 75–115 | monkey-patch aiortc h264 |
| `INDEX_HTML` / `CLIENT_JS` | 120–245 | WebRTC 前端 |
| `BGRArrayVideoStreamTrack` | 250–304 | aiortc Track |
| `WebRTC_PublisherThread` | 307–477 | 单端口 WebRTC 线程 |
| `WebRTC_PublisherManager` | 483–531 | WebRTC 单例管理器 |
| `reload_uvc_driver` | 536–544 | 内核驱动重载 |
| `CameraFinder` | 549–824 | 相机发现 |
| `CameraFinder.__init__` | 558–601 | 构造 + 索引 |
| `CameraFinder._list_*` 系列 | 604–689 | 私有发现工具 |
| `CameraFinder.is_*_exist` / `get_*_by_*` | 724–784 | 公开 API |
| `CameraFinder.info` | 787–824 | 漂亮打印 |
| `BaseCamera` | 826–899 | 相机基类 |
| `RealSenseCamera` | 901–998 | RealSense 实现 |
| `UVCCamera` | 1000–1062 | pyuvc 实现 |
| `OpenCVCamera` | 1064–1115 | V4L2 通用实现 |
| `IsaacSimCamera` | 1117–1198 | 仿真共享内存 |
| `ImageServer` | 1202–1471 | 顶层编排 |
| `ImageServer.__init__` | 1203–1330 | 解析 + 实例化相机 |
| `ImageServer._update_frames` / `_zmq_pub` / `_webrtc_pub` | 1332–1400 | 三个工作线程函数 |
| `ImageServer._clean_up` | 1402–1424 | 资源回收 |
| `ImageServer.start` / `wait` / `stop` | 1429–1471 | 公开 API |
| `signal_handler` / `set_performance_mode` | 1476–1492 | 工具 |
| `run_isaacsim_server` | 1494–1505 | 仿真入口 |
| `main` | 1507–1564 | CLI 主入口 |

### `image_client.py`

| 名称 | 行 | 角色 |
| --- | --- | --- |
| `TripleRingBuffer` | 39–60 | 三槽环形缓冲 |
| `SimpleFPSMonitor` | 62–94 | 滚动窗口 FPS |
| `ZMQ_PublisherThread` | 98–192 | PUB 线程 |
| `ZMQ_PublisherManager` | 194–281 | PUB 单例管理器 |
| `TeleImage` | 286–323 | 客户端帧数据类 |
| `ZMQ_SubscriberThread` | 326–469 | SUB + 解码线程 |
| `ZMQ_SubscriberManager` | 471–539 | SUB 单例管理器 |
| `ZMQ_Responser` | 544–597 | REP cam_config 服务 |
| `ZMQ_Requester` | 602–671 | REQ + 本地兜底 |
| `ImageClient` | 677–726 | 顶层用户 API |
| `main` | 728–770 | `teleimager-client` CLI |

---

> **写作约定回顾**：本文档采用了 README 4.x 节中的设计语言（"Triple Ring Buffer"、"三种相机标识符"、"三种传输方式"），并为每个类都配了"职责 + 关键属性 + 关键方法 + 与谁交互"的统一格式。读完一遍后，建议再回去对照 `image_server.py` / `image_client.py` 两份源码扫一遍——本文档里出现的所有行号、类名、方法名都和源码 1:1 对应，可以作为 IDE 跳转的参考。
