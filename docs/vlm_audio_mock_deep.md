# Unitree G1：VLM 视觉、语音交互与“模仿人类动作”系统研究方案

**文件名**：`vlm_audio_mock.md`  
**研究日期**：2026-05-03  
**目标机器人**：Unitree G1 / G1 EDU，优先假设你已经能通过 Unitree SDK2 或 ROS2 包装完成走、跑、停止、站立、转向、静态动作等高层 primitive。  
**核心目标**：让 G1 具备“看见 → 理解 → 说话 → 调用安全动作 → 逐步模仿人”的能力。

---

## 0. 结论先行

你想做的方向是可行的，但需要分层实现，而不是把 GPT / VLM 直接接到底层电机。

最合理的路线是：

```text
摄像头 / RealSense / TeleImager / ROS2 Image
        ↓
本地快速感知：人/物体/深度/障碍物/地面约束
        ↓
OpenAI GPT-5.5 Vision / 其他 VLM：慢速语义理解、任务规划、场景解释
        ↓
安全监督器：状态机、限速、碰撞保护、姿态约束、人工授权、E-stop
        ↓
技能服务器：walk_to / turn / stop / say / wave / reach / grasp / imitate_xxx
        ↓
Unitree SDK2 / ROS2 / RL policy / LeRobot policy / motion retargeting policy
```

**最重要原则**：

> GPT / VLM 只负责“理解、规划、选择动作”，不能直接输出关节角、力矩、DDS 原始消息或底层电机命令。

你的当前能力已经能做走跑和静态动作，所以你下一步不应该先训练一个巨大的端到端模型，而应该先做一个 **VLM + Audio + Safe Skill Layer 的 mock 系统**：

1. G1 能把相机画面发给 GPT-5.5 Vision。
2. GPT-5.5 只输出结构化 JSON，例如 `say`、`turn_left`、`walk_forward`、`stop`。
3. 你的安全层检查 JSON 是否允许执行。
4. 技能服务器调用你已经实现的动作 demo。
5. G1 用 OpenAI TTS 或 Realtime API 说话。
6. 后续再用 XR 遥操作、LeRobot、GMR、RL tracking policy 做真正的 imitation learning / human motion retargeting。

---

## 1. 你真正要做的系统，不是“给机器人接一个聊天模型”

很多人第一次做“机器人 + GPT / VLM”时会犯一个错误：把问题想成“机器人把摄像头发给 GPT，然后 GPT 告诉机器人怎么动”。

对于 G1 这种人形机器人，正确理解应该是：

```text
GPT / VLM 是高层大脑
本地感知是反射系统
安全层是脊髓和保护机制
动作 primitive / RL policy 是肌肉记忆
SDK2 / ROS2 / DDS 是神经信号通道
```

因此，你未来系统至少要分成 6 个模块：

| 模块 | 作用 | 推荐实现 |
|---|---|---|
| Camera / Image Service | 采集 G1 视角或外接相机画面 | `teleimager`、OpenCV、RealSense、ROS2 Image Topic |
| Local Perception | 低延迟检测人、障碍物、深度、目标框 | YOLO、SAM、DepthAnything、RealSense depth、AprilTag |
| VLM / LLM Planner | 理解场景、生成任务计划、选择 primitive | OpenAI GPT-5.5 Vision / GPT-5.5 / Realtime API |
| Audio Agent | 语音输入、语音输出、对话 | OpenAI Realtime API、Speech-to-Text、Text-to-Speech |
| Safety Supervisor | 动作过滤、限速、禁区、E-stop、看门狗 | Python/C++ 状态机 + 手柄/硬件急停 |
| Skill Server | 把高层动作映射到你已有的 G1 动作 | Unitree SDK2、ROS2、RL policy、LeRobot policy |

这和你列出的 B/C/D 三条线是兼容的：

- **B 强化学习 / Locomotion / Sim2Real**：提供稳定 locomotion primitive。
- **C 遥操作 / 数据采集 / 模仿学习**：提供 manipulation / imitation policy。
- **D 摄像头 / 视觉 / AI**：提供高层语义理解和人机交互。

---

## 2. GPT-5.5 Vision 是否能接入 G1？可以，但要这样接

### 2.1 OpenAI 侧能力判断

OpenAI 官方模型说明显示，`gpt-5.5` 支持 Responses API、Chat Completions、Batch、streaming、function calling、structured outputs、image input 等能力。`gpt-5.5 pro` 也支持图像输入和结构化输出，但更适合复杂推理、审查、调试和规划，不适合放进高频控制环。OpenAI 的视觉文档也说明 Responses API 可以接收图片输入，并支持 `input_image`、`image_url` / base64 data URL、`detail` 等参数。

因此结论是：

> **可以把 G1 摄像头画面接入 GPT-5.5 Vision。**

但是，它不应该运行在 50 Hz、100 Hz 或 500 Hz 的控制环里，而应该运行在：

```text
0.5 Hz ~ 2 Hz：高层语义理解 / 任务规划
5 Hz ~ 10 Hz：如果是简单视觉问答或状态更新，可谨慎使用
10 Hz ~ 30 Hz：应交给本地 YOLO / depth / obstacle detector
50 Hz+：必须由本地控制器、RL policy、MPC、SDK motion service 处理
```

### 2.2 模型分工建议

| 任务 | 推荐模型 / 方法 | 原因 |
|---|---|---|
| 场景理解、目标选择、自然语言解释 | GPT-5.5 Vision | 支持图像输入，适合语义理解和规划 |
| 复杂任务分解、离线策略审查 | GPT-5.5 Pro | 更强推理，但成本/延迟更高 |
| 实时语音对话 | OpenAI Realtime API | 低延迟语音到语音，多模态会话 |
| 语音合成 | `gpt-4o-mini-tts` / Realtime audio output | 可控语气、语速、情绪，支持流式音频 |
| 语音识别 | `gpt-4o-transcribe` / Realtime transcription | 适合命令识别、对话转写 |
| 高频避障 | 本地 YOLO / depth / RealSense / LiDAR | 云端 VLM 延迟不可控 |
| 运动控制 | Unitree SDK2 / RL policy / LeRobot policy | 控制必须本地、安全、确定性强 |

### 2.3 最推荐的接入方式

```text
TeleImager / OpenCV / ROS2 Image
        ↓ JPEG 压缩 / resize
Base64 image data URL
        ↓
OpenAI Responses API: model = gpt-5.5
        ↓
结构化 JSON 输出
        ↓
Safety Supervisor
        ↓
Skill Server
```

你不要让 GPT 直接输出类似：

```json
{
  "joint_1": 0.13,
  "joint_2": -0.42,
  "torque": 1.5
}
```

而应该只允许：

```json
{
  "intent": "approach_person",
  "actions": [
    {"type": "say", "text": "我看到你了，我会慢慢走近。"},
    {"type": "turn", "yaw_deg": 10},
    {"type": "walk_forward", "speed_mps": 0.15, "duration_s": 1.0},
    {"type": "stop"}
  ],
  "safety_notes": ["person_detected", "low_speed", "requires_clear_path"]
}
```

---

## 3. 推荐总体架构：Slow Brain + Fast Reflex + Safe Skill

### 3.1 逻辑架构

