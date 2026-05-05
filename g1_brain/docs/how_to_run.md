# How to run g1_brain

This is the operator-side guide: prerequisites, startup sequence, debug
entry points, common errors, and the path to real-robot deployment.

For architecture / why each piece exists, read
[`architecture.md`](architecture.md). For the full design doc see
[`../../docs/g1_plan.md`](../../docs/g1_plan.md).

---

## 1. Prerequisites

### 1.1 Conda env

The agent runs in the `agi` Miniforge env, which already has
`unitree_sdk2py`, MuJoCo, mediapipe, ultralytics, faster-whisper, openai,
sounddevice, and webrtcvad installed. From a fresh checkout:

```bash
conda activate agi
cd ~/unitree/unitree-notes/g1_brain
pip install -e .
```

### 1.2 OpenAI API key

The Slow Brain (Realtime + GPT-5.5 vision) is cloud-only in v1:

```bash
export OPENAI_API_KEY=sk-...
```

You can override individual models via:
- `OPENAI_REALTIME_MODEL` (default `gpt-realtime`)
- `OPENAI_VISION_MODEL` (default `gpt-5.5`)
- `OPENAI_TTS_MODEL` (default `gpt-4o-mini-tts`)

### 1.3 Model weights

YOLO11 and DepthAnythingV2 download on first use.

| What | Where | Size |
| --- | --- | --- |
| YOLO11s | `~/.config/Ultralytics/yolo11s.pt` | ~22 MB |
| MediaPipe BlazePose | bundled in the wheel | — |
| DepthAnythingV2-Small *(off by default)* | `~/.cache/huggingface/hub/` | ~100 MB |

### 1.4 MuJoCo + teleimager

MuJoCo runs in `unitree` (NOT `agi`) because it pins
`mujoco==3.5.0` for warp compatibility. teleimager runs there too. See
each repo's README for setup; both are git clones in
`~/unitree/unitree-notes/`.

The G1 simulator uses MuJoCo's GLFW backend for its on-screen viewer, so
Terminal 1 still needs `MUJOCO_GL=glfw`. The agent process (Terminal 4),
on the other hand, only does **off-screen** rendering for its head
camera, and `g1_brain.perception.mujoco_head_cam` sets
`MUJOCO_GL=egl` automatically at import time so it works on WSL2/WSLg
without crashing on `X_GLXMakeCurrent` (see §5.2). Override only if you
need software (`MUJOCO_GL=osmesa`) or you have a real X session and
want GLFW (`MUJOCO_GL=glfw`).

### 1.5 Head camera mounting

The stock G1 MJCFs (`unitree_mujoco/unitree_robots/g1/scene_*.xml`) ship
**without any `<camera>` element**. `MuJoCoHeadCamera` notices this and
splices one onto a body via `mujoco.MjSpec` at construction time — by
default `head_camera` on `torso_link` looking forward (+X) at 60° vFov.
The defaults live in `g1_brain.perception.mujoco_head_cam` and are
overridable per-deployment under `cameras.head.*`:

| YAML key | Purpose | Default |
| --- | --- | --- |
| `attach_body` | body that the camera rigidly follows | `torso_link` |
| `attach_pos` | mount position in that body's frame (m) | `[0.08, 0.0, 0.45]` |
| `attach_xyaxes` | camera orientation (`x`, then `y` axis in body frame) | `[0,-1,0, 0,0,1]` (look +X) |
| `attach_fovy` | vertical field of view (deg) | `60.0` |

If the MJCF *does* already define a camera with the requested name (real
robot, or a custom scene), the synthesis path is skipped and that camera
is used as-is.

---

## 2. The 4-terminal startup sequence

```bash
# Terminal 1 — MuJoCo physics + viewer
conda activate unitree
export MUJOCO_GL=glfw
cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
python unitree_mujoco.py
# config.py now ships ELASTIC_BAND_INIT_LENGTH=2.0, which makes the band
# slack at the standing pose, so the G1 sits on the floor right away —
# no key presses required. In the viewer you can still:
#   press 9 to toggle the band off entirely (clean fall test)
#   press 7 / 8 to nudge the band length by ±0.1 m

# Terminal 2 — USB camera service
conda activate unitree
cd ~/unitree/unitree-notes/teleimager
python -m teleimager.image_server

# Terminal 3 — E-stop listener (independent process)
conda activate agi
cd ~/unitree/unitree-notes/g1_brain
python -m g1_brain.safety.estop_listener
# Press ESC at any time to engage; the file /tmp/g1_brain_estop is
# touched and the agent's SafetySupervisor rejects all motion until the
# file is removed.

# Terminal 4 — agent
conda activate agi
cd ~/unitree/unitree-notes/g1_brain
export OPENAI_API_KEY=sk-...
python -m g1_brain.apps.agent_main --mode confirm
```

