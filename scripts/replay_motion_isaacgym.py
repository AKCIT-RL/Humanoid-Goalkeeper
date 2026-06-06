#!/usr/bin/env python3
"""Kinematic replay of goalkeeper motions in IsaacGym with offscreen rendering to MP4."""
# KNOWN ISSUE: Booster T1 URDF currently segfaults in IsaacGym Preview 4 during
# asset/actor creation. Workaround: use scripts/replay_motion_pybullet.py for T1.
import argparse
import os
import sys

from isaacgym import gymapi, gymtorch, gymutil

import numpy as np
import torch

# Ensure legged_gym is importable
sys.path.insert(0, "/workspace/legged_gym")


def quat_xyzw_to_wxyz(q):
    """Convert quaternion from (x,y,z,w) to gymapi Quat(x,y,z,w) - IsaacGym uses xyzw natively."""
    return q


def load_motion(pt_path):
    """Load a .pt motion file and return the data dict."""
    data = torch.load(pt_path, map_location="cpu")
    if not isinstance(data, dict):
        raise ValueError(f"Expected dict, got {type(data).__name__}")
    return data


def create_sim(gym, headless=True, use_gpu=True):
    """Create IsaacGym sim with PhysX."""
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
    sim_params.physx.use_gpu = use_gpu

    compute_device = 0
    graphics_device = 0 if not headless else 0  # Need graphics device for camera

    sim = gym.create_sim(compute_device, graphics_device, gymapi.SIM_PHYSX, sim_params)
    if sim is None:
        raise RuntimeError("Failed to create sim")
    return sim


def setup_camera(gym, env, width=640, height=480):
    """Create offscreen camera sensor."""
    cam_props = gymapi.CameraProperties()
    cam_props.width = width
    cam_props.height = height
    cam_props.enable_tensors = False

    cam_handle = gym.create_camera_sensor(env, cam_props)

    # Position camera to see the robot from the side-front
    cam_pos = gymapi.Vec3(2.5, 2.0, 1.5)
    cam_target = gymapi.Vec3(0.0, 0.0, 0.7)
    gym.set_camera_location(cam_handle, env, cam_pos, cam_target)

    return cam_handle


def render_frame(gym, sim, env, cam_handle, width=640, height=480):
    """Render one frame from the camera sensor and return as numpy RGB array."""
    gym.step_graphics(sim)
    gym.render_all_camera_sensors(sim)
    image = gym.get_camera_image(sim, env, cam_handle, gymapi.IMAGE_COLOR)
    # image is a flat array of RGBA uint8
    img = np.frombuffer(image, dtype=np.uint8).reshape(height, width, 4)
    return img[:, :, :3]  # RGB only


