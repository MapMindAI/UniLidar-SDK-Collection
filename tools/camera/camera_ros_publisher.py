#!/usr/bin/python3
# coding=utf-8
"""USB camera publisher — opens a V4L2 camera and publishes JPEG-compressed frames to ROS 2."""

import os
import time
from typing import Optional

import cv2
import numpy as np

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage

# ── Config from environment ───────────────────────────────────────────────────
DEVICE       = os.environ.get("CAMERA_DEVICE",  "/dev/video4")
WIDTH        = int(os.environ.get("CAMERA_WIDTH",  "1280"))
HEIGHT       = int(os.environ.get("CAMERA_HEIGHT", "960"))
FPS          = float(os.environ.get("CAMERA_FPS",  "30"))
FRAME_ID     = os.environ.get("CAMERA_FRAME_ID", "camera")
IMAGE_TOPIC  = os.environ.get("CAMERA_IMAGE_TOPIC", "/camera/image_raw/compressed")
JPEG_QUALITY = int(os.environ.get("CAMERA_JPEG_QUALITY", "80"))
EXPOSURE     = os.environ.get("CAMERA_EXPOSURE")
AUTO_EXPOSURE_TARGET_BRIGHTNESS = float(
    os.environ.get("CAMERA_AUTO_EXPOSURE_TARGET_BRIGHTNESS", "100.0")
)
AUTO_EXPOSURE_TOLERANCE = float(
    os.environ.get("CAMERA_AUTO_EXPOSURE_TOLERANCE", "8.0")
)
AUTO_EXPOSURE_MIN = os.environ.get("CAMERA_AUTO_EXPOSURE_MIN")
AUTO_EXPOSURE_MAX = os.environ.get("CAMERA_AUTO_EXPOSURE_MAX")
AUTO_EXPOSURE_INTERVAL = float(os.environ.get("CAMERA_AUTO_EXPOSURE_INTERVAL", "0.5"))
AUTO_EXPOSURE_ROI_RADIUS_RATIO = float(
    os.environ.get("CAMERA_AUTO_EXPOSURE_ROI_RADIUS_RATIO", "0.45")
)
AUTO_EXPOSURE_SAMPLE_STRIDE = max(
    1, int(os.environ.get("CAMERA_AUTO_EXPOSURE_SAMPLE_STRIDE", "8"))
)
AUTO_EXPOSURE_SMOOTHING = float(
    os.environ.get("CAMERA_AUTO_EXPOSURE_SMOOTHING", "0.2")
)
AUTO_EXPOSURE_MAX_SCALE_PER_STEP = float(
    os.environ.get("CAMERA_AUTO_EXPOSURE_MAX_SCALE_PER_STEP", "1.25")
)
AUTO_EXPOSURE_LOG_INTERVAL = float(
    os.environ.get("CAMERA_AUTO_EXPOSURE_LOG_INTERVAL", "5.0")
)


def set_manual_exposure_mode(cap: cv2.VideoCapture) -> None:
    if not cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 1.0):
        raise RuntimeError("Failed to disable camera auto exposure")


def apply_manual_exposure(cap: cv2.VideoCapture, exposure: float) -> None:
    set_manual_exposure_mode(cap)
    if not cap.set(cv2.CAP_PROP_EXPOSURE, exposure):
        raise RuntimeError(f"Failed to set camera exposure to {exposure}")


def open_camera(
    device: str, width: int, height: int, fps: float, exposure: float | None
) -> cv2.VideoCapture:
    cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
    if not cap.isOpened():
        raise RuntimeError(f"Failed to open camera device {device}")
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FPS, fps)
    set_manual_exposure_mode(cap)
    if exposure is not None:
        apply_manual_exposure(cap, exposure)
    return cap