You can omit Terminal 3 if you only want soft safety (the supervisor still
gates everything; you just lose the panic-button exit).

Terminal 2 (teleimager) is the recommended path for the USB camera,
because the same client code works in sim and on the real robot — only
`cameras.usb.teleimager_host` changes between the two. If you don't want
to run teleimager (laptop dev, no webcam server), set
`cameras.usb.source: cv2` and `UsbCamera` will open `/dev/video0`
directly. The `cv2` and `teleimager` backends both fight over the same
device, so don't run them concurrently.

Terminal 4 no longer needs an `MUJOCO_GL` export — `mujoco_head_cam`
defaults to `egl`, which is what WSLg expects.

---

## 3. The 4 debug entry points

All under `g1_brain.apps.*`. Each is a self-contained `python -m` runnable.

### 3.1 `perception_debug` — does the eye work?

```bash
python -m g1_brain.apps.perception_debug
python -m g1_brain.apps.perception_debug --show   # opens cv2 windows
```

Loops at 2 Hz printing `SceneState.summary_for_llm()`. Good first sanity
check: do detections appear? does pose detection fire? does the head
camera have a frame age < 1 s?

You only need MuJoCo running if you want head-camera output; USB +
MediaPipe-Pose works on its own.

### 3.2 `safety_debug` — does my safety config make sense?

```bash
python -m g1_brain.apps.safety_debug
python -m g1_brain.apps.safety_debug --scenarios ./my_scenarios.json
```

Builds a SafetySupervisor with mocked SceneStateBus / RobotStateBus / FSM /
EstopClient and runs a list of (tool, args, expected verdict) scenarios.
Useful for A/B-ing safety.* config tweaks. No DDS, no MuJoCo, no OpenAI.

### 3.3 `skill_debug` — does the body work?

```bash
python -m g1_brain.apps.skill_debug
```

Connects DDS, spins up ComboController and SkillServer, then waits on
stdin. Number keys 1–9 invoke individual skills (walk, turn, gestures,
stop, release_arms). `q` to quit cleanly.

Use this to verify ComboController + SafetySupervisor + SkillServer end
to end without involving the LLM.

### 3.4 `estop_test` — does the kill switch work?

```bash
python -m g1_brain.apps.estop_test
```

Times engage / poll / release on the configured flag path. Passes/fails
without printing anything else if the round trip works. Run once after
install to confirm /tmp is writable; run again any time you change the
flag path.

---

## 4. Run modes (`--mode`)

| Mode | Effect |
| --- | --- |
| `observe` | All motion tools rejected. `say` / `describe_scene` / `query_scene_state` still work. Use during config tuning. |
| `confirm` *(default)* | Each motion tool prompts `y/N` in Terminal 4 before executing. Default and recommended. |
| `active` | Motion executes immediately within the safety bounds. Use only when you trust the LLM and the scene. |

`--vision-only` is a separate axis: drops every motion tool from the
schema and skips DDS init, so MuJoCo isn't required either.

---

## 5. Common errors and fixes

### 5.1 DDS doesn't connect / `lowstate_age` keeps growing

Symptoms: `[combo] waiting for first /rt/lowstate ...` never proceeds; or
SafetySupervisor rejects every motion call with `watchdog: lowstate age ...`.

Causes / fixes:
- MuJoCo (Terminal 1) isn't running yet → start it first.
- MuJoCo is on a different DDS domain. Check
  `cyclonedds.xml` and that `cfg.robot.domain_id` matches what
  `unitree_mujoco.py` was launched with (the python sim defaults to 1).
- `interface: lo` doesn't exist on this system → set to your loopback
  alias (Linux is usually `lo`; on macOS `lo0`).

