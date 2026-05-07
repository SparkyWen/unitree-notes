# g1_brain architecture (cliffs notes)

This is the ~500-line condensed version. The full design (1500+ lines) is
in [`../../docs/g1_plan.md`](../../docs/g1_plan.md).

---

## 1. Three layers, three time scales

```
┌────────────────────────────────────────────────────────────────────┐
│                       USER (voice / keyboard)                      │
└────────────────────────────────────────────────────────────────────┘
                                ↕
┌────────────────────────────────────────────────────────────────────┐
│  SLOW BRAIN  (g1_brain/brain/)                  0.2 - 2 Hz         │
│  - OpenAI Realtime (gpt-realtime, reused from va-demo)             │
│  - GPT-5.5 Vision via describe_scene tool                          │
│  - tool calls -> high-level intent / parameterized skill           │
└────────────────────────────────────────────────────────────────────┘
                                ↕            (intent JSON)
┌────────────────────────────────────────────────────────────────────┐
│  SAFE SKILL  (g1_brain/safety/ + g1_brain/skills/)                 │
│  - SafetySupervisor: 12 rules (whitelist, FSM, run-mode, watchdog, │
│    pose, scene, E-stop, GPT-5.5 vision risk gate)                  │
│  - SkillServer: ~16 skills routed to ComboController / Keyframe    │
└────────────────────────────────────────────────────────────────────┘
                                ↕            (skill call)
┌────────────────────────────────────────────────────────────────────┐
│  FAST REFLEX  (g1_brain/perception/ + scene_state/)    5-30 Hz     │
│  - Dual cameras:                                                   │
│      USB    — laptop/robot RGB via teleimager (or cv2 fallback)    │
│      head   — MuJoCo offscreen RGB+depth, EGL-backed, own thread,  │
│               camera synthesized onto torso_link if MJCF lacks one │
│  - YOLO11, MediaPipe-Pose, MuJoCo native depth                     │
│  - Fused into SceneState (clear_path / nearest_obstacle / ...)     │
│  - Safety reads SceneState before every motion skill               │
└────────────────────────────────────────────────────────────────────┘
                                ↕            (lowcmd / lowstate)
┌────────────────────────────────────────────────────────────────────┐
│  RUNTIME  (reuses g1_sim_demo)         50 / 500 / 1000 Hz          │
│  - ComboController (RL @ 50 Hz + arm-overlay envelope)             │
│  - Keyframe player (g1_sim_keyboard's static poses)                │
│  - Real-robot swap: LocoClient + G1ArmActionClient                 │
└────────────────────────────────────────────────────────────────────┘
                                ↕     DDS (domain 1 = sim, 0 = real)
┌────────────────────────────────────────────────────────────────────┐
│  unitree_mujoco simulate_python   <or>   real G1 PC2               │
└────────────────────────────────────────────────────────────────────┘
```

**Key invariant**: every downward command (Brain -> Skill -> Runtime)
goes through `SafetySupervisor.validate()`. The LLM never sees lowstate /
motor data and can never emit a joint angle.

---

## 2. Frequency table (load-bearing — don't violate)

| Loop | Rate | Owner | Off-limits to |
| --- | --: | --- | --- |
| Motor PD | 1000 Hz | MuJoCo / motor controller | Python anywhere |
| ComboController RL tick | 50 Hz | `ComboController._tick` | LLM, Brain |
| Keyframe player | 500 Hz | `g1_sim_keyboard.G1Controller` | LLM |
| SafetySupervisor watchdog | 20 Hz | `safety/watchdogs.py` | LLM |
| Perception RGB / depth | 10–30 Hz | `perception/cameras.py` | LLM |
| YOLO detection | 10–20 Hz | `perception/object_detector.py` | LLM |
| MediaPipe-Pose | 10–30 Hz | `perception/pose_detector.py` | LLM |
| SceneState fusion | 10 Hz | `scene_state/fusion.py` | LLM |
| Brain (vision tool) | 0.5–2 Hz | Realtime tool call | — |
| Brain (Realtime audio) | streaming | OpenAI gpt-realtime | — |
| E-stop poll | 50 Hz | `safety/estop_listener.py` | nobody bypasses it |

