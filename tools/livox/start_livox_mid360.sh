#!/usr/bin/env bash
set -euo pipefail

# Starts the Livox ROS 2 driver for a Mid-360 and publishes its point cloud
# and IMU topics. Run tools/livox/build_livox_sdk.sh first.
#
# Env overrides:
#   ROS_DISTRO        ROS 2 distro to source if not already sourced (default: jazzy)
#   LIVOX_WS          colcon workspace built by build_livox_sdk.sh (default: ~/ws_livox)
#   LIVOX_NET_IFACE   host NIC connected to the Mid-360 (default: eth0)
#   LIVOX_LAUNCH_FILE launch_ROS2 file to run (default: msg_MID360_launch.py)

ROS_DISTRO="${ROS_DISTRO:-jazzy}"
LIVOX_WS="${LIVOX_WS:-${HOME}/ws_livox}"
LIVOX_NET_IFACE="${LIVOX_NET_IFACE:-eth0}"
LIVOX_LAUNCH_FILE="${LIVOX_LAUNCH_FILE:-msg_MID360_launch.py}"

if [[ ! -f "${LIVOX_WS}/install/setup.bash" ]]; then
  echo "no build found at ${LIVOX_WS}; run tools/livox/build_livox_sdk.sh first" >&2
  exit 1
fi

# ROS 2's generated setup.bash files reference unset variables; relax -u
# just for sourcing them.
set +u
if [[ -z "${AMENT_PREFIX_PATH:-}" ]]; then
  # shellcheck disable=SC1091
  source "/opt/ros/${ROS_DISTRO}/setup.bash"
fi
# shellcheck disable=SC1091
source "${LIVOX_WS}/install/setup.bash"
set -u

if ! ip -4 -o addr show dev "${LIVOX_NET_IFACE}" 2>/dev/null | grep -q "inet "; then
  echo "no IPv4 address on ${LIVOX_NET_IFACE}." >&2
  echo "The Mid-360 needs the host on the same subnet as the host_net_info" >&2
  echo "entry in livox_ros_driver2/config/MID360_config.json — check the cable" >&2
  echo "and the ${LIVOX_NET_IFACE} network config, then retry." >&2
  exit 1
fi

export LD_LIBRARY_PATH="${LD_LIBRARY_PATH:-}:/usr/local/lib"

echo "Launching livox_ros_driver2 (${LIVOX_LAUNCH_FILE}) on ${LIVOX_NET_IFACE}..."
exec ros2 launch livox_ros_driver2 "${LIVOX_LAUNCH_FILE}"
