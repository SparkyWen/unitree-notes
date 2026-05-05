# Unitree G1 — Slow Brain + Fast Reflex + Safe Skill 设计稿（g1_brain）

**版本**：v1.0
**日期**：2026-05-05
**作者**：Helios + Claude
**目标**：在 MuJoCo 仿真上把 Slow Brain（VLM/Realtime）+ Fast Reflex（本地 CV 感知）+ Safe Skill（安全监督 + 技能服务器）三层完整跑通；架构同时为未来真机部署预留接口。
**参考**：
- `docs/vlm_audio_mock_deep.md`（架构总纲）
- `va-demo/`（已完成的 Slow Brain 雏形 + 部分 Safe Skill）
- `g1_sim_demo/`（已完成的 Skill 底层：ComboController + 19 个 keyframe 动作 + 低层 PD）

---

## 0. 一句话概括

新建一个独立顶层包 `g1_brain/`，**import 而不重写** va-demo 的 Realtime/VAD/wake-word 链路和 g1_sim_demo 的 ComboController/keyframe 动作，在它们之上加 4 个新子系统：

1. **Perception**：双相机（USB 看人 + MuJoCo 头摄看场景）+ YOLO11 + MediaPipe-Pose + DepthAnythingV2 + MuJoCo native depth；输出 `SceneState`。
2. **Safety**：升级版 SafetySupervisor + 7-状态 FSM + 独立进程 E-stop + watchdog 套娃；所有下行命令必须经过它。
3. **Skills**：把 va-demo 的 6 个工具扩到 ~16 个，把 g1_sim_keyboard 的 11 个静态 keyframe 动作和 LocoClient 高层动作全部封装成 named skill。
4. **Mock Imitation**：手势检测 → 安全过滤 → 调用对应 skill（笔记 §10.1 的 Phase 5 语义模仿）。

跑通后 Phase 0–5 全覆盖，Phase 6（XR + LeRobot）和 Phase 7（GMR + RL tracking）作为 future work 在 §11 勾勒。

---

## 1. 总体架构

### 1.1 三层心智模型

```
┌────────────────────────────────────────────────────────────────────┐
│                       USER (语音 / 键盘 / 手柄)                     │
└────────────────────────────────────────────────────────────────────┘
                                ↕
┌────────────────────────────────────────────────────────────────────┐
│  SLOW BRAIN  (g1_brain/brain/)              0.2 - 2 Hz             │
│  - OpenAI Realtime (gpt-realtime, 复用 va-demo)                     │
│  - GPT-5.5 Vision via describe_scene tool                           │
│  - tool_calls → 高层意图 / L1+L2 skill                              │
└────────────────────────────────────────────────────────────────────┘
                                ↕            (intent JSON)
┌────────────────────────────────────────────────────────────────────┐
│  SAFE SKILL  (g1_brain/safety/ + g1_brain/skills/)                  │
│  - SafetySupervisor: FSM + whitelist + bounds + watchdog + E-stop  │
│  - SkillServer: L1/L2 → ComboController / Keyframe / Loco          │
└────────────────────────────────────────────────────────────────────┘
                                ↕            (skill call)
┌────────────────────────────────────────────────────────────────────┐
│  FAST REFLEX  (g1_brain/perception/ + scene_state/)   5-30 Hz      │
│  - 双相机：USB(用户视角) + MuJoCo头摄(机器人视角)                    │
│  - YOLO11 (人/物) + MediaPipe-Pose (手势) + Depth                  │
│  - 融合成 SceneState (clear_path / nearest_obstacle / persons / …) │
│  - Safety 在每个 motion skill 执行前必须读最新 SceneState           │
└────────────────────────────────────────────────────────────────────┘
                                ↕            (lowcmd / lowstate)
┌────────────────────────────────────────────────────────────────────┐
│  RUNTIME  (复用 g1_sim_demo)         50 / 500 / 1000 Hz            │
│  - ComboController (RL 50Hz + 安全包络内手势)                       │
│  - Keyframe player (g1_sim_keyboard 那 19 个静态 pose)              │
│  - 真机切换：LocoClient / G1ArmActionClient (高层) 替代之            │
└────────────────────────────────────────────────────────────────────┘
                                ↕     DDS (domain 1 lo / domain 0 真机)
┌────────────────────────────────────────────────────────────────────┐
│  unitree_mujoco simulate_python   <or>   真机 G1 PC2                │
└────────────────────────────────────────────────────────────────────┘
```

### 1.2 控制频率严格分层

| 层 | 频率 | 谁负责 | 谁绝对不能进 |
|---|---:|---|---|
| 电机 PD 控制 | 1000 Hz | MuJoCo 物理 / 真机 motor controller | LLM、Python 任何代码 |
| ComboController RL tick | 50 Hz | `ComboController._tick`（已有） | LLM、Brain |
| Keyframe player | 500 Hz | `g1_sim_keyboard.G1Controller`（已有） | LLM |
| SafetySupervisor watchdog | 20 Hz | `safety/watchdog.py` | LLM |
| Perception RGB / 深度 | 10–30 Hz | `perception/cameras.py` + `perception/depth.py` | LLM |
| YOLO 检测 | 10–20 Hz | `perception/object_detector.py` | LLM |
| MediaPipe-Pose | 10–30 Hz | `perception/pose_detector.py` | LLM |
| SceneState 融合广播 | 10 Hz | `scene_state/fusion.py` | LLM |
| Brain（VLM 描述场景） | 0.5–2 Hz on demand | Realtime tool call | LLM 自己 |
| Brain（Realtime 对话） | 流式 | OpenAI gpt-realtime | LLM 自己 |
| E-stop 监听器 | 50 Hz polling | `safety/estop_listener.py`（独立进程） | 谁都不能 bypass |

**核心不变量**：

- 任何下行命令（VLM → Skill → Runtime）都必须经过 `SafetySupervisor.validate()` 同步调用；`validate()` 内部读 `SceneState.snapshot()` + `RobotState.snapshot()`。
- LLM 永远不直接看到 lowstate / motor 数据。
- LLM 永远不能输出 L3（关节角 / lowcmd）；只能输出 L1（高层意图）和 L2（参数化技能）。
- E-stop 进程独立，主进程死锁时 E-stop 仍能向 DDS 推 zero-torque lowcmd。

### 1.3 进程模型

**单主进程 + asyncio + 后台线程 + 1 个独立 E-stop 进程**。

理由：
- va-demo 已经用 asyncio 主循环 + Camera/MicStream/SpeakerStream/ComboController 各自后台线程跑通，新加 perception 只需再加 2-3 个后台线程
- 不引入 ROS2 / ZMQ 进程拆分（Phase 6+ 真机部署再考虑）
- E-stop 必须独立进程，主进程任何卡死/异常都不能让它失效

### 1.4 与 va-demo / g1_sim_demo 的关系

