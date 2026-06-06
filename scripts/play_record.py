#!/usr/bin/env python3
"""Run a trained policy checkpoint and record an MP4 video.

Tries three rendering strategies in order:
  1. IsaacGym camera sensor (offscreen)
  2. IsaacGym viewer + write_viewer_image_to_file
  3. Fallback: save trajectory .pt and replay via PyBullet
"""
import argparse
import os
import sys
import signal
import time
import shutil
import subprocess
import traceback

import faulthandler

faulthandler.enable()

# IsaacGym must be imported before torch and legged_gym
import isaacgym
from isaacgym import gymapi, gymtorch, gymutil

import numpy as np
import torch

from legged_gym.envs import *
from legged_gym.utils import get_args, task_registry


def parse_play_args():
    """Parse play_record-specific args, then merge with IsaacGym args."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--exptid", type=str, default="ours_5k_20260605_152157")
    parser.add_argument("--checkpoint", type=int, default=4999)
    parser.add_argument("--num_envs", type=int, default=6)
    parser.add_argument("--steps", type=int, default=600)
    parser.add_argument("--output", type=str, default=None)
    parser.add_argument("--width", type=int, default=720)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--camera_pos", type=str, default="5,0,1.5")
    parser.add_argument("--camera_target", type=str, default="0,0,0.5")
    parser.add_argument("--strategy", type=int, default=0,
                        help="Force a strategy (1,2,3). 0 = try in order.")
    play_args, remaining = parser.parse_known_args()

    if play_args.output is None:
        play_args.output = f"/workspace/data/play_videos/ours_{play_args.exptid}_ckpt{play_args.checkpoint}.mp4"

    play_args.camera_pos = [float(x) for x in play_args.camera_pos.split(",")]
    play_args.camera_target = [float(x) for x in play_args.camera_target.split(",")]

    # num_envs must be a multiple of 6 (env splits into 6 ball regions)
    if play_args.num_envs % 6 != 0:
        play_args.num_envs = max(6, (play_args.num_envs // 6 + 1) * 6)
        print(f"WARNING: num_envs adjusted to {play_args.num_envs} (must be multiple of 6)")

    # Inject remaining args back so gymutil.parse_arguments can consume them
    sys.argv = [sys.argv[0]] + remaining
    return play_args


def setup_env_and_policy(play_args, headless=True):
    """Create env and load policy from checkpoint. Returns (env, policy, gym, sim, args)."""
    ig_args = get_args()
    ig_args.task = play_args.exptid.split("_")[0] if not hasattr(ig_args, "task") else ig_args.task
    # Force task to "29" (the goalkeeper task)
    ig_args.task = "29"
    ig_args.exptid = play_args.exptid
    ig_args.checkpoint = play_args.checkpoint
    ig_args.headless = headless

    env_cfg, train_cfg = task_registry.get_cfgs(name=ig_args.task)
    env_cfg.env.num_envs = play_args.num_envs
    env_cfg.env.episode_length_s = max(3, (play_args.steps * 0.02) + 1)
    env_cfg.env.play = True
    env_cfg.noise.add_noise = False
    env_cfg.domain_rand.randomize_initial_joint_pos = False
    env_cfg.domain_rand.randomize_friction = True
    env_cfg.domain_rand.push_robots = False
    env_cfg.domain_rand.push_interval_s = 6
    env_cfg.domain_rand.randomize_base_mass = False
    env_cfg.domain_rand.randomize_base_com = False

    env, _ = task_registry.make_env(name=ig_args.task, args=ig_args, env_cfg=env_cfg)
    obs = env.get_observations()

    train_cfg.runner.resume = True
    ppo_runner, train_cfg = task_registry.make_alg_runner(
        env=env, name=ig_args.task, args=ig_args, train_cfg=train_cfg)
    policy = ppo_runner.get_inference_policy(device=env.device)

    return env, policy, ig_args


def strategy1_camera_sensor(env, policy, play_args):
    """Use gym.create_camera_sensor for offscreen rendering."""
    print("\n=== Strategy 1: camera sensor (offscreen) ===")
    gym = env.gym
    sim = env.sim
    env_handle = env.envs[0]

    cam_props = gymapi.CameraProperties()
    cam_props.width = play_args.width
    cam_props.height = play_args.height
    cam_props.enable_tensors = True

    cam_handle = gym.create_camera_sensor(env_handle, cam_props)
    if cam_handle == -1:
        raise RuntimeError("create_camera_sensor returned -1")

    cam_pos = gymapi.Vec3(*play_args.camera_pos)
    cam_target = gymapi.Vec3(*play_args.camera_target)
    gym.set_camera_location(cam_handle, env_handle, cam_pos, cam_target)

    frames = []
    obs = env.get_observations()
    total_reward = 0.0
    t0 = time.time()

    for t in range(play_args.steps):
        actions = policy(obs.detach())
        obs, privileged_obs, rews, dones, infos, _, _ = env.step(actions.detach())
        total_reward += rews.mean().item()

        gym.fetch_results(sim, True)
        gym.step_graphics(sim)
        gym.render_all_camera_sensors(sim)
        gym.start_access_image_tensors(sim)

        cam_tensor = gym.get_camera_image_gpu_tensor(sim, env_handle, cam_handle, gymapi.IMAGE_COLOR)
        torch_tensor = gymtorch.wrap_tensor(cam_tensor)
        frame = torch_tensor.cpu().numpy().astype(np.uint8)
        # Shape is (H, W, 4) RGBA -> take RGB
        frames.append(frame[:, :, :3].copy())

        gym.end_access_image_tensors(sim)

        if t % 100 == 0:
            print(f"  Step {t}/{play_args.steps}, mean_rew={rews.mean().item():.4f}")

    elapsed = time.time() - t0
    avg_rew = total_reward / play_args.steps
    print(f"  Done. {len(frames)} frames in {elapsed:.1f}s. Avg reward: {avg_rew:.4f}")
    return frames, avg_rew


def strategy2_viewer(env, policy, play_args):
    """Use viewer + write_viewer_image_to_file."""
    print("\n=== Strategy 2: viewer + write_viewer_image_to_file ===")
    gym = env.gym
    sim = env.sim

    if env.viewer is None:
        raise RuntimeError("No viewer available (env created headless). "
                           "Strategy 2 needs headless=False.")

    frame_dir = "/tmp/play_record_frames"
    if os.path.exists(frame_dir):
        shutil.rmtree(frame_dir)
    os.makedirs(frame_dir)

    cam_pos = gymapi.Vec3(*play_args.camera_pos)
    cam_target = gymapi.Vec3(*play_args.camera_target)
    gym.viewer_camera_look_at(env.viewer, None, cam_pos, cam_target)

    obs = env.get_observations()
    total_reward = 0.0
    t0 = time.time()

    for t in range(play_args.steps):
        actions = policy(obs.detach())
        obs, privileged_obs, rews, dones, infos, _, _ = env.step(actions.detach())
        total_reward += rews.mean().item()

        gym.fetch_results(sim, True)
        gym.step_graphics(sim)
        gym.draw_viewer(env.viewer, sim, True)

        frame_path = os.path.join(frame_dir, f"{t:05d}.png")
        gym.write_viewer_image_to_file(env.viewer, frame_path)

        if t % 100 == 0:
            print(f"  Step {t}/{play_args.steps}, mean_rew={rews.mean().item():.4f}")

    elapsed = time.time() - t0
    avg_rew = total_reward / play_args.steps
    print(f"  Done. {play_args.steps} frames in {elapsed:.1f}s. Avg reward: {avg_rew:.4f}")

    # Encode with ffmpeg
    print("  Encoding MP4 with ffmpeg...")
    out_path = play_args.output
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-framerate", "50",
        "-i", os.path.join(frame_dir, "%05d.png"),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-preset", "fast",
        "-crf", "23",
        out_path,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print(f"  ffmpeg error: {proc.stderr}")
        raise RuntimeError("ffmpeg failed")
    shutil.rmtree(frame_dir)
    return None, avg_rew  # frames already saved as MP4


def strategy3_trajectory(env, policy, play_args):
    """Save trajectory data and replay via PyBullet."""
    print("\n=== Strategy 3: save trajectory + PyBullet replay ===")
    gym = env.gym
    sim = env.sim

    obs = env.get_observations()
    total_reward = 0.0
    t0 = time.time()

    root_positions = []
    root_orientations = []
    dof_positions = []

    for t in range(play_args.steps):
        actions = policy(obs.detach())
        obs, privileged_obs, rews, dones, infos, _, _ = env.step(actions.detach())
        total_reward += rews.mean().item()

        # Collect trajectory from env 0
        root_states = env.root_states  # (num_envs * num_actors, 13)
        num_actors = root_states.shape[0] // env.num_envs
        robot_root = root_states[0 * num_actors]  # env 0, actor 0
        root_positions.append(robot_root[:3].cpu().clone())
        root_orientations.append(robot_root[3:7].cpu().clone())
        dof_positions.append(env.dof_pos[0].cpu().clone())

        if t % 100 == 0:
            print(f"  Step {t}/{play_args.steps}, mean_rew={rews.mean().item():.4f}")

    elapsed = time.time() - t0
    avg_rew = total_reward / play_args.steps
    print(f"  Done. {play_args.steps} steps in {elapsed:.1f}s. Avg reward: {avg_rew:.4f}")

    # Save trajectory
    traj_path = play_args.output.replace(".mp4", "_trajectory.pt")
    os.makedirs(os.path.dirname(traj_path), exist_ok=True)
    traj_data = {
        "base_position": torch.stack(root_positions),       # (T, 3)
        "base_pose": torch.stack(root_orientations),         # (T, 4)  xyzw
        "joint_position": torch.stack(dof_positions),        # (T, num_dof)
        "joint_velocity": torch.zeros_like(torch.stack(dof_positions)),  # zeros for kinematic replay
        "dof_names": list(env.dof_names),                    # IsaacGym DoF order (matches joint_position columns)
    }
    torch.save(traj_data, traj_path)
    print(f"  Saved trajectory: {traj_path} ({os.path.getsize(traj_path) / 1024:.1f} KB)")

    # Replay via PyBullet
    urdf_path = "/workspace/legged_gym/resources/robots/g1/urdf/g1_29.urdf"
    mapping_path = "/workspace/data/goalkeeper_ours/joint_id.txt"

    # Check if mapping file exists; if not, skip pybullet rendering
    if not os.path.isfile(mapping_path):
        # Try alternate paths
        for alt in ["/workspace/legged_gym/resources/datasets/goalkeeper/joint_id.txt"]:
            if os.path.isfile(alt):
                mapping_path = alt
                break

    pybullet_cmd = [
        sys.executable, "-m", "pip", "install", "pybullet", "--quiet",
    ]
    subprocess.run(pybullet_cmd, capture_output=True)

    pybullet_cmd = [
        sys.executable, "/workspace/scripts/replay_motion_pybullet.py",
        "--motion", traj_path,
        "--urdf", urdf_path,
        "--output_mp4", play_args.output,
        "--fps", "50",
        "--width", str(play_args.width),
        "--height", str(play_args.height),
        "--mapping", mapping_path,
    ]
    print(f"  Running PyBullet replay: {' '.join(pybullet_cmd)}")
    proc = subprocess.run(pybullet_cmd, capture_output=True, text=True)
    print(proc.stdout)
    if proc.returncode != 0:
        print(f"  PyBullet error: {proc.stderr}")
        print("  WARNING: PyBullet replay failed. Trajectory saved but no MP4.")
        return None, avg_rew

    return None, avg_rew  # MP4 already written by subprocess


def save_frames_to_mp4(frames, output_path, fps=50):
    """Encode frames list to MP4 via ffmpeg pipe."""
    if not frames:
        raise ValueError("No frames to encode")

    h, w = frames[0].shape[:2]
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo",
        "-vcodec", "rawvideo",
        "-s", f"{w}x{h}",
        "-pix_fmt", "rgb24",
        "-r", str(fps),
        "-i", "-",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-preset", "fast",
        "-crf", "23",
        output_path,
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    for frame in frames:
        proc.stdin.write(frame.tobytes())
    proc.stdin.close()
    proc.wait()

    if proc.returncode != 0:
        stderr = proc.stderr.read().decode()
        raise RuntimeError(f"ffmpeg failed: {stderr}")

    fsize = os.path.getsize(output_path)
    duration = len(frames) / fps
    print(f"  Saved MP4: {output_path} ({fsize / 1024:.1f} KB, {duration:.1f}s, {len(frames)} frames)")


def main():
    play_args = parse_play_args()

    print(f"Experiment: {play_args.exptid}")
    print(f"Checkpoint: {play_args.checkpoint}")
    print(f"Num envs:   {play_args.num_envs}")
    print(f"Steps:      {play_args.steps}")
    print(f"Output:     {play_args.output}")
    print(f"Resolution: {play_args.width}x{play_args.height}")

    strategies_to_try = [1, 2, 3] if play_args.strategy == 0 else [play_args.strategy]
    errors = {}
    t_total_start = time.time()

    for strat in strategies_to_try:
        try:
            # Strategies 1 needs graphics_device; strategies 2 needs viewer; 3 is headless
            headless = (strat == 3)
            print(f"\n{'='*60}")
            print(f"Setting up env (headless={headless}) for strategy {strat}...")
            env, policy, ig_args = setup_env_and_policy(play_args, headless=headless)

            if strat == 1:
                frames, avg_rew = strategy1_camera_sensor(env, policy, play_args)
                save_frames_to_mp4(frames, play_args.output)
            elif strat == 2:
                _, avg_rew = strategy2_viewer(env, policy, play_args)
            elif strat == 3:
                _, avg_rew = strategy3_trajectory(env, policy, play_args)

            t_total = time.time() - t_total_start
            print(f"\n{'='*60}")
            print(f"SUCCESS with strategy {strat}")
            print(f"Total time: {t_total:.1f}s")
            print(f"Avg reward: {avg_rew:.4f}")

            if avg_rew < 0.01:
                print("NOTE: Policy appears mostly static (very low reward).")
            else:
                print("NOTE: Policy shows activity (non-trivial rewards).")

            # Validate output
            if os.path.isfile(play_args.output):
                fsize = os.path.getsize(play_args.output)
                print(f"Output file: {play_args.output} ({fsize / 1024:.1f} KB)")
            else:
                print(f"WARNING: Output file not found at {play_args.output}")

            # Print errors from failed strategies
            if errors:
                print("\nFailed strategies:")
                for s, e in errors.items():
                    print(f"  Strategy {s}: {e}")

            return

        except Exception as e:
            tb = traceback.format_exc()
            errors[strat] = str(e)
            print(f"\nStrategy {strat} FAILED: {e}")
            print(tb)
            # Try to clean up env
            try:
                if 'env' in dir():
                    del env
            except Exception:
                pass
            continue

    print(f"\nAll strategies failed:")
    for s, e in errors.items():
        print(f"  Strategy {s}: {e}")
    sys.exit(1)


if __name__ == "__main__":
    main()
