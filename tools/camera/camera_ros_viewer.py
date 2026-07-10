#!/usr/bin/python3
# coding=utf-8
"""Camera viewer — subscribes to a ROS 2 CompressedImage topic, displays it,
and can save frames to disk (e.g. for building a calibration image set)."""

import os
import time

import cv2
import numpy as np

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage

# ── Config from environment ───────────────────────────────────────────────────
IMAGE_TOPIC = os.environ.get("CAMERA_IMAGE_TOPIC", "/camera/image_raw/compressed")
WINDOW_NAME = os.environ.get("CAMERA_VIEWER_WINDOW", IMAGE_TOPIC)
SAVE_DIR = os.environ.get("CAMERA_SAVE_DIR", "data/camera_calib")


class CameraViewer(Node):
    def __init__(self):
        super().__init__("camera_ros_viewer")
        self.sub = self.create_subscription(
            CompressedImage, IMAGE_TOPIC, self.on_image, 10
        )
        self.frame_count = 0
        self.last_report_t = time.monotonic()
        self.last_frame = None
        self.saved_count = 0
        self.get_logger().info(
            f"Subscribed to {IMAGE_TOPIC} — press 's' to save a frame to "
            f"{SAVE_DIR}, 'q' to quit"
        )

    def on_image(self, msg: CompressedImage):
        frame = cv2.imdecode(np.frombuffer(msg.data, np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            self.get_logger().warning("Failed to decode incoming image")
            return
        self.last_frame = frame

        display = frame.copy()
        cv2.putText(
            display, f"saved: {self.saved_count}  ['s' save, 'q' quit]",
            (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2, cv2.LINE_AA,
        )
        cv2.imshow(WINDOW_NAME, display)

        self.frame_count += 1
        now = time.monotonic()
        if now - self.last_report_t >= 5.0:
            fps = self.frame_count / (now - self.last_report_t)
            self.get_logger().info(f"Receiving at {fps:.1f} fps")
            self.frame_count = 0
            self.last_report_t = now

    def save_frame(self):
        if self.last_frame is None:
            self.get_logger().warning("No frame received yet, nothing to save")
            return
        os.makedirs(SAVE_DIR, exist_ok=True)
        path = os.path.join(SAVE_DIR, f"frame_{self.saved_count:04d}.png")
        cv2.imwrite(path, self.last_frame)
        self.saved_count += 1
        self.get_logger().info(f"Saved {path} ({self.saved_count} total)")


def camera_viewer_node():
    rclpy.init()
    node = CameraViewer()

    try:
        while rclpy.ok():
            rclpy.spin_once(node, timeout_sec=0.05)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            elif key == ord("s"):
                node.save_frame()
    finally:
        cv2.destroyAllWindows()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    try:
        camera_viewer_node()
    except KeyboardInterrupt:
        pass