```text
┌──────────────────────────────────────────────────────────────┐
│                         User / Human                         │
│       voice command / gesture / demonstration / object        │
└──────────────────────────────────────────────────────────────┘
                                ↓
┌──────────────────────────────────────────────────────────────┐
│                     Sensor Input Layer                        │
│  G1 camera / RealSense / USB camera / mic / remote joystick   │
└──────────────────────────────────────────────────────────────┘
                                ↓
┌──────────────────────────────────────────────────────────────┐
│                    Perception Layer                           │
│  TeleImager / ROS2 Image / OpenCV / YOLO / depth / pose        │
└──────────────────────────────────────────────────────────────┘
                                ↓
┌──────────────────────────────────────────────────────────────┐
│                    AI Reasoning Layer                         │
│  GPT-5.5 Vision / GPT-5.5 / Realtime API / behavior tree       │
└──────────────────────────────────────────────────────────────┘
                                ↓ structured action JSON
┌──────────────────────────────────────────────────────────────┐
│                    Safety Supervisor                          │
│  whitelist / speed limit / watchdog / posture check / E-stop   │
└──────────────────────────────────────────────────────────────┘
                                ↓ approved skill call
┌──────────────────────────────────────────────────────────────┐
│                    Skill Server                               │
│  say / stop / walk / turn / reach / wave / grasp / policy      │
└──────────────────────────────────────────────────────────────┘
                                ↓
┌──────────────────────────────────────────────────────────────┐
│                    Unitree G1 Runtime                         │
│  SDK2 / DDS / ROS2 / sport mode / RL policy / LeRobot policy   │
└──────────────────────────────────────────────────────────────┘
```

### 3.2 控制频率分层

| 层级 | 频率 | 谁负责 | 说明 |
|---|---:|---|---|
| 电机控制 / 关节闭环 | 100 Hz ~ 1000 Hz | Unitree 控制器 / policy | GPT 绝不能参与 |
| Locomotion policy / SDK motion service | 20 Hz ~ 100 Hz | 本地 policy / SDK | 走、跑、转向、平衡 |
| 避障 / 姿态保护 / watchdog | 10 Hz ~ 50 Hz | 本地安全层 | 任何 AI 命令都必须经过这里 |
| 视觉检测 / depth / tracking | 5 Hz ~ 30 Hz | 本地 CV | 人、障碍物、目标框 |
| VLM 场景理解 | 0.5 Hz ~ 2 Hz | GPT-5.5 Vision | 语义理解，不做闭环控制 |
| 任务规划 / 对话 | 0.2 Hz ~ 2 Hz | GPT-5.5 / Realtime | 规划和交互 |

---

## 4. 代码仓库研究：哪些仓库应该看，分别用来做什么

### 4.1 Unitree SDK2 / SDK2 Python

#### 价值

`unitree_sdk2` 是 Unitree SDK version 2，支持基于 DDS 的通信，官方 README 给出了 Ubuntu 20.04、GCC 9.4 等构建环境信息。`unitree_sdk2_python` 的 README 明确说明 Python SDK 与 C++ SDK2 一致，机器人状态和控制可以通过 request-response 或 topic pub/sub 完成，并提供 high-level control、low-level control、front camera、obstacle avoidance switch、VUI volume/light control 等示例。

#### 你要重点看

```text
unitree_sdk2_python/example/g1/
unitree_sdk2_python/example/g1/high_level/
unitree_sdk2_python/example/g1/low_level/
unitree_sdk2_python/example/g1/audio/
unitree_sdk2_python/example/g1/front_camera/
unitree_sdk2_python/example/g1/vui/
```

#### 用法定位

- **高层运动**：优先用 high-level / sport / motion service。
- **前置相机**：可以先用 SDK2 Python front camera 示例做最小闭环。
- **音量 / 灯光**：VUI 示例可以设置音量和亮度，但不要把它误认为完整语音代理。
- **底层电机**：只建议用于你已经理解并且有保护措施的实验；VLM/LLM 不应该直接碰。

#### 社区经验重点

GitHub issue 中有人反馈：G1 进入 debug mode 后 high-level AI sport client 被关闭，导致 RPC SDK 运动命令不响应；重启或恢复 motion service 才能继续使用高层动作。另有用户反馈 WaveHand / ShakeHand 在某些 SDK/API/模式下无法触发，远程控制器能触发但 SDK 报错。这说明：

```text
同一个动作是否可用，取决于：
1. 机器人版本 / firmware
2. EDU 与否
3. 当前 mode
4. sport service 是否运行
5. Python SDK / C++ SDK / ROS2 封装是否暴露了该动作
```

所以你的 `SkillServer` 必须对每个 primitive 做运行前检查，而不是假设所有官方动作永远可用。

---

### 4.2 teleimager：图像服务核心仓库

#### 价值

`unitreerobotics/teleimager` 是官方图像服务仓库。README 描述它可以从 UVC、OpenCV、RealSense 捕获图像，并通过 ZeroMQ / WebRTC 发布图像；它被 `xr_teleoperate` 使用。仓库还说明支持多相机、WebRTC、ZMQ PUB-SUB、ZMQ REQ-REP 配置命令、分辨率/FPS 配置、triple ring buffer 等。

#### 为什么它对你很重要

如果你要做 GPT-5.5 Vision，第一步不是写机器人控制，而是稳定拿到图像流：

```text
G1 camera / RealSense
        ↓
teleimager image_server
        ↓
ZMQ image_client / WebRTC client / OpenCV consumer
        ↓
resize + JPEG encode
        ↓
GPT-5.5 Vision
```

#### 推荐实践

- 先用 ZMQ PUB-SUB 拿最新帧。
- 不要把所有帧都发给 GPT；只抽帧，例如 1 FPS 或 2 FPS。
- 高频帧给本地 CV 模型做检测和避障。
- 给 GPT 的图像尽量 resize，例如宽边 768 或 1024。
- 对于空间判断，保留相机内参、深度或本地检测结果，不要完全依赖 VLM 推测距离。

---

### 4.3 xr_teleoperate：遥操作、相机、数据记录入口

#### 价值

`unitreerobotics/xr_teleoperate` 是官方 XR 遥操作仓库，README 说明它支持通过 Apple Vision Pro、PICO 4 Ultra Enterprise、Meta Quest 3 等 XR 设备遥操作 G1，支持 G1 29DoF、23DoF、H1、Dex3、Inspire、BrainCo 等。文档还给出了 `--record` 数据记录、仿真模式、物理部署 image service 启动流程等。

#### 对你的意义

你想做“AI + 摄像头 + G1”，这个仓库是非常重要的入口，因为它天然包含：

```text
XR 设备 / 摄像头 / 图像服务
        ↓
人类遥操作
        ↓
数据记录
        ↓
LeRobot / imitation learning
        ↓
真机策略测试
```

#### 你要重点复用

- `teleop_hand_and_arm.py`
- `--record` 数据采集流程
- image service physical deployment
- `episode_writer.py`
- filters / visualizer
- 和 `unitree_lerobot` 的数据格式衔接

#### 社区经验重点

Issue 中有人反馈 Vision Pro 上 WebRTC / 证书 / 黑屏 / DDS 连接可能出问题；也有人反馈 Inspire FTP 手部配置会导致程序退出。另有 `unitree_lerobot` issue 显示，有用户已经成功用 Meta Quest 3 采集数据、转成 LeRobot 数据格式并跑通训练 pipeline，但在 eval 阶段遇到 Hugging Face API 限流和 URDF 缺失问题。

这说明：

```text
XR 遥操作路线是可行的，
但部署时最容易卡在：
1. HTTPS / WebRTC 证书
2. DDS 网络
3. 设备 IP / 网卡
4. 末端执行器型号
5. URDF / 资产路径
6. 数据格式转换
```

---

### 4.4 LeRobot / Unitree LeRobot：模仿学习路线

#### 价值

Hugging Face LeRobot 官方文档已经明确提到支持 Unitree G1，可进行 teleoperate、训练 locomani­pulation policies、仿真测试，并区分 29DoF 和 23DoF 版本。`unitreerobotics/unitree_lerobot` 和 `unitreerobotics/unitree_IL_lerobot` 是你后续做双臂、灵巧手、数据训练、策略测试和部署的重要仓库。

#### 推荐路线

```text
Step 1：用 xr_teleoperate 采集人类演示数据
Step 2：转换成 LeRobot 数据集格式
Step 3：先训练一个非常小的任务，例如：挥手 / 指向 / 抓取固定物体
Step 4：仿真评估
Step 5：低速真机测试
Step 6：加入视觉条件和语音任务条件
```

