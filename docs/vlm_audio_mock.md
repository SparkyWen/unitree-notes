# Unitree G1：VLM + Audio + Human-Mimic 高级功能实现研究方案

> 文件名：`vlm_audio_mock.md`  
> 日期：2026-05-03  
> 目标：基于 Unitree G1，实现 **视觉模型感知、语音交互、动作技能调用、人类动作模仿、遥操作数据采集、RL/Sim2Real 真机部署** 的完整技术路线。  
> 核心原则：**AI/VLM/LLM 不直接控制电机；AI 只做感知、解释、任务规划和有限技能选择；真正执行由安全层 + skill primitive + SDK2/ROS2/RL policy 完成。**

---

## 0. 结论先讲

你的目标可以拆成三件事：

1. **让 G1 看见：**
   - 使用 G1 自带/外接相机；
   - 用 `teleimager` / WebRTC / ZMQ / ROS2 Image Topic 获取图像；
   - 抽帧送入 OpenAI vision-capable model、YOLO、SAM、Depth、VLM 或本地模型；
   - 输出结构化环境理解，而不是自然语言长篇描述。

2. **让 G1 说话 / 听人说话：**
   - 输出语音：OpenAI TTS → 生成音频 → G1 speaker 播放；
   - 输入语音：G1 mic / 外接麦克风 → OpenAI STT / Realtime API → 文本命令；
   - 如果使用 `experientialtech/g1-audio-driver`，G1 的 4-mic array 和 head speaker 可以桥接成 Linux 标准 PulseAudio 设备。

3. **让 G1 “像人一样做动作”：**
   - 短期：让 AI 调用已有动作：`walk_forward`, `turn`, `stop`, `say`, `play_motion_policy`；
   - 中期：使用 `xr_teleoperate` 采集人类遥操作数据 → `unitree_lerobot` / LeRobot 训练 imitation policy；
   - 长期：使用 GMR / G1 Moves / motion retargeting，把人类视频、BVH、SMPL-X、FBX、PICO/VR 数据重定向到 G1，再用 RL policy 稳定跟踪，最后 Sim2Real 到真机。

---

## 1. 是否可以接入 OpenAI 的 GPT-5.5 视觉模型？

### 1.1 准确说法

可以接入 **OpenAI 视觉能力模型**，但需要注意：

- 如果你说的 “GPT-5.5” 是 ChatGPT 里的模型名，它不一定等于 OpenAI API 中公开可调用的 `model` id。
- API 里应以 OpenAI 官方 model list 为准。官方文档目前列出 GPT-5.2、GPT-5.1、GPT-5、GPT-5 mini、GPT-5 nano、GPT-4.1、Realtime/audio models 等。
- 官方模型页显示 GPT-5 系列支持 **image input**，但普通 GPT-5 / GPT-5.2 这类模型的 audio 通常不是同一个接口能力；音频交互应使用 Audio API 或 Realtime/audio models。
- 视觉不是“视频流原生理解”。工程上通常是 **相机视频抽帧 → 单帧/多帧图像输入 → VLM 输出结构化决策**。

### 1.2 推荐模型分工

| 子任务 | 推荐接口/模型类型 | 用法 |
|---|---|---|
| 场景理解 / 识别障碍物 / 判断任务 | Responses API + vision-capable model | 每 0.5–2 秒抽帧一次 |
| 高级任务规划 | Responses API + function calling / structured output | 输出 JSON action primitive |
| 实时语音对话 | Realtime API | 低延迟语音输入输出 |
| 文本转语音 | Audio Speech / TTS model | 生成 mp3/wav，再由 G1 speaker 播放 |
| 语音转文本 | Audio Transcriptions / Realtime | G1 mic 或外接 mic 输入 |

### 1.3 不推荐做法

不要做：

```text
camera frame → GPT/VLM → 直接输出每个关节角度/电机力矩 → G1
```

应该做：

```text
camera frame → VLM 环境理解 → LLM planner → skill primitive → safety layer → Unitree SDK2 / ROS2 / trained policy
```

---

## 2. 最终系统架构