class AutoExposureController:
    def __init__(self, cap: cv2.VideoCapture, node: Node):
        self.cap = cap
        self.node = node
        self.last_adjust_time = 0.0
        self.last_log_time = 0.0
        self.min_exposure: Optional[float] = (
            float(AUTO_EXPOSURE_MIN) if AUTO_EXPOSURE_MIN is not None else None
        )
        self.max_exposure: Optional[float] = (
            float(AUTO_EXPOSURE_MAX) if AUTO_EXPOSURE_MAX is not None else None
        )
        self.smoothed_brightness: Optional[float] = None
        self.metering_shape = None
        self.metering_bounds = None
        self.metering_mask = None
        initial_exposure = cap.get(cv2.CAP_PROP_EXPOSURE)
        if initial_exposure == 0.0:
            initial_exposure = 100.0
        self.current_exposure = self.clamp_exposure(initial_exposure)
        if not self.cap.set(cv2.CAP_PROP_EXPOSURE, self.current_exposure):
            raise RuntimeError(
                f"Failed to set initial camera exposure to {self.current_exposure}"
            )
        self.node.get_logger().info(
            "Software auto exposure enabled: "
            f"target={AUTO_EXPOSURE_TARGET_BRIGHTNESS}, "
            f"range=[{self.min_exposure}, {self.max_exposure}], "
            f"smoothing={AUTO_EXPOSURE_SMOOTHING}, "
            f"max_scale_per_step={AUTO_EXPOSURE_MAX_SCALE_PER_STEP}, "
            f"interval={AUTO_EXPOSURE_INTERVAL}s, "
            f"roi_radius_ratio={AUTO_EXPOSURE_ROI_RADIUS_RATIO}, "
            f"sample_stride={AUTO_EXPOSURE_SAMPLE_STRIDE}"
        )

    def clamp_exposure(self, exposure: float) -> float:
        if self.min_exposure is not None:
            exposure = max(self.min_exposure, exposure)
        if self.max_exposure is not None:
            exposure = min(self.max_exposure, exposure)
        return exposure

    def update_metering_region(self, frame_shape) -> None:
        height, width = frame_shape[:2]
        radius = int(min(height, width) * 0.5 * AUTO_EXPOSURE_ROI_RADIUS_RATIO)
        if radius <= 0:
            self.metering_bounds = (0, height, 0, width)
            self.metering_mask = None
            self.metering_shape = frame_shape
            return

        center_x = width // 2
        center_y = height // 2
        x0 = max(0, center_x - radius)
        x1 = min(width, center_x + radius)
        y0 = max(0, center_y - radius)
        y1 = min(height, center_y + radius)

        ys = np.arange(y0, y1, AUTO_EXPOSURE_SAMPLE_STRIDE)
        xs = np.arange(x0, x1, AUTO_EXPOSURE_SAMPLE_STRIDE)
        mask = (
            (ys[:, None] - center_y) ** 2 + (xs[None, :] - center_x) ** 2
            <= radius**2
        ).astype(np.uint8)

        self.metering_bounds = (y0, y1, x0, x1)
        self.metering_mask = mask * 255
        self.metering_shape = frame_shape

    def compute_mean_brightness(self, frame) -> float:
        if self.metering_shape != frame.shape:
            self.update_metering_region(frame.shape)

        y0, y1, x0, x1 = self.metering_bounds
        sample = frame[
            y0:y1:AUTO_EXPOSURE_SAMPLE_STRIDE,
            x0:x1:AUTO_EXPOSURE_SAMPLE_STRIDE,
        ]
        gray = cv2.cvtColor(sample, cv2.COLOR_BGR2GRAY)
        if self.metering_mask is None:
            return float(cv2.mean(gray)[0])
        return float(cv2.mean(gray, mask=self.metering_mask)[0])

    def log_adjustment(self, now: float, mean_brightness: float) -> None:
        if (
            AUTO_EXPOSURE_LOG_INTERVAL <= 0.0
            or now - self.last_log_time < AUTO_EXPOSURE_LOG_INTERVAL
        ):
            return
        self.last_log_time = now
        self.node.get_logger().info(
            f"Auto exposure adjusted to {self.current_exposure:.1f} "
            f"(mean brightness {mean_brightness:.1f}, "
            f"smoothed {self.smoothed_brightness:.1f})"
        )

    def update(self, frame) -> None:
        now = time.monotonic()
        if now - self.last_adjust_time < AUTO_EXPOSURE_INTERVAL:
            return

        mean_brightness = self.compute_mean_brightness(frame)
        if self.smoothed_brightness is None:
            self.smoothed_brightness = mean_brightness
        else:
            self.smoothed_brightness = (
                (1.0 - AUTO_EXPOSURE_SMOOTHING) * self.smoothed_brightness
                + AUTO_EXPOSURE_SMOOTHING * mean_brightness
            )

        error = AUTO_EXPOSURE_TARGET_BRIGHTNESS - self.smoothed_brightness
        if abs(error) <= AUTO_EXPOSURE_TOLERANCE:
            self.last_adjust_time = now
            return

        target_scale = AUTO_EXPOSURE_TARGET_BRIGHTNESS / max(
            self.smoothed_brightness, 1.0
        )
        max_scale = max(AUTO_EXPOSURE_MAX_SCALE_PER_STEP, 1.0)
        target_scale = max(1.0 / max_scale, min(max_scale, target_scale))
        next_exposure = self.current_exposure * target_scale
        next_exposure = self.clamp_exposure(next_exposure)
        if next_exposure == self.current_exposure:
            self.last_adjust_time = now
            return
        if not self.cap.set(cv2.CAP_PROP_EXPOSURE, next_exposure):
            self.node.get_logger().warning(
                f"Failed to update camera exposure to {next_exposure}"
            )
            self.last_adjust_time = now
            return

        self.current_exposure = next_exposure
        self.last_adjust_time = now
        self.log_adjustment(now, mean_brightness)


