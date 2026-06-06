#!/usr/bin/env python3
"""Render a GMR-retargeted Booster T1 PKL to MP4 using MuJoCo offscreen renderer."""

import argparse
import os
import pickle

import numpy as np
import mujoco as mj
import imageio


XML_BY_NDOF = {
    23: "/app/assets/booster_t1/T1_serial.xml",
    29: "/app/assets/booster_t1_29dof/t1_mocap.xml",
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pkl_path", type=str, required=True)
    parser.add_argument("--xml_path", type=str, default=None,
                        help="Override XML path. If None, autodetects from dof_pos.shape[1].")
    parser.add_argument("--robot_base", type=str, default="Waist")
    parser.add_argument("--out_path", type=str, required=True)
    parser.add_argument("--cam_distance", type=float, default=2.5)
    parser.add_argument("--cam_elevation", type=float, default=-10.0)
    parser.add_argument("--cam_azimuth", type=float, default=120.0)
    parser.add_argument("--width", type=int, default=720)
    parser.add_argument("--height", type=int, default=480)
    args = parser.parse_args()

    with open(args.pkl_path, "rb") as f:
        motion = pickle.load(f)

    fps = int(motion["fps"])
    root_pos = motion["root_pos"]          # (T, 3)
    root_rot_xyzw = motion["root_rot"]     # (T, 4) xyzw
    dof_pos = motion["dof_pos"]            # (T, ndof)

    ndof = dof_pos.shape[1]
    if args.xml_path is not None:
        xml_path = args.xml_path
    else:
        if ndof not in XML_BY_NDOF:
            raise ValueError(f"Unexpected dof count {ndof}; expected 23 or 29.")
        xml_path = XML_BY_NDOF[ndof]

    print(f"[INFO] pkl={args.pkl_path}")
    print(f"[INFO] frames={dof_pos.shape[0]} ndof={ndof} fps={fps}")
    print(f"[INFO] xml={xml_path}")
    print(f"[INFO] root_pos z-range=[{root_pos[:,2].min():.3f}, {root_pos[:,2].max():.3f}]")

    model = mj.MjModel.from_xml_path(xml_path)
    data = mj.MjData(model)

    expected_qpos = 7 + ndof
    if model.nq != expected_qpos:
        raise ValueError(
            f"Model nq={model.nq} but expected 7+{ndof}={expected_qpos}; "
            f"mismatch between XML and PKL."
        )

    renderer = mj.Renderer(model, height=args.height, width=args.width)

    cam = mj.MjvCamera()
    cam.type = mj.mjtCamera.mjCAMERA_FREE
    cam.distance = args.cam_distance
    cam.elevation = args.cam_elevation
    cam.azimuth = args.cam_azimuth
    robot_base_id = model.body(args.robot_base).id

    out_dir = os.path.dirname(args.out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    writer = imageio.get_writer(args.out_path, fps=fps)

    n_frames = dof_pos.shape[0]
    for i in range(n_frames):
        # qpos layout: [pos(3), quat_wxyz(4), joints(ndof)]
        data.qpos[:3] = root_pos[i]
        x, y, z, w = root_rot_xyzw[i]
        data.qpos[3:7] = np.array([w, x, y, z])  # xyzw -> wxyz
        data.qpos[7:7 + ndof] = dof_pos[i]
        mj.mj_forward(model, data)

        cam.lookat[:] = data.xpos[robot_base_id]
        renderer.update_scene(data, camera=cam)
        writer.append_data(renderer.render())

    writer.close()
    renderer.close()
    print(f"[INFO] rendered {n_frames} frames, output: {args.out_path}")


if __name__ == "__main__":
    main()
