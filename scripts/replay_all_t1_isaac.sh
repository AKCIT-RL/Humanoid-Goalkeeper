#!/usr/bin/env bash
# Render all 6 T1 motions via PyBullet (Isaac-substitute) using booster_t1 URDF.
set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="${REPO_ROOT}/data/t1_isaac_videos"
# data/ is owned by root from prior docker runs; create dir inside container.
docker run --rm -v "${REPO_ROOT}":/workspace humanoid-goalkeeper:latest \
  bash -c "mkdir -p /workspace/data/t1_isaac_videos && chmod 777 /workspace/data/t1_isaac_videos"

for motion in lefthand leftjump leftstep righthand rightjump rightstep; do
  echo "=== ${motion} ==="
  docker run --rm \
    --gpus all \
    -v "${REPO_ROOT}":/workspace \
    -w /workspace \
    humanoid-goalkeeper:latest \
    python scripts/replay_t1_pybullet.py \
      --motion /workspace/data/goalkeeper_ours_t1/${motion}.pt \
      --urdf /workspace/legged_gym/resources/robots/booster_t1/urdf/T1_serial.urdf \
      --output_mp4 /workspace/data/t1_isaac_videos/${motion}.mp4
done

echo "=== DONE ==="
ls -lh "${OUT_DIR}"