```text
┌──────────────────────────────────────────────────────────┐
│                     Human / Environment                  │
│        voice command, visual scene, human demo, objects   │
└─────────────────────────────┬────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────┐
│  Perception Layer                                         │
│  - teleimager / WebRTC / ZMQ / ROS2 Image                 │
│  - G1 mic / PulseAudio / external microphone              │
│  - IMU, joint states, battery, temperature, robot mode     │
└─────────────────────────────┬────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────┐
│  AI Understanding Layer                                   │
│  - OpenAI vision model / local VLM                         │
│  - STT for user voice command                              │
│  - object detection / depth / segmentation                 │
│  - scene graph / hazard map                                │
└─────────────────────────────┬────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────┐
│  Planner Layer                                            │
│  - LLM / Behavior Tree / FSM                               │
│  - converts perception into safe intent                    │
│  - outputs only structured primitive calls                 │
└─────────────────────────────┬────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────┐
│  Safety + Skill Broker                                    │
│  - whitelist actions only                                  │
│  - speed / duration / workspace limits                     │
│  - e-stop / confidence threshold / human confirmation      │
│  - no raw low-level joint commands from AI                 │
└─────────────────────────────┬────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────┐
│  Execution Layer                                          │
│  - Unitree SDK2 / unitree_sdk2_python                      │
│  - ROS2 bridge                                             │
│  - LeRobot policy inference                                │
│  - RL policy ONNX / Torch                                  │
│  - prebuilt primitive library                              │
└─────────────────────────────┬────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────┐
│                      Unitree G1                           │
│       walk, turn, stop, speak, gesture, grasp, mimic       │
└──────────────────────────────────────────────────────────┘
```

---

## 3. 关键仓库研究

### 3.1 Unitree 官方 / 半官方底层仓库

| 仓库 | 你应该学什么 | 用在你的项目哪里 |
|---|---|---|
| `unitreerobotics/unitree_sdk2` | DDS 通信、机器人服务、C++ 控制、G1 audio/client 示例 | 真机控制底层 |
| `unitreerobotics/unitree_sdk2_python` | Python 控制接口，最适合接 AI 代码 | Python AI stack → G1 |
| `unitreerobotics/unitree_ros2` | ROS2 集成方式 | 后续导航、SLAM、MoveIt2 |
| `unitreerobotics/unitree_mujoco` | MuJoCo 仿真 | Sim2Sim / 安全测试 |
| `unitreerobotics/unitree_model` | URDF / MJCF / robot model | IK、仿真、可视化 |
| `unitreerobotics/UnitreecameraSDK` | 相机 SDK | 原始相机接入 |
| `unitreerobotics/teleimager` | UVC/OpenCV/RealSense → ZMQ/WebRTC 图像服务 | 视觉输入主入口 |

---

### 3.2 强化学习 / Locomotion / Sim2Real

| 仓库 | 重点 | 你应该如何使用 |
|---|---|---|
| `unitreerobotics/unitree_rl_gym` | 官方 RL GYM，支持 G1；工作流 Train → Play → Sim2Sim → Sim2Real | 训练/部署基础 locomotion policy |
| `unitreerobotics/unitree_rl_lab` | IsaacLab-based，支持 G1-29dof；含 Sim2Sim / Sim2Real 部署 | 做更大规模 RL 训练 |
| `unitreerobotics/unitree_rl_mjlab` | MuJoCo/MJLab，支持 G1 Flat、G1-23DoF、G1 motion tracking | 做轻量运动模仿、动作跟踪 |
| `mujocolab/g1_spinkick_example` | G1 spin kick 示例 | 学习复杂动作 policy 的训练和部署 |
| `experientialtech/g1-moves` | 60 个 G1 人类动作模仿数据，BVH/PKL/NPZ/ONNX policy | 快速获得“像人一样动”的素材和 policy |

#### 对你的启发

你未来的 skill primitive 不应该只有：

```python
walk_forward()
turn_left()
stop()
```

还应该扩展到：

```python
play_policy("wave_hand")
play_policy("dance_short")
play_policy("karate_guard")
play_policy("point_to_object")
play_policy("bow")
play_policy("hands_up")
```

也就是说，VLM/LLM 只决定 **调用哪个技能**，技能本身来自 RL / motion imitation / retargeting。

---

### 3.3 遥操作 / 数据采集 / 模仿学习

