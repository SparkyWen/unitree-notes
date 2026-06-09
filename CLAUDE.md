# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo actually is

Despite the name "notes" and the parent-workspace CLAUDE.md describing this as "read-only clones of upstream Unitree reference repos," **this is an active development repo** (`git@github.com:SparkyWen/unitree-notes.git`, currently on `feature/multi-geo`). It contains substantial **original** G1 humanoid AI projects layered on top of **vendored** Unitree upstream repos. The vendored repos are reference-grade (read them freely, don't edit them in normal feature work); the original projects below are the actual product.

### Original work (edit these)

| Path | What it is |
|------|-----------|
| `g1_brain/` | **The flagship.** A three-layer agent for the Unitree G1: slow brain (Codex daemon) + fast reflex (OpenAI Realtime voice loop) + safe skill layer. Also hosts the **fleet** multi-robot command center. Python package is nested at `g1_brain/g1_brain/`. |
| `va-demo/` | Earlier voice+vision agent (OpenAI Realtime, "Hi Sparky" wake word). `g1_brain`'s `BrainRealtimeAgent` subclasses va-demo's `RealtimeAgent` — va-demo is the upstream of the fast brain. Package at `va-demo/va_demo/`. |
| `g1_sim_demo/` | MuJoCo control demos: RL walking policy (ONNX) + keyboard-triggered arm gestures. `g1_sim_rl_combo.py` is the canonical "ComboController" the brain and fleet drive. |
| `g1_real_demo/` | Real-hardware mirror of `g1_sim_demo` (DDS, MotionSwitcher release, "lying" hardware-check mode). |
| `teleimager/` | Multi-camera ZeroMQ/WebRTC image server feeding vision agents. Package at `teleimager/src/teleimager/`. |
| `instructions.md`, `README.md`, `mcp_twilio_design.md`, `docs/` | Operational runbooks + design docs (see "Where the real docs live"). |
| `issue/` | Troubleshooting logs (DDS perms, WSL2 CPU/GPU rendering). |

### Vendored Unitree / third-party upstream (reference only — don't edit in feature work)

`unitree_sdk2_python/` (DDS Python bindings; what the brain/demos `import unitree_sdk2py` from), `unitree_mujoco/` (the MuJoCo simulator + MJCF assets in `unitree_robots/`; **everything launches the sim from `unitree_mujoco/simulate_python/`**), `unitree_rl_mjlab/` (RL training/deploy: mjlab + rsl_rl + MuJoCo Warp), plus `unitree_ros/`, `unitree_ros2/`, `unitree_sim_isaaclab/`, `unitree_lerobot/`, `xr_teleoperate/`, `unifolm-vla/`, `unifolm-world-model-action/`.

## Environments

Two Miniforge conda envs (Python 3.11) do all the work — see workspace memory and `docs/libs_compatible.md`:

- **`unitree`** — lean sim+RL stack. `mujoco` pinned to **3.5.0** for `mujoco-warp` compatibility. Runs the three core reference repos and the sim demos.
- **`agi`** — full stack: unifies `sdk2py + mujoco + rl_mjlab + teleimager + unifolm-vla` via `numpy==1.26.4`. This is what `g1_brain` and `va-demo` run under. `requirements.txt` at the repo root is a frozen snapshot of this env.

Install ordering matters (`requirements.txt` / README §Install): install `numpy==1.26.4` **first** to lock the numerical base, then the rest (pulls `torch 2.11+cu130`, `mujoco 3.5.0`, `openai`, `ultralytics`, `mediapipe`, `faster-whisper`, and the `-e ./subdir` editable installs). The SDK must be `pip install -e`'d so demos can `import unitree_sdk2py`.

### WSL2 gotchas (this machine runs under WSL2)
- **Audio:** `sounddevice`/`pyaudio` need `$CONDA_PREFIX/lib/alsa-lib` symlinked to `/usr/lib/x86_64-linux-gnu/alsa-lib` so ALSA can reach WSLg's PulseAudio.
- **Rendering:** there is no `libGL_nvidia` in WSL2. Offscreen MuJoCo on Mesa llvmpipe (CPU) is *faster* than the D3D12→NVIDIA translation. MuJoCo physics always runs on CPU regardless of GPU env vars; CUDA for torch/YOLO is fine. See `issue/mujoco_cpu_or_gpu.md`.

## Common commands

The MuJoCo simulator is the substrate for almost everything; start it first. In the viewer, the **elastic band** keys matter: `9` toggles the suspension band, `7`/`8` lower/raise it (the G1 hangs in the air until you lower the band).

```bash
# ── MuJoCo simulator (DDS bridge + viewer) ──────────────────────────
conda activate unitree
cd unitree_mujoco/simulate_python
python unitree_mujoco.py          # or ./run_sim.sh (sets WSL2 export vars for you)

# ── Sim control demo (separate terminal) ────────────────────────────
conda activate unitree
cd g1_sim_demo && python g1_sim_rl_combo.py     # RL walk + 1–8 gesture keys

# ── g1_brain fast brain (run from the OUTER g1_brain/ dir) ──────────
conda activate agi
cd g1_brain
python -m g1_brain.apps.agent_main --mode observe|confirm|active
#   debug entry points: g1_brain.apps.{perception,safety,skill,estop}_debug

# ── Fleet command center (live multi-robot sim + web console) ───────
python -m g1_brain.fleet.sim.command_center --viewer --scene demo
#   web console at http://127.0.0.1:8787 ; --solo for one robot ;
#   --no-codex for deterministic NL parser only (no LLM calls)

# ── Fleet coordinator (anomaly-driven closed-loop dispatch) ─────────
python -m g1_brain.fleet.coordinator --host 0.0.0.0 --port 8090   # dashboard at :8090

# ── va-demo (run from va-demo/) ─────────────────────────────────────
cd va-demo && python -m va_demo.main --mode observe|confirm|active
```

### Tests
`g1_brain` is the only subtree with a real suite (~100 test files, `pytest-asyncio` in `asyncio_mode=auto`). Codex subprocesses are mocked, so the green path **does not burn the LLM subscription**.

```bash
cd g1_brain
pytest                          # full suite
pytest tests/test_safety_supervisor.py            # single file
pytest tests/fleet -k rendezvous                  # fleet subset
pytest -m "not slow"            # skip the `slow` marker (real MuJoCo physics gates)
```
`va-demo/` has its own `pytest.ini`; run `pytest` from that dir.

## Architecture: g1_brain (the part worth understanding deeply)

Three layers, decoupled by a thread-safe **scene-state bus** (`g1_brain/g1_brain/scene_state/fusion.py`, the `SceneStateBus`/`RobotStateBus` snapshot pattern — producers write, consumers read immutable snapshots):

1. **Fast brain** — `brain/realtime_agent.py` (`BrainRealtimeAgent`, subclasses va-demo's `RealtimeAgent`) drives a ~100 ms OpenAI Realtime voice loop through a `conversation_state.py` FSM (IDLE→CAPTURING→THINKING→SPEAKING). All LLM tool calls funnel through `skills/skill_server.py`. Wired together in `apps/agent_main.py`.
2. **Slow brain** — `memory/daemon.py` (`CodexDaemon`) spawns a persistent `codex mcp-server` subprocess; the fast brain reaches it via an `ask_slow_brain(query)` tool. Memory is a two-phase pipeline: `phase1.py` (per-session extraction via `codex exec`) → `phase2.py` (global consolidation into `MEMORY.md`, git-committed baseline). Both brains query prior memory through the **sandboxed** `memory/recall.py` (`grep`/`read`/`glob` over two allowed roots).
3. **Safe skill layer** — `safety/supervisor.py` gates *every* tool call through an ordered rule set (whitelist → FSM state → run mode → watchdogs → pose/scene checks → param clamp → E-stop), against the 7-state FSM in `safety/state_machine.py`. The **E-stop** (`safety/estop_client.py`) runs as an *independent process* watching ESC and touching `/tmp/g1_brain_estop`; even if the agent deadlocks it publishes zero-torque lowcmd to DDS. `safety/vision_risk_gate.py` adds optional per-motion GPT vision review.

**Perception** (`perception/runner.py` → `PerceptionRunner`) owns threaded workers: `cameras.py` (MuJoCo-rendered head cam + USB cam), `object_detector.py` (YOLOv11s), `pose_detector.py` (MediaPipe gestures → `mock_imitation/`), `derivations.py` (depth→ground constraint). All publish to the scene bus.

**Fleet** (`g1_brain/g1_brain/fleet/`) is the multi-robot stack:
- `sim/command_center.py` wires a live `WorldSim` (MuJoCo @ 50 Hz) + `FleetCommander` (NL→plan) + `LiveExecutor` (preemptible mission controller) + web console (`command_center_ui.py`).
- `coordinator/nl_position.py` is a **deterministic offline NL parser** (coords / landmarks / relative / "all") tried *before* the LLM commander — positional commands need no Codex call. `fleet_commander.py` falls through to the LLM (`codex_fleet_llm.py`) for relay/rendezvous/patrol verbs.
- `sim/shared_world.py` puts multiple RL G1s in **one** MuJoCo world via `MjSpec.attach` + a reused `ComboController` (no DDS).

**Phone bridge** (`g1_brain/g1_brain/phone/`) bridges a Twilio Media Stream into a `PhoneRealtimeSession` (subclass of the fast brain). Public host + reverse tunnel; credentials in gitignored `.env` (see `g1_brain/.env.example`).

Config: `g1_brain/configs/g1_brain.yaml` (mode sim|real, run_mode, robot/mjcf, cameras, perception, the safety limits). Secrets in `g1_brain/.env`.

## Non-obvious cross-cutting facts

These cost real debugging time and aren't visible from the code:

- **PD torque must be recomputed every sim substep (200 Hz), not per 50 Hz control tick** — otherwise the shared-world RL robot oscillates and falls. This is *the* gotcha for fleet shared-world / combo control.
- **Codex model:** this ChatGPT account rejects the default `gpt-5.3-codex`. Use **`gpt-5.5`** (`reasoning xhigh` is valid) — already the default in `command_center.py`. `CodexClient` forces `--ignore-user-config`, so the model must be passed via `-m`/`model_override`. Every Codex call in g1_brain defaults to `reasoning_effort=high` + `service_tier=fast` (1.5× priority).
- **Two brains, two tool surfaces:** the fast brain uses `recall_grep`/`recall_read` skills; the slow brain (Codex daemon) has its *own* shell. Don't expose `recall_*` to Codex — they aren't its tools.
- **Head-cam ↔ sim scene coupling:** the brain's head cam clones its own `MjModel`. `robot.mjcf_path` in the config must match the scene `unitree_mujoco` loaded (e.g. `USE_TERRAIN`), or the brain perceives a different world than the operator sees.
- **MuJoCo viewer lag** is governed by the C++ `render_loop`'s per-frame cost (vsync-bound), *not* by `viewer.sync()`. Cut shadows/reflections/MSAA at the model level. (A `mjtVisFlag.mjVIS_SHADOW` toggle once crashed the viewer — fixed.)

## Where the real docs live

This repo is heavily documented — prefer reading these over re-deriving:
- `instructions.md` — the operational runbook (numbered §1–§7: run rl_combo, va, memory harness, `run_sim.sh`, phone bridge, fleet coordinator, fleet closed-loop). Largely in Chinese.
- `README.md` (root) — full install + multi-terminal launch guide (English + 简体中文).
- `g1_brain/README.md` — the brain's own architecture / skill catalog / safety rules / test guide.
- `docs/` — per-subsystem design notes: `coordinator-design.md`, `multi-architecture.md`, `harness-design.md`, `va-demo-design.md`, `terrain_how_to_use.md`, plus a `<repo>.md` note for each vendored upstream repo.

## Sibling project

The parent workspace (`/home/helios/unitree/`) also holds `cs47-command-center/` — an unrelated Electron + Express + FastAPI product with its own (gitignored) CLAUDE.md. Its robot-bridge hardcodes `~/unitree_sdk2_python/`, which is *not* this workspace's clone path — a common cross-repo startup failure noted in the workspace CLAUDE.md.
