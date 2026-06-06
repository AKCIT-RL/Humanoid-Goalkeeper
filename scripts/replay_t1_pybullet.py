#!/usr/bin/env python3
"""Kinematic replay of T1 .pt motion in PyBullet -> MP4.

Headless DIRECT-mode replay used as Isaac substitute (Vulkan render bug in
container blocks IsaacGym camera sensor for the T1 URDF). Mapping is built
from `dof_names` embedded in the .pt file (23 DOFs for T1).
"""
import argparse
import os
import subprocess
import sys

import numpy as np
import torch


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--motion", required=True)
    ap.add_argument(
        "--urdf",
        default="/workspace/legged_gym/resources/robots/booster_t1/urdf/T1_serial.urdf",
    )
    ap.add_argument("--output_mp4", required=True)
    ap.add_argument("--width", type=int, default=720)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--fps", type=int, default=30)
    args = ap.parse_args()

    data = torch.load(args.motion, map_location="cpu")
    base_pos = data["base_position"].cpu().numpy()
    base_quat = data["base_pose"].cpu().numpy()  # xyzw (matches PyBullet)
    joint_pos = data["joint_position"].cpu().numpy()
    joint_vel = data["joint_velocity"].cpu().numpy()
    dof_names = data.get("dof_names")
    if dof_names is None:
        raise RuntimeError("Motion missing 'dof_names' (T1 requires explicit mapping)")
    T = base_pos.shape[0]

    try:
        import pybullet as p
        import pybullet_data
    except ImportError:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--quiet", "pybullet"]
        )
        import pybullet as p
        import pybullet_data

    out_dir = os.path.dirname(args.output_mp4)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    print(f"Motion:  {args.motion}  frames={T}  dofs={len(dof_names)}")
    print(f"URDF:    {args.urdf}")
    print(f"Output:  {args.output_mp4}")

    p.connect(p.DIRECT)
    p.setAdditionalSearchPath(pybullet_data.getDataPath())
    p.setGravity(0, 0, -9.81)
    p.loadURDF("plane.urdf")

    robot = p.loadURDF(
        args.urdf,
        basePosition=base_pos[0].tolist(),
        baseOrientation=base_quat[0].tolist(),
        useFixedBase=False,
    )

    n = p.getNumJoints(robot)
    pb_name_to_idx = {}
    for i in range(n):
        info = p.getJointInfo(robot, i)
        name = info[1].decode("utf-8")
        jtype = info[2]
        if jtype != p.JOINT_FIXED:
            pb_name_to_idx[name] = i

    mapping = []
    for mot_i, name in enumerate(dof_names):
        if name in pb_name_to_idx:
            mapping.append((pb_name_to_idx[name], mot_i))
    print(
        f"Mapped {len(mapping)}/{len(dof_names)} joints "
        f"(URDF has {n} joints, {len(pb_name_to_idx)} non-fixed)"
    )
    if len(mapping) == 0:
        print("URDF joints:", list(pb_name_to_idx.keys()))
        print("Motion dof_names:", list(dof_names))
        raise RuntimeError("Zero joints mapped — check URDF/motion compatibility")

    cam_distance = 3.0
    cam_yaw = 45
    cam_pitch = -20

    frames = []
    for t in range(T):
        bp = base_pos[t]
        bq = base_quat[t]
        p.resetBasePositionAndOrientation(robot, bp.tolist(), bq.tolist())
        for pb_i, mot_i in mapping:
            p.resetJointState(
                robot,
                pb_i,
                targetValue=float(joint_pos[t, mot_i]),
                targetVelocity=float(joint_vel[t, mot_i]),
            )

        cam_target = [float(bp[0]), float(bp[1]), float(bp[2]) + 0.2]
        view = p.computeViewMatrixFromYawPitchRoll(
            cameraTargetPosition=cam_target,
            distance=cam_distance,
            yaw=cam_yaw,
            pitch=cam_pitch,
            roll=0,
            upAxisIndex=2,
        )
        proj = p.computeProjectionMatrixFOV(
            fov=60, aspect=args.width / args.height, nearVal=0.1, farVal=100.0
        )
        _, _, px, _, _ = p.getCameraImage(
            width=args.width,
            height=args.height,
            viewMatrix=view,
            projectionMatrix=proj,
            renderer=p.ER_TINY_RENDERER,
        )
        frame = np.array(px, dtype=np.uint8).reshape(args.height, args.width, 4)
        frames.append(frame[:, :, :3].copy())

        if t % 50 == 0:
            print(f"  frame {t}/{T}", flush=True)

    p.disconnect()

    print(f"Encoding {len(frames)} frames -> {args.output_mp4}")
    proc = subprocess.Popen(
        [
            "ffmpeg", "-y",
            "-f", "rawvideo", "-vcodec", "rawvideo",
            "-s", f"{args.width}x{args.height}",
            "-pix_fmt", "rgb24",
            "-r", str(args.fps),
            "-i", "-",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-preset", "fast", "-crf", "23",
            args.output_mp4,
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    for f in frames:
        proc.stdin.write(f.tobytes())
    proc.stdin.close()
    proc.wait()
    if proc.returncode != 0:
        print("ffmpeg error:", proc.stderr.read().decode())
        sys.exit(1)

    fsize = os.path.getsize(args.output_mp4)
    print(
        f"Saved: {args.output_mp4} "
        f"({fsize / 1024:.1f} KB, {len(frames) / args.fps:.1f}s, {len(frames)} frames)"
    )


if __name__ == "__main__":
    main()