---

## 3. Data flow: a worked example

The annotated dialog (verbatim from the design doc §10.2):

```
You: Hi Sparky
[wake] hi sparky                                # wake-word detector flips
                                                # ConversationStateMachine
                                                # to LISTENING
You: 看一下前面有什么？
[describe_scene] head camera frame -> GPT-5.5   # LLM tool call routed
                                                # through SafetySupervisor
                                                # (no motion -> no
                                                # confirm prompt) and then
                                                # to vision.VisionClient
Sparky: 我看到正前方大约 1 米外有一张红色椅子，地面平整，路径基本通畅。
You: 那向前走两步过去看一下
[query_scene_state] called by LLM               # LLM tool call -> SkillServer
[scene] persons=0, nearest_obstacle=1.05m,      # SceneState.summary_for_llm()
        clear_path=true                         # comes back as the tool result
[tool] walk(vx=0.18, wz=0, duration_s=0.8)      # SkillServer.execute("walk")
[safety] confirm prompt: execute walk(...)? [y/N] y
                                                # run_mode=confirm so user
                                                # gets a y/N gate
[scene check at t=0.4s] obstacle=0.9m -> still ok   # SkillServer._skill_walk
[scene check at t=0.6s] obstacle=0.78m -> still ok  # re-reads SceneState
                                                # every 0.2s and aborts if
                                                # path no longer clear
[walk done] actual_duration=0.8s, final_obstacle=0.7m
Sparky: 我向前走了一小步...
You: [waves]
[perception] gesture=wave_right conf=0.88       # MediaPipe -> derivations.
        persist=1.2s                            # classify_gesture, persists
                                                # 1s before publishing
[brain] auto-suggest mock_imitate(wave_right)   # GestureAutoTrigger
                                                # injects a perception event
                                                # into BrainRealtimeAgent
Sparky: 我看到你在向我挥手, 我也挥一下。
[tool] mock_imitate(wave_right) -> gesture(wave_right)  # SkillServer
                                                # routes to ComboController
                                                # arm-overlay
[combo] arm_overlay queued, releases in 3.2s
You: 谢谢，停一下
[tool] stop()
Sparky: 已停止，等你下一步指示。
```

Sequence call graph:

```
Realtime WS
   │ tool_call event
   ▼
BrainRealtimeAgent._dispatch_tool
   │
   ▼
SafetySupervisor.validate(tool, args)        ─── reads SceneStateBus.snapshot()
   │  ok=False -> return reason to Brain          and RobotStateBus.snapshot()
   │  ok=True ────────────────────────────────────────────────┐
   │                                                          │
   ▼                                                          ▼
SkillServer.execute(tool, sanitized_args)              EstopClient.is_engaged()
   │
   ├── _skill_say        -> TTSClient
   ├── _skill_walk       -> ComboController.set_command(...)  (re-checks scene every 0.2s)
   ├── _skill_gesture    -> ComboController.push_arm_action(...)
   ├── _skill_static_pose-> KeyframeExtras
   ├── _skill_describe_scene -> CameraHub + VisionClient
   └── ...
```

---

## 4. SceneState — the contract

This is the single object the SafetySupervisor reads. Defined in
`scene_state/types.py`:

```python
@dataclass
class SceneState:
    ts_usb / ts_head / ts_pose / ts_yolo_*     # monotonic timestamps
    user_pose: HumanPose | None                # MediaPipe 33 landmarks + gesture
    user_detections: list[Detection]
    head_detections: list[Detection]
    ground: GroundConstraint | None            # clear_path / nearest_obstacle ...
    perception_warnings: list[str]
```

`SceneStateBus` (in `scene_state/fusion.py`) owns the live mutable state
behind an RLock. Producers call `update_*()`; consumers call `snapshot()`
which rebuilds an immutable dataclass copy. Watchdogs query
`usb_frame_age_s()` / `head_frame_age_s()` directly so they can fire
even before the first detection comes in.

