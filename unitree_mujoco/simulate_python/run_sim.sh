#!/usr/bin/env bash
# Launch the Unitree G1 MuJoCo simulator with the WSL2-tuned environment that
# reduces viewer-window stutter. See docs/performance-optimization-GPU.md § 5
# for the diagnosis behind each variable.
#
# Use this instead of `python unitree_mujoco.py` so you don't have to remember
# every env var. The script does NOT activate conda — run `conda activate agi`
# first (or whichever env you keep your sim deps in).
#
# Usage:
#   conda activate agi
#   cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
#   ./run_sim.sh

set -e

# Mesa -> D3D12 translation, routed to the NVIDIA discrete adapter. Without
# these the simulator opens on llvmpipe CPU and is genuinely slow.
export MESA_LOADER_DRIVER_OVERRIDE=d3d12
export GALLIUM_DRIVER=d3d12
export MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA
export LIBGL_ALWAYS_SOFTWARE=0
export MUJOCO_GL=glfw

# Disable vsync on the Mesa side. WSLg already does its own compositor pacing;
# letting Mesa also wait for vblank stacks two synchronisation layers and is
# a known D3D12-on-WSL2 stutter source. With vsync off, frames present as
# soon as D3D12 finishes -- the compositor still bounds the peak to display
# refresh, but the GL submit thread stops getting blocked.
export vblank_mode=0

# Submit GL commands from a Mesa worker thread instead of the caller. With
# D3D12 each call pays translation cost; offloading hides that latency from
# the viewer thread so viewer.sync() returns faster.
export mesa_glthread=true

# Cap Mesa's own internal threading so it doesn't compete with the physics
# thread or the agent process if you run them on the same machine.
export LP_NUM_THREADS=${LP_NUM_THREADS:-4}

# Fail loudly if no conda env is active — bare `python` isn't on WSL2's system
# PATH, so the exec below would otherwise die with a cryptic "not found".
if ! command -v python >/dev/null; then
  echo "run_sim.sh: 'python' not on PATH — did you forget 'conda activate agi'?" >&2
  exit 1
fi

# Hand off to the actual launcher. Pass through any extra args (the upstream
# script ignores them today but might gain CLI flags later).
exec python unitree_mujoco.py "$@"