### 5.2 MuJoCo / OpenGL errors

There are two MuJoCo processes in this stack and they want different
GL backends:

**(a) The simulator (Terminal 1)** opens an on-screen viewer window.
On WSL2/WSLg use `MUJOCO_GL=glfw` and confirm WSLg is up
(`echo $DISPLAY` should print `:0`). When SSH'ing in headless, use
`MUJOCO_GL=osmesa` (software) — `egl` works on bare-metal Linux but is
fragile under WSLg for GUI windows.

**(b) The agent's head camera (Terminal 4)** renders off-screen only.
`g1_brain.perception.mujoco_head_cam` sets `MUJOCO_GL=egl` at import
time. You should not need to set it. The override order is the same
`os.environ.setdefault` pattern — anything you exported before launch
wins.

Diagnostic mapping:

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Terminal 1 dies with "OpenGL renderer null" | WSLg not exposing GLX, or MUJOCO_GL not set | export `MUJOCO_GL=glfw`, check `echo $DISPLAY` |
| Terminal 4 dies with `X Error: BadAccess … X_GLXMakeCurrent` | g1_brain head cam fell back to GLFW under WSLg | should not happen anymore — confirm `MUJOCO_GL` is empty or `egl` before launching agent_main; if explicitly set to `glfw`, unset it |
| Head cam silent + debug log shows `EGL_BAD_ACCESS on eglMakeCurrent` | a `mujoco.Renderer` was constructed on the main thread but used from another (legacy bug) | should not happen anymore — `MuJoCoHeadCamera` now lazy-builds renderers inside its render thread; pull latest |
| Head cam silent on a remote box without a GPU | EGL has no driver | `export MUJOCO_GL=osmesa` before agent_main (slower, software fallback) |

### 5.3 CUDA out-of-memory on the 4060

Symptoms: ultralytics or transformers OOMs at startup or first inference.

Fixes (in order of preference):
- Set `perception.yolo.weights: yolo11n.pt` (5 M params instead of 22 M).
- Disable mono depth: `perception.mono_depth.enabled: false` (it's off by
  default).
- Drop head-camera resolution to 480x360 in `cameras.head`.
- Quit other GPU processes (Chrome, VS Code language servers).

### 5.4 OpenAI 401 / rate-limited

Symptoms: agent_main exits with `OPENAI_API_KEY is not set`, or Realtime
errors from the websocket.

Fixes:
- `export OPENAI_API_KEY=sk-...` and re-run.
- Confirm the model names: `OPENAI_REALTIME_MODEL`, `OPENAI_VISION_MODEL`,
  `OPENAI_TTS_MODEL`. Realtime requires beta access on your account.
- For local dev without internet, run with `--no-realtime` (mic / camera
  / safety still runs, just no LLM).

### 5.5 Watchdog trip during dialog

Symptoms: Sparky responds, then at the next motion call rejects with
`watchdog tripped: ...`.

Causes / fixes:
- `head_frame` watchdog: head camera lost frames. Likely MuJoCo dropped
  to <2 FPS due to GPU pressure; close other GPU apps.
- `lowstate` watchdog: ComboController stopped getting state. Check
  Terminal 1 — MuJoCo may have crashed.
- `rl_policy_active` watchdog: usually means MuJoCo restarted; restart the
  agent to re-boot the policy ramp.

### 5.6 ComboController `policy_active` never becomes True

Symptoms: agent_main logs `policy not active after 30s; continuing anyway`
and SkillServer rejects every motion call.

Causes:
- MuJoCo wasn't ready when DDS init ran. Restart agent_main.
- The simulator is running on a different domain (see 5.1).
- The boot ramp aborted because lowstate stopped midway. Watch
  Terminal 1 for an error.

### 5.7 Head camera renders an empty / sky-only frame

Symptoms: `latest_head_bgr()` returns a frame that's all sky / blue
gradient with a checkered floor far away. The "synthesized head camera"
INFO log line *did* appear at startup.

This means the synthesized camera is mounted correctly but the robot
isn't visible because it's too far away from the camera origin (i.e.
the camera is sitting at `(0.08, 0, 0.45)` in `torso_link`'s frame
looking forward — it's *inside* the robot's head looking outward, which
is correct). When the simulator starts the robot at the origin and
hasn't been kicked off yet, the only thing in front is the floor.

