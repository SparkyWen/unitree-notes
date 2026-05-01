# unitree_sdk2_python 仓库全量分析

> 分析范围：`unitree_sdk2_python/` 子目录。当前工作区还包含 `unitree_mujoco/`、`unitree_rl_mjlab/` 等旁路项目，但本文件按用户指定只展开 `unitree_sdk2_python`。

## 1. 全目录相对路径

```text
unitree_sdk2_python/
unitree_sdk2_python/example/
unitree_sdk2_python/example/b2/
unitree_sdk2_python/example/b2/camera/
unitree_sdk2_python/example/b2/high_level/
unitree_sdk2_python/example/b2/low_level/
unitree_sdk2_python/example/b2w/
unitree_sdk2_python/example/b2w/camera/
unitree_sdk2_python/example/b2w/high_level/
unitree_sdk2_python/example/b2w/low_level/
unitree_sdk2_python/example/g1/
unitree_sdk2_python/example/g1/audio/
unitree_sdk2_python/example/g1/high_level/
unitree_sdk2_python/example/g1/low_level/
unitree_sdk2_python/example/go2/
unitree_sdk2_python/example/go2/front_camera/
unitree_sdk2_python/example/go2/high_level/
unitree_sdk2_python/example/go2/low_level/
unitree_sdk2_python/example/go2w/
unitree_sdk2_python/example/go2w/high_level/
unitree_sdk2_python/example/go2w/low_level/
unitree_sdk2_python/example/h1/
unitree_sdk2_python/example/h1/high_level/
unitree_sdk2_python/example/h1/low_level/
unitree_sdk2_python/example/h1_2/
unitree_sdk2_python/example/h1_2/low_level/
unitree_sdk2_python/example/h2/
unitree_sdk2_python/example/h2/high_level/
unitree_sdk2_python/example/h2/low_level/
unitree_sdk2_python/example/helloworld/
unitree_sdk2_python/example/motionSwitcher/
unitree_sdk2_python/example/obstacles_avoid/
unitree_sdk2_python/example/vui_client/
unitree_sdk2_python/example/wireless_controller/
unitree_sdk2_python/unitree_sdk2py/
unitree_sdk2_python/unitree_sdk2py/b2/
unitree_sdk2_python/unitree_sdk2py/b2/back_video/
unitree_sdk2_python/unitree_sdk2py/b2/front_video/
unitree_sdk2_python/unitree_sdk2py/b2/robot_state/
unitree_sdk2_python/unitree_sdk2py/b2/sport/
unitree_sdk2_python/unitree_sdk2py/b2/vui/
unitree_sdk2_python/unitree_sdk2py/comm/
unitree_sdk2_python/unitree_sdk2py/comm/motion_switcher/
unitree_sdk2_python/unitree_sdk2py/core/
unitree_sdk2_python/unitree_sdk2py/g1/
unitree_sdk2_python/unitree_sdk2py/g1/arm/
unitree_sdk2_python/unitree_sdk2py/g1/audio/
unitree_sdk2_python/unitree_sdk2py/g1/loco/
unitree_sdk2_python/unitree_sdk2py/go2/
unitree_sdk2_python/unitree_sdk2py/go2/obstacles_avoid/
unitree_sdk2_python/unitree_sdk2py/go2/robot_state/
unitree_sdk2_python/unitree_sdk2py/go2/sport/
unitree_sdk2_python/unitree_sdk2py/go2/video/
unitree_sdk2_python/unitree_sdk2py/go2/vui/
unitree_sdk2_python/unitree_sdk2py/h1/
unitree_sdk2_python/unitree_sdk2py/h1/loco/
unitree_sdk2_python/unitree_sdk2py/h2/
unitree_sdk2_python/unitree_sdk2py/h2/loco/
unitree_sdk2_python/unitree_sdk2py/idl/
unitree_sdk2_python/unitree_sdk2py/idl/builtin_interfaces/
unitree_sdk2_python/unitree_sdk2py/idl/builtin_interfaces/msg/
unitree_sdk2_python/unitree_sdk2py/idl/builtin_interfaces/msg/dds_/
unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/
unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/msg/
unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/msg/dds_/
unitree_sdk2_python/unitree_sdk2py/idl/nav_msgs/
unitree_sdk2_python/unitree_sdk2py/idl/nav_msgs/msg/
unitree_sdk2_python/unitree_sdk2py/idl/nav_msgs/msg/dds_/
unitree_sdk2_python/unitree_sdk2py/idl/sensor_msgs/
unitree_sdk2_python/unitree_sdk2py/idl/sensor_msgs/msg/
unitree_sdk2_python/unitree_sdk2py/idl/sensor_msgs/msg/dds_/
unitree_sdk2_python/unitree_sdk2py/idl/sensor_msgs/msg/dds_/PointField_Constants/
unitree_sdk2_python/unitree_sdk2py/idl/std_msgs/
unitree_sdk2_python/unitree_sdk2py/idl/std_msgs/msg/
unitree_sdk2_python/unitree_sdk2py/idl/std_msgs/msg/dds_/
unitree_sdk2_python/unitree_sdk2py/idl/unitree_api/
unitree_sdk2_python/unitree_sdk2py/idl/unitree_api/msg/
unitree_sdk2_python/unitree_sdk2py/idl/unitree_api/msg/dds_/
unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/
unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/
unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/
unitree_sdk2_python/unitree_sdk2py/idl/unitree_hg/
unitree_sdk2_python/unitree_sdk2py/idl/unitree_hg/msg/
unitree_sdk2_python/unitree_sdk2py/idl/unitree_hg/msg/dds_/
unitree_sdk2_python/unitree_sdk2py/rpc/
unitree_sdk2_python/unitree_sdk2py/test/
unitree_sdk2_python/unitree_sdk2py/test/client/
unitree_sdk2_python/unitree_sdk2py/test/crc/
unitree_sdk2_python/unitree_sdk2py/test/helloworld/
unitree_sdk2_python/unitree_sdk2py/test/lowlevel/
unitree_sdk2_python/unitree_sdk2py/test/rpc/
unitree_sdk2_python/unitree_sdk2py/utils/
unitree_sdk2_python/unitree_sdk2py/utils/lib/
unitree_sdk2_python/.gitignore
unitree_sdk2_python/LICENSE
unitree_sdk2_python/README zh.md
unitree_sdk2_python/README.md
unitree_sdk2_python/example/b2/camera/camera_opencv.py
unitree_sdk2_python/example/b2/camera/capture_image.py
unitree_sdk2_python/example/b2/high_level/b2_sport_client.py
unitree_sdk2_python/example/b2/low_level/b2_stand_example.py
unitree_sdk2_python/example/b2/low_level/unitree_legged_const.py
unitree_sdk2_python/example/b2w/camera/camera_opencv.py
unitree_sdk2_python/example/b2w/camera/capture_image.py
unitree_sdk2_python/example/b2w/high_level/b2w_sport_client.py
unitree_sdk2_python/example/b2w/low_level/b2w_stand_example.py
unitree_sdk2_python/example/b2w/low_level/unitree_legged_const.py
unitree_sdk2_python/example/g1/audio/g1_audio_client_example.py
unitree_sdk2_python/example/g1/audio/g1_audio_client_play_wav.py
unitree_sdk2_python/example/g1/audio/test.wav
unitree_sdk2_python/example/g1/audio/wav.py
unitree_sdk2_python/example/g1/high_level/g1_arm5_sdk_dds_example.py
unitree_sdk2_python/example/g1/high_level/g1_arm7_sdk_dds_example.py
unitree_sdk2_python/example/g1/high_level/g1_arm_action_example.py
unitree_sdk2_python/example/g1/high_level/g1_loco_client_example.py
unitree_sdk2_python/example/g1/low_level/g1_low_level_example.py
unitree_sdk2_python/example/g1/readme.md
unitree_sdk2_python/example/go2/front_camera/camera_opencv.py
unitree_sdk2_python/example/go2/front_camera/capture_image.py
unitree_sdk2_python/example/go2/high_level/go2_sport_client.py
unitree_sdk2_python/example/go2/high_level/go2_utlidar_switch.py
unitree_sdk2_python/example/go2/low_level/go2_stand_example.py
unitree_sdk2_python/example/go2/low_level/unitree_legged_const.py
unitree_sdk2_python/example/go2w/high_level/go2w_sport_client.py
unitree_sdk2_python/example/go2w/low_level/go2w_stand_example.py
unitree_sdk2_python/example/go2w/low_level/unitree_legged_const.py
unitree_sdk2_python/example/h1/high_level/h1_loco_client_example.py
unitree_sdk2_python/example/h1/low_level/h1_low_level_example.py
unitree_sdk2_python/example/h1/low_level/unitree_legged_const.py
unitree_sdk2_python/example/h1_2/low_level/h1_2_low_level_example.py
unitree_sdk2_python/example/h2/high_level/h2_loco_client_example.py
unitree_sdk2_python/example/h2/low_level/h2_ankle_swing_example.py
unitree_sdk2_python/example/helloworld/publisher.py
unitree_sdk2_python/example/helloworld/subscriber.py
unitree_sdk2_python/example/helloworld/user_data.py
unitree_sdk2_python/example/motionSwitcher/motion_switcher_example.py
unitree_sdk2_python/example/obstacles_avoid/obstacles_avoid_move.py
unitree_sdk2_python/example/obstacles_avoid/obstacles_avoid_switch.py
unitree_sdk2_python/example/vui_client/vui_client_example.py
unitree_sdk2_python/example/wireless_controller/wireless_controller.py
unitree_sdk2_python/pyproject.toml
unitree_sdk2_python/setup.py
unitree_sdk2_python/unitree_sdk2py/__init__.py
unitree_sdk2_python/unitree_sdk2py/b2/back_video/back_video_api.py
unitree_sdk2_python/unitree_sdk2py/b2/back_video/back_video_client.py
unitree_sdk2_python/unitree_sdk2py/b2/front_video/front_video_api.py
unitree_sdk2_python/unitree_sdk2py/b2/front_video/front_video_client.py
unitree_sdk2_python/unitree_sdk2py/b2/robot_state/robot_state_api.py
unitree_sdk2_python/unitree_sdk2py/b2/robot_state/robot_state_client.py
unitree_sdk2_python/unitree_sdk2py/b2/sport/sport_api.py
unitree_sdk2_python/unitree_sdk2py/b2/sport/sport_client.py
unitree_sdk2_python/unitree_sdk2py/b2/vui/vui_api.py
unitree_sdk2_python/unitree_sdk2py/b2/vui/vui_client.py
unitree_sdk2_python/unitree_sdk2py/comm/motion_switcher/__init__.py
unitree_sdk2_python/unitree_sdk2py/comm/motion_switcher/motion_switcher_api.py
unitree_sdk2_python/unitree_sdk2py/comm/motion_switcher/motion_switcher_client.py
unitree_sdk2_python/unitree_sdk2py/core/__init__.py
unitree_sdk2_python/unitree_sdk2py/core/channel.py
unitree_sdk2_python/unitree_sdk2py/core/channel_config.py
unitree_sdk2_python/unitree_sdk2py/core/channel_name.py
unitree_sdk2_python/unitree_sdk2py/g1/arm/g1_arm_action_api.py
unitree_sdk2_python/unitree_sdk2py/g1/arm/g1_arm_action_client.py
unitree_sdk2_python/unitree_sdk2py/g1/audio/g1_audio_api.py
unitree_sdk2_python/unitree_sdk2py/g1/audio/g1_audio_client.py
unitree_sdk2_python/unitree_sdk2py/g1/loco/g1_loco_api.py
unitree_sdk2_python/unitree_sdk2py/g1/loco/g1_loco_client.py
unitree_sdk2_python/unitree_sdk2py/go2/__init__.py
unitree_sdk2_python/unitree_sdk2py/go2/obstacles_avoid/__init__.py
unitree_sdk2_python/unitree_sdk2py/go2/obstacles_avoid/obstacles_avoid_api.py
unitree_sdk2_python/unitree_sdk2py/go2/obstacles_avoid/obstacles_avoid_client.py
unitree_sdk2_python/unitree_sdk2py/go2/robot_state/__init__.py
unitree_sdk2_python/unitree_sdk2py/go2/robot_state/robot_state_api.py
unitree_sdk2_python/unitree_sdk2py/go2/robot_state/robot_state_client.py
unitree_sdk2_python/unitree_sdk2py/go2/sport/__init__.py
unitree_sdk2_python/unitree_sdk2py/go2/sport/sport_api.py
unitree_sdk2_python/unitree_sdk2py/go2/sport/sport_client.py
unitree_sdk2_python/unitree_sdk2py/go2/video/__init__.py
unitree_sdk2_python/unitree_sdk2py/go2/video/video_api.py
unitree_sdk2_python/unitree_sdk2py/go2/video/video_client.py
unitree_sdk2_python/unitree_sdk2py/go2/vui/__init__.py
unitree_sdk2_python/unitree_sdk2py/go2/vui/vui_api.py
unitree_sdk2_python/unitree_sdk2py/go2/vui/vui_client.py
unitree_sdk2_python/unitree_sdk2py/h1/loco/h1_loco_api.py
unitree_sdk2_python/unitree_sdk2py/h1/loco/h1_loco_client.py
unitree_sdk2_python/unitree_sdk2py/h2/loco/h2_loco_api.py
unitree_sdk2_python/unitree_sdk2py/h2/loco/h2_loco_client.py
unitree_sdk2_python/unitree_sdk2py/idl/__init__.py
unitree_sdk2_python/unitree_sdk2py/idl/builtin_interfaces/__init__.py
unitree_sdk2_python/unitree_sdk2py/idl/builtin_interfaces/msg/__init__.py
unitree_sdk2_python/unitree_sdk2py/idl/builtin_interfaces/msg/dds_/_Time_.py
unitree_sdk2_python/unitree_sdk2py/idl/builtin_interfaces/msg/dds_/__init__.py
unitree_sdk2_python/unitree_sdk2py/idl/default.py
unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/__init__.py
unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/msg/__init__.py
unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/msg/dds_/_Point32_.py
unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/msg/dds_/_PointStamped_.py
unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/msg/dds_/_Point_.py
unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/msg/dds_/_Pose2D_.py
unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/msg/dds_/_PoseStamped_.py
unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/msg/dds_/_PoseWithCovarianceStamped_.py
unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/msg/dds_/_PoseWithCovariance_.py
unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/msg/dds_/_Pose_.py
unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/msg/dds_/_QuaternionStamped_.py
unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/msg/dds_/_Quaternion_.py
unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/msg/dds_/_TwistStamped_.py
unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/msg/dds_/_TwistWithCovarianceStamped_.py
unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/msg/dds_/_TwistWithCovariance_.py
unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/msg/dds_/_Twist_.py
unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/msg/dds_/_Vector3_.py
unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/msg/dds_/__init__.py
unitree_sdk2_python/unitree_sdk2py/idl/nav_msgs/__init__.py
unitree_sdk2_python/unitree_sdk2py/idl/nav_msgs/msg/__init__.py
unitree_sdk2_python/unitree_sdk2py/idl/nav_msgs/msg/dds_/_MapMetaData_.py
unitree_sdk2_python/unitree_sdk2py/idl/nav_msgs/msg/dds_/_OccupancyGrid_.py
unitree_sdk2_python/unitree_sdk2py/idl/nav_msgs/msg/dds_/_Odometry_.py
unitree_sdk2_python/unitree_sdk2py/idl/nav_msgs/msg/dds_/__init__.py
unitree_sdk2_python/unitree_sdk2py/idl/sensor_msgs/__init__.py
unitree_sdk2_python/unitree_sdk2py/idl/sensor_msgs/msg/__init__.py
unitree_sdk2_python/unitree_sdk2py/idl/sensor_msgs/msg/dds_/PointField_Constants/_PointField_.py
unitree_sdk2_python/unitree_sdk2py/idl/sensor_msgs/msg/dds_/PointField_Constants/__init__.py
unitree_sdk2_python/unitree_sdk2py/idl/sensor_msgs/msg/dds_/_PointCloud2_.py
unitree_sdk2_python/unitree_sdk2py/idl/sensor_msgs/msg/dds_/_PointField_.py
unitree_sdk2_python/unitree_sdk2py/idl/sensor_msgs/msg/dds_/__init__.py
unitree_sdk2_python/unitree_sdk2py/idl/std_msgs/__init__.py
unitree_sdk2_python/unitree_sdk2py/idl/std_msgs/msg/__init__.py
unitree_sdk2_python/unitree_sdk2py/idl/std_msgs/msg/dds_/_Header_.py
unitree_sdk2_python/unitree_sdk2py/idl/std_msgs/msg/dds_/_String_.py
unitree_sdk2_python/unitree_sdk2py/idl/std_msgs/msg/dds_/__init__.py
unitree_sdk2_python/unitree_sdk2py/idl/unitree_api/__init__.py
unitree_sdk2_python/unitree_sdk2py/idl/unitree_api/msg/__init__.py
unitree_sdk2_python/unitree_sdk2py/idl/unitree_api/msg/dds_/_RequestHeader_.py
unitree_sdk2_python/unitree_sdk2py/idl/unitree_api/msg/dds_/_RequestIdentity_.py
unitree_sdk2_python/unitree_sdk2py/idl/unitree_api/msg/dds_/_RequestLease_.py
unitree_sdk2_python/unitree_sdk2py/idl/unitree_api/msg/dds_/_RequestPolicy_.py
unitree_sdk2_python/unitree_sdk2py/idl/unitree_api/msg/dds_/_Request_.py
unitree_sdk2_python/unitree_sdk2py/idl/unitree_api/msg/dds_/_ResponseHeader_.py
unitree_sdk2_python/unitree_sdk2py/idl/unitree_api/msg/dds_/_ResponseStatus_.py
unitree_sdk2_python/unitree_sdk2py/idl/unitree_api/msg/dds_/_Response_.py
unitree_sdk2_python/unitree_sdk2py/idl/unitree_api/msg/dds_/__init__.py
unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/__init__.py
unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/__init__.py
unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_AudioData_.py
unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_BmsCmd_.py
unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_BmsState_.py
unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_Error_.py
unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_Go2FrontVideoData_.py
unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_HeightMap_.py
unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_IMUState_.py
unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_InterfaceConfig_.py
unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_LidarState_.py
unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_LowCmd_.py
unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_LowState_.py
unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_MotorCmd_.py
unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_MotorCmds_.py
unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_MotorState_.py
unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_MotorStates_.py
unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_PathPoint_.py
unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_Req_.py
unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_Res_.py
unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_SportModeState_.py
unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_TimeSpec_.py
unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_UwbState_.py
unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_UwbSwitch_.py
unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_WirelessController_.py
unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/__init__.py
unitree_sdk2_python/unitree_sdk2py/idl/unitree_hg/.idlpy_manifest
unitree_sdk2_python/unitree_sdk2py/idl/unitree_hg/__init__.py
unitree_sdk2_python/unitree_sdk2py/idl/unitree_hg/msg/.idlpy_manifest
unitree_sdk2_python/unitree_sdk2py/idl/unitree_hg/msg/__init__.py
unitree_sdk2_python/unitree_sdk2py/idl/unitree_hg/msg/dds_/.idlpy_manifest
unitree_sdk2_python/unitree_sdk2py/idl/unitree_hg/msg/dds_/_BmsCmd_.py
unitree_sdk2_python/unitree_sdk2py/idl/unitree_hg/msg/dds_/_BmsState_.py
unitree_sdk2_python/unitree_sdk2py/idl/unitree_hg/msg/dds_/_HandCmd_.py
unitree_sdk2_python/unitree_sdk2py/idl/unitree_hg/msg/dds_/_HandState_.py
unitree_sdk2_python/unitree_sdk2py/idl/unitree_hg/msg/dds_/_IMUState_.py
unitree_sdk2_python/unitree_sdk2py/idl/unitree_hg/msg/dds_/_LowCmd_.py
unitree_sdk2_python/unitree_sdk2py/idl/unitree_hg/msg/dds_/_LowState_.py
unitree_sdk2_python/unitree_sdk2py/idl/unitree_hg/msg/dds_/_MainBoardState_.py
unitree_sdk2_python/unitree_sdk2py/idl/unitree_hg/msg/dds_/_MotorCmd_.py
unitree_sdk2_python/unitree_sdk2py/idl/unitree_hg/msg/dds_/_MotorState_.py
unitree_sdk2_python/unitree_sdk2py/idl/unitree_hg/msg/dds_/_PressSensorState_.py
unitree_sdk2_python/unitree_sdk2py/idl/unitree_hg/msg/dds_/__init__.py
unitree_sdk2_python/unitree_sdk2py/rpc/__init__.py
unitree_sdk2_python/unitree_sdk2py/rpc/client.py
unitree_sdk2_python/unitree_sdk2py/rpc/client_base.py
unitree_sdk2_python/unitree_sdk2py/rpc/client_stub.py
unitree_sdk2_python/unitree_sdk2py/rpc/internal.py
unitree_sdk2_python/unitree_sdk2py/rpc/lease_client.py
unitree_sdk2_python/unitree_sdk2py/rpc/lease_server.py
unitree_sdk2_python/unitree_sdk2py/rpc/request_future.py
unitree_sdk2_python/unitree_sdk2py/rpc/server.py
unitree_sdk2_python/unitree_sdk2py/rpc/server_base.py
unitree_sdk2_python/unitree_sdk2py/rpc/server_stub.py
unitree_sdk2_python/unitree_sdk2py/test/client/obstacles_avoid_client_example.py
unitree_sdk2_python/unitree_sdk2py/test/client/robot_service_client_example.py
unitree_sdk2_python/unitree_sdk2py/test/client/sport_client_example.py
unitree_sdk2_python/unitree_sdk2py/test/client/video_client_example.py
unitree_sdk2_python/unitree_sdk2py/test/client/vui_client_example.py
unitree_sdk2_python/unitree_sdk2py/test/crc/test_crc.py
unitree_sdk2_python/unitree_sdk2py/test/helloworld/helloworld.py
unitree_sdk2_python/unitree_sdk2py/test/helloworld/publisher.py
unitree_sdk2_python/unitree_sdk2py/test/helloworld/subscriber.py
unitree_sdk2_python/unitree_sdk2py/test/lowlevel/lowlevel_control.py
unitree_sdk2_python/unitree_sdk2py/test/lowlevel/read_lowstate.py
unitree_sdk2_python/unitree_sdk2py/test/lowlevel/sub_lowstate.py
unitree_sdk2_python/unitree_sdk2py/test/lowlevel/unitree_go2_const.py
unitree_sdk2_python/unitree_sdk2py/test/rpc/test_api.py
unitree_sdk2_python/unitree_sdk2py/test/rpc/test_client_example.py
unitree_sdk2_python/unitree_sdk2py/test/rpc/test_server_example.py
unitree_sdk2_python/unitree_sdk2py/utils/__init__.py
unitree_sdk2_python/unitree_sdk2py/utils/bqueue.py
unitree_sdk2_python/unitree_sdk2py/utils/clib_lookup.py
unitree_sdk2_python/unitree_sdk2py/utils/crc.py
unitree_sdk2_python/unitree_sdk2py/utils/future.py
unitree_sdk2_python/unitree_sdk2py/utils/hz_sample.py
unitree_sdk2_python/unitree_sdk2py/utils/joystick.py
unitree_sdk2_python/unitree_sdk2py/utils/lib/crc_aarch64.so
unitree_sdk2_python/unitree_sdk2py/utils/lib/crc_amd64.so
unitree_sdk2_python/unitree_sdk2py/utils/singleton.py
unitree_sdk2_python/unitree_sdk2py/utils/thread.py
unitree_sdk2_python/unitree_sdk2py/utils/timerfd.py
```

