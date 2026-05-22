# Performance optimization — GPU usage & WSL2 rendering (2026-05-22)

Captures everything that came out of the 2026-05-22 perf-debug session
on the `fix/audio-interrupt-buffer` branch: what the operator observed,
how each bottleneck was isolated with hard numbers, what code changed,
how to re-verify, and what remains as optional follow-up.

The single most important takeaway is **counterintuitive** and worth
calling out up front:

> **On WSL2 + NVIDIA, Mesa llvmpipe (CPU/SIMD) renders MuJoCo offscreen
> ~2× faster than the D3D12 NVIDIA translation layer**, because WSL2
> ships no native `libGL_nvidia.so` (`/usr/lib/wsl/lib/` has only
> `libd3d12.so` + `libcuda.so`). "Use the GPU for rendering" is the wrong
> instinct here — the GPU's there, but the only pipe to it is the slow
> D3D12 translator. CUDA itself (torch / YOLO / mediapipe-GPU) is fine.

The user's original hypothesis — "the 4060 isn't being used, that's why
it's slow" — was therefore both **right** (some things were CPU-only that
shouldn't be) and **wrong** (graphics GL is faster as CPU on WSL2). The
fix targeted CPU saturation, not GL backend swaps.

---

## 1. What the operator observed

Running `python -m g1_brain.apps.agent_main --mode confirm` against
`unitree_mujoco.py` in a sibling terminal that had
`MESA_LOADER_DRIVER_OVERRIDE=d3d12 GALLIUM_DRIVER=d3d12
MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA MUJOCO_GL=glfw` exported:

- The simulator window stuttered visibly.
- The agent_main terminal occasionally froze for ~seconds at a time;
  pressing any key on the keyboard would immediately unblock output and
  flush all backlog.
- `nvidia-smi` reported 0 % GPU utilisation; user concluded "we're not
  using the 4060".

Initial agent log excerpt confirming the rendering fallback:

```
libEGL warning: DRI3 error: Could not get DRI3 device
libEGL warning: Ensure your X server supports DRI3 to get accelerated rendering
GL version: 3.2 (OpenGL ES 3.2 Mesa 25.2.8-0ubuntu0.24.04.1), renderer: llvmpipe (LLVM 20.1.2, 256 bits)
```

That `llvmpipe` line came from MediaPipe initialising its EGL context —
not from MuJoCo — but it correctly tells us EGL on this box reaches only
software Mesa, never the 4060.

---

## 2. Investigation methodology

The instinct to "switch MUJOCO_GL or set D3D12 env vars" was rejected
until measurements existed. Phase 1 of systematic debugging was strictly
evidence-collection, no fixes.

### 2.1 Environment probe

```bash
# Without any D3D12 env vars
glxinfo -B | grep -E "OpenGL renderer|Accelerated|Vendor|Device"
#   Vendor: Mesa, Device: llvmpipe, Accelerated: no, OpenGL renderer: llvmpipe

# With the operator's D3D12 env vars
MESA_LOADER_DRIVER_OVERRIDE=d3d12 GALLIUM_DRIVER=d3d12 \
  MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA glxinfo -B | grep ...
#   Vendor: Microsoft, Device: D3D12 (NVIDIA GeForce RTX 4060 Laptop GPU),
#   Accelerated: yes, OpenGL renderer: D3D12 (NVIDIA RTX 4060)

# What ships in WSL2's library shim
ls /usr/lib/wsl/lib | grep -i 'GL\|nvidia'
#   libcuda.so, libd3d12.so, libnvidia-encode.so, libnvidia-ml.so, ...
#   NO libGL_nvidia.so / libEGL_nvidia.so
```

The third command is the smoking gun: NVIDIA's native Linux OpenGL
driver is **not** present in WSL2. Only D3D12 translation is available.

### 2.2 MuJoCo render benchmark (G1 + terrain scene, 640×480)

Two warmup-aware benchmarks of one full `update_scene + render` call
against the actual production MJCF (`scene_29dof_terrain.xml`):

| Backend (with D3D12 env if NVIDIA) | RGB ms/frame | depth ms/frame |
|---|---|---|
| **EGL Mesa llvmpipe (CPU/SIMD)** | **134.5 ms** | 27.4 ms |
| GLFW + D3D12 NVIDIA 4060 | 249.2 ms | 66.2 ms |

