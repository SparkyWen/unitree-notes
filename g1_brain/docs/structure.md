# G1 Brain — System Structure

> Living architecture document. Captures **what is implemented today** in
> `g1_brain/` and **what is planned next** (harness multi-agent layer with
> long-term memory, advanced safety, recovery, and policy-skill library).
>
> Companion to [`architecture.md`](architecture.md) (cliffs notes of the
> current code) and [`../../docs/harness_g1.md`](../../docs/harness_g1.md)
> (the rationale for the harness-driven extension).

---

## 0. TL;DR

The system is a **layered, skill-oriented, agentic robot OS** for the
Unitree G1. The LLM is a **task-level orchestrator**, never a real-time
controller. Every downward command crosses a safety supervisor before it
becomes motion.

```
Human intent  →  Reasoning (LLM + memory)  →  Safety  →  Skills  →  Runtime  →  G1
                                          ↑
                          Perception / SceneState (closed loop)
```

Key invariants (do not violate):

1. **LLM never sees lowstate / motor data and never emits a joint angle.**
2. **Every tool call goes through `SafetySupervisor.validate()`.**
3. **The E-stop runs in a separate process** so it survives a deadlock in
   the main agent.
4. **High-frequency loops (1 kHz motor PD, 50 Hz RL tick, 500 Hz keyframe,
   20 Hz watchdog) are off-limits to the LLM and to Python in general.**

---

## 1. Complete Flow Diagram (current + planned)

> Solid boxes = implemented. Dashed boxes = planned (harness layer,
> memory, recovery, RL/LeRobot policy library, ROS2 action transport).

