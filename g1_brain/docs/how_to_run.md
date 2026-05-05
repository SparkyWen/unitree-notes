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

---

## 2. The 4-terminal startup sequence

```bash
# Terminal 1 — MuJoCo physics + viewer
conda activate unitree
export MUJOCO_GL=glfw
cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
python unitree_mujoco.py
# In the viewer window:
#   press 8 a few times to drop the G1 onto the floor
#   press 9 to release the elastic band

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

You can omit Terminal 2 if you pass `cameras.usb.source: cv2` in
`configs/g1_brain.yaml` and have a webcam.

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

### 5.2 MuJoCo: `OpenGL renderer null`

Symptoms: MuJoCo errors out with a renderer / GLFW error on launch.

Fix: `export MUJOCO_GL=glfw` *before* launching MuJoCo. On WSL2, also
make sure WSLg is active (`echo $DISPLAY` should print `:0` or similar).
If you're SSHing in, prefer `MUJOCO_GL=egl` for headless rendering.

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

---

## 6. Switching from sim to real robot

The architecture leaves slots for this; the actual swap is a
configuration change plus a couple of adapter implementations. See
[`../../docs/g1_plan.md`](../../docs/g1_plan.md) §8.3 for the full
checklist. Highlights:

- `mode: real` in the YAML — Safety stops rejecting `loco_high` /
  `arm_action_high` / `audio_tts_robot` and SkillServer routes those to
  `LocoClient` / `G1ArmActionClient` / `AudioClient`.
- Replace `cameras.head` with a `RealSenseCamera` adapter (interface
  identical: `latest_bgr / latest_depth / frame_age_seconds`).
- `safety.estop` stays the same file-based flag; additionally bind a real
  hardware E-stop (handheld remote button) to write the same flag.
- Walk safety bounds: keep them at the v1 levels until you've validated
  the chassis on real hardware. Do *not* loosen `vx_max` until a human
  has run a 30-minute supervised loop without incident.