So switching to the GPU path makes things **slower**, not faster, for
this workload. Reason: MuJoCo's `Renderer` issues many small draw calls
per frame; Mesa's D3D12 translator pays per-call CPU overhead that
swamps the GPU savings. llvmpipe is multi-core SIMD on the host CPU and
just happens to suit this access pattern. The simulator window itself,
which batches into one buffer-swap per frame, doesn't pay the same cost
and **is** correctly GPU-accelerated through D3D12 — but that's a
different code path than the offscreen rendering g1_brain does.

### 2.3 YOLO device benchmark

```python
import torch
from ultralytics import YOLO
m = YOLO('yolo11s.pt')
img = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)

# Default 'auto' branch in old code path:
m.predict(img, device='cpu')    # 99.2 ms/inference
m.predict(img, device='cuda:0') # 13.3 ms/inference   <-- 7.5× speedup
```

Then the giveaway in `object_detector.py:59-63` (pre-fix):

```python
if device and device != "auto":
    try:
        self._model.to(device)
```

The config default `device: "auto"` therefore **never** calls `.to()`,
and `YOLO('yolo11s.pt')` defaults to CPU. So `device: "auto"` in
`g1_brain.yaml` meant `device: "cpu"` in practice, silently.

### 2.4 CPU budget audit

With everything pre-fix:

| Worker | per-call cost | rate | CPU/sec |
|---|---|---|---|
| YOLO head (CPU) | 99 ms | 15 Hz | 1485 ms = ~1.5 cores |
| YOLO usb  (CPU) | 99 ms | 15 Hz | 1485 ms = ~1.5 cores |
| head-cam RGB render | 134 ms | 20 Hz | 2680 ms = ~3 cores (across llvmpipe threads) |
| head-cam depth render | 27 ms | 20 Hz | 540 ms |
| Audio + DDS + asyncio + Realtime WS | — | — | residual |

Multiply by `LP_NUM_THREADS` default (= host core count, ~16 on this
laptop) and llvmpipe alone was free to grab every spare core. Result:
audio/asyncio callbacks starve, the Realtime websocket falls behind, the
simulator window can't keep up with its own 60 Hz step → stutter
everywhere, including in the terminal.

---

## 3. Root causes (three independent ones)

1. **YOLO silently CPU-bound.** `device: "auto"` never resolved to
   `cuda:0`, so all object detection ran on CPU. ~8× slower than
   necessary, saturating one core per source thread.

2. **MuJoCo head-cam carried two `Renderer` instances.** Originally a
   workaround for a GLX BadAccess crash when juggling two GL contexts
   from a worker thread on WSLg (see the comment block at
   `mujoco_head_cam.py:21-25`). Two renderers means two scene uploads
   per cycle. A single renderer with `enable_depth_rendering()` toggle
   reuses the same scene buffer for both passes.

3. **CPU thread sprawl unbounded.** llvmpipe + numpy/torch/Mesa each
   defaulted to one thread per host core. With multiple of them running
   simultaneously, total threads ≫ cores, kernel scheduler thrashes,
   audio callbacks deadline-miss, simulator window starves.

Plus one **non-code** issue:

4. **Windows Terminal Quick Edit Mode.** Clicking anywhere in the
   terminal window (even by accident) selects text and **pauses
   console output** until any key is pressed. Pure Windows console
   feature; no Python / WSL / repo fix applies.

---

## 4. Fixes applied (this branch)

### 4.1 YOLO device resolution
**File:** `g1_brain/perception/object_detector.py:52-72`

`device="auto"` now explicitly resolves to `cuda:0` (when
`torch.cuda.is_available()`) or `cpu`, always calls `.to(device)`, and
**also passes `device=` explicitly to every `predict()` call** because
ultralytics' internal auto-detect can otherwise drift back to CPU.
Startup logs include `yolo device: cuda:0` so future regressions are
visible in `agent.log` at line 1.

```python
resolved = device
if not device or device == "auto":
    import torch
    resolved = "cuda:0" if torch.cuda.is_available() else "cpu"
self._model.to(resolved)
self._device = resolved
log.info("yolo device: %s", resolved)
...
# In _infer:
results = self._model(bgr, conf=self._conf, verbose=False, device=self._device)
```

**Expected effect:** ~8× speedup per YOLO call (99 → 13 ms), freeing
~3 cores. nvidia-smi will now show GPU utilisation under load.

### 4.2 Single-renderer head cam
**File:** `g1_brain/perception/mujoco_head_cam.py:78-86, 273-302, 298-325`

