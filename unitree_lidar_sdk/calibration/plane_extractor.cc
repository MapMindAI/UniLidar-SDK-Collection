// Copyright 2026 MapMindAI Inc. All rights reserved.

#include "unitree_lidar_sdk/calibration/plane_extractor.h"

#include <algorithm>
#include <cmath>
#include <limits>
#include <numeric>
#include <optional>
#include <random>

#include <Eigen/Eigenvalues>
#include <glog/logging.h>

namespace dm::third_party {
namespace {

std::vector<Eigen::Vector3f> ExtractPositions(const std::vector<CloudPoint>& points) {
  std::vector<Eigen::Vector3f> positions;
  positions.reserve(points.size());
  for (const CloudPoint& point : points) {
    positions.push_back(point.xyz);
  }
  return positions;
}

std::vector<int> SampleIndices(int count, int max_count) {
  std::vector<int> indices(count);
  std::iota(indices.begin(), indices.end(), 0);
  if (count <= max_count) {
    return indices;
  }
  std::mt19937 rng(0x5EED1234);
  std::shuffle(indices.begin(), indices.end(), rng);
  indices.resize(max_count);
  return indices;
}

std::optional<PlaneModel> FitPlaneFromIndices(const std::vector<Eigen::Vector3f>& points,
                                              const std::vector<int>& indices, int plane_id,
                                              int max_planes) {
  if (indices.size() < 3) {
    return std::nullopt;
  }

  Eigen::Vector3f centroid = Eigen::Vector3f::Zero();
  for (int index : indices) {
    centroid += points[index];
  }
  centroid /= static_cast<float>(indices.size());

  Eigen::Matrix3f covariance = Eigen::Matrix3f::Zero();
  for (int index : indices) {
    const Eigen::Vector3f delta = points[index] - centroid;
    covariance += delta * delta.transpose();
  }

  const Eigen::SelfAdjointEigenSolver<Eigen::Matrix3f> solver(covariance);
  if (solver.info() != Eigen::Success) {
    return std::nullopt;
  }

  PlaneModel plane;
  plane.id = plane_id;
  plane.normal = solver.eigenvectors().col(0).normalized();
  plane.centroid = centroid;
  plane.d = -plane.normal.dot(centroid);
  plane.axis_u = solver.eigenvectors().col(2).normalized();
  plane.axis_v = solver.eigenvectors().col(1).normalized();
  plane.color = ColorForRing(plane_id, std::max(1, max_planes));
  plane.point_indices = indices;

  plane.uv_min = Eigen::Vector2f::Constant(std::numeric_limits<float>::infinity());
  plane.uv_max = Eigen::Vector2f::Constant(-std::numeric_limits<float>::infinity());
  double sum_abs = 0.0;
  double sum_sq = 0.0;
  for (int index : indices) {
    const Eigen::Vector3f delta = points[index] - centroid;
    const Eigen::Vector2f uv(delta.dot(plane.axis_u), delta.dot(plane.axis_v));
    plane.uv_min = plane.uv_min.cwiseMin(uv);
    plane.uv_max = plane.uv_max.cwiseMax(uv);
    const double residual = std::abs(plane.normal.dot(points[index]) + plane.d);
    sum_abs += residual;
    sum_sq += residual * residual;
  }
  plane.mean_abs_residual_m = sum_abs / static_cast<double>(indices.size());
  plane.rms_residual_m = std::sqrt(sum_sq / static_cast<double>(indices.size()));
  return plane;
}

}  // namespace

std::vector<PlaneModel> DetectPlanes(const ReplayFrame& merged_frame,
                                     const PlaneExtractionConfig& config) {
  std::vector<PlaneModel> planes;
  if (!config.enabled || merged_frame.points.size() < 3) {
    return planes;
  }

  const std::vector<Eigen::Vector3f> points = ExtractPositions(merged_frame.points);
  std::vector<int> active_indices =
      SampleIndices(static_cast<int>(points.size()), std::max(3, config.detection_sample_limit));
  std::mt19937 rng(0xC0FFEE);

  for (int plane_id = 0; plane_id < config.max_planes; ++plane_id) {
    if (active_indices.size() < static_cast<size_t>(std::max(3, config.min_inliers))) {
      break;
    }

    int best_inlier_count = 0;
    std::vector<int> best_inliers;

    std::uniform_int_distribution<int> pick(0, static_cast<int>(active_indices.size()) - 1);
    for (int iteration = 0; iteration < config.ransac_iterations; ++iteration) {
      const int idx0 = active_indices[pick(rng)];
      const int idx1 = active_indices[pick(rng)];
      const int idx2 = active_indices[pick(rng)];
      if (idx0 == idx1 || idx0 == idx2 || idx1 == idx2) {
        continue;
      }

      const Eigen::Vector3f p0 = points[idx0];
      const Eigen::Vector3f p1 = points[idx1];
      const Eigen::Vector3f p2 = points[idx2];
      const Eigen::Vector3f normal = (p1 - p0).cross(p2 - p0);
      const float norm = normal.norm();
      if (norm < 1e-4f) {
        continue;
      }

      const Eigen::Vector3f unit_normal = normal / norm;
      const float d = -unit_normal.dot(p0);

      std::vector<int> inliers;
      inliers.reserve(active_indices.size());
      for (int point_index : active_indices) {
        const float residual = std::abs(unit_normal.dot(points[point_index]) + d);
        if (residual <= config.inlier_threshold_m) {
          inliers.push_back(point_index);
        }
      }
      if (static_cast<int>(inliers.size()) > best_inlier_count) {
        best_inlier_count = static_cast<int>(inliers.size());
        best_inliers = std::move(inliers);
      }
    }

    if (best_inlier_count < config.min_inliers) {
      break;
    }

    std::optional<PlaneModel> refined_plane =
        FitPlaneFromIndices(points, best_inliers, plane_id, config.max_planes);
    if (!refined_plane.has_value()) {
      break;
    }

    std::vector<int> refined_inliers;
    refined_inliers.reserve(active_indices.size());
    for (int point_index : active_indices) {
      const float residual =
          std::abs(refined_plane->normal.dot(points[point_index]) + refined_plane->d);
      if (residual <= config.inlier_threshold_m) {
        refined_inliers.push_back(point_index);
      }
    }
    refined_plane = FitPlaneFromIndices(points, refined_inliers, plane_id, config.max_planes);
    if (!refined_plane.has_value()) {
      break;
    }

    const Eigen::Vector2f extent = refined_plane->uv_max - refined_plane->uv_min;
    if (extent.x() < config.min_extent_m || extent.y() < config.min_extent_m) {
      break;
    }

    planes.push_back(*refined_plane);

    std::vector<int> next_active;
    next_active.reserve(active_indices.size());
    std::vector<bool> is_inlier(points.size(), false);
    for (int point_index : refined_plane->point_indices) {
      is_inlier[point_index] = true;
    }
    for (int point_index : active_indices) {
      if (!is_inlier[point_index]) {
        next_active.push_back(point_index);
      }
    }
    active_indices = std::move(next_active);
  }

  return planes;
}

void LogPlaneSummary(const std::vector<PlaneModel>& planes) {
  LOG(INFO) << "Extracted " << planes.size() << " planes.";
  for (const PlaneModel& plane : planes) {
    const Eigen::Vector2f extent = plane.uv_max - plane.uv_min;
    LOG(INFO) << "Plane[" << plane.id << "] inliers=" << plane.point_indices.size()
              << " normal=[" << plane.normal.transpose() << "]"
              << " extent=[" << extent.transpose() << "]"
              << " mean_abs=" << plane.mean_abs_residual_m
              << " rms=" << plane.rms_residual_m;
  }
}

}  // namespace dm::third_party