## 2. 总览

| 项目 | 内容 |
|---|---|
| 文件总数 | 228 |
| 目录总数 | 93，含根目录 |
| 主要语言/格式 | Python、Markdown、TOML、CycloneDDS IDL 生成 Python、Linux `.so`、WAV |
| 核心依赖 | `cyclonedds==0.10.2`、`numpy`、`opencv-python`；部分手柄工具还导入 `pygame`，但 setup.py 未列出 pygame。 |
| 核心通信模型 | `core.channel` 建立 DDS Domain/Topic/Reader/Writer；`rpc` 用 `rt/api/<service>/request` 与 `rt/api/<service>/response` topic 实现请求响应；低层控制直接发布/订阅 `rt/lowcmd`、`rt/lowstate` 等 DDS topic。 |
| 支持机器人/服务 | Go2/Go2W、B2/B2W、G1、H1、H1_2、H2；运动、低层控制、视频、VUI、避障、语音、运动模式切换、机器人服务状态。 |

## 3. 目录包含内容表

| 目录 | 子目录 | 文件 | 作用 |
|---|---|---|---|
| `unitree_sdk2_python/` | - | - | SDK 根目录：安装配置、README、许可证、example 示例和 unitree_sdk2py 包源码。 |
| `unitree_sdk2_python/example/` | b2/, b2w/, g1/, go2/, go2w/, h1/, h1_2/, h2/, helloworld/, motionSwitcher/, obstacles_avoid/, vui_client/, wireless_controller/ | - | 面向用户的运行示例，按机器人型号和服务分类。 |
| `unitree_sdk2_python/example/b2/` | camera/, high_level/, low_level/ | - | 示例子目录：b2 相关脚本。 |
| `unitree_sdk2_python/example/b2/camera/` | - | camera_opencv.py, capture_image.py | 示例子目录：b2/camera 相关脚本。 |
| `unitree_sdk2_python/example/b2/high_level/` | - | b2_sport_client.py | 示例子目录：b2/high_level 相关脚本。 |
| `unitree_sdk2_python/example/b2/low_level/` | - | b2_stand_example.py, unitree_legged_const.py | 示例子目录：b2/low_level 相关脚本。 |
| `unitree_sdk2_python/example/b2w/` | camera/, high_level/, low_level/ | - | 示例子目录：b2w 相关脚本。 |
| `unitree_sdk2_python/example/b2w/camera/` | - | camera_opencv.py, capture_image.py | 示例子目录：b2w/camera 相关脚本。 |
| `unitree_sdk2_python/example/b2w/high_level/` | - | b2w_sport_client.py | 示例子目录：b2w/high_level 相关脚本。 |
| `unitree_sdk2_python/example/b2w/low_level/` | - | b2w_stand_example.py, unitree_legged_const.py | 示例子目录：b2w/low_level 相关脚本。 |
| `unitree_sdk2_python/example/g1/` | audio/, high_level/, low_level/ | readme.md | 示例子目录：g1 相关脚本。 |
| `unitree_sdk2_python/example/g1/audio/` | - | g1_audio_client_example.py, g1_audio_client_play_wav.py, test.wav, wav.py | 示例子目录：g1/audio 相关脚本。 |
| `unitree_sdk2_python/example/g1/high_level/` | - | g1_arm5_sdk_dds_example.py, g1_arm7_sdk_dds_example.py, g1_arm_action_example.py, g1_loco_client_example.py | 示例子目录：g1/high_level 相关脚本。 |
| `unitree_sdk2_python/example/g1/low_level/` | - | g1_low_level_example.py | 示例子目录：g1/low_level 相关脚本。 |
| `unitree_sdk2_python/example/go2/` | front_camera/, high_level/, low_level/ | - | 示例子目录：go2 相关脚本。 |
| `unitree_sdk2_python/example/go2/front_camera/` | - | camera_opencv.py, capture_image.py | 示例子目录：go2/front_camera 相关脚本。 |
| `unitree_sdk2_python/example/go2/high_level/` | - | go2_sport_client.py, go2_utlidar_switch.py | 示例子目录：go2/high_level 相关脚本。 |
| `unitree_sdk2_python/example/go2/low_level/` | - | go2_stand_example.py, unitree_legged_const.py | 示例子目录：go2/low_level 相关脚本。 |
| `unitree_sdk2_python/example/go2w/` | high_level/, low_level/ | - | 示例子目录：go2w 相关脚本。 |
| `unitree_sdk2_python/example/go2w/high_level/` | - | go2w_sport_client.py | 示例子目录：go2w/high_level 相关脚本。 |
| `unitree_sdk2_python/example/go2w/low_level/` | - | go2w_stand_example.py, unitree_legged_const.py | 示例子目录：go2w/low_level 相关脚本。 |
| `unitree_sdk2_python/example/h1/` | high_level/, low_level/ | - | 示例子目录：h1 相关脚本。 |
| `unitree_sdk2_python/example/h1/high_level/` | - | h1_loco_client_example.py | 示例子目录：h1/high_level 相关脚本。 |
| `unitree_sdk2_python/example/h1/low_level/` | - | h1_low_level_example.py, unitree_legged_const.py | 示例子目录：h1/low_level 相关脚本。 |
| `unitree_sdk2_python/example/h1_2/` | low_level/ | - | 示例子目录：h1_2 相关脚本。 |
| `unitree_sdk2_python/example/h1_2/low_level/` | - | h1_2_low_level_example.py | 示例子目录：h1_2/low_level 相关脚本。 |
| `unitree_sdk2_python/example/h2/` | high_level/, low_level/ | - | 示例子目录：h2 相关脚本。 |
| `unitree_sdk2_python/example/h2/high_level/` | - | h2_loco_client_example.py | 示例子目录：h2/high_level 相关脚本。 |
| `unitree_sdk2_python/example/h2/low_level/` | - | h2_ankle_swing_example.py | 示例子目录：h2/low_level 相关脚本。 |
| `unitree_sdk2_python/example/helloworld/` | - | publisher.py, subscriber.py, user_data.py | 示例子目录：helloworld 相关脚本。 |
| `unitree_sdk2_python/example/motionSwitcher/` | - | motion_switcher_example.py | 示例子目录：motionSwitcher 相关脚本。 |
| `unitree_sdk2_python/example/obstacles_avoid/` | - | obstacles_avoid_move.py, obstacles_avoid_switch.py | 示例子目录：obstacles_avoid 相关脚本。 |
| `unitree_sdk2_python/example/vui_client/` | - | vui_client_example.py | 示例子目录：vui_client 相关脚本。 |
| `unitree_sdk2_python/example/wireless_controller/` | - | wireless_controller.py | 示例子目录：wireless_controller 相关脚本。 |
| `unitree_sdk2_python/unitree_sdk2py/` | b2/, comm/, core/, g1/, go2/, h1/, h2/, idl/, rpc/, test/, utils/ | __init__.py | 可安装 Python 包主体，包含 DDS 通道、RPC、机器人服务客户端、IDL 消息和工具。 |
| `unitree_sdk2_python/unitree_sdk2py/b2/` | back_video/, front_video/, robot_state/, sport/, vui/ | - | SDK 源码子目录：b2。 |
| `unitree_sdk2_python/unitree_sdk2py/b2/back_video/` | - | back_video_api.py, back_video_client.py | SDK 源码子目录：b2/back_video。 |
| `unitree_sdk2_python/unitree_sdk2py/b2/front_video/` | - | front_video_api.py, front_video_client.py | SDK 源码子目录：b2/front_video。 |
| `unitree_sdk2_python/unitree_sdk2py/b2/robot_state/` | - | robot_state_api.py, robot_state_client.py | SDK 源码子目录：b2/robot_state。 |
| `unitree_sdk2_python/unitree_sdk2py/b2/sport/` | - | sport_api.py, sport_client.py | SDK 源码子目录：b2/sport。 |
| `unitree_sdk2_python/unitree_sdk2py/b2/vui/` | - | vui_api.py, vui_client.py | SDK 源码子目录：b2/vui。 |
| `unitree_sdk2_python/unitree_sdk2py/comm/` | motion_switcher/ | - | SDK 源码子目录：comm。 |
| `unitree_sdk2_python/unitree_sdk2py/comm/motion_switcher/` | - | __init__.py, motion_switcher_api.py, motion_switcher_client.py | SDK 源码子目录：comm/motion_switcher。 |
| `unitree_sdk2_python/unitree_sdk2py/core/` | - | __init__.py, channel.py, channel_config.py, channel_name.py | CycloneDDS 通信核心层。 |
| `unitree_sdk2_python/unitree_sdk2py/g1/` | arm/, audio/, loco/ | - | SDK 源码子目录：g1。 |
| `unitree_sdk2_python/unitree_sdk2py/g1/arm/` | - | g1_arm_action_api.py, g1_arm_action_client.py | SDK 源码子目录：g1/arm。 |
| `unitree_sdk2_python/unitree_sdk2py/g1/audio/` | - | g1_audio_api.py, g1_audio_client.py | SDK 源码子目录：g1/audio。 |
| `unitree_sdk2_python/unitree_sdk2py/g1/loco/` | - | g1_loco_api.py, g1_loco_client.py | SDK 源码子目录：g1/loco。 |
| `unitree_sdk2_python/unitree_sdk2py/go2/` | obstacles_avoid/, robot_state/, sport/, video/, vui/ | __init__.py | SDK 源码子目录：go2。 |
| `unitree_sdk2_python/unitree_sdk2py/go2/obstacles_avoid/` | - | __init__.py, obstacles_avoid_api.py, obstacles_avoid_client.py | SDK 源码子目录：go2/obstacles_avoid。 |
| `unitree_sdk2_python/unitree_sdk2py/go2/robot_state/` | - | __init__.py, robot_state_api.py, robot_state_client.py | SDK 源码子目录：go2/robot_state。 |
| `unitree_sdk2_python/unitree_sdk2py/go2/sport/` | - | __init__.py, sport_api.py, sport_client.py | SDK 源码子目录：go2/sport。 |
| `unitree_sdk2_python/unitree_sdk2py/go2/video/` | - | __init__.py, video_api.py, video_client.py | SDK 源码子目录：go2/video。 |
| `unitree_sdk2_python/unitree_sdk2py/go2/vui/` | - | __init__.py, vui_api.py, vui_client.py | SDK 源码子目录：go2/vui。 |
| `unitree_sdk2_python/unitree_sdk2py/h1/` | loco/ | - | SDK 源码子目录：h1。 |
| `unitree_sdk2_python/unitree_sdk2py/h1/loco/` | - | h1_loco_api.py, h1_loco_client.py | SDK 源码子目录：h1/loco。 |
| `unitree_sdk2_python/unitree_sdk2py/h2/` | loco/ | - | SDK 源码子目录：h2。 |
| `unitree_sdk2_python/unitree_sdk2py/h2/loco/` | - | h2_loco_api.py, h2_loco_client.py | SDK 源码子目录：h2/loco。 |
| `unitree_sdk2_python/unitree_sdk2py/idl/` | builtin_interfaces/, geometry_msgs/, nav_msgs/, sensor_msgs/, std_msgs/, unitree_api/, unitree_go/, unitree_hg/ | __init__.py, default.py | CycloneDDS IDL Python 生成代码，定义所有 DDS 消息结构。 |
| `unitree_sdk2_python/unitree_sdk2py/idl/builtin_interfaces/` | msg/ | __init__.py | IDL 包目录：builtin_interfaces 消息模块/初始化文件。 |
| `unitree_sdk2_python/unitree_sdk2py/idl/builtin_interfaces/msg/` | dds_/ | __init__.py | IDL 包目录：builtin_interfaces/msg 消息模块/初始化文件。 |
| `unitree_sdk2_python/unitree_sdk2py/idl/builtin_interfaces/msg/dds_/` | - | _Time_.py, __init__.py | IDL 包目录：builtin_interfaces/msg/dds_ 消息模块/初始化文件。 |
| `unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/` | msg/ | __init__.py | IDL 包目录：geometry_msgs 消息模块/初始化文件。 |
| `unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/msg/` | dds_/ | __init__.py | IDL 包目录：geometry_msgs/msg 消息模块/初始化文件。 |
| `unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/msg/dds_/` | - | _Point32_.py, _PointStamped_.py, _Point_.py, _Pose2D_.py, _PoseStamped_.py, _PoseWithCovarianceStamped_.py, _PoseWithCovariance_.py, _Pose_.py, _QuaternionStamped_.py, _Quaternion_.py, _TwistStamped_.py, _TwistWithCovarianceStamped_.py, _TwistWithCovariance_.py, _Twist_.py, _Vector3_.py, __init__.py | IDL 包目录：geometry_msgs/msg/dds_ 消息模块/初始化文件。 |
| `unitree_sdk2_python/unitree_sdk2py/idl/nav_msgs/` | msg/ | __init__.py | IDL 包目录：nav_msgs 消息模块/初始化文件。 |
| `unitree_sdk2_python/unitree_sdk2py/idl/nav_msgs/msg/` | dds_/ | __init__.py | IDL 包目录：nav_msgs/msg 消息模块/初始化文件。 |
| `unitree_sdk2_python/unitree_sdk2py/idl/nav_msgs/msg/dds_/` | - | _MapMetaData_.py, _OccupancyGrid_.py, _Odometry_.py, __init__.py | IDL 包目录：nav_msgs/msg/dds_ 消息模块/初始化文件。 |
| `unitree_sdk2_python/unitree_sdk2py/idl/sensor_msgs/` | msg/ | __init__.py | IDL 包目录：sensor_msgs 消息模块/初始化文件。 |
| `unitree_sdk2_python/unitree_sdk2py/idl/sensor_msgs/msg/` | dds_/ | __init__.py | IDL 包目录：sensor_msgs/msg 消息模块/初始化文件。 |
| `unitree_sdk2_python/unitree_sdk2py/idl/sensor_msgs/msg/dds_/` | PointField_Constants/ | _PointCloud2_.py, _PointField_.py, __init__.py | IDL 包目录：sensor_msgs/msg/dds_ 消息模块/初始化文件。 |
| `unitree_sdk2_python/unitree_sdk2py/idl/sensor_msgs/msg/dds_/PointField_Constants/` | - | _PointField_.py, __init__.py | IDL 包目录：sensor_msgs/msg/dds_/PointField_Constants 消息模块/初始化文件。 |
| `unitree_sdk2_python/unitree_sdk2py/idl/std_msgs/` | msg/ | __init__.py | IDL 包目录：std_msgs 消息模块/初始化文件。 |
| `unitree_sdk2_python/unitree_sdk2py/idl/std_msgs/msg/` | dds_/ | __init__.py | IDL 包目录：std_msgs/msg 消息模块/初始化文件。 |
| `unitree_sdk2_python/unitree_sdk2py/idl/std_msgs/msg/dds_/` | - | _Header_.py, _String_.py, __init__.py | IDL 包目录：std_msgs/msg/dds_ 消息模块/初始化文件。 |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_api/` | msg/ | __init__.py | IDL 包目录：unitree_api 消息模块/初始化文件。 |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_api/msg/` | dds_/ | __init__.py | IDL 包目录：unitree_api/msg 消息模块/初始化文件。 |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_api/msg/dds_/` | - | _RequestHeader_.py, _RequestIdentity_.py, _RequestLease_.py, _RequestPolicy_.py, _Request_.py, _ResponseHeader_.py, _ResponseStatus_.py, _Response_.py, __init__.py | IDL 包目录：unitree_api/msg/dds_ 消息模块/初始化文件。 |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/` | msg/ | __init__.py | IDL 包目录：unitree_go 消息模块/初始化文件。 |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/` | dds_/ | __init__.py | IDL 包目录：unitree_go/msg 消息模块/初始化文件。 |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/` | - | _AudioData_.py, _BmsCmd_.py, _BmsState_.py, _Error_.py, _Go2FrontVideoData_.py, _HeightMap_.py, _IMUState_.py, _InterfaceConfig_.py, _LidarState_.py, _LowCmd_.py, _LowState_.py, _MotorCmd_.py, _MotorCmds_.py, _MotorState_.py, _MotorStates_.py, _PathPoint_.py, _Req_.py, _Res_.py, _SportModeState_.py, _TimeSpec_.py, _UwbState_.py, _UwbSwitch_.py, _WirelessController_.py, __init__.py | IDL 包目录：unitree_go/msg/dds_ 消息模块/初始化文件。 |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_hg/` | msg/ | .idlpy_manifest, __init__.py | IDL 包目录：unitree_hg 消息模块/初始化文件。 |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_hg/msg/` | dds_/ | .idlpy_manifest, __init__.py | IDL 包目录：unitree_hg/msg 消息模块/初始化文件。 |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_hg/msg/dds_/` | - | .idlpy_manifest, _BmsCmd_.py, _BmsState_.py, _HandCmd_.py, _HandState_.py, _IMUState_.py, _LowCmd_.py, _LowState_.py, _MainBoardState_.py, _MotorCmd_.py, _MotorState_.py, _PressSensorState_.py, __init__.py | IDL 包目录：unitree_hg/msg/dds_ 消息模块/初始化文件。 |
| `unitree_sdk2_python/unitree_sdk2py/rpc/` | - | __init__.py, client.py, client_base.py, client_stub.py, internal.py, lease_client.py, lease_server.py, request_future.py, server.py, server_base.py, server_stub.py | 基于 DDS topic 的 request/response RPC 框架。 |
| `unitree_sdk2_python/unitree_sdk2py/test/` | client/, crc/, helloworld/, lowlevel/, rpc/ | - | 包内开发测试/旧示例。 |
| `unitree_sdk2_python/unitree_sdk2py/test/client/` | - | obstacles_avoid_client_example.py, robot_service_client_example.py, sport_client_example.py, video_client_example.py, vui_client_example.py | SDK 源码子目录：test/client。 |
| `unitree_sdk2_python/unitree_sdk2py/test/crc/` | - | test_crc.py | SDK 源码子目录：test/crc。 |
| `unitree_sdk2_python/unitree_sdk2py/test/helloworld/` | - | helloworld.py, publisher.py, subscriber.py | SDK 源码子目录：test/helloworld。 |
| `unitree_sdk2_python/unitree_sdk2py/test/lowlevel/` | - | lowlevel_control.py, read_lowstate.py, sub_lowstate.py, unitree_go2_const.py | SDK 源码子目录：test/lowlevel。 |
| `unitree_sdk2_python/unitree_sdk2py/test/rpc/` | - | test_api.py, test_client_example.py, test_server_example.py | SDK 源码子目录：test/rpc。 |
| `unitree_sdk2_python/unitree_sdk2py/utils/` | lib/ | __init__.py, bqueue.py, clib_lookup.py, crc.py, future.py, hz_sample.py, joystick.py, singleton.py, thread.py, timerfd.py | 通用工具：CRC、队列、future、线程、timerfd、手柄。 |
| `unitree_sdk2_python/unitree_sdk2py/utils/lib/` | - | crc_aarch64.so, crc_amd64.so | SDK 源码子目录：utils/lib。 |

## 4. 每个文件作用总表

| 文件 | 类型 | 行数 | 大小 | 文件作用 | 主要类 | 顶层函数 | 主要常量/变量 |
|---|---:|---:|---:|---|---|---|---|
| `unitree_sdk2_python/.gitignore` | Git 忽略规则 | 39 | 296 B | 忽略 Python 缓存、构建产物、虚拟环境、日志、IDE 等本地文件。 | - | - | - |
| `unitree_sdk2_python/LICENSE` | 许可证文本 | 29 | 1.5 KB | BSD 3-Clause 许可证：声明 Unitree Robotics 版权、再发布条件和免责声明。 | - | - | - |
| `unitree_sdk2_python/README zh.md` | Markdown 文档 | 121 | 4.6 KB | 中文 README：与英文 README 对应，介绍安装、FAQ、DDS 通信和各类示例运行方法。 | - | - | - |
| `unitree_sdk2_python/README.md` | Markdown 文档 | 113 | 5.4 KB | 英文 README：说明安装依赖、CycloneDDS 编译/环境变量问题、DDS 发布订阅、高层/底层控制、遥控器、摄像头、避障、VUI 使用方式。 | - | - | - |
| `unitree_sdk2_python/example/b2/camera/camera_opencv.py` | Python 源码 | 51 | 1.6 KB | 摄像头实时显示示例：初始化 DDS 网络，调用视频客户端获取图像 bytes，用 OpenCV 解码并显示。 | - | display_image(window_name, data) | - |
| `unitree_sdk2_python/example/b2/camera/capture_image.py` | Python 源码 | 51 | 1.5 KB | 摄像头抓拍示例：调用视频客户端获取一帧 JPEG/图像数据并保存/展示。 | - | - | - |
| `unitree_sdk2_python/example/b2/high_level/b2_sport_client.py` | Python 源码 | 106 | 3.5 KB | RPC 客户端封装：继承/使用 Client，将业务方法转成 JSON 参数或二进制请求发送到机器人服务；公开方法 2 个。 | TestOption; UserInterface | - | - |
| `unitree_sdk2_python/example/b2/low_level/b2_stand_example.py` | Python 源码 | 175 | 6.2 KB | 四足机器人低层站立示例：订阅 LowState、发布 LowCmd，插值关节目标并用 CRC 校验命令。 | Custom | - | - |
| `unitree_sdk2_python/example/b2/low_level/unitree_legged_const.py` | Python 源码 | 20 | 345 B | 四足低层控制常量：定义腿/关节索引、控制级别、停止位置/速度哨兵值。 | - | - | LegID, HIGHLEVEL, LOWLEVEL, TRIGERLEVEL |
| `unitree_sdk2_python/example/b2w/camera/camera_opencv.py` | Python 源码 | 51 | 1.6 KB | 摄像头实时显示示例：初始化 DDS 网络，调用视频客户端获取图像 bytes，用 OpenCV 解码并显示。 | - | display_image(window_name, data) | - |
| `unitree_sdk2_python/example/b2w/camera/capture_image.py` | Python 源码 | 51 | 1.5 KB | 摄像头抓拍示例：调用视频客户端获取一帧 JPEG/图像数据并保存/展示。 | - | - | - |
| `unitree_sdk2_python/example/b2w/high_level/b2w_sport_client.py` | Python 源码 | 101 | 3.1 KB | RPC 客户端封装：继承/使用 Client，将业务方法转成 JSON 参数或二进制请求发送到机器人服务；公开方法 2 个。 | TestOption; UserInterface | - | - |
| `unitree_sdk2_python/example/b2w/low_level/b2w_stand_example.py` | Python 源码 | 196 | 7.2 KB | 四足机器人低层站立示例：订阅 LowState、发布 LowCmd，插值关节目标并用 CRC 校验命令。 | Custom | - | - |
| `unitree_sdk2_python/example/b2w/low_level/unitree_legged_const.py` | Python 源码 | 24 | 485 B | 四足低层控制常量：定义腿/关节索引、控制级别、停止位置/速度哨兵值。 | - | - | LegID, HIGHLEVEL, LOWLEVEL, TRIGERLEVEL |
| `unitree_sdk2_python/example/g1/audio/g1_audio_client_example.py` | Python 源码 | 44 | 1.3 KB | G1 语音服务示例：测试 TTS、音量获取/设置、RGB LED 控制等。 | - | - | - |
| `unitree_sdk2_python/example/g1/audio/g1_audio_client_play_wav.py` | Python 源码 | 35 | 1.1 KB | G1 WAV 播放示例：读取本目录 test.wav 并调用 G1AudioClient.PlayStream 推送音频。 | - | main() | - |
| `unitree_sdk2_python/example/g1/audio/test.wav` | 音频样本 | 3185 | 129.1 KB | G1 音频示例用 WAV 文件：供 g1_audio_client_play_wav.py 读取并通过语音服务推送 PCM 流。 | - | - | - |
| `unitree_sdk2_python/example/g1/audio/wav.py` | Python 源码 | 166 | 6.2 KB | WAV 处理工具：读取 PCM WAV、写 WAV、分块播放 PCM 流给 G1AudioClient。 | - | read_wav(filename), write_wave(filename, sample_rate, samples, num_channels), play_pcm_stream(client, pcm_list, stream_name, chunk_size, sleep_time, verbose) | - |
| `unitree_sdk2_python/example/g1/high_level/g1_arm5_sdk_dds_example.py` | Python 源码 | 192 | 6.7 KB | G1 5DoF 手臂 DDS 示例：直接发布 LowCmd 控制双臂关节，演示逐段插值和 CRC。 | G1JointIndex; Custom | - | - |
| `unitree_sdk2_python/example/g1/high_level/g1_arm7_sdk_dds_example.py` | Python 源码 | 194 | 6.8 KB | G1 7DoF 手臂 DDS 示例：直接发布 LowCmd 控制含腕部的双臂关节，演示逐段插值和 CRC。 | G1JointIndex; Custom | - | - |
| `unitree_sdk2_python/example/g1/high_level/g1_arm_action_example.py` | Python 源码 | 141 | 5.3 KB | G1 arm action RPC 示例：列出动作并执行指定动作 ID。 | TestOption; UserInterface | - | - |
| `unitree_sdk2_python/example/g1/high_level/g1_loco_client_example.py` | Python 源码 | 117 | 3.9 KB | 人形机器人高层 loco 服务示例：通过 LocoClient 执行 FSM 切换、站立/移动/挥手/握手等动作。 | TestOption; UserInterface | - | - |
| `unitree_sdk2_python/example/g1/low_level/g1_low_level_example.py` | Python 源码 | 205 | 7.2 KB | 人形机器人低层控制示例：发布 HG LowCmd、订阅 HG LowState、按关节索引设置位置/刚度/阻尼并计算 CRC。 | G1JointIndex; Mode; Custom | - | G1_NUM_MOTOR, Kp, Kd |
| `unitree_sdk2_python/example/g1/readme.md` | Markdown 文档 | 5 | 172 B | G1 示例说明：提示使用通用运动服务和臂部 DDS 示例前需要切换运动模式。 | - | - | - |
| `unitree_sdk2_python/example/go2/front_camera/camera_opencv.py` | Python 源码 | 41 | 1.1 KB | 摄像头实时显示示例：初始化 DDS 网络，调用视频客户端获取图像 bytes，用 OpenCV 解码并显示。 | - | - | - |
| `unitree_sdk2_python/example/go2/front_camera/capture_image.py` | Python 源码 | 30 | 736 B | 摄像头抓拍示例：调用视频客户端获取一帧 JPEG/图像数据并保存/展示。 | - | - | - |
| `unitree_sdk2_python/example/go2/high_level/go2_sport_client.py` | Python 源码 | 155 | 5.0 KB | RPC 客户端封装：继承/使用 Client，将业务方法转成 JSON 参数或二进制请求发送到机器人服务；公开方法 2 个。 | TestOption; UserInterface | - | - |
| `unitree_sdk2_python/example/go2/high_level/go2_utlidar_switch.py` | Python 源码 | 39 | 1.1 KB | 示例脚本。 | Custom | - | - |
| `unitree_sdk2_python/example/go2/low_level/go2_stand_example.py` | Python 源码 | 176 | 6.4 KB | 四足机器人低层站立示例：订阅 LowState、发布 LowCmd，插值关节目标并用 CRC 校验命令。 | Custom | - | - |
| `unitree_sdk2_python/example/go2/low_level/unitree_legged_const.py` | Python 源码 | 20 | 345 B | 四足低层控制常量：定义腿/关节索引、控制级别、停止位置/速度哨兵值。 | - | - | LegID, HIGHLEVEL, LOWLEVEL, TRIGERLEVEL |
| `unitree_sdk2_python/example/go2w/high_level/go2w_sport_client.py` | Python 源码 | 99 | 3.1 KB | RPC 客户端封装：继承/使用 Client，将业务方法转成 JSON 参数或二进制请求发送到机器人服务；公开方法 2 个。 | TestOption; UserInterface | - | - |
| `unitree_sdk2_python/example/go2w/low_level/go2w_stand_example.py` | Python 源码 | 196 | 7.2 KB | 四足机器人低层站立示例：订阅 LowState、发布 LowCmd，插值关节目标并用 CRC 校验命令。 | Custom | - | - |
| `unitree_sdk2_python/example/go2w/low_level/unitree_legged_const.py` | Python 源码 | 24 | 485 B | 四足低层控制常量：定义腿/关节索引、控制级别、停止位置/速度哨兵值。 | - | - | LegID, HIGHLEVEL, LOWLEVEL, TRIGERLEVEL |
| `unitree_sdk2_python/example/h1/high_level/h1_loco_client_example.py` | Python 源码 | 96 | 2.9 KB | 人形机器人高层 loco 服务示例：通过 LocoClient 执行 FSM 切换、站立/移动/挥手/握手等动作。 | TestOption; UserInterface | - | - |
| `unitree_sdk2_python/example/h1/low_level/h1_low_level_example.py` | Python 源码 | 167 | 5.2 KB | 人形机器人低层控制示例：发布 HG LowCmd、订阅 HG LowState、按关节索引设置位置/刚度/阻尼并计算 CRC。 | H1JointIndex; Custom | - | H1_NUM_MOTOR |
| `unitree_sdk2_python/example/h1/low_level/unitree_legged_const.py` | Python 源码 | 5 | 90 B | 四足低层控制常量：定义腿/关节索引、控制级别、停止位置/速度哨兵值。 | - | - | HIGHLEVEL, LOWLEVEL, TRIGERLEVEL |
| `unitree_sdk2_python/example/h1_2/low_level/h1_2_low_level_example.py` | Python 源码 | 201 | 7.5 KB | 人形机器人低层控制示例：发布 HG LowCmd、订阅 HG LowState、按关节索引设置位置/刚度/阻尼并计算 CRC。 | H1_2_JointIndex; Mode; Custom | - | H1_2_NUM_MOTOR |
| `unitree_sdk2_python/example/h2/high_level/h2_loco_client_example.py` | Python 源码 | 112 | 3.3 KB | 人形机器人高层 loco 服务示例：通过 LocoClient 执行 FSM 切换、站立/移动/挥手/握手等动作。 | TestOption; UserInterface | - | - |
| `unitree_sdk2_python/example/h2/low_level/h2_ankle_swing_example.py` | Python 源码 | 185 | 6.0 KB | 人形机器人低层控制示例：发布 HG LowCmd、订阅 HG LowState、按关节索引设置位置/刚度/阻尼并计算 CRC。 | Mode; H2JointIndex; Custom | - | H2_NUM_MOTOR, HG_CMD_TOPIC, HG_STATE_TOPIC, Kp, Kd |
| `unitree_sdk2_python/example/helloworld/publisher.py` | Python 源码 | 28 | 689 B | DDS hello world 发布端：初始化 ChannelFactory，按 topic 发布自定义 UserData/HelloWorld 消息。 | - | - | - |
| `unitree_sdk2_python/example/helloworld/subscriber.py` | Python 源码 | 20 | 526 B | DDS hello world 订阅端：订阅 topic 并打印收到的自定义消息。 | - | - | - |
| `unitree_sdk2_python/example/helloworld/user_data.py` | Python 源码 | 9 | 251 B | 自定义 DDS IDL 结构示例：定义 UserData(IdlStruct) 的 name 和 value 字段。 | UserData(IdlStruct) | - | - |
| `unitree_sdk2_python/example/motionSwitcher/motion_switcher_example.py` | Python 源码 | 36 | 922 B | 通用运动模式切换示例：检查当前模式、选择/释放 sport 或 ai 等模式。 | Custom | - | - |
| `unitree_sdk2_python/example/obstacles_avoid/obstacles_avoid_move.py` | Python 源码 | 38 | 1.0 KB | Go2 避障移动示例：通过 ObstaclesAvoidClient 发送速度/位置移动命令。 | - | - | - |
| `unitree_sdk2_python/example/obstacles_avoid/obstacles_avoid_switch.py` | Python 源码 | 94 | 2.8 KB | Go2 避障开关示例：循环查询/设置避障状态和远程命令来源。 | - | - | - |
| `unitree_sdk2_python/example/vui_client/vui_client_example.py` | Python 源码 | 77 | 1.9 KB | VUI 示例：循环设置灯光开关、音量和亮度并读取状态。 | - | - | - |
| `unitree_sdk2_python/example/wireless_controller/wireless_controller.py` | Python 源码 | 131 | 3.8 KB | 无线遥控器状态示例：订阅 LowState，解析 wireless_remote 位域/摇杆浮点数并打印按键状态。 | unitreeRemoteController; Custom | - | - |
| `unitree_sdk2_python/pyproject.toml` | Python 构建配置 | 3 | 89 B | PEP 517 构建入口：指定 setuptools 和 wheel 作为构建系统。 | - | - | - |
| `unitree_sdk2_python/setup.py` | Python 源码 | 21 | 711 B | setuptools 安装脚本：定义包名 unitree_sdk2py、版本 1.0.1、BSD-3-Clause、Python>=3.8，以及 cyclonedds==0.10.2/numpy/opencv-python 依赖。 | - | - | - |
| `unitree_sdk2_python/unitree_sdk2py/__init__.py` | Python 源码 | 10 | 128 B | Python 包初始化文件：标记该目录为可导入包；有些 IDL 子包还集中 re-export 消息类。 | - | - | __all__ |
| `unitree_sdk2_python/unitree_sdk2py/b2/back_video/back_video_api.py` | Python 源码 | 16 | 209 B | 服务 API 常量文件：定义服务名 ROBOT_BACK_VIDEO_SERVICE_NAME、版本 ROBOT_BACK_VIDEO_API_VERSION、1 个接口 ID/错误码，供对应 client 注册和调用。 | - | - | ROBOT_BACK_VIDEO_SERVICE_NAME, ROBOT_BACK_VIDEO_API_VERSION, ROBOT_BACK_VIDEO_API_ID_GETIMAGESAMPLE |
| `unitree_sdk2_python/unitree_sdk2py/b2/back_video/back_video_client.py` | Python 源码 | 23 | 540 B | RPC 客户端封装：继承/使用 Client，将业务方法转成 JSON 参数或二进制请求发送到机器人服务；公开方法 2 个。 | BackVideoClient(Client) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/b2/front_video/front_video_api.py` | Python 源码 | 16 | 213 B | 服务 API 常量文件：定义服务名 ROBOT_FRONT_VIDEO_SERVICE_NAME、版本 ROBOT_FRONT_VIDEO_API_VERSION、1 个接口 ID/错误码，供对应 client 注册和调用。 | - | - | ROBOT_FRONT_VIDEO_SERVICE_NAME, ROBOT_FRONT_VIDEO_API_VERSION, ROBOT_FRONT_VIDEO_API_ID_GETIMAGESAMPLE |
| `unitree_sdk2_python/unitree_sdk2py/b2/front_video/front_video_client.py` | Python 源码 | 23 | 546 B | RPC 客户端封装：继承/使用 Client，将业务方法转成 JSON 参数或二进制请求发送到机器人服务；公开方法 2 个。 | FrontVideoClient(Client) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/b2/robot_state/robot_state_api.py` | Python 源码 | 25 | 371 B | 服务 API 常量文件：定义服务名 ROBOT_STATE_SERVICE_NAME、版本 ROBOT_STATE_API_VERSION、3 个接口 ID/错误码，供对应 client 注册和调用。 | - | - | ROBOT_STATE_SERVICE_NAME, ROBOT_STATE_API_VERSION, ROBOT_STATE_API_ID_SERVICE_SWITCH, ROBOT_STATE_API_ID_REPORT_FREQ, ROBOT_STATE_API_ID_SERVICE_LIST, ROBOT_STATE_ERR_SERVICE_SWITCH, ROBOT_STATE_ERR_SERVICE_PROTECTED |
| `unitree_sdk2_python/unitree_sdk2py/b2/robot_state/robot_state_client.py` | Python 源码 | 84 | 2.1 KB | RPC 客户端封装：继承/使用 Client，将业务方法转成 JSON 参数或二进制请求发送到机器人服务；公开方法 4 个。 | ServiceState; RobotStateClient(Client) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/b2/sport/sport_api.py` | Python 源码 | 45 | 1.2 KB | 服务 API 常量文件：定义服务名 SPORT_SERVICE_NAME、版本 SPORT_API_VERSION、21 个接口 ID/错误码，供对应 client 注册和调用。 | - | - | SPORT_SERVICE_NAME, SPORT_API_VERSION, ROBOT_SPORT_API_ID_DAMP, ROBOT_SPORT_API_ID_BALANCESTAND, ROBOT_SPORT_API_ID_STOPMOVE, ROBOT_SPORT_API_ID_STANDUP, ROBOT_SPORT_API_ID_STANDDOWN, ROBOT_SPORT_API_ID_RECOVERYSTAND, ROBOT_SPORT_API_ID_MOVE, ROBOT_SPORT_API_ID_SWITCHGAIT, ROBOT_SPORT_API_ID_BODYHEIGHT, ROBOT_SPORT_API_ID_SPEEDLEVEL ... 共26个 |
| `unitree_sdk2_python/unitree_sdk2py/b2/sport/sport_client.py` | Python 源码 | 219 | 6.5 KB | RPC 客户端封装：继承/使用 Client，将业务方法转成 JSON 参数或二进制请求发送到机器人服务；公开方法 22 个。 | PathPoint; SportClient(Client) | - | SPORT_PATH_POINT_SIZE |
| `unitree_sdk2_python/unitree_sdk2py/b2/vui/vui_api.py` | Python 源码 | 21 | 303 B | 服务 API 常量文件：定义服务名 VUI_SERVICE_NAME、版本 VUI_API_VERSION、6 个接口 ID/错误码，供对应 client 注册和调用。 | - | - | VUI_SERVICE_NAME, VUI_API_VERSION, VUI_API_ID_SETSWITCH, VUI_API_ID_GETSWITCH, VUI_API_ID_SETVOLUME, VUI_API_ID_GETVOLUME, VUI_API_ID_SETBRIGHTNESS, VUI_API_ID_GETBRIGHTNESS |
| `unitree_sdk2_python/unitree_sdk2py/b2/vui/vui_client.py` | Python 源码 | 86 | 2.1 KB | RPC 客户端封装：继承/使用 Client，将业务方法转成 JSON 参数或二进制请求发送到机器人服务；公开方法 7 个。 | VuiClient(Client) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/comm/motion_switcher/__init__.py` | Python 源码 | 0 | 0 B | Python 包初始化文件：标记该目录为可导入包；有些 IDL 子包还集中 re-export 消息类。 | - | - | - |
| `unitree_sdk2_python/unitree_sdk2py/comm/motion_switcher/motion_switcher_api.py` | Python 源码 | 29 | 538 B | 服务 API 常量文件：定义服务名 MOTION_SWITCHER_SERVICE_NAME、版本 MOTION_SWITCHER_API_VERSION、5 个接口 ID/错误码，供对应 client 注册和调用。 | - | - | MOTION_SWITCHER_SERVICE_NAME, MOTION_SWITCHER_API_VERSION, MOTION_SWITCHER_API_ID_CHECK_MODE, MOTION_SWITCHER_API_ID_SELECT_MODE, MOTION_SWITCHER_API_ID_RELEASE_MODE, MOTION_SWITCHER_API_ID_SET_SILENT, MOTION_SWITCHER_API_ID_GET_SILENT |
| `unitree_sdk2_python/unitree_sdk2py/comm/motion_switcher/motion_switcher_client.py` | Python 源码 | 51 | 1.4 KB | RPC 客户端封装：继承/使用 Client，将业务方法转成 JSON 参数或二进制请求发送到机器人服务；公开方法 4 个。 | MotionSwitcherClient(Client) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/core/__init__.py` | Python 源码 | 0 | 0 B | Python 包初始化文件：标记该目录为可导入包；有些 IDL 子包还集中 re-export 消息类。 | - | - | - |
| `unitree_sdk2_python/unitree_sdk2py/core/channel.py` | Python 源码 | 301 | 9.6 KB | DDS 通道核心：封装 CycloneDDS Domain/Participant/Topic、DataWriter/DataReader、异步回调队列、ChannelFactory 单例以及发布/订阅便捷类。 | Channel; ChannelFactory(Singleton); ChannelPublisher; ChannelSubscriber | ChannelFactoryInitialize(id, networkInterface) | - |
| `unitree_sdk2_python/unitree_sdk2py/core/channel_config.py` | Python 源码 | 25 | 861 B | CycloneDDS XML 配置模板：一个指定网卡，一个自动选择网卡，供 ChannelFactory.Init 根据 networkInterface 选择。 | - | - | ChannelConfigHasInterface, ChannelConfigAutoDetermine |
| `unitree_sdk2_python/unitree_sdk2py/core/channel_name.py` | Python 源码 | 34 | 646 B | RPC 通道命名规则：定义 SEND/RECV 枚举，以及客户端/服务端 request/response Topic 名称拼接规则。 | ChannelType(Enum) | GetClientChannelName(serviceName, channelType), GetServerChannelName(serviceName, channelType) | - |
| `unitree_sdk2_python/unitree_sdk2py/g1/arm/g1_arm_action_api.py` | Python 源码 | 19 | 254 B | 服务 API 常量文件：定义服务名 ARM_ACTION_SERVICE_NAME、版本 ARM_ACTION_API_VERSION、2 个接口 ID/错误码，供对应 client 注册和调用。 | - | - | ARM_ACTION_SERVICE_NAME, ARM_ACTION_API_VERSION, ROBOT_API_ID_ARM_ACTION_EXECUTE_ACTION, ROBOT_API_ID_ARM_ACTION_GET_ACTION_LIST |
| `unitree_sdk2_python/unitree_sdk2py/g1/arm/g1_arm_action_client.py` | Python 源码 | 56 | 1.3 KB | RPC 客户端封装：继承/使用 Client，将业务方法转成 JSON 参数或二进制请求发送到机器人服务；公开方法 3 个。 | G1ArmActionClient(Client) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/g1/audio/g1_audio_api.py` | Python 源码 | 24 | 398 B | 服务 API 常量文件：定义服务名 AUDIO_SERVICE_NAME、版本 AUDIO_API_VERSION、7 个接口 ID/错误码，供对应 client 注册和调用。 | - | - | AUDIO_SERVICE_NAME, AUDIO_API_VERSION, ROBOT_API_ID_AUDIO_TTS, ROBOT_API_ID_AUDIO_ASR, ROBOT_API_ID_AUDIO_START_PLAY, ROBOT_API_ID_AUDIO_STOP_PLAY, ROBOT_API_ID_AUDIO_GET_VOLUME, ROBOT_API_ID_AUDIO_SET_VOLUME, ROBOT_API_ID_AUDIO_SET_RGB_LED |
| `unitree_sdk2_python/unitree_sdk2py/g1/audio/g1_audio_client.py` | Python 源码 | 71 | 2.2 KB | RPC 客户端封装：继承/使用 Client，将业务方法转成 JSON 参数或二进制请求发送到机器人服务；公开方法 7 个。 | AudioClient(Client) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/g1/loco/g1_loco_api.py` | Python 源码 | 32 | 639 B | 服务 API 常量文件：定义服务名 LOCO_SERVICE_NAME、版本 LOCO_API_VERSION、12 个接口 ID/错误码，供对应 client 注册和调用。 | - | - | LOCO_SERVICE_NAME, LOCO_API_VERSION, ROBOT_API_ID_LOCO_GET_FSM_ID, ROBOT_API_ID_LOCO_GET_FSM_MODE, ROBOT_API_ID_LOCO_GET_BALANCE_MODE, ROBOT_API_ID_LOCO_GET_SWING_HEIGHT, ROBOT_API_ID_LOCO_GET_STAND_HEIGHT, ROBOT_API_ID_LOCO_GET_PHASE, ROBOT_API_ID_LOCO_SET_FSM_ID, ROBOT_API_ID_LOCO_SET_BALANCE_MODE, ROBOT_API_ID_LOCO_SET_SWING_HEIGHT, ROBOT_API_ID_LOCO_SET_STAND_HEIGHT ... 共14个 |
| `unitree_sdk2_python/unitree_sdk2py/g1/loco/g1_loco_client.py` | Python 源码 | 127 | 3.7 KB | RPC 客户端封装：继承/使用 Client，将业务方法转成 JSON 参数或二进制请求发送到机器人服务；公开方法 20 个。 | LocoClient(Client) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/go2/__init__.py` | Python 源码 | 0 | 0 B | Python 包初始化文件：标记该目录为可导入包；有些 IDL 子包还集中 re-export 消息类。 | - | - | - |
| `unitree_sdk2_python/unitree_sdk2py/go2/obstacles_avoid/__init__.py` | Python 源码 | 0 | 0 B | Python 包初始化文件：标记该目录为可导入包；有些 IDL 子包还集中 re-export 消息类。 | - | - | - |
| `unitree_sdk2_python/unitree_sdk2py/go2/obstacles_avoid/obstacles_avoid_api.py` | Python 源码 | 19 | 337 B | 服务 API 常量文件：定义服务名 OBSTACLES_AVOID_SERVICE_NAME、版本 OBSTACLES_AVOID_API_VERSION、4 个接口 ID/错误码，供对应 client 注册和调用。 | - | - | OBSTACLES_AVOID_SERVICE_NAME, OBSTACLES_AVOID_API_VERSION, OBSTACLES_AVOID_API_ID_SWITCH_SET, OBSTACLES_AVOID_API_ID_SWITCH_GET, OBSTACLES_AVOID_API_ID_MOVE, OBSTACLES_AVOID_API_ID_USE_REMOTE_COMMAND_FROM_API |
| `unitree_sdk2_python/unitree_sdk2py/go2/obstacles_avoid/obstacles_avoid_client.py` | Python 源码 | 80 | 2.3 KB | RPC 客户端封装：继承/使用 Client，将业务方法转成 JSON 参数或二进制请求发送到机器人服务；公开方法 7 个。 | ObstaclesAvoidClient(Client) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/go2/robot_state/__init__.py` | Python 源码 | 0 | 0 B | Python 包初始化文件：标记该目录为可导入包；有些 IDL 子包还集中 re-export 消息类。 | - | - | - |
| `unitree_sdk2_python/unitree_sdk2py/go2/robot_state/robot_state_api.py` | Python 源码 | 25 | 371 B | 服务 API 常量文件：定义服务名 ROBOT_STATE_SERVICE_NAME、版本 ROBOT_STATE_API_VERSION、3 个接口 ID/错误码，供对应 client 注册和调用。 | - | - | ROBOT_STATE_SERVICE_NAME, ROBOT_STATE_API_VERSION, ROBOT_STATE_API_ID_SERVICE_SWITCH, ROBOT_STATE_API_ID_REPORT_FREQ, ROBOT_STATE_API_ID_SERVICE_LIST, ROBOT_STATE_ERR_SERVICE_SWITCH, ROBOT_STATE_ERR_SERVICE_PROTECTED |
| `unitree_sdk2_python/unitree_sdk2py/go2/robot_state/robot_state_client.py` | Python 源码 | 84 | 2.1 KB | RPC 客户端封装：继承/使用 Client，将业务方法转成 JSON 参数或二进制请求发送到机器人服务；公开方法 4 个。 | ServiceState; RobotStateClient(Client) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/go2/sport/__init__.py` | Python 源码 | 0 | 0 B | Python 包初始化文件：标记该目录为可导入包；有些 IDL 子包还集中 re-export 消息类。 | - | - | - |
| `unitree_sdk2_python/unitree_sdk2py/go2/sport/sport_api.py` | Python 源码 | 63 | 1.4 KB | 服务 API 常量文件：定义服务名 SPORT_SERVICE_NAME、版本 SPORT_API_VERSION、39 个接口 ID/错误码，供对应 client 注册和调用。 | - | - | SPORT_SERVICE_NAME, SPORT_API_VERSION, SPORT_API_ID_DAMP, SPORT_API_ID_BALANCESTAND, SPORT_API_ID_STOPMOVE, SPORT_API_ID_STANDUP, SPORT_API_ID_STANDDOWN, SPORT_API_ID_RECOVERYSTAND, SPORT_API_ID_EULER, SPORT_API_ID_MOVE, SPORT_API_ID_SIT, SPORT_API_ID_RISESIT ... 共44个 |
| `unitree_sdk2_python/unitree_sdk2py/go2/sport/sport_client.py` | Python 源码 | 363 | 10.7 KB | RPC 客户端封装：继承/使用 Client，将业务方法转成 JSON 参数或二进制请求发送到机器人服务；公开方法 39 个。 | PathPoint; SportClient(Client) | - | SPORT_PATH_POINT_SIZE |
| `unitree_sdk2_python/unitree_sdk2py/go2/video/__init__.py` | Python 源码 | 0 | 0 B | Python 包初始化文件：标记该目录为可导入包；有些 IDL 子包还集中 re-export 消息类。 | - | - | - |
| `unitree_sdk2_python/unitree_sdk2py/go2/video/video_api.py` | Python 源码 | 16 | 171 B | 服务 API 常量文件：定义服务名 VIDEO_SERVICE_NAME、版本 VIDEO_API_VERSION、1 个接口 ID/错误码，供对应 client 注册和调用。 | - | - | VIDEO_SERVICE_NAME, VIDEO_API_VERSION, VIDEO_API_ID_GETIMAGESAMPLE |
| `unitree_sdk2_python/unitree_sdk2py/go2/video/video_client.py` | Python 源码 | 23 | 482 B | RPC 客户端封装：继承/使用 Client，将业务方法转成 JSON 参数或二进制请求发送到机器人服务；公开方法 2 个。 | VideoClient(Client) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/go2/vui/__init__.py` | Python 源码 | 0 | 0 B | Python 包初始化文件：标记该目录为可导入包；有些 IDL 子包还集中 re-export 消息类。 | - | - | - |
| `unitree_sdk2_python/unitree_sdk2py/go2/vui/vui_api.py` | Python 源码 | 21 | 303 B | 服务 API 常量文件：定义服务名 VUI_SERVICE_NAME、版本 VUI_API_VERSION、6 个接口 ID/错误码，供对应 client 注册和调用。 | - | - | VUI_SERVICE_NAME, VUI_API_VERSION, VUI_API_ID_SETSWITCH, VUI_API_ID_GETSWITCH, VUI_API_ID_SETVOLUME, VUI_API_ID_GETVOLUME, VUI_API_ID_SETBRIGHTNESS, VUI_API_ID_GETBRIGHTNESS |
| `unitree_sdk2_python/unitree_sdk2py/go2/vui/vui_client.py` | Python 源码 | 86 | 2.1 KB | RPC 客户端封装：继承/使用 Client，将业务方法转成 JSON 参数或二进制请求发送到机器人服务；公开方法 7 个。 | VuiClient(Client) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/h1/loco/h1_loco_api.py` | Python 源码 | 31 | 600 B | 服务 API 常量文件：定义服务名 LOCO_SERVICE_NAME、版本 LOCO_API_VERSION、11 个接口 ID/错误码，供对应 client 注册和调用。 | - | - | LOCO_SERVICE_NAME, LOCO_API_VERSION, ROBOT_API_ID_LOCO_GET_FSM_ID, ROBOT_API_ID_LOCO_GET_FSM_MODE, ROBOT_API_ID_LOCO_GET_BALANCE_MODE, ROBOT_API_ID_LOCO_GET_SWING_HEIGHT, ROBOT_API_ID_LOCO_GET_STAND_HEIGHT, ROBOT_API_ID_LOCO_GET_PHASE, ROBOT_API_ID_LOCO_SET_FSM_ID, ROBOT_API_ID_LOCO_SET_BALANCE_MODE, ROBOT_API_ID_LOCO_SET_SWING_HEIGHT, ROBOT_API_ID_LOCO_SET_STAND_HEIGHT ... 共13个 |
| `unitree_sdk2_python/unitree_sdk2py/h1/loco/h1_loco_client.py` | Python 源码 | 83 | 2.4 KB | RPC 客户端封装：继承/使用 Client，将业务方法转成 JSON 参数或二进制请求发送到机器人服务；公开方法 12 个。 | LocoClient(Client) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/h2/loco/h2_loco_api.py` | Python 源码 | 32 | 826 B | 服务 API 常量文件：定义服务名 LOCO_SERVICE_NAME、版本 LOCO_API_VERSION、17 个接口 ID/错误码，供对应 client 注册和调用。 | - | - | LOCO_SERVICE_NAME, LOCO_API_VERSION, ROBOT_API_ID_LOCO_GET_FSM_ID, ROBOT_API_ID_LOCO_GET_FSM_MODE, ROBOT_API_ID_LOCO_GET_BALANCE_MODE, ROBOT_API_ID_LOCO_GET_SWING_HEIGHT, ROBOT_API_ID_LOCO_GET_STAND_HEIGHT, ROBOT_API_ID_LOCO_GET_PHASE, ROBOT_API_ID_LOCO_GET_ARM_SDK_STATUS, ROBOT_API_ID_LOCO_GET_AVAILABLE_FSM_IDS, ROBOT_API_ID_LOCO_SET_FSM_ID, ROBOT_API_ID_LOCO_SET_BALANCE_MODE ... 共19个 |
| `unitree_sdk2_python/unitree_sdk2py/h2/loco/h2_loco_client.py` | Python 源码 | 249 | 7.4 KB | RPC 客户端封装：继承/使用 Client，将业务方法转成 JSON 参数或二进制请求发送到机器人服务；公开方法 35 个。 | LocoClient(Client) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/__init__.py` | Python 源码 | 12 | 271 B | Python 包初始化文件：标记该目录为可导入包；有些 IDL 子包还集中 re-export 消息类。 | - | - | __all__ |
| `unitree_sdk2_python/unitree_sdk2py/idl/builtin_interfaces/__init__.py` | Python 源码 | 9 | 167 B | Python 包初始化文件：标记该目录为可导入包；有些 IDL 子包还集中 re-export 消息类。 | - | - | __all__ |
| `unitree_sdk2_python/unitree_sdk2py/idl/builtin_interfaces/msg/__init__.py` | Python 源码 | 9 | 173 B | Python 包初始化文件：标记该目录为可导入包；有些 IDL 子包还集中 re-export 消息类。 | - | - | __all__ |
| `unitree_sdk2_python/unitree_sdk2py/idl/builtin_interfaces/msg/dds_/_Time_.py` | Python 源码 | 28 | 625 B | CycloneDDS 生成的 IDL 数据结构 Time_：定义 DDS 消息字段和类型注解，共 2 个字段。 | Time_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/builtin_interfaces/msg/dds_/__init__.py` | Python 源码 | 9 | 186 B | Python 包初始化文件：标记该目录为可导入包；有些 IDL 子包还集中 re-export 消息类。 | - | - | __all__ |
| `unitree_sdk2_python/unitree_sdk2py/idl/default.py` | Python 源码 | 268 | 10.3 KB | IDL 默认值工厂：为所有 DDS 消息类型创建带默认字段的实例，供示例和低层控制初始化命令/状态结构。 | - | builtin_interfaces_msgs_msg_dds__Time_(), std_msgs_msg_dds__Header_(), std_msgs_msg_dds__String_(), geometry_msgs_msg_dds__Point_(), geometry_msgs_msg_dds__Point32_(), geometry_msgs_msg_dds__PointStamped_(), geometry_msgs_msg_dds__Quaternion_(), geometry_msgs_msg_dds__Vector3_(), geometry_msgs_msg_dds__Pose_(), geometry_msgs_msg_dds__Pose2D_(), geometry_msgs_msg_dds__PoseStamped_(), geometry_msgs_msg_dds__PoseWithCovariance_(), geometry_msgs_msg_dds__PoseWithCovarianceStamped_(), geometry_msgs_msg_dds__QuaternionStamped_(), geometry_msgs_msg_dds__Twist_(), geometry_msgs_msg_dds__TwistStamped_(), geometry_msgs_msg_dds__TwistWithCovariance_(), geometry_msgs_msg_dds__TwistWithCovarianceStamped_(), nav_msgs_msg_dds__MapMetaData_(), nav_msgs_msg_dds__OccupancyGrid_(), nav_msgs_msg_dds__Odometry_(), sensor_msgs_msg_dds__PointField_Constants_PointField_(), sensor_msgs_msg_dds__PointField_Constants_PointCloud2_(), unitree_go_msg_dds__AudioData_(), unitree_go_msg_dds__BmsCmd_(), unitree_go_msg_dds__BmsState_(), unitree_go_msg_dds__Error_(), unitree_go_msg_dds__Go2FrontVideoData_(), unitree_go_msg_dds__HeightMap_(), unitree_go_msg_dds__IMUState_(), unitree_go_msg_dds__InterfaceConfig_(), unitree_go_msg_dds__LidarState_(), unitree_go_msg_dds__MotorCmd_(), unitree_go_msg_dds__MotorState_(), unitree_go_msg_dds__LowCmd_(), unitree_go_msg_dds__LowState_(), unitree_go_msg_dds__Req_(), unitree_go_msg_dds__Res_(), unitree_go_msg_dds__TimeSpec_(), unitree_go_msg_dds__PathPoint_(), unitree_go_msg_dds__SportModeState_(), unitree_go_msg_dds__UwbState_(), unitree_go_msg_dds__UwbSwitch_(), unitree_go_msg_dds__WirelessController_(), unitree_hg_msg_dds__BmsCmd_(), unitree_hg_msg_dds__BmsState_(), unitree_hg_msg_dds__IMUState_(), unitree_hg_msg_dds__MotorCmd_(), unitree_hg_msg_dds__MotorState_(), unitree_hg_msg_dds__MainBoardState_(), unitree_hg_msg_dds__LowCmd_(), unitree_hg_msg_dds__LowState_(), unitree_hg_msg_dds__PressSensorState_(), unitree_hg_msg_dds__HandCmd_(), unitree_hg_msg_dds__HandState_(), unitree_api_msg_dds__RequestIdentity_(), unitree_api_msg_dds__RequestLease_(), unitree_api_msg_dds__RequestPolicy_(), unitree_api_msg_dds__RequestHeader_(), unitree_api_msg_dds__Request_(), unitree_api_msg_dds__ResponseStatus_(), unitree_api_msg_dds__ResponseHeader_(), unitree_api_msg_dds__Response_() | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/__init__.py` | Python 源码 | 9 | 162 B | Python 包初始化文件：标记该目录为可导入包；有些 IDL 子包还集中 re-export 消息类。 | - | - | __all__ |
| `unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/msg/__init__.py` | Python 源码 | 9 | 168 B | Python 包初始化文件：标记该目录为可导入包；有些 IDL 子包还集中 re-export 消息类。 | - | - | __all__ |
| `unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/msg/dds_/_Point32_.py` | Python 源码 | 29 | 635 B | CycloneDDS 生成的 IDL 数据结构 Point32_：定义 DDS 消息字段和类型注解，共 3 个字段。 | Point32_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/msg/dds_/_PointStamped_.py` | Python 源码 | 31 | 760 B | CycloneDDS 生成的 IDL 数据结构 PointStamped_：定义 DDS 消息字段和类型注解，共 2 个字段。 | PointStamped_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/msg/dds_/_Point_.py` | Python 源码 | 29 | 629 B | CycloneDDS 生成的 IDL 数据结构 Point_：定义 DDS 消息字段和类型注解，共 3 个字段。 | Point_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/msg/dds_/_Pose2D_.py` | Python 源码 | 29 | 636 B | CycloneDDS 生成的 IDL 数据结构 Pose2D_：定义 DDS 消息字段和类型注解，共 3 个字段。 | Pose2D_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/msg/dds_/_PoseStamped_.py` | Python 源码 | 32 | 756 B | CycloneDDS 生成的 IDL 数据结构 PoseStamped_：定义 DDS 消息字段和类型注解，共 2 个字段。 | PoseStamped_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/msg/dds_/_PoseWithCovarianceStamped_.py` | Python 源码 | 32 | 812 B | CycloneDDS 生成的 IDL 数据结构 PoseWithCovarianceStamped_：定义 DDS 消息字段和类型注解，共 2 个字段。 | PoseWithCovarianceStamped_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/msg/dds_/_PoseWithCovariance_.py` | Python 源码 | 28 | 712 B | CycloneDDS 生成的 IDL 数据结构 PoseWithCovariance_：定义 DDS 消息字段和类型注解，共 2 个字段。 | PoseWithCovariance_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/msg/dds_/_Pose_.py` | Python 源码 | 28 | 701 B | CycloneDDS 生成的 IDL 数据结构 Pose_：定义 DDS 消息字段和类型注解，共 2 个字段。 | Pose_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/msg/dds_/_QuaternionStamped_.py` | Python 源码 | 32 | 786 B | CycloneDDS 生成的 IDL 数据结构 QuaternionStamped_：定义 DDS 消息字段和类型注解，共 2 个字段。 | QuaternionStamped_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/msg/dds_/_Quaternion_.py` | Python 源码 | 30 | 665 B | CycloneDDS 生成的 IDL 数据结构 Quaternion_：定义 DDS 消息字段和类型注解，共 4 个字段。 | Quaternion_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/msg/dds_/_TwistStamped_.py` | Python 源码 | 32 | 761 B | CycloneDDS 生成的 IDL 数据结构 TwistStamped_：定义 DDS 消息字段和类型注解，共 2 个字段。 | TwistStamped_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/msg/dds_/_TwistWithCovarianceStamped_.py` | Python 源码 | 32 | 817 B | CycloneDDS 生成的 IDL 数据结构 TwistWithCovarianceStamped_：定义 DDS 消息字段和类型注解，共 2 个字段。 | TwistWithCovarianceStamped_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/msg/dds_/_TwistWithCovariance_.py` | Python 源码 | 28 | 717 B | CycloneDDS 生成的 IDL 数据结构 TwistWithCovariance_：定义 DDS 消息字段和类型注解，共 2 个字段。 | TwistWithCovariance_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/msg/dds_/_Twist_.py` | Python 源码 | 28 | 697 B | CycloneDDS 生成的 IDL 数据结构 Twist_：定义 DDS 消息字段和类型注解，共 2 个字段。 | Twist_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/msg/dds_/_Vector3_.py` | Python 源码 | 29 | 635 B | CycloneDDS 生成的 IDL 数据结构 Vector3_：定义 DDS 消息字段和类型注解，共 3 个字段。 | Vector3_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/msg/dds_/__init__.py` | Python 源码 | 23 | 1.0 KB | Python 包初始化文件：标记该目录为可导入包；有些 IDL 子包还集中 re-export 消息类。 | - | - | __all__ |
| `unitree_sdk2_python/unitree_sdk2py/idl/nav_msgs/__init__.py` | Python 源码 | 9 | 157 B | Python 包初始化文件：标记该目录为可导入包；有些 IDL 子包还集中 re-export 消息类。 | - | - | __all__ |
| `unitree_sdk2_python/unitree_sdk2py/idl/nav_msgs/msg/__init__.py` | Python 源码 | 9 | 163 B | Python 包初始化文件：标记该目录为可导入包；有些 IDL 子包还集中 re-export 消息类。 | - | - | __all__ |
| `unitree_sdk2_python/unitree_sdk2py/idl/nav_msgs/msg/dds_/_MapMetaData_.py` | Python 源码 | 35 | 882 B | CycloneDDS 生成的 IDL 数据结构 MapMetaData_：定义 DDS 消息字段和类型注解，共 5 个字段。 | MapMetaData_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/nav_msgs/msg/dds_/_OccupancyGrid_.py` | Python 源码 | 33 | 788 B | CycloneDDS 生成的 IDL 数据结构 OccupancyGrid_：定义 DDS 消息字段和类型注解，共 3 个字段。 | OccupancyGrid_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/nav_msgs/msg/dds_/_Odometry_.py` | Python 源码 | 35 | 882 B | CycloneDDS 生成的 IDL 数据结构 Odometry_：定义 DDS 消息字段和类型注解，共 4 个字段。 | Odometry_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/nav_msgs/msg/dds_/__init__.py` | Python 源码 | 11 | 306 B | Python 包初始化文件：标记该目录为可导入包；有些 IDL 子包还集中 re-export 消息类。 | - | - | __all__ |
| `unitree_sdk2_python/unitree_sdk2py/idl/sensor_msgs/__init__.py` | Python 源码 | 9 | 160 B | Python 包初始化文件：标记该目录为可导入包；有些 IDL 子包还集中 re-export 消息类。 | - | - | __all__ |
| `unitree_sdk2_python/unitree_sdk2py/idl/sensor_msgs/msg/__init__.py` | Python 源码 | 9 | 166 B | Python 包初始化文件：标记该目录为可导入包；有些 IDL 子包还集中 re-export 消息类。 | - | - | __all__ |
| `unitree_sdk2_python/unitree_sdk2py/idl/sensor_msgs/msg/dds_/PointField_Constants/_PointField_.py` | Python 源码 | 28 | 550 B | CycloneDDS 生成的 IDL 数据结构 _PointField_.py：定义 DDS 消息字段和类型注解，共 0 个字段。 | - | - | INT8_, UINT8_, INT16_, UINT16_, INT32_, UINT32_, FLOAT32_, FLOAT64_ |
| `unitree_sdk2_python/unitree_sdk2py/idl/sensor_msgs/msg/dds_/PointField_Constants/__init__.py` | Python 源码 | 9 | 344 B | Python 包初始化文件：标记该目录为可导入包；有些 IDL 子包还集中 re-export 消息类。 | - | - | __all__ |
| `unitree_sdk2_python/unitree_sdk2py/idl/sensor_msgs/msg/dds_/_PointCloud2_.py` | Python 源码 | 39 | 957 B | CycloneDDS 生成的 IDL 数据结构 PointCloud2_：定义 DDS 消息字段和类型注解，共 9 个字段。 | PointCloud2_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/sensor_msgs/msg/dds_/_PointField_.py` | Python 源码 | 30 | 664 B | CycloneDDS 生成的 IDL 数据结构 PointField_：定义 DDS 消息字段和类型注解，共 4 个字段。 | PointField_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/sensor_msgs/msg/dds_/__init__.py` | Python 源码 | 11 | 312 B | Python 包初始化文件：标记该目录为可导入包；有些 IDL 子包还集中 re-export 消息类。 | - | - | __all__ |
| `unitree_sdk2_python/unitree_sdk2py/idl/std_msgs/__init__.py` | Python 源码 | 9 | 157 B | Python 包初始化文件：标记该目录为可导入包；有些 IDL 子包还集中 re-export 消息类。 | - | - | __all__ |
| `unitree_sdk2_python/unitree_sdk2py/idl/std_msgs/msg/__init__.py` | Python 源码 | 9 | 163 B | Python 包初始化文件：标记该目录为可导入包；有些 IDL 子包还集中 re-export 消息类。 | - | - | __all__ |
| `unitree_sdk2_python/unitree_sdk2py/idl/std_msgs/msg/dds_/_Header_.py` | Python 源码 | 32 | 701 B | CycloneDDS 生成的 IDL 数据结构 Header_：定义 DDS 消息字段和类型注解，共 2 个字段。 | Header_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/std_msgs/msg/dds_/_String_.py` | Python 源码 | 27 | 568 B | CycloneDDS 生成的 IDL 数据结构 String_：定义 DDS 消息字段和类型注解，共 1 个字段。 | String_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/std_msgs/msg/dds_/__init__.py` | Python 源码 | 10 | 223 B | Python 包初始化文件：标记该目录为可导入包；有些 IDL 子包还集中 re-export 消息类。 | - | - | __all__ |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_api/__init__.py` | Python 源码 | 9 | 160 B | Python 包初始化文件：标记该目录为可导入包；有些 IDL 子包还集中 re-export 消息类。 | - | - | __all__ |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_api/msg/__init__.py` | Python 源码 | 9 | 166 B | Python 包初始化文件：标记该目录为可导入包；有些 IDL 子包还集中 re-export 消息类。 | - | - | __all__ |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_api/msg/dds_/_RequestHeader_.py` | Python 源码 | 29 | 793 B | CycloneDDS 生成的 IDL 数据结构 RequestHeader_：定义 DDS 消息字段和类型注解，共 3 个字段。 | RequestHeader_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_api/msg/dds_/_RequestIdentity_.py` | Python 源码 | 28 | 634 B | CycloneDDS 生成的 IDL 数据结构 RequestIdentity_：定义 DDS 消息字段和类型注解，共 2 个字段。 | RequestIdentity_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_api/msg/dds_/_RequestLease_.py` | Python 源码 | 27 | 601 B | CycloneDDS 生成的 IDL 数据结构 RequestLease_：定义 DDS 消息字段和类型注解，共 1 个字段。 | RequestLease_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_api/msg/dds_/_RequestPolicy_.py` | Python 源码 | 28 | 628 B | CycloneDDS 生成的 IDL 数据结构 RequestPolicy_：定义 DDS 消息字段和类型注解，共 2 个字段。 | RequestPolicy_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_api/msg/dds_/_Request_.py` | Python 源码 | 28 | 693 B | CycloneDDS 生成的 IDL 数据结构 Request_：定义 DDS 消息字段和类型注解，共 3 个字段。 | Request_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_api/msg/dds_/_ResponseHeader_.py` | Python 源码 | 28 | 730 B | CycloneDDS 生成的 IDL 数据结构 ResponseHeader_：定义 DDS 消息字段和类型注解，共 2 个字段。 | ResponseHeader_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_api/msg/dds_/_ResponseStatus_.py` | Python 源码 | 27 | 609 B | CycloneDDS 生成的 IDL 数据结构 ResponseStatus_：定义 DDS 消息字段和类型注解，共 1 个字段。 | ResponseStatus_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_api/msg/dds_/_Response_.py` | Python 源码 | 28 | 692 B | CycloneDDS 生成的 IDL 数据结构 Response_：定义 DDS 消息字段和类型注解，共 3 个字段。 | Response_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_api/msg/dds_/__init__.py` | Python 源码 | 16 | 616 B | Python 包初始化文件：标记该目录为可导入包；有些 IDL 子包还集中 re-export 消息类。 | - | - | __all__ |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/__init__.py` | Python 源码 | 9 | 159 B | Python 包初始化文件：标记该目录为可导入包；有些 IDL 子包还集中 re-export 消息类。 | - | - | __all__ |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/__init__.py` | Python 源码 | 9 | 165 B | Python 包初始化文件：标记该目录为可导入包；有些 IDL 子包还集中 re-export 消息类。 | - | - | __all__ |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_AudioData_.py` | Python 源码 | 28 | 636 B | CycloneDDS 生成的 IDL 数据结构 AudioData_：定义 DDS 消息字段和类型注解，共 2 个字段。 | AudioData_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_BmsCmd_.py` | Python 源码 | 28 | 622 B | CycloneDDS 生成的 IDL 数据结构 BmsCmd_：定义 DDS 消息字段和类型注解，共 2 个字段。 | BmsCmd_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_BmsState_.py` | Python 源码 | 35 | 844 B | CycloneDDS 生成的 IDL 数据结构 BmsState_：定义 DDS 消息字段和类型注解，共 9 个字段。 | BmsState_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_Error_.py` | Python 源码 | 28 | 606 B | CycloneDDS 生成的 IDL 数据结构 Error_：定义 DDS 消息字段和类型注解，共 2 个字段。 | Error_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_Go2FrontVideoData_.py` | Python 源码 | 30 | 751 B | CycloneDDS 生成的 IDL 数据结构 Go2FrontVideoData_：定义 DDS 消息字段和类型注解，共 4 个字段。 | Go2FrontVideoData_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_HeightMap_.py` | Python 源码 | 33 | 773 B | CycloneDDS 生成的 IDL 数据结构 HeightMap_：定义 DDS 消息字段和类型注解，共 7 个字段。 | HeightMap_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_IMUState_.py` | Python 源码 | 31 | 774 B | CycloneDDS 生成的 IDL 数据结构 IMUState_：定义 DDS 消息字段和类型注解，共 5 个字段。 | IMUState_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_InterfaceConfig_.py` | Python 源码 | 29 | 673 B | CycloneDDS 生成的 IDL 数据结构 InterfaceConfig_：定义 DDS 消息字段和类型注解，共 3 个字段。 | InterfaceConfig_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_LidarState_.py` | Python 源码 | 43 | 1.1 KB | CycloneDDS 生成的 IDL 数据结构 LidarState_：定义 DDS 消息字段和类型注解，共 17 个字段。 | LidarState_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_LowCmd_.py` | Python 源码 | 40 | 1.1 KB | CycloneDDS 生成的 IDL 数据结构 LowCmd_：定义 DDS 消息字段和类型注解，共 14 个字段。 | LowCmd_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_LowState_.py` | Python 源码 | 48 | 1.4 KB | CycloneDDS 生成的 IDL 数据结构 LowState_：定义 DDS 消息字段和类型注解，共 22 个字段。 | LowState_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_MotorCmd_.py` | Python 源码 | 33 | 740 B | CycloneDDS 生成的 IDL 数据结构 MotorCmd_：定义 DDS 消息字段和类型注解，共 7 个字段。 | MotorCmd_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_MotorCmds_.py` | Python 源码 | 23 | 626 B | CycloneDDS 生成的 IDL 数据结构 MotorCmds_：定义 DDS 消息字段和类型注解，共 1 个字段。 | MotorCmds_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_MotorState_.py` | Python 源码 | 37 | 859 B | CycloneDDS 生成的 IDL 数据结构 MotorState_：定义 DDS 消息字段和类型注解，共 11 个字段。 | MotorState_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_MotorStates_.py` | Python 源码 | 23 | 636 B | CycloneDDS 生成的 IDL 数据结构 MotorStates_：定义 DDS 消息字段和类型注解，共 1 个字段。 | MotorStates_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_PathPoint_.py` | Python 源码 | 33 | 734 B | CycloneDDS 生成的 IDL 数据结构 PathPoint_：定义 DDS 消息字段和类型注解，共 7 个字段。 | PathPoint_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_Req_.py` | Python 源码 | 28 | 579 B | CycloneDDS 生成的 IDL 数据结构 Req_：定义 DDS 消息字段和类型注解，共 2 个字段。 | Req_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_Res_.py` | Python 源码 | 29 | 617 B | CycloneDDS 生成的 IDL 数据结构 Res_：定义 DDS 消息字段和类型注解，共 3 个字段。 | Res_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_SportModeState_.py` | Python 源码 | 42 | 1.3 KB | CycloneDDS 生成的 IDL 数据结构 SportModeState_：定义 DDS 消息字段和类型注解，共 16 个字段。 | SportModeState_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_TimeSpec_.py` | Python 源码 | 28 | 613 B | CycloneDDS 生成的 IDL 数据结构 TimeSpec_：定义 DDS 消息字段和类型注解，共 2 个字段。 | TimeSpec_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_UwbState_.py` | Python 源码 | 43 | 1.1 KB | CycloneDDS 生成的 IDL 数据结构 UwbState_：定义 DDS 消息字段和类型注解，共 17 个字段。 | UwbState_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_UwbSwitch_.py` | Python 源码 | 27 | 594 B | CycloneDDS 生成的 IDL 数据结构 UwbSwitch_：定义 DDS 消息字段和类型注解，共 1 个字段。 | UwbSwitch_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_WirelessController_.py` | Python 源码 | 31 | 707 B | CycloneDDS 生成的 IDL 数据结构 WirelessController_：定义 DDS 消息字段和类型注解，共 5 个字段。 | WirelessController_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/__init__.py` | Python 源码 | 31 | 1.3 KB | Python 包初始化文件：标记该目录为可导入包；有些 IDL 子包还集中 re-export 消息类。 | - | - | __all__ |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_hg/.idlpy_manifest` | IDL 生成清单 | 43 | 187 B | CycloneDDS idlc Python 后端生成清单：记录该 IDL 包/目录的生成元数据。 | - | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_hg/__init__.py` | Python 源码 | 9 | 159 B | Python 包初始化文件：标记该目录为可导入包；有些 IDL 子包还集中 re-export 消息类。 | - | - | __all__ |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_hg/msg/.idlpy_manifest` | IDL 生成清单 | 43 | 198 B | CycloneDDS idlc Python 后端生成清单：记录该 IDL 包/目录的生成元数据。 | - | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_hg/msg/__init__.py` | Python 源码 | 9 | 165 B | Python 包初始化文件：标记该目录为可导入包；有些 IDL 子包还集中 re-export 消息类。 | - | - | __all__ |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_hg/msg/dds_/.idlpy_manifest` | IDL 生成清单 | 43 | 265 B | CycloneDDS idlc Python 后端生成清单：记录该 IDL 包/目录的生成元数据。 | - | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_hg/msg/dds_/_BmsCmd_.py` | Python 源码 | 28 | 623 B | CycloneDDS 生成的 IDL 数据结构 BmsCmd_：定义 DDS 消息字段和类型注解，共 2 个字段。 | BmsCmd_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_hg/msg/dds_/_BmsState_.py` | Python 源码 | 39 | 992 B | CycloneDDS 生成的 IDL 数据结构 BmsState_：定义 DDS 消息字段和类型注解，共 13 个字段。 | BmsState_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_hg/msg/dds_/_HandCmd_.py` | Python 源码 | 28 | 687 B | CycloneDDS 生成的 IDL 数据结构 HandCmd_：定义 DDS 消息字段和类型注解，共 2 个字段。 | HandCmd_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_hg/msg/dds_/_HandState_.py` | Python 源码 | 35 | 1012 B | CycloneDDS 生成的 IDL 数据结构 HandState_：定义 DDS 消息字段和类型注解，共 9 个字段。 | HandState_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_hg/msg/dds_/_IMUState_.py` | Python 源码 | 31 | 774 B | CycloneDDS 生成的 IDL 数据结构 IMUState_：定义 DDS 消息字段和类型注解，共 5 个字段。 | IMUState_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_hg/msg/dds_/_LowCmd_.py` | Python 源码 | 31 | 762 B | CycloneDDS 生成的 IDL 数据结构 LowCmd_：定义 DDS 消息字段和类型注解，共 5 个字段。 | LowCmd_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_hg/msg/dds_/_LowState_.py` | Python 源码 | 35 | 953 B | CycloneDDS 生成的 IDL 数据结构 LowState_：定义 DDS 消息字段和类型注解，共 9 个字段。 | LowState_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_hg/msg/dds_/_MainBoardState_.py` | Python 源码 | 30 | 754 B | CycloneDDS 生成的 IDL 数据结构 MainBoardState_：定义 DDS 消息字段和类型注解，共 4 个字段。 | MainBoardState_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_hg/msg/dds_/_MotorCmd_.py` | Python 源码 | 33 | 724 B | CycloneDDS 生成的 IDL 数据结构 MotorCmd_：定义 DDS 消息字段和类型注解，共 7 个字段。 | MotorCmd_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_hg/msg/dds_/_MotorState_.py` | Python 源码 | 36 | 867 B | CycloneDDS 生成的 IDL 数据结构 MotorState_：定义 DDS 消息字段和类型注解，共 10 个字段。 | MotorState_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_hg/msg/dds_/_PressSensorState_.py` | Python 源码 | 30 | 732 B | CycloneDDS 生成的 IDL 数据结构 PressSensorState_：定义 DDS 消息字段和类型注解，共 4 个字段。 | PressSensorState_(idl.IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_hg/msg/dds_/__init__.py` | Python 源码 | 19 | 696 B | Python 包初始化文件：标记该目录为可导入包；有些 IDL 子包还集中 re-export 消息类。 | - | - | __all__ |
| `unitree_sdk2_python/unitree_sdk2py/rpc/__init__.py` | Python 源码 | 0 | 0 B | Python 包初始化文件：标记该目录为可导入包；有些 IDL 子包还集中 re-export 消息类。 | - | - | - |
| `unitree_sdk2_python/unitree_sdk2py/rpc/client.py` | Python 源码 | 111 | 3.9 KB | 高层 RPC Client：维护 API 注册表、API 版本、可选租约 Client，并在调用前检查 API 是否注册。 | Client(ClientBase) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/rpc/client_base.py` | Python 源码 | 128 | 5.0 KB | RPC 客户端基础调用层：构造 RequestHeader/Request/二进制请求，等待 Future 响应，处理超时、API 不匹配和错误码。 | ClientBase | - | - |
| `unitree_sdk2_python/unitree_sdk2py/rpc/client_stub.py` | Python 源码 | 69 | 2.3 KB | RPC 客户端 DDS stub：创建 request 发送通道和 response 接收通道，用 RequestFutureQueue 按请求 ID 匹配响应。 | ClientStub | - | - |
| `unitree_sdk2_python/unitree_sdk2py/rpc/internal.py` | Python 源码 | 31 | 743 B | RPC 内部常量：内部 API、租约 API、默认租约时长以及客户端/服务端错误码。 | - | - | RPC_INTERNAL_API_ID_MAX, RPC_API_ID_INTERNAL_API_VERSION, RPC_API_ID_LEASE_APPLY, RPC_API_ID_LEASE_RENEWAL, RPC_LEASE_TERM, RPC_OK, RPC_ERR_UNKNOWN, RPC_ERR_CLIENT_SEND, RPC_ERR_CLIENT_API_NOT_REG, RPC_ERR_CLIENT_API_TIMEOUT, RPC_ERR_CLIENT_API_NOT_MATCH, RPC_ERR_CLIENT_API_DATA ... 共20个 |
| `unitree_sdk2_python/unitree_sdk2py/rpc/lease_client.py` | Python 源码 | 113 | 2.8 KB | RPC 客户端封装：继承/使用 Client，将业务方法转成 JSON 参数或二进制请求发送到机器人服务；公开方法 7 个。 | LeaseContext; LeaseClient(ClientBase) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/rpc/lease_server.py` | Python 源码 | 151 | 4.1 KB | 租约服务端：只允许一个活跃租约，处理 apply/renewal，并在过期后释放。 | LeaseCache; LeaseServer(ServerBase) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/rpc/request_future.py` | Python 源码 | 46 | 1.1 KB | 请求 Future 队列：保存待响应请求并在 response 到达时唤醒等待线程。 | RequestFuture(Future); RequestFutureQueue | - | - |
| `unitree_sdk2_python/unitree_sdk2py/rpc/server.py` | Python 源码 | 122 | 4.0 KB | 高层 RPC Server：注册字符串/二进制 API handler，处理内部版本查询、租约校验、异常捕获并回发 Response。 | Server(ServerBase) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/rpc/server_base.py` | Python 源码 | 32 | 991 B | RPC 服务端基类：保存服务名，启动 ServerStub，提供发送 Response 的基础方法。 | ServerBase | - | - |
| `unitree_sdk2_python/unitree_sdk2py/rpc/server_stub.py` | Python 源码 | 78 | 2.6 KB | RPC 服务端 DDS stub：创建 request 接收通道和 response 发送通道，用普通队列/优先队列线程分发请求。 | ServerStub | - | - |
| `unitree_sdk2_python/unitree_sdk2py/test/client/obstacles_avoid_client_example.py` | Python 源码 | 91 | 2.7 KB | 开发/测试脚本：验证对应客户端、RPC、CRC、低层 DDS 或 hello world 通信路径。 | - | - | - |
| `unitree_sdk2_python/unitree_sdk2py/test/client/robot_service_client_example.py` | Python 源码 | 50 | 1.6 KB | 开发/测试脚本：验证对应客户端、RPC、CRC、低层 DDS 或 hello world 通信路径。 | - | - | - |
| `unitree_sdk2_python/unitree_sdk2py/test/client/sport_client_example.py` | Python 源码 | 109 | 3.1 KB | 开发/测试脚本：验证对应客户端、RPC、CRC、低层 DDS 或 hello world 通信路径。 | - | - | - |
| `unitree_sdk2_python/unitree_sdk2py/test/client/video_client_example.py` | Python 源码 | 26 | 724 B | 开发/测试脚本：验证对应客户端、RPC、CRC、低层 DDS 或 hello world 通信路径。 | - | - | - |
| `unitree_sdk2_python/unitree_sdk2py/test/client/vui_client_example.py` | Python 源码 | 74 | 1.8 KB | 开发/测试脚本：验证对应客户端、RPC、CRC、低层 DDS 或 hello world 通信路径。 | - | - | - |
| `unitree_sdk2_python/unitree_sdk2py/test/crc/test_crc.py` | Python 源码 | 27 | 715 B | 开发/测试脚本：验证对应客户端、RPC、CRC、低层 DDS 或 hello world 通信路径。 | - | - | - |
| `unitree_sdk2_python/unitree_sdk2py/test/helloworld/helloworld.py` | Python 源码 | 6 | 148 B | 开发/测试脚本：验证对应客户端、RPC、CRC、低层 DDS 或 hello world 通信路径。 | HelloWorld(IdlStruct) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/test/helloworld/publisher.py` | Python 源码 | 22 | 500 B | 开发/测试脚本：验证对应客户端、RPC、CRC、低层 DDS 或 hello world 通信路径。 | - | - | - |
| `unitree_sdk2_python/unitree_sdk2py/test/helloworld/subscriber.py` | Python 源码 | 19 | 373 B | 开发/测试脚本：验证对应客户端、RPC、CRC、低层 DDS 或 hello world 通信路径。 | - | - | - |
| `unitree_sdk2_python/unitree_sdk2py/test/lowlevel/lowlevel_control.py` | Python 源码 | 51 | 1.9 KB | 开发/测试脚本：验证对应客户端、RPC、CRC、低层 DDS 或 hello world 通信路径。 | - | - | - |
| `unitree_sdk2_python/unitree_sdk2py/test/lowlevel/read_lowstate.py` | Python 源码 | 24 | 784 B | 开发/测试脚本：验证对应客户端、RPC、CRC、低层 DDS 或 hello world 通信路径。 | - | LowStateHandler(msg) | - |
| `unitree_sdk2_python/unitree_sdk2py/test/lowlevel/sub_lowstate.py` | Python 源码 | 15 | 448 B | 开发/测试脚本：验证对应客户端、RPC、CRC、低层 DDS 或 hello world 通信路径。 | - | LowStateHandler(msg) | - |
| `unitree_sdk2_python/unitree_sdk2py/test/lowlevel/unitree_go2_const.py` | Python 源码 | 20 | 345 B | 开发/测试脚本：验证对应客户端、RPC、CRC、低层 DDS 或 hello world 通信路径。 | - | - | LegID, HIGHLEVEL, LOWLEVEL, TRIGERLEVEL |
| `unitree_sdk2_python/unitree_sdk2py/test/rpc/test_api.py` | Python 源码 | 9 | 143 B | 服务 API 常量文件：定义服务名 TEST_SERVICE_NAME、版本 TEST_API_VERSION、2 个接口 ID/错误码，供对应 client 注册和调用。 | - | - | TEST_SERVICE_NAME, TEST_API_VERSION, TEST_API_ID_MOVE, TEST_API_ID_STOP |
| `unitree_sdk2_python/unitree_sdk2py/test/rpc/test_client_example.py` | Python 源码 | 62 | 1.5 KB | RPC 支撑模块。 | TestClient(Client) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/test/rpc/test_server_example.py` | Python 源码 | 45 | 1017 B | RPC 支撑模块。 | TestServer(Server) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/utils/__init__.py` | Python 源码 | 0 | 0 B | Python 包初始化文件：标记该目录为可导入包；有些 IDL 子包还集中 re-export 消息类。 | - | - | - |
| `unitree_sdk2_python/unitree_sdk2py/utils/bqueue.py` | Python 源码 | 58 | 1.6 KB | 有界阻塞队列：支持 Put/Get/Clear/Size/Interrupt，可选择满队列时替换旧元素。 | BQueue | - | - |
| `unitree_sdk2_python/unitree_sdk2py/utils/clib_lookup.py` | Python 源码 | 17 | 386 B | C 标准库函数查找器：通过 ctypes.CDLL(None) 绑定 libc 函数并设置参数/返回类型。 | - | CLIBCheckError(ret, func, args), CLIBLookup(name, resType, argTypes) | - |
| `unitree_sdk2_python/unitree_sdk2py/utils/crc.py` | Python 源码 | 228 | 8.4 KB | CRC 计算器：按 Unitree Go/HG 低层消息内存布局 pack 字段，Linux 上调用预编译 so，其他平台用 Python CRC32。 | CRC(Singleton) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/utils/future.py` | Python 源码 | 104 | 2.9 KB | Future/Condition 同步原语：表示 deferred/ready/failed 状态，支持等待结果、成功和失败通知。 | FutureState(Enum); FutureResult; Future | - | - |
| `unitree_sdk2_python/unitree_sdk2py/utils/hz_sample.py` | Python 源码 | 24 | 643 B | 频率采样器：根据连续触发次数和时间跨度估算 Hz。 | HZSample | - | - |
| `unitree_sdk2_python/unitree_sdk2py/utils/joystick.py` | Python 源码 | 251 | 8.0 KB | 手柄状态模型：解析/合成 Unitree wireless_remote 40 字节数据，支持 pygame Logitech F710 映射、按键边沿和连击计数。 | Button; Axis; Joystick; PyGameJoystick(Joystick); LogicJoystick(PyGameJoystick) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/utils/lib/crc_aarch64.so` | Linux 共享库 | 29 | 7.7 KB | 预编译 CRC 动态库：供 utils.crc 通过 ctypes 调用，在 Linux 上加速低层命令/状态消息 CRC32 计算。 | - | - | - |
| `unitree_sdk2_python/unitree_sdk2py/utils/lib/crc_amd64.so` | Linux 共享库 | 33 | 14.8 KB | 预编译 CRC 动态库：供 utils.crc 通过 ctypes 调用，在 Linux 上加速低层命令/状态消息 CRC32 计算。 | - | - | - |
| `unitree_sdk2_python/unitree_sdk2py/utils/singleton.py` | Python 源码 | 11 | 247 B | 单例基类：重写 __new__，确保继承类只有一个实例。 | Singleton | - | - |
| `unitree_sdk2_python/unitree_sdk2py/utils/thread.py` | Python 源码 | 83 | 2.6 KB | 线程 Future 封装：普通线程返回 FutureResult，RecurrentThread 用 timerfd 定频循环执行任务。 | Thread(Future); RecurrentThread(Thread) | - | - |
| `unitree_sdk2_python/unitree_sdk2py/utils/timerfd.py` | Python 源码 | 45 | 1.3 KB | Linux timerfd ctypes 绑定：定义 timespec/itimerspec 和 timerfd_create/settime/gettime。 | timespec(ctypes.Structure); itimerspec(ctypes.Structure) | - | - |

## 5. 核心架构说明

| 层级 | 关键文件 | 职责细节 |
|---|---|---|
| DDS 通道层 | `unitree_sdk2py/core/channel.py`, `channel_config.py`, `channel_name.py` | 初始化 CycloneDDS 域和参与者；按网卡或自动策略生成 XML 配置；创建 Topic；封装 writer 写入超时等待和 reader 同步读取/异步回调；回调用 `BQueue` 可做队列缓冲；定义 RPC topic 命名规则。 |
| RPC 客户端层 | `rpc/client_base.py`, `client.py`, `client_stub.py`, `request_future.py` | 业务 client 先注册 API ID；调用时构造 `RequestHeader(identity, lease, policy)` 与 JSON/binary 参数；`ClientStub` 发布 request 并订阅 response；`RequestFutureQueue` 按 monotonic_ns 请求 ID 匹配 response；统一处理发送失败、超时、API 不匹配。 |
| RPC 服务端层 | `rpc/server_base.py`, `server.py`, `server_stub.py` | 服务端订阅 request topic，普通队列和可选优先队列分发；注册字符串 handler 或 binary handler；自动处理内部 API version 查询、租约校验、异常转错误码和 response 回发。 |
| 租约机制 | `rpc/lease_client.py`, `rpc/lease_server.py`, `rpc/internal.py` | 服务名后加 `_lease` 形成租约服务；客户端用 `hostname/service/pid` 申请并周期续约；服务端只保存一个有效 lease，过期释放；受租约保护 API 会检查 leaseId。 |
| IDL 消息层 | `unitree_sdk2py/idl/**` | CycloneDDS idlc 生成 dataclass/IdlStruct，描述标准 ROS 风格消息、Unitree API request/response、四足 `unitree_go` 消息、人形 `unitree_hg` 消息。 |
| 工具层 | `utils/*` | CRC 按低层协议字段顺序打包并调用 `.so`/Python 实现；future/queue/thread 支撑异步；timerfd 支撑定频线程；joystick 解析遥控器 40 字节数组。 |

## 6. 服务 API 常量表

| API 文件 | 服务名 | 版本 | API ID | 错误码 |
|---|---|---|---|---|
| `unitree_sdk2_python/unitree_sdk2py/b2/back_video/back_video_api.py` | `ROBOT_BACK_VIDEO_SERVICE_NAME='back_videohub'` | `ROBOT_BACK_VIDEO_API_VERSION='1.0.0.0'` | `ROBOT_BACK_VIDEO_API_ID_GETIMAGESAMPLE=1001` | - |
| `unitree_sdk2_python/unitree_sdk2py/b2/front_video/front_video_api.py` | `ROBOT_FRONT_VIDEO_SERVICE_NAME='front_videohub'` | `ROBOT_FRONT_VIDEO_API_VERSION='1.0.0.0'` | `ROBOT_FRONT_VIDEO_API_ID_GETIMAGESAMPLE=1001` | - |
| `unitree_sdk2_python/unitree_sdk2py/b2/robot_state/robot_state_api.py` | `ROBOT_STATE_SERVICE_NAME='robot_state'` | `ROBOT_STATE_API_VERSION='1.0.0.1'` | `ROBOT_STATE_API_ID_SERVICE_SWITCH=1001`<br>`ROBOT_STATE_API_ID_REPORT_FREQ=1002`<br>`ROBOT_STATE_API_ID_SERVICE_LIST=1003` | `ROBOT_STATE_ERR_SERVICE_SWITCH=5201`<br>`ROBOT_STATE_ERR_SERVICE_PROTECTED=5202` |
| `unitree_sdk2_python/unitree_sdk2py/b2/sport/sport_api.py` | `SPORT_SERVICE_NAME='sport'` | `SPORT_API_VERSION='1.0.0.1'` | `ROBOT_SPORT_API_ID_DAMP=1001`<br>`ROBOT_SPORT_API_ID_BALANCESTAND=1002`<br>`ROBOT_SPORT_API_ID_STOPMOVE=1003`<br>`ROBOT_SPORT_API_ID_STANDUP=1004`<br>`ROBOT_SPORT_API_ID_STANDDOWN=1005`<br>`ROBOT_SPORT_API_ID_RECOVERYSTAND=1006`<br>`ROBOT_SPORT_API_ID_MOVE=1008`<br>`ROBOT_SPORT_API_ID_SWITCHGAIT=1011`<br>`ROBOT_SPORT_API_ID_BODYHEIGHT=1013`<br>`ROBOT_SPORT_API_ID_SPEEDLEVEL=1015`<br>`ROBOT_SPORT_API_ID_TRAJECTORYFOLLOW=1018`<br>`ROBOT_SPORT_API_ID_CONTINUOUSGAIT=1019`<br>`ROBOT_SPORT_API_ID_MOVETOPOS=1036`<br>`ROBOT_SPORT_API_ID_SWITCHMOVEMODE=1038`<br>`ROBOT_SPORT_API_ID_VISIONWALK=1101`<br>`ROBOT_SPORT_API_ID_HANDSTAND=1039`<br>`ROBOT_SPORT_API_ID_AUTORECOVERY_SET=1040`<br>`ROBOT_SPORT_API_ID_FREEWALK=1045`<br>`ROBOT_SPORT_API_ID_CLASSICWALK=1049`<br>`ROBOT_SPORT_API_ID_FASTWALK=1050`<br>`ROBOT_SPORT_API_ID_FREEEULER=1051` | `SPORT_ERR_CLIENT_POINT_PATH=4101`<br>`SPORT_ERR_SERVER_OVERTIME=4201`<br>`SPORT_ERR_SERVER_NOT_INIT=4202` |
| `unitree_sdk2_python/unitree_sdk2py/b2/vui/vui_api.py` | `VUI_SERVICE_NAME='vui'` | `VUI_API_VERSION='1.0.0.1'` | `VUI_API_ID_SETSWITCH=1001`<br>`VUI_API_ID_GETSWITCH=1002`<br>`VUI_API_ID_SETVOLUME=1003`<br>`VUI_API_ID_GETVOLUME=1004`<br>`VUI_API_ID_SETBRIGHTNESS=1005`<br>`VUI_API_ID_GETBRIGHTNESS=1006` | - |
| `unitree_sdk2_python/unitree_sdk2py/comm/motion_switcher/motion_switcher_api.py` | `MOTION_SWITCHER_SERVICE_NAME='motion_switcher'` | `MOTION_SWITCHER_API_VERSION='1.0.0.1'` | `MOTION_SWITCHER_API_ID_CHECK_MODE=1001`<br>`MOTION_SWITCHER_API_ID_SELECT_MODE=1002`<br>`MOTION_SWITCHER_API_ID_RELEASE_MODE=1003`<br>`MOTION_SWITCHER_API_ID_SET_SILENT=1004`<br>`MOTION_SWITCHER_API_ID_GET_SILENT=1005` | - |
| `unitree_sdk2_python/unitree_sdk2py/g1/arm/g1_arm_action_api.py` | `ARM_ACTION_SERVICE_NAME='arm'` | `ARM_ACTION_API_VERSION='1.0.0.14'` | `ROBOT_API_ID_ARM_ACTION_EXECUTE_ACTION=7106`<br>`ROBOT_API_ID_ARM_ACTION_GET_ACTION_LIST=7107` | - |
| `unitree_sdk2_python/unitree_sdk2py/g1/audio/g1_audio_api.py` | `AUDIO_SERVICE_NAME='voice'` | `AUDIO_API_VERSION='1.0.0.0'` | `ROBOT_API_ID_AUDIO_TTS=1001`<br>`ROBOT_API_ID_AUDIO_ASR=1002`<br>`ROBOT_API_ID_AUDIO_START_PLAY=1003`<br>`ROBOT_API_ID_AUDIO_STOP_PLAY=1004`<br>`ROBOT_API_ID_AUDIO_GET_VOLUME=1005`<br>`ROBOT_API_ID_AUDIO_SET_VOLUME=1006`<br>`ROBOT_API_ID_AUDIO_SET_RGB_LED=1010` | - |
| `unitree_sdk2_python/unitree_sdk2py/g1/loco/g1_loco_api.py` | `LOCO_SERVICE_NAME='sport'` | `LOCO_API_VERSION='1.0.0.0'` | `ROBOT_API_ID_LOCO_GET_FSM_ID=7001`<br>`ROBOT_API_ID_LOCO_GET_FSM_MODE=7002`<br>`ROBOT_API_ID_LOCO_GET_BALANCE_MODE=7003`<br>`ROBOT_API_ID_LOCO_GET_SWING_HEIGHT=7004`<br>`ROBOT_API_ID_LOCO_GET_STAND_HEIGHT=7005`<br>`ROBOT_API_ID_LOCO_GET_PHASE=7006`<br>`ROBOT_API_ID_LOCO_SET_FSM_ID=7101`<br>`ROBOT_API_ID_LOCO_SET_BALANCE_MODE=7102`<br>`ROBOT_API_ID_LOCO_SET_SWING_HEIGHT=7103`<br>`ROBOT_API_ID_LOCO_SET_STAND_HEIGHT=7104`<br>`ROBOT_API_ID_LOCO_SET_VELOCITY=7105`<br>`ROBOT_API_ID_LOCO_SET_ARM_TASK=7106` | - |
| `unitree_sdk2_python/unitree_sdk2py/go2/obstacles_avoid/obstacles_avoid_api.py` | `OBSTACLES_AVOID_SERVICE_NAME='obstacles_avoid'` | `OBSTACLES_AVOID_API_VERSION='1.0.0.2'` | `OBSTACLES_AVOID_API_ID_SWITCH_SET=1001`<br>`OBSTACLES_AVOID_API_ID_SWITCH_GET=1002`<br>`OBSTACLES_AVOID_API_ID_MOVE=1003`<br>`OBSTACLES_AVOID_API_ID_USE_REMOTE_COMMAND_FROM_API=1004` | - |
| `unitree_sdk2_python/unitree_sdk2py/go2/robot_state/robot_state_api.py` | `ROBOT_STATE_SERVICE_NAME='robot_state'` | `ROBOT_STATE_API_VERSION='1.0.0.1'` | `ROBOT_STATE_API_ID_SERVICE_SWITCH=1001`<br>`ROBOT_STATE_API_ID_REPORT_FREQ=1002`<br>`ROBOT_STATE_API_ID_SERVICE_LIST=1003` | `ROBOT_STATE_ERR_SERVICE_SWITCH=5201`<br>`ROBOT_STATE_ERR_SERVICE_PROTECTED=5202` |
| `unitree_sdk2_python/unitree_sdk2py/go2/sport/sport_api.py` | `SPORT_SERVICE_NAME='sport'` | `SPORT_API_VERSION='1.0.0.1'` | `SPORT_API_ID_DAMP=1001`<br>`SPORT_API_ID_BALANCESTAND=1002`<br>`SPORT_API_ID_STOPMOVE=1003`<br>`SPORT_API_ID_STANDUP=1004`<br>`SPORT_API_ID_STANDDOWN=1005`<br>`SPORT_API_ID_RECOVERYSTAND=1006`<br>`SPORT_API_ID_EULER=1007`<br>`SPORT_API_ID_MOVE=1008`<br>`SPORT_API_ID_SIT=1009`<br>`SPORT_API_ID_RISESIT=1010`<br>`SPORT_API_ID_SPEEDLEVEL=1015`<br>`SPORT_API_ID_HELLO=1016`<br>`SPORT_API_ID_STRETCH=1017`<br>`SPORT_API_ID_CONTENT=1020`<br>`SPORT_API_ID_DANCE1=1022`<br>`SPORT_API_ID_DANCE2=1023`<br>`SPORT_API_ID_SWITCHJOYSTICK=1027`<br>`SPORT_API_ID_POSE=1028`<br>`SPORT_API_ID_SCRAPE=1029`<br>`SPORT_API_ID_FRONTFLIP=1030`<br>`SPORT_API_ID_FRONTJUMP=1031`<br>`SPORT_API_ID_FRONTPOUNCE=1032`<br>`SPORT_API_ID_HEART=1036`<br>`SPORT_API_ID_STATICWALK=1061`<br>`SPORT_API_ID_TROTRUN=1062`<br>`SPORT_API_ID_ECONOMICGAIT=1063`<br>`SPORT_API_ID_LEFTFLIP=2041`<br>`SPORT_API_ID_BACKFLIP=2043`<br>`SPORT_API_ID_HANDSTAND=2044`<br>`SPORT_API_ID_FREEWALK=2045`<br>`SPORT_API_ID_FREEBOUND=2046`<br>`SPORT_API_ID_FREEJUMP=2047`<br>`SPORT_API_ID_FREEAVOID=2048`<br>`SPORT_API_ID_CLASSICWALK=2049`<br>`SPORT_API_ID_WALKUPRIGHT=2050`<br>`SPORT_API_ID_CROSSSTEP=2051`<br>`SPORT_API_ID_AUTORECOVERY_SET=2054`<br>`SPORT_API_ID_AUTORECOVERY_GET=2055`<br>`SPORT_API_ID_SWITCHAVOIDMODE=2058` | `SPORT_ERR_CLIENT_POINT_PATH=4101`<br>`SPORT_ERR_SERVER_OVERTIME=4201`<br>`SPORT_ERR_SERVER_NOT_INIT=4202` |
| `unitree_sdk2_python/unitree_sdk2py/go2/video/video_api.py` | `VIDEO_SERVICE_NAME='videohub'` | `VIDEO_API_VERSION='1.0.0.1'` | `VIDEO_API_ID_GETIMAGESAMPLE=1001` | - |
| `unitree_sdk2_python/unitree_sdk2py/go2/vui/vui_api.py` | `VUI_SERVICE_NAME='vui'` | `VUI_API_VERSION='1.0.0.1'` | `VUI_API_ID_SETSWITCH=1001`<br>`VUI_API_ID_GETSWITCH=1002`<br>`VUI_API_ID_SETVOLUME=1003`<br>`VUI_API_ID_GETVOLUME=1004`<br>`VUI_API_ID_SETBRIGHTNESS=1005`<br>`VUI_API_ID_GETBRIGHTNESS=1006` | - |
| `unitree_sdk2_python/unitree_sdk2py/h1/loco/h1_loco_api.py` | `LOCO_SERVICE_NAME='loco'` | `LOCO_API_VERSION='2.0.0.0'` | `ROBOT_API_ID_LOCO_GET_FSM_ID=8001`<br>`ROBOT_API_ID_LOCO_GET_FSM_MODE=8002`<br>`ROBOT_API_ID_LOCO_GET_BALANCE_MODE=8003`<br>`ROBOT_API_ID_LOCO_GET_SWING_HEIGHT=8004`<br>`ROBOT_API_ID_LOCO_GET_STAND_HEIGHT=8005`<br>`ROBOT_API_ID_LOCO_GET_PHASE=8006`<br>`ROBOT_API_ID_LOCO_SET_FSM_ID=8101`<br>`ROBOT_API_ID_LOCO_SET_BALANCE_MODE=8102`<br>`ROBOT_API_ID_LOCO_SET_SWING_HEIGHT=8103`<br>`ROBOT_API_ID_LOCO_SET_STAND_HEIGHT=8104`<br>`ROBOT_API_ID_LOCO_SET_VELOCITY=8105` | - |
| `unitree_sdk2_python/unitree_sdk2py/h2/loco/h2_loco_api.py` | `LOCO_SERVICE_NAME='sport'` | `LOCO_API_VERSION='1.0.0.0'` | `ROBOT_API_ID_LOCO_GET_FSM_ID=7001`<br>`ROBOT_API_ID_LOCO_GET_FSM_MODE=7002`<br>`ROBOT_API_ID_LOCO_GET_BALANCE_MODE=7003`<br>`ROBOT_API_ID_LOCO_GET_SWING_HEIGHT=7004`<br>`ROBOT_API_ID_LOCO_GET_STAND_HEIGHT=7005`<br>`ROBOT_API_ID_LOCO_GET_PHASE=7006`<br>`ROBOT_API_ID_LOCO_GET_ARM_SDK_STATUS=7007`<br>`ROBOT_API_ID_LOCO_GET_AVAILABLE_FSM_IDS=7008`<br>`ROBOT_API_ID_LOCO_SET_FSM_ID=7101`<br>`ROBOT_API_ID_LOCO_SET_BALANCE_MODE=7102`<br>`ROBOT_API_ID_LOCO_SET_SWING_HEIGHT=7103`<br>`ROBOT_API_ID_LOCO_SET_STAND_HEIGHT=7104`<br>`ROBOT_API_ID_LOCO_SET_VELOCITY=7105`<br>`ROBOT_API_ID_LOCO_SET_ARM_TASK=7106`<br>`ROBOT_API_ID_LOCO_SET_SPEED_MODE=7107`<br>`ROBOT_API_ID_LOCO_SET_PUNCH_API=7108`<br>`ROBOT_API_ID_LOCO_SET_ARM_SDK_STATUS=7109` | - |
| `unitree_sdk2_python/unitree_sdk2py/test/rpc/test_api.py` | `TEST_SERVICE_NAME='test'` | `TEST_API_VERSION='1.0.0.1'` | `TEST_API_ID_MOVE=1008`<br>`TEST_API_ID_STOP=1002` | - |

## 7. Client 方法明细表

| Client 文件 | 类 | 公开方法/作用入口 |
|---|---|---|
| `unitree_sdk2_python/example/b2/high_level/b2_sport_client.py` | `TestOption, UserInterface` | `convert_to_int(self, input_str)`<br>`terminal_handle(self)` |
| `unitree_sdk2_python/example/b2w/high_level/b2w_sport_client.py` | `TestOption, UserInterface` | `convert_to_int(self, input_str)`<br>`terminal_handle(self)` |
| `unitree_sdk2_python/example/go2/high_level/go2_sport_client.py` | `TestOption, UserInterface` | `convert_to_int(self, input_str)`<br>`terminal_handle(self)` |
| `unitree_sdk2_python/example/go2w/high_level/go2w_sport_client.py` | `TestOption, UserInterface` | `convert_to_int(self, input_str)`<br>`terminal_handle(self)` |
| `unitree_sdk2_python/unitree_sdk2py/b2/back_video/back_video_client.py` | `BackVideoClient` | `Init(self)`<br>`GetImageSample(self)` |
| `unitree_sdk2_python/unitree_sdk2py/b2/front_video/front_video_client.py` | `FrontVideoClient` | `Init(self)`<br>`GetImageSample(self)` |
| `unitree_sdk2_python/unitree_sdk2py/b2/robot_state/robot_state_client.py` | `ServiceState, RobotStateClient` | `Init(self)`<br>`ServiceList(self)`<br>`ServiceSwitch(self, name, switch)`<br>`SetReportFreq(self, interval, duration)` |
| `unitree_sdk2_python/unitree_sdk2py/b2/sport/sport_client.py` | `PathPoint, SportClient` | `Init(self)`<br>`Damp(self)`<br>`BalanceStand(self)`<br>`StopMove(self)`<br>`StandUp(self)`<br>`StandDown(self)`<br>`RecoveryStand(self)`<br>`Move(self, vx, vy, vyaw)`<br>`SwitchGait(self, t)`<br>`BodyHeight(self, height)`<br>`SpeedLevel(self, level)`<br>`TrajectoryFollow(self, path)`<br>`ContinuousGait(self, flag)`<br>`MoveToPos(self, x, y, yaw)`<br>`SwitchMoveMode(self, flag)`<br>`VisionWalk(self, flag)`<br>`HandStand(self, flag)`<br>`AutoRecoverySet(self, flag)`<br>`FreeWalk(self)`<br>`ClassicWalk(self, flag)`<br>`FastWalk(self, flag)`<br>`FreeEuler(self, flag)` |
| `unitree_sdk2_python/unitree_sdk2py/b2/vui/vui_client.py` | `VuiClient` | `Init(self)`<br>`SetSwitch(self, enable)`<br>`GetSwitch(self)`<br>`SetVolume(self, level)`<br>`GetVolume(self)`<br>`SetBrightness(self, level)`<br>`GetBrightness(self)` |
| `unitree_sdk2_python/unitree_sdk2py/comm/motion_switcher/motion_switcher_client.py` | `MotionSwitcherClient` | `Init(self)`<br>`CheckMode(self)`<br>`SelectMode(self, nameOrAlias)`<br>`ReleaseMode(self)` |
| `unitree_sdk2_python/unitree_sdk2py/g1/arm/g1_arm_action_client.py` | `G1ArmActionClient` | `Init(self)`<br>`ExecuteAction(self, action_id)`<br>`GetActionList(self)` |
| `unitree_sdk2_python/unitree_sdk2py/g1/audio/g1_audio_client.py` | `AudioClient` | `Init(self)`<br>`TtsMaker(self, text, speaker_id)`<br>`GetVolume(self)`<br>`SetVolume(self, volume)`<br>`LedControl(self, R, G, B)`<br>`PlayStream(self, app_name, stream_id, pcm_data)`<br>`PlayStop(self, app_name)` |
| `unitree_sdk2_python/unitree_sdk2py/g1/loco/g1_loco_client.py` | `LocoClient` | `Init(self)`<br>`SetFsmId(self, fsm_id)`<br>`SetBalanceMode(self, balance_mode)`<br>`SetStandHeight(self, stand_height)`<br>`SetVelocity(self, vx, vy, omega, duration)`<br>`SetTaskId(self, task_id)`<br>`Damp(self)`<br>`Start(self)`<br>`Squat2StandUp(self)`<br>`Lie2StandUp(self)`<br>`Sit(self)`<br>`StandUp2Squat(self)`<br>`ZeroTorque(self)`<br>`StopMove(self)`<br>`HighStand(self)`<br>`LowStand(self)`<br>`Move(self, vx, vy, vyaw, continous_move)`<br>`BalanceStand(self, balance_mode)`<br>`WaveHand(self, turn_flag)`<br>`ShakeHand(self, stage)` |
| `unitree_sdk2_python/unitree_sdk2py/go2/obstacles_avoid/obstacles_avoid_client.py` | `ObstaclesAvoidClient` | `Init(self)`<br>`SwitchSet(self, on)`<br>`SwitchGet(self)`<br>`Move(self, vx, vy, vyaw)`<br>`UseRemoteCommandFromApi(self, isRemoteCommandsFromApi)`<br>`MoveToAbsolutePosition(self, vx, vy, vyaw)`<br>`MoveToIncrementPosition(self, vx, vy, vyaw)` |
| `unitree_sdk2_python/unitree_sdk2py/go2/robot_state/robot_state_client.py` | `ServiceState, RobotStateClient` | `Init(self)`<br>`ServiceList(self)`<br>`ServiceSwitch(self, name, switch)`<br>`SetReportFreq(self, interval, duration)` |
| `unitree_sdk2_python/unitree_sdk2py/go2/sport/sport_client.py` | `PathPoint, SportClient` | `Init(self)`<br>`Damp(self)`<br>`BalanceStand(self)`<br>`StopMove(self)`<br>`StandUp(self)`<br>`StandDown(self)`<br>`RecoveryStand(self)`<br>`Euler(self, roll, pitch, yaw)`<br>`Move(self, vx, vy, vyaw)`<br>`Sit(self)`<br>`RiseSit(self)`<br>`SpeedLevel(self, level)`<br>`Hello(self)`<br>`Stretch(self)`<br>`Content(self)`<br>`Dance1(self)`<br>`Dance2(self)`<br>`SwitchJoystick(self, on)`<br>`Pose(self, flag)`<br>`Scrape(self)`<br>`FrontFlip(self)`<br>`FrontJump(self)`<br>`FrontPounce(self)`<br>`Heart(self)`<br>`LeftFlip(self)`<br>`BackFlip(self)`<br>`FreeWalk(self)`<br>`FreeBound(self, flag)`<br>`FreeJump(self, flag)`<br>`FreeAvoid(self, flag)`<br>`WalkUpright(self, flag)`<br>`CrossStep(self, flag)`<br>`StaticWalk(self)`<br>`TrotRun(self)`<br>`HandStand(self, flag)`<br>`ClassicWalk(self, flag)`<br>`AutoRecoverySet(self, enabled)`<br>`AutoRecoveryGet(self)`<br>`SwitchAvoidMode(self)` |
| `unitree_sdk2_python/unitree_sdk2py/go2/video/video_client.py` | `VideoClient` | `Init(self)`<br>`GetImageSample(self)` |
| `unitree_sdk2_python/unitree_sdk2py/go2/vui/vui_client.py` | `VuiClient` | `Init(self)`<br>`SetSwitch(self, enable)`<br>`GetSwitch(self)`<br>`SetVolume(self, level)`<br>`GetVolume(self)`<br>`SetBrightness(self, level)`<br>`GetBrightness(self)` |
| `unitree_sdk2_python/unitree_sdk2py/h1/loco/h1_loco_client.py` | `LocoClient` | `Init(self)`<br>`SetFsmId(self, fsm_id)`<br>`SetStandHeight(self, stand_height)`<br>`SetVelocity(self, vx, vy, omega, duration)`<br>`Damp(self)`<br>`Start(self)`<br>`StandUp(self)`<br>`ZeroTorque(self)`<br>`StopMove(self)`<br>`HighStand(self)`<br>`LowStand(self)`<br>`Move(self, vx, vy, vyaw, continous_move)` |
| `unitree_sdk2_python/unitree_sdk2py/h2/loco/h2_loco_client.py` | `LocoClient` | `Init(self)`<br>`SetFsmId(self, fsm_id)`<br>`SetBalanceMode(self, balance_mode)`<br>`SetSwingHeight(self, swing_height)`<br>`SetStandHeight(self, stand_height)`<br>`SetVelocity(self, vx, vy, omega, duration)`<br>`SetTaskId(self, task_id)`<br>`SetSpeedMode(self, speed_mode)`<br>`SetPunchApi(self, punch_api)`<br>`SetArmSdkStatus(self, arm_sdk_status)`<br>`Damp(self)`<br>`Start(self)`<br>`Squat(self)`<br>`Sit(self)`<br>`StandUp(self)`<br>`ZeroTorque(self)`<br>`StopMove(self)`<br>`HighStand(self)`<br>`LowStand(self)`<br>`Move(self, vx, vy, vyaw, continous_move)`<br>`BalanceStand(self)`<br>`ContinuousGait(self, flag)`<br>`SwitchMoveMode(self, flag)`<br>`WaveHand(self, turn_flag)`<br>`ShakeHand(self, stage)`<br>`EnableArmSDK(self)`<br>`DisableArmSDK(self)`<br>`GetFsmId(self)`<br>`GetFsmMode(self)`<br>`GetBalanceMode(self)`<br>`GetSwingHeight(self)`<br>`GetStandHeight(self)`<br>`GetPhase(self)`<br>`GetArmSdkStatus(self)`<br>`GetAvailableFsmIds(self)` |
| `unitree_sdk2_python/unitree_sdk2py/rpc/lease_client.py` | `LeaseContext, LeaseClient` | `Update(self, id, term)`<br>`Reset(self)`<br>`Valid(self)`<br>`Init(self)`<br>`WaitApplied(self)`<br>`GetId(self)`<br>`Applied(self)` |

## 8. 示例脚本明细表

| 示例文件 | 作用 | 类 | 顶层函数 |
|---|---|---|---|
| `unitree_sdk2_python/example/b2/camera/camera_opencv.py` | 摄像头实时显示示例：初始化 DDS 网络，调用视频客户端获取图像 bytes，用 OpenCV 解码并显示。 | - | display_image(window_name, data) |
| `unitree_sdk2_python/example/b2/camera/capture_image.py` | 摄像头抓拍示例：调用视频客户端获取一帧 JPEG/图像数据并保存/展示。 | - | - |
| `unitree_sdk2_python/example/b2/high_level/b2_sport_client.py` | RPC 客户端封装：继承/使用 Client，将业务方法转成 JSON 参数或二进制请求发送到机器人服务；公开方法 2 个。 | TestOption, UserInterface | - |
| `unitree_sdk2_python/example/b2/low_level/b2_stand_example.py` | 四足机器人低层站立示例：订阅 LowState、发布 LowCmd，插值关节目标并用 CRC 校验命令。 | Custom | - |
| `unitree_sdk2_python/example/b2/low_level/unitree_legged_const.py` | 四足低层控制常量：定义腿/关节索引、控制级别、停止位置/速度哨兵值。 | - | - |
| `unitree_sdk2_python/example/b2w/camera/camera_opencv.py` | 摄像头实时显示示例：初始化 DDS 网络，调用视频客户端获取图像 bytes，用 OpenCV 解码并显示。 | - | display_image(window_name, data) |
| `unitree_sdk2_python/example/b2w/camera/capture_image.py` | 摄像头抓拍示例：调用视频客户端获取一帧 JPEG/图像数据并保存/展示。 | - | - |
| `unitree_sdk2_python/example/b2w/high_level/b2w_sport_client.py` | RPC 客户端封装：继承/使用 Client，将业务方法转成 JSON 参数或二进制请求发送到机器人服务；公开方法 2 个。 | TestOption, UserInterface | - |
| `unitree_sdk2_python/example/b2w/low_level/b2w_stand_example.py` | 四足机器人低层站立示例：订阅 LowState、发布 LowCmd，插值关节目标并用 CRC 校验命令。 | Custom | - |
| `unitree_sdk2_python/example/b2w/low_level/unitree_legged_const.py` | 四足低层控制常量：定义腿/关节索引、控制级别、停止位置/速度哨兵值。 | - | - |
| `unitree_sdk2_python/example/g1/audio/g1_audio_client_example.py` | G1 语音服务示例：测试 TTS、音量获取/设置、RGB LED 控制等。 | - | - |
| `unitree_sdk2_python/example/g1/audio/g1_audio_client_play_wav.py` | G1 WAV 播放示例：读取本目录 test.wav 并调用 G1AudioClient.PlayStream 推送音频。 | - | main() |
| `unitree_sdk2_python/example/g1/audio/test.wav` | G1 音频示例用 WAV 文件：供 g1_audio_client_play_wav.py 读取并通过语音服务推送 PCM 流。 | - | - |
| `unitree_sdk2_python/example/g1/audio/wav.py` | WAV 处理工具：读取 PCM WAV、写 WAV、分块播放 PCM 流给 G1AudioClient。 | - | read_wav(filename), write_wave(filename, sample_rate, samples, num_channels), play_pcm_stream(client, pcm_list, stream_name, chunk_size, sleep_time, verbose) |
| `unitree_sdk2_python/example/g1/high_level/g1_arm5_sdk_dds_example.py` | G1 5DoF 手臂 DDS 示例：直接发布 LowCmd 控制双臂关节，演示逐段插值和 CRC。 | G1JointIndex, Custom | - |
| `unitree_sdk2_python/example/g1/high_level/g1_arm7_sdk_dds_example.py` | G1 7DoF 手臂 DDS 示例：直接发布 LowCmd 控制含腕部的双臂关节，演示逐段插值和 CRC。 | G1JointIndex, Custom | - |
| `unitree_sdk2_python/example/g1/high_level/g1_arm_action_example.py` | G1 arm action RPC 示例：列出动作并执行指定动作 ID。 | TestOption, UserInterface | - |
| `unitree_sdk2_python/example/g1/high_level/g1_loco_client_example.py` | 人形机器人高层 loco 服务示例：通过 LocoClient 执行 FSM 切换、站立/移动/挥手/握手等动作。 | TestOption, UserInterface | - |
| `unitree_sdk2_python/example/g1/low_level/g1_low_level_example.py` | 人形机器人低层控制示例：发布 HG LowCmd、订阅 HG LowState、按关节索引设置位置/刚度/阻尼并计算 CRC。 | G1JointIndex, Mode, Custom | - |
| `unitree_sdk2_python/example/g1/readme.md` | G1 示例说明：提示使用通用运动服务和臂部 DDS 示例前需要切换运动模式。 | - | - |
| `unitree_sdk2_python/example/go2/front_camera/camera_opencv.py` | 摄像头实时显示示例：初始化 DDS 网络，调用视频客户端获取图像 bytes，用 OpenCV 解码并显示。 | - | - |
| `unitree_sdk2_python/example/go2/front_camera/capture_image.py` | 摄像头抓拍示例：调用视频客户端获取一帧 JPEG/图像数据并保存/展示。 | - | - |
| `unitree_sdk2_python/example/go2/high_level/go2_sport_client.py` | RPC 客户端封装：继承/使用 Client，将业务方法转成 JSON 参数或二进制请求发送到机器人服务；公开方法 2 个。 | TestOption, UserInterface | - |
| `unitree_sdk2_python/example/go2/high_level/go2_utlidar_switch.py` | 示例脚本。 | Custom | - |
| `unitree_sdk2_python/example/go2/low_level/go2_stand_example.py` | 四足机器人低层站立示例：订阅 LowState、发布 LowCmd，插值关节目标并用 CRC 校验命令。 | Custom | - |
| `unitree_sdk2_python/example/go2/low_level/unitree_legged_const.py` | 四足低层控制常量：定义腿/关节索引、控制级别、停止位置/速度哨兵值。 | - | - |
| `unitree_sdk2_python/example/go2w/high_level/go2w_sport_client.py` | RPC 客户端封装：继承/使用 Client，将业务方法转成 JSON 参数或二进制请求发送到机器人服务；公开方法 2 个。 | TestOption, UserInterface | - |
| `unitree_sdk2_python/example/go2w/low_level/go2w_stand_example.py` | 四足机器人低层站立示例：订阅 LowState、发布 LowCmd，插值关节目标并用 CRC 校验命令。 | Custom | - |
| `unitree_sdk2_python/example/go2w/low_level/unitree_legged_const.py` | 四足低层控制常量：定义腿/关节索引、控制级别、停止位置/速度哨兵值。 | - | - |
| `unitree_sdk2_python/example/h1/high_level/h1_loco_client_example.py` | 人形机器人高层 loco 服务示例：通过 LocoClient 执行 FSM 切换、站立/移动/挥手/握手等动作。 | TestOption, UserInterface | - |
| `unitree_sdk2_python/example/h1/low_level/h1_low_level_example.py` | 人形机器人低层控制示例：发布 HG LowCmd、订阅 HG LowState、按关节索引设置位置/刚度/阻尼并计算 CRC。 | H1JointIndex, Custom | - |
| `unitree_sdk2_python/example/h1/low_level/unitree_legged_const.py` | 四足低层控制常量：定义腿/关节索引、控制级别、停止位置/速度哨兵值。 | - | - |
| `unitree_sdk2_python/example/h1_2/low_level/h1_2_low_level_example.py` | 人形机器人低层控制示例：发布 HG LowCmd、订阅 HG LowState、按关节索引设置位置/刚度/阻尼并计算 CRC。 | H1_2_JointIndex, Mode, Custom | - |
| `unitree_sdk2_python/example/h2/high_level/h2_loco_client_example.py` | 人形机器人高层 loco 服务示例：通过 LocoClient 执行 FSM 切换、站立/移动/挥手/握手等动作。 | TestOption, UserInterface | - |
| `unitree_sdk2_python/example/h2/low_level/h2_ankle_swing_example.py` | 人形机器人低层控制示例：发布 HG LowCmd、订阅 HG LowState、按关节索引设置位置/刚度/阻尼并计算 CRC。 | Mode, H2JointIndex, Custom | - |
| `unitree_sdk2_python/example/helloworld/publisher.py` | DDS hello world 发布端：初始化 ChannelFactory，按 topic 发布自定义 UserData/HelloWorld 消息。 | - | - |
| `unitree_sdk2_python/example/helloworld/subscriber.py` | DDS hello world 订阅端：订阅 topic 并打印收到的自定义消息。 | - | - |
| `unitree_sdk2_python/example/helloworld/user_data.py` | 自定义 DDS IDL 结构示例：定义 UserData(IdlStruct) 的 name 和 value 字段。 | UserData | - |
| `unitree_sdk2_python/example/motionSwitcher/motion_switcher_example.py` | 通用运动模式切换示例：检查当前模式、选择/释放 sport 或 ai 等模式。 | Custom | - |
| `unitree_sdk2_python/example/obstacles_avoid/obstacles_avoid_move.py` | Go2 避障移动示例：通过 ObstaclesAvoidClient 发送速度/位置移动命令。 | - | - |
| `unitree_sdk2_python/example/obstacles_avoid/obstacles_avoid_switch.py` | Go2 避障开关示例：循环查询/设置避障状态和远程命令来源。 | - | - |
| `unitree_sdk2_python/example/vui_client/vui_client_example.py` | VUI 示例：循环设置灯光开关、音量和亮度并读取状态。 | - | - |
| `unitree_sdk2_python/example/wireless_controller/wireless_controller.py` | 无线遥控器状态示例：订阅 LowState，解析 wireless_remote 位域/摇杆浮点数并打印按键状态。 | unitreeRemoteController, Custom | - |

## 9. IDL 消息字段全表

这些文件基本都是 CycloneDDS `idlc` 自动生成的 `@dataclass` + `IdlStruct`，真正作用是定义 DDS 序列化字段；业务代码通过这些类构造/发布/订阅机器人消息。

| IDL 文件 | 消息类 | 字段 |
|---|---|---|
| `unitree_sdk2_python/unitree_sdk2py/idl/__init__.py` | `` | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/builtin_interfaces/__init__.py` | `` | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/builtin_interfaces/msg/__init__.py` | `` | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/builtin_interfaces/msg/dds_/_Time_.py` | `Time_` | `sec: types.int32`<br>`nanosec: types.uint32` |
| `unitree_sdk2_python/unitree_sdk2py/idl/builtin_interfaces/msg/dds_/__init__.py` | `` | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/__init__.py` | `` | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/msg/__init__.py` | `` | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/msg/dds_/_Point32_.py` | `Point32_` | `x: types.float32`<br>`y: types.float32`<br>`z: types.float32` |
| `unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/msg/dds_/_PointStamped_.py` | `PointStamped_` | `header: 'unitree_sdk2py.idl.std_msgs.msg.dds_.Header_'`<br>`point: 'unitree_sdk2py.idl.geometry_msgs.msg.dds_.Point_'` |
| `unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/msg/dds_/_Point_.py` | `Point_` | `x: types.float64`<br>`y: types.float64`<br>`z: types.float64` |
| `unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/msg/dds_/_Pose2D_.py` | `Pose2D_` | `x: types.float64`<br>`y: types.float64`<br>`theta: types.float64` |
| `unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/msg/dds_/_PoseStamped_.py` | `PoseStamped_` | `header: 'unitree_sdk2py.idl.std_msgs.msg.dds_.Header_'`<br>`pose: 'unitree_sdk2py.idl.geometry_msgs.msg.dds_.Pose_'` |
| `unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/msg/dds_/_PoseWithCovarianceStamped_.py` | `PoseWithCovarianceStamped_` | `header: 'unitree_sdk2py.idl.std_msgs.msg.dds_.Header_'`<br>`pose: 'unitree_sdk2py.idl.geometry_msgs.msg.dds_.PoseWithCovariance_'` |
| `unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/msg/dds_/_PoseWithCovariance_.py` | `PoseWithCovariance_` | `pose: 'unitree_sdk2py.idl.geometry_msgs.msg.dds_.Pose_'`<br>`covariance: types.array[types.float64, 36]` |
| `unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/msg/dds_/_Pose_.py` | `Pose_` | `position: 'unitree_sdk2py.idl.geometry_msgs.msg.dds_.Point_'`<br>`orientation: 'unitree_sdk2py.idl.geometry_msgs.msg.dds_.Quaternion_'` |
| `unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/msg/dds_/_QuaternionStamped_.py` | `QuaternionStamped_` | `header: 'unitree_sdk2py.idl.std_msgs.msg.dds_.Header_'`<br>`quaternion: 'unitree_sdk2py.idl.geometry_msgs.msg.dds_.Quaternion_'` |
| `unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/msg/dds_/_Quaternion_.py` | `Quaternion_` | `x: types.float64`<br>`y: types.float64`<br>`z: types.float64`<br>`w: types.float64` |
| `unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/msg/dds_/_TwistStamped_.py` | `TwistStamped_` | `header: 'unitree_sdk2py.idl.std_msgs.msg.dds_.Header_'`<br>`twist: 'unitree_sdk2py.idl.geometry_msgs.msg.dds_.Twist_'` |
| `unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/msg/dds_/_TwistWithCovarianceStamped_.py` | `TwistWithCovarianceStamped_` | `header: 'unitree_sdk2py.idl.std_msgs.msg.dds_.Header_'`<br>`twist: 'unitree_sdk2py.idl.geometry_msgs.msg.dds_.TwistWithCovariance_'` |
| `unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/msg/dds_/_TwistWithCovariance_.py` | `TwistWithCovariance_` | `twist: 'unitree_sdk2py.idl.geometry_msgs.msg.dds_.Twist_'`<br>`covariance: types.array[types.float64, 36]` |
| `unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/msg/dds_/_Twist_.py` | `Twist_` | `linear: 'unitree_sdk2py.idl.geometry_msgs.msg.dds_.Vector3_'`<br>`angular: 'unitree_sdk2py.idl.geometry_msgs.msg.dds_.Vector3_'` |
| `unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/msg/dds_/_Vector3_.py` | `Vector3_` | `x: types.float64`<br>`y: types.float64`<br>`z: types.float64` |
| `unitree_sdk2_python/unitree_sdk2py/idl/geometry_msgs/msg/dds_/__init__.py` | `` | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/nav_msgs/__init__.py` | `` | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/nav_msgs/msg/__init__.py` | `` | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/nav_msgs/msg/dds_/_MapMetaData_.py` | `MapMetaData_` | `map_load_time: 'unitree_sdk2py.idl.builtin_interfaces.msg.dds_.Time_'`<br>`resolution: types.float32`<br>`width: types.uint32`<br>`height: types.uint32`<br>`origin: 'unitree_sdk2py.idl.geometry_msgs.msg.dds_.Pose_'` |
| `unitree_sdk2_python/unitree_sdk2py/idl/nav_msgs/msg/dds_/_OccupancyGrid_.py` | `OccupancyGrid_` | `header: 'unitree_sdk2py.idl.std_msgs.msg.dds_.Header_'`<br>`info: 'unitree_sdk2py.idl.nav_msgs.msg.dds_.MapMetaData_'`<br>`data: types.sequence[types.uint8]` |
| `unitree_sdk2_python/unitree_sdk2py/idl/nav_msgs/msg/dds_/_Odometry_.py` | `Odometry_` | `header: 'unitree_sdk2py.idl.std_msgs.msg.dds_.Header_'`<br>`child_frame_id: str`<br>`pose: 'unitree_sdk2py.idl.geometry_msgs.msg.dds_.PoseWithCovariance_'`<br>`twist: 'unitree_sdk2py.idl.geometry_msgs.msg.dds_.TwistWithCovariance_'` |
| `unitree_sdk2_python/unitree_sdk2py/idl/nav_msgs/msg/dds_/__init__.py` | `` | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/sensor_msgs/__init__.py` | `` | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/sensor_msgs/msg/__init__.py` | `` | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/sensor_msgs/msg/dds_/PointField_Constants/_PointField_.py` | `` | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/sensor_msgs/msg/dds_/PointField_Constants/__init__.py` | `` | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/sensor_msgs/msg/dds_/_PointCloud2_.py` | `PointCloud2_` | `header: 'unitree_sdk2py.idl.std_msgs.msg.dds_.Header_'`<br>`height: types.uint32`<br>`width: types.uint32`<br>`fields: types.sequence['unitree_sdk2py.idl.sensor_msgs.msg.dds_.PointField_']`<br>`is_bigendian: bool`<br>`point_step: types.uint32`<br>`row_step: types.uint32`<br>`data: types.sequence[types.uint8]`<br>`is_dense: bool` |
| `unitree_sdk2_python/unitree_sdk2py/idl/sensor_msgs/msg/dds_/_PointField_.py` | `PointField_` | `name: str`<br>`offset: types.uint32`<br>`datatype: types.uint8`<br>`count: types.uint32` |
| `unitree_sdk2_python/unitree_sdk2py/idl/sensor_msgs/msg/dds_/__init__.py` | `` | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/std_msgs/__init__.py` | `` | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/std_msgs/msg/__init__.py` | `` | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/std_msgs/msg/dds_/_Header_.py` | `Header_` | `stamp: 'unitree_sdk2py.idl.builtin_interfaces.msg.dds_.Time_'`<br>`frame_id: str` |
| `unitree_sdk2_python/unitree_sdk2py/idl/std_msgs/msg/dds_/_String_.py` | `String_` | `data: str` |
| `unitree_sdk2_python/unitree_sdk2py/idl/std_msgs/msg/dds_/__init__.py` | `` | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_api/__init__.py` | `` | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_api/msg/__init__.py` | `` | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_api/msg/dds_/_RequestHeader_.py` | `RequestHeader_` | `identity: 'unitree_sdk2py.idl.unitree_api.msg.dds_.RequestIdentity_'`<br>`lease: 'unitree_sdk2py.idl.unitree_api.msg.dds_.RequestLease_'`<br>`policy: 'unitree_sdk2py.idl.unitree_api.msg.dds_.RequestPolicy_'` |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_api/msg/dds_/_RequestIdentity_.py` | `RequestIdentity_` | `id: types.int64`<br>`api_id: types.int64` |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_api/msg/dds_/_RequestLease_.py` | `RequestLease_` | `id: types.int64` |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_api/msg/dds_/_RequestPolicy_.py` | `RequestPolicy_` | `priority: types.int32`<br>`noreply: bool` |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_api/msg/dds_/_Request_.py` | `Request_` | `header: 'unitree_sdk2py.idl.unitree_api.msg.dds_.RequestHeader_'`<br>`parameter: str`<br>`binary: types.sequence[types.uint8]` |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_api/msg/dds_/_ResponseHeader_.py` | `ResponseHeader_` | `identity: 'unitree_sdk2py.idl.unitree_api.msg.dds_.RequestIdentity_'`<br>`status: 'unitree_sdk2py.idl.unitree_api.msg.dds_.ResponseStatus_'` |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_api/msg/dds_/_ResponseStatus_.py` | `ResponseStatus_` | `code: types.int32` |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_api/msg/dds_/_Response_.py` | `Response_` | `header: 'unitree_sdk2py.idl.unitree_api.msg.dds_.ResponseHeader_'`<br>`data: str`<br>`binary: types.sequence[types.uint8]` |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_api/msg/dds_/__init__.py` | `` | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/__init__.py` | `` | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/__init__.py` | `` | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_AudioData_.py` | `AudioData_` | `time_frame: types.uint64`<br>`data: types.sequence[types.uint8]` |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_BmsCmd_.py` | `BmsCmd_` | `off: types.uint8`<br>`reserve: types.array[types.uint8, 3]` |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_BmsState_.py` | `BmsState_` | `version_high: types.uint8`<br>`version_low: types.uint8`<br>`status: types.uint8`<br>`soc: types.uint8`<br>`current: types.int32`<br>`cycle: types.uint16`<br>`bq_ntc: types.array[types.uint8, 2]`<br>`mcu_ntc: types.array[types.uint8, 2]`<br>`cell_vol: types.array[types.uint16, 15]` |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_Error_.py` | `Error_` | `source: types.uint32`<br>`state: types.uint32` |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_Go2FrontVideoData_.py` | `Go2FrontVideoData_` | `time_frame: types.uint64`<br>`video720p: types.sequence[types.uint8]`<br>`video360p: types.sequence[types.uint8]`<br>`video180p: types.sequence[types.uint8]` |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_HeightMap_.py` | `HeightMap_` | `stamp: types.float64`<br>`frame_id: str`<br>`resolution: types.float32`<br>`width: types.uint32`<br>`height: types.uint32`<br>`origin: types.array[types.float32, 2]`<br>`data: types.sequence[types.float32]` |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_IMUState_.py` | `IMUState_` | `quaternion: types.array[types.float32, 4]`<br>`gyroscope: types.array[types.float32, 3]`<br>`accelerometer: types.array[types.float32, 3]`<br>`rpy: types.array[types.float32, 3]`<br>`temperature: types.uint8` |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_InterfaceConfig_.py` | `InterfaceConfig_` | `mode: types.uint8`<br>`value: types.uint8`<br>`reserve: types.array[types.uint8, 2]` |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_LidarState_.py` | `LidarState_` | `stamp: types.float64`<br>`firmware_version: str`<br>`software_version: str`<br>`sdk_version: str`<br>`sys_rotation_speed: types.float32`<br>`com_rotation_speed: types.float32`<br>`error_state: types.uint8`<br>`cloud_frequency: types.float32`<br>`cloud_packet_loss_rate: types.float32`<br>`cloud_size: types.uint32`<br>`cloud_scan_num: types.uint32`<br>`imu_frequency: types.float32`<br>`imu_packet_loss_rate: types.float32`<br>`imu_rpy: types.array[types.float32, 3]`<br>`serial_recv_stamp: types.float64`<br>`serial_buffer_size: types.uint32`<br>`serial_buffer_read: types.uint32` |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_LowCmd_.py` | `LowCmd_` | `head: types.array[types.uint8, 2]`<br>`level_flag: types.uint8`<br>`frame_reserve: types.uint8`<br>`sn: types.array[types.uint32, 2]`<br>`version: types.array[types.uint32, 2]`<br>`bandwidth: types.uint16`<br>`motor_cmd: types.array['unitree_sdk2py.idl.unitree_go.msg.dds_.MotorCmd_', 20]`<br>`bms_cmd: 'unitree_sdk2py.idl.unitree_go.msg.dds_.BmsCmd_'`<br>`wireless_remote: types.array[types.uint8, 40]`<br>`led: types.array[types.uint8, 12]`<br>`fan: types.array[types.uint8, 2]`<br>`gpio: types.uint8`<br>`reserve: types.uint32`<br>`crc: types.uint32` |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_LowState_.py` | `LowState_` | `head: types.array[types.uint8, 2]`<br>`level_flag: types.uint8`<br>`frame_reserve: types.uint8`<br>`sn: types.array[types.uint32, 2]`<br>`version: types.array[types.uint32, 2]`<br>`bandwidth: types.uint16`<br>`imu_state: 'unitree_sdk2py.idl.unitree_go.msg.dds_.IMUState_'`<br>`motor_state: types.array['unitree_sdk2py.idl.unitree_go.msg.dds_.MotorState_', 20]`<br>`bms_state: 'unitree_sdk2py.idl.unitree_go.msg.dds_.BmsState_'`<br>`foot_force: types.array[types.int16, 4]`<br>`foot_force_est: types.array[types.int16, 4]`<br>`tick: types.uint32`<br>`wireless_remote: types.array[types.uint8, 40]`<br>`bit_flag: types.uint8`<br>`adc_reel: types.float32`<br>`temperature_ntc1: types.uint8`<br>`temperature_ntc2: types.uint8`<br>`power_v: types.float32`<br>`power_a: types.float32`<br>`fan_frequency: types.array[types.uint16, 4]`<br>`reserve: types.uint32`<br>`crc: types.uint32` |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_MotorCmd_.py` | `MotorCmd_` | `mode: types.uint8`<br>`q: types.float32`<br>`dq: types.float32`<br>`tau: types.float32`<br>`kp: types.float32`<br>`kd: types.float32`<br>`reserve: types.array[types.uint32, 3]` |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_MotorCmds_.py` | `MotorCmds_` | `cmds: types.sequence['unitree_sdk2py.idl.unitree_go.msg.dds_.MotorCmd_']` |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_MotorState_.py` | `MotorState_` | `mode: types.uint8`<br>`q: types.float32`<br>`dq: types.float32`<br>`ddq: types.float32`<br>`tau_est: types.float32`<br>`q_raw: types.float32`<br>`dq_raw: types.float32`<br>`ddq_raw: types.float32`<br>`temperature: types.uint8`<br>`lost: types.uint32`<br>`reserve: types.array[types.uint32, 2]` |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_MotorStates_.py` | `MotorStates_` | `states: types.sequence['unitree_sdk2py.idl.unitree_go.msg.dds_.MotorState_']` |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_PathPoint_.py` | `PathPoint_` | `t_from_start: types.float32`<br>`x: types.float32`<br>`y: types.float32`<br>`yaw: types.float32`<br>`vx: types.float32`<br>`vy: types.float32`<br>`vyaw: types.float32` |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_Req_.py` | `Req_` | `uuid: str`<br>`body: str` |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_Res_.py` | `Res_` | `uuid: str`<br>`data: types.sequence[types.uint8]`<br>`body: str` |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_SportModeState_.py` | `SportModeState_` | `stamp: 'unitree_sdk2py.idl.unitree_go.msg.dds_.TimeSpec_'`<br>`error_code: types.uint32`<br>`imu_state: 'unitree_sdk2py.idl.unitree_go.msg.dds_.IMUState_'`<br>`mode: types.uint8`<br>`progress: types.float32`<br>`gait_type: types.uint8`<br>`foot_raise_height: types.float32`<br>`position: types.array[types.float32, 3]`<br>`body_height: types.float32`<br>`velocity: types.array[types.float32, 3]`<br>`yaw_speed: types.float32`<br>`range_obstacle: types.array[types.float32, 4]`<br>`foot_force: types.array[types.int16, 4]`<br>`foot_position_body: types.array[types.float32, 12]`<br>`foot_speed_body: types.array[types.float32, 12]`<br>`path_point: types.array['unitree_sdk2py.idl.unitree_go.msg.dds_.PathPoint_', 10]` |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_TimeSpec_.py` | `TimeSpec_` | `sec: types.int32`<br>`nanosec: types.uint32` |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_UwbState_.py` | `UwbState_` | `version: types.array[types.uint8, 2]`<br>`channel: types.uint8`<br>`joy_mode: types.uint8`<br>`orientation_est: types.float32`<br>`pitch_est: types.float32`<br>`distance_est: types.float32`<br>`yaw_est: types.float32`<br>`tag_roll: types.float32`<br>`tag_pitch: types.float32`<br>`tag_yaw: types.float32`<br>`base_roll: types.float32`<br>`base_pitch: types.float32`<br>`base_yaw: types.float32`<br>`joystick: types.array[types.float32, 2]`<br>`error_state: types.uint8`<br>`buttons: types.uint8`<br>`enabled_from_app: types.uint8` |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_UwbSwitch_.py` | `UwbSwitch_` | `enabled: types.uint8` |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/_WirelessController_.py` | `WirelessController_` | `lx: types.float32`<br>`ly: types.float32`<br>`rx: types.float32`<br>`ry: types.float32`<br>`keys: types.uint16` |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_go/msg/dds_/__init__.py` | `` | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_hg/__init__.py` | `` | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_hg/msg/__init__.py` | `` | - |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_hg/msg/dds_/_BmsCmd_.py` | `BmsCmd_` | `cmd: types.uint8`<br>`reserve: types.array[types.uint8, 40]` |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_hg/msg/dds_/_BmsState_.py` | `BmsState_` | `version_high: types.uint8`<br>`version_low: types.uint8`<br>`fn: types.uint8`<br>`cell_vol: types.array[types.uint16, 40]`<br>`bmsvoltage: types.array[types.uint32, 3]`<br>`current: types.int32`<br>`soc: types.uint8`<br>`soh: types.uint8`<br>`temperature: types.array[types.int16, 12]`<br>`cycle: types.uint16`<br>`manufacturer_date: types.uint16`<br>`bmsstate: types.array[types.uint32, 5]`<br>`reserve: types.array[types.uint32, 3]` |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_hg/msg/dds_/_HandCmd_.py` | `HandCmd_` | `motor_cmd: types.sequence['unitree_sdk2py.idl.unitree_hg.msg.dds_.MotorCmd_']`<br>`reserve: types.array[types.uint32, 4]` |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_hg/msg/dds_/_HandState_.py` | `HandState_` | `motor_state: types.sequence['unitree_sdk2py.idl.unitree_hg.msg.dds_.MotorState_']`<br>`press_sensor_state: types.sequence['unitree_sdk2py.idl.unitree_hg.msg.dds_.PressSensorState_']`<br>`imu_state: 'unitree_sdk2py.idl.unitree_hg.msg.dds_.IMUState_'`<br>`power_v: types.float32`<br>`power_a: types.float32`<br>`system_v: types.float32`<br>`device_v: types.float32`<br>`error: types.array[types.uint32, 2]`<br>`reserve: types.array[types.uint32, 2]` |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_hg/msg/dds_/_IMUState_.py` | `IMUState_` | `quaternion: types.array[types.float32, 4]`<br>`gyroscope: types.array[types.float32, 3]`<br>`accelerometer: types.array[types.float32, 3]`<br>`rpy: types.array[types.float32, 3]`<br>`temperature: types.int16` |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_hg/msg/dds_/_LowCmd_.py` | `LowCmd_` | `mode_pr: types.uint8`<br>`mode_machine: types.uint8`<br>`motor_cmd: types.array['unitree_sdk2py.idl.unitree_hg.msg.dds_.MotorCmd_', 35]`<br>`reserve: types.array[types.uint32, 4]`<br>`crc: types.uint32` |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_hg/msg/dds_/_LowState_.py` | `LowState_` | `version: types.array[types.uint32, 2]`<br>`mode_pr: types.uint8`<br>`mode_machine: types.uint8`<br>`tick: types.uint32`<br>`imu_state: 'unitree_sdk2py.idl.unitree_hg.msg.dds_.IMUState_'`<br>`motor_state: types.array['unitree_sdk2py.idl.unitree_hg.msg.dds_.MotorState_', 35]`<br>`wireless_remote: types.array[types.uint8, 40]`<br>`reserve: types.array[types.uint32, 4]`<br>`crc: types.uint32` |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_hg/msg/dds_/_MainBoardState_.py` | `MainBoardState_` | `fan_state: types.array[types.uint16, 6]`<br>`temperature: types.array[types.int16, 6]`<br>`value: types.array[types.float32, 6]`<br>`state: types.array[types.uint32, 6]` |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_hg/msg/dds_/_MotorCmd_.py` | `MotorCmd_` | `mode: types.uint8`<br>`q: types.float32`<br>`dq: types.float32`<br>`tau: types.float32`<br>`kp: types.float32`<br>`kd: types.float32`<br>`reserve: types.uint32` |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_hg/msg/dds_/_MotorState_.py` | `MotorState_` | `mode: types.uint8`<br>`q: types.float32`<br>`dq: types.float32`<br>`ddq: types.float32`<br>`tau_est: types.float32`<br>`temperature: types.array[types.int16, 2]`<br>`vol: types.float32`<br>`sensor: types.array[types.uint32, 2]`<br>`motorstate: types.uint32`<br>`reserve: types.array[types.uint32, 4]` |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_hg/msg/dds_/_PressSensorState_.py` | `PressSensorState_` | `pressure: types.array[types.float32, 12]`<br>`temperature: types.array[types.float32, 12]`<br>`lost: types.uint32`<br>`reserve: types.uint32` |
| `unitree_sdk2_python/unitree_sdk2py/idl/unitree_hg/msg/dds_/__init__.py` | `` | - |

## 10. 重点文件逐项说明

| 文件/目录 | 细节 |
|---|---|
| `unitree_sdk2py/core/channel.py` | `Channel.__Reader` 支持同步 `Read(timeout)` 和 listener 回调；有 `queueLen` 时会先放入 `BQueue`，再由后台线程调用 handler，避免 DDS listener 中执行重逻辑。`Channel.__Writer` 会等待 publication matched，再调用 `DataWriter.write`。`ChannelFactory` 是单例，初始化一次 DDS Domain/Participant，之后所有 Publisher/Subscriber/Client/Server 都从这里创建通道。 |
| `unitree_sdk2py/rpc/client_base.py` | `_CallBase` 走字符串参数请求，`_CallBinaryBase` 走二进制请求，`_CallRequestWithParamAndBinBase` 同时带 JSON 和 bytes；所有请求都使用 `time.monotonic_ns()` 作为 identity id。注意 `_CallRequestWithParamAndBinNoReplyBase` 内部使用了未定义变量 `request_binary`，按代码看这是潜在拼写 bug，应该是 `requestBinary`。 |
| `unitree_sdk2py/rpc/request_future.py` | `RequestFutureQueue.Remove` 中判断的是内建名 `id` 而不是参数 `requestId`，因此超时清理分支实际不会按预期删除对应 future；正常 response 到达路径会在 `Get` 时 pop。 |
| `unitree_sdk2py/utils/crc.py` | 对 Go 低层命令/状态和 HG 低层命令/状态分别定义 struct pack 格式；打包时严格按字段顺序展开数组和嵌套 motor/bms/imu 结构，最后把每 4 字节转成 uint32 列表再 CRC。Linux x86_64/aarch64 会加载 `utils/lib/crc_amd64.so` 或 `crc_aarch64.so`。 |
| `unitree_sdk2py/idl/default.py` | 提供大量 `xxx_()` 默认构造函数，低层示例大量使用它初始化 `LowCmd_`、`MotorCmd_`、`BmsCmd_` 等嵌套结构，避免手写所有字段。 |
| `example/*/low_level/*` | 低层示例通常订阅 `rt/lowstate`，发布 `rt/lowcmd`；先等待状态到达，再按阶段插值关节位置/速度/力矩/刚度/阻尼，写入 `cmd.crc = CRC().Crc(cmd)` 后发布。真实机器人运行前需要关闭可能冲突的高层运动服务。 |
| `example/*/high_level/*` | 高层示例通过各 robot client 调 RPC 服务，参数一般 JSON 化为 `data`、`x/y/z`、`velocity`、`duration` 等键；一些 Move 类调用用 no-reply 发送持续速度命令。 |
| `example/g1/audio/*` | G1 语音服务使用 `voice` RPC 服务：TTS/音量/LED 是 JSON 请求，音频流播放通过 `PlayStream` 同时发送 JSON 元数据和 PCM bytes。 |
| `example/wireless_controller/wireless_controller.py` 与 `utils/joystick.py` | 前者手动解析 lowstate 中的 remote 字节并打印；后者提供可复用模型，可解析 button bit、float 摇杆、边沿状态和连击，也可把手柄对象重新合成为 40 字节 wireless_remote。 |

## 11. 注意事项

| 项目 | 说明 |
|---|---|
| 网络初始化 | 所有 DDS/RPC 示例都需要先调用 `ChannelFactoryInitialize(0, networkInterface)`；如果不传网卡，则使用自动探测 XML。 |
| 真实机器人安全 | 低层控制会直接发电机命令，必须确认机器人型号、关节索引、服务模式、急停和支撑条件；README 也提示低层控制前关闭高层运动服务。 |
| 依赖缺口 | `utils/joystick.py` 使用 `pygame`，但 `setup.py` 只声明 cyclonedds/numpy/opencv-python；需要运行 pygame 手柄工具时需另装 pygame。 |
| 代码质量风险 | 发现两个静态层面的疑点：`client_base.py` 的 `request_binary` 未定义；`request_future.py` 的 `Remove` 使用了 `id` 而不是 `requestId`。本文只做分析，没有修改源码。 |