| 仓库 | 重点 | 用法 |
|---|---|---|
| `unitreerobotics/xr_teleoperate` | XR 设备控制 G1；支持 G1 29DoF / 23DoF、Dex 手、Inspire、BrainCo；支持 sim、record、IPC | 采集你自己的高质量数据 |
| `unitreerobotics/unitree_lerobot` | G1 + LeRobot 改造版；支持数据转换、模型部署、真机测试 | 训练模仿学习策略 |
| `huggingface/lerobot` | 官方 LeRobot；支持 Unitree G1 23/29 DoF、ZMQ 相机、MuJoCo sim、policy inference | 正式训练/推理框架 |
| `Roboparty/GMR` | SMPL-X / BVH / FBX / PICO → Unitree G1 29DoF / 43DoF retargeting | 从人类动作数据生成 G1 动作 |
| `NVIDIA/soma-retargeter` | BVH → Unitree G1 29DoF retargeting | 另一个动作重定向参考 |

#### 对你的启发

“让 G1 模拟我们人做什么”至少有三条路线：

| 路线 | 输入 | 中间处理 | 输出 | 难度 |
|---|---|---|---|---|
| A. XR 遥操作 | Apple Vision Pro / Quest / PICO | `xr_teleoperate` 记录 episode | LeRobot dataset → policy | 中 |
| B. 动捕/动作文件 | BVH / FBX / SMPL-X / AMASS | GMR / retargeting / IK | G1 joint trajectory / RL policy | 中高 |
| C. 单目视频 | 手机视频 | pose estimation / GVHMR / video2robot | retarget → policy | 高 |

最现实路线：**先用 XR 遥操作采集你自己的数据，再用 LeRobot 训练。**

---

### 3.4 视觉 / 自主导航 / AI 决策

| 仓库 | 重点 | 你应该借鉴什么 |
|---|---|---|
| `unitreerobotics/teleimager` | 多相机图像服务，UVC/OpenCV/RealSense → ZMQ/WebRTC | 图像服务层 |
| `unitreerobotics/xr_teleoperate` | 真机物理部署时需要手动启动 image service；支持 head camera 测试页面 | G1 图像部署流程 |
| `GalacTechNyc/unitree-g1-autonomous` | 用 Gemini 1.5 Pro 做实时 camera analysis，10Hz loop + 1Hz AI query + safety fallback | 你的 OpenAI VLM 架构参考 |
| `deepglint/FAST_LIO_LOCALIZATION_HUMANOID` | 人形机器人 FAST-LIO localization | 复杂导航定位 |
| `Ericcsr/G1_localization` | G1 localization | ROS2 / SLAM |
| `leeyngdo/elevation_mapping_g1` | G1 elevation mapping | 地形感知 |

#### 关键工程模式

`unitree-g1-autonomous` 的思路非常值得借鉴：

```text
Camera Module
  → AI Vision Module
  → Main Autonomous Controller
  → Robot Control Module
  → Safety fallback
```

你把 Gemini 换成 OpenAI vision-capable model 就可以：

```text
Camera
  → OpenAI VLM
  → JSON action proposal
  → Safety Validator
  → Unitree Skill Broker
  → G1
```

---

### 3.5 音频 / 说话 / 听话

| 仓库 / 接口 | 重点 | 用法 |
|---|---|---|
| `experientialtech/g1-audio-driver` | 把 G1 4-mic array 和 head speaker 桥接成 PulseAudio 标准设备 | 最适合让 G1 “像普通 Linux 设备一样说话/听话” |
| Unitree SDK2 G1 audio examples | G1 audio client、TTS、play stream、volume、LED 等 | 更底层，适合 C++ 或 SDK 原生接口 |
| OpenAI TTS | 文本 → 语音 | 让 G1 说自然语言 |
| OpenAI STT / Realtime | 语音 → 文本 / 实时语音对话 | 让 G1 听人说话 |

`g1-audio-driver` 的价值是：它把 G1 的头部麦克风和喇叭做成标准 Linux audio device：

```text
G1 mic array  → PulseAudio source: g1_microphone
G1 speaker    → PulseAudio sink:   g1_speaker
```

这样你的 AI 程序不需要直接理解 Unitree 内部音频协议，直接：

```bash
parecord --device=g1_microphone ...
paplay --device=g1_speaker speech.wav
```

---

## 4. 推荐落地路线

## 阶段 1：G1 会“看见并描述”