#### 为什么它比直接 VLM 控制更适合“模拟人做什么”

“模拟人做什么”分两类：

1. **语义模仿**：人挥手，G1 也挥手；人指左边，G1 转向左边。
2. **运动轨迹模仿**：人怎么摆手，G1 尽量复现相似关节轨迹。

VLM 适合做第一类，不适合直接做第二类。第二类应该走：

```text
人类动作数据 / XR / mocap / BVH / SMPL-X
        ↓
retarget 到 G1
        ↓
仿真验证
        ↓
tracking policy / imitation policy
        ↓
真机低速部署
```

---

### 4.5 GMR：人类动作重定向到 G1

#### 价值

`Roboparty/GMR` 支持把 SMPL-X、AMASS、BVH、FBX、PICO 等人体动作数据重定向到 Unitree G1，包括 29DoF 和带手的 43DoF 版本。它非常适合你想做的“让 G1 模拟我们人做什么”。

#### 用法定位

| 目标 | 是否适合 GMR | 说明 |
|---|---|---|
| 人挥手 → G1 挥手 | 适合 | 可 retarget upper body motion |
| 人跳舞 → G1 学跳舞 | 适合，但要仿真验证 | 需要平衡和接触约束 |
| 人走路 → G1 复现步态 | 不建议直接真机 | 应用 RL tracking policy |
| 人做复杂全身动作 | 研究级 | 需要动力学约束、安全过滤、仿真大量验证 |
| 手部灵巧操作 | 适合与 LeRobot 结合 | 需要手部硬件、数据和策略 |

#### 推荐做法

```text
GMR retarget motion
        ↓
MuJoCo / IsaacLab 仿真检查
        ↓
转换成 reference motion
        ↓
RL tracking policy 训练
        ↓
Sim2Sim
        ↓
限速真机部署
```

不要把 retarget 出来的关节轨迹直接无保护地下发到真机。

---

### 4.6 RL Gym / RL Lab / MJLab：动作技能 primitive 的来源

你列出的 B 线非常关键，尤其是：

- `unitree_rl_gym`：官方 RL 环境，支持 Go2、H1、H1_2、G1，工作流包括 train / play / sim2sim / sim2real。
- `unitree_rl_lab`：基于 IsaacLab，支持 G1-29dof。
- `unitree_rl_mjlab`：基于 MuJoCo，支持 G1、G1 tracking 等任务。
- `mujocolab/g1_spinkick_example`：G1 双旋踢示例，展示 reference motion、训练、ONNX checkpoint、真机部署思路。

#### 你应该怎样使用 RL 仓库

不要一开始就把 GPT 接 RL policy。你应该先把 RL policy 封装成动作 primitive：

```python
walk_forward(speed=0.2, duration=1.0)
turn_left(yaw_rate=0.3, duration=0.8)
track_motion(name="wave_001", speed_scale=0.5)
stop()
recover_stand()
```

然后让 GPT 只能调用这些 primitive。

#### 社区经验重点

GitHub issues 里已经有很多 sim2real 问题，例如：

- sim2sim 可行但 sim2real 手臂/腿卡住或姿态异常。
- 29DoF 改 23DoF 时 motor ID、关节映射、配置文件容易出错。
- 部署时机器人抖动、无 joystick 自动前进、velocity mode 不响应。
- deployment YAML、关节速度、初始姿态、firmware / mode 都会影响结果。

所以你的 AI 系统里，RL policy 必须被当作“经过验证的技能”，而不是“随便调用的黑箱”。

---

### 4.7 GalacTechNyc/unitree-g1-autonomous：VLM 控制 G1 的社区参考

这个仓库是目前比较贴近你想法的社区项目之一。README 描述其使用 Gemini API 做 G1 自主导航，包括实时相机分析、障碍物检测、安全层、10Hz 控制循环、1Hz AI 查询、仿真模式、日志系统等。

它的意义不是让你照抄 Gemini，而是它验证了一个正确架构：

```text
高频控制循环 ≠ 高频 AI 查询
```

也就是：

```text
10 Hz 控制循环：本地执行和安全
1 Hz AI 查询：高层视觉理解和决策
```

你接 OpenAI GPT-5.5 Vision 时，也应该采用类似结构。

---

### 4.8 UnifoLM-VLA / HumanoidVLM / NaVILA：研究趋势

Unitree 在 2026 年公开了 `unifolm-vla`，定位为 Vision-Language-Action 模型，目标是通过机器人操作数据持续预训练，把 VLM 推向 embodied brain。另有 HumanoidVLM 等研究展示了在 Unitree G1 上用 egocentric RGB + VLM / RAG 选择控制参数的思路。

这些说明你的方向是对的：未来的人形机器人会越来越多使用 VLM / VLA。

但对你当前阶段来说，最实际的路线仍然是：

```text
VLM 负责语义层
LeRobot / RL / SDK primitive 负责动作层
Safety Supervisor 负责中间强约束
```

---

## 5. 你应该实现的第一个版本：VLM + Audio + Mock Skill Layer

### 5.1 第一个版本的目标

第一个版本不要追求“完全自主”。目标应该是：

```text
G1 能看见画面
G1 能听懂或接收文字命令
G1 能说话
G1 能根据 GPT-5.5 的结构化输出调用你已有的动作 demo
G1 在任何异常时能 stop
```

### 5.2 目录结构建议

```text
g1_vlm_audio_mock/
  README.md
  configs/
    robot.yaml
    safety.yaml
    skills.yaml
    openai.yaml
  apps/
    agent_main.py
    camera_debug.py
    tts_debug.py
    skill_debug.py
  perception/
    teleimager_client.py
    opencv_camera.py
    local_detector.py
    scene_state.py
  llm/
    openai_vlm.py
    prompts.py
    schemas.py
  audio/
    tts_player.py
    stt_client.py
    realtime_voice_agent.py
  g1/
    sdk2_adapter.py
    skill_server.py
    motion_primitives.py
    vui_adapter.py
  safety/
    supervisor.py
    constraints.py
    watchdog.py
  logs/
    episodes/
    vlm_decisions/
    safety_events/
```

### 5.3 技能白名单设计

`configs/skills.yaml`：

```yaml
allowed_skills:
  say:
    max_chars: 120
    allow_when_moving: true

  stop:
    priority: 100
    allow_always: true

  walk_forward:
    max_speed_mps: 0.30
    max_duration_s: 1.50
    requires_clear_path: true
    requires_standing: true

  turn:
    max_yaw_deg: 30
    max_duration_s: 1.50
    requires_standing: true

  wave_hand:
    max_duration_s: 3.00
    requires_standing: true
    requires_not_holding_object: true

  look_at:
    max_yaw_deg: 25
    max_pitch_deg: 15

  reach_pose:
    enabled: false
    reason: "enable only after arm IK and collision checks are validated"

  grasp:
    enabled: false
    reason: "enable only after LeRobot/teleop policy is validated"
```

### 5.4 安全配置建议

`configs/safety.yaml`：

```yaml
robot:
  require_manual_enable: true
  require_estop_ready: true
  default_mode: "observe_only"

motion_limits:
  max_vx_mps: 0.30
  max_vy_mps: 0.10
  max_yaw_rate_radps: 0.40
  max_action_duration_s: 1.50
  max_consecutive_motion_actions: 3

perception_limits:
  min_person_distance_m: 0.80
  min_obstacle_distance_m: 0.60
  require_local_clear_path: true

watchdog:
  command_timeout_ms: 500
  ai_response_timeout_s: 5.0
  stop_on_camera_lost: true
  stop_on_network_lost: true
  stop_on_pose_unstable: true

policy:
  allow_ai_to_move: false  # 初期必须 false，只允许人工确认后执行
  require_human_confirm_for_move: true
  log_every_action: true
```

