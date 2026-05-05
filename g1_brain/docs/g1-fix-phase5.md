# g1-fix-phase5 — "让他挥手时说要摄像头" / `usb_frame` 看门狗误锁所有动作

Date: 2026-05-05
Branch: main

## 1. Symptom（用户原始描述）

操作者在 MuJoCo 仿真中运行：

```bash
python -m g1_brain.apps.agent_main --mode confirm
```

启动一切正常（`fsm: BOOT -> STANDING -> ENGAGED`，policy 进入），但只要说一句
"挥手 / Wave your hand"，Sparky 就回答类似：

> 抱歉，我没能成功模仿你的挥手。可能摄像头画面有问题。
> 看来摄像头画面可能还有问题。你能稍微调整一下，或者让我确认一下周围环境吗？

并且**完全不挥手**。终端日志里两条关键拒绝：

```text
20:12:20 va_demo.realtime_agent: tool call: mock_imitate({'gesture': 'wave_right'})
20:12:20 g1_brain.skills.skill_server: safety rejected mock_imitate({'gesture': 'wave_right'}):
         watchdog tripped: usb_frame=age=infs
20:12:44 va_demo.realtime_agent: tool call: gesture({'name': 'wave_right'})
20:12:44 g1_brain.skills.skill_server: safety rejected gesture({'name': 'wave_right'}):
         watchdog tripped: usb_frame=age=infs
```

操作者的疑问有三个，每一个都被这次修复回答清楚：

1. **挥手为什么要摄像头？挥手不就是动手臂吗？** → 是 BUG。底下 §2 解释。
2. **MuJoCo 中机器人是不是有自己的摄像头？我能不能开它？** → 有，而且**已经在跑**了。
   日志里这一行就是它启动的证据：
   ```text
   g1_brain.perception.mujoco_head_cam: synthesized head camera 'head_camera'
       on body 'torso_link' at pos=(0.08, 0.0, 0.45) fovy=60.0°
   ```
   只是没有图形界面让你"看"它，需要主动跑 §4.1 的命令。
3. **我笔记本摄像头是不是必须？** → 不是。它只用于检测**用户**的手势喂给
   `mock_imitate` 自动镜像，机器人自己挥手 / 走路 / 描述场景**完全不依赖**它。

## 2. Root cause

### 2.1 真正的 BUG —— `usb_frame` 看门狗错误地锁住所有动作

`g1_brain/safety/watchdogs.py` 维护 5 个看门狗：

| 看门狗 | 检查什么 | `emergency` | 应该锁动作吗？ |
| --- | --- | --- | --- |
| `lowstate` | DDS 收 `rt/lowstate` 的延迟 | True | ✅ 是 |
| `head_frame` | MuJoCo 头相机最近一帧的年龄 | True | ✅ 是（仅 walk/approach） |
| `pose` | IMU 重力投影 z（机器人是否在跌倒） | True | ✅ 是 |
| `rl_policy` | combo 的 `policy_active` flag | True | ✅ 是 |
| **`usb_frame`** | **笔记本/teleimager USB 相机最近一帧的年龄** | **False** | **❌ 否 —— 它是 informational** |

`emergency=False` 在原作者意图里是"informational：会写日志、追踪 trip 时间用于
auto-recovery，但**不**升级到 EMERGENCY_STOP，也**不**应该挡动作"。可是
`_set_trip` 的实现里：

```python
def _set_trip(self, name, reason, *, emergency):
    ...
    if self.supervisor is not None:
        self.supervisor.set_watchdog_trip(name, reason)   # <-- 不论 emergency 都推
    if emergency and elapsed >= hold and not in_grace:
        self.fsm.transition(RobotFsmState.EMERGENCY_STOP, ...)
```

`emergency` 标志只控制了 FSM 提升那一步，**没有**控制是否把 trip 同步给 supervisor。
而 `SafetySupervisor.validate` 里：

```python
# supervisor.py:216-220
if is_motion and self._watchdog_trips:
    tripped = ", ".join(f"{k}={v}" for k, v in self._watchdog_trips.items())
    return False, f"watchdog tripped: {tripped}", {}
```

