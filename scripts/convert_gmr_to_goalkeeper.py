#!/usr/bin/env python3
"""Convert GMR retargeted PKL files to goalkeeper .pt dataset format."""

import argparse
import os
import pickle
import sys
import xml.etree.ElementTree as ET

import numpy as np
import torch

# ── Compat: PKLs saved with numpy 2.x have numpy._core references ───────────
if not hasattr(np, "_core"):
    import numpy.core as _np_core
    sys.modules["numpy._core"] = _np_core
    # Also alias sub-modules that may be referenced
    for sub in ("multiarray", "numeric", "_multiarray_umath", "umath"):
        mod = getattr(_np_core, sub, None)
        if mod is not None:
            sys.modules[f"numpy._core.{sub}"] = mod

# ── Mapeamento PKL → nome final ─────────────────────────────────────────────
PKL_TO_MOTION = {
    "unitree_g1_left-up": "lefthand",
    "unitree_g1_left-medium": "leftjump",
    "unitree_g1_left-down": "leftstep",
    "unitree_g1_right-up": "righthand",
    "unitree_g1_right-medium": "rightjump",
    "unitree_g1_right-down": "rightstep",
}


def load_joint_id_txt(path: str) -> list[str]:
    """Return ordered list of 21 target joint names from joint_id.txt."""
    names = []
    with open(path) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) == 2:
                names.append(parts[1])
    return names


def parse_mjcf_joint_order(xml_path: str) -> list[str]:
    """Return ordered list of joint names from the MJCF XML."""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    return [j.get("name") for j in root.iter("joint") if j.get("name")]


def compute_reindex_map(
    mjcf_joints: list[str], target_joints: list[str]
) -> list[int]:
    """Build index list: for each target joint, its column in the MJCF dof_pos.

    Raises ValueError if any target joint is missing from the MJCF.
    """
    mjcf_idx = {name: i for i, name in enumerate(mjcf_joints)}
    missing = [n for n in target_joints if n not in mjcf_idx]
    if missing:
        raise ValueError(f"Target joints NOT found in MJCF: {missing}")
    return [mjcf_idx[n] for n in target_joints]


def compute_joint_velocity(
    joint_pos: np.ndarray, fps: float
) -> np.ndarray:
    """Finite-difference velocity; last frame replicates penultimate."""
    vel = np.zeros_like(joint_pos)
    vel[:-1] = (joint_pos[1:] - joint_pos[:-1]) * fps
    vel[-1] = vel[-2] if len(vel) > 1 else 0.0
    return vel


def compute_base_velocity(pos: np.ndarray, fps: float) -> np.ndarray:
    """Finite-difference linear velocity for base position."""
    vel = np.zeros_like(pos)
    vel[:-1] = (pos[1:] - pos[:-1]) * fps
    vel[-1] = vel[-2] if len(vel) > 1 else 0.0
    return vel


def euler_from_quaternion_np(q: np.ndarray) -> np.ndarray:
    """Convert (N,4) xyzw quaternion to (N,3) roll-pitch-yaw."""
    x, y, z, w = q[:, 0], q[:, 1], q[:, 2], q[:, 3]
    t0 = 2.0 * (w * x + y * z)
    t1 = 1.0 - 2.0 * (x * x + y * y)
    roll = np.arctan2(t0, t1)
    t2 = np.clip(2.0 * (w * y - z * x), -1.0, 1.0)
    pitch = np.arcsin(t2)
    t3 = 2.0 * (w * z + x * y)
    t4 = 1.0 - 2.0 * (y * y + z * z)
    yaw = np.arctan2(t3, t4)
    return np.stack([roll, pitch, yaw], axis=-1)


def compute_base_angular_velocity(
    quat: np.ndarray, fps: float
) -> np.ndarray:
    """Finite-diff angular velocity from quaternion → euler → diff."""
    rpy = euler_from_quaternion_np(quat)
    vel = np.zeros_like(rpy)
    vel[:-1] = (rpy[1:] - rpy[:-1]) * fps
    vel[-1] = vel[-2] if len(vel) > 1 else 0.0
    return vel


