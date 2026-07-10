# USB Camera — ROS 2 Streaming and Fisheye Calibration

Tooling under [`tools/camera/`](../tools/camera) to discover a USB/V4L2
camera, stream it over ROS 2, and calibrate a very-wide-FOV fisheye lens
using the Double Sphere camera model.

---

## Discover cameras

[`tools/camera/list_usb_cameras.py`](../tools/camera/list_usb_cameras.py)
enumerates `/dev/video*`, filters to actual V4L2 capture devices, and
prints resolution, fps, supported resolutions, and USB vendor:product —
grouped by USB port so you can see which nodes share one physical port.

```bash
python3 tools/camera/list_usb_cameras.py
python3 tools/camera/list_usb_cameras.py --verbose   # debug logging
```

---

## Publish to ROS 2 — `camera_ros_publisher.py`

[`tools/camera/camera_ros_publisher.py`](../tools/camera/camera_ros_publisher.py)
opens a V4L2 camera with OpenCV and publishes JPEG-compressed frames.

| Env var | Default | Meaning |
|---|---|---|
| `CAMERA_DEVICE` | `/dev/video4` | V4L2 device path |
| `CAMERA_WIDTH` | `1280` | Capture width |
| `CAMERA_HEIGHT` | `960` | Capture height |
| `CAMERA_FPS` | `30` | Capture/publish rate |
| `CAMERA_EXPOSURE` | unset | Manual exposure value passed to V4L2/OpenCV; when unset, the publisher runs its own brightness-based auto exposure loop |
| `CAMERA_AUTO_EXPOSURE_TARGET_BRIGHTNESS` | `100.0` | Target mean grayscale brightness (0–255) for the software auto exposure loop |
| `CAMERA_AUTO_EXPOSURE_TOLERANCE` | `8.0` | No exposure change is made while mean brightness stays within this error band |
| `CAMERA_AUTO_EXPOSURE_MIN` | unset | Lower clamp for the software-selected exposure value |
| `CAMERA_AUTO_EXPOSURE_MAX` | unset | Upper clamp for the software-selected exposure value |
| `CAMERA_AUTO_EXPOSURE_INTERVAL` | `0.5` | Seconds between exposure adjustments |
| `CAMERA_AUTO_EXPOSURE_ROI_RADIUS_RATIO` | `0.45` | Radius of the center-circle metering region, as a fraction of half the smaller image dimension |
| `CAMERA_AUTO_EXPOSURE_SMOOTHING` | `0.2` | Exponential moving average factor for brightness; lower values react more slowly but oscillate less |
| `CAMERA_AUTO_EXPOSURE_MAX_SCALE_PER_STEP` | `1.25` | Maximum multiplicative exposure change applied in one adjustment step |
| `CAMERA_FRAME_ID` | `camera` | `header.frame_id` on published messages |
| `CAMERA_IMAGE_TOPIC` | `/camera/image_raw/compressed` | Output topic |
| `CAMERA_JPEG_QUALITY` | `80` | JPEG encode quality (0–100) |

```bash
source /opt/ros/humble/setup.bash
CAMERA_DEVICE=/dev/video4 CAMERA_WIDTH=1280 CAMERA_HEIGHT=960 \
CAMERA_AUTO_EXPOSURE_TARGET_BRIGHTNESS=90 \
  python3 tools/camera/camera_ros_publisher.py
```

If the image is overexposed, lower `CAMERA_AUTO_EXPOSURE_TARGET_BRIGHTNESS`, lower
`CAMERA_AUTO_EXPOSURE_MAX`, or set `CAMERA_EXPOSURE` for a fixed manual value.
The software auto exposure meters only a center circle by default so black fisheye
border pixels do not bias the image darker than it really is.
If exposure oscillates, lower `CAMERA_AUTO_EXPOSURE_SMOOTHING` or lower
`CAMERA_AUTO_EXPOSURE_MAX_SCALE_PER_STEP`.

| Topic | Type | Format |
|---|---|---|
| `/camera/image_raw/compressed` (configurable) | `sensor_msgs/msg/CompressedImage` | `jpeg` |

