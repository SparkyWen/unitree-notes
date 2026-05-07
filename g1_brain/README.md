<div align="center">

# 🧠 g1_brain

### *Slow Brain · Fast Reflex · Safe Skill — a three-layer agent for the Unitree G1 humanoid*

*面向宇树 G1 人形机器人的「慢脑 + 快反射 + 安全技能」三层智能体*

<br/>

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![MuJoCo](https://img.shields.io/badge/MuJoCo-3.5.0-1A73E8?style=for-the-badge&logo=googlecolab&logoColor=white)](https://mujoco.org/)
[![OpenAI Realtime](https://img.shields.io/badge/OpenAI-Realtime_API-412991?style=for-the-badge&logo=openai&logoColor=white)](https://platform.openai.com/docs/guides/realtime)
[![YOLO](https://img.shields.io/badge/YOLO-11-00FFFF?style=for-the-badge&logo=ultralytics&logoColor=black)](https://docs.ultralytics.com/)
[![MediaPipe](https://img.shields.io/badge/MediaPipe-Pose-00BFA5?style=for-the-badge&logo=google&logoColor=white)](https://developers.google.com/mediapipe)

[![Status](https://img.shields.io/badge/status-active-success.svg?style=flat-square)]()
[![Conda](https://img.shields.io/badge/Env-agi-44A833?style=flat-square&logo=anaconda&logoColor=white)](../README.md#-two-conda-environments)
[![Tests](https://img.shields.io/badge/tests-pytest-0A9EDC?style=flat-square&logo=pytest&logoColor=white)](tests/)
[![Tools](https://img.shields.io/badge/LLM_tools-16-purple?style=flat-square)](#-skill-catalog)
[![Safety](https://img.shields.io/badge/safety_rules-12-FF6B35?style=flat-square)](#-safety--12-rules--7-state-fsm)
[![License](https://img.shields.io/badge/license-Apache_2.0-blue.svg?style=flat-square)](../README.md#-license)

<br/>

**📂 Workspace:** [`unitree-notes`](../README.md) ｜ **📐 Full design:** [`docs/g1_plan.md`](../docs/g1_plan.md) ｜ **🏗️ Architecture:** [`docs/architecture.md`](docs/architecture.md) ｜ **🚀 Run guide:** [`docs/how_to_run.md`](docs/how_to_run.md)

</div>

<br/>

---

## 📑 Table of Contents

- [✨ What is `g1_brain`?](#-what-is-g1_brain)
- [🌟 Highlights](#-highlights)
- [🧱 Architecture at a Glance](#-architecture-at-a-glance)
- [🗂️ Repository Layout](#%EF%B8%8F-repository-layout)
- [📦 Install](#-install)
- [🚀 Run (4 terminals)](#-run-4-terminals)
- [🎚️ Run Modes & Flags](#%EF%B8%8F-run-modes--flags)
- [🛠️ Skill Catalog](#%EF%B8%8F-skill-catalog)
- [🛡️ Safety — 11 Rules + 7-state FSM](#%EF%B8%8F-safety--11-rules--7-state-fsm)
- [👁️ Perception Pipeline](#%EF%B8%8F-perception-pipeline)
- [💃 Mock Imitation](#-mock-imitation)
- [⚙️ Configuration](#%EF%B8%8F-configuration)
- [🐞 Debug Entry Points](#-debug-entry-points)
- [✅ Tests](#-tests)
- [📚 Documentation](#-documentation)
- [🤖 Path to Real Robot](#-path-to-real-robot)
- [🔧 Troubleshooting](#-troubleshooting)
- [🔗 Related Projects](#-related-projects)
- [📜 License](#-license)

---

## ✨ What is `g1_brain`?

> **A new top-level package that *imports* (and never modifies) [`va-demo/`](../va-demo/) and [`g1_sim_demo/`](../g1_sim_demo/), and adds three layers on top: Perception, Safety, and Skills.**

The G1 needs three time-scales of cognition simultaneously, and the OpenAI Realtime API alone can't hit all of them. `g1_brain` separates them cleanly:

| Layer | Rate | Owner | Job |
|---|---|---|---|
| 🧠 **Slow Brain** | 0.2–2 Hz | OpenAI Realtime + GPT-5.5 Vision | Plan, talk, decide which skill to call |
| 🛡️ **Safe Skill** | per-call | `SafetySupervisor` + `SkillServer` | Validate, clamp, route, abort |
| ⚡ **Fast Reflex** | 5–30 Hz | Cameras + YOLO + MediaPipe + depth | Build a `SceneState` the safety layer reads |

The LLM never touches motors. Every command flows through `SafetySupervisor.validate()` → `SkillServer.execute()` → existing controllers. **No new physics, no new motors — just a cognitive shell around the proven `g1_sim_rl_combo` stack.**

---

## 🌟 Highlights

| | |
|---|---|
| 🪆 **Builds on top of `va-demo` + `g1_sim_demo`** | Reuses the wake-word ("Hi Sparky"), VAD, conversation FSM, ComboController, keyframe library — adds cognition rather than rewriting infrastructure. |
| 👀 **Dual-camera perception** | USB cam (laptop / robot teleimager → MediaPipe-Pose) + first-person MuJoCo head cam (synthesized onto `torso_link` via `MjSpec`, EGL off-screen). |
| 🎯 **YOLO11 + MediaPipe-Pose + depth, fused** | Outputs a single thread-safe `SceneState` with `clear_path`, `nearest_obstacle_m`, `nearest_person_m`, gestures, and a tiny `summary_for_llm()`. |
| 🛡️ **12 safety rules + 7-state FSM** | Whitelist · FSM gating · run_mode · 4 watchdogs · pose check · param clamp · scene checks · E-stop · GPT-5.5 vision risk gate (Rule 12, spec [`docs/g1_v1.md`](docs/g1_v1.md)). Applied to *every* tool call. |
| 🚨 **Independent E-stop process** | `safety/estop_listener.py` runs separately, listens for **ESC**, publishes 30 zero-torque frames straight to DDS even if the agent deadlocks. |
| 🧰 **~16 LLM-callable tools** | `walk` · `turn` · `gesture` · `static_pose` · `look_at` · `approach` · `mock_imitate` · `say` · `describe_scene` · `query_scene_state` · `stop` · `release_arms` · plus 3 real-robot-only stubs. |
| 💃 **Mock imitation (Phase 5)** | User waves → MediaPipe classifies the gesture → SafetySupervisor checks distance → robot waves back. LLM-driven *and* auto-trigger paths both supported. |
| 🎚️ **Three run modes** | `observe` (no motion) · `confirm` (y/N gate) · `active` (autonomous). Plus `--vision-only` to drop DDS entirely for laptop-only dev. |
| 🩺 **4 self-contained debug entries** | `perception_debug` · `safety_debug` · `skill_debug` · `estop_test` — each runnable as `python -m`, each tests one layer in isolation. |
| 🧪 **12 pytest files, no hardware required** | OpenAI / DDS / cameras are all stubbed; tests run on any laptop in seconds. |

---

## 🧱 Architecture at a Glance

```
┌────────────────────────────────────────────────────────────────────┐
│                       USER (voice / keyboard)                      │
└────────────────────────────────────────────────────────────────────┘
                                ↕
┌────────────────────────────────────────────────────────────────────┐
│  🧠 SLOW BRAIN  (g1_brain/brain/)                  0.2 - 2 Hz      │
│  - OpenAI Realtime (gpt-realtime, reused from va-demo)             │
│  - GPT-5.5 Vision via describe_scene tool                          │
│  - tool calls → high-level intent / parameterized skill            │
└────────────────────────────────────────────────────────────────────┘
                                ↕            (intent JSON)
┌────────────────────────────────────────────────────────────────────┐
│  🛡️ SAFE SKILL  (g1_brain/safety/ + g1_brain/skills/)              │
│  - SafetySupervisor: 12 rules (whitelist, FSM, run-mode, watchdog, │
│    pose, scene, E-stop, GPT-5.5 vision risk gate)                  │
│  - SkillServer: ~16 skills routed to ComboController / Keyframe    │
└────────────────────────────────────────────────────────────────────┘
                                ↕            (skill call)
┌────────────────────────────────────────────────────────────────────┐
│  ⚡ FAST REFLEX  (g1_brain/perception/ + scene_state/)    5-30 Hz  │
│  - Dual cameras (USB + MuJoCo head), YOLO11, MediaPipe-Pose, depth │
│  - Fused into SceneState (clear_path / nearest_obstacle / ...)     │
│  - Safety reads SceneState before every motion skill               │
└────────────────────────────────────────────────────────────────────┘
                                ↕            (lowcmd / lowstate)
┌────────────────────────────────────────────────────────────────────┐
│  🦿 RUNTIME  (reuses g1_sim_demo)         50 / 500 / 1000 Hz       │
│  - ComboController (RL @ 50 Hz + arm-overlay envelope)             │
│  - Keyframe player (g1_sim_keyboard's static poses)                │
│  - Real-robot swap: LocoClient + G1ArmActionClient                 │
└────────────────────────────────────────────────────────────────────┘
                                ↕     DDS (domain 1 = sim, 0 = real)
┌────────────────────────────────────────────────────────────────────┐
│  unitree_mujoco simulate_python   <or>   real G1 PC2               │
└────────────────────────────────────────────────────────────────────┘
```

> 📐 **Key invariant** — every downward command flows through `SafetySupervisor.validate()`. The LLM never sees lowstate / motor data and can never emit a joint angle.
>
> Read [`docs/architecture.md`](docs/architecture.md) for the full ~500-line summary, or [`../docs/g1_plan.md`](../docs/g1_plan.md) for the 1500+-line design.

---

## 🗂️ Repository Layout

```
g1_brain/
├── 📂 g1_brain/              ← The package
│   ├── 👁️ perception/         ·  Cameras · YOLO · MediaPipe · depth · derivations
│   │   ├── cameras.py        ·  CameraHub: USB + head-cam orchestrator
│   │   ├── usb_camera.py     ·  teleimager / cv2 backends for the user-facing cam
│   │   ├── mujoco_head_cam.py·  EGL off-screen first-person head cam (MjSpec-attached)
│   │   ├── object_detector.py·  YOLO11 wrapper (head + USB)
│   │   ├── pose_detector.py  ·  MediaPipe-Pose 33-landmark wrapper (USB)
│   │   ├── depth.py          ·  MuJoCo native depth + (optional) DepthAnythingV2
│   │   ├── derivations.py    ·  classify_gesture · clear_path · ground_constraint
│   │   └── runner.py         ·  background loops fusing into SceneStateBus
│   ├── 🧬 scene_state/        ·  Shared SceneState/RobotState dataclasses
│   │   ├── types.py          ·  SceneState · HumanPose · Detection · Ground · Gesture
│   │   └── fusion.py         ·  Thread-safe RLock-protected bus, snapshot()
│   ├── 🛡️ safety/             ·  FSM + SafetySupervisor + watchdogs + E-stop
│   │   ├── state_machine.py  ·  7-state FSM (BOOT…STANDING…ENGAGED…ACTING…E-STOP…)
│   │   ├── supervisor.py     ·  validate() — the 12 rules in code
│   │   ├── vision_risk_gate.py · Rule 12: GPT-5.5 head-cam SAFE/RISK reviewer
│   │   ├── pose_check.py     ·  projected-gravity-z tipping detector
│   │   ├── watchdogs.py      ·  lowstate / head_frame / usb_frame / pose @ 20 Hz
│   │   ├── estop_client.py   ·  /tmp flag reader (in-process)
│   │   └── estop_listener.py ·  separate process: ESC key → flag + zero-torque DDS
│   ├── 🛠️ skills/             ·  SkillServer + tool schemas + keyframe extras
│   │   ├── skill_server.py   ·  execute(tool, args) — dispatch + scene re-checks
│   │   ├── tool_schemas.py   ·  OpenAI function schemas (~16 tools)
│   │   ├── keyframe_extras.py·  hug + salute keyframes (extends g1_sim_keyboard)
│   │   ├── compound_skills.py·  approach / look_at / mock_imitate composition
│   │   └── real_robot_adapters.py · stubs that route to LocoClient on real
│   ├── 🧠 brain/              ·  Realtime agent (extends va-demo) + scene-aware prompt
│   │   ├── realtime_agent.py ·  BrainRealtimeAgent — replaces 4 things in va-demo
│   │   ├── prompts.py        ·  REALTIME_SYSTEM_PROMPT_BRAIN (+ vision-only variant)
│   │   └── scene_summary.py  ·  scene → short prompt-friendly text
│   ├── 💃 mock_imitation/     ·  User gesture → robot gesture mirror (Phase 5)
│   │   ├── gesture_to_skill.py · MIRRORABLE map: wave_right / wave_left / hands_up / t_pose
│   │   └── auto_trigger.py   ·  ≥1 s of high-conf gesture → inject prompt event
│   └── 🚀 apps/               ·  agent_main + 4 debug entry points
│       ├── agent_main.py     ·  THE entry point — wires every layer together
│       ├── perception_debug.py · "does the eye work?"
│       ├── safety_debug.py   ·  "does my safety config make sense?"
│       ├── skill_debug.py    ·  "does the body work?"
│       └── estop_test.py     ·  "does the kill switch work?"
│
├── ⚙️  configs/g1_brain.yaml  ·  Single source of truth — robot / cameras / perception /
│                                safety / openai / audio / wakeword / mock_imitation
├── 📚 docs/                  ·  Architecture · how_to_run · extending_skills · phase fixes
│   ├── architecture.md       ·  ~500-line layered architecture writeup
│   ├── how_to_run.md         ·  Operator guide: prereqs · 4 terminals · 4 debug entries
│   ├── extending_skills.md   ·  4 places to touch when adding a tool
│   ├── g1_brain_QA1.md       ·  Q&A: gotchas around how_to_run.md
│   ├── g1-fix-phase1.md      ·  Phase-1 fix log (post-boot pose oscillation)
│   ├── g1-fix-phase2.md      ·  Phase-2 fix log (RL ramp + watchdog grace)
│   ├── g1-fix-phase3.md      ·  Phase-3 fix log (head-cam EGL threading)
│   └── g1-fix-phase5.md      ·  Phase-5 fix log (USB watchdog locking gestures)
├── 🧪 tests/                 ·  pytest suite — 12 files, no hardware required
└── 📦 pyproject.toml          ·  ultralytics · mediapipe · openai · pyyaml · pynput · …
```

> 🧷 The package only **imports** code under [`../va-demo/`](../va-demo/) and [`../g1_sim_demo/`](../g1_sim_demo/) — they remain untouched. Editing `g1_brain/` is safe; editing those is not.

---

## 📦 Install

This package lives inside the [`agi`](../README.md#-two-conda-environments) conda env (Miniforge), which already has `unitree_sdk2py`, MuJoCo, mediapipe, ultralytics, openai, sounddevice, and webrtcvad. From a fresh checkout:

```bash
conda activate agi
cd ~/unitree/unitree-notes/g1_brain
pip install -e .
```

| What | Where | Size |
|---|---|---|
| 🟦 YOLO11s | `~/.config/Ultralytics/yolo11s.pt` | ~22 MB |
| 🟢 MediaPipe BlazePose | bundled in the wheel | — |
| 🟣 DepthAnythingV2-Small *(off by default)* | `~/.cache/huggingface/hub/` | ~100 MB |

> 🔑 You'll also need `OPENAI_API_KEY` exported before running the agent — Realtime + Vision + TTS are cloud-only in v1. Override individual models via `OPENAI_REALTIME_MODEL`, `OPENAI_VISION_MODEL`, `OPENAI_TTS_MODEL`.

---

## 🚀 Run (4 terminals)

> 🔍 Detailed prereqs, gotchas, WSL2 notes, and switch-to-real-robot steps live in [`docs/how_to_run.md`](docs/how_to_run.md). The block below is the speed-run.

```bash
# ── 🖥️ Terminal 1 — MuJoCo physics + viewer ─────────────────────────
conda activate unitree
export MUJOCO_GL=glfw
cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
python unitree_mujoco.py
#   G1 lands on the floor immediately (ELASTIC_BAND_INIT_LENGTH=2.0
#   leaves the band slack at standing height); press '9' to toggle the
#   band off entirely, '7' / '8' to nudge length by ±0.1 m.

# ── 📷 Terminal 2 — USB camera service ──────────────────────────────
conda activate unitree
cd ~/unitree/unitree-notes/teleimager
python -m teleimager.image_server

# ── 🚨 Terminal 3 — E-stop listener (independent process) ───────────
conda activate agi
python -m g1_brain.safety.estop_listener
#   Press ESC at any time to engage. Even if the agent deadlocks,
#   this process publishes 30 frames of zero-torque lowcmd to DDS.

# ── 🤖 Terminal 4 — agent ───────────────────────────────────────────
conda activate agi
export OPENAI_API_KEY=sk-...
python -m g1_brain.apps.agent_main --mode confirm
```

> ⚡ You can omit Terminal 3 if you only want soft safety. You can also drop Terminal 1 + 2 if you pass `--vision-only` to Terminal 4 (DDS / MuJoCo / USB cam all skipped).

---

## 🎚️ Run Modes & Flags

| Flag | Effect |
|---|---|
| `--mode observe` | All motion tools rejected. `say` / `describe_scene` / `query_scene_state` still work. Use during config tuning. |
| `--mode confirm` *(default)* | Each motion tool prompts y/N in Terminal 4 before executing. **Recommended for keyboard debugging only** — blocks voice control mid-conversation. |
| `--mode active` | Motion executes immediately within safety bounds. Use when you trust the LLM and the scene. |
| `--vision-only` | Drops every motion tool from the schema, skips DDS init, MuJoCo not required — laptop-only dev. Mirrors `va-demo`'s flag. |
| `--no-skills` | Like `--vision-only` but keeps the schema; rejects motion at runtime. |
| `--no-realtime` | Keep audio / camera / safety alive without a Realtime session — useful when offline. |

---

## 🛠️ Skill Catalog

> 📂 Schemas: [`g1_brain/skills/tool_schemas.py`](g1_brain/skills/tool_schemas.py) · Dispatcher: [`g1_brain/skills/skill_server.py`](g1_brain/skills/skill_server.py) · Adding a new one: [`docs/extending_skills.md`](docs/extending_skills.md)

### 🗣️ I/O & metadata (no motion)

| Tool | Purpose |
|---|---|
| `say(text)` | Short canned TTS reply (≤ 200 chars). Realtime audio is preferred for conversational content. |
| `describe_scene(question?, detail?)` | Snapshot head cam → GPT-5.5 Vision → text answer. The robot's primary "look at the world" verb. |
| `query_scene_state()` | Returns the latest `SceneState.summary_for_llm()` — counts, distances, `clear_path`, gestures. **No camera call**, near-zero latency. |
| `stop()` | Velocity → 0, releases arm overlay. Always allowed (even under E-stop). |
| `release_arms()` | Hand the upper body back to the locomotion policy. |
| `ask_human(question)` | Voice prompt to the user; default-routed to `say` in v1. |

### 🦿 Motion (gated by 12 safety rules + scene re-check)

| Tool | Args | Notes |
|---|---|---|
| `walk` | `vx`, `vy`, `wz`, `duration_s` | Re-reads `SceneState` every 0.2 s; aborts if `clear_path` flips false. Bounds: `vx≤0.20`, `vy≤0.10`, `wz≤0.30`, `duration≤1.0 s`. |
| `turn` | `yaw_deg` | Maps to `walk(wz=…, duration_s=…)` internally. |
| `gesture` | `name ∈ {wave_right · wave_left · hands_up · t_pose · salute · clap · guard · punch_combo · hug}` | Arm-overlay only; needs `nearest_person_m > 0.5`. |
| `static_pose` | `name ∈ {salute · hug}` | Hold-then-release; uses `keyframe_extras`. The other 7 keyframes overlap with `gesture`. |
| `look_at` | `target ∈ {person · ahead · left · right · ground}` | Symbolic yaw → delegates to `turn`. |
| `approach` | `target_class`, `target_distance_m` | L1 compound: walk loop with scene re-checks until target is reached. |
| `mock_imitate` | `gesture ∈ MIRRORABLE` | Validated against `wave_right / wave_left / hands_up / t_pose`; routes to `gesture()` after distance check. |

### 🤖 Real-robot only (rejected in sim)

| Tool | Routes to |
|---|---|
| `loco_high` | `LocoClient` high-level locomotion |
| `arm_action_high` | `G1ArmActionClient` predefined arms |
| `audio_tts_robot` | On-robot `AudioClient` TTS |

> 🧷 The supervisor rejects unknown tools with `unknown_tool`, real-only tools in sim with `sim_only`, and motion in observe mode with `observe_mode`.

---

## 🛡️ Safety — 11 Rules + 7-state FSM

### State machine

```
BOOT  ─►  STANDING  ─►  ENGAGED  ─►  ACTING  ─►  STANDING  ─►  …
            ▲                                       │
            └────── RECOVERING ─────────────────────┤
                          ▲                         ▼
                          └──────── EMERGENCY_STOP ◄┴── FAULT
```

Defined in [`g1_brain/safety/state_machine.py`](g1_brain/safety/state_machine.py). Recovery from `EMERGENCY_STOP` is automatic if all motion-blocking watchdogs stay clear for `recovery_hold_s` (default **5 s**), routed via `RECOVERING → STANDING`. `FAULT` is a manual sink.

### The 12 rules — applied in order, every tool call

| # | Rule | What it checks |
|--:|---|---|
| 1 | 📋 **Whitelist** | `tool ∈ ALLOWED_TOOLS`. |
| 2 | 🚦 **FSM gating** | Current state allows this tool (motion vs no-motion). |
| 3 | 🎚️ **run_mode** | `observe` blocks all motion; `confirm` prompts y/N. |
| 4 | ⏱️ **lowstate watchdog** | `lowstate_age < 0.5 s` (skipped during `boot_grace_s`). |
| 5 | 📷 **head-cam watchdog** | `head_frame_age < 2.0 s` for `walk` / `approach`. |
| 6 | 🧠 **RL policy active** | ComboController has finished its boot ramp. |
| 7 | 🪂 **Pose check** | Projected gravity z ≤ `-0.85`; tipping → `EMERGENCY_STOP`. |
| 8 | ✂️ **Parameter clamp** | `vx`/`vy`/`wz`/`duration_s` clipped to safe envelope. |
| 9 | 🛤️ **Scene check (walk)** | `clear_path=True`, `nearest_obstacle_m > 0.6`, `nearest_person_m > 0.8`. |
| 10 | 👥 **Scene check (gesture)** | `nearest_person_m > 0.5`. |
| 11 | 🚨 **E-stop flag** | `EstopClient.is_engaged()` rejects everything except `say` / `stop` / `describe_scene` / `query_scene_state`. |
| 12 | 👁️ **Vision risk gate** | GPT-5.5 reviews the head-cam JPEG + rendered action sentence. SAFE → auto-execute regardless of run_mode; RISK → fall through to terminal y/N with the GPT reason printed inline. `say` / `stop` / `release_arms` bypass to SAFE; backward `walk` (vx<0) bypasses to RISK. Frame-fail / timeout / api_error / parse-fail all return RISK. Disable via `safety.vision_gate.enabled: false`. Spec: [`docs/g1_v1.md`](docs/g1_v1.md). |

> 🧷 Source of truth: [`g1_brain/safety/supervisor.py::validate()`](g1_brain/safety/supervisor.py) and [`g1_brain/safety/vision_risk_gate.py`](g1_brain/safety/vision_risk_gate.py). Rule 11 is hoisted earlier in code so user-facing prompts also short-circuit. Adding a new rule? Mirror the pattern in [`tests/test_safety_supervisor.py`](tests/test_safety_supervisor.py).

### 🚨 The independent E-stop

Separate process — [`safety/estop_listener.py`](g1_brain/safety/estop_listener.py):

1. Listens for **ESC** via `pynput` (configurable in `safety.estop.keys`).
2. Touches `/tmp/g1_brain_estop` (the agent's `EstopClient` polls this 50 Hz).
3. Publishes 30 frames of zero-torque `lowcmd` straight to DDS — even if the agent deadlocks.
4. Verify the round-trip with `python -m g1_brain.apps.estop_test`.

---

## 👁️ Perception Pipeline

```
USB cam (teleimager / cv2)            MuJoCo head cam (EGL, off-screen)
        │                                       │
        ▼                                       ▼
 MediaPipe-Pose 33 lm           YOLO11 (head + USB)         MuJoCo native depth
        │                          │                          │
        ▼                          ▼                          ▼
   classify_gesture          Detection list              GroundConstraint
   (wave / hands_up / …)                                 (clear_path / nearest_obstacle_m)
        │                          │                          │
        └──────────────────► SceneStateBus ◄──────────────────┘
                              (RLock + snapshot)
                                    │
                                    ▼
                       Safety reads · LLM reads via query_scene_state
```

> 📷 **Two cameras, two completely different jobs.**
>
> - **head** — robot's first-person view. Drives `describe_scene`, ground constraint, head-stream YOLO. Always enable.
> - **usb** — user-facing. Feeds MediaPipe so the agent can spot user gestures. Optional (set `cameras.usb.enabled: false` to skip without losing walking / gestures / scene description).
>
> See [`docs/architecture.md` §9.1](docs/architecture.md) for why the head cam is constructed *after* DDS init and why its EGL renderers are built inside the worker thread (fixes `EGL_BAD_ACCESS`).

---

## 💃 Mock Imitation

Phase 5 of the design — *"user waves → robot waves back."*

```
USB Cam ─► PoseDetector ─► classify_gesture ─► SceneStateBus
                                                     │
                          ┌──────────────────────────┴──────────────────────────┐
                          ▼                                                     ▼
                (a) LLM-driven                                          (b) auto-trigger
        describe_scene sees user_pose,                          GestureAutoTrigger watches for
        LLM may call mock_imitate(name)                         ≥1 s of high-conf gesture and
                                                                injects a perception event into
                                                                BrainRealtimeAgent
                          │                                                     │
                          └──────────────────► SafetySupervisor ◄───────────────┘
                                                     │
                                                     ▼
                          mock_imitate validates name ∈ MIRRORABLE,
                          maps to gesture() and goes through the same 12 rules
```

Mirrorable set: `wave_right · wave_left · hands_up · t_pose`. Configurable under `mock_imitation.mirrorable` in [`configs/g1_brain.yaml`](configs/g1_brain.yaml).

---

## ⚙️ Configuration

Single source of truth: [`configs/g1_brain.yaml`](configs/g1_brain.yaml).

| Section | Key knobs |
|---|---|
| 🔌 `mode` | `sim` / `real` — flips real-only tools and adapter routing. |
| 🎚️ `run_mode` | `observe` / `confirm` / `active`. |
| 🤖 `robot` | `domain_id` (1 = sim · 0 = real), `interface`, `mjcf_path`. |
| 📷 `cameras.usb` | `enabled`, `source: teleimager / cv2`, `teleimager_host`, `cv2_index`, `poll_hz`. |
| 📹 `cameras.head` | `attach_body`, `attach_pos`, `attach_xyaxes`, `attach_fovy` (synthesized onto `torso_link` by default). |
| 👁️ `perception` | YOLO weights + conf, MediaPipe gesture persistence, depth backend, ground-constraint cone. |
| 🛡️ `safety` | `walk` bounds · `gesture` concurrency · `scene` distances · `pose.gravity_z_min` · `watchdog` ages + grace + recovery hold · `estop` keys. |
| 🤖 `openai` | `realtime_model` · `vision_model` · `tts_model` + voices. |
| 🎤 `audio` / `wakeword` / `utterance` / `conversation` | Reused from `va-demo` — wake phrases ("hi sparky", "嗨 sparky"), VAD aggressiveness, listening windows. |
| 💃 `mock_imitation` | `enabled`, `auto_suggest_high_conf`, `auto_suggest_persist_s`, `mirrorable`. |
| 📜 `logging` | Level + log dir + rotate size. |

> 💡 The full file is heavily commented — read it once before tuning.

---

## 🐞 Debug Entry Points

Each is `python -m g1_brain.apps.<name>` and tests one layer in isolation. Full descriptions in [`docs/how_to_run.md` §3](docs/how_to_run.md).

| Entry | Question it answers | Hardware needed |
|---|---|---|
| 👁️ `perception_debug` *(`--show` for cv2 windows)* | Does the eye work? Are detections firing? Frame-age fresh? | USB cam ± MuJoCo |
| 🛡️ `safety_debug` *(`--scenarios path.json`)* | Does my safety config make sense? — runs scripted (tool, args, expected) tests against a fully-mocked supervisor. | None |
| 🦿 `skill_debug` | Does the body work? — number keys 1–9 invoke individual skills end-to-end. | MuJoCo |
| 🚨 `estop_test` | Does the kill switch work? — times engage / poll / release. | None |

---

## ✅ Tests

```bash
cd ~/unitree/unitree-notes/g1_brain
pytest tests/ -v
```

OpenAI / DDS / cameras are stubbed; the suite runs on any laptop in a few seconds.

| File | What it covers |
|---|---|
| [`test_apps_smoke.py`](tests/test_apps_smoke.py) | All 4 debug entry points + `agent_main` import without hardware. |
| [`test_brain_prompts.py`](tests/test_brain_prompts.py) | Prompt does/doesn't mention motion verbs in vision-only. |
| [`test_estop_flow.py`](tests/test_estop_flow.py) | Touch flag → all motion rejected, `say` still allowed. |
| [`test_mock_imitation.py`](tests/test_mock_imitation.py) | Auto-trigger threshold, mirrorable set, distance gate. |
| [`test_perception_derivations.py`](tests/test_perception_derivations.py) | `classify_gesture` · `clear_path` · `summary_for_llm`. |
| [`test_safety_supervisor.py`](tests/test_safety_supervisor.py) | All 12 rules — golden cases per rule (incl. vision-gate integration). |
| [`test_vision_risk_gate.py`](tests/test_vision_risk_gate.py) | Rule 12: bypass paths, frame health, GPT-5.5 SAFE/RISK/parse_fail/timeout/api_error. |
| [`test_scene_state_bus.py`](tests/test_scene_state_bus.py) | Lock semantics, snapshot immutability, frame-age helpers. |
| [`test_skill_server.py`](tests/test_skill_server.py) | Each `_skill_*` end-to-end on stubs (incl. scene re-check). |
| [`test_state_machine.py`](tests/test_state_machine.py) | FSM transitions, RECOVERING hold, FAULT sink. |
| [`test_tool_schemas.py`](tests/test_tool_schemas.py) | OpenAI Realtime schema validity, enum coverage. |
| [`test_vertical_slice.py`](tests/test_vertical_slice.py) | Brain → Safety → Skill → Scene round-trip on stubs. |
| [`test_watchdogs.py`](tests/test_watchdogs.py) | Watchdog flags + boot-grace + recovery-hold semantics. |

---

## 📚 Documentation

### 🧠 g1_brain-local

| Doc | Lines | Scope |
|---|--:|---|
| [`docs/architecture.md`](docs/architecture.md) | ~330 | The cliffs-notes version of the design — 3 layers, frequency table, worked example, FSM, perception, process model. |
| [`docs/how_to_run.md`](docs/how_to_run.md) | ~390 | Operator guide — prereqs, 4-terminal startup, 4 debug entries, run modes, common errors, sim → real switch, WSL2 specifics. |
| [`docs/extending_skills.md`](docs/extending_skills.md) | ~190 | The 4 places to touch when adding a new tool, plus a checklist. |
| [`docs/g1_brain_QA1.md`](docs/g1_brain_QA1.md) | ~430 | Q&A round 1 — gotchas around `how_to_run.md`. |
| [`docs/g1-fix-phase1.md`](docs/g1-fix-phase1.md) | ~160 | Fix log: post-boot pose oscillation. |
| [`docs/g1-fix-phase2.md`](docs/g1-fix-phase2.md) | ~340 | Fix log: RL ramp + watchdog grace + recovery hold. |
| [`docs/g1-fix-phase3.md`](docs/g1-fix-phase3.md) | ~250 | Fix log: head-cam EGL threading + DDS subscription order. |
| [`docs/g1-fix-phase5.md`](docs/g1-fix-phase5.md) | ~570 | Fix log: USB watchdog locking gestures even when usb cam disabled. |

### 🌍 Cross-cutting (in workspace)

| Doc | Scope |
|---|---|
| [`../docs/g1_plan.md`](../docs/g1_plan.md) | The full 1500+-line design that motivated this package. |
| [`../docs/vlm_audio_mock_deep.md`](../docs/vlm_audio_mock_deep.md) | Architecture-level research notes (Slow Brain / Fast Reflex / Safe Skill primer). |
| [`../va-demo/docs/video-design.md`](../va-demo/docs/video-design.md) | Vision pipeline reused under the hood. |
| [`../va-demo/docs/audio-awake.md`](../va-demo/docs/audio-awake.md) | Wake-word + state-machine design also reused. |
| [`../README.md`](../README.md) | Workspace top-level README. |

---

## 🤖 Path to Real Robot

The architecture leaves slots for this; the swap is mostly configuration. Highlights — full checklist in [`docs/how_to_run.md` §6](docs/how_to_run.md#6-switching-from-sim-to-real-robot) and [`../docs/g1_plan.md` §8.3](../docs/g1_plan.md):

| Sim → Real | Change |
|---|---|
| 🔌 `mode` | `sim` → `real`. Safety stops rejecting `loco_high` / `arm_action_high` / `audio_tts_robot`; SkillServer routes them to `LocoClient` / `G1ArmActionClient` / `AudioClient`. |
| 📷 `cameras.usb` | Keep `source: teleimager`; change `teleimager_host` from `127.0.0.1` to the robot's IP. |
| 📹 `cameras.head` | Either disable (rely on the onboard depth/RGB through teleimager) **or** plug a `RealSenseCamera` adapter into `CameraHub._build_head` exposing the same interface (`latest_bgr / latest_depth_meters / frame_age_seconds / hfov_deg / vfov_deg`). |
| 🚨 `safety.estop` | Keep the file-flag; *additionally* bind a real hardware E-stop button to write the same flag. |
| 🦿 `safety.walk` | Do **not** loosen `vx_max` until you've run a 30-min supervised real-robot loop without incident. |

> ⚠️ Always keep the **physical E-stop within reach** when running on the real G1.

---

## 🔧 Troubleshooting

<details>
<summary><b>🔴 <code>lowstate_age</code> keeps growing / DDS doesn't connect</b></summary>

- MuJoCo (Terminal 1) isn't running yet → start it first.
- DDS domain mismatch — `cfg.robot.domain_id` must match `unitree_mujoco.py`'s domain (sim defaults to **1**).
- `interface: lo` not present → set to your loopback alias (Linux `lo`, macOS `lo0`).

Full mapping: [`docs/how_to_run.md` §5.1](docs/how_to_run.md).
</details>

<details>
<summary><b>🔴 Head cam: <code>X Error: BadAccess … X_GLXMakeCurrent</code> or empty/sky-only frames</b></summary>

The agent's head cam renders **off-screen only** and `g1_brain.perception.mujoco_head_cam` sets `MUJOCO_GL=egl` at import time — you should not need to set it. If you previously exported `MUJOCO_GL=glfw`, **unset it** before launching `agent_main`.

If the frame is sky-only, confirm `ELASTIC_BAND_INIT_LENGTH=2.0` (newer simulator default) — older `0.0` suspends the robot above the floor and the head sees only the skybox.

Full mapping: [`docs/how_to_run.md` §5.2 / §5.7](docs/how_to_run.md).
</details>

<details>
<summary><b>🔴 ComboController: <code>policy not active after 30 s; continuing anyway</code></b></summary>

- MuJoCo wasn't ready when DDS init ran → restart `agent_main`.
- Simulator on the wrong domain (see above).
- The boot ramp aborted because lowstate stopped midway → check Terminal 1 for an error.

Full mapping: [`docs/how_to_run.md` §5.6](docs/how_to_run.md).
</details>

<details>
<summary><b>🔴 Watchdog trip during dialog</b></summary>

- `head_frame` watchdog → MuJoCo dropped to <2 FPS due to GPU pressure; close other GPU apps.
- `lowstate` watchdog → ComboController stopped getting state. Check Terminal 1.
- `usb_frame` watchdog → teleimager stopped publishing or webcam unplugged. The supervisor only blocks gestures that *need* the user-facing camera; pose-only blocking was loosened in [`docs/g1-fix-phase5.md`](docs/g1-fix-phase5.md).

Full mapping: [`docs/how_to_run.md` §5.5](docs/how_to_run.md).
</details>

<details>
<summary><b>🔴 OpenAI 401 / Realtime websocket errors</b></summary>

- `export OPENAI_API_KEY=sk-...` and re-run.
- Realtime requires beta access on your account.
- For local dev without internet, `--no-realtime` keeps mic / camera / safety alive without an LLM.

Full mapping: [`docs/how_to_run.md` §5.4](docs/how_to_run.md).
</details>

<details>
<summary><b>🔴 CUDA out-of-memory on the GPU</b></summary>

In order:
- Set `perception.yolo.weights: yolo11n.pt` (5 M params instead of 22 M).
- Disable mono depth: `perception.mono_depth.enabled: false` (off by default).
- Drop head-camera resolution to 480×360 in `cameras.head`.
- Quit other GPU processes.

Full mapping: [`docs/how_to_run.md` §5.3](docs/how_to_run.md).
</details>

<details>
<summary><b>🔴 WSL2 / WSLg specifics</b></summary>

- **GLX BadAccess** — head cam now defaults to EGL; don't set `MUJOCO_GL=glfw` for the agent.
- **EGL context affinity** — `MuJoCoHeadCamera` constructs its renderers inside its own thread; don't reorder.
- **Webcam contention** — `usbipd` mounts `/dev/video0`; teleimager's `image_server` opens it. Don't run `cv2.VideoCapture(0)` in parallel.
- **ALSA underrun warnings** — cosmetic, from PulseAudio buffer alignment under WSLg.

Full mapping: [`docs/how_to_run.md` §7](docs/how_to_run.md).
</details>

---

## 🔗 Related Projects

| Project | Relationship |
|---|---|
| 🎙️ [`../va-demo/`](../va-demo/) | Source of the wake-word, VAD, ConversationStateMachine, Realtime WS framework. `BrainRealtimeAgent` subclasses `va_demo.realtime_agent.RealtimeAgent` and replaces 4 things (skills, supervisor, prompt, schemas). |
| 🎬 [`../g1_sim_demo/`](../g1_sim_demo/) | Source of `ComboController` (RL @ 50 Hz + arm-overlay envelope), `g1_sim_keyboard.G1Controller` (keyframe player), and the 11-keyframe library. SkillServer routes calls into both. |
| 🦿 [`../g1_real_demo/`](../g1_real_demo/) | Sister real-robot harness — the `MotionSwitcher.ReleaseMode()` pattern + bounded `lowstate` wait will be reused when `mode: real` is enabled. |
| 📷 [`../teleimager/`](../teleimager/) | The image server `cameras.usb` talks to. Same client code works in sim and on real — only `teleimager_host` changes. |
| 🦾 [`../unitree_sdk2_python/`](../unitree_sdk2_python/) | DDS bindings + message IDLs imported by safety + ComboController. |
| 🌍 [`../unitree_mujoco/`](../unitree_mujoco/) | Source of the simulator + MJCF assets. The head cam attaches synthesized `<camera>`s to its G1 scenes via `MjSpec`. |

---

## 📜 License

Code under `g1_brain/` is licensed under **Apache 2.0**, matching the rest of the in-house deliverables in this workspace ([`g1_sim_demo/`](../g1_sim_demo/), [`g1_real_demo/`](../g1_real_demo/), [`va-demo/`](../va-demo/)). The upstream snapshots imported here retain their original licenses — see the [workspace license overview](../README.md#-license).

---

<div align="center">

<br/>

**🧠 Slow Brain · ⚡ Fast Reflex · 🛡️ Safe Skill — three time-scales, one humanoid.**

<sub>Built on top of [`va-demo`](../va-demo/) + [`g1_sim_demo`](../g1_sim_demo/) — adds cognition, never rewrites infrastructure.</sub>

<br/>

[⬆ Back to top](#-g1_brain) ｜ [🏠 Workspace README](../README.md) ｜ [📐 Full design](../docs/g1_plan.md) ｜ [🚀 Run guide](docs/how_to_run.md)

</div>