第一阶段建议：

```text
observe_only → suggest_action → require_human_confirm → execute_safe_skill
```

也就是先让 GPT 说“我建议执行 turn_left”，由你按键确认后再动。

---

## 6. GPT-5.5 Vision 结构化输出设计

### 6.1 Prompt 原则

系统提示词应该非常明确：

```text
你是 Unitree G1 的高层任务规划器。
你不能输出底层电机命令。
你只能从允许的技能列表中选择动作。
任何不确定、危险、遮挡、距离不明、地面不清晰的情况，必须输出 stop 或 ask_human。
移动速度必须保守。
输出必须是 JSON。
```

### 6.2 推荐 JSON schema

```json
{
  "scene_summary": "我看到前方有一个人，地面基本清晰。",
  "risk_level": "low",
  "needs_human_confirmation": true,
  "actions": [
    {
      "type": "say",
      "text": "我看到你了。我会先停在原地。"
    },
    {
      "type": "stop"
    }
  ],
  "reason": "前方有人，距离无法仅凭单目图像可靠估计，因此不主动靠近。"
}
```

### 6.3 Python：调用 GPT-5.5 Vision 的示例

> 注意：下面是架构示例。你需要把 `frame_b64` 替换为 TeleImager / OpenCV / ROS2 取到的 JPEG base64。

```python
import base64
import json
from openai import OpenAI

client = OpenAI()

SYSTEM_PROMPT = """
你是 Unitree G1 的高层视觉任务规划器。
你只能输出 JSON，不能输出底层电机命令。
允许动作只有：say, stop, walk_forward, turn, wave_hand, ask_human。
如果距离、障碍物、地面、人体位置不确定，必须保守，优先 stop 或 ask_human。
"""

ALLOWED_SKILLS = {
    "say": {"max_chars": 120},
    "stop": {},
    "walk_forward": {"max_speed_mps": 0.3, "max_duration_s": 1.5},
    "turn": {"max_yaw_deg": 30},
    "wave_hand": {"max_duration_s": 3.0},
    "ask_human": {},
}


def analyze_frame_with_gpt55(frame_b64: str, user_goal: str) -> dict:
    prompt = f"""
用户目标：{user_goal}

允许技能：
{json.dumps(ALLOWED_SKILLS, ensure_ascii=False)}

请根据图像输出严格 JSON：
{{
  "scene_summary": str,
  "risk_level": "low" | "medium" | "high",
  "needs_human_confirmation": bool,
  "actions": [
    {{"type": "say", "text": str}} |
    {{"type": "stop"}} |
    {{"type": "walk_forward", "speed_mps": float, "duration_s": float}} |
    {{"type": "turn", "yaw_deg": float}} |
    {{"type": "wave_hand"}} |
    {{"type": "ask_human", "question": str}}
  ],
  "reason": str
}}
"""

    response = client.responses.create(
        model="gpt-5.5",
        input=[
            {
                "role": "system",
                "content": [{"type": "input_text", "text": SYSTEM_PROMPT}],
            },
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {
                        "type": "input_image",
                        "image_url": f"data:image/jpeg;base64,{frame_b64}",
                        "detail": "low",
                    },
                ],
            },
        ],
    )

    # 实际工程里建议使用 structured outputs / JSON schema，并做异常处理。
    text = response.output_text
    return json.loads(text)
```

### 6.4 为什么 `detail: low` 通常够用

如果只是判断“前方有没有人 / 物体 / 大致场景”，`detail: low` 可以降低延迟和成本。只有当你需要读小字、看手部细节、判断微小物体时，再用高细节或原图细节。

但如果涉及距离、碰撞、是否能迈步，VLM 不是可靠距离传感器。你应该结合：

- RealSense depth
- stereo depth
- LiDAR / SLAM
- local obstacle detection
- robot base state / foot contact state

---

## 7. Safety Supervisor：最关键的工程模块

### 7.1 你必须拦截所有 AI 动作

```python
class SafetySupervisor:
    def __init__(self, cfg, scene_state, robot_state):
        self.cfg = cfg
        self.scene_state = scene_state
        self.robot_state = robot_state

    def validate(self, action: dict) -> tuple[bool, str]:
        action_type = action.get("type")

        if action_type == "stop":
            return True, "stop is always allowed"

        if action_type == "say":
            text = action.get("text", "")
            if len(text) > self.cfg["say"]["max_chars"]:
                return False, "speech text too long"
            return True, "speech allowed"

        if not self.robot_state.estop_ready:
            return False, "estop not ready"

        if not self.robot_state.is_standing:
            return False, "robot is not in standing state"

        if action_type == "walk_forward":
            if not self.cfg["policy"]["allow_ai_to_move"]:
                return False, "AI motion disabled"

            speed = float(action.get("speed_mps", 0))
            duration = float(action.get("duration_s", 0))

            if speed > self.cfg["motion_limits"]["max_vx_mps"]:
                return False, "speed too high"
            if duration > self.cfg["motion_limits"]["max_action_duration_s"]:
                return False, "duration too long"
            if not self.scene_state.clear_path:
                return False, "path is not clear"
            if self.scene_state.nearest_obstacle_m < self.cfg["perception_limits"]["min_obstacle_distance_m"]:
                return False, "obstacle too close"
            return True, "walk_forward allowed"

        if action_type == "turn":
            yaw_deg = abs(float(action.get("yaw_deg", 0)))
            if yaw_deg > self.cfg["skills"]["turn"]["max_yaw_deg"]:
                return False, "yaw too large"
            return True, "turn allowed"

        if action_type == "wave_hand":
            if self.robot_state.is_moving:
                return False, "cannot wave while moving"
            return True, "wave allowed"

        return False, f"unknown action type: {action_type}"
```

### 7.2 安全层要做的不只是限速

你至少需要这些保护：

| 保护 | 内容 |
|---|---|
| 技能白名单 | GPT 只能调用允许动作 |
| 参数限幅 | 速度、角度、持续时间、步数全部限制 |
| 状态检查 | 站立、平衡、support mode、motion service 状态 |
| 看门狗 | 超时未收到控制信号就 stop |
| 人工确认 | 初期所有移动都要人工确认 |
| E-stop | 手柄、物理按钮或独立进程能立即停机 |
| 感知保护 | 相机丢失、深度丢失、障碍物过近立即 stop |
| 日志 | 每次 VLM 输出、拒绝原因、执行动作都记录 |
| 回退动作 | 失败时 stop / recover_stand / ask_human |

### 7.3 不要让 GPT 输出连续长动作

错误：

```json
{"type": "walk_forward", "speed_mps": 0.5, "duration_s": 20}
```

正确：

```json
{"type": "walk_forward", "speed_mps": 0.15, "duration_s": 0.8}
```

然后重新感知、重新判断。

---

## 8. Skill Server：把你的现有 demo 封装成 AI 可调用工具

### 8.1 设计原则

你已经做过走跑、静态动作 demo，所以不要重写机器人底层。你应该包装已有功能：