Collapsed two `mujoco.Renderer` instances into one with depth toggle:

```python
self._renderer.disable_depth_rendering()
self._renderer.update_scene(self._data, camera=cam_arg)
rgb = self._renderer.render()
self._renderer.enable_depth_rendering()
depth = self._renderer.render()
self._renderer.disable_depth_rendering()
```

This (a) removes the two-GL-context fragility that drove the original
`MUJOCO_GL=egl` choice on WSL, (b) reuses scene-buffer upload across
RGB+depth passes, (c) halves GL state memory. Wall-clock cycle on
llvmpipe is dominated by the RGB pass (~134 ms); depth toggle adds
~27 ms, so total ~167 ms/cycle vs ~270 ms with two independent renderers.

### 4.3 Render thread niceness
**File:** `g1_brain/perception/mujoco_head_cam.py:310-317`

```python
try:
    os.nice(10)
except Exception:
    pass
```

The render thread runs inside the agent process and competes with audio
callbacks, the Realtime websocket, and asyncio. `nice(10)` keeps it as a
fully working thread but lets the kernel preempt it whenever audio /
asyncio actually need a slot. Best-effort — silently no-ops on platforms
that reject the syscall.

### 4.4 Head-cam poll rate 20 → 10 Hz
**File:** `g1_brain/configs/g1_brain.yaml:59-68`

The vision LLM is called at most every few seconds; ground watchdog
runs at ~5 Hz; the LLM's `describe_scene` tool can wait. 10 Hz halves
render CPU with no observable downstream regression. Inline comment in
the YAML documents the WSL2 reasoning so future operators don't crank
it back up assuming it was a tuning oversight.

### 4.5 Bound the thread pools at process start
**File:** `g1_brain/apps/agent_main.py:18-29` (above all other imports)

```python
import os as _os
_os.environ.setdefault("LP_NUM_THREADS", "3")    # llvmpipe
_os.environ.setdefault("OMP_NUM_THREADS", "3")   # numpy/scipy
_os.environ.setdefault("MKL_NUM_THREADS", "3")   # MKL
_os.environ.setdefault("PYTHONUNBUFFERED", "1")  # defensive flush
```

Crucially placed **above** any other import, because thread-count env
vars are read by numpy / mujoco / torch at first import and cached. Set
them after the fact and they're ignored.

`PYTHONUNBUFFERED=1` is defensive — Python logging is already
line-buffered on a TTY, but if any subprocess pipes stdout into a logger
the env var keeps it flowing.

---

## 5. Simulator viewer-window stutter (the *second* perf round, 2026-05-22 PM)

After the §4 fixes landed the operator confirmed that the agent terminal,
voice, and overall system feel fluid — but the `unitree_mujoco.py`
viewer window itself still stutters (robot/camera movement jerky).
That's a different bottleneck than what §4 addressed: it lives inside
the simulator process (PID separate from agent_main), in the GL/D3D12
viewer thread, and changing agent-side code can't reach it.

### 5.1 What the bench data actually shows

`viewer.sync()` (the GL submit call inside `PhysicsViewerThread`) is
**fast** under WSL2 + D3D12 NVIDIA — and faster than the original §2
benches suggested for offscreen rendering:

```
G1+terrain scene, D3D12 NVIDIA, viewer window foregrounded:
  viewer.sync() n=80: p50=5.0ms p95=5.3ms max=5.9ms mean=5.0ms
  (with concurrent 200 Hz physics thread holding shared lock):
  lock-wait p50=0.00ms p95=0.19ms max=0.73ms
  sync()    p50=4.63ms p95=5.68ms max=11.41ms
```

So the GL submit is ~5 ms and the physics-vs-viewer lock contention is
~zero. With `VIEWER_DT = 0.02` (20 ms sleep) plus ~5 ms sync, the
viewer thread should run at ~40 fps consistently. The user still
perceives stutter.

### 5.2 The root cause is past sync()

`viewer.sync()` only posts commands to the **front** of the pipeline.
The full path before pixels reach the screen is:

```
Mesa GL  →  D3D12 translator  →  DXGI present  →
WSLg Wayland compositor  →  Hyper-V graphics relay  →  Windows desktop
```