`RobotState` is the parallel dataclass for the body (gravity proj,
ang vel, RL policy active). Lives in `RobotStateBus`. Producer is the
`_RobotStateProducer` thread in `apps/agent_main.py`, which polls
`ComboController.low_state` at 20 Hz.

---

## 5. Safety: 7-state FSM + 12 rules

**FSM** (in `safety/state_machine.py`) — `BOOT → STANDING → ENGAGED →
ACTING → STANDING ...` with `EMERGENCY_STOP` and `FAULT` as universal
sinks. Recovery is manual: from EMERGENCY_STOP you go through RECOVERING
back to STANDING.

**12 rules** (in `safety/supervisor.py`, applied in order to every tool
call):

1. **Whitelist** — tool in `ALLOWED_TOOLS`
2. **FSM gating** — current state allows this tool (motion vs no-motion)
3. **run_mode** — observe blocks all motion; confirm prompts y/N
4. **lowstate watchdog** — `lowstate_age < 0.5s`
5. **head-cam watchdog** — `head_frame_age < 2.0s` for walk / approach
6. **RL policy active**
7. **Pose check** — projected gravity z below threshold; tipping triggers
   EMERGENCY_STOP
8. **Parameter clamp** — vx/vy/wz/duration clipped to safe envelope
9. **Scene check (walk)** — `clear_path=True`, `nearest_obstacle_m > 0.6`,
   `nearest_person_m > 0.8`
10. **Scene check (gesture)** — `nearest_person_m > 0.5`
11. **E-stop flag** — `EstopClient.is_engaged()` → reject everything except
    `say` / `stop` / `describe_scene` / `query_scene_state`
12. **Vision risk gate** (spec `docs/g1_v1.md`) — for motion tools that
    cleared rules 1–10, send the head-cam JPEG + a rendered action
    sentence to GPT-5.5 (`vision_model: gpt-5.5`); SAFE short-circuits
    (auto-execute regardless of run_mode), RISK falls through to the
    legacy `_confirm_in_terminal` y/N with the GPT-supplied reason
    printed inline. `say` / `stop` / `release_arms` bypass to SAFE; a
    backward `walk` (vx<0) bypasses to RISK because the head camera is
    blind to behind. Frame age, brightness, GPT timeout, GPT exception,
    and unparseable output all return RISK so the operator never gets a
    silent auto-execute on failure. Disable with
    `safety.vision_gate.enabled: false` to revert bit-for-bit to the
    pre-design build.

Rule 11 is hoisted earlier in code so the user-facing prompts also short
circuit.

The E-stop is a separate process (`safety/estop_listener.py`) that
listens for ESC and writes `/tmp/g1_brain_estop`. Even if the agent
deadlocks, the listener still publishes 30 frames of zero-torque lowcmd
to DDS.

---

## 6. Skills

`skills/skill_server.py::SkillServer.execute(tool, args)`:

1. Calls `safety.validate(tool, args)`.
2. If ok, dispatches to `_skill_<tool>` coroutine.
3. Returns a JSON-friendly dict that includes a SceneState summary so the
   Brain can decide its next move without an extra tool call.

Tool catalog (~16 — see `skills/tool_schemas.py` for the full JSON
schemas): `say`, `describe_scene`, `query_scene_state`, `look_at`,
`approach`, `mock_imitate`, `ask_human`, `walk`, `turn`, `gesture`,
`static_pose`, `stop`, `release_arms`, plus three real-only tools that
get rejected in sim mode (`loco_high`, `arm_action_high`,
`audio_tts_robot`).

---

## 7. Brain

`brain/realtime_agent.py::BrainRealtimeAgent` subclasses
`va_demo.realtime_agent.RealtimeAgent` and replaces only:

- the SkillBackend → `g1_brain.skills.SkillServer`
- the SafetySupervisor → `g1_brain.safety.SafetySupervisor`
- the system prompt → `brain/prompts.py` (mentions every tool, reminds
  the LLM it cannot call L3 motor commands, tells it to call
  `describe_scene` / `query_scene_state` before walking)