def main():
    parser = argparse.ArgumentParser(description="Replay goalkeeper motion in IsaacGym")
    parser.add_argument("--motion", required=True, help="Path to .pt motion file")
    parser.add_argument("--urdf", required=True, help="Path to robot URDF")
    parser.add_argument("--output_mp4", required=True, help="Output MP4 path")
    parser.add_argument(
        "--mapping",
        default=None,
        help="Path to joint_id.txt mapping (lines '<idx> <joint_name>'). "
             "If omitted, falls back to the .pt's 'dof_names' key, or to the "
             "default G1 joint_id.txt at "
             "/workspace/legged_gym/resources/datasets/goalkeeper/joint_id.txt.",
    )
    parser.add_argument("--headless", action="store_true", default=True)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    args = parser.parse_args()

    # Resolve paths
    motion_path = args.motion
    urdf_path = args.urdf
    for p_attr in ["motion", "urdf"]:
        p = getattr(args, p_attr)
        if not os.path.isabs(p):
            for base in ["/workspace", os.getcwd()]:
                candidate = os.path.join(base, p)
                if os.path.isfile(candidate):
                    setattr(args, p_attr, candidate)
                    break
    motion_path = args.motion
    urdf_path = args.urdf

    output_dir = os.path.dirname(args.output_mp4)
    if output_dir and not os.path.isdir(output_dir):
        os.makedirs(output_dir, exist_ok=True)

    print(f"Motion: {motion_path}")
    print(f"URDF:   {urdf_path}")
    print(f"Output: {args.output_mp4}")

    # Load motion data
    data = load_motion(motion_path)
    n_frames = data["base_position"].shape[0]
    n_joints_motion = data["joint_position"].shape[1]
    print(f"Motion frames: {n_frames}, joints in data: {n_joints_motion}")

    # Resolve joint mapping (motion joint name -> motion joint index).
    # Priority: 1) explicit --mapping file, 2) 'dof_names' inside the .pt,
    # 3) fallback to default G1 joint_id.txt.
    if args.mapping is not None:
        mapping_path = args.mapping
        with open(mapping_path) as f:
            lines = [l.strip().split() for l in f.readlines() if l.strip()]
        joint_id_map = {name: int(idx) for idx, name in lines}
        print(f"Mapping: {mapping_path} ({len(joint_id_map)} joints)")
    elif "dof_names" in data:
        joint_id_map = {name: i for i, name in enumerate(data["dof_names"])}
        print(f"Mapping: from .pt 'dof_names' ({len(joint_id_map)} joints)")
    else:
        mapping_path = "/workspace/legged_gym/resources/datasets/goalkeeper/joint_id.txt"
        with open(mapping_path) as f:
            lines = [l.strip().split() for l in f.readlines() if l.strip()]
        joint_id_map = {name: int(idx) for idx, name in lines}
        print(f"Mapping: {mapping_path} (fallback G1, {len(joint_id_map)} joints)")

    # Initialize IsaacGym
    gym = gymapi.acquire_gym()
    sim = create_sim(gym, headless=args.headless)

    # Add ground plane
    plane_params = gymapi.PlaneParams()
    plane_params.normal = gymapi.Vec3(0.0, 0.0, 1.0)
    gym.add_ground(sim, plane_params)

    # Load robot asset
    urdf_dir = os.path.dirname(urdf_path)
    urdf_file = os.path.basename(urdf_path)
    asset_options = gymapi.AssetOptions()
    asset_options.fix_base_link = False
    asset_options.use_mesh_materials = True
    asset_options.default_dof_drive_mode = gymapi.DOF_MODE_POS
    asset_options.collapse_fixed_joints = False
    asset_options.replace_cylinder_with_capsule = True

    robot_asset = gym.load_asset(sim, urdf_dir, urdf_file, asset_options)
    if robot_asset is None:
        raise RuntimeError(f"Failed to load asset: {urdf_path}")

    num_dofs = gym.get_asset_dof_count(robot_asset)
    dof_names = gym.get_asset_dof_names(robot_asset)
    print(f"Robot DOFs: {num_dofs}")
    print(f"DOF names: {list(dof_names)}")

    # Create environment
    env_spacing = 3.0
    env_lower = gymapi.Vec3(-env_spacing, -env_spacing, 0.0)
    env_upper = gymapi.Vec3(env_spacing, env_spacing, env_spacing)
    env = gym.create_env(sim, env_lower, env_upper, 1)

    # Create actor
    pose = gymapi.Transform()
    pose.p = gymapi.Vec3(0.0, 0.0, 0.8)
    pose.r = gymapi.Quat(0.0, 0.0, 0.0, 1.0)
    actor = gym.create_actor(env, robot_asset, pose, "g1", 0, 0)

    # Set high PD gains so position targets are tracked closely
    props = gym.get_actor_dof_properties(env, actor)
    for i in range(num_dofs):
        props["driveMode"][i] = gymapi.DOF_MODE_POS
        props["stiffness"][i] = 1000.0
        props["damping"][i] = 100.0
    gym.set_actor_dof_properties(env, actor, props)

    # Setup camera
    cam_handle = setup_camera(gym, env, args.width, args.height)

    # Prepare sim
    gym.prepare_sim(sim)

    # Get state tensors
    _root_tensor = gym.acquire_actor_root_state_tensor(sim)
    _dof_state_tensor = gym.acquire_dof_state_tensor(sim)
    root_tensor = gymtorch.wrap_tensor(_root_tensor)
    dof_state_tensor = gymtorch.wrap_tensor(_dof_state_tensor)

    # Build DOF mapping: motion joint index -> sim DOF index
    dof_mapping = []  # list of (sim_dof_idx, motion_joint_idx)
    for sim_idx, dof_name in enumerate(dof_names):
        if dof_name in joint_id_map:
            motion_idx = joint_id_map[dof_name]
            dof_mapping.append((sim_idx, motion_idx))

    print(f"Mapped {len(dof_mapping)}/{num_dofs} DOFs to motion data ({n_joints_motion} motion joints)")

    # Render loop
    frames = []
    actor_idx = torch.tensor([0], dtype=torch.int32, device="cuda:0")

    for t in range(n_frames):
        # Set root state (base position + quaternion)
        base_pos = data["base_position"][t]  # (3,)
        base_quat = data["base_pose"][t]  # (4,) xyzw

        root_tensor[0, 0] = base_pos[0].item()
        root_tensor[0, 1] = base_pos[1].item()
        root_tensor[0, 2] = base_pos[2].item()
        root_tensor[0, 3] = base_quat[0].item()  # x
        root_tensor[0, 4] = base_quat[1].item()  # y
        root_tensor[0, 5] = base_quat[2].item()  # z
        root_tensor[0, 6] = base_quat[3].item()  # w
        # Linear velocity
        if t < n_frames - 1:
            base_vel = (data["base_position"][t + 1] - data["base_position"][t]) * args.fps
        else:
            base_vel = torch.zeros(3)
        root_tensor[0, 7] = base_vel[0].item()
        root_tensor[0, 8] = base_vel[1].item()
        root_tensor[0, 9] = base_vel[2].item()
        # Angular velocity
        root_tensor[0, 10] = 0.0
        root_tensor[0, 11] = 0.0
        root_tensor[0, 12] = 0.0

        gym.set_actor_root_state_tensor_indexed(sim, _root_tensor,
                                                 gymtorch.unwrap_tensor(actor_idx), 1)

        # Set DOF positions as targets
        joint_pos = data["joint_position"][t]  # (n_joints_motion,)
        joint_vel = data["joint_velocity"][t]  # (n_joints_motion,)

        for sim_idx, motion_idx in dof_mapping:
            dof_state_tensor[sim_idx, 0] = joint_pos[motion_idx].item()
            dof_state_tensor[sim_idx, 1] = joint_vel[motion_idx].item()

        gym.set_dof_state_tensor_indexed(sim, _dof_state_tensor,
                                          gymtorch.unwrap_tensor(actor_idx), 1)

        # Also set position targets for PD controller
        dof_pos_targets = torch.zeros(num_dofs, dtype=torch.float32)
        for sim_idx, motion_idx in dof_mapping:
            dof_pos_targets[sim_idx] = joint_pos[motion_idx].item()
        gym.set_actor_dof_position_targets(env, actor, dof_pos_targets.numpy())

        # Step simulation (needed for rendering pipeline)
        gym.simulate(sim)
        gym.fetch_results(sim, True)

        # Render
        frame = render_frame(gym, sim, env, cam_handle, args.width, args.height)
        frames.append(frame)

        if t % 50 == 0:
            print(f"  Frame {t}/{n_frames}")

    print(f"Rendered {len(frames)} frames")

    # Save MP4 using ffmpeg via pipe
    import subprocess
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
        # Fallback: save as individual PNGs
        print("Falling back to PNG sequence...")
        png_dir = args.output_mp4.replace(".mp4", "_frames")
        os.makedirs(png_dir, exist_ok=True)
        from PIL import Image
        for i, frame in enumerate(frames):
            Image.fromarray(frame).save(os.path.join(png_dir, f"{i:04d}.png"))
        print(f"Saved {len(frames)} PNGs to {png_dir}")
    else:
        fsize = os.path.getsize(args.output_mp4)
        duration = len(frames) / args.fps
        print(f"Saved: {args.output_mp4} ({fsize / 1024:.1f} KB, {duration:.1f}s, {len(frames)} frames)")

    gym.destroy_sim(sim)


if __name__ == "__main__":
    main()
