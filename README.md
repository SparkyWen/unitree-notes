<div align="center">

# 🤖 Unitree Notes

### *A curated reference, simulation & deployment playground for the Unitree G1 humanoid*

*面向宇树 G1 人形机器人的参考资料、仿真试验场与真机部署工作区*

<br/>

[![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![MuJoCo](https://img.shields.io/badge/MuJoCo-3.5.0-1A73E8?style=for-the-badge&logo=googlecolab&logoColor=white)](https://mujoco.org/)
[![PyTorch](https://img.shields.io/badge/PyTorch-2.11-EE4C2C?style=for-the-badge&logo=pytorch&logoColor=white)](https://pytorch.org/)
[![ONNX](https://img.shields.io/badge/ONNX_Runtime-1.25-005CED?style=for-the-badge&logo=onnx&logoColor=white)](https://onnxruntime.ai/)
[![CUDA](https://img.shields.io/badge/CUDA-13.0-76B900?style=for-the-badge&logo=nvidia&logoColor=white)](https://developer.nvidia.com/cuda-toolkit)
[![OpenAI](https://img.shields.io/badge/OpenAI-Realtime_API-412991?style=for-the-badge&logo=openai&logoColor=white)](https://platform.openai.com/docs/guides/realtime)

[![Unitree](https://img.shields.io/badge/Robot-Unitree_G1_29DoF-FF6B35?style=flat-square&logo=robotframework&logoColor=white)](https://www.unitree.com/g1)
[![Platform](https://img.shields.io/badge/Platform-Linux_/_WSL2-FCC624?style=flat-square&logo=linux&logoColor=black)](https://learn.microsoft.com/windows/wsl/)
[![DDS](https://img.shields.io/badge/DDS-CycloneDDS_0.10-00ADD8?style=flat-square&logo=eclipsefoundation&logoColor=white)](https://github.com/eclipse-cyclonedds/cyclonedds)
[![ROS 2](https://img.shields.io/badge/ROS_2-Jazzy-22314E?style=flat-square&logo=ros&logoColor=white)](https://docs.ros.org/en/jazzy/)
[![Conda](https://img.shields.io/badge/Conda-Miniforge-44A833?style=flat-square&logo=anaconda&logoColor=white)](https://github.com/conda-forge/miniforge)
[![Transformers](https://img.shields.io/badge/🤗_Transformers-4.52-FFD21E?style=flat-square)](https://huggingface.co/docs/transformers)
[![Diffusers](https://img.shields.io/badge/🤗_Diffusers-0.35-FFD21E?style=flat-square)](https://huggingface.co/docs/diffusers)
[![Ultralytics](https://img.shields.io/badge/Ultralytics-YOLO11-042A4D?style=flat-square&logo=ultralytics&logoColor=white)](https://docs.ultralytics.com/)
[![MediaPipe](https://img.shields.io/badge/MediaPipe-Pose-00897B?style=flat-square&logo=google&logoColor=white)](https://developers.google.com/mediapipe)
[![License](https://img.shields.io/badge/Code-Apache_2.0-blue.svg?style=flat-square)](#-license)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg?style=flat-square)](#-contributing)
[![Status](https://img.shields.io/badge/status-active-success.svg?style=flat-square)]()

<br/>

**🌐 Language / 语言：** [English](#-english) ｜ [简体中文](#-简体中文)

</div>

<br/>

---

<a id="-english"></a>

## 🇬🇧 English

> A complete, opinionated workspace for studying, simulating, and deploying control & cognition stacks on the **Unitree G1** humanoid — bundling **eleven upstream reference repos** (SDK · MuJoCo · RL · ROS 1 · ROS 2 · IsaacLab · LeRobot · VLA · WMA · XR teleop · image server) alongside four hand-written deliverables: [`g1_sim_demo/`](g1_sim_demo/) (sim demos from sine wave to RL+gestures), [`g1_real_demo/`](g1_real_demo/) (real-robot deployment), [`va-demo/`](va-demo/) (a voice + vision agent that talks to G1 via OpenAI Realtime), and [`g1_brain/`](g1_brain/) (a Slow-Brain + Fast-Reflex + Safe-Skill three-layer cognitive agent extending va-demo with perception, an **11-rule safety supervisor**, and **17 LLM-callable skills**).

### 📑 Table of Contents

- [✨ Highlights](#-highlights)
- [📊 At a Glance](#-at-a-glance)
- [🗂️ Repository Layout](#%EF%B8%8F-repository-layout)
- [🐍 Two Conda Environments](#-two-conda-environments)
- [📦 Prerequisites](#-prerequisites)
- [🚀 Quick Start](#-quick-start)
- [🎹 Hotkey Cheat Sheet](#-hotkey-cheat-sheet)
- [🌟 In-house Deliverables](#-in-house-deliverables)
  - [🎬 `g1_sim_demo/` — MuJoCo demo catalogue](#-g1_sim_demo--mujoco-demo-catalogue)
  - [🦿 `g1_real_demo/` — real-robot deployment](#-g1_real_demo--real-robot-deployment)
  - [🎙️ `va-demo/` — voice + vision agent](#%EF%B8%8F-va-demo--voice--vision-agent)
  - [🧠 `g1_brain/` — Slow Brain + Fast Reflex + Safe Skill agent](#-g1_brain--slow-brain--fast-reflex--safe-skill-agent)
- [🧰 Skill Catalog (`g1_brain`)](#-skill-catalog-g1_brain)
- [🛡️ Safety Supervisor — the 11 rules](#%EF%B8%8F-safety-supervisor--the-11-rules)
- [📡 Upstream Reference Repos](#-upstream-reference-repos)
- [🧱 Architecture Overview](#-architecture-overview)
- [🔌 DDS Topic & Joint Reference](#-dds-topic--joint-reference)
- [📚 Documentation Index](#-documentation-index)
- [📈 Performance & Resource Notes](#-performance--resource-notes)
- [🗺️ Roadmap & Status](#%EF%B8%8F-roadmap--status)
- [🛠️ Troubleshooting](#%EF%B8%8F-troubleshooting)
- [❓ FAQ](#-faq)
- [🤝 Contributing](#-contributing)
- [📜 License](#-license)
- [🙏 Acknowledgements](#-acknowledgements)

---

### ✨ Highlights

| | |
|---|---|
| 🤖 **Eleven upstream repos in one place** | Pinned snapshots of `unitree_sdk2_python`, `unitree_mujoco`, `unitree_rl_mjlab`, `unitree_ros`, `unitree_ros2`, `unitree_sim_isaaclab`, `unitree_lerobot`, `xr_teleoperate`, `teleimager`, `unifolm-vla`, and `unifolm-world-model-action` — every layer of the G1 stack readable in one `cd`. |
| 🎮 **Five turn-key G1 sim demos** | From a 70-line "send a sine wave" warm-up to a 1000-line RL+gesture combo controller, every script is heavily commented and runs **out of the box** against the Python MuJoCo bridge. |
| 🦿 **Real-robot deployment harness** | `g1_real_demo/g1_real_rl_combo.py` adds the `MotionSwitcher` release, bounded `lowstate` wait, and a `lying`-mode CLI for wiring/DDS verification before you ever stand the robot up. |
| 🎙️ **Voice + Vision Realtime agent** | `va-demo/` ships a wake-word ("Hi Sparky") gated, full-duplex Realtime voice agent that can **describe scenes via vision** *and* tool-call `walk` / `gesture` / `stop` against the running RL policy — confirm / observe / active / vision-only run modes. |
| 🧠 **Slow Brain + Fast Reflex + Safe Skill** | `g1_brain/` extends `va-demo` with a 3-layer agent — first-person MuJoCo head cam + YOLO11 + MediaPipe-Pose fused into a thread-safe `SceneState`, an **11-rule SafetySupervisor** + 7-state FSM + independent E-stop process, and **17 LLM-callable skills** spanning I/O, motion, and real-only stubs (`walk` · `turn` · `gesture` · `static_pose` · `look_at` · `approach` · `mock_imitate` · `describe_scene` · `query_scene_state` · `recall_history` · `ask_human` · …). See [`g1_brain/README.md`](g1_brain/README.md). |
| 🧠 **Real ONNX policy in the loop** | `g1_sim_rl_walk.py`, `g1_sim_rl_combo.py`, and `g1_real_rl_combo.py` all load the official `unitree_rl_mjlab` velocity-tracking ONNX checkpoint and execute the **exact same observation / action pipeline** end-to-end on sim and on hardware. |
| 🧷 **Sim-friendly fixes baked in** | Upstream `g1_low_level_example.py` deadlocks on `MotionSwitcherClient.CheckMode()` and assumes DDS domain 0 — every script in `g1_sim_demo/` ships with the proven domain-1 + skip-MotionSwitcher patch and a `mode_machine` handshake. |
| 🐍 **One unified conda env** | The `agi` env reconciles **7 mutually-conflicting upstreams** into **~310 fully-pinned packages** (numpy 1.26.4 + torch 2.11.0+cu130 + mujoco 3.5.0 + tyro 1.0.13 + transformers 4.52 + diffusers 0.35 + tensorflow 2.15 + jax 0.7 + …) — frozen at the repo root in [`requirements.txt`](requirements.txt); per-pin reasoning in [`docs/libs_compatible.md`](docs/libs_compatible.md). A leaner `unitree` env (sim + RL only) is a strict subset. |
| 📚 **27 000+ lines of curated Chinese notes** | Heavily-annotated walkthroughs on MuJoCo internals, lowcmd/lowstate schemas, joint indices, training-time invariants, the policy-tolerant arm-override envelope, ROS↔SDK lineage, VLA vs WMA semantics, WSL2 audio plumbing — every file in `docs/` and `*/docs/` is project-grade reading. |

---

### 📊 At a Glance

> The numbers behind the highlights — useful when planning disk space, network attach time, or how big a bite to take first.

| 📦 Footprint | Value |
|---|---|
| 🏢 **Upstream reference repos** | **11** (read-only snapshots) |
| 🌟 **In-house deliverables** | **4** (`g1_sim_demo` · `g1_real_demo` · `va-demo` · `g1_brain`) |
| 🎮 **G1 MuJoCo demo scripts** | **5** sim + **1** real ≈ 2 700 LOC of annotated control loops |
| 🛠️ **LLM-callable skills (`g1_brain`)** | **17** — 7 I/O · 7 motion · 3 real-only stubs |
| 🛡️ **Safety rules (`g1_brain`)** | **11** — see [§ Safety Supervisor](#%EF%B8%8F-safety-supervisor--the-11-rules) |
| 🎭 **Built-in arm gestures** | **9** (`wave_right` · `wave_left` · `hands_up` · `t_pose` · `salute` · `clap` · `guard` · `punch_combo` · `hug`) |
| 🧱 **Static poses** | **2** (`salute` · `hug`) — held until `release_arms()` |
| 🪞 **Mirrorable user gestures** | **4** (`wave_right` · `wave_left` · `hands_up` · `t_pose`) |
| 🐍 **`agi` env packages (pinned)** | ~**310** in [`requirements.txt`](requirements.txt) |
| 🐍 **`unitree` env packages (pinned)** | ~**150** (lean sim + RL subset) |
| 🤖 **G1 actuated DoF** | **29** (12 leg · 3 waist · 14 arm — see [§ DDS & Joint Reference](#-dds-topic--joint-reference)) |
| 🌐 **DDS domain conventions** | **1** = sim on `lo` · **0** = real robot on `192.168.123.0/24` |
| 🎤 **Wake word** | "**Hi Sparky**" (`faster-whisper tiny`, local CPU) |
| 📐 **Realtime cognition rates** | Slow Brain 0.2–2 Hz · Fast Reflex 5–30 Hz · Sim control 50–500 Hz · Bridge `lowstate` 1 kHz |
| 🧪 **Pytest test suites** | `va-demo/tests/` + `g1_brain/tests/` (FSM · supervisor · scene bus · skill server · vertical slice · …) |
| 📚 **Curated Chinese deep-dives** | **27 000+** lines across `docs/` and `*/docs/` |
| ⚖️ **License** | **Apache 2.0** for in-house code · upstream snapshots retain their own license |

---

### 🗂️ Repository Layout

```text
unitree-notes/
│
├── 🌟 In-house deliverables ───────────────────────────────────────────────
│
├── 📂 g1_sim_demo/                  ← 🎮 G1 MuJoCo demo collection
│   ├── g1_sim_low_level.py          ·  Sine-wave ankle/wrist swing   (≈ 200 LOC)
│   ├── g1_sim_interactive.py        ·  6 keyboard presets, 500 Hz    (≈ 350 LOC)
│   ├── g1_sim_keyboard.py           ·  Full keyboard playground      (≈ 600 LOC)
│   ├── g1_sim_rl_walk.py            ·  ONNX velocity-tracking walk   (≈ 500 LOC)
│   ├── g1_sim_rl_combo.py           ·  RL walk + arm-gesture combo   (≈ 1000 LOC)
│   └── docs/                        ·  Demo-specific Q&A and tutorials (QA1–QA5,
│                                       learn-mujoco, demo-explain, report)
│
├── 📂 g1_real_demo/                 ← 🦿 Real-hardware deployment
│   ├── g1_real_rl_combo.py          ·  RL walk + gestures on physical G1
│   ├── docs/demo-QA7.md             ·  `lying`-mode wiring/DDS verification
│   └── issue/realmachine.md         ·  "robot doesn't move" diagnosis log
│
├── 📂 va-demo/                      ← 🎙️ Voice + Vision Realtime agent
│   ├── va_demo/                     ·  audio_io · camera · vision · tts ·
│   │                                   wake_word · utterance_vad · spoken_cache ·
│   │                                   conversation_state · realtime_agent ·
│   │                                   safety · skills · prompts · main
│   ├── configs/va_demo.yaml         ·  All knobs (wake-word, VAD, robot, OpenAI)
│   ├── scripts/                     ·  audio_loopback / camera_debug /
│   │                                   tts_debug / wake_word_debug /
│   │                                   skill_debug / vision_loop_debug
│   ├── tests/                       ·  pytest: safety, VAD, wake-word,
│   │                                   spoken cache, vision-only mode, …
│   ├── docs/                        ·  audio-awake / audio-use /
│   │                                   video-design / video-use
│   └── requirements.txt             ·  openai · sounddevice · faster-whisper ·
│                                       webrtcvad-wheels · pyzmq · opencv-python
│
├── 📂 g1_brain/                     ← 🧠 Slow Brain + Fast Reflex + Safe Skill agent
│   ├── g1_brain/perception/         ·  CameraHub · USB cam · MuJoCo head cam (EGL) ·
│   │                                   YOLO11 · MediaPipe-Pose · depth · derivations
│   ├── g1_brain/scene_state/        ·  SceneState/RobotState dataclasses + RLock bus
│   ├── g1_brain/safety/             ·  7-state FSM · SafetySupervisor (11 rules) ·
│   │                                   watchdogs · independent E-stop process
│   ├── g1_brain/skills/             ·  SkillServer · ~16 OpenAI tool schemas ·
│   │                                   keyframe_extras · compound_skills
│   ├── g1_brain/brain/              ·  BrainRealtimeAgent (extends va-demo) +
│   │                                   scene-aware system prompt
│   ├── g1_brain/mock_imitation/     ·  user gesture → MIRRORABLE robot gesture (Phase 5)
│   ├── g1_brain/apps/               ·  agent_main + perception/safety/skill/estop debug
│   ├── configs/g1_brain.yaml        ·  Single source of truth (robot · cameras ·
│   │                                   perception · safety · openai · audio · wakeword)
│   ├── docs/                        ·  architecture · how_to_run · extending_skills ·
│   │                                   g1_brain_QA1 · g1-fix-phase{1,2,3,5}
│   ├── tests/                       ·  pytest: 11-rule supervisor · FSM · scene bus ·
│   │                                   skill server · vertical slice · watchdogs · …
│   └── pyproject.toml               ·  ultralytics · mediapipe · openai · pyyaml · pynput
│
├── 📡 Upstream reference repos (read-only snapshots) ─────────────────────
│
├── 📂 unitree_sdk2_python/          ·  DDS bindings + message IDLs (CycloneDDS)
├── 📂 unitree_mujoco/               ·  Official MuJoCo simulator + MJCF assets
├── 📂 unitree_rl_mjlab/             ·  RL training (mjlab + rsl_rl + Warp) + sim2real
├── 📂 unitree_ros/                  ·  ROS 1 + Gazebo packages (legacy reference)
├── 📂 unitree_ros2/                 ·  ROS 2 bridge atop CycloneDDS (Jazzy/humble)
├── 📂 unitree_sim_isaaclab/         ·  Isaac Lab simulator for G1 manipulation tasks
├── 📂 unitree_lerobot/              ·  LeRobot adapter (data conversion + policy
│                                      deploy on G1+Dex1/Dex3/Inspire/Brainco)
├── 📂 xr_teleoperate/               ·  XR/AVP teleoperation (Apple Vision Pro etc.)
├── 📂 teleimager/                   ·  Multi-camera image server (ZeroMQ/WebRTC)
├── 📂 unifolm-vla/                  ·  UnifoLM Vision-Language-Action framework
├── 📂 unifolm-world-model-action/   ·  UnifoLM World-Model-Action framework
│
├── 📖 Cross-cutting docs ─────────────────────────────────────────────────
│
├── 📂 docs/                         ·  Chinese deep-dive notes (see index below)
├── 📂 issue/                        ·  Workspace-level issue logs
├── 📄 instructions.md               ·  Curated run-orders for sim + va-demo
├── 📄 requirements.txt              ·  Frozen pip-freeze of the working env
└── 📄 README.md                     ·  📍 You are here
```

---

### 🐍 Two Conda Environments

This repo runs in **two parallel envs** — pick the smaller one when possible.

| Env | Purpose | Python | Key pins (`requirements.txt` is the source of truth) | Where to use |
|---|---|---|---|---|
| 🟢 **`unitree`** | Plain sim + RL stack | 3.11 | mujoco 3.5.0 · cyclonedds 0.10.2 · torch 2.11 · onnxruntime 1.25 · mjlab 1.2.0 · rsl-rl-lib 5.0.1 | `g1_sim_demo/`, `g1_real_demo/`, `unitree_mujoco`, `unitree_rl_mjlab` training |
| 🔵 **`agi`** | Everything-in-one | 3.11.15 | numpy **1.26.4** · scipy 1.17.1 · torch **2.11.0+cu130** · torchvision 0.26.0+cu130 · triton 3.6 · mujoco 3.5.0 · mujoco-warp 3.5.0 · cyclonedds 0.10.2 · tyro 1.0.13 · mjlab 1.2.0 · rsl-rl-lib 5.0.1 · transformers 4.52.3 · diffusers 0.35.1 · tokenizers 0.21.4 · accelerate 1.5.2 · safetensors 0.7.0 · datasets 3.6 · huggingface-hub 0.34 · tensorflow 2.15 · jax 0.7.1 · onnxruntime 1.22.1 · openai 2.33 · faster-whisper 1.2.1 · webrtcvad-wheels 2.0.14 · sounddevice 0.5.5 · pyzmq 27.1 · mediapipe 0.10.21 · ultralytics 8.4.46 · opencv-python 4.11 · protobuf 4.25.9 | `va-demo/`, `g1_brain/`, `teleimager`, `unifolm-vla`, `unifolm-world-model-action`, `xr_teleoperate`, `unitree_lerobot` |

> 📐 **Why two?** Seven upstream `pyproject.toml` files disagree on numpy / torch / mujoco / tyro pins. The `agi` env is the resolved compatibility set — patches for `unifolm-vla/pyproject.toml` and `unifolm-world-model-action/pyproject.toml` (saved as `pyproject.toml.bak`) loosen ghost pins. The full reasoning is in [`docs/libs_compatible.md`](docs/libs_compatible.md).
>
> 📦 **What lives in `requirements.txt`?** The repo-root [`requirements.txt`](requirements.txt) is a verbatim freeze of the working `agi` env: header docstring with the resolved pins, `-e ./<subdir>` lines for the in-repo packages (`unitree_sdk2_python` · `unitree_rl_mjlab` · `teleimager` · `unifolm-vla` · `g1_brain` · `dex-retargeting`), two `git+https` VCS pins (`dlimp` · `televuer`), and ~310 alphabetically-sorted PyPI pins. Drop the file into a fresh `python=3.11` conda env and `pip install -r requirements.txt` to reproduce the exact stack.
>
> 🔧 `unitree_ros2` is **not** a Python package — install it as a system-level ROS 2 **Jazzy** workspace following [`docs/ros2_sdk.md`](docs/ros2_sdk.md).
>
> 🧱 **Disk footprint** ≈ 14 GB for the `agi` env once CUDA-13 wheels (`nvidia-cublas`, `nvidia-cudnn-cu13`, `nvidia-nccl-cu13`, `nvidia-cusparselt-cu13`, …) and the `tensorflow` / `torch` / `jax` triple are resolved. Plan accordingly on WSL2's mounted `vhdx`.

---

### 📦 Prerequisites

| Layer | Requirement | Notes |
|---|---|---|
| 🖥️ **OS** | Linux (Ubuntu 22.04 / 24.04) or WSL2 + WSLg | macOS / native-Windows are **not** supported by CycloneDDS wheels. |
| 🐍 **Python** | 3.11 | Pinned by `mjlab` and `cyclonedds` wheels. |
| 🧪 **Conda** | [Miniforge](https://github.com/conda-forge/miniforge) recommended | Both `unitree` and `agi` envs assume Miniforge. |
| 🎮 **GPU** *(optional)* | NVIDIA + CUDA 13 + driver ≥ 560 | Required for **training** and for VLA / WMA inference. CPU is fine for sim playback and the RL ONNX policy. |
| 🤖 **Real robot** *(optional)* | Unitree G1 EDU on the same LAN | Use the actual NIC (e.g. `enp3s0`) on `192.168.123.0/24`. |
| 🎤 **Microphone / 🔈 Speaker** *(va-demo)* | Any USB / WSLg-routed audio device | WSL2 needs the ALSA→Pulse symlink — see [`docs/wsl2_audio.md`](docs/wsl2_audio.md). |
| 📷 **Camera** *(va-demo)* | UVC USB webcam | WSL2 needs `usbipd` to attach — see [`docs/camera_ui_demo.md`](docs/camera_ui_demo.md). |
| 🔑 **OpenAI API key** *(va-demo)* | `OPENAI_API_KEY` exported | Realtime + vision + TTS all hit the OpenAI API. |

---

### 🚀 Quick Start

#### 1️⃣ Clone

```bash
git clone https://github.com/SparkyWen/unitree-notes.git
cd unitree-notes
```

#### 2️⃣ Create the env you actually need

<details>
<summary><b>🟢 Option A — minimal <code>unitree</code> env (sim + RL only)</b></summary>

```bash
conda create -n unitree python=3.11 -y
conda activate unitree
pip install -r requirements.txt

# editable install so demos can `import unitree_sdk2py`
pip install -e unitree_sdk2_python
```
</details>

<details>
<summary><b>🔵 Option B — unified <code>agi</code> env (sim + RL + va-demo + g1_brain + VLA + teleop)</b></summary>

The fastest path is the repo-root [`requirements.txt`](requirements.txt) — it freezes the entire working stack, including in-repo editable installs:

```bash
conda create -n agi python=3.11 -y
conda activate agi

# numerical base — must come first to lock numpy 1.26.4
pip install "numpy==1.26.4" "scipy<2"

# everything else — pulls torch 2.11+cu130, mujoco 3.5.0, transformers 4.52,
# diffusers 0.35, tensorflow 2.15, jax 0.7.1, openai 2.33, ultralytics 8.4.46,
# mediapipe 0.10.21, faster-whisper 1.2.1, all -e ./subdir packages, etc.
pip install -r requirements.txt
```

If you'd rather install upstream-by-upstream (closer to how the env was originally bootstrapped):

```bash
conda create -n agi python=3.11 -y
conda activate agi
pip install "numpy==1.26.4" "scipy<2"

# Unitree sim + RL stack
pip install -e unitree_sdk2_python
pip install -e unitree_mujoco/simulate_python   # if applicable
pip install -e unitree_rl_mjlab

# va-demo + g1_brain + teleimager + xr_teleoperate
pip install -r va-demo/requirements.txt
pip install -e g1_brain
pip install -e "teleimager[server]"
pip install -e xr_teleoperate                   # follow its README extras

# UnifoLM stacks (after editing the two pyproject.toml.bak ghost pins)
pip install -e unifolm-vla
pip install -e unifolm-world-model-action

# unitree_lerobot
pip install -e unitree_lerobot
```

> ⚠️ Read [`docs/libs_compatible.md`](docs/libs_compatible.md) **before** the upstream-by-upstream path — there are several `pyproject.toml` edits required to break ghost pins. The `requirements.txt` route already encodes the resolved pins so you can skip the editing.
</details>

#### 3️⃣ Configure the simulator for G1

Edit `unitree_mujoco/simulate_python/config.py`:

```python
ROBOT               = "g1"      # loads g1_29dof.xml (29 motors)
ENABLE_ELASTIC_BAND = True      # required for bipeds — keeps G1 hanging upright
USE_JOYSTICK        = 0         # set to 1 only if a wired joystick is plugged in
DOMAIN_ID           = 1         # IMPORTANT: demos assume domain 1 + interface "lo"
INTERFACE           = "lo"
```

#### 4️⃣ Smoke test (two terminals)

```bash
# ── Terminal 1 — start the MuJoCo bridge ──────────────────────────
conda activate unitree
cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
python unitree_mujoco.py
#   When the viewer opens, press '9' to enable the elastic band so G1
#   hangs in the air. (Press '7' to lower it, '8' to raise it.)
```

```bash
# ── Terminal 2 — run the warm-up demo ─────────────────────────────
conda activate unitree
cd ~/unitree/unitree-notes/g1_sim_demo
python g1_sim_low_level.py
#   You should see the ankles swing, then the wrists join in.
#   IMU rpy prints once per second as a heartbeat.
```

> ✅ **If the heartbeat is printing and the viewer shows motion, you're done.** Proceed to the demo catalogue.
>
> 💡 For a curated run-order covering both the RL combo demo and the full `va-demo` (with WSL2 USB-camera attach), see [`instructions.md`](instructions.md).

---

### 🎹 Hotkey Cheat Sheet

> Every keyboard binding across every script in one place — bookmark this when you're operating, demoing, or onboarding someone new.

#### MuJoCo viewer (`unitree_mujoco/simulate_python`)

| Key | Action |
|---|---|
| <kbd>9</kbd> | Toggle elastic band (must be **ON** before any control script — keeps G1 hanging upright) |
| <kbd>8</kbd> | Pull elastic band up (raise robot) |
| <kbd>7</kbd> | Lower elastic band (let feet touch ground) |
| Mouse drag (LMB) | Rotate camera |
| Mouse drag (RMB) | Pan camera |
| Scroll | Zoom |
| <kbd>Esc</kbd> | Close viewer (kills the bridge) |

#### `g1_sim_demo/g1_sim_interactive.py` & `g1_sim_keyboard.py`

| Key | Action |
|---|---|
| <kbd>z</kbd> | Zero pose |
| <kbd>w</kbd> | Wave |
| <kbd>b</kbd> | Bow |
| <kbd>k</kbd> | Knee lift |
| <kbd>a</kbd> | Clap |
| <kbd>r</kbd> | (`g1_sim_keyboard`) Recover to first measured pose |
| <kbd>x</kbd> | (`g1_sim_keyboard`) Emergency soften — drop Kp |
| <kbd>q</kbd> | Quit (always settles to zero first) |

#### `g1_sim_demo/g1_sim_rl_walk.py` (and the locomotion side of `g1_sim_rl_combo.py` / `g1_real_rl_combo.py`)

| Key | Action |
|---|---|
| <kbd>w</kbd> / <kbd>s</kbd> | Forward / backward velocity (`vx`) |
| <kbd>a</kbd> / <kbd>d</kbd> | Strafe left / right (`vy`) |
| <kbd>q</kbd> / <kbd>e</kbd> | Yaw left / right (`wz`) |
| <kbd>r</kbd> | Reset commanded velocities to zero |
| <kbd>f</kbd> | Toggle freeze (hold last pose) |

#### `g1_sim_demo/g1_sim_rl_combo.py` & `g1_real_demo/g1_real_rl_combo.py` — arm gestures

> Pressed on top of the locomotion keys. Gestures only override the upper body (joints 15–28) and clip to the policy-tolerant envelope so legs stay in-distribution.

| Key | Gesture |
|---|---|
| <kbd>1</kbd> | `wave_right` |
| <kbd>2</kbd> | `wave_left` |
| <kbd>3</kbd> | `hands_up` |
| <kbd>4</kbd> | `t_pose` |
| <kbd>5</kbd> | `salute` |
| <kbd>6</kbd> | `clap` |
| <kbd>7</kbd> | `guard` |
| <kbd>8</kbd> | `punch_combo` |
| <kbd>0</kbd> / <kbd>Space</kbd> | Release arms back to RL policy |
| <kbd>Esc</kbd> | Stop + zero velocities |

> 🛡️ For `g1_real_rl_combo.py lying`, keys <kbd>1</kbd>..<kbd>7</kbd> instead trigger small per-joint arm wiggles to verify motor response without standing the robot up.

#### `va-demo/` & `g1_brain/`

| Key / phrase | Action |
|---|---|
| Spoken: "**Hi Sparky**" | Open the wake gate — only after this does mic audio reach OpenAI Realtime |
| Spoken: "stop", "release arms", … | Resolved by the LLM into `stop()` / `release_arms()` tool calls |
| <kbd>Backspace</kbd> | (active mode) Hard cancel of in-flight motion call |
| <kbd>Ctrl-C</kbd> | Graceful shutdown — stops audio, releases arms, writes transcripts |
| <kbd>Esc</kbd> *(separate process)* | `g1_brain.safety.estop_listener` — independent E-stop that survives main-process deadlock |
| <kbd>y</kbd> / <kbd>N</kbd> | (`--mode confirm`) Approve / reject each motion tool call |

---

### 🌟 In-house Deliverables

This repo's three deliverables, in order of dependency depth.

#### 🎬 `g1_sim_demo/` — MuJoCo demo catalogue

> All demos live under `g1_sim_demo/`. Run them with the simulator already up. Pass a real NIC name (e.g. `enp3s0`) as the **first** CLI argument to target a real G1 instead — the script will auto-switch to DDS domain 0.

<table>
<thead>
<tr><th>#</th><th>Script</th><th>What it does</th><th>Best for</th></tr>
</thead>
<tbody>

<tr>
<td>1️⃣</td>
<td><code>g1_sim_low_level.py</code></td>
<td>Three-stage scripted motion: zero-out → PR-mode ankle sine → AB-mode ankle + wrist sine.</td>
<td>📡 Verifying SDK ↔ bridge plumbing.</td>
</tr>

<tr>
<td>2️⃣</td>
<td><code>g1_sim_interactive.py</code></td>
<td>500 Hz control thread + cosine-eased keyframes. Keys: <kbd>z</kbd> zero · <kbd>w</kbd> wave · <kbd>b</kbd> bow · <kbd>k</kbd> knee · <kbd>a</kbd> clap · <kbd>q</kbd> quit.</td>
<td>🎮 First taste of keyboard teleop.</td>
</tr>

<tr>
<td>3️⃣</td>
<td><code>g1_sim_keyboard.py</code></td>
<td>Larger preset library, "real" reset (captures first measured pose), emergency-soften on <kbd>x</kbd>, per-action duration scaling, safe shutdown that always settles to zero first.</td>
<td>🎨 Posing / animating without writing code.</td>
</tr>

<tr>
<td>4️⃣</td>
<td><code>g1_sim_rl_walk.py</code></td>
<td>Loads <code>policy.onnx</code> from <code>unitree_rl_mjlab</code>, builds the 98-D obs from <code>rt/lowstate</code>, runs the policy at 50 Hz, scales/offsets to a 29-D <code>q_target</code>, publishes <code>rt/lowcmd</code>. Keys: <kbd>w/s</kbd>/<kbd>a/d</kbd>/<kbd>q/e</kbd>/<kbd>r</kbd>/<kbd>f</kbd>.</td>
<td>🚶 Closed-loop RL walking in sim.</td>
</tr>

<tr>
<td>5️⃣</td>
<td><code>g1_sim_rl_combo.py</code></td>
<td>Same RL walk, but the upper-body slice (joints 15–28) can be temporarily overridden by keyboard-triggered arm gestures — wave, hands-up, T-pose, salute, clap, guard, punch — clipped to the policy-tolerant envelope so legs never go OOD. Single publisher, no DDS race.</td>
<td>🤹 Walking + gesturing simultaneously.</td>
</tr>

</tbody>
</table>

#### 🦿 `g1_real_demo/` — real-robot deployment

> Real-hardware sibling of `g1_sim_demo/g1_sim_rl_combo.py`. Same RL policy, same gesture set, but **hardened for the physical G1**.

| File | Purpose |
|---|---|
| `g1_real_rl_combo.py` | Single-process controller: ONNX velocity policy on legs/waist + keyboard arm gestures, with `MotionSwitcher` release, bounded `lowstate` wait, and a `lying` test mode. |
| `docs/demo-QA7.md` | Walks through the `lying` mode used to verify wiring/DDS without standing the robot up. |
| `issue/realmachine.md` | Diagnosis log for "press 1/2/3 and the robot does nothing" — root cause: onboard high-level controller still owning `rt/lowcmd`. |

**What's different from the sim version:**

1. **`MotionSwitcherClient.ReleaseMode()`** is called on init — the G1's onboard `ai`/`normal`/`advanced` controller owns `rt/lowcmd` until released, otherwise our commands silently lose to the high-level writer.
2. **Bounded `lowstate` wait** — times out with an actionable checklist (wrong interface, wrong DDS domain, robot in high-level mode, link down, multicast blocked) instead of busy-waiting forever.
3. **`lying` CLI mode** — skip boot ramp and policy, hold the measured pose at low Kp, let keys 1..7 trigger small per-joint arm wiggles. Use when the robot can't stand and you only want to confirm motors respond.
4. **CycloneDDS tracing override** — silences DDS noise on real hardware.

```bash
conda activate unitree

# real robot — find the interface on the G1's 192.168.123.0/24 subnet
ip -br addr | grep 192.168.123
python g1_real_rl_combo.py <iface>           # e.g. eno3
# walking + arm gestures, after MotionSwitcher release

# real robot, can't stand — wiring/DDS check only
python g1_real_rl_combo.py <iface> lying     # e.g. eno3 lying
```

> ⚠️ Always keep the **e-stop within reach** when running on the real robot. The `lying` mode exists so you can verify the DDS path *before* the robot is upright.

#### 🎙️ `va-demo/` — voice + vision agent

> A wake-word-gated, full-duplex Realtime voice agent that **describes scenes via vision** and **tool-calls walk / gesture / stop** against the running RL policy. Built on top of `g1_sim_rl_combo`, `teleimager`, and the OpenAI Realtime + Vision + TTS APIs.

**Tools the model can call**

| Tool | Purpose |
|---|---|
| `say(text)` | Canned TTS reply |
| `stop()` | Zero velocity + release arms |
| `release_arms()` | Hand arms back to the locomotion policy |
| `walk(vx, vy, wz, duration_s)` | Short low-speed move |
| `gesture(name)` | One of: `wave_right`, `wave_left`, `hands_up`, `t_pose`, `salute`, `clap`, `guard`, `punch_combo` |
| `describe_scene(question?, detail?)` | Snapshot a frame → vision model → text answer |

**Wake-word behaviour**

The agent does **not** stream mic audio to OpenAI Realtime until you say "**Hi, Sparky**". This solves two problems the original always-on Realtime session had:

1. The Realtime API's server VAD was so eager any cough committed a turn.
2. Sparky's own TTS playback bled into the mic and Sparky kept cutting itself off mid-reply.

After the wake word fires, you speak normally; ~1.5 s of silence commits the utterance. Sparky's reply opens an **8 s listening window** during which you can speak again *without* re-saying the wake word.

The wake-word detector is `faster-whisper tiny` running locally on CPU; transcription for actual turns uses **OpenAI gpt-4o-transcribe** (cloud) — see [`docs/audio-awake.md`](va-demo/docs/audio-awake.md) for the full design.

**Run modes**

| Flag | Effect |
|---|---|
| `--mode confirm` *(default)* | Every motion tool call prompts y/N in the terminal first. |
| `--mode active` | Full autonomy — model decides; keep an eye on the elastic band & `Backspace`. |
| `--mode observe` | Motion disabled; vision + voice still work. |
| `--vision-only` | Trim motion tools entirely (no DDS init, mujoco not required) — ideal for keyframe-vision-speech loop testing. |
| `--no-wakeword` | Bypass wake gate; mic streams continuously to Realtime (legacy A/B testing only). |
| `--no-realtime` | Keep audio/camera/skills alive without a Realtime session. |

**Run order (3 terminals, `agi` env)**

```bash
# ── Terminal 1 — MuJoCo simulator ─────────────────────────────────
conda activate agi
cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
python unitree_mujoco.py
# in viewer: press 8 a few times to lower the band; optionally 9 to disable

# ── Terminal 2 — TeleImager image server ──────────────────────────
conda activate agi
cd ~/unitree/unitree-notes/teleimager
python -m teleimager.image_server

# ── Terminal 3 — va-demo agent ────────────────────────────────────
conda activate agi
cd ~/unitree/unitree-notes/va-demo
set -a; source .env; set +a              # loads OPENAI_API_KEY
python -m va_demo.main                    # default: --mode confirm
```

> 📷 WSL2 camera attach: `usbipd attach --wsl --busid <id>` from PowerShell — see [`docs/camera_ui_demo.md`](docs/camera_ui_demo.md).
>
> 🔉 WSL2 audio fix: symlink `$CONDA_PREFIX/lib/alsa-lib` → `/usr/lib/x86_64-linux-gnu/alsa-lib` so ALSA finds the pulse plugin — see [`docs/wsl2_audio.md`](docs/wsl2_audio.md).

#### 🧠 `g1_brain/` — Slow Brain + Fast Reflex + Safe Skill agent

> A new top-level package that **imports** (never modifies) [`va-demo/`](va-demo/) and [`g1_sim_demo/`](g1_sim_demo/) and adds three layers on top: **Perception · Safety · Skills**. The G1 needs three time-scales of cognition simultaneously and OpenAI Realtime alone can't hit all of them — this package separates them cleanly and routes everything through a single safety-validated skill server.

📂 **Read first:** [`g1_brain/README.md`](g1_brain/README.md) · [`g1_brain/docs/architecture.md`](g1_brain/docs/architecture.md) · [`g1_brain/docs/how_to_run.md`](g1_brain/docs/how_to_run.md) · [`docs/g1_plan.md`](docs/g1_plan.md) (full 1500+-line design)

**The three layers**

| Layer | Rate | Owner | Job |
|---|---|---|---|
| 🧠 **Slow Brain** | 0.2–2 Hz | OpenAI Realtime + GPT-5.5 Vision | Plan, talk, decide which skill to call |
| 🛡️ **Safe Skill** | per-call | `SafetySupervisor` + `SkillServer` | Validate (11 rules), clamp, route, abort |
| ⚡ **Fast Reflex** | 5–30 Hz | Cameras + YOLO11 + MediaPipe-Pose + depth | Build a `SceneState` the safety layer reads |

**Skill catalog (17 LLM-callable tools)** — see [§ Skill Catalog](#-skill-catalog-g1_brain) below for full signatures.

| Class | Tools |
|---|---|
| 🗣️ I/O — no motion | `say` · `describe_scene` · `query_scene_state` · `recall_history` · `ask_human` · `stop` · `release_arms` |
| 🦿 Motion (gated by safety + FSM) | `walk` · `turn` · `gesture` · `static_pose` · `look_at` · `approach` · `mock_imitate` |
| 🤖 Real-only stubs (rejected in sim) | `loco_high` · `arm_action_high` · `audio_tts_robot` |

**Three run modes** — `--mode observe` (no motion) · `--mode confirm` *(default — y/N gate)* · `--mode active` (autonomous within safety bounds). Plus `--vision-only` to drop DDS for laptop-only dev.

**Run order (4 terminals, `agi` env)**

```bash
# ── Terminal 1 — MuJoCo simulator ─────────────────────────────────
conda activate unitree
export MUJOCO_GL=glfw
cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
python unitree_mujoco.py

# ── Terminal 2 — TeleImager USB cam service ──────────────────────
conda activate unitree
cd ~/unitree/unitree-notes/teleimager
python -m teleimager.image_server

# ── Terminal 3 — Independent E-stop listener (ESC → kill) ─────────
conda activate agi
python -m g1_brain.safety.estop_listener

# ── Terminal 4 — agent ───────────────────────────────────────────
conda activate agi
export OPENAI_API_KEY=sk-...
python -m g1_brain.apps.agent_main --mode confirm
```

**Built-in debug entries** — `python -m g1_brain.apps.{perception_debug, safety_debug, skill_debug, estop_test}` — each tests one layer in isolation.

> 🛡️ **Key invariant:** every tool call goes through `SafetySupervisor.validate()` (whitelist · FSM gating · run_mode · 4 watchdogs · pose check · param clamp · scene checks · E-stop). The LLM never touches motors. The independent E-stop process keeps a panic-button exit even if the agent deadlocks.

---

### 🧰 Skill Catalog (`g1_brain`)

> The 17 OpenAI tool schemas exposed to Slow Brain. Source of truth: [`g1_brain/g1_brain/skills/tool_schemas.py`](g1_brain/g1_brain/skills/tool_schemas.py). Every schema is validated against the 11 rules in [§ Safety Supervisor](#%EF%B8%8F-safety-supervisor--the-11-rules) before reaching `SkillServer`.

#### 🗣️ I/O — no-motion (always allowed outside `BOOT`)

| Tool | Signature | Purpose |
|---|---|---|
| `say` | `say(text: str ≤ 200 chars)` | Canned OpenAI TTS reply — preferred for short, scripted messages. |
| `describe_scene` | `describe_scene(question?: str, detail?: "low"\|"high")` | Snapshot the current frame → vision model → text answer. |
| `query_scene_state` | `query_scene_state(field?: str)` | Read the live `SceneState` (people, gestures, depth, robot pose) without re-running vision. |
| `recall_history` | `recall_history(turns?: int)` | Replay the last *N* user/assistant turns from the on-disk transcript JSONL. |
| `ask_human` | `ask_human(question: str)` | Pause for an explicit human reply before continuing — used when scene/safety is ambiguous. |
| `stop` | `stop()` | Zero velocity, latch arms back to the policy. Allowed even in `BOOT`. |
| `release_arms` | `release_arms()` | Hand the upper body back to locomotion (after a gesture/static pose). |

#### 🦿 Motion (gated by `STANDING/ENGAGED/ACTING` FSM states + run_mode)

| Tool | Signature | Notes |
|---|---|---|
| `walk` | `walk(vx, vy, wz, duration_s)` | Short low-speed move; clamped per `safety.params` and rejected if `scene_check_walk` fails. |
| `turn` | `turn(angle_deg, duration_s?)` | In-place yaw — convenience wrapper around `walk(0, 0, wz, …)`. |
| `gesture` | `gesture(name)` | One of **9** RL-safe gestures: `wave_right` · `wave_left` · `hands_up` · `t_pose` · `salute` · `clap` · `guard` · `punch_combo` · `hug`. |
| `static_pose` | `static_pose(name)` | One of **2** held poses: `salute` · `hug`. Held until `release_arms()`. |
| `look_at` | `look_at(target)` | One of `person` · `ahead` · `left` · `right` · `ground`. Slow-Brain's primary "where to point the head cam" verb. |
| `approach` | `approach(target?, distance_m?)` | Walk forward (with safety scene-check) until the requested distance is reached or path is blocked. |
| `mock_imitate` | `mock_imitate()` | Phase-5 imitation: pick the user's most-recently-detected pose (one of **4 mirrorable** gestures: `wave_right` · `wave_left` · `hands_up` · `t_pose`) and mirror it back. |

#### 🤖 Real-only stubs (auto-rejected in sim)

| Tool | Status |
|---|---|
| `loco_high` | High-level locomotion command on a real G1 (rejected in sim). |
| `arm_action_high` | Arm-action library command on a real G1 (rejected in sim). |
| `audio_tts_robot` | Speak through the robot's onboard speaker (rejected in sim). |

---

### 🛡️ Safety Supervisor — the 11 rules

> Source of truth: [`g1_brain/g1_brain/safety/supervisor.py`](g1_brain/g1_brain/safety/supervisor.py) — every rule below runs **in order** for every tool call. Rejection returns `(ok=False, reason, sanitized_args)`; the only side-effect is rule 7 latching the FSM into `EMERGENCY_STOP` because that signals an in-progress fall.

| # | Rule | Trips when… | Effect |
|:-:|---|---|---|
| 1 | 🔐 **Whitelist** | tool name ∉ `ALLOWED_TOOLS` | Rejection — prevents the LLM from inventing names. |
| 2 | 🚦 **FSM gating** | tool not allowed in current `RobotFsmState` (e.g. motion in `BOOT` / `FAULT`) | Rejection — see the per-state allow-lists (`_FSM_MOTION_ALLOWED`, `_FSM_NO_MOTION_ALLOWED`). |
| 3 | 🎚 **`run_mode`** | mode is `observe` and tool is motion **·** mode is `confirm` and the y/N gate failed | Rejection — `active` mode skips the gate but still passes rules 4-11. |
| 4 | ⏱ **`lowstate` watchdog** | no `rt/lowstate` packet in *N* ms (default 250 ms) | Latched trip — only `stop` / `release_arms` / no-motion tools survive. |
| 5 | 🎥 **head-cam watchdog** | no fresh head-cam frame in *N* ms (default 1000 ms) | Latched trip — vision-dependent tools (`describe_scene`, `look_at`, …) blocked. |
| 6 | 🦿 **RL-policy-active watchdog** | the locomotion policy hasn't ticked in *N* ms (e.g. backed off mid-boot) | Latched trip — motion tools blocked until the policy resumes. |
| 7 | 📐 **body pose check** | `gravity_proj_z` from `quat_imu` falls below the upright threshold | Rejection **+** FSM transitions to `EMERGENCY_STOP` (real fall in progress). |
| 8 | ✂️ **parameter clamp** | `walk(vx, vy, wz, duration)` exceeds the configured envelope | Args are sanitized in-place (clamped) before forwarding. |
| 9 | 🚧 **scene check (`walk`)** | clear-path / nearest-obstacle / nearest-person fails the configured thresholds | Rejection — `approach` and `walk` only. |
| 10 | 👤 **scene check (`gesture`)** | a person is closer than `safety.gesture_min_person_m` | Rejection — protects bystanders from `t_pose` / `punch_combo` etc. |
| 11 | 🛑 **E-stop flag** | the independent `estop_listener` process has set its IPC flag | Rejection of *every* tool — only via process exit can it be cleared. |

> 🎯 **Independent E-stop process.** `python -m g1_brain.safety.estop_listener` runs in its own terminal, listens for <kbd>Esc</kbd>, and writes a watchdog flag the supervisor polls every tick. It survives the main agent deadlocking — by design, the panic button is **not** a thread inside the same process it has to kill.

---

### 📡 Upstream Reference Repos

> All eleven directories below are **read-only snapshots** kept clean for diffability against upstream. Patch by overlay/wrapping rather than editing them in place.

| Dir | Layer | What it gives you | Deep-dive doc |
|---|---|---|:---:|
| 📂 [`unitree_sdk2_python/`](unitree_sdk2_python/) | DDS bindings | CycloneDDS Python bindings, message IDLs (`unitree_go`, `unitree_hg`), CRC, ChannelFactory. The plumbing every demo imports. | [`docs/unitree_sdk2_python.md`](docs/unitree_sdk2_python.md) |
| 📂 [`unitree_mujoco/`](unitree_mujoco/) | Sim | MJCF assets for Go2/B2/H1/G1 + Python bridge that publishes `rt/lowstate` and consumes `rt/lowcmd` so a control script can't tell sim from real. | [`docs/unitree_mujoco.md`](docs/unitree_mujoco.md) |
| 📂 [`unitree_rl_mjlab/`](unitree_rl_mjlab/) | RL | mjlab + rsl_rl + MuJoCo Warp training pipeline; sim2real deployment scripts; the `policy.onnx` checkpoint our demos run. | [`docs/unitree_rl_mjlab.md`](docs/unitree_rl_mjlab.md) |
| 📂 [`unitree_ros/`](unitree_ros/) | ROS 1 | Gazebo sim packages + URDF/SRDF for Go1/Go2/B1/B2/H1/G1/Z1/A1 — historical reference. | [`docs/unitree_ros.md`](docs/unitree_ros.md) |
| 📂 [`unitree_ros2/`](unitree_ros2/) | ROS 2 | C++ ament workspace bridging CycloneDDS topics into ROS 2 (foxy / humble / jazzy). | [`docs/unitree_ros2.md`](docs/unitree_ros2.md) · [`docs/ros2_sdk.md`](docs/ros2_sdk.md) |
| 📂 [`unitree_sim_isaaclab/`](unitree_sim_isaaclab/) | Sim | NVIDIA Isaac Lab manipulation tasks (`reset_pose_test`, `send_commands_*`) for G1 + dexterous hands; same DDS topics as real robot. | — |
| 📂 [`unitree_lerobot/`](unitree_lerobot/) | Datasets/Policies | Adapter for HuggingFace **LeRobot** v2/v3 — converts AVP/XR teleop JSON to LeRobot format, deploys ACT / Diffusion / π₀ / π₀.₅ / GR00T policies on real G1+Dex1/Dex3/Inspire/Brainco. | [`docs/unitree_lerobot.md`](docs/unitree_lerobot.md) |
| 📂 [`xr_teleoperate/`](xr_teleoperate/) | Teleop | XR / Apple Vision Pro teleoperation — body retargeting, hand pose to dex hand mapping, full-body data recording for LeRobot. | [`docs/xr_teleoperate.md`](docs/xr_teleoperate.md) |
| 📂 [`teleimager/`](teleimager/) | Vision pipe | Multi-camera image server (UVC / OpenCV / RealSense) over **ZeroMQ PUB-SUB** + WebRTC. The frame source for `xr_teleoperate` and `va-demo`. | [`docs/teleimager.md`](docs/teleimager.md) |
| 📂 [`unifolm-vla/`](unifolm-vla/) | VLA | UnifoLM-VLA-0: vision-language-action model with continued pretraining on robot manipulation data — generalises across 12 manipulation task categories with one policy. | [`docs/unifolm-vla.md`](docs/unifolm-vla.md) |
| 📂 [`unifolm-world-model-action/`](unifolm-world-model-action/) | WMA | UnifoLM-WMA-0: world-model + action head; the world model doubles as a synthetic-data simulator and as a policy-enhancement signal that predicts future interactions. | [`docs/unifolm-world-model-action.md`](docs/unifolm-world-model-action.md) |

> 🧠 New here? [`docs/vla_wma.md`](docs/vla_wma.md) is a 1-page primer on what VLA / WMA / SLAM each are and how they relate.

---

### 🧱 Architecture Overview

#### Sim demo control loop (`g1_sim_demo/*.py`, `g1_real_demo/g1_real_rl_combo.py`)

```
┌──────────────────────────────────────────────────────────────────────┐
│                        Your control script                          │
│                       (g1_sim_demo/*.py)                             │
│                                                                      │
│   ┌────────────────────┐         ┌───────────────────────────────┐  │
│   │ Keyboard / preset  │  enq.   │  Control loop (50–500 Hz)     │  │
│   │ keyframe scheduler │ ──────► │  - cosine-ease interpolation  │  │
│   └────────────────────┘         │  - or  ONNX policy inference  │  │
│                                  │  - PD targets + Kp/Kd         │  │
│                                  └────────────┬──────────────────┘  │
│                                               │                      │
└───────────────────────────────────────────────┼──────────────────────┘
                                                │ rt/lowcmd
                                                ▼
                       ┌─────────────────────────────────────┐
                       │  unitree_sdk2py  (DDS publisher)    │
                       │   CycloneDDS · domain 1 · lo        │
                       └─────────────────┬───────────────────┘
                                         │
                                         ▼
                       ┌─────────────────────────────────────┐
                       │   unitree_mujoco/simulate_python    │
                       │   MJCF: g1_29dof.xml (29 motors)    │
                       │   bridge ─►  rt/lowstate (1 kHz)    │
                       └─────────────────────────────────────┘
                                         │
                                         ▼
                       ┌─────────────────────────────────────┐
                       │      MuJoCo viewer  (GLFW)          │
                       │   '9' band on · '7' down · '8' up   │
                       └─────────────────────────────────────┘
```

🔁 **Why the same script runs on the real robot:** swap the `lo` argument for the robot's NIC name; the script flips to DDS domain 0 and the rest of the pipeline (`unitree_sdk2py` → `rt/lowcmd` → joint controllers) is identical. This is the entire point of MuJoCo "as a fake robot."

#### `va-demo` agent loop

```
┌──────────────────────────────────────────────────────────────────────────┐
│                                  va-demo                                │
│                                                                          │
│   🎤 mic                                                                 │
│   sounddevice ─► MicStream.subscribe() ──┬─► WakeWordDetector            │
│                                          │       (faster-whisper tiny)   │
│                                          │                               │
│                                          └─► UtteranceVAD (webrtcvad)    │
│                                                  │                       │
│                                                  ▼                       │
│                                       gpt-4o-transcribe                  │
│                                                  │                       │
│                                                  ▼                       │
│   📝 prompt + tools  ─►  OpenAI Realtime API (websocket, full-duplex)    │
│                                  │                                       │
│              tool calls ◄────────┤                                       │
│                                  │                                       │
│       ┌──────────────────────────┼───────────────────────────────┐       │
│       ▼                          ▼                               ▼       │
│  walk / gesture /         describe_scene                       say        │
│  stop / release_arms     (snapshot ─► gpt-5.x vision)          (TTS)      │
│       │                          │                               │       │
│       │                          │                               │       │
│       ▼                          ▼                               ▼       │
│  Safety supervisor      teleimager (ZMQ frame)            speaker out    │
│       │                                                                  │
│       ▼                                                                  │
│  ComboController  ─►  rt/lowcmd  (same DDS path as g1_sim_rl_combo.py)   │
└──────────────────────────────────────────────────────────────────────────┘
```

> 📐 Full design: [`docs/va-demo-design.md`](docs/va-demo-design.md) · run guide: [`docs/va-demo-use.md`](docs/va-demo-use.md).

---

### 🔌 DDS Topic & Joint Reference

> Quick lookup card for the most common DDS topics, message families, and the G1 29-DoF joint index map. The authoritative reference is [`docs/unitree_sdk2_python.md`](docs/unitree_sdk2_python.md).

#### 🌐 DDS domain conventions

| Where | Domain | Interface | Set by |
|---|:-:|---|---|
| 🟢 **MuJoCo simulator** | **1** | `lo` | `unitree_mujoco/simulate_python/config.py::DOMAIN_ID, INTERFACE` |
| 🦿 **Real G1 (EDU)** | **0** | NIC on `192.168.123.0/24` (e.g. `enp3s0`, `eno3`) | first CLI argument to every `g1_*_demo` script |

> 🔁 **Same script, two destinations:** every demo script accepts the interface name as `argv[1]`; passing `lo` keeps it on domain 1 (sim), passing a real NIC name flips it to domain 0 (hardware). The `unitree_sdk2py` ↔ DDS layer is identical in both cases.

#### 📨 Topics every demo touches

| Topic | Direction (control script's POV) | Message | Rate | Used by |
|---|:-:|---|:-:|---|
| `rt/lowstate` | ◀ subscribe | `unitree_hg::LowState_` | 1 kHz | every demo (joint angles, velocities, torques, IMU `quat_imu`, `gyroscope`, foot force) |
| `rt/lowcmd` | ▶ publish | `unitree_hg::LowCmd_` | 50–500 Hz | every demo (per-joint `q`, `dq`, `kp`, `kd`, `tau`) |
| `rt/sportmodestate` | ◀ subscribe | `unitree_hg::SportModeState_` | 50 Hz | high-level mode introspection (real robot only) |
| `rt/api/loco/request` | ▶ publish | `unitree_api::Request_` | on demand | `loco_high` skill (`g1_brain`, real only) |
| `rt/api/motion_switcher/request` | ▶ publish | `unitree_api::Request_` | once at startup | `MotionSwitcherClient.ReleaseMode()` (real only) |

> 🧷 **CRC matters.** Every `rt/lowcmd` packet has a CRC field that the bridge / robot validates. `unitree_sdk2py.utils.crc.CRC` computes it; if you forget to set it, motors silently ignore the command. All in-house demos call `cmd.crc = CRC().Crc(cmd)` before each publish.

#### 🦴 G1 29-DoF joint index map

| Index | Joint | Group |
|:-:|---|---|
| 0–5 | `left_hip_pitch` · `left_hip_roll` · `left_hip_yaw` · `left_knee` · `left_ankle_pitch` · `left_ankle_roll` | 🦵 Left leg |
| 6–11 | `right_hip_pitch` · `right_hip_roll` · `right_hip_yaw` · `right_knee` · `right_ankle_pitch` · `right_ankle_roll` | 🦵 Right leg |
| 12–14 | `waist_yaw` · `waist_roll` · `waist_pitch` | 🦴 Waist |
| 15–21 | `left_shoulder_pitch` · `left_shoulder_roll` · `left_shoulder_yaw` · `left_elbow` · `left_wrist_roll` · `left_wrist_pitch` · `left_wrist_yaw` | 🦾 Left arm |
| 22–28 | `right_shoulder_pitch` · `right_shoulder_roll` · `right_shoulder_yaw` · `right_elbow` · `right_wrist_roll` · `right_wrist_pitch` · `right_wrist_yaw` | 🦾 Right arm |

> 🤹 **Why 15–28 is special:** `g1_sim_rl_combo.py` and `g1_real_rl_combo.py` only override the **upper-body slice (joints 15–28)** with arm gestures. Legs + waist (0–14) stay fully under the RL policy so the locomotion controller never sees an OOD command. The override values are clipped to the policy-tolerant envelope captured during training.

#### 🎚 Two ankle modes (PR vs AB)

| Mode | What's published | When |
|---|---|---|
| **PR** (Pitch-Roll) | One target per ankle joint directly | First half of `g1_sim_low_level.py`; default for kinematic teleop. |
| **AB** (A/B linkage) | A/B parallel-linkage targets | Second half of `g1_sim_low_level.py`; required by some RL policies trained on the parallel-linkage abstraction. |

---

### 📚 Documentation Index

> All docs are Chinese (🇨🇳) unless noted. The deep-dives are **300–2 000 lines each** — they read more like book chapters than READMEs.

#### 🧭 Cross-cutting

| Doc | Scope |
|---|---|
| [`docs/demo-overall.md`](docs/demo-overall.md) | One-page tour: how to run a demo from each of the six core repos in MuJoCo, with a WSL2 GPU-accel preface. |
| [`docs/demo_run.md`](docs/demo_run.md) | Master cheat-sheet: every demo command in this repo, copy-pasteable. |
| [`docs/libs_compatible.md`](docs/libs_compatible.md) | The full compatibility matrix that defines the `agi` env — pin-by-pin reasoning. |
| [`docs/wsl2_audio.md`](docs/wsl2_audio.md) | How to fix `sounddevice`/PortAudio under WSL2 + conda. |
| [`docs/camera_ui_demo.md`](docs/camera_ui_demo.md) | `usbipd` → WSL2 → `teleimager.image_server` → live video. |
| [`docs/ros2_sdk.md`](docs/ros2_sdk.md) | The ROS / ROS 2 vs Unitree SDK lineage, and how `unitree_ros2` plugs in. |
| [`docs/vla_wma.md`](docs/vla_wma.md) | One-page primer: VLA vs WMA vs SLAM. |
| [`docs/vlm_audio_mock.md`](docs/vlm_audio_mock.md) · [`vlm_audio_mock_deep.md`](docs/vlm_audio_mock_deep.md) | The full G1 VLM + audio + human-mimic research plan that motivated `va-demo`. |
| [`instructions.md`](instructions.md) | Curated run-orders for `mujoco rl_combo` and `mujoco + va-demo` with WSL2 USB-camera attach. |

#### 🎮 In-house demos

| Doc | Scope |
|---|---|
| [`g1_sim_demo/docs/G1 MuJoCo SDK Bridge Demo.md`](g1_sim_demo/docs/G1%20MuJoCo%20SDK%20Bridge%20Demo.md) | Why upstream G1 low-level breaks in sim, and how this repo fixes it. |
| [`g1_sim_demo/docs/learn-mujoco.md`](g1_sim_demo/docs/learn-mujoco.md) | First-principles MuJoCo tutorial (XML, joints, contacts, viewer). 1 700 lines. |
| [`g1_sim_demo/docs/how to use mujoco demo and customize motions.md`](g1_sim_demo/docs/how%20to%20use%20mujoco%20demo%20and%20customize%20motions.md) | How to design new keyframe sequences. |
| [`g1_sim_demo/docs/demo-explain.md`](g1_sim_demo/docs/demo-explain.md) | What each `g1_sim_*.py` script does, line-by-line. |
| [`g1_sim_demo/docs/mujoco_use1.md`](g1_sim_demo/docs/mujoco_use1.md) · [`mujoco_use2.md`](g1_sim_demo/docs/mujoco_use2.md) | MuJoCo viewer usage cookbook. |
| [`g1_sim_demo/docs/demo-QA1.md`](g1_sim_demo/docs/demo-QA1.md) … [`demo-QA5.md`](g1_sim_demo/docs/demo-QA5.md) | Five rounds of progressive Q&A: keyboard latency, action_scale, OOD inputs, gesture envelopes. |
| [`g1_sim_demo/docs/report.md`](g1_sim_demo/docs/report.md) | End-of-iteration design report. |
| [`g1_real_demo/docs/demo-QA7.md`](g1_real_demo/docs/demo-QA7.md) | `lying`-mode wiring/DDS verification on the real robot. |
| [`g1_real_demo/issue/realmachine.md`](g1_real_demo/issue/realmachine.md) | Diagnosis log for "robot doesn't move" on real hardware. |

#### 🎙️ va-demo

| Doc | Scope |
|---|---|
| [`docs/va-demo-design.md`](docs/va-demo-design.md) | The voice + vision + Realtime agent design spec. |
| [`docs/va-demo-use.md`](docs/va-demo-use.md) | Full run guide for all `--mode` combinations. |
| [`docs/va-design.md`](docs/va-design.md) | Phase-by-phase completion summary. |
| [`va-demo/docs/audio-awake.md`](va-demo/docs/audio-awake.md) | Wake-word + state-machine implementation deep-dive. |
| [`va-demo/docs/audio-use.md`](va-demo/docs/audio-use.md) | Tuning guide: VAD thresholds, RMS gates, listening windows. |
| [`va-demo/docs/video-design.md`](va-demo/docs/video-design.md) | Vision-only mode design. |
| [`va-demo/docs/video-use.md`](va-demo/docs/video-use.md) | Vision-only mode operator guide. |

#### 🧠 g1_brain

| Doc | Scope |
|---|---|
| [`g1_brain/README.md`](g1_brain/README.md) | 📍 Package landing page — highlights, layout, install, run, modes, skills, safety, perception, mock imitation, configuration, debug entries, tests, troubleshooting. |
| [`docs/g1_plan.md`](docs/g1_plan.md) | The full 1500+-line design that motivated `g1_brain` (Slow Brain + Fast Reflex + Safe Skill, Phases 0–7). |
| [`docs/vlm_audio_mock.md`](docs/vlm_audio_mock.md) · [`vlm_audio_mock_deep.md`](docs/vlm_audio_mock_deep.md) | Architecture-level research notes that fed the design — VLM + audio + human-mimic primer. |
| [`g1_brain/docs/architecture.md`](g1_brain/docs/architecture.md) | ~330-line cliffs-notes architecture (3 layers, frequency table, FSM, perception threading, process model). |
| [`g1_brain/docs/how_to_run.md`](g1_brain/docs/how_to_run.md) | Operator guide — prereqs, 4-terminal startup, debug entries, run modes, common errors, sim → real switch, WSL2 specifics. |
| [`g1_brain/docs/extending_skills.md`](g1_brain/docs/extending_skills.md) | The 4 places to touch when adding a new tool, plus a checklist. |
| [`g1_brain/docs/g1_brain_QA1.md`](g1_brain/docs/g1_brain_QA1.md) | Q&A round 1 — gotchas around `how_to_run.md`. |
| [`g1_brain/docs/g1-fix-phase1.md`](g1_brain/docs/g1-fix-phase1.md) | Fix log: post-boot pose oscillation. |
| [`g1_brain/docs/g1-fix-phase2.md`](g1_brain/docs/g1-fix-phase2.md) | Fix log: RL ramp + watchdog grace + recovery hold. |
| [`g1_brain/docs/g1-fix-phase3.md`](g1_brain/docs/g1-fix-phase3.md) | Fix log: head-cam EGL threading + DDS subscription order. |
| [`g1_brain/docs/g1-fix-phase5.md`](g1_brain/docs/g1-fix-phase5.md) | Fix log: USB watchdog locking gestures even when USB cam disabled. |

#### 📡 Upstream deep-dives

| Doc | Scope |
|---|---|
| [`docs/unitree_sdk2_python.md`](docs/unitree_sdk2_python.md) | DDS topics, message IDLs, ChannelFactory, CRC, joint indices. |
| [`docs/unitree_mujoco.md`](docs/unitree_mujoco.md) | Simulator architecture, bridge internals, MJCF / scene authoring. |
| [`docs/unitree_rl_mjlab.md`](docs/unitree_rl_mjlab.md) | RL framework, training pipeline, sim2real deployment. |
| [`docs/unitree_ros.md`](docs/unitree_ros.md) | ROS 1 + Gazebo packages, every URDF/SRDF in the tree. |
| [`docs/unitree_ros2.md`](docs/unitree_ros2.md) | ROS 2 bridge, Cyclone XML config, dev container layout. |
| [`docs/unitree_lerobot.md`](docs/unitree_lerobot.md) | LeRobot v2/v3 conversion, policy training, real-G1 deployment. |
| [`docs/xr_teleoperate.md`](docs/xr_teleoperate.md) | XR / AVP teleop architecture, retargeting, recording. |
| [`docs/teleimager.md`](docs/teleimager.md) | Multi-camera ZMQ + WebRTC server internals. |
| [`docs/unifolm-vla.md`](docs/unifolm-vla.md) | Per-file walkthrough of the VLA codebase. |
| [`docs/unifolm-world-model-action.md`](docs/unifolm-world-model-action.md) | Per-file walkthrough of the WMA codebase. |
| `docs/Unitree G1 相关 GitHub 仓库深度调研报告.pdf` | Long-form survey report (PDF). |

---

### 📈 Performance & Resource Notes

> Order-of-magnitude numbers measured on the reference dev box (Ryzen 7 7840HS · RTX 4060 Laptop 8 GB · 32 GB RAM · WSL2 + WSLg, Ubuntu 22.04). Take them as ballpark, not benchmarks.

#### ⏱ Tick rates

| Loop | Where | Typical rate | Comment |
|---|---|:-:|---|
| 🦴 Bridge `rt/lowstate` | `unitree_mujoco` | **1 kHz** | Set by the MuJoCo step + bridge loop; matches the real robot. |
| 🚶 RL policy inference | `g1_sim_rl_*.py` | **50 Hz** | ONNX Runtime CPU is usually faster than this — bottleneck is the publish cadence we choose. |
| 🤹 Combo upper-body override | `g1_sim_rl_combo.py` | **50 Hz** (same loop) | Single publisher → no DDS races. |
| 🧠 Slow Brain (Realtime API) | `g1_brain` | **0.2–2 Hz** | Bounded by network round-trip + LLM thinking. |
| ⚡ Fast Reflex (perception) | `g1_brain.perception` | **5–30 Hz** | YOLO11 + MediaPipe-Pose + depth fusion; capped by camera FPS. |
| 🎤 Wake-word check | `va-demo.wake_word` | **8–16 Hz** | `faster-whisper tiny` on CPU; ~50–100 ms per shot. |

#### 💾 Memory & disk

| Resource | Footprint | Notes |
|---|---|---|
| 🟢 `unitree` env (RSS at idle) | ~ **400 MB** | Pure Python + ONNX + MuJoCo. |
| 🔵 `agi` env (RSS at idle) | ~ **1.2 GB** | Adds torch / transformers / mediapipe / ultralytics. Vision agent peaks around 3–4 GB once vision is hot. |
| 🐍 `agi` env on disk | ~ **14 GB** | Dominated by `nvidia-*` CUDA-13 wheels, torch, tensorflow, mujoco-warp. |
| 🪞 `g1_brain` head-cam (EGL) | ~ **400 MB** RAM, **~ 0.5 GB** GPU | Each camera clones its own `MjModel` to keep the EGL context single-threaded. |
| 🎬 RL ONNX checkpoint | ~ **2 MB** | Tiny — `policy.onnx` is a pure MLP. |

#### 🌡 Common bottlenecks

- 🥵 **WSL2 + sounddevice CPU spike** when `audio.input_block_ms < 20` — keep ≥ 20 ms.
- 🌐 **Realtime websocket latency** dominates Slow Brain perceived latency; nearby OpenAI region helps more than any local optimization.
- 🧊 **First MuJoCo step** under WSL2's D3D12 GL path takes 1–2 s; subsequent steps are < 0.5 ms. Don't put the `np.set_printoptions` style warm-up inside the control loop.

---

### 🗺️ Roadmap & Status

> Snapshot of what's stable, what's actively being polished, and what's on the wishlist. Not all items are mine to ship — some are upstream-tracked.

#### ✅ Stable

- `g1_sim_demo/g1_sim_low_level.py` · `g1_sim_interactive.py` · `g1_sim_keyboard.py` — sine-wave + keyframe playgrounds.
- `g1_sim_demo/g1_sim_rl_walk.py` · `g1_sim_rl_combo.py` — RL walk + arm-gesture combo.
- `g1_real_demo/g1_real_rl_combo.py` — real-robot port (with `lying` test mode).
- `va-demo/` — wake-word-gated Realtime voice + vision agent (4 run modes).
- `g1_brain/` — Slow-Brain + Fast-Reflex + Safe-Skill agent: 11-rule supervisor · 7-state FSM · independent E-stop · 17 LLM-callable skills · MuJoCo head-cam perception · `mock_imitate` (Phase 5).
- `requirements.txt` — frozen `agi` env reproducible from `python=3.11` + `pip install -r requirements.txt`.

#### 🚧 In progress / refining

- 🧠 Persistent voice transcript schema for future SQLite + FTS5 ingest (typed content blocks, `uuid`, `session_id`).
- 🎯 Vision-risk-gate (`g1_brain/safety/vision_risk_gate.py`) — additional checks beyond the 11 rules, for ambiguous human-proximity cases.
- 🦿 Real-robot validation of `mock_imitate` end-to-end (sim works; real-robot mirror loop is being tuned).
- 📷 Stereo / RealSense head-cam path for true depth (currently uses MuJoCo monocular with derivation).

#### 🌱 Wishlist

- 🤗 Bridging `unitree_lerobot` ACT / Diffusion / π₀ policies into the `g1_brain` skill server.
- 🌐 ROS 2 Jazzy bridge for the `g1_brain` `SceneState` so other ROS nodes can subscribe to fused perception.
- 🧬 World-model rollouts via `unifolm-world-model-action` as a planning aid before `walk` is dispatched.
- 🧤 Dex-hand teleop loop — `xr_teleoperate` → `g1_brain` skills → real Dex3 / Inspire / Brainco hand.

> 🤝 **Want to help?** [§ Contributing](#-contributing) lists the kinds of PRs that fit best.

---

### 🛠️ Troubleshooting

<details>
<summary><b>🔴 Terminal 2 hangs on <code>waiting for first /rt/lowstate</code></b></summary>

The simulator is not running, **or** the DDS domain / interface does not match. Verify:

```python
# unitree_mujoco/simulate_python/config.py
DOMAIN_ID = 1
INTERFACE = "lo"
```

and that Terminal 1's `python unitree_mujoco.py` is still alive.
</details>

<details>
<summary><b>🔴 The robot collapses the moment the script starts</b></summary>

You forgot the elastic band. In the MuJoCo viewer press <kbd>9</kbd> **before** running any control script. For RL walk demos, press <kbd>8</kbd> a few times to **lower** the band so the feet just touch the ground, then optionally press <kbd>9</kbd> to disable the band — but only after `[rl] policy ready` is printed.
</details>

<details>
<summary><b>🔴 GLFW / viewer fails to open under WSL2</b></summary>

WSLg should set `$DISPLAY` automatically. If you SSH'd in, use `ssh -X user@host`. If it still fails, run `glxinfo | head` to confirm OpenGL is available. For GPU acceleration, [`instructions.md`](instructions.md) shows the `MESA_LOADER_DRIVER_OVERRIDE=d3d12` / `MUJOCO_GL=glfw` block that switches WSL2 onto the NVIDIA D3D12 path.
</details>

<details>
<summary><b>🔴 <code>ModuleNotFoundError: unitree_sdk2py</code></b></summary>

Install the SDK in editable mode from this repo:

```bash
pip install -e unitree_sdk2_python
```
</details>

<details>
<summary><b>🔴 CRC failure / motors don't move (sim)</b></summary>

The simulator must load the G1 29-DOF scene (default when `ROBOT="g1"`), and the bridge must speak the `unitree_hg` message family — both happen automatically when `config.ROBOT == "g1"`. Re-check the simulator config.
</details>

<details>
<summary><b>🔴 Real robot: bridge launches but joints don't respond</b></summary>

The G1's onboard high-level controller is still owning `rt/lowcmd`. `g1_real_demo/g1_real_rl_combo.py` calls `MotionSwitcherClient.ReleaseMode()` to fix this — confirm the call succeeded in stdout. See [`g1_real_demo/issue/realmachine.md`](g1_real_demo/issue/realmachine.md) for the full incident log.
</details>

<details>
<summary><b>🔴 va-demo: <code>OSError: PortAudioError ... device unavailable</code></b></summary>

Your WSL/Linux audio stack isn't exposing a default mic/speaker. Three fixes, in order:

1. Apply the conda-env ALSA→Pulse symlink from [`docs/wsl2_audio.md`](docs/wsl2_audio.md).
2. `conda install -n agi -c conda-forge portaudio`.
3. Set explicit `audio.input_device` / `audio.output_device` indices in `va-demo/configs/va_demo.yaml` from `python -c "import sounddevice as sd; print(sd.query_devices())"`.
</details>

<details>
<summary><b>🔴 va-demo: <code>no frame received</code></b></summary>

`teleimager.image_server` isn't running, **or** the camera isn't attached to WSL2. Run `usbipd attach --wsl --busid <id>` from PowerShell (see [`docs/camera_ui_demo.md`](docs/camera_ui_demo.md)) and confirm the `head_camera::zmq_port` in `cam_config_server.yaml` matches what `va_demo.yaml` expects.
</details>

<details>
<summary><b>🔴 va-demo: model never wakes up on "Hi Sparky"</b></summary>

Two knobs in `configs/va_demo.yaml::wakeword`:

- `rms_threshold` — raise if it triggers on background sound, lower if it ignores you.
- `phrases` — add accent variants ("hi sparkie", "嗨 spark") to the substring list.

Run `python scripts/wake_word_debug.py` to see the matcher's per-frame decisions live.
</details>

<details>
<summary><b>🔴 <code>numpy</code> ABI mismatch / <code>torch</code> import error in the <code>agi</code> env</b></summary>

Almost always means a fresh `pip install` upgraded numpy past 2.0. Re-pin:

```bash
pip install --force-reinstall "numpy==1.26.4"
```

The full set of pins that survives all 7 upstreams is in [`docs/libs_compatible.md`](docs/libs_compatible.md), and the verbatim freeze is in the repo-root [`requirements.txt`](requirements.txt).
</details>

<details>
<summary><b>🔴 <code>g1_brain</code>: head-cam stuck at 0 FPS / SafetySupervisor rule 5 keeps tripping</b></summary>

The MuJoCo head cam runs a single-threaded EGL context with its own cloned `MjModel`. Two common causes:

1. The `robot.mjcf_path` in `configs/g1_brain.yaml` doesn't match what `unitree_mujoco` is actually loading — set both sides to the same scene XML (terrain vs. plain) so the brain's clone matches the operator's view.
2. `MUJOCO_GL` isn't set to `glfw` (or `egl` on a headless box). Add `export MUJOCO_GL=glfw` to the simulator terminal.

See [`g1_brain/docs/g1-fix-phase3.md`](g1_brain/docs/g1-fix-phase3.md) for the full incident log on EGL threading + DDS subscription order.
</details>

<details>
<summary><b>🔴 <code>g1_brain</code>: motion tools rejected with <code>"FSM gating"</code> right after boot</b></summary>

Rule 2 (FSM gating) keeps motion calls out of `BOOT`. The agent transitions through `BOOT → STANDING → ENGAGED → ACTING` as `lowstate` arrives, the RL policy ramps, and the run-mode gate clears. The transition is automatic — usually < 2 s. If you're stuck in `BOOT`:

- Confirm `lowstate` is flowing (`Terminal 2` simulator alive, `DOMAIN_ID=1`, `INTERFACE=lo`).
- Confirm the RL policy has logged `[rl] policy ready` — rule 6 won't clear until then.
- See the FSM diagram in [`g1_brain/docs/architecture.md`](g1_brain/docs/architecture.md).
</details>

<details>
<summary><b>🔴 <code>pip install -e ./unitree_sdk2_python</code> fails with <code>cyclonedds</code> wheel build</b></summary>

CycloneDDS Python bindings only have prebuilt wheels for Linux x86_64 + CPython 3.10/3.11. On macOS or Windows native (or Python 3.12), the wheel falls back to source build and almost always fails. Use **WSL2 + Ubuntu 22.04 / 24.04** with **Python 3.11** as documented in [§ Prerequisites](#-prerequisites).
</details>

<details>
<summary><b>🔴 Realtime websocket disconnects every ~30 s</b></summary>

Most often a network proxy / VPN issue — the OpenAI Realtime API uses a long-lived websocket and aggressive corp proxies will close idle TCP. Either run direct, or whitelist `api.openai.com` in your proxy config. `va-demo` already pings the websocket with a `response.create` keep-alive, so anything < 30 s is upstream.
</details>

<details>
<summary><b>🔴 <code>requirements.txt</code> install fails on <code>-e ./unifolm-vla</code></b></summary>

The unpatched upstream `pyproject.toml` pins `numpy >= 2.0`, which fights the resolved `numpy==1.26.4`. The repo ships `pyproject.toml.bak` files documenting the ghost-pin removal — apply them (or follow the manual edits in [`docs/libs_compatible.md`](docs/libs_compatible.md)) and re-run.
</details>

<details>
<summary><b>🔴 Real robot: <code>MotionSwitcher</code> release succeeds but the robot still ignores commands</b></summary>

Two follow-ups after `ReleaseMode()`:

1. The robot's mode-switch acknowledgement arrives in `rt/sportmodestate` — wait for `mode == 0` (debug / low-level) before publishing `rt/lowcmd`. `g1_real_rl_combo.py` does this; if you wrote a custom script, mirror that handshake.
2. If the e-stop button on the robot is engaged, no low-level command will execute. Confirm the LED status before assuming a software fault.

Full incident log: [`g1_real_demo/issue/realmachine.md`](g1_real_demo/issue/realmachine.md).
</details>

---

### ❓ FAQ

<details>
<summary><b>❓ Do I need a real Unitree G1 to use this repo?</b></summary>

No. Every demo runs against the MuJoCo bridge first; `g1_real_demo/` is only relevant when you have a physical G1 EDU on the same LAN. The voice + vision agent (`va-demo/`) and the cognition agent (`g1_brain/`) work entirely in sim.
</details>

<details>
<summary><b>❓ Can I use this on macOS or native Windows?</b></summary>

Not currently. CycloneDDS Python wheels exist only for Linux x86_64; the rest of the stack (mujoco, torch+cu130, mediapipe) all ship Linux wheels you can rely on. Use **Ubuntu 22.04 / 24.04** or **WSL2 + WSLg** under Windows 11.
</details>

<details>
<summary><b>❓ Can I run <code>g1_brain</code> without an OpenAI API key?</b></summary>

Partial yes — the perception layer, scene-state bus, and skill server all run without any LLM, and you can drive them from `python -m g1_brain.apps.skill_debug` or `safety_debug`. The Slow-Brain layer (Realtime + Vision) does require `OPENAI_API_KEY`.
</details>

<details>
<summary><b>❓ Why pin <code>numpy</code> at 1.26.4 instead of upgrading to 2.x?</b></summary>

`tensorflow 2.15`, `mediapipe 0.10`, several `unifolm-*` packages, and a few of the older `cyclonedds`-adjacent libraries still build against the numpy 1.x ABI. Upgrading numpy past 2.0 reliably breaks at least three of the seven upstreams resolved in the `agi` env. The full reasoning is in [`docs/libs_compatible.md`](docs/libs_compatible.md).
</details>

<details>
<summary><b>❓ Why pin <code>mujoco</code> at exactly 3.5.0?</b></summary>

`mujoco-warp 3.5.0` (the GPU backend used by `unitree_rl_mjlab` for training) requires an exact version match — the C ABI surface across mujoco / mujoco-warp / `mjlab` is not stable across patch versions yet.
</details>

<details>
<summary><b>❓ How do I add a new skill to <code>g1_brain</code>?</b></summary>

Four edits, in this order: (1) add the schema in `g1_brain/skills/tool_schemas.py`; (2) implement the handler in `g1_brain/skills/skill_server.py`; (3) add it to the FSM allow-lists in `g1_brain/safety/supervisor.py`; (4) extend tests under `g1_brain/tests/`. The full checklist is in [`g1_brain/docs/extending_skills.md`](g1_brain/docs/extending_skills.md).
</details>

<details>
<summary><b>❓ Can I plug in a different LLM provider (Claude, Gemini, local)?</b></summary>

`va-demo` and `g1_brain` are wired for the OpenAI Realtime API specifically — its server-VAD turn model and tool-call schema shape several layers (transcript persistence, prompt structure, vision call). A non-Realtime adapter is plausible but not in-tree; a `BrainRealtimeAgent` subclass + a transport shim is the smallest viable cut.
</details>

<details>
<summary><b>❓ How big is the GPU footprint?</b></summary>

For inference (sim playback, `g1_brain` perception) a 6 GB GPU is comfortable; an 8 GB laptop GPU runs YOLO11 + MediaPipe-Pose + the Realtime client + a head-cam snapshot pipeline simultaneously without OOM. RL **training** (`unitree_rl_mjlab`) wants 16+ GB; that's not run on the dev box, it's a cluster job.
</details>

---

### 🤝 Contributing

Contributions are welcome — especially:

- 🆕 **New demos** under `g1_sim_demo/` or `g1_real_demo/` (e.g. teleoperation via `pygame`, ROS 2 bridge, MoCap retargeting).
- 🎙️ **va-demo skills** (new tool calls — e.g. `look_at(target)`, `count_steps_to(object)`).
- 🧠 **`g1_brain/` skills, safety rules, or perception derivations** — see [`g1_brain/docs/extending_skills.md`](g1_brain/docs/extending_skills.md) for the 4-step recipe.
- 📝 **Documentation translations** (English versions of the `docs/*.md` deep-dives).
- 🐛 **Bug fixes** in any of the in-house scripts.

#### Workflow

```bash
# fork → clone → branch
git checkout -b feature/my-cool-demo

# write code under g1_sim_demo/ or va-demo/, follow the existing
# module-docstring pattern (run order, architecture overview, key map, deps)

# verify
python g1_sim_demo/my_cool_demo.py
# or
cd va-demo && python -m pytest tests/ -v

# commit + push + open a PR
git commit -m "feat: add <demo name>"
git push origin feature/my-cool-demo
```

> 🙅 **Please do not modify** the upstream snapshot directories (`unitree_sdk2_python/`, `unitree_mujoco/`, `unitree_rl_mjlab/`, `unitree_ros/`, `unitree_ros2/`, `unitree_sim_isaaclab/`, `unitree_lerobot/`, `xr_teleoperate/`, `teleimager/`, `unifolm-vla/`, `unifolm-world-model-action/`) — they are kept clean for diffability against upstream. Vendor patches by overlaying or wrapping instead. The two `pyproject.toml.bak` files document where ghost-pin edits are required for `agi` env compatibility.

---

### 📜 License

This repository contains code under multiple licenses:

| Path | License | Source |
|---|---|---|
| `g1_sim_demo/`, `g1_real_demo/`, `va-demo/`, `g1_brain/`, `docs/`, `instructions.md`, `requirements.txt`, `README.md` | **Apache 2.0** | This repository |
| `unitree_sdk2_python/`, `unitree_mujoco/`, `unitree_rl_mjlab/`, `unitree_ros/`, `unitree_ros2/`, `unitree_sim_isaaclab/`, `unitree_lerobot/`, `xr_teleoperate/`, `teleimager/` | See each repo's `LICENSE` | © Unitree Robotics |
| `unifolm-vla/`, `unifolm-world-model-action/` | See each repo's `LICENSE` | © Unitree Robotics / UnifoLM |

When redistributing, retain each upstream license file and any required NOTICE.

---

### 🙏 Acknowledgements

This project would not exist without the generous open-source releases from:

- 🏢 **[Unitree Robotics](https://www.unitree.com/)** — for the SDK, MuJoCo bridge, `mjlab`-based RL framework, IsaacLab tasks, LeRobot adapter, XR teleop, image server, and the UnifoLM model family.
- 🔬 **[Google DeepMind / MuJoCo team](https://mujoco.org/)** — for the physics engine.
- 🧠 **[`rsl_rl`](https://github.com/leggedrobotics/rsl_rl)** by ETH Robotic Systems Lab — for the on-policy PPO trainer.
- ⚡ **[NVIDIA Warp](https://github.com/NVIDIA/warp) & [Isaac Lab](https://isaac-sim.github.io/IsaacLab/)** — for the GPU-accelerated MuJoCo Warp backend and the manipulation simulator.
- 🤗 **[HuggingFace LeRobot](https://github.com/huggingface/lerobot)** — for the dataset format and policy zoo (ACT / Diffusion / π₀ / GR00T).
- 🎙️ **[OpenAI Realtime / Vision / TTS APIs](https://platform.openai.com/)** — for the cognition layer behind `va-demo`.
- 🔊 **[`faster-whisper`](https://github.com/SYSTRAN/faster-whisper) & [`webrtcvad`](https://github.com/wiseman/py-webrtcvad)** — for the local wake-word + utterance-VAD pipeline.

If this repo helped you, **a ⭐ on GitHub is the cheapest way to say thanks.**

---

<br/>

<a id="-简体中文"></a>

## 🇨🇳 简体中文

> 一个为 **宇树 G1 人形机器人** 量身打造的、完整的、有观点的研究 / 仿真 / 真机部署工作区。仓库里同时包含 **十一份上游参考代码快照**（SDK · MuJoCo · RL · ROS 1 · ROS 2 · IsaacLab · LeRobot · VLA · WMA · XR 遥操 · 图像服务器）和四套自研交付物：[`g1_sim_demo/`](g1_sim_demo/)（从正弦波到 RL+手势的仿真 demo）、[`g1_real_demo/`](g1_real_demo/)（真机部署）、[`va-demo/`](va-demo/)（基于 OpenAI Realtime 的语音 + 视觉智能体）和 [`g1_brain/`](g1_brain/)（在 va-demo 之上叠加感知 / **11 条安全规则** / **17 个 LLM 工具**的"慢脑 + 快反射 + 安全技能"三层认知智能体）。

### 📑 目录

- [✨ 核心亮点](#-核心亮点)
- [📊 一图速览](#-一图速览)
- [🗂️ 仓库结构](#%EF%B8%8F-仓库结构)
- [🐍 两个 Conda 环境](#-两个-conda-环境)
- [📦 环境依赖](#-环境依赖)
- [🚀 快速开始](#-快速开始)
- [🎹 按键速查表](#-按键速查表)
- [🌟 自研交付物](#-自研交付物)
  - [🎬 `g1_sim_demo/` — MuJoCo Demo 一览](#-g1_sim_demo--mujoco-demo-一览)
  - [🦿 `g1_real_demo/` — 真机部署](#-g1_real_demo--真机部署)
  - [🎙️ `va-demo/` — 语音 + 视觉智能体](#%EF%B8%8F-va-demo--语音--视觉智能体)
  - [🧠 `g1_brain/` — 慢脑 + 快反射 + 安全技能 智能体](#-g1_brain--慢脑--快反射--安全技能-智能体)
- [🧰 技能目录（`g1_brain`）](#-技能目录g1_brain)
- [🛡️ 安全监督器 — 11 条规则](#%EF%B8%8F-安全监督器--11-条规则)
- [📡 上游参考仓库](#-上游参考仓库)
- [🧱 架构总览](#-架构总览)
- [🔌 DDS Topic 与关节速查](#-dds-topic-与关节速查)
- [📚 文档索引](#-文档索引)
- [📈 性能与资源占用](#-性能与资源占用)
- [🗺️ 路线图与状态](#%EF%B8%8F-路线图与状态)
- [🛠️ 故障排查](#%EF%B8%8F-故障排查)
- [❓ 常见问题（FAQ）](#-常见问题faq)
- [🤝 参与贡献](#-参与贡献)
- [📜 许可证](#-许可证)
- [🙏 致谢](#-致谢)

---

### ✨ 核心亮点

| | |
|---|---|
| 🤖 **十一个上游仓库一站到位** | 同时托管 `unitree_sdk2_python`、`unitree_mujoco`、`unitree_rl_mjlab`、`unitree_ros`、`unitree_ros2`、`unitree_sim_isaaclab`、`unitree_lerobot`、`xr_teleoperate`、`teleimager`、`unifolm-vla`、`unifolm-world-model-action` 的固定快照——G1 软件栈每一层都能在一个 `cd` 内读到。 |
| 🎮 **五个开箱即用的 G1 仿真 demo** | 从 70 行的"发一段正弦波"热身脚本，到 1000 行的 RL+手势 combo 控制器，每个脚本都写满了 inline 注释，对着 Python MuJoCo 桥接器 **直接就能跑**。 |
| 🦿 **真机部署脚手架** | `g1_real_demo/g1_real_rl_combo.py` 在 sim 版本基础上加了 `MotionSwitcher` 释放、有界 `lowstate` 等待和 `lying` 检线模式——在让机器人站起来之前就能验证 DDS 通路。 |
| 🎙️ **语音 + 视觉 Realtime 智能体** | `va-demo/` 自带"嗨 Sparky"唤醒词的 OpenAI Realtime 全双工语音智能体，可以**调用视觉**描述场景，也能**工具调用** `walk` / `gesture` / `stop` 直接驱动 RL 策略——支持 confirm / observe / active / vision-only 四种运行模式。 |
| 🧠 **慢脑 + 快反射 + 安全技能** | `g1_brain/` 在 `va-demo` 之上加 3 层智能体——MuJoCo 头摄第一视角 + YOLO11 + MediaPipe-Pose 融合成线程安全的 `SceneState`；**11 条安全规则**的 SafetySupervisor + 7 状态 FSM + 独立进程 E-stop；以及 **17 个 LLM 可调用技能**，覆盖 I/O、运动、仅真机三大类（`walk` · `turn` · `gesture` · `static_pose` · `look_at` · `approach` · `mock_imitate` · `describe_scene` · `query_scene_state` · `recall_history` · `ask_human` · …）。详见 [`g1_brain/README.md`](g1_brain/README.md)。 |
| 🧠 **真 ONNX 策略闭环跑** | `g1_sim_rl_walk.py`、`g1_sim_rl_combo.py`、`g1_real_rl_combo.py` 全部直接加载 `unitree_rl_mjlab` 官方的速度跟踪 ONNX checkpoint——sim 和真机走的是同一条 obs/action 流水线。 |
| 🧷 **针对仿真的修复内置** | 上游 `g1_low_level_example.py` 在仿真里会卡死在 `MotionSwitcherClient.CheckMode()`，且 DDS domain 写死为 0。本仓库脚本默认走 domain 1、跳过 MotionSwitcher、并补上 `mode_machine` 握手。 |
| 🐍 **统一的一份 conda 环境** | `agi` env 把 **7 个互相冲突的上游** 调和成 **~310 个完全锁定版本的依赖包**（numpy 1.26.4 + torch 2.11.0+cu130 + mujoco 3.5.0 + tyro 1.0.13 + transformers 4.52 + diffusers 0.35 + tensorflow 2.15 + jax 0.7 + …），全量冻结在仓库根的 [`requirements.txt`](requirements.txt)；逐 pin 推理见 [`docs/libs_compatible.md`](docs/libs_compatible.md)。只跑 sim+RL 时可用更精简的 `unitree` env（严格子集）。 |
| 📚 **27 000+ 行精读中文笔记** | MuJoCo 内核、lowcmd / lowstate schema、关节索引、训练时的隐式不变量、策略可容忍的"上肢覆盖包络"、ROS↔SDK 关系、VLA vs WMA 语义、WSL2 音频通路——`docs/` 和 `*/docs/` 下每一篇都是项目级阅读。 |

---

### 📊 一图速览

> 把"亮点"里的形容词换成可对账的数字——规划磁盘、网卡挂载耗时、或者决定先吃哪一块时翻一下。

| 📦 体量 | 数值 |
|---|---|
| 🏢 **上游参考仓库** | **11**（只读快照） |
| 🌟 **自研交付物** | **4**（`g1_sim_demo` · `g1_real_demo` · `va-demo` · `g1_brain`） |
| 🎮 **G1 MuJoCo demo 脚本** | 仿真 **5** + 真机 **1** ≈ 2 700 行带注释控制环 |
| 🛠️ **LLM 可调用技能（`g1_brain`）** | **17**——7 I/O + 7 运动 + 3 仅真机 |
| 🛡️ **安全规则（`g1_brain`）** | **11**——见 [§ 安全监督器](#%EF%B8%8F-安全监督器--11-条规则) |
| 🎭 **内置上肢手势** | **9**（`wave_right` · `wave_left` · `hands_up` · `t_pose` · `salute` · `clap` · `guard` · `punch_combo` · `hug`） |
| 🧱 **静态姿态** | **2**（`salute` · `hug`）——保持到 `release_arms()` |
| 🪞 **可被镜像的用户手势** | **4**（`wave_right` · `wave_left` · `hands_up` · `t_pose`） |
| 🐍 **`agi` env 锁定包数** | ~**310** 条目（[`requirements.txt`](requirements.txt)） |
| 🐍 **`unitree` env 锁定包数** | ~**150**（精简的 sim + RL 子集） |
| 🤖 **G1 主动自由度** | **29**（12 腿 · 3 腰 · 14 上肢——见 [§ DDS 与关节](#-dds-topic-与关节速查)） |
| 🌐 **DDS domain 约定** | **1** = `lo` 上的仿真 · **0** = `192.168.123.0/24` 上的真机 |
| 🎤 **唤醒词** | "**嗨 Sparky**"（本地 CPU 上的 `faster-whisper tiny`） |
| 📐 **Realtime 三层频率** | 慢脑 0.2–2 Hz · 快反射 5–30 Hz · 仿真控制 50–500 Hz · 桥接 `lowstate` 1 kHz |
| 🧪 **pytest 测试** | `va-demo/tests/` + `g1_brain/tests/`（FSM · supervisor · scene bus · skill server · 端到端纵切片 · …） |
| 📚 **中文深度笔记** | **27 000+** 行，分布在 `docs/` 与 `*/docs/` |
| ⚖️ **许可证** | 自研代码 **Apache 2.0** · 上游快照保留各自许可证 |

---

### 🗂️ 仓库结构

```text
unitree-notes/
│
├── 🌟 自研交付物 ──────────────────────────────────────────────────────────
│
├── 📂 g1_sim_demo/                  ← 🎮 G1 MuJoCo demo 集
│   ├── g1_sim_low_level.py          ·  踝/腕正弦摆动              (≈ 200 行)
│   ├── g1_sim_interactive.py        ·  6 个键盘预设, 500 Hz       (≈ 350 行)
│   ├── g1_sim_keyboard.py           ·  完整键盘 playground         (≈ 600 行)
│   ├── g1_sim_rl_walk.py            ·  ONNX 速度跟踪行走           (≈ 500 行)
│   ├── g1_sim_rl_combo.py           ·  RL 行走 + 上肢手势叠加      (≈ 1000 行)
│   └── docs/                        ·  Demo 专用 Q&A 与教程（QA1–QA5、
│                                       learn-mujoco、demo-explain、report）
│
├── 📂 g1_real_demo/                 ← 🦿 真机部署
│   ├── g1_real_rl_combo.py          ·  真机 RL 行走 + 手势
│   ├── docs/demo-QA7.md             ·  `lying` 模式接线/DDS 验证
│   └── issue/realmachine.md         ·  "机器人不动"诊断日志
│
├── 📂 va-demo/                      ← 🎙️ 语音 + 视觉 Realtime 智能体
│   ├── va_demo/                     ·  audio_io · camera · vision · tts ·
│   │                                   wake_word · utterance_vad · spoken_cache ·
│   │                                   conversation_state · realtime_agent ·
│   │                                   safety · skills · prompts · main
│   ├── configs/va_demo.yaml         ·  全部参数（唤醒词、VAD、机器人、OpenAI）
│   ├── scripts/                     ·  audio_loopback / camera_debug /
│   │                                   tts_debug / wake_word_debug /
│   │                                   skill_debug / vision_loop_debug
│   ├── tests/                       ·  pytest：safety、VAD、唤醒词、
│   │                                   spoken cache、vision-only mode……
│   ├── docs/                        ·  audio-awake / audio-use /
│   │                                   video-design / video-use
│   └── requirements.txt             ·  openai · sounddevice · faster-whisper ·
│                                       webrtcvad-wheels · pyzmq · opencv-python
│
├── 📂 g1_brain/                     ← 🧠 慢脑 + 快反射 + 安全技能 智能体
│   ├── g1_brain/perception/         ·  CameraHub · USB 摄像头 · MuJoCo 头摄（EGL）·
│   │                                   YOLO11 · MediaPipe-Pose · 深度 · 派生量
│   ├── g1_brain/scene_state/        ·  SceneState/RobotState 数据类 + RLock 共享总线
│   ├── g1_brain/safety/             ·  7 状态 FSM · SafetySupervisor（11 条规则）·
│   │                                   watchdog · 独立进程 E-stop
│   ├── g1_brain/skills/             ·  SkillServer · ~16 个 OpenAI 工具 schema ·
│   │                                   keyframe_extras · compound_skills
│   ├── g1_brain/brain/              ·  BrainRealtimeAgent（继承 va-demo）+
│   │                                   场景感知 system prompt
│   ├── g1_brain/mock_imitation/     ·  用户手势 → MIRRORABLE 机器人手势（Phase 5）
│   ├── g1_brain/apps/               ·  agent_main + perception/safety/skill/estop debug
│   ├── configs/g1_brain.yaml        ·  唯一配置（机器人 · 摄像头 · 感知 ·
│   │                                   安全 · openai · 音频 · 唤醒词）
│   ├── docs/                        ·  architecture · how_to_run · extending_skills ·
│   │                                   g1_brain_QA1 · g1-fix-phase{1,2,3,5}
│   ├── tests/                       ·  pytest：11 条规则 · FSM · 场景总线 ·
│   │                                   skill server · 端到端纵切片 · watchdog · …
│   └── pyproject.toml               ·  ultralytics · mediapipe · openai · pyyaml · pynput
│
├── 📡 上游参考仓库（只读快照）─────────────────────────────────────────────
│
├── 📂 unitree_sdk2_python/          ·  DDS 绑定 + 消息 IDL（CycloneDDS）
├── 📂 unitree_mujoco/               ·  官方 MuJoCo 仿真器 + MJCF 资产
├── 📂 unitree_rl_mjlab/             ·  RL 训练（mjlab + rsl_rl + Warp）+ sim2real
├── 📂 unitree_ros/                  ·  ROS 1 + Gazebo 包（历史参考）
├── 📂 unitree_ros2/                 ·  基于 CycloneDDS 的 ROS 2 桥（jazzy/humble）
├── 📂 unitree_sim_isaaclab/         ·  G1 操作任务的 Isaac Lab 仿真器
├── 📂 unitree_lerobot/              ·  LeRobot 适配层（数据转换 + 真机部署）
├── 📂 xr_teleoperate/               ·  XR / AVP 遥操作（Apple Vision Pro 等）
├── 📂 teleimager/                   ·  多相机图像服务（ZeroMQ / WebRTC）
├── 📂 unifolm-vla/                  ·  UnifoLM 视觉-语言-动作框架
├── 📂 unifolm-world-model-action/   ·  UnifoLM 世界模型-动作框架
│
├── 📖 跨切面文档 ─────────────────────────────────────────────────────────
│
├── 📂 docs/                         ·  中文深度笔记（见下方索引）
├── 📂 issue/                        ·  工作区级 issue 日志
├── 📄 instructions.md               ·  仿真 + va-demo 的精选启动顺序
├── 📄 requirements.txt              ·  当前可用环境的 pip-freeze 快照
└── 📄 README.md                     ·  📍 你正在看的文件
```

---

### 🐍 两个 Conda 环境

本仓库实际跑在 **两个并行 env** 上——能用小的就用小的。

| Env | 用途 | Python | 关键 pin（以 `requirements.txt` 为准） | 在哪用 |
|---|---|---|---|---|
| 🟢 **`unitree`** | 纯 sim + RL 栈 | 3.11 | mujoco 3.5.0 · cyclonedds 0.10.2 · torch 2.11 · onnxruntime 1.25 · mjlab 1.2.0 · rsl-rl-lib 5.0.1 | `g1_sim_demo/`、`g1_real_demo/`、`unitree_mujoco`、`unitree_rl_mjlab` 训练 |
| 🔵 **`agi`** | 全功能整合 | 3.11.15 | numpy **1.26.4** · scipy 1.17.1 · torch **2.11.0+cu130** · torchvision 0.26.0+cu130 · triton 3.6 · mujoco 3.5.0 · mujoco-warp 3.5.0 · cyclonedds 0.10.2 · tyro 1.0.13 · mjlab 1.2.0 · rsl-rl-lib 5.0.1 · transformers 4.52.3 · diffusers 0.35.1 · tokenizers 0.21.4 · accelerate 1.5.2 · safetensors 0.7.0 · datasets 3.6 · huggingface-hub 0.34 · tensorflow 2.15 · jax 0.7.1 · onnxruntime 1.22.1 · openai 2.33 · faster-whisper 1.2.1 · webrtcvad-wheels 2.0.14 · sounddevice 0.5.5 · pyzmq 27.1 · mediapipe 0.10.21 · ultralytics 8.4.46 · opencv-python 4.11 · protobuf 4.25.9 | `va-demo/`、`g1_brain/`、`teleimager`、`unifolm-vla`、`unifolm-world-model-action`、`xr_teleoperate`、`unitree_lerobot` |

> 📐 **为什么要两个？** 七份上游 `pyproject.toml` 在 numpy / torch / mujoco / tyro 上互相冲突。`agi` env 是把矛盾解开后的最终兼容集——`unifolm-vla/pyproject.toml` 和 `unifolm-world-model-action/pyproject.toml` 各保留了一份 `pyproject.toml.bak` 作为放宽幽灵 pin 的存档。完整推理见 [`docs/libs_compatible.md`](docs/libs_compatible.md)。
>
> 📦 **`requirements.txt` 里到底有什么？** 仓库根的 [`requirements.txt`](requirements.txt) 是当前可用 `agi` env 的逐字冻结：开头有写明已解析关键 pin 的注释；接着是仓库内可编辑安装（`-e ./<subdir>`，覆盖 `unitree_sdk2_python` · `unitree_rl_mjlab` · `teleimager` · `unifolm-vla` · `g1_brain` · `dex-retargeting`）；两条 `git+https` 第三方 VCS（`dlimp` · `televuer`）；以及 ~310 条字典序排好的 PyPI pin。在新建的 `python=3.11` conda env 里直接 `pip install -r requirements.txt` 就能复现整个栈。
>
> 🔧 `unitree_ros2` **不是** Python 包——按 [`docs/ros2_sdk.md`](docs/ros2_sdk.md) 装成系统级 ROS 2 **Jazzy** 工作区。
>
> 🧱 **磁盘开销** 在 CUDA-13 wheel（`nvidia-cublas`、`nvidia-cudnn-cu13`、`nvidia-nccl-cu13`、`nvidia-cusparselt-cu13` 等）+ `tensorflow` / `torch` / `jax` 三件套全部落地后约为 **14 GB**。WSL2 下注意 `vhdx` 容量。

---

### 📦 环境依赖

| 层级 | 要求 | 备注 |
|---|---|---|
| 🖥️ **操作系统** | Linux（Ubuntu 22.04 / 24.04）或 WSL2 + WSLg | macOS / 原生 Windows **不支持**——CycloneDDS 没有这两个平台的轮子。 |
| 🐍 **Python** | 3.11 | 由 `mjlab` 和 `cyclonedds` 的轮子限制。 |
| 🧪 **Conda** | 推荐 [Miniforge](https://github.com/conda-forge/miniforge) | `unitree` 和 `agi` 两个 env 都默认 Miniforge。 |
| 🎮 **GPU**（可选） | NVIDIA + CUDA 13 + 驱动 ≥ 560 | **训练**、**VLA / WMA 推理**需要；纯仿真和 RL ONNX 策略 CPU 即可。 |
| 🤖 **真机**（可选） | 同局域网下的 Unitree G1 EDU | 把命令里的 `lo` 替换成实际网卡名（例如 `enp3s0`），机器人通常在 `192.168.123.0/24`。 |
| 🎤 **麦克风 / 🔈 扬声器**（va-demo） | 任何 USB / WSLg 透出的音频设备 | WSL2 下需要 ALSA→Pulse 软链——见 [`docs/wsl2_audio.md`](docs/wsl2_audio.md)。 |
| 📷 **摄像头**（va-demo） | UVC USB 摄像头 | WSL2 下需要 `usbipd` 挂载——见 [`docs/camera_ui_demo.md`](docs/camera_ui_demo.md)。 |
| 🔑 **OpenAI API key**（va-demo） | 设好 `OPENAI_API_KEY` | Realtime + Vision + TTS 都走 OpenAI API。 |

---

### 🚀 快速开始

#### 1️⃣ 克隆仓库

```bash
git clone https://github.com/SparkyWen/unitree-notes.git
cd unitree-notes
```

#### 2️⃣ 按需创建 env

<details>
<summary><b>🟢 选项 A — 精简 <code>unitree</code> env（仅 sim + RL）</b></summary>

```bash
conda create -n unitree python=3.11 -y
conda activate unitree
pip install -r requirements.txt

# editable 模式装 SDK，demo 才能 import unitree_sdk2py
pip install -e unitree_sdk2_python
```
</details>

<details>
<summary><b>🔵 选项 B — 整合 <code>agi</code> env（sim + RL + va-demo + g1_brain + VLA + 遥操）</b></summary>

最快的路径就是仓库根的 [`requirements.txt`](requirements.txt)——它把整个工作中的栈（含仓库内可编辑安装）都冻结好了：

```bash
conda create -n agi python=3.11 -y
conda activate agi

# 数值底座——必须最先装来锁住 numpy 1.26.4
pip install "numpy==1.26.4" "scipy<2"

# 其余一切——会拉 torch 2.11+cu130、mujoco 3.5.0、transformers 4.52、
# diffusers 0.35、tensorflow 2.15、jax 0.7.1、openai 2.33、ultralytics 8.4.46、
# mediapipe 0.10.21、faster-whisper 1.2.1，以及所有 -e ./subdir 包。
pip install -r requirements.txt
```

如果你想按上游一个一个装（更接近这个 env 当年的 bootstrap 顺序）：

```bash
conda create -n agi python=3.11 -y
conda activate agi
pip install "numpy==1.26.4" "scipy<2"

# Unitree sim + RL 栈
pip install -e unitree_sdk2_python
pip install -e unitree_mujoco/simulate_python   # 如适用
pip install -e unitree_rl_mjlab

# va-demo + g1_brain + teleimager + xr_teleoperate
pip install -r va-demo/requirements.txt
pip install -e g1_brain
pip install -e "teleimager[server]"
pip install -e xr_teleoperate                   # 按其 README 装额外依赖

# UnifoLM 双栈（先按 pyproject.toml.bak 改幽灵 pin）
pip install -e unifolm-vla
pip install -e unifolm-world-model-action

# unitree_lerobot
pip install -e unitree_lerobot
```

> ⚠️ 走 **逐上游** 路径之前**必须**先看 [`docs/libs_compatible.md`](docs/libs_compatible.md)——有几处 `pyproject.toml` 需要手动改才能解开 ghost pin。`requirements.txt` 路线已经把解出来的 pin 写死了，可以省掉这一步。
</details>

#### 3️⃣ 把模拟器切到 G1

编辑 `unitree_mujoco/simulate_python/config.py`：

```python
ROBOT               = "g1"      # 加载 g1_29dof.xml (29 个电机)
ENABLE_ELASTIC_BAND = True      # 双足必须启用——把 G1 吊在原地
USE_JOYSTICK        = 0         # 没接有线手柄时一定要置 0
DOMAIN_ID           = 1         # 重要：所有 demo 都假定 domain 1 + lo
INTERFACE           = "lo"
```

#### 4️⃣ 冒烟测试（双终端）

```bash
# ── 终端 1：启动 MuJoCo 桥接器 ─────────────────────────────────
conda activate unitree
cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
python unitree_mujoco.py
#   viewer 弹出后，按 '9' 启用悬挂带（让 G1 吊在原地）。
#   '7' 让带子下落，'8' 把带子向上拉。
```

```bash
# ── 终端 2：跑入门 demo ────────────────────────────────────────
conda activate unitree
cd ~/unitree/unitree-notes/g1_sim_demo
python g1_sim_low_level.py
#   会先看到双脚踝摆动，再加上手腕摆动。
#   终端每秒打印一次 IMU rpy 当作心跳。
```

> ✅ **只要心跳在打印、viewer 里能看到动作，就说明环境没问题。** 接下来去 demo 列表挨个玩。
>
> 💡 想看包含 RL combo + va-demo + WSL2 USB 摄像头挂载的精选启动顺序，请看 [`instructions.md`](instructions.md)。

---

### 🎹 按键速查表

> 把所有脚本里的键盘绑定汇总成一张卡，操作、演示、带新人时翻一下就够了。

#### MuJoCo viewer（`unitree_mujoco/simulate_python`）

| 按键 | 作用 |
|---|---|
| <kbd>9</kbd> | 切换悬挂带（**任何控制脚本启动前都要先开** —— 让 G1 吊在原地） |
| <kbd>8</kbd> | 把悬挂带向上拉（抬高机器人） |
| <kbd>7</kbd> | 把悬挂带放下（让脚刚好接触地面） |
| 鼠标左键拖动 | 旋转视角 |
| 鼠标右键拖动 | 平移视角 |
| 滚轮 | 缩放 |
| <kbd>Esc</kbd> | 关闭 viewer（顺带杀掉桥接器） |

#### `g1_sim_demo/g1_sim_interactive.py` 与 `g1_sim_keyboard.py`

| 按键 | 作用 |
|---|---|
| <kbd>z</kbd> | 回零位 |
| <kbd>w</kbd> | 挥手 |
| <kbd>b</kbd> | 鞠躬 |
| <kbd>k</kbd> | 抬腿 |
| <kbd>a</kbd> | 拍手 |
| <kbd>r</kbd> | （`g1_sim_keyboard`）恢复到首帧测得的姿态 |
| <kbd>x</kbd> | （`g1_sim_keyboard`）紧急软化 —— 调低 Kp |
| <kbd>q</kbd> | 退出（永远先回零再下电） |

#### `g1_sim_demo/g1_sim_rl_walk.py`（以及 `g1_sim_rl_combo.py` / `g1_real_rl_combo.py` 的运动部分）

| 按键 | 作用 |
|---|---|
| <kbd>w</kbd> / <kbd>s</kbd> | 前进 / 后退（`vx`） |
| <kbd>a</kbd> / <kbd>d</kbd> | 左 / 右平移（`vy`） |
| <kbd>q</kbd> / <kbd>e</kbd> | 左 / 右旋（`wz`） |
| <kbd>r</kbd> | 把目标速度归零 |
| <kbd>f</kbd> | 切换 freeze（保持当前姿态） |

#### `g1_sim_demo/g1_sim_rl_combo.py` 与 `g1_real_demo/g1_real_rl_combo.py` —— 上肢手势

> 与运动键并行使用。手势只覆盖上肢（关节 15–28），且每帧都会被裁剪到策略训练时的安全包络内，腿部仍由 RL 接管。

| 按键 | 手势 |
|---|---|
| <kbd>1</kbd> | `wave_right`（右手挥手） |
| <kbd>2</kbd> | `wave_left`（左手挥手） |
| <kbd>3</kbd> | `hands_up`（举双手） |
| <kbd>4</kbd> | `t_pose`（T 形展开） |
| <kbd>5</kbd> | `salute`（敬礼） |
| <kbd>6</kbd> | `clap`（拍手） |
| <kbd>7</kbd> | `guard`（防御姿态） |
| <kbd>8</kbd> | `punch_combo`（出拳组合） |
| <kbd>0</kbd> / <kbd>Space</kbd> | 释放上肢回 RL 策略 |
| <kbd>Esc</kbd> | 速度归零 + 释放上肢 |

> 🛡️ `g1_real_rl_combo.py lying` 模式下，<kbd>1</kbd>..<kbd>7</kbd> 改为触发小幅单关节抖动，用来在不站起来的情况下确认电机响应。

#### `va-demo/` 与 `g1_brain/`

| 按键 / 短语 | 作用 |
|---|---|
| 语音："**嗨 Sparky**" | 打开唤醒门 —— 唤醒后麦克风音频才会上传 OpenAI Realtime |
| 语音："stop"、"release arms" 等 | 由 LLM 翻成 `stop()` / `release_arms()` 工具调用 |
| <kbd>Backspace</kbd> | （active 模式）硬取消当前进行中的运动调用 |
| <kbd>Ctrl-C</kbd> | 优雅退出 —— 关音频、放上肢、写 transcript |
| <kbd>Esc</kbd> *（独立进程）* | `g1_brain.safety.estop_listener` —— 主进程死锁也能切电的独立 E-stop |
| <kbd>y</kbd> / <kbd>N</kbd> | （`--mode confirm`）在终端逐次审批运动工具调用 |

---

### 🌟 自研交付物

按依赖深度从浅到深列出。

#### 🎬 `g1_sim_demo/` — MuJoCo Demo 一览

> 所有 demo 都在 `g1_sim_demo/` 下。运行前请先按"终端 1"启动模拟器。把脚本的**第一个**命令行参数换成实际网卡名（如 `enp3s0`），脚本会自动切到 DDS domain 0 控制真机。

<table>
<thead>
<tr><th>#</th><th>脚本</th><th>功能</th><th>适合谁</th></tr>
</thead>
<tbody>

<tr>
<td>1️⃣</td>
<td><code>g1_sim_low_level.py</code></td>
<td>三段式预设动作：全身回零位 → PR 模式踝关节正弦 → AB 模式踝关节 + 手腕正弦。</td>
<td>📡 验证 SDK ↔ 桥接器 通路。</td>
</tr>

<tr>
<td>2️⃣</td>
<td><code>g1_sim_interactive.py</code></td>
<td>500 Hz 控制线程 + 余弦插值关键帧。按键：<kbd>z</kbd> 回零 · <kbd>w</kbd> 挥手 · <kbd>b</kbd> 鞠躬 · <kbd>k</kbd> 抬腿 · <kbd>a</kbd> 拍手 · <kbd>q</kbd> 退出。</td>
<td>🎮 第一次玩键盘遥控。</td>
</tr>

<tr>
<td>3️⃣</td>
<td><code>g1_sim_keyboard.py</code></td>
<td>更大的预设库；"真"reset（首帧测得姿态会被记下来供 'r' 恢复）；<kbd>x</kbd> 急停软化；动作时长可缩放；退出前永远先回零位再下电。</td>
<td>🎨 不写代码就能摆姿势/做动画。</td>
</tr>

<tr>
<td>4️⃣</td>
<td><code>g1_sim_rl_walk.py</code></td>
<td>从 <code>unitree_rl_mjlab</code> 加载 <code>policy.onnx</code>，从 <code>rt/lowstate</code> 拼出 98 维 obs，50 Hz 跑策略，还原成 29 维 <code>q_target</code> 后发出 <code>rt/lowcmd</code>。按键：<kbd>w/s</kbd>/<kbd>a/d</kbd>/<kbd>q/e</kbd>/<kbd>r</kbd>/<kbd>f</kbd>。</td>
<td>🚶 仿真里跑闭环 RL 行走。</td>
</tr>

<tr>
<td>5️⃣</td>
<td><code>g1_sim_rl_combo.py</code></td>
<td>同样的 RL 行走，但是上肢（关节 15–28）可以被键盘触发的手势临时接管——挥手 / 举手 / T-pose / 敬礼 / 拍手 / 防御 / 出拳——并且每帧都会被裁剪到"策略训练时见过的范围"，确保腿不会因 OOD 输入崩盘。**全程只有一个 publisher 写 lowcmd**，没有 DDS 竞争。</td>
<td>🤹 一边走路一边做手势。</td>
</tr>

</tbody>
</table>

#### 🦿 `g1_real_demo/` — 真机部署

> `g1_sim_demo/g1_sim_rl_combo.py` 的真机姊妹版。同一份 RL 策略、同一组手势，但是**针对真机做了加固**。

| 文件 | 用途 |
|---|---|
| `g1_real_rl_combo.py` | 单进程控制器：腿/腰跑 ONNX 速度策略 + 上肢键盘手势，外加 `MotionSwitcher` 释放、有界 `lowstate` 等待、`lying` 检线模式。 |
| `docs/demo-QA7.md` | `lying` 模式如何在不站起来的情况下验证接线和 DDS 通路。 |
| `issue/realmachine.md` | "按 1/2/3 机器人没反应" 的诊断日志——根因是真机高层控制器仍然占着 `rt/lowcmd`。 |

**与仿真版本的差异：**

1. **初始化时调用 `MotionSwitcherClient.ReleaseMode()`**——G1 自带的 `ai`/`normal`/`advanced` 控制器会一直持有 `rt/lowcmd`，不释放就会被它默默盖掉我们的指令。
2. **有界 `lowstate` 等待**——超时后打印一份可执行检查表（接口名错、DDS domain 错、机器人在高层模式、链路 down、组播被屏蔽），而不是一直 busy-wait。
3. **`lying` CLI 模式**——跳过启动 ramp 和策略，按测得姿态低 Kp 锁住，1..7 键触发小幅单关节抖动。在机器人站不起来时（线短、断电等）只为确认电机能响应。
4. **覆盖 CycloneDDS tracing**——压掉真机上 DDS 的噪声日志。

```bash
conda activate unitree

# 真机——在 G1 的 192.168.123.0/24 子网里找网卡
ip -br addr | grep 192.168.123
python g1_real_rl_combo.py <iface>           # 例如 eno3
# MotionSwitcher 释放后即可走路 + 出手势

# 真机但站不起来——只检查接线 / DDS
python g1_real_rl_combo.py <iface> lying     # 例如 eno3 lying
```

> ⚠️ 真机运行时**急停按钮永远要在手边**。`lying` 模式存在的意义就是让你在机器人立起来之前先把 DDS 通路验明正身。

#### 🎙️ `va-demo/` — 语音 + 视觉智能体

> 一个由唤醒词（"嗨 Sparky"）门控的全双工 Realtime 语音智能体——能**通过视觉模型**描述场景，也能**工具调用** `walk` / `gesture` / `stop` 直接驱动跑着的 RL 策略。基于 `g1_sim_rl_combo`、`teleimager` 以及 OpenAI Realtime + Vision + TTS API。

**模型可调用的工具**

| 工具 | 用途 |
|---|---|
| `say(text)` | 直接 TTS 回复 |
| `stop()` | 速度归零 + 释放上肢 |
| `release_arms()` | 把上肢交回给 locomotion 策略 |
| `walk(vx, vy, wz, duration_s)` | 短时低速移动 |
| `gesture(name)` | 任选一个：`wave_right` / `wave_left` / `hands_up` / `t_pose` / `salute` / `clap` / `guard` / `punch_combo` |
| `describe_scene(question?, detail?)` | 抓一帧 → 视觉模型 → 返回文字描述 |

**唤醒词行为**

智能体在说出"**嗨 Sparky**"之前**不会**把麦克风音频上传到 OpenAI Realtime。这一步解决了原本"一直挂线"模式下的两个问题：

1. Realtime API 的服务端 VAD 太敏感，咳一声都会触发 turn。
2. Sparky 自己 TTS 播放出来的声音会泄漏进麦克风，让它不停打断自己。

唤醒词触发后正常说话；停顿 ~1.5 s 后自动提交一段。Sparky 回复后会打开 **8 秒倾听窗口**，期间你可以直接说后续问题、**不用再喊一遍唤醒词**。

唤醒词检测器是**本地 CPU 上跑的 `faster-whisper tiny`**；正式 turn 的语音识别用的是云端 **OpenAI gpt-4o-transcribe**——完整设计见 [`docs/audio-awake.md`](va-demo/docs/audio-awake.md)。

**运行模式**

| 标志 | 效果 |
|---|---|
| `--mode confirm`（默认） | 每次动作类工具调用都先在终端打 y/N 提示。 |
| `--mode active` | 完全自主——模型说什么算什么；带子和 `Backspace` 备好。 |
| `--mode observe` | 禁用所有动作；视觉 + 语音照常工作。 |
| `--vision-only` | 把动作工具完全裁掉（不初始化 DDS、不依赖 mujoco）——验关键帧→视觉→语音回路时最方便。 |
| `--no-wakeword` | 跳过唤醒门；麦克风持续上传 Realtime（仅用于 A/B 调试）。 |
| `--no-realtime` | 不连 Realtime，但保留音频/摄像头/技能进程存活。 |

**启动顺序（3 个终端，全部在 `agi` env）**

```bash
# ── 终端 1：MuJoCo 仿真器 ──────────────────────────────────────
conda activate agi
cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
python unitree_mujoco.py
# viewer 里按 8 几下让带子放下，可选按 9 关掉

# ── 终端 2：TeleImager 图像服务 ────────────────────────────────
conda activate agi
cd ~/unitree/unitree-notes/teleimager
python -m teleimager.image_server

# ── 终端 3：va-demo 智能体 ─────────────────────────────────────
conda activate agi
cd ~/unitree/unitree-notes/va-demo
set -a; source .env; set +a              # 加载 OPENAI_API_KEY
python -m va_demo.main                    # 默认 --mode confirm
```

> 📷 WSL2 摄像头挂载：从 PowerShell 执行 `usbipd attach --wsl --busid <id>`——见 [`docs/camera_ui_demo.md`](docs/camera_ui_demo.md)。
>
> 🔉 WSL2 音频修复：把 `$CONDA_PREFIX/lib/alsa-lib` 软链到 `/usr/lib/x86_64-linux-gnu/alsa-lib`，让 ALSA 能找到 pulse 插件——见 [`docs/wsl2_audio.md`](docs/wsl2_audio.md)。

#### 🧠 `g1_brain/` — 慢脑 + 快反射 + 安全技能 智能体

> 一个新建的顶层包，**只 import 不修改** [`va-demo/`](va-demo/) 与 [`g1_sim_demo/`](g1_sim_demo/)，在它们之上叠加 **感知 · 安全 · 技能** 三层。OpenAI Realtime 一个回路无法同时覆盖三个时间尺度，本包把它们彻底分开，并把所有下行命令统一过一道安全验证后路由到唯一的技能服务器。

📂 **必读：** [`g1_brain/README.md`](g1_brain/README.md) · [`g1_brain/docs/architecture.md`](g1_brain/docs/architecture.md) · [`g1_brain/docs/how_to_run.md`](g1_brain/docs/how_to_run.md) · [`docs/g1_plan.md`](docs/g1_plan.md)（完整 1500+ 行设计稿）

**三层心智模型**

| 层级 | 频率 | 谁来做 | 做什么 |
|---|---|---|---|
| 🧠 **慢脑（Slow Brain）** | 0.2–2 Hz | OpenAI Realtime + GPT-5.5 Vision | 规划、对话、决定调用哪个技能 |
| 🛡️ **安全技能（Safe Skill）** | 每次调用 | `SafetySupervisor` + `SkillServer` | 验证（11 条规则）、裁剪、路由、中止 |
| ⚡ **快反射（Fast Reflex）** | 5–30 Hz | 摄像头 + YOLO11 + MediaPipe-Pose + 深度 | 构建供安全层读取的 `SceneState` |

**技能目录（17 个 LLM 可调用工具）** —— 完整签名见下方 [§ 技能目录](#-技能目录g1_brain)。

| 类别 | 工具 |
|---|---|
| 🗣️ I/O —— 不涉及运动 | `say` · `describe_scene` · `query_scene_state` · `recall_history` · `ask_human` · `stop` · `release_arms` |
| 🦿 运动（受安全 + FSM 关卡） | `walk` · `turn` · `gesture` · `static_pose` · `look_at` · `approach` · `mock_imitate` |
| 🤖 仅真机（仿真直接拒绝） | `loco_high` · `arm_action_high` · `audio_tts_robot` |

**三种运行模式** — `--mode observe`（禁动）· `--mode confirm`（默认 — y/N 关卡）· `--mode active`（在安全包络内自主执行）。`--vision-only` 跳过 DDS 用作笔记本独立开发。

**启动顺序（4 个终端，全部 `agi` env）**

```bash
# ── 终端 1：MuJoCo 仿真器 ──────────────────────────────────────
conda activate unitree
export MUJOCO_GL=glfw
cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
python unitree_mujoco.py

# ── 终端 2：TeleImager 图像服务 ────────────────────────────────
conda activate unitree
cd ~/unitree/unitree-notes/teleimager
python -m teleimager.image_server

# ── 终端 3：独立 E-stop 监听（按 ESC 即灭车） ───────────────────
conda activate agi
python -m g1_brain.safety.estop_listener

# ── 终端 4：智能体本体 ─────────────────────────────────────────
conda activate agi
export OPENAI_API_KEY=sk-...
python -m g1_brain.apps.agent_main --mode confirm
```

**内置调试入口** — `python -m g1_brain.apps.{perception_debug, safety_debug, skill_debug, estop_test}`，每个都把一层独立验出来。

> 🛡️ **关键不变量：** 每一次工具调用都要过 `SafetySupervisor.validate()`（白名单 · FSM 关卡 · run_mode · 4 个 watchdog · 姿态检查 · 参数裁剪 · 场景检查 · E-stop）。LLM 永远碰不到电机；独立的 E-stop 进程保证就算主进程死锁也能切电。

---

### 🧰 技能目录（`g1_brain`）

> 暴露给慢脑的 17 个 OpenAI 工具 schema。权威源：[`g1_brain/g1_brain/skills/tool_schemas.py`](g1_brain/g1_brain/skills/tool_schemas.py)。每条 schema 在到达 `SkillServer` 之前都要先过 [§ 安全监督器](#%EF%B8%8F-安全监督器--11-条规则) 的 11 条规则。

#### 🗣️ I/O —— 不涉及运动（除 `BOOT` 外永远允许）

| 工具 | 签名 | 作用 |
|---|---|---|
| `say` | `say(text: str ≤ 200 字符)` | 走 OpenAI TTS 直接合成的短回复（适合标准化、固定话术）。 |
| `describe_scene` | `describe_scene(question?: str, detail?: "low"\|"high")` | 抓当前一帧 → 视觉模型 → 文字描述。 |
| `query_scene_state` | `query_scene_state(field?: str)` | 直接读 `SceneState`（人、手势、深度、机器人姿态）—— 不重跑视觉。 |
| `recall_history` | `recall_history(turns?: int)` | 从落盘 transcript JSONL 取最近 *N* 轮对话回放。 |
| `ask_human` | `ask_human(question: str)` | 在场景/安全有歧义时，停下等人类明确回答再继续。 |
| `stop` | `stop()` | 速度归零、上肢交回策略；`BOOT` 状态下也允许。 |
| `release_arms` | `release_arms()` | 把上肢交回 locomotion 策略（手势/静态姿后调用）。 |

#### 🦿 运动（受 `STANDING/ENGAGED/ACTING` FSM + run_mode 双重关卡）

| 工具 | 签名 | 备注 |
|---|---|---|
| `walk` | `walk(vx, vy, wz, duration_s)` | 短时低速移动；按 `safety.params` 裁剪，`scene_check_walk` 不通过即拒绝。 |
| `turn` | `turn(angle_deg, duration_s?)` | 原地转向 —— `walk(0, 0, wz, …)` 的便捷封装。 |
| `gesture` | `gesture(name)` | **9** 个 RL 安全手势之一：`wave_right` · `wave_left` · `hands_up` · `t_pose` · `salute` · `clap` · `guard` · `punch_combo` · `hug`。 |
| `static_pose` | `static_pose(name)` | **2** 个保持式姿态：`salute` · `hug`，到 `release_arms()` 才解除。 |
| `look_at` | `look_at(target)` | 取值 `person` · `ahead` · `left` · `right` · `ground`。慢脑控制头摄朝向的主要动词。 |
| `approach` | `approach(target?, distance_m?)` | 在场景检查通过的前提下走到目标距离，或路径被挡时停下。 |
| `mock_imitate` | `mock_imitate()` | Phase 5 模仿：取用户最近识别到的姿态（**4** 个 mirrorable 之一：`wave_right` · `wave_left` · `hands_up` · `t_pose`）镜像回去。 |

#### 🤖 仅真机（仿真自动拒绝）

| 工具 | 状态 |
|---|---|
| `loco_high` | 真机 G1 的高层运动指令（仿真直接拒）。 |
| `arm_action_high` | 真机 G1 的预置上肢动作库（仿真直接拒）。 |
| `audio_tts_robot` | 通过机器人本体扬声器说话（仿真直接拒）。 |

---

### 🛡️ 安全监督器 —— 11 条规则

> 权威源：[`g1_brain/g1_brain/safety/supervisor.py`](g1_brain/g1_brain/safety/supervisor.py)。每次工具调用都按下表**顺序**走完 11 条；拒绝时返回 `(ok=False, reason, sanitized_args)`，**不**主动产生副作用——唯一例外是规则 7 触发时把 FSM 锁到 `EMERGENCY_STOP`，因为那意味着真摔了。

| # | 规则 | 触发条件 | 效果 |
|:-:|---|---|---|
| 1 | 🔐 **白名单** | 工具名 ∉ `ALLOWED_TOOLS` | 拒绝 —— 杜绝 LLM 自创工具名。 |
| 2 | 🚦 **FSM 关卡** | 当前 `RobotFsmState` 不允许该工具（例如 `BOOT` / `FAULT` 中调运动） | 拒绝 —— 详见 `_FSM_MOTION_ALLOWED` / `_FSM_NO_MOTION_ALLOWED` 每态白名单。 |
| 3 | 🎚 **`run_mode`** | `observe` 模式调运动 **·** `confirm` 模式 y/N 关卡未通过 | 拒绝；`active` 模式跳过 y/N，但仍要过规则 4-11。 |
| 4 | ⏱ **`lowstate` watchdog** | 超过 *N* ms（默认 250 ms）没收到 `rt/lowstate` | 锁定式 trip —— 仅 `stop` / `release_arms` / 不涉运动工具能过。 |
| 5 | 🎥 **头摄 watchdog** | 超过 *N* ms（默认 1000 ms）没拿到新头摄帧 | 锁定式 trip —— 视觉相关工具（`describe_scene`、`look_at`…）封禁。 |
| 6 | 🦿 **RL 策略活跃 watchdog** | locomotion 策略超过 *N* ms 没 tick（例如启动期回退） | 锁定式 trip —— 运动工具封禁，直到策略恢复。 |
| 7 | 📐 **姿态检查** | 由 IMU `quat_imu` 推出的 `gravity_proj_z` 跌破直立阈值 | 拒绝 + FSM 转入 `EMERGENCY_STOP`（真摔进行中）。 |
| 8 | ✂️ **参数裁剪** | `walk(vx, vy, wz, duration)` 超出配置包络 | 在转发前就地裁剪 sanitized_args。 |
| 9 | 🚧 **场景检查（`walk`）** | 净空 / 最近障碍 / 最近行人 任一不达阈 | 拒绝 —— 影响 `walk` / `approach`。 |
| 10 | 👤 **场景检查（`gesture`）** | 有人比 `safety.gesture_min_person_m` 更近 | 拒绝 —— 防止 `t_pose` / `punch_combo` 等动作伤到旁人。 |
| 11 | 🛑 **E-stop 标志** | 独立 `estop_listener` 进程已置位 IPC 标志 | 所有工具一律拒绝；唯有杀掉 listener 进程才能解除。 |

> 🎯 **独立 E-stop 进程。** `python -m g1_brain.safety.estop_listener` 单开一个终端，监听 <kbd>Esc</kbd>，把一个 watchdog 标志写到 supervisor 每帧轮询的 IPC 通道。它**不是**主进程里的某个线程 —— 设计上"急停按钮不能装在它要切掉的那个进程里"。

---

### 📡 上游参考仓库

> 下面这十一个目录都是**只读快照**，保持干净以便和上游做 diff。要打补丁请用 overlay / wrapper，不要直接改它们。

| 目录 | 层级 | 提供什么 | 深度文档 |
|---|---|---|:---:|
| 📂 [`unitree_sdk2_python/`](unitree_sdk2_python/) | DDS 绑定 | CycloneDDS Python 绑定、消息 IDL（`unitree_go`、`unitree_hg`）、CRC、ChannelFactory。每个 demo 都要 import 的底层管道。 | [`docs/unitree_sdk2_python.md`](docs/unitree_sdk2_python.md) |
| 📂 [`unitree_mujoco/`](unitree_mujoco/) | 仿真 | Go2/B2/H1/G1 的 MJCF 资产 + Python 桥接器，发布 `rt/lowstate`、消费 `rt/lowcmd`，让控制脚本无法区分 sim 和真机。 | [`docs/unitree_mujoco.md`](docs/unitree_mujoco.md) |
| 📂 [`unitree_rl_mjlab/`](unitree_rl_mjlab/) | 强化学习 | mjlab + rsl_rl + MuJoCo Warp 的训练流水线；sim2real 部署脚本；本仓库 demo 跑的 `policy.onnx` 出自这里。 | [`docs/unitree_rl_mjlab.md`](docs/unitree_rl_mjlab.md) |
| 📂 [`unitree_ros/`](unitree_ros/) | ROS 1 | Gazebo 仿真包 + Go1/Go2/B1/B2/H1/G1/Z1/A1 的 URDF/SRDF（历史参考）。 | [`docs/unitree_ros.md`](docs/unitree_ros.md) |
| 📂 [`unitree_ros2/`](unitree_ros2/) | ROS 2 | 把 CycloneDDS topic 桥到 ROS 2（foxy / humble / jazzy）的 C++ ament 工作区。 | [`docs/unitree_ros2.md`](docs/unitree_ros2.md) · [`docs/ros2_sdk.md`](docs/ros2_sdk.md) |
| 📂 [`unitree_sim_isaaclab/`](unitree_sim_isaaclab/) | 仿真 | NVIDIA Isaac Lab 操作任务（`reset_pose_test`、`send_commands_*`），G1 + 灵巧手；DDS topic 与真机一致。 | — |
| 📂 [`unitree_lerobot/`](unitree_lerobot/) | 数据/策略 | HuggingFace **LeRobot** v2/v3 的适配——把 AVP/XR 遥操采的 JSON 转 LeRobot 格式，并把 ACT / Diffusion / π₀ / π₀.₅ / GR00T 等 policy 部署到真机 G1+Dex1/Dex3/Inspire/Brainco。 | [`docs/unitree_lerobot.md`](docs/unitree_lerobot.md) |
| 📂 [`xr_teleoperate/`](xr_teleoperate/) | 遥操 | XR / Apple Vision Pro 遥操作——身体重定向、手势映射到灵巧手、为 LeRobot 录数据。 | [`docs/xr_teleoperate.md`](docs/xr_teleoperate.md) |
| 📂 [`teleimager/`](teleimager/) | 视觉链路 | 多相机图像服务（UVC / OpenCV / RealSense），通过 **ZeroMQ PUB-SUB** + WebRTC 发布。是 `xr_teleoperate` 和 `va-demo` 的画面来源。 | [`docs/teleimager.md`](docs/teleimager.md) |
| 📂 [`unifolm-vla/`](unifolm-vla/) | VLA | UnifoLM-VLA-0：在机器人操作数据上做继续预训练的视觉-语言-动作模型，单策略覆盖 12 大类操作任务。 | [`docs/unifolm-vla.md`](docs/unifolm-vla.md) |
| 📂 [`unifolm-world-model-action/`](unifolm-world-model-action/) | WMA | UnifoLM-WMA-0：世界模型 + 动作头；世界模型既能当合成数据生成器，又能预测未来交互来增强决策。 | [`docs/unifolm-world-model-action.md`](docs/unifolm-world-model-action.md) |

> 🧠 第一次接触？[`docs/vla_wma.md`](docs/vla_wma.md) 是一篇 1 页的入门：VLA / WMA / SLAM 各是什么、彼此什么关系。

---

### 🧱 架构总览

#### 仿真 demo 控制回路（`g1_sim_demo/*.py`、`g1_real_demo/g1_real_rl_combo.py`）

```
┌──────────────────────────────────────────────────────────────────────┐
│                       你写的控制脚本                                 │
│                      (g1_sim_demo/*.py)                              │
│                                                                      │
│   ┌────────────────────┐         ┌───────────────────────────────┐  │
│   │ 键盘 / 预设关键帧  │  入队   │  控制循环 (50–500 Hz)         │  │
│   │ 调度器             │ ──────► │  - 余弦插值                   │  │
│   └────────────────────┘         │  - 或 ONNX 策略推理           │  │
│                                  │  - PD 目标 + Kp/Kd            │  │
│                                  └────────────┬──────────────────┘  │
│                                               │                      │
└───────────────────────────────────────────────┼──────────────────────┘
                                                │ rt/lowcmd
                                                ▼
                       ┌─────────────────────────────────────┐
                       │  unitree_sdk2py（DDS publisher）    │
                       │   CycloneDDS · domain 1 · lo        │
                       └─────────────────┬───────────────────┘
                                         │
                                         ▼
                       ┌─────────────────────────────────────┐
                       │   unitree_mujoco/simulate_python    │
                       │   MJCF: g1_29dof.xml (29 个电机)    │
                       │   bridge ─►  rt/lowstate (1 kHz)    │
                       └─────────────────────────────────────┘
                                         │
                                         ▼
                       ┌─────────────────────────────────────┐
                       │      MuJoCo viewer  (GLFW)          │
                       │   '9' 上挂 · '7' 落下 · '8' 抬起    │
                       └─────────────────────────────────────┘
```

🔁 **同一份脚本为什么能上真机：** 把命令行的 `lo` 换成实际网卡名，脚本自动切到 DDS domain 0；后面 `unitree_sdk2py → rt/lowcmd → 关节控制器` 这一段是完全一样的。这就是"用 MuJoCo 当一只假机器人"的全部意义。

#### `va-demo` 智能体回路

```
┌──────────────────────────────────────────────────────────────────────────┐
│                                  va-demo                                │
│                                                                          │
│   🎤 麦克风                                                              │
│   sounddevice ─► MicStream.subscribe() ──┬─► WakeWordDetector            │
│                                          │       (faster-whisper tiny)   │
│                                          │                               │
│                                          └─► UtteranceVAD (webrtcvad)    │
│                                                  │                       │
│                                                  ▼                       │
│                                       gpt-4o-transcribe                  │
│                                                  │                       │
│                                                  ▼                       │
│   📝 prompt + tools  ─►  OpenAI Realtime API（websocket，全双工）        │
│                                  │                                       │
│              tool calls ◄────────┤                                       │
│                                  │                                       │
│       ┌──────────────────────────┼───────────────────────────────┐       │
│       ▼                          ▼                               ▼       │
│  walk / gesture /         describe_scene                       say        │
│  stop / release_arms     (一帧画面 ─► gpt-5.x vision)         (TTS)       │
│       │                          │                               │       │
│       ▼                          ▼                               ▼       │
│  Safety supervisor        teleimager（ZMQ 帧）             扬声器输出    │
│       │                                                                  │
│       ▼                                                                  │
│  ComboController  ─►  rt/lowcmd（与 g1_sim_rl_combo.py 同一条 DDS 路径）│
└──────────────────────────────────────────────────────────────────────────┘
```

> 📐 完整设计：[`docs/va-demo-design.md`](docs/va-demo-design.md) · 运行指南：[`docs/va-demo-use.md`](docs/va-demo-use.md)。

---

### 🔌 DDS Topic 与关节速查

> 最常用的 DDS topic、消息族，以及 G1 29-DoF 关节索引图。完整说明见 [`docs/unitree_sdk2_python.md`](docs/unitree_sdk2_python.md)。

#### 🌐 DDS domain 约定

| 在哪 | Domain | 网卡 | 由谁设置 |
|---|:-:|---|---|
| 🟢 **MuJoCo 仿真** | **1** | `lo` | `unitree_mujoco/simulate_python/config.py::DOMAIN_ID, INTERFACE` |
| 🦿 **真机 G1（EDU）** | **0** | `192.168.123.0/24` 子网中的实际网卡（如 `enp3s0`、`eno3`） | 每个 `g1_*_demo` 脚本的第一个命令行参数 |

> 🔁 **同一份脚本，两个目的地：** demo 脚本都用 `argv[1]` 作为接口名 —— `lo` 表示走 domain 1（仿真），真实 NIC 则切到 domain 0（真机）。中间 `unitree_sdk2py` ↔ DDS 那一段在两个场景下完全一致。

#### 📨 每个 demo 都会触碰的 topic

| Topic | 方向（控制脚本视角） | 消息 | 频率 | 谁在用 |
|---|:-:|---|:-:|---|
| `rt/lowstate` | ◀ 订阅 | `unitree_hg::LowState_` | 1 kHz | 每个 demo（关节角速度、力矩、IMU `quat_imu`、`gyroscope`、足底力） |
| `rt/lowcmd` | ▶ 发布 | `unitree_hg::LowCmd_` | 50–500 Hz | 每个 demo（每个关节的 `q`、`dq`、`kp`、`kd`、`tau`） |
| `rt/sportmodestate` | ◀ 订阅 | `unitree_hg::SportModeState_` | 50 Hz | 高层模式自省（仅真机） |
| `rt/api/loco/request` | ▶ 发布 | `unitree_api::Request_` | 按需 | `loco_high` 技能（`g1_brain`，仅真机） |
| `rt/api/motion_switcher/request` | ▶ 发布 | `unitree_api::Request_` | 启动期一次 | `MotionSwitcherClient.ReleaseMode()`（仅真机） |

> 🧷 **CRC 不是装饰。** 每条 `rt/lowcmd` 都有 CRC 字段，桥接器 / 真机会校验。`unitree_sdk2py.utils.crc.CRC` 用来算 CRC；忘了写就会被电机静默忽略。本仓库所有自研 demo 在每次发布前都会先 `cmd.crc = CRC().Crc(cmd)`。

#### 🦴 G1 29-DoF 关节索引图

| 索引 | 关节 | 分组 |
|:-:|---|---|
| 0–5 | `left_hip_pitch` · `left_hip_roll` · `left_hip_yaw` · `left_knee` · `left_ankle_pitch` · `left_ankle_roll` | 🦵 左腿 |
| 6–11 | `right_hip_pitch` · `right_hip_roll` · `right_hip_yaw` · `right_knee` · `right_ankle_pitch` · `right_ankle_roll` | 🦵 右腿 |
| 12–14 | `waist_yaw` · `waist_roll` · `waist_pitch` | 🦴 腰部 |
| 15–21 | `left_shoulder_pitch` · `left_shoulder_roll` · `left_shoulder_yaw` · `left_elbow` · `left_wrist_roll` · `left_wrist_pitch` · `left_wrist_yaw` | 🦾 左臂 |
| 22–28 | `right_shoulder_pitch` · `right_shoulder_roll` · `right_shoulder_yaw` · `right_elbow` · `right_wrist_roll` · `right_wrist_pitch` · `right_wrist_yaw` | 🦾 右臂 |

> 🤹 **为什么 15–28 是特殊的：** `g1_sim_rl_combo.py` 与 `g1_real_rl_combo.py` **只覆盖上肢（关节 15–28）**；腿与腰（0–14）始终在 RL 策略里，避免给 locomotion 控制器一个 OOD 输入。覆盖值会被裁剪到训练时见过的策略包络。

#### 🎚 两种踝关节模式（PR vs AB）

| 模式 | 发什么 | 何时使用 |
|---|---|---|
| **PR**（Pitch-Roll） | 直接给每个踝关节一个目标 | `g1_sim_low_level.py` 前半段；运动学遥控的默认模式。 |
| **AB**（A/B 联动） | 平行联动的 A/B 目标 | `g1_sim_low_level.py` 后半段；某些以平行联动抽象训练的 RL 策略要求。 |

---

### 📚 文档索引

> 没特别标注的都是中文（🇨🇳）。深度笔记每篇 **300–2 000 行**——读起来更像书的一章而不是 README。

#### 🧭 跨切面

| 文档 | 内容 |
|---|---|
| [`docs/demo-overall.md`](docs/demo-overall.md) | 一页串讲：六大核心仓库分别怎么在 MuJoCo 里跑通自己的 demo，含 WSL2 GPU 加速前置块。 |
| [`docs/demo_run.md`](docs/demo_run.md) | 总目录小抄——把所有 demo 命令归档到一处，可直接复制粘贴。 |
| [`docs/libs_compatible.md`](docs/libs_compatible.md) | 定义 `agi` env 的完整兼容性矩阵——逐 pin 推理。 |
| [`docs/wsl2_audio.md`](docs/wsl2_audio.md) | WSL2 + conda 下修 `sounddevice`/PortAudio。 |
| [`docs/camera_ui_demo.md`](docs/camera_ui_demo.md) | `usbipd` → WSL2 → `teleimager.image_server` → 实时图传。 |
| [`docs/ros2_sdk.md`](docs/ros2_sdk.md) | ROS / ROS 2 与 Unitree SDK 的关系，以及 `unitree_ros2` 的位置。 |
| [`docs/vla_wma.md`](docs/vla_wma.md) | 一页入门：VLA vs WMA vs SLAM。 |
| [`docs/vlm_audio_mock.md`](docs/vlm_audio_mock.md) · [`vlm_audio_mock_deep.md`](docs/vlm_audio_mock_deep.md) | 推动 `va-demo` 落地的完整 G1 VLM + 音频 + human-mimic 研究方案。 |
| [`instructions.md`](instructions.md) | "mujoco rl_combo" 与 "mujoco + va-demo + WSL2 USB 摄像头" 的精选启动顺序。 |

#### 🎮 自研 demo

| 文档 | 内容 |
|---|---|
| [`g1_sim_demo/docs/G1 MuJoCo SDK Bridge Demo.md`](g1_sim_demo/docs/G1%20MuJoCo%20SDK%20Bridge%20Demo.md) | 上游 G1 低层例子在仿真里为啥跑不通，以及本仓库怎么修。 |
| [`g1_sim_demo/docs/learn-mujoco.md`](g1_sim_demo/docs/learn-mujoco.md) | 从零开始的 MuJoCo 教程（XML、关节、接触、viewer）。1 700 行。 |
| [`g1_sim_demo/docs/how to use mujoco demo and customize motions.md`](g1_sim_demo/docs/how%20to%20use%20mujoco%20demo%20and%20customize%20motions.md) | 怎么自己设计新的关键帧序列。 |
| [`g1_sim_demo/docs/demo-explain.md`](g1_sim_demo/docs/demo-explain.md) | 每个 `g1_sim_*.py` 脚本逐段解读。 |
| [`g1_sim_demo/docs/mujoco_use1.md`](g1_sim_demo/docs/mujoco_use1.md) · [`mujoco_use2.md`](g1_sim_demo/docs/mujoco_use2.md) | MuJoCo viewer 使用速查。 |
| [`g1_sim_demo/docs/demo-QA1.md`](g1_sim_demo/docs/demo-QA1.md) … [`demo-QA5.md`](g1_sim_demo/docs/demo-QA5.md) | 五轮渐进式 Q&A：键盘延迟、action_scale、OOD 输入、手势安全包络。 |
| [`g1_sim_demo/docs/report.md`](g1_sim_demo/docs/report.md) | 阶段性设计报告。 |
| [`g1_real_demo/docs/demo-QA7.md`](g1_real_demo/docs/demo-QA7.md) | 真机 `lying` 模式接线/DDS 验证。 |
| [`g1_real_demo/issue/realmachine.md`](g1_real_demo/issue/realmachine.md) | 真机 "机器人不动" 诊断日志。 |

#### 🎙️ va-demo

| 文档 | 内容 |
|---|---|
| [`docs/va-demo-design.md`](docs/va-demo-design.md) | 语音 + 视觉 + Realtime 智能体的设计文档。 |
| [`docs/va-demo-use.md`](docs/va-demo-use.md) | 全部 `--mode` 组合的运行指南。 |
| [`docs/va-design.md`](docs/va-design.md) | 阶段性完成总结。 |
| [`va-demo/docs/audio-awake.md`](va-demo/docs/audio-awake.md) | 唤醒词 + 状态机的实现详解。 |
| [`va-demo/docs/audio-use.md`](va-demo/docs/audio-use.md) | 调参指南：VAD 阈值、RMS 门限、倾听窗口。 |
| [`va-demo/docs/video-design.md`](va-demo/docs/video-design.md) | Vision-only 模式设计。 |
| [`va-demo/docs/video-use.md`](va-demo/docs/video-use.md) | Vision-only 模式操作手册。 |

#### 🧠 g1_brain

| 文档 | 内容 |
|---|---|
| [`g1_brain/README.md`](g1_brain/README.md) | 📍 包总览——亮点、目录、安装、运行、模式、技能、安全、感知、模仿、配置、调试、测试、故障排查。 |
| [`docs/g1_plan.md`](docs/g1_plan.md) | 推动 `g1_brain` 落地的 1500+ 行设计稿（慢脑 + 快反射 + 安全技能，Phase 0–7）。 |
| [`docs/vlm_audio_mock.md`](docs/vlm_audio_mock.md) · [`vlm_audio_mock_deep.md`](docs/vlm_audio_mock_deep.md) | 设计前置的架构级研究笔记——VLM + 音频 + human-mimic 入门。 |
| [`g1_brain/docs/architecture.md`](g1_brain/docs/architecture.md) | ~330 行的精简架构（三层、频率表、FSM、感知线程、进程模型）。 |
| [`g1_brain/docs/how_to_run.md`](g1_brain/docs/how_to_run.md) | 操作员手册——前置依赖、4 个终端启动、调试入口、运行模式、常见错误、sim → real 切换、WSL2 注意。 |
| [`g1_brain/docs/extending_skills.md`](g1_brain/docs/extending_skills.md) | 加新工具时要改的 4 个地方 + checklist。 |
| [`g1_brain/docs/g1_brain_QA1.md`](g1_brain/docs/g1_brain_QA1.md) | Q&A 第一轮——`how_to_run.md` 周边的疑问。 |
| [`g1_brain/docs/g1-fix-phase1.md`](g1_brain/docs/g1-fix-phase1.md) | 修复日志：启动后姿态震荡。 |
| [`g1_brain/docs/g1-fix-phase2.md`](g1_brain/docs/g1-fix-phase2.md) | 修复日志：RL ramp + watchdog 宽限期 + 恢复 hold。 |
| [`g1_brain/docs/g1-fix-phase3.md`](g1_brain/docs/g1-fix-phase3.md) | 修复日志：头摄 EGL 线程 + DDS 订阅时序。 |
| [`g1_brain/docs/g1-fix-phase5.md`](g1_brain/docs/g1-fix-phase5.md) | 修复日志：USB watchdog 在 USB 关闭时仍锁住手势。 |

#### 📡 上游深度笔记

| 文档 | 内容 |
|---|---|
| [`docs/unitree_sdk2_python.md`](docs/unitree_sdk2_python.md) | DDS topic、消息 IDL、ChannelFactory、CRC、关节索引。 |
| [`docs/unitree_mujoco.md`](docs/unitree_mujoco.md) | 模拟器架构、桥接器内核、MJCF / 场景制作。 |
| [`docs/unitree_rl_mjlab.md`](docs/unitree_rl_mjlab.md) | RL 框架、训练流水线、sim2real 部署。 |
| [`docs/unitree_ros.md`](docs/unitree_ros.md) | ROS 1 + Gazebo 包，每一份 URDF/SRDF。 |
| [`docs/unitree_ros2.md`](docs/unitree_ros2.md) | ROS 2 桥、Cyclone XML 配置、devcontainer 布局。 |
| [`docs/unitree_lerobot.md`](docs/unitree_lerobot.md) | LeRobot v2/v3 数据转换、策略训练、真机 G1 部署。 |
| [`docs/xr_teleoperate.md`](docs/xr_teleoperate.md) | XR / AVP 遥操架构、重定向、录制。 |
| [`docs/teleimager.md`](docs/teleimager.md) | 多相机 ZMQ + WebRTC 服务内核。 |
| [`docs/unifolm-vla.md`](docs/unifolm-vla.md) | VLA 代码逐文件走读。 |
| [`docs/unifolm-world-model-action.md`](docs/unifolm-world-model-action.md) | WMA 代码逐文件走读。 |
| `docs/Unitree G1 相关 GitHub 仓库深度调研报告.pdf` | 长篇综述报告（PDF）。 |

---

### 📈 性能与资源占用

> 在参考开发机（Ryzen 7 7840HS · RTX 4060 Laptop 8 GB · 32 GB RAM · WSL2 + WSLg, Ubuntu 22.04）上的量级。当成"数量级"看，不是基准。

#### ⏱ 频率

| 回路 | 在哪 | 典型频率 | 备注 |
|---|---|:-:|---|
| 🦴 桥接器 `rt/lowstate` | `unitree_mujoco` | **1 kHz** | 由 MuJoCo step + 桥接循环决定；和真机对齐。 |
| 🚶 RL 策略推理 | `g1_sim_rl_*.py` | **50 Hz** | ONNX Runtime 在 CPU 上比这个快得多 —— 瓶颈是我们选择的发布频率。 |
| 🤹 Combo 上肢覆盖 | `g1_sim_rl_combo.py` | **50 Hz**（同回路） | 单一 publisher，不存在 DDS 竞争。 |
| 🧠 慢脑（Realtime API） | `g1_brain` | **0.2–2 Hz** | 由网络往返 + LLM 思考时间决定。 |
| ⚡ 快反射（感知） | `g1_brain.perception` | **5–30 Hz** | YOLO11 + MediaPipe-Pose + 深度融合；摄像头帧率封顶。 |
| 🎤 唤醒词 | `va-demo.wake_word` | **8–16 Hz** | CPU 上的 `faster-whisper tiny`；约 50–100 ms / 次。 |

#### 💾 内存与磁盘

| 资源 | 占用 | 备注 |
|---|---|---|
| 🟢 `unitree` env（idle RSS） | 约 **400 MB** | 纯 Python + ONNX + MuJoCo。 |
| 🔵 `agi` env（idle RSS） | 约 **1.2 GB** | 加上 torch / transformers / mediapipe / ultralytics。视觉跑起来后峰值 3–4 GB。 |
| 🐍 `agi` env 磁盘 | 约 **14 GB** | 主要是 `nvidia-*` CUDA-13 wheel、torch、tensorflow、mujoco-warp。 |
| 🪞 `g1_brain` 头摄（EGL） | 约 **400 MB** RAM、**0.5 GB** GPU | 每个摄像头各克隆一份 `MjModel`，让 EGL 上下文在单线程里跑。 |
| 🎬 RL ONNX checkpoint | 约 **2 MB** | `policy.onnx` 是个轻量 MLP。 |

#### 🌡 常见瓶颈

- 🥵 WSL2 + sounddevice 在 `audio.input_block_ms < 20` 时 CPU 飙升 —— 别低于 20 ms。
- 🌐 Realtime websocket 的 RTT 是慢脑感知延迟的大头；选离 OpenAI 区域近的网络比任何本地优化都更划算。
- 🧊 WSL2 的 D3D12 GL 路径，第一帧 MuJoCo step 要 1–2 s；之后每步 < 0.5 ms。`np.set_printoptions` 这种暖机别放进控制循环。

---

### 🗺️ 路线图与状态

> 一份"哪些稳定、哪些在打磨、哪些还在愿望清单"的现状卡。不是所有项都由我交付 —— 部分是上游进度。

#### ✅ 稳定

- `g1_sim_demo/g1_sim_low_level.py` · `g1_sim_interactive.py` · `g1_sim_keyboard.py` —— 正弦 + 关键帧 playground。
- `g1_sim_demo/g1_sim_rl_walk.py` · `g1_sim_rl_combo.py` —— RL 行走 + 上肢手势 combo。
- `g1_real_demo/g1_real_rl_combo.py` —— 真机版（含 `lying` 检线模式）。
- `va-demo/` —— 唤醒词门控的 Realtime 语音 + 视觉智能体（4 种运行模式）。
- `g1_brain/` —— 慢脑 + 快反射 + 安全技能：11 条规则 supervisor · 7 状态 FSM · 独立 E-stop · 17 个 LLM 工具 · MuJoCo 头摄感知 · `mock_imitate`（Phase 5）。
- `requirements.txt` —— `agi` env 的逐字冻结，`python=3.11` + `pip install -r requirements.txt` 一键复现。

#### 🚧 进行中 / 打磨中

- 🧠 长期对话日志 schema（typed content blocks、`uuid`、`session_id`）—— 为后续 SQLite + FTS5 摄入做准备。
- 🎯 视觉风险门（`g1_brain/safety/vision_risk_gate.py`）—— 在 11 条规则之外补一层针对 ambiguous human-proximity 的检查。
- 🦿 `mock_imitate` 端到端真机验证（仿真已通；真机镜像回路在调）。
- 📷 立体 / RealSense 头摄的真深度通路（当前用 MuJoCo 单目 + 深度派生）。

#### 🌱 愿望清单

- 🤗 把 `unitree_lerobot` 的 ACT / Diffusion / π₀ 策略接进 `g1_brain` 的 SkillServer。
- 🌐 给 `g1_brain` 的 `SceneState` 写一个 ROS 2 Jazzy 桥，让其它 ROS 节点也能订阅融合后的感知。
- 🧬 用 `unifolm-world-model-action` 做世界模型 rollout，在 `walk` 实际下发前做规划性预演。
- 🧤 灵巧手遥操闭环：`xr_teleoperate` → `g1_brain` 技能 → 真机 Dex3 / Inspire / Brainco。

> 🤝 **想帮忙？** 见 [§ 参与贡献](#-参与贡献)，里面列了最匹配的 PR 类型。

---

### 🛠️ 故障排查

<details>
<summary><b>🔴 终端 2 卡在 <code>waiting for first /rt/lowstate</code></b></summary>

模拟器没起来，**或者** DDS 的 domain / 网卡跟脚本对不上。逐项检查：

```python
# unitree_mujoco/simulate_python/config.py
DOMAIN_ID = 1
INTERFACE = "lo"
```

并确认终端 1 的 `python unitree_mujoco.py` 仍在运行。
</details>

<details>
<summary><b>🔴 脚本一启动 G1 就摔倒</b></summary>

忘了开悬挂带。**先**在 viewer 里按 <kbd>9</kbd>，**再**起控制脚本。RL 行走 demo 还需要按 <kbd>8</kbd> 几下，**把带子放低让脚刚好接触地面**，再视情况按 <kbd>9</kbd> 关掉带子——但**只能**在终端打印出 `[rl] policy ready` 之后再关。
</details>

<details>
<summary><b>🔴 WSL2 下 GLFW / viewer 弹不出来</b></summary>

WSLg 会自动设 `$DISPLAY`。如果是 SSH 进来的，要用 `ssh -X user@host`。还不行就 `glxinfo | head` 确认 OpenGL 是否可用。要 GPU 加速，[`instructions.md`](instructions.md) 给出了把 WSL2 切到 NVIDIA D3D12 的 `MESA_LOADER_DRIVER_OVERRIDE=d3d12` / `MUJOCO_GL=glfw` 启动块。
</details>

<details>
<summary><b>🔴 <code>ModuleNotFoundError: unitree_sdk2py</code></b></summary>

从本仓库可编辑安装 SDK：

```bash
pip install -e unitree_sdk2_python
```
</details>

<details>
<summary><b>🔴 仿真：CRC 校验失败 / 电机不动</b></summary>

模拟器必须加载 G1 的 29-DOF 场景（`ROBOT="g1"` 时默认就是），桥接器必须用 `unitree_hg` 系列消息——这两条只要 `config.ROBOT == "g1"` 就会自动满足。回去再核对一次仿真器配置。
</details>

<details>
<summary><b>🔴 真机：bridge 起来了但关节没反应</b></summary>

真机高层控制器仍占着 `rt/lowcmd`。`g1_real_demo/g1_real_rl_combo.py` 用 `MotionSwitcherClient.ReleaseMode()` 解决——确认 stdout 里这次调用成功。完整事件日志在 [`g1_real_demo/issue/realmachine.md`](g1_real_demo/issue/realmachine.md)。
</details>

<details>
<summary><b>🔴 va-demo：<code>OSError: PortAudioError ... device unavailable</code></b></summary>

WSL/Linux 音频栈没透出默认麦/扬声器。三步走：

1. 按 [`docs/wsl2_audio.md`](docs/wsl2_audio.md) 给 conda env 打上 ALSA→Pulse 软链。
2. `conda install -n agi -c conda-forge portaudio`。
3. 在 `va-demo/configs/va_demo.yaml` 里把 `audio.input_device` / `audio.output_device` 写成 `python -c "import sounddevice as sd; print(sd.query_devices())"` 给出的具体设备号。
</details>

<details>
<summary><b>🔴 va-demo：<code>no frame received</code></b></summary>

`teleimager.image_server` 没起来，**或者**摄像头没挂到 WSL2。从 PowerShell `usbipd attach --wsl --busid <id>`（见 [`docs/camera_ui_demo.md`](docs/camera_ui_demo.md)），并核对 `cam_config_server.yaml::head_camera::zmq_port` 与 `va_demo.yaml` 是否一致。
</details>

<details>
<summary><b>🔴 va-demo：怎么喊都不"嗨 Sparky"</b></summary>

`configs/va_demo.yaml::wakeword` 下两个旋钮：

- `rms_threshold`——背景音里乱触发就调高，正常说话还触发不了就调低。
- `phrases`——把口音变体（"hi sparkie"、"嗨 spark"）加到子串列表里。

跑 `python scripts/wake_word_debug.py` 可以实时看匹配器每帧的判定。
</details>

<details>
<summary><b>🔴 <code>agi</code> env 下 <code>numpy</code> ABI 不匹配 / <code>torch</code> 导入报错</b></summary>

几乎都是某次 `pip install` 把 numpy 升过 2.0 了。重新锁回去：

```bash
pip install --force-reinstall "numpy==1.26.4"
```

让 7 个上游都能活下去的完整 pin 集合在 [`docs/libs_compatible.md`](docs/libs_compatible.md)，逐字冻结版本在仓库根的 [`requirements.txt`](requirements.txt)。
</details>

<details>
<summary><b>🔴 <code>g1_brain</code>：头摄一直 0 FPS / 安全规则 5 反复触发</b></summary>

头摄走的是单线程 EGL，并各自克隆一份 `MjModel`。常见两种原因：

1. `configs/g1_brain.yaml` 里的 `robot.mjcf_path` 与 `unitree_mujoco` 实际加载的场景不一致 —— 两边都用同一份 XML（terrain 与否一致），克隆出来的 model 才能和 viewer 看到的一样。
2. `MUJOCO_GL` 没设成 `glfw`（无头机器上是 `egl`）。在仿真终端里 `export MUJOCO_GL=glfw`。

完整事件日志见 [`g1_brain/docs/g1-fix-phase3.md`](g1_brain/docs/g1-fix-phase3.md)（EGL 线程 + DDS 订阅时序）。
</details>

<details>
<summary><b>🔴 <code>g1_brain</code>：启动后立刻调运动总是被 <code>"FSM gating"</code> 拒</b></summary>

规则 2（FSM 关卡）会把运动调用挡在 `BOOT` 外。`lowstate` 到位、RL 策略 ramp 完、run-mode 关卡通过后，FSM 自动 `BOOT → STANDING → ENGAGED → ACTING`，通常不到 2 秒。卡在 `BOOT` 的话：

- 确认 `lowstate` 在流（终端 2 仿真还活着、`DOMAIN_ID=1`、`INTERFACE=lo`）。
- 确认终端打了 `[rl] policy ready` —— 规则 6 在此之前不会通过。
- FSM 状态图见 [`g1_brain/docs/architecture.md`](g1_brain/docs/architecture.md)。
</details>

<details>
<summary><b>🔴 <code>pip install -e ./unitree_sdk2_python</code> 卡在 <code>cyclonedds</code> wheel 编译</b></summary>

CycloneDDS 的 Python 绑定只有 Linux x86_64 + CPython 3.10/3.11 的 prebuilt wheel；macOS、原生 Windows、或 Python 3.12 都会回退到源码编译，几乎必败。请按 [§ 环境依赖](#-环境依赖) 用 **WSL2 + Ubuntu 22.04 / 24.04 + Python 3.11**。
</details>

<details>
<summary><b>🔴 Realtime websocket 大约每 30 秒断一次</b></summary>

九成是网络代理 / VPN —— OpenAI Realtime API 用的是长连 websocket，激进的企业代理会把 idle TCP 关了。要么走直连，要么把 `api.openai.com` 加白；`va-demo` 自己已经在 ping `response.create` 保活，30 秒以内的断线大概率不是它的问题。
</details>

<details>
<summary><b>🔴 装 <code>requirements.txt</code> 在 <code>-e ./unifolm-vla</code> 上失败</b></summary>

未打过补丁的上游 `pyproject.toml` 写的是 `numpy >= 2.0`，跟解出来的 `numpy==1.26.4` 撞车。仓库内 `pyproject.toml.bak` 文件记录了"幽灵 pin 应该改成什么样"——按它改（或对照 [`docs/libs_compatible.md`](docs/libs_compatible.md) 的手动编辑指引）后再装。
</details>

<details>
<summary><b>🔴 真机：<code>MotionSwitcher</code> 释放成功但机器人还是不响应指令</b></summary>

`ReleaseMode()` 之后还有两个排查点：

1. 模式切换确认会从 `rt/sportmodestate` 回来 —— 必须等到 `mode == 0`（debug / 低层）才发 `rt/lowcmd`。`g1_real_rl_combo.py` 已经做了这一握手；自己写脚本时务必照搬。
2. 机器人本体的 e-stop 按键按下时，任何 lowcmd 都不会执行。先看本体 LED 状态，再怀疑软件。

完整事件日志：[`g1_real_demo/issue/realmachine.md`](g1_real_demo/issue/realmachine.md)。
</details>

---

### ❓ 常见问题（FAQ）

<details>
<summary><b>❓ 我得有真机 G1 才能用这个仓库吗？</b></summary>

不需要。每个 demo 都是先在 MuJoCo 桥接器上跑通的；`g1_real_demo/` 仅在你局域网里有真机 G1 EDU 时才相关。语音 + 视觉智能体（`va-demo/`）和认知智能体（`g1_brain/`）完全可以纯仿真跑。
</details>

<details>
<summary><b>❓ 能在 macOS 或原生 Windows 上跑吗？</b></summary>

目前不行。CycloneDDS 的 Python wheel 只有 Linux x86_64；其余的 mujoco、torch+cu130、mediapipe 也都依赖 Linux wheel。请用 **Ubuntu 22.04 / 24.04** 或 Windows 11 下的 **WSL2 + WSLg**。
</details>

<details>
<summary><b>❓ 没有 OpenAI API key 也能跑 <code>g1_brain</code> 吗？</b></summary>

可以跑一部分 —— 感知层、scene-state 总线、SkillServer 都不依赖 LLM，可以用 `python -m g1_brain.apps.skill_debug` 或 `safety_debug` 直接驱动。慢脑（Realtime + Vision）那一层确实需要 `OPENAI_API_KEY`。
</details>

<details>
<summary><b>❓ 为什么把 <code>numpy</code> 锁在 1.26.4 而不是升到 2.x？</b></summary>

`tensorflow 2.15`、`mediapipe 0.10`、几个 `unifolm-*` 包，以及一些较老的、跟 `cyclonedds` 同代的库，依然用 numpy 1.x ABI 编译。把 numpy 升到 2.0 后，`agi` env 的 7 个上游里至少 3 个会立刻挂掉。完整推理在 [`docs/libs_compatible.md`](docs/libs_compatible.md)。
</details>

<details>
<summary><b>❓ 为什么 <code>mujoco</code> 必须正好 3.5.0？</b></summary>

`mujoco-warp 3.5.0`（`unitree_rl_mjlab` 训练端用的 GPU 后端）要求版本严格对齐 —— mujoco / mujoco-warp / `mjlab` 的 C ABI 在不同 patch 版本之间还不稳定。
</details>

<details>
<summary><b>❓ 怎么给 <code>g1_brain</code> 加新技能？</b></summary>

按顺序四处改：(1) `g1_brain/skills/tool_schemas.py` 里加 schema；(2) `g1_brain/skills/skill_server.py` 实现 handler；(3) `g1_brain/safety/supervisor.py` 的 FSM 白名单里登记；(4) `g1_brain/tests/` 加测试。完整 checklist 见 [`g1_brain/docs/extending_skills.md`](g1_brain/docs/extending_skills.md)。
</details>

<details>
<summary><b>❓ 能换成别的 LLM（Claude / Gemini / 本地模型）吗？</b></summary>

`va-demo` 与 `g1_brain` 是按 OpenAI Realtime API 的形态设计的 —— 服务端 VAD 的 turn 模型和 tool_call schema 渗透到了 transcript 持久化、prompt 结构、视觉调用等多处。理论上写一层非 Realtime 适配可以跑，但当前不在 in-tree 计划里；最小可用切口是给 `BrainRealtimeAgent` 写子类 + 一个 transport shim。
</details>

<details>
<summary><b>❓ 显存大概要多少？</b></summary>

推理（仿真回放、`g1_brain` 感知）6 GB 显卡很舒服；8 GB 笔记本卡能同时跑 YOLO11 + MediaPipe-Pose + Realtime 客户端 + 头摄抓帧而不 OOM。RL **训练**（`unitree_rl_mjlab`）要 16 GB+，那不是开发机干的活，是集群活。
</details>

---

### 🤝 参与贡献

欢迎贡献，特别是：

- 🆕 **新 demo**（`g1_sim_demo/` 或 `g1_real_demo/` 下，例如 `pygame` 遥控、ROS 2 桥、动捕重定向）。
- 🎙️ **va-demo 新技能**（新工具调用——例如 `look_at(target)`、`count_steps_to(object)`）。
- 🧠 **`g1_brain/` 新技能、安全规则、感知派生量**——按 [`g1_brain/docs/extending_skills.md`](g1_brain/docs/extending_skills.md) 的 4 步配方走。
- 📝 **文档英译**（把 `docs/*.md` 的深度解读翻译成英文）。
- 🐛 **bug 修复**（任意自研脚本）。

#### 流程

```bash
# fork → clone → 拉分支
git checkout -b feature/my-cool-demo

# 在 g1_sim_demo/ 或 va-demo/ 下写代码，沿用现有的 module-docstring 风格
# （运行步骤 / 架构概述 / 按键映射 / 依赖）

# 验证
python g1_sim_demo/my_cool_demo.py
# 或
cd va-demo && python -m pytest tests/ -v

# 提交 + 推送 + 开 PR
git commit -m "feat: add <demo name>"
git push origin feature/my-cool-demo
```

> 🙅 **请勿修改**任何上游快照目录（`unitree_sdk2_python/`、`unitree_mujoco/`、`unitree_rl_mjlab/`、`unitree_ros/`、`unitree_ros2/`、`unitree_sim_isaaclab/`、`unitree_lerobot/`、`xr_teleoperate/`、`teleimager/`、`unifolm-vla/`、`unifolm-world-model-action/`）——它们要保持干净以便和上游 diff。如果一定要打补丁，请用 overlay / wrapper 的方式实现。两个 `pyproject.toml.bak` 文件记录了为兼容 `agi` env 必须做的幽灵 pin 修改。

---

### 📜 许可证

本仓库内含多种许可证：

| 路径 | 许可证 | 来源 |
|---|---|---|
| `g1_sim_demo/`、`g1_real_demo/`、`va-demo/`、`g1_brain/`、`docs/`、`instructions.md`、`requirements.txt`、`README.md` | **Apache 2.0** | 本仓库 |
| `unitree_sdk2_python/`、`unitree_mujoco/`、`unitree_rl_mjlab/`、`unitree_ros/`、`unitree_ros2/`、`unitree_sim_isaaclab/`、`unitree_lerobot/`、`xr_teleoperate/`、`teleimager/` | 见各仓库 `LICENSE` | © 宇树科技 |
| `unifolm-vla/`、`unifolm-world-model-action/` | 见各仓库 `LICENSE` | © 宇树科技 / UnifoLM |

二次分发时，请保留各上游许可证文件以及对应的 NOTICE。

---

### 🙏 致谢

如果没有以下项目的开源贡献，本仓库不可能存在：

- 🏢 **[宇树科技 / Unitree Robotics](https://www.unitree.com/)** — 提供 SDK、MuJoCo 桥接器、`mjlab` RL 框架、IsaacLab 任务、LeRobot 适配、XR 遥操、图像服务、以及 UnifoLM 模型家族。
- 🔬 **[Google DeepMind / MuJoCo 团队](https://mujoco.org/)** — 提供物理引擎。
- 🧠 **[`rsl_rl`](https://github.com/leggedrobotics/rsl_rl)** by ETH Robotic Systems Lab — on-policy PPO 训练器。
- ⚡ **[NVIDIA Warp](https://github.com/NVIDIA/warp) & [Isaac Lab](https://isaac-sim.github.io/IsaacLab/)** — GPU 加速的 MuJoCo Warp 后端与操作仿真器。
- 🤗 **[HuggingFace LeRobot](https://github.com/huggingface/lerobot)** — 数据集格式与策略库（ACT / Diffusion / π₀ / GR00T）。
- 🎙️ **[OpenAI Realtime / Vision / TTS API](https://platform.openai.com/)** — `va-demo` 背后的认知层。
- 🔊 **[`faster-whisper`](https://github.com/SYSTRAN/faster-whisper) & [`webrtcvad`](https://github.com/wiseman/py-webrtcvad)** — 本地唤醒词 + utterance VAD 流水线。

如果这个仓库对你有帮助，**给一个 ⭐ 是最便宜的鼓励方式。**

---

<div align="center">

<br/>

**Made with ☕ &nbsp;by [@SparkyWen](https://github.com/SparkyWen) — for the Unitree community.**

*"The best way to learn a robot is to make it dance — first in sim, then for real, and one day, it'll talk back."*

<br/>

[⬆ Back to top / 回到顶部](#-unitree-notes)

</div>
