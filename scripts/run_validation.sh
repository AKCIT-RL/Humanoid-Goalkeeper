#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."

echo "=== Dry-run: dataset ORIGINAL ==="
./docker_run.sh python /workspace/scripts/dry_run_motionlib.py \
  --folder legged_gym/resources/datasets/goalkeeper

echo ""
echo "=== Dry-run: dataset NOSSO ==="
./docker_run.sh python /workspace/scripts/dry_run_motionlib.py \
  --folder data/goalkeeper_ours

echo ""
echo "=== Replay motions (PyBullet fallback — IsaacGym Vulkan incompatible with driver 580+) ==="
mkdir -p data/replays

for motion in lefthand leftjump leftstep righthand rightjump rightstep; do
  echo "--- Replay ORIGINAL: ${motion} ---"
  ./docker_run.sh bash -c "pip install -q pybullet 2>/dev/null && \
    python /workspace/scripts/replay_motion_pybullet.py \
    --motion /workspace/legged_gym/resources/datasets/goalkeeper/${motion}.pt \
    --urdf /workspace/legged_gym/resources/robots/g1/urdf/g1_29.urdf \
    --output_mp4 /workspace/data/replays/original_${motion}.mp4 \
    --fps 30"

  echo "--- Replay OURS: ${motion} ---"
  ./docker_run.sh bash -c "pip install -q pybullet 2>/dev/null && \
    python /workspace/scripts/replay_motion_pybullet.py \
    --motion /workspace/data/goalkeeper_ours/${motion}.pt \
    --urdf /workspace/legged_gym/resources/robots/g1/urdf/g1_29.urdf \
    --output_mp4 /workspace/data/replays/ours_${motion}.mp4 \
    --fps 30"
done

echo ""
echo "=== Side-by-side videos ==="
./docker_run.sh bash -c "
for motion in lefthand leftjump leftstep righthand rightjump rightstep; do
  if [ -f /workspace/data/replays/original_\${motion}.mp4 ] && [ -f /workspace/data/replays/ours_\${motion}.mp4 ]; then
    ffmpeg -y \
      -i /workspace/data/replays/original_\${motion}.mp4 \
      -i /workspace/data/replays/ours_\${motion}.mp4 \
      -filter_complex '[0:v][1:v]hstack=inputs=2' \
      /workspace/data/replays/sbs_\${motion}.mp4 2>/dev/null && echo \"Created sbs_\${motion}.mp4\" || echo \"FAIL sbs_\${motion}\"
  else
    echo \"SKIP sbs_\${motion}: missing source video(s)\"
  fi
done
"

echo ""
echo "=== Summary ==="
ls -lh data/replays/*.mp4 2>/dev/null || echo "No MP4 files generated"
echo "DONE"