---

## View and save frames — `camera_ros_viewer.py`

[`tools/camera/camera_ros_viewer.py`](../tools/camera/camera_ros_viewer.py)
subscribes to the topic above, shows a live window, and can save frames to
disk — this is how you build the image set for the calibration workflow
below.

| Env var | Default | Meaning |
|---|---|---|
| `CAMERA_IMAGE_TOPIC` | `/camera/image_raw/compressed` | Topic to subscribe to |
| `CAMERA_VIEWER_WINDOW` | same as `CAMERA_IMAGE_TOPIC` | OpenCV window title |
| `CAMERA_SAVE_DIR` | `data/camera_calib` | Where saved frames go |

```bash
source /opt/ros/humble/setup.bash
python3 tools/camera/camera_ros_viewer.py
```

Keys: **`s`** saves the current frame as `frame_0000.png`, `frame_0001.png`,
... in `CAMERA_SAVE_DIR` (PNG, not JPEG, to avoid stacking a second lossy
encode on top of the topic's own JPEG compression). **`q`** quits. The
window overlays the running saved-frame count.

---

## Fisheye intrinsics calibration (Double Sphere model)

Tools under [`tools/camera/calibration/`](../tools/camera/calibration).

### Why AprilGrid, not a checkerboard

A very-wide-FOV fisheye needs calibration images where the target reaches
the extreme edges and corners of the frame — that's where the lens's
distortion parameters are actually constrained. Checkerboard corner
detection degrades badly under that much distortion and under partial
occlusion. An AprilGrid (a grid of individually-identifiable AprilTags)
detects reliably tag-by-tag even when most of the board is out of frame or
heavily warped, and each tag still contributes 4 known corners.

### Why Double Sphere, not a pinhole/Kannala-Brandt model

The Double Sphere model (Usenko, Demmel, Cremers, *"The Double Sphere
Camera Model,"* 3DV 2018 — the same `ds` camera type used by
[Basalt](https://gitlab.com/VladyslavUsenko/basalt)) has a closed-form
projection *and* unprojection and natively supports fields of view beyond
180°, which a pinhole or low-order polynomial fisheye model cannot
represent. Its 6 parameters — `fx, fy, cx, cy, xi, alpha` — can be copied
directly into a Basalt or Kalibr config that expects that parameterization
(this repo does not attempt to reproduce Basalt's exact calibration JSON
schema, only the parameter values).

### Step 1 — generate and print a calibration board

[`generate_aprilgrid.py`](../tools/camera/calibration/generate_aprilgrid.py)
writes a printable board plus the `board.yaml` the calibrator needs.

| Arg | Default | Meaning |
|---|---|---|
| `--rows` / `--cols` | `6` / `6` | Tag grid size |
| `--tag-size-mm` | `50.0` | Physical size of one printed tag |
| `--tag-spacing` | `0.3` | Gap between tags, as a fraction of tag size |
| `--margin-mm` | `15.0` | White border around the grid |
| `--dpi` | `300.0` | Print resolution |
| `--start-id` | `0` | First AprilTag id used |
| `--family` | `DICT_APRILTAG_36h11` | `cv2.aruco` dictionary |
| `--output` | `aprilgrid` | Output basename |

```bash
python3 tools/camera/calibration/generate_aprilgrid.py \
  --rows 6 --cols 6 --tag-size-mm 20 --output data/aprilgrid
```

Writes `aprilgrid.png`, `aprilgrid.pdf`, `aprilgrid.board.yaml`. **Print the
PDF at 100% / actual size** ("fit to page" will silently change the
physical tag size and throw off every downstream measurement), then mount
it on something flat and rigid.

### Step 2 — capture calibration images

Run the publisher and viewer (above) pointed at the board, and press `s`
to save 20–40+ images. For a very-wide-FOV lens, centered fronto-parallel
shots are not enough — the parts of the model that matter (`xi`, `alpha`)
are only constrained by images where the board reaches the **edges and
corners** of the frame:

- Move the board close enough, and tilted enough, that it fills a corner
  or edge of the frame in several shots, not just the center.
- Vary distance and tilt angle broadly across the set.
- A few centered/fronto-parallel shots are still useful for stability, but
  should not be the majority.

### Step 3 — run the calibrator

[`calibrate_double_sphere.py`](../tools/camera/calibration/calibrate_double_sphere.py)
detects tags with OpenCV's `aruco` AprilTag detector, bootstraps a pose per
image, then jointly refines intrinsics + poses with a sparse bundle
adjustment (`scipy.optimize.least_squares`), rejecting outlier corners and
refitting once.

| Arg | Default | Meaning |
|---|---|---|
| `--images-dir` | *(required)* | Directory of saved calibration images |
| `--board` | *(required)* | `board.yaml` from step 1 |
| `--output` | `<images-dir>/calibration.yaml` | Output path |
| `--min-tags` | `4` | Minimum tags detected to keep an image |
| `--reject-px` | `5.0` | Outlier rejection threshold, pixels |
| `--hfov-deg` | `190.0` | Rough horizontal FOV, for the initial focal-length guess |
| `--visualize` | off | Show detections per image while running |

```bash
python3 tools/camera/calibration/calibrate_double_sphere.py \
  --images-dir data/camera_calib \
  --board data/aprilgrid.board.yaml \
  --hfov-deg 190
```

It prints per-image tag counts, overall reprojection RMSE, and the worst
5 views by RMSE — recapture or delete any view that stands out and rerun
if the overall RMSE looks too high for your lens. The output yaml:

```yaml
model: double_sphere
image_width: 1280
image_height: 960
fx: ...
fy: ...
cx: ...
cy: ...
xi: ...
alpha: ...
overall_rmse_px: ...
num_views_used: ...
num_views_total: ...
```

`fx/fy/cx/cy/xi/alpha` are the Double Sphere parameters described above —
copy them into any downstream config (Basalt, Kalibr, or a custom
projection) that expects that model.

### Step 4 — verify with the undistorted live viewer

[`undistort_viewer.py`](../tools/camera/calibration/undistort_viewer.py)
loads `calibration.yaml`, subscribes to the live topic, and shows a
rectified (virtual-pinhole) view — straight lines in the scene should look
straight. This is the quickest sanity check that a calibration is actually
good, before trusting it downstream.

| Env var | Default | Meaning |
|---|---|---|
| `CAMERA_IMAGE_TOPIC` | `/camera/image_raw/compressed` | Topic to subscribe to |
| `CAMERA_VIEWER_WINDOW` | `undistorted` | OpenCV window title |
| `CAMERA_CALIBRATION_YAML` | `calibration.yaml` | Path written by step 3 |
| `CAMERA_UNDISTORT_FOV_DEG` | `120` | Horizontal FOV of the virtual pinhole output |

```bash
source /opt/ros/humble/setup.bash
CAMERA_CALIBRATION_YAML=data/camera_calib/calibration.yaml \
  python3 tools/camera/calibration/undistort_viewer.py
```

A rectilinear (pinhole) image can't represent a full fisheye FOV — as
`CAMERA_UNDISTORT_FOV_DEG` grows, pixels near the edges of the *output*
window correspond to source pixels further and further out, until they run
off the edge of the actual captured frame and render black. That's
expected, not a bug; lower the FOV to trade width for less border, or
accept the black border as the honest edge of what a pinhole re-projection
can show. The incoming frame size must match `calibration.yaml`'s
`image_width`/`image_height` — the viewer logs a warning and skips frames
that don't.

### Notes on the bearing-vector pose bootstrap

A camera with FOV over 180° breaks `cv2.solvePnP`'s usual pinhole
assumption (it needs every point in front of the camera, `z > 0`), so
`calibrate_double_sphere.py` bootstraps each image's pose from a planar
homography fit directly on unprojected 3D bearing vectors instead — this
works regardless of FOV since it never divides by a ray's `z` component.
Both the Double Sphere projection/unprojection round-trip and this pose
bootstrap were validated against synthetic ground truth (closed-form
unprojection, and a rendered-image pipeline through a known camera) before
being relied on here.