def build_target_dict(
    pkl_data: dict,
    reindex: list[int],
    ref_data: dict | None,
) -> dict:
    """Build a goalkeeper-format dict from a GMR PKL dict."""
    fps = float(pkl_data["fps"])
    root_pos = pkl_data["root_pos"].astype(np.float32)
    root_rot = pkl_data["root_rot"].astype(np.float32)
    dof_pos = pkl_data["dof_pos"].astype(np.float32)
    N = root_pos.shape[0]

    # Core fields
    joint_pos = dof_pos[:, reindex]  # (N, 21)
    joint_vel = compute_joint_velocity(joint_pos, fps)
    base_vel = compute_base_velocity(root_pos, fps)
    base_ang_vel = compute_base_angular_velocity(root_rot, fps)

    result = {
        "base_position": torch.tensor(root_pos, dtype=torch.float32),
        "base_pose": torch.tensor(root_rot, dtype=torch.float32),
        "base_velocity": torch.tensor(base_vel, dtype=torch.float32),
        "base_angular_velocity": torch.tensor(base_ang_vel, dtype=torch.float32),
        "joint_position": torch.tensor(joint_pos, dtype=torch.float32),
        "joint_velocity": torch.tensor(joint_vel, dtype=torch.float32),
    }

    # Link / keyframe fields — match reference shape (K links)
    K = 17  # default from reference
    if ref_data is not None:
        for key in ref_data:
            if key not in result:
                ref_tensor = ref_data[key]
                shape = list(ref_tensor.shape)
                shape[0] = N  # adapt frame count
                result[key] = torch.zeros(shape, dtype=torch.float32)
    else:
        # Fallback: create standard link fields with zeros
        result["link_position"] = torch.zeros(N, K, 3, dtype=torch.float32)
        result["link_orientation"] = torch.zeros(N, K, 4, dtype=torch.float32)
        result["link_velocity"] = torch.zeros(N, K, 3, dtype=torch.float32)
        result["link_angular_velocity"] = torch.zeros(N, K, 3, dtype=torch.float32)

    # Also add typo-spelled keys used by MotionLib code in g1_utils.py
    if "link_orientation" in result and "link_oritentation" not in result:
        result["link_oritentation"] = result["link_orientation"]
    if "link_velocity" in result and "lin_velocity" not in result:
        result["lin_velocity"] = result["link_velocity"]

    return result


def convert_one(
    pkl_path: str,
    out_path: str,
    reindex: list[int],
    ref_data: dict | None,
) -> None:
    """Convert a single GMR PKL to goalkeeper .pt."""
    with open(pkl_path, "rb") as f:
        pkl_data = pickle.load(f)
    target = build_target_dict(pkl_data, reindex, ref_data)
    torch.save(target, out_path)


def validate_one(pt_path: str, ref_path: str | None) -> dict:
    """Validate a generated .pt and return summary info."""
    data = torch.load(pt_path, map_location="cpu")

    info = {"path": pt_path, "ok": True, "issues": []}

    # Check NaN
    for k, v in data.items():
        if isinstance(v, torch.Tensor) and torch.isnan(v).any():
            info["issues"].append(f"NaN in {k}")
            info["ok"] = False

    # Check joint shapes
    jp = data.get("joint_position")
    jv = data.get("joint_velocity")
    if jp is None:
        info["issues"].append("missing joint_position")
        info["ok"] = False
    else:
        info["N"] = jp.shape[0]
        info["joint_dim"] = jp.shape[1]
        if jp.shape[1] != 21:
            info["issues"].append(f"joint_position dim={jp.shape[1]}, expected 21")
            info["ok"] = False
        info["dof_pos_range"] = (float(jp.min()), float(jp.max()))

    if jv is not None:
        info["dof_vel_range"] = (float(jv.min()), float(jv.max()))
        if jp is not None and jv.shape != jp.shape:
            info["issues"].append(
                f"joint_velocity shape {jv.shape} != joint_position {jp.shape}"
            )
            info["ok"] = False

    # Shape consistency (all temporal dims = N)
    if jp is not None:
        N = jp.shape[0]
        for k, v in data.items():
            if isinstance(v, torch.Tensor) and v.shape[0] != N:
                info["issues"].append(f"{k} has {v.shape[0]} frames, expected {N}")
                info["ok"] = False

    # Compare keys with reference
    if ref_path and os.path.exists(ref_path):
        ref = torch.load(ref_path, map_location="cpu")
        ref_keys = set(ref.keys())
        our_keys = set(data.keys())
        info["ref_keys"] = sorted(ref_keys)
        info["our_keys"] = sorted(our_keys)
        missing = ref_keys - our_keys
        extra = our_keys - ref_keys
        if missing:
            info["issues"].append(f"missing keys vs ref: {missing}")
        if extra:
            info["extra_keys"] = sorted(extra)
        # dtype comparison
        info["dtype_match"] = {}
        for k in sorted(ref_keys & our_keys):
            if isinstance(ref[k], torch.Tensor) and isinstance(data[k], torch.Tensor):
                info["dtype_match"][k] = (
                    str(ref[k].dtype),
                    str(data[k].dtype),
                    ref[k].dtype == data[k].dtype,
                )

    if not info["issues"]:
        info["issues"] = ["NONE"]

    return info


