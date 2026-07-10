#!/usr/bin/python3
# coding=utf-8
"""Calibrate a camera's intrinsics from AprilGrid images using the Double Sphere model.

Usage:
    python3 calibrate_double_sphere.py --images-dir data/camera_calib --board aprilgrid.board.yaml

Reference model: V. Usenko, N. Demmel, D. Cremers, "The Double Sphere Camera
Model", 3DV 2018 -- the same "ds" camera type used by Basalt. The output yaml's
fx/fy/cx/cy/xi/alpha fields can be copied directly into a Basalt or Kalibr
config that expects that parameterization.
"""

import argparse
import glob
import os

import cv2
import numpy as np
import yaml
from scipy.optimize import least_squares
from scipy.sparse import lil_matrix

from aprilgrid_board import load_board_yaml
import double_sphere as ds


# ── AprilGrid detection ────────────────────────────────────────────────────────

def detect_board(gray: np.ndarray, board, detector) -> tuple:
    """Detect tags and return (object_points (N,3), image_points (N,2), num_tags)."""
    corners, ids, _ = detector.detectMarkers(gray)
    if ids is None:
        return np.zeros((0, 3)), np.zeros((0, 2)), 0

    points_by_id = board.object_points_by_id()
    obj_pts, img_pts = [], []
    for tag_corners, tag_id in zip(corners, ids.ravel()):
        obj = points_by_id.get(int(tag_id))
        if obj is None:
            continue
        obj_pts.extend(obj)
        img_pts.extend(tag_corners.reshape(4, 2))

    if not obj_pts:
        return np.zeros((0, 3)), np.zeros((0, 2)), 0
    return np.array(obj_pts), np.array(img_pts), len(obj_pts) // 4


# ── Bearing-vector pose bootstrap (works for FOV > 180 deg, unlike solvePnP) ───

def _skew(v: np.ndarray) -> np.ndarray:
    x, y, z = v
    return np.array([[0, -z, y], [z, 0, -x], [-y, x, 0]])


def _homography_from_bearings(board_xy: np.ndarray, bearings: np.ndarray) -> np.ndarray:
    n = board_xy.shape[0]
    A = np.zeros((3 * n, 9))
    for i in range(n):
        x, y = board_xy[i]
        p = np.array([x, y, 1.0])
        s = _skew(bearings[i])
        m = np.zeros((3, 9))
        for r in range(3):
            m[:, 3 * r : 3 * r + 3] = s[:, r : r + 1] * p[None, :]
        A[3 * i : 3 * i + 3, :] = m
    _, _, vt = np.linalg.svd(A)
    return vt[-1].reshape(3, 3)


def _decompose_homography(H: np.ndarray) -> tuple:
    h1, h2, h3 = H[:, 0], H[:, 1], H[:, 2]
    m = np.stack([h1, h2], axis=1)
    u, s, vt = np.linalg.svd(m, full_matrices=False)
    r12 = u @ vt
    lam = 2.0 / (s[0] + s[1])
    r1, r2 = r12[:, 0], r12[:, 1]
    r3 = np.cross(r1, r2)
    R = np.stack([r1, r2, r3], axis=1)
    t = lam * h3
    return R, t


def bootstrap_pose(board_xy: np.ndarray, pixels: np.ndarray, intrinsics) -> tuple:
    """Initial (rvec, tvec) for a planar board from bearing vectors, via a
    homography DLT + decomposition. Unlike cv2.solvePnP this has no
    forward-facing (z>0) assumption, so it works for FOV > 180 deg.
    """
    bearings, _ = ds.unproject(pixels, intrinsics)
    H = _homography_from_bearings(board_xy, bearings)

    R, t = _decompose_homography(H)
    board3 = np.c_[board_xy, np.zeros(len(board_xy))]
    reconstructed = (R @ board3.T).T + t
    if np.sum(np.einsum("ij,ij->i", reconstructed, bearings)) < 0:
        R, t = _decompose_homography(-H)

    rvec, _ = cv2.Rodrigues(R)
    return rvec.ravel(), t


# ── Bundle adjustment ──────────────────────────────────────────────────────────

INTRINSICS_SIZE = 6
POSE_SIZE = 6


def _pack(intrinsics, poses) -> np.ndarray:
    x = list(intrinsics)
    for rvec, tvec in poses:
        x.extend(rvec)
        x.extend(tvec)
    return np.array(x, dtype=float)


def _unpack(x: np.ndarray, num_views: int) -> tuple:
    intrinsics = x[:INTRINSICS_SIZE]
    poses = []
    idx = INTRINSICS_SIZE
    for _ in range(num_views):
        poses.append((x[idx : idx + 3], x[idx + 3 : idx + 6]))
        idx += POSE_SIZE
    return intrinsics, poses


