# Docker Compose Stack, Remote Web Server, and Logs

Three layers run on the collection device:

1. **The compose stack** — the actual data-collection containers (lidar SDK,
   recorder, RTK, camera).
2. **`webserver.py`** — a small browser UI + JSON API that starts/stops that
   stack and tails its container logs.
3. **`unilidar-web.service`** — a systemd unit that keeps `webserver.py`
   itself running across reboots.

---

## Compose stack — `unilidar_collection.compose.yml`

[`docker_compose/unilidar_mapping/unilidar_collection.compose.yml`](../docker_compose/unilidar_mapping/unilidar_collection.compose.yml)

| Service | Container name | Image | Purpose |
|---|---|---|---|
| `unilidar_sdk` | `UniLidarSdk` | `yeliudm/arm64-ros2humble-opencv4.8.1` | Runs the checked-in `unitree_lidar_rosnode` binary, publishes `/unilidar/imu`, `/unilidar/cloud` |
| `recorder` | `Recorder` | `yeliudm/arm64-ros2humble-opencv4.8.1` | `ros2 bag record` of the lidar/RTK/depth-camera topics into `data/rosbags/` |
| `rtk_publisher` | `RtkPublisher` | `yeliudm/arm64-ros2humble-opencv4.8.1-rtk` | Runs `tools/rtk/rtk_ros_publisher.py`, publishes `/rtk/fix` |
| `camera_publisher` | `CameraPublisher` | `yeliudm/arm64-ros2humble-opencv4.8.1` | Runs `tools/camera/camera_ros_publisher.py`, publishes the USB camera's `CompressedImage` topic |

All four run `privileged: true` with `network_mode/ipc/pid: host` and mount
`/dev` — ROS 2 DDS discovery needs host networking, and the lidar/RTK/camera
each need direct device access. Each service's command waits for the system
clock to pass a fixed sanity timestamp before starting (the RK3566 board has
no RTC-backed clock at boot, so a container can otherwise start with a clock
years in the past, which breaks ROS timestamps).

`docker_compose/unitree_lidar_sdk/unitree_lidar_rosnode` is a **checked-in
prebuilt arm64 binary**, not built from source when the stack starts — see
`AGENTS.md` §2 if you're changing `unitree_lidar_rosnode.cc`.

`rtk_publisher` and `camera_publisher` are configured entirely through
`environment:` vars with `${VAR:-default}` compose substitution — see
[`doc/README_RTK.md`](README_RTK.md) and [`doc/README_CAMERA.md`](README_CAMERA.md)
for what each one does.

### Start / stop

[`arm64_start_unilidar.sh`](../docker_compose/unilidar_mapping/arm64_start_unilidar.sh) /
[`arm64_stop_unilidar.sh`](../docker_compose/unilidar_mapping/arm64_stop_unilidar.sh)
take an optional compose name (default `unilidar_collection`):

```bash
docker_compose/unilidar_mapping/arm64_start_unilidar.sh
docker_compose/unilidar_mapping/arm64_stop_unilidar.sh
```

`arm64_start_unilidar.sh` also: sources `/etc/unilidar/rtk.env` if present
(so RTK/camera env vars are picked up), `chmod 777`s the RTK serial port if
it exists, runs `tools/set_cpu_freq_max.sh`, then
`docker compose up -d --force-recreate`.

| Env var | Default | Meaning |
|---|---|---|
| `COMPOSE_PROJECT_NAME` | `unilidar` | Compose project name (`-p`) |
| `COMPOSE_FILE_PATH` | `<repo>/docker_compose/unilidar_mapping/<name>.compose.yml` | Compose file to use |
| `RTK_ENV_FILE` | `/etc/unilidar/rtk.env` | Sourced before `up` if it exists |

---

## Remote web server — `webserver.py`

[`docker_compose/unilidar_mapping/webserver.py`](../docker_compose/unilidar_mapping/webserver.py)
is a dependency-free `http.server`-based app: a browser UI plus the JSON API
backing it.

```bash
python3 docker_compose/unilidar_mapping/webserver.py
# or
docker_compose/unilidar_mapping/start_webserver.sh
```