The API-level bench only measures the first hop. The remaining hops
each have their own pacing/buffering that the WSL guest can't observe
or control from Python. On native Linux these don't exist — `glXSwapBuffers`
goes straight to the X server which goes straight to the display
controller. WSLg trades that simplicity for cross-OS portability and
inherits a frame-pacing tax we have to live with.

Confirmed via `nvidia-smi --query-compute-apps`:
* sim process (PID 17013) shows as **Type G** (graphics) — discrete
  4060 IS engaged, not running on integrated graphics
* GPU memory ~762 MiB used by sim+agent combined
* GPU utilisation 33-34 % under load (plenty of GPU headroom available)

So it's not "GPU underused" or "wrong adapter" — it's pipeline pacing.

### 5.3 What was changed to reduce the stutter

**File:** `unitree_mujoco/simulate_python/config.py`

```python
VIEWER_DT = 0.033   # was 0.02 -- 30 fps target instead of 50 fps
```

WSLg can't sustain 50 fps consistently for this scene; variable
25-50 fps timing feels stuttery, constant ~30 fps feels smooth. Frame
**consistency** matters more than peak rate for perceived smoothness.
Drop back to 0.02 if the operator has every other knob tuned and a
fast Windows-side setup.

**File:** `unitree_mujoco/simulate_python/run_sim.sh` (new, executable)

Bundles the D3D12 env vars the operator was setting by hand plus three
new stutter-reduction tweaks:

| Env var | Effect |
|---|---|
| `vblank_mode=0` | Disable Mesa-side vsync. WSLg has its own compositor pacing; two layers of vblank waiting stack and stutter. With Mesa vsync off, frames present as soon as D3D12 finishes. |
| `mesa_glthread=true` | Submit GL commands from a Mesa worker thread instead of the caller. Each call pays a D3D12 translation tax; offloading hides it from `viewer.sync()`. |
| `LP_NUM_THREADS=4` | Cap Mesa's internal threading so it doesn't compete with the agent process if both are running on the same machine. |

Measured A/B on this WSL2 box (G1+terrain scene, 60 sync calls each,
no other GPU work running):

| Metric | Baseline (D3D12 only) | + vblank=0 + glthread | Δ |
|---|---|---|---|
| p50 sync ms | 5.04 | 5.00 | — |
| p95 sync ms | 5.81 | 5.38 | -7 % |
| **p99 sync ms** | **9.94** | **5.92** | **-40 %** |
| **max sync ms** | **9.94** | **5.93** | **-40 %** |

The median doesn't move — neither does GPU throughput. What changes is
the **tail**: max latency falls from ~10 ms to ~6 ms. Tail latency is
exactly what perceived stutter feels like: an occasional frame that
arrives twice as late as its neighbours reads as a "hitch" to the eye.
Cutting the tail in half is the win, not changing the average.

Use it as:

```bash
conda activate agi
cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
./run_sim.sh
```

### 5.4 Windows-side knobs (operator action required)

These are not under WSL's control. If §5.3 alone doesn't make the
viewer smooth, the next two tend to actually move the needle on
laptops with Optimus / hybrid graphics:

1. **NVIDIA Control Panel** → *Manage 3D settings* → *Program Settings* →
   add `python.exe` (and `wslhost.exe` if listed) → set:
   * **Power management mode:** *Prefer maximum performance* (stops
     Optimus from downclocking the 4060 when "load looks light" to
     DXGI)
   * **Vertical sync:** *Off* (we already disabled vsync on the Mesa
     side; matching at the driver level avoids one more buffering
     layer)
   * **Threaded optimization:** *On*
   * **Low Latency Mode:** *On*

2. **Windows Settings → System → Display → Graphics** → add `python.exe`
   from `~/miniforge3/envs/agi/bin/python.exe` (or whichever conda
   env runs the sim) → **High performance** preference.

3. **Hardware-Accelerated GPU Scheduling (HAGS)** is a known WSL2
   stutter source on some driver versions. Toggle: *Settings → System →
   Display → Graphics → Default graphics settings → Hardware-accelerated
   GPU scheduling*. Try turning it OFF, reboot, retest; if no change,
   turn it back ON. The right setting is driver/Windows-version dependent.

4. **Close other GPU-heavy Windows apps** (browsers with hardware accel
   on lots of tabs, video conferencing, Discord overlay, MSI Afterburner,
   anything that uses DXGI). The 4060 has 8 GB but D3D12-on-WSL2
   shares the DXGI command queue with native Windows apps; competition
   for command submission slots shows up as viewer stutter.

