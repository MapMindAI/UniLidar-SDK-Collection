#!/usr/bin/python3
# coding=utf-8
"""Camera viewer — subscribes to a ROS 2 CompressedImage topic and displays it."""

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


class CameraViewer(Node):
    def __init__(self):
        super().__init__("camera_ros_viewer")
        self.sub = self.create_subscription(
            CompressedImage, IMAGE_TOPIC, self.on_image, 10
        )
        self.frame_count = 0
        self.last_report_t = time.monotonic()
        self.get_logger().info(f"Subscribed to {IMAGE_TOPIC}, press 'q' to quit")

    def on_image(self, msg: CompressedImage):
        frame = cv2.imdecode(np.frombuffer(msg.data, np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            self.get_logger().warning("Failed to decode incoming image")
            return

        cv2.imshow(WINDOW_NAME, frame)

        self.frame_count += 1
        now = time.monotonic()
        if now - self.last_report_t >= 5.0:
            fps = self.frame_count / (now - self.last_report_t)
            self.get_logger().info(f"Receiving at {fps:.1f} fps")
            self.frame_count = 0
            self.last_report_t = now


def camera_viewer_node():
    rclpy.init()
    node = CameraViewer()

    try:
        while rclpy.ok():
            rclpy.spin_once(node, timeout_sec=0.05)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
    finally:
        cv2.destroyAllWindows()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    try:
        camera_viewer_node()
    except KeyboardInterrupt:
        pass
