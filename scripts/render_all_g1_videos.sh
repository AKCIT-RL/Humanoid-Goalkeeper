#!/usr/bin/env bash
# Render all 6 GMR-retargeted Unitree G1 PKL motions to MP4 (headless).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${REPO_ROOT}/data/g1_videos"
# Use docker to mkdir because data/ is owned by root from previous container runs.
docker run --rm \
    -v "${REPO_ROOT}/data:/data" \
    copycat-gmr:latest \
    bash -c "mkdir -p /data/g1_videos && chmod 777 /data/g1_videos"

MOTIONS=(left-down left-medium left-up right-down right-medium right-up)

for MOTION in "${MOTIONS[@]}"; do
    echo "=== Rendering unitree_g1_${MOTION} ==="
    docker run --rm \
        -e MUJOCO_GL=egl \
        -e PYOPENGL_PLATFORM=egl \
        -v "${REPO_ROOT}/ViMoS/retarget/GMR:/app" \
        -v "${REPO_ROOT}/scripts:/scripts" \
        -v "${REPO_ROOT}/data:/data" \
        -w /app \
        copycat-gmr:latest \
        python /scripts/render_gmr_pkl_t1.py \
            --pkl_path "/app/output/pkl/unitree_g1_${MOTION}.pkl" \
            --xml_path "/app/assets/unitree_g1/g1_mocap_29dof.xml" \
            --robot_base pelvis \
            --out_path "/data/g1_videos/unitree_g1_${MOTION}.mp4"
done

echo
echo "=== All videos written to ${OUT_DIR} ==="
ls -lh "${OUT_DIR}"