```python
class G1SkillServer:
    def __init__(self, sdk_adapter, tts, safety):
        self.sdk = sdk_adapter
        self.tts = tts
        self.safety = safety

    def execute(self, action: dict):
        ok, reason = self.safety.validate(action)
        if not ok:
            self.stop()
            self.tts.say(f"这个动作不安全，我不会执行。原因是：{reason}")
            return {"status": "rejected", "reason": reason}

        action_type = action["type"]
        if action_type == "say":
            return self.say(action["text"])
        if action_type == "stop":
            return self.stop()
        if action_type == "walk_forward":
            return self.walk_forward(action["speed_mps"], action["duration_s"])
        if action_type == "turn":
            return self.turn(action["yaw_deg"])
        if action_type == "wave_hand":
            return self.wave_hand()
        raise ValueError(f"unknown action: {action_type}")

    def say(self, text: str):
        self.tts.say(text)
        return {"status": "ok", "skill": "say"}

    def stop(self):
        self.sdk.stop_motion()
        return {"status": "ok", "skill": "stop"}

    def walk_forward(self, speed_mps: float, duration_s: float):
        self.sdk.velocity_move(vx=speed_mps, vy=0.0, yaw_rate=0.0)
        self.sdk.sleep(duration_s)
        self.sdk.stop_motion()
        return {"status": "ok", "skill": "walk_forward"}

    def turn(self, yaw_deg: float):
        yaw_rate = 0.25 if yaw_deg > 0 else -0.25
        duration = min(abs(yaw_deg) / 20.0, 1.5)
        self.sdk.velocity_move(vx=0.0, vy=0.0, yaw_rate=yaw_rate)
        self.sdk.sleep(duration)
        self.sdk.stop_motion()
        return {"status": "ok", "skill": "turn"}

    def wave_hand(self):
        # 调用你已经验证过的静态动作 demo / high-level action / arm motion primitive
        self.sdk.play_static_motion("wave_hand_safe_v1")
        return {"status": "ok", "skill": "wave_hand"}
```

### 8.2 SDK2 Adapter 不要暴露底层细节给 GPT

```python
class G1SDK2Adapter:
    def velocity_move(self, vx: float, vy: float, yaw_rate: float):
        # 这里包装你现有的 Unitree SDK2 / ROS2 调用
        # GPT 不应该知道 DDS topic、motor ID、joint index。
        pass

    def stop_motion(self):
        pass

    def play_static_motion(self, name: str):
        pass

    def get_robot_state(self):
        pass

    def sleep(self, seconds: float):
        import time
        time.sleep(seconds)
```

---

## 9. G1 说话：三条路线

你提到“让 G1 说话”。这里要区分三种方案。

### 9.1 路线 A：OpenAI TTS 生成音频，本地播放

这是最推荐的第一版。

```text
text
 ↓
OpenAI TTS: gpt-4o-mini-tts / tts-1 / tts-1-hd
 ↓
WAV / MP3 / PCM
 ↓
G1 PC2 / 外接主机 / Jetson / USB speaker / 蓝牙音箱播放
```

OpenAI 官方文档显示，Audio API 的 speech endpoint 基于 GPT-4o mini TTS，支持 11 个内置声音、多语言、streaming，并要求向用户说明语音由 AI 生成。文档也给了 `gpt-4o-mini-tts` 的 Python 流式示例，并说明可通过指令控制语气、语速、情绪、口音、音调等。

示例：

```python
from openai import OpenAI
from pathlib import Path
import subprocess

client = OpenAI()


def speak_to_file(text: str, out_path: str = "/tmp/g1_speech.mp3"):
    with client.audio.speech.with_streaming_response.create(
        model="gpt-4o-mini-tts",
        voice="coral",
        input=text,
        instructions="声音自然、友好、简洁，像一个安全的人形机器人助手。",
    ) as response:
        response.stream_to_file(out_path)
    return out_path


def play_audio(path: str):
    # Linux 上可按实际环境改成 aplay / ffplay / paplay / pipewire / pygame / pyaudio
    subprocess.run(["ffplay", "-nodisp", "-autoexit", path], check=False)


def say(text: str):
    path = speak_to_file(text)
    play_audio(path)
```

优点：

- 声音自然。
- 可多语言。
- 能控制语气。
- 不依赖 G1 本地 TTS 是否完善。

缺点：

- 需要网络。
- 有 API 延迟。
- 需要确认 G1 PC2 或外接主机的音频输出设备。

### 9.2 路线 B：OpenAI Realtime API 语音到语音

如果你想要“人跟 G1 对话”，Realtime API 更适合：

```text
麦克风音频
 ↓
Realtime API
 ↓
模型理解语音 + 工具调用 + 回复音频
 ↓
G1 播放声音
 ↓
必要时调用 Skill Server
```

OpenAI 官方文档说明 Realtime API 支持低延迟语音到语音、多模态输入、音频/文本输出，并支持 WebRTC、WebSocket、SIP 等方式。Realtime conversation 文档也说明会话可包含音频、图像、文本输入以及 function calling。

推荐架构：

```text
Browser / Python audio client / G1 host mic
        ↓ WebRTC or WebSocket
OpenAI Realtime session
        ↓ tool call
Application Server / Safety Supervisor
        ↓ approved skill
G1 Skill Server
```

OpenAI server-controls 文档也强调，业务逻辑和 tool use 通常应该放在应用服务器侧，并可通过 sideband control channel 监控会话、更新指令和响应工具调用。对机器人来说，这一点非常重要：

> 语音模型可以请求工具调用，但真正是否执行动作，必须由你的本地安全服务器决定。

### 9.3 路线 C：G1 本地 VUI / AudioClient

`unitree_sdk2_python` 里有 G1 VUI 示例，可以控制音量和灯光。社区 issue 里有人提到 G1 firmware 版本会影响 audio / LED；也有人提到本地中文 TTS 相关限制。由于官方公开文档目前对 G1 完整麦克风输入和高质量 TTS 的说明不够充分，我建议你：

1. **第一版不要依赖 G1 内置语音系统**。
2. 用外接 USB 麦克风和 USB/蓝牙/HDMI 音箱更快打通。
3. 只把 G1 VUI 当成音量、灯光、状态反馈的辅助接口。
4. 等你确认本机 AudioClient / 麦克风 API 后，再替换音频 I/O。

---

## 10. 让 G1 “模拟我们人做什么”：分三阶段实现

你说“让 G1 可以模拟我们人做什么”，这句话非常关键，但工程上必须拆开。

### 10.1 第一阶段：语义模仿 / Mock Imitation

这是最快能做出来的版本。

```text
摄像头看到人
        ↓
本地人体姿态估计 / VLM 判断动作
        ↓
识别：挥手、指左、指右、举手、蹲下、停止
        ↓
调用预定义 G1 动作 primitive
```

例子：

| 人类动作 | G1 响应 |
|---|---|
| 人挥手 | `wave_hand()` |
| 人指左 | `turn(yaw_deg=-15)` |
| 人指右 | `turn(yaw_deg=15)` |
| 人说“过来一点” | `walk_forward(0.15, 0.8)` |
| 人张开手掌做停止手势 | `stop()` |
| 人举手 | `say("我看到你举手了。") + wave_hand()` |

这一阶段可以用：

- MediaPipe / OpenPose / MMPose / YOLO-pose
- GPT-5.5 Vision 做语义确认
- 你已有的静态动作 demo

这是最适合你现在做的版本，因为它不需要真正学习连续轨迹。

### 10.2 第二阶段：遥操作数据 → Imitation Learning

当你要让 G1 学会“像人一样操作”时，就进入 LeRobot 路线：

```text
XR 遥操作
        ↓
采集图像、关节、末端执行器、人类动作
        ↓
unitree_lerobot / LeRobot 数据格式
        ↓
训练 policy
        ↓
仿真测试
        ↓
真机低速部署
```

适合任务：

- 拿杯子
- 按按钮
- 抓取固定物体
- 挥手 / 指向
- 双臂简单同步动作
- 桌面 manipulation

不建议一开始做：

- 快速奔跑中抓取
- 跳跃
- 踢腿
- 复杂全身舞蹈
- 人机近距离互动中的大幅快速动作

### 10.3 第三阶段：GMR / Motion Retargeting / RL Tracking

当你要“人怎么动，G1 也怎么动”时，路线应为：

```text
人类动作数据：SMPL-X / AMASS / BVH / FBX / PICO / XR
        ↓
GMR retarget to Unitree G1
        ↓
MuJoCo / IsaacLab 验证运动学可行性
        ↓
构造成 reference motion
        ↓
训练 tracking policy
        ↓
Sim2Sim
        ↓
Sim2Real
```

