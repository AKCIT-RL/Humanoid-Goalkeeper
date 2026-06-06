#!/usr/bin/env python3
"""Dry-run validation: load goalkeeper .pt files via MotionLib and test get_expert_obs."""
import argparse
import os
import sys
import traceback

# IsaacGym MUST be imported before torch (requirement of IsaacGym Preview 4)
try:
    import isaacgym  # noqa: F401
except ImportError:
    pass

import torch

# Ensure legged_gym is importable (works inside Docker at /workspace)
sys.path.insert(0, "/workspace/legged_gym")

# Imported lazily inside run_dry_run() for --robot=g1 only; T1 mode does not
# need MotionLib (which is G1-specific: 29 DoF, fixed padding, etc.).

# 29 DOF names in URDF order (from g1_29.urdf revolute joints)
DOF_NAMES = [
    "left_hip_pitch_joint", "left_hip_roll_joint", "left_hip_yaw_joint",
    "left_knee_joint", "left_ankle_pitch_joint", "left_ankle_roll_joint",
    "right_hip_pitch_joint", "right_hip_roll_joint", "right_hip_yaw_joint",
    "right_knee_joint", "right_ankle_pitch_joint", "right_ankle_roll_joint",
    "waist_yaw_joint", "waist_roll_joint", "waist_pitch_joint",
    "left_shoulder_pitch_joint", "left_shoulder_roll_joint", "left_shoulder_yaw_joint",
    "left_elbow_joint", "left_wrist_roll_joint", "left_wrist_pitch_joint",
    "left_wrist_yaw_joint",
    "right_shoulder_pitch_joint", "right_shoulder_roll_joint", "right_shoulder_yaw_joint",
    "right_elbow_joint", "right_wrist_roll_joint", "right_wrist_pitch_joint",
    "right_wrist_yaw_joint",
]

# T1 canonical joint order (23 DoF, matches scripts/convert_gmr_to_goalkeeper.py
# and ViMoS/retarget/GMR/assets/booster_t1/T1_serial.xml).
T1_DOF_NAMES = [
    "AAHead_yaw", "Head_pitch",
    "Left_Shoulder_Pitch", "Left_Shoulder_Roll",
    "Left_Elbow_Pitch", "Left_Elbow_Yaw",
    "Right_Shoulder_Pitch", "Right_Shoulder_Roll",
    "Right_Elbow_Pitch", "Right_Elbow_Yaw",
    "Waist",
    "Left_Hip_Pitch", "Left_Hip_Roll", "Left_Hip_Yaw",
    "Left_Knee_Pitch", "Left_Ankle_Pitch", "Left_Ankle_Roll",
    "Right_Hip_Pitch", "Right_Hip_Roll", "Right_Hip_Yaw",
    "Right_Knee_Pitch", "Right_Ankle_Pitch", "Right_Ankle_Roll",
]

# No "keyframe" links in g1_29.urdf, so this is empty
KEYFRAME_NAMES = []

FPS = 30
MIN_DT = 0.1
NUM_STEPS = 2
BATCH_SIZE = 8

REQUIRED_KEYS = [
    "base_position", "base_pose", "base_velocity", "base_angular_velocity",
    "joint_position", "joint_velocity",
    "link_position", "link_oritentation", "lin_velocity", "link_angular_velocity",
]

EXPECTED_SHAPES_G1 = {
    "base_position": ("N", 3),
    "base_pose": ("N", 4),
    "base_velocity": ("N", 3),
    "base_angular_velocity": ("N", 3),
    "joint_position": ("N", 21),
    "joint_velocity": ("N", 21),
    "link_position": ("N", 17, 3),
    "link_oritentation": ("N", 17, 4),
    "lin_velocity": ("N", 17, 3),
    "link_angular_velocity": ("N", 17, 3),
}

EXPECTED_SHAPES_T1 = {
    "base_position": ("N", 3),
    "base_pose": ("N", 4),
    "base_velocity": ("N", 3),
    "base_angular_velocity": ("N", 3),
    "joint_position": ("N", 23),
    "joint_velocity": ("N", 23),
}

# Keep backward-compatible name used elsewhere; set at runtime from --robot.
EXPECTED_SHAPES = EXPECTED_SHAPES_G1


