#!/usr/bin/python3
# coding=utf-8
"""Double Sphere camera model.

Reference: V. Usenko, N. Demmel, D. Cremers, "The Double Sphere Camera Model", 3DV 2018.
Same parameterization ("ds") used by the Basalt calibration/VIO toolkit.

Intrinsics are the 6-vector (fx, fy, cx, cy, xi, alpha).
"""

import numpy as np
import yaml


def load_calibration_yaml(path: str) -> tuple:
    """Load a calibration.yaml written by calibrate_double_sphere.py.

    Returns (intrinsics 6-vector, (width, height)).
    """
    with open(path) as f:
        data = yaml.safe_load(f)
    intrinsics = np.array(
        [data["fx"], data["fy"], data["cx"], data["cy"], data["xi"], data["alpha"]]
    )
    return intrinsics, (int(data["image_width"]), int(data["image_height"]))


def build_undistort_map(intrinsics, dst_width: int, dst_height: int, fov_deg: float) -> tuple:
    """Build a cv2.remap-compatible (map_x, map_y) that renders a rectified,
    virtual-pinhole view of the given Double Sphere camera.

    fov_deg is the desired horizontal field of view of the virtual pinhole
    camera; a rectilinear projection cannot cover a full fisheye FOV, so this
    is necessarily a crop of the original image, not a full unwarp.
    """
    fx_v = (dst_width / 2.0) / np.tan(np.radians(fov_deg) / 2.0)
    cx_v, cy_v = dst_width / 2.0, dst_height / 2.0

    us, vs = np.meshgrid(np.arange(dst_width), np.arange(dst_height))
    x = (us - cx_v) / fx_v
    y = (vs - cy_v) / fx_v
    rays = np.stack([x, y, np.ones_like(x)], axis=-1)

    pixels, valid = project(rays, intrinsics)
    map_x = pixels[..., 0].astype(np.float32)
    map_y = pixels[..., 1].astype(np.float32)
    map_x[~valid] = -1
    map_y[~valid] = -1
    return map_x, map_y


def project(points_cam: np.ndarray, intrinsics) -> tuple:
    """Project 3D points (camera frame, shape (...,3)) to pixels (...,2).

    Returns (pixels, valid) where valid is False for points outside the
    model's forward-projection domain (denominator collapses to ~0).
    """
    fx, fy, cx, cy, xi, alpha = intrinsics
    x = points_cam[..., 0]
    y = points_cam[..., 1]
    z = points_cam[..., 2]

    d1 = np.sqrt(x * x + y * y + z * z)
    zp = xi * d1 + z
    d2 = np.sqrt(x * x + y * y + zp * zp)
    denom = alpha * d2 + (1.0 - alpha) * zp

    valid = denom > 1e-9
    denom_safe = np.where(valid, denom, 1e-9)
    u = fx * x / denom_safe + cx
    v = fy * y / denom_safe + cy
    return np.stack([u, v], axis=-1), valid


def unproject(pixels: np.ndarray, intrinsics) -> tuple:
    """Unproject pixels (...,2) to camera-frame bearing vectors (...,3) (not unit length).

    Returns (bearings, valid) where valid is False for pixels outside the
    model's domain (would require unprojecting off the sensor's FOV).
    """
    fx, fy, cx, cy, xi, alpha = intrinsics
    mx = (pixels[..., 0] - cx) / fx
    my = (pixels[..., 1] - cy) / fy
    r2 = mx * mx + my * my

    disc1 = 1.0 - (2.0 * alpha - 1.0) * r2
    valid = disc1 > 0
    disc1_safe = np.where(valid, disc1, 1e-12)
    mz = (1.0 - alpha * alpha * r2) / (alpha * np.sqrt(disc1_safe) + (1.0 - alpha))

    disc2 = mz * mz + (1.0 - xi * xi) * r2
    valid = valid & (disc2 > 0)
    disc2_safe = np.where(disc2 > 0, disc2, 1e-12)
    scale = (mz * xi + np.sqrt(disc2_safe)) / (mz * mz + r2)

    bearings = np.stack([scale * mx, scale * my, scale * mz - xi], axis=-1)
    return bearings, valid


def max_fov_deg(xi: float, alpha: float) -> float:
    """Theoretical maximum field of view (degrees) supported by these parameters."""
    if alpha <= 0.5:
        w1 = alpha / (1.0 - alpha)
    else:
        w1 = (1.0 - alpha) / alpha
    w2 = (w1 + xi) / np.sqrt(2.0 * w1 * xi + xi * xi + 1.0)
    # Valid forward-projection domain: z > -w2 * d1, i.e. angle-from-optical-axis < acos(-w2)
    return float(np.degrees(np.arccos(np.clip(-w2, -1.0, 1.0)))) * 2.0