### 目标

```text
G1 camera → OpenAI VLM → describe scene → G1 speaker says the result
```

### 最小闭环

1. 在 G1 PC2 或外部 laptop 上启动 camera stream；
2. 每 1 秒截取一帧；
3. 发送给 OpenAI vision-capable model；
4. 返回一句结构化描述；
5. OpenAI TTS 生成音频；
6. 通过 `paplay --device=g1_speaker` 播放。

### VLM prompt

```text
You are the perception module of a Unitree G1 humanoid robot.
Analyze the image from the robot's front camera.

Return JSON only:
{
  "scene_summary": "short human-readable summary",
  "obstacles": [
    {"type": "person|chair|wall|table|unknown", "position": "left|center|right", "distance_estimate": "near|medium|far"}
  ],
  "is_safe_to_move": true,
  "recommended_action": "stop|look_left|look_right|walk_forward_slow|turn_left|turn_right",
  "confidence": 0.0
}

Rules:
- If a person, animal, stair, reflective surface, glass, or unknown obstacle is near, choose "stop".
- Never output raw joint angles.
- Never suggest fast movement.
```

---

## 阶段 2：G1 会“听懂并回答”

### 目标

```text
Human: "What do you see?"
G1: captures image → VLM analyzes → speaks answer
```

### 实现路径

```text
G1 microphone
  → OpenAI STT / Realtime
  → command parser
  → if command asks visual question:
        capture frame
        VLM analyze
        TTS answer
  → play via G1 speaker
```

### 示例命令分类

| 用户语音 | Planner 输出 |
|---|---|
| “What do you see?” | `describe_scene` |
| “Can you move forward?” | `proposal: walk_forward_slow`, requires safety check |
| “Stop.” | immediate `stop` |
| “Copy my movement.” | enter `imitation_recording` or `retargeting` flow |
| “Wave your hand.” | `play_motion_policy("wave_hand")` |

---

## 阶段 3：G1 会“安全地根据视觉移动”

### 目标

```text
VLM detects free path → planner selects primitive → safety gate approves → G1 walks slowly
```

### 第一版只允许 5 个动作

```python
ALLOWED_PRIMITIVES = {
    "stop",
    "turn_left_slow",
    "turn_right_slow",
    "walk_forward_slow",
    "say"
}
```

### 安全限制

```python
MAX_FORWARD_SPEED = 0.20   # m/s
MAX_YAW_SPEED = 0.25       # rad/s
MAX_ACTION_DURATION = 1.0  # seconds
MIN_CONFIDENCE = 0.75
REQUIRE_HUMAN_ARMED_MODE = True
```

### 决策流程

```text
frame
  → VLM JSON
  → schema validation
  → safety validation
  → current robot state validation
  → primitive execution
  → immediate stop if confidence low / stale frame / person nearby
```

---

## 阶段 4：G1 会“模仿人类动作”

### 路线 A：使用现成动作数据

使用：

```text
experientialtech/g1-moves
```

流程：

```text
BVH / PKL / NPZ / ONNX policy
  → MuJoCo simulation
  → policy test
  → skill registry
  → play_policy("dance_01")
```

适合快速 demo：跳舞、挥手、武术姿势、弯腰、举手等。

### 路线 B：用 GMR 处理人类动作

使用：

```text
Roboparty/GMR
```

流程：

```text
AMASS / SMPL-X / BVH / FBX / PICO data
  → GMR retargeting to Unitree G1
  → 保存 G1 robot motion
  → MuJoCo 验证
  → RL motion imitation
  → Sim2Real
```

适合真正研究：  
**Retargeting quality、foot contact、joint limit、stability、style imitation、online imitation**。

### 路线 C：XR 遥操作采集自己的数据

使用：

```text
unitreerobotics/xr_teleoperate
unitreerobotics/unitree_lerobot
huggingface/lerobot
```

流程：

```text
XR headset / controller / hand tracking
  → teleoperate G1 in simulation or real robot
  → record episode
  → convert dataset
  → train policy
  → inference on G1
```

适合做真实任务：

- 指向一个物体；
- 递东西；
- 按按钮；
- 打招呼；
- 简单抓取；
- 辅助老人/患者拿轻物；
- 教育场景中的“示范动作”。

---

