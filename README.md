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

[![Unitree](https://img.shields.io/badge/Robot-Unitree_G1-FF6B35?style=flat-square&logo=robotframework&logoColor=white)](https://www.unitree.com/g1)
[![Platform](https://img.shields.io/badge/Platform-Linux_/_WSL2-FCC624?style=flat-square&logo=linux&logoColor=black)](https://learn.microsoft.com/windows/wsl/)
[![DDS](https://img.shields.io/badge/DDS-CycloneDDS-00ADD8?style=flat-square&logo=eclipsefoundation&logoColor=white)](https://github.com/eclipse-cyclonedds/cyclonedds)
[![ROS 2](https://img.shields.io/badge/ROS_2-Jazzy-22314E?style=flat-square&logo=ros&logoColor=white)](https://docs.ros.org/en/jazzy/)
[![Conda](https://img.shields.io/badge/Conda-Miniforge-44A833?style=flat-square&logo=anaconda&logoColor=white)](https://github.com/conda-forge/miniforge)
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

> A complete, opinionated workspace for studying, simulating, and deploying control & cognition stacks on the **Unitree G1** humanoid — bundling **ten upstream reference repos** (SDK, MuJoCo, RL, ROS, IsaacLab, LeRobot, VLA, WMA, XR teleop, image server) alongside three hand-written deliverables: `g1_sim_demo/` (sim demos from sine wave to RL+gestures), `g1_real_demo/` (real-robot deployment), and `va-demo/` (a voice + vision agent that talks to G1 via OpenAI Realtime).

### 📑 Table of Contents

- [✨ Highlights](#-highlights)
- [🗂️ Repository Layout](#%EF%B8%8F-repository-layout)
- [🐍 Two Conda Environments](#-two-conda-environments)
- [📦 Prerequisites](#-prerequisites)
- [🚀 Quick Start](#-quick-start)
- [🌟 In-house Deliverables](#-in-house-deliverables)
  - [🎬 `g1_sim_demo/` — MuJoCo demo catalogue](#-g1_sim_demo--mujoco-demo-catalogue)
  - [🦿 `g1_real_demo/` — real-robot deployment](#-g1_real_demo--real-robot-deployment)
  - [🎙️ `va-demo/` — voice + vision agent](#%EF%B8%8F-va-demo--voice--vision-agent)
- [📡 Upstream Reference Repos](#-upstream-reference-repos)
- [🧱 Architecture Overview](#-architecture-overview)
- [📚 Documentation Index](#-documentation-index)
- [🛠️ Troubleshooting](#%EF%B8%8F-troubleshooting)
- [🤝 Contributing](#-contributing)
- [📜 License](#-license)
- [🙏 Acknowledgements](#-acknowledgements)

---

### ✨ Highlights

| | |
|---|---|
| 🤖 **Ten upstream repos in one place** | Pinned snapshots of `unitree_sdk2_python`, `unitree_mujoco`, `unitree_rl_mjlab`, `unitree_ros`, `unitree_ros2`, `unitree_sim_isaaclab`, `unitree_lerobot`, `xr_teleoperate`, `teleimager`, `unifolm-vla`, and `unifolm-world-model-action` — every layer of the G1 stack readable in one `cd`. |
| 🎮 **Five turn-key G1 sim demos** | From a 70-line "send a sine wave" warm-up to a 1000-line RL+gesture combo controller, every script is heavily commented and runs **out of the box** against the Python MuJoCo bridge. |
| 🦿 **Real-robot deployment harness** | `g1_real_demo/g1_real_rl_combo.py` adds the `MotionSwitcher` release, bounded `lowstate` wait, and a `lying`-mode CLI for wiring/DDS verification before you ever stand the robot up. |
| 🎙️ **Voice + Vision Realtime agent** | `va-demo/` ships a wake-word ("Hi Sparky") gated, full-duplex Realtime voice agent that can **describe scenes via vision** *and* tool-call `walk` / `gesture` / `stop` against the running RL policy — confirm / observe / active / vision-only run modes. |
| 🧠 **Real ONNX policy in the loop** | `g1_sim_rl_walk.py`, `g1_sim_rl_combo.py`, and `g1_real_rl_combo.py` all load the official `unitree_rl_mjlab` velocity-tracking ONNX checkpoint and execute the **exact same observation / action pipeline** end-to-end on sim and on hardware. |
| 🧷 **Sim-friendly fixes baked in** | Upstream `g1_low_level_example.py` deadlocks on `MotionSwitcherClient.CheckMode()` and assumes DDS domain 0 — every script in `g1_sim_demo/` ships with the proven domain-1 + skip-MotionSwitcher patch and a `mode_machine` handshake. |
| 🐍 **One unified conda env** | `agi` env reconciles 7 mutually-conflicting upstreams (numpy 1.26.4 + torch 2.11.0+cu130 + mujoco 3.5.0 + tyro 1.0.13 + …) — full compatibility matrix in [`docs/libs_compatible.md`](docs/libs_compatible.md). A leaner `unitree` env exists for sim+RL only. |
| 📚 **27 000+ lines of curated Chinese notes** | Heavily-annotated walkthroughs on MuJoCo internals, lowcmd/lowstate schemas, joint indices, training-time invariants, the policy-tolerant arm-override envelope, ROS↔SDK lineage, VLA vs WMA semantics, WSL2 audio plumbing — every file in `docs/` and `*/docs/` is project-grade reading. |

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

| Env | Purpose | Python | Key pins | Where to use |
|---|---|---|---|---|
| 🟢 **`unitree`** | Plain sim + RL stack | 3.11 | mujoco 3.5.0 · cyclonedds 0.10.2 · torch 2.11 · onnxruntime 1.25 · mjlab 1.2.0 · rsl-rl-lib 5.0.1 | `g1_sim_demo/`, `g1_real_demo/`, `unitree_mujoco`, `unitree_rl_mjlab` training |
| 🔵 **`agi`** | Everything-in-one | 3.11 | numpy **1.26.4** · torch 2.11+cu130 · mujoco 3.5.0 · tyro 1.0.13 · transformers 4.52 · diffusers 0.35 · tensorflow 2.15 · faster-whisper · webrtcvad-wheels · openai · pyzmq | `va-demo/`, `teleimager`, `unifolm-vla`, `unifolm-world-model-action`, `xr_teleoperate`, `unitree_lerobot` |

> 📐 **Why two?** Seven upstream `pyproject.toml` files disagree on numpy / torch / mujoco / tyro pins. The `agi` env is the resolved compatibility set — patches for `unifolm-vla/pyproject.toml` and `unifolm-world-model-action/pyproject.toml` (saved as `pyproject.toml.bak`) loosen ghost pins. The full reasoning is in [`docs/libs_compatible.md`](docs/libs_compatible.md).
>
> 🔧 `unitree_ros2` is **not** a Python package — install it as a system-level ROS 2 **Jazzy** workspace following [`docs/ros2_sdk.md`](docs/ros2_sdk.md).

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
<summary><b>🔵 Option B — unified <code>agi</code> env (sim + RL + va-demo + VLA + teleop)</b></summary>

Follow the step-by-step guide in [`docs/libs_compatible.md`](docs/libs_compatible.md). High-level shape:

```bash
conda create -n agi python=3.11 -y
conda activate agi

# numerical base — must come first to lock numpy 1.26.4
pip install "numpy==1.26.4" "scipy<2"

# Unitree sim + RL stack
pip install -e unitree_sdk2_python
pip install -e unitree_mujoco/simulate_python   # if applicable
pip install -e unitree_rl_mjlab

# va-demo deps
pip install -r va-demo/requirements.txt

# teleimager + xr_teleoperate
pip install -e "teleimager[server]"
pip install -e xr_teleoperate         # follow its README extras

# UnifoLM stacks (after editing the two pyproject.toml.bak ghost pins)
pip install -e unifolm-vla
pip install -e unifolm-world-model-action

# unitree_lerobot
pip install -e unitree_lerobot
```

> ⚠️ Read [`docs/libs_compatible.md`](docs/libs_compatible.md) before running these — there are several `pyproject.toml` edits required to break ghost pins.
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

---

### 📡 Upstream Reference Repos

> All ten directories below are **read-only snapshots** kept clean for diffability against upstream. Patch by overlay/wrapping rather than editing them in place.

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

The full set of pins that survives all 7 upstreams is in [`docs/libs_compatible.md`](docs/libs_compatible.md).
</details>

---

### 🤝 Contributing

Contributions are welcome — especially:

- 🆕 **New demos** under `g1_sim_demo/` or `g1_real_demo/` (e.g. teleoperation via `pygame`, ROS 2 bridge, MoCap retargeting).
- 🎙️ **va-demo skills** (new tool calls — e.g. `look_at(target)`, `count_steps_to(object)`).
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
| `g1_sim_demo/`, `g1_real_demo/`, `va-demo/`, `docs/`, `instructions.md`, `requirements.txt`, `README.md` | **Apache 2.0** | This repository |
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

> 一个为 **宇树 G1 人形机器人** 量身打造的、完整的、有观点的研究 / 仿真 / 真机部署工作区。仓库里同时包含 **十份上游参考代码快照**（SDK / MuJoCo / RL / ROS / IsaacLab / LeRobot / VLA / WMA / XR 遥操 / 图像服务器）和三套自研交付物：`g1_sim_demo/`（从正弦波到 RL+手势的仿真 demo）、`g1_real_demo/`（真机部署）、`va-demo/`（基于 OpenAI Realtime 的语音 + 视觉智能体）。

### 📑 目录

- [✨ 核心亮点](#-核心亮点)
- [🗂️ 仓库结构](#%EF%B8%8F-仓库结构)
- [🐍 两个 Conda 环境](#-两个-conda-环境)
- [📦 环境依赖](#-环境依赖)
- [🚀 快速开始](#-快速开始)
- [🌟 自研交付物](#-自研交付物)
  - [🎬 `g1_sim_demo/` — MuJoCo Demo 一览](#-g1_sim_demo--mujoco-demo-一览)
  - [🦿 `g1_real_demo/` — 真机部署](#-g1_real_demo--真机部署)
  - [🎙️ `va-demo/` — 语音 + 视觉智能体](#%EF%B8%8F-va-demo--语音--视觉智能体)
- [📡 上游参考仓库](#-上游参考仓库)
- [🧱 架构总览](#-架构总览)
- [📚 文档索引](#-文档索引)
- [🛠️ 故障排查](#%EF%B8%8F-故障排查)
- [🤝 参与贡献](#-参与贡献)
- [📜 许可证](#-许可证)
- [🙏 致谢](#-致谢)

---

### ✨ 核心亮点

| | |
|---|---|
| 🤖 **十个上游仓库一站到位** | 同时托管 `unitree_sdk2_python`、`unitree_mujoco`、`unitree_rl_mjlab`、`unitree_ros`、`unitree_ros2`、`unitree_sim_isaaclab`、`unitree_lerobot`、`xr_teleoperate`、`teleimager`、`unifolm-vla`、`unifolm-world-model-action` 的固定快照——G1 软件栈每一层都能在一个 `cd` 内读到。 |
| 🎮 **五个开箱即用的 G1 仿真 demo** | 从 70 行的"发一段正弦波"热身脚本，到 1000 行的 RL+手势 combo 控制器，每个脚本都写满了 inline 注释，对着 Python MuJoCo 桥接器 **直接就能跑**。 |
| 🦿 **真机部署脚手架** | `g1_real_demo/g1_real_rl_combo.py` 在 sim 版本基础上加了 `MotionSwitcher` 释放、有界 `lowstate` 等待和 `lying` 检线模式——在让机器人站起来之前就能验证 DDS 通路。 |
| 🎙️ **语音 + 视觉 Realtime 智能体** | `va-demo/` 自带"嗨 Sparky"唤醒词的 OpenAI Realtime 全双工语音智能体，可以**调用视觉**描述场景，也能**工具调用** `walk` / `gesture` / `stop` 直接驱动 RL 策略——支持 confirm / observe / active / vision-only 四种运行模式。 |
| 🧠 **真 ONNX 策略闭环跑** | `g1_sim_rl_walk.py`、`g1_sim_rl_combo.py`、`g1_real_rl_combo.py` 全部直接加载 `unitree_rl_mjlab` 官方的速度跟踪 ONNX checkpoint——sim 和真机走的是同一条 obs/action 流水线。 |
| 🧷 **针对仿真的修复内置** | 上游 `g1_low_level_example.py` 在仿真里会卡死在 `MotionSwitcherClient.CheckMode()`，且 DDS domain 写死为 0。本仓库脚本默认走 domain 1、跳过 MotionSwitcher、并补上 `mode_machine` 握手。 |
| 🐍 **统一的一份 conda 环境** | `agi` env 调和了 7 个互相冲突的上游（numpy 1.26.4 + torch 2.11.0+cu130 + mujoco 3.5.0 + tyro 1.0.13 + …），完整兼容性矩阵见 [`docs/libs_compatible.md`](docs/libs_compatible.md)；只跑 sim+RL 时可用更精简的 `unitree` env。 |
| 📚 **27 000+ 行精读中文笔记** | MuJoCo 内核、lowcmd / lowstate schema、关节索引、训练时的隐式不变量、策略可容忍的"上肢覆盖包络"、ROS↔SDK 关系、VLA vs WMA 语义、WSL2 音频通路——`docs/` 和 `*/docs/` 下每一篇都是项目级阅读。 |

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

| Env | 用途 | Python | 关键 pin | 在哪用 |
|---|---|---|---|---|
| 🟢 **`unitree`** | 纯 sim + RL 栈 | 3.11 | mujoco 3.5.0 · cyclonedds 0.10.2 · torch 2.11 · onnxruntime 1.25 · mjlab 1.2.0 · rsl-rl-lib 5.0.1 | `g1_sim_demo/`、`g1_real_demo/`、`unitree_mujoco`、`unitree_rl_mjlab` 训练 |
| 🔵 **`agi`** | 全功能整合 | 3.11 | numpy **1.26.4** · torch 2.11+cu130 · mujoco 3.5.0 · tyro 1.0.13 · transformers 4.52 · diffusers 0.35 · tensorflow 2.15 · faster-whisper · webrtcvad-wheels · openai · pyzmq | `va-demo/`、`teleimager`、`unifolm-vla`、`unifolm-world-model-action`、`xr_teleoperate`、`unitree_lerobot` |

> 📐 **为什么要两个？** 七份上游 `pyproject.toml` 在 numpy / torch / mujoco / tyro 上互相冲突。`agi` env 是把矛盾解开后的最终兼容集——`unifolm-vla/pyproject.toml` 和 `unifolm-world-model-action/pyproject.toml` 各保留了一份 `pyproject.toml.bak` 作为放宽幽灵 pin 的存档。完整推理见 [`docs/libs_compatible.md`](docs/libs_compatible.md)。
>
> 🔧 `unitree_ros2` **不是** Python 包——按 [`docs/ros2_sdk.md`](docs/ros2_sdk.md) 装成系统级 ROS 2 **Jazzy** 工作区。

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
<summary><b>🔵 选项 B — 整合 <code>agi</code> env（sim + RL + va-demo + VLA + 遥操）</b></summary>

按 [`docs/libs_compatible.md`](docs/libs_compatible.md) 一步一步装。大致顺序：

```bash
conda create -n agi python=3.11 -y
conda activate agi

# 数值底座——必须最先装来锁住 numpy 1.26.4
pip install "numpy==1.26.4" "scipy<2"

# Unitree sim + RL 栈
pip install -e unitree_sdk2_python
pip install -e unitree_mujoco/simulate_python   # 如适用
pip install -e unitree_rl_mjlab

# va-demo 依赖
pip install -r va-demo/requirements.txt

# teleimager + xr_teleoperate
pip install -e "teleimager[server]"
pip install -e xr_teleoperate         # 按其 README 装额外依赖

# UnifoLM 双栈（先按 pyproject.toml.bak 改幽灵 pin）
pip install -e unifolm-vla
pip install -e unifolm-world-model-action

# unitree_lerobot
pip install -e unitree_lerobot
```

> ⚠️ 装之前**必须**先看 [`docs/libs_compatible.md`](docs/libs_compatible.md)——有几处 `pyproject.toml` 需要手动改才能解开 ghost pin。
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

---

### 📡 上游参考仓库

> 下面这十个目录都是**只读快照**，保持干净以便和上游做 diff。要打补丁请用 overlay / wrapper，不要直接改它们。

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

让 7 个上游都能活下去的完整 pin 集合在 [`docs/libs_compatible.md`](docs/libs_compatible.md)。
</details>

---

### 🤝 参与贡献

欢迎贡献，特别是：

- 🆕 **新 demo**（`g1_sim_demo/` 或 `g1_real_demo/` 下，例如 `pygame` 遥控、ROS 2 桥、动捕重定向）。
- 🎙️ **va-demo 新技能**（新工具调用——例如 `look_at(target)`、`count_steps_to(object)`）。
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
| `g1_sim_demo/`、`g1_real_demo/`、`va-demo/`、`docs/`、`instructions.md`、`requirements.txt`、`README.md` | **Apache 2.0** | 本仓库 |
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
