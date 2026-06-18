// Copyright 2026 MapMindAI Inc. All rights reserved.

#ifndef UNITREE_LIDAR_SDK_REPLAYER_VIEWER_H_
#define UNITREE_LIDAR_SDK_REPLAYER_VIEWER_H_

#include <vector>

#include <pangolin/pangolin.h>
#include "unitree_lidar_sdk/calibration/calibration_optimizer.h"
#include "unitree_lidar_sdk/calibration/plane_extractor.h"
#include "unitree_lidar_sdk/calibration/replayer_common.h"

namespace pangolin {

struct OrthographicHandler3D : Handler3D {
  OrthographicHandler3D(OpenGlRenderState* cam_state, AxisDirection enforce_up = AxisNone,
                        float trans_scale = 0.01f, float zoom_fraction = PANGO_DFLT_HANDLER3D_ZF,
                        GLprecision initial_extent = 50)
      : Handler3D((*cam_state), enforce_up, trans_scale, zoom_fraction), current(initial_extent) {}

  GLprecision current = 50;

  void Mouse(View& display, MouseButton button, int x, int y, bool pressed,  // NOLINT
             int button_state) override {                                    // NOLINT
    last_pos[0] = static_cast<float>(x);
    last_pos[1] = static_cast<float>(y);
    funcKeyState = 0;
    if (pressed) {
      GetPosNormal(display, x, y, p, Pw, Pc, n, last_z);
      if (ValidWinDepth(p[2])) {
        last_z = p[2];
        std::copy(Pc, Pc + 3, rot_center);
      }
      if (button == MouseWheelUp || button == MouseWheelDown) {
        const GLprecision change = (button == MouseWheelUp ? 1 : -1) * 50 * tf;
        current -= change * std::pow(std::log(std::abs(current) + 1), 2);
        current = std::max<GLprecision>(1e-3, current);
        cam_state->SetProjectionMatrix(pangolin::ProjectionMatrixOrthographic(
            -current, current, -current, current, -5000, 5000));
        return;
      }
      funcKeyState = button_state;
    }

    Handler3D::Mouse(display, button, x, y, pressed, button_state);
  }
};

}  // namespace pangolin

namespace calibration {

struct ViewerConfig {
  int window_width = 1600;
  int window_height = 900;
  double play_hz = 5.0;
  double point_size = 2.0;
  double merged_point_size = 1.0;
  bool orthographic_camera = true;
  double orthographic_extent = 50.0;
  bool show_planes = true;
  bool show_plane_inliers = true;
  CalibrationParameters initial_calibration_parameters;
};

void RunViewer(const std::vector<ReplayFrame>& frames, const ReplayFrame* merged_beginning_frame,
               int merged_frame_count, const std::vector<PlaneModel>& planes,
               const ViewerConfig& config);

}  // namespace calibration

#endif  // UNITREE_LIDAR_SDK_REPLAYER_VIEWER_H_