## 5. 推荐代码架构

```text
g1_ai_stack/
├── configs/
│   ├── robot.yaml
│   ├── camera.yaml
│   ├── audio.yaml
│   ├── safety.yaml
│   └── skills.yaml
├── perception/
│   ├── camera_client.py          # teleimager / OpenCV / ZMQ / WebRTC frame client
│   ├── frame_sampler.py          # 1Hz VLM frame sampling
│   ├── openai_vision.py          # OpenAI vision JSON output
│   └── local_detector.py         # optional YOLO / depth
├── audio/
│   ├── g1_audio_io.py            # g1_microphone / g1_speaker wrapper
│   ├── openai_tts.py             # text → wav/mp3
│   ├── openai_stt.py             # speech → text
│   └── dialogue_manager.py
├── planner/
│   ├── prompt_templates.py
│   ├── intent_parser.py
│   ├── behavior_tree.py
│   └── structured_actions.py
├── safety/
│   ├── guard.py                  # all safety validation
│   ├── robot_state_monitor.py
│   ├── estop.py
│   └── limits.py
├── skills/
│   ├── base_skill.py
│   ├── locomotion_skills.py
│   ├── speech_skills.py
│   ├── gesture_skills.py
│   ├── policy_player.py
│   └── skill_registry.py
├── unitree/
│   ├── sdk2_client.py
│   ├── ros2_bridge.py
│   └── state_reader.py
├── mock/
│   ├── mock_camera.py
│   ├── mock_robot.py
│   └── mock_audio.py
├── scripts/
│   ├── run_describe_scene.py
│   ├── run_voice_chat.py
│   ├── run_vlm_nav_safe.py
│   └── run_policy_skill_demo.py
└── README.md
```

---

## 6. VLM 控制 JSON Schema

建议所有模型输出都必须符合 schema：

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "scene_summary",
    "hazards",
    "user_intent",
    "recommended_primitive",
    "primitive_args",
    "confidence",
    "requires_human_confirmation"
  ],
  "properties": {
    "scene_summary": {"type": "string"},
    "hazards": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["type", "location", "severity"],
        "properties": {
          "type": {"type": "string"},
          "location": {"type": "string"},
          "severity": {"type": "string", "enum": ["low", "medium", "high"]}
        }
      }
    },
    "user_intent": {
      "type": "string",
      "enum": [
        "describe_scene",
        "navigate",
        "speak",
        "imitate_motion",
        "gesture",
        "stop",
        "unknown"
      ]
    },
    "recommended_primitive": {
      "type": "string",
      "enum": [
        "stop",
        "say",
        "walk_forward_slow",
        "turn_left_slow",
        "turn_right_slow",
        "play_policy",
        "ask_human"
      ]
    },
    "primitive_args": {"type": "object"},
    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    "requires_human_confirmation": {"type": "boolean"}
  }
}
```

---

## 7. OpenAI VLM 示例伪代码

> 注意：模型名以你账号当前 API 可用 model list 为准。不要硬编码不存在的 `gpt-5.5` API model id。

```python
from openai import OpenAI
import base64
import json
from pathlib import Path

client = OpenAI()

def encode_image(path: str) -> str:
    data = Path(path).read_bytes()
    return base64.b64encode(data).decode("utf-8")

def analyze_frame(image_path: str) -> dict:
    img_b64 = encode_image(image_path)

    prompt = """
You are the perception-planning module of a Unitree G1 humanoid robot.
Analyze the front-camera image and return JSON only.

Never output raw motor commands or joint angles.
Choose only one primitive from:
stop, say, walk_forward_slow, turn_left_slow, turn_right_slow, ask_human.

If uncertain, choose stop or ask_human.
"""

    response = client.responses.create(
        model="gpt-5.2",  # replace with your available vision-capable model
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {
                        "type": "input_image",
                        "image_url": f"data:image/jpeg;base64,{img_b64}",
                        "detail": "low"
                    }
                ],
            }
        ],
    )

    text = response.output_text
    return json.loads(text)
```

---

## 8. OpenAI TTS + G1 speaker 示例伪代码

如果你使用 `g1-audio-driver`，可以把 G1 speaker 当成 PulseAudio sink：

```python
from openai import OpenAI
from pathlib import Path
import subprocess

client = OpenAI()

