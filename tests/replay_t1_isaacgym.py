#!/usr/bin/env python3
"""Tester-owned IsaacGym kinematic replay for T1 motions.

Not modifying production `scripts/replay_motion_isaacgym.py` because it
hardcodes the G1 joint mapping path (`/workspace/legged_gym/resources/
datasets/goalkeeper/joint_id.txt`) — that's a bug to report but not fix here.

This script mirrors the production replay but uses `dof_names` embedded
in the .pt to map joints, so it works for any robot.
"""
import argparse
import os
import subprocess
import sys

# IsaacGym must be imported BEFORE torch.
from isaacgym import gymapi, gymtorch  # noqa: F401

import numpy as np
import torch


def load_motion(pt_path: str) -> dict:
    data = torch.load(pt_path, map_location="cpu")
    if not isinstance(data, dict):
        raise ValueError(f"Expected dict, got {type(data).__name__}")
    return data


def create_sim(gym):
    sim_params = gymapi.SimParams()
    sim_params.dt = 1.0 / 60.0
    sim_params.substeps = 2
    sim_params.up_axis = gymapi.UP_AXIS_Z
    sim_params.gravity = gymapi.Vec3(0.0, 0.0, -9.81)
    sim_params.physx.solver_type = 1
    sim_params.physx.num_position_iterations = 4
    sim_params.physx.num_velocity_iterations = 1
    sim_params.physx.contact_offset = 0.02
    sim_params.physx.rest_offset = 0.0
    sim_params.physx.use_gpu = True
    sim = gym.create_sim(0, 0, gymapi.SIM_PHYSX, sim_params)
    if sim is None:
        raise RuntimeError("Failed to create sim")
    return sim


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--motion", required=True)
    ap.add_argument("--urdf", required=True)
    ap.add_argument("--output_mp4", required=True)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=480)
    args = ap.parse_args()

    data = load_motion(args.motion)
    n_frames = data["base_position"].shape[0]
    n_joints = data["joint_position"].shape[1]
    dof_names_motion = data.get("dof_names")
    if dof_names_motion is None:
        raise RuntimeError("Motion file missing 'dof_names' (T1 needs explicit mapping)")
    print(f"Motion: {args.motion}  frames={n_frames}  joints={n_joints}")
    print(f"URDF:   {args.urdf}")

    os.makedirs(os.path.dirname(args.output_mp4) or ".", exist_ok=True)

    gym = gymapi.acquire_gym()
    sim = create_sim(gym)

    plane = gymapi.PlaneParams()
    plane.normal = gymapi.Vec3(0, 0, 1)
    gym.add_ground(sim, plane)

    asset_opts = gymapi.AssetOptions()
    asset_opts.fix_base_link = False
    asset_opts.default_dof_drive_mode = gymapi.DOF_MODE_POS
    asset_opts.collapse_fixed_joints = False
    asset_opts.replace_cylinder_with_capsule = True
    asset = gym.load_asset(sim, os.path.dirname(args.urdf),
                            os.path.basename(args.urdf), asset_opts)
    if asset is None:
        raise RuntimeError("Failed to load asset")

    num_dofs = gym.get_asset_dof_count(asset)
    dof_names = list(gym.get_asset_dof_names(asset))
    print(f"Robot DOFs={num_dofs}  names={dof_names}", flush=True)

    env = gym.create_env(sim, gymapi.Vec3(-3, -3, 0), gymapi.Vec3(3, 3, 3), 1)
    pose = gymapi.Transform()
    pose.p = gymapi.Vec3(0, 0, 0.8)
    pose.r = gymapi.Quat(0, 0, 0, 1)
    actor = gym.create_actor(env, asset, pose, "robot", 0, 0)

    props = gym.get_actor_dof_properties(env, actor)
    for i in range(num_dofs):
        props["driveMode"][i] = gymapi.DOF_MODE_POS
        props["stiffness"][i] = 1000.0
        props["damping"][i] = 100.0
    gym.set_actor_dof_properties(env, actor, props)

    # Camera (GPU tensor mode — same as play_record.py to avoid segfaults)
    cam_props = gymapi.CameraProperties()
    cam_props.width = args.width
    cam_props.height = args.height
    cam_props.enable_tensors = True
    cam = gym.create_camera_sensor(env, cam_props)
    if cam == -1:
        raise RuntimeError("create_camera_sensor returned -1")
    gym.set_camera_location(cam, env,
                            gymapi.Vec3(2.5, 2.0, 1.5),
                            gymapi.Vec3(0.0, 0.0, 0.7))

    gym.prepare_sim(sim)

    _root = gym.acquire_actor_root_state_tensor(sim)
    _dof = gym.acquire_dof_state_tensor(sim)
    root_t = gymtorch.wrap_tensor(_root)
    dof_t = gymtorch.wrap_tensor(_dof)

    # Build sim_idx -> motion_idx map via dof_names
    name_to_motion_idx = {n: i for i, n in enumerate(dof_names_motion)}
    mapping = []
    for sim_i, dn in enumerate(dof_names):
        if dn in name_to_motion_idx:
            mapping.append((sim_i, name_to_motion_idx[dn]))
    print(f"Mapped {len(mapping)}/{num_dofs} DOFs from motion")

    frames = []
    actor_idx = torch.tensor([0], dtype=torch.int32, device="cuda:0")

    for t in range(n_frames):
        bp = data["base_position"][t]
        bq = data["base_pose"][t]
        root_t[0, 0:3] = bp
        root_t[0, 3:7] = bq
        if t < n_frames - 1:
            v = (data["base_position"][t + 1] - bp) * args.fps
        else:
            v = torch.zeros(3)
        root_t[0, 7:10] = v
        root_t[0, 10:13] = 0.0
        gym.set_actor_root_state_tensor_indexed(
            sim, _root, gymtorch.unwrap_tensor(actor_idx), 1
        )

        jp = data["joint_position"][t]
        jv = data["joint_velocity"][t]
        for sim_i, mot_i in mapping:
            dof_t[sim_i, 0] = jp[mot_i]
            dof_t[sim_i, 1] = jv[mot_i]
        gym.set_dof_state_tensor_indexed(
            sim, _dof, gymtorch.unwrap_tensor(actor_idx), 1
        )

        targets = np.zeros(num_dofs, dtype=np.float32)
        for sim_i, mot_i in mapping:
            targets[sim_i] = float(jp[mot_i])
        gym.set_actor_dof_position_targets(env, actor, targets)

        # camera follow
        bp_xyz = bp.tolist()
        gym.set_camera_location(cam, env,
                                gymapi.Vec3(bp_xyz[0] + 2.5, bp_xyz[1] + 2.0, bp_xyz[2] + 0.8),
                                gymapi.Vec3(bp_xyz[0], bp_xyz[1], bp_xyz[2]))

        gym.simulate(sim)
        gym.fetch_results(sim, True)
        gym.step_graphics(sim)
        gym.render_all_camera_sensors(sim)
        gym.start_access_image_tensors(sim)
        cam_tensor = gym.get_camera_image_gpu_tensor(
            sim, env, cam, gymapi.IMAGE_COLOR
        )
        torch_t = gymtorch.wrap_tensor(cam_tensor)
        arr = torch_t.cpu().numpy().astype(np.uint8)
        frames.append(arr[:, :, :3].copy())
        gym.end_access_image_tensors(sim)
        if t % 25 == 0:
            print(f"  frame {t}/{n_frames}", flush=True)

    print(f"Encoding {len(frames)} frames → {args.output_mp4}")
    proc = subprocess.Popen([
        "ffmpeg", "-y",
        "-f", "rawvideo", "-vcodec", "rawvideo",
        "-s", f"{args.width}x{args.height}",
        "-pix_fmt", "rgb24",
        "-r", str(args.fps),
        "-i", "-",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-preset", "fast", "-crf", "23",
        args.output_mp4,
    ], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    for f in frames:
        proc.stdin.write(f.tobytes())
    proc.stdin.close()
    proc.wait()
    if proc.returncode != 0:
        err = proc.stderr.read().decode()
        print(f"ffmpeg failed: {err}")
        sys.exit(2)
    sz = os.path.getsize(args.output_mp4)
    print(f"OK {args.output_mp4} ({sz/1024:.1f} KB)")
    gym.destroy_sim(sim)


if __name__ == "__main__":
    main()