Sanity checks:
- Confirm the simulator's `ELASTIC_BAND_INIT_LENGTH` is at the new
  default (2.0) — older checkouts with `0.0` suspend the robot above
  the floor and the head cam will see only sky.
- Confirm `cameras.head.subscribe_dds` is true (default) and that DDS
  is up — otherwise the head cam renders from the model's keyframe
  pose, not the live pose. With `--no-skills` / `--vision-only` we
  intentionally fall back to keyframe pose.
- If you're testing against a non-G1 MJCF, override `attach_body` to a
  body that exists in *that* model.

### 5.8 Head camera DDS subscribers fail with `'NoneType' object has no attribute '_ref'`

Should not happen anymore. Historical cause: `CameraHub` was being
constructed before `ChannelFactoryInitialize`, so
`ChannelSubscriber.Init('rt/lowstate')` raced the factory. Fixed in
`apps/agent_main.py` — camera_hub is now built after DDS init and
inherits `subscribe_dds=False` automatically when `--no-skills` /
`--vision-only` is passed (no DDS init at all).

If you somehow see this error, you're probably on an older checkout, or
you're constructing `MuJoCoHeadCamera` directly in your own script
before calling `ChannelFactoryInitialize`. Either reorder, or pass
`subscribe_dds=False` to render from keyframe pose only.

---

## 6. Switching from sim to real robot

The architecture leaves slots for this; the actual swap is a
configuration change plus a couple of adapter implementations. See
[`../../docs/g1_plan.md`](../../docs/g1_plan.md) §8.3 for the full
checklist. Highlights:

- `mode: real` in the YAML — Safety stops rejecting `loco_high` /
  `arm_action_high` / `audio_tts_robot` and SkillServer routes those to
  `LocoClient` / `G1ArmActionClient` / `AudioClient`.
- `cameras.usb`: keep `source: teleimager`, change
  `teleimager_host` from `127.0.0.1` to the robot's IP. The on-robot
  teleimager service exposes the real RGB camera the same way the
  laptop's local instance does in sim.
- `cameras.head`: in sim this is the synthesized MuJoCo first-person
  view of the robot in its own simulated world. On the real robot you
  have two reasonable options:
  - **Disable it** (`cameras.head.enabled: false`) and rely on the
    onboard depth/RGB camera fed through teleimager.
  - **Replace** the `MuJoCoHeadCamera` with a `RealSenseCamera` adapter
    exposing the same interface
    (`latest_bgr / latest_depth_meters / frame_age_seconds /
    hfov_deg / vfov_deg`). Plug it in by editing
    `perception/cameras.py::CameraHub._build_head` to branch on
    `cfg.get("real")` (or `cfg.mode`).
- `safety.estop` stays the same file-based flag; additionally bind a real
  hardware E-stop (handheld remote button) to write the same flag.
- Walk safety bounds: keep them at the v1 levels until you've validated
  the chassis on real hardware. Do *not* loosen `vx_max` until a human
  has run a 30-minute supervised loop without incident.

---

## 7. WSL2 / WSLg specifics (current dev box)

This repo is being developed against Linux on WSL2 (Ubuntu in WSLg).
A few pitfalls have already been worked around in code; if you move to
native Linux, you'll be unaffected by all of them.

- **GLX BadAccess in the agent**: WSLg's GLX bridge can't keep two
  MuJoCo `Renderer` GLFW contexts current from a worker thread. The
  head cam now defaults to EGL (see §5.2). If you ever set
  `MUJOCO_GL=glfw` for the agent on WSL, expect the crash back.
- **EGL context affinity**: `MuJoCoHeadCamera` constructs its
  renderers inside the render thread, not the main thread, because
  EGL contexts can only be made current from the thread that created
  them. Don't reorder this if you refactor.
- **Webcam under WSLg**: `usbipd-win` mounts the laptop webcam at
  `/dev/video0`. teleimager's `image_server` opens it; `cv2.VideoCapture(0)`
  will then fail because the device is busy. Pick one consumer.
- **ALSA underrun warnings** during startup are cosmetic and come from
  PulseAudio buffer alignment under WSLg. They do not indicate dropped
  audio.