### 5.5 What is *not* fixable from inside WSL

* The Mesa→D3D12 translation tax itself (~constant per draw call)
* WSLg Wayland compositor latency (frames buffered through Hyper-V)
* Windows DXGI present pacing
* NVIDIA driver scheduling between native Windows apps and WSL2 guests

If after §5.3 + §5.4 the viewer still stutters, the practical options
are: (a) accept ~30 fps as the WSL2 ceiling for this scene, (b) reduce
scene complexity (USE_TERRAIN=False in `config.py` drops heightfields
+ ramps; saves ~30% of viewer geometry), (c) shrink the viewer window
(fewer pixels per frame = less per-frame GPU work), (d) run on native
Linux for development if maximum smoothness is required.

### 5.6 Correction: mouse-rotation lag is a *render_loop* problem, not a sync problem (third round, 2026-05-22 evening)

After §5.3 landed the operator reported that the viewer window is
**still** laggy when they rotate the camera with the mouse. Re-reading
the MuJoCo viewer source clarifies why §5.3 was aimed at the wrong
target for *this* symptom:

* `mujoco.viewer.launch_passive` spawns a **C++ `render_loop` thread**
  inside `_simulate.cpython-311.so`. That thread owns the GLFW window,
  receives mouse callbacks, and renders one frame per loop iteration,
  paced by `glfwSwapInterval(1)` against the display refresh (WSLg
  reports 60 Hz here).
* `viewer.sync()` only copies `MjData` → the internal `MjvScene`. It
  does **not** issue a redraw, and it does not run in the render
  thread. The §5.3 `VIEWER_DT` knob therefore controls how often the
  *robot animation* updates inside the viewer window — it has no
  influence on mouse-rotation responsiveness.
* So the §5.3 measurements (p99 sync 10 → 6 ms) were real and useful
  for robot-motion smoothness, but the mouse-rotation symptom is a
  separate issue: **render_loop per-frame cost exceeds the 16.6 ms
  60 Hz budget, so frames drop 60 → 30 → 60 unevenly during rotation**,
  which reads as "卡顿不流畅".

#### What drives the per-frame cost on this scene (WSL2 D3D12)

The G1+terrain scene has no `<quality>` block, so it inherits MuJoCo
defaults. The dominant costs per frame, ranked:

1. **Shadow map for the directional light** — default `shadowsize=4096`,
   one full extra geometry pass per shadow-casting light.
2. **Floor reflection** — `<material name="groundplane" reflectance=
   "0.2"/>` triggers a second full geometry pass mirrored through the
   floor.
3. **MSAA 4×** — default `offsamples=4` quadruples fragment-shader work.
4. Terrain geoms (≈30 boxes + 1 hfield) — moderate.
5. Skybox 3072×512 — small.

On native Linux + libGL_nvidia each GL call is essentially free, so
these defaults are fine. On WSL2 every call pays the Mesa→D3D12
translation tax, and (1)+(2)+(3) together push the per-frame budget
over 16.6 ms.

#### The fix (this round)

**File:** `unitree_mujoco/simulate_python/unitree_mujoco.py`

