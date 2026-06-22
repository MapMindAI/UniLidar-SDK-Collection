# Unitree LiDAR Calibration

This document describes the offline calibration workflow under
[`unitree_lidar_sdk/calibration/`](./calibration/).

The calibration tools work on recorded raw packet files instead of live lidar
streams. This makes it easier to test different correction models, inspect
merged point clouds, extract planes, and compare residuals repeatably.

## Overview

The current workflow is:

1. Record raw `LidarPointDataPacket` packets with
   [`unitree_lidar_packet_recorder`](./unitree_lidar_packet_recorder.cc).
2. Decode packets into replay frames and a merged beginning cloud.
3. Extract large planes from the merged cloud with some inlier tolerance.
4. Measure point-to-plane residuals.
5. Optimize or manually tune calibration parameters.
6. Visualize the result in Pangolin.

There are two calibration entrypoints:

- [`unitree_lidar_packet_auto_calibrator`](./unitree_lidar_packet_auto_calibrator.cc):
  runs plane extraction, evaluates residuals, searches calibration parameters,
  then opens the viewer.
- [`unitree_lidar_packet_manual_calibrator`](./unitree_lidar_packet_manual_calibrator.cc):
  skips the optimizer and starts from user-provided parameters so you can inspect
  the merged cloud directly.

## Code Structure

The calibration code is split into small libraries under
[`unitree_lidar_sdk/calibration/`](./calibration/), built by
[`unitree_lidar_sdk/calibration/BUILD`](./calibration/BUILD):

- [`replayer_common.h`](./calibration/replayer_common.h) and
  [`replayer_common.cc`](./calibration/replayer_common.cc):
  packet loading, packet-to-sample decode, replay frame construction, merged
  cloud construction, and point rebuild from calibration.
- [`plane_extractor.h`](./calibration/plane_extractor.h) and
  [`plane_extractor.cc`](./calibration/plane_extractor.cc):
  plane detection and plane summary utilities.
- [`calibration_optimizer.h`](./calibration/calibration_optimizer.h) and
  [`calibration_optimizer.cc`](./calibration/calibration_optimizer.cc):
  calibration parameter model, residual evaluation, and automatic search.
- [`replayer_viewer.h`](./calibration/replayer_viewer.h) and
  [`replayer_viewer.cc`](./calibration/replayer_viewer.cc):
  Pangolin viewer for replay frames, merged cloud, and extracted planes.

## Calibration Model

Each point starts from the vendor packet geometry and is then adjusted by a
simple calibration model:

- range correction: `delta_range_alpha_fcn(alpha)`
- alpha correction: `delta_alpha_theta_fcn(theta)`

The current parameterization exposed by the optimizer and manual viewer is:

- range coefficients: `c0`, `c1`, `c2`
- theta-to-alpha coefficients: `t0`, `t1`

The supported range model families are:

- `constant`: `c0`
- `linear`: `c0 + c1 * alpha`
- `quadratic`: `c0 + c1 * alpha + c2 * alpha^2`

The theta-dependent alpha correction is a simple linear model:

- `t0 + t1 * theta`

These parameters are stored in
[`CalibrationParameters`](./calibration/calibration_optimizer.h) and converted
to a `UniLidarCalibration` instance before rebuilding the point cloud.

## Plane-Based Optimization

The automatic calibrator uses the merged beginning cloud as the optimization
target.

### Step 1: Plane extraction

The tool runs RANSAC on the merged cloud and extracts up to `--max_planes`
planes.

Relevant flags:

- `--extract_planes=true|false`
- `--max_planes=<N>`
- `--plane_inlier_threshold_m=<meters>`
- `--plane_ransac_iterations=<N>`
- `--plane_min_inliers=<N>`
- `--plane_detection_sample_limit=<N>`
- `--plane_min_extent_m=<meters>`

### Step 2: Residual evaluation

For each point in the merged cloud, the tool finds the nearest extracted plane
within `--calibration_assignment_threshold_m` and computes point-to-plane error.

The logged summary includes:

- assigned point count
- mean absolute residual
- RMS residual
- maximum absolute residual

### Step 3: Parameter search

The optimizer tests one or more range model families and adjusts the active
coefficients with coordinate descent.

Relevant flags:

- `--optimize_calibration=true|false`
- `--range_model_candidates=constant,linear,quadratic`
- `--calibration_iterations=<N>`
- `--calibration_range_step_m=<meters>`
- `--optimize_range_coefficients=true|false`
- `--calibration_alpha_step_rad=<radians>`
- `--optimize_alpha_theta_coefficients=true|false`
- `--calibration_regularization=<lambda>`
- `--calibration_assignment_threshold_m=<meters>`

The selected model and coefficients are printed to the log before the viewer
opens.

## Viewer

Both calibrators use the same Pangolin viewer.

The viewer shows:

- current replay frame points
- merged beginning cloud
- extracted plane rectangles and normals
- plane inlier points

Useful viewer toggles include:

- `Play`, `Prev`, `Next`, `Reset`, `Loop`
- `Show Merged`
- `Show Planes`
- `Show Plane Pts`
- `Point Size`
- `Merged Pt Size`

The merged cloud is useful for checking whether the plane surfaces become
tighter after calibration.

## Build

Build the calibration tools with Bazel:

```bash
bazel build //unitree_lidar_sdk:unitree_lidar_packet_auto_calibrator
bazel build //unitree_lidar_sdk:unitree_lidar_packet_manual_calibrator
```

## Record Data

Record a packet file first:

```bash
bazel-bin/unitree_lidar_sdk/unitree_lidar_packet_recorder \
  --logtostderr=1 \
  --serial_port=/dev/ttyACM0 \
  --output_path=data/unitree_lidar_packets.bin \
  --max_packets=2000
```

## Run Automatic Calibration

Example:

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

This will:

1. load packets
2. build replay frames
3. merge the first `N` frames
4. extract planes
5. print baseline residuals
6. search calibration parameters
7. rebuild the point clouds with the selected parameters
8. open the viewer

## Run Manual Calibration

Example:

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

This path is useful when:

- the optimizer gets trapped in a local minimum
- you want to inspect how each parameter changes wall or floor sharpness
- you want to compare manual hypotheses against the automatic result

## Practical Notes

- The calibration tools require a recorded packet file, not a live stream.
- The viewer needs a desktop session because it opens a Pangolin GUI window.
- Plane-based optimization works best when the merged beginning frames contain
  several large, stable planar surfaces such as walls, floor, or cabinet faces.
- If residual assignment is low, increase `--merge_beginning_frames`, collect a
  cleaner scene, or loosen `--plane_inlier_threshold_m` and
  `--calibration_assignment_threshold_m`.
- If the optimization result is unstable, start from manual inspection first and
  narrow the parameter ranges before rerunning the auto calibrator.