```
┌────────────────────────────────────────────────────────────────────────────┐
│  L7  HUMAN / OPERATOR                                                      │
│  voice command · gesture · demonstration · keyboard · joystick · E-stop    │
└────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌────────────────────────────────────────────────────────────────────────────┐
│  L6  SENSOR INPUT LAYER                                              5–30 Hz│
│  ┌─────────────────┐ ┌─────────────────┐ ┌──────────────────┐              │
│  │ Head camera     │ │ USB camera      │ │ Microphone       │              │
│  │ MuJoCo offscreen│ │ teleimager / cv2│ │ MicStream (24 k) │              │
│  │ RGB + depth     │ │ RGB             │ │                  │              │
│  └─────────────────┘ └─────────────────┘ └──────────────────┘              │
│  ┌- - - - - - - - -┐ ┌- - - - - - - - -┐ ┌- - - - - - - - -┐               │
│  │ RealSense (D435)│ │ ROS2 Image topic│ │ Joystick / UI    │ planned       │
│  └- - - - - - - - -┘ └- - - - - - - - -┘ └- - - - - - - - -┘               │
└────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌────────────────────────────────────────────────────────────────────────────┐
│  L5  PERCEPTION LAYER                                                10 Hz │
│  YOLO11 (objects) · MediaPipe-Pose (gestures) · MuJoCo native depth        │
│  Ground constraint (cone 15°, 0.5–1.5 m, clearance 0.6 m)                  │
│        │                                                                    │
│        ▼                                                                    │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │ SceneStateBus  (RLock-guarded mutable state, snapshot() returns      │  │
│  │ immutable copy)                                                      │  │
│  │   user_pose · user_detections · head_detections                      │  │
│  │   ground{ clear_path, nearest_obstacle_m, nearest_person_m }         │  │
│  │   ts_usb · ts_head · ts_pose · perception_warnings                   │  │
│  ├──────────────────────────────────────────────────────────────────────┤  │
│  │ RobotStateBus  (gravity proj · ang vel · RL active · lowstate_age)   │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────────┘
                                       │ snapshot()
                                       ▼
┌────────────────────────────────────────────────────────────────────────────┐
│  L4  AI REASONING LAYER                                          0.2–2 Hz  │
│                                                                            │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │ BrainRealtimeAgent  (extends va-demo RealtimeAgent)                  │  │
│  │   · OpenAI Realtime  gpt-realtime         streaming voice in/out     │  │
│  │   · GPT-5.5 Vision   describe_scene       0.5–2 Hz, head frame       │  │
│  │   · Tool dispatcher  ─► SafetySupervisor.validate ─► SkillServer     │  │
│  │   · Wake-word + UtteranceVAD + ConversationStateMachine (va-demo)    │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                            │
│  ┌- - - - - - - - - - - - - - PLANNED - - - - - - - - - - - - - - - - -┐  │
│  │ Harness Multi-Agent Orchestrator                                     │  │
│  │   1. TaskUnderstandingAgent  natural language ─► structured intent   │  │
│  │   2. SkillPlannerAgent       intent ─► skill DAG (deps + pre/post)   │  │
│  │   3. SafetySupervisorAgent   rule engine + LLM, veto power           │  │
│  │   4. PerceptionAgent         queries SceneState, VLM scene caption   │  │
│  │   5. ExecutionMonitorAgent   subscribes feedback, aborts on drift    │  │
│  │   6. RecoveryAgent           failure ─► stop / damp / sit / retry    │  │
│  │   7. MemoryAgent             episode store, self-reflection, RAG     │  │
│  └- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -┘  │
│                                                                            │
│  ┌- - - - - - - - - - - - - - PLANNED - - - - - - - - - - - - - - - - -┐  │
│  │ Long-Term Memory Subsystem                                           │  │
│  │   · EpisodicMemory   per-task trace (skills, sensors, outcomes)      │  │
│  │   · SemanticMemory   facts: room layout, named objects, people       │  │
│  │   · ProceduralMemory successful skill sequences, recipes             │  │
│  │   · ReflectiveMemory failure post-mortems, "do/don't" rules          │  │
│  │   · Vector store (e.g. sqlite-vec / chroma) + structured JSON        │  │
│  │   Hooks: pre-task RAG retrieval · post-task summarization            │  │
│  └- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -┘  │
└────────────────────────────────────────────────────────────────────────────┘
                                       │ structured tool call (JSON)
                                       ▼
┌────────────────────────────────────────────────────────────────────────────┐
│  L3  SAFETY SUPERVISOR (FSM + 11 rules)                              20 Hz │
│                                                                            │
│  State machine:  BOOT → STANDING → ENGAGED → ACTING → STANDING …           │
│                          │                                                 │
│                          └──► EMERGENCY_STOP ──► RECOVERING ──► STANDING   │
│                          └──► FAULT (manual reset)                         │
│                                                                            │
│  Rules applied per tool call:                                              │
│    1. Whitelist                  6. RL policy active                       │
│    2. FSM gating                 7. Pose check (gravity z ≤ -0.85)         │
│    3. run_mode (obs/conf/act)    8. Parameter clamp (vx ≤ 0.2, …)          │
│    4. lowstate_age < 0.5 s       9. Scene check — walk (path/obs/person)   │
│    5. head_frame_age < 2.0 s    10. Scene check — gesture (person ≥ 0.5m)  │
│                                 11. E-stop flag (/tmp/g1_brain_estop)      │
│                                                                            │
│  ┌- - - - - - - - - - - PLANNED EXTENSIONS - - - - - - - - - - - - - -┐   │
│  │ · Rule engine YAML config (currently hard-coded in supervisor.py)  │   │
│  │ · Per-skill confirmation policy (high/medium/low risk)             │   │
│  │ · Geo-fence / workspace boundary check                             │   │
│  │ · Battery / temperature / network-latency guards                   │   │
│  │ · Fatigue policy (cumulative motion budget)                        │   │
│  │ · Privacy filter on outbound vision frames                         │   │
│  └- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -┘   │
│                                                                            │
│  Independent E-stop process (safety/estop_listener.py)                     │
│    ESC key  ─►  /tmp/g1_brain_estop  ─►  publish 30 zero-torque lowcmd     │
│    Survives main-process deadlock. Polled at 50 Hz everywhere.             │
└────────────────────────────────────────────────────────────────────────────┘
                                       │ approved skill call
                                       ▼
┌────────────────────────────────────────────────────────────────────────────┐
│  L2  SKILL SERVER (~16 skills)                                             │
│                                                                            │
│  Implemented:                                                              │
│    say · stop · walk(vx,vy,wz,dur) · turn · gesture · static_pose          │
│    look_at · approach · describe_scene · query_scene_state                 │
│    mock_imitate · ask_human · release_arms                                 │
│  Real-only (rejected in sim):                                              │
│    loco_high · arm_action_high · audio_tts_robot                           │
│                                                                            │
│  walk re-reads SceneState every 0.2 s; aborts if path no longer clear.     │
│  Every skill returns a SceneState summary so the brain can act without an  │
│  extra round-trip.                                                         │
│                                                                            │
│  ┌- - - - - - - - - - - PLANNED SKILLS - - - - - - - - - - - - - - - -┐   │
│  │ grasp_object · release_object · pick_place · handover                │  │
│  │ navigate_to(x, y, yaw) · follow(person_id) · scan_area               │  │
│  │ run_policy(policy_id, params)  ◄── unified RL/LeRobot adapter        │  │
│  └- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -┘   │
└────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌────────────────────────────────────────────────────────────────────────────┐
│  L1  CONTROLLER / POLICY LAYER                                             │
│                                                                            │
│  Implemented:                                                              │
│    ComboController  RL locomotion @ 50 Hz + arm-overlay envelope           │
│    Keyframe player  static poses @ 500 Hz (g1_sim_keyboard)                │
│    Real-robot path  LocoClient + G1ArmActionClient (high-level)            │
│                                                                            │
│  ┌- - - - - - - - - - - PLANNED - - - - - - - - - - - - - - - - - - -┐    │
│  │ · LeRobot policy adapter (pick-place / locomanipulation)            │    │
│  │ · IsaacLab-trained RL policy adapter                                │    │
│  │ · Motion retargeting policy (teleop replay / imitation)             │    │
│  │ · Whole-body controller (Cartesian targets ─► joint trajectory)     │    │
│  └- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -┘    │
└────────────────────────────────────────────────────────────────────────────┘
                                       │ DDS  (sim domain=1, real=0)
                                       ▼
┌────────────────────────────────────────────────────────────────────────────┐
│  L0  HARDWARE / SIM LAYER                                       1 kHz PD   │
│                                                                            │
│   unitree_mujoco simulate_python   ◄── current default                     │
│        │                                                                   │
│        └─►  rt/lowcmd · rt/lowstate · rt/sportmodestate · rt/secondary_imu │
│                                                                            │
│   Real Unitree G1 PC2  ◄── swap target (DDS domain 0)                      │
│                                                                            │
│  ┌- - - - - - - - - - - PLANNED - - - - - - - - - - - - - - - - - - -┐    │
│  │ unitree_sim_isaaclab  for manipulation / pick-place rehearsal       │    │
│  │ ROS2 action transport (g1_msgs/ExecuteSkill.action)                 │    │
│  └- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -┘    │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Layer-by-Layer Reference

### L7 — Human / Operator
| Channel | Status | Module |
|---|---|---|
| Voice (wake-word "Sparky" + utterance) | implemented | va-demo (`gpt-4o-transcribe`) |
| Gesture (4 mirrorable poses) | implemented | `perception/derivations.py::classify_gesture` |
| Keyboard E-stop (ESC) | implemented | `safety/estop_listener.py` |
| Demonstration / object presentation | partial | YOLO11 80-class detection |
| Joystick / Web UI / hardware E-stop | planned | — |

### L6 — Sensor Input
| Sensor | Status | Module / topic |
|---|---|---|
| MuJoCo head camera (RGB + depth) | implemented | `perception/mujoco_head_cam.py` (EGL, own thread, MJCF auto-synthesis) |
| USB / laptop camera | implemented | `perception/usb_camera.py` (teleimager or cv2) |
| Microphone (24 kHz) | implemented | `MicStream` from va-demo |
| RealSense D435/D455 | planned | — |
| ROS2 `sensor_msgs/Image` ingest | planned | — |
| Joystick / external trigger | planned | — |

### L5 — Perception
| Producer | Rate | Output to SceneStateBus |
|---|---|---|
| YOLO11 (head + usb) | 10–20 Hz | `head_detections`, `user_detections` |
| MediaPipe-Pose | 10–30 Hz | `user_pose` (33 landmarks) → gesture label |
| Ground constraint (depth cone) | 10 Hz | `clear_path`, `nearest_obstacle_m`, `nearest_person_m` |
| Mono-depth (off in sim) | n/a | reserved for real-robot when depth missing |

`SceneStateBus.snapshot()` is **the only** read path used by safety and
brain. Producers update via `update_*()`; consumers always copy. This is
the contract — do not bypass it.

### L4 — AI Reasoning (current)
- `brain/realtime_agent.py::BrainRealtimeAgent` — sub-class of va-demo
  `RealtimeAgent`; replaces SkillBackend / SafetySupervisor / system
  prompt / tool list.
- `brain/prompts.py` — system prompt forbids low-level commands and
  requires a `describe_scene` / `query_scene_state` before motion.
- `brain/scene_summary.py` — compact scene digest for the LLM.

### L4 — AI Reasoning (planned harness extension)

Seven roles of an **agent pipeline**, not a chat group. Each role owns a
discrete, testable contract.

```
┌──────────────────────────────────────────────────────────────────────┐
│ TaskUnderstandingAgent   NL utterance ─► structured intent + slots   │
│ SkillPlannerAgent        intent ─► DAG of skill nodes (pre/post)     │
│ SafetySupervisorAgent    rules + LLM judgement, veto power           │
│ PerceptionAgent          SceneState + VLM caption + RAG facts        │
│ ExecutionMonitorAgent    subscribes feedback, aborts on drift        │
│ RecoveryAgent            classified failures ─► retry / safe pose    │
│ MemoryAgent              episode store + reflection + retrieval      │
└──────────────────────────────────────────────────────────────────────┘
                              │ shared
                              ▼
            BlackboardBus (typed events: TaskGoal, SkillCall,
            SafetyVerdict, ExecutionResult, MemoryWrite)