**任何一个** trip flag 都拒绝**任何一个**动作工具。结果：用户没开 teleimager
（笔记本摄像头服务） → `usb_frame age = infs` → trip 推给 supervisor →
`gesture` / `walk` / `turn` / `mock_imitate` 全被拒。

注释里写得很清楚 "USB-frame trip is informational (sets a flag but does not
promote)"，但 informational 这个语义只兑现了一半。

### 2.2 LLM 把"usb_frame"误读成"摄像头有问题"

SkillServer 把拒绝原因原样塞进工具结果：

```json
{"ok": false, "skill": "gesture", "reason": "watchdog tripped: usb_frame=age=infs"}
```

LLM 看到 `usb_frame`，**符合统计直觉**地翻译成"USB 摄像头画面有问题"，于是对
用户说"摄像头画面可能还有问题"。这不是 LLM 偏离指令，而是 prompt 没有告诉它
USB 相机的真实角色（**只**给 `mock_imitate` 自动镜像用，与 `gesture` 无关），
LLM 也没法知道 `usb_frame` 在 g1_brain 里其实**不应该**与挥手相关。

### 2.3 相机角色被 prompt 模糊化

旧版 `REALTIME_SYSTEM_PROMPT_BRAIN`：

```text
- A USB camera looking at the user (so the perception layer can detect their gestures).
```

只说"USB 相机看用户、检测手势"，没说**机器人自己挥手不需要它**。LLM 因此倾向
把任何 USB 相关错误归因为"挥手做不到"。

## 3. Fix

### 3.1 (A) `_set_trip` / `_clear_trip` 让 informational trip 不再外泄给 supervisor

`g1_brain/safety/watchdogs.py:219-256` —— 把 supervisor 同步收紧到只在
`emergency=True` 时才发生：

```python
def _set_trip(self, name: str, reason: str, *, emergency: bool) -> None:
    with self._lock:
        now = time.monotonic()
        if self._trip_since[name] is None:
            self._trip_since[name] = now
            log.warning("watchdog %s tripped: %s", name, reason)
        elapsed = now - self._trip_since[name]
        in_grace = self._in_boot_grace(now)
    # Only emergency-class (motion-blocking) trips propagate to the
    # supervisor. ``emergency=False`` trips (currently usb_frame) are
    # informational: they get logged + tracked locally for recovery
    # bookkeeping, but they MUST NOT block motion calls. usb_frame
    # gates user-gesture detection (the laptop webcam fed via
    # teleimager) — losing it should not stop the robot from waving,
    # walking, or otherwise running, since none of those skills read
    # the USB stream.
    if self.supervisor is not None and emergency:
        try:
            self.supervisor.set_watchdog_trip(name, reason)
        except Exception:
            log.exception("watchdog: supervisor set_watchdog_trip raised")
    hold = self._hold_down_s.get(name, 0.0)
    if emergency and elapsed >= hold and not in_grace:
        try:
            self.fsm.transition(RobotFsmState.EMERGENCY_STOP, f"watchdog {name}: {reason}")
        except IllegalTransitionError:
            pass

def _clear_trip(self, name: str) -> None:
    with self._lock:
        if self._trip_since[name] is not None:
            self._trip_since[name] = None
            log.info("watchdog %s cleared", name)
    # Always best-effort clear; idempotent if the trip was never set
    # on the supervisor in the first place (informational trips).
    if self.supervisor is not None:
        try:
            self.supervisor.set_watchdog_trip(name, None)
        except Exception:
            log.exception("watchdog: supervisor clear raised")
```

行为变化：

| 场景 | 改前 | 改后 |
| --- | --- | --- |
| `usb_frame age=infs`（无 teleimager） | ❌ 所有动作被拒（"watchdog tripped: usb_frame=age=infs"） | ✅ 日志里仍有 `WARNING watchdog usb_frame tripped`（informational），动作继续工作 |
| `lowstate age=1.5s`（DDS 卡） | ❌ 所有动作被拒 | ❌ 仍拒（行为不变，emergency=True） |
| `head_frame age=10s` | ❌ 所有动作被拒 + 5s 后 EMERGENCY_STOP | ❌ 仍拒（行为不变） |
| `pose gravity_z=-0.5` | ❌ 立即 EMERGENCY_STOP | ❌ 仍拒（行为不变） |

