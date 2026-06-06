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

T1_PKL_TO_MOTION = {
    "booster_t1_left-up": "lefthand",
    "booster_t1_left-medium": "leftjump",
    "booster_t1_left-down": "leftstep",
    "booster_t1_right-up": "righthand",
    "booster_t1_right-medium": "rightjump",
    "booster_t1_right-down": "rightstep",
}

# Lista canônica de joints T1 (ordem do MJCF T1_serial.xml, 23 DoF)
T1_JOINT_NAMES = [
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


def apply_z_offset(
    root_pos: np.ndarray,
    strategy: str,
    z_target_min: float,
    z_fixed_offset: float = 0.0,
) -> tuple[np.ndarray, float]:
    """Apply a per-motion Z offset to root_pos.

    Strategies:
      - ``none``: no change.
      - ``auto``: shift so that ``root_pos[:,2].min() == z_target_min``.
        Preserves relative Z variation (jumps/squats stay intact).
      - ``fixed``: add ``z_fixed_offset`` to all frames.

    Returns the corrected root_pos and the applied scalar offset.
    """
    if strategy == "none":
        return root_pos, 0.0
    if strategy == "fixed":
        root_pos = root_pos.copy()
        root_pos[:, 2] += z_fixed_offset
        return root_pos, float(z_fixed_offset)
    if strategy == "auto":
        z_min = float(root_pos[:, 2].min())
        offset = z_target_min - z_min
        root_pos = root_pos.copy()
        root_pos[:, 2] += offset
        return root_pos, offset
    raise ValueError(f"Unknown z_offset_strategy: {strategy}")


def build_target_dict(
    pkl_data: dict,
    reindex: list[int] | None,
    ref_data: dict | None,
    dof_names: list[str] | None = None,
    z_offset_strategy: str = "none",
    z_target_min: float = 0.55,
    z_fixed_offset: float = 0.0,
) -> dict:
    """Build a goalkeeper-format dict from a GMR PKL dict.

    If ``reindex`` is None, ``dof_pos`` from the PKL is used as-is (no joint
    reordering). ``dof_names`` is stored verbatim under the ``dof_names`` key.

    A Z offset can be applied to ``root_pos`` (see :func:`apply_z_offset`) to
    correct the trunk height when GMR retargeting outputs sunken roots.
    """
    fps = float(pkl_data["fps"])
    root_pos = pkl_data["root_pos"].astype(np.float32)
    root_rot = pkl_data["root_rot"].astype(np.float32)
    dof_pos = pkl_data["dof_pos"].astype(np.float32)
    N = root_pos.shape[0]

    root_pos, z_offset_applied = apply_z_offset(
        root_pos, z_offset_strategy, z_target_min, z_fixed_offset
    )

    # Core fields
    if reindex is None:
        joint_pos = dof_pos
    else:
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

    if dof_names is not None:
        result["dof_names"] = list(dof_names)

    return result


def convert_one(
    pkl_path: str,
    out_path: str,
    reindex: list[int] | None,
    ref_data: dict | None,
    dof_names: list[str] | None = None,
    z_offset_strategy: str = "none",
    z_target_min: float = 0.55,
    z_fixed_offset: float = 0.0,
) -> float:
    """Convert a single GMR PKL to goalkeeper .pt. Returns applied Z offset."""
    with open(pkl_path, "rb") as f:
        pkl_data = pickle.load(f)
    z_raw_min = float(pkl_data["root_pos"][:, 2].min())
    target = build_target_dict(
        pkl_data, reindex, ref_data, dof_names=dof_names,
        z_offset_strategy=z_offset_strategy,
        z_target_min=z_target_min,
        z_fixed_offset=z_fixed_offset,
    )
    torch.save(target, out_path)
    z_new_min = float(target["base_position"][:, 2].min().item())
    return z_new_min - z_raw_min


def validate_one(pt_path: str, ref_path: str | None, expected_dim: int = 21) -> dict:
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
        if jp.shape[1] != expected_dim:
            info["issues"].append(f"joint_position dim={jp.shape[1]}, expected {expected_dim}")
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
        "--robot",
        choices=["g1", "t1"],
        default="g1",
        help="Target robot family (g1: 21 DoF reindexed, t1: 23 DoF passthrough)",
    )
    parser.add_argument(
        "--input_dir",
        default="ViMoS/retarget/GMR/output/pkl",
        help="Directory with <prefix>_*.pkl files",
    )
    parser.add_argument(
        "--output_dir",
        default=None,
        help="Output directory for .pt files (default: data/goalkeeper_ours for g1, "
             "data/goalkeeper_ours_t1 for t1)",
    )
    parser.add_argument(
        "--ref_pt",
        default="legged_gym/resources/datasets/goalkeeper/leftstep.pt",
        help="Reference .pt for validation (g1 only; ignored for t1)",
    )
    parser.add_argument(
        "--joint_id_txt",
        default="legged_gym/resources/datasets/goalkeeper/joint_id.txt",
        help="Path to joint_id.txt (g1 only; ignored for t1)",
    )
    parser.add_argument(
        "--mjcf_xml",
        default=None,
        help="Path to MJCF XML (default: g1_mocap_29dof.xml for g1, "
             "T1_serial.xml for t1)",
    )
    parser.add_argument(
        "--z_offset_strategy",
        choices=["auto", "fixed", "none"],
        default=None,
        help="How to correct root Z (trunk height). 'auto' shifts each motion "
             "so its minimum Z equals --z_target_min (preserves jumps/squats). "
             "'fixed' adds --z_fixed_offset. 'none' is passthrough. "
             "Default: 'auto' for t1, 'none' for g1.",
    )
    parser.add_argument(
        "--z_target_min",
        type=float,
        default=0.55,
        help="Target minimum trunk Z (m) for --z_offset_strategy=auto (default 0.55).",
    )
    parser.add_argument(
        "--z_fixed_offset",
        type=float,
        default=0.0,
        help="Constant offset (m) added to root Z for --z_offset_strategy=fixed.",
    )
    args = parser.parse_args()

    is_t1 = args.robot == "t1"
    if args.output_dir is None:
        args.output_dir = "data/goalkeeper_ours_t1" if is_t1 else "data/goalkeeper_ours"
    if args.mjcf_xml is None:
        args.mjcf_xml = (
            "ViMoS/retarget/GMR/assets/booster_t1/T1_serial.xml"
            if is_t1
            else "ViMoS/retarget/GMR/assets/unitree_g1/g1_mocap_29dof.xml"
        )
    if args.z_offset_strategy is None:
        args.z_offset_strategy = "auto" if is_t1 else "none"

    os.makedirs(args.output_dir, exist_ok=True)

    # ── Step 1: Build reindex map (g1) or canonical joint list (t1) ──────────
    mjcf_joints = parse_mjcf_joint_order(args.mjcf_xml)
    print(f"MJCF joints ({len(mjcf_joints)}):")
    for i, j in enumerate(mjcf_joints):
        print(f"  {i:2d}: {j}")

    if is_t1:
        if mjcf_joints != T1_JOINT_NAMES:
            raise ValueError(
                f"MJCF joint order does not match canonical T1 list.\n"
                f"  MJCF: {mjcf_joints}\n"
                f"  T1:   {T1_JOINT_NAMES}"
            )
        target_joints = T1_JOINT_NAMES
        reindex = None
        pkl_map = T1_PKL_TO_MOTION
        expected_dim = 23
        ref_data = None  # ref is G1, not applicable
        print(f"\nT1 canonical joints ({len(target_joints)}): using dof_pos as-is")
        # Write joint_id.txt next to outputs
        joint_id_out = os.path.join(args.output_dir, "joint_id.txt")
        with open(joint_id_out, "w") as f:
            for i, name in enumerate(target_joints):
                f.write(f"{i} {name}\n")
        print(f"Wrote joint_id.txt → {joint_id_out}")
    else:
        target_joints = load_joint_id_txt(args.joint_id_txt)
        print(f"\nTarget joints ({len(target_joints)}):")
        for i, j in enumerate(target_joints):
            print(f"  {i:2d}: {j}")
        reindex = compute_reindex_map(mjcf_joints, target_joints)
        print(f"\nReindex map (21 ints): {reindex}")
        print("Mapping:")
        for i, (name, src) in enumerate(zip(target_joints, reindex)):
            print(f"  target[{i}] = {name} ← mjcf[{src}] = {mjcf_joints[src]}")
        pkl_map = PKL_TO_MOTION
        expected_dim = 21
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
    dof_names_arg = target_joints if is_t1 else None
    print(
        f"Z offset strategy: {args.z_offset_strategy}"
        + (f" (target_min={args.z_target_min:.3f}m)" if args.z_offset_strategy == "auto" else "")
        + (f" (fixed={args.z_fixed_offset:+.3f}m)" if args.z_offset_strategy == "fixed" else "")
    )
    for pkl_stem, motion_name in pkl_map.items():
        pkl_path = os.path.join(args.input_dir, f"{pkl_stem}.pkl")
        out_path = os.path.join(args.output_dir, f"{motion_name}.pt")

        if not os.path.exists(pkl_path):
            print(f"WARNING: {pkl_path} not found — skipping")
            continue

        offset = convert_one(
            pkl_path, out_path, reindex, ref_data, dof_names=dof_names_arg,
            z_offset_strategy=args.z_offset_strategy,
            z_target_min=args.z_target_min,
            z_fixed_offset=args.z_fixed_offset,
        )
        converted.append((motion_name, out_path))
        print(f"  {pkl_stem}.pkl → {motion_name}.pt   (Z offset applied: {offset:+.3f}m)")

    # ── Step 4: Validate ─────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("VALIDATION")
    print("=" * 60)

    header = f"{'Motion':<14} {'N':>5} {'jp shape':>12} {'jv shape':>12} {'dof_pos range':>22} {'dof_vel range':>22} {'NaN':>5} {'OK':>4}"
    print(header)
    print("-" * len(header))

    all_ok = True
    for motion_name, pt_path in converted:
        info = validate_one(pt_path, args.ref_pt if not is_t1 else None, expected_dim=expected_dim)
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
    if converted and not is_t1:
        print("\n--- Key comparison (ref vs ours) ---")
        info = validate_one(converted[0][1], args.ref_pt, expected_dim=expected_dim)
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
