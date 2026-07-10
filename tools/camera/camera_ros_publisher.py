#!/usr/bin/python3
# coding=utf-8
"""USB camera publisher — opens a V4L2 camera and publishes JPEG-compressed frames to ROS 2."""

import os
import time

import cv2

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


def open_camera(device: str, width: int, height: int, fps: float) -> cv2.VideoCapture:
    cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
    if not cap.isOpened():
        raise RuntimeError(f"Failed to open camera device {device}")
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FPS, fps)
    return cap


def camera_publisher_node():
    rclpy.init()
    node = Node("camera_ros_publisher")
    pub = node.create_publisher(CompressedImage, IMAGE_TOPIC, 10)

    node.get_logger().info(
        f"Opening {DEVICE} at {WIDTH}x{HEIGHT}@{FPS}fps, publishing to {IMAGE_TOPIC}"
    )
    cap = open_camera(DEVICE, WIDTH, HEIGHT, FPS)

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
