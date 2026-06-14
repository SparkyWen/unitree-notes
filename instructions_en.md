# 1. Running rl_combo in MuJoCo

Terminal 1:

```bash
conda activate agi

export MESA_LOADER_DRIVER_OVERRIDE=d3d12
export GALLIUM_DRIVER=d3d12
export MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA
export LIBGL_ALWAYS_SOFTWARE=0
export MUJOCO_GL=glfw

glxinfo -B | grep -E "OpenGL renderer|Accelerated|Device|Vendor"

cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
python unitree_mujoco.py
```

Terminal 2:

```
conda activate agi
cd ~/unitree/unitree-notes/g1_brain
set -a; source .env; set +a            # OPENAI_API_KEY etc.
python -m g1_brain.apps.agent_main --mode confirm
```



### Startup sequence (just follow these steps)

```bash
# ① Open one terminal (one is enough)
conda activate agi && cd ~/unitree/unitree-notes/g1_brain

# ② (optional but recommended) Confirm codex is present first: if it is, you get the real AI; if not, it auto-falls back to deterministic planning
which codex && codex --version

# ③ Launch the command center (this single command internally does 4 things in order — see below)
python -m g1_brain.fleet.sim.command_center --viewer
```

What `③` does **inside the process, in order** (you don't manage this — it just helps to know what you're waiting for):

