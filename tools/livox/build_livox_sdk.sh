#!/usr/bin/env bash
set -euo pipefail

# Builds & installs Livox-SDK2, then builds the livox_ros_driver2 ROS 2
# package against it. Requires a sourced ROS 2 environment (ROS_DISTRO set).
#
# Env overrides:
#   LIVOX_WS   colcon workspace to build into (default: ~/ws_livox)

if [[ -z "${ROS_DISTRO:-}" ]]; then
  echo "ROS_DISTRO is not set; source your ROS 2 environment first, e.g.:" >&2
  echo "  source /opt/ros/jazzy/setup.bash" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
SDK_DIR="${REPO_ROOT}/Livox-SDK2"
DRIVER_DIR="${REPO_ROOT}/livox_ros_driver2"
WS_DIR="${LIVOX_WS:-${HOME}/ws_livox}"

if [[ ! -d "${SDK_DIR}/sdk_core" ]]; then
  echo "the Livox-SDK2 submodule is missing or empty; run:" >&2
  echo "  git -C ${REPO_ROOT} submodule update --init --recursive" >&2
  exit 1
fi

if [[ ! -f "${DRIVER_DIR}/package.xml" ]]; then
  echo "livox_ros_driver2 is missing at ${DRIVER_DIR}" >&2
  exit 1
fi

echo "== Building & installing Livox-SDK2 =="
cmake -S "${SDK_DIR}" -B "${SDK_DIR}/build"
cmake --build "${SDK_DIR}/build" -j"$(nproc)"
sudo cmake --install "${SDK_DIR}/build"
sudo ldconfig

if ! command -v colcon >/dev/null 2>&1; then
  echo "== Installing colcon =="
  sudo apt-get update
  sudo apt-get install -y python3-colcon-common-extensions python3-rosdep
fi

if command -v rosdep >/dev/null 2>&1; then
  echo "== Resolving livox_ros_driver2 dependencies via rosdep =="
  sudo rosdep init >/dev/null 2>&1 || true
  rosdep update
fi

echo "== Setting up colcon workspace at ${WS_DIR} =="
mkdir -p "${WS_DIR}/src"
ln -sfn "${DRIVER_DIR}" "${WS_DIR}/src/livox_ros_driver2"

if command -v rosdep >/dev/null 2>&1; then
  rosdep install --from-paths "${WS_DIR}/src" --ignore-src -r -y
fi

echo "== Building livox_ros_driver2 (${ROS_DISTRO}) =="
(cd "${WS_DIR}" && colcon build --symlink-install --packages-select livox_ros_driver2)

echo "Build complete."
echo "Before running, source: ${WS_DIR}/install/setup.bash"