| 文件 / 模块 | g1_brain 怎么用 |
|---|---|
| `va_demo.realtime_agent.RealtimeAgent` | **import + 子类化**，扩展 tool 集 |
| `va_demo.audio_io` (MicStream/SpeakerStream) | **直接 import**，零修改 |
| `va_demo.wake_word`、`utterance_vad`、`conversation_state` | **直接 import**，零修改 |
| `va_demo.tts.TTSClient`、`vision.VisionClient` | **直接 import**，零修改 |
| `va_demo.camera.Camera`（USB / teleimager） | **直接 import**，作为 USB 相机源 |
| `va_demo.safety` | **不用**，写新版（向后兼容老接口供 va-demo 单独用） |
| `va_demo.skills.SkillBackend` | **不用**，写新版扩展 skill 集 |
| `va_demo.prompts` | **不用**，写新版 prompt（包含 SceneState 注入） |
| `g1_sim_demo.g1_sim_rl_combo.ComboController` | **直接 import**，作为运动后端 |
| `g1_sim_demo.g1_sim_rl_combo.build_arm_actions` | **直接 import**，8 个手势 |
| `g1_sim_demo.g1_sim_keyboard` 的 11 个静态 pose | **import 函数**：`wave_left_pose`, `t_pose_pose`, `bow_pose`, …；包装成 KeyframeSkill |

**重要约束**：g1_brain 不修改 va-demo 和 g1_sim_demo 的任何文件。如果发现需要修改，说明边界没划好，要么改 g1_brain 自己适配，要么写一个 thin wrapper。

---

## 2. Perception 层（Fast Reflex）

### 2.1 双相机源

```
┌─────────────────────────────────┐         ┌──────────────────────────────────┐
│  USB Camera                     │         │  MuJoCo Head Camera              │
│  src: teleimager (走真机)       │         │  src: mujoco.Renderer offscreen │
│       OR cv2.VideoCapture(0)    │         │  从 g1.xml 里 <camera> 标签拉    │
│                                 │         │  RGB + 原生 depth (米单位)       │
│  用途: 看人(对话/gesture mirror)│         │  用途: G1 第一视角(地形/障碍)   │
│  采样: 20 Hz 后台线程           │         │  采样: 20 Hz 后台线程           │
└────────────┬────────────────────┘         └──────────────┬───────────────────┘
             │                                              │
             │ BGR ndarray + ts                             │ BGR + depth(meters)
             ▼                                              ▼
       ┌──────────────────────────────────────────────────────────┐
       │  perception/cameras.py: CameraHub                        │
       │  - latest_usb_bgr() / latest_usb_jpeg_b64()              │
       │  - latest_head_bgr() / latest_head_depth() / _jpeg_b64() │
       │  - frame_age_seconds(source)                             │
       └──────────────────────────────────────────────────────────┘
```

#### 2.1.1 USB 相机（用户视角）

直接复用 `va_demo.camera.Camera`，零修改。优点：daemon 后台 20Hz 拉帧、watchdog 兼容、jpeg b64 已实现。

#### 2.1.2 MuJoCo 头部相机（机器人视角）

新写 `g1_brain/perception/mujoco_head_cam.py`。关键技术：
- 使用 `mujoco.Renderer` 离屏渲染，不影响 viewer 的可视化
- 从 G1 MJCF（`unitree_mujoco/unitree_robots/g1/scene_29dof.xml`）中查找 `<camera>` 元素；G1 在 `g1_29dof.xml` 中预定义了 `head_camera` 节点
- 每帧渲染 RGB（ndarray uint8）和 depth（ndarray float32 米单位）
- 通过 DDS Subscriber 监听 `rt/lowstate` 拿到机器人当前姿态，把 mj_data.qpos / qvel 同步到一个独立的 mjModel 副本以便渲染（unitree_mujoco 的 simulate_python 已经在跑物理，我们 fork 出一个只读的 mjData 用来渲染）
- 渲染分辨率默认 640×480（深度太大会拖性能，太小损失语义）
- GPU 渲染：用 `MUJOCO_GL=glfw`（你的 4060 + WSL2 D3D12 已经验证可行）

实现细节：
```python
class MuJoCoHeadCamera:
    def __init__(self, mjcf_path: str, camera_name: str = "head_camera",
                 width: int = 640, height: int = 480, poll_hz: float = 20.0):
        self.model = mujoco.MjModel.from_xml_path(mjcf_path)
        self.data = mujoco.MjData(self.model)
        self.renderer = mujoco.Renderer(self.model, height=height, width=width)
        self.cam_id = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_CAMERA, camera_name)
        # 后台线程订阅 rt/lowstate 同步 qpos
        self._sub = ChannelSubscriber("rt/lowstate", LowState_)
        self._sub.Init(self._on_lowstate, 10)
        # 后台渲染线程
        threading.Thread(target=self._render_loop, daemon=True).start()
```

**真机迁移**：在真机上 `MuJoCoHeadCamera` 替换为 `RealSenseCamera`（D435i / G1 EDU 自带前置相机），接口（`latest_bgr()`、`latest_depth()`）保持一致。

### 2.2 模型选型与下载方案

#### 2.2.1 物体 / 人检测：YOLO11

- **首选**：`ultralytics` 包的 YOLO11s（22M 参数，COCO 80 类，4060 上 60+ FPS）
- **下载**：`pip install ultralytics`，首次 `YOLO("yolo11s.pt")` 自动从 GitHub Release 拉模型权重（~22 MB）；离线也可手动从 https://github.com/ultralytics/assets/releases 下载放 `~/.config/Ultralytics/`
- **更轻量**：YOLO11n（5M 参数，CPU 上 15+ FPS）；CPU 降级时用
- **更准确**：YOLO11m（39M）；4060 跑得动但 30 FPS 够用了，默认 s 即可

#### 2.2.2 人体姿态 / 手势：MediaPipe-Pose

- **首选**：`mediapipe` 官方 Python 包 BlazePose（33 个 landmark）
- **下载**：`pip install mediapipe`；模型权重打包在 wheel 内，不用单独下载
- **替代**：YOLO11-Pose（如果想统一框架）；MMPose（更准确但部署重）；RTMPose（速度准确兼顾，但要装 mmcv 较麻烦）
- **推荐 MediaPipe 的原因**：
  - 单文件 import，无 mmcv / cuda 编译问题
  - 已经支持 holistic（含手部 21 landmark），未来做手势精细识别可平滑升级
  - 4060 / CPU 都能跑，CPU 已能 30+ FPS

#### 2.2.3 单目深度：DepthAnythingV2

- **用途**：仅用于"未来真机时若 RealSense 故障则降级"和"想验证 sim2real 时不用 ground-truth 深度"。仿真阶段默认走 MuJoCo native depth（白嫖 ground truth）。
- **首选**：DepthAnythingV2-Small（~25M 参数，4060 上 15+ FPS，metric depth 版本）
- **下载**：
  ```python
  # 首次会从 HuggingFace 自动下载 (~100 MB)
  from transformers import pipeline
  depth_est = pipeline("depth-estimation",
                        model="depth-anything/Depth-Anything-V2-Small-hf",
                        device="cuda:0")
  ```
- **离线**：`huggingface-cli download depth-anything/Depth-Anything-V2-Small-hf`，配 `HF_HOME`
- **首版默认关闭**（`perception.mono_depth.enabled: false`），仿真用 MuJoCo native；想测时改 yaml 即可

#### 2.2.4 视觉描述（VLM）

- 复用 va-demo：OpenAI GPT-5.5 via Responses API（`vision.VisionClient.describe()`）
- 开源替代（可选，未来真机本地部署时考虑）：Qwen2.5-VL-7B（apache-2.0，4060 不够，需 24GB GPU），LLaVA-OneVision，CogVLM2 — 这些**不在本版范围**，仅在 §11 future work 列出

#### 2.2.5 语音识别 / 合成（已就位，无需新增）