| Env var | Default | Meaning |
|---|---|---|
| `UNILIDAR_WEB_HOST` | `0.0.0.0` | Bind address |
| `UNILIDAR_WEB_PORT` | `8080` | Bind port |
| `UNILIDAR_COMPOSE_NAME` | `unilidar_collection` | Compose file basename to control |
| `UNILIDAR_CONTAINER_NAME` | `UniLidarSdk` | Container `/api/status` reports on |
| `UNILIDAR_START_SCRIPT` / `UNILIDAR_STOP_SCRIPT` | `arm64_start_unilidar.sh` / `arm64_stop_unilidar.sh` | Scripts run by the Start/Stop buttons |
| `UNILIDAR_COPY_SCRIPT` | `tools/copy_to_drive.sh` | Script run by the Copy to Drive tool |
| `UNILIDAR_CHECK_CPU_FREQ_SCRIPT` / `UNILIDAR_SET_CPU_FREQ_MAX_SCRIPT` | `tools/check_current_cpu_freq.sh` / `tools/set_cpu_freq_max.sh` | Scripts run by the CPU Freq tools |

### UI

Open `http://<device-ip>:8080/`.

| Section | Controls |
|---|---|
| **Header** | Running/Stopped status pill, container and compose file info |
| **Start / Stop** | Launch or stop the compose stack |
| **Logs** | Live log tabs: `UniLidarSdk`, `Recorder`, `RtkPublisher`, `CameraPublisher` |
| **Tools** | Copy to Drive · List Topics · Check CPU Freq · Set CPU Max — shared output pane |
| **Settings** (collapsed) | Calibration parameters (`alpha_bais_bias`, `range_fix_a0`, `range_fix_a1`) saved into the compose file (restart the stack to apply), and the optional recorder bag name postfix |

Status and logs auto-refresh (every 3s / 2s respectively) while the page is
open. The log pane only auto-scrolls when it is already at the bottom, so
scrolling up to read older lines isn't interrupted by the refresh.

### JSON API

| Method | Path | Does |
|---|---|---|
| GET | `/api/status` | `{running, container_name, compose_file, docker_available}` |
| GET | `/api/logs?tail=N&container=NAME` | `docker logs --tail=N <container>` for **any** container name, not just the four UI tabs |
| GET | `/api/params` | Current `alpha_bais_bias`/`range_fix_a0`/`range_fix_a1` from the compose file |
| GET | `/api/bag_suffix` | Current recorder bag name postfix |
| POST | `/api/start`, `/api/stop` | Run the start/stop script |
| POST | `/api/copy` | Run `tools/copy_to_drive.sh` |
| POST | `/api/topics` | `ros2 topic list` inside `UniLidarSdk` |
| POST | `/api/cpu_freq`, `/api/cpu_freq_max` | Run the CPU-freq check/set scripts |
| POST | `/api/params`, `/api/bag_suffix` | Write the JSON body's values back into the compose file |

```bash
curl "http://<device-ip>:8080/api/logs?tail=200&container=CameraPublisher"
curl -X POST "http://<device-ip>:8080/api/start"
```

---

## Viewing logs

- **Web UI**: pick a container under Start / Stop / Logs.
- **Direct**: `docker logs -f UniLidarSdk` (or `Recorder` / `RtkPublisher` / `CameraPublisher`).
- **The webserver process itself**, when running under systemd (below):
  `sudo journalctl -u unilidar-web.service -f`.

---

## Run the web server at boot — `unilidar-web.service`

[`docker_compose/boot_app/enable_unilidar_web_boot.sh`](../docker_compose/boot_app/enable_unilidar_web_boot.sh)
generates and installs the systemd unit with the current repo path and
invoking user baked in — **rerun it** after moving or recloning the repo.

```bash
sudo bash docker_compose/boot_app/enable_unilidar_web_boot.sh
```

This writes:

- `/etc/systemd/system/unilidar-web.service` — `ExecStart`s `webserver.py`
  from this checkout, `EnvironmentFile=-/etc/unilidar/rtk.env` (the leading
  `-` means systemd won't fail to start if the file is missing), `Restart=always`
- `/etc/unilidar/rtk.env`, only if it doesn't already exist — the RTK/camera
  env vars consumed by both the boot service and `arm64_start_unilidar.sh`

Then runs `systemctl daemon-reload`, `enable`, and `restart` on the unit.

```bash
sudo systemctl status unilidar-web.service
sudo journalctl -u unilidar-web.service -b
```

[`docker_compose/boot_app/unilidar-web.service`](../docker_compose/boot_app/unilidar-web.service)
is an example unit checked in for reference only — it has a hardcoded path
from whoever last generated it; don't install it by hand.