- the tool schema list → `skills/tool_schemas.py`

Wake-word + UtteranceVAD + ConversationStateMachine are all reused from
va-demo unchanged.

---

## 8. Mock imitation (Phase 5)

```
USB Camera ─► PoseDetector (MediaPipe, 15 Hz)
                  │
                  ▼ landmarks
            derivations.classify_gesture()
                  │
                  ▼ (gesture, conf)
            SceneStateBus.update_user_pose
                  │
       ┌──────────┴──────────┐
       │                     │
 (a) LLM-driven          (b) auto-trigger
     describe_scene          GestureAutoTrigger watches
     sees user_pose          for >=1s of high conf, then
     and may call            calls brain.inject_perception_event
     mock_imitate(...)       which prods the LLM to call
                             mock_imitate
```

Both paths exist. mock_imitate validates the gesture name against
`GestureLabel.MIRRORABLE` (wave_right / wave_left / hands_up / t_pose),
maps it to the matching `gesture()` skill, and goes through the same
SafetySupervisor pipeline as any other motion.

---

## 9. Process model

Single main process running asyncio + many background threads + one
independent E-stop process.

- Main process: asyncio loop running BrainRealtimeAgent + WS uplink/downlink
- Background threads: MicStream, SpeakerStream, UsbCamera, MuJoCoHeadCamera
  (own EGL context — see below), YOLO, Pose, ComboController (50 Hz),
  watchdogs (20 Hz), RobotStateProducer (20 Hz), GestureAutoTrigger
- Independent process: `safety/estop_listener.py` — only thing that can
  publish lowcmd if the main process deadlocks

This is enough for v1. Phase 6+ (real robot) may move some of this to ROS2
or ZMQ; v1 keeps it intentionally small.

### 9.1 MuJoCo head camera — startup and threading

Two facts that drive the implementation in `perception/mujoco_head_cam.py`:

1. **DDS subscribers must outlive `ChannelFactoryInitialize`.** The head
   camera subscribes to `rt/lowstate` and `rt/sportmodestate` so its
   private `MjData` tracks the live robot. `agent_main.py` therefore
   constructs `CameraHub` **after** the DDS factory is initialized, and
   passes `subscribe_dds=False` automatically when running with
   `--no-skills` / `--vision-only` (no DDS at all). Subscribing before
   the factory is up raises `'NoneType' object has no attribute '_ref'`.
2. **GL contexts are pinned to the thread that created them.** EGL
   raises `EGL_BAD_ACCESS` (and GLX raises `BadAccess`) if a context is
   made current on a different thread than it was created on. The
   render-thread therefore *constructs* its own RGB and depth
   `mujoco.Renderer` instances at the top of its loop, not in
   `__init__`. `close()` only signals stop and joins; teardown of the
   GL contexts happens in the worker's `finally` block.

Camera synthesis: stock G1 MJCFs (`scene_29dof.xml`, `scene_23dof.xml`)
do not define any `<camera>`. `MuJoCoHeadCamera._load_or_synthesize_model`
loads the MJCF as an `MjSpec`, walks its existing cameras, and only if
the requested `camera_name` is missing, it `add_camera`s one onto
`attach_body` (default `torso_link`) before compiling. This keeps the
upstream `unitree_mujoco/` checkout untouched while still giving the
head a sensible first-person view.

---

## 10. Where to look next

- Implementation details and rationale → `../../docs/g1_plan.md`
- Step-by-step run instructions → `how_to_run.md`
- Add a new skill → `extending_skills.md`
- File-by-file reading order:
  1. `scene_state/types.py` (data contracts)
  2. `safety/supervisor.py` (the 12 rules in code; rule 12 is in `safety/vision_risk_gate.py`)
  3. `skills/skill_server.py` (dispatch)
  4. `apps/agent_main.py` (wiring)
  5. `brain/realtime_agent.py` (extension of va-demo)