复用 va-demo：
- ASR: `gpt-4o-transcribe`（cloud）或 `faster-whisper-tiny`（local fallback）
- TTS: `gpt-4o-mini-tts`（cloud）+ Realtime API 自带语音输出
- Wake word: 已实现的 "Hi Sparky" 流水线

### 2.3 SceneState 数据契约

`g1_brain/scene_state/types.py`:

```python
from dataclasses import dataclass, field
from typing import Optional
import numpy as np

@dataclass
class Detection:
    class_name: str          # "person" / "chair" / "bottle" / ...
    bbox_xyxy: tuple          # (x1, y1, x2, y2) in image pixels
    score: float              # 0..1
    distance_m: Optional[float]  # None if no depth
    bearing_deg: Optional[float] # 相对相机光轴的水平角，左负右正
    pitch_deg: Optional[float]   # 上正下负

@dataclass
class HumanPose:
    """MediaPipe 33 landmark + 派生手势标签"""
    landmarks_xy: np.ndarray  # (33, 2) 归一化 [0,1] 图像坐标
    landmarks_z: np.ndarray   # (33,) 相对 hip 深度（MediaPipe 提供）
    visibility: np.ndarray    # (33,)
    gesture: Optional[str]    # 派生：'wave_right' / 'wave_left' / 'point_left'
                              #       / 'point_right' / 'stop_palm' / 'hands_up'
                              #       / 't_pose' / 'crossed_arms' / None
    gesture_confidence: float

@dataclass
class GroundConstraint:
    clear_path: bool           # 正前方 1.5m 锥形区域内是否可走
    nearest_obstacle_m: float  # 锥形区域内最近障碍物距离（含 inf）
    nearest_person_m: float    # 任意方向最近人距离（含 inf）
    floor_visible_ratio: float # 视野中下半部分判定为地面的比例
    surface_tilt_deg: float    # 地面平均倾角（>15° 视为不平）

@dataclass
class SceneState:
    # 时间戳（monotonic 秒）
    ts_usb: float = 0.0
    ts_head: float = 0.0
    ts_pose: float = 0.0
    ts_yolo: float = 0.0

    # USB 摄像头侧（人/手势）
    user_pose: Optional[HumanPose] = None
    user_detections: list = field(default_factory=list)

    # MuJoCo 头摄侧（场景/地形）
    head_detections: list = field(default_factory=list)
    ground: Optional[GroundConstraint] = None

    # 元信息
    camera_resolution: tuple = (640, 480)
    perception_warnings: list = field(default_factory=list)  # ['no_depth', 'usb_dark', ...]
```

`g1_brain/scene_state/fusion.py` 提供：
- `SceneStateBus`：单例，线程安全，`update_*()` 由 perception 后台线程调用，`snapshot() -> SceneState` 由 SafetySupervisor 同步调用
- 内部用 RLock + 不可变 dataclass copy；不引入 asyncio Queue（fusion 不在 asyncio 上下文里）

### 2.4 派生量计算

`g1_brain/perception/derivations.py`：

#### 2.4.1 GroundConstraint（用 MuJoCo native depth）
- 取深度图下 60% 区域（地面候选）
- 在距离机器人 0.5–1.5m 的水平锥形（±15°）内统计：
  - `clear_path = (锥形区域 90% 像素的深度 > 0.6m)`
  - `nearest_obstacle_m = min(锥形区域深度)`
- `surface_tilt_deg`：对锥形区域深度做平面拟合，求与水平的夹角

#### 2.4.2 距离 / 方位（YOLO bbox + depth）
- 对每个 YOLO bbox 取中心像素的深度作为 distance_m
- 用相机内参算 bearing/pitch：
  - `bearing_deg = atan2((cx - cx_center) * z, fx) * 180/π`
  - 头摄相机内参从 mjModel 直接拿（FoV → fx/fy）

#### 2.4.3 手势分类（MediaPipe landmark → label）
简单几何规则，不引入额外模型（笔记 §10.1 推荐）：

| 手势 | 几何条件 |
|---|---|
| `wave_right` | 右手腕 y < 右肩 y - 0.15 且 |右手腕 x - 右肩 x| > 0.1 |
| `wave_left` | 镜像 |
| `hands_up` | 双腕 y < 双肩 y - 0.2 |
| `t_pose` | 双腕 y ≈ 双肩 y（差 < 0.05），双腕 x 远离躯干（差 > 0.3） |
| `point_left` | 一只手腕水平伸出，肘伸直，另一只手贴身 |
| `point_right` | 镜像 |
| `stop_palm` | 一只手前伸，肘弯曲 90°，手掌朝向相机（landmark visibility 配合） |
| `crossed_arms` | 双腕 x 跨过身体中线 |

每帧给出 `(gesture, confidence)`；`confidence` = 几何条件满足度（0–1）。
默认阈值 0.7，连续 3 帧满足才触发（防抖）。

### 2.5 Perception 模块文件清单

```
g1_brain/perception/
├── __init__.py
├── cameras.py             # CameraHub: 双相机统一接口
├── usb_camera.py          # 包装 va_demo.camera.Camera
├── mujoco_head_cam.py     # MuJoCo offscreen renderer + lowstate 订阅
├── object_detector.py     # YOLO11 wrapper, 后台 10-20 Hz
├── pose_detector.py       # MediaPipe-Pose wrapper, 后台 10-15 Hz
├── depth.py               # MuJoCo native depth + DepthAnythingV2 后备
├── derivations.py         # GroundConstraint / 距离方位 / 手势分类
└── runner.py              # PerceptionRunner: 启停所有后台线程，聚合到 SceneStateBus
```

### 2.6 Perception 资源消耗预估（4060 + WSL2）

| 模块 | GPU 显存 | GPU 利用率 | CPU |
|---|---:|---:|---:|
| MuJoCo offscreen renderer (640×480, 20Hz) | ~300 MB | 5% | 8% |
| YOLO11s (640, 15 Hz, 双流) | ~600 MB | 15% | 5% |
| MediaPipe-Pose (USB only, 15 Hz) | ~50 MB | 2% | 10% |
| DepthAnythingV2-S（默认关闭） | ~800 MB | 30% | 5% |
| **合计（默认开关）** | **~1 GB** | **~25%** | **~25%** |

留 7 GB 给 MuJoCo 物理 + 浏览器 + 其他工具，无压力。

---

## 3. Safety 层

### 3.1 7-状态 FSM

```
                         ┌──────────────┐
                         │  BOOT        │  系统启动，加载模型/连接 DDS
                         └──────┬───────┘
                                │ 全部子系统 ready
                                ▼
                         ┌──────────────┐
              ┌──────────│  STANDING    │◄────────┐  (recover)
              │          │  (idle)      │         │
              │          └──────┬───────┘         │
       (E-stop)                 │ user wake / cmd │
              │                 ▼                 │
              │          ┌──────────────┐         │
              │     ┌────│  ENGAGED     │         │
              │     │    │  (会话进行)  │         │
              │     │    └──────┬───────┘         │
              │     │           │ motion skill    │
              │     │           ▼                 │
              │     │    ┌──────────────┐         │
              │     │    │  ACTING      │         │
              │     │    │  (执行动作)  │         │
              │     │    └──────┬───────┘         │
              │     │           │ done            │
              │     │           └─────────────────┤
              │     │ session end                 │
              │     └─────────────────────────────┘
              │                                   │
              ▼                                   │
       ┌──────────────┐                           │
       │  EMERGENCY   │ ── recover button / op ───┘
       │  STOP        │
       └──────┬───────┘
              │ unrecoverable (倒地 / 长时间无 lowstate)
              ▼
       ┌──────────────┐
       │  FAULT       │  写日志 + 等运维介入
       └──────────────┘

       任意状态 ──── 异常 ────► EMERGENCY STOP
```

