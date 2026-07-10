#!/usr/bin/python3
# coding=utf-8
"""Undistorted camera viewer — loads calibrated Double Sphere intrinsics,
subscribes to a ROS 2 CompressedImage topic, and shows a rectified
(virtual-pinhole) view of the live feed."""

import os

import cv2
import numpy as np

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage

import double_sphere as ds

# ── Config from environment ───────────────────────────────────────────────────
IMAGE_TOPIC = os.environ.get("CAMERA_IMAGE_TOPIC", "/camera/image_raw/compressed")
WINDOW_NAME = os.environ.get("CAMERA_VIEWER_WINDOW", "undistorted")
CALIBRATION_YAML = os.environ.get("CAMERA_CALIBRATION_YAML", "calibration.yaml")
FOV_DEG = float(os.environ.get("CAMERA_UNDISTORT_FOV_DEG", "120"))


class UndistortViewer(Node):
    def __init__(self):
        super().__init__("camera_undistort_viewer")
        self.intrinsics, self.calib_size = ds.load_calibration_yaml(CALIBRATION_YAML)
        width, height = self.calib_size
        self.map_x, self.map_y = ds.build_undistort_map(self.intrinsics, width, height, FOV_DEG)
        self.warned_size_mismatch = False

        xi, alpha = self.intrinsics[4], self.intrinsics[5]
        max_fov = ds.max_fov_deg(xi, alpha)
        if FOV_DEG >= max_fov:
            self.get_logger().warning(
                f"Requested FOV {FOV_DEG:.0f} deg >= this calibration's max "
                f"{max_fov:.0f} deg -- edges of the undistorted view will be black"
            )

        self.sub = self.create_subscription(CompressedImage, IMAGE_TOPIC, self.on_image, 10)
        self.get_logger().info(
            f"Loaded {CALIBRATION_YAML} ({width}x{height}), undistorting {IMAGE_TOPIC} "
            f"at {FOV_DEG:.0f} deg virtual FOV, press 'q' to quit"
        )

    def on_image(self, msg: CompressedImage):
        frame = cv2.imdecode(np.frombuffer(msg.data, np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            self.get_logger().warning("Failed to decode incoming image")
            return

        if (frame.shape[1], frame.shape[0]) != self.calib_size:
            if not self.warned_size_mismatch:
                self.get_logger().warning(
                    f"Frame size {frame.shape[1]}x{frame.shape[0]} != calibration size "
                    f"{self.calib_size[0]}x{self.calib_size[1]} -- undistortion will be wrong"
                )
                self.warned_size_mismatch = True
            return

        undistorted = cv2.remap(
            frame, self.map_x, self.map_y,
            interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT,
        )
        cv2.imshow(WINDOW_NAME, undistorted)


def undistort_viewer_node():
    rclpy.init()
    node = UndistortViewer()

    try:
        while rclpy.ok():
            rclpy.spin_once(node, timeout_sec=0.05)
            if (cv2.waitKey(1) & 0xFF) == ord("q"):
                break
    finally:
        cv2.destroyAllWindows()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    try:
        undistort_viewer_node()
    except KeyboardInterrupt:
        pass