def g1_say(text: str):
    out = Path("/tmp/g1_speech.mp3")

    audio = client.audio.speech.create(
        model="gpt-4o-mini-tts",
        voice="coral",
        input=text,
        instructions="Speak clearly, warmly, and briefly."
    )

    out.write_bytes(audio.read())

    subprocess.run([
        "paplay",
        "--device=g1_speaker",
        str(out)
    ], check=True)
```

如果不使用 `g1-audio-driver`，你也可以：

1. 用 OpenAI TTS 生成 wav/mp3；
2. 上传/发送到 G1 PC2；
3. 调 Unitree SDK2 G1 audio PlayStream / audio client 播放；
4. 或先用外接 USB speaker 做 MVP。

---

## 9. G1 听人说话的两种路线

### 路线 A：非实时、简单稳定

```text
G1 mic / USB mic
  → arecord / parecord 保存短音频
  → OpenAI transcription
  → intent parser
  → action primitive
```

优点：简单、稳定、容易调试。  
缺点：不是实时语音对话。

### 路线 B：Realtime API

```text
G1 mic stream
  → Realtime API
  → model understands voice
  → model returns text/audio/tool call
  → action broker handles tool call
```

优点：交互自然、低延迟。  
缺点：工程复杂，必须严格限制工具调用权限，不能让模型直接控制底层。

---

## 10. Skill Registry 设计

```python
from dataclasses import dataclass
from typing import Callable, Dict, Any

@dataclass
class Skill:
    name: str
    description: str
    max_duration_s: float
    requires_confirmation: bool
    handler: Callable[[Dict[str, Any]], None]

class SkillRegistry:
    def __init__(self):
        self.skills = {}

    def register(self, skill: Skill):
        self.skills[skill.name] = skill

    def execute(self, name: str, args: dict, safety_guard):
        if name not in self.skills:
            raise ValueError(f"Unknown skill: {name}")

        skill = self.skills[name]

        safety_guard.validate_skill_call(skill, args)
        return skill.handler(args)
```

示例 skill：

```python
registry.register(Skill(
    name="walk_forward_slow",
    description="Walk forward slowly for a short duration.",
    max_duration_s=1.0,
    requires_confirmation=False,
    handler=lambda args: unitree.walk(vx=min(args.get("vx", 0.15), 0.20), duration=0.5)
))

registry.register(Skill(
    name="say",
    description="Speak using the G1 speaker.",
    max_duration_s=10.0,
    requires_confirmation=False,
    handler=lambda args: g1_say(args["text"])
))

registry.register(Skill(
    name="play_policy",
    description="Play a prevalidated motion imitation policy.",
    max_duration_s=5.0,
    requires_confirmation=True,
    handler=lambda args: policy_player.play(args["policy_id"])
))
```

---

## 11. Safety Guard 设计

### 11.1 必须拦截的情况

任何一个成立就 `stop()`：

- VLM confidence < 0.75；
- 图像帧超过 1 秒没有更新；
- 机器人姿态异常；
- battery / temperature 异常；
- 人或动物距离过近；
- 当前不是 debug/safe/armed mode；
- action 不在白名单；
- action duration 超过限制；
- 用户没有显式启用 autonomous mode；
- network / DDS 心跳异常；
- human operator 按下 e-stop。

### 11.2 状态机

```text
IDLE
  ↓ human arms system
ARMED
  ↓ valid perception + valid command
EXECUTING_PRIMITIVE
  ↓ primitive finished
ARMED

任何状态：
  e-stop / hazard / stale sensor / low confidence
    → STOPPED
```

### 11.3 关键原则

```text
LLM/VLM output = proposal
Safety Guard output = permission
Skill Broker output = execution
```

不要让模型输出：

```json
{"left_knee": 0.34, "right_ankle": -0.22}
```

只允许：

```json
{"primitive": "turn_left_slow", "duration": 0.5}
```

---

## 12. “G1 模仿人”的完整技术路线

## 12.1 快速 demo 路线：G1 Moves

```text
g1-moves dataset
  → choose existing ONNX policy
  → run in MuJoCo
  → register as play_policy("dance_short")
  → VLM/voice calls it