| 状态 | 允许 motion skill | 允许 say/describe | watchdog 触发动作 |
|---|---|---|---|
| BOOT | ❌ | ❌ | 等到所有子系统 ready 才进 STANDING |
| STANDING | 仅 `release_arms` / `recover_stand` | ✅ | 进 EMERGENCY |
| ENGAGED | ❌ | ✅ | 进 STANDING |
| ACTING | 当前 skill 继续；新 motion skill 排队 | ✅ | 进 EMERGENCY |
| EMERGENCY_STOP | 仅 `recover_stand`（人工触发后） | ✅（汇报） | 留在 EMERGENCY |
| FAULT | ❌ | ✅（解释） | 留在 FAULT |

### 3.2 SafetySupervisor 拦截规则（11 条）

每个 motion tool call 进 `validate()` 时按顺序检查：

1. **白名单**：`tool in ALLOWED_TOOLS`
2. **FSM 状态**：当前状态允许此 tool（见上表）
3. **run_mode**：observe 全拦 motion；confirm 弹终端 y/N；active 直放
4. **Watchdog (lowstate)**：`lowstate_age < 0.5s`
5. **Watchdog (head cam)**：`head_frame_age < 2.0s`
6. **Watchdog (RL policy active)**：`combo_ctl.policy_active == True`
7. **姿态检查**：IMU 投影重力的 z 分量 < -0.85（约 ±32° 倾角内）；超出视为接近倒地，进 EMERGENCY
8. **参数 clamp**：vx/vy/wz/duration 按 yaml 边界 clip（不拒绝，clip 后传下去）
9. **场景检查（仅 walk）**：
   - `SceneState.ground.clear_path == True`
   - `SceneState.ground.nearest_obstacle_m > min_obstacle_m`（默认 0.6）
   - `SceneState.ground.nearest_person_m > min_person_m`（默认 0.8）
10. **场景检查（仅 gesture）**：
    - `SceneState.ground.nearest_person_m > min_person_for_gesture_m`（默认 0.5，更宽松）
11. **E-stop 标志**：`estop_flag == False`（来自共享文件 / 共享内存）

通过则返回 `(True, "", sanitized_args)`；失败则返回 `(False, reason, {})`，并写日志 + 通过 say 解释（视配置）。

### 3.3 E-stop 独立进程

`g1_brain/safety/estop_listener.py`：
- 独立进程，import `unitree_sdk2py.core.channel`，订阅 DDS
- 监听三个触发源：
  1. **键盘**：`ESC` 按键（pynput / termios）
  2. **手柄**（可选）：xbox/switch 手柄某按键
  3. **共享文件**：`/tmp/g1_brain_estop` 文件存在即触发
- 触发后立即：
  1. 创建/touch 共享文件 `/tmp/g1_brain_estop`（让主进程的 SafetySupervisor 看到）
  2. 直接向 `rt/lowcmd` 推 30 帧 zero-torque（kp=0, kd=0, q=current, tau=0），覆盖主进程可能仍在发的 lowcmd
  3. 写日志 `/tmp/g1_brain_estop.log`
- 主进程定期 `check_estop_file()`，发现文件存在则进 EMERGENCY_STOP
- 解除：删除文件 + 主进程进 STANDING

为什么独立进程：主进程死锁 / 段错误 / 无限循环时，asyncio 主循环也死了，但 E-stop 进程仍能向 DDS 推 lowcmd。

### 3.4 watchdog 套娃

| watchdog | 周期 | 触发条件 | 触发动作 |
|---|---:|---|---|
| lowstate watchdog | 100 ms | `lowstate_age > 0.5s` | 拒所有 motion；持续 2s 进 EMERGENCY |
| frame watchdog (head) | 500 ms | `head_frame_age > 2.0s` | 拒 walk；持续 5s 进 EMERGENCY |
| frame watchdog (USB) | 500 ms | `usb_frame_age > 3.0s` | 拒 mock_imitate / 通知 LLM |
| pose watchdog | 100 ms | `gravity_z > -0.85` | 立即 EMERGENCY |
| RL policy watchdog | 100 ms | `policy_active == False` 且当前在 ENGAGED/ACTING | 立即 EMERGENCY |
| Realtime WS watchdog | 1 s | WS 断 30s 未重连 | 进 STANDING（停对话不停机） |

### 3.5 Safety 模块文件清单

```
g1_brain/safety/
├── __init__.py
├── state_machine.py        # FSM 类 + 状态枚举 + 转移规则
├── supervisor.py           # SafetySupervisor: validate() 主入口
├── watchdogs.py            # 5 个 watchdog 后台线程
├── estop_listener.py       # 独立进程入口（python -m g1_brain.safety.estop_listener）
├── estop_client.py         # 主进程读 estop 标志的客户端
└── pose_check.py           # IMU → projected_gravity → tilt 检查
```

---

## 4. Skills 层

### 4.1 完整工具菜单（暴露给 LLM）

#### L1（高层意图，LLM 偏好用这些）

| 工具 | 参数 | 实现 | 说明 |
|---|---|---|---|
| `say` | text | TTSClient（复用 va-demo） | 口播一句话 |
| `describe_scene` | question, detail | VisionClient + USB 或 head cam | 取一帧问 GPT-5.5 |
| `look_at` | target ∈ {person, object_name, left, right, ahead, ground} | turn(yaw_deg) 派生 | 调向某物 |
| `approach` | target_name, target_distance_m | walk 多步循环 | 慢速逼近某物 |
| `mock_imitate` | gesture ∈ {wave, hands_up, t_pose, salute} | gesture skill | 看到 user 做啥 G1 做啥 |
| `ask_human` | question | TTSClient + 暂停 | 问问题等回答 |

#### L2（参数化技能，LLM 也可以直接调）

| 工具 | 参数 | 实现 | 说明 |
|---|---|---|---|
| `walk` | vx, vy, wz, duration_s | ComboController.set_command + sleep | 短时走（已有，clamp 加严） |
| `turn` | yaw_deg | walk(wz, duration) 派生 | 原地小转 |
| `gesture` | name | ComboController.push_arm_action | 8 个 RL 兼容手势（已有） |
| `static_pose` | name | KeyframePlayer | g1_sim_keyboard 的 11 个静态 pose |
| `stop` | — | combo.stop + release_arms | 急停（不进 EMERGENCY） |
| `release_arms` | — | combo.release_arms | 把手交回 RL（已有） |

#### L1/L2 真机 only（仿真不支持，留在 schema 但 reject）

| 工具 | 真机后端 | 仿真行为 |
|---|---|---|
| `loco_high` | `LocoClient.WaveHand/ShakeHand/Squat/StandUp` | reject `sim_only` |
| `arm_action_high` | `G1ArmActionClient` (16 个动作) | reject `sim_only` |
| `audio_tts_robot` | `AudioClient.TtsMaker`（机器人本机 TTS） | reject |

### 4.2 KeyframePlayer：把 g1_sim_keyboard 的静态 pose 接进来

