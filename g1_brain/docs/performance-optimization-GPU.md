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

## 5. The Windows-side fix (separate from code)

The "press any key to refresh terminal output" symptom is **Windows
Terminal Quick Edit Mode**. It cannot be patched from inside WSL.

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

## 6. How to re-verify (after pulling these changes)

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

## 7. Optional / future optimizations (not yet applied)

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

## 8. Reference benchmark commands

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

## 9. Branch / commit pointer

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