def camera_publisher_node():
    rclpy.init()
    node = Node("camera_ros_publisher")
    pub = node.create_publisher(CompressedImage, IMAGE_TOPIC, 10)

    node.get_logger().info(
        f"Opening {DEVICE}, requesting {WIDTH}x{HEIGHT}@{FPS}fps, publishing to {IMAGE_TOPIC}"
    )
    exposure = float(EXPOSURE) if EXPOSURE is not None else None
    cap = open_camera(DEVICE, WIDTH, HEIGHT, FPS, exposure)
    actual_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    actual_fps = cap.get(cv2.CAP_PROP_FPS)
    node.get_logger().info(f"Opened {DEVICE} at {actual_width}x{actual_height}@{actual_fps:.1f}fps")
    if exposure is not None:
        actual_exposure = cap.get(cv2.CAP_PROP_EXPOSURE)
        node.get_logger().info(
            f"Requested exposure {exposure}, camera reports {actual_exposure}"
        )
        auto_exposure_controller = None
    else:
        auto_exposure_controller = AutoExposureController(cap, node)

    encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY]
    period = 1.0 / FPS if FPS > 0 else 0.0
    warned_read_failure = False

    try:
        while rclpy.ok():
            loop_start = time.monotonic()
            rclpy.spin_once(node, timeout_sec=0.0)

            ok, frame = cap.read()
            if not ok or frame is None:
                if not warned_read_failure:
                    node.get_logger().warning(f"Failed to read frame from {DEVICE}")
                    warned_read_failure = True
                time.sleep(0.1)
                continue
            warned_read_failure = False
            received_time = node.get_clock().now().to_msg()
            if auto_exposure_controller is not None:
                auto_exposure_controller.update(frame)

            ok, encoded = cv2.imencode(".jpg", frame, encode_params)
            if not ok:
                node.get_logger().warning("Failed to JPEG-encode frame")
                continue

            msg = CompressedImage()
            msg.header.stamp = received_time
            msg.header.frame_id = FRAME_ID
            msg.format = "jpeg"
            msg.data = encoded.tobytes()
            pub.publish(msg)

            if period > 0.0:
                elapsed = time.monotonic() - loop_start
                remaining = period - elapsed
                if remaining > 0:
                    time.sleep(remaining)
    finally:
        cap.release()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    try:
        camera_publisher_node()
    except KeyboardInterrupt:
        pass
