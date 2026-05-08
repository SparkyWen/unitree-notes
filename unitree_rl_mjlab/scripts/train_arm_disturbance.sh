#!/usr/bin/env bash
# One-key launcher for Unitree-G1-Flat-Arm-Disturbance continue-training.
#
# Run from the unitree_rl_mjlab/ directory on the lab computer:
#
#   cd ~/unitree-notes/unitree_rl_mjlab
#   bash scripts/train_arm_disturbance.sh
#
# What this does:
#   1. Activates the unitree-env virtualenv.
#   2. Generates gestures.npz from the velocity/v0 deploy.yaml (idempotent).
#   3. Symlinks the latest g1_velocity checkpoint into the g1_arm_disturbance
#      log directory so the --agent.resume mechanism can find it.
#   4. Launches training warm-started from that checkpoint.
#
# Optional env vars (override defaults):
#   SRC_RUN    – name of the g1_velocity run to warm-start from
#                (default: latest run under logs/rsl_rl/g1_velocity/)
#   NUM_ENVS   – number of parallel environments  (default: 4096)
#   GPU_IDS    – comma-separated GPU ids, e.g. "0,1"  (default: 0)
#   MAX_ITER   – max training iterations  (default: 10001)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="${VENV:-$HOME/unitree_sdk2_python/unitree-env}"
DEPLOY_YAML="${REPO_ROOT}/deploy/robots/g1/config/policy/velocity/v0/params/deploy.yaml"
GESTURES_NPZ="${REPO_ROOT}/src/assets/motions/g1/gestures.npz"

SRC_LOG="${REPO_ROOT}/logs/rsl_rl/g1_velocity"
DST_LOG="${REPO_ROOT}/logs/rsl_rl/g1_arm_disturbance"
WARMSTART_LINK_NAME="warmstart_velocity_v0"

NUM_ENVS="${NUM_ENVS:-4096}"
GPU_IDS="${GPU_IDS:-0}"
MAX_ITER="${MAX_ITER:-10001}"

# ── Activate venv ─────────────────────────────────────────────────────────────
# shellcheck disable=SC1091
source "${VENV}/bin/activate"

# ── Step 1: generate gestures.npz ────────────────────────────────────────────
if [ ! -f "${GESTURES_NPZ}" ]; then
    echo "==> Generating gestures.npz ..."
    python "${REPO_ROOT}/src/assets/motions/g1/make_gestures_npz.py" \
        --deploy-yaml "${DEPLOY_YAML}" \
        --out "${GESTURES_NPZ}" \
        --fps 50
    echo "    Written: ${GESTURES_NPZ}"
else
    echo "==> gestures.npz exists — skipping generation."
fi

# ── Step 2: resolve source (warm-start) run directory ────────────────────────
if [ -n "${SRC_RUN:-}" ]; then
    SRC_RUN_DIR="${SRC_LOG}/${SRC_RUN}"
else
    SRC_RUN_DIR="$(ls -dt "${SRC_LOG}"/2* 2>/dev/null | head -1 || true)"
fi

if [ -z "${SRC_RUN_DIR}" ] || [ ! -d "${SRC_RUN_DIR}" ]; then
    echo "ERROR: No g1_velocity run found under ${SRC_LOG}."
    echo "       Train Unitree-G1-Flat first (scripts/train.py Unitree-G1-Flat), or"
    echo "       set SRC_RUN=<run-dir-name> to point at an existing checkpoint."
    exit 1
fi
echo "==> Warm-start source: ${SRC_RUN_DIR}"

# ── Step 3: symlink into g1_arm_disturbance log dir ──────────────────────────
# get_checkpoint_path looks inside logs/rsl_rl/<experiment_name>/<load_run>/
mkdir -p "${DST_LOG}"
LINK_PATH="${DST_LOG}/${WARMSTART_LINK_NAME}"
if [ -L "${LINK_PATH}" ]; then
    rm "${LINK_PATH}"
fi
ln -s "${SRC_RUN_DIR}" "${LINK_PATH}"
echo "==> Linked: ${LINK_PATH} -> ${SRC_RUN_DIR}"

# ── Step 4: launch training ───────────────────────────────────────────────────
cd "${REPO_ROOT}"
echo "==> Starting training (Unitree-G1-Flat-Arm-Disturbance) ..."
python scripts/train.py \
    Unitree-G1-Flat-Arm-Disturbance \
    --env.scene.num-envs "${NUM_ENVS}" \
    --agent.resume true \
    --agent.load-run "${WARMSTART_LINK_NAME}" \
    --agent.experiment-name g1_arm_disturbance \
    --agent.max-iterations "${MAX_ITER}" \
    --gpu-ids "${GPU_IDS}"
