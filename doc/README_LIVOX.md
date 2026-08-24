# Livox Mid-360

Vendor SDK and ROS 2 driver for a Livox Mid-360 lidar, in addition to the
Unitree L2 stack. `Livox-SDK2/` is still a vendor git submodule — treat its
source as read-only. `livox_ros_driver2/` is vendored **in-tree** (forked from
upstream `4a1def9`) and is ours to edit: the ROS 1 half, the `build.sh` that
regenerated `package.xml`/`launch/` at build time, and the launch/config files
for other lidar models were dropped, leaving a plain ROS 2 colcon package with
a real `package.xml` and `launch/`.

## Network prerequisite

The Mid-360 connects over Ethernet with a persisted static IP (survives
power cycles). The host NIC (default `eth0`) must have a static IPv4 address
matching the `host_net_info` entry in
`livox_ros_driver2/config/MID360_config.json`, on the lidar's subnet.

If `eth0` sits at "connecting (getting IP configuration)" in `nmcli device
status`, it means the interface is on DHCP and the Mid-360 isn't serving
one — set a static IP instead. To find the lidar's actual IP/expected host
IP (they're device-specific, not always the vendor default
`192.168.1.100`/`192.168.1.5`), plug in, then on the host run:

```bash
sudo tcpdump -i eth0 -n
```

The lidar broadcasts ARP/PTP/point-data traffic revealing its own IP and the
host IP it expects (e.g. `<lidar_ip>.<port> > <expected_host_ip>.<port>`).
Set the host NIC to that expected IP via `nmcli connection modify <conn>
ipv4.method manual ipv4.addresses <expected_host_ip>/24`, and update
`MID360_config.json`'s `host_net_info`/`lidar_configs` to match — the
deployed RK3588 in this repo's history used `192.168.123.161` (host) /
`192.168.123.120` (lidar), not the vendor defaults.

## Build

```bash
source /opt/ros/jazzy/setup.bash
tools/livox/build_livox_sdk.sh
```

This builds and `sudo make install`s Livox-SDK2 into `/usr/local`, then
`colcon build --symlink-install`s `livox_ros_driver2` into a workspace at
`~/ws_livox` (override with `LIVOX_WS`). Re-run after pulling SDK submodule
updates or editing the driver's C++ sources; `config/` and `launch/` edits are
symlinked into the install and take effect on the next start.

## Run

```bash
tools/livox/start_livox_mid360.sh
```

Sources the workspace, checks the NIC has an IP, and runs
`ros2 launch livox_ros_driver2 msg_MID360_launch.py`, which publishes the
Mid-360's point cloud on `/livox/lidar` as `sensor_msgs/PointCloud2` and its
IMU on `/livox/imu` as `sensor_msgs/Imu`. Set `LIVOX_LAUNCH_FILE` to
`rviz_MID360_launch.py` to bring up rviz2 alongside the driver.

The cloud carries the driver's packed 26-byte point: `x`, `y`, `z`,
`intensity` (float32), `tag`, `line` (uint8), and a float64 `timestamp` that
is the point's nanosecond offset within the message, not an absolute time.
Both launch files set `xfer_format = 0` in
`livox_ros_driver2/launch/`; set it to `1` for the legacy
`livox_ros_driver2/msg/CustomMsg` format, which is still built and available.

## Config

Edit `livox_ros_driver2/config/MID360_config.json` for this deployment's
host IP and the lidar's IP — see the field reference in
`livox_ros_driver2/README.md` §4.

## Recording and downloading bags

The `/mid360` remote web control page (see `doc/RemoteWebControl/README.md`)
records `ros2 bag` sessions to `data/rosbags_mid360/` on the device. From a
dev machine, pull them off and delete them from the device with:

```bash
REMOTE_HOST=<user>@<device-ip> tools/fetch_rosbags.sh
```