def _residuals(x, object_points_list, image_points_list) -> np.ndarray:
    intrinsics, poses = _unpack(x, len(object_points_list))
    out = []
    for obj, img, (rvec, tvec) in zip(object_points_list, image_points_list, poses):
        R, _ = cv2.Rodrigues(rvec)
        cam_pts = (R @ obj.T).T + tvec
        proj, _ = ds.project(cam_pts, intrinsics)
        out.append((proj - img).ravel())
    return np.concatenate(out)


def _jac_sparsity(object_points_list) -> lil_matrix:
    num_views = len(object_points_list)
    n_res = sum(len(o) for o in object_points_list) * 2
    n_params = INTRINSICS_SIZE + POSE_SIZE * num_views
    sparsity = lil_matrix((n_res, n_params), dtype=np.int8)
    row = 0
    idx = INTRINSICS_SIZE
    for obj in object_points_list:
        n = len(obj) * 2
        sparsity[row : row + n, 0:INTRINSICS_SIZE] = 1
        sparsity[row : row + n, idx : idx + POSE_SIZE] = 1
        row += n
        idx += POSE_SIZE
    return sparsity


def _bounds(num_views: int, width: int, height: int) -> tuple:
    n_params = INTRINSICS_SIZE + POSE_SIZE * num_views
    lb = np.full(n_params, -np.inf)
    ub = np.full(n_params, np.inf)
    max_dim = max(width, height)
    lb[0], ub[0] = 1.0, 20.0 * max_dim  # fx
    lb[1], ub[1] = 1.0, 20.0 * max_dim  # fy
    lb[2], ub[2] = -0.5 * width, 1.5 * width  # cx
    lb[3], ub[3] = -0.5 * height, 1.5 * height  # cy
    lb[4], ub[4] = -1.0, 1.0  # xi
    lb[5], ub[5] = 1e-6, 1.0 - 1e-6  # alpha
    return lb, ub


def run_bundle_adjustment(
    object_points_list,
    image_points_list,
    image_size,
    init_intrinsics=None,
    hfov_deg=190.0,
    reject_px=5.0,
) -> dict:
    """Jointly refine (fx,fy,cx,cy,xi,alpha) and one pose per view.

    Two passes: an initial fit, then a refit after dropping observations
    whose reprojection error exceeds reject_px (handles the occasional
    mis-detected tag corner).
    """
    width, height = image_size
    if init_intrinsics is None:
        fx0 = width / np.radians(hfov_deg)
        init_intrinsics = np.array([fx0, fx0, width / 2.0, height / 2.0, 0.0, 0.5])

    poses = [
        bootstrap_pose(obj[:, :2], img, init_intrinsics)
        for obj, img in zip(object_points_list, image_points_list)
    ]

    obj_list, img_list = list(object_points_list), list(image_points_list)
    view_indices = list(range(len(obj_list)))
    x = _pack(init_intrinsics, poses)

    for _pass in range(2):
        lb, ub = _bounds(len(obj_list), width, height)
        sparsity = _jac_sparsity(obj_list)
        result = least_squares(
            _residuals,
            x,
            args=(obj_list, img_list),
            jac_sparsity=sparsity,
            x_scale="jac",
            method="trf",
            bounds=(lb, ub),
        )
        x = result.x

        residuals = _residuals(x, obj_list, img_list).reshape(-1, 2)
        errors_px = np.linalg.norm(residuals, axis=1)

        if _pass == 1:
            break

        # Drop outlier observations and re-fit once. Track surviving view
        # indices explicitly so per-view poses stay aligned with their view
        # even if a view in the middle of the list is dropped entirely.
        kept_indices, kept_obj, kept_img = [], [], []
        idx = 0
        for i, (obj, img) in enumerate(zip(obj_list, img_list)):
            n = len(obj)
            keep = errors_px[idx : idx + n] <= reject_px
            idx += n
            if keep.sum() >= 4:  # need at least one full tag
                kept_indices.append(i)
                kept_obj.append(obj[keep])
                kept_img.append(img[keep])

        if sum(len(o) for o in kept_obj) == sum(len(o) for o in obj_list):
            break  # nothing to drop, skip the redundant second pass

        intrinsics, poses = _unpack(x, len(obj_list))
        poses = [poses[i] for i in kept_indices]
        view_indices = [view_indices[i] for i in kept_indices]
        obj_list, img_list = kept_obj, kept_img
        x = _pack(intrinsics, poses)

    intrinsics, poses = _unpack(x, len(obj_list))
    residuals = _residuals(x, obj_list, img_list).reshape(-1, 2)
    errors_px = np.linalg.norm(residuals, axis=1)

    per_view_rmse = []
    idx = 0
    for obj in obj_list:
        n = len(obj)
        per_view_rmse.append(float(np.sqrt(np.mean(errors_px[idx : idx + n] ** 2))))
        idx += n

    return {
        "intrinsics": intrinsics,
        "poses": poses,
        "overall_rmse_px": float(np.sqrt(np.mean(errors_px ** 2))),
        "per_view_rmse_px": per_view_rmse,
        "view_indices": view_indices,  # indices into the input lists that survived rejection
        "num_views_used": len(obj_list),
        "num_points_used": sum(len(o) for o in obj_list),
    }


