#!/usr/bin/env python3
"""Export NavSatFix messages from a ROS 2 bag to RTK viewer text format."""

import argparse
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import rosbag2_py
    from rclpy.serialization import deserialize_message
    from sensor_msgs.msg import NavSatFix
except ImportError as exc:
    raise SystemExit(
        f"ROS 2 not available: {exc}\n"
        "Source your ROS 2 workspace first:\n"
        "  source /opt/ros/humble/setup.bash"
    ) from exc


# ── Fix quality helpers ───────────────────────────────────────────────────────

def infer_fix_quality(msg: NavSatFix) -> int:
    """
    NavSatFix.status loses the distinction between RTK fixed/float/DGPS
    (all become GBAS_FIX=2). Recover the original quality from covariance.
    """
    s = msg.status.status
    if s < 0:   # STATUS_NO_FIX
        return 0
    if s == 0:  # STATUS_FIX
        return 4
    # STATUS_GBAS_FIX — distinguish by horizontal variance
    if msg.position_covariance_type != NavSatFix.COVARIANCE_TYPE_UNKNOWN:
        h_var = msg.position_covariance[0]
        if h_var <= 0.001:   # ≤ 0.032 m std → RTK fixed
            return 4
        if h_var <= 0.25:    # ≤ 0.50 m std → RTK float
            return 5
    return 2  # DGPS or unknown GBAS


_FIX_LABEL = {0: "invalid", 1: "单点", 2: "dgps", 4: "固定", 5: "浮动"}

def fix_label(q: int) -> str:
    return _FIX_LABEL.get(q, str(q))


def horizontal_accuracy_m(msg: NavSatFix) -> float:
    if msg.position_covariance_type == NavSatFix.COVARIANCE_TYPE_UNKNOWN:
        return float("nan")
    return math.sqrt(max(0.0, msg.position_covariance[0]))


# ── Timestamp formatting ──────────────────────────────────────────────────────

def ns_to_local(stamp_ns: int) -> datetime:
    return datetime.fromtimestamp(stamp_ns / 1e9, tz=timezone.utc).astimezone()


def fmt_ts(dt: datetime) -> str:
    """YYYY-M-D HH:MM:SS.mmm  (no leading zeros on month/day — matches viewer regex)"""
    return f"{dt.year}-{dt.month}-{dt.day} {dt.strftime('%H:%M:%S')}.{dt.microsecond // 1000:03d}"


def fmt_date(dt: datetime) -> str:
    return f"{dt.year}/{dt.month:02d}/{dt.day:02d}"


def fmt_time(dt: datetime) -> str:
    return f"{dt.strftime('%H:%M:%S')}.{dt.microsecond // 1000:03d}"


# ── Bag reading ───────────────────────────────────────────────────────────────

def open_reader(bag_path: str) -> rosbag2_py.SequentialReader:
    # Auto-detect storage plugin from extension; empty string lets rosbag2 decide.
    p = Path(bag_path)
    if p.suffix == ".mcap":
        storage_id = "mcap"
    elif p.suffix == ".db3":
        storage_id = "sqlite3"
    else:
        storage_id = ""   # directory bag — rosbag2 reads metadata.yaml

    storage_options  = rosbag2_py.StorageOptions(uri=bag_path, storage_id=storage_id)
    converter_options = rosbag2_py.ConverterOptions(
        input_serialization_format="cdr",
        output_serialization_format="cdr",
    )
    reader = rosbag2_py.SequentialReader()
    reader.open(storage_options, converter_options)
    return reader


def list_topics(reader: rosbag2_py.SequentialReader) -> dict:
    return {t.name: t.type for t in reader.get_all_topics_and_types()}


# ── Export ────────────────────────────────────────────────────────────────────

def export(bag_path: str, topic: str, output_path: str) -> None:
    reader = open_reader(bag_path)
    available = list_topics(reader)

    if topic not in available:
        print(f"Topic '{topic}' not found in bag. Available topics:", file=sys.stderr)
        for name, typ in sorted(available.items()):
            print(f"  {name}  [{typ}]", file=sys.stderr)
        raise SystemExit(1)

    reader.set_filter(rosbag2_py.StorageFilter(topics=[topic]))

    count = 0
    skipped = 0

    with open(output_path, "w", encoding="utf-8") as f:
        # One-line header — viewer skips any line not starting with 4 digits.
        f.write("timestamp\tdevice\tdate\tsys_time\tgps_date\tgps_time\tsats\tfix\thdg\tsol\tlon\tlat\tacc\talt\tspeed\n")

        while reader.has_next():
            topic_name, data, stamp_ns = reader.read_next()
            try:
                msg: NavSatFix = deserialize_message(data, NavSatFix)
            except Exception:
                skipped += 1
                continue

            if math.isnan(msg.latitude) or math.isnan(msg.longitude):
                skipped += 1
                continue

            dt      = ns_to_local(stamp_ns)
            ts      = fmt_ts(dt)
            date    = fmt_date(dt)
            time_s  = fmt_time(dt)
            q       = infer_fix_quality(msg)
            fix     = fix_label(q)
            acc     = horizontal_accuracy_m(msg)
            acc_str = f"{acc:.4f}" if not math.isnan(acc) else "0.0000"
            alt_str = f"{msg.altitude:.4f}" if not math.isnan(msg.altitude) else "0.0000"

            # Line 0: timestamp \t device \t date
            f.write(f"{ts}\tRTKBag\t{date}\n")
            # Line 1: sys_time \t gps_date  (viewer reads but doesn't use)
            f.write(f"{time_s}\t{date}\n")
            # Line 2: gps_time \t sats \t fix \t hdg \t sol \t lon \t lat \t acc \t alt \t speed
            #   viewer fields[5]=lon  [6]=lat  [7]=acc  [8]=alt  [1]=sats  [2]=fix
            f.write(f"{time_s}\t0\t{fix}\t0\t0\t{msg.longitude:.8f}\t{msg.latitude:.8f}\t{acc_str}\t{alt_str}\t0.0000\n")
            count += 1

    print(f"Exported {count} points → {output_path}")
    if skipped:
        print(f"Skipped {skipped} messages (decode error or NaN position)")


# ── CLI ───────────────────────────────────────────────────────────────────────

def default_output(bag_path: str) -> str:
    p = Path(bag_path)
    stem = p.stem if p.is_file() else p.name
    return str(p.parent / f"{stem}_rtk.txt")


def main() -> None:
    p = argparse.ArgumentParser(
        description="Export NavSatFix from a ROS 2 bag to RTK viewer .txt format"
    )
    p.add_argument("bag",           help="Path to bag file (.db3, .mcap) or bag directory")
    p.add_argument("-t", "--topic", default="/rtk/fix",
                   help="NavSatFix topic name (default: /rtk/fix)")
    p.add_argument("-o", "--output", default="",
                   help="Output .txt path (default: <bag_name>_rtk.txt next to bag)")
    args = p.parse_args()

    bag_path = Path(args.bag)
    if not bag_path.exists():
        raise SystemExit(f"Not found: {bag_path}")

    output = args.output or default_output(str(bag_path))
    export(str(bag_path), args.topic, output)


if __name__ == "__main__":
    main()
