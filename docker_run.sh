#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
IMAGE="humanoid-goalkeeper:latest"
NAME="humanoid-goalkeeper-$(date +%s)"

# X11 (necessário para viewer do IsaacGym; em SSH pode pular)
XAUTH_ARGS=""
if [[ -n "${DISPLAY:-}" ]]; then
  XAUTH_ARGS="-e DISPLAY=$DISPLAY -v /tmp/.X11-unix:/tmp/.X11-unix:rw"
fi

docker run --rm -it \
  --gpus all \
  --name "$NAME" \
  --shm-size=16g \
  --ipc=host \
  -e NVIDIA_DRIVER_CAPABILITIES=all \
  -e VK_ICD_FILENAMES=/opt/isaacgym/docker/nvidia_icd.json \
  $XAUTH_ARGS \
  -v "$REPO_ROOT/legged_gym:/workspace/legged_gym" \
  -v "$REPO_ROOT/rsl_rl:/workspace/rsl_rl" \
  -v "$REPO_ROOT/data:/workspace/data" \
  -v "$REPO_ROOT/logs:/workspace/logs" \
  -v "$REPO_ROOT/scripts:/workspace/scripts" \
  "$IMAGE" "$@"
