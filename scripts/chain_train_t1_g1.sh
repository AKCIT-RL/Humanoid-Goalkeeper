#!/usr/bin/env bash
# chain_train_t1_g1.sh — Treina T1 (booster_t1) primeiro, depois G1 (29), em containers Docker.
set -euo pipefail

REPO_ROOT="/home/marcos/Humanoid-Goalkeeper"
IMAGE="humanoid-goalkeeper:latest"
LOG_DIR="$REPO_ROOT/training_logs"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"

WANDB_KEY="${WANDB_API_KEY:?Set WANDB_API_KEY env var}"
WANDB_USERNAME="marcospaulo2-federal-university-of-goi-s"
WANDB_PROJECT="goalkeepper"

MAX_ITERATIONS="${MAX_ITERATIONS:-5000}"

if [ "${1:-}" = "--smoke" ]; then
    MAX_ITERATIONS=2
fi

EXPTID_T1="booster_t1_${TIMESTAMP}"
EXPTID_G1="g1_29_${TIMESTAMP}"

CONTAINER_T1="humanoid-goalkeeper-train-t1"
CONTAINER_G1="humanoid-goalkeeper-train-g1"

mkdir -p "$LOG_DIR"

DOCKER_VOLUMES=(
    -v "$REPO_ROOT/legged_gym:/workspace/legged_gym"
    -v "$REPO_ROOT/rsl_rl:/workspace/rsl_rl"
    -v "$REPO_ROOT/data:/workspace/data"
    -v "$REPO_ROOT/logs:/workspace/logs"
    -v "$REPO_ROOT/scripts:/workspace/scripts"
)

DOCKER_COMMON=(
    --gpus all
    --shm-size=16g
    --ipc=host
    --restart=no
    -e NVIDIA_DRIVER_CAPABILITIES=all
    -e VK_ICD_FILENAMES=/opt/isaacgym/docker/nvidia_icd.json
    -e WANDB_API_KEY="$WANDB_KEY"
    -e WANDB_USERNAME="$WANDB_USERNAME"
    -e WANDB_PROJECT="$WANDB_PROJECT"
)

run_task() {
    local task="$1"
    local exptid="$2"
    local container_name="$3"

    echo ""
    echo "=========================================="
    echo "[$(date)] RUN task=$task exptid=$exptid max_iter=$MAX_ITERATIONS"
    echo "=========================================="

    docker stop "$container_name" 2>/dev/null || true
    docker rm "$container_name" 2>/dev/null || true

    docker run -d \
        --name "$container_name" \
        "${DOCKER_COMMON[@]}" \
        "${DOCKER_VOLUMES[@]}" \
        "$IMAGE" \
        bash -lc "cd /workspace/legged_gym/legged_gym/scripts && exec python -u train.py --task $task --exptid $exptid --headless --max_iterations $MAX_ITERATIONS"

    echo "[$(date)] Container $container_name launched. Waiting for completion..."

    local exit_code=0
    docker wait "$container_name" || exit_code=$?
    local container_exit
    container_exit="$(docker inspect --format='{{.State.ExitCode}}' "$container_name" 2>/dev/null || echo unknown)"

    docker logs "$container_name" > "$LOG_DIR/${exptid}_final.log" 2>&1
    echo "[$(date)] Container $container_name exit=$container_exit log=$LOG_DIR/${exptid}_final.log"

    if [ "$container_exit" != "0" ]; then
        echo "ERROR: task $task ($exptid) exited with $container_exit" >&2
        return 1
    fi
}

echo "=========================================="
echo "Chain train T1+G1 started at $(date)"
echo "EXPTID_T1: $EXPTID_T1"
echo "EXPTID_G1: $EXPTID_G1"
echo "MAX_ITERATIONS: $MAX_ITERATIONS"
echo "=========================================="

run_task booster_t1 "$EXPTID_T1" "$CONTAINER_T1"
run_task 29         "$EXPTID_G1" "$CONTAINER_G1"

cat > "$LOG_DIR/chain_t1_g1_done.txt" <<EOF
Chain T1+G1 completed at $(date)
Started: $TIMESTAMP

Run T1: $EXPTID_T1  log=$LOG_DIR/${EXPTID_T1}_final.log
Run G1: $EXPTID_G1  log=$LOG_DIR/${EXPTID_G1}_final.log
EOF

echo "[$(date)] chain_t1_g1_done.txt written. All done."
