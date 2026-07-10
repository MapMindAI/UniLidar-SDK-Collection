#!/usr/bin/env python3
"""List available USB cameras and their supported resolutions (Linux/V4L2)."""

import argparse
import glob
import logging
from pathlib import Path
import re
import shutil
import subprocess

import cv2


def list_video_devices() -> list[str]:
    nodes = []
    for path in glob.glob("/dev/video*"):
        name = Path(path).name
        m = re.fullmatch(r"video(\d+)", name)
        if m:
            nodes.append((int(m.group(1)), path))
    return [path for _, path in sorted(nodes, key=lambda item: item[0])]


def is_capture_device(device: str) -> bool:
    if shutil.which("v4l2-ctl") is None:
        return True
    try:
        proc = subprocess.run(
            ["v4l2-ctl", "--device", device, "--all"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, OSError):
        return False

    text = proc.stdout.lower()
    return "video capture" in text or "video capture multilane" in text


def get_usb_info_from_device(device: str) -> dict:
    video_node = Path(device).name
    video_sysfs = Path("/sys/class/video4linux") / video_node
    if not video_sysfs.exists():
        return {
            "usb_port": "unknown",
            "usb_vendor": "unknown",
            "usb_product": "unknown",
            "usb_bus_path": "unknown",
        }

    try:
        device_path = (video_sysfs / "device").resolve()
    except OSError:
        return {
            "usb_port": "unknown",
            "usb_vendor": "unknown",
            "usb_product": "unknown",
            "usb_bus_path": "unknown",
        }

    usb_node = None
    for candidate in [device_path, *device_path.parents]:
        if (candidate / "idVendor").exists() and (candidate / "idProduct").exists():
            usb_node = candidate
            break

    if usb_node is None:
        return {
            "usb_port": "unknown",
            "usb_vendor": "unknown",
            "usb_product": "unknown",
            "usb_bus_path": str(device_path),
        }

    try:
        vendor = (usb_node / "idVendor").read_text(encoding="utf-8").strip()
        product = (usb_node / "idProduct").read_text(encoding="utf-8").strip()
    except OSError:
        vendor = "unknown"
        product = "unknown"

    return {
        "usb_port": usb_node.name,
        "usb_vendor": vendor,
        "usb_product": product,
        "usb_bus_path": str(usb_node),
    }


def get_supported_resolutions_v4l2(device: str) -> list[str]:
    if shutil.which("v4l2-ctl") is None:
        return []

    try:
        proc = subprocess.run(
            ["v4l2-ctl", "--device", device, "--list-formats-ext"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, OSError):
        return []

    resolutions = set()
    for line in proc.stdout.splitlines():
        m = re.search(r"Size:\s+Discrete\s+(\d+)x(\d+)", line)
        if m:
            resolutions.add(f"{m.group(1)}x{m.group(2)}")

    return sorted(
        resolutions,
        key=lambda s: (int(s.split("x")[0]), int(s.split("x")[1])),
    )


def get_supported_resolutions_fallback(device: str) -> list[str]:
    candidates = [
        (320, 240),
        (640, 480),
        (800, 600),
        (1280, 720),
        (1280, 960),
        (1920, 1080),
        (2560, 1440),
        (3840, 2160),
    ]

    cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
    if not cap.isOpened():
        return []

    try:
        found = set()
        for w, h in candidates:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
            actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
            if actual_w > 0 and actual_h > 0:
                found.add(f"{actual_w}x{actual_h}")
        return sorted(found, key=lambda s: (int(s.split("x")[0]), int(s.split("x")[1])))
    finally:
        cap.release()


def get_supported_resolutions(device: str) -> tuple[list[str], str]:
    resolutions = get_supported_resolutions_v4l2(device)
    if resolutions:
        return resolutions, "v4l2-ctl"

    resolutions = get_supported_resolutions_fallback(device)
    if resolutions:
        return resolutions, "opencv-probe"

    return [], "none"


def probe_device(device: str) -> dict | None:
    cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
    try:
        if not cap.isOpened():
            return None

        ok, frame = cap.read()
        if not ok or frame is None:
            return None

        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)

        resolutions, source = get_supported_resolutions(device)

        camera = {
            "device": device,
            "index": int(Path(device).name.replace("video", "")),
            "width": width,
            "height": height,
            "fps": fps,
            "supported_resolutions": resolutions,
            "resolution_source": source,
        }
        camera.update(get_usb_info_from_device(device))
        return camera
    finally:
        cap.release()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="List available USB cameras")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)

    devices = list_video_devices()
    if not devices:
        logging.warning("No /dev/video* nodes found.")
        return

    logging.info("Discovered video nodes: %s", ", ".join(devices))

    capture_devices = [d for d in devices if is_capture_device(d)]
    if not capture_devices:
        logging.warning("No V4L2 capture devices found.")
        return

    found = []
    for device in capture_devices:
        cam = probe_device(device)
        if cam is None:
            logging.info("Skipping %s (not readable as capture stream)", device)
            continue

        found.append(cam)
        logging.info(
            (
                "Found device=%s (index=%d), resolution=%dx%d, fps=%.2f, "
                "usb_port=%s, vid:pid=%s:%s"
            ),
            cam["device"],
            cam["index"],
            cam["width"],
            cam["height"],
            cam["fps"],
            cam["usb_port"],
            cam["usb_vendor"],
            cam["usb_product"],
        )
        logging.info(
            "  supported_resolutions (%s): %s",
            cam["resolution_source"],
            ", ".join(cam["supported_resolutions"]) if cam["supported_resolutions"] else "unknown",
        )

    if not found:
        logging.warning("No readable camera streams detected from capture devices.")
        return

    print("\nAvailable USB cameras:")
    for cam in found:
        print(
            f"- device={cam['device']} index={cam['index']} resolution={cam['width']}x{cam['height']} "
            f"fps={cam['fps']:.2f} usb_port={cam['usb_port']} vid:pid={cam['usb_vendor']}:{cam['usb_product']}"
        )
        print(
            f"  supported_resolutions[{cam['resolution_source']}]: "
            + (", ".join(cam["supported_resolutions"]) if cam["supported_resolutions"] else "unknown")
        )

    port_groups = {}
    for cam in found:
        port_groups.setdefault(cam["usb_port"], []).append(cam["device"])

    print("\nUSB port sharing:")
    for port, devs in sorted(port_groups.items(), key=lambda item: item[0]):
        if port == "unknown":
            print(f"- usb_port={port}: devices={sorted(devs)} (no sysfs USB mapping)")
        elif len(devs) > 1:
            print(f"- usb_port={port}: devices={sorted(devs)} (shared port)")
        else:
            print(f"- usb_port={port}: devices={sorted(devs)}")


if __name__ == "__main__":
    main()
