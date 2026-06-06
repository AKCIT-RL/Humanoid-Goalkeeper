"""Bateria de validação dos artefatos de retargeting T1.

Cobre Categorias 1, 2, 3, 7 e 8 do prompt do Validador Agressivo.
Categorias 4–6 (replay em PyBullet / IsaacGym, cross-check de vídeos)
são feitas pelo `replay_all_t1.sh` por dependerem de Docker.

Executar:
    tests/venv/bin/pytest tests/test_t1_motions.py -v
"""
from __future__ import annotations

import math
import os
import pickle
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pytest
import torch

# ── Constantes do projeto ───────────────────────────────────────────────────
REPO = Path(__file__).resolve().parent.parent
T1_DIR = REPO / "data" / "goalkeeper_ours_t1"
G1_DIR = REPO / "data" / "goalkeeper_ours"
PKL_DIR = REPO / "ViMoS" / "retarget" / "GMR" / "output" / "pkl"
GMR_VIDEOS = REPO / "ViMoS" / "retarget" / "GMR" / "videos"
T1_URDF = REPO / "ViMoS" / "retarget" / "GMR" / "assets" / "booster_t1" / "T1_serial.urdf"
T1_MJCF = REPO / "ViMoS" / "retarget" / "GMR" / "assets" / "booster_t1" / "T1_serial.xml"

MOTIONS = ["lefthand", "leftjump", "leftstep", "righthand", "rightjump", "rightstep"]

PKL_MAP = {
    "lefthand": "booster_t1_left-up",
    "leftjump": "booster_t1_left-medium",
    "leftstep": "booster_t1_left-down",
    "righthand": "booster_t1_right-up",
    "rightjump": "booster_t1_right-medium",
    "rightstep": "booster_t1_right-down",
}