需要把 `g1_sim_keyboard.py` 的 11 个 pose 在 g1_brain 里能调用。难点：g1_sim_keyboard 自己有一个 500Hz 控制线程（`G1Controller`），它会把 lowcmd 直接 publish 到 `rt/lowcmd`；而 ComboController 也在 publish，会冲突。

解决方案：**KeyframePlayer 不独立 publish，而是把 pose 注入 ComboController 的 arm_overlay 队列**。具体地：
- ComboController 已有 `push_arm_action(keyframes)` 接口（仅控 arm 14 维），keyframes = `[(duration, arm_pose_14d), ...]`
- 把 g1_sim_keyboard 的 pose 函数（29 维）裁剪成 arm 部分（15..28 共 14 维），用 ComboController 的同一个 envelope clamp（`_clamp_arm_to_safe_envelope`）保护，转成 keyframes 推进去
- 涉及 leg/waist 的 pose（lift_knee / squat / kick / bow）**不接** —— 这些需要中断 RL policy，目前不在 v1 范围；想用就先 release RL（risk 高，留给 future work）

可接的（11 个 → 实际 9 个）：
- `wave_left_pose`、`hands_up_pose`、`t_pose_pose`、`salute_pose`、`clap_pose`、`hug_pose`、`boxer_guard_pose`、`punch_right_pose`、`punch_left_pose`

ComboController 已有的（重复，保留 ComboController 的实现）：
- 上面 8 个手势已经在 `g1_sim_rl_combo.build_arm_actions()`

新增（g1_sim_keyboard 独有）：
- `salute`、`hug` — 这两个 g1_sim_keyboard 里有，combo 里没有；写 delta 函数 + envelope clamp 接进 ComboController 的 push_arm_action

不接的（需要中断 RL，v1 跳过）：
- `bow`、`lean_left`、`lean_right`、`twist_left`、`twist_right`（waist，影响 projected_gravity，会让 RL 误判）
- `lift_left_knee`、`lift_right_knee`、`squat`、`kick_right`（leg，绝对不能在 RL 维持平衡时单独动）

对 LLM 暴露的 `static_pose` 工具的 enum 就是上面"可接的"那个集合 + "salute"、"hug"。

### 4.3 SkillServer 设计

`g1_brain/skills/skill_server.py`：

```python
class SkillServer:
    """统一 skill 调度，所有 skill 都过 SafetySupervisor。"""

    def __init__(self, combo_ctl, safety, tts, vision, camera_hub, scene_bus):
        self.combo = combo_ctl
        self.safety = safety
        self.tts = tts
        self.vision = vision
        self.cam = camera_hub
        self.scene = scene_bus
        # 把 g1_sim_keyboard 的 salute/hug 注入 combo（带 envelope clamp）
        self._extra_arm_actions = self._build_extra_arm_actions()

    async def execute(self, tool: str, args: dict) -> dict:
        ok, reason, args2 = await self.safety.validate(tool, args, self.scene)
        if not ok:
            return {"ok": False, "reason": reason}
        try:
            return await getattr(self, f"_skill_{tool}")(**args2)
        except Exception as e:
            log.exception("skill exception")
            await self._skill_stop()
            return {"ok": False, "reason": f"exception: {e!s}"}
```

每个 skill 实现一个 `_skill_<name>` 协程；`_skill_walk` 增加场景检查（每 0.2s 重新读 SceneState 决定是否提前停）：
```python
async def _skill_walk(self, vx, vy, wz, duration_s):
    self.combo.set_command(vx, vy, wz)
    t0 = time.monotonic()
    interval = 0.2
    try:
        while time.monotonic() - t0 < duration_s:
            await asyncio.sleep(interval)
            scene = self.scene.snapshot()
            if scene.ground and not scene.ground.clear_path:
                log.warning("walk aborted: path blocked at t=%.2f", time.monotonic()-t0)
                break
            if scene.ground and scene.ground.nearest_obstacle_m < 0.5:
                log.warning("walk aborted: obstacle %.2fm", scene.ground.nearest_obstacle_m)
                break
    finally:
        self.combo.set_command(0.0, 0.0, 0.0)
    return {"ok": True, "skill": "walk", "actual_duration_s": time.monotonic()-t0}
```

### 4.4 Skills 模块文件清单

```
g1_brain/skills/
├── __init__.py
├── skill_server.py             # SkillServer: 调度 + 场景反应式中断
├── tool_schemas.py             # OpenAI Realtime tool JSON schema 定义（~16 个工具）
├── keyframe_extras.py          # salute/hug 等额外 arm 手势（接进 ComboController）
├── compound_skills.py          # look_at / approach / mock_imitate 派生实现
└── real_robot_adapters.py      # LocoClient / G1ArmActionClient 真机适配（v1 占位）
```

---

## 5. Brain 层（Slow Brain）

### 5.1 复用与扩展

va-demo 的 `realtime_agent.RealtimeAgent` 整体复用，唯一改动是：
- 注入 `g1_brain.skills.SkillServer` 取代原 `va_demo.skills.SkillBackend`
- 注入 `g1_brain.safety.SafetySupervisor` 取代原 `va_demo.safety.SafetySupervisor`
- `_build_tool_schemas()` 取自 `g1_brain.skills.tool_schemas`（~16 个工具）
- 新增 system prompt（`g1_brain/brain/prompts.py`），包含 SceneState 注入说明

### 5.2 SceneState 注入策略

LLM 不能直接读 SceneState（太大、变化频繁），但需要"知道"场景概要。两条路：

#### 5.2.1 被动：tool 返回结果里附带 scene snapshot 摘要

每次 motion skill 返回时附 SceneState 简化字典：
```json
{"ok": true, "skill": "walk", "scene": {"persons": 1, "nearest_obstacle_m": 1.2, "clear_path": true}}
```
LLM 读到后决定下一步。

#### 5.2.2 主动：增加 `query_scene_state` tool

让 LLM 想知道时主动查；返回简化文本：
```
"Scene at t=12.3s: 1 person ahead 1.5m, no obstacles within 2m, ground clear, last user gesture: wave_right (0.85 conf 0.8s ago)"
```

**两条都做**。被动是默认，让 LLM 不用问就有上下文；主动是兜底，让 LLM 在不确定时能查。

### 5.3 新 Prompt（关键节选）

`g1_brain/brain/prompts.py` —— REALTIME_SYSTEM_PROMPT_BRAIN：

```
You are the high-level brain of a Unitree G1 humanoid robot named "Sparky"
running in a MuJoCo simulator. You see the world through:
- Your front-facing camera (head camera) — your own first-person view
- A USB camera looking at the user

You can:
- Speak via the say tool or your own voice replies
- Look at the scene via describe_scene (uses head camera by default)
- Query the perception system via query_scene_state
- Move via short, conservative motion skills (walk, turn, gesture, static_pose,
  look_at, approach, mock_imitate, stop, release_arms)

Hard rules (you cannot violate, the safety layer will reject you):
- You DO NOT have direct motor control. You can only call the listed tools.
- Walk durations <= 1.0 s, vx <= 0.2 m/s, wz <= 0.3 rad/s unless the user
  explicitly insists.
- Before you walk forward, ALWAYS call describe_scene or query_scene_state
  to confirm the path is clear.
- If a motion tool returns ok=false with a "path blocked" / "obstacle" reason,
  STOP. Do not retry. Explain in the user's language and ask for direction.
- Mock imitation: when the user does a recognizable gesture (wave / hands_up /
  t_pose / point), the perception system flags it; you may call
  mock_imitate(gesture=...) to mirror it back. Always say something first
  ("我看到你在挥手, 我也挥一下"), then call the gesture.

Style:
- Speak in the user's language (Chinese or English).
- Keep replies short and natural. Don't narrate every tool call.
- IMPORTANT: never say "Sparky" yourself; it's the wake word.
```

