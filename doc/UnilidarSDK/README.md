# Unitree Lidar SDK

This repo wraps the Unitree L2 lidar SDK with a Bazel build, a ROS 2 bridge,
and offline packet tools for recording, replay, and calibration.

## What is here

- `unitree_lidar_sdk/include/` and `lib/`: vendor headers and prebuilt static libraries
- `unitree_lidar_sdk/examples/`: serial and UDP SDK examples
- `unitree_lidar_sdk/unitree_lidar_rosnode.cc`: ROS 2 bridge for `/unilidar/imu` and `/unilidar/cloud`
- `unitree_lidar_sdk/unitree_lidar_packet_recorder.cc`: raw packet recorder
- `unitree_lidar_sdk/unitree_lidar_packet_replayer.cc`: packet replay and inspection
- `unitree_lidar_sdk/calibration/`: plane extraction, optimization, and Pangolin viewer

## Build

```bash
bazel build //...
```

If you change `unitree_lidar_rosnode.cc`, rebuild the arm64 binary and replace
`docker_compose/unitree_lidar_sdk/unitree_lidar_rosnode`. The compose stack
runs that checked-in binary directly.

## ROS 2 bridge

`unitree_lidar_rosnode` reads Unitree lidar data and publishes:

- `/unilidar/imu`
- `/unilidar/cloud`

It supports two cloud paths:

- SDK cloud conversion: use the vendor point cloud and translate it into `PointCloud2`
- Raw packet conversion: decode `LidarPointDataPacket` and build `PointCloud2` manually

The raw path exists so the repo can control point layout, timing, and ring
accumulation behavior.

## Calibration

Calibration works on recorded packet files, not live lidar streams.

The usual flow is:

1. record raw packets with `unitree_lidar_packet_recorder`
2. replay and merge the first frames into a beginning cloud
3. extract large planes
4. evaluate point-to-plane residuals
5. optimize or manually tune calibration parameters
6. inspect the result in the Pangolin viewer

There are two entrypoints:

- `unitree_lidar_packet_auto_calibrator`: plane extraction plus parameter search
- `unitree_lidar_packet_manual_calibrator`: manual parameter tuning in the same viewer

### Calibration model

The current parameterization is small and explicit:

- range coefficients: `c0`, `c1`, `c2`
- theta-to-alpha coefficients: `t0`, `t1`

Supported range models:

- `constant`
- `linear`
- `quadratic`

### Build calibration tools

```bash
bazel build //unitree_lidar_sdk:unitree_lidar_packet_auto_calibrator
bazel build //unitree_lidar_sdk:unitree_lidar_packet_manual_calibrator
```

### Record packets

```bash
bazel-bin/unitree_lidar_sdk/unitree_lidar_packet_recorder \
  --logtostderr=1 \
  --serial_port=/dev/ttyACM0 \
  --output_path=data/unitree_lidar_packets.bin \
  --max_packets=2000
```

### Run automatic calibration

```bash
bazel-bin/unitree_lidar_sdk/unitree_lidar_packet_auto_calibrator \
  --logtostderr=1 \
  --input_path=data/unitree_lidar_packets.bin \
  --accumulate_rings=50 \
  --merge_beginning_frames=100 \
  --extract_planes=true \
  --max_planes=3 \
  --plane_inlier_threshold_m=0.05 \
  --range_model_candidates=constant,linear,quadratic \
  --optimize_alpha_theta_coefficients=true
```

### Run manual calibration

```bash
bazel-bin/unitree_lidar_sdk/unitree_lidar_packet_manual_calibrator \
  --logtostderr=1 \
  --input_path=data/unitree_lidar_packets.bin \
  --accumulate_rings=50 \
  --merge_beginning_frames=100 \
  --manual_range_c0=0.0 \
  --manual_range_c1=0.0 \
  --manual_range_c2=0.0 \
  --manual_alpha_t0=0.0 \
  --manual_alpha_t1=0.0
```

## Practical notes

- the viewer needs a desktop session because it opens a Pangolin window
- plane fitting works best with large flat walls, floors, and cabinets
- the automatic optimizer helps, but manual replay tuning is still the practical fallback