这条路线更接近你列出的 RL/MJLab/spinkick 示例。比如双旋踢这种动作，不是 VLM 直接控制做出来的，而是：

```text
参考动作 → 模仿训练 → tracking policy → 真机部署
```

VLM 在这里的作用是：

```text
用户说：“做一个转身踢”
        ↓
VLM/LLM 判断意图
        ↓
选择已经训练好的 skill：spin_kick_safe_v1
        ↓
安全层检查周围无人、场地足够、人工确认
        ↓
执行 policy
```

---

## 11. 推荐开发路线图

### Phase 0：安全准备

目标：确保任何 AI 系统都不能让机器人失控。

任务：

- 手柄 / 物理 E-stop 可用。
- `stop()` primitive 可靠。
- `recover_stand()` 或安全站立逻辑可靠。
- 记录当前 firmware、SDK2 版本、G1 版本、DoF、末端执行器。
- 建立 `observe_only` 模式。
- 所有动作有日志。

验收：

```text
无论 AI 输出什么，Safety Supervisor 都能拒绝危险动作。
```

### Phase 1：G1 会看、会描述、会说话，但不移动

目标：打通摄像头 → GPT-5.5 Vision → TTS。

任务：

- 使用 TeleImager 或 OpenCV 获取图像。
- 每 1 秒抽一帧。
- 发给 GPT-5.5 Vision。
- 让模型输出 `scene_summary`。
- 使用 OpenAI TTS 播放中文语音。
- 不执行任何移动动作。

验收：

```text
G1 能说：“我看到前方有一个人，右侧有一张桌子。”
```

### Phase 2：G1 能选择动作，但需要人工确认

目标：VLM 输出结构化 action JSON。

任务：

- Prompt 限制动作白名单。
- 加 JSON schema / structured outputs。
- Safety Supervisor 校验。
- 终端显示建议动作。
- 人按键确认后执行。

验收：

```text
用户说“向我打招呼”，G1 输出 wave_hand + say，人工确认后执行。
```

### Phase 3：低速视觉导航 mock

目标：实现非常保守的视觉响应。

任务：

- 本地检测人 / 目标物。
- VLM 只做语义解释。
- `turn`、`walk_forward` 每次只执行 0.5~1.0 秒。
- 每步后重新观察。
- 障碍物过近立即 stop。

验收：

```text
G1 能在空旷环境中缓慢转向目标，并在接近人或障碍物前停止。
```

### Phase 4：语音代理

目标：人可以自然说话控制 G1。

任务：

- 接入 Realtime API 或 Speech-to-Text + TTS。
- 用户语音 → intent。
- intent → skill call。
- skill call → Safety Supervisor。
- 回复语音。

验收：

```text
用户说：“看一下前面有什么。”
G1 看图后回答。
用户说：“向左转一点。”
G1 请求确认或低速转向。
```

### Phase 5：语义模仿

目标：看到人做简单动作，G1 做对应动作。

任务：

- 人体姿态估计。
- 识别 waving / pointing / stop gesture。
- 调用静态动作 primitive。
- 记录动作数据。

验收：

```text
人挥手，G1 挥手。
人做停止手势，G1 stop。
```

### Phase 6：遥操作数据 + LeRobot

目标：训练一个真正的视觉条件 imitation policy。

任务：

- 用 `xr_teleoperate --record` 采集数据。
- 转成 LeRobot 格式。
- 训练一个小任务。
- 仿真验证。
- 真机低速执行。

验收：

```text
G1 能根据摄像头完成一个简单桌面动作，例如伸手触碰目标。
```

### Phase 7：GMR + Tracking Policy

目标：从人类动作数据生成 G1 全身动作技能。

任务：

- 用 GMR retarget BVH / SMPL-X / PICO 数据。
- MuJoCo / IsaacLab 验证。
- 用 MJLab / RL Lab 训练 tracking policy。
- 封装为 `track_motion(name)` primitive。

验收：

```text
G1 能安全执行一个经过仿真和真机验证的动作技能，例如 wave / bow / dance_step_01。
```

---

## 12. 最小可运行 Demo 设计

### 12.1 Demo 名称

```text
G1 VLM Audio Mock Agent
```

### 12.2 Demo 行为

用户对 G1 说或输入：

```text
“看看前面有什么，然后跟我打个招呼。”
```

系统流程：

```text
1. 抽取一帧图像
2. GPT-5.5 Vision 分析画面
3. 输出 JSON：say + wave_hand
4. Safety Supervisor 检查 wave_hand 是否允许
5. G1 说话
6. G1 执行已验证的 wave_hand 静态动作
7. stop
8. 记录日志
```

### 12.3 主循环示例

```python
def main_loop(camera, vlm, skills, safety):
    user_goal = "看看前面有什么，然后用安全的方式回应我。"

    while True:
        frame = camera.get_latest_frame()
        scene_state = camera.estimate_scene_state(frame)  # 可先返回 mock clear_path=True

        decision = vlm.analyze(frame, user_goal=user_goal)
        print("VLM decision:", decision)

        for action in decision.get("actions", []):
            ok, reason = safety.validate(action)
            if not ok:
                skills.execute({"type": "stop"})
                skills.execute({"type": "say", "text": f"我拒绝执行这个动作：{reason}"})
                continue

            # 第一阶段建议加人工确认
            if action["type"] in {"walk_forward", "turn", "wave_hand"}:
                confirm = input(f"Execute {action}? [y/N] ")
                if confirm.lower() != "y":
                    skills.execute({"type": "say", "text": "我已取消动作。"})
                    continue

            skills.execute(action)

        break
```

---

## 13. 摄像头接入建议

### 13.1 最快路线：OpenCV / SDK front camera

如果你只是要证明 GPT-5.5 Vision 可用，可以先用最简单的 OpenCV：

```python
import cv2
import base64


def capture_jpeg_b64(camera_id=0):
    cap = cv2.VideoCapture(camera_id)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise RuntimeError("failed to read camera")

    frame = cv2.resize(frame, (768, 432))
    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
    if not ok:
        raise RuntimeError("failed to encode jpeg")
    return base64.b64encode(buf).decode("utf-8")
```

### 13.2 更长期路线：TeleImager

推荐把 TeleImager 作为正式图像服务：

```text
teleimager-server
        ↓
ZMQ subscriber
        ↓
latest frame buffer
        ↓
local perception + VLM sampling
```

原因：

- 支持 UVC / OpenCV / RealSense。
- 支持 ZMQ / WebRTC。
- 能服务多个消费者。
- triple ring buffer 适合实时应用，只取最新帧，不阻塞。

### 13.3 ROS2 路线

如果你的整体栈已经偏 ROS2，可以统一为：

```text
/camera/color/image_raw
/camera/depth/image_raw
/detections
/scene_state
/g1/skill_request
/g1/skill_status
/g1/safety_state
```

然后让 AI agent 只订阅 `/scene_state` 和抽样图像，不直接接触底层 topic。

---

## 14. 音频输入建议

### 14.1 第一版：外接麦克风

不要一开始纠结 G1 内置麦克风 API。建议：

```text
USB mic / laptop mic / XR device mic
        ↓
Speech-to-Text / Realtime API
        ↓
intent
        ↓
Skill Server
```

### 14.2 Speech-to-Text 示例

```python
from openai import OpenAI

client = OpenAI()


def transcribe_audio(path: str) -> str:
    with open(path, "rb") as f:
        transcription = client.audio.transcriptions.create(
            model="gpt-4o-transcribe",
            file=f,
        )
    return transcription.text
```

### 14.3 Realtime API 更适合连续对话

对于“和 G1 说话”的体验，Realtime API 比“录音 → STT → GPT → TTS”更自然，因为它能做低延迟语音到语音，并且可以通过 tool calling 触发动作请求。