1. Start **WorldSim**: both G1s enter the same `MjModel`, and the **50 Hz control thread** spins up. The terminal prints two lines of `[combo] policy engaged …` (the RL gait controllers for both robots are ready — **this is normal**).
2. Create the **codex commander**: the terminal prints `[command-center] AI brain: codex gpt-5.5 (reasoning=xhigh)`. (If codex isn't installed / not logged in, it prints "falling back to deterministic planning".)
3. Start the **web service** on a background thread, printing `[command-center] console: http://127.0.0.1:8787/   (Ctrl-C to exit)`.
4. **Pop up the MuJoCo 3D window** on the main thread (when `--viewer` is set).

```bash
# ④ Wait until the terminal prints the "console: http://127.0.0.1:8787/" line, then open it in your browser
#    (open it only after the service is up; the port defaults to 8787 and can be changed with --port)

# ⑤ Type a command into the web "AI Commander" box and press Enter. Example:
#    Have g1_a and g1_b rendezvous in the middle, then have g1_a hand patrol over to g1_b
#    The first command takes codex ~10s to think (xhigh); the page shows "Commander thinking…" — just wait it out.

# ⑥ Watch the result: in the 3D window, the two G1s really do walk toward each other and meet at the midpoint → g1_b takes over patrol, g1_a stands by;
#    the web top-down view / telemetry / event stream refresh in real time. Issue another command mid-run → it preempts immediately (newest wins).

# ⑦ Exit: close the 3D window, or press Ctrl-C in the terminal (either one stops the whole process).
```



---

# 2. Running va in MuJoCo

## 1. Launch the VA demo

### Terminal 1 — MuJoCo simulation

```bash
conda activate agi
cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
python unitree_mujoco.py
```

- After the MuJoCo viewer pops up: press `7` to **lower the G1** to the ground, press `9` to **release/disable the elastic band** (pressing `8` goes the other way and hoists it back up — generally not needed during debugging).
- You're good once the G1's feet are on the ground and the policy takes over and keeps it standing (with slight ankle adjustments).
- In the window you can drag with the mouse to rotate the view and scroll to zoom; after a fall, press `Backspace` once to reset the simulation state.

### Terminal 2 — TeleImager image server

#### ==First attach the camera into WSL2==

Make sure the WSL2 Ubuntu window is already open, then run this in PowerShell:

```powershell
usbipd attach --wsl --busid 1-8
```

Check again:

```powershell
usbipd list
```

Expected state:

```text
1-8    322e:2122  USB2.0 HD UVC WebCam    Attached
```

As long as the state isn't `Attached`, there will be no `/dev/video0` inside WSL2.

```bash
conda activate agi
cd ~/unitree/unitree-notes/teleimager
python -m teleimager.image_server
```

- Binds `127.0.0.1:55555` (PUB) / `60000` (REQ) by default.
- For how to attach the camera into WSL2, see `docs/camera_ui_demo.md`.

### Terminal 3 — va-demo main process

```bash
conda activate agi
cd ~/unitree/unitree-notes/va-demo
set -a; source .env; set +a       # ← critical, loads OPENAI_API_KEY
python -m va_demo.main
```

After startup, the logs look roughly like:

```
INFO va_demo: DDS initialized: domain=1 iface=lo
INFO va_demo: waiting for ComboController policy_active ...
[combo] policy ready
INFO va_demo: run_mode=confirm
... websocket connected to wss://api.openai.com/v1/realtime ...
```

On your first run, keep the default `--mode confirm`: every `walk()` / `gesture()` prints a y/N prompt in the terminal. Once you trust it, switch:

```bash
python -m va_demo.main --mode active     # no more prompts; the model moves the moment it decides to
python -m va_demo.main --mode observe    # actions fully disabled — voice + vision only
python -m va_demo.main --mode confirm
```

#### Level 1 — confirm mode (this is the one you use for day-to-day debugging)

```bash
python -m va_demo.main --mode confirm
```

Dialogue script (**core acceptance test** — keep your eyes on the MuJoCo viewer):

| You say | Expected in terminal | Expected in the viewer |
| -------------- | ------------------------------------------------------------ | ----------------------------------------- |
| "Wave your right hand at me" | `tool: gesture(name="wave_right")`, executes automatically (gesture doesn't prompt by default) | Right-arm wave trajectory; returns compliantly to rest after a few seconds |
| "Take a step forward" | Prints `walk(...) y/N?` and waits for you to press `y` | After you press `y`, the G1 takes a step and stops/stands steady after 0.5–1.5 s |
| "Turn 90 degrees left" | safety clamps the `wz`/`duration` upper limits and rejects an over-large request | Only a small rotation actually happens, or it's rejected (check the terminal log) |
| "Throw a punch" | `gesture(name="punch_combo")` | Punch combo (identical to pressing `8` in combo) |
| "Stop" | `tool: stop()` | Velocity drops to zero, arms relax back to the policy default |

Any one of these looking wrong = the problem is in `va_demo/realtime_agent.py` (argument parsing) or the tool descriptions (`va_demo/prompts.py`) causing the model to pass odd values — check the actual tool-call arguments in the terminal log.

#### Level 2 — active mode (no prompts, fully automatic)

```bash
python -m va_demo.main --mode active
```

Only use this after you already trust the model's judgment from Level 5. The actions you see in the viewer are entirely the model's decision — **make sure the support harness can quickly restart / `Backspace` to reset / keep Ctrl-C ready**.

---



# 3. Memory Harness — full workflow

The complete way to wire the G1 into a Codex subscription for long-term memory + `ask_slow_brain`. The design lives in `docs/harness-design.md`, the spec in `g1_brain/docs/superpowers/specs/2026-05-21-g1-memory-harness-design.md`.

## 3.1 One-time setup

```bash
# 1. Codex CLI logged in (using your subscribed account)
codex login                     # opens browser, authorize, done once
codex --version                 # should print a version number

# 2. ripgrep installed (used by the fast brain's recall_grep)
which rg && rg --version | head -1
# if missing: sudo apt install ripgrep

# 3. pytest etc. available in the agi env (only for running tests; not needed to run the agent)
~/miniforge3/envs/agi/bin/python -c "import pytest, asyncio; print('ok')"
```

The `memory:` section at the end of `configs/g1_brain.yaml` defaults to `enabled: true` — no change needed.

## 3.2 Startup sequence (memory follows the agent automatically)

You only need 2 terminals to run the memory harness. **Do not also run `g1_sim_rl_combo.py` separately** — `agent_main.py` defaults to `isolate_controller=True` internally and automatically spawns a `ComboProxy` subprocess running the ComboController; if you launch `g1_sim_rl_combo.py` independently as well, two ComboControllers will fight over publishing to `/rt/lowcmd`.

```bash
# Terminal 1 — MuJoCo simulation
conda activate agi

# Use D3D12 GPU acceleration under WSL2 (skip this block on native Linux)
export MESA_LOADER_DRIVER_OVERRIDE=d3d12
export GALLIUM_DRIVER=d3d12
export MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA
export LIBGL_ALWAYS_SOFTWARE=0
export MUJOCO_GL=glfw
glxinfo -B | grep -E "OpenGL renderer|Accelerated|Device|Vendor"

cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
python unitree_mujoco.py    # press 7 to lower, press 9 to release the harness

# Terminal 2 — agent (memory enabled automatically; spawns its own ComboProxy subprocess)
conda activate agi
cd ~/unitree/unitree-notes/g1_brain
set -a; source .env; set +a            # OPENAI_API_KEY etc.
python -m g1_brain.apps.agent_main --mode confirm
```

Optional third terminal — E-stop listener (panic button; press ESC for instant zero torque):

```bash
conda activate agi
cd ~/unitree/unitree-notes/g1_brain
python -m g1_brain.safety.estop_listener
```

If you don't start it, the SafetySupervisor's software safety still works — you're just missing one independent fail-safe process.

> ⚠️ `cameras.usb.source` defaults to `teleimager`. If you don't intend to test wave / pose vision skills, the agent will continuously report `watchdog usb_frame tripped` (non-fatal; the memory harness main flow is unaffected). To silence it entirely, run `teleimager.image_server`, or set `cameras.usb.enabled` to `false` in `configs/g1_brain.yaml`.

At startup you should see this in `agent.log`:
```
memory subsystem started; root=/home/<user>/.unitree/g1_brain
codex daemon ready (tool=codex)
memory: injected N chars of passive context     # N=0 on first enable; there's content only after Phase2 has run once
```

---



# 4. Using `run_sim.sh` instead of manual exports under WSL2

That blob of `export MESA_LOADER_DRIVER_OVERRIDE=...` from Terminal 1 in §1 / §2 / §3 no longer needs to be typed by hand — `unitree_mujoco/simulate_python/run_sim.sh` bundles it, plus three extra environment variables that mitigate WSL2 stutter.

## 4.1 The new launch method

**Terminal 1 (sim):**

```bash
conda activate agi
cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
./run_sim.sh
```

**Terminal 2 (agent):** unchanged, word for word.

```bash
conda activate agi
cd ~/unitree/unitree-notes/g1_brain
set -a; source .env; set +a            # OPENAI_API_KEY etc.
python -m g1_brain.apps.agent_main --mode confirm
```

The order is still "sim first, then agent" — the agent immediately looks for robot state on DDS at startup, and if the sim isn't up it gets no data on the very first frame.

## 4.2 What's baked into `run_sim.sh`

The last line, `exec python unitree_mujoco.py "$@"`, is what actually does the work; everything before it is `export`s. Two groups:

**Group one: what you used to export by hand (identical to Terminal 1 in §1 / §3)**

```
MESA_LOADER_DRIVER_OVERRIDE=d3d12
GALLIUM_DRIVER=d3d12
MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA
LIBGL_ALWAYS_SOFTWARE=0
MUJOCO_GL=glfw
```

Without this group you fall back to llvmpipe CPU software rendering and the viewer is genuinely laggy.

**Group two: the new WSL2 viewer-stutter mitigation added this round**

```
vblank_mode=0          # turn off Mesa-side vsync to avoid stacking two layers with WSLg's compositor pacing
mesa_glthread=true     # GL commands are submitted on a Mesa worker thread, so viewer.sync() returns faster
LP_NUM_THREADS=4       # cap Mesa's internal threads so it doesn't fight the agent for cores
```

A/B measurements drop the p99 / max of `viewer.sync()` from ~10 ms to ~6 ms (**the median is unchanged — it cuts the tail latency**, which is exactly the metric that corresponds to perceptible "stutter"). The full diagnosis is in `g1_brain/docs/performance-optimization-GPU.md §5`.

## 4.3 Compared to the old manual run, is any functionality missing?

**No functionality is lost.** The sim process is functionally equivalent to running `python unitree_mujoco.py` as before:

- Same viewer window (`7` to lower / `9` to release the harness / `Backspace` to reset all work the same)
- Same physics, same DDS output
- `exec` replaces the process, so Ctrl-C behaves identically
- Command-line arguments pass through (`./run_sim.sh --foo` is forwarded verbatim to python)

Only three details are worth being explicit about:

1. **The physics rate didn't change — only the viewer redraw got slower.**
   In `config.py`, `VIEWER_DT` going from 0.02 → 0.033 is the **redraw period of the viewer window**, not the physics rate. `SIMULATE_DT = 0.005` (200 Hz) is unchanged.
   - The joint states, IMU, and camera data the agent receives are unchanged in rate; the DDS side notices nothing
   - The only change: the viewer image goes from "target 50 fps, actual jumping 25–50" → "target 30 fps, steady ~30"
   - After installing the Windows-side settings in §5.4, if you want 50 fps back, just set `VIEWER_DT = 0.02` in `config.py`

2. **`mesa_glthread=true` is newly introduced.**
   It's safe for MuJoCo viewer's single-threaded GL-call pattern; but if you see **texture corruption, missing geometry, or flickering**, comment out that line in the script. This kind of bug is state-dependent and may only surface on long runs / scene switches.

3. **The script does not do two things for you:**
   - It doesn't activate conda — you must `conda activate agi` first
   - It doesn't cd — you must `cd` into `simulate_python/` first, or `python unitree_mujoco.py` won't find the file

## 4.4 How this slots into §1 / §2 / §3

Replace **everything in Terminal 1** from the three chapters above (from `export ...` through `python unitree_mujoco.py`) with:

```bash
conda activate agi
cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
./run_sim.sh
```

All other terminals (agent / teleimager / estop / va_demo main process) stay the same.

---



# 5. Running the phone bridge in MuJoCo (Twilio + Realtime)

Teleoperate the robot over the phone. The flow once it's wired up: you dial the Twilio number → Twilio Media Streams travels over the reverse tunnel → lands on local `g1_brain/phone/bridge_server.py` → bridges to OpenAI Realtime → the model understands what you say → calls tools like `gesture` / `walk` / `stop` → the existing safety supervisor + vision risk gate + SkillServer → DDS → the G1 in MuJoCo actually moves.

The detailed design is in `mcp_twilio_design.md`, the implementation plan in `docs/superpowers/plans/2026-05-24-twilio-phone-bridge.md`, and the VPS reverse tunnel is kept alive by the systemd-user unit `sparkytun-tunnel.service`.

## 5.1 One-time setup (do once)

```bash
# 1. Write Twilio + public bridge URL into .env (gitignored)
cd ~/unitree/unitree-notes/g1_brain
# Write TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_FROM_NUMBER /
# PUBLIC_BRIDGE_URL / PHONE_ALLOWED_CALLERS into .env
# Reference: g1_brain/.env.example

# 2. Verify the Twilio credentials
set -a; source .env; set +a
python -m g1_brain.phone.call_me --dry-run
# Expected: Twilio credentials valid; account: <your account friendly name>

# 3. Verify the reverse tunnel is alive
systemctl --user is-active sparkytun-tunnel    # should print active
curl -i https://twilio.openproduct.cn/healthz  # returns 502 when the bridge isn't running (normal)
```

## 5.2 Startup sequence

You need 3 terminals (estop is an optional 4th). **In the phone scenario, `--mode active` is mandatory** — you're on a call and can't go press y/N in a terminal, so confirm mode is unusable; safety falls back to §10's Rule 12 (vision_risk_gate).

### Terminal 1 — MuJoCo simulation

```bash
conda activate agi
cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
python unitree_mujoco.py
```

After the viewer pops up: press `7` to lower the G1, press `9` to release the elastic band. You're good once the G1 stands steady.

### Terminal 2 — E-stop listener (recommended but optional)

```bash
conda activate agi
cd ~/unitree/unitree-notes/g1_brain
python -m g1_brain.safety.estop_listener
```

`ESC` triggers the E-stop; afterward any motion tool is rejected by Rule 11, and the model will tell you over the phone "Emergency stop engaged".

### Terminal 3 — brain + phone bridge (the full pipeline)

```bash
conda activate agi
cd ~/unitree/unitree-notes/g1_brain
set -a; source .env; set +a
python -m g1_brain.apps.agent_main --enable-phone --mode active
```

Wait until you see these two lines before proceeding:

```
... INFO g1_brain: combo policy active
... INFO g1_brain: phone bridge listening on 127.0.0.1:8787
```

Note that the `phone bridge listening` line only appears after all perception/yolo/vision-gate initialization completes — roughly 60 seconds from pressing Enter on `python ...` to the bridge actually listening. Call before that and Twilio gets a 502, then hangs up after 1 second.

## 5.3 Placing a call

Two ways, pick either.

### Method A — dial directly from the CLI

```bash
conda activate agi
cd ~/unitree/unitree-notes/g1_brain
set -a; source .env; set +a
python -m g1_brain.phone.call_me
# Dials PHONE_ALLOWED_CALLERS[0] by default; or specify explicitly with --to +61...
```

After it outputs `call placed; CallSid=CA...; To=+61...`, your phone rings in about 3 seconds.

### Method B — say "Hi Sparky, call me" locally

T3 is already running with the mic open. Say "Hi Sparky", wait for `wake heard` in the log, then say "call me" (or "给我打电话"). The local Realtime sees the `start_phone_call` tool, calls it → automatically picks `PHONE_ALLOWED_CALLERS[0]` and dials.

**Safety note**: the model can only dial numbers on the `PHONE_ALLOWED_CALLERS` allowlist — this is a hard gate added after an incident on 2026-05-24, when wake-word ASR misheard `+6848` as `+6888` and ended up calling an Australian stranger for 3 minutes. Now, even if ASR errs, the dial is rejected by SkillServer and returns `not in allowed callers`.

---

# 6. Fleet shared world + RL real gait + AI commander (rendezvous / relay · real-time command center)

§7 is "two independent MuJoCo worlds + DDS dual-process" — the two robots can't see each other. §8 is the **single shared world** route added this round: **two G1s walk in the same MuJoCo world (one window) using a real RL gait and perceive each other**, driven by an **AI commander that accepts natural language** (OpenAI, or the **codex brain** in §8.4) that delegates a sub-agent to each robot to accomplish **rendezvous / relay** coordination. The newest addition, **§8.4 AI command & dispatch center**, turns this line into a **real-time interaction**: type in the browser → codex plans → robots actually move in the 3D window → you can preempt mid-run (newest command wins).

Design doc `docs/superpowers/specs/2026-06-07-fleet-shared-world-rl-coordinator-design.md`; plans `docs/superpowers/plans/2026-06-07-fleet-shared-world-p1.md` + `2026-06-07-fleet-coordinator-p2.md`.

Key differences from §7:

- **One world, one window**: `MjSpec.attach` merges both G1s into one `MjModel`, with truly shared physics (they actually collide when close) + neighbor perception; no more two domains, two windows.
- **Real gait**: movement uses an RL velocity-tracking policy (reusing `g1_sim_demo`'s `ComboController`, driven directly without DDS), not posing while suspended from a harness.
- **Layered AI dispatch**: `FleetCommander` (NL → multi-robot plan) → per-robot `RobotSubAgent` (→ op sequence) → deterministic `RendezvousBarrier` (rendezvous sync); auto-falls back to deterministic planning when there's no `OPENAI_API_KEY`.

## 6.1 Watch the rendezvous / relay demo (recommended to run this first) ★ New GUI

One natural-language sentence → the AI commander decomposes it → two sub-agents each plan → the two G1s walk to the middle and meet in **the same window** → barrier sync → patrol token a→b:

```bash
conda activate agi && cd ~/unitree/unitree-notes/g1_brain
python -m g1_brain.fleet.sim.scenario_rendezvous --viewer
# Custom command: --nl "Have g1_a and g1_b rendezvous in the middle, then have g1_a hand patrol over to g1_b"
```

In one MuJoCo window you'll see: the two G1s walk toward each other with a real gait to the midpoint (keeping a safe gap, no collision) → g1_b takes over and starts patrolling (small circle in place), g1_a stops and stands by.

**Headless auto-acceptance** (no window, for CI; prints `ALL CHECKS PASSED` at the end):

```bash
MUJOCO_GL=egl python -m g1_brain.fleet.sim.scenario_rendezvous
```

Expected ending (all 9 items pass):

```
[commander] hand off patrol after rendezvous [relay] handoff g1_a -> g1_b
[subagent g1_a] navigate -> await_barrier -> idle
[subagent g1_b] navigate -> await_barrier -> patrol
=== VERIFICATION (rendezvous / relay) ===
  [PASS] rendezvous barrier fired (both arrived)
  [PASS] g1_b patrolling after handoff / g1_a idle / both upright / no collision
=== ALL CHECKS PASSED ===
```

## 6.2 Just watch the shared world itself (two G1s walking in the same window) ★ New GUI

No AI — go straight to watching "two G1s walk to the midpoint in one world":

```bash
conda activate agi && cd ~/unitree/unitree-notes/g1_brain
python -m g1_brain.fleet.sim.shared_world_node --viewer
# Headless smoke test (prints both robots' final pose / gz / gap):
python -m g1_brain.fleet.sim.shared_world_node --seconds 9
```

> Under WSL2 the window goes through WSLg display (same as §7.5's GUI). On-screen GL defaults to `glfw`; for headless use `MUJOCO_GL=egl`. The RL policy runs on `onnxruntime` CPU, no extra GPU needed. If the window won't open it's a display issue (not this code) — troubleshoot the same way as §7.3.

## 6.3 AI commander chat (dashboard / API)

The coordinator web page (`GET /` from §7.3) gains a new **"AI Commander" chat card**: type a natural-language command and it returns the commander's multi-robot plan + each robot's sub-agent op sequence. You can also hit the API directly:

```bash
curl -s -X POST http://127.0.0.1:8090/chat -H 'content-type: application/json' \
  -d '{"nl":"Both robots rendezvous in the middle, then g1_a hands patrol to g1_b"}' | python -m json.tool
```

With no `OPENAI_API_KEY` it uses the deterministic planner (keywords + snapshot); with a key set it goes through OpenAI (same op syntax, same validation).

> ⚠️ Boundary (updated): this chat card (§8.3, coordinator web page) only returns **the commander's decision (plan + ops)**, and it's wired to the DDS registry. For "type in the web page → the shared-world robots actually move", see **§8.4 AI command & dispatch center** below — it connects WorldSim + 3D window + web page + codex commander + preemptive execution in a single process.

## 6.4 AI command & dispatch center (watch live + command live + drive for real) ★ New GUI

This connects the "not-yet-wired" line from §8.3: **one process** simultaneously starts **WorldSim (§8.2's shared world) + the MuJoCo 3D window + the web console**, with the **codex brain** acting as commander. Type in the browser → codex plans → sub-agents expand ops → `LiveExecutor` **preemptively** drives the live WorldSim (newest command wins), robots move in the 3D window, and the web top-down view / telemetry / event stream update in real time.

> This round (`feature/multi-geo`) adds three things, detailed in "Web UI + complete natural-language command guide" below: ① **natural-language position control** — coordinates / named landmarks / relative motion / multiple robots together, **usable without codex**; ② **demo scene** — the flat arena has obstacles placed in it + a gentle-terrain test strip, and navigation **automatically routes around obstacles**; ③ **solo mode `--solo`** — start only one G1, convenient for testing a single robot's behavior. `--viewer` includes this scene by default (`--scene demo`).

### Key mental model (read first, save yourself a detour)

**§6.4 is a single process that brings its own entire world.** Completely different from §7's "6 terminals + DDS dual-process" — here you **only need one terminal and one command**. You **do not** need to do any of the following first:

- ❌ No need to start §1's `unitree_mujoco.py` first (it builds its own shared world on the fly with `MjSpec.attach`).
- ❌ No need to start §6.2's `coordinator` first (only §8.3's chat card depends on the coordinator; §8.4 does not).
- ❌ No need for DDS / `robot_node` / domain setup (§8.4 drives an in-memory world directly, not over DDS).
- ❌ No need for `OPENAI_API_KEY` / `.env` (the commander uses **codex**, not the OpenAI API).
- ❌ You don't even **need codex**: **position / landmark / relative / multi-robot / formation (circling · face-to-face · raise arms) / rendezvous / relay** — these common commands work even with `--no-codex` (via the in-process deterministic parser). **Only "arbitrary free-form phrasing"** needs the codex brain. See [Web UI + complete natural-language command guide] below for details.

One command in, and it **brings everything up in order by itself**.

### Prerequisites (one-time; basically already in place)

1. conda `agi` env (§1.1).
2. `codex` logged in (your ChatGPT account, `~/.codex/config.toml` already set to `gpt-5.5`). If you don't want codex, add `--no-codex` for deterministic planning.
3. `--viewer` requires a window → WSLg display working (same as §7.5 / §8.2). No display → use headless (see below).

### Startup sequence (just follow these steps)

```bash
# ① Open one terminal (one is enough)
conda activate agi && cd ~/unitree/unitree-notes/g1_brain

# ② (optional but recommended) Confirm codex is present first: if it is, you get the real AI; if not, it auto-falls back to deterministic planning
which codex && codex --version

# ③ Launch the command center (this single command internally does 4 things in order — see below)
python -m g1_brain.fleet.sim.command_center --viewer
```

What `③` does **inside the process, in order** (you don't manage this — it just helps to know what you're waiting for):

1. Start **WorldSim**: both G1s enter the same `MjModel`, and the **50 Hz control thread** spins up. The terminal prints two lines of `[combo] policy engaged …` (the RL gait controllers for both robots are ready — **this is normal**).
2. Create the **codex commander**: the terminal prints `[command-center] AI brain: codex gpt-5.5 (reasoning=xhigh)`. (If codex isn't installed / not logged in, it prints "falling back to deterministic planning".)
3. Start the **web service** on a background thread, printing `[command-center] console: http://127.0.0.1:8787/   (Ctrl-C to exit)`.
4. **Pop up the MuJoCo 3D window** on the main thread (when `--viewer` is set).

```bash
# ④ Wait until the terminal prints the "console: http://127.0.0.1:8787/" line, then open it in your browser
#    (open it only after the service is up; the port defaults to 8787 and can be changed with --port)

# ⑤ Type a command into the web "AI Commander" box and press Enter. Example:
#    Have g1_a and g1_b rendezvous in the middle, then have g1_a hand patrol over to g1_b
#    The first command takes codex ~10s to think (xhigh); the page shows "Commander thinking…" — just wait it out.

# ⑥ Watch the result: in the 3D window, the two G1s really do walk toward each other and meet at the midpoint → g1_b takes over patrol, g1_a stands by;
#    the web top-down view / telemetry / event stream refresh in real time. Issue another command mid-run → it preempts immediately (newest wins).

# ⑦ Exit: close the 3D window, or press Ctrl-C in the terminal (either one stops the whole process).
```

> Memorize the order in one line: **`conda activate agi` → `python -m …command_center --viewer` → wait for the "console: http://…" line → open the browser → type a command → watch the robots move in the 3D window**. There's no other "start A first, then start B".

### Web UI + complete natural-language command guide (the core: how to use the UI to command multiple robots in NL)

This is the heart of this section — **you just type in this web page to command multiple robots in natural language**. After opening `http://127.0.0.1:8787/`, the page has four cards top to bottom:

| Card | What it shows / what you do |
|---|---|
| **Live top-down view** (top-down) | Each robot is a **colored dot + a short heading line**; **obstacles** are drawn in their real colors (red/green pillars, blue/yellow boxes, roadblocks — the low wall is the background); **landmark names** are labeled directly on the map (assembly point / top-left / top-right / bottom-left / bottom-right / terrain test zone…); a dashed circle is drawn when there's a rendezvous point; a dashed gap line is drawn between the two robots. **Since names are labeled on the map, you can command by name directly.** |
| **AI Commander** (say what you're thinking) | The **input box for typing natural-language commands** — Enter to send. The line below is `例 / examples`, common-phrasing hints; below that is the conversation log (what you said + the commander's plan / per-robot op sequence). |
| **Event stream** (dispatch / execution) | The commander's decisions + execution log refresh line by line: `commander: …[navigate]`, `g1_a arrived`, `rendezvous complete`, `g1_b takes over patrol`, `✓ mission complete`. |
| **Telemetry** (telemetry) | A live table of each robot's x / y / heading / pose. |

#### Which natural-language commands you can issue (by category, with whether codex is required)

Type Chinese or English directly into the "AI Commander" box and press Enter. **The first three of the four categories below work offline (`--no-codex`):**

**① Position control (most common · no codex needed)**

| What you want | Say this |
|---|---|
| Send a robot to coordinates | `g1_a go to 2,1` ／ `g1_a 走到 2,1` ／ `g1_a 去 -2 0` |
| Send a robot to a named landmark | `Send g1_a to the red pillar` ／ `g1_b to the assembly point` ／ `g1_a to the top-left corner` (landmark names are on the top-down view) |
| Move relative to itself | `g1_a forward 2m` ／ `g1_a back 1m` ／ `g1_a 前进 2米` |
| Multiple robots to the same place | `both go to the assembly point` ／ `all go to center` ／ `both go to the terrain test zone` |

**② Formation actions (no codex needed)**

| What you want | Say this |
|---|---|
| Circle | `both circle clockwise` ／ `circle counterclockwise for 20s` (the two robots turn in opposite directions) |
| Line up / face each other | `the two robots face each other` ／ `line up` |
| Raise arms | `raise both arms` ／ `lift both hands` |

**③ Rendezvous / relay (multi-robot coordination · the deterministic parser also understands these few phrases · steadier with codex)**

| What you want | Say this |
|---|---|
| Rendezvous | `both robots rendezvous in the middle` |
| Hand off patrol after rendezvous | `Have g1_a and g1_b rendezvous in the middle, then have g1_a hand patrol to g1_b` |

**④ Arbitrary free-form phrasing (needs the codex brain)**

When codex is online, you can freely combine the actions above and phrase them more naturally (e.g. `g1_a go check the top-right corner first, then come back and rendezvous with g1_b`). With `--no-codex`, only the fixed phrasings in ①②③ above are recognized; anything it can't parse returns `cannot execute / needs clarification`.

#### How to command one robot vs. all robots together

- **Target a specific robot**: write the robot name `g1_a` / `g1_b` in the sentence (e.g. `g1_a go to 2,1` moves only g1_a).
- **Command together**: use "both / all / both of them / all / both" (e.g. `both go to the assembly point` moves both).
- **Only one target, no robot name, and there are two robots** → treated as **ambiguous**; the offline parser **doesn't guess** and hands it to the rendezvous/relay commander (to avoid moving the wrong one). In solo mode (`--solo`) with only one robot, omitting the name defaults to that one.

#### How the commander decides internally (routing — just so you know)

Browser Enter → `POST /command` → `plan_mission` tries in order:

1. **codex present** → let codex orchestrate each robot's ops directly (most free);
2. otherwise → **offline position parsing** (coordinates / landmark / relative / multi-robot → `navigate`);
3. otherwise → **deterministic formation** (circle / face-to-face / raise arms);
4. otherwise → **rendezvous / relay commander** (rendezvous / relay, with barrier sync).

Once matched, it's handed to `LiveExecutor` to drive the live world **preemptively** — **issuing another command mid-run takes over immediately (newest wins)**, robots move in the 3D window, and the top-down view / event stream / telemetry refresh in sync.

> **The little obstacle-avoidance ↔ rendezvous mechanism**: navigation **routes around static obstacles** (pillars / boxes / roadblocks) by default, and also **dodges the other robot**; but once it enters the **rendezvous / face-to-face** phase, it **automatically turns off "dodge the other one"**, so the two robots can still actually press together to complete the rendezvous.

#### Demo scene / obstacles / terrain (`--viewer` includes it by default)

- **Default `--scene demo`**: a flat arena with **obstacles to route around** (red / green pillars, blue / yellow boxes, roadblocks — the low wall is the background) + a **gentle-terrain test strip** (along +X: ~10° slope + low undulation + a low step, the robot can walk up it).
- **Test a single robot**: add `--solo` (starts only g1_a; web page / scene are the same). Example: after `--viewer --solo`, issue `g1_a go to the terrain test zone` to watch it cross the slope, and `g1_a go to the red pillar` to watch it route around the obstacle.
- **Back to a bare floor**: `--scene bare` (the clean flat ground like §8.1/§8.2).
- **Performance**: obstacles / terrain are all **static primitives** (box / cylinder, **no height field / mesh / extra light sources, 0 added degrees of freedom**), with almost zero extra overhead for WSL2 software rendering (measured demo scene ~2 ms/step, far below the 50 Hz 20 ms budget).

> Want a one-page quick reference (without the details above): `docs/command-center-arena-how-to-use.md`.

### Common switches

```bash
--scene demo|bare          # arena scene: demo=obstacles+gentle terrain (default), bare=clean flat ground
--solo                     # start only one robot, g1_a, to test a single robot's behavior
--no-codex                 # don't call codex; use deterministic parsing (offline, most responsive; understands position/landmark/relative/multi-robot/formation/rendezvous-relay, can't parse free-form phrasing)
--reasoning low|medium|high|xhigh   # codex thinking effort (default xhigh; for more responsiveness use low)
--model gpt-5.5            # codex model (default; codex's built-in gpt-5.3-codex is unavailable on the ChatGPT plan, so we always pass gpt-5.5 explicitly)
--port 8787 --host 127.0.0.1
```

### Troubleshooting (by symptom)

- **3D window won't pop up**: display issue (WSLg), unrelated to this code; either fix the display, or **drop `--viewer`** and use the web page alone (for headless, set `MUJOCO_GL=egl`).
- **Browser won't open**: you opened it before the "console: http://…" line appeared; or the port is taken — switch with `--port`.
- **Commander only recognizes fixed phrasings (can't parse free sentences)**: it fell back to deterministic parsing (position / landmark / relative / multi-robot / formation / rendezvous-relay all still work, but arbitrary free-form doesn't). To get free-form phrasing, bring codex online: check the terminal for `AI brain: codex …`; if absent, run `which codex` / check the login. Conversely, for pure offline and most responsive, just use `--no-codex`.
- **Issued "go to a landmark" but it says it doesn't recognize it**: the landmark name must match what's labeled on the top-down view (assembly point / top-left / red pillar / terrain test zone…); use `go to 2,1`-style `x,y` for coordinates. `--scene bare` has no obstacles / landmarks, so naturally it won't recognize landmark names (just use coordinates).
- **"Both go to the same point" but they don't press together**: `both go to the assembly point` navigates each independently to the same point, and obstacle avoidance stops them at about a 0.7 m gap (no overlap); for a true pressed-together rendezvous, use `both robots rendezvous in the middle` (goes through the rendezvous barrier, which auto-disables mutual dodging during the rendezvous phase).
- **The first command is very slow**: codex `xhigh` is genuinely thinking, this is normal (~10s); for responsiveness use `--reasoning low` or `--no-codex`.

### Headless auto-acceptance (no window, CI; POST a command to drive real physics through rendezvous-relay)

```bash
python -m pytest -m slow tests/fleet/test_command_center_e2e.py -q
```

- **AI brain = codex**: `CodexFleetLLM` (gpt-5.5 + xhigh) decomposes natural language into a FleetPlan; on a codex error / no `codex` binary it auto-falls back to deterministic planning. Sub-agents always expand ops deterministically (only NL→plan goes through codex).
- **Preemption**: issue another command while the robot is still executing the previous one, and the newest command takes over immediately (generation counter; the old task stops itself).

## 8.5 Key file map (added in §8)

| File | Responsibility |
|---|---|
| `fleet/sim/shared_world.py` | `MjSpec.attach` merges the two G1s into one `MjModel` + per-robot slicing + PD recompute every substep + neighbor perception + adds static obstacles/terrain by `scene=` |
| `fleet/sim/scene.py` | Scene registry (single source of truth): obstacle/terrain geometry + named landmarks (coords ↔ names) for `demo`/`bare`/`solo`; shared by world geometry / top-down view / NL parsing / codex snapshot |
| `fleet/sim/rl_adapter.py` | Reuses `ComboController` without DDS (feeds a fake LowState + intercepts `_publish`) to run the RL velocity policy |
| `fleet/sim/nav.py` | Position→velocity navigation outer loop (clamped to the policy command range to prevent OOD) + reactive obstacle avoidance (routes around obstacles / the other robot) |
| `fleet/agent/motion/rl_shared_backend.py` | Shared-world single-robot MotionBackend (navigation / PATROL small circle / IDLE) |
| `fleet/sim/shared_world_node.py` | World Sim process: 50 Hz isolated control thread + optional viewer (§8.2) |
| `fleet/coordinator/{fleet_plan,fleet_commander,robot_subagent,barrier}.py` | AI commander decision layer: FleetPlan + NL decomposition (OpenAI + fallback) + per-robot sub-agent + deterministic rendezvous barrier |
| `fleet/sim/scenario_rendezvous.py` | End-to-end rendezvous/relay orchestration + acceptance (§8.1) |
| `fleet/coordinator/app.py` `POST /chat` | Layered dispatch entry point for the dashboard/API (§8.3) |
| `fleet/sim/command_center.py` | AI command & dispatch center: WorldSim + 3D window + web console + codex commander, all in one launch (§8.4) |
| `fleet/sim/live_executor.py` | Preemptive op executor (newest command wins), driving the live WorldSim (§8.4) |
| `fleet/coordinator/codex_fleet_llm.py` | Wires the codex brain in as the FleetCommander's LLM (`plan_fleet`, gpt-5.5 + xhigh) |
| `fleet/coordinator/nl_position.py` | Offline NL→position parsing (coords/landmark/relative/multi-robot → `navigate`); falls back to the commander on formation/rendezvous/relay words; makes position control **not depend on codex** |
| `fleet/coordinator/choreographer.py` | NL routing `plan_mission`: codex → offline position parsing → deterministic formation → rendezvous/relay commander |
| `fleet/sim/command_center_ui.py` | The console web page: live top-down view (with obstacles/landmarks) + chat (with example-phrase hints) + event stream + telemetry |

> Key engineering point: when the RL velocity policy is driven inside a hand-written MuJoCo loop, **the PD torque must be recomputed every physics substep (200 Hz) using the latest q/dq** — not set once per 50 Hz control tick — otherwise the torque is stale → oscillation → falling over. This is the dividing line between the robot "flying around erratically" and "walking steadily".