# ── CLI ─────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--images-dir", required=True, help="Directory of calibration images")
    parser.add_argument("--board", required=True, help="board.yaml written by generate_aprilgrid.py")
    parser.add_argument("--output", default=None, help="Output yaml path (default: <images-dir>/calibration.yaml)")
    parser.add_argument("--min-tags", type=int, default=4, help="Minimum tags detected to keep an image")
    parser.add_argument("--reject-px", type=float, default=5.0, help="Outlier rejection threshold (pixels)")
    parser.add_argument("--hfov-deg", type=float, default=190.0, help="Rough horizontal FOV estimate, for the initial focal-length guess")
    parser.add_argument("--visualize", action="store_true", help="Show each image's detections")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    board = load_board_yaml(args.board)

    params = cv2.aruco.DetectorParameters()
    params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_APRILTAG
    detector = cv2.aruco.ArucoDetector(board.dictionary(), params)

    image_paths = sorted(
        p for ext in ("*.png", "*.jpg", "*.jpeg") for p in glob.glob(os.path.join(args.images_dir, ext))
    )
    if not image_paths:
        raise SystemExit(f"No images found in {args.images_dir}")

    object_points_list, image_points_list, used_paths = [], [], []
    image_size = None
    for path in image_paths:
        img = cv2.imread(path)
        if img is None:
            print(f"skip {path}: failed to read")
            continue
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        if image_size is None:
            image_size = (gray.shape[1], gray.shape[0])

        obj, pix, num_tags = detect_board(gray, board, detector)
        if num_tags < args.min_tags:
            print(f"skip {path}: only {num_tags} tags detected (need {args.min_tags})")
            continue

        if args.visualize:
            preview = img.copy()
            cv2.aruco.drawDetectedMarkers(preview, [pix[i : i + 4].reshape(1, 4, 2).astype(np.float32) for i in range(0, len(pix), 4)])
            cv2.imshow("detections", preview)
            cv2.waitKey(200)

        object_points_list.append(obj)
        image_points_list.append(pix)
        used_paths.append(path)
        print(f"{path}: {num_tags} tags, {len(obj)} points")

    if args.visualize:
        cv2.destroyAllWindows()

    if len(object_points_list) < 3:
        raise SystemExit(f"Only {len(object_points_list)} usable images; need at least 3 (many more recommended)")

    result = run_bundle_adjustment(
        object_points_list,
        image_points_list,
        image_size,
        hfov_deg=args.hfov_deg,
        reject_px=args.reject_px,
    )

    fx, fy, cx, cy, xi, alpha = (float(v) for v in result["intrinsics"])
    print("\n--- calibration result (Double Sphere) ---")
    print(f"fx={fx:.3f} fy={fy:.3f} cx={cx:.3f} cy={cy:.3f} xi={xi:.5f} alpha={alpha:.5f}")
    print(f"max supported FOV at these parameters: {ds.max_fov_deg(xi, alpha):.1f} deg")
    print(f"overall reprojection RMSE: {result['overall_rmse_px']:.3f} px "
          f"over {result['num_views_used']}/{len(object_points_list)} views, "
          f"{result['num_points_used']} points")

    used_paths_final = [used_paths[i] for i in result["view_indices"]]
    worst = sorted(zip(used_paths_final, result["per_view_rmse_px"]), key=lambda kv: -kv[1])[:5]
    print("worst views:")
    for path, rmse in worst:
        print(f"  {path}: {rmse:.3f} px")

    output_path = args.output or os.path.join(args.images_dir, "calibration.yaml")
    with open(output_path, "w") as f:
        yaml.safe_dump(
            {
                "model": "double_sphere",
                "comment": "fx,fy,cx,cy,xi,alpha use the Usenko et al. 2018 Double Sphere "
                "parameterization (Basalt camera_type: ds)",
                "image_width": image_size[0],
                "image_height": image_size[1],
                "fx": fx,
                "fy": fy,
                "cx": cx,
                "cy": cy,
                "xi": xi,
                "alpha": alpha,
                "overall_rmse_px": result["overall_rmse_px"],
                "num_views_used": result["num_views_used"],
                "num_views_total": len(object_points_list),
            },
            f,
            sort_keys=False,
        )
    print(f"\nWrote {output_path}")


if __name__ == "__main__":
    main()
