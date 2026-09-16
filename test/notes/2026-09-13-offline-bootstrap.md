# 2026-09-13 离线骨架搭建

- 目标：不连树莓派，先把基础闭环流程在 Mac 上跑通
- 已完成：
  - 模块拆分：audio / vision / servo / app / config / interfaces
  - mock 输入脚本：拍手事件 + 人脸轨迹
  - 单元测试：算法、限位、状态机
  - 部署脚本占位：`scripts/deploy_to_pi.sh`
- 结论：离线可以验证业务逻辑与状态切换；硬件真实性需真机联调