但是架构上要坚持：

```text
Realtime tool call
        ↓
Application server receives tool call
        ↓
Safety Supervisor validates
        ↓
Skill Server executes or rejects
        ↓
Realtime model explains result to user
```

---

## 15. Tool Calling 设计：让语音模型调用安全工具

OpenAI Realtime / Responses 都可以和工具调用思路结合。你可以定义工具：

```json
[
  {
    "name": "g1_say",
    "description": "让 G1 说一句话",
    "parameters": {
      "type": "object",
      "properties": {
        "text": {"type": "string", "maxLength": 120}
      },
      "required": ["text"]
    }
  },
  {
    "name": "g1_turn",
    "description": "让 G1 原地低速转向",
    "parameters": {
      "type": "object",
      "properties": {
        "yaw_deg": {"type": "number", "minimum": -30, "maximum": 30}
      },
      "required": ["yaw_deg"]
    }
  },
  {
    "name": "g1_stop",
    "description": "立即停止 G1 的高层运动"
  }
]
```

注意：

```text
工具 schema 只做第一层限制。
真正安全检查必须在本地 Safety Supervisor 里做。
```

---

## 16. 常见坑和规避方法

### 16.1 G1 mode / sport service 问题

现象：

```text
SDK 连接正常，但运动命令不响应。
```

可能原因：

- debug mode 关闭了 high-level AI sport client。
- 当前不是可执行 high-level motion 的模式。
- 远程控制器和 SDK 处于不同状态。
- firmware / EDU 权限 / service 状态不匹配。

规避：

- 每次启动 agent 前检查 mode。
- 做一个 `robot_state_check.py`。
- 先执行 `stand / stop / small_turn` 自检。
- 如果 high-level 不响应，不让 AI agent 进入 active 模式。

### 16.2 SDK 可用动作和遥控器动作不一致

现象：

```text
遥控器能挥手，SDK 调用 WaveHand / ShakeHand 报错。
```

规避：

- 不把官方动作名直接暴露给 GPT。
- 你的技能名应是自己的：`wave_hand_safe_v1`。
- 每个技能启动前检查是否可用。
- 不可用时返回 `skill_unavailable`，让 G1 用语音解释。

### 16.3 WebRTC / HTTPS / 证书问题

现象：

```text
XR 设备或浏览器黑屏，看不到图像。
```

规避：

- 确认证书已经安装到设备。
- 确认 image server host / IP 正确。
- 先用本机浏览器测试 WebRTC 页面。
- ZMQ 图像链路和 WebRTC 图像链路分开调试。

### 16.4 DDS 网络问题

现象：

```text
等待订阅 DDS / robot state 卡住。
```

规避：

- 优先有线网络调试。
- 确认 `NETWORK_INTERFACE`。
- 确认 PC2 / robot / host 同网段。
- 不要同时开多个冲突的 DDS domain / interface。

### 16.5 Sim2Real 不稳定

现象：

```text
仿真能动，真机不动、乱动、抖动、姿态异常。
```

规避：

- 先 sim2sim。
- 确认 DoF：23DoF / 29DoF / 43DoF。
- 确认 motor ID / joint order / URDF / MJCF。
- 降低动作幅度和速度。
- 真机先吊装或保护架。
- 日志记录每个 joint command / observation。

### 16.6 VLM 误判距离

现象：

```text
GPT 说“前方很安全”，但其实距离很近。
```

规避：

- VLM 不负责距离安全。
- 使用 depth / LiDAR / stereo / local detector。
- 所有前进动作要求 `clear_path == true`。
- 单次前进不超过 0.5~1.0 秒。

### 16.7 语音延迟

现象：

```text
G1 回答慢，体验像卡住。
```

规避：

- 短句优先。
- 使用 streaming TTS。
- 常用语音缓存，例如“我已停止”“这个动作不安全”。
- 语音和动作解耦：先说“好的”，再规划。
- 实时对话用 Realtime API，不要每轮都 STT → GPT → TTS。

---

## 17. 你现在最应该写的 5 个小程序

### 17.1 `camera_debug.py`

功能：

```text
读取 G1/RealSense/USB 摄像头 → 保存 jpg → 显示 FPS → 可发给 GPT-5.5 描述
```

验收：

```text
每 1 秒保存一张图，GPT 能正确描述画面。
```

### 17.2 `tts_debug.py`

功能：

```text
输入文字 → OpenAI TTS → G1/主机播放
```

验收：

```text
G1 能说中文：“你好，我是 G1，我现在处于观察模式。”
```

### 17.3 `skill_debug.py`

功能：

```text
命令行选择 primitive：stop / turn / walk / wave / stand
```

验收：

```text
所有 primitive 可单独执行，失败会自动 stop。
```

### 17.4 `vlm_decision_debug.py`

功能：

```text
图片 + 用户目标 → GPT-5.5 JSON → 打印，不执行
```

验收：

```text
输出 JSON 始终可 parse，动作在白名单内。
```

### 17.5 `agent_main.py`

功能：

```text
摄像头 + VLM + TTS + Safety + SkillServer 串起来
```

验收：

```text
observe_only / confirm / active 三种模式可切换。
```

---

## 18. 推荐的第一个 Demo 脚本逻辑

```text
启动：
1. 检查 OpenAI API key
2. 检查摄像头
3. 检查音频输出
4. 检查 G1 stop() 是否可用
5. 检查 robot state 是否 standing
6. 进入 observe_only

用户输入：
“看一下我在做什么，然后回应我。”

循环：
1. 抽一帧
2. 本地检测人 / 障碍物
3. GPT-5.5 Vision 输出 JSON
4. Safety 检查
5. 如果动作是 say，直接说
6. 如果动作是 wave/turn/walk，要求人工确认
7. 执行动作
8. stop
9. 记录日志
```

---

## 19. 评估指标

你需要从一开始就做评估，否则后面会失控。

| 指标 | 目标 |
|---|---|
| VLM JSON parse 成功率 | > 99% |
| 非白名单动作出现次数 | 0 |
| Safety 拒绝危险动作成功率 | 100% |
| stop 响应时间 | 尽可能低，建议 < 300ms 作为工程目标 |
| 摄像头帧率 | 本地 > 10 FPS，VLM 抽样 1 FPS |
| TTS 首包延迟 | 越低越好，优先 streaming |
| 单次移动动作持续时间 | 初期 ≤ 1.0s |
| 人工确认覆盖率 | 初期移动动作 100% |
| 日志完整率 | 100% |

---

## 20. 未来高级版本：从 Agent 到 Embodied System

当第一版跑通后，可以继续升级。

### 20.1 Behavior Tree

把 GPT 输出变成行为树节点，而不是直接动作列表：

```text
Goal: greet_person
  ├── Check: person_visible
  ├── Check: robot_standing
  ├── Action: say("你好")
  ├── Action: wave_hand
  └── Action: stop
```

优点：

- 可解释。
- 可中断。
- 可复用。
- 容易加安全检查。

### 20.2 Memory / Scene Graph

维护一个 scene graph：

```json
{
  "objects": [
    {"id": "person_1", "type": "person", "bearing_deg": 5, "distance_m": 1.8},
    {"id": "chair_1", "type": "chair", "bearing_deg": -20, "distance_m": 1.2}
  ],
  "robot": {
    "mode": "standing",
    "last_action": "wave_hand",
    "battery": 0.72
  }
}
```

GPT 看 scene graph + 抽样图像，而不是每次从零理解。

### 20.3 多模型协作

```text
YOLO / depth：快速安全感知
GPT-5.5 Vision：场景语义
GPT-5.5：任务规划
Realtime：语音交互
LeRobot policy：操作技能
RL policy：运动技能
Behavior Tree：执行组织
Safety Supervisor：强约束
```

### 20.4 技能库版本化

每个技能都要有版本：

