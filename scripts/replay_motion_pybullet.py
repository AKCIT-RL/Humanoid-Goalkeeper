#!/usr/bin/env python3
"""Kinematic replay of goalkeeper motions using PyBullet (headless EGL rendering) to MP4.

Fallback for when IsaacGym Vulkan rendering is not available in Docker.
"""
import argparse
import os
import sys
import subprocess
import math

import numpy as np
import torch
import pybullet as p
import pybullet_data


def load_motion(pt_path):
    data = torch.load(pt_path, map_location="cpu")
    if not isinstance(data, dict):
        raise ValueError(f"Expected dict, got {type(data).__name__}")
    return data


def load_joint_mapping(mapping_path):
    with open(mapping_path) as f:
        lines = [l.strip().split() for l in f.readlines()]
    return {name: int(idx) for idx, name in lines}


def quat_xyzw_to_xyzw(q):
    """Motion data quaternion order is (x,y,z,w) which is already PyBullet's order."""
    return q


def main():
    parser = argparse.ArgumentParser(description="Replay goalkeeper motion via PyBullet")
    parser.add_argument("--motion", required=True, help="Path to .pt motion file")
    parser.add_argument("--urdf", required=True, help="Path to robot URDF")
    parser.add_argument("--output_mp4", required=True, help="Output MP4 path")
    parser.add_argument("--headless", action="store_true", default=True)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--mapping", default=None, help="Path to joint_id.txt")
    args = parser.parse_args()

    # Resolve paths
    for attr in ["motion", "urdf", "mapping"]:
        val = getattr(args, attr)
        if val is None:
            continue
        if not os.path.isabs(val):
            for base in ["/workspace", os.getcwd()]:
                candidate = os.path.join(base, val)
                if os.path.isfile(candidate):
                    setattr(args, attr, candidate)
                    break

    if args.mapping is None:
        args.mapping = "/workspace/legged_gym/resources/datasets/goalkeeper/joint_id.txt"

    output_dir = os.path.dirname(args.output_mp4)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    print(f"Motion:  {args.motion}")
    print(f"URDF:    {args.urdf}")
    print(f"Output:  {args.output_mp4}")
    print(f"Mapping: {args.mapping}")

    # Load data
    data = load_motion(args.motion)
    joint_id_map = load_joint_mapping(args.mapping)
    n_frames = data["base_position"].shape[0]
    print(f"Motion frames: {n_frames}, FPS: {args.fps}")

    # Connect PyBullet in DIRECT mode (headless)
    physicsClient = p.connect(p.DIRECT)
    p.setAdditionalSearchPath(pybullet_data.getDataPath())
    p.setGravity(0, 0, -9.81)

    # Load ground
    p.loadURDF("plane.urdf")

    # Load robot
    base_pos = data["base_position"][0].tolist()
    base_quat = data["base_pose"][0].tolist()  # xyzw
    robot_id = p.loadURDF(args.urdf, basePosition=base_pos, baseOrientation=base_quat,
                           useFixedBase=False, flags=p.URDF_USE_SELF_COLLISION)

    # Get joint info
    num_joints = p.getNumJoints(robot_id)
    pb_joint_map = {}  # joint_name -> pybullet_joint_index
    for i in range(num_joints):
        info = p.getJointInfo(robot_id, i)
        joint_name = info[1].decode("utf-8")
        joint_type = info[2]
        if joint_type != p.JOINT_FIXED:
            pb_joint_map[joint_name] = i

    print(f"PyBullet joints: {num_joints} total, {len(pb_joint_map)} active")
    print(f"Active joints: {list(pb_joint_map.keys())}")

    # Build mapping: pybullet_joint_idx -> motion_data_col_idx
    # Prefer dof_names embedded in the trajectory (matches joint_position columns 1:1).
    # Fallback to joint_id.txt mapping if dof_names is absent.
    dof_mapping = []
    motion_dof_names = data.get("dof_names")
    if motion_dof_names is not None:
        name_to_motion_idx = {name: i for i, name in enumerate(motion_dof_names)}
        for joint_name, pb_idx in pb_joint_map.items():
            if joint_name in name_to_motion_idx:
                dof_mapping.append((pb_idx, name_to_motion_idx[joint_name]))
        print(f"Mapped {len(dof_mapping)}/{len(pb_joint_map)} PyBullet joints via dof_names ({len(motion_dof_names)} motion DoFs)")
    else:
        for joint_name, pb_idx in pb_joint_map.items():
            if joint_name in joint_id_map:
                motion_idx = joint_id_map[joint_name]
                dof_mapping.append((pb_idx, motion_idx))
        print(f"Mapped {len(dof_mapping)} joints via joint_id.txt fallback")

    # Camera setup (target updated per-frame to follow the robot)
    cam_distance = 3.0
    cam_yaw = 45
    cam_pitch = -20
    cam_target = [0.0, 0.0, 0.7]

    # Render loop
    frames = []
    for t in range(n_frames):
        # Set base pose
        base_pos = data["base_position"][t].tolist()
        base_quat = data["base_pose"][t].tolist()
        p.resetBasePositionAndOrientation(robot_id, base_pos, base_quat)

        # Camera follows the robot (env_origins offset means robot is not at world origin)
        cam_target = [base_pos[0], base_pos[1], base_pos[2] + 0.2]

        # Set joint positions
        joint_pos = data["joint_position"][t]
        joint_vel = data["joint_velocity"][t]
        for pb_idx, motion_idx in dof_mapping:
            p.resetJointState(robot_id, pb_idx,
                              targetValue=joint_pos[motion_idx].item(),
                              targetVelocity=joint_vel[motion_idx].item())

        # Step to update state
        p.stepSimulation()

        # Render
        view_matrix = p.computeViewMatrixFromYawPitchRoll(
            cameraTargetPosition=cam_target,
            distance=cam_distance,
            yaw=cam_yaw,
            pitch=cam_pitch,
            roll=0,
            upAxisIndex=2,
        )
        proj_matrix = p.computeProjectionMatrixFOV(
            fov=60,
            aspect=args.width / args.height,
            nearVal=0.1,
            farVal=100.0,
        )
        _, _, px, _, _ = p.getCameraImage(
            width=args.width,
            height=args.height,
            viewMatrix=view_matrix,
            projectionMatrix=proj_matrix,
            renderer=p.ER_TINY_RENDERER,
        )
        frame = np.array(px, dtype=np.uint8).reshape(args.height, args.width, 4)
        frames.append(frame[:, :, :3])  # RGB only

        if t % 50 == 0:
            print(f"  Frame {t}/{n_frames}", flush=True)

    p.disconnect()

    print(f"Rendered {len(frames)} frames, encoding MP4...")

    # Encode MP4 via ffmpeg pipe
    cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo",
        "-vcodec", "rawvideo",
        "-s", f"{args.width}x{args.height}",
        "-pix_fmt", "rgb24",
        "-r", str(args.fps),
        "-i", "-",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-preset", "fast",
        "-crf", "23",
        args.output_mp4,
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    for frame in frames:
        proc.stdin.write(frame.tobytes())
    proc.stdin.close()
    proc.wait()

    if proc.returncode != 0:
        stderr = proc.stderr.read().decode()
        print(f"ffmpeg error: {stderr}")
        sys.exit(1)

    fsize = os.path.getsize(args.output_mp4)
    duration = len(frames) / args.fps
    print(f"Saved: {args.output_mp4} ({fsize / 1024:.1f} KB, {duration:.1f}s, {len(frames)} frames)")


if __name__ == "__main__":
    main()