### 5.4 Brain 模块文件清单

```
g1_brain/brain/
├── __init__.py
├── prompts.py                 # REALTIME_SYSTEM_PROMPT_BRAIN + VISION_SCENE_PROMPT
├── realtime_agent.py          # 子类化 va_demo.RealtimeAgent，注入新 SkillServer
└── scene_summary.py           # SceneState -> LLM-friendly text/dict 摘要
```

---

## 6. Mock Imitation（Phase 5 语义模仿）

### 6.1 数据流

```
USB Camera  →  PoseDetector (MediaPipe, 15 Hz)
                    ↓
              landmarks → derivations.classify_gesture()
                    ↓
              gesture, confidence
                    ↓ (写入 SceneStateBus.user_pose.gesture)
                    ↓
        ┌───────────┴────────────┐
        │                        │
   (a) LLM 主动                (b) 被动触发
       describe_scene 时        gesture 持续 1s 高置信度
       看到 user_pose.gesture   → 直接调 mock_imitate
       → 自己判断要不要 mirror
```

两条路都打开。LLM 自由判断 + perception 自动建议。`mock_imitate(gesture)` 内部：
1. 校验 `gesture` 在 `MIRRORABLE_GESTURES` 集合（`{wave_right, wave_left, hands_up, t_pose}`）
2. 调用对应 `gesture` skill（已有 8 个 RL-safe 手势 + salute/hug）
3. mapping：
   - `wave_right` → `gesture(wave_right)`
   - `wave_left` → `gesture(wave_left)`
   - `hands_up` → `gesture(hands_up)`
   - `t_pose` → `gesture(t_pose)`
   - 其它 user gesture（point/stop/cross/squat）暂时不 mirror

### 6.2 Mock Imitation 模块文件清单

```
g1_brain/mock_imitation/
├── __init__.py
├── gesture_to_skill.py        # MIRRORABLE_GESTURES 映射表 + mock_imitate 实现
└── auto_trigger.py            # 后台线程：连续 1s 高置信度 → 提示 LLM
```

---

## 7. 配置 / 目录 / 测试 / 日志

### 7.1 完整目录结构

```
unitree-notes/g1_brain/
├── README.md
├── pyproject.toml             # 包元信息 + 依赖（兼容 conda agi env）
├── requirements.txt           # 显式列出所有 pip 依赖
├── configs/
│   ├── g1_brain.yaml          # 主配置
│   ├── safety_envelope.yaml   # 安全限值
│   └── skills_catalog.yaml    # 工具菜单 + 限值
├── g1_brain/
│   ├── __init__.py
│   ├── perception/            # §2.5
│   ├── scene_state/
│   │   ├── __init__.py
│   │   ├── types.py
│   │   └── fusion.py
│   ├── safety/                # §3.5
│   ├── skills/                # §4.4
│   ├── brain/                 # §5.4
│   ├── mock_imitation/        # §6.2
│   └── apps/
│       ├── __init__.py
│       ├── agent_main.py            # 完整 Slow+Fast+Safe agent 入口
│       ├── perception_debug.py      # 只跑 perception，可视化 SceneState
│       ├── safety_debug.py          # 模拟 SceneState + 走 SafetySupervisor
│       ├── skill_debug.py           # 命令行选 skill 触发
│       └── estop_test.py            # 测试 E-stop 链路
├── tests/
│   ├── conftest.py
│   ├── test_scene_state.py
│   ├── test_safety_supervisor.py
│   ├── test_skill_server.py
│   ├── test_perception_derivations.py  # 几何手势分类
│   ├── test_mock_imitation.py
│   └── test_estop_flow.py
└── docs/
    ├── README.md
    ├── architecture.md       # 复制 §1-§6 精简版
    ├── how_to_run.md         # 启动顺序、需要开几个终端
    └── extending_skills.md   # 怎么加新 skill
```

### 7.2 配置示例：`configs/g1_brain.yaml`

```yaml
mode: "sim"                     # sim / real
run_mode: "confirm"             # observe / confirm / active

robot:
  domain_id: 1
  interface: "lo"
  mjcf_path: "${HOME}/unitree/unitree-notes/unitree_mujoco/unitree_robots/g1/scene_29dof.xml"

cameras:
  usb:
    enabled: true
    source: "teleimager"        # teleimager / cv2
    teleimager_host: "127.0.0.1"
    teleimager_request_port: 60000
    cv2_index: 0
    poll_hz: 20
  head:
    enabled: true
    camera_name: "head_camera"
    width: 640
    height: 480
    poll_hz: 20

perception:
  device: "auto"                # cuda / cpu / auto
  yolo:
    enabled: true
    weights: "yolo11s.pt"
    conf: 0.4
    inference_hz: 15
    classes: null               # null = 全 80 类；或 [0,56,57,...]
  pose:
    enabled: true
    inference_hz: 15
    min_visibility: 0.5
  mono_depth:
    enabled: false              # sim 默认走 native depth；想测 sim2real 时开
    model: "depth-anything/Depth-Anything-V2-Small-hf"
  ground_constraint:
    cone_half_angle_deg: 15
    cone_min_dist_m: 0.5
    cone_max_dist_m: 1.5
    safe_clearance_m: 0.6

safety:
  walk:
    vx_max: 0.2
    vy_max: 0.1
    wz_max: 0.3
    duration_max_s: 1.0
    duration_min_s: 0.2
  gesture:
    max_concurrent: 1
  scene:
    min_obstacle_m: 0.6
    min_person_m: 0.8
    min_person_for_gesture_m: 0.5
  pose:
    gravity_z_min: -0.85       # 投影重力 z (单位向量) 阈值
  watchdog:
    lowstate_max_age_s: 0.5
    head_frame_max_age_s: 2.0
    usb_frame_max_age_s: 3.0
  say:
    max_chars: 200
  estop:
    flag_path: "/tmp/g1_brain_estop"
    keys: ["esc"]
    publish_zero_torque_count: 30

openai:
  realtime_model: "gpt-realtime"
  vision_model: "gpt-5.5"
  tts_model: "gpt-4o-mini-tts"
  tts_voice: "alloy"
  realtime_voice: "alloy"
  vision_detail: "medium"

# 复用 va-demo 的音频/wake-word 配置
audio:
  samplerate: 24000
  block_ms: 50
  speaker_buffer_ms: 200
  input_device: null
  output_device: null

wakeword:
  enabled: true
  backend: openai
  openai_model: "gpt-4o-transcribe"
  openai_prompt: "Sparky"
  rolling_window_s: 1.5
  inference_rate_hz: 2.0
  rms_threshold: 100
  cooldown_s: 2.0
  language: null
  phrases: ["hi sparky", "hey sparky", "嗨 sparky", "你好 sparky"]

utterance:
  silence_threshold_ms: 1500
  max_duration_s: 30.0
  vad_aggressiveness: 2
  no_speech_timeout_s: 4.0

conversation:
  listening_window_s: 8.0
  selfecho_dedup_window_s: 6.0

mock_imitation:
  enabled: true
  auto_suggest_high_conf: 0.8
  auto_suggest_persist_s: 1.0
  mirrorable: ["wave_right", "wave_left", "hands_up", "t_pose"]

logging:
  level: "INFO"
  log_dir: "${HOME}/unitree/unitree-notes/g1_brain/logs"
  rotate_mb: 50
```