```

适合你做非常有冲击力的 demo：

```text
User: "Can you show me a dance move?"
G1: "Sure. I will perform a short safe dance motion."
G1: play_policy("J_Dance0_StepTouch")
```

## 12.2 研究路线：GMR

```text
human motion file / video pose
  → SMPL-X / BVH / FBX / PICO
  → GMR retargeting to Unitree G1
  → MuJoCo preview
  → save robot motion
  → motion imitation training
  → Sim2Real
```

适合做论文/深入研究：  
**Retargeting quality、foot contact、joint limit、stability、style imitation、online imitation**。

## 12.3 产品路线：XR Teleoperate + LeRobot

```text
XR device
  → teleoperate G1 arm/hand
  → record episodes
  → convert to LeRobot dataset
  → train policy
  → deploy policy to G1
```

适合做真实任务：

- 指向一个物体；
- 递东西；
- 按按钮；
- 打招呼；
- 简单抓取；
- 辅助老人/患者拿轻物；
- 教育场景中的“示范动作”。

---

## 13. 推荐最小 MVP：VLM + Audio + Safe Primitive

### 13.1 MVP 功能

```text
用户说：“What do you see?”
G1：
  1. 录音转文字；
  2. 截取当前摄像头图像；
  3. VLM 分析；
  4. 通过 TTS 说出：“I see a table in front of me and a person on my left.”
```

再升级：

```text
用户说：“Move closer to the table.”
G1：
  1. VLM 判断前方是否安全；
  2. 如果安全，只走 0.3 秒；
  3. 停下；
  4. 再看一帧；
  5. 继续或停止。
```

### 13.2 为什么要小步走？

不要一次让机器人走 3 米。  
应该是：

```text
sense → think → move 0.2m → stop → sense again
```

这比“看一次图像然后连续走很久”安全很多。

---

## 14. Agent / Codex 可执行任务清单

你可以让 Codex 先做这个最小项目骨架：

```text
Create a Python project named g1_ai_stack.

Requirements:
1. Implement a mock-safe Unitree G1 AI stack with these modules:
   - perception/camera_client.py
   - perception/openai_vision.py
   - audio/openai_tts.py
   - audio/g1_audio_io.py
   - planner/intent_parser.py
   - safety/guard.py
   - skills/skill_registry.py
   - skills/locomotion_skills.py
   - skills/speech_skills.py
   - scripts/run_describe_scene.py
   - scripts/run_vlm_nav_safe.py

2. Do not implement raw low-level motor control.
3. All robot actions must go through SkillRegistry and SafetyGuard.
4. Use mock robot by default.
5. Add an interface where real Unitree SDK2 commands can be plugged in later.
6. OpenAI vision must output structured JSON only.
7. Speech output should first write audio to /tmp/g1_speech.mp3 and optionally call paplay --device=g1_speaker.
8. Include configs/safety.yaml with conservative speed and duration limits.
9. Include README.md explaining how to switch from mock mode to real robot mode.
10. Include tests for:
    - low confidence → stop
    - unknown primitive → reject
    - stale frame → stop
    - say primitive → allowed
    - walk_forward_slow with too high speed → clipped or rejected
```

---

## 15. 你接下来应该按什么顺序做

| 顺序 | 任务 | 输出 |
|---:|---|---|
| 1 | 跑通 `g1-audio-driver` 或外接 speaker | G1 能说话 |
| 2 | 跑通 OpenAI TTS | 输入文本，G1 播放语音 |
| 3 | 跑通 teleimager / OpenCV 截图 | 得到前视图 frame |
| 4 | 跑通 OpenAI VLM JSON 输出 | 图像 → structured perception |
| 5 | 做 mock robot skill broker | 不接真机，验证规划逻辑 |
| 6 | 接入 Unitree SDK2 high-level control | 只支持 stop / slow walk / slow turn |
| 7 | 加 e-stop 和 human armed mode | 安全可控 |
| 8 | 接入 LeRobot / G1 Moves policy | `play_policy()` |
| 9 | 做语音命令 + 视觉执行闭环 | 多模态 demo |
| 10 | 开始自己的遥操作数据采集 | 训练个性化 imitation policy |

---

## 16. 最推荐的第一个 demo

我建议你先做这个：

```text
Demo Name: G1 Vision Voice Companion

User: "Hi G1, what do you see?"
G1:
  - captures camera image
  - analyzes with OpenAI vision model
  - says: "I see a chair in front of me, a table on the right, and a clear path on the left."