Added `_apply_low_quality_viewer(mj_model)` called right before
`launch_passive`. It mutates the *model* (not the viewer's scene,
which the passive viewer doesn't expose to Python):

```python
for i in range(model.nlight):
    model.light_castshadow[i] = 0      # skip shadow pass entirely
for i in range(model.nmat):
    model.mat_reflectance[i] = 0.0     # skip reflection pass
model.vis.quality.shadowsize = 1024     # was 4096
model.vis.quality.offsamples = 2        # was 4 (MSAA halved)
```

These are upstream causes — disabling them at the source removes the
extra render passes regardless of `MjvScene.flags`. The
`shadowsize`/`offsamples` changes don't matter while shadows are off
but keep the toggle cheap if the operator re-enables shadows from the
UI later.

**File:** `unitree_mujoco/simulate_python/config.py`

* `VIEWER_DT = 0.02` (restored from 0.033). The §5.3 → 0.033 was
  diagnosed against the wrong bottleneck; this knob doesn't gate
  mouse rotation, so we go back to 50 Hz robot-animation update.
* `LOW_QUALITY_VIEWER = True` — set False to restore full visual
  fidelity (e.g. for screenshots), accepting the WSL2 stutter.

#### Why this works even though §5.3 was "right" too

§5.3's `vblank_mode=0` + `mesa_glthread=true` + `LP_NUM_THREADS` are
still useful — they cut the *tail* of `viewer.sync()`, which the
physics thread depends on (the SimulationThread blocks behind the
lock that sync() holds). The §5.6 fix is independent: it cuts the
C++ render_loop's per-frame cost so the loop itself stays inside
the 16.6 ms vsync window. The two rounds address different threads.

#### Sanity check

```bash
conda activate agi
cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
./run_sim.sh
```

Expected: the floor no longer mirrors the robot; no cast shadow on
the ground; mouse-drag rotation feels smooth (no 60→30 fps oscillation).
If shadow/reflection are wanted back for a screenshot, set
`LOW_QUALITY_VIEWER = False` in `config.py` and relaunch.

---

## 6. Windows Terminal Quick Edit Mode

Separate non-code symptom from the original report: terminal output
freezes mid-stream and only resumes when any key is pressed. This is
**Windows Terminal's Quick Edit Mode** selecting on click and pausing
console output — fully a Windows setting, no WSL code change applies.

**To disable:**

1. Open Windows Terminal → top-bar dropdown → **Settings**.
2. Left panel → **Profiles** → select the Ubuntu / WSL profile being
   used.
3. **Advanced** tab → set **"Mode for treating right-clicks"** to
   `paste` (so right-click no longer enters a select-pause state), and
   turn **off** "Copy on selection" if it's on.
4. If launched via `wsl.exe` from an old `conhost.exe` console instead
   of Windows Terminal: right-click title bar → **Properties** →
   **Options** → **uncheck "QuickEdit Mode"**.

Verification: click into the terminal mid-stream — output should keep
flowing instead of freezing until you press a key.

---

## 7. How to re-verify (after pulling these changes)

```bash
conda activate agi
cd ~/unitree/unitree-notes/g1_brain
python -c "
import torch; print('torch.cuda:', torch.cuda.is_available())
from ultralytics import YOLO
m = YOLO('yolo11s.pt'); print('YOLO default device:', m.device)
"

# Expected:
# torch.cuda: True
# YOLO default device: cpu        ← this is ultralytics' construct-time default; will get overridden
```

Then launch the agent:

```bash
set -a; source .env; set +a
python -m g1_brain.apps.agent_main --mode confirm
```

In the launch log, look for:

```
INFO g1_brain.perception.object_detector: yolo device: cuda:0
INFO g1_brain.perception.object_detector: yolo worker started: source=head
INFO g1_brain.perception.object_detector: yolo worker started: source=usb
```

In a second terminal:

```bash
nvidia-smi  # should now show ~200-500 MB used by python agent_main + GPU utilisation > 0 % under load
```

Watch the simulator window — stutter should be substantially reduced
once both YOLO workers are off-CPU and the head-cam render thread is at
nice(10).

---

## 8. Optional / future optimizations (not yet applied)

These were considered and **deliberately not implemented** in this pass,
either because they're more invasive or because we should first verify
the above is sufficient. List is here so the next session can pick them
up without re-deriving the analysis.

### 7.1 Move head-cam render to its own subprocess

`mujoco_head_cam.py` runs in a daemon thread inside agent_main; even at
nice(10) it shares the GIL with the Realtime websocket and audio
threads. A subprocess (similar to `safety/combo_proxy.py` for the
controller) would entirely isolate the GIL impact. Cost: IPC for
frames (use shared-memory or zerocopy buffers; pickling 640×480 RGB at
10 Hz is ~9 MB/s which is fine over a `multiprocessing.shared_memory`
ring buffer).

Verdict: revisit if simulator window still stutters after this branch's
fixes land. The current architecture comment block at
`mujoco_head_cam.py:21-25` should grow a "subprocess fallback considered
but not implemented because ..." line if/when this is reopened.

### 7.2 Lower head-cam resolution from 640×480 to 320×240

The vision LLM upscales to its own internal target; the ground
constraint uses depth at a coarse cone (`perception.ground_constraint`
in `g1_brain.yaml`); YOLO11s detects fine at 320 px. A 4× pixel
reduction → ~4× faster render. Reason not yet applied: would change the
operator-visible debug window in `apps/perception_debug.py --show` and
needs a one-pass review of every downstream consumer of `latest_bgr()`.

### 7.3 Skip render when no consumer needs a fresh frame

`MuJoCoHeadCamera._render_once` currently renders unconditionally at
poll rate. If no one has called `latest_bgr()` / `latest_depth_meters()`
since the last render, skipping is free. Add a "consumed" flag set on
each public getter, cleared on each render. Saves ~50 % render cost
during stretches where the LLM isn't asking and nothing else is reading.

### 7.4 Reduce MediaPipe pose inference rate

`perception.pose.inference_hz: 15` in the YAML — same CPU sink as YOLO
was, on the **USB** camera only. With MediaPipe-on-CPU staying CPU even
after this branch (MediaPipe GPU delegate needs working EGL → it falls
back to XNNPACK = CPU on WSL2), pose is a real cost. Drop to 10 Hz or
gate on whether anyone is currently looking at gesture output.

### 7.5 D3D12-on-NVIDIA path *for shape-light scenes*

The G1 + terrain scene is mesh-heavy. For lighter scenes (sphere world,
pure-primitive ablations) D3D12 may break even or beat llvmpipe. If a
future user runs on a scene with <1000 triangles, retry the
`MUJOCO_GL=glfw` + `MESA_LOADER_DRIVER_OVERRIDE=d3d12` combination and
re-benchmark. The fast path is workload-dependent.

### 7.6 Native GL via WSLg + GLX *if NVIDIA ever ships it*

`/usr/lib/wsl/lib/` should be re-checked periodically for
`libGL_nvidia.so` / `libEGL_nvidia.so`. As of WSL kernel 6.6 and
NVIDIA driver 595.79 (the box this doc was authored on), neither
exists. When/if NVIDIA adds them, EGL on the 4060 becomes viable and
the order-of-magnitude render speedup that "GPU rendering" intuitively
promises becomes real. Until then: stay on llvmpipe.

---

## 9. Reference benchmark commands

For reproducing the numbers in this doc on the same box. All run from
`g1_brain/` with the `agi` conda env active.

```bash
# 1. Render-backend speed on the production scene
python - <<'PY'
import os, time
os.environ['MUJOCO_GL']='egl'
import mujoco
m = mujoco.MjModel.from_xml_path(
  '/home/helios/unitree/unitree-notes/unitree_mujoco/unitree_robots/g1/scene_29dof_terrain.xml')
d = mujoco.MjData(m)
r = mujoco.Renderer(m, 480, 640)
for _ in range(40): r.update_scene(d); r.render()      # warmup
t0=time.perf_counter()
for _ in range(50): r.update_scene(d); r.render()
print('RGB ms/frame:', (time.perf_counter()-t0)/50*1000)
r.enable_depth_rendering()
for _ in range(10): r.update_scene(d); r.render()
t0=time.perf_counter()
for _ in range(50): r.update_scene(d); r.render()
print('depth ms/frame:', (time.perf_counter()-t0)/50*1000)
import os as _os; _os._exit(0)
PY

# 2. YOLO CPU vs CUDA on a 640x480 BGR
python - <<'PY'
import time, numpy as np
from ultralytics import YOLO
m = YOLO('yolo11s.pt')
img = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
for d in ('cpu','cuda:0'):
    for _ in range(3): m.predict(img, verbose=False, device=d)
    t0=time.perf_counter()
    for _ in range(20): m.predict(img, verbose=False, device=d)
    print(f'{d}: {(time.perf_counter()-t0)/20*1000:.1f} ms/inference')
PY

# 3. WSL2 GL driver presence (the smoking-gun probe)
ls /usr/lib/wsl/lib | grep -i 'GL\|nvidia'
# If libGL_nvidia.so / libEGL_nvidia.so are missing → see § 7.6
```

---

## 10. Branch / commit pointer

All code changes for this optimization pass landed on branch
`fix/audio-interrupt-buffer`. Files touched:

- `g1_brain/perception/object_detector.py` (§ 4.1)
- `g1_brain/perception/mujoco_head_cam.py` (§ 4.2, § 4.3)
- `g1_brain/configs/g1_brain.yaml` (§ 4.4)
- `g1_brain/apps/agent_main.py` (§ 4.5)
- `docs/performance-optimization-GPU.md` (this file)

The non-obvious WSL2 GPU finding is also cached in the operator's
auto-memory at `~/.claude/projects/-home-helios-unitree-unitree-notes/
memory/wsl2_gpu_rendering.md` so future Claude sessions don't re-do the
benchmark to rediscover that D3D12-NVIDIA is slower than llvmpipe here.