```

Hard rules for the harness layer:
1. **SafetyAgent has the highest priority.** Any other agent's vote can
   be overridden by safety; safety cannot be overridden by any agent.
2. **No agent emits low-level commands.** They produce skill-level JSON
   that goes through the existing L3 supervisor.
3. **Memory writes are append-only.** Reflection produces *new* records,
   never mutates past ones.
4. **Every agent has a timeout.** A stuck agent must not wedge the bot.

### L4 — Long-Term Memory (planned)

Four memory kinds, each with a clear write trigger and read use:

| Kind | What goes in | Written when | Read when |
|---|---|---|---|
| Episodic | Trace of one task: utterance, plan, skills called, sensor snapshots, outcome | Task end | Reflection, debugging, "did we do X before?" |
| Semantic | Stable facts: room map, named objects, named people, locations | Operator teach-in, perception confirms | Pre-task grounding ("the couch is in the south") |
| Procedural | Successful skill sequences (recipes) | After 2+ confirmed successes | Plan reuse: "make tea" ─► recall the recipe |
| Reflective | Lessons: "do not wave while walking", "needs 1.5 m clearance" | Failure post-mortem | Plan-time rule injection, prompt augmentation |

Storage sketch:
- Structured JSON per record (id, ts, kind, payload).
- Embedding vector on a summary field (sqlite-vec / chroma — pick one).
- Retrieval policy: top-k by cosine + recency boost; safety records
  always retrieved.
- **Privacy boundary**: no raw audio, no raw video — only descriptions,
  bounding-box summaries, and explicit operator-tagged frames.

Integration points (where memory plugs into the rest of the system):
- **Pre-task RAG**: TaskPlanner queries memory for similar episodes
  before producing a DAG.
- **Post-task summarization**: ExecutionMonitor → MemoryAgent writes
  episodic + reflective records.
- **Safety augmentation**: reflective rules become first-class entries in
  the supervisor's rule engine (after operator review).

### L3 — Safety Supervisor

Today: `safety/supervisor.py` (11 rules) + `safety/state_machine.py`
(7 states) + `safety/watchdogs.py` (20 Hz) +
`safety/estop_listener.py` (independent process).

Planned extensions:
- Move rule definitions to `configs/safety_rules.yaml` (currently
  hard-coded). Operators can tighten without code changes.
- Per-skill **risk class** {low, medium, high} → drives confirmation
  policy.
- **Workspace geo-fence** — bounding box / no-go zones in a room frame.
- **Resource guards** — battery %, joint temperature, network latency
  to robot, CPU/GPU saturation.
- **Fatigue / duty-cycle** — cumulative motion budget per session.
- **Outbound privacy filter** — strip / blur faces before sending frames
  to GPT-5.5 Vision when configured.
- **Audit log** — every accept/reject with reason, joined to the
  episodic memory record.

### L2 — Skill Server
- Dispatch: `skills/skill_server.py::SkillServer.execute(tool, args)` —
  calls `safety.validate`, then `_skill_<tool>`, returns JSON dict
  including a SceneState summary.
- Tool schemas: `skills/tool_schemas.py` (JSON Schema, ~16 tools).
- Compound moves: `skills/compound_skills.py`.
- Real-robot adapters: `skills/real_robot_adapters.py`
  (LocoClient, G1ArmActionClient).

Planned skill additions: `grasp_object`, `release_object`, `pick_place`,
`handover`, `navigate_to`, `follow`, `scan_area`, and the unifying
`run_policy(policy_id, params)` adapter that lets the harness call any
trained RL / LeRobot policy as just another skill.

### L1 — Controller / Policy
- `ComboController` — RL locomotion at 50 Hz with arm-overlay envelope
  (so a wave does not destabilize gait).
- Keyframe player — 500 Hz static-pose interpolator from
  `g1_sim_keyboard`.
- Real-robot swap — `LocoClient` + `G1ArmActionClient` (high-level only;
  raw lowcmd is never exposed to higher layers).

Planned: LeRobot pick-place policies, IsaacLab-trained RL,
motion retargeting / teleop replay, whole-body Cartesian controller.

### L0 — Hardware / Sim
- `unitree_mujoco simulate_python` — current default.
- DDS topics: `rt/lowcmd`, `rt/lowstate`, `rt/sportmodestate`,
  `rt/secondary_imu` (G1).
- Real G1 PC2 — same DDS topics, domain 0 instead of 1.
- Planned: `unitree_sim_isaaclab` for manipulation, optional ROS2 action
  transport (`g1_msgs/ExecuteSkill.action`).

---

## 3. Frequency Table (load-bearing — do not violate)

| Loop | Rate | Owner | Off-limits to |
|---|---:|---|---|
| Motor PD | 1000 Hz | MuJoCo / motor controller | Python |
| Combo RL tick | 50 Hz | `ComboController._tick` | LLM, Brain |
| Keyframe player | 500 Hz | `g1_sim_keyboard.G1Controller` | LLM |
| Watchdogs | 20 Hz | `safety/watchdogs.py` | LLM |
| RobotState producer | 20 Hz | `apps/agent_main.py` | LLM |
| Camera RGB / depth | 10–30 Hz | `perception/cameras.py` | LLM |
| YOLO detection | 10–20 Hz | `perception/object_detector.py` | LLM |
| MediaPipe-Pose | 10–30 Hz | `perception/pose_detector.py` | LLM |
| SceneState fusion | 10 Hz | `scene_state/fusion.py` | LLM |
| Brain (vision tool) | 0.5–2 Hz | Realtime tool call | — |
| Brain (audio) | streaming | OpenAI gpt-realtime | — |
| E-stop poll | 50 Hz | `safety/estop_listener.py` | nobody bypasses |

---

## 4. Repository Map

```
g1_brain/
├── apps/
│   ├── agent_main.py          # process wiring (asyncio + threads)
│   ├── perception_debug.py    # live camera + detections viewer
│   ├── safety_debug.py        # FSM / rules inspector
│   ├── skill_debug.py         # skill dispatcher REPL
│   └── estop_test.py          # E-stop drill
├── brain/
│   ├── realtime_agent.py      # BrainRealtimeAgent (extends va-demo)
│   ├── prompts.py             # system prompt
│   └── scene_summary.py       # compact digest for the LLM
├── perception/
│   ├── cameras.py             # CameraHub (USB + head)
│   ├── usb_camera.py          # teleimager / cv2 source
│   ├── mujoco_head_cam.py     # EGL offscreen renderer
│   ├── object_detector.py     # YOLO11
│   ├── pose_detector.py       # MediaPipe-Pose
│   ├── depth.py               # mono-depth (off in sim)
│   ├── derivations.py         # gesture, ground constraint
│   └── runner.py              # producer threads
├── scene_state/
│   ├── types.py               # SceneState, RobotState dataclasses
│   ├── fusion.py              # SceneStateBus, RobotStateBus
│   └── __init__.py
├── safety/
│   ├── supervisor.py          # the 11 rules
│   ├── state_machine.py       # 7-state FSM
│   ├── watchdogs.py           # 20 Hz health checks
│   ├── pose_check.py          # gravity-z tipping detector
│   ├── combo_proxy.py         # subprocess fence around RL controller
│   ├── estop_client.py        # reads /tmp/g1_brain_estop
│   └── estop_listener.py      # independent ESC-key process
├── skills/
│   ├── skill_server.py        # dispatcher (~16 tools)
│   ├── tool_schemas.py        # JSON schemas
│   ├── compound_skills.py     # higher-level macros
│   ├── keyframe_extras.py     # static poses
│   └── real_robot_adapters.py # LocoClient / G1ArmActionClient
├── mock_imitation/
│   ├── auto_trigger.py        # gesture → mock_imitate
│   └── gesture_to_skill.py    # gesture label → skill
├── configs/g1_brain.yaml      # one config to rule them all
└── docs/
    ├── architecture.md        # cliffs notes (≈500 lines)
    ├── structure.md           # ← this file
    ├── how_to_run.md
    ├── extending_skills.md
    └── g1-fix-phase[1..9].md  # incident logs