T1_JOINT_NAMES_CANONICAL = [
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

REQUIRED_KEYS = {
    "base_position", "base_pose", "base_velocity",
    "base_angular_velocity", "joint_position", "joint_velocity",
}

FPS_DEFAULT = 30


# ── Helpers ─────────────────────────────────────────────────────────────────
def _load_pt(name: str) -> dict:
    path = T1_DIR / f"{name}.pt"
    return torch.load(path, map_location="cpu", weights_only=False)


def _load_pkl(stem: str) -> dict:
    """Compat com PKLs salvos em numpy 2.x (referências a numpy._core)."""
    import sys
    if not hasattr(np, "_core"):
        import numpy.core as _np_core
        sys.modules["numpy._core"] = _np_core
        for sub in ("multiarray", "numeric", "_multiarray_umath", "umath"):
            mod = getattr(_np_core, sub, None)
            if mod is not None:
                sys.modules[f"numpy._core.{sub}"] = mod
    with open(PKL_DIR / f"{stem}.pkl", "rb") as f:
        return pickle.load(f)


def _parse_mjcf_joint_ranges(xml_path: Path) -> dict[str, tuple[float, float]]:
    tree = ET.parse(xml_path)
    root = tree.getroot()
    out = {}
    for j in root.iter("joint"):
        name = j.get("name")
        rng = j.get("range")
        if name and rng:
            lo, hi = (float(x) for x in rng.split())
            out[name] = (lo, hi)
    return out


def _parse_mjcf_joint_order(xml_path: Path) -> list[str]:
    tree = ET.parse(xml_path)
    root = tree.getroot()
    return [j.get("name") for j in root.iter("joint") if j.get("name")]


def _parse_urdf_revolute_order(urdf_path: Path) -> list[str]:
    tree = ET.parse(urdf_path)
    root = tree.getroot()
    out = []
    for j in root.findall("joint"):
        jtype = j.attrib.get("type")
        if jtype in ("revolute", "continuous"):
            mimic = j.find("mimic")
            if mimic is not None:
                continue
            out.append(j.attrib["name"])
    return out


def _ffprobe(path: Path) -> dict:
    """Retorna metadados via ffprobe; ffprobe pode estar em docker."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries",
        "stream=nb_frames,duration,width,height,r_frame_rate:format=duration",
        "-of", "default=noprint_wrappers=1", str(path),
    ]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, timeout=30).decode()
    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        raise RuntimeError(f"ffprobe failed: {e}") from e
    info: dict[str, str] = {}
    for line in out.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            info[k.strip()] = v.strip()
    return info


# ── Fixtures ────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module", params=MOTIONS, ids=MOTIONS)
def motion(request):
    name = request.param
    data = _load_pt(name)
    return name, data


@pytest.fixture(scope="module")
def mjcf_ranges():
    return _parse_mjcf_joint_ranges(T1_MJCF)


@pytest.fixture(scope="module")
def mjcf_order():
    return _parse_mjcf_joint_order(T1_MJCF)


@pytest.fixture(scope="module")
def urdf_order():
    return _parse_urdf_revolute_order(T1_URDF)


@pytest.fixture(scope="module")
def joint_id_txt():
    lines = (T1_DIR / "joint_id.txt").read_text().strip().splitlines()
    parsed = []
    for ln in lines:
        idx_str, name = ln.split()
        parsed.append((int(idx_str), name))
    return parsed


# ═════════════════════════════════════════════════════════════════════════════
# 1) Schema e integridade dos .pt
# ═════════════════════════════════════════════════════════════════════════════
class TestSchema:

    def test_loadable(self, motion):
        name, data = motion
        assert isinstance(data, dict), f"{name}: deveria ser dict, é {type(data)}"

    def test_required_keys_present(self, motion):
        name, data = motion
        missing = REQUIRED_KEYS - set(data.keys())
        assert not missing, f"{name}: faltando chaves {missing}"

    def test_dof_names_present(self, motion):
        name, data = motion
        assert "dof_names" in data, f"{name}: faltando 'dof_names' (necessário para mapeamento T1)"

    def test_joint_position_shape(self, motion):
        name, data = motion
        jp = data["joint_position"]
        assert jp.ndim == 2 and jp.shape[1] == 23, (
            f"{name}: joint_position shape {tuple(jp.shape)} != (N, 23)"
        )

    def test_base_pose_shape(self, motion):
        name, data = motion
        bp = data["base_pose"]
        assert bp.ndim == 2 and bp.shape[1] == 4, (
            f"{name}: base_pose shape {tuple(bp.shape)} != (N, 4)"
        )

    def test_base_position_shape(self, motion):
        name, data = motion
        bp = data["base_position"]
        assert bp.ndim == 2 and bp.shape[1] == 3, (
            f"{name}: base_position shape {tuple(bp.shape)} != (N, 3)"
        )

    def test_all_dtypes_float32(self, motion):
        name, data = motion
        bad = []
        for k, v in data.items():
            if isinstance(v, torch.Tensor) and v.dtype != torch.float32:
                bad.append((k, str(v.dtype)))
        assert not bad, f"{name}: tensores não-float32: {bad}"

    def test_frame_count_consistency(self, motion):
        name, data = motion
        N = data["joint_position"].shape[0]
        bad = {}
        for k, v in data.items():
            if isinstance(v, torch.Tensor) and v.shape[0] != N:
                bad[k] = v.shape[0]
        assert not bad, f"{name}: N esperado={N}, chaves divergentes={bad}"

    def test_no_nan_or_inf(self, motion):
        name, data = motion
        bad = []
        for k, v in data.items():
            if isinstance(v, torch.Tensor):
                if torch.isnan(v).any():
                    bad.append(f"{k}:NaN")
                if torch.isinf(v).any():
                    bad.append(f"{k}:Inf")
        assert not bad, f"{name}: NaN/Inf encontrados em {bad}"

    def test_base_pose_is_unit_quaternion(self, motion):
        name, data = motion
        bp = data["base_pose"]
        norms = torch.linalg.norm(bp, dim=1)
        max_err = float((norms - 1.0).abs().max())
        assert max_err < 1e-3, (
            f"{name}: quaternion não-unitário, max |norm-1| = {max_err:.6f}"
        )

    def test_dof_names_length_and_order(self, motion):
        name, data = motion
        dof = list(data["dof_names"])
        assert len(dof) == 23, f"{name}: dof_names tem {len(dof)}, esperado 23"
        assert dof == T1_JOINT_NAMES_CANONICAL, (
            f"{name}: dof_names difere da ordem canônica T1.\n"
            f"  obtido: {dof}\n  esperado: {T1_JOINT_NAMES_CANONICAL}"
        )


# ═════════════════════════════════════════════════════════════════════════════
# 2) Consistência físico-cinemática
# ═════════════════════════════════════════════════════════════════════════════
class TestKinematics:

    def test_joint_within_mjcf_ranges(self, motion, mjcf_ranges):
        name, data = motion
        jp = data["joint_position"].numpy()
        dof_names = list(data["dof_names"])
        violations = []
        for j_idx, j_name in enumerate(dof_names):
            lo, hi = mjcf_ranges[j_name]
            col = jp[:, j_idx]
            col_min, col_max = float(col.min()), float(col.max())
            # tolerância 1e-4 para numerical noise
            if col_min < lo - 1e-4 or col_max > hi + 1e-4:
                n_bad_lo = int((col < lo - 1e-4).sum())
                n_bad_hi = int((col > hi + 1e-4).sum())
                violations.append(
                    f"{j_name} (idx {j_idx}): obs=[{col_min:.4f}, {col_max:.4f}] "
                    f"range=[{lo}, {hi}] under={n_bad_lo} over={n_bad_hi}"
                )
        assert not violations, (
            f"{name}: violações de range MJCF:\n  " + "\n  ".join(violations)
        )

    def test_joint_velocity_finite_difference(self, motion):
        name, data = motion
        # tenta inferir fps do PKL fonte
        try:
            pkl = _load_pkl(PKL_MAP[name])
            fps = float(pkl["fps"])
        except Exception:
            fps = float(FPS_DEFAULT)
        jp = data["joint_position"].numpy()
        jv = data["joint_velocity"].numpy()
        if jp.shape[0] < 2:
            pytest.skip(f"{name}: motion muito curta para fd")
        expected = (jp[1:] - jp[:-1]) * fps
        diff = np.abs(jv[:-1] - expected)
        max_err = float(diff.max())
        assert max_err < 1e-3, (
            f"{name}: joint_velocity ≠ FD(joint_position)*{fps}; max_err={max_err:.6f}"
        )

    def test_base_velocity_finite_difference(self, motion):
        name, data = motion
        try:
            pkl = _load_pkl(PKL_MAP[name])
            fps = float(pkl["fps"])
        except Exception:
            fps = float(FPS_DEFAULT)
        pos = data["base_position"].numpy()
        vel = data["base_velocity"].numpy()
        if pos.shape[0] < 2:
            pytest.skip(f"{name}: motion muito curta")
        expected = (pos[1:] - pos[:-1]) * fps
        diff = np.abs(vel[:-1] - expected)
        max_err = float(diff.max())
        assert max_err < 1e-3, (
            f"{name}: base_velocity ≠ FD(base_position)*{fps}; max_err={max_err:.6f}"
        )

    def test_base_angular_velocity_loose(self, motion):
        """Loose check: angular velocity coerência por euler diff (atol 0.1)."""
        name, data = motion
        try:
            pkl = _load_pkl(PKL_MAP[name])
            fps = float(pkl["fps"])
        except Exception:
            fps = float(FPS_DEFAULT)
        q = data["base_pose"].numpy()  # xyzw
        # converte para euler
        x, y, z, w = q[:, 0], q[:, 1], q[:, 2], q[:, 3]
        t0 = 2.0 * (w * x + y * z)
        t1 = 1.0 - 2.0 * (x * x + y * y)
        roll = np.arctan2(t0, t1)
        t2 = np.clip(2.0 * (w * y - z * x), -1.0, 1.0)
        pitch = np.arcsin(t2)
        t3 = 2.0 * (w * z + x * y)
        t4 = 1.0 - 2.0 * (y * y + z * z)
        yaw = np.arctan2(t3, t4)
        rpy = np.stack([roll, pitch, yaw], axis=-1)
        if rpy.shape[0] < 2:
            pytest.skip(f"{name}: motion muito curta")
        expected = (rpy[1:] - rpy[:-1]) * fps
        av = data["base_angular_velocity"].numpy()
        diff = np.abs(av[:-1] - expected)
        # tolera wrap-around eventual
        max_err = float(diff.max())
        assert max_err < 0.1, (
            f"{name}: base_angular_velocity diverge de euler diff; max_err={max_err:.4f}"
        )

    def test_joint_velocity_smoothness(self, motion):
        name, data = motion
        jv = data["joint_velocity"].numpy()
        max_abs = float(np.abs(jv).max())
        assert max_abs < 50.0, (
            f"{name}: joint_velocity max abs = {max_abs:.2f} rad/s (>50 = suspeito)"
        )

    def test_base_height_sane(self, motion):
        """T1 ~1m altura; z médio deveria ser ~0.5–1.5m."""
        name, data = motion
        z = data["base_position"].numpy()[:, 2]
        z_mean = float(z.mean())
        assert 0.3 < z_mean < 1.5, (
            f"{name}: base_position[:,2] médio = {z_mean:.3f}m (fora de [0.3, 1.5])"
        )

    def test_z_offset_preserves_relative_height(self, motion):
        """Round 2 regression: o fix de bug #1 desloca Z mas não pode alterar a
        variação relativa (z.max - z.min). Compara contra o PKL bruto do GMR."""
        name, data = motion
        try:
            pkl = _load_pkl(PKL_MAP[name])
        except FileNotFoundError:
            pytest.skip(f"PKL bruto ausente para {name}")
        z_pt = data["base_position"].numpy()[:, 2]
        z_raw = np.asarray(pkl["root_pos"])[:, 2]
        assert z_pt.shape[0] == z_raw.shape[0], (
            f"{name}: N frames diferentes pt={z_pt.shape[0]} raw={z_raw.shape[0]}"
        )
        span_pt = float(z_pt.max() - z_pt.min())
        span_raw = float(z_raw.max() - z_raw.min())
        assert abs(span_pt - span_raw) < 1e-5, (
            f"{name}: span Z alterado pelo offset! raw={span_raw:.6f}, "
            f"pt={span_pt:.6f}, diff={abs(span_pt - span_raw):.3e}"
        )


# ═════════════════════════════════════════════════════════════════════════════
# 3) Mapeamento joints (regressão crítica)
# ═════════════════════════════════════════════════════════════════════════════
class TestJointMapping:

    def test_mjcf_order_matches_canonical(self, mjcf_order):
        assert mjcf_order == T1_JOINT_NAMES_CANONICAL, (
            f"MJCF order difere da lista canônica T1.\n"
            f"  MJCF: {mjcf_order}\n"
            f"  canon: {T1_JOINT_NAMES_CANONICAL}"
        )

    def test_urdf_order_matches_canonical(self, urdf_order):
        assert urdf_order == T1_JOINT_NAMES_CANONICAL, (
            f"URDF revolute order difere da lista canônica T1.\n"
            f"  URDF: {urdf_order}\n"
            f"  canon: {T1_JOINT_NAMES_CANONICAL}"
        )

    def test_joint_id_txt_matches_canonical(self, joint_id_txt):
        assert len(joint_id_txt) == 23, f"joint_id.txt tem {len(joint_id_txt)} linhas (esperado 23)"
        for i, (idx, name) in enumerate(joint_id_txt):
            assert idx == i, f"linha {i}: idx={idx} (esperado {i})"
            assert name == T1_JOINT_NAMES_CANONICAL[i], (
                f"linha {i}: name={name} (esperado {T1_JOINT_NAMES_CANONICAL[i]})"
            )

    def test_dof_names_matches_joint_id_txt(self, motion, joint_id_txt):
        name, data = motion
        txt_names = [n for _, n in joint_id_txt]
        assert list(data["dof_names"]) == txt_names, (
            f"{name}: dof_names difere de joint_id.txt"
        )


# ═════════════════════════════════════════════════════════════════════════════
# 7) Sanity de não-regressão para G1
# ═════════════════════════════════════════════════════════════════════════════
class TestG1Regression:

    def test_g1_pt_still_loadable(self):
        for f in MOTIONS:
            p = G1_DIR / f"{f}.pt"
            assert p.exists(), f"G1 motion ausente: {p}"
            d = torch.load(p, map_location="cpu", weights_only=False)
            assert d["joint_position"].shape[1] == 21, (
                f"G1 {f}: joint_position shape mudou! ({tuple(d['joint_position'].shape)})"
            )

    def test_convert_script_help(self):
        """Confirma que o CLI continua respondendo (com --robot novo)."""
        script = REPO / "scripts" / "convert_gmr_to_goalkeeper.py"
        out = subprocess.run(
            ["python3", str(script), "--help"],
            capture_output=True, text=True, timeout=30,
        )
        assert out.returncode == 0, f"--help falhou: {out.stderr}"
        assert "--robot" in out.stdout, "CLI sem flag --robot"
        assert "g1" in out.stdout and "t1" in out.stdout, "choices g1/t1 ausentes"


# ═════════════════════════════════════════════════════════════════════════════
# 8) Checks específicos do paper (motion priors)
# ═════════════════════════════════════════════════════════════════════════════
LEFT_ARM_IDX = [
    T1_JOINT_NAMES_CANONICAL.index(n) for n in [
        "Left_Shoulder_Pitch", "Left_Shoulder_Roll",
        "Left_Elbow_Pitch", "Left_Elbow_Yaw",
    ]
]
RIGHT_ARM_IDX = [
    T1_JOINT_NAMES_CANONICAL.index(n) for n in [
        "Right_Shoulder_Pitch", "Right_Shoulder_Roll",
        "Right_Elbow_Pitch", "Right_Elbow_Yaw",
    ]
]


class TestMotionSemantics:

    @pytest.mark.parametrize("name", ["lefthand", "leftjump", "leftstep"])
    def test_left_arm_movement(self, name):
        if name != "lefthand":
            pytest.skip(f"check arm-move só para lefthand (este: {name})")
        data = _load_pt(name)
        jp = data["joint_position"].numpy()
        spans = [float(jp[:, i].max() - jp[:, i].min()) for i in LEFT_ARM_IDX]
        max_span = max(spans)
        assert max_span > 0.3, (
            f"{name}: braço esquerdo praticamente parado; max span = {max_span:.3f} rad "
            f"(idx {LEFT_ARM_IDX}, spans {spans})"
        )

    @pytest.mark.parametrize("name", ["righthand"])
    def test_right_arm_movement(self, name):
        data = _load_pt(name)
        jp = data["joint_position"].numpy()
        spans = [float(jp[:, i].max() - jp[:, i].min()) for i in RIGHT_ARM_IDX]
        max_span = max(spans)
        assert max_span > 0.3, (
            f"{name}: braço direito praticamente parado; max span = {max_span:.3f} rad "
            f"(idx {RIGHT_ARM_IDX}, spans {spans})"
        )

    @pytest.mark.parametrize("name", ["leftjump", "rightjump"])
    def test_jump_z_motion(self, name):
        data = _load_pt(name)
        z = data["base_position"].numpy()[:, 2]
        span = float(z.max() - z.min())
        assert span > 0.05, (
            f"{name}: variação Z = {span:.3f}m (<0.05m), motion não parece um pulo"
        )

    @pytest.mark.parametrize("name", ["leftstep", "rightstep"])
    def test_step_y_motion(self, name):
        data = _load_pt(name)
        y = data["base_position"].numpy()[:, 1]
        span = float(y.max() - y.min())
        assert span > 0.05, (
            f"{name}: variação Y = {span:.3f}m (<0.05m), motion não parece um step lateral"
        )


# ═════════════════════════════════════════════════════════════════════════════
# 6) Cross-check vídeos GMR vs duração do .pt
# ═════════════════════════════════════════════════════════════════════════════
@pytest.mark.skipif(
    subprocess.call(
        ["which", "ffprobe"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    ) != 0,
    reason="ffprobe não instalado",
)
class TestGMRVideos:

    @pytest.mark.parametrize("motion_name", MOTIONS)
    def test_video_exists_and_metadata(self, motion_name):
        stem = PKL_MAP[motion_name]
        vid = GMR_VIDEOS / f"{stem}.mp4"
        assert vid.exists(), f"vídeo GMR ausente: {vid}"
        assert vid.stat().st_size > 1000, f"vídeo GMR muito pequeno: {vid.stat().st_size} bytes"
        info = _ffprobe(vid)
        assert "duration" in info, f"ffprobe sem duração: {info}"
        dur = float(info["duration"])
        assert dur > 0, f"vídeo zero duration"

    @pytest.mark.parametrize("motion_name", MOTIONS)
    def test_video_duration_matches_motion(self, motion_name):
        stem = PKL_MAP[motion_name]
        vid = GMR_VIDEOS / f"{stem}.mp4"
        if not vid.exists():
            pytest.skip("vídeo ausente (coberto em outro teste)")
        info = _ffprobe(vid)
        try:
            pkl = _load_pkl(stem)
            fps = float(pkl["fps"])
        except Exception:
            fps = float(FPS_DEFAULT)
        data = _load_pt(motion_name)
        n = data["base_position"].shape[0]
        expected = n / fps
        vid_dur = float(info["duration"])
        assert abs(vid_dur - expected) < 0.5, (
            f"{motion_name}: duração vídeo={vid_dur:.2f}s, esperado={expected:.2f}s "
            f"(N={n}, fps={fps})"
        )