def check_shapes(data, name):
    """Verify tensor shapes match expected schema. Returns list of issues."""
    issues = []
    n_frames = None
    for key, expected in EXPECTED_SHAPES.items():
        if key not in data:
            # link_oritentation and lin_velocity only needed if keyframes exist
            if key in ("link_oritentation", "lin_velocity") and len(KEYFRAME_NAMES) == 0:
                continue
            issues.append(f"  MISSING key '{key}'")
            continue
        t = data[key]
        if not isinstance(t, torch.Tensor):
            issues.append(f"  {key}: expected Tensor, got {type(t).__name__}")
            continue
        shape = tuple(t.shape)
        if n_frames is None:
            n_frames = shape[0]
        if shape[0] != n_frames:
            issues.append(f"  {key}: frame count {shape[0]} != {n_frames}")
        exp_tail = expected[1:]
        actual_tail = shape[1:]
        if actual_tail != exp_tail:
            issues.append(f"  {key}: shape tail {actual_tail} != expected {exp_tail}")
    return issues, n_frames


def run_dry_run(folder, mapping_path, robot="g1"):
    print(f"\n{'='*60}")
    print(f"DRY-RUN: {folder}  (robot={robot})")
    print(f"{'='*60}")

    # Select expected schema for this robot.
    global EXPECTED_SHAPES
    if robot == "t1":
        EXPECTED_SHAPES = EXPECTED_SHAPES_T1
    else:
        EXPECTED_SHAPES = EXPECTED_SHAPES_G1

    # Step 1: raw torch.load validation
    pt_files = sorted([f for f in os.listdir(folder) if f.endswith(".pt")])
    if not pt_files:
        print(f"ERROR: No .pt files in {folder}")
        return False

    results = {}
    all_ok = True

    print(f"\n--- Step 1: Raw schema validation ---")
    for fname in pt_files:
        path = os.path.join(folder, fname)
        motion_name = fname[:-3]
        try:
            data = torch.load(path, map_location="cpu")
        except Exception as e:
            results[motion_name] = {"status": "LOAD_FAIL", "error": str(e)}
            all_ok = False
            continue

        if not isinstance(data, dict):
            results[motion_name] = {"status": "WRONG_TYPE", "error": f"Expected dict, got {type(data).__name__}"}
            all_ok = False
            continue

        issues, n_frames = check_shapes(data, motion_name)
        # Extra checks: NaN, finite ranges
        for k, v in data.items():
            if isinstance(v, torch.Tensor):
                if torch.isnan(v).any():
                    issues.append(f"  NaN in '{k}'")
                if torch.isinf(v).any():
                    issues.append(f"  Inf in '{k}'")
        extra_keys = set(data.keys()) - set(EXPECTED_SHAPES.keys()) - {"link_orientation", "link_velocity", "base_velocity"}
        results[motion_name] = {
            "status": "OK" if not issues else "SHAPE_ISSUES",
            "n_frames": n_frames,
            "keys": sorted(data.keys()),
            "issues": issues,
            "extra_keys": sorted(extra_keys) if extra_keys else [],
        }
        if issues:
            all_ok = False

    # Print schema table
    print(f"\n{'Motion':<12} {'Frames':>6} {'Status':<14} {'Issues'}")
    print("-" * 60)
    for name, r in sorted(results.items()):
        n = r.get("n_frames", "?")
        status = r["status"]
        issues_str = "; ".join(r.get("issues", [r.get("error", "")])) or "-"
        print(f"{name:<12} {str(n):>6} {status:<14} {issues_str}")

    # For T1: MotionLib is G1-specific (29 DoF, padding); skip steps 2-3.
    if robot == "t1":
        # Cross-check that --mapping length matches T1 expectation (23 DoF).
        try:
            with open(mapping_path) as f:
                n_map = sum(1 for line in f if line.strip())
        except Exception as e:
            print(f"\n  Could not read mapping {mapping_path}: {e}")
            return False
        if n_map != 23:
            print(f"\n  ERROR: mapping has {n_map} entries, expected 23 for T1")
            all_ok = False
        else:
            print(f"\n  Mapping {mapping_path}: {n_map} entries (OK for T1)")
        print(f"\n  Steps 2/3 (MotionLib instantiation, get_expert_obs): SKIPPED — "
              f"MotionLib is G1-specific (29 DoF). T1 validation is schema-only.")
        print(f"\n{'='*60}")
        print(f"RESULT: {'ALL PASSED' if all_ok else 'SOME FAILURES'}")
        print(f"{'='*60}\n")
        return all_ok

    # G1 path: lazily import MotionLib.
    from legged_gym.envs.g1.g1_utils import MotionLib, load_imitation_dataset

    # Step 2: MotionLib instantiation via load_imitation_dataset
    print(f"\n--- Step 2: MotionLib instantiation ---")
    try:
        multidataset, mapping = load_imitation_dataset(folder, mapping_path)
        print(f"  load_imitation_dataset OK: {len(multidataset)} motions loaded")
        print(f"  Mapping has {len(mapping)} joints: {sorted(mapping.keys())[:5]}...")
    except Exception as e:
        print(f"  load_imitation_dataset FAILED: {e}")
        traceback.print_exc()
        return False

    motionlib_results = {}
    for key in sorted(multidataset.keys()):
        datasets = multidataset[key]
        try:
            ml = MotionLib(
                datasets, mapping, DOF_NAMES, KEYFRAME_NAMES,
                fps=FPS, min_dt=MIN_DT, device="cpu",
                amp_obs_type="dof", num_steps=NUM_STEPS,
            )
            motionlib_results[key] = {
                "status": "OK",
                "num_motion": ml.num_motion,
                "tot_len": ml.tot_len.item(),
                "dof_pos_shape": tuple(ml.motion_dof_pos.shape),
            }
        except Exception as e:
            motionlib_results[key] = {"status": "FAIL", "error": str(e)}
            traceback.print_exc()
            all_ok = False

    print(f"\n{'Motion':<12} {'Status':<8} {'num_motion':>10} {'tot_len':>8} {'dof_pos shape'}")
    print("-" * 65)
    for name, r in sorted(motionlib_results.items()):
        if r["status"] == "OK":
            print(f"{name:<12} {'OK':<8} {r['num_motion']:>10} {r['tot_len']:>8} {r['dof_pos_shape']}")
        else:
            print(f"{name:<12} {'FAIL':<8} {r['error']}")

    # Step 3: get_expert_obs test
    print(f"\n--- Step 3: get_expert_obs test ---")
    for key in sorted(multidataset.keys()):
        if motionlib_results[key]["status"] != "OK":
            print(f"  {key}: SKIPPED (MotionLib failed)")
            continue
        datasets = multidataset[key]
        ml = MotionLib(
            datasets, mapping, DOF_NAMES, KEYFRAME_NAMES,
            fps=FPS, min_dt=MIN_DT, device="cpu",
            amp_obs_type="dof", num_steps=NUM_STEPS,
        )
        try:
            obs = ml.get_expert_obs(BATCH_SIZE)
            print(f"  {key}: get_expert_obs OK -> shape {tuple(obs.shape)}, "
                  f"range [{obs.min().item():.4f}, {obs.max().item():.4f}]")
        except Exception as e:
            print(f"  {key}: get_expert_obs FAILED: {e}")
            traceback.print_exc()
            all_ok = False

    print(f"\n{'='*60}")
    print(f"RESULT: {'ALL PASSED' if all_ok else 'SOME FAILURES'}")
    print(f"{'='*60}\n")
    return all_ok