```text
wave_hand_safe_v1
wave_hand_safe_v2
walk_forward_flat_v1
turn_in_place_v1
reach_red_cube_lerobot_v1
track_motion_bow_v1
```

记录：

- 适用 DoF
- 适用地面
- 最大速度
- 是否真机验证
- 是否需要人工确认
- 是否允许在人附近执行
- 失败回退动作

---

## 21. 最推荐的学习和实现顺序

按照你的目标和当前能力，我建议优先级是：

```text
1. SDK2 high-level skill wrapper
2. TeleImager / camera frame pipeline
3. OpenAI GPT-5.5 Vision JSON decision
4. OpenAI TTS / Realtime voice
5. Safety Supervisor
6. Mock imitation: gesture → primitive
7. XR teleoperate data collection
8. LeRobot imitation policy
9. GMR motion retargeting
10. RL tracking policy / Sim2Real
```

不要一开始做：

```text
端到端 VLA 直接控制全身
GPT 直接输出关节角
云端模型实时闭环走路
未验证 retarget 轨迹直接真机执行
没有 E-stop 的自主移动
```

---

## 22. 建议你从这个最小 prompt 开始

```text
你是 Unitree G1 的高层机器人任务规划器。
你不能输出任何底层电机、关节角、力矩、DDS topic 或 ROS2 raw command。
你只能调用以下技能：say, stop, turn, walk_forward, wave_hand, ask_human。
机器人当前处于低速安全实验模式。
如果画面中有人、宠物、障碍物、楼梯、玻璃、反光、地面不清晰、距离不确定，必须保守。
移动动作必须很短，必须低速，必要时必须请求人工确认。
输出必须是 JSON，不能包含额外自然语言。
```

---

## 23. 一个完整的 mock 决策例子

用户命令：

```text
“看着我，然后模仿我打招呼。”
```

VLM 输入：

```text
图像：人站在 G1 前方约 2 米，右手抬起
本地检测：person_detected=true, clear_path=true, nearest_obstacle=1.5m
机器人状态：standing=true, moving=false
```

VLM 输出：

```json
{
  "scene_summary": "画面中有一个人站在机器人前方，并抬起一只手，像是在打招呼。",
  "risk_level": "low",
  "needs_human_confirmation": true,
  "actions": [
    {"type": "say", "text": "我看到你在打招呼，我也向你打招呼。"},
    {"type": "wave_hand"},
    {"type": "stop"}
  ],
  "reason": "用户似乎在做挥手动作，机器人可以用已验证的 wave_hand_safe_v1 做语义模仿。"
}
```

Safety Supervisor：

```text
检查 robot standing: yes
检查 moving: no
检查 wave_hand enabled: yes
检查 nearby obstacle: safe
检查 human confirmation: required
等待人工确认
执行
```

---

## 24. 参考资料与仓库索引

### OpenAI 官方资料

1. OpenAI Models Compare：`gpt-5.5` / `gpt-5.5 pro` 支持 image input、function calling、structured outputs 等。  
   https://developers.openai.com/api/docs/models/compare
2. OpenAI Quickstart：Responses API 使用方式和图片输入示例。  
   https://developers.openai.com/api/docs/quickstart
3. OpenAI Images and Vision Guide：`input_image`、图片格式、`detail` 参数、视觉输入限制。  
   https://developers.openai.com/api/docs/guides/images-vision
4. OpenAI Text-to-Speech Guide：`gpt-4o-mini-tts`、streaming、voice、instructions。  
   https://developers.openai.com/api/docs/guides/text-to-speech
5. OpenAI Speech-to-Text Guide：`gpt-4o-transcribe` 等。  
   https://developers.openai.com/api/docs/guides/speech-to-text
6. OpenAI Realtime API Guide：低延迟语音到语音、多模态输入、WebRTC/WebSocket/SIP。  
   https://developers.openai.com/api/docs/guides/realtime
7. OpenAI Realtime Conversations：会话、图像输入、function calling、session 结构。  
   https://developers.openai.com/api/docs/guides/realtime-conversations
8. OpenAI Realtime Server Controls：sideband control、工具调用、服务器侧业务逻辑。  
   https://developers.openai.com/api/docs/guides/realtime-server-controls

### Unitree 官方 / 近官方仓库

1. Unitree SDK2  
   https://github.com/unitreerobotics/unitree_sdk2
2. Unitree SDK2 Python  
   https://github.com/unitreerobotics/unitree_sdk2_python
3. TeleImager  
   https://github.com/unitreerobotics/teleimager
4. XR Teleoperate  
   https://github.com/unitreerobotics/xr_teleoperate
5. Unitree LeRobot  
   https://github.com/unitreerobotics/unitree_lerobot
6. Unitree IL LeRobot  
   https://github.com/unitreerobotics/unitree_IL_lerobot
7. Unitree RL Gym  
   https://github.com/unitreerobotics/unitree_rl_gym
8. Unitree RL Lab  
   https://github.com/unitreerobotics/unitree_rl_lab
9. Unitree RL MJLab  
   https://github.com/unitreerobotics/unitree_rl_mjlab
10. Unitree UnifoLM-VLA  
   https://github.com/unitreerobotics/unifolm-vla

### 模仿学习 / Retargeting / 社区项目

1. Hugging Face LeRobot Unitree G1 文档  
   https://huggingface.co/docs/lerobot/en/unitree_g1
2. Roboparty GMR  
   https://github.com/Roboparty/GMR
3. mujocolab G1 Spin Kick Example  
   https://github.com/mujocolab/g1_spinkick_example
4. GalacTechNyc Unitree G1 Autonomous  
   https://github.com/GalacTechNyc/unitree-g1-autonomous
5. mkrcek Unitree G1 public notes  
   https://github.com/mkrcek/unitree-g1-public

### 值得看的经验帖 / Issues

1. `unitree_sdk2_python` issue：G1 debug mode / ai sport client / SDK movement response。  
   https://github.com/unitreerobotics/unitree_sdk2_python/issues/43
2. `unitree_sdk2_python` issue：WaveHand / ShakeHand API 与遥控器行为不一致。  
   https://github.com/unitreerobotics/unitree_sdk2_python/issues/42
3. `xr_teleoperate` issue：Vision Pro / WebRTC / camera black screen / DDS 连接问题。  
   https://github.com/unitreerobotics/xr_teleoperate/issues/262
4. `xr_teleoperate` issue：G1 + Apple Vision Pro + Inspire FTP 运行问题。  
   https://github.com/unitreerobotics/xr_teleoperate/issues/210
5. `unitree_lerobot` issue：Meta Quest 3 采集、LeRobot 转换、训练 pipeline 跑通但 eval 遇到 API/URDF 问题。  
   https://github.com/unitreerobotics/unitree_lerobot/issues/37
6. `unitree_rl_gym` issue：sim2sim 到 sim2real 的手臂/腿部部署问题。  
   https://github.com/unitreerobotics/unitree_rl_gym/issues/65

---

## 25. 最后的工程建议

你现在的最佳路线不是“先做一个巨大的通用 G1 AI”，而是先做一个稳定、可解释、可回退的最小系统：

```text
G1 看一帧图
        ↓
GPT-5.5 Vision 输出安全 JSON
        ↓
G1 用 TTS 说话
        ↓
人工确认
        ↓
调用你已经验证过的 primitive
        ↓
stop
```

只要这个系统跑通，你就有了一个非常好的扩展框架。后面无论你接 LeRobot、GMR、RL tracking policy、Realtime voice agent，还是本地 VLA，都可以接到同一个 `Safety Supervisor + Skill Server` 上。

一句话总结：

> 让 GPT-5.5 做 G1 的“高层语义大脑”，让 TeleImager / local CV 做“眼睛和反射”，让 Unitree SDK2 / RL / LeRobot 做“动作技能”，让 Safety Supervisor 做“底线”。