def main():
    parser = argparse.ArgumentParser(description="Convert GMR PKLs to goalkeeper .pt")
    parser.add_argument(
        "--input_dir",
        default="ViMoS/retarget/GMR/output/pkl",
        help="Directory with unitree_g1_*.pkl files",
    )
    parser.add_argument(
        "--output_dir",
        default="data/goalkeeper_ours",
        help="Output directory for .pt files",
    )
    parser.add_argument(
        "--ref_pt",
        default="legged_gym/resources/datasets/goalkeeper/leftstep.pt",
        help="Reference .pt for validation",
    )
    parser.add_argument(
        "--joint_id_txt",
        default="legged_gym/resources/datasets/goalkeeper/joint_id.txt",
        help="Path to joint_id.txt",
    )
    parser.add_argument(
        "--mjcf_xml",
        default="ViMoS/retarget/GMR/assets/unitree_g1/g1_mocap_29dof.xml",
        help="Path to G1 MJCF XML",
    )
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    # ── Step 1: Build reindex map ────────────────────────────────────────────
    target_joints = load_joint_id_txt(args.joint_id_txt)
    mjcf_joints = parse_mjcf_joint_order(args.mjcf_xml)

    print(f"MJCF joints ({len(mjcf_joints)}):")
    for i, j in enumerate(mjcf_joints):
        print(f"  {i:2d}: {j}")

    print(f"\nTarget joints ({len(target_joints)}):")
    for i, j in enumerate(target_joints):
        print(f"  {i:2d}: {j}")

    reindex = compute_reindex_map(mjcf_joints, target_joints)
    print(f"\nReindex map (21 ints): {reindex}")
    print("Mapping:")
    for i, (name, src) in enumerate(zip(target_joints, reindex)):
        print(f"  target[{i}] = {name} ← mjcf[{src}] = {mjcf_joints[src]}")

    # ── Step 2: Load reference ───────────────────────────────────────────────
    ref_data = None
    if args.ref_pt and os.path.exists(args.ref_pt):
        ref_data = torch.load(args.ref_pt, map_location="cpu")
        print(f"\nReference .pt loaded: {args.ref_pt}")
        for k, v in ref_data.items():
            if isinstance(v, torch.Tensor):
                print(f"  {k}: {v.shape} {v.dtype}")

    # ── Step 3: Convert each PKL ─────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("CONVERTING")
    print("=" * 60)

    converted = []
    for pkl_stem, motion_name in PKL_TO_MOTION.items():
        pkl_path = os.path.join(args.input_dir, f"{pkl_stem}.pkl")
        out_path = os.path.join(args.output_dir, f"{motion_name}.pt")

        if not os.path.exists(pkl_path):
            print(f"WARNING: {pkl_path} not found — skipping")
            continue

        convert_one(pkl_path, out_path, reindex, ref_data)
        converted.append((motion_name, out_path))
        print(f"  {pkl_stem}.pkl → {motion_name}.pt")

    # ── Step 4: Validate ─────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("VALIDATION")
    print("=" * 60)

    header = f"{'Motion':<14} {'N':>5} {'jp shape':>12} {'jv shape':>12} {'dof_pos range':>22} {'dof_vel range':>22} {'NaN':>5} {'OK':>4}"
    print(header)
    print("-" * len(header))

    all_ok = True
    for motion_name, pt_path in converted:
        info = validate_one(pt_path, args.ref_pt)
        N = info.get("N", "?")
        jd = info.get("joint_dim", "?")
        dpr = info.get("dof_pos_range", ("?", "?"))
        dvr = info.get("dof_vel_range", ("?", "?"))
        has_nan = "NO" if info["issues"] == ["NONE"] or not any("NaN" in i for i in info["issues"]) else "YES"
        ok = "OK" if info["ok"] else "FAIL"
        if not info["ok"]:
            all_ok = False

        print(
            f"{motion_name:<14} {N:>5} {f'(N,{jd})':>12} {f'(N,{jd})':>12} "
            f"{f'[{dpr[0]:.3f}, {dpr[1]:.3f}]':>22} "
            f"{f'[{dvr[0]:.3f}, {dvr[1]:.3f}]':>22} "
            f"{has_nan:>5} {ok:>4}"
        )

        if info["issues"] != ["NONE"]:
            for issue in info["issues"]:
                print(f"  !! {issue}")

    # Key comparison with reference
    if converted:
        print("\n--- Key comparison (ref vs ours) ---")
        info = validate_one(converted[0][1], args.ref_pt)
        ref_keys = info.get("ref_keys", [])
        our_keys = info.get("our_keys", [])
        extra = info.get("extra_keys", [])
        print(f"  Ref keys:  {ref_keys}")
        print(f"  Our keys:  {our_keys}")
        if extra:
            print(f"  Extra (compat aliases): {extra}")
        print("\n--- Dtype comparison ---")
        for k, (rd, od, match) in info.get("dtype_match", {}).items():
            status = "OK" if match else "MISMATCH"
            print(f"  {k:<28} ref={rd:<15} ours={od:<15} {status}")

    print(f"\nAll OK: {all_ok}")
    if all_ok:
        print(f"Output directory: {args.output_dir}")
        for _, pt_path in converted:
            print(f"  {pt_path}")


if __name__ == "__main__":
    main()
