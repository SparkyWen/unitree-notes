#!/usr/bin/env bash
# One-key launcher for Unitree-G1-23Dof-Flat-Arm-Disturbance training.
#
# Run from the unitree_rl_mjlab/ directory on the lab computer:
#
#   cd ~/unitree-notes/unitree_rl_mjlab
#   bash scripts/train_arm_disturbance.sh
#
# Start-mode priority (automatic):
#   1. Resume from most recent g1_23dof_arm_disturbance run (if any).
#   2. Warm-start from most recent g1_23dof_velocity run (if any).
#   3. Cold start.
#
# Optional env vars:
#   ARM_RUN    – exact run name under logs/rsl_rl/g1_23dof_arm_disturbance/
#                to resume from (default: latest)
#   SRC_RUN    – exact run name under logs/rsl_rl/g1_23dof_velocity/ for
#                warm-start (default: latest); ignored if an arm run is found
#   NUM_ENVS   – number of parallel environments  (default: 4096)
#   GPU_IDS    – comma-separated GPU ids, e.g. "0,1"  (default: 0)
#   MAX_ITER   – max training iterations  (default: 20001)
#   RECORD_VIDEO – set to "false" to disable periodic video snapshots (default: true)
#
# Video clips are saved to:
#   logs/rsl_rl/g1_23dof_arm_disturbance/<run>/videos/train/
# To watch training live, run in a separate terminal (once a checkpoint exists):
#   cd ~/unitree-notes/unitree_rl_mjlab
#   PYTHONPATH=. python scripts/play.py Unitree-G1-23Dof-Flat-Arm-Disturbance \
#     --agent.experiment-name g1_23dof_arm_disturbance --num-envs 4

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="${VENV:-$HOME/Git/unitree_mujoco/.venv}"
GESTURES_NPZ="${REPO_ROOT}/src/assets/motions/g1/gestures_23dof.npz"

ARM_LOG="${REPO_ROOT}/logs/rsl_rl/g1_23dof_arm_disturbance"
SRC_LOG="${REPO_ROOT}/logs/rsl_rl/g1_23dof_velocity"
WARMSTART_LINK_NAME="warmstart_23dof_velocity"

NUM_ENVS="${NUM_ENVS:-4096}"
GPU_IDS="${GPU_IDS:-0}"
MAX_ITER="${MAX_ITER:-20001}"

# tyro expects list[int] notation, e.g. [0] or [0,1].
# Convert bare comma-separated ids (e.g. "0" or "0,1") to bracket form.
if [[ "${GPU_IDS}" != \[* ]]; then
    GPU_IDS="[${GPU_IDS}]"
fi
RECORD_VIDEO="${RECORD_VIDEO:-true}"

# ── Activate venv ─────────────────────────────────────────────────────────────
# shellcheck disable=SC1091
source "${VENV}/bin/activate"

# Add repo root to PYTHONPATH so 'import src.tasks' resolves correctly.
export PYTHONPATH="${REPO_ROOT}:${PYTHONPATH:-}"

# ── Step 1: generate gestures_23dof.npz ──────────────────────────────────────
if [ ! -f "${GESTURES_NPZ}" ]; then
    echo "==> Generating gestures_23dof.npz ..."
    python "${REPO_ROOT}/src/assets/motions/g1/make_gestures_npz.py" \
        --dof 23 \
        --out "${GESTURES_NPZ}" \
        --fps 50
    echo "    Written: ${GESTURES_NPZ}"
else
    echo "==> gestures_23dof.npz exists — skipping generation."
fi

# ── Step 2: determine start mode ─────────────────────────────────────────────
START_MODE="cold"
LOAD_RUN=""

# Priority 1: resume from an existing arm-disturbance checkpoint.
if [ -n "${ARM_RUN:-}" ]; then
    ARM_RESUME_DIR="${ARM_LOG}/${ARM_RUN}"
else
    ARM_RESUME_DIR="$(ls -dt "${ARM_LOG}"/2* 2>/dev/null | head -1 || true)"
fi

if [ -n "${ARM_RESUME_DIR}" ] && [ -d "${ARM_RESUME_DIR}" ]; then
    START_MODE="resume"
    LOAD_RUN="$(basename "${ARM_RESUME_DIR}")"
    echo "==> Resuming arm-disturbance run: ${LOAD_RUN}"
else
    # Priority 2: warm-start from a g1_23dof_velocity checkpoint.
    if [ -n "${SRC_RUN:-}" ]; then
        SRC_RUN_DIR="${SRC_LOG}/${SRC_RUN}"
    else
        SRC_RUN_DIR="$(ls -dt "${SRC_LOG}"/2* 2>/dev/null | head -1 || true)"
    fi

    if [ -n "${SRC_RUN_DIR}" ] && [ -d "${SRC_RUN_DIR}" ]; then
        START_MODE="warmstart"
        mkdir -p "${ARM_LOG}"
        LINK_PATH="${ARM_LOG}/${WARMSTART_LINK_NAME}"
        if [ -L "${LINK_PATH}" ]; then
            rm "${LINK_PATH}"
        fi
        ln -s "${SRC_RUN_DIR}" "${LINK_PATH}"
        LOAD_RUN="${WARMSTART_LINK_NAME}"
        echo "==> Warm-start: ${LINK_PATH} -> ${SRC_RUN_DIR}"
    else
        echo "==> No checkpoint found — cold start."
    fi
fi

# ── Step 3: launch training ───────────────────────────────────────────────────
cd "${REPO_ROOT}"
echo "==> Starting training (Unitree-G1-23Dof-Flat-Arm-Disturbance) ..."

VIDEO_FLAG=""
if [ "${RECORD_VIDEO}" = "true" ]; then
    VIDEO_FLAG="--video True"
fi

if [ "${START_MODE}" = "cold" ]; then
    # shellcheck disable=SC2086
    python scripts/train.py \
        Unitree-G1-23Dof-Flat-Arm-Disturbance \
        --env.scene.num-envs "${NUM_ENVS}" \
        --agent.experiment-name g1_23dof_arm_disturbance \
        --agent.max-iterations "${MAX_ITER}" \
        --gpu-ids "${GPU_IDS}" \
        ${VIDEO_FLAG}
else
    # shellcheck disable=SC2086
    python scripts/train.py \
        Unitree-G1-23Dof-Flat-Arm-Disturbance \
        --env.scene.num-envs "${NUM_ENVS}" \
        --agent.resume true \
        --agent.load-run "${LOAD_RUN}" \
        --agent.experiment-name g1_23dof_arm_disturbance \
        --agent.max-iterations "${MAX_ITER}" \
        --gpu-ids "${GPU_IDS}" \
        ${VIDEO_FLAG}
fi