### 7.3 测试策略

- **单测优先级 1**（必须）：
  - `test_safety_supervisor.py`: 11 条规则全覆盖 + FSM 转移合法性
  - `test_perception_derivations.py`: 手势分类规则、geom 计算
  - `test_scene_state.py`: 线程安全 snapshot + dataclass 不可变性
  - `test_skill_server.py`: 每个 skill 通过 mock SafetySupervisor + ComboController
- **单测优先级 2**：
  - `test_mock_imitation.py`: gesture → skill 映射、auto trigger 防抖
  - `test_estop_flow.py`: estop file → safety reject + FSM 转移
- **集成测**（手动 / e2e）：
  - `apps/agent_main.py --no-realtime --no-skills`：只跑 perception，看 SceneState
  - `apps/skill_debug.py`：命令行选 skill，确认走 ComboController
  - 完整端到端：开 MuJoCo + teleimager + agent_main，喊 "Hi Sparky → 走两步" 看 confirm 提示

### 7.4 日志规范

- 每个动作（VLM tool call、SafetySupervisor decision、skill execution、watchdog 事件、E-stop）都写到 `logs/episodes/<ts>/`
- 三个日志文件：
  - `decisions.jsonl`：VLM tool call 的 input/output（含 args、validate result、final result）
  - `safety.jsonl`：reject reasons、FSM 状态转移、watchdog trips
  - `perception.jsonl`：SceneState 快照（每 10 帧采一次，节省空间）
- 失败动作 + 异常额外写 `errors/<ts>.json`（含 stack trace）

---

## 8. 路线图、验收、Phase 6+ 展望

### 8.1 实施 Phase（对应笔记 §11）

| Phase | 内容 | 验收 |
|---|---|---|
| **P0 安全准备** | E-stop 链路、SafetySupervisor 拦截、observe_only mode | 任意 LLM 输出都不能让 G1 倒地或撞物（手动注入恶意 tool call 测试） |
| **P1 看+说不动** | Perception 跑通，SceneState 广播；Brain 用 describe_scene + say | 喊 "Sparky 前面有什么"，G1 用语音说出场景描述 |
| **P2 选动作 + 人工确认** | Skill 全工具上线，run_mode=confirm | 喊 "走两步"，看到 confirm prompt，按 y 后 G1 慢速走 0.5–1s 然后停 |
| **P3 低速视觉导航 mock** | walk 内部反应式中断 + scene check 11 条全开 | 在 G1 前面放虚拟障碍（MuJoCo 加 box），喊"向前走"，G1 走到 0.6m 自动停 |
| **P4 语音代理完整** | 全语音对话 + tool 路径，wake-word + utterance commit + barge-in 处理 | 完整对话 5 轮无中断，每轮 RTT < 6s |
| **P5 语义模仿** | mock_imitation 全开，auto-suggest + LLM 主动两条路 | 你挥手，G1 1.5s 内挥手回应 |

### 8.2 Phase 6 / 7（future work，不在 v1 范围）

- **P6 XR 遥操作 + LeRobot**：`xr_teleoperate --record` 采集你做的动作，转 LeRobot 数据格式，训练 imitation policy（`reach_red_cube_lerobot_v1`）—— 接到 SkillServer 成为 `lerobot_policy(name)` 工具
- **P7 GMR + RL tracking**：用 GMR 把 SMPL-X / BVH 重定向到 G1，MuJoCo 验证后训 RL tracking policy；接到 SkillServer 成为 `track_motion(name)` 工具
- **本地 VLM**：用 Qwen2.5-VL / LLaVA-OneVision 替代 GPT-5.5，未来真机离线场景

### 8.3 真机迁移 checklist（基于 v1 设计）

| 子系统 | sim → real 的改动 |
|---|---|
| `cameras.usb` | source=teleimager 已是真机路径，无变化 |
| `cameras.head` | `MuJoCoHeadCamera` → `RealSenseCamera` / `G1FrontCamera`（新写适配器，接口同 `latest_bgr/latest_depth/frame_age_seconds`） |
| `perception.mono_depth` | sim 关；real 上若 RealSense 故障可启 DepthAnythingV2 |
| `skills.skill_server` | `combo_ctl` → `LocoClient + G1ArmActionClient`；新写 `RealRobotSkillServer`（接口与 sim 一致），main.py 看 `mode: real` 切换 |
| `safety.estop` | flag 文件机制保留；同时绑定真机硬件 E-stop（手柄按键） |
| `safety.fsm` | 一致；增加 `STAND_UP_SEQUENCE` 状态用于真机首次站起 |
| `brain` | 一致；prompt 加一句 "you are now on a real robot, be even more conservative" |

迁移时要做的真机专属验证（笔记 §16 全套坑都要走一遍）：
- mode_machine 是不是 high-level service 模式
- LocoClient 能不能 Move(0,0,0)
- G1ArmActionClient WaveHand 能不能触发
- DDS 网络、firmware、EDU 权限
- E-stop 真机 reachable

---

## 9. 依赖清单（pyproject.toml + requirements.txt）

### 9.1 复用（已在你 agi env 里）

`unitree_sdk2py`, `cyclonedds`, `mujoco`, `numpy`, `opencv-python`, `pyyaml`, `sounddevice`, `webrtcvad`, `websockets`, `openai`, `aiohttp`

### 9.2 新增

```
ultralytics>=8.3              # YOLO11
mediapipe>=0.10               # BlazePose
torch>=2.1                    # ultralytics 依赖；4060 用 cu121
torchvision>=0.16
pynput>=1.7                   # E-stop 键盘监听
# 可选（默认关闭）
transformers>=4.40            # DepthAnythingV2 via HuggingFace
accelerate>=0.30
```

预估首次安装大小：
- ultralytics + torch (cu121) ≈ 3–4 GB
- mediapipe ≈ 200 MB
- transformers + DAv2-Small ≈ 600 MB（按需）

### 9.3 离线模型缓存路径

```
~/.config/Ultralytics/yolo11s.pt          # ~22 MB，首次自动拉
~/.cache/huggingface/hub/                  # DepthAnythingV2-Small ~100 MB
mediapipe 模型在 wheel 内                   # 无需单独下载
```

---

## 10. 启动顺序与运行示例

### 10.1 仿真完整启动（4 个终端）

```bash
# Terminal 1: MuJoCo 仿真
conda activate unitree
export MUJOCO_GL=glfw
cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
python unitree_mujoco.py
# viewer: 按 8 几次让 G1 落地，按 9 解除弹力带

# Terminal 2: teleimager（USB 摄像头服务）
conda activate unitree
cd ~/unitree/unitree-notes/teleimager
python -m teleimager.image_server

# Terminal 3: E-stop 监听器（独立进程，键盘 ESC 触发）
conda activate agi
cd ~/unitree/unitree-notes/g1_brain
python -m g1_brain.safety.estop_listener

# Terminal 4: g1_brain 主进程
conda activate agi
cd ~/unitree/unitree-notes/g1_brain
export OPENAI_API_KEY=sk-...
python -m g1_brain.apps.agent_main --mode confirm
```

### 10.2 一次完整对话样例