```

---

## 5. Worked Example (current code path)

```
You:    Hi Sparky
[wake]  hi sparky                                # ConversationStateMachine -> LISTENING

You:    What is in front of you?
[brain] tool_call describe_scene
[safety] validate(describe_scene) -> ok          # no motion, no confirm
[skill] _skill_describe_scene
        head frame -> VisionClient (gpt-5.5)
Sparky: A red chair about 1 m ahead, floor clear.

You:    Walk forward two steps to look at it.
[brain] tool_call query_scene_state              # LLM grounds itself first
[scene] persons=0  nearest_obstacle=1.05 m  clear_path=true
[brain] tool_call walk(vx=0.18, wz=0, duration_s=0.8)
[safety] rules 1..11 pass; clamps 0.18 -> 0.18
        run_mode=active, no confirm needed
[skill] _skill_walk
        ComboController.set_command(...)
        every 0.2 s: re-read SceneState
            t=0.4 s  obstacle=0.9 m   ok
            t=0.6 s  obstacle=0.78 m  ok
        done; final_obstacle=0.7 m
Sparky: I took a small step forward.

You:    [waves]
[perc]  gesture=wave_right conf=0.88  (persisted 1.2 s)
[brain] decides to mirror
[brain] tool_call mock_imitate(wave_right)
[safety] scene check (gesture): nearest_person=1.4 m -> ok
[skill] arm_overlay queued, releases in 3.2 s
Sparky: I see you waving — waving back.

