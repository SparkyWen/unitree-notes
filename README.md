<div align="center">

# 🤖 Unitree Notes

### *A curated reference & simulation playground for the Unitree G1 humanoid*

*面向宇树 G1 人形机器人的参考资料与仿真试验场*

<br/>

[![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![MuJoCo](https://img.shields.io/badge/MuJoCo-3.5.0-1A73E8?style=for-the-badge&logo=googlecolab&logoColor=white)](https://mujoco.org/)
[![PyTorch](https://img.shields.io/badge/PyTorch-2.11-EE4C2C?style=for-the-badge&logo=pytorch&logoColor=white)](https://pytorch.org/)
[![ONNX](https://img.shields.io/badge/ONNX_Runtime-1.25-005CED?style=for-the-badge&logo=onnx&logoColor=white)](https://onnxruntime.ai/)
[![CUDA](https://img.shields.io/badge/CUDA-13.0-76B900?style=for-the-badge&logo=nvidia&logoColor=white)](https://developer.nvidia.com/cuda-toolkit)

[![Unitree](https://img.shields.io/badge/Robot-Unitree_G1-FF6B35?style=flat-square&logo=robotframework&logoColor=white)](https://www.unitree.com/g1)
[![Platform](https://img.shields.io/badge/Platform-Linux_/_WSL2-FCC624?style=flat-square&logo=linux&logoColor=black)](https://learn.microsoft.com/windows/wsl/)
[![DDS](https://img.shields.io/badge/DDS-CycloneDDS-00ADD8?style=flat-square&logo=eclipsefoundation&logoColor=white)](https://github.com/eclipse-cyclonedds/cyclonedds)
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

> A complete, opinionated workspace for studying, simulating, and deploying control policies on the **Unitree G1** humanoid robot — bundling three upstream reference repos with a hand-written `g1_sim_demo/` collection that walks you from a single-joint sine wave all the way to **closed-loop RL walking with overlaid arm gestures**.

### 📑 Table of Contents

- [✨ Highlights](#-highlights)
- [🗂️ Repository Layout](#%EF%B8%8F-repository-layout)
- [📦 Prerequisites](#-prerequisites)
- [🚀 Quick Start](#-quick-start)
- [🎬 Demo Catalogue](#-demo-catalogue)
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
| 🤖 **Three upstream repos in one place** | Pinned snapshots of `unitree_mujoco`, `unitree_sdk2_python`, and `unitree_rl_mjlab` so you can read SDK message layouts, MJCF assets, and RL training code without hunting across GitHub. |
| 🎮 **Five turn-key G1 demos** | From a 70-line "send a sine wave" warm-up to a 1000-line RL+gesture combo controller, every script is documented inline and runs **out of the box** against the Python MuJoCo bridge. |
| 🧠 **Real ONNX policy in the loop** | `g1_sim_rl_walk.py` and `g1_sim_rl_combo.py` load the official `unitree_rl_mjlab` velocity-tracking ONNX checkpoint and execute the **exact same observation / action pipeline** that runs on the real robot. |
| 🧷 **Sim-friendly fixes baked in** | Upstream `g1_low_level_example.py` deadlocks on `MotionSwitcherClient.CheckMode()` and assumes DDS domain 0; our scripts ship with the proven domain-1 + skip-MotionSwitcher patch and a `mode_machine` handshake. |
| 📚 **400+ pages of curated docs** | Heavily-annotated walkthroughs on MuJoCo internals, low-cmd / low-state schemas, joint indices, training-time invariants, and the policy-tolerant arm-override envelope. |
| 🐍 **One conda env, fully resolved** | `requirements.txt` is the actual `pip freeze` from a working Python 3.11 environment — no version drift, no mystery upgrades. |

---

### 🗂️ Repository Layout

```text
unitree-notes/
├── 📂 g1_sim_demo/                ← 🌟 Hand-written G1 demos (this repo's deliverable)
│   ├── g1_sim_low_level.py        ·  Sine-wave ankle/wrist swing  (≈ 200 LOC)
│   ├── g1_sim_interactive.py      ·  6 keyboard presets, 500 Hz   (≈ 350 LOC)
│   ├── g1_sim_keyboard.py         ·  Full keyboard playground     (≈ 600 LOC)
│   ├── g1_sim_rl_walk.py          ·  ONNX velocity-tracking walk  (≈ 500 LOC)
│   ├── g1_sim_rl_combo.py         ·  RL walk + arm-gesture combo  (≈ 1000 LOC)
│   └── docs/                      ·  Demo-specific Q&A and tutorials
│
├── 📂 unitree_sdk2_python/        ← 📡 Upstream SDK (DDS bindings, message IDLs)
├── 📂 unitree_mujoco/             ← 🌐 Upstream MuJoCo simulator + MJCF assets
├── 📂 unitree_rl_mjlab/           ← 🧠 Upstream RL training & sim2real deployment
│
├── 📂 docs/                       ← 📖 Project-wide notes (Chinese)
│   ├── demo_run.md                ·  Master cheat-sheet for every demo
│   ├── unitree_sdk2_python.md     ·  SDK deep-dive
│   ├── unitree_mujoco.md          ·  Simulator deep-dive
│   └── unitree_rl_mjlab.md        ·  RL framework deep-dive
│
├── 📄 requirements.txt            ← 🐍 Frozen Python 3.11 dependency snapshot
└── 📄 README.md                   ← 📍 You are here
```

---

### 📦 Prerequisites

| Layer | Requirement | Notes |
|---|---|---|
| 🖥️ **OS** | Linux (Ubuntu 22.04+) or WSL2 with WSLg | macOS / native-Windows are **not** supported by the SDK's CycloneDDS build. |
| 🐍 **Python** | 3.11 | Pinned by `mjlab` and `cyclonedds` wheels. |
| 🧪 **Conda** | [Miniforge](https://github.com/conda-forge/miniforge) recommended | A virtualenv works too, but the docs assume `conda activate unitree`. |
| 🎮 **GPU** *(optional)* | NVIDIA + CUDA 13 + driver ≥ 560 | Only required for **training**. Inference and simulation run fine on CPU. |
| 🤖 **Real robot** *(optional)* | Unitree G1 EDU on the same LAN | Replace `lo` with the actual NIC name (e.g. `enp3s0`) on every command. |

---

### 🚀 Quick Start

#### 1️⃣ Clone & create the environment

```bash
git clone https://github.com/SparkyWen/unitree-notes.git
cd unitree-notes

# create the env (Python 3.11) and install everything in one shot
conda create -n unitree python=3.11 -y
conda activate unitree
pip install -r requirements.txt

# install the SDK in editable mode so the demos can import unitree_sdk2py
pip install -e unitree_sdk2_python
```

#### 2️⃣ Configure the simulator for G1

Edit `unitree_mujoco/simulate_python/config.py`:

```python
ROBOT               = "g1"      # loads g1_29dof.xml (29 motors)
ENABLE_ELASTIC_BAND = True      # required for bipeds — keeps G1 hanging upright
USE_JOYSTICK        = 0         # set to 1 only if a wired joystick is plugged in
DOMAIN_ID           = 1         # IMPORTANT: demos assume domain 1 + interface "lo"
INTERFACE           = "lo"
```

#### 3️⃣ Smoke test (two terminals)

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

---

### 🎬 Demo Catalogue

> All demos live under `g1_sim_demo/`. Run them with the simulator already up (Terminal 1 above). Pass a real NIC name (e.g. `enp3s0`) as the **first** CLI argument to target a real G1 instead — the script will auto-switch to DDS domain 0.

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

---

### 🧱 Architecture Overview

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

---

### 📚 Documentation Index

| Doc | Scope | Language |
|---|---|:---:|
| [`docs/demo_run.md`](docs/demo_run.md) | Master cheat-sheet — every demo command in this repo, copy-pasteable. | 🇨🇳 |
| [`docs/unitree_sdk2_python.md`](docs/unitree_sdk2_python.md) | DDS topics, message IDLs, channel factory, CRC, joint indices. | 🇨🇳 |
| [`docs/unitree_mujoco.md`](docs/unitree_mujoco.md) | Simulator architecture, bridge internals, MJCF / scene authoring. | 🇨🇳 |
| [`docs/unitree_rl_mjlab.md`](docs/unitree_rl_mjlab.md) | RL framework, training pipeline, sim2real deployment. | 🇨🇳 |
| [`g1_sim_demo/docs/G1 MuJoCo SDK Bridge Demo.md`](g1_sim_demo/docs/G1%20MuJoCo%20SDK%20Bridge%20Demo.md) | Why upstream G1 low-level breaks in sim, and how this repo fixes it. | 🇨🇳 |
| [`g1_sim_demo/docs/learn-mujoco.md`](g1_sim_demo/docs/learn-mujoco.md) | First-principles MuJoCo tutorial (XML, joints, contacts, viewer). | 🇨🇳 |
| [`g1_sim_demo/docs/how to use mujoco demo and customize motions.md`](g1_sim_demo/docs/how%20to%20use%20mujoco%20demo%20and%20customize%20motions.md) | How to design new keyframe sequences. | 🇨🇳 |
| [`g1_sim_demo/docs/demo-QA1.md`](g1_sim_demo/docs/demo-QA1.md) … [`demo-QA5.md`](g1_sim_demo/docs/demo-QA5.md) | Five rounds of progressive Q&A: keyboard latency, action_scale, OOD inputs, gesture envelopes. | 🇨🇳 |

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

WSLg should set `$DISPLAY` automatically. If you SSH'd in, use `ssh -X user@host`. If it still fails, run `glxinfo | head` to confirm OpenGL is available.
</details>

<details>
<summary><b>🔴 <code>ModuleNotFoundError: unitree_sdk2py</code></b></summary>

Install the SDK in editable mode from this repo:

```bash
pip install -e unitree_sdk2_python
```
</details>

<details>
<summary><b>🔴 CRC failure / motors don't move</b></summary>

The simulator must load the G1 29-DOF scene (default when `ROBOT="g1"`), and the bridge must speak the `unitree_hg` message family — both happen automatically when `config.ROBOT == "g1"`. Re-check the config edit from step 2.
</details>

<details>
<summary><b>🔴 Real-robot run: bridge launches but joints don't respond</b></summary>

The cs47-command-center note applies: many setups hardcode `~/unitree_sdk2_python/unitree-env/...`. Either symlink this clone into that path **or** edit the launch script to point to this workspace.
</details>

---

### 🤝 Contributing

Contributions are welcome — especially:

- 🆕 **New demos** under `g1_sim_demo/` (e.g. teleoperation via `pygame`, ROS 2 bridge, MoCap retargeting).
- 📝 **Documentation translations** (English versions of the `docs/*.md` deep-dives).
- 🐛 **Bug fixes** in any of the `g1_sim_demo/` scripts.

#### Workflow

```bash
# fork → clone → branch
git checkout -b feature/my-cool-demo

# write code under g1_sim_demo/, follow the existing module-docstring pattern
# (run order, architecture overview, key map, dependencies)

# verify in sim
python g1_sim_demo/my_cool_demo.py

# commit + push + open a PR
git commit -m "feat: add <demo name>"
git push origin feature/my-cool-demo
```

> 🙅 **Please do not modify** files under `unitree_sdk2_python/`, `unitree_mujoco/`, or `unitree_rl_mjlab/` — they are kept clean for diffability against upstream. Vendor patches by overlaying or wrapping instead.

---

### 📜 License

This repository contains code under multiple licenses:

| Path | License | Source |
|---|---|---|
| `g1_sim_demo/`, `docs/`, `README.md`, `requirements.txt` | **Apache 2.0** | This repository |
| `unitree_sdk2_python/` | See [`unitree_sdk2_python/LICENSE`](unitree_sdk2_python/LICENSE) | © Unitree Robotics |
| `unitree_mujoco/`     | See [`unitree_mujoco/LICENSE`](unitree_mujoco/LICENSE) | © Unitree Robotics |
| `unitree_rl_mjlab/`   | See [`unitree_rl_mjlab/LICENCE`](unitree_rl_mjlab/LICENCE) | © Unitree Robotics |

When redistributing, retain each upstream license file and any required NOTICE.

---

### 🙏 Acknowledgements

This project would not exist without the generous open-source releases from:

- 🏢 **[Unitree Robotics](https://www.unitree.com/)** — for the SDK, the MuJoCo bridge, and the `mjlab`-based RL framework.
- 🔬 **[Google DeepMind / MuJoCo team](https://mujoco.org/)** — for the physics engine.
- 🧠 **[`rsl_rl`](https://github.com/leggedrobotics/rsl_rl)** by ETH Robotic Systems Lab — for the on-policy PPO trainer.
- ⚡ **[NVIDIA Warp](https://github.com/NVIDIA/warp)** — for the GPU-accelerated MuJoCo Warp backend used during training.

If this repo helped you, **a ⭐ on GitHub is the cheapest way to say thanks.**

---

<br/>

<a id="-简体中文"></a>

## 🇨🇳 简体中文

> 一个为 **宇树 G1 人形机器人** 量身打造的、完整的、有观点的研究/仿真/部署工作区。仓库里同时包含三份**上游参考代码快照** 和一套自研的 `g1_sim_demo/` 演示集——从最简单的"给电机发个正弦波"一路走到 **闭环 RL 行走 + 上肢手势叠加**。

### 📑 目录

- [✨ 核心亮点](#-核心亮点)
- [🗂️ 仓库结构](#%EF%B8%8F-仓库结构)
- [📦 环境依赖](#-环境依赖)
- [🚀 快速开始](#-快速开始)
- [🎬 Demo 一览](#-demo-一览)
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
| 🤖 **三份上游仓库一站到位** | 同时托管 `unitree_mujoco`、`unitree_sdk2_python`、`unitree_rl_mjlab` 三个上游仓库的固定快照——查 SDK 消息布局、MJCF 模型、RL 训练代码不用再到处翻 GitHub。 |
| 🎮 **五个开箱即用的 G1 demo** | 从 70 行的"发一段正弦波"热身脚本，到 1000 行的 RL+手势 combo 控制器，每个脚本都写满了 inline 注释，对着 Python MuJoCo 桥接器 **直接就能跑**。 |
| 🧠 **真 ONNX 策略闭环跑** | `g1_sim_rl_walk.py` 和 `g1_sim_rl_combo.py` 直接加载 `unitree_rl_mjlab` 官方的速度跟踪 ONNX checkpoint，**走的是真机部署同款 obs/action 流水线**。 |
| 🧷 **针对仿真的修复内置** | 上游 `g1_low_level_example.py` 在仿真里会卡死在 `MotionSwitcherClient.CheckMode()`，且 DDS domain 写死为 0。本仓库脚本默认走 domain 1、跳过 MotionSwitcher、并补上 `mode_machine` 握手。 |
| 📚 **400+ 页精读文档** | MuJoCo 内核、lowcmd / lowstate schema、关节索引、训练时的隐式不变量、策略可容忍的"上肢覆盖包络"——每个细节都有详细中文解释。 |
| 🐍 **一份 conda 环境，已完全锁版本** | `requirements.txt` 是真正能跑通的 Python 3.11 环境的 `pip freeze`——没有版本漂移、没有暗处升级。 |

---

### 🗂️ 仓库结构

```text
unitree-notes/
├── 📂 g1_sim_demo/                ← 🌟 自研 G1 demo（本仓库的核心交付物）
│   ├── g1_sim_low_level.py        ·  踝/腕正弦摆动            (≈ 200 行)
│   ├── g1_sim_interactive.py      ·  6 个键盘预设, 500 Hz     (≈ 350 行)
│   ├── g1_sim_keyboard.py         ·  完整键盘 playground       (≈ 600 行)
│   ├── g1_sim_rl_walk.py          ·  ONNX 速度跟踪行走         (≈ 500 行)
│   ├── g1_sim_rl_combo.py         ·  RL 行走 + 上肢手势叠加    (≈ 1000 行)
│   └── docs/                      ·  Demo 专用 Q&A 与教程
│
├── 📂 unitree_sdk2_python/        ← 📡 上游 SDK（DDS 绑定 + 消息 IDL）
├── 📂 unitree_mujoco/             ← 🌐 上游 MuJoCo 模拟器 + MJCF 资产
├── 📂 unitree_rl_mjlab/           ← 🧠 上游 RL 训练 + sim2real 部署
│
├── 📂 docs/                       ← 📖 项目级笔记（中文）
│   ├── demo_run.md                ·  全部 demo 的运行命令小抄
│   ├── unitree_sdk2_python.md     ·  SDK 深度解读
│   ├── unitree_mujoco.md          ·  模拟器深度解读
│   └── unitree_rl_mjlab.md        ·  RL 框架深度解读
│
├── 📄 requirements.txt            ← 🐍 锁定的 Python 3.11 依赖快照
└── 📄 README.md                   ← 📍 你正在看的文件
```

---

### 📦 环境依赖

| 层级 | 要求 | 备注 |
|---|---|---|
| 🖥️ **操作系统** | Linux（Ubuntu 22.04+）或 WSL2 + WSLg | macOS / 原生 Windows **不支持**——CycloneDDS 没有这两个平台的轮子。 |
| 🐍 **Python** | 3.11 | 由 `mjlab` 和 `cyclonedds` 的轮子限制。 |
| 🧪 **Conda** | 推荐 [Miniforge](https://github.com/conda-forge/miniforge) | 用 venv 也行，但所有文档都假定 `conda activate unitree`。 |
| 🎮 **GPU**（可选） | NVIDIA + CUDA 13 + 驱动 ≥ 560 | 仅在 **训练** 时需要；推理和仿真在 CPU 上完全够用。 |
| 🤖 **真机**（可选） | 同局域网下的 Unitree G1 EDU | 把命令里的 `lo` 替换成实际网卡名（例如 `enp3s0`）。 |

---

### 🚀 快速开始

#### 1️⃣ 克隆 + 创建环境

```bash
git clone https://github.com/SparkyWen/unitree-notes.git
cd unitree-notes

# 一条命令把环境装齐（Python 3.11）
conda create -n unitree python=3.11 -y
conda activate unitree
pip install -r requirements.txt

# 把 SDK 装成可编辑模式，demo 才能 import unitree_sdk2py
pip install -e unitree_sdk2_python
```

#### 2️⃣ 把模拟器切到 G1

编辑 `unitree_mujoco/simulate_python/config.py`：

```python
ROBOT               = "g1"      # 加载 g1_29dof.xml (29 个电机)
ENABLE_ELASTIC_BAND = True      # 双足必须启用——把 G1 吊在原地
USE_JOYSTICK        = 0         # 没接有线手柄时一定要置 0
DOMAIN_ID           = 1         # 重要：所有 demo 都假定 domain 1 + lo
INTERFACE           = "lo"
```

#### 3️⃣ 冒烟测试（双终端）

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

---

### 🎬 Demo 一览

> 所有 demo 都在 `g1_sim_demo/` 下。运行前请先按上面"终端 1"启动模拟器。把脚本的**第一个**命令行参数换成实际网卡名（如 `enp3s0`），脚本会自动切到 DDS domain 0 控制真机。

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

---

### 🧱 架构总览

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

---

### 📚 文档索引

| 文档 | 内容 | 语言 |
|---|---|:---:|
| [`docs/demo_run.md`](docs/demo_run.md) | 总目录小抄——把所有 demo 命令归档到一处，可直接复制粘贴。 | 🇨🇳 |
| [`docs/unitree_sdk2_python.md`](docs/unitree_sdk2_python.md) | DDS topic、消息 IDL、ChannelFactory、CRC、关节索引。 | 🇨🇳 |
| [`docs/unitree_mujoco.md`](docs/unitree_mujoco.md) | 模拟器架构、桥接器内核、MJCF / 场景制作。 | 🇨🇳 |
| [`docs/unitree_rl_mjlab.md`](docs/unitree_rl_mjlab.md) | RL 框架、训练流水线、sim2real 部署。 | 🇨🇳 |
| [`g1_sim_demo/docs/G1 MuJoCo SDK Bridge Demo.md`](g1_sim_demo/docs/G1%20MuJoCo%20SDK%20Bridge%20Demo.md) | 上游 G1 低层例子在仿真里为啥跑不通，以及本仓库怎么修。 | 🇨🇳 |
| [`g1_sim_demo/docs/learn-mujoco.md`](g1_sim_demo/docs/learn-mujoco.md) | 从零开始的 MuJoCo 教程（XML、关节、接触、viewer）。 | 🇨🇳 |
| [`g1_sim_demo/docs/how to use mujoco demo and customize motions.md`](g1_sim_demo/docs/how%20to%20use%20mujoco%20demo%20and%20customize%20motions.md) | 怎么自己设计新的关键帧序列。 | 🇨🇳 |
| [`g1_sim_demo/docs/demo-QA1.md`](g1_sim_demo/docs/demo-QA1.md) … [`demo-QA5.md`](g1_sim_demo/docs/demo-QA5.md) | 五轮渐进式 Q&A：键盘延迟、action_scale、OOD 输入、手势安全包络。 | 🇨🇳 |

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

WSLg 会自动设 `$DISPLAY`。如果是 SSH 进来的，要用 `ssh -X user@host`。还不行就 `glxinfo | head` 确认 OpenGL 是否可用。
</details>

<details>
<summary><b>🔴 <code>ModuleNotFoundError: unitree_sdk2py</code></b></summary>

从本仓库可编辑安装 SDK：

```bash
pip install -e unitree_sdk2_python
```
</details>

<details>
<summary><b>🔴 CRC 校验失败 / 电机不动</b></summary>

模拟器必须加载 G1 的 29-DOF 场景（`ROBOT="g1"` 时默认就是），桥接器必须用 `unitree_hg` 系列消息——这两条只要 `config.ROBOT == "g1"` 就会自动满足。回去再核对一次第 2 步的配置。
</details>

<details>
<summary><b>🔴 真机：bridge 起来了但关节没反应</b></summary>

很多本地工具（如 cs47-command-center）会写死 `~/unitree_sdk2_python/unitree-env/...` 这条路径。要么把本仓库 symlink 过去，要么改启动脚本指向本工作区的实际路径。
</details>

---

### 🤝 参与贡献

欢迎贡献，特别是：

- 🆕 **新 demo**（`g1_sim_demo/` 下，例如 `pygame` 遥控、ROS 2 桥、动捕重定向）。
- 📝 **文档英译**（把 `docs/*.md` 的深度解读翻译成英文）。
- 🐛 **bug 修复**（针对 `g1_sim_demo/` 下任意脚本）。

#### 流程

```bash
# fork → clone → 拉分支
git checkout -b feature/my-cool-demo

# 在 g1_sim_demo/ 下写代码，沿用现有的 module-docstring 风格
# （运行步骤 / 架构概述 / 按键映射 / 依赖）

# 在仿真里验证
python g1_sim_demo/my_cool_demo.py

# 提交 + 推送 + 开 PR
git commit -m "feat: add <demo name>"
git push origin feature/my-cool-demo
```

> 🙅 **请勿修改** `unitree_sdk2_python/`、`unitree_mujoco/`、`unitree_rl_mjlab/` 三个目录里的代码——它们要保持干净的状态以便和上游 diff。如果一定要打补丁，请用 overlay / wrapper 的方式实现。

---

### 📜 许可证

本仓库内含多种许可证：

| 路径 | 许可证 | 来源 |
|---|---|---|
| `g1_sim_demo/`、`docs/`、`README.md`、`requirements.txt` | **Apache 2.0** | 本仓库 |
| `unitree_sdk2_python/` | 见 [`unitree_sdk2_python/LICENSE`](unitree_sdk2_python/LICENSE) | © 宇树科技 |
| `unitree_mujoco/`     | 见 [`unitree_mujoco/LICENSE`](unitree_mujoco/LICENSE) | © 宇树科技 |
| `unitree_rl_mjlab/`   | 见 [`unitree_rl_mjlab/LICENCE`](unitree_rl_mjlab/LICENCE) | © 宇树科技 |

二次分发时，请保留各上游许可证文件以及对应的 NOTICE。

---

### 🙏 致谢

如果没有以下项目的开源贡献，本仓库不可能存在：

- 🏢 **[宇树科技 / Unitree Robotics](https://www.unitree.com/)** — 提供 SDK、MuJoCo 桥接器、以及基于 `mjlab` 的 RL 框架。
- 🔬 **[Google DeepMind / MuJoCo 团队](https://mujoco.org/)** — 提供物理引擎。
- 🧠 **[`rsl_rl`](https://github.com/leggedrobotics/rsl_rl)**，由 ETH Robotic Systems Lab 维护 — 提供 on-policy PPO 训练器。
- ⚡ **[NVIDIA Warp](https://github.com/NVIDIA/warp)** — 训练时使用的 GPU 加速 MuJoCo Warp 后端。

如果这个仓库对你有帮助，**给一个 ⭐ 是最便宜的鼓励方式。**

---

<div align="center">

<br/>

**Made with ☕ &nbsp;by [@SparkyWen](https://github.com/SparkyWen) — for the Unitree community.**

*"The best way to learn a robot is to make it dance — first in sim, then for real."*

<br/>

[⬆ Back to top / 回到顶部](#-unitree-notes)

</div>
