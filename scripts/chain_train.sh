#!/usr/bin/env bash
# chain_train.sh — Orquestra dois treinos sequenciais (ours + real) em containers Docker.
# Projetado para rodar com nohup e sobreviver ao disconnect SSH.
# NÃO use set -e globalmente — queremos continuar mesmo se o primeiro run falhar.

REPO_ROOT="/home/marcos/Humanoid-Goalkeeper"
IMAGE="humanoid-goalkeeper:latest"
LOG_DIR="$REPO_ROOT/training_logs"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"

WANDB_KEY="${WANDB_API_KEY:?Set WANDB_API_KEY env var}"
WANDB_ENTITY="marcospaulo2-federal-university-of-goi-s"
WANDB_PROJECT="goalkeepper"

# EXPTIDs únicos
EXPTID_OURS="ours_5k_${TIMESTAMP}"
EXPTID_REAL="real_5k_${TIMESTAMP}"

CONTAINER_OURS="humanoid-goalkeeper-train-ours-5k"
CONTAINER_REAL="humanoid-goalkeeper-train-real-5k"

MAX_ITER=5000

mkdir -p "$LOG_DIR"

echo "=========================================="
echo "Chain training started at $(date)"
echo "EXPTID_OURS: $EXPTID_OURS"
echo "EXPTID_REAL: $EXPTID_REAL"
echo "MAX_ITER:    $MAX_ITER"
echo "=========================================="

# -------------------------------------------------------
# Passo 0 — Parar container antigo (se existir)
# -------------------------------------------------------
echo "[$(date)] Stopping old container humanoid-goalkeeper-train..."
docker stop humanoid-goalkeeper-train 2>/dev/null || true
docker rm humanoid-goalkeeper-train 2>/dev/null || true
echo "[$(date)] Old container cleaned up."

# Também limpar containers anteriores com os mesmos nomes (re-run seguro)
docker stop "$CONTAINER_OURS" 2>/dev/null || true
docker rm "$CONTAINER_OURS" 2>/dev/null || true
docker stop "$CONTAINER_REAL" 2>/dev/null || true
docker rm "$CONTAINER_REAL" 2>/dev/null || true

# -------------------------------------------------------
# Volumes comuns
# -------------------------------------------------------
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
    -e WANDB_USERNAME="$WANDB_ENTITY"
    -e WANDB_PROJECT="$WANDB_PROJECT"
)

# -------------------------------------------------------
# Run 1 — ours dataset
# -------------------------------------------------------
echo ""
echo "=========================================="
echo "[$(date)] RUN 1: $EXPTID_OURS (dataset=ours, max_iter=$MAX_ITER)"
echo "=========================================="

docker run -d \
    --name "$CONTAINER_OURS" \
    "${DOCKER_COMMON[@]}" \
    "${DOCKER_VOLUMES[@]}" \
    "$IMAGE" \
    bash /workspace/scripts/train_entrypoint.sh "$EXPTID_OURS" ours "$MAX_ITER"

echo "[$(date)] Container $CONTAINER_OURS launched. Waiting for completion..."

# docker wait retorna o exit code do container
EXIT_OURS=0
docker wait "$CONTAINER_OURS" || EXIT_OURS=$?
# Capturar o exit code real do container (docker wait imprime o exit code)
CONTAINER_EXIT_OURS=$(docker inspect --format='{{.State.ExitCode}}' "$CONTAINER_OURS" 2>/dev/null || echo "unknown")

echo "[$(date)] Container $CONTAINER_OURS finished. Exit code: $CONTAINER_EXIT_OURS"

# Salvar log final
docker logs "$CONTAINER_OURS" > "$LOG_DIR/${EXPTID_OURS}_final.log" 2>&1
echo "[$(date)] Log saved to $LOG_DIR/${EXPTID_OURS}_final.log"

# -------------------------------------------------------
# Run 2 — real dataset
# -------------------------------------------------------
echo ""
echo "=========================================="
echo "[$(date)] RUN 2: $EXPTID_REAL (dataset=real, max_iter=$MAX_ITER)"
echo "=========================================="

docker run -d \
    --name "$CONTAINER_REAL" \
    "${DOCKER_COMMON[@]}" \
    "${DOCKER_VOLUMES[@]}" \
    "$IMAGE" \
    bash /workspace/scripts/train_entrypoint.sh "$EXPTID_REAL" real "$MAX_ITER"

echo "[$(date)] Container $CONTAINER_REAL launched. Waiting for completion..."

EXIT_REAL=0
docker wait "$CONTAINER_REAL" || EXIT_REAL=$?
CONTAINER_EXIT_REAL=$(docker inspect --format='{{.State.ExitCode}}' "$CONTAINER_REAL" 2>/dev/null || echo "unknown")

echo "[$(date)] Container $CONTAINER_REAL finished. Exit code: $CONTAINER_EXIT_REAL"

# Salvar log final
docker logs "$CONTAINER_REAL" > "$LOG_DIR/${EXPTID_REAL}_final.log" 2>&1
echo "[$(date)] Log saved to $LOG_DIR/${EXPTID_REAL}_final.log"

# -------------------------------------------------------
# Resumo final
# -------------------------------------------------------
echo ""
echo "=========================================="
echo "Chain training finished at $(date)"
echo "=========================================="
echo "Run 1 ($EXPTID_OURS): exit code $CONTAINER_EXIT_OURS"
echo "Run 2 ($EXPTID_REAL): exit code $CONTAINER_EXIT_REAL"

cat > "$LOG_DIR/chain_done.txt" <<EOF
Chain training completed at $(date)
Started at: $TIMESTAMP

Run 1: $EXPTID_OURS
  Dataset: ours
  Container: $CONTAINER_OURS
  Exit code: $CONTAINER_EXIT_OURS
  Log: $LOG_DIR/${EXPTID_OURS}_final.log

Run 2: $EXPTID_REAL
  Dataset: real
  Container: $CONTAINER_REAL
  Exit code: $CONTAINER_EXIT_REAL
  Log: $LOG_DIR/${EXPTID_REAL}_final.log
EOF

echo "[$(date)] chain_done.txt written. All done."