def main():
    parser = argparse.ArgumentParser(
        description="Dry-run MotionLib validation. For --robot=g1 instantiates "
                    "MotionLib + tests get_expert_obs; for --robot=t1 runs "
                    "schema-only validation (MotionLib is G1-specific)."
    )
    parser.add_argument("--folder", required=True, help="Path to folder with .pt files")
    parser.add_argument("--mapping", default=None, help="Path to joint_id.txt (default: <folder>/joint_id.txt or standard goalkeeper path)")
    parser.add_argument(
        "--robot",
        choices=["g1", "t1"],
        default="g1",
        help="Robot family. 'g1' instantiates MotionLib (29 DoF, fixed padding); "
             "'t1' does schema-only validation (23 DoF, no MotionLib).",
    )
    args = parser.parse_args()

    folder = args.folder
    if not os.path.isabs(folder):
        # Try relative to /workspace (Docker) or cwd
        for base in ["/workspace", os.getcwd()]:
            candidate = os.path.join(base, folder)
            if os.path.isdir(candidate):
                folder = candidate
                break

    if not os.path.isdir(folder):
        print(f"ERROR: folder not found: {folder}")
        sys.exit(1)

    # Resolve mapping path
    mapping_path = args.mapping
    if mapping_path is None:
        # Try in the folder itself
        candidate = os.path.join(folder, "joint_id.txt")
        if os.path.isfile(candidate):
            mapping_path = candidate
        else:
            # Fall back to standard goalkeeper path
            mapping_path = "/workspace/legged_gym/resources/datasets/goalkeeper/joint_id.txt"

    if not os.path.isfile(mapping_path):
        print(f"ERROR: mapping file not found: {mapping_path}")
        sys.exit(1)

    print(f"Folder:  {folder}")
    print(f"Mapping: {mapping_path}")
    print(f"Robot:   {args.robot}")

    ok = run_dry_run(folder, mapping_path, robot=args.robot)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