You:    Stop, please.
[brain] tool_call stop()
Sparky: Stopped. Awaiting next instruction.
```

---

## 6. Roadmap (mapped to the diagram above)

| Phase | Scope | New layers / boxes |
|---|---|---|
| ✅ P0 | Sim wakeword + voice + describe_scene + walk + gesture | L7 (voice/gesture), L6 (head+usb cam, mic), L5 (YOLO+pose+ground), L4 (BrainRealtimeAgent), L3 (11 rules + FSM + E-stop), L2 (16 skills), L1 (Combo+Keyframe), L0 (MuJoCo) |
| ◻ P1 | Harness orchestrator skeleton (Task/Plan/Safety/Monitor agents) | L4 dashed boxes (agents 1–5) |
| ◻ P2 | Long-term memory (episodic + reflective first) | L4 dashed memory subsystem |
| ◻ P3 | Safety rule engine YAML + workspace geofence + audit log | L3 dashed extensions |
| ◻ P4 | Real-robot swap (DDS domain 0, LocoClient end-to-end) | L0 swap target |
| ◻ P5 | RealSense + ROS2 image ingest | L6 dashed inputs |
| ◻ P6 | LeRobot / IsaacLab policy library via `run_policy` | L1 dashed adapters, L2 dashed skills (grasp / pick_place) |
| ◻ P7 | RecoveryAgent + MemoryAgent feedback loop | L4 agents 6–7 |
| ◻ P8 | ROS2 action transport (`g1_msgs/ExecuteSkill.action`) | L0 / L2 transport swap |

---

## 7. Hard Rules (lessons that cost us time)

1. **GL contexts are pinned to the thread that created them.**
   `MuJoCoHeadCamera` constructs its `mujoco.Renderer` inside the worker
   thread, never in `__init__`. Otherwise EGL raises `EGL_BAD_ACCESS`.
2. **DDS subscribers must outlive `ChannelFactoryInitialize`.** Construct
   `CameraHub` after the DDS factory is up, or pass
   `subscribe_dds=False` for vision-only runs.
3. **`run_mode: confirm` blocks voice control.** It needs a terminal
   y/N. Use `active` for live operation, `confirm` only for keyboard
   debugging.
4. **`recovery_hold_s` must be ≥ 5 s.** Anything shorter causes
   ENGAGED ↔ EMERGENCY_STOP flapping near the gravity-z threshold.
5. **The LLM must call `describe_scene` / `query_scene_state` before
   walking.** Enforced both by prompt (`brain/prompts.py`) and by
   safety scene-check rules (#9, #10).
6. **`mock_imitation` is currently disabled** by operator preference
   (config `mock_imitation.enabled: false`). Pose detection stays on so
   the brain can still describe the user; only the auto-suggest path is
   off. Re-enable by flipping the config — no code changes needed.

---

## 8. Pointers

- Code reading order: `scene_state/types.py` → `safety/supervisor.py` →
  `skills/skill_server.py` → `apps/agent_main.py` → `brain/realtime_agent.py`.
- Run instructions: [`how_to_run.md`](how_to_run.md).
- Add a new skill: [`extending_skills.md`](extending_skills.md).
- Why a harness layer at all: [`../../docs/harness_g1.md`](../../docs/harness_g1.md).
- Compact current-state design: [`architecture.md`](architecture.md).