User: "Can you move forward?"
G1:
  - checks image
  - if safe: "I will move forward slowly."
  - moves forward for 0.3 seconds
  - stops
  - captures another image
  - says: "I have stopped. The path is still clear."

User: "Show me a human-like gesture."
G1:
  - says: "I will perform a pre-validated gesture."
  - play_policy("wave_hand") or pre-recorded safe arm motion
```

这个 demo 同时体现：

- 视觉理解；
- 语音交互；
- 安全动作；
- skill primitive；
- 不直接低层控制；
- 后续可扩展到 imitation learning。

---

## 17. 参考来源

1. OpenAI Images and Vision Guide：Responses API 可处理 image input，并支持图像理解。  
   https://platform.openai.com/docs/guides/vision

2. OpenAI Responses API Reference：Responses API 支持 text/image input、function calling、structured outputs 等。  
   https://platform.openai.com/docs/api-reference/responses/create

3. OpenAI Text-to-Speech Guide：Audio speech endpoint 可将文本转为语音。  
   https://platform.openai.com/docs/guides/text-to-speech

4. OpenAI Speech-to-Text Guide：Audio transcription 支持 `gpt-4o-transcribe`、`gpt-4o-mini-transcribe` 等。  
   https://platform.openai.com/docs/guides/speech-to-text

5. OpenAI Realtime API：支持低延迟 WebRTC/WebSocket/SIP，多模态实时交互。  
   https://platform.openai.com/docs/api-reference/realtime

6. LeRobot Unitree G1 文档：支持 Unitree G1 teleoperate、locomanipulation policy、simulation、23/29 DoF、ZMQ camera。  
   https://huggingface.co/docs/lerobot/main/en/unitree_g1

7. `unitreerobotics/xr_teleoperate`：Unitree humanoid XR teleoperation，支持 G1 29DoF/23DoF、Dex/BrainCo/Inspire hands、record、sim、image service。  
   https://github.com/unitreerobotics/xr_teleoperate

8. `unitreerobotics/unitree_lerobot`：Unitree G1 + LeRobot 数据转换、训练、部署。  
   https://github.com/unitreerobotics/unitree_lerobot

9. `unitreerobotics/unitree_rl_gym`：官方 RL GYM，Train → Play → Sim2Sim → Sim2Real。  
   https://github.com/unitreerobotics/unitree_rl_gym

10. `unitreerobotics/unitree_rl_lab`：IsaacLab-based Unitree RL，支持 G1-29DoF。  
    https://github.com/unitreerobotics/unitree_rl_lab

11. `unitreerobotics/unitree_rl_mjlab`：MuJoCo/MJLab RL，支持 G1 tracking、23DoF、motion imitation。  
    https://github.com/unitreerobotics/unitree_rl_mjlab

12. `Roboparty/GMR`：支持 Unitree G1 / G1 with hands 的 SMPL-X、BVH、FBX、PICO 动作重定向。  
    https://github.com/Roboparty/GMR

13. `GalacTechNyc/unitree-g1-autonomous`：Gemini API + G1 camera autonomous navigation demo。  
    https://github.com/GalacTechNyc/unitree-g1-autonomous

14. `experientialtech/g1-audio-driver`：G1 4-mic array / head speaker → PulseAudio bridge。  
    https://github.com/experientialtech/g1-audio-driver

15. `exptech/g1-moves`：60 clips G1 motion-capture dataset，BVH/PKL/NPZ/ONNX policies。  
    https://huggingface.co/datasets/exptech/g1-moves

16. `Robotics-Ark/ark_unitree_g1`：G1 drivers、simulation bridges、IK、pick-place demo。  
    https://github.com/Robotics-Ark/ark_unitree_g1

---

## 18. 最后一句话

你真正要做的不是“让 GPT 控制机器人”，而是：

```text
让 GPT/VLM 成为 G1 的大脑解释层，
让 Safety Guard 成为 G1 的神经反射层，
让 SDK2/ROS2/RL policies 成为 G1 的运动系统，
让 LeRobot/GMR/teleoperation 成为 G1 学会人类动作的训练系统。
```

这套路线才是安全、可扩展、可以持续研究并最终做成产品的路线。
