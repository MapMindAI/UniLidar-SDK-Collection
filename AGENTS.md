Mandatory rules for AI coding agents contributing to this repo. Direct user instructions win — flag the conflict when they do.

## Repository layout

UniLidar SDK Collection packages the Unitree L2 lidar SDK, an RTK GNSS
pipeline, USB camera tooling, and a Docker/systemd deployment for an
RK3566-based mapping data collector.

```
├── unitree_lidar_sdk/                 # Vendor Unitree lidar SDK (Bazel, C++17)
│   ├── include/, lib/{aarch64,x86_64}/    # vendor headers + prebuilt static libs
│   ├── examples/                      # example_lidar_serial.cpp, example_lidar_udp.cpp, ...
│   ├── calibration/                   # offline extrinsic calibration: plane_extractor,
│   │                                   # calibration_optimizer, replayer_viewer (Pangolin)
│   ├── unitree_lidar_rosnode.cc       # ROS 2 bridge: publishes /unilidar/imu, /unilidar/cloud
│   └── README_calibrate.md            # calibration workflow, current known issues
├── tools/                             # standalone Python/shell scripts, no package structure
│   ├── rtk/                           # rtk_ros_publisher.py (NTRIP+NMEA -> NavSatFix), rtk_test.py,
│   │                                   # bag_to_rtk_txt.py
│   ├── camera/                        # camera_ros_publisher.py, camera_ros_viewer.py, list_usb_cameras.py
│   │   └── calibration/               # AprilGrid board generator + Double Sphere intrinsics calibrator
│   ├── setup_unilidar_sudo.sh, set_cpu_freq_max.sh, check_current_cpu_freq.sh, copy_to_drive.sh
├── docker_compose/
│   ├── unilidar_mapping/               # compose file, start/stop scripts, webserver.py (remote control UI)
│   ├── unitree_lidar_sdk/              # CHECKED-IN prebuilt arm64 unitree_lidar_rosnode binary
│   └── boot_app/                       # systemd unit + installer for boot-time web service
├── web/                                # rtk_viewer.html static viewer served by webserver.py
├── third_party/                        # Bazel BUILD wrappers for system-installed deps
│                                        # (ros_humble, pangolin, gflags, glog, eigen)
├── doc/                                 # per-topic docs: README_RTK.md, README_CAMERA.md
├── assets/                              # README images/gifs
├── setup.sh                             # root one-shot installer (sudo rules, CPU governor, boot service)
└── WORKSPACE, BUILD, .bazelrc, .clang-format   # Bazel + C++ build/format config
```

No CI pipeline exists in this repo yet — see §3.

## 1. Read the docs before starting a task

| Doc | Covers |
|---|---|
| root `README.md` | Setup flow, SDK/rosnode overview, calibration highlight, remote web control, RTK pointer |
| `doc/README_RTK.md` | WTRTK-960H hardware specs, RTK fix states, NTRIP/NMEA background |
| `doc/README_CAMERA.md` | Camera tooling and the AprilGrid/Double Sphere calibration workflow (fill in alongside `tools/camera/`) |
| `unitree_lidar_sdk/README_calibrate.md` | Lidar extrinsic calibration workflow, automatic vs. manual tuning, known issues |

Read whichever doc(s) cover the subsystem you're about to touch — the Bazel/ROS 2 dependency wiring and the docker-compose/systemd deployment path aren't obvious from a single file's context.

## 2. Update docs before opening a PR

Ship the doc fix with the code — not as a follow-up.

| Change | Update |
|---|---|
| RTK hardware, NTRIP/NMEA handling, or `tools/rtk/*` behavior | `doc/README_RTK.md` |
| Camera publisher/viewer or `tools/camera/calibration/*` behavior | `doc/README_CAMERA.md` |
| `unitree_lidar_sdk/calibration/*` or the extrinsic calibration workflow | `unitree_lidar_sdk/README_calibrate.md` |
| `unitree_lidar_sdk/unitree_lidar_rosnode.cc` or its Bazel deps | rebuild for arm64 and replace `docker_compose/unitree_lidar_sdk/unitree_lidar_rosnode` — the compose stack execs that checked-in binary directly, it is **not** built from source at deploy time |
| `docker_compose/unilidar_mapping/webserver.py` UI/controls, new tool buttons | root `README.md`'s "Remote Web Control" table |
| New top-level directory, new tool subdirectory | this file's repository layout tree |
| New contributor-facing rule, workflow, or convention | this file (`AGENTS.md`) |

## 3. No automated test suite — verify manually before opening a PR

