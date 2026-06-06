#!/usr/bin/env bash
# Roda replays cinemáticos T1 (PyBullet + IsaacGym) dentro do docker.
# Saída: tests/videos_t1/{pybullet,isaacgym}_<motion>.mp4
set -u  # NOT -e: queremos coletar TODOS os logs mesmo se um falhar

REPO="$(cd "$(dirname "$0")/.." && pwd)"
IMAGE="humanoid-goalkeeper:latest"
MOTIONS=(lefthand leftjump leftstep righthand rightjump rightstep)

mkdir -p "$REPO/tests/videos_t1" "$REPO/tests/logs"

# Roda uma única invocação docker que faz tudo (instala pybullet + roda todos).
docker run --rm \
  --gpus all \
  --shm-size=8g \
  --ipc=host \
  -e NVIDIA_DRIVER_CAPABILITIES=all \
  -e VK_ICD_FILENAMES=/opt/isaacgym/docker/nvidia_icd.json \
  -v "$REPO/legged_gym:/workspace/legged_gym" \
  -v "$REPO/data:/workspace/data" \
  -v "$REPO/scripts:/workspace/scripts" \
  -v "$REPO/ViMoS:/workspace/ViMoS" \
  -v "$REPO/tests:/workspace/tests" \
  "$IMAGE" bash -c '
set +e
cd /workspace
echo "=== Installing pybullet ==="
pip install --quiet pybullet 2>&1 | tail -3

URDF=/workspace/ViMoS/retarget/GMR/assets/booster_t1/T1_serial.urdf
MOTIONS_DIR=/workspace/data/goalkeeper_ours_t1
OUT=/workspace/tests/videos_t1
LOGS=/workspace/tests/logs

mkdir -p "$OUT" "$LOGS"
ls -la "$URDF" || { echo "URDF NOT FOUND"; exit 1; }

for M in lefthand leftjump leftstep righthand rightjump rightstep; do
  echo
  echo "===================================================="
  echo "=== PyBullet replay: $M"
  echo "===================================================="
  python3 /workspace/scripts/replay_motion_pybullet.py \
    --motion "$MOTIONS_DIR/$M.pt" \
    --urdf "$URDF" \
    --mapping "$MOTIONS_DIR/joint_id.txt" \
    --output_mp4 "$OUT/pybullet_$M.mp4" \
    > "$LOGS/pybullet_$M.log" 2>&1
  rc=$?
  echo "  exit=$rc  size=$(stat -c%s "$OUT/pybullet_$M.mp4" 2>/dev/null || echo missing)"
  if [[ $rc -ne 0 ]]; then
    echo "  --- last 15 lines ---"
    tail -15 "$LOGS/pybullet_$M.log"
  fi

  echo
  echo "===================================================="
  echo "=== IsaacGym replay: $M"
  echo "===================================================="
  python3 /workspace/tests/replay_t1_isaacgym.py \
    --motion "$MOTIONS_DIR/$M.pt" \
    --urdf "$URDF" \
    --output_mp4 "$OUT/isaacgym_$M.mp4" \
    > "$LOGS/isaacgym_$M.log" 2>&1
  rc=$?
  echo "  exit=$rc  size=$(stat -c%s "$OUT/isaacgym_$M.mp4" 2>/dev/null || echo missing)"
  if [[ $rc -ne 0 ]]; then
    echo "  --- last 15 lines ---"
    tail -15 "$LOGS/isaacgym_$M.log"
  fi
done

echo
echo "=== ffprobe outputs ==="
for f in "$OUT"/*.mp4 /workspace/ViMoS/retarget/GMR/videos/*.mp4; do
  if [[ -f "$f" ]]; then
    dur=$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$f" 2>/dev/null)
    sz=$(stat -c%s "$f")
    echo "  $(basename "$f"):  ${dur}s  ${sz} bytes"
  fi
done

echo
echo "=== Summary ==="
ls -la "$OUT"/*.mp4 2>/dev/null
'
