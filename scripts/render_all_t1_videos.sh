#!/usr/bin/env bash
# Render all 6 GMR-retargeted Booster T1 PKL motions to MP4 (headless).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${REPO_ROOT}/data/t1_videos"
# Use docker to mkdir because data/ is owned by root from previous container runs.
docker run --rm \
    -v "${REPO_ROOT}/data:/data" \
    copycat-gmr:latest \
    bash -c "mkdir -p /data/t1_videos && chmod 777 /data/t1_videos"

MOTIONS=(left-down left-medium left-up right-down right-medium right-up)

for MOTION in "${MOTIONS[@]}"; do
    echo "=== Rendering booster_t1_${MOTION} ==="
    docker run --rm \
        -e MUJOCO_GL=egl \
        -e PYOPENGL_PLATFORM=egl \
        -v "${REPO_ROOT}/ViMoS/retarget/GMR:/app" \
        -v "${REPO_ROOT}/scripts:/scripts" \
        -v "${REPO_ROOT}/data:/data" \
        -w /app \
        copycat-gmr:latest \
        python /scripts/render_gmr_pkl_t1.py \
            --pkl_path "/app/output/pkl/booster_t1_${MOTION}.pkl" \
            --out_path "/data/t1_videos/booster_t1_${MOTION}.mp4"
done

echo
echo "=== All videos written to ${OUT_DIR} ==="
ls -lh "${OUT_DIR}"
