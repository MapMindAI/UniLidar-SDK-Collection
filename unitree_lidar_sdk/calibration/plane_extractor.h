// Copyright 2026 MapMindAI Inc. All rights reserved.

#ifndef UNITREE_LIDAR_SDK_PLANE_EXTRACTOR_H_
#define UNITREE_LIDAR_SDK_PLANE_EXTRACTOR_H_

#include <vector>

#include <Eigen/Core>

#include "unitree_lidar_sdk/calibration/replayer_common.h"

namespace calibration {

struct PlaneExtractionConfig {
  bool enabled = true;
  int max_planes = 4;
  double inlier_threshold_m = 0.05;
  int ransac_iterations = 600;
  int min_inliers = 400;
  int detection_sample_limit = 25000;
  double min_extent_m = 0.75;
};

struct PlaneModel {
  int id = -1;
  Eigen::Vector3f normal = Eigen::Vector3f::UnitZ();
  float d = 0.0f;
  Eigen::Vector3f centroid = Eigen::Vector3f::Zero();
  Eigen::Vector3f axis_u = Eigen::Vector3f::UnitX();
  Eigen::Vector3f axis_v = Eigen::Vector3f::UnitY();
  Eigen::Vector2f uv_min = Eigen::Vector2f::Zero();
  Eigen::Vector2f uv_max = Eigen::Vector2f::Zero();
  Eigen::Vector3f color = Eigen::Vector3f::Ones();
  std::vector<int> point_indices;
  double mean_abs_residual_m = 0.0;
  double rms_residual_m = 0.0;
};

std::vector<PlaneModel> DetectPlanes(const ReplayFrame& merged_frame,
                                     const PlaneExtractionConfig& config);
void LogPlaneSummary(const std::vector<PlaneModel>& planes);

}  // namespace calibration

#endif  // UNITREE_LIDAR_SDK_PLANE_EXTRACTOR_H_
