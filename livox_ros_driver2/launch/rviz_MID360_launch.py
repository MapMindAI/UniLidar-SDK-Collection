import os
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node

# Driver config lives in msg_MID360_launch.py; this file only adds rviz2.
cur_path = os.path.split(os.path.realpath(__file__))[0] + '/'
cur_config_path = cur_path + '../config'
rviz_config_path = os.path.join(cur_config_path, 'display_point_cloud_ROS2.rviz')
driver_launch_path = os.path.join(cur_path, 'msg_MID360_launch.py')


def generate_launch_description():
    livox_driver = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(driver_launch_path)
        )

    livox_rviz = Node(
            package='rviz2',
            executable='rviz2',
            output='screen',
            arguments=['--display-config', rviz_config_path]
        )

    return LaunchDescription([
        livox_driver,
        livox_rviz,
    ])
