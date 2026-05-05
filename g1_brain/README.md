# g1_brain

Slow Brain + Fast Reflex + Safe Skill agent for the Unitree G1 humanoid,
running first against the MuJoCo simulator. Architecture and full design:
[`../docs/g1_plan.md`](../docs/g1_plan.md).

## What this is

A new top-level package that **imports** (does not modify) the existing
`va-demo/` (Realtime audio + GPT-5.5 vision) and `g1_sim_demo/` (RL combo
controller + keyframe library) demos, and adds three new layers on top:

1. **Perception (Fast Reflex)** — dual cameras (USB user-facing via
   teleimager + MuJoCo first-person head cam, EGL-rendered offscreen,
   camera synthesized onto `torso_link` when the MJCF doesn't ship
   one), YOLO11, MediaPipe-Pose, depth, fused into a `SceneState`.
2. **Safety** — extended SafetySupervisor with 11 validation rules, a
   7-state FSM, and an independent E-stop process.
3. **Skills** — ~16 LLM-callable tools covering walk, turn, gesture,
   static pose, look_at, approach, mock_imitate, stop, release_arms,
   say, describe_scene, query_scene_state.

## Install

```bash
conda activate agi    # the env that already has unitree_sdk2py + va-demo deps
cd ~/unitree/unitree-notes/g1_brain
pip install -e .
```

YOLO11 weights download automatically on first run (~22 MB to
`~/.config/Ultralytics/`).

## Run (4 terminals)

See [`docs/how_to_run.md`](docs/how_to_run.md) for details.

```bash
# Terminal 1: MuJoCo
conda activate unitree
export MUJOCO_GL=glfw
cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
python unitree_mujoco.py
# G1 lands on the floor immediately (ELASTIC_BAND_INIT_LENGTH=2.0
# leaves the band slack at standing height); press '9' to toggle the
# band off entirely, '7' / '8' to nudge length by ±0.1 m.

# Terminal 2: USB camera service
conda activate unitree
cd ~/unitree/unitree-notes/teleimager
python -m teleimager.image_server

# Terminal 3: E-stop listener (independent process; press ESC to trigger)
conda activate agi
python -m g1_brain.safety.estop_listener

# Terminal 4: agent
conda activate agi
export OPENAI_API_KEY=sk-...
python -m g1_brain.apps.agent_main --mode confirm
```

## Modes

`--mode observe`  motion blocked entirely; describe_scene + say only.
`--mode confirm`  every motion tool prompts y/N in the terminal first (default).
`--mode active`   motion executes immediately within safety bounds.

`--vision-only`   skip DDS / RL controller init; talk + look only (mirrors
                  va-demo's vision-only flag).

## Layout

```
g1_brain/
├── perception/        YOLO + MediaPipe + cameras + depth + derivations
├── scene_state/       Shared SceneState/RobotState dataclasses + thread-safe bus
├── safety/            FSM + SafetySupervisor + watchdogs + E-stop
├── skills/            SkillServer + tool schemas + keyframe extras
├── brain/             Realtime agent (extends va-demo) + scene-aware prompt
├── mock_imitation/    User gesture → robot gesture mirror (Phase 5)
└── apps/              agent_main + 4 debug entries (perception/safety/skill/estop)
```

## Tests

```bash
pytest tests/ -v
```

Most tests stub out OpenAI / DDS / cameras; you can run them on any laptop.

## Reference docs

- [`../docs/g1_plan.md`](../docs/g1_plan.md) — full design (1500+ lines)
- [`../docs/vlm_audio_mock_deep.md`](../docs/vlm_audio_mock_deep.md) — research notes
- [`../va-demo/docs/video-design.md`](../va-demo/docs/video-design.md) — vision pipeline