```
You: Hi Sparky
[wake] hi sparky
You: 看一下前面有什么？
[describe_scene] head camera frame -> GPT-5.5
Sparky: 我看到正前方大约 1 米外有一张红色椅子，地面平整，路径基本通畅。
You: 那向前走两步过去看一下
[query_scene_state] called by LLM
[scene] persons=0, nearest_obstacle=1.05m, clear_path=true
[tool] walk(vx=0.18, wz=0, duration_s=0.8)
[safety] confirm prompt: execute walk(...)? [y/N] y
[scene check at t=0.4s] obstacle=0.9m -> still ok
[scene check at t=0.6s] obstacle=0.78m -> still ok
[walk done] actual_duration=0.8s, final_obstacle=0.7m
Sparky: 我向前走了一小步，离椅子大概 0.7 米，你想我再靠近一点还是停在这里？
You: [挥手]
[perception] gesture=wave_right conf=0.88 persist=1.2s
[brain] auto-suggest mock_imitate(wave_right)
Sparky: 我看到你在向我挥手，我也挥一下。
[tool] mock_imitate(wave_right) -> gesture(wave_right)
[combo] arm_overlay queued, releases in 3.2s
You: 谢谢，停一下
[tool] stop()
Sparky: 已停止，等你下一步指示。
```

---

## 11. 评估指标（笔记 §19 直接引用 + 适配）

| 指标 | v1 目标 | 怎么测 |
|---|---|---|
| LLM tool call schema parse 成功率 | > 99% | 跑 50 轮对话日志 |
| 非白名单动作出现次数 | 0 | grep `unknown tool` |
| Safety 拒绝危险动作成功率 | 100% | apps/safety_debug.py 注入 50 个恶意 args |
| stop 响应时间 | < 300 ms | 从 tool call 到 combo.set_command(0,0,0) 计时 |
| E-stop 触发到 zero-torque 上 DDS | < 200 ms | estop_test.py |
| MuJoCo 头摄帧率 | > 15 FPS | perception_debug 看输出 |
| YOLO11s 头摄推理 | > 12 FPS | 同上 |
| MediaPipe-Pose USB | > 12 FPS | 同上 |
| TTS 首包延迟 | < 800 ms | 复用 va-demo 已测 |
| 单次 walk 持续 | ≤ 1.0 s | 配置 + 单测保证 |
| 人工确认覆盖率（confirm 模式） | 100% motion | safety_debug |
| 日志完整率 | 100% | 跑 60 分钟对话后 grep |

---

## 12. 不在范围（明确排除）

避免误以为这些是 v1 内容：

- **多帧 / 视频 VLM 推理**：单帧 keyframe，无运动检测、无快照锁定
- **本地 VLM 替代 GPT-5.5**：用云端，本地模型留给 §11.2 future
- **LeRobot policy 真训**：用既有 ComboController + keyframe，不训新 policy
- **GMR / RL tracking**：完全留 future
- **真机部署**：v1 只跑 sim；架构留好接口
- **手部精细操作 / Inspire 手**：完全不动
- **Behavior Tree / py_trees**：v1 用 enum FSM 够用，BT 留 future
- **多机器人**：单 G1
- **Realtime 断线自动重连**：复用 va-demo（断了退出，让用户重启）
- **日志可视化 dashboard**：只写 jsonl，看的工具留 future

---

## 13. 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| MuJoCo offscreen 与 viewer 同时 GPU 渲染卡顿 | 中 | 性能 | 渲染分辨率默认 640×480；超过 25% GPU 利用率自动降到 480×360 |
| YOLO 误检 → 假障碍 → 拒 walk | 中 | 可用性 | conf 默认 0.4；非 person/动物的 class 不 gating walk；clear_path 也要看 depth |
| MediaPipe 误识别 gesture | 高 | 用户困惑 | 1 秒持续 + 0.7 conf 双门槛；mock_imitate 始终先 say 解释 |
| E-stop 进程崩溃（无人发现） | 低 | 安全 | 主进程 watchdog 监听 estop 进程心跳；丢失 5s 进 STANDING |
| GPT-5.5 视觉账号未开通 | 低 | 视觉失效 | env 切到 gpt-4o；vision.describe 异常时 say "看不清" |
| ComboController policy_active=False（mode 切换） | 中 | 走/手势失效 | safety watchdog 直接拒 motion；建议用户重启 |
| 4060 显存不足（同时跑 YOLO + DAv2 + MuJoCo） | 低 | OOM 崩溃 | 默认关 DAv2；perception_debug 提供 memory profile |
| WSL2 USB 断开（teleimager 失效） | 中 | mock_imitation 失效 | usb_frame watchdog 拒；mock_imitation 自动停 auto-suggest |

---

## 14. 与笔记 vlm_audio_mock_deep.md 的逐节对照

| 笔记节 | 本设计落地位置 |
|---|---|
| §1 Slow Brain + Fast Reflex + Safe Skill 三层 | §1.1 心智模型 |
| §3.2 控制频率分层 | §1.2 频率表 |
| §4 仓库研究（SDK/teleimager/xr/LeRobot/GMR/RL） | §1.4 复用 + §11.2 future |
| §5 第一版 mock 系统 + 目录结构 | §7 完整目录 |
| §6 GPT-5.5 Vision 结构化输出 | §5.2 SceneState 注入 + 复用 va-demo describe_scene |
| §7 Safety Supervisor | §3 全节 |
| §8 Skill Server | §4 全节 |
| §9 G1 说话三路线 | 用路线 A (cloud TTS) + B (Realtime) |
| §10 模拟人 → 三阶段 | §6 落地阶段 1；阶段 2/3 → §11.2 future |
| §11 路线图 P0–P7 | §8.1 P0–P5 落地；P6/P7 → §11.2 future |
| §12 最小 demo | §10.2 完整对话样例 |
| §13 摄像头 | §2.1 双相机 + §2.2 模型 |
| §14 音频输入 | 复用 va-demo |
| §15 tool calling | §4.1 完整菜单 + §4.3 SkillServer |
| §16 常见坑 | §13 风险与缓解 + §8.3 真机 checklist |
| §17 五个小程序 | §7.1 apps/ 五个 debug 入口 |
| §19 评估指标 | §11 全节 |
| §20 高级版本 (Behavior Tree / Scene Graph) | future, §12 排除清单 |

---

## 15. 总结

**v1 核心交付**：在 MuJoCo 上把 Slow Brain + Fast Reflex + Safe Skill 三层完整跑通，覆盖笔记 Phase 0–5。

**关键设计取舍**：
- 新建 `g1_brain/` 顶层包，**import 而不重写** va-demo 和 g1_sim_demo
- 双相机：USB（看人）+ MuJoCo head cam（看场景）
- LLM 限 L1/L2，不允许 L3 关节角
- SafetySupervisor 11 条规则 + 7 状态 FSM + 独立 E-stop 进程
- Skill 16 个工具，覆盖 walk/turn/gesture/static_pose/look_at/approach/mock_imitate
- mock_imitation 仅做语义级（gesture name → 已验证 skill），不做连续姿态镜像

**跑通后可立即扩展的方向**：
1. 接 LeRobot policy（P6）
2. 接 GMR + RL tracking（P7）
3. 真机部署（替换 cameras + skills 适配器即可）
4. 升级 LLM 到本地 VLM（隐私 / 离线场景）

**全套验收**：跑通 §10.2 那段对话样例 + §11 全部指标达标 = v1 done.