clear 路径改动只是注释；`set_watchdog_trip(..., None)` 对没设过的 key 等同于
`dict.pop(..., None)`，无副作用。

### 3.2 (B) Brain prompt 明确两个相机的职责，并禁止 LLM 把 `usb_frame` 误读成"摄像头有问题"

`g1_brain/brain/prompts.py::REALTIME_SYSTEM_PROMPT_BRAIN`：

旧：
> - Your front-facing camera (head camera) — your own first-person view ...
> - A USB camera looking at the user (so the perception layer can detect their gestures).

新：
> - **Your head camera** — your own first-person view, **rendered by MuJoCo** from a
>   virtual camera mounted on the robot's torso. This is what YOU see while
>   walking around the simulated world. **It is always available in sim.**
> - **(Optional) A USB camera** that watches the human user so the perception
>   layer can detect THEIR hand gestures. **This is purely for the mock_imitate
>   auto-trigger** feature (you mirror the user's wave when they show one). It
>   is **NOT required for any of your own motion skills.** It may be unavailable
>   if the user has not started the laptop webcam stream.

并新增两条硬规则：

> - gesture / static_pose / walk / turn do NOT depend on the USB camera. If a
>   call returns ok=false with a reason that mentions "usb_frame" / "USB" /
>   "teleimager" / "user-gesture detection", treat it as an unrelated config
>   warning — do NOT tell the user "the camera image is bad" or "I can't see
>   you clearly". Retry the same call after acknowledging the warning, or
>   proceed without retry if the user gave a direct command.
> - Tool selection for direct verbal commands:
>     * "Wave" / "挥手" / "Salute" → call gesture(name="wave_right" / "salute" / ...).
>       gesture is purely a motor primitive; no camera is needed.
>     * mock_imitate is reserved for MIRRORING the user's just-detected
>       gesture. Only call it when a system note says "User showed gesture: X",
>       not for plain verbal commands like "wave your hand".

修复了用户日志里看到的两个 LLM 错误：第一次错把 "wave your hand" 路由到
`mock_imitate`，第二次拒绝后说"摄像头画面有问题"。

### 3.3 (C) 在配置里把两个相机的职责区分写死

`configs/g1_brain.yaml::cameras` —— 给整段加块状注释：

```yaml
cameras:
  # === Two cameras, two completely different jobs ==========================
  # head: the robot's own first-person camera, rendered by MuJoCo from a
  #       <camera> attached to torso_link. This is what the robot itself
  #       "sees" while walking. It drives describe_scene, ground constraint
  #       (terrain / obstacles / clear_path), and head-stream YOLO. ALWAYS
  #       enable this in sim — it is the robot's eyes.
  # usb:  a separate camera (laptop webcam by default) pointed at the human
  #       user. It feeds MediaPipe pose detection so the perception layer
  #       can spot the user waving / showing T-pose / etc., which then
  #       triggers mock_imitate (the "user waves → robot waves back" demo).
  #       It is OPTIONAL. Disable it (enabled: false below) if you do not
  #       want / cannot run a webcam — gestures, walking, and describe_scene
  #       all keep working because they only need the head camera. Losing
  #       the USB stream raises an informational warning but never blocks
  #       motion.
  usb:
    enabled: true               # set false to skip the laptop webcam entirely
    ...
  head:
    enabled: true               # leave true — this is the robot's own eyes
    ...
    # To inspect the rendered head view live, run:
    #   python -m g1_brain.apps.perception_debug --show
```

不想看到 `WARNING watchdog usb_frame tripped` 那行日志的话，把
`cameras.usb.enabled: false` 即可，整个 USB 子系统都不会启动，看门狗也不会
trip（虽然现在 trip 也不挡动作了）。

### 3.4 (D) 新回归测试

`g1_brain/tests/test_watchdogs.py` 加两个：

- **`test_informational_trip_does_not_propagate_to_supervisor`** —— 直接调
  `wd._set_trip("usb_frame", "...", emergency=False)`，断言 supervisor 的
  `_watchdog_trips` 里**没有** `usb_frame`。同时调一个 emergency=True 的
  `lowstate`，断言**有**，确保改动没把 emergency 通路也斩断。
- **`test_emergency_clear_propagates_to_supervisor`** —— 调
  `wd._set_trip("lowstate", ..., emergency=True)` 然后 `wd._clear_trip("lowstate")`，
  断言 supervisor 端 trip 已清空（防止 emergency 路径在改动里被误伤）。

## 4. 指挥相机 / 看机器人自己看到什么的命令大全

这是用户最关心的部分。下面把"机器人能看到什么"分成 5 类来讲，每一类都给出
**具体 shell 命令** + **看到什么** + **为什么需要 / 不需要 MuJoCo 在跑**。

> 所有 g1_brain 命令都假设你已经 `conda activate agi` 并 `cd ~/unitree/unitree-notes/g1_brain`。
> MuJoCo 那条假设你已经 `conda activate unitree`（不同 env，因为 mujoco 版本 pin 不同）。

### 4.1 **`perception_debug --show`** —— 最直接：看头相机和 USB 相机两路实时画面

```bash
conda activate agi
cd ~/unitree/unitree-notes/g1_brain
python -m g1_brain.apps.perception_debug --show
```

会做两件事：
1. **终端 2 Hz 打印** `SceneStateBus.snapshot().summary_for_llm()`，里面有
   `nearest_obstacle_m`、`clear_path`、`surface_tilt_deg`、`user_gesture` 等等。
   就是 LLM 调 `query_scene_state` 看到的同一个 dict。
2. **弹出 cv2 窗口**：
   - **`head` 窗口** —— **机器人自己的眼睛**。从 MuJoCo 渲染的 RGB，叠加 YOLO
     检测框（绿色矩形 + 类名 + 距离 m）。
   - **`usb` 窗口** —— 笔记本摄像头看到的画面，叠加 YOLO 框 + MediaPipe Pose
     的 33 个关键点（黄色圆点）+ 当前手势识别结果（如果置信度 > 阈值）。

按 `q` 关闭窗口；`Ctrl-C` 退掉进程。

**前置依赖**：
- 想看 `head` 窗口里有内容 → MuJoCo 仿真器（`unitree_mujoco.py`）必须在跑，
  否则相机渲染从默认 keyframe pose 出帧（机器人定格姿态）。
- 想看 `usb` 窗口里有内容 → 要么 `cameras.usb.source: teleimager` + teleimager
  服务在跑，要么改成 `cv2` 让它直接打开 `/dev/video0`。
- **不需要** OpenAI API key、**不需要** combo controller、**不需要** DDS 完整
  握手。`perception_debug` 是纯感知子图。

实际窗口示例（控制台）：
```text
20:30:01 INFO g1_brain.perception.mujoco_head_cam: synthesized head camera 'head_camera' on body 'torso_link' at pos=(0.08, 0.0, 0.45) fovy=60.0°
20:30:01 INFO g1_brain.perception.object_detector: yolo worker started: source=head
20:30:01 INFO g1_brain.perception.object_detector: yolo worker started: source=usb
{'persons_visible': 1, 'nearest_obstacle_m': 1.42, 'clear_path': True, 'surface_tilt_deg': 1.8, 'user_gesture': None}
```

### 4.2 **不带 `--show`** —— 终端文本巡检（无显示器 / SSH 场景）

```bash
python -m g1_brain.apps.perception_debug
```

只打印 `summary_for_llm()`，没有 cv2 窗口。在 SSH / WSL2 没接 X server / 服务器
机器上，这是确认"感知到底活着没"的最快方式。`Ctrl-C` 退出。

### 4.3 **MuJoCo 自带的全局视角** —— 看仿真世界本身（不是机器人视角）

```bash
conda activate unitree
export MUJOCO_GL=glfw         # WSLg 必须；裸 Linux 也行
cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
python unitree_mujoco.py
```

弹出 MuJoCo 自带的 GLFW viewer：第三人称鸟瞰整个场景，可以鼠标拖动相机、滚轮
缩放、右键平移。

它和 4.1 的 `head` 窗口是**两个完全不同的视角**：
- `unitree_mujoco.py` 的 viewer：**第三人称**外部观察者视角（"上帝视角"）。
- `perception_debug --show` 的 `head` 窗口：**第一人称**机器人自己的眼睛
  （`torso_link` 上 +X 0.08、+Z 0.45 那个虚拟相机渲染出来的）。

viewer 里有用的快捷键（已知）：
- `9`：toggle 弹簧带（elastic band）开关。开着时机器人挂在空中；关掉就让它
  自然落到地面（fall test）。
- `7` / `8`：弹簧带长度 ±0.1 m。
- `Tab`：切换 free / fixed camera。
- 鼠标左拖：旋转相机；右拖：平移；滚轮：缩放。

### 4.4 **`safety_debug`** —— 看安全规则在你的配置下会怎么判

```bash
python -m g1_brain.apps.safety_debug
```

不看相机。它**用 mock 的 SceneStateBus / RobotStateBus / FSM** 跑一组场景，检查
SafetySupervisor 在你当前 `safety.*` 阈值下会接受 / 拒绝哪些 (tool, args)。
A/B 调 `vx_max` / `min_obstacle_m` / `gravity_z_min` 之类的时候用。

也可以塞自定义场景：
```bash
python -m g1_brain.apps.safety_debug --scenarios ./my_scenarios.json
```

### 4.5 **`skill_debug`** —— 不开相机直接键盘驱动机器人挥手 / 走路

```bash
python -m g1_brain.apps.skill_debug
```

把 ComboController + SkillServer 跑起来等 stdin。数字键直接触发：
- `1` / `2` / ... `8`：8 个 RL-tolerant 手势（wave_right / wave_left / hands_up /
  t_pose / salute / clap / guard / punch_combo）。
- 其他映射看 `skill_debug.py` 的 keymap。
- `q`：干净退出。

**完全不依赖 LLM、不依赖摄像头**，是验证"挥手通路本身正常吗"最干净的办法。本次
phase 5 修复后，即使 `usb_frame` watchdog 在 trip，`skill_debug` 里按 `1` 也能
正常触发挥手（之前是按了没反应、终端打印 `safety rejected ...`）。

### 4.6 **`describe_scene` / `query_scene_state`** —— 让机器人自己用语言描述它看到什么

这两个**不是**独立命令，而是 LLM 在 agent_main 里能调的工具。语音里说：

> 看一下你前面有什么 / What do you see ahead?

LLM 会调 `describe_scene`，SkillServer 把头相机当前帧（base64-jpeg）+ 一句
prompt 发给 GPT-5.5 vision，让它出一两句中文描述。注意：

- **优先用 head 相机**，没有 head 才回落到 USB（参见
  `skill_server.py::_latest_jpeg_b64_preferring_head`）。
- 在 MuJoCo 仿真里，描述出来的是**仿真世界**里的内容（地砖、墙体、其它仿真对象）。

```bash
# 普通启动后说话即可：
python -m g1_brain.apps.agent_main
# 然后 "Hi Sparky" → "你前面看到什么"
```

`query_scene_state` 给的是**结构化** dict（不是图像）：感知子图融合出来的
`persons_visible / nearest_obstacle_m / nearest_person_m / clear_path /
surface_tilt_deg / user_gesture / warnings`。LLM 可以读但不显示给你；想看的话
跑 §4.1 的 `perception_debug` 直接打印。

### 4.7 **存一帧 head 相机 jpeg 做截图分析**

没有现成命令，但 3 行 python 就够，适合写自己的测试：

```bash
conda activate agi
python - <<'PY'
import base64, time
from g1_brain.perception.cameras import CameraHub
import yaml, os
cfg = yaml.safe_load(open(os.path.expanduser("~/unitree/unitree-notes/g1_brain/configs/g1_brain.yaml")))
cfg = {k: v for k, v in cfg.items()}
hub = CameraHub(cfg.get("cameras", {}), subscribe_dds=False)
time.sleep(2.0)  # 等渲染线程出第一帧
b64 = hub.latest_head_jpeg_b64()
if b64 is None:
    print("no head frame yet — is MuJoCo running?")
else:
    open("/tmp/head_snapshot.jpg", "wb").write(base64.b64decode(b64))
    print("saved /tmp/head_snapshot.jpg")
hub.close()
PY
```

跑完 `xdg-open /tmp/head_snapshot.jpg`（或用 VS Code 之类的图像查看器打开）就能
看到机器人此刻的第一人称截图。

### 4.8 **改 head 相机的位置 / 朝向 / 视场角**

不是命令而是配置，但 phase 5 既然全在讲"机器人看什么"就一并写清楚。
`configs/g1_brain.yaml::cameras.head`：

| YAML key | 含义 | 默认 |
| --- | --- | --- |
| `attach_body` | 相机刚性挂在哪个 body 上 | `torso_link` |
| `attach_pos` | 该 body 局部坐标系下的安装位置（米） | `[0.08, 0.0, 0.45]` |
| `attach_xyaxes` | 相机朝向（先 x 轴再 y 轴在 body frame 里的方向） | `[0,-1,0, 0,0,1]`（向 +X 看） |
| `attach_fovy` | 垂直视场角（度） | `60.0` |
| `width` / `height` | 渲染分辨率 | `640 / 480` |
| `poll_hz` | 渲染线程频率 | `20` |

例：装到机器人头部往下看一点（让它看脚前的地面）：
```yaml
head:
  enabled: true
  attach_body: torso_link
  attach_pos: [0.08, 0.0, 0.50]      # 抬高一点点
  attach_xyaxes: [0,-1,0,  -0.3,0,0.95]  # 往下倾 ~17°
```
改完跑 `perception_debug --show` 立刻能看到效果。

### 4.9 **彻底关掉笔记本摄像头**

如果你完全不打算用 mock_imitate 自动镜像（本来就没这个需求 / 没接 USB 摄像头），
最干净的做法：

```yaml
# configs/g1_brain.yaml
cameras:
  usb:
    enabled: false
```

效果：
- `CameraHub._build_usb` 返回 `None`，`UsbCamera` 不构造，teleimager 客户端不连。
- `PerceptionRunner._frame_age_loop` 跳过 USB 那一支。
- `usb_frame` watchdog 仍然会 trip（年龄是 inf），日志里仍然有那行 WARNING，但
  **不挡动作**（phase 5 修复保证）。

如果连日志里那行 WARNING 都不想要，最干净是把 `usb_frame` watchdog 整个跳掉，
但那需要另外加个 `cameras.usb.enabled` → 决定 watchdog 是否注册的逻辑，超出了
phase 5 的范围。当前 WARNING 是无害的。

### 4.10 **完整 4 终端启动顺序**（参考）

```bash
# Terminal 1 — MuJoCo 物理 + 第三人称 viewer
conda activate unitree
export MUJOCO_GL=glfw
cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
python unitree_mujoco.py

# Terminal 2 — USB 相机服务（如果你想用 USB；否则跳过）
conda activate unitree
cd ~/unitree/unitree-notes/teleimager
python -m teleimager.image_server

# Terminal 3 — E-stop 监听器（独立进程，按 ESC 触发紧急停止）
conda activate agi
cd ~/unitree/unitree-notes/g1_brain
python -m g1_brain.safety.estop_listener

# Terminal 4 — 主 agent
conda activate agi
cd ~/unitree/unitree-notes/g1_brain
export OPENAI_API_KEY=sk-...
python -m g1_brain.apps.agent_main
# (本次 phase 5 之后默认就是 active 模式；想要 y/N 确认仍可加 --mode confirm，但
#  注意它阻塞语音控制——见 phase 3 文档)
```

想"看机器人自己看到什么"，再开第 5 个 terminal 跑 §4.1 的 `perception_debug --show`
即可——它和 agent_main 共用同一个 SceneStateBus 实例时不会，但**两个独立进程**
各自起一份感知子图也没问题（各自的 CameraHub，互不干扰）。

## 5. Files changed

```
g1_brain/safety/watchdogs.py              ~10 行：_set_trip / _clear_trip 加 emergency 闸
g1_brain/brain/prompts.py                 重写 head/USB 角色段 + 新增 2 条 hard rule
configs/g1_brain.yaml                     cameras 段加块状注释，标 head/usb 职责
g1_brain/tests/test_watchdogs.py          新增 _CaptureSupervisor 桩 + 2 个测试
docs/g1-fix-phase5.md                     本文档
```

## 6. Verification

```bash
$ /home/helios/miniforge3/envs/agi/bin/python -m pytest tests/ 2>&1 | tail -5
tests/test_vertical_slice.py .......                                     [ 97%]
tests/test_watchdogs.py .....                                            [100%]

============================= 219 passed in 2.67s ==============================
```

新增 2 个测试 + 老 217 个测试全过（phase 4 没新增测试，所以从 phase 3 的 217
直接到 phase 5 的 219）。

聚焦 phase 5 涉及的两组：
```bash
$ python -m pytest tests/test_watchdogs.py tests/test_safety_supervisor.py -v
tests/test_watchdogs.py::test_recovery_to_standing_rearms_boot_grace PASSED
tests/test_watchdogs.py::test_other_transitions_do_not_rearm_grace PASSED
tests/test_watchdogs.py::test_informational_trip_does_not_propagate_to_supervisor PASSED  # 新
tests/test_watchdogs.py::test_emergency_clear_propagates_to_supervisor PASSED              # 新
tests/test_watchdogs.py::test_unsubscribe_on_stop PASSED
tests/test_safety_supervisor.py::test_watchdog_trip_flag_blocks_motion PASSED  # 关键回归
... 共 37 PASSED
```

特别注意 `test_watchdog_trip_flag_blocks_motion` 仍然通过——它直接调
`supervisor.set_watchdog_trip("lowstate", ...)` 然后断言 `walk` 被拒。这证明
emergency 通路完全没有被改动；只有 watchdog manager 这一侧对 `usb_frame` 的同步
被关掉了。

### 手工验证流程

```bash
# 1. 不开 teleimager（即不开 USB 相机服务），启 MuJoCo + agent
#    Terminal 1:
conda activate unitree && export MUJOCO_GL=glfw && \
    cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python && python unitree_mujoco.py
#    Terminal 4:
conda activate agi && cd ~/unitree/unitree-notes/g1_brain && \
    export OPENAI_API_KEY=sk-... && python -m g1_brain.apps.agent_main

# 2. 等 fsm: BOOT -> STANDING -> ENGAGED 出现
# 3. 终端日志里**会**仍然看到 "watchdog usb_frame tripped: age=infs" —— 这是 informational，
#    是预期的、无害的。
# 4. 说话：
#    "Hi Sparky"
#    "Wave your hand."
# 5. 期望：LLM 调 gesture(wave_right)，supervisor 通过，机器人在 MuJoCo
#    第三人称 viewer 里实际挥手。
# 6. 不再出现 "可能摄像头画面有问题" 这种回答——LLM 的新 prompt 明确禁止它把
#    usb_frame 错误归因为相机故障；并且现在根本不会出现这个错误了。
```

成功的判据是：

- 终端里**有** `WARNING watchdog usb_frame tripped: age=infs`（告知性日志）。
- 终端里**没有** `safety rejected gesture(...): watchdog tripped: usb_frame=...`。
- MuJoCo viewer 里看到机器人手臂动了。

如果你现在开第 5 个终端跑 `python -m g1_brain.apps.perception_debug --show`，
`head` 窗口会显示机器人挥手过程中第一人称视角；`usb` 窗口因为没开 teleimager
会保持空白（这是预期的）。

## 7. Out of scope

- 把 `usb_frame` watchdog 完全跳过（让 `cameras.usb.enabled: false` 也连带把
  watchdog 注册都关掉）—— 这只是消除一行无害日志的 nice-to-have，不属于本次
  bug 范围。
- 用 RealSense / 真机相机替换 `MuJoCoHeadCamera` —— 见
  [`how_to_run.md`](how_to_run.md) §6。
- 让 `mock_imitate` 在没有 USB 视觉源时给出**专门的**拒绝原因（"USB camera
  unavailable, gesture mirroring disabled"）而不是 fall through 到通用拒绝
  —— 设计改动，不是 bug。