This repo has no CI and no test framework wired up. That means correctness is on you, not on a check that will catch you later:

* C++ / Bazel changes: `bazel build //...` must succeed cleanly (project code builds with `-Wall -Wextra -Werror`; only `external/` and `third_party/` are warning-exempt).
* Python tool changes: `python3 -m py_compile` catches syntax errors only — it proves nothing about correctness. For anything with real logic (a projection model, a parser, a bundle adjustment), verify it actually works: run it against real or synthetic data and check the output, the way `tools/camera/calibration/calibrate_double_sphere.py` was validated against a hand-derived closed-form and a synthetic rendered-image pipeline before being shipped. Use the `/verify` skill for changes with a runtime surface to exercise.
* Anything touching `docker_compose/*` or `setup.sh`: dry-read the script path affected (which files it writes, which services it restarts) — these run as root on a real device and are not covered by any test.

## 4. Run the simplify skill before opening a PR

Once the diff is functionally complete, run `/simplify`. Apply the legitimate findings; note false positives in the PR summary.

## 5. Keep prose and comments concise

* Docs: tight prose. One sentence beats two. Cut hedges, cut narration, cut sentences that restate a heading.
* Code comments: add one only when a reader can't derive the why from the identifiers and structure. Skip comments that restate what the code does, narrate the task, or reference the PR/caller. One short line, not a docstring paragraph.
* Python tools in this repo follow an established header convention — config pulled from `os.environ.get(...)` into module-level constants at the top of the file (see `tools/rtk/rtk_ros_publisher.py`, `tools/camera/camera_ros_publisher.py`). Match it for new ROS 2 node scripts instead of inventing argparse config for things that are really per-deployment environment settings.

## 6. Destructive-action discipline

Follow the harness's default git-safety protocol (no force-push, `git reset --hard`, branch deletion, or `--no-verify` without explicit user confirmation this session). Repo-specific additions:

* Treat vendor files as read-only unless the user asks for a rewrite: `unitree_lidar_sdk/include/`, `unitree_lidar_sdk/lib/{aarch64,x86_64}/`, and the checked-in `docker_compose/unitree_lidar_sdk/unitree_lidar_rosnode` binary. They're either vendor-supplied or a build artifact — hand-editing them desyncs source from binary silently.
* `setup.sh`, `tools/set_cpu_freq_max.sh`, `tools/setup_unilidar_sudo.sh`, and `docker_compose/boot_app/enable_unilidar_web_boot.sh` write real root-owned system state (sudoers rules, CPU governor, a systemd unit) on whatever machine they run on. Never run them speculatively to "see what happens" — read them, then confirm with the user before executing.
* `docker_compose/unilidar_mapping/*.compose.yml` changes affect a stack that may be live on a deployed device; don't assume a `docker compose up -d --force-recreate` is safe to run without confirming the target.

## 7. Scope discipline

* Broad reshuffles ship separately. A drive-by within the files you're already touching is fine; a sweep across unrelated tools/directories is its own PR.
* No backwards-compatibility shims or feature flags for hypothetical callers. This codebase is small enough to change every call site in one PR.
* Keep the codebase clean as you go. When you spot duplicated logic — same env-var config header, same yaml load/save, same boilerplate block — hoist it into a shared module in the same PR if the lift is small (see `tools/camera/calibration/aprilgrid_board.py` and `double_sphere.py`, shared by the generator and the calibrator). Refactor when it makes the diff smaller and cleaner; don't refactor for its own sake.

## 8. Prefer the simplest design that solves the concrete problem

Pick the design that solves only the requirement on the table. Don't add abstraction layers, configurable knobs, extra primitives, or extension points "in case we need them later." Don't claim compatibility with an external format (e.g. Basalt's or Kalibr's exact calibration JSON schema) unless you've actually verified the field names — state clearly what parameterization you match and let the user transcribe it, rather than fabricating a schema.

When proposing or reviewing a design, drop the bullet that starts with "this also lets us…" or "leaves room for…". Two-tier mechanisms, pluggable backends, and speculative interfaces are debt: they widen the API surface, multiply test cases, and lock in assumptions that may turn out wrong.

## 9. Naming

Match the existing convention: full descriptive words for directories and new tools (`docker_compose`, `unitree_lidar_sdk`, `tools/camera/calibration`), except well-known domain acronyms already used throughout the repo (`rtk`, `ros`, `sdk`, `imu`, `gnss`, `ntrip`, `nmea`, and camera-model notation like `fx`/`fy`/`cx`/`cy`/`xi`/`alpha`). When in doubt, spell it out.